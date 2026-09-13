"""Write the finished pages out as CBZ, PDF or a plain folder.

Page order is the only thing that can be silently wrong in an export, because
every reader sorts an archive's names itself and none of them agree about what
``page10`` means next to ``page9``. The names written here are zero-padded and
already in reading order, so byte-wise sorting and reading order are the same
thing and no reader has to guess.

Nothing is re-encoded unless it has to be. A page that was never touched is
copied through byte for byte.
"""

from __future__ import annotations

import argparse
import sys
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pageir as ir
import stages
from pageir import IMAGE_SUFFIXES

FORMATS = ("cbz", "pdf", "dir")


def _resolve(root: Path, page: dict[str, Any]) -> tuple[Path, str]:
    """The most finished version of this page that exists, and which it is."""
    for key in ("final", "clean", "image"):
        relative = page.get(key)
        if relative and (root / relative).exists():
            return root / relative, key
    raise FileNotFoundError(f"no image for {page['id']}")


def _page_source(root: Path, page: dict[str, Any]) -> Path:
    return _resolve(root, page)[0]


def _wants_rendering(page: dict[str, Any]) -> bool:
    """Whether this page has Persian on it that a render has to carry."""
    return any((region.get("target_text") or "").strip()
               for region in page.get("regions", [])
               if not region.get("dropped"))


def _manifest(doc: dict[str, Any], root: Path) -> dict[str, str]:
    """Which file each page will ship, resolved before anything is written."""
    return {page["id"]: _resolve(root, page)[1] for page in doc["pages"]}


def _dependencies(doc: dict[str, Any], root: Path, doc_path: Path) -> set[Path]:
    """Every file this chapter is made of, resolved through symlinks.

    An export reads these while it writes, so writing onto one of them destroys
    the chapter mid-flight. Resolved rather than compared as written, because
    `work/pages/../pages/p0001.png` and a symlink alias name the same bytes.
    """
    found = {doc_path.resolve()}
    # The container this chapter was imported from. Not a working file, and
    # that is exactly why it belongs here: everything else under `root` can be
    # rebuilt from it, and it cannot be rebuilt from anything.
    origin = (doc.get("source") or {}).get("path")
    if isinstance(origin, str) and origin:
        candidate = Path(origin)
        if candidate.exists():
            found.add(candidate.resolve())
    for page in doc.get("pages", []):
        for key in ("image", "clean", "final", "mask", "writable"):
            relative = page.get(key)
            if isinstance(relative, str) and relative:
                candidate = root / relative
                if candidate.exists():
                    found.add(candidate.resolve())
    return found


def _refuse_collisions(doc: dict[str, Any], root: Path, doc_path: Path,
                       out: Path, fmt: str) -> None:
    """Refuse an output path that lands on something the chapter is made of.

    Checked for every format and after `--format` has been resolved: guessing
    the format from the suffix is exactly how `--format cbz --out page.png`
    walks past a suffix-based guard.
    """
    owned = _dependencies(doc, root, doc_path)
    target = out.resolve()

    if target in owned:
        raise ValueError(
            f"{out} is a file the chapter is made of. Exporting onto it would "
            "destroy what the export is reading. Pick a different --out."
        )

    if fmt == "dir":
        # A folder export writes `0001.png`, `0002.png`… Those are legal page
        # names, so a chapter whose own pages are named that way has its
        # originals overwritten rather than flagged by the stranger check
        # below, which only looks at files the export will NOT replace.
        clashing = sorted(str(path) for path in owned if path.parent == target)
        if clashing:
            raise ValueError(
                f"{out} holds {len(clashing)} file(s) the chapter is made of "
                f"({', '.join(Path(c).name for c in clashing[:4])}…). Exporting "
                "there would write over the originals. Export to an empty folder."
            )
        return


def _scratch(beside: Path, label: str) -> Path:
    """A scratch path this export owns.

    `<name>.part` was predictable, so two exports of the same chapter wrote to
    the same file and an operator's own `<name>.part` was overwritten and then
    deleted. A random suffix makes ownership a fact.
    """
    import secrets

    for _ in range(8):
        candidate = beside.with_name(
            f"{beside.name}.{label}-{secrets.token_hex(6)}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find an unused scratch name beside {beside}")


