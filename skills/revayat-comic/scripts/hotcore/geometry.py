"""Pure computational geometry kernels for comic detection and balloon fitting.

All functions operate on plain Python integers, floats, lists, and flat row-major
0/255 mask bytes so they can run directly in pure Python or through the compiled
Rust PyO3 extension (`rust/hotcore-rs`) generated and gated by `rust-anything`.
"""

from __future__ import annotations

import math


def box_gap(a: list[int], b: list[int]) -> float:
    """Euclidean gap distance between two `[x, y, w, h]` rectangles."""
    if len(a) < 4 or len(b) < 4:
        raise ValueError("Each box must have four integers: [x, y, w, h]")
    ax0, ay0, aw, ah = a[0], a[1], a[2], a[3]
    bx0, by0, bw, bh = b[0], b[1], b[2], b[3]
    dx = max(0, max(ax0, bx0) - min(ax0 + aw, bx0 + bw))
    dy = max(0, max(ay0, by0) - min(ay0 + ah, by0 + bh))
    return math.hypot(dx, dy)


def cluster_boxes(
    seeds: list[list[int]],
    max_seeds: int = 400,
    reach: float = 1.6,
) -> list[list[list[int]]]:
    """Group `[x, y, w, h]` boxes that lie within `reach * max_side` of each other."""
    if not seeds:
        return []
    if max_seeds < 1:
        raise ValueError("max_seeds must be positive")
    work = [list(box) for box in seeds]
    if len(work) > max_seeds:
        work = sorted(work, key=lambda box: -(box[2] * box[3]))[:max_seeds]

    n = len(work)
    parent = list(range(n))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(n):
        ai = work[i]
        ax0, ay0, aw, ah = ai[0], ai[1], ai[2], ai[3]
        ax1 = ax0 + aw
        ay1 = ay0 + ah
        for j in range(i + 1, n):
            bj = work[j]
            bx0, by0, bw, bh = bj[0], bj[1], bj[2], bj[3]
            dx = max(0, max(ax0, bx0) - min(ax1, bx0 + bw))
            dy = max(0, max(ay0, by0) - min(ay1, by0 + bh))
            scale = max(aw, ah, bw, bh)
            limit = reach * scale
            if limit >= 0.0 and (dx * dx + dy * dy) <= limit * limit + 1e-12:
                # Match exact floating-point sqrt comparison against reach * scale.
                if math.hypot(dx, dy) <= limit:
                    parent[find(i)] = find(j)

    groups: dict[int, list[list[int]]] = {}
    for index, box in enumerate(work):
        groups.setdefault(find(index), []).append(box)
    return list(groups.values())


def row_widths(mask_flat: bytes, width: int, height: int) -> list[int]:
    """Return the widest contiguous nonzero run for every row in a flat mask."""
    if not isinstance(mask_flat, (bytes, bytearray)):
        raise TypeError("mask_flat must be bytes")
    if width < 0 or height < 0:
        raise ValueError("width and height must be non-negative")
    if len(mask_flat) != width * height:
        raise ValueError("mask_flat length must equal width * height")
    if height == 0:
        return []
    if width == 0:
        return [0] * height

    widths: list[int] = []
    for row in range(height):
        start = row * width
        end = start + width
        best = 0
        run = 0
        for value in mask_flat[start:end]:
            if value:
                run += 1
                if run > best:
                    best = run
            else:
                run = 0
        widths.append(best)
    return widths


def band_span(
    mask_flat: bytes,
    width: int,
    height: int,
    first: int,
    last: int,
) -> list[int]:
    """Return `[left, span_width]` of the widest contiguous column run active on
    every row in `[first, last)`."""
    if not isinstance(mask_flat, (bytes, bytearray)):
        raise TypeError("mask_flat must be bytes")
    if width < 0 or height < 0:
        raise ValueError("width and height must be non-negative")
    if len(mask_flat) != width * height:
        raise ValueError("mask_flat length must equal width * height")
    clamped_first = max(0, first)
    clamped_last = min(height, last)
    if clamped_last <= clamped_first or width == 0:
        return [0, 0]

    best_start = 0
    best_len = 0
    run_start = 0
    run_len = 0

    for col in range(width):
        all_on = True
        for row in range(clamped_first, clamped_last):
            if mask_flat[row * width + col] == 0:
                all_on = False
                break
        if all_on:
            if run_len == 0:
                run_start = col
            run_len += 1
            if run_len > best_len:
                best_start = run_start
                best_len = run_len
        else:
            run_len = 0

    return [best_start, best_len]


def body_bounds(
    widths: list[int],
    reference: int = -1,
    body_width: float = 0.5,
) -> list[int]:
    """Return `[first_row, length]` of the longest run of rows at least
    `body_width * ref` wide. Pass `reference < 0` to use `max(widths)`."""
    if not widths:
        return [0, 0]
    ref = max(widths) if reference < 0 else reference
    threshold = ref * body_width
    best_start = 0
    best_length = 0
    run_start = 0
    run_length = 0
    for index, w in enumerate(widths):
        if w >= threshold:
            if run_length == 0:
                run_start = index
            run_length += 1
            if run_length > best_length:
                best_start = run_start
                best_length = run_length
        else:
            run_length = 0
    return [best_start, best_length]


def candidate_bodies(
    widths: list[int],
    body_width: float = 0.5,
) -> list[list[int]]:
    """Primary `body_bounds` plus quantile fallbacks for spiked or bridged shapes."""
    if not widths:
        return []
    ordered = sorted(widths)
    n = len(ordered)
    refs = (
        ordered[-1],
        ordered[int(0.85 * (n - 1))],
        ordered[int(0.75 * (n - 1))],
        ordered[n // 2],
    )
    seen: set[tuple[int, int]] = set()
    bodies: list[list[int]] = []
    for ref in refs:
        if ref <= 0:
            continue
        band = body_bounds(widths, ref, body_width)
        key = (band[0], band[1])
        if band[1] > 0 and key not in seen:
            seen.add(key)
            bodies.append(band)
    return bodies
