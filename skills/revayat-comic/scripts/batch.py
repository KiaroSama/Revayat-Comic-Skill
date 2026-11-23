"""Plan isolated local workspaces and merge page shards after their writers stop."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

import pageir as ir
from workspace import destination_claim

MANIFEST = "batch-manifest.json"
_BOOK_SUFFIXES = {".cbz", ".cbr", ".pdf"}
_PAGE_ID = re.compile(r"p[0-9]+")
_REGION_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]*")
_PAGE_STAGE_MAPS = ("pages", "page_options")


class BatchItem(TypedDict):
    id: str
    workdir: str
    pages: list[int] | None
    status: Literal["pending", "running", "done", "failed"]
    error: NotRequired[str]
    input: NotRequired[str]


class BatchManifest(TypedDict):
    mode: Literal["shards", "books"]
    source: str
    workers: int
    items: list[BatchItem]
    snapshot: NotRequired[dict[str, Any]]


def _owned(root: Path, name: str | Path) -> Path:
    path = root / name
    if not path.is_relative_to(root) or path.resolve() != path or path.is_symlink():
        raise ValueError(f"asset is outside its workspace or is a link: {name}")
    return path


def _file(path: Path) -> Path:
    if not path.is_file():
        raise ValueError(f"expected a regular file: {path}")
    return path


def _worksheets(root: Path, doc: dict) -> Path:
    folder = _owned(root, ir.worksheet_folder(root / "comic.json", doc))
    parts = folder.relative_to(root).parts
    if not parts or parts[0].casefold() in {"pages", "clean", "final", "masks", "crops"}:
        raise ValueError("worksheets must use a separate directory inside the chapter")
    return folder


def _doc(root: Path) -> dict:
    path = _file(_owned(root, "comic.json"))
    doc = ir.load_doc(path)
    if not isinstance(doc.get("pages"), list) or not doc["pages"]:
        raise ValueError(f"invalid chapter schema: expected pages in {path}")
    for field in ("meta", "source", "stages"):
        if not isinstance(doc.get(field, {}), dict):
            raise ValueError(f"invalid chapter schema: expected an object for {field}")
    return doc


def _page_id(page: Any) -> str:
    pid = page.get("id") if isinstance(page, dict) else None
    if not isinstance(pid, str) or not _PAGE_ID.fullmatch(pid):
        raise ValueError("invalid page schema: expected a canonical page ID")
    return pid


def _region_ids(page: dict) -> set[str]:
    regions = page.get("regions")
    if not isinstance(regions, list):
        raise ValueError(f"{page['id']}: invalid regions schema")
    ids = set()
    for region in regions:
        rid = region.get("id") if isinstance(region, dict) else None
        if (not isinstance(rid, str) or not _REGION_ID.fullmatch(rid)
                or rid.casefold() in ids):
            raise ValueError(f"{page['id']}: invalid or duplicate region ID {rid!r}")
        box = region.get("bbox")
        if (not isinstance(box, list) or len(box) != 4
                or any(type(value) is not int for value in box)
                or region.get("kind") not in ir.REGION_KINDS
                or region.get("orientation") not in ir.ORIENTATIONS
                or not isinstance(region.get("target_text", ""), str)
                or not isinstance(region.get("speaker"), (str, type(None)))
                or not isinstance(region.get("review", []), list)
                or any(type(region.get(flag, False)) is not bool for flag in ("locked", "dropped"))):
            raise ValueError(f"{page['id']}/{rid}: invalid region schema")
        ids.add(rid.casefold())
    return {region["id"] for region in regions}


def _files(folder: Path) -> Iterator[Path]:
    if folder.exists():
        yield from sorted(folder.iterdir(), key=lambda path: (path.name.casefold(), path.name))


def _asset(root: Path, name: Any, folder: str, page: str, *, per_page_dir: bool = False) -> Path:
    if not isinstance(name, str) or not name:
        raise ValueError(f"{page}: invalid {folder} asset path")
    path = _file(_owned(root, name))
    expected = root / folder / page if per_page_dir else root / folder
    if path.parent != expected or (not per_page_dir and path.stem != page and folder != "pages"):
        raise ValueError(f"{page}: {folder} asset is outside its page scope: {name}")
    return path


def _dimensions(page: dict, source: Path) -> tuple[int, int]:
    size = ir.load_image(source).size
    for key, actual in zip(("width", "height"), size, strict=True):
        if key in page and (type(page[key]) is not int or page[key] != actual):
            raise ValueError(f"{page['id']}: original image dimensions {size} do not match metadata")
    return size


def _page_files(root: Path, page: dict, worksheets: Path, *, include_source: bool = False
                ) -> Iterator[Path]:
    pid = page["id"]
    if include_source:
        yield _asset(root, page.get("image"), "pages", pid)
    for field in ("clean", "final"):
        if page.get(field):
            yield _asset(root, page[field], field, pid)
    # Validate recorded paths as well as copying per-page artifacts the current build owns.
    for name in [page.get("mask"), page.get("writable"),
                 *(r.get("mask") for r in page["regions"])]:
        if name:
            _asset(root, name, "masks", pid, per_page_dir=True)
    sheets = page.get("sheets") or []
    if not isinstance(sheets, list):
        raise ValueError(f"{pid}: invalid sheets schema")
    for name in [page.get("overview"), *sheets]:
        if name:
            _asset(root, name, "crops", pid, per_page_dir=True)
    for folder in ("masks", "crops"):
        yield from (_file(_owned(root, path))
                    for path in _files(_owned(root, Path(folder) / pid)) if path.suffix == ".png")
    for path in _files(worksheets):
        if path.name.startswith(pid + ".") and path.suffix in {".txt", ".md", ".json"}:
            yield _file(_owned(root, path))


def _retarget_receipt(page: dict, directory: Path) -> None:
    receipt = page.get("worksheet_receipt")
    if isinstance(receipt, dict):
        receipt["path"] = str(directory / f"{page['id']}.done.txt")


def _stage_slice(stages: dict, ids: set[str]) -> dict:
    result = deepcopy(stages)
    for record in result.values():
        for field in _PAGE_STAGE_MAPS:
            if field in record:
                record[field] = {key: val for key, val in record[field].items() if key in ids}
        for need, pages in (record.get("needs") or {}).items():
            record["needs"][need] = {key: val for key, val in pages.items() if key in ids}
    return result


def _merge_page_stages(result: dict, source: dict, pid: str) -> None:
    for stage in sorted(result.keys() | source.keys()):
        record = source.get(stage)
        if stage not in result:
            result[stage] = {"scheme": record.get("scheme"), "pages": {},
                             "page_options": {}, "needs": {}}
        target = result[stage]
        for field in _PAGE_STAGE_MAPS:
            target.get(field, {}).pop(pid, None)
            if record and target.get("scheme") == record.get("scheme") and pid in record.get(field, {}):
                target.setdefault(field, {})[pid] = record[field][pid]
        for rows in (target.get("needs") or {}).values():
            rows.pop(pid, None)
        if record and target.get("scheme") == record.get("scheme"):
            for need, rows in (record.get("needs") or {}).items():
                if pid in rows:
                    target.setdefault("needs", {}).setdefault(need, {})[pid] = rows[pid]


def _write_manifest(root: Path, manifest: BatchManifest) -> None:
    ir.write_text(root / MANIFEST, ir.dumps(manifest) + "\n")


def _shared_digest(doc: dict) -> str:
    """Bind worker decisions to the chapter-wide inputs they actually used."""
    shared = deepcopy({key: value for key, value in doc.items()
                       if key not in {"pages", "stages"}})
    shared.get("meta", {}).pop("worksheets", None)
    # Mask runs update this default even for one selected page. The effective
    # mode and its freshness options belong to each page, as in stages.py.
    shared.get("meta", {}).pop("free_lettering_mask", None)
    shared.get("source", {}).pop("page_count", None)
    payload = json.dumps(shared, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return ir.sha256_bytes(payload.encode("utf-8"))


def _asset_snapshot(root: Path, doc: dict) -> dict[str, str | None]:
    worksheets = _worksheets(root, doc)
    paths = {_owned(root, "glossary.json")}
    for page in doc["pages"]:
        paths.update(_page_files(root, page, worksheets, include_source=True))
    return {path.relative_to(root).as_posix(): ir.sha256_file(_file(path))
            if path.exists() else None for path in sorted(paths)}


def _snapshot(batch: Path) -> dict:
    manifest = json.loads(_file(_owned(batch, MANIFEST)).read_text(encoding="utf-8"))
    snapshot = manifest.get("snapshot")
    digest = re.compile(r"[0-9a-f]{64}")
    if (not isinstance(snapshot, dict)
            or any(not isinstance(snapshot.get(key), str)
                   or not digest.fullmatch(snapshot[key]) for key in ("document", "shared"))
            or not isinstance(snapshot.get("assets"), dict)
            or any(not isinstance(key, str) or
                   (value is not None and (not isinstance(value, str) or not digest.fullmatch(value)))
                   for key, value in snapshot["assets"].items())):
        raise ValueError("batch has no valid frozen snapshot; preserve drafts and create a new plan")
    return snapshot


def _check_snapshot(root: Path, doc: dict, snapshot: dict, pending: dict[Path, Path],
                    before: str, assets: dict[str, str | None]) -> None:
    """Permit the frozen base or an exact no-op replay, never a stale overwrite."""
    if before == snapshot["document"] and assets == snapshot["assets"]:
        for target in pending:
            name = target.relative_to(root).as_posix()
            if name not in snapshot["assets"] and target.exists():
                raise ValueError(f"chapter asset changed after the batch snapshot: {name}")
        return
    expected = dict(snapshot["assets"])
    expected.update({target.relative_to(root).as_posix(): ir.sha256_file(source)
                     for target, source in pending.items()})
    after = ir.sha256_bytes((ir.dumps(doc) + "\n").encode("utf-8"))
    if before == after and assets.keys() <= expected.keys():
        for name, wanted in expected.items():
            path = _owned(root, name)
            actual = ir.sha256_file(_file(path)) if path.exists() else None
            if actual != wanted:
                break
        else:
            return
    raise ValueError("chapter changed after the batch snapshot; preserve drafts and reconcile before replanning")


@contextmanager
def _plan_directory(out: Path) -> Iterator[Path]:
    with destination_claim(out, out / MANIFEST):
        if out.exists():
            raise ValueError(f"batch output already exists: {out}")
        with tempfile.TemporaryDirectory(prefix=".revayat-batch-", dir=out.parent) as scratch:
            staged = Path(scratch) / "plan"
            staged.mkdir()
            yield staged
            staged.rename(out)


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def plan_shards(doc_dir: str | Path, shards: int, out: str | Path | None = None) -> BatchManifest:
    root = Path(doc_dir).resolve()
    out = Path(out).resolve() if out is not None else root / "batch"
    _file(_owned(root, "comic.json"))
    with ir.workspace_lock(root, what="plan-shards"):
        doc = _doc(root)
        pages = doc["pages"]
        if not 1 <= shards <= len(pages):
            raise ValueError(f"shards must be between 1 and the page count ({len(pages)})")
        ids = [_page_id(page) for page in pages]
        if len(ids) != len(set(ids)):
            raise ValueError("overlapping page IDs in source chapter")
        worksheets = _worksheets(root, doc)
        worksheet_name = worksheets.relative_to(root)
        manifest: BatchManifest = {
            "mode": "shards", "source": str(root), "workers": shards, "items": [],
            "snapshot": {"document": ir.sha256_file(root / "comic.json"),
                         "shared": _shared_digest(doc), "assets": _asset_snapshot(root, doc)},
        }
        base, extra = divmod(len(pages), shards)
        with _plan_directory(out) as staged:
            start = 0
            for number in range(shards):
                stop = start + base + (number < extra)
                sid = f"shard-{number + 1:03d}"
                shard = staged / sid
                subset = deepcopy(pages[start:stop])
                for page in subset:
                    _region_ids(page)
                    for path in _page_files(root, page, worksheets, include_source=True):
                        _copy(path, shard / path.relative_to(root))
                    _retarget_receipt(page, out / sid / worksheet_name)
                glossary = _owned(root, "glossary.json")
                if glossary.exists():
                    _copy(_file(glossary), shard / glossary.name)
                local = {**doc, "pages": subset, "stages": _stage_slice(doc.get("stages", {}), set(ids[start:stop]))}
                local["meta"] = {**doc.get("meta", {}), "worksheets": worksheet_name.as_posix()}
                local["source"] = {**doc.get("source", {}), "page_count": len(subset)}
                ir.save_doc(local, shard / "comic.json")
                manifest["items"].append({"id": sid, "workdir": sid, "pages": [start, stop], "status": "pending"})
                start = stop
            _write_manifest(staged, manifest)
    return manifest


def _shard_folders(batch: Path, into: Path) -> list[tuple[Path, list[int]]]:
    path = _file(_owned(batch, MANIFEST))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("mode") != "shards"
            or not isinstance(manifest.get("items"), list) or not manifest["items"]):
        raise ValueError("expected a shards manifest")
    result = {}
    for item in manifest["items"]:
        sid = item.get("id") if isinstance(item, dict) else None
        span = item.get("pages") if isinstance(item, dict) else None
        if (not isinstance(sid, str) or not re.fullmatch(r"shard-[0-9]{3,}", sid)
                or sid in result or item.get("workdir") != sid
                or item.get("status") not in ("pending", "running", "done", "failed")
                or not isinstance(span, list) or len(span) != 2
                or not all(type(index) is int for index in span) or not 0 <= span[0] < span[1]):
            raise ValueError("invalid or overlapping shard manifest item")
        root = _owned(batch, sid)
        if into == root or into.is_relative_to(root):
            raise ValueError("merge destination must not be inside a shard")
        if item["status"] in {"running", "failed"}:
            raise ValueError(f"{sid}: shard status is {item['status']}; finish the worker before merging")
        result[sid] = (root, span)
    return [result[sid] for sid in sorted(result)]


def _prepare_merge(root: Path, doc: dict, shards: list[tuple[Path, list[int]]], shared: str,
                   external_glossary: str | None
                   ) -> dict[Path, Path]:
    ids = [_page_id(page) for page in doc["pages"]]
    seen: dict[str, tuple[Path, dict, dict]] = {}
    planned = []
    for shard, (first, stop) in shards:
        local = _doc(shard)
        if _shared_digest(local) != shared:
            raise ValueError(f"{shard.name}: shared glossary or policy changed; reconcile before replanning")
        glossary = _owned(shard, "glossary.json")
        glossary_hash = ir.sha256_file(_file(glossary)) if glossary.exists() else None
        if glossary_hash != external_glossary:
            raise ValueError(f"{shard.name}: shared glossary file changed; reconcile before replanning")
        shard_ids = []
        for page in local["pages"]:
            pid = _page_id(page)
            if (not page.get("free_lettering_mask") and
                    local["meta"].get("free_lettering_mask", "glyphs") !=
                    doc["meta"].get("free_lettering_mask", "glyphs")):
                raise ValueError(f"{pid}: legacy page mask mode would change during merge; "
                                 "rebuild this page's masks with its intended mode first")
            if pid in seen:
                raise ValueError(f"overlapping page ID: {pid}")
            seen[pid] = (shard, local, page)
            shard_ids.append(pid)
        planned.append((first, stop, shard_ids))
    if len(set(ids)) != len(ids) or set(ids) != seen.keys():
        raise ValueError("shard pages do not match the original chapter")
    if any(stop > len(ids) or ids[first:stop] != shard_ids for first, stop, shard_ids in planned):
        raise ValueError("shard pages do not match their planned page ranges")

    worksheets = _worksheets(root, doc)
    pending: dict[Path, Path] = {}
    target_stages = doc.setdefault("stages", {})
    for original in doc["pages"]:
        pid = original["id"]
        shard, local, revised = seen[pid]
        if not _region_ids(original) <= _region_ids(revised):
            raise ValueError(f"{pid}: original region IDs changed")
        original_path = _asset(root, original.get("image"), "pages", pid)
        shard_path = _asset(shard, revised.get("image"), "pages", pid)
        size = _dimensions(original, original_path)
        if _dimensions(revised, shard_path) != size:
            raise ValueError(f"{pid}: shard dimensions differ from original {size}")
        if (any(revised.get(key) != original.get(key) for key in ("image", "index", "sha256"))
                or ir.sha256_file(original_path) != ir.sha256_file(shard_path)):
            raise ValueError(f"{pid}: original page identity changed")

        local_worksheets = _worksheets(shard, local)
        for source in _page_files(shard, revised, local_worksheets):
            if source.parent == local_worksheets:
                target = _owned(root, worksheets / source.name)
            else:
                target = _owned(root, source.relative_to(shard))
            if source.parent in (shard / "clean", shard / "final"):
                actual = ir.load_image(source).size
                if actual != size:
                    raise ValueError(f"{pid}: {source.parent.name} dimensions {actual} differ from {size}")
            if target in pending or (target.exists() and not target.is_file()):
                raise ValueError(f"overlapping or invalid merge destination: {target}")
            pending[target] = source
        revised.update(width=size[0], height=size[1])
        _retarget_receipt(revised, worksheets)
        original.clear()
        original.update(revised)
        _merge_page_stages(target_stages, local.get("stages", {}), pid)
    return pending


def _publish(root: Path, doc: dict, pending: dict[Path, Path]) -> None:
    # Prepare every new file and backup before replacing any chapter asset.
    with tempfile.TemporaryDirectory(prefix=".revayat-merge-", dir=root) as scratch:
        scratch = Path(scratch)
        promote = []
        for index, (target, source) in enumerate(pending.items()):
            staged = scratch / "new" / str(index)
            _copy(source, staged)
            backup = None
            if target.exists():
                backup = scratch / "old" / str(index)
                _copy(target, backup)
            promote.append((target, staged, backup))
        replaced = []
        try:
            for target, staged, backup in promote:
                target.parent.mkdir(parents=True, exist_ok=True)
                staged.replace(target)
                replaced.append((target, backup))
            ir.save_doc(doc, root / "comic.json")
        except BaseException:
            failed = []
            for target, backup in reversed(replaced):
                try:
                    if backup is None:
                        target.unlink()
                    else:
                        backup.replace(target)
                except OSError:
                    failed.append(target)
            if failed:
                retained = scratch.with_suffix(".recovery")
                scratch.rename(retained)
                raise RuntimeError(f"could not restore merge assets; backups retained in {retained}") from None
            raise


def merge_shards(batch_dir: str | Path, into: str | Path) -> dict[str, Any]:
    batch, root = Path(batch_dir).resolve(), Path(into).resolve()
    shards = _shard_folders(batch, root)
    for directory in (root, *(shard for shard, _ in shards)):
        _file(_owned(directory, "comic.json"))
    with ir.workspace_lock(root, what="merge-shards"), ExitStack() as locks:
        for shard, _ in shards:
            locks.enter_context(ir.workspace_lock(shard, what="merge-shards"))
        doc = _doc(root)
        snapshot = _snapshot(batch)
        if _shared_digest(doc) != snapshot["shared"]:
            raise ValueError("shared chapter inputs changed after the batch snapshot")
        before, assets = ir.sha256_file(root / "comic.json"), _asset_snapshot(root, doc)
        pending = _prepare_merge(root, doc, shards, snapshot["shared"],
                                 snapshot["assets"].get("glossary.json"))
        _check_snapshot(root, doc, snapshot, pending, before, assets)
        _publish(root, doc, pending)
    return {"document": str(root / "comic.json"), "pages": len(doc["pages"]), "shards": len(shards)}


def _books(root: Path) -> Iterator[tuple[Path, list[Path]]]:
    children = [p for p in _files(root) if not p.is_symlink() and p.resolve() == p]
    loose = [p for p in children if p.is_file() and p.suffix.lower() in ir.IMAGE_SUFFIXES]
    if loose:
        yield root, loose
    for child in children:
        if child.is_file() and child.suffix.lower() in _BOOK_SUFFIXES:
            yield child, [child]
        elif child.is_dir():
            images = [p for p in _files(child) if p.suffix.lower() in ir.IMAGE_SUFFIXES
                      and p.is_file() and not p.is_symlink() and p.resolve() == p]
            if images:
                yield child, images


def plan_books(input_dir: str | Path, out: str | Path, workers: int | None = None) -> BatchManifest:
    root, out = Path(input_dir).resolve(), Path(out).resolve()
    if not root.is_dir():
        raise ValueError(f"expected a book input directory: {root}")
    if workers is None:
        workers = min(4, os.cpu_count() or 1)
    if workers < 1:
        raise ValueError("workers must be positive")
    books = list(_books(root))
    if not books:
        raise ValueError(f"no comic inputs found in {root}")
    manifest: BatchManifest = {"mode": "books", "source": str(root),
                               "workers": min(workers, len(books)), "items": []}
    used: set[str] = set()
    with _plan_directory(out) as staged:
        for source, files in books:
            name = source.name if source.is_dir() else source.stem
            base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or "book"
            if re.fullmatch(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])", base):
                base = "book-" + base
            slug = base
            counter = 2
            while slug in used:
                slug = f"{base}-{counter}"
                counter += 1
            used.add(slug)
            workdir = Path("books") / slug
            for path in files:
                _copy(path, staged / workdir / "input" / path.name)
            staged_input = "input" if source.is_dir() else f"input/{source.name}"
            manifest["items"].append({"id": slug, "workdir": workdir.as_posix(), "pages": None,
                                      "status": "pending", "input": staged_input})
        _write_manifest(staged, manifest)
    return manifest


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


@ir.cli
def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    shards = commands.add_parser("plan-shards", help="split a prepared chapter")
    shards.add_argument("doc_dir", type=Path)
    shards.add_argument("--shards", required=True, type=int)
    shards.add_argument("--out", type=Path)
    merge = commands.add_parser("merge-shards", help="merge completed chapter shards")
    merge.add_argument("batch_dir", type=Path)
    merge.add_argument("--into", required=True, type=Path)
    books = commands.add_parser("plan-books", help="stage books in separate workspaces")
    books.add_argument("input_dir", type=Path)
    books.add_argument("--out", required=True, type=Path)
    books.add_argument("--workers", type=int)
    try:
        args = parser.parse_args(argv)
        if args.command == "plan-shards":
            report = plan_shards(args.doc_dir, args.shards, args.out)
        elif args.command == "merge-shards":
            report = merge_shards(args.batch_dir, args.into)
        else:
            report = plan_books(args.input_dir, args.out, args.workers)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, AttributeError) as error:
        print(ir.dumps({"ok": False, "error": str(error)}))
        return 1
    print(ir.dumps({"ok": True, **report}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
