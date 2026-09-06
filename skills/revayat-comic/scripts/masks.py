"""Turn a text box into the exact set of pixels that may be repainted.

A box is not a mask. Painting the whole box white erases the balloon outline,
the tail, and whatever artwork the box happens to overlap; painting only the
glyph pixels leaves a grey halo, because the edge of a glyph is anti-aliased and
those in-between pixels are still ink. So the mask is the glyph shapes, grown by
a small, measured amount, and then clipped back inside the balloon so the
outline can never be touched.

The union of every region's mask is written per page as well. That union is the
*authorised edit area*: after cleaning and typesetting, ``qa`` proves that every
pixel outside it is byte-identical to the page that came in. No stage is trusted
to stay inside its own lines; it is checked.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import pageir as ir

#: How far the glyph shapes are grown, as a share of the page's smaller side.
#: Enough to swallow anti-aliasing and JPEG ringing, small enough that a balloon
#: with tight lettering does not lose its outline.
DEFAULT_GROW = 0.0035

#: Extra margin around the text box before thresholding. The detector's box
#: hugs the glyphs; a stroke that leans out of it is still part of the letter.
DEFAULT_PAD = 0.004

#: How far inside its own outline a balloon may be repainted, as a share of the
#: balloon's smaller side. This is what keeps the outline intact.
OUTLINE_INSET = 0.035


def _cv2():
    ir.require("cv2", "opencv-python-headless", "building text masks")
    import cv2

    return cv2


def _numpy():
    ir.require("numpy", "numpy", "building text masks")
    import numpy

    return numpy


def balloon_interior(page_rgb, balloon, polarity: str, page_size: tuple[int, int],
                     *, inset: float = 0.0):
    """The paper inside a balloon's outline, as a page-sized 0/255 mask.

    A balloon's *bounding box* is not its interior, and using the box is a real
    defect rather than an approximation: the corners of the box around an
    ellipse are outside the balloon, so a mask clipped to the box repaints the
    artwork in those corners and erases the parts of the outline that cut
    across them. Measured — it left the balloons as pairs of arcs with a white
    rectangle punched through the screentone behind them.

    ``inset`` shrinks the result by that share of the balloon's smaller side,
    which is how the outline itself is kept out of reach.
    """
    cv2, np = _cv2(), _numpy()
    width, height = page_size
    canvas = np.zeros((height, width), np.uint8)
    x, y, w, h = ir.clamp_bbox(balloon, width, height)
    if w < 6 or h < 6:
        return canvas

    window = page_rgb[y:y + h, x:x + w]
    gray = cv2.cvtColor(window, cv2.COLOR_RGB2GRAY) if window.ndim == 3 else window
    if polarity == "dark":
        gray = 255 - gray
    _, light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
    if count < 2:
        return canvas

    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = 1 + int(np.argmax(areas))
    centre = int(labels[h // 2, w // 2])
    # The paper is far and away the biggest light component inside a balloon's
    # own box, so anything much smaller under the centre pixel is not it. Two
    # ways that happens, and only the first used to be handled: the centre lands
    # on a letter (label 0), or it lands on a *speck* — a dot of screentone, an
    # anti-aliased edge, the gap inside an `o`. Measured on a real page: the
    # centre hit a 113-pixel fleck, the interior came back empty, cleaning had
    # nothing to paint, and the English stayed on the finished page with every
    # count reporting success. Only `source-text-survived` noticed.
    if centre == 0 or int(stats[centre, cv2.CC_STAT_AREA]) < 0.5 * int(areas[largest - 1]):
        centre = largest

    inside = ((labels == centre).astype(np.uint8)) * 255
    # The letters are holes in that component. Filling them is unambiguous here:
    # the outline is outside the component, so it cannot be filled by accident.
    frame = np.zeros((h + 2, w + 2), np.uint8)
    frame[1:-1, 1:-1] = inside
    flooded = frame.copy()
    scratch = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(flooded, scratch, (0, 0), 255)
    inside = cv2.bitwise_or(inside, cv2.bitwise_not(flooded)[1:-1, 1:-1])

    if inset > 0:
        radius = max(1, int(inset * min(w, h)))
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1)
        )
        inside = cv2.erode(inside, kernel)

    canvas[y:y + h, x:x + w] = inside
    return canvas


#: Region kinds that live inside a balloon. `sfx`, `sign` and `unknown` are
#: lettering on the artwork and have no interior to find.
BALLOON_KINDS = ("speech", "thought", "narration")

#: A derived balloon may not be larger than this share of the page. Above it the
#: component is a panel or the page background, not a balloon — the same ceiling
#: `detect` uses, for the same reason.
MAX_DERIVED_BALLOON = 0.13


def find_balloon(page_rgb, bbox, polarity: str, page_size: tuple[int, int]):
    """The balloon around a box the reader drew, or ``None``.

    A region added by hand carries a text box and nothing else, so cleaning and
    typesetting would treat it as lettering on open artwork: the mask would not
    be clipped to an interior and Persian could be set straight over the
    outline. That matters most for the case the add feature exists to serve —
    **splitting one region that covers two balloons**, where both halves are
    balloons and neither knows it.

    So the enclosing light component is found the same way `balloon_interior`
    finds the paper, and accepted only if it really encloses the box and is
    small enough to be a balloon rather than a panel.
    """
    cv2, np = _cv2(), _numpy()
    width, height = page_size
    x, y, w, h = ir.clamp_bbox(bbox, width, height)
    if w < 4 or h < 4:
        return None

    # Look in a window around the box: the balloon is bigger than its lettering.
    margin = max(w, h)
    wx, wy, ww, wh = ir.clamp_bbox(
        [x - margin, y - margin, w + 2 * margin, h + 2 * margin], width, height)
    window = page_rgb[wy:wy + wh, wx:wx + ww]
    gray = cv2.cvtColor(window, cv2.COLOR_RGB2GRAY) if window.ndim == 3 else window
    if polarity == "dark":
        gray = 255 - gray
    _, light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
    if count < 2:
        return None

    # Seed from the paper *around* the lettering, not from the middle of it. The
    # centre of a text box usually lands on a letter, which is label 0, and
    # falling back to "the biggest component in the window" then picks the page
    # background rather than the balloon — measured on the fixture, where it
    # found nothing at all. A ring just outside the box is inside the balloon
    # when there is one, and is artwork when there is not.
    ring = [(x - wx + w // 2, y - wy - 4), (x - wx + w // 2, y - wy + h + 3),
            (x - wx - 4, y - wy + h // 2), (x - wx + w + 3, y - wy + h // 2),
            (x - wx + w // 2, y - wy + h // 2)]
    seen: dict[int, int] = {}
    for column, row in ring:
        if 0 <= row < wh and 0 <= column < ww:
            label = int(labels[row, column])
            if label:
                seen[label] = seen.get(label, 0) + 1

    cap = MAX_DERIVED_BALLOON * width * height
    for label, _votes in sorted(seen.items(), key=lambda item: -item[1]):
        bx, by, bw, bh = (int(stats[label, index]) for index in
                          (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                           cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        found = [wx + bx, wy + by, bw, bh]
        encloses = (found[0] <= x and found[1] <= y
                    and found[0] + found[2] >= x + w
                    and found[1] + found[3] >= y + h)
        if encloses and bw * bh <= cap:
            return found
    return None


def _ink_mask(window, polarity: str):
    """Glyph pixels inside a crop, as 0/255."""
    cv2 = _cv2()
    gray = cv2.cvtColor(window, cv2.COLOR_RGB2GRAY) if window.ndim == 3 else window
    if polarity == "dark":
        gray = 255 - gray
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask


def region_mask(
    page_rgb,
    region: dict[str, Any],
    page_size: tuple[int, int],
    *,
    grow: float = DEFAULT_GROW,
    pad: float = DEFAULT_PAD,
    solid_free: bool = False,
):
    """``(mask, box)`` — an 8-bit mask and the page-space box it covers.

    ``solid_free`` covers a region that has **no balloon** — lettering drawn
    straight onto the artwork — as one filled area instead of the glyph shapes.

    That is the wrong shape for the built-in cleaners, which would blank a
    rectangle out of the drawing, and the right one for a generative cleaner:
    clipped back to letter shapes, a reconstruction has to invent artwork inside
    strokes a few pixels wide and every seam lands on a glyph edge, which is
    exactly where the eye looks. Given the whole patch it can redraw what was
    under the lettering. Only usable with ``clean --external``, and ``clean``
    refuses the combination without it.
    """
    cv2, np = _cv2(), _numpy()
    width, height = page_size
    smaller = min(width, height)

    box = ir.expand_bbox(region["bbox"], max(2.0, pad * smaller), width, height)
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return np.zeros((1, 1), np.uint8), [x, y, 1, 1]

    balloon = region.get("balloon")
    if solid_free and not balloon:
        return np.full((h, w), 255, np.uint8), box

    window = page_rgb[y:y + h, x:x + w]
    mask = _ink_mask(window, region.get("polarity", "light"))

    radius = max(1, int(round(grow * smaller)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    mask = cv2.dilate(mask, kernel)
    # Close the gaps *between* letters as well, so the fill behind a line of
    # text is one continuous repair rather than a row of separate patches with
    # slivers of the old background surviving between them.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    if balloon:
        # Clip to the balloon's real interior, inset so the outline itself is
        # structurally out of reach. Not the bounding box — see balloon_interior.
        allowed = balloon_interior(
            page_rgb, balloon, region.get("polarity", "light"),
            page_size, inset=OUTLINE_INSET,
        )
        mask = cv2.bitwise_and(mask, allowed[y:y + h, x:x + w])

    return mask, box


def build_document(
    doc_path: str | Path,
    *,
    grow: float = DEFAULT_GROW,
    pad: float = DEFAULT_PAD,
    pages: Sequence[str] | None = None,
    solid_free: bool = False,
) -> dict[str, Any]:
    np = _numpy()
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)

    from PIL import Image

    written = 0
    derived = 0
    per_page: list[dict[str, Any]] = []
    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        if not page.get("regions"):
            per_page.append({"page": page["id"], "regions": 0, "coverage": 0.0})
            continue

        rgb = np.asarray(ir.load_image(root / page["image"]))
        size = (page["width"], page["height"])
        union = np.zeros((page["height"], page["width"]), np.uint8)

        for region in page["regions"]:
            # A box the reader drew arrives with no balloon. Find it, so a
            # hand-split pair of balloons is masked and typeset like any other.
            if (region.get("detector") == "reader" and not region.get("balloon")
                    and region["kind"] in BALLOON_KINDS):
                region["balloon"] = find_balloon(
                    rgb, region["bbox"], region.get("polarity", "light"), size)
                derived += region["balloon"] is not None

            mask, box = region_mask(rgb, region, size, grow=grow, pad=pad,
                                    solid_free=solid_free)
            relative = f"masks/{page['id']}/{region['id']}.png"
            ir.write_bytes(
                root / relative,
                _encode_png(Image.fromarray(mask, mode="L")),
            )
            region["mask"] = relative
            region["mask_box"] = box
            x, y, w, h = box
            union[y:y + h, x:x + w] = np.maximum(union[y:y + h, x:x + w], mask)
            written += 1

        relative = f"masks/{page['id']}/union.png"
        ir.write_bytes(root / relative, _encode_png(Image.fromarray(union, mode="L")))
        page["mask"] = relative
        coverage = float((union > 0).sum()) / float(page["width"] * page["height"])
        page["mask_coverage"] = round(coverage, 5)
        per_page.append({
            "page": page["id"],
            "regions": len(page["regions"]),
            "coverage": page["mask_coverage"],
        })

    # Recorded so `clean` can refuse the one combination that would destroy
    # artwork: a solid free-lettering mask handed to the built-in cleaners.
    doc["meta"]["free_lettering_mask"] = "solid" if solid_free else "glyphs"
    ir.stamp_stage(doc, "masks", {"written": written, "balloons_derived": derived})
    ir.save_doc(doc, doc_path)

    # A mask covering a third of the page is not lettering; something matched
    # the artwork. Cleaning that would destroy the drawing, so it is surfaced
    # here rather than discovered in the finished file.
    excessive = [entry["page"] for entry in per_page if entry["coverage"] > 0.28]
    return {
        "document": str(doc_path),
        "masks_written": written,
        "balloons_derived": derived,
        "pages": per_page,
        "excessive_coverage": excessive,
        "warning": (
            "These pages would have more than 28% of their artwork repainted. "
            "Re-run detect with tighter thresholds, or drop the offending "
            "regions, before cleaning."
        ) if excessive else None,
    }


def _encode_png(image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def load_mask(path: str | Path):
    """Read a mask back as a 0/255 array."""
    np = _numpy()
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("L"))


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic mask",
        description="Build the pixel mask for every detected text region.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument("--grow", type=float, default=DEFAULT_GROW,
                        help="how far to grow the glyph shapes, as a share of "
                             f"the page's smaller side (default {DEFAULT_GROW})")
    parser.add_argument("--pad", type=float, default=DEFAULT_PAD,
                        help="margin added around the detector's text box")
    parser.add_argument("--free-lettering", choices=("glyphs", "solid"),
                        default="glyphs",
                        help="how to mask lettering drawn onto the artwork with "
                             "no balloon around it. `glyphs` (default) covers the "
                             "letter shapes; `solid` covers the whole region so a "
                             "generative cleaner can redraw what was under it — "
                             "that one only works with `clean --external`")
    args = parser.parse_args(argv)

    report = build_document(
        args.doc,
        grow=args.grow,
        pad=args.pad,
        pages=[p for p in args.pages.split(",") if p] or None,
        solid_free=args.free_lettering == "solid",
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
