"""Reference kernels for grayscale comic-page geometry."""

from math import isfinite
from statistics import median

_MAX_INT = 2**63 - 1


def _integer(value, minimum, maximum=_MAX_INT):
    return type(value) is int and minimum <= value <= maximum


def _image(data, width, height):
    if not _integer(width, 1) or not _integer(height, 1):
        raise ValueError("image dimensions must be positive integers")
    if not isinstance(data, bytes) or len(data) != width * height:
        raise ValueError("image must be bytes of length width * height")


def _ratio(value, *, positive=False):
    return (
        type(value) in (int, float)
        and 0 <= value <= 1
        and (not positive or value > 0)
        and isfinite(value)
    )


def _rect(box, minimum=1):
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(
            _integer(v, lower)
            for v, lower in zip(box, (0, 0, minimum, minimum), strict=True)
        )
        and box[0] + box[2] <= _MAX_INT
        and box[1] + box[3] <= _MAX_INT
    )


def find_panel_gutters(
    gray: bytes, width: int, height: int, bg_luma: int, min_gutter: int, margin: int
) -> list[list[int]]:
    """Trim each outer edge, then cut the widest valid horizontal or vertical gutter."""
    _image(gray, width, height)
    if not _integer(bg_luma, 0, 255):
        raise ValueError("background luma must be in 0..255")
    if not _integer(min_gutter, 1) or not _integer(margin, 0):
        raise ValueError("minimum gutter must be positive and margin nonnegative")

    def trim(start, end, values):
        def blank(line):
            pixels = list(values(line))
            return sum(p >= bg_luma for p in pixels) * 100 >= len(pixels) * 96

        left, right = start, end
        while left < min(right, start + margin) and blank(left):
            left += 1
        while right > max(left, end - margin) and blank(right - 1):
            right -= 1
        return left, right

    top, bottom = trim(0, height, lambda y: gray[y * width : (y + 1) * width])
    if top == bottom:
        return []
    left, right = trim(
        0, width, lambda x: (gray[y * width + x] for y in range(top, bottom))
    )
    minimum = max(min_gutter * 3, 24)
    panels = []

    def widest(start, end, blank):
        best = None
        run = start
        for i in range(start, end + 1):
            if i < end and blank(i):
                continue
            if run >= start + minimum and minimum <= end - i and i - run >= min_gutter:
                if best is None or i - run > best[1] - best[0]:
                    best = (run, i)
            run = i + 1
        return best

    def split(x0, y0, x1, y1, depth):
        w, h = x1 - x0, y1 - y0
        if depth < 8 and w >= minimum and h >= minimum:
            if h >= 2 * minimum + min_gutter:
                band = widest(
                    y0,
                    y1,
                    lambda y: all(
                        p >= bg_luma for p in gray[y * width + x0 : y * width + x1]
                    ),
                )
                if band is not None:
                    split(x0, y0, x1, band[0], depth + 1)
                    split(x0, band[1], x1, y1, depth + 1)
                    return
            if w >= 2 * minimum + min_gutter:
                band = widest(
                    x0,
                    x1,
                    lambda x: all(
                        gray[y * width + x] >= bg_luma for y in range(y0, y1)
                    ),
                )
                if band is not None:
                    split(x0, y0, band[0], y1, depth + 1)
                    split(band[1], y0, x1, y1, depth + 1)
                    return
        panels.append([x0, y0, w, h])

    if right - left >= minimum and bottom - top >= minimum:
        split(left, top, right, bottom, 0)
    return panels


def _neighbors(x, y, width, height, diagonal):
    for ny in range(max(0, y - 1), min(height, y + 2)):
        for nx in range(max(0, x - 1), min(width, x + 2)):
            if (nx != x or ny != y) and (diagonal or nx == x or ny == y):
                yield ny * width + nx


def _components(data, width, height, threshold, diagonal):
    seen = bytearray(len(data))
    for seed, value in enumerate(data):
        if value < threshold or seen[seed]:
            continue
        queue = [seed]
        seen[seed] = 1
        y0, x0 = divmod(seed, width)
        x1, y1 = x0, y0
        for index in queue:
            y, x = divmod(index, width)
            x0, y0 = min(x0, x), min(y0, y)
            x1, y1 = max(x1, x), max(y1, y)
            for neighbor in _neighbors(x, y, width, height, diagonal):
                if not seen[neighbor] and data[neighbor] >= threshold:
                    queue.append(neighbor)
                    seen[neighbor] = 1
        yield [x0, y0, x1 - x0 + 1, y1 - y0 + 1, len(queue)], queue


def connected_components_boxes(
    mask: bytes, width: int, height: int, min_area: int, max_area: int
) -> list[list[int]]:
    """Return the area and bounds of each qualifying 8-connected foreground region."""
    _image(mask, width, height)
    if not _integer(min_area, 1) or not _integer(max_area, min_area):
        raise ValueError("component area bounds must be positive and ordered")
    boxes = [
        box
        for box, _ in _components(mask, width, height, 1, True)
        if min_area <= box[4] <= max_area
    ]
    return sorted(boxes, key=lambda b: (b[1], -b[0], b[0], b[3], b[2]))


