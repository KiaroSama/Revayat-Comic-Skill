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
    """Who has spoken so far, and how often, in first-appearance order.

    Order is by first appearance rather than by frequency because it is stable:
    a frequency sort reshuffles as a chapter progresses and the same page would
    build two different packages on two runs.
    """
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


def build(doc: dict[str, Any], page_id: str, *,
          budget: int = CONTEXT_BUDGET) -> dict[str, Any]:
    """The bounded package for one page.

    `constraints` and `context` are separate on purpose. Everything under
    `constraints` was decided by a person or a locked glossary and is not open
    for reinterpretation; everything under `context` is there to inform a
    choice. Flattening the two is how a locked term gets "improved".
    """
    meta = doc.get("meta", {})
    glossary = {
        term: entry for term, entry in (meta.get("glossary") or {}).items()
        if isinstance(entry, dict) and entry.get("locked")
    } or (meta.get("glossary") or {})

    previous, truncated = _previous(doc, page_id, budget)
    spent = sum(len(row["fa"]) + len(row["src"]) for row in previous)

    return {
        "page": page_id,
        "constraints": {
            "glossary": glossary,
            "policy": {
                "sfx": meta.get("sfx_policy", "keep"),
                "direction": meta.get("direction", "rtl"),
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
            "speakers": _speakers(doc, page_id),
            "previous_lines": previous,
            "next_page": _next(doc, page_id),
            "style_notes": meta.get("style_notes") or [],
        },
        "budget": {
            "characters": budget,
            "characters_used": spent,
            "previous_lines": len(previous),
            "truncated": truncated,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The bounded chapter context for one page.")
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True)
    parser.add_argument("--budget", type=int, default=CONTEXT_BUDGET)
    args = parser.parse_args(argv)

    doc = ir.load_doc(Path(args.doc))
    ir.emit(build(doc, args.page, budget=args.budget))
    return 0


if __name__ == "__main__":
    sys.exit(main())
