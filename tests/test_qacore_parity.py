"""Pixel QA behavior and optional native parity."""

import importlib
import random
import sys

import pytest

from qacore import kernels as reference


@pytest.fixture(params=["python", "dispatch"])
def kernels(request):
    if request.param == "python":
        return reference
    return importlib.import_module("qacore")


def bitmap(*rows):
    return bytes(128 if char == "#" else 0 for row in rows for char in row)


def test_outline_bleed_counts_only_original_dark_pixels(kernels):
    original = bytes([20, 29, 30, 0, 35, 12])
    final = bytes([40, 255, 255, 19, 100, 1])
    ink = bytes([0, 1, 255, 0, 0, 23])
    assert kernels.detect_outline_bleed(original, final, 3, 2, ink, 30, 20) == [1, 2, 0, 0, 2, 1]
    assert kernels.detect_outline_bleed(original, original, 3, 2, bytes(6), 30, 1) == [0, 0, -1, -1, -1, -1]


def test_contrast_uses_wcag_luminance_and_a_clipped_square(kernels):
    # Pure red ink sees white, green and blue, including blue on the diagonal.
    rgb = bytes.fromhex("ff0000 ffffff 000000 00ff00 0000ff 000000")
    mask = bitmap("#..", "...")
    bg = (1.0 + 0.7152 + 0.0722) / 3
    expected = [(bg + 0.05) / (0.2126 + 0.05), 0.2126, bg]
    assert kernels.measure_region_contrast(rgb, mask, 3, 2, 1) == pytest.approx(expected, abs=1e-14)
    assert kernels.measure_region_contrast(rgb, mask, 3, 2, 2**150)[2] == pytest.approx(bg * 3 / 5)
    for radius, ink in [(0, mask), (1, bytes(6)), (1, bytes([255]) * 6)]:
        assert kernels.measure_region_contrast(rgb, ink, 3, 2, radius) == [1.0, 0.0, 0.0]


def test_contrast_linearizes_both_sides_of_the_transfer_cutoff(kernels):
    rgb = bytes([10, 10, 10, 11, 11, 11])
    ratio, ink, bg = kernels.measure_region_contrast(rgb, b"\x00\xff", 2, 1, 1)
    assert bg == pytest.approx(0.003035269835488375, abs=1e-15)
    assert ink == pytest.approx(0.003346535763899161, abs=1e-15)
    assert ratio == pytest.approx((0.003346535763899161 + 0.05) / (0.003035269835488375 + 0.05), abs=1e-14)


def test_halo_excludes_inside_and_outside_and_uses_strict_threshold(kernels):
    original = bytes(18)
    clean = bytes.fromhex("ffffff 0a0000 ffff00 000900 00000b ffffff")
    mask = bitmap("#..", "...")
    assert kernels.detect_halo_artifacts(original, clean, mask, 3, 2, 1, 10) == [1, 11, 3]
    assert kernels.detect_halo_artifacts(original, clean, mask, 3, 2, 1, 11) == [0, 11, 3]
    assert kernels.detect_halo_artifacts(original, clean, mask, 3, 2, 0, 10) == [0, 0, 0]
    assert kernels.detect_halo_artifacts(original, clean, mask, 3, 2, 2**150, 10) == [3, 255, 5]


def test_ssim_uses_only_complete_unmasked_tiles_and_averages_them(kernels):
    original = bytes(17 * 8)
    final = bytes.fromhex("00" * 8 + "ff" * 9) * 8
    expected_dark_to_white = 6.5025 / (255**2 + 6.5025)
    assert kernels.compute_patch_ssim(original, final, 17, 8, bytes(136)) == pytest.approx(
        (1 + expected_dark_to_white) / 2, abs=1e-14
    )
    assert kernels.compute_patch_ssim(original, final, 17, 8, bytes(8) + b"\x80" + bytes(127)) == 1.0


def test_ssim_falls_back_to_unmasked_population_statistics(kernels):
    assert kernels.compute_patch_ssim(bytes([0, 2, 9]), bytes([2, 0, 200]), 3, 1, b"\0\0\xff") == pytest.approx(
        56.5225 / 60.5225, abs=1e-14
    )
    assert kernels.compute_patch_ssim(bytes(64), bytes([200]) * 64, 8, 8, b"\xff" + bytes(63)) == pytest.approx(
        6.5025 / (200**2 + 6.5025), abs=1e-14
    )
    assert kernels.compute_patch_ssim(b"\0", b"\xff", 1, 1, b"\xff") == 1.0


