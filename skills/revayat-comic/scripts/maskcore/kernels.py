"""Reference kernels for row-major balloon masks without image-library dependencies."""

import sys
from collections import deque

_I64_MIN = -(2**63)
_I64_MAX = 2**63 - 1


def _checked_size(data, width, height):
    if not (
        isinstance(width, int) and isinstance(height, int)
        and 0 < width <= sys.maxsize and 0 < height <= sys.maxsize // width
    ):
        raise ValueError("invalid image dimensions")
    size = width * height
    if not isinstance(data, bytes) or len(data) != size:
        raise ValueError("pixel buffer must be bytes and match image dimensions")
    return size


def _neighbors(index, width, height):
    y, x = divmod(index, width)
    if x > 0:
        yield index - 1
    if x + 1 < width:
        yield index + 1
    if y > 0:
        yield index - width
    if y + 1 < height:
        yield index + width


def _scan_lines(data, length, count, step, stride, radius, erosion):
    out = bytearray(len(data))
    # For binary masks, the most recent decisive pixel suffices for the clipped window.
    decisive = 0 if erosion else 255
    other = 255 - decisive
    for line in range(count):
        start = line * stride
        cursor = 0
        last = -length
        for center in range(length):
            end = min(length - 1, center + radius)
            while cursor <= end:
                if data[start + cursor * step] == decisive:
                    last = cursor
                cursor += 1
            out[start + center * step] = decisive if last >= max(0, center - radius) else other
    return out


def _morph(mask, width, height, radius, erosion):
    if radius == 0:
        return bytes(mask)
    rows = _scan_lines(mask, width, height, 1, width, radius, erosion)
    return bytes(_scan_lines(rows, height, width, width, 1, radius, erosion))


def _checked_binary(mask, width, height, radius):
    _checked_size(mask, width, height)
    if not isinstance(radius, int) or radius < 0:
        raise ValueError("radius must be non-negative")
    if mask.count(0) + mask.count(255) != len(mask):
        raise ValueError("mask must be binary (0 or 255)")


def flood_balloon_interior(
    gray: bytes, width: int, height: int, seed_x: int, seed_y: int, wall_luma: int, grad_thresh: int, min_inset: int,
) -> bytes:
    """Flood cardinal neighbors, rejecting dark or steep-gradient pixels, then inset the mask."""
    size = _checked_size(gray, width, height)
    if not (
        isinstance(seed_x, int) and isinstance(seed_y, int)
        and 0 <= seed_x < width and 0 <= seed_y < height
    ):
        raise ValueError("seed is outside the image")
    if not isinstance(wall_luma, int) or not 0 <= wall_luma <= 255:
        raise ValueError("wall_luma must be between 0 and 255")
    if not isinstance(grad_thresh, int) or not 0 <= grad_thresh <= 256:
        raise ValueError("grad_thresh must be between 0 and 256")
    if not isinstance(min_inset, int) or min_inset < 0:
        raise ValueError("min_inset must be non-negative")

    seed = seed_y * width + seed_x
    seen = bytearray(size)
    seen[seed] = 1
    mask = bytearray(size)
    queue = deque([seed])
    while queue:
        index = queue.popleft()
        luma = gray[index]
        if luma < wall_luma or grad_thresh == 0:
            continue
        neighbors = tuple(_neighbors(index, width, height))
        if any(abs(luma - gray[n]) >= grad_thresh for n in neighbors):
            continue
        mask[index] = 255
        for neighbor in neighbors:
            if not seen[neighbor]:
                seen[neighbor] = 1
                queue.append(neighbor)
    return _morph(mask, width, height, min_inset, True)


def erode_linf(mask: bytes, width: int, height: int, radius: int) -> bytes:
    """Return the binary minimum over each clipped square window."""
    _checked_binary(mask, width, height, radius)
    return _morph(mask, width, height, radius, True)


def dilate_linf(mask: bytes, width: int, height: int, radius: int) -> bytes:
    """Return the binary maximum over each clipped square window."""
    _checked_binary(mask, width, height, radius)
    return _morph(mask, width, height, radius, False)


