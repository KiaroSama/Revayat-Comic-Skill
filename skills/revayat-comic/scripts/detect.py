"""Find the panels, the balloons and the lettering on a page.

The detector is deliberately classical. A vision model can describe a page far
better than this code can, but it cannot return a box that is accurate to the
pixel — and a box that is wrong by four pixels leaves a rim of Japanese around
every cleaned balloon. So geometry is measured here, and judgement is left to
the reader looking at the crops (see ``crops.py``).

Three things are found, in descending order of how reliable they are:

1. **Balloons.** A speech balloon is a light region enclosed by its own outline,
   so it survives as one connected component while the page background stays a
   different one. This is the strong case, and most dialogue is in it.
2. **Panels.** A recursive cut along the gutters. Panels matter only for reading
   order, so being approximately right is enough.
3. **Free lettering** — sound effects, signs, captions drawn over artwork. This
   is the weak case and it is reported as such: every region it returns carries
   low confidence, and the reader is shown the crop and asked to drop it if
   there is no text there.

**What the reader cannot do, and it matters**: the worksheet can drop a region,
re-label it and name its speaker, but it cannot **add** a balloon the detector
missed, or **split** one region that covers two. On a real chapter both happen
several times per volume — adjacent balloons merge, and a panel is sometimes
returned as one balloon because a panel interior is also a light region inside
an outline. Text in those balloons is lost, silently, and only a reader looking
at `overview.png` will see it. Do not read a full worksheet as a full page.

Both polarities are searched: white balloons with black text, and black
balloons with white text, which are common in flashbacks and night scenes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import pageir as ir
import stages

# --- Tuning knobs -----------------------------------------------------------
# Comics vary more than any threshold can absorb: a 900-pixel web scan and a
# 4000-pixel tankobon scan disagree about what "small" means. Everything below
# is a fraction of the page, and every one of them is exposed on the command
# line, because the right value is a property of the book, not of this file.

DEFAULTS = {
    # A balloon, as a share of page area. The ceiling is low on purpose: a panel
    # interior is also a light region inside an outline, and on a sparse page it
    # is indistinguishable from a very large balloon except by size.
    "balloon_min_area": 0.0006,
    "balloon_max_area": 0.13,
    # Smallest side of a balloon, as a share of the page's smaller dimension.
    # Without a floor here, the white gaps *between* letters qualify as tiny
    # dark balloons, and every line of text sprouts three of them.
    "balloon_min_side": 0.05,
    # How blobby a balloon is: component area over its bounding box.
    "balloon_min_solidity": 0.42,
    # How much ink a balloon's interior holds. Below this it is empty artwork;
    # above it, it is a dark drawing rather than lettering.
    "ink_min": 0.015,
    "ink_max": 0.55,
    # A glyph, as a share of the page's smaller dimension.
    "glyph_min": 0.004,
    "glyph_max": 0.22,
    # Gutter detection for panels: a cut line must be this clean and this wide.
    "gutter_max_ink": 0.008,
    "gutter_min_span": 0.012,
    "panel_min_area": 0.02,
    # Smallest piece of free lettering worth reporting, as a share of the page's
    # smaller side. Below it, the matches are panel corners and border joints.
    "sfx_min_side": 0.035,
    # What separates a word from a piece of drawing. Measured on a real volume
    # (Sekirei v01, Yen Press): every one of these three is needed, and none of
    # them is about how the marks *look* — only about how a set of them relates.
    #
    # A word has several marks. Two eyes, or a button and its shadow, do not.
    # Three and not more, because a real sound effect is often three characters
    # (ドドド) and the size test below does the discriminating anyway: measured
    # over four real pages, moving this from 5 to 3 admitted one extra false
    # positive in total and made short effects reachable at all.
    "sfx_min_glyphs": 3,
    # Letters in one piece of lettering are near enough the same size; artwork
    # is not. This is the strongest of the three, and the only one that does not
    # care about orientation or how many lines the block runs to.
    "sfx_size_uniformity": 0.80,
    # How far the marks stray across their own line, in multiples of a mark.
    # Screentone and hair pass the size test and fail here.
    "sfx_max_spread": 1.5,
}


def _cv2():
    ir.require("cv2", "opencv-python-headless", "detecting balloons and lettering")
    import cv2

    return cv2


def _numpy():
    ir.require("numpy", "numpy", "image measurement")
    import numpy

    return numpy


# --------------------------------------------------------------------------- #
# Panels
# --------------------------------------------------------------------------- #

def _cut_axis(ink, axis: int, options: dict[str, float], length: int) -> list[tuple[int, int]]:
    """Runs along `axis` that are empty enough to be a gutter."""
    profile = ink.mean(axis=axis) / 255.0
    empty = profile <= options["gutter_max_ink"]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(empty):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(empty)))
    span = max(2, int(options["gutter_min_span"] * length))
    return [run for run in runs if run[1] - run[0] >= span]


def _split(ink, origin: tuple[int, int], options: dict[str, float],
           page_area: float, depth: int = 0) -> list[list[int]]:
    """Recursive gutter cut. Returns page-space boxes."""
    height, width = ink.shape[:2]
    x0, y0 = origin
    if depth >= 6 or height < 8 or width < 8:
        return [[x0, y0, width, height]]

    # Horizontal gutters split rows; vertical gutters split columns. Take
    # whichever gives the cleaner separation first, then recurse into each part.
    for axis, length in ((1, height), (0, width)):
        runs = _cut_axis(ink, axis, options, length)
        interior = [run for run in runs if run[0] > 0 and run[1] < length]
        if not interior:
            continue
        pieces: list[list[int]] = []
        cursor = 0
        for start, end in interior + [(length, length)]:
            if start - cursor < 8:
                cursor = end
                continue
            if axis == 1:
                block = ink[cursor:start, :]
                pieces += _split(block, (x0, y0 + cursor), options, page_area, depth + 1)
            else:
                block = ink[:, cursor:start]
                pieces += _split(block, (x0 + cursor, y0), options, page_area, depth + 1)
            cursor = end
        if pieces:
            return pieces
    return [[x0, y0, width, height]]


def find_panels(gray, options: dict[str, float]) -> list[list[int]]:
    cv2, np = _cv2(), _numpy()
    height, width = gray.shape[:2]
    page_area = float(height * width)
    # Ink is anything far from the page's own paper tone, so a grey or black
    # background page is measured the same way a white one is.
    paper = float(np.median(gray))
    ink = (np.abs(gray.astype(np.int16) - paper) > 48).astype(np.uint8) * 255
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    boxes = _split(ink, (0, 0), options, page_area)
    minimum = options["panel_min_area"] * page_area
    keep = [box for box in boxes if box[2] * box[3] >= minimum]
    # One box covering the whole page is not a panel decomposition; it is the
    # detector saying it found no gutters, and reading order should fall back to
    # plain geometry rather than trust a single fake panel.
    if len(keep) <= 1:
        return []
    return keep


# --------------------------------------------------------------------------- #
# Balloons
# --------------------------------------------------------------------------- #

def _components(mask, np):
    cv2 = _cv2()
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    return count, labels, stats


def _fill_lettering(mask, np, max_side: float):
    """Absorb the letters into the balloon interior, and nothing else.

    Two obvious approaches are both wrong, and both were measured before this
    one was written:

    * A morphological close dilates the white first, which jumps a four-pixel
      balloon outline and welds the interior to the page background. Every white
      balloon then vanishes into one page-sized component.
    * Filling every enclosed hole fills the *outline itself*: a balloon's border
      is a closed ring of ink that the page border cannot reach around, so it
      qualifies as a hole, and filling it has the same effect as the close.

    What separates the two is shape, not size. A letter is a solid blob; a
    balloon outline is a thin ring enclosing a large empty box, so its area is a
    few percent of the box it occupies. Solidity tells them apart at any scale.
    """
    cv2 = _cv2()
    height, width = mask.shape
    # A one-pixel zero frame guarantees the flood has somewhere to start even
    # when the page's own corner is white.
    canvas = np.zeros((height + 2, width + 2), np.uint8)
    canvas[1:-1, 1:-1] = mask
    flooded = canvas.copy()
    scratch = np.zeros((height + 4, width + 4), np.uint8)
    cv2.floodFill(flooded, scratch, (0, 0), 255)
    holes = cv2.bitwise_not(flooded)[1:-1, 1:-1]

    count, labels, stats = _components(holes, np)

    # Decide per label, then paint in **one** pass. Painting inside the loop
    # (`keep[labels == label] = 255`) compares the whole page once per hole, and
    # a page of screentone has thousands of holes: measured at 1897x2702, this
    # single function was 419 s of a 420 s page, and a 191-page volume would
    # have taken most of a day. The vectorised form is the same output.
    sides = np.maximum(stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT])
    boxes = np.maximum(1, stats[:, cv2.CC_STAT_WIDTH] * stats[:, cv2.CC_STAT_HEIGHT])
    solidity = stats[:, cv2.CC_STAT_AREA] / boxes.astype(np.float64)
    allowed = (sides <= max_side) & (solidity >= 0.30)
    allowed[0] = False                      # label 0 is the background
    if count < 2 or not allowed[1:count].any():
        return mask
    keep = np.where(allowed[labels], np.uint8(255), np.uint8(0))
    return cv2.bitwise_or(mask, keep)


def _balloon_candidates(gray, options: dict[str, float], invert: bool) -> list[dict[str, Any]]:
    cv2, np = _cv2(), _numpy()
    height, width = gray.shape[:2]
    page_area = float(height * width)

    source = 255 - gray if invert else gray
    _, light = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Absorb the lettering into the interior, so a balloon crossed by a long
    # vertical line of kanji is one component rather than two.
    solid = _fill_lettering(light, np, options["glyph_max"] * min(height, width))

    count, labels, stats = _components(solid, np)
    minimum = options["balloon_min_area"] * page_area
    maximum = options["balloon_max_area"] * page_area

    floor = options["balloon_min_side"] * min(height, width)

    found: list[dict[str, Any]] = []
    for label in range(1, count):
        x, y, w, h, area = (int(stats[label][index]) for index in range(5))
        if area < minimum or area > maximum:
            continue
        if min(w, h) < max(12.0, floor):
            continue
        if area / float(w * h) < options["balloon_min_solidity"]:
            continue
        # The page background is the component that runs to the edges. A real
        # balloon can touch one edge; touching two opposite ones means it is the
        # paper, not a balloon.
        touches = (x <= 1) + (y <= 1) + (x + w >= width - 1) + (y + h >= height - 1)
        if touches >= 2:
            continue

        interior = (labels[y:y + h, x:x + w] == label)
        window = source[y:y + h, x:x + w]
        # Ink *inside the balloon only* — measuring the whole bounding box lets
        # artwork in the corners outside a round balloon count as lettering.
        inked = float((window[interior] < 128).sum())
        share = inked / max(1.0, float(interior.sum()))
        if not (options["ink_min"] <= share <= options["ink_max"]):
            continue

        found.append({
            "bbox": [x, y, w, h],
            "interior_area": int(interior.sum()),
            "ink_share": round(share, 4),
            "polarity": "dark" if invert else "light",
            "solidity": round(area / float(w * h), 3),
        })
    return found


def _text_inside(gray, balloon: dict[str, Any], options: dict[str, float]) -> list[int] | None:
    """The tight box around the lettering in a balloon, in page coordinates."""
    cv2, np = _cv2(), _numpy()
    x, y, w, h = balloon["bbox"]
    window = gray[y:y + h, x:x + w]
    if balloon["polarity"] == "dark":
        window = 255 - window
    _, dark = cv2.threshold(window, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Drop the outline: it is the ring of ink hugging the balloon border, and
    # including it makes the text box the balloon box.
    border = max(1, int(0.05 * min(w, h)))
    dark[:border, :] = 0
    dark[-border:, :] = 0
    dark[:, :border] = 0
    dark[:, -border:] = 0

    count, labels, stats = _components(dark, np)
    smaller = min(gray.shape[:2])
    low = options["glyph_min"] * smaller
    high = options["glyph_max"] * smaller

    keep = [
        stats[label][:4] for label in range(1, count)
        if low <= max(stats[label][2], stats[label][3]) <= high
        and stats[label][4] >= 4
    ]
    if not keep:
        return None
    x0 = min(int(box[0]) for box in keep)
    y0 = min(int(box[1]) for box in keep)
    x1 = max(int(box[0]) + int(box[2]) for box in keep)
    y1 = max(int(box[1]) + int(box[3]) for box in keep)
    if x1 <= x0 or y1 <= y0:
        return None
    return [x + x0, y + y0, x1 - x0, y1 - y0]


# --------------------------------------------------------------------------- #
# Free lettering
# --------------------------------------------------------------------------- #

def _looks_like_lettering(group: list[list[int]], options: dict[str, float]) -> bool:
    """Is this cluster of marks a piece of writing, or a piece of drawing?

    Nothing here looks at a single mark, because a single mark cannot tell you:
    an eye and a letter O are the same blob. What separates writing is how a
    *set* of marks relates — several of them, near enough one size, sitting
    along a line. Measured against a real volume where the alternative was 22
    clusters per page, of which two were text.

    The size test does the most work and is the one to trust: letters cut from
    one font are within a factor of two of each other, while hair, screentone
    and cloth folds produce marks of every size at once. It is also the only
    test here that does not care about orientation, so vertical Japanese and a
    four-line English caption pass it equally.

    `ponytail: the spread test measures one block, so lettering running past
    roughly five lines reads as scattered and is dropped. Free lettering that
    long is rare — it would be in a box, and boxes are found as balloons — and
    the reader is shown the page anyway. Split the block by line if that stops
    being true.`
    """
    group = _absorb_satellites(group)
    count = len(group)
    if count < options["sfx_min_glyphs"]:
        return False

    sizes = sorted(max(box[2], box[3]) for box in group)
    median = sizes[count // 2] if count % 2 else (sizes[count // 2 - 1] + sizes[count // 2]) / 2
    median = max(1.0, float(median))
    alike = sum(1 for size in sizes if 0.55 * median <= size <= 1.8 * median)
    if alike / count < options["sfx_size_uniformity"]:
        return False

    # Spread across the line, from the smaller eigenvalue of the centres'
    # covariance — orientation-free, so it reads horizontal and vertical
    # lettering the same way.
    xs = [box[0] + box[2] / 2 for box in group]
    ys = [box[1] + box[3] / 2 for box in group]
    mx, my = sum(xs) / count, sum(ys) / count
    sxx = sum((x - mx) ** 2 for x in xs) / count
    syy = sum((y - my) ** 2 for y in ys) / count
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / count
    half_trace = (sxx + syy) / 2
    gap = max(0.0, half_trace * half_trace - (sxx * syy - sxy * sxy)) ** 0.5
    across = max(0.0, half_trace - gap) ** 0.5
    return across / median <= options["sfx_max_spread"]


def _absorb_satellites(group: Sequence[Sequence[int]]) -> list[list[int]]:
    """Fold a small mark into the larger one it belongs to.

    A connected component is not a character. In Japanese a single one is
    routinely several disconnected strokes of very different sizes: ド is ト
    plus two tiny dakuten, ン is two strokes. Measured on a real katakana effect
    at 110 px, ドカン came out as six components — three around 85 px and three
    around 20 px — so the size-uniformity test scored 3/6 and rejected it. The
    same shape appears in Latin: an i and its tittle, a j, an exclamation mark.

    So before asking whether the marks are alike, marks far below the median
    that sit right against a bigger one are merged into it. The threshold is the
    *same* 0.55 the size test uses as its lower bound, on purpose: this absorbs
    exactly the marks that test would have rejected, and nothing else.

    Merging can only lower the count, never raise it, so it can make the glyph
    minimum harder to reach but never invents a cluster that was not there.
    """
    if len(group) < 2:
        return [list(box) for box in group]

    sizes = sorted(max(box[2], box[3]) for box in group)
    middle = len(sizes) // 2
    median = float(sizes[middle] if len(sizes) % 2
                   else (sizes[middle - 1] + sizes[middle]) / 2)
    if median <= 0:
        return [list(box) for box in group]

    small = [box for box in group if max(box[2], box[3]) < 0.55 * median]
    large = [list(box) for box in group if max(box[2], box[3]) >= 0.55 * median]
    if not small or not large:
        return [list(box) for box in group]

    kept: list[list[int]] = []
    for box in small:
        cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
        best, best_gap = None, None
        for host in large:
            reach = 0.75 * max(host[2], host[3])
            # Distance from the small mark's centre to the host's box, zero
            # when it is inside. A diacritic sits against its base character;
            # a speck of screentone half a glyph away does not.
            dx = max(host[0] - cx, 0.0, cx - (host[0] + host[2]))
            dy = max(host[1] - cy, 0.0, cy - (host[1] + host[3]))
            gap = (dx * dx + dy * dy) ** 0.5
            if gap <= reach and (best_gap is None or gap < best_gap):
                best, best_gap = host, gap
        if best is None:
            kept.append(list(box))
            continue
        x0 = min(best[0], box[0])
        y0 = min(best[1], box[1])
        x1 = max(best[0] + best[2], box[0] + box[2])
        y1 = max(best[1] + best[3], box[1] + box[3])
        best[0], best[1], best[2], best[3] = x0, y0, x1 - x0, y1 - y0
    return large + kept


def _free_lettering(gray, taken: Sequence[Sequence[int]],
                    options: dict[str, float]) -> list[dict[str, Any]]:
    """Clusters of glyph-sized shapes that are not inside any balloon.

    This is the honest weak spot. Sound effects are drawn, not typeset: they
    lean, stretch, outline themselves and merge into the artwork. What follows
    finds the obvious ones and is wrong about the rest, which is why every
    region it returns is marked low confidence and shown to a reader.
    """
    cv2, np = _cv2(), _numpy()
    height, width = gray.shape[:2]
    smaller = min(height, width)

    blocked = np.zeros((height, width), np.uint8)
    for box in taken:
        x, y, w, h = (int(value) for value in box)
        blocked[max(0, y):y + h, max(0, x):x + w] = 255

    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    results: list[dict[str, Any]] = []
    low = options["glyph_min"] * smaller
    high = options["glyph_max"] * smaller

    for mask, polarity in ((dark, "light"), (bright, "dark")):
        working = cv2.bitwise_and(mask, cv2.bitwise_not(blocked))
        count, labels, stats = _components(working, np)
        seeds = []
        for label in range(1, count):
            x, y, w, h, area = (int(stats[label][index]) for index in range(5))
            if not (low <= max(w, h) <= high):
                continue
            if area / float(max(1, w * h)) < 0.12:
                continue
            seeds.append([x, y, w, h])
        if len(seeds) < 2:
            continue

        for group in _cluster(seeds):
            if not _looks_like_lettering(group, options):
                continue
            box = _hull(group, width, height)
            if max(box[2], box[3]) < options["sfx_min_side"] * smaller:
                continue
            if any(ir.bbox_iou(box, other) > 0.25 for other in taken):
                continue
            results.append({
                "bbox": box,
                "glyphs": len(group),
                "polarity": polarity,
            })
    return results


#: How far apart two marks can be and still belong to the same piece of
#: lettering, as a multiple of the larger one. Letters in a word sit closer
#: together than a word sits to the artwork around it.
CLUSTER_REACH = 1.1

#: Clustering is quadratic in the number of marks. A page of dense screentone
#: can produce thousands, so the largest ones are kept and the rest ignored —
#: lettering is not the smallest thing on the page.
MAX_SEEDS = 400


def _gap(a, b) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    dx = max(0, max(ax0, bx0) - min(ax0 + aw, bx0 + bw))
    dy = max(0, max(ay0, by0) - min(ay0 + ah, by0 + bh))
    return (dx * dx + dy * dy) ** 0.5


def _cluster(seeds: list[list[int]]) -> list[list[list[int]]]:
    """Group marks that are close relative to their own size.

    A single dilation cannot do this. Its reach is one number for the whole
    page, so a value that groups small dialogue type leaves a large sound
    effect as separate blobs and drops it silently, while a value that catches
    the sound effect welds every line of dialogue into one block. Comparing each
    pair against *their* size has no such conflict.
    """
    if len(seeds) > MAX_SEEDS:
        seeds = sorted(seeds, key=lambda box: -box[2] * box[3])[:MAX_SEEDS]

    parent = list(range(len(seeds)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(seeds)):
        for j in range(i + 1, len(seeds)):
            scale = max(seeds[i][2], seeds[i][3], seeds[j][2], seeds[j][3])
            if _gap(seeds[i], seeds[j]) <= CLUSTER_REACH * scale:
                parent[find(i)] = find(j)

    groups: dict[int, list[list[int]]] = {}
    for index, box in enumerate(seeds):
        groups.setdefault(find(index), []).append(box)
    return list(groups.values())


def _hull(group: list[list[int]], width: int, height: int) -> list[int]:
    x0 = min(box[0] for box in group)
    y0 = min(box[1] for box in group)
    x1 = max(box[0] + box[2] for box in group)
    y1 = max(box[1] + box[3] for box in group)
    return ir.clamp_bbox([x0, y0, x1 - x0, y1 - y0], width, height)


# --------------------------------------------------------------------------- #
# Page driver
# --------------------------------------------------------------------------- #

def detect_page(
    image_path: str | Path,
    *,
    options: dict[str, float] | None = None,
    find_sfx: bool = True,
) -> dict[str, Any]:
    cv2, np = _cv2(), _numpy()
    options = {**DEFAULTS, **(options or {})}

    rgb = np.asarray(ir.load_image(image_path))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape[:2]

    panels = find_panels(gray, options)

    balloons: list[dict[str, Any]] = []
    for invert in (False, True):
        balloons.extend(_balloon_candidates(gray, options, invert))
    # A light and a dark pass can both claim the same balloon. Keep the one that
    # is more solid; it is the polarity that actually matches the artwork.
    balloons.sort(key=lambda item: (-item["solidity"], -item["interior_area"]))
    unique: list[dict[str, Any]] = []
    for candidate in balloons:
        box = candidate["bbox"]
        # A panel interior is a light region inside an outline too. When a
        # candidate is essentially the panel, it is the panel.
        if any(ir.bbox_iou(box, panel) > 0.65 for panel in panels):
            continue
        if any(ir.bbox_iou(box, kept["bbox"]) > 0.35 for kept in unique):
            continue
        # A balloon inside another balloon is a hole in its lettering, not a
        # second balloon.
        if any(ir.bbox_contains(kept["bbox"], box, slack=0.9) for kept in unique):
            continue
        unique.append(candidate)

    regions: list[dict[str, Any]] = []
    for balloon in unique:
        text = _text_inside(gray, balloon, options)
        if text is None:
            continue
        # A vertical Japanese line is much taller than it is wide. Getting this
        # right decides whether the crop is rotated before a reader sees it.
        orientation = "vertical" if text[3] > 1.6 * text[2] else "horizontal"
        regions.append({
            "bbox": text,
            "balloon": balloon["bbox"],
            "kind": "speech",
            "orientation": orientation,
            "confidence": 0.80,
            "detector": "balloon",
            "polarity": balloon["polarity"],
        })

    if find_sfx:
        taken = [region["balloon"] for region in regions]
        for free in _free_lettering(gray, taken, options):
            box = free["bbox"]
            regions.append({
                "bbox": box,
                "balloon": None,
                "kind": "sfx",
                "orientation": "vertical" if box[3] > 1.6 * box[2] else "horizontal",
                # Deliberately below any sensible review threshold. Free
                # lettering is a guess, and the skill treats it as one.
                "confidence": 0.35,
                "detector": "free",
                "polarity": free["polarity"],
            })

    return {"regions": regions, "panels": panels, "size": [width, height]}


def detect_document(
    doc_path: str | Path,
    *,
    options: dict[str, float] | None = None,
    find_sfx: bool = True,
    pages: Sequence[str] | None = None,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    direction = doc["meta"].get("reading_direction", "rtl")

    totals = {"regions": 0, "speech": 0, "sfx": 0, "panels": 0}
    per_page: list[dict[str, Any]] = []

    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        # A page whose regions were reviewed keeps them: re-detecting would
        # renumber the ids the worksheet already refers to.
        if any(region.get("locked") for region in page.get("regions", [])):
            per_page.append({"page": page["id"], "skipped": "locked"})
            continue

        image = ir.resolve(doc_path, page["image"])
        found = detect_page(image, options=options, find_sfx=find_sfx)

        page["panels"] = [
            {"id": f"{page['id']}n{index + 1:02d}", "bbox": box}
            for index, box in enumerate(found["panels"])
        ]
        page["regions"] = []
        for ordinal, raw in enumerate(found["regions"], start=1):
            region = ir.new_region(
                ir.region_id_for(page, ordinal),
                raw["bbox"],
                kind=raw["kind"],
                orientation=raw["orientation"],
                detector=raw["detector"],
                confidence=raw["confidence"],
            )
            region["balloon"] = raw["balloon"]
            region["polarity"] = raw["polarity"]
            for panel in page["panels"]:
                if ir.bbox_contains(panel["bbox"], region["bbox"], slack=0.6):
                    region["panel"] = panel["id"]
                    break
            page["regions"].append(region)

        ir.assign_reading_order(page, direction)
        totals["regions"] += len(page["regions"])
        totals["speech"] += sum(1 for r in page["regions"] if r["kind"] == "speech")
        totals["sfx"] += sum(1 for r in page["regions"] if r["kind"] == "sfx")
        totals["panels"] += len(page["panels"])
        per_page.append({
            "page": page["id"],
            "regions": len(page["regions"]),
            "panels": len(page["panels"]),
        })

    stages.stamp_stage(doc, "detect", {"totals": totals})
    ir.save_doc(doc, doc_path)

    empty = [entry["page"] for entry in per_page if entry.get("regions") == 0]
    return {
        "document": str(doc_path),
        "totals": totals,
        "pages": per_page,
        "pages_without_text": empty,
        "warning": (
            f"{len(empty)} page(s) came back with no text at all. A splash page "
            "genuinely has none; more than a couple means the thresholds do not "
            "fit this book — see references/detection.md."
        ) if len(empty) > max(1, len(per_page) // 5) else None,
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic detect",
        description="Find panels, balloons and lettering.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default="", help="comma-separated page ids")
    parser.add_argument("--no-sfx", action="store_true",
                        help="skip free lettering; balloons only")
    for name, value in DEFAULTS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=float, default=None,
                            help=f"default {value}")
    args = parser.parse_args(argv)

    options = {
        name: getattr(args, name)
        for name in DEFAULTS
        if getattr(args, name, None) is not None
    }
    report = detect_document(
        args.doc,
        options=options,
        find_sfx=not args.no_sfx,
        pages=[p for p in args.pages.split(",") if p] or None,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