def test_residual_ink_filters_specks_and_reports_weighted_centroid(kernels):
    positions = (0, 7, 3, 4, 5, 18)
    mask = bytes(128 if i in positions else 0 for i in range(24))
    gray = bytes(100 if i in positions[:2] else 140 if i in positions[2:] else 0 for i in range(24))
    # Two diagonal pixels and three horizontal pixels survive; the remote speck does not.
    assert kernels.detect_residual_ink(gray, mask, 6, 4, 120, 20, 2) == [5, 3, 2, 0]
    assert kernels.detect_residual_ink(gray, mask, 6, 4, 120, 21, 1) == [0, 0, -1, -1]
    assert kernels.detect_residual_ink(gray, mask, 6, 4, 120, 0, 2**150) == [0, 0, -1, -1]


def test_ink_bounds_are_tight_and_include_equality(kernels):
    original = bytes(18)
    final = bytes.fromhex("000000 000400 000005 000000 040000 000000")
    assert kernels.compute_ink_bounds(original, final, 3, 2, 4) == [1, 0, 2, 2, 3]
    assert kernels.compute_ink_bounds(original, final, 3, 2, 5) == [2, 0, 1, 1, 1]
    assert kernels.compute_ink_bounds(original, final, 3, 2, 6) == [0, 0, 0, 0, 0]
    assert kernels.compute_ink_bounds(original, final, 3, 2, 0) == [0, 0, 3, 2, 6]
    assert kernels.compute_ink_bounds(original, original, 3, 2, 0) == [0, 0, 0, 0, 0]


@pytest.mark.parametrize(("name", "args", "message"), [
    ("detect_outline_bleed", (b"", b"", 0, 1, b"", 0, 0), "invalid image dimensions"),
    ("detect_outline_bleed", (b"\0", b"\0", 1, 1, b"\0", 256, 0), "luma and difference thresholds"),
    ("measure_region_contrast", (b"\0" * 3, b"\0", 1, 1, -1), "radius must be"),
    ("measure_region_contrast", (bytearray(3), b"\0", 1, 1, 0), "pixel buffer must be"),
    ("detect_halo_artifacts", (b"\0" * 3, b"\0" * 3, b"\0", 1, 1, True, 0), "radius must be"),
    ("detect_halo_artifacts", (b"\0" * 3, b"", b"\0", 1, 1, 1, 0), "pixel buffer must be"),
    ("compute_patch_ssim", (b"\0", b"\0", sys.maxsize, 2, b"\0"), "invalid image dimensions"),
    ("compute_patch_ssim", (b"\0", b"\0", 1, 1, memoryview(b"\0")), "pixel buffer must be"),
    ("detect_residual_ink", (b"\0", b"\1", 1, 1, 255, 0, 0), "minimum cluster size must be"),
    ("detect_residual_ink", (b"\0", b"\1", 1, 1, 255, 0, 1.0), "minimum cluster size must be"),
    ("compute_ink_bounds", (b"\0" * 3, b"\0" * 3, 1, 1, 2**150), "luma and difference thresholds"),
    ("compute_ink_bounds", (b"\0" * 3, b"\0" * 3, True, 1, 1), "invalid image dimensions"),
])
def test_invalid_dimensions_buffers_and_ranges_raise_value_error(kernels, name, args, message):
    with pytest.raises(ValueError, match=message):
        getattr(kernels, name)(*args)


def calls(width, height, original, final, mask, rgb, changed, radius):
    return {
        "detect_outline_bleed": (original, final, width, height, mask, 200, 20),
        "measure_region_contrast": (rgb, mask, width, height, radius),
        "detect_halo_artifacts": (rgb, changed, mask, width, height, radius, 20),
        "compute_patch_ssim": (original, final, width, height, mask),
        "detect_residual_ink": (final, mask, width, height, 220, 20, 2),
        "compute_ink_bounds": (rgb, changed, width, height, 20),
    }


def test_randomized_native_parity():
    dispatch = importlib.import_module("qacore")
    rng = random.Random(6113)
    for w, h in [(1, 1), (1, 7), (7, 1), (8, 8), (9, 17), (31, 23), (100, 81)]:
        size = w * h
        original, final = rng.randbytes(size), rng.randbytes(size)
        rgb, changed = rng.randbytes(size * 3), rng.randbytes(size * 3)
        for radius in (0, 1, 4, w + h):
            mask = bytes(255 if rng.randrange(9) == 0 else 0 for _ in range(size))
            for name, args in calls(w, h, original, final, mask, rgb, changed, radius).items():
                expected = getattr(reference, name)(*args)
                actual = getattr(dispatch, name)(*args)
                if name in {"measure_region_contrast", "compute_patch_ssim"}:
                    assert actual == pytest.approx(expected, rel=1e-13, abs=1e-14)
                else:
                    assert actual == expected


def test_dispatch_can_force_python(monkeypatch):
    dispatch = importlib.import_module("qacore")
    with monkeypatch.context() as env:
        env.setenv("REVAYAT_QACORE", "python")
        try:
            assert importlib.reload(dispatch).BACKEND == "python"
            assert dispatch.detect_outline_bleed is reference.detect_outline_bleed
        finally:
            env.undo()
            importlib.reload(dispatch)