def detect_speech_balloons(
    gray: bytes,
    width: int,
    height: int,
    white_thresh: int,
    min_area: int,
    max_area_ratio: float,
    min_fill_ratio: float,
) -> list[list[int]]:
    """Find 4-connected bright regions bounded by dark pixels in their one-pixel ring."""
    _image(gray, width, height)
    if not _integer(white_thresh, 0, 255):
        raise ValueError("white threshold must be in 0..255")
    if (
        not _integer(min_area, 1)
        or not _ratio(max_area_ratio, positive=True)
        or not _ratio(min_fill_ratio)
    ):
        raise ValueError("balloon area must be positive and ratios in range")
    boxes = []
    for box, pixels in _components(gray, width, height, white_thresh, False):
        x, y, w, h, area = box
        borders = (x == 0) + (y == 0) + (x + w == width) + (y + h == height)
        if (
            borders >= 3
            or not min_area <= area <= max_area_ratio * len(gray)
            or area / (w * h) < min_fill_ratio
        ):
            continue
        ring = set()
        for index in pixels:
            py, px = divmod(index, width)
            ring.update(_neighbors(px, py, width, height, True))
        ring.difference_update(pixels)
        dark = sum(gray[i] < white_thresh - 25 for i in ring)
        if ring and 20 * dark >= 9 * len(ring):
            boxes.append(box)
    return boxes


def _groups(boxes, linked):
    parents = list(range(len(boxes)))
    sizes = [1] * len(boxes)

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i):
            if linked(a, boxes[j]):
                ra, rb = root(i), root(j)
                if ra == rb:
                    continue
                if sizes[ra] < sizes[rb]:
                    ra, rb = rb, ra
                parents[rb] = ra
                sizes[ra] += sizes[rb]
    clusters = {}
    for i in range(len(boxes)):
        clusters.setdefault(root(i), []).append(i)
    return clusters.values()


def _span(a0, alen, b0, blen):
    return min(a0 + alen, b0 + blen) - max(a0, b0)


def merge_text_lines(
    boxes: list[list[int]], max_dx: int, max_dy: int, min_overlap_ratio: float
) -> list[list[int]]:
    """Merge transitively linked boxes and return their bounds top-to-bottom, then left-to-right."""
    if not isinstance(boxes, list) or not all(_rect(box) for box in boxes):
        raise ValueError("boxes must contain valid [x, y, w, h] rectangles")
    if (
        not _integer(max_dx, 0)
        or not _integer(max_dy, 0)
        or not _ratio(min_overlap_ratio)
    ):
        raise ValueError("text gaps must be nonnegative and overlap ratio in 0..1")

    def linked(a, b):
        dx = _span(a[0], a[2], b[0], b[2])
        dy = _span(a[1], a[3], b[1], b[3])
        return (
            -dx <= max_dx and max(0, dy) >= min_overlap_ratio * min(a[3], b[3])
        ) or (-dy <= max_dy and max(0, dx) >= min_overlap_ratio * min(a[2], b[2]))

    merged = []
    for group in _groups(boxes, linked):
        members = [boxes[i] for i in group]
        left = min(b[0] for b in members)
        top = min(b[1] for b in members)
        right = max(b[0] + b[2] for b in members)
        bottom = max(b[1] + b[3] for b in members)
        merged.append([left, top, right - left, bottom - top])
    return sorted(merged, key=lambda b: (b[1], b[0]))


def sort_reading_order(
    boxes: list[list[int]], rtl: bool, row_tolerance: int
) -> list[int]:
    """Group overlapping row bands and return the original indices in reading order."""
    if not isinstance(boxes, list) or not all(_rect(box) for box in boxes):
        raise ValueError("boxes must contain valid [x, y, w, h] rectangles")
    if type(rtl) is not bool or not _integer(row_tolerance, 0):
        raise ValueError("rtl must be a boolean and row tolerance nonnegative")

    def same_row(a, b):
        centers = abs(2 * (a[1] - b[1]) + a[3] - b[3])
        overlap = _span(a[1], a[3], b[1], b[3])
        return centers <= 2 * row_tolerance or 2 * overlap >= min(a[3], b[3])

    rows = sorted(
        _groups(boxes, same_row),
        key=lambda row: (min(boxes[i][1] for i in row), row[0]),
    )
    return [
        i
        for row in rows
        for i in sorted(
            row, key=lambda j: (-(boxes[j][0] + boxes[j][2]) if rtl else boxes[j][0], j)
        )
    ]


def estimate_stroke_width(
    gray: bytes, width: int, height: int, box_rect: list[int]
) -> float:
    """Return the median ink run length across rows and columns of a crop."""
    _image(gray, width, height)
    if not _rect(box_rect, 0):
        raise ValueError("stroke box must be a valid [x, y, w, h] rectangle")
    x, y, w, h = box_rect
    if x + w > width or y + h > height:
        raise ValueError("stroke box must fit in the image")
    if not w or not h:
        return 0.0
    rows = [gray[i * width + x : i * width + x + w] for i in range(y, y + h)]
    darkest, brightest = min(map(min, rows)), max(map(max, rows))
    if brightest - darkest < 24:
        return 0.0
    threshold = (darkest + brightest) // 2
    runs = []
    for lines in (rows, zip(*rows, strict=True)):
        for line in lines:
            run = 0
            for pixel in line:
                if pixel <= threshold:
                    run += 1
                elif run:
                    runs.append(run)
                    run = 0
            if run:
                runs.append(run)
    return float(median(runs))
