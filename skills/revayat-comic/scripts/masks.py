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
import stages

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
                     *, inset: float = 0.0, min_inset: int = 0, seed_box: Any = None):
    """The paper inside a balloon's outline, as a page-sized 0/255 mask.

    A balloon's *bounding box* is not its interior, and using the box is a real
    defect rather than an approximation: the corners of the box around an
    ellipse are outside the balloon, so a mask clipped to the box repaints the
    artwork in those corners and erases the parts of the outline that cut
    across them. Measured — it left the balloons as pairs of arcs with a white
    rectangle punched through the screentone behind them.

    ``inset`` shrinks the paper by a share of the smaller side, with a pixel
    floor of ``min_inset``. ``seed_box`` keeps a margin leak from taking over
    component selection.
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
    if polarity != "dark" and (gray >= 232).any():
        # Otsu alone can group a faint outline with the paper when dark ink is present.
        dx = cv2.Sobel(gray, cv2.CV_16S, 1, 0)
        dy = cv2.Sobel(gray, cv2.CV_16S, 0, 1)
        light[(gray < 232) | (np.abs(dx) + np.abs(dy) >= 42)] = 0

    def _pick_component(binary):
        cnt, lbls, st, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if cnt < 2:
            return 0, lbls, st
        areas = st[1:, cv2.CC_STAT_AREA]
        largest_lbl = 1 + int(np.argmax(areas))
        chosen = 0
        if seed_box is not None:
            sx, sy, sw, sh = ir.clamp_bbox(seed_box, width, height)
            lx0, ly0 = max(0, sx - x), max(0, sy - y)
            lx1, ly1 = min(w, sx + sw - x), min(h, sy + sh - y)
            if lx1 > lx0 and ly1 > ly0:
                sub = lbls[ly0:ly1, lx0:lx1]
                nonzero = sub[sub > 0]
                if nonzero.size > 0:
                    vals, counts = np.unique(nonzero, return_counts=True)
                    chosen = int(vals[int(np.argmax(counts))])
        if chosen == 0:
            chosen = int(lbls[h // 2, w // 2])
            if chosen == 0 or int(st[chosen, cv2.CC_STAT_AREA]) < 0.5 * int(areas[largest_lbl - 1]):
                chosen = largest_lbl
        return chosen, lbls, st

    centre, labels, stats = _pick_component(light)
    if centre == 0:
        return canvas

    inside = ((labels == centre).astype(np.uint8)) * 255
    # Guard against thin 1-2px gaps in an open/margin-touching balloon outline:
    # if the chosen component floods across 3+ edges of the balloon box, thicken
    # dark outlines slightly and re-seed from `seed_box` so margin paper stays out.
    touches = int(inside[0, :].any()) + int(inside[-1, :].any()) + int(inside[:, 0].any()) + int(inside[:, -1].any())
    if seed_box is not None and touches >= 3:
        sealed = cv2.erode(light, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        c2, l2, _ = _pick_component(sealed)
        if c2 > 0:
            cand = ((l2 == c2).astype(np.uint8)) * 255
            t2 = int(cand[0, :].any()) + int(cand[-1, :].any()) + int(cand[:, 0].any()) + int(cand[:, -1].any())
            if t2 < touches and int((cand > 0).sum()) >= 0.15 * int((inside > 0).sum()):
                inside = cv2.dilate(cand, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
                inside = cv2.bitwise_and(inside, light)

    # The letters are holes in that component. Filling them is unambiguous here:
    # the outline is outside the component, so it cannot be filled by accident.
    frame = np.zeros((h + 2, w + 2), np.uint8)
    frame[1:-1, 1:-1] = inside
    flooded = frame.copy()
    scratch = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(flooded, scratch, (0, 0), 255)
    inside = cv2.bitwise_or(inside, cv2.bitwise_not(flooded)[1:-1, 1:-1])

    if inset > 0 or min_inset:
        radius = max(1, min_inset, int(inset * min(w, h)))
        shape = cv2.MORPH_RECT if min_inset else cv2.MORPH_ELLIPSE
        kernel = cv2.getStructuringElement(shape, (2 * radius + 1, 2 * radius + 1))
        if min_inset:
            inside = cv2.erode(inside, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        else:
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
    cv2 = _cv2()
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
    box_area = float(max(1, w * h))
    for label, _votes in sorted(seen.items(), key=lambda item: -item[1]):
        bx, by, bw, bh = (int(stats[label, index]) for index in
                          (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                           cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        found = [wx + bx, wy + by, bw, bh]
        encloses = (found[0] <= x and found[1] <= y
                    and found[0] + found[2] >= x + w
                    and found[1] + found[3] >= y + h)
        if not (encloses and bw * bh <= cap):
            continue
        # Reject components that leaked into the surrounding panel background
        # and only stopped at the artificial search-window crop walls (when the
        # text box is large enough that the search window can enclose a balloon).
        crop_hits = (
            (bx == 0 and wx > 0)
            + (by == 0 and wy > 0)
            + (bx + bw == ww and wx + ww < width)
            + (by + bh == wh and wy + wh < height)
        )
        if crop_hits >= 2 and min(w, h) >= 36:
            continue
        # Reject leaked background components whose `balloon_interior` picks a
        # different lobe and barely covers the lettering box itself.
        interior = balloon_interior(
            page_rgb, found, polarity, page_size, inset=OUTLINE_INSET,
        )
        if float((interior[y:y + h, x:x + w] > 0).sum()) / box_area >= 0.35:
            return found
    return None


def _clip_colliding_balloons(
    regions: list[dict[str, Any]],
    derived_ids: set[str],
    page_rgb,
    page_size: tuple[int, int],
) -> None:
    """Separate derived balloons that merged across a twin-balloon neck.

    When two distinct text boxes live in connected balloons (e.g. a hand-split
    double balloon), `find_balloon` flood-fills across the neck and returns the
    same merged union for both, so `typeset` centres both texts on top of each
    other. Clip each derived balloon to its own side of the midpoint between
    the two text boxes; if clipping leaves the box uncovered, drop the derived
    balloon so `typeset` falls back to the region's own box.
    """
    originals = {r["id"]: r.get("balloon") for r in regions}
    for region in regions:
        if region["id"] not in derived_ids or not originals.get(region["id"]):
            continue
        ax, ay, aw, ah = region["bbox"]
        acx, acy = ax + aw / 2.0, ay + ah / 2.0
        bx, by, bw, bh = originals[region["id"]]
        x0, y0, x1, y1 = bx, by, bx + bw, by + bh
        clipped = False
        for other in regions:
            if other["id"] == region["id"]:
                continue
            if ir.bbox_iou(region["bbox"], other["bbox"]) >= 0.25:
                continue
            other_area = originals.get(other["id"]) or other["bbox"]
            if (ir.bbox_iou([x0, y0, x1 - x0, y1 - y0], other["bbox"]) == 0.0
                    and ir.bbox_iou([x0, y0, x1 - x0, y1 - y0], other_area) <= 0.15):
                continue
            ox, oy, ow, oh = other["bbox"]
            ocx, ocy = ox + ow / 2.0, oy + oh / 2.0
            if abs(ocx - acx) >= abs(ocy - acy):
                if ocx >= acx:
                    split = int((ax + aw + ox) / 2.0)
                    split = max(ax + aw, min(ox, split)) if ax + aw <= ox else int((acx + ocx) / 2.0)
                    if split < x1:
                        x1 = split
                        clipped = True
                else:
                    split = int((ox + ow + ax) / 2.0)
                    split = max(ox + ow, min(ax, split)) if ox + ow <= ax else int((acx + ocx) / 2.0)
                    if split > x0:
                        x0 = split
                        clipped = True
            else:
                if ocy >= acy:
                    split = int((ay + ah + oy) / 2.0)
                    split = max(ay + ah, min(oy, split)) if ay + ah <= oy else int((acy + ocy) / 2.0)
                    if split < y1:
                        y1 = split
                        clipped = True
                else:
                    split = int((oy + oh + ay) / 2.0)
                    split = max(oy + oh, min(ay, split)) if oy + oh <= ay else int((acy + ocy) / 2.0)
                    if split > y0:
                        y0 = split
                        clipped = True
        if not clipped:
            continue
        if x1 - x0 < max(12, aw) or y1 - y0 < max(12, ah):
            region["balloon"] = None
            continue
        candidate = [x0, y0, x1 - x0, y1 - y0]
        interior = balloon_interior(
            page_rgb, candidate, region.get("polarity", "light"),
            page_size, inset=OUTLINE_INSET,
        )
        cov = float((interior[ay:ay + ah, ax:ax + aw] > 0).sum()) / float(max(1, aw * ah))
        region["balloon"] = candidate if cov >= 0.35 else None


def _ink_mask(window, polarity: str):
    """Glyph pixels inside a crop, as 0/255."""
    cv2 = _cv2()
    gray = cv2.cvtColor(window, cv2.COLOR_RGB2GRAY) if window.ndim == 3 else window
    if polarity == "dark":
        gray = 255 - gray
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask


def _strip_perimeter_contours(mask, cv2, np):
    """Separate interior glyph ink from border-touching hair, frames, and outlines.

    `region_mask` already expands `region["bbox"]` outward by `pad`, so genuine
    glyphs sit inside the window while hair, panel frames, screentone corners,
    and balloon outlines cross the 1px outer perimeter. Returns
    `(cleaned_mask, forbidden_border_mask)` so regions without an enclosed
    balloon never paint solid white rectangles over artwork.
    """
    h, w = mask.shape[:2]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count < 2:
        return mask, np.zeros_like(mask)
    keep = np.zeros_like(mask)
    forbidden = np.zeros_like(mask)
    kept_any = False
    for idx in range(1, count):
        cx = int(stats[idx, cv2.CC_STAT_LEFT])
        cy = int(stats[idx, cv2.CC_STAT_TOP])
        cw = int(stats[idx, cv2.CC_STAT_WIDTH])
        ch = int(stats[idx, cv2.CC_STAT_HEIGHT])
        touches = cx == 0 or cy == 0 or (cx + cw) >= w or (cy + ch) >= h
        if touches:
            forbidden[labels == idx] = 255
        else:
            keep[labels == idx] = 255
            kept_any = True
    if not kept_any:
        # Safety fallback if a zero-pad tight box touches every glyph: strip only
        # large artwork contours (hair/frames/outlines), keep small glyphs.
        win_area = max(1, h * w)
        keep.fill(0)
        forbidden.fill(0)
        for idx in range(1, count):
            cw = int(stats[idx, cv2.CC_STAT_WIDTH])
            ch = int(stats[idx, cv2.CC_STAT_HEIGHT])
            area = int(stats[idx, cv2.CC_STAT_AREA])
            if area >= 0.08 * win_area or cw >= 0.35 * w or ch >= 0.35 * h:
                forbidden[labels == idx] = 255
            else:
                keep[labels == idx] = 255
    return keep, forbidden


def region_mask(
    page_rgb,
    region: dict[str, Any],
    page_size: tuple[int, int],
    *,
    grow: float = DEFAULT_GROW,
    pad: float = DEFAULT_PAD,
    solid_free: bool = False,
    full_balloon: bool = False,
):
    """``(mask, box)`` — an 8-bit mask and the page-space box it covers.

    ``solid_free`` covers a region that has **no balloon** — lettering drawn
    straight onto the artwork — as one filled area instead of the glyph shapes.
    ``full_balloon`` expands the ink search across the entire inset balloon
    interior for single-region balloons so no edge lettering survives cleaning.
    """
    cv2, np = _cv2(), _numpy()
    width, height = page_size
    smaller = min(width, height)

    box = ir.expand_bbox(region["bbox"], max(2.0, pad * smaller), width, height)
    balloon = region.get("balloon")
    if balloon and full_balloon:
        bx, by, bw, bh = ir.clamp_bbox(balloon, width, height)
        x0 = min(box[0], bx)
        y0 = min(box[1], by)
        x1 = max(box[0] + box[2], bx + bw)
        y1 = max(box[1] + box[3], by + bh)
        box = ir.clamp_bbox([x0, y0, x1 - x0, y1 - y0], width, height)

    x, y, w, h = box
    if w <= 0 or h <= 0:
        return np.zeros((1, 1), np.uint8), [x, y, 1, 1]

    if solid_free and not balloon:
        return np.full((h, w), 255, np.uint8), box

    polarity = region.get("polarity", "light")
    allowed = None
    if balloon:
        # Compute the safe inset balloon interior FIRST and neutralize pixels
        # outside it before Otsu thresholding so dark hair/screentone in the
        # corners of the balloon box cannot bias Otsu or leak into the mask.
        allowed = balloon_interior(
            page_rgb, balloon, polarity,
            page_size, inset=OUTLINE_INSET, min_inset=2 if full_balloon else 0,
            seed_box=region.get("bbox"),
        )
        allowed_win = allowed[y:y + h, x:x + w] > 0
        window = page_rgb[y:y + h, x:x + w].copy()
        paper_fill = 0 if polarity == "dark" else 255
        if allowed_win.any():
            window[~allowed_win] = paper_fill
    else:
        window = page_rgb[y:y + h, x:x + w]

    mask = _ink_mask(window, polarity)

    forbidden = None
    if not balloon and not region.get("erase") and (w * h) < 0.25 * (width * height):
        mask, forbidden = _strip_perimeter_contours(mask, cv2, np)

    radius = max(1, int(round(grow * smaller)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    mask = cv2.dilate(mask, kernel)
    # Close the gaps *between* letters as well, so the fill behind a line of
    # text is one continuous repair rather than a row of separate patches with
    # slivers of the old background surviving between them.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    if forbidden is not None and forbidden.any():
        # Protect border-touching hair/outline pixels + 1px safety rim.
        guard = cv2.dilate(forbidden, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(guard))

    if allowed is not None:
        mask = cv2.bitwise_and(mask, allowed[y:y + h, x:x + w])
        # When `full_balloon` expanded the search window across the whole
        # balloon to catch missed lettering, shrink `box` back to the tight
        # padded hull of the masked pixels so `clean` samples pure balloon paper
        # instead of outer corner hair/speedlines.
        if full_balloon and mask.any():
            ys, xs = np.nonzero(mask)
            margin = max(2, int(round(pad * smaller)))
            nx0 = max(0, int(xs.min()) - margin)
            ny0 = max(0, int(ys.min()) - margin)
            nx1 = min(w, int(xs.max()) + 1 + margin)
            ny1 = min(h, int(ys.max()) + 1 + margin)
            mask = mask[ny0:ny1, nx0:nx1].copy()
            box = [x + nx0, y + ny0, nx1 - nx0, ny1 - ny0]

    return mask, box


def _retire_assets(root: Path, page: dict[str, Any],
                   written: set[str]) -> list[str]:
    """Delete the mask files a PREVIOUS MASK RUN wrote and this one did not.

    A rebuild that leaves the previous run's files behind leaves authority
    behind with them: remove every region from a page and the union mask still
    said the cleaner could rewrite most of it.

    Scoped by OWNERSHIP, not by folder. Sweeping every name the run did not
    write took `masks/<page>/writable.png` with it — which `typeset` writes,
    and which the delivery certificate checks — so an ordinary re-mask made the
    page fail publication for a file nobody had touched. It would take a
    letterer's own notes out of that folder too.

    So each run records what it wrote in `page["mask_assets"]`, and the next
    one retires exactly the difference. A file this stage has never written is
    not this stage's to delete.
    """
    owned = [name for name in (page.get("mask_assets") or [])
             if isinstance(name, str)]
    folder = root / "masks" / page["id"]
    retired = []
    for name in owned:
        if name in written:
            continue
        child = folder / name
        if child.is_file():
            child.unlink()
            retired.append(f"{page['id']}/{name}")
    page["mask_assets"] = sorted(written)
    return retired

@ir.mutating
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
    # The effective sound-effect policy: an effect this chapter keeps is
    # artwork, and artwork is not the cleaner's to rewrite.
    policy = doc["meta"].get("sfx_policy", "keep")

    from PIL import Image

    written = 0
    derived = 0
    retired: list[str] = []
    per_page: list[dict[str, Any]] = []
    for page in doc["pages"]:
        if pages is not None and page["id"] not in pages:
            continue
        if not page.get("regions"):
            # A page with nothing on it still has to be REBUILT, not skipped.
            # Skipping left the previous run's union and region masks on disk,
            # so removing every region from a page left the cleaner authorised
            # over most of it — with nothing in the document to say why.
            empty = np.zeros((page["height"], page["width"]), np.uint8)
            relative = f"masks/{page['id']}/union.png"
            ir.write_bytes(root / relative,
                           _encode_png(Image.fromarray(empty, mode="L")))
            page["mask"] = relative
            page["mask_coverage"] = 0.0
            page["free_lettering_mask"] = "solid" if solid_free else "glyphs"
            page["mask_options"] = {"grow": grow, "pad": pad,
                                    "solid_free": bool(solid_free)}
            retired += _retire_assets(root, page, {"union.png"})
            # Everything downstream was derived from regions this page no
            # longer has.
            cleared = ir.restore_blank_page(page)
            per_page.append({"page": page["id"], "regions": 0,
                             "not_masked": 0, "coverage": 0.0,
                             "restored": cleared})
            continue

        written_names: set[str] = set()
        rgb = np.asarray(ir.load_image(root / page["image"]))
        size = (page["width"], page["height"])
        union = np.zeros((page["height"], page["width"]), np.uint8)

        skipped = 0
        editable: list[dict[str, Any]] = []
        derived_ids: set[str] = set()
        for region in page["regions"]:
            # Authority to change pixels comes from the decisions that stand
            # NOW. A region the reader dropped has no text in it, and one they
            # kept is text they asked to leave in the artwork — masking either
            # put artwork inside the area the cleaner is allowed to rewrite and
            # inside the denominator the preservation proof divides by.
            if not ir.may_be_edited(region, policy):
                region["mask"] = None
                region["mask_box"] = None
                skipped += 1
                continue
            # A box the reader drew, or a free-lettering detection reclassified
            # into a balloon kind, arrives with no balloon. Find it, so it is
            # masked and typeset like any other balloon.
            if not region.get("balloon") and region["kind"] in BALLOON_KINDS:
                region["balloon"] = find_balloon(
                    rgb, region["bbox"], region.get("polarity", "light"), size)
                if region["balloon"] is not None:
                    derived_ids.add(region["id"])
            editable.append(region)

        if derived_ids:
            _clip_colliding_balloons(editable, derived_ids, rgb, size)
            derived += sum(
                1 for r in editable if r["id"] in derived_ids and r.get("balloon")
            )

        def _balloon_shared(target: dict[str, Any]) -> bool:
            tb = target.get("balloon")
            if not tb:
                return False
            tx0, ty0, tw, th = tb
            tx1, ty1 = tx0 + tw, ty0 + th
            for other in editable:
                if other["id"] == target["id"]:
                    continue
                ob = other.get("bbox")
                if not ob:
                    continue
                ox0, oy0, ow, oh = ob
                if min(tx1, ox0 + ow) > max(tx0, ox0) and min(ty1, oy0 + oh) > max(ty0, oy0):
                    return True
            return False

        for region in editable:
            mask, box = region_mask(
                rgb, region, size, grow=grow, pad=pad, solid_free=solid_free,
                full_balloon=bool(region.get("balloon")) and not _balloon_shared(region),
            )
            relative = f"masks/{page['id']}/{region['id']}.png"
            ir.write_bytes(
                root / relative,
                _encode_png(Image.fromarray(mask, mode="L")),
            )
            region["mask"] = relative
            region["mask_box"] = box
            written_names.add(Path(relative).name)
            x, y, w, h = box
            union[y:y + h, x:x + w] = np.maximum(union[y:y + h, x:x + w], mask)
            written += 1

        relative = f"masks/{page['id']}/union.png"
        ir.write_bytes(root / relative, _encode_png(Image.fromarray(union, mode="L")))
        page["mask"] = relative
        written_names.add("union.png")
        retired += _retire_assets(root, page, written_names)
        coverage = float((union > 0).sum()) / float(page["width"] * page["height"])
        page["mask_coverage"] = round(coverage, 5)
        # Written HERE, by the builder, for THIS page. The mode was recorded
        # once for the whole document at the end of the run, so masking page A
        # solid and then page B with glyphs left one flag describing neither —
        # and `clean` read it and gave page A the cleaners a solid patch must
        # never reach. `clean` used to write this back afterwards, which is a
        # guess about what the masks on disk are; the builder knows.
        page["free_lettering_mask"] = "solid" if solid_free else "glyphs"
        page["mask_options"] = {"grow": grow, "pad": pad,
                                "solid_free": bool(solid_free)}
        per_page.append({
            "page": page["id"],
            "regions": len(page["regions"]),
            "not_masked": skipped,
            "coverage": page["mask_coverage"],
        })

    # The document-wide flag stays for a page that has never been masked and
    # for every older document; the per-page value above is what `clean` reads
    # when it is there.
    if per_page:
        doc["meta"]["free_lettering_mask"] = "solid" if solid_free else "glyphs"
    stages.stamp_stage(doc, "masks",
                       {"written": written, "balloons_derived": derived,
                        "retired": len(retired)},
                       options={"grow": grow, "pad": pad,
                                "solid_free": solid_free}, pages=pages)
    ir.save_doc(doc, doc_path)

    # A mask covering a third of the page is not lettering; something matched
    # the artwork. Cleaning that would destroy the drawing, so it is surfaced
    # here rather than discovered in the finished file.
    excessive = [entry["page"] for entry in per_page if entry["coverage"] > 0.28]
    return {
        "document": str(doc_path),
        "masks_written": written,
        "balloons_derived": derived,
        # Files this rebuild removed because nothing writes them any more. A
        # rebuild that leaves them behind leaves authority behind with them.
        "retired": len(retired),
        "retired_assets": retired[:20],
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

@ir.cli
def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic mask",
        description="Build the pixel mask for every detected text region.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default=None)
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
        pages=ir.parse_pages(args.pages),
        solid_free=args.free_lettering == "solid",
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
