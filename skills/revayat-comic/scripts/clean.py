"""Remove the source lettering without touching anything else.

Cleaning escalates. Most balloons are flat paper with black letters on them, and
for those the correct repair is to read the balloon's own colour and paint it
back — no model, no guessing, no texture invented where there was none. Only
when the region sits on real artwork does it go to an inpainter.

    flat      the region's background is uniform  ->  fill with that colour
    inpaint   there is line art or texture under it  ->  OpenCV Telea
    external  a cleaned page supplied from elsewhere  ->  composited in
    keep      left alone on purpose (an SFX under the `keep` policy)

The last step is the one that makes the whole thing safe. Whatever produced the
repaired pixels, they are composited back through the mask:

    out = original * (1 - alpha) + repaired * alpha        alpha <= mask

Since ``alpha`` is zero everywhere the mask is zero, every pixel outside the
authorised area is the original byte, by construction rather than by good
behaviour. That holds even for an external image produced by a generative model
that redrew half the page: only the masked pixels of it are ever used.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import masks as mask_tools
import pageir as ir

#: Standard deviation, in 8-bit levels, below which a background counts as flat.
#: Screentone is not flat and must not be filled; measured dot patterns sit well
#: above this, plain paper well below.
FLAT_STD = 9.0

#: How wide the blend ramp is, in pixels. It lives entirely inside the mask.
FEATHER = 2

#: Telea's radius. Larger reconstructs more context and smears more.
INPAINT_RADIUS = 4


def _cv2():
    ir.require("cv2", "opencv-python-headless", "cleaning artwork")
    import cv2

    return cv2


def _numpy():
    ir.require("numpy", "numpy", "cleaning artwork")
    import numpy

    return numpy


def _background_sample(window, mask, np, allowed=None):
    """Pixels in the crop that are *not* being repainted — the paper itself.

    ``allowed`` restricts the sample to the balloon's interior. Without it the
    sample picks up the balloon outline and whatever artwork sits in the corners
    of the crop, and a plain white balloon on a screentone background measures
    as textured. Every balloon then goes to the inpainter instead of taking the
    exact flat fill that is right for it — measured: nine balloons out of nine.
    """
    keep = mask == 0
    if allowed is not None:
        keep &= allowed > 0
    if keep.sum() < 24:
        return None
    return window[keep]


def choose_strategy(window, mask, np, allowed=None) -> tuple[str, tuple[int, int, int] | None]:
    sample = _background_sample(window, mask, np, allowed)
    if sample is None:
        return "inpaint", None
    spread = float(sample.reshape(-1, sample.shape[-1]).std(axis=0).max())
    if spread <= FLAT_STD:
        colour = tuple(int(round(value)) for value in sample.reshape(-1, 3).mean(axis=0))
        return "flat", colour
    return "inpaint", None


def _repair(window, mask, strategy: str, colour, np):
    cv2 = _cv2()
    if strategy == "flat":
        painted = np.empty_like(window)
        painted[:, :] = np.array(colour, dtype=window.dtype)
        return painted
    # Telea propagates the surrounding structure inwards. It is not a generative
    # model and will not invent a face; on a screentone gradient it produces a
    # smooth patch, which is the honest failure and is visible in review.
    return cv2.inpaint(window, (mask > 0).astype(np.uint8), INPAINT_RADIUS, cv2.INPAINT_TELEA)


def _composite(base, repaired, mask, np):
    """Blend, with the ramp strictly inside the authorised mask."""
    cv2 = _cv2()
    blurred = cv2.GaussianBlur(mask, (2 * FEATHER + 1, 2 * FEATHER + 1), 0)
    # Clamping to the hard mask is what keeps the guarantee: a Gaussian spreads
    # outward, and without this the ramp would leak a few pixels past the area
    # QA has authorised, failing the pixel-preservation check it exists to pass.
    alpha = np.minimum(blurred, mask).astype(np.float32) / 255.0
    alpha = alpha[..., None]
    return (base.astype(np.float32) * (1.0 - alpha)
            + repaired.astype(np.float32) * alpha).round().astype(np.uint8)


def clean_page(
    doc_path: Path,
    page: dict[str, Any],
    *,
    policy: str,
    external: Path | None = None,
) -> dict[str, Any]:
    np = _numpy()
    root = ir.doc_dir(doc_path)
    base = np.asarray(ir.load_image(root / page["image"])).copy()

    supplied = None
    if external is not None:
        candidate = next(
            (external / f"{page['id']}{suffix}"
             for suffix in (".png", ".jpg", ".jpeg", ".webp")
             if (external / f"{page['id']}{suffix}").exists()),
            None,
        )
        if candidate is not None:
            supplied = np.asarray(ir.load_image(candidate))
            if supplied.shape != base.shape:
                raise ValueError(
                    f"{candidate.name} is {supplied.shape[1]}x{supplied.shape[0]}, "
                    f"but {page['id']} is {base.shape[1]}x{base.shape[0]}. A "
                    "cleaned page has to be the same size as the original."
                )

    counts = {"flat": 0, "inpaint": 0, "external": 0, "keep": 0, "skipped": 0}
    for region in page.get("regions", []):
        if region.get("dropped") or not region.get("mask"):
            counts["skipped"] += 1
            continue
        if region["kind"] == "sfx" and policy in {"keep", "annotate"}:
            # The artwork *is* the sound effect. Erasing it to write the same
            # thing in Persian is a loss, so these two policies leave it drawn.
            region["fill"] = "keep"
            counts["keep"] += 1
            continue

        mask = mask_tools.load_mask(root / region["mask"])
        x, y, w, h = region["mask_box"]
        if w <= 0 or h <= 0 or not mask.any():
            counts["skipped"] += 1
            continue
        window = base[y:y + h, x:x + w]

        if supplied is not None:
            repaired, strategy, colour = supplied[y:y + h, x:x + w], "external", None
        else:
            allowed = None
            if region.get("balloon"):
                interior = mask_tools.balloon_interior(
                    base, region["balloon"], region.get("polarity", "light"),
                    (page["width"], page["height"]),
                    inset=mask_tools.OUTLINE_INSET,
                )
                allowed = interior[y:y + h, x:x + w]
            strategy, colour = choose_strategy(window, mask, np, allowed)
            repaired = _repair(window, mask, strategy, colour, np)

        base[y:y + h, x:x + w] = _composite(window, repaired, mask, np)
        region["fill"] = strategy
        if colour is not None:
            region["fill_colour"] = list(colour)
        counts[strategy] += 1

    from PIL import Image

    relative = f"clean/{page['id']}.png"
    ir.save_image(Image.fromarray(base), root / relative)
    page["clean"] = relative
    return counts


def clean_document(
    doc_path: str | Path,
    *,
    external: str | Path | None = None,
    pages: Sequence[str] | None = None,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    policy = doc["meta"].get("sfx_policy", "keep")
    external_dir = Path(external).expanduser() if external else None
    if external_dir is not None and not external_dir.is_dir():
        raise FileNotFoundError(f"--external is not a folder: {external_dir}")
    if (doc["meta"].get("free_lettering_mask") == "solid"
            and external_dir is None):
        raise ValueError(
            "the masks for this document were built with "
            "`mask --free-lettering solid`, which covers each piece of free "
            "lettering as a whole patch rather than as letter shapes. That is "
            "for a generative cleaner: painting it flat or inpainting it would "
            "blank a rectangle out of the artwork. Either pass --external with "
            "your reconstructed pages, or rebuild the masks with "
            "`mask --free-lettering glyphs`."
        )

    totals = {"flat": 0, "inpaint": 0, "external": 0, "keep": 0, "skipped": 0}
    per_page: list[dict[str, Any]] = []
    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        if not page.get("regions"):
            continue
        counts = clean_page(doc_path, page, policy=policy, external=external_dir)
        for key, value in counts.items():
            totals[key] += value
        per_page.append({"page": page["id"], **counts})

    ir.stamp_stage(doc, "clean", {"totals": totals})
    ir.save_doc(doc, doc_path)

    heavy = [entry["page"] for entry in per_page if entry["inpaint"] > entry["flat"]]
    return {
        "document": str(doc_path),
        "totals": totals,
        "pages": per_page,
        "inpaint_heavy_pages": heavy,
        "note": (
            "On these pages most regions needed inpainting rather than a flat "
            "fill, which means the lettering sits on artwork. Look at them "
            "before exporting; Telea smooths, it does not redraw."
        ) if heavy else None,
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic clean",
        description="Remove source lettering through the authorised masks.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument("--external", default=None,
                        help="folder of externally cleaned pages named "
                             "<page id>.png; only their masked pixels are used")
    args = parser.parse_args(argv)

    report = clean_document(
        args.doc,
        external=args.external,
        pages=[p for p in args.pages.split(",") if p] or None,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
