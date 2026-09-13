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
import stages
import providers

#: Below this a reading is a guess. It becomes a review note rather than text.
#: Deliberately high: a wrong transcription is worse than an empty one, because
#: an empty region is visible to every gate and a wrong one is invisible to all
#: of them.
MIN_CONFIDENCE = 0.65


def crop_identity(page: dict[str, Any], region: dict[str, Any]) -> str:
    """What the crop for this region is a crop OF.

    Region ids are ordinals and survive a re-detection, so `p0001/r002.png`
    from before the boxes moved was still on disk and still matched the name.
    The BALLOON is in here too: the cropper pads to it, so a balloon traced
    differently produces a different picture from the same box — and the old
    name could not tell those apart either.
    """
    return ir.sha256_bytes(
        f"{page['sha256']}|{region['bbox']}|{region.get('orientation')}|"
        f"{region.get('balloon')}|{region.get('polarity')}"
        .encode("utf-8"))[:8]


def _crop_path(root: Path, page: dict[str, Any], region: dict[str, Any],
               page_image) -> Path:
    """One region, written where an engine can open it by path.

    Engines take a file, not an array, and the crop the reader already looks at
    is the right input: same padding, same bounds, so a disagreement is about
    the reading rather than about two different pictures.
    """
    # Named for the geometry it came from, not for the region alone. Region
    # ids are ordinals and survive a re-detection, so `p0001/r002.png` from
    # before the boxes moved was still on disk and still matched the name —
    # and the engine read the old picture of a different part of the page.
    where = crop_identity(page, region)
    target = root / "ocr" / page["id"] / f"{region['id']}-{where}.png"
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
    vision: str | None = None,
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

    eyes = providers.get("vision", vision)
    orientation_aware = providers.wants(engine, "ocr", "orientation")
    counts = {"applied": 0, "unchanged": 0, "locked": 0, "needs_review": 0,
              "failed": 0, "resumed": 0}
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
            # Real resume: work this provider already finished is not re-read.
            # The previous version called the engine again and let a differing
            # answer overwrite a good one, which made two runs of the same
            # command produce two different documents.
            # Asked BEFORE the call, and about the crop this run would make —
            # the skip used to happen before anything consulted the crop name
            # at all, so a region whose box had moved was resumed against a
            # reading of a different part of the page.
            identity = providers.request_identity(
                crop=crop_identity(page, region), provider=provider,
                language=language, vision=vision,
                orientation=region.get("orientation") if orientation_aware
                else None)
            if providers.completed(region, "ocr", "source_text",
                                   identity=identity):
                counts["resumed"] += 1
                page_counts["resumed"] += 1
                continue

            crop = _crop_path(root, page, region, page_image)
            # Vertical Japanese is the reason this stage exists, and the
            # detector already measured it — so an engine that can use the
            # writing direction is told it rather than left to re-derive it
            # from a crop with the page cut away. Offered, never imposed: an
            # engine that does not name the argument is called as before.
            extra = {}
            if orientation_aware:
                extra["orientation"] = region.get("orientation", "horizontal")
            result = providers.call(engine, "ocr", str(crop), language,
                                    timeout=timeout, name=provider, **extra)
            before = (region.get("source_text") or "").strip()
            outcome = providers.apply(region, "source_text", result,
                                      min_confidence=min_confidence,
                                      identity=identity)
            counts[outcome] += 1
            page_counts[outcome] += 1
            if outcome == "needs_review" and result.ok and before:
                row = {
                    "region": region["id"],
                    "kept": before,
                    "read": str(result.data).strip(),
                    # Which way the line ran. A disagreement on a vertical
                    # region is a different kind of disagreement — it is where
                    # furigana gets mixed into the line — and the person
                    # scanning this list should not have to open the crop to
                    # find out which ones those were.
                    "orientation": region.get("orientation", "horizontal"),
                }
                # Optional third opinion. A vision model looking at the crop can
                # sometimes settle which reading is right — but it is advisory,
                # it never writes, and everything above works with `eyes` None.
                if eyes is not None:
                    verdict = providers.call(
                        eyes, "vision", str(crop),
                        [{"id": region["id"], "kept": before,
                          "read": row["read"]}],
                        timeout=timeout, name=vision)
                    if verdict.ok:
                        row["vision"] = str(verdict.data)[:300]
                        ir.add_audit(
                            region,
                            f"{vision} on the disagreement: {row['vision']}")
                    region.setdefault("provenance", []).append(
                        verdict.as_provenance())
                disagreements.append(row)

        per_page.append({"page": page["id"], **page_counts})
        # Saved per page, for the same reason translation is: an interrupted
        # run must not throw away the pages it has already read.
        ir.save_doc(doc, doc_path)

    stages.stamp_stage(doc, "ocr", {"provider": provider, "totals": counts,
                                    "orientation_aware": orientation_aware},
                       options={"provider": provider, "vision": vision,
                                "min_confidence": min_confidence},
                       pages=pages)
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
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Optional OCR second opinion. Off by default; the reading "
                    "model is the primary transcriber.")
    parser.add_argument("--doc", required=True)
    parser.add_argument("--provider", required=True,
                        help="registered OCR provider name")
    parser.add_argument("--pages", default="")
    parser.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE)
    parser.add_argument("--timeout", type=float, default=providers.DEFAULT_TIMEOUT)
    parser.add_argument("--vision", default=None,
                        help="optional vision provider, asked only to comment "
                             "on a disagreement; it never writes")
    args = parser.parse_args(argv)

    ir.emit(read_document(
        args.doc,
        provider=args.provider,
        pages=[p for p in args.pages.split(",") if p] or None,
        min_confidence=args.min_confidence,
        timeout=args.timeout,
        vision=args.vision,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
