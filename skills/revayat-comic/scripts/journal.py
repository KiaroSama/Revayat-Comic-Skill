"""The record an export leaves so an interrupted run can be finished.

Publishing a chapter is two writes: the package at the destination, and the
stamp in the document that describes it. Either can fail on its own — a full
disk, a document open elsewhere, a process killed — and then the folder holds
this edition while `comic.json` describes the last one, with `qa package`
comparing the new files against the old manifest and reporting every one of
them as wrong.

So the record is written FIRST, before a byte is published, and removed only
after the document has been saved. Two things follow from that order:

* a record left on disk means the publication was interrupted somewhere
  between those two points, and
* a record can describe an edition that never landed, so finding one is not
  permission to stamp it.

That second point is the whole of `verifies`. The old reconciliation applied
whatever the record said, which certified a document that had changed since
with an older export's manifest — a coherent-looking chapter assembled from two
generations. A record is applied only when the document it was written against
and the bytes it published are both still exactly what it names; anything else
is kept aside as evidence and not acted on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pageir as ir

PENDING_SUFFIX = ".export-pending.json"
CONFLICT_SUFFIX = ".export-conflict"


def path_for(doc_path: Path) -> Path:
    """Where an export records the edition it is about to publish."""
    return doc_path.with_name(doc_path.name + PENDING_SUFFIX)


def write(doc_path: Path, *, destination: Path, published: dict[str, str],
          result: dict[str, Any], options: dict[str, Any]) -> None:
    """Record the transaction. Called before anything is published.

    `document` is the generation this edition was made from — the bytes of the
    document as they are now, before the stamp this export will add.
    `published` is every file the publication will put at the destination, by
    the bytes it will put there, which is what makes "did it land?" answerable
    without reopening the package.
    """
    ir.write_text(path_for(doc_path), ir.dumps({
        "document": ir.sha256_file(doc_path),
        "destination": str(Path(destination).resolve()),
        "published": published,
        "result": result,
        "options": options,
    }) + "\n")


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


def verifies(doc_path: Path, record: dict[str, Any]) -> str:
    """Empty when this record may be applied, else why it may not be."""
    if record.get("unreadable"):
        return "the record could not be read"
    for field in ("document", "destination", "published", "result", "options"):
        if field not in record:
            return f"the record does not say what it {field} was"
    if record["document"] != ir.sha256_file(doc_path):
        return ("the document has changed since this export ran, so its "
                "manifest describes a different edition")

    destination = Path(record["destination"])
    published = record["published"]
    if not isinstance(published, dict) or not published:
        return "the record names no published bytes"
    # A folder export puts its files inside the destination; an archive or a
    # PDF is the destination, under its own name.
    base = destination if record["result"].get("format") == "dir" \
        else destination.parent
    for name, digest in published.items():
        landed = base / name
        if not landed.is_file():
            return f"{landed} was never published"
        if ir.sha256_file(landed) != digest:
            return f"{landed} is not the file this export wrote"
    return ""


def reject(doc_path: Path, reason: str) -> Path:
    """Move an unusable record aside, keeping it. Returns where it went.

    Deleting it would destroy the only description of what the interrupted run
    was doing, and leaving it in place would make every later export trip over
    the same refusal.
    """
    pending = path_for(doc_path)
    record = read(doc_path) or {}
    for index in range(1, 100):
        kept = doc_path.with_name(
            f"{doc_path.name}{CONFLICT_SUFFIX}-{index:02d}.json")
        if not kept.exists():
            break
    else:                                  # pragma: no cover - 99 conflicts
        kept = doc_path.with_name(f"{doc_path.name}{CONFLICT_SUFFIX}-99.json")
    record["rejected_because"] = reason
    ir.write_text(kept, ir.dumps(record) + "\n")
    pending.unlink(missing_ok=True)
    return kept
