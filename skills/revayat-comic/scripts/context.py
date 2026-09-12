"""What a translator needs to know about the rest of the chapter, bounded.

Step 5 hands a page's worksheet, its crop sheets and the translation policy to
whoever is translating. That is enough to translate the page and not enough to
translate it *consistently*: a character who was `شما` on page 4 becomes `تو` on
page 5, a term settled in the glossary drifts, and a sentence split across two
pages loses its join.

This builds the missing piece and nothing more. Three properties matter, and the
first is the one that makes it usable at all:

**Bounded.** A chapter does not fit in a prompt and should not try to. The
package is capped in characters and in region count, and it fills that budget
from the nearest pages outward, because a line two pages back matters more than
one twenty pages back. `CONTEXT_BUDGET` is the whole contract.

**Deterministic.** The same document and page produce the same package, byte for
byte, every time. That is what makes a resumed run continue rather than restart:
nothing here depends on call order, wall-clock time or what happened to be
cached.

**Locked decisions win.** The glossary and any region a person committed to are
facts here, never suggestions. Everything else in the package is context; those
are constraints, and they are marked as such so a translator cannot mistake one
for the other.

What this is *not* is a summary. It never condenses dialogue into a paraphrase,
never merges two regions, and never drops a line to save room — it carries fewer
lines instead. Summarising the story is how a translation quietly loses the
thing it was supposed to carry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pageir as ir
import worksheet

#: Characters of dialogue the package may carry. Roughly two pages of a talky
#: chapter, which is where consistency actually lives; past that the marginal
#: line adds prompt cost and no accuracy.
CONTEXT_BUDGET = 3000

#: Regions of already-translated dialogue to look back over, at most.
MAX_PREVIOUS = 24

#: Regions of the *next* page to mention, by kind only. Enough to see that a
#: sentence continues; not enough to translate ahead and lock in a reading.
MAX_NEXT = 8


def _speakers(doc: dict[str, Any], upto: str) -> list[dict[str, Any]]:
    """Who has spoken so far, in first-appearance order, with what is known.

    Order is by first appearance rather than by frequency because it is stable:
    a frequency sort reshuffles as a chapter progresses and the same page would
    build two different packages on two runs.

    `register`, `relationships` and `voice` come from `meta.cast` when somebody
    has written them and are **absent otherwise**. Nothing here infers a
    character's speech register from their line count: a guess about how a
    person talks, handed to a translator as context, is worse than silence
    because it reads like knowledge.
    """
    cast = (doc.get("meta", {}).get("cast") or {})
    seen: dict[str, dict[str, Any]] = {}
    for page in doc["pages"]:
        for region in page.get("regions", []):
            name = (region.get("speaker") or "").strip()
            if not name or region.get("dropped"):
                continue
            entry = seen.setdefault(name, {"speaker": name, "lines": 0,
                                           "first_page": page["id"]})
            entry["lines"] += 1
        if page["id"] == upto:
            break

    for name, entry in seen.items():
        known = cast.get(name)
        if not isinstance(known, dict):
            continue
        for field_name in ("register", "voice", "relationships", "pronouns"):
            value = known.get(field_name)
            if value:
                entry[field_name] = value
    return list(seen.values())


def _previous(doc: dict[str, Any], page_id: str,
              budget: int) -> tuple[list[dict[str, str]], bool]:
    """Translated dialogue before this page, nearest first, until the budget.

    Returns the lines and whether anything was left out. The flag has to come
    from the loop rather than be inferred from the total afterwards: the loop
    stops *before* adding the line that would not fit, so a package that dropped
    six pages of dialogue can still be well under its own budget. Inferring it
    reported `truncated: false` on a package that was plainly truncated.
    """
    lines: list[dict[str, str]] = []
    spent = 0
    for page in reversed(doc["pages"][:_index(doc, page_id)]):
        for region in reversed(page.get("regions", [])):
            target = (region.get("target_text") or "").strip()
            if not target or region.get("dropped"):
                continue
            source = (region.get("source_text") or "").strip()
            cost = len(target) + len(source)
            if spent + cost > budget or len(lines) >= MAX_PREVIOUS:
                return list(reversed(lines)), True
            spent += cost
            lines.append({
                "page": page["id"],
                "region": region["id"],
                "speaker": (region.get("speaker") or "").strip(),
                "src": source,
                "fa": target,
            })
    return list(reversed(lines)), False


def _index(doc: dict[str, Any], page_id: str) -> int:
    for position, page in enumerate(doc["pages"]):
        if page["id"] == page_id:
            return position
    raise KeyError(f"no page {page_id!r} in this document")


def _next(doc: dict[str, Any], page_id: str) -> list[dict[str, str]]:
    """The following page, by region kind only.

    Deliberately thin. Enough to notice that the page ends mid-sentence; not
    enough to translate ahead, which would commit a reading before the page it
    belongs to has been looked at.
    """
    position = _index(doc, page_id) + 1
    if position >= len(doc["pages"]):
        return []
    following = doc["pages"][position]
    out = []
    for region in following.get("regions", [])[:MAX_NEXT]:
        if region.get("dropped"):
            continue
        out.append({"region": region["id"], "kind": region["kind"],
                    "speaker": (region.get("speaker") or "").strip()})
    return out


#: A hard limit per informational section, so a chapter with a novel in its
#: notes cannot quietly become the whole package. Anything cut is named in
#: `budget.overflowed`. There is no entry for `constraints`: see `build`.
SECTION_LIMITS = {
    "scene": 1200,
    "style_notes": 1200,
    "series_notes": 1200,
    "speakers": 2000,
}


def _fit(value, limit: int, name: str, over: list[str]):
    """One informational section, cut to its own limit and named if cut."""
    if len(ir.dumps(value)) <= limit:
        return value
    over.append(name)
    if isinstance(value, str):
        return value[:limit]
    kept = list(value)
    while kept and len(ir.dumps(kept)) > limit:
        kept.pop()
    return kept


def unmerged_before(doc_path: Path, doc: dict[str, Any],
                    page_id: str, *,
                    worksheets: str | Path | None = None) -> list[str]:
    """Earlier pages whose reply is written but not merged into the document.

    This is the whole failure mode of the workflow, made checkable. A page's
    context is the pages before it, and `build` reads `comic.json` — so a reply
    sitting in `pNNNN.done.txt` is invisible to it. Translating page 5 while
    page 4's Persian is still only a file on disk produces a context that is
    silently missing exactly the page it most needed.

    Returns the offending page ids, nearest first. Empty is the good case.
    """
    folder = Path(worksheets) if worksheets else doc_path.parent / "worksheets"
    if not folder.is_dir():
        return []
    behind: list[str] = []
    for page in doc["pages"][:_index(doc, page_id)]:
        reply = folder / f"{page['id']}.done.txt"
        if not reply.is_file():
            continue
        recorded = page.get("worksheet_digest")
        if recorded is None:
            # Merged by a build that did not record what it consumed.
            # Fall back to the old question rather than declaring every
            # page of an existing chapter unmerged.
            translated = any(
                (region.get("target_text") or "").strip()
                for region in page.get("regions", [])
                if not region.get("dropped")
            )
            if not translated:
                behind.append(page["id"])
            continue
        # Three failures, one test. The reply was never merged; or it was
        # merged and then edited, so the page holds last time's Persian;
        # or it was merged and only partly applied. "Does this page hold
        # any Persian yet" answered yes to the last two.
        if (recorded != worksheet.reply_digest(ir.read_text(reply))
                or not page.get("worksheet_clean", False)):
            behind.append(page["id"])
    return list(reversed(behind))


def build(doc: dict[str, Any], page_id: str, *,
          budget: int = CONTEXT_BUDGET) -> dict[str, Any]:
    """The bounded package for one page.

    `constraints` and `context` are separate on purpose. Everything under
    `constraints` was decided by a person or a locked glossary and is not open
    for reinterpretation; everything under `context` is there to inform a
    choice. Flattening the two is how a locked term gets "improved".
    """
    meta = doc.get("meta", {})
    # The canonical location, which is `glossary.entries` — not `meta.glossary`.
    # The first version read the wrong key and its test synthesised the wrong
    # key to match, so both agreed with each other and neither agreed with the
    # glossary stage. A test that builds its own fixture can validate a schema
    # that does not exist.
    entries = (doc.get("glossary") or {}).get("entries") or {}
    glossary = {
        term: entry.get("target", "")
        for term, entry in entries.items()
        if isinstance(entry, dict) and entry.get("locked")
        and (entry.get("target") or "").strip()
    }

    previous, truncated = _previous(doc, page_id, budget)
    over: list[str] = []
    # `constraints` is deliberately absent from this: a locked term that
    # silently vanishes to fit is a name the chapter then spells two ways.
    # It is reported as over budget instead, and sent whole.
    scene = _fit(meta.get("scene") or "", SECTION_LIMITS["scene"], "scene", over)
    style_notes = _fit(meta.get("style_notes") or [],
                       SECTION_LIMITS["style_notes"], "style_notes", over)
    series_notes = _fit(meta.get("series_notes") or [],
                        SECTION_LIMITS["series_notes"], "series_notes", over)
    speakers = _fit(_speakers(doc, page_id), SECTION_LIMITS["speakers"],
                    "speakers", over)
    spent = sum(len(row["fa"]) + len(row["src"]) for row in previous)

    sizes = {
        "speakers": len(ir.dumps(speakers)),
        "translation_memory": len(ir.dumps(previous)),
        "scene": len(scene),
        "style_notes": len(ir.dumps(style_notes)),
        "series_notes": len(ir.dumps(series_notes)),
        "glossary": len(ir.dumps(glossary)),
    }
    constraints_size = sizes["glossary"]

    package = {
        "page": page_id,
        "constraints": {
            "glossary": glossary,
            "policy": {
                "sfx": meta.get("sfx_policy", "keep"),
                # `reading_direction` is the key the importer writes.
                # `direction` is never set, so this always said "rtl" and
                # a left-to-right book was described backwards.
                "direction": meta.get("reading_direction", "rtl"),
                "source_language": meta.get("source_language", "ja"),
            },
            "rules": [
                "one source region becomes exactly one translated region",
                "never merge two balloons or split one across two",
                "never summarise, omit, soften or add",
                "a locked glossary term is used as written",
            ],
        },
        "context": {
            "speakers": speakers,
            # The chapter's own recent dialogue *is* the translation memory —
            # source beside target, nearest first. Not a summary of it.
            "translation_memory": previous,
            "next_page": _next(doc, page_id),
            # Written by a person, absent when nobody wrote one. An invented
            # scene description is a confident guess about the story, handed to
            # a translator as if it were established.
            "scene": scene,
            "style_notes": style_notes,
            "series_notes": series_notes,
        },
        "budget": {
            "characters": budget,
            "characters_used": spent,
            "lines": len(previous),
            "truncated": truncated,
            "section_limits": dict(SECTION_LIMITS),
            "sections": sizes,
            "overflowed": over,
            "constraints_characters": constraints_size,
            "constraints_over_budget": constraints_size > budget,
            # Measured with this field still holding a placeholder, so it is
            # a few characters short of the final string. It is here because
            # `characters_used` counted the dialogue alone while the glossary
            # and the notes went in beside it unbounded — an advertised 3000
            # describing a package of over 200,000.
            "package_characters": 0,
        },
    }
    package["budget"]["package_characters"] = len(ir.dumps(package))
    return package


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="The bounded chapter context for one page.")
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True)
    parser.add_argument("--budget", type=int, default=CONTEXT_BUDGET)
    parser.add_argument("--worksheets", default="",
                        help="where the finished worksheets are, when `worksheet "
                             "build --out` put them somewhere other than "
                             "work/worksheets")
    parser.add_argument("--allow-unmerged", action="store_true",
                        help="build the context even though earlier pages are "
                             "translated but not merged; they will be missing "
                             "from it")
    args = parser.parse_args(argv)

    doc_path = Path(args.doc)
    doc = ir.load_doc(doc_path)

    # The lock. Building a context while an earlier page's reply is unmerged is
    # the one mistake this whole package exists to prevent, and it is silent:
    # the JSON comes out well-formed and missing the pages that mattered. Refuse
    # by default; `--allow-unmerged` is there for the deliberate case, and says
    # what it costs.
    behind = unmerged_before(doc_path, doc, args.page,
                             worksheets=args.worksheets or None)
    if behind and not args.allow_unmerged:
        raise SystemExit(
            f"{', '.join(behind)} have been translated but not merged, so this "
            f"context would be missing them.\n"
            f"Run:  revayat-comic worksheet merge --doc {args.doc}\n"
            f"then build this context again. Translating a page before the "
            f"pages ahead of it are merged is what makes a chapter drift.\n"
            f"Pass --allow-unmerged if you meant to translate these together "
            f"and accept that they cannot see each other."
        )

    package = build(doc, args.page, budget=args.budget)
    if behind:
        package["budget"]["unmerged_pages"] = behind
    ir.emit(package)
    return 0


if __name__ == "__main__":
    sys.exit(main())
