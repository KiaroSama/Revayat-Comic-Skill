"""Reference kernels for shaped balloon layout in integer pixels."""

from sys import maxsize


def _pixel(value, minimum=0):
    return type(value) is int and minimum <= value <= maxsize


def _vector(values):
    return type(values) is list and all(_pixel(value) for value in values)


def _image_size(width, height):
    if not (_pixel(width, 1) and _pixel(height, 1)) or height > maxsize // width:
        raise ValueError("invalid image dimensions")
    return width * height


def _validate_masks(size, *masks):
    if any(type(mask) is not bytes or len(mask) != size for mask in masks):
        raise ValueError("mask buffer must be bytes and match image dimensions")


def _validate_spans(spans):
    if type(spans) is not list or any(
        not _vector(row) or len(row) != 2 or row[0] > row[1] for row in spans
    ):
        raise ValueError("spans must contain ordered pairs of nonnegative integer edges")


def scan_mask_spans(mask: bytes, width: int, height: int) -> list[list[int]]:
    """Return the leftmost widest active run on each row as [left, right)."""
    _validate_masks(_image_size(width, height), mask)
    spans = []
    for offset in range(0, len(mask), width):
        left = right = start = 0
        for x, value in enumerate(mask[offset:offset + width]):
            if value:
                if x + 1 - start > right - left:
                    left, right = start, x + 1
            else:
                start = x + 1
        spans.append([left, right])
    return spans


def _bands(spans, start, stop, line_height, pad_x):
    for y in range(start, stop - line_height + 1):
        rows = spans[y:y + line_height]
        yield max(row[0] for row in rows) + pad_x, min(row[1] for row in rows) - pad_x


def _wrap(words, space, bands, step, line_height, start, stop):
    n = len(words)
    best = None
    result = []
    center = (len(bands) - 1) // 2
    for top in sorted(range(len(bands)), key=lambda y: (abs(y - center), y)):
        # Each layer uses one more line. At a given word only the cheapest prefix matters.
        states = {0: 0}
        parents = []
        for band_index in range(top, len(bands), step):
            left, right = bands[band_index]
            if right <= left:
                break
            next_states = {}
            predecessors = {}
            for i, cost in sorted(states.items()):
                remaining = right - left
                for j in range(i + 1, n + 1):
                    remaining -= words[j - 1] + (space if j > i + 1 else 0)
                    if remaining < 0:
                        break
                    score = cost + remaining * remaining
                    if j not in next_states or score < next_states[j]:
                        next_states[j] = score
                        predecessors[j] = i
            parents.append(predecessors)
            if n in next_states:
                footprint = band_index - top + line_height
                center = (stop - start - footprint) // 2
                key = (next_states.pop(n), abs(top - center), top, len(parents))
                if best is None or key < best:
                    best = key
                    result = []
                    end = n
                    for layer in range(len(parents) - 1, -1, -1):
                        i = parents[layer][end]
                        row = top + layer * step
                        result.append([i, end, start + row, *bands[row]])
                        end = i
                    result.reverse()
            if not next_states:
                break
            states = next_states
    return result


def fit_lines_to_spans(word_widths: list[int], space_width: int, line_height: int, line_gap: int,
                       spans: list[list[int]], pad_x: int, pad_y: int) -> list[list[int]]:
    """Minimize squared slack across all lines, breaking ties by vertical centering."""
    if not _vector(word_widths):
        raise ValueError("word widths must be nonnegative integers")
    if not (_pixel(line_height, 1) and all(_pixel(v) for v in (space_width, line_gap, pad_x, pad_y))):
        raise ValueError("invalid line metrics or padding")
    _validate_spans(spans)
    active = [y for y, (left, right) in enumerate(spans) if left < right]
    if not word_widths or not active:
        return []
    start, stop = active[0] + pad_y, active[-1] + 1 - pad_y
    if stop - start < line_height:
        return []
    bands = list(_bands(spans, start, stop, line_height, pad_x))
    return _wrap(word_widths, space_width, bands, line_height + line_gap, line_height, start, stop)


