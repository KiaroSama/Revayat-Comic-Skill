"""Reference cleaning kernels for tightly packed row-major RGB and masks."""

from math import sqrt
from sys import float_info, maxsize


def _size(width, height):
    if type(width) is not int or type(height) is not int or not (0 < width <= maxsize and 0 < height <= maxsize // width):
        raise ValueError("invalid image dimensions")
    return width * height


def _buffers(size, *buffers):
    if any(type(data) is not bytes or len(data) != size * channels for data, channels in buffers):
        raise ValueError("pixel buffer must be bytes and match image dimensions")


def _radius(value):
    if type(value) is not int or value < 0:
        raise ValueError("radius must be a nonnegative integer")


def _iterations(value):
    if type(value) is not int or not 0 <= value <= maxsize:
        raise ValueError("iterations must be an integer from 0 to sys.maxsize")


def _channel(value):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("fill channels must be integers from 0 to 255")


def _threshold(value):
    if type(value) not in (int, float) or not 0 <= value <= float_info.max:
        raise ValueError("standard deviation threshold must be a finite nonnegative number")


def _distances(mask, width, height, interior):
    # A virtual border contributes only to the interior distance transform.
    far = max(width, height) + 1
    edge = 0 if interior else far
    stride = width + 2
    distance = [edge] * (stride * (height + 2))
    for y in range(height):
        start = (y + 1) * stride + 1
        for x in range(width):
            if bool(mask[y * width + x]) == interior:
                pos = start + x
                up = pos - stride
                distance[pos] = 1 + min(distance[pos - 1], distance[up - 1], distance[up], distance[up + 1], far - 1)
            else:
                distance[start + x] = 0
    for y in range(height - 1, -1, -1):
        start = (y + 1) * stride + 1
        for pos in range(start + width - 1, start - 1, -1):
            if distance[pos]:
                down = pos + stride
                distance[pos] = min(distance[pos], 1 + min(
                    distance[pos + 1], distance[down - 1], distance[down], distance[down + 1]
                ))
    for y in range(height):
        start = (y + 1) * stride + 1
        yield from distance[start:start + width]


def _ring(mask, width, height, radius):
    if not radius or not any(mask) or all(mask):
        return
    # No finite in-image distance can exceed this cap.
    radius = min(radius, max(width, height) - 1)
    for i, distance in enumerate(_distances(mask, width, height, False)):
        if 0 < distance <= radius:
            yield i * 3


def _median(rgb, ring):
    hist = [[0] * 256 for _ in range(3)]
    count = 0
    for offset in ring:
        for channel in range(3):
            hist[channel][rgb[offset + channel]] += 1
        count += 1
    if count == 0:
        return [255, 255, 255, 0]
    medians = []
    for counts in hist:
        rank = (count - 1) // 2
        for value, frequency in enumerate(counts):
            if frequency > rank:
                medians.append(value)
                break
            rank -= frequency
    return [*medians, count]


def sample_ring_background(rgb: bytes, mask: bytes, width: int, height: int, ring_px: int) -> list[int]:
    """Return the lower RGB medians and count of the unmasked ring."""
    size = _size(width, height)
    _buffers(size, (rgb, 3), (mask, 1))
    _radius(ring_px)
    return _median(rgb, _ring(mask, width, height, ring_px))


def compute_feather_alpha(mask: bytes, width: int, height: int, radius: int) -> bytes:
    """Ramp inward from unmasked pixels and the outside of the image."""
    size = _size(width, height)
    _buffers(size, (mask, 1))
    _radius(radius)
    if radius == 0:
        return bytes(255 if active else 0 for active in mask)
    return bytes(min(255, (distance * 255 + radius // 2) // radius)
                 for distance in _distances(mask, width, height, True))


def composite_masked_rgb(orig_rgb: bytes, fill_rgb: bytes, alpha: bytes, width: int, height: int) -> bytes:
    """Blend with integer rounding, preserving every zero-alpha byte."""
    size = _size(width, height)
    _buffers(size, (orig_rgb, 3), (fill_rgb, 3), (alpha, 1))
    result = bytearray(orig_rgb)
    for i, amount in enumerate(alpha):
        if amount:
            for offset in range(i * 3, i * 3 + 3):
                result[offset] = (fill_rgb[offset] * amount + orig_rgb[offset] * (255 - amount) + 127) // 255
    return bytes(result)


def diffuse_inpaint_rgb(rgb: bytes, mask: bytes, width: int, height: int, iterations: int) -> bytes:
    """Seed from the first ring, then run four-neighbor Jacobi with clamped edges."""
    size = _size(width, height)
    _buffers(size, (rgb, 3), (mask, 1))
    _iterations(iterations)
    if not any(mask):
        return rgb
    if all(mask):
        return b"\xff" * len(rgb)
    seed = bytes(_median(rgb, _ring(mask, width, height, 1))[:3])
    current = bytearray(rgb)
    for i, active in enumerate(mask):
        if active:
            current[i * 3:i * 3 + 3] = seed
    if iterations == 0:
        return bytes(current)
    neighbors = []
    for i, active in enumerate(mask):
        if active:
            y, x = divmod(i, width)
            neighbors.append((i * 3, (i - (x > 0)) * 3, (i + (x + 1 < width)) * 3,
                              (i - width * (y > 0)) * 3, (i + width * (y + 1 < height)) * 3))
    following = current.copy()
    for step in range(iterations):
        changed = repeats = False
        for at, left, right, up, down in neighbors:
            for channel in range(3):
                value = (current[left + channel] + current[right + channel] +
                         current[up + channel] + current[down + channel] + 2) // 4
                changed |= value != current[at + channel]
                repeats |= value != following[at + channel]
                following[at + channel] = value
        current, following = following, current
        if not changed:
            break
        if not repeats:
            # Both buffers now belong to an exact two-cycle.
            return bytes(following if (iterations - step - 1) % 2 else current)
    return bytes(current)


def detect_textured_ring(rgb: bytes, mask: bytes, width: int, height: int, ring_px: int, std_thresh: float) -> list[float]:
    """Flag rings whose population luma deviation exceeds the threshold."""
    size = _size(width, height)
    _buffers(size, (rgb, 3), (mask, 1))
    _radius(ring_px)
    _threshold(std_thresh)
    low, high = [255] * 3, [0] * 3
    count, mean, squared = 0, 0.0, 0.0
    for offset in _ring(mask, width, height, ring_px):
        red, green, blue = rgb[offset:offset + 3]
        luma = 299 * red + 587 * green + 114 * blue
        count += 1
        delta = luma - mean
        mean += delta / count
        squared += delta * (luma - mean)
        for channel, value in enumerate((red, green, blue)):
            low[channel] = min(low[channel], value)
            high[channel] = max(high[channel], value)
    if count == 0:
        return [0.0, 0.0, 0.0, 0.0]
    deviation = sqrt(squared / count) / 1000.0
    return [float(deviation > std_thresh), deviation, float(max(hi - lo for lo, hi in zip(low, high))), float(count)]


def fill_flat_rgb(orig_rgb: bytes, mask: bytes, width: int, height: int, r: int, g: int, b: int) -> bytes:
    """Replace active pixels with a constant RGB color."""
    size = _size(width, height)
    _buffers(size, (orig_rgb, 3), (mask, 1))
    for value in (r, g, b):
        _channel(value)
    fill = bytes((r, g, b))
    result = bytearray(orig_rgb)
    for i, active in enumerate(mask):
        if active:
            result[i * 3:i * 3 + 3] = fill
    return bytes(result)
