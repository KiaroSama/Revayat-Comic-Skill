"""Reference kernels for pixel QA on tightly packed, row-major images."""

from sys import maxsize


def _size(width, height):
    if type(width) is not int or type(height) is not int or not (0 < width <= maxsize and 0 < height <= maxsize // width):
        raise ValueError("invalid image dimensions")
    return width * height


def _buffers(size, *buffers):
    if any(type(data) is not bytes or len(data) != size * channels for data, channels in buffers):
        raise ValueError("pixel buffer must be bytes and match image dimensions")


def _channel(value):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("luma and difference thresholds must be integers from 0 to 255")


def _radius(value):
    if type(value) is not int or value < 0:
        raise ValueError("radius must be a nonnegative integer")


def _scan_axis(mask, lines, length, line_step, pixel_step, radius):
    marks = bytearray(len(mask))
    for line in range(lines):
        start = line * line_step
        latest = -1
        cursor = 0
        for center in range(length):
            stop = min(length, center + radius + 1)
            while cursor < stop:
                if mask[start + cursor * pixel_step]:
                    latest = cursor
                cursor += 1
            if latest >= max(0, center - radius):
                marks[start + center * pixel_step] = 1
    return marks


def _dilate(mask, width, height, radius):
    # Two one-dimensional scans give the exact square neighborhood in linear time.
    rows = _scan_axis(mask, height, width, width, 1, radius)
    return _scan_axis(rows, width, height, 1, width, radius)


def detect_outline_bleed(orig_gray: bytes, final_gray: bytes, width: int, height: int, ink_mask: bytes,
                         wall_thresh: int, diff_thresh: int) -> list[int]:
    """Count erased and crossed dark wall pixels and give their inclusive bounds."""
    size = _size(width, height)
    _buffers(size, (orig_gray, 1), (final_gray, 1), (ink_mask, 1))
    _channel(wall_thresh)
    _channel(diff_thresh)
    erased = crossed = 0
    left, top, right, bottom = width, height, -1, -1
    for i, (before, after, ink) in enumerate(zip(orig_gray, final_gray, ink_mask)):
        if before >= wall_thresh:
            continue
        if ink:
            crossed += 1
        elif after - before >= diff_thresh:
            erased += 1
        else:
            continue
        y, x = divmod(i, width)
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x), max(bottom, y)
    if right < 0:
        left = top = -1
    return [erased, crossed, left, top, right, bottom]


def _linearize(channel):
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


_LINEAR = tuple(_linearize(channel) for channel in range(256))


def measure_region_contrast(rgb: bytes, ink_mask: bytes, width: int, height: int, pad: int) -> list[float]:
    """Compare mean WCAG 2.1 luminance of ink and nearby non-ink pixels."""
    size = _size(width, height)
    _buffers(size, (rgb, 3), (ink_mask, 1))
    _radius(pad)
    if not pad or not any(ink_mask) or 0 not in ink_mask:
        return [1.0, 0.0, 0.0]
    near = _dilate(ink_mask, width, height, pad)
    ink_count = bg_count = 0
    ink_sum = bg_sum = 0.0
    for i, included in enumerate(near):
        if not included:
            continue
        k = i * 3
        luma = 0.2126 * _LINEAR[rgb[k]] + 0.7152 * _LINEAR[rgb[k + 1]] + 0.0722 * _LINEAR[rgb[k + 2]]
        if ink_mask[i]:
            ink_count += 1
            ink_sum += luma
        else:
            bg_count += 1
            bg_sum += luma
    if not bg_count:
        return [1.0, 0.0, 0.0]
    ink, bg = ink_sum / ink_count, bg_sum / bg_count
    return [(max(ink, bg) + 0.05) / (min(ink, bg) + 0.05), ink, bg]


def _delta(before, after, i):
    k = i * 3
    return max(abs(before[k] - after[k]), abs(before[k + 1] - after[k + 1]), abs(before[k + 2] - after[k + 2]))


