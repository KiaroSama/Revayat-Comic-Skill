"""The worksheet protocol — how the reader's answers get back into the document.

One worksheet per page, plain text, one block per region:

    @@ p0001r003 speech vertical
    src: やめろ！
    fa: بس کن!

Plain text rather than JSON for the reason the sibling novel skill found the
hard way: models corrupt JSON and fight Persian quoting, while a missing ``@@``
line is caught deterministically at merge. A field continues onto the next line
until another field or another ``@@`` starts, so multi-line dialogue needs no
escaping at all.

Three optional fields let the reader correct what the detector guessed, because
the reader can see the page and the detector cannot:

    kind:    reclassify — the detector called it speech, it is a sign
    speaker: who is talking, for the glossary and for voice consistency
    drop:    yes — there is no text here; the detector matched artwork

Merging refuses rather than guesses. If the page was re-detected after the
worksheet was written, region ids no longer mean what the worksheet thinks they
mean, and a merge would file every translation against the wrong balloon. The
document's fingerprint is stamped into the worksheet and compared on the way
back in.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import pageir as ir

HEADER = re.compile(r"^@@\s+(?P<id>[A-Za-z0-9_#-]+)(?:\s+(?P<rest>.*))?$")
FIELD = re.compile(r"^(?P<name>src|fa|kind|speaker|note|drop)\s*:\s?(?P<value>.*)$")
FINGERPRINT = re.compile(r"^#\s*fingerprint:\s*(?P<value>[0-9a-f]{64})\s*$", re.M)

FIELDS = ("src", "fa", "kind", "speaker", "note", "drop")

_DIRECTION_WORDS = {
    "rtl": "right to left (Japanese order: the rightmost balloon is first)",
    "ltr": "left to right",
}


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def _glossary_table(doc: dict[str, Any], limit: int = 40) -> list[str]:
    entries = doc.get("glossary", {}).get("entries", {})
    locked = [
        (source, entry) for source, entry in entries.items()
        if entry.get("target")
    ][:limit]
    if not locked:
        return []
    lines = [
        "# Names and terms — these are binding. Use exactly the Persian given.",
        "#",
        "#   source                 Persian                role",
        "#   ---------------------  ---------------------  ------------------",
    ]
    for source, entry in locked:
        lines.append(
            f"#   {source[:21]:<21}  {entry['target'][:21]:<21}  "
            f"{entry.get('role', '')[:18]}"
        )
    lines.append("#")
    return lines


def page_worksheet(doc: dict[str, Any], page: dict[str, Any], fingerprint: str) -> str:
    meta = doc["meta"]
    direction = meta.get("reading_direction", "rtl")
    regions = page.get("regions", [])

    lines = [
        f"# {meta.get('title') or 'comic'} — page {page['id']} "
        f"({page['index'] + 1} of {len(doc['pages'])})",
        f"# fingerprint: {fingerprint}",
        "#",
        "# Look at these before writing anything:",
        f"#   {page.get('overview', '(run crops first)')}",
    ]
    for sheet in page.get("sheets", []):
        lines.append(f"#   {sheet}")
    lines += [
        "#",
        f"# Source language: {meta.get('source_language')}   "
        f"target: {meta.get('target_language')}",
        f"# Reading order: {_DIRECTION_WORDS.get(direction, direction)}",
        f"# Sound effects: {meta.get('sfx_policy', 'keep')}",
        "#",
        "# Fill in `src:` with what the balloon actually says, and `fa:` with the",
        "# Persian. Keep every `@@` line exactly as it is. A field continues on",
        "# the following lines until the next field or the next `@@`.",
        "#",
        "# Optional corrections — use them when the crop shows the detector was",
        "# wrong. You can see the page; it could not.",
        "#   kind:    speech | thought | narration | sfx | sign | unknown",
        "#   speaker: a short stable name, the same one every time",
        "#   drop:    yes   — there is no text here at all",
        "#",
    ]
    lines += _glossary_table(doc)

    for region in regions:
        lines.append("")
        lines.append(f"@@ {region['id']} {region['kind']} {region['orientation']}")
        if region.get("panel"):
            lines.append(f"# panel {region['panel']}, "
                         f"reading order {region.get('reading_order')}")
        if region.get("confidence", 1.0) < 0.5:
            lines.append("# low-confidence detection — check the crop; "
                         "`drop: yes` if there is no text")
        lines.append(f"src: {region.get('source_text', '')}")
        lines.append(f"fa: {region.get('target_text', '')}")
        if region.get("speaker"):
            lines.append(f"speaker: {region['speaker']}")
    return "\n".join(lines) + "\n"


def build_document(
    doc_path: str | Path,
    out: str | Path | None = None,
    *,
    pages: Sequence[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    folder = Path(out) if out else root / "worksheets"
    fingerprint = ir.fingerprint(doc)

    existing = sorted(folder.glob("*.done.txt")) if folder.exists() else []
    stale = [
        path.name for path in existing
        if (match := FINGERPRINT.search(ir.read_text(path)))
        and match.group("value") != fingerprint
    ]
    if stale and not force:
        return {
            "refused": "stale-worksheets",
            "stale": stale[:20],
            "detail": (
                "These completed worksheets were written against a different "
                "set of regions, so their ids no longer point at the same "
                "balloons. Re-translate them, or pass --force if you are "
                "certain the regions did not move."
            ),
        }

    written: list[str] = []
    empty: list[str] = []
    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        if not page.get("regions"):
            empty.append(page["id"])
            continue
        target = folder / f"{page['id']}.txt"
        ir.write_text(target, page_worksheet(doc, page, fingerprint))
        written.append(str(target.relative_to(root)) if target.is_relative_to(root)
                       else str(target))

    return {
        "worksheets": written,
        "count": len(written),
        "pages_without_text": empty,
        "fingerprint": fingerprint,
        "next": "Translate each one to <page>.done.txt, then run `worksheet merge`.",
    }


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def parse_worksheet(text: str) -> dict[str, dict[str, str]]:
    """``{region id: {field: value}}``. Unknown lines continue the last field."""
    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    field: str | None = None

    for raw in text.splitlines():
        header = HEADER.match(raw)
        if header:
            region_id = header.group("id")
            current = blocks.setdefault(region_id, {"_seen": 0})
            current["_seen"] = int(current.get("_seen", 0)) + 1
            field = None
            continue
        if current is None:
            continue
        if raw.lstrip().startswith("#"):
            continue
        match = FIELD.match(raw)
        if match:
            field = match.group("name")
            current[field] = match.group("value").strip()
            continue
        if field is not None:
            # A continuation line. Keep the newline: a balloon that breaks its
            # own line does so for a reason, and the typesetter may honour it.
            current[field] = (current[field] + "\n" + raw.strip()).strip()
    return blocks


def _apply(region: dict[str, Any], block: dict[str, str],
           report: dict[str, list[str]]) -> bool:
    if block.get("drop", "").strip().lower() in {"yes", "true", "1"}:
        region["dropped"] = True
        region["target_text"] = ""
        region["source_text"] = ""
        report["dropped"].append(region["id"])
        return True

    source = block.get("src", "").strip()
    target = block.get("fa", "").strip()
    kind = block.get("kind", "").strip().lower()
    speaker = block.get("speaker", "").strip()
    note = block.get("note", "").strip()

    if kind:
        if kind not in ir.REGION_KINDS:
            report["bad_kind"].append(f"{region['id']}: {kind}")
        elif kind != region["kind"]:
            region["kind"] = kind
            report["reclassified"].append(f"{region['id']} -> {kind}")
    if speaker:
        region["speaker"] = speaker
    if note:
        region.setdefault("review", []).append(note)

    region["source_text"] = source
    region["target_text"] = target
    region["dropped"] = False
    # Locking stops a later `detect` run from renumbering a region a human or a
    # reading model has already committed a translation to.
    region["locked"] = bool(source or target)
    return bool(target)


def merge_document(
    doc_path: str | Path,
    worksheets: str | Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    folder = Path(worksheets) if worksheets else root / "worksheets"
    fingerprint = ir.fingerprint(doc)
    policy = doc["meta"].get("sfx_policy", "keep")

    if not folder.exists():
        return {"ok": False, "error": f"no worksheets at {folder}"}

    report: dict[str, Any] = {
        "merged": 0,
        "dropped": [],
        "reclassified": [],
        "bad_kind": [],
        "missing_outputs": [],
        "missing_regions": [],
        "unknown_regions": [],
        "duplicate_regions": [],
        "empty_translation": [],
        "stale_worksheets": [],
    }

    by_page = {page["id"]: page for page in doc["pages"]}
    for page_id, page in by_page.items():
        if not page.get("regions"):
            continue
        path = folder / f"{page_id}.done.txt"
        if not path.exists():
            report["missing_outputs"].append(page_id)
            continue

        text = ir.read_text(path)
        stamped = FINGERPRINT.search(text)
        if stamped and stamped.group("value") != fingerprint and not force:
            report["stale_worksheets"].append(page_id)
            continue

        blocks = parse_worksheet(text)
        known = {region["id"] for region in page["regions"]}
        for region_id, block in blocks.items():
            if int(block.get("_seen", 1)) > 1:
                report["duplicate_regions"].append(region_id)
        report["unknown_regions"] += sorted(set(blocks) - known)

        for region in page["regions"]:
            block = blocks.get(region["id"])
            if block is None:
                report["missing_regions"].append(region["id"])
                continue
            filled = _apply(region, block, report)
            if filled:
                report["merged"] += 1
            elif not region.get("dropped") and ir.translatable(region, policy):
                report["empty_translation"].append(region["id"])

    ir.stamp_stage(doc, "worksheet", {"merged": report["merged"]})
    ir.save_doc(doc, doc_path)

    blocking = (
        report["missing_outputs"] or report["missing_regions"]
        or report["unknown_regions"] or report["duplicate_regions"]
        or report["stale_worksheets"] or report["empty_translation"]
        or report["bad_kind"]
    )
    report["ok"] = not blocking
    for key in ("missing_regions", "unknown_regions", "empty_translation"):
        report[key] = report[key][:25]
    return report


def status(doc_path: str | Path, worksheets: str | Path | None = None) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    folder = Path(worksheets) if worksheets else root / "worksheets"

    expected = [page["id"] for page in doc["pages"] if page.get("regions")]
    done = [page_id for page_id in expected if (folder / f"{page_id}.done.txt").exists()]
    return {
        "pages_with_text": len(expected),
        "translated": len(done),
        "remaining": [page_id for page_id in expected if page_id not in set(done)],
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic worksheet",
        description="Build translation worksheets, or merge the answers back.",
    )
    parser.add_argument("action", choices=["build", "merge", "status"])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--worksheets", default=None)
    parser.add_argument("--pages", default="")
    parser.add_argument("--force", action="store_true",
                        help="proceed even though the regions changed")
    args = parser.parse_args(argv)

    if args.action == "build":
        report = build_document(
            args.doc, args.worksheets,
            pages=[p for p in args.pages.split(",") if p] or None,
            force=args.force,
        )
        ir.emit(report)
        return 1 if report.get("refused") else 0

    if args.action == "status":
        ir.emit(status(args.doc, args.worksheets))
        return 0

    report = merge_document(args.doc, args.worksheets, force=args.force)
    ir.emit(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
