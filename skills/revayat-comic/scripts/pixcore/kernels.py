"""Reference pixel QA kernels for packed RGB and single-channel masks."""


def _pixel_count(width: int, height: int) -> int:
    if width < 0 or height < 0:
        raise ValueError("width and height must be non-negative")
    return width * height


_BUFFER = "pixel buffer has the wrong length or type"


def _valid_buffers(size: int, *buffers: bytes) -> bool:
    return all(isinstance(buffer, bytes) and len(buffer) == size for buffer in buffers)


def _rgb_diff(a: bytes, b: bytes, offset: int) -> int:
    return max(
        abs(a[offset] - b[offset]),
        abs(a[offset + 1] - b[offset + 1]),
        abs(a[offset + 2] - b[offset + 2]),
    )


def _clamp_box(box: list[int], width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
        raise ValueError("box must contain four integers: [x, y, w, h]")
    x, y, w, h = box
    return (
        max(0, min(x, width)), max(0, min(y, height)),
        max(0, min(x + w, width)), max(0, min(y + h, height)),
    )


def outside_mask_diff(
    orig_rgb: bytes, clean_rgb: bytes, mask_l: bytes, width: int, height: int, threshold: int,
) -> list[int]:
    """Return the number of changes and maximum channel difference outside the mask."""
    size = _pixel_count(width, height)
    if not _valid_buffers(3 * size, orig_rgb, clean_rgb) or not _valid_buffers(size, mask_l):
        raise ValueError(_BUFFER)
    changed = max_diff = 0
    for i, masked in enumerate(mask_l):
        if not masked:
            diff = _rgb_diff(orig_rgb, clean_rgb, 3 * i)
            max_diff = max(max_diff, diff)
            changed += diff > threshold
    return [changed, max_diff]


def changed_mask_rgb(a_rgb: bytes, b_rgb: bytes, width: int, height: int, threshold: int) -> bytes:
    """Mark each pixel whose largest channel difference exceeds the threshold."""
    size = _pixel_count(width, height)
    if not _valid_buffers(3 * size, a_rgb, b_rgb):
        raise ValueError(_BUFFER)
    return bytes(255 if _rgb_diff(a_rgb, b_rgb, i) > threshold else 0 for i in range(0, 3 * size, 3))


def overlap_changed_pixels(
    changed_mask: bytes, width: int, height: int, boxes: list[list[int]],
) -> list[list[int]]:
    """Return changed-pixel counts in each nonempty pairwise intersection."""
    if not _valid_buffers(_pixel_count(width, height), changed_mask):
        raise ValueError(_BUFFER)
    if not isinstance(boxes, list):
        raise ValueError("boxes must be a list")
    clipped = [_clamp_box(box, width, height) for box in boxes]
    overlaps = []
    for i, (ax0, ay0, ax1, ay1) in enumerate(clipped):
        for j in range(i + 1, len(clipped)):
            bx0, by0, bx1, by1 = clipped[j]
            x0, y0 = max(ax0, bx0), max(ay0, by0)
            x1, y1 = min(ax1, bx1), min(ay1, by1)
            if x0 >= x1 or y0 >= y1:
                continue
            count = 0
            for y in range(y0, y1):
                row = y * width
                pixels = changed_mask[row + x0 : row + x1]
                count += len(pixels) - pixels.count(0)
            if count:
                overlaps.append([i, j, count])
    return overlaps


def outline_crossing_pixels(
    orig_rgb: bytes, clean_rgb: bytes, final_rgb: bytes, safe_mask: bytes,
    width: int, height: int, box: list[int], dark_polarity: bool, diff_threshold: int,
) -> int:
    """Count new ink on non-paper pixels outside the safe interior."""
    size = _pixel_count(width, height)
    if not _valid_buffers(3 * size, orig_rgb, clean_rgb, final_rgb) or not _valid_buffers(size, safe_mask):
        raise ValueError(_BUFFER)
    x0, y0, x1, y1 = _clamp_box(box, width, height)
    if x0 >= x1 or y0 >= y1:
        return 0
    count = 0
    for y in range(y0, y1):
        row = y * width
        for i in range(row + x0, row + x1):
            if safe_mask[i] or _rgb_diff(final_rgb, clean_rgb, 3 * i) <= diff_threshold:
                continue
            offset = 3 * i
            rgb_sum = orig_rgb[offset] + orig_rgb[offset + 1] + orig_rgb[offset + 2]
            count += (rgb_sum > 120) if dark_polarity else (rgb_sum < 645)
    return count