def detect_halo_artifacts(orig_rgb: bytes, clean_rgb: bytes, mask: bytes, width: int, height: int, ring_px: int,
                          diff_thresh: int) -> list[int]:
    """Count changed pixels in the clipped outer ring and measure its maximum delta."""
    size = _size(width, height)
    _buffers(size, (orig_rgb, 3), (clean_rgb, 3), (mask, 1))
    _radius(ring_px)
    _channel(diff_thresh)
    if not ring_px or not any(mask) or 0 not in mask:
        return [0, 0, 0]
    ring = _dilate(mask, width, height, ring_px)
    dirty = maximum = total = 0
    for i, included in enumerate(ring):
        if included and not mask[i]:
            delta = _delta(orig_rgb, clean_rgb, i)
            dirty += delta > diff_thresh
            maximum = max(maximum, delta)
            total += 1
    return [dirty, maximum, total]


def _ssim(pairs):
    count = x_sum = y_sum = x2_sum = y2_sum = xy_sum = 0
    for x, y in pairs:
        count += 1
        x_sum += x
        y_sum += y
        x2_sum += x * x
        y2_sum += y * y
        xy_sum += x * y
    if not count:
        return 1.0
    x_mean, y_mean = x_sum / count, y_sum / count
    x_var = x2_sum / count - x_mean * x_mean
    y_var = y2_sum / count - y_mean * y_mean
    cov = xy_sum / count - x_mean * y_mean
    return ((2.0 * x_mean * y_mean + 6.5025) * (2.0 * cov + 58.5225)
            / ((x_mean * x_mean + y_mean * y_mean + 6.5025) * (x_var + y_var + 58.5225)))


def compute_patch_ssim(orig_gray: bytes, final_gray: bytes, width: int, height: int, mask: bytes) -> float:
    """Average population SSIM over untouched 8x8 tiles, or over unmasked pixels."""
    size = _size(width, height)
    _buffers(size, (orig_gray, 1), (final_gray, 1), (mask, 1))
    count = 0
    total = 0.0
    for y in range(0, height - 7, 8):
        for x in range(0, width - 7, 8):
            start = y * width + x
            rows = range(start, start + 8 * width, width)
            if any(any(mask[k:k + 8]) for k in rows):
                continue
            total += _ssim((orig_gray[i], final_gray[i]) for k in rows for i in range(k, k + 8))
            count += 1
    if count:
        return total / count
    return _ssim((a, b) for a, b, m in zip(orig_gray, final_gray, mask) if not m)


def detect_residual_ink(clean_gray: bytes, mask: bytes, width: int, height: int, bg_luma: int, delta_thresh: int,
                        min_cluster: int) -> list[int]:
    """Keep 8-connected residual clusters and give their aggregate pixel centroid."""
    size = _size(width, height)
    _buffers(size, (clean_gray, 1), (mask, 1))
    _channel(bg_luma)
    _channel(delta_thresh)
    if type(min_cluster) is not int or min_cluster < 1:
        raise ValueError("minimum cluster size must be a positive integer")
    pending = bytearray(m != 0 and abs(gray - bg_luma) >= delta_thresh for gray, m in zip(clean_gray, mask))
    total = largest = sum_x = sum_y = 0
    for i in range(size):
        if not pending[i]:
            continue
        pending[i] = 0
        stack = [i]
        count = cluster_x = cluster_y = 0
        while stack:
            y, x = divmod(stack.pop(), width)
            count += 1
            cluster_x += x
            cluster_y += y
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    j = ny * width + nx
                    if pending[j]:
                        pending[j] = 0
                        stack.append(j)
        if count >= min_cluster:
            total += count
            largest = max(largest, count)
            sum_x += cluster_x
            sum_y += cluster_y
    return [total, largest, sum_x // total, sum_y // total] if total else [0, 0, -1, -1]


def compute_ink_bounds(before_rgb: bytes, after_rgb: bytes, width: int, height: int, diff_thresh: int) -> list[int]:
    """Give the tight rectangle and count of changed RGB pixels meeting the threshold."""
    size = _size(width, height)
    _buffers(size, (before_rgb, 3), (after_rgb, 3))
    _channel(diff_thresh)
    if before_rgb == after_rgb:
        return [0, 0, 0, 0, 0]
    if diff_thresh == 0:
        return [0, 0, width, height, size]
    count = 0
    left, top, right, bottom = width, height, -1, -1
    for i in range(size):
        if _delta(before_rgb, after_rgb, i) >= diff_thresh:
            count += 1
            y, x = divmod(i, width)
            left, top = min(left, x), min(top, y)
            right, bottom = max(right, x), max(bottom, y)
    return [left, top, right - left + 1, bottom - top + 1, count] if count else [0, 0, 0, 0, 0]