def harmonize_font_sizes(sizes: list[int], areas: list[int], max_step: int, floor_size: int) -> list[int]:
    """Cap participating sizes at the lower weighted median plus max_step."""
    if not (_vector(sizes) and _vector(areas)):
        raise ValueError("font sizes and areas must be nonnegative integers")
    if len(sizes) != len(areas):
        raise ValueError("sizes and areas must have equal lengths")
    if not (_pixel(max_step) and _pixel(floor_size)):
        raise ValueError("font limits must be nonnegative integers")
    eligible = sorted((size, area) for size, area in zip(sizes, areas) if size >= floor_size and area)
    if not eligible:
        return sizes.copy()
    remaining = (sum(area for _, area in eligible) + 1) // 2
    for target, area in eligible:
        remaining -= area
        if remaining <= 0:
            return [min(size, target + max_step) if area else size for size, area in zip(sizes, areas)]


def _wall_distances(walls, width, height):
    far = max(width, height)
    distance = [0 if value else far for value in walls]
    # Opposite passes propagate diagonal and orthogonal steps at the same cost.
    for direction in (1, -1):
        rows = range(height) if direction == 1 else range(height - 1, -1, -1)
        columns = range(width) if direction == 1 else range(width - 1, -1, -1)
        for y in rows:
            row = y * width
            prev_y = y - direction
            for x in columns:
                index = row + x
                value = distance[index]
                if not value:
                    continue
                if 0 <= x - direction < width:
                    value = min(value, distance[index - direction] + 1)
                if 0 <= prev_y < height:
                    prev = prev_y * width + x
                    value = min(value, distance[prev] + 1)
                    if x:
                        value = min(value, distance[prev - 1] + 1)
                    if x + 1 < width:
                        value = min(value, distance[prev + 1] + 1)
                distance[index] = value
    return distance


def check_ink_wall_clearance(ink_mask: bytes, wall_mask: bytes, width: int, height: int,
                             min_clearance: int) -> list[int]:
    """Count ink pixels closer than the limit and report the first worst pixel."""
    _validate_masks(_image_size(width, height), ink_mask, wall_mask)
    if not _pixel(min_clearance):
        raise ValueError("minimum clearance must be a nonnegative integer")
    if not min_clearance or not any(ink_mask) or not any(wall_mask):
        return [0, min_clearance, -1, -1]
    best, worst, count = min_clearance, -1, 0
    for index, distance in enumerate(_wall_distances(wall_mask, width, height)):
        if ink_mask[index] and distance < min_clearance:
            count += 1
            if distance < best:
                best, worst = distance, index
    return [count, best, worst % width, worst // width] if count else [0, min_clearance, -1, -1]


def select_largest_inscribed_band(spans: list[list[int]], min_width: int, min_height: int) -> list[int]:
    """Return the largest rectangle; ties favor the topmost, then leftmost."""
    _validate_spans(spans)
    if not (_pixel(min_width, 1) and _pixel(min_height, 1)):
        raise ValueError("invalid minimum band size")
    best = (0, 0, 0, 0, 0)
    for y, (left, right) in enumerate(spans):
        for bottom in range(y, len(spans)):
            a, b = spans[bottom]
            left, right = max(left, a), min(right, b)
            width, height = right - left, bottom - y + 1
            if width < min_width:
                break
            if height >= min_height and (width * height, -y, -left) > best[:3]:
                best = (width * height, -y, -left, width, height)
    return [-best[2], -best[1], best[3], best[4]]


def align_lines_rtl(line_widths: list[int], band_lefts: list[int], band_rights: list[int], mode: int) -> list[int]:
    """Return clamped line origins for centered, right, or left alignment."""
    if not all(_vector(item) for item in (line_widths, band_lefts, band_rights)):
        raise ValueError("line widths and band edges must be nonnegative integers")
    if not len(line_widths) == len(band_lefts) == len(band_rights):
        raise ValueError("line widths and band edges must have equal lengths")
    if any(left > right for left, right in zip(band_lefts, band_rights)):
        raise ValueError("band edges must be ordered")
    if not _pixel(mode) or mode > 2:
        raise ValueError("alignment mode must be 0, 1, or 2")
    return [
        left + (spare // 2 if mode == 0 else spare if mode == 1 else 0)
        for width, left, right in zip(line_widths, band_lefts, band_rights)
        for spare in [max(0, right - left - width)]
    ]
