"""An optional machine translator, for when nobody is reading the page.

**The default is that you translate.** Step 5 of the skill hands the reading
model the crop sheets, the worksheet and the bounded chapter context, and it
writes the Persian — with the speaker's face and the answering balloon in view.
That is the whole design and this module does not change it.

This exists for the case the design does not cover: a run with no reader at all.
A scheduled batch, a text-only host, a first pass over two hundred pages that a
person will then correct. In that case a translation provider is better than an
empty document, and the safety rules are the same ones every provider gets:

* it fills empty regions only — a value already there came from somewhere, and
  a machine does not overwrite it;
* a locked region is never touched, and a differing answer becomes a recorded
  disagreement;
* it receives the same bounded context package a human translator gets, so the
  glossary and the previous page's dialogue constrain it too;
* every failure is a status, and the document stays valid.

What it cannot do is see the page. It gets text and context, not the drawing —
which is exactly why it is the fallback and not the default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import context as chapter_context
import pageir as ir
import stages
import providers


def translate_document(
    doc_path: str | Path,
    *,
    provider: str,
    pages: Sequence[str] | None = None,
    budget: int = chapter_context.CONTEXT_BUDGET,
    timeout: float = providers.DEFAULT_TIMEOUT,
    worksheets: str | Path | None = None,
    allow_unmerged: bool = False,
) -> dict[str, Any]:
    """Translate every region that has source text and no Persian yet.

    Refuses a page whose earlier pages are translated but unmerged, for the
    same reason and with the same wording as `context build` does. This path
    built its own package and asked nothing, so the automatic route did
    silently what the manual route was written to refuse.
    """
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    engine = providers.get("translation", provider)

    counts = {"applied": 0, "unchanged": 0, "locked": 0, "needs_review": 0,
              "failed": 0, "resumed": 0, "skipped": 0}
    per_page: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []

    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        regions = [r for r in page.get("regions", []) if not r.get("dropped")]
        if not regions:
            continue

        state = chapter_context.preflight(
            doc_path, doc, page["id"], worksheets=worksheets,
            allow_unmerged=allow_unmerged)
        if not state["ok"]:
            refused.append({"page": page["id"],
                            "unmerged": state["unmerged"]})
            counts["skipped"] += len(regions)
            continue

        # Built once per page and handed to every region on it: the package is
        # about where the page sits in the chapter, not about one balloon.
        package = chapter_context.build(doc, page["id"], budget=budget)
        if state["unmerged"]:
            package["budget"]["unmerged_pages"] = state["unmerged"]
            package["budget"]["unmerged_override"] = True
        page_counts = dict.fromkeys(counts, 0)

        for region in regions:
            source = (region.get("source_text") or "").strip()
            if not source or not ir.translatable(
                    region, doc["meta"].get("sfx_policy", "keep")):
                counts["skipped"] += 1
                page_counts["skipped"] += 1
                continue
            identity = providers.request_identity(
                source=source, provider=provider,
                # The constraints the answer was produced under. Locking a
                # name or changing an approved spelling used to leave every
                # line translated before it looking finished.
                constraints=package.get("constraints"),
                kind=region["kind"], speaker=region.get("speaker") or "")
            if providers.completed(region, "translation", "target_text",
                                   identity=identity):
                counts["resumed"] += 1
                page_counts["resumed"] += 1
                continue

            result = providers.call(
                engine, "translation", source,
                {**package, "region": region["id"],
                 "kind": region["kind"],
                 "speaker": region.get("speaker", "")},
                timeout=timeout, name=provider)
            outcome = providers.apply(region, "target_text", result,
                                      identity=identity)
            counts[outcome] += 1
            page_counts[outcome] += 1

        per_page.append({"page": page["id"], **page_counts})
        # Saved per page. The whole chapter was written at the end, so an
        # interrupted run — a timeout, a rate limit, a closed laptop — threw
        # away every answer it had already paid for and asked for them again.
        ir.save_doc(doc, doc_path)

    if refused:
        counts["refused_pages"] = len(refused)
    stages.stamp_stage(doc, "translate", {"provider": provider,
                                          "totals": counts},
                       options={"provider": provider, "budget": budget},
                       pages=pages)
    ir.save_doc(doc, doc_path)

    return {
        "refused": refused,
        "next": (chapter_context.refusal(
            {"unmerged": sorted({p for entry in refused
                                 for p in entry["unmerged"]})}, doc_path)
            if refused else None),
        "document": str(doc_path),
        "provider": provider,
        "totals": counts,
        "pages": per_page,
        "note": (
            "Machine translation is a first pass, not a finished one. Read the "
            "crop sheets and correct it in the worksheet; `falint` and `qa` "
            "still apply, and a corrected region stops being re-translated."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Optional machine translation. Off by default; you are the "
                    "translator.")
    parser.add_argument("--doc", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument("--budget", type=int,
                        default=chapter_context.CONTEXT_BUDGET)
    parser.add_argument("--timeout", type=float,
                        default=providers.DEFAULT_TIMEOUT)
    parser.add_argument("--worksheets", default=None,
                        help="where the replies live, if not beside the document")
    parser.add_argument("--allow-unmerged", action="store_true",
                        help="translate pages whose earlier replies are not "
                             "merged, accepting that they cannot see them")
    args = parser.parse_args(argv)

    report = translate_document(
        args.doc,
        provider=args.provider,
        pages=[p for p in args.pages.split(",") if p] or None,
        budget=args.budget,
        timeout=args.timeout,
        worksheets=args.worksheets,
        allow_unmerged=args.allow_unmerged,
    )
    ir.emit(report)
    # A refused page is not a translated page, and exiting 0 told a script it
    # was.
    return 1 if report.get("refused") else 0


if __name__ == "__main__":
    sys.exit(main())
