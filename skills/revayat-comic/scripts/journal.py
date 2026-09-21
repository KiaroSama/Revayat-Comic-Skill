"""Durable publication intent, progress and recovery across package and metadata.

Before moving anything, record old/new digests and the complete export stamp.
Every move is recoverable even if its following progress write never happened.
Backups survive until metadata commits. Unknown bytes and altered intent are
preserved without being certified or overwritten.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pageir as ir

PENDING_SUFFIX = ".export-pending.json"
CONFLICT_SUFFIX = ".export-conflict"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def path_for(doc_path: Path) -> Path:
    return doc_path.with_name(doc_path.name + PENDING_SUFFIX)


def _intent(record: dict[str, Any]) -> str:
    value = {key: value for key, value in record.items()
             if key not in {"intent", "progress", "progress_hash"}}
    return ir.sha256_bytes(json.dumps(value, sort_keys=True,
                                     ensure_ascii=False).encode("utf-8"))


def _persist(doc_path: Path, record: dict[str, Any]) -> None:
    if record.get("schema") == 2:
        record["progress_hash"] = ir.sha256_bytes(ir.dumps(record["progress"]).encode("utf-8"))
    ir.write_text(path_for(doc_path), ir.dumps(record) + "\n")


def _locations(record: dict[str, Any], name: str) -> tuple[Path, Path, Path]:
    out = Path(record["destination"])
    directory = record["result"]["format"] == "dir"
    stage = out.with_name(out.name + ".revayat-part")
    backup = out.with_name(out.name + ".revayat-kept") / name
    return (out / name if directory else out,
            stage / name if directory else stage, backup)


def _digest(path: Path) -> str | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"{path} is not an ordinary transaction file")
    return ir.sha256_file(path) if path.exists() else None


def write(doc_path: Path, *, destination: Path, published: dict[str, str],
          result: dict[str, Any], options: dict[str, Any],
          document: dict[str, Any] | None = None,
          inputs: dict[str, str] | None = None) -> None:
    record = {"document": ir.sha256_file(doc_path),
              "destination": str(destination.resolve()), "published": published,
              "result": result, "options": options}
    if document is not None:
        if isinstance(document, ir.Document) and record["document"] != document.generation:
            raise RuntimeError("the document changed before publication; reload it")
        backup = destination.with_name(destination.name + ".revayat-kept")
        if backup.exists():
            raise RuntimeError(f"{backup} already holds recovery data; recover it first")
        previous = {name: _digest(_locations(record, name)[0]) for name in published}
        record.update(schema=2, previous=previous, inputs=inputs or {},
                      export_stamp=document["stages"]["export"],
                      document_after=ir.sha256_bytes((ir.dumps(document) + "\n").encode("utf-8")),
                      progress={"phase": "prepared", "entries": {}})
        record["intent"] = _intent(record)
        reason = input_problem(record)
        if reason:
            raise RuntimeError(reason)
    _persist(doc_path, record)


def clear(doc_path: Path) -> None:
    path_for(doc_path).unlink(missing_ok=True)


def read(doc_path: Path) -> dict[str, Any] | None:
    pending = path_for(doc_path)
    if not pending.is_file():
        return None
    try:
        record = json.loads(ir.read_text(pending))
    except (ValueError, OSError):
        return {"unreadable": True}
    return record if isinstance(record, dict) else {"unreadable": True}


def validate(record: dict[str, Any]) -> str:
    """Validate types and confinement before dereferencing a journal field."""
    if record.get("unreadable"):
        return "the record could not be read"
    for field, kind in (("document", str), ("destination", str),
                        ("published", dict), ("result", dict), ("options", dict)):
        if not isinstance(record.get(field), kind):
            return f"invalid {field} in recovery record"
    if not _DIGEST.fullmatch(record["document"]):
        return "invalid document digest"
    out = Path(record["destination"])
    fmt = record["result"].get("format")
    if (not out.is_absolute() or "\0" in str(out) or ".." in out.parts
            or not isinstance(fmt, str) or fmt not in {"cbz", "pdf", "dir"}):
        return "invalid destination or format"
    result = record["result"]
    if (not isinstance(result.get("path"), str) or "\0" in result["path"]
            or not isinstance(result.get("manifest"), list)):
        return "invalid publication result"
    for row in result["manifest"]:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or not isinstance(row.get("page"), str)
                or any(type(row.get(key)) is not int or row[key] <= 0 for key in ("width", "height"))):
            return "invalid publication manifest row"
    published = record["published"]
    if not published:
        return "the record names no published bytes"
    for name, digest in published.items():
        if (not isinstance(name, str) or name in {"", ".", ".."}
                or any(char in name for char in "/\\:\0")
                or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
            return "invalid published name or digest"
    if fmt != "dir" and set(published) != {out.name}:
        return "file publication names another destination"
    if record.get("schema") == 2:
        if record.get("intent") != _intent(record):
            return "publication intent was altered"
        if (not isinstance(record.get("previous"), dict)
                or set(record["previous"]) != set(published)
                or not isinstance(record.get("export_stamp"), dict)
                or not isinstance(record.get("progress"), dict)
                or not isinstance(record.get("document_after"), str)
                or not _DIGEST.fullmatch(record["document_after"])):
            return "invalid transaction intent"
        for digest in record["previous"].values():
            if digest is not None and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
                return "invalid previous digest"
        if record["export_stamp"].get("manifest") != record["result"].get("manifest"):
            return "export stamp disagrees with publication"
        progress = record["progress"]
        phases = {"prepared", "backing-up", "backed-up", "promoted", "published"}
        if (not isinstance(progress.get("phase"), str) or progress["phase"] not in phases
                or not isinstance(progress.get("entries"), dict)
                or any(name not in published or not isinstance(phase, str) or phase not in phases
                       for name, phase in progress["entries"].items())
                or record.get("progress_hash") != ir.sha256_bytes(ir.dumps(progress).encode("utf-8"))):
            return "invalid or altered publication progress"
        inputs = record.get("inputs")
        if not isinstance(inputs, dict) or any(
                not isinstance(path, str) or not Path(path).is_absolute() or "\0" in path
                or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
                for path, digest in inputs.items()):
            return "invalid recovery input map"
    elif "schema" in record:
        return "unrecognized journal version"
    return ""


def input_problem(record: dict[str, Any]) -> str:
    try:
        for path, digest in (record.get("inputs") or {}).items():
            if ir.sha256_file(path) != digest:
                return "an input has changed since this export ran; preserve the recorded edition"
    except OSError:
        return "an input is missing or unreadable; preserve the recorded edition"
    return ""


def verifies(doc_path: Path, record: dict[str, Any]) -> str:
    reason = validate(record)
    if reason:
        return reason
    accepted = {record["document"]}
    if record.get("schema") == 2:
        accepted.add(record["document_after"])
    if ir.sha256_file(doc_path) not in accepted:
        return "the document has changed since this export ran"
    reason = input_problem(record)
    if reason:
        return reason
    try:
        for name, wanted in record["published"].items():
            target, _, _ = _locations(record, name)
            if _digest(target) != wanted:
                return f"{target} is not the file this export published"
    except (OSError, ValueError) as error:
        return str(error)
    return ""


def progress(doc_path: Path, record: dict[str, Any], phase: str,
             name: str | None = None) -> None:
    record["progress"]["phase"] = phase
    if name:
        record["progress"]["entries"][name] = phase
    _persist(doc_path, record)


def _check_files(record: dict[str, Any]) -> None:
    out = Path(record["destination"])
    roots = [out.parent, out.with_name(out.name + ".revayat-kept"),
             out.with_name(out.name + ".revayat-part")]
    if record["result"]["format"] == "dir":
        roots.append(out)
    for folder in roots:
        if folder.is_symlink() or folder.resolve() != folder:
            raise ValueError("recovery directory was replaced by a symlink")
    directories = [out.with_name(out.name + ".revayat-kept")]
    if record["result"]["format"] == "dir":
        directories.append(out.with_name(out.name + ".revayat-part"))
    for folder in directories:
        if folder.exists() and (not folder.is_dir() or
                                {child.name for child in folder.iterdir()} - set(record["published"])):
            raise ValueError(f"{folder} contains unowned entries; preserve them for inspection")
    for name, wanted in record["published"].items():
        target, stage, backup = _locations(record, name)
        old = record["previous"][name]
        if _digest(target) not in {None, old, wanted}:
            raise ValueError(f"{target} changed outside this transaction")
        if _digest(stage) not in {None, wanted}:
            raise ValueError(f"{stage} changed outside this transaction")
        if _digest(backup) not in {None, old}:
            raise ValueError(f"{backup} changed outside this transaction")


def promote(doc_path: Path, record: dict[str, Any], *, resume: bool = False) -> None:
    """Promote a validated intent; keep every previous file until commitment."""
    _check_files(record)
    for name, wanted in record["published"].items():
        target, stage, backup = _locations(record, name)
        if resume and _digest(target) == wanted:
            continue
        if _digest(stage) != wanted:
            raise ValueError(f"{stage} cannot supply the new generation")
        progress(doc_path, record, "backing-up", name)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not backup.exists():
            target.replace(backup)
        progress(doc_path, record, "backed-up", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.replace(target)
        progress(doc_path, record, "promoted", name)
    progress(doc_path, record, "published")


def rollback(record: dict[str, Any]) -> bool:
    """Restore a whole old generation; preserve ambiguous bytes and backups."""
    try:
        _check_files(record)
        for name, old in record["previous"].items():
            target, _, backup = _locations(record, name)
            if old is not None and old not in {_digest(target), _digest(backup)}:
                return False
        for name, old in reversed(list(record["previous"].items())):
            target, _, backup = _locations(record, name)
            if _digest(target) == old:
                continue
            if old is None:
                target.unlink(missing_ok=True)
            else:
                backup.replace(target)
        return True
    except (OSError, ValueError):
        return False


def finish(doc_path: Path, record: dict[str, Any], *, committed: bool = True) -> None:
    """Retire verified backups after metadata or an entire rollback lands."""
    _check_files(record)
    if committed:
        if ir.sha256_file(doc_path) != record["document_after"]:
            raise ValueError("publication metadata has not committed")
        reason = verifies(doc_path, record)
        if reason:
            raise ValueError(reason)
    elif (ir.sha256_file(doc_path) != record["document"] or any(
            _digest(_locations(record, name)[0]) != old
            for name, old in record["previous"].items())):
        raise ValueError("rollback has not restored the previous generation")
    for name, old in record["previous"].items():
        _, _, backup = _locations(record, name)
        if backup.exists():
            if old is None or _digest(backup) != old:
                raise ValueError(f"{backup}: backup ownership changed")
            backup.unlink()
    out = Path(record["destination"])
    folder = out.with_name(out.name + ".revayat-kept")
    if folder.exists():
        folder.rmdir()  # preserve unexpected entries instead of recursively deleting
    for name, wanted in record["published"].items():
        _, staged, _ = _locations(record, name)
        if staged.exists():
            if _digest(staged) != wanted:
                raise ValueError(f"{staged}: staging ownership changed")
            staged.unlink()
    staging = out.with_name(out.name + ".revayat-part")
    if record["result"]["format"] == "dir" and staging.exists():
        staging.rmdir()
    clear(doc_path)


def resume(doc_path: Path, record: dict[str, Any]) -> str:
    """Return published or rolled-back; refuse unrelated state before any move."""
    reason = validate(record)
    if reason:
        raise ValueError(reason)
    current = ir.sha256_file(doc_path)
    if current not in {record["document"], record["document_after"]}:
        raise ValueError("the document has changed since this export ran")
    reason = input_problem(record)
    if reason:
        raise ValueError(reason)
    _check_files(record)
    if record["progress"].get("phase") == "published":
        reason = verifies(doc_path, record)
        if reason:
            raise ValueError(reason)
    if current == record["document_after"]:
        reason = verifies(doc_path, record)
        if reason:
            raise ValueError(reason)
        return "published"
    can_finish = all(
        _digest(_locations(record, name)[0]) == digest
        or _digest(_locations(record, name)[1]) == digest
        for name, digest in record["published"].items())
    if can_finish:
        promote(doc_path, record, resume=True)
        return "published"
    if rollback(record):
        finish(doc_path, record, committed=False)
        return "rolled-back"
    raise ValueError("neither generation can be recovered; backups were preserved")


def reject(doc_path: Path, reason: str) -> Path:
    record = read(doc_path) or {}
    for index in range(1, 100):
        kept = doc_path.with_name(f"{doc_path.name}{CONFLICT_SUFFIX}-{index:02d}.json")
        if not kept.exists():
            break
    else:
        raise RuntimeError("recovery conflict archive is full; preserve and inspect it")
    record["rejected_because"] = reason
    ir.write_text(kept, ir.dumps(record) + "\n")
    clear(doc_path)