def _pixel_digest(payload: bytes) -> str:
    """A hash of what the page LOOKS like, not of how it was packed.

    A PDF re-wraps every image it is given, so the encoded bytes on the way out
    are not the encoded bytes on the way in and an exact comparison could not
    be made at all — which is why a PDF carried no hash, and why an exported
    chapter replaced by an unrelated image of the same shape passed every
    check it had.
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(payload)) as image:
            return ir.sha256_bytes(image.convert("RGB").tobytes())
    except Exception:      # pragma: no cover - an unreadable page fails earlier
        return ""


def _shipped(page: dict[str, Any], name: str, payload: bytes,
             quality: int) -> dict[str, Any]:
    """One manifest row: what this page was shipped as.

    `sha256` is the hash of the bytes THIS EXPORT WROTE, whatever they are —
    the re-encoded JPEG, not the PNG it came from — so it is always comparable.
    It was gated behind `lossy` on the theory that a re-encoded page "will
    never hash to the bytes on disk", which is true of the source file and not
    of the payload recorded here: the effect was that every JPEG page in a
    package went unverified.

    `lossy` survives as truthful metadata about the encoding, and the flag was
    also inverted — a JPEG, the one lossy thing this writes, was recorded as
    lossless.

    `pixels` is the hash of the decoded image, which survives a container
    re-wrapping the bytes. It is what a PDF can be checked against.
    """
    return {
        "page": page["id"],
        "name": name,
        "sha256": ir.sha256_bytes(payload),
        "pixels": _pixel_digest(payload),
        "width": page["width"],
        "height": page["height"],
        "lossy": name.lower().endswith((".jpg", ".jpeg")),
    }


def _export_cbz(doc: dict[str, Any], root: Path, out: Path,
                quality: int, draft: bool = False) -> dict[str, Any]:
    written = 0
    manifest: list[dict[str, Any]] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written to a temporary name and moved into place, so an interrupted export
    # cannot leave a half-written archive that opens and is missing chapters.
    staging = _scratch(out, "part")
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            for page in doc["pages"]:
                source = _page_source(root, page)
                name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
                payload, name = _encode(source, name, quality)
                archive.writestr(name, payload)
                manifest.append(_shipped(page, name, payload, quality))
                written += 1
            archive.writestr(
                "ComicInfo.xml", _comic_info(doc, draft).encode("utf-8")
            )
        staging.replace(out)
    finally:
        # An encoding failure half way through leaves the previous package
        # untouched and no debris beside it.
        staging.unlink(missing_ok=True)
    return {"format": "cbz", "path": str(out), "pages": written,
            "manifest": manifest}


def _encode(source: Path, name: str, quality: int) -> tuple[bytes, str]:
    """Bytes for the archive: as-is, or re-encoded to JPEG when asked."""
    if quality <= 0 or source.suffix.lower() in {".jpg", ".jpeg"}:
        return source.read_bytes(), name
    import io

    image = ir.load_image(source)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, subsampling=0, optimize=True)
    return buffer.getvalue(), str(Path(name).with_suffix(".jpg"))


def _comic_info(doc: dict[str, Any], draft: bool = False) -> str:
    """The metadata sidecar every comic reader looks for."""
    meta = doc["meta"]

    def escape(value: str) -> str:
        return (str(value).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    fields = [
        ("Title", meta.get("title", "")),
        ("Number", meta.get("chapter", "")),
        ("LanguageISO", meta.get("target_language", "fa")),
        ("PageCount", str(len(doc["pages"]))),
        ("Translator", meta.get("tool", "")),
        # Inside the package, so a draft cannot pass for an approved
        # edition once the report has scrolled away.
        *([("Notes", "DRAFT - did not pass publication QA")]
          if draft else []),
        # Persian is read right to left, so a two-page spread has to be paired
        # the other way round. `Manga` carries that: the ComicInfo
        # documentation says the field "defines the reading direction as
        # right-to-left when set to YesAndRightToLeft". Plain `Yes` only says
        # the book is a manga and leaves direction unstated, so every spread
        # in the book was still shown back to front.
        ("Manga", "YesAndRightToLeft"
         if meta.get("reading_direction") == "rtl" else "No"),
    ]
    body = "".join(
        f"  <{name}>{escape(value)}</{name}>\n" for name, value in fields if value
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"{body}</ComicInfo>\n"
    )


def _export_pdf(doc: dict[str, Any], root: Path, out: Path,
                quality: int, draft: bool = False) -> dict[str, Any]:
    pymupdf = ir.require("pymupdf", "pymupdf", "writing a PDF")
    out.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        manifest: list[dict[str, Any]] = []
        for index, page in enumerate(doc["pages"]):
            source = _page_source(root, page)
            payload, _ = _encode(source, source.name, quality)
            rect = pymupdf.Rect(0, 0, page["width"], page["height"])
            new_page = document.new_page(width=page["width"], height=page["height"])
            new_page.insert_image(rect, stream=payload)
            manifest.append({"page": page["id"], "name": f"{index + 1:04d}",
                             "width": page["width"], "height": page["height"],
                             # What the page looks like. The encoded bytes are
                             # the PDF's to choose; the pixels are not.
                             "pixels": _pixel_digest(payload),
                             "lossy": True})
        title = doc["meta"].get("title", "")
        document.set_metadata({
            # DRAFT in the package itself, not only in the report. A PDF
            # produced with `--draft` was indistinguishable from an approved
            # edition the moment the terminal scrolled away, and a PDF is the
            # format people forward.
            "title": f"[DRAFT] {title}".strip() if draft else title,
            "subject": ("DRAFT — this package did not pass publication QA"
                        if draft else ""),
            "keywords": "revayat-comic draft" if draft else "revayat-comic",
            "producer": doc["meta"].get("tool", ""),
        })
        # Saved beside the destination and moved into place, so a write that
        # fails part way cannot replace a good package with a truncated one.
        staging = _scratch(out, "part")
        document.save(str(staging), garbage=3, deflate=True)
    finally:
        document.close()
    try:
        staging.replace(out)
    finally:
        staging.unlink(missing_ok=True)
    return {"format": "pdf", "path": str(out), "pages": len(doc["pages"]),
            "draft": draft, "manifest": manifest}


def _pending_path(doc_path: Path) -> Path:
    """Where an export records the stamp it is about to commit."""
    return doc_path.with_name(doc_path.name + ".export-pending.json")


def reconcile_pending(doc_path: str | Path) -> dict[str, Any] | None:
    """Apply a stamp a previous export wrote out but could not commit.

    The package and the document that describes it are two writes, and the
    second one can fail — a full disk, a document open elsewhere. Then the
    folder holds this edition and `comic.json` describes the last one, and
    `qa package` compares the new files against the old manifest and reports
    them all as wrong.

    So the stamp is staged beside the document BEFORE the output is published
    and removed once it is committed. One left behind is the record of an
    interrupted export, and this puts it in.
    """
    doc_path = Path(doc_path)
    pending = _pending_path(doc_path)
    if not pending.is_file():
        return None
    import json

    record = json.loads(ir.read_text(pending))
    doc = ir.load_doc(doc_path)
    stages.stamp_stage(doc, "export", record["result"],
                       options=record["options"])
    ir.save_doc(doc, doc_path)
    pending.unlink(missing_ok=True)
    return record


def _restore(out: Path, replaced: Path, promoted: list[str],
             backed_up: list[str]) -> bool:
    """Put the previous edition back. Returns whether it is safe to discard it.

    Every file this run promoted is removed and every file it moved aside is
    put back — the two lists differ, because a file can be backed up and then
    fail to be replaced.

    A restore that itself fails leaves the backup where it is: it is then the
    only copy of the operator's previous edition, and deleting it to tidy up
    after a failed rollback would turn a recoverable failure into a loss. A
    recovery note beside it says what the files are.
    """
    intact = True
    for name in reversed(promoted):
        try:
            (out / name).unlink(missing_ok=True)
        except OSError:
            intact = False
    for name in reversed(backed_up):
        kept = replaced / name
        if not kept.exists():
            continue
        try:
            kept.replace(out / name)
        except OSError:
            intact = False
    if not intact:
        try:
            ir.write_text(replaced / "RECOVERY.txt",
                          "This folder holds the previous edition of files an "
                          "export moved aside. The export failed AND putting "
                          "them back failed, so they were kept here rather "
                          "than deleted. Move them back by hand.\n")
        except OSError:
            pass
    return intact


def _export_dir(doc: dict[str, Any], root: Path, out: Path,
                quality: int, draft: bool = False) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []

    planned = set()
    for page in doc["pages"]:
        source = _page_source(root, page)
        name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
        planned.add(_encode(source, name, quality)[1])

    # Exporting into a folder that already holds other images would mix them
    # into the chapter — pointing --out at the working folder's own `pages/`
    # silently ships the untranslated originals alongside the finished ones.
    strangers = sorted(
        child.name for child in out.iterdir()
        if child.is_file()
        and child.suffix.lower() in IMAGE_SUFFIXES
        and child.name not in planned
    )
    if strangers:
        raise ValueError(
            f"{out} already contains {len(strangers)} image(s) that this export "
            f"will not replace ({', '.join(strangers[:4])}…). They would be "
            "shipped as part of the chapter. Export to an empty folder."
        )

    # Written to a staging folder and moved in, so a chapter that fails half
    # way — an unreadable page, a full disk — leaves the previous export whole
    # instead of a mixture of two. Moved file by file rather than swapping the
    # folder, because anything else the operator keeps in there is not ours.
    staging = _scratch(out, "part")
    staging.mkdir(parents=True, exist_ok=False)
    replaced = _scratch(out, "kept")
    # Set before the try, because the cleanup below reads it on every path —
    # including a failure that happens before a single file has been promoted.
    rolled_back = True
    try:
        for page in doc["pages"]:
            source = _page_source(root, page)
            name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
            payload, name = _encode(source, name, quality)
            ir.write_bytes(staging / name, payload)
            manifest.append(_shipped(page, name, payload, quality))
        ir.write_text(staging / "ComicInfo.xml", _comic_info(doc, draft))

        # Promoted with the previous edition of each file held aside until
        # every one has landed. Promoting file by file and hoping was enough
        # for the first failure: a `replace` that raised half way through left
        # some pages from this chapter and the rest from the last one, in a
        # folder that looked finished.
        replaced.mkdir(parents=True, exist_ok=False)
        promoted: list[str] = []
        backed_up: list[str] = []
        try:
            for child in sorted(staging.iterdir()):
                target = out / child.name
                if target.exists():
                    target.replace(replaced / child.name)
                    # Journalled HERE, before the promotion that may fail.
                    # Recording it afterwards meant the one file whose
                    # promotion raised had its previous edition moved aside,
                    # left out of the rollback list, and then deleted by the
                    # `finally` below — the operator's current file destroyed
                    # by a failure that changed nothing else.
                    backed_up.append(child.name)
                child.replace(target)
                promoted.append(child.name)
        except BaseException:
            rolled_back = _restore(out, replaced, promoted, backed_up)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if rolled_back:
            shutil.rmtree(replaced, ignore_errors=True)
    return {"format": "dir", "path": str(out), "pages": len(doc["pages"]),
            "manifest": manifest}


def export_document(
    doc_path: str | Path, out: str | Path, *, fmt: str | None = None,
    quality: int = 0, draft: bool = False,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    out = Path(out).expanduser()

    if fmt is None:
        suffix = out.suffix.lower()
        fmt = {".cbz": "cbz", ".zip": "cbz", ".pdf": "pdf"}.get(suffix, "dir")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")
    # An export that could not commit its own stamp last time. Reconciled
    # before this one starts, so the document never describes an edition older
    # than the files beside it.
    if reconcile_pending(doc_path) is not None:
        doc = ir.load_doc(doc_path)
    _refuse_collisions(doc, root, doc_path, out, fmt)

    # Resolved before a byte is written, because the fallback is silent: a
    # page whose render is missing shipped its cleaned version — or the
    # untranslated original — and was still counted under `typeset_pages`.
    sources = _manifest(doc, root)
    unrendered = sorted(
        page["id"] for page in doc["pages"]
        if _wants_rendering(page) and sources[page["id"]] != "final"
    )
    if not draft:
        # The whole gate, not export's own narrower question. Asking only "is
        # there a file for every page that wants one" let a chapter whose
        # render was stale, whose lines had overflowed, or whose erasures had
        # never been cleaned go into a package without `qa` ever running.
        import qa

        state = qa.publication_preflight(doc_path)
        if not state["ok"]:
            named = ", ".join(
                f"{item['code']} ({item['where']})"
                for item in state["blocking"][:4])
            raise ValueError(
                f"this chapter does not pass publication QA: "
                f"{state['blocking_count']} blocking finding(s) — {named}. "
                f"{state['next']}"
            )
    if unrendered and not draft:
        raise ValueError(
            f"{len(unrendered)} page(s) carry Persian that has not been "
            f"rendered: {', '.join(unrendered[:6])}. Run `typeset`, or pass "
            "--draft to ship the cleaned pages instead and have the report "
            "say so page by page."
        )

    writers = {"cbz": _export_cbz, "pdf": _export_pdf, "dir": _export_dir}
    report = writers[fmt](doc, root, out, quality, draft)
    staged_stamp = _pending_path(doc_path)

    # Counted from what was actually written, not from what the document says
    # exists. A recorded `final` whose file has been deleted is not a
    # typeset page, and a cleaned page is not an unchanged original.
    report["sources"] = sources
    report["draft"] = draft
    if draft:
        # A draft says so in the report AND in the package. Without the second
        # one, a folder or archive produced with `--draft` is indistinguishable
        # from an approved edition as soon as the report scrolls away.
        report["approved"] = False
        report["note"] = ("DRAFT — this package did NOT pass publication QA "
                          "and must not be shipped as a finished chapter.")
    else:
        report["approved"] = True
    report["typeset_pages"] = sum(1 for key in sources.values() if key == "final")
    report["cleaned_pages"] = sum(1 for key in sources.values() if key == "clean")
    report["original_pages"] = sum(1 for key in sources.values() if key == "image")
    report["untouched_pages"] = report["original_pages"]
    if unrendered:
        report["unrendered_pages"] = unrendered
        report["note"] = (
            f"DRAFT: {len(unrendered)} page(s) carry Persian that was never "
            "rendered and shipped without it. `sources` says which file each "
            "page used."
        )
    elif report["original_pages"]:
        report["note"] = (
            f"{report['original_pages']} page(s) had no translated text and "
            "were exported exactly as they arrived."
        )
    result = {"format": fmt, "path": str(out),
              # What was shipped, so `qa package` can check the package
              # against it rather than against a sort of its own file names.
              "manifest": report.get("manifest") or []}
    options = {"format": fmt, "quality": quality, "draft": draft}
    # Staged first, committed second, removed third. A crash between the
    # package landing and the document being saved used to leave the two
    # permanently disagreeing with nothing on disk that said so.
    ir.write_text(staged_stamp, ir.dumps({"result": result,
                                          "options": options}) + "\n")
    stages.stamp_stage(doc, "export", result, options=options)
    ir.save_doc(doc, doc_path)
    staged_stamp.unlink(missing_ok=True)
    return report


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic export", description="Write the finished chapter out."
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--out", required=True,
                        help="chapter-fa.cbz, chapter-fa.pdf, or a folder")
    parser.add_argument("--format", choices=list(FORMATS), default=None,
                        help="inferred from --out when omitted")
    parser.add_argument("--draft", action="store_true",
                        help="ship pages whose Persian was never rendered, "
                             "using their cleaned or original image; the "
                             "report then says which file each page used")
    parser.add_argument("--jpeg-quality", type=int, default=0,
                        help="re-encode pages as JPEG at this quality; 0 keeps "
                             "the original bytes, which is the default. Note "
                             "that JPEG is not automatically smaller: line art "
                             "with flat whites compresses better as PNG, and "
                             "JPEG adds ringing along every ink edge")
    args = parser.parse_args(argv)

    report = export_document(
        args.doc, args.out, fmt=args.format, quality=args.jpeg_quality,
        draft=args.draft,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