def _box_bounds(boxes):
    if not isinstance(boxes, list) or not boxes:
        raise ValueError("boxes must be a non-empty list")
    bounds = []
    for box in boxes:
        if (
            not isinstance(box, (list, tuple)) or len(box) != 4
            or not all(isinstance(v, int) and _I64_MIN <= v <= _I64_MAX for v in box)
            or box[2] <= 0 or box[3] <= 0
        ):
            raise ValueError("box must contain four signed 64-bit integers with positive width and height")
        x, y, w, h = box
        bounds.append((x, y, x + w - 1, y + h - 1, 2 * x + w, 2 * y + h))
    return bounds


def _trim_seams(owners, width, height, margin):
    queue = deque()
    for index, owner in enumerate(owners):
        if owner >= 0 and any(owners[n] >= 0 and owners[n] != owner for n in _neighbors(index, width, height)):
            queue.append((index, 1))
    for index, _ in queue:
        owners[index] = -1
    while queue:
        index, distance = queue.popleft()
        if distance < margin:
            for neighbor in _neighbors(index, width, height):
                if owners[neighbor] >= 0:
                    owners[neighbor] = -1
                    queue.append((neighbor, distance + 1))


def partition_voronoi_lobes(
    union_mask: bytes, width: int, height: int, ux0: int, uy0: int, boxes: list[list[int]], seam_margin: int,
) -> list[int]:
    """Choose owners by rectangle distance, doubled-center distance, then input index."""
    size = _checked_size(union_mask, width, height)
    if not (
        isinstance(ux0, int) and isinstance(uy0, int)
        and _I64_MIN <= ux0 <= _I64_MAX and _I64_MIN <= uy0 <= _I64_MAX
    ):
        raise ValueError("union origin must use signed 64-bit coordinates")
    if not isinstance(seam_margin, int) or seam_margin < 0:
        raise ValueError("seam_margin must be non-negative")
    bounds = _box_bounds(boxes)
    owners = [-1] * size
    for index, active in enumerate(union_mask):
        if not active:
            continue
        y, x = divmod(index, width)
        x, y = x + ux0, y + uy0
        best = None
        for owner, (left, top, right, bottom, cx2, cy2) in enumerate(bounds):
            dx = max(left - x, x - right, 0)
            dy = max(top - y, y - bottom, 0)
            score = (dx * dx + dy * dy, (2 * x - cx2) ** 2 + (2 * y - cy2) ** 2)
            if best is None or score < best:
                owners[index], best = owner, score
    if seam_margin and len(bounds) > 1:
        _trim_seams(owners, width, height, seam_margin)
    return owners


def strip_perimeter_contours(
    mask: bytes, width: int, height: int, min_area_ratio: float, min_span_ratio: float,
) -> tuple[bytes, bytes]:
    """Split qualifying edge-touching 8-connected components from the kept mask."""
    size = _checked_size(mask, width, height)
    if not isinstance(min_area_ratio, (int, float)) or not 0 <= min_area_ratio <= 1:
        raise ValueError("min_area_ratio must be between 0 and 1")
    if not isinstance(min_span_ratio, (int, float)) or not 0 <= min_span_ratio <= 1:
        raise ValueError("min_span_ratio must be between 0 and 1")
    unseen = bytearray(mask)
    kept, stripped = bytearray(size), bytearray(size)
    area_floor = min_area_ratio * size
    span_x, span_y = min_span_ratio * width, min_span_ratio * height
    for seed in range(size):
        if not unseen[seed]:
            continue
        unseen[seed] = 0
        component = [seed]
        top, left = divmod(seed, width)
        bottom, right = top, left
        for index in component:
            y, x = divmod(index, width)
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for row in range(max(0, y - 1), min(height, y + 2)):
                for col in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = row * width + col
                    if unseen[neighbor]:
                        unseen[neighbor] = 0
                        component.append(neighbor)
        border = left == 0 or right == width - 1 or top == 0 or bottom == height - 1
        span = right - left + 1 >= span_x or bottom - top + 1 >= span_y
        dest = stripped if border and span and len(component) >= area_floor else kept
        for index in component:
            dest[index] = 255
    return bytes(kept), bytes(stripped)
