"""Names and recurring terms, so a character is called the same thing twice.

A chapter is translated a page at a time. Without a shared table, page 3 calls
her هاروکا and page 11 calls her هارukا, and both readings are defensible in
isolation — which is exactly why the decision has to be made once and then
enforced rather than re-taken on every page.

Candidate finding here is deliberately modest. There is no named-entity model
for Japanese hiding in this file; a name arrives because the reader named a
speaker, because the reader wrote it in `propose:`, or because a balloon says
the same short thing several times across the chapter, which is what a name in
a comic looks like. Everything else is the reader's judgement, entered by hand.

`propose:` exists because the other two are not enough. A name that is only
*mentioned* — "did you see Anna?" — is said once, by somebody else, and is too
long for the repeat rule to notice; the only way in was to write it into
`speaker`, which then claimed the wrong person was talking and carried that
voice into every later page's context.

A locked target is a decision, and re-deciding it does not erase the first one:
changing one bumps `version` and keeps what it used to be, so a chapter
translated against the earlier spelling can still be found.

``check`` is the half that earns its keep: it reports every place a locked term
was rendered differently, which is the drift that no amount of care prevents.
"""

from __future__ import annotations

import argparse
import re
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pageir as ir
import stages

#: A balloon that is only a name is short. Longer than this and a repeat is a
#: catchphrase or a stock reaction, not a candidate for the names table.
MAX_NAME_LENGTH = 12
MIN_OCCURRENCES = 2


#: Roles, weakest claim first. A term the reader named as a speaker outranks
#: one they merely pointed at, which outranks one the repeat rule guessed.
ROLES = ("term", "mentioned", "character")


def _entry(source: str, *, role: str = "", first: str = "") -> dict[str, Any]:
    return {
        "target": "",
        "role": role,
        "first_seen": first,
        "count": 0,
        "locked": False,
        "version": 1,
    }


def _promote(entry: dict[str, Any], role: str) -> None:
    """Raise an entry's role, never lower it.

    A character who is also mentioned by name in someone else's balloon must
    not stop being a character because the mention was scanned second.
    """
    current = entry.get("role") or ""
    if current not in ROLES or ROLES.index(role) > ROLES.index(current):
        entry["role"] = role


def set_target(entry: dict[str, Any], target: str) -> dict[str, Any]:
    """Record a canonical form, keeping the one it replaces.

    Only a LOCKED entry has a decision to preserve; an unlocked `target` is
    still a suggestion and overwriting it costs nothing.
    """
    target = (target or "").strip()
    previous = (entry.get("target") or "").strip()
    if entry.get("locked") and previous and previous != target:
        entry.setdefault("previous", []).append({
            "target": previous,
            "version": int(entry.get("version") or 1),
        })
        entry["version"] = int(entry.get("version") or 1) + 1
    entry["target"] = target
    return entry


def scan(doc_path: str | Path) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    glossary = doc.setdefault("glossary", {})
    entries: dict[str, Any] = glossary.setdefault("entries", {})

    speakers: Counter[str] = Counter()
    mentioned: Counter[str] = Counter()
    repeats: Counter[str] = Counter()
    first_seen: dict[str, str] = {}

    for page, region in ir.iter_regions(doc):
        if region.get("dropped"):
            continue
        speaker = (region.get("speaker") or "").strip()
        if speaker:
            speakers[speaker] += 1
            first_seen.setdefault(speaker, page["id"])
        for name in region.get("proposed") or []:
            name = name.strip()
            if name:
                mentioned[name] += 1
                first_seen.setdefault(name, page["id"])
        source = (region.get("source_text") or "").strip()
        if source and len(source) <= MAX_NAME_LENGTH and "\n" not in source:
            repeats[source] += 1
            first_seen.setdefault(source, page["id"])

    for name, count in speakers.items():
        entry = entries.setdefault(name, _entry(name, role="character",
                                                first=first_seen.get(name, "")))
        entry["count"] = count
        _promote(entry, "character")
    for name, count in mentioned.items():
        entry = entries.setdefault(name, _entry(name, role="mentioned",
                                                first=first_seen.get(name, "")))
        # A name that is both said and mentioned is counted once for each, so
        # the table shows how often the chapter uses it at all.
        entry["count"] = entry.get("count", 0) + count if name in speakers \
            else count
        _promote(entry, "mentioned")
    for text, count in repeats.items():
        existing = entries.get(text)
        if existing is not None:
            # Refresh it. Speaker counts were updated on every scan and
            # term counts were not, so a term that had nearly left the
            # chapter still looked like one of its commonest words. The
            # reader's own `target`, `locked` and `role` are untouched.
            existing["count"] = count
            continue
        if count < MIN_OCCURRENCES:
            continue
        entry = entries.setdefault(text, _entry(text, role="term",
                                                first=first_seen.get(text, "")))
        entry["count"] = count
    for text, entry in entries.items():
        # A term that no longer appears at all is not in `repeats`, so it
        # would have kept whichever count it had when it last did.
        if entry.get("role") == "term" and text not in repeats:
            entry["count"] = 0
        entry.setdefault("version", 1)

    stages.stamp_stage(doc, "glossary", {"entries": len(entries)})
    ir.save_doc(doc, doc_path)

    needs = sorted(
        (name for name, entry in entries.items() if not entry.get("target")),
        key=lambda name: -entries[name]["count"],
    )
    return {
        "entries": len(entries),
        "needs_persian": needs[:40],
        "needs_persian_count": len(needs),
        "how": (
            "Edit the `glossary.entries` table in comic.json: set `target` to the "
            "Persian and `locked` to true. Locked entries are printed in every "
            "worksheet and enforced by `glossary check`."
        ),
    }


