"""An optional second opinion on what the source text says.

**This stage is off by default and should usually stay off.** The reading model
running the skill sees the crop sheets, the speaker's face and the balloon that
answers, and reads all three together; an OCR engine sees one rectangle. On
every page this project has measured, the engine is the weaker reader.

Where it earns its place is narrow and real:

* **a host with no vision** — a scripted batch run, a text-only client;
* **a script the host reads poorly** — vertical Japanese with furigana is the
  standard example, and `manga-ocr` is trained on exactly it;
* **a second pair of eyes on a page that matters**, where a disagreement is
  itself the useful output.

The rule that makes it safe to run at all: **it never invents text and never
overwrites a decision.** A confident reading fills an empty region. A
disagreement with a locked value is recorded as a disagreement, not applied. An
unconfident reading becomes a review note and nothing else. Inventing
`source_text` is the one failure the pipeline cannot recover from, because every
later stage — glossary, translation, QA — trusts it completely.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import crops
import pageir as ir
import providers

#: Below this a reading is a guess. It becomes a review note rather than text.
#: Deliberately high: a wrong transcription is worse than an empty one, because
#: an empty region is visible to every gate and a wrong one is invisible to all
#: of them.
MIN_CONFIDENCE = 0.65


def _crop_path(root: Path, page: dict[str, Any], region: dict[str, Any],
               page_image) -> Path:
    """One region, written where an engine can open it by path.

    Engines take a file, not an array, and the crop the reader already looks at
    is the right input: same padding, same bounds, so a disagreement is about
    the reading rather than about two different pictures.
    """
    target = root / "ocr" / page["id"] / f"{region['id']}.png"
    if not target.exists():
        crop = crops._crop_for(page_image, region,
                               (page["width"], page["height"]))
        import masks as mask_tools

        ir.write_bytes(target, mask_tools._encode_png(crop))
    return target


def read_document(
    doc_path: str | Path,
    *,
    provider: str,
    pages: Sequence[str] | None = None,
    min_confidence: float = MIN_CONFIDENCE,
    timeout: float = providers.DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Read every region that does not already have a committed transcription.

    Resumable by construction: a region that is `locked`, or that a previous run
    already filled, is compared rather than re-read, so interrupting this stage
    and running it again costs the calls it did not finish and nothing else.
    """
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    engine = providers.get("ocr", provider)
    language = doc["meta"].get("source_language", "ja")

    counts = {"applied": 0, "locked": 0, "needs_review": 0, "failed": 0}
    disagreements: list[dict[str, str]] = []
    per_page: list[dict[str, Any]] = []

    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        regions = [r for r in page.get("regions", []) if not r.get("dropped")]
        if not regions:
            continue
        page_image = ir.load_image(root / page["image"])
        page_counts = dict.fromkeys(counts, 0)

        for region in regions:
            crop = _crop_path(root, page, region, page_image)
            result = providers.call(engine, "ocr", str(crop), language,
                                    timeout=timeout, name=provider)
            before = (region.get("source_text") or "").strip()
            outcome = providers.apply(region, "source_text", result,
                                      min_confidence=min_confidence)
            counts[outcome] += 1
            page_counts[outcome] += 1
            if outcome == "needs_review" and result.ok and before:
                disagreements.append({
                    "region": region["id"],
                    "kept": before,
                    "read": str(result.data).strip(),
                })

        per_page.append({"page": page["id"], **page_counts})

    ir.stamp_stage(doc, "ocr", {"provider": provider, "totals": counts})
    ir.save_doc(doc, doc_path)

    return {
        "document": str(doc_path),
        "provider": provider,
        "totals": counts,
        "pages": per_page,
        "disagreements": disagreements[:40],
        "disagreement_count": len(disagreements),
        "note": (
            "A disagreement is not an error. The locked value was kept and the "
            "engine's reading recorded beside it; look at those regions in the "
            "crop sheet and decide."
        ) if disagreements else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Optional OCR second opinion. Off by default; the reading "
                    "model is the primary transcriber.")
    parser.add_argument("--doc", required=True)
    parser.add_argument("--provider", required=True,
                        help="registered OCR provider name")
    parser.add_argument("--pages", default="")
    parser.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE)
    parser.add_argument("--timeout", type=float, default=providers.DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    ir.emit(read_document(
        args.doc,
        provider=args.provider,
        pages=[p for p in args.pages.split(",") if p] or None,
        min_confidence=args.min_confidence,
        timeout=args.timeout,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
