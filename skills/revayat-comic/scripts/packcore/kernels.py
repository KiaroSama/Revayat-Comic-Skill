"""Dependency-free reference kernels for archive order and raster verification."""

import math
import re

_DIGIT_RUN = re.compile(r"([0-9۰-۹٠-٩]+)")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_DECIMAL = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _sort_key(name: str) -> tuple:
    parts = _DIGIT_RUN.split(name)
    key = []
    for i, part in enumerate(parts):
        if i % 2:
            digits = part.translate(_DECIMAL).lstrip("0")
            key.append((len(digits), digits))
        else:
            key.append(part.translate(_ASCII_LOWER))
    return tuple(key)


def natural_sort_order(names: list[str]) -> list[int]:
    """Return stable filename indices using numeric runs and raw spelling ties."""
    if type(names) is not list or any(type(name) is not str for name in names):
        raise ValueError("names must be a list of strings")
    return sorted(range(len(names)), key=lambda i: (_sort_key(names[i]), names[i], i))


def _positive_int(value: int) -> bool:
    return type(value) is int and value > 0


def _finite_real(value: float) -> float:
    if type(value) not in (int, float):
        return math.nan
    try:
        return float(value)
    except OverflowError:
        return math.nan


def _check_rgb(rgb: bytes, width: int, height: int) -> None:
    if not _positive_int(width) or not _positive_int(height):
        raise ValueError("width and height must be positive integers")
    if type(rgb) is not bytes or len(rgb) != 3 * width * height:
        raise ValueError("RGB buffer must contain exactly width * height * 3 bytes")


def _luma(r: int, g: int, b: int) -> int:
    return (77 * r + 150 * g + 29 * b) >> 8


def analyze_rgb_page(rgb: bytes, width: int, height: int) -> list[int]:
    """Return the FNV-1a checksum, luma range, mean times 100 and nonwhite count."""
    _check_rgb(rgb, width, height)
    digest = 2166136261
    min_luma, max_luma, luma_sum, non_white = 255, 0, 0, 0
    pixels = iter(rgb)
    for r, g, b in zip(pixels, pixels, pixels):
        digest = ((digest ^ r) * 16777619) & 0xFFFFFFFF
        digest = ((digest ^ g) * 16777619) & 0xFFFFFFFF
        digest = ((digest ^ b) * 16777619) & 0xFFFFFFFF
        luma = _luma(r, g, b)
        min_luma = min(min_luma, luma)
        max_luma = max(max_luma, luma)
        luma_sum += luma
        non_white += luma < 245
    return [digest, min_luma, max_luma, luma_sum * 100 // (width * height), non_white]


def validate_page_dimensions(dims: list[list[int]], max_aspect_ratio: float, min_edge: int, max_pixels: int) -> list[int]:
    """Return indices outside the given edge, area or aspect bounds."""
    ratio = _finite_real(max_aspect_ratio)
    if not math.isfinite(ratio) or ratio < 1.0 or not _positive_int(min_edge) or not _positive_int(max_pixels):
        raise ValueError("dimension bounds must have a finite aspect ratio >= 1 and positive integer edges and area")
    if type(dims) is not list:
        raise ValueError("dims must be a list of two-element lists")
    invalid = []
    for i, row in enumerate(dims):
        if type(row) is not list or len(row) != 2:
            raise ValueError("dims must be a list of two-element lists")
        w, h = row
        if not _positive_int(w) or not _positive_int(h) or min(w, h) < min_edge or w * h > max_pixels:
            invalid.append(i)
            continue
        try:
            if max(w, h) / min(w, h) <= ratio:
                continue
        except OverflowError:
            pass
        invalid.append(i)
    return invalid


def compute_pdf_page_layout(page_w: int, page_h: int, target_dpi: float, max_edge_pt: float) -> list[float]:
    """Return PDF width, height, effective DPI and uniform downscale."""
    if not _positive_int(page_w) or not _positive_int(page_h):
        raise ValueError("page dimensions must be positive integers")
    w, h, dpi, limit = map(_finite_real, (page_w, page_h, target_dpi, max_edge_pt))
    if not all(math.isfinite(n) and n > 0.0 for n in (w, h, dpi, limit)):
        raise ValueError("page dimensions, DPI and point limit must be finite and positive")
    pt_w, pt_h = 72.0 * w / dpi, 72.0 * h / dpi
    if not all(math.isfinite(n) and n > 0.0 for n in (pt_w, pt_h)):
        raise ValueError("PDF page dimensions are out of range")
    scale = min(1.0, limit / max(pt_w, pt_h))
    if scale == 0.0:
        raise ValueError("scaled PDF layout is out of range")
    pt_w, pt_h, effective_dpi = min(limit, pt_w * scale), min(limit, pt_h * scale), dpi / scale
    if not all(math.isfinite(n) and n > 0.0 for n in (pt_w, pt_h, effective_dpi)):
        raise ValueError("scaled PDF layout is out of range")
    return [pt_w, pt_h, effective_dpi, scale]


def diff_raster_tiles(orig_rgb: bytes, final_rgb: bytes, width: int, height: int, tile_size: int, tol: int) -> list[list[int]]:
    """Return changed tile coordinates, pixel counts and largest channel deltas."""
    _check_rgb(orig_rgb, width, height)
    _check_rgb(final_rgb, width, height)
    if not _positive_int(tile_size):
        raise ValueError("tile_size must be a positive integer")
    if type(tol) is not int or not 0 <= tol <= 255:
        raise ValueError("tol must be an integer between 0 and 255")
    if orig_rgb == final_rgb or tol == 255:
        return []
    tiles = []
    for ty, y in enumerate(range(0, height, tile_size)):
        for tx, x in enumerate(range(0, width, tile_size)):
            changed, largest = 0, 0
            for row in range(y, min(y + tile_size, height)):
                start = (row * width + x) * 3
                end = (row * width + min(x + tile_size, width)) * 3
                for p in range(start, end, 3):
                    delta = max(abs(orig_rgb[p + c] - final_rgb[p + c]) for c in (0, 1, 2))
                    if delta > tol:
                        changed += 1
                        largest = max(largest, delta)
            if changed:
                tiles.append([tx, ty, changed, largest])
    return tiles


def compute_grayscale_histogram(rgb: bytes, width: int, height: int) -> list[int]:
    """Return 256 exact counts in increasing integer luma order."""
    _check_rgb(rgb, width, height)
    histogram = [0] * 256
    pixels = iter(rgb)
    for r, g, b in zip(pixels, pixels, pixels):
        histogram[_luma(r, g, b)] += 1
    return histogram