#: A term written in a script that has word boundaries. `Ann` inside
#: `Anna` is not an occurrence of `Ann`, and reporting it sends a
#: translator to correct something that was already right.
_BOUNDED_TERM = re.compile(r"^[A-Za-z][A-Za-z\u2019'-]*$")


def _mentions(term: str, source: str) -> bool:
    """Whether `source` really uses `term`.

    Substring for everything else, deliberately. Japanese has no spaces,
    so a word-boundary test never matches a CJK term at all and every one
    of them would quietly stop being enforced; Persian inflects by
    attaching, so the same applies there.
    """
    if _BOUNDED_TERM.match(term):
        return re.search(rf"\b{re.escape(term)}\b", source) is not None
    return term in source


def check(doc_path: str | Path, *, limit: int | None = 30) -> dict[str, Any]:
    doc = ir.load_doc(Path(doc_path))
    entries = doc.get("glossary", {}).get("entries", {})
    locked = {
        source: entry["target"]
        for source, entry in entries.items()
        if entry.get("locked") and entry.get("target")
    }
    if not locked:
        return {"ok": True, "locked": 0, "drift": [],
                "note": "No locked terms, so nothing to enforce."}

    drift: list[dict[str, str]] = []
    for _, region in ir.iter_regions(doc):
        if region.get("dropped"):
            continue
        source = (region.get("source_text") or "")
        target = (region.get("target_text") or "")
        if not source or not target:
            continue
        for term, expected in locked.items():
            # Only meaningful where the source term is actually present; a term
            # absent from the balloon cannot have been rendered wrongly in it.
            if _mentions(term, source) and expected not in target:
                drift.append({
                    "region": region["id"],
                    "term": term,
                    "expected": expected,
                    "got": target[:60],
                })
    return {
        "ok": not drift,
        "locked": len(locked),
        "drift": drift if limit is None else drift[:limit],
        "drift_count": len(drift),
    }


def apply_file(doc_path: str | Path, table: str | Path) -> dict[str, Any]:
    """Merge a hand-written ``{"source": {"target": ...}}`` table into the doc."""
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    payload = json.loads(ir.read_text(table))
    entries = doc.setdefault("glossary", {}).setdefault("entries", {})

    applied = 0
    for source, value in payload.items():
        record = {"target": value} if isinstance(value, str) else dict(value)
        entry = entries.setdefault(source, _entry(source))
        # A hand-made decision outranks anything scanning produced, but the
        # occurrence count stays: it is measurement, not judgement.
        for key in ("target", "role", "note"):
            if record.get(key):
                entry[key] = record[key]
        entry["locked"] = bool(record.get("locked", True))
        applied += 1

    ir.save_doc(doc, doc_path)
    return {"applied": applied, "entries": len(entries)}


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic glossary",
        description="Collect names and terms, and enforce them.",
    )
    parser.add_argument("action", choices=["scan", "check", "apply"])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--table", default=None, help="JSON table, for `apply`")
    args = parser.parse_args(argv)

    if args.action == "scan":
        report = scan(args.doc)
    elif args.action == "check":
        report = check(args.doc)
    else:
        if not args.table:
            parser.error("apply needs --table")
        report = apply_file(args.doc, args.table)
    ir.emit(report)
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
