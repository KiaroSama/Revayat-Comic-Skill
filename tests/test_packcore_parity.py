"""The same package and raster contracts apply with or without the native wheel."""

import importlib
import random
from importlib.util import find_spec

import pytest


@pytest.fixture(params=["python", "dispatch"])
def kernels(request):
    if request.param == "python":
        return importlib.import_module("packcore.kernels")
    return importlib.import_module("packcore")


def test_dispatch_package_exists():
    assert find_spec("packcore") is not None


def test_python_override(monkeypatch):
    dispatch = importlib.import_module("packcore")
    python = importlib.import_module("packcore.kernels")
    try:
        with monkeypatch.context() as env:
            env.setenv("REVAYAT_PACKCORE", "python")
            importlib.reload(dispatch)
            assert dispatch.BACKEND == "python"
            for name in dispatch.__all__[1:]:
                assert getattr(dispatch, name) is getattr(python, name)
    finally:
        importlib.reload(dispatch)


def test_natural_sort_uses_exact_magnitude_and_raw_ties(kernels):
    names = ["P10", "p۲", "p٠٢", "p2", "P2", "p2", "p9", "P", "", "p²", "p٣x"]
    assert kernels.natural_sort_order(names) == [8, 7, 4, 3, 5, 2, 1, 10, 6, 0, 9]
    huge = "9" * 4500
    assert kernels.natural_sort_order(["p1" + "0" * 4500, "p" + huge, "p0" + huge]) == [2, 1, 0]
    assert kernels.natural_sort_order(["p\udfff", "p", "p\ud800", "p😀"]) == [2, 0, 1, 3]
    assert kernels.natural_sort_order([]) == []


def test_rgb_summary_hashes_bytes_and_floors_mean(kernels):
    assert kernels.analyze_rgb_page(bytes(3), 1, 1) == [1253111735, 0, 0, 0, 1]
    data = bytes([244, 244, 244, 245, 245, 245, 255, 0, 0])
    assert kernels.analyze_rgb_page(data, 3, 1) == [2212677221, 76, 245, 18833, 2]


def test_dimensions_report_bounds_and_wrong_types_by_row(kernels):
    rows = [[2, 3], [3, 2], [1, 3], [2, 4], [3, 3], [True, 3], [2.0, 3], [0, 3], [2, -3]]
    assert kernels.validate_page_dimensions(rows, 1.5, 2, 6) == [2, 3, 4, 5, 6, 7, 8]
    width = 2**63
    assert kernels.validate_page_dimensions([[width, width], [width, width + 1]], 1, 1, width**2) == [1]
    width = 10**400
    assert kernels.validate_page_dimensions([[width, width], [width, width + 1]], 1, 1, width**2) == [1]
    assert kernels.validate_page_dimensions([], 1, 1, 1) == []


def test_dimensions_aspect_matches_exact_integer_division(kernels):
    width, height = 9007199254740995, 9007199254740993
    assert width / height == 1.0000000000000002
    assert kernels.validate_page_dimensions([[width, height]], width / height, 1, width * height) == []


def test_pdf_layout_caps_long_edge_and_preserves_physical_scale(kernels):
    assert kernels.compute_pdf_page_layout(600, 900, 300, 1000) == [144, 216, 300, 1]
    assert kernels.compute_pdf_page_layout(600, 900, 300, 108) == [72, 108, 600, 0.5]
    assert kernels.compute_pdf_page_layout(1, 1, 72, 1) == [1, 1, 72, 1]


def test_diff_reports_partial_tiles_in_row_major_order(kernels):
    original = bytes([10] * 27)
    final = bytearray(original)
    for pixel, channel, value in ((0, 2, 18), (1, 1, 0), (2, 2, 255), (4, 0, 21), (8, 0, 40)):
        final[3 * pixel + channel] = value
    assert kernels.diff_raster_tiles(original, bytes(final), 3, 3, 2, 8) == [
        [0, 0, 2, 11], [1, 0, 1, 245], [1, 1, 1, 30],
    ]
    assert kernels.diff_raster_tiles(original, bytes(final), 3, 3, 10**100, 8) == [[0, 0, 4, 245]]
    assert kernels.diff_raster_tiles(original, bytes(final), 3, 3, 1, 255) == []


def test_histogram_is_integer_luma_and_counts_every_pixel(kernels):
    data = bytes(range(256))
    greys = bytes(channel for value in data for channel in (value, value, value))
    assert kernels.compute_grayscale_histogram(greys, 16, 16) == [1] * 256
    hist = kernels.compute_grayscale_histogram(bytes([255, 0, 0, 0, 255, 0, 0, 0, 255]), 3, 1)
    assert [(i, count) for i, count in enumerate(hist) if count] == [(28, 1), (76, 1), (149, 1)]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("natural_sort_order", (("p1",),)),
        ("natural_sort_order", ("p1",)),
        ("natural_sort_order", (["p1", 2],)),
        ("analyze_rgb_page", (bytearray(3), 1, 1)),
        ("analyze_rgb_page", (bytes(3), True, 1)),
        ("analyze_rgb_page", (bytes(3), 1, 0)),
        ("analyze_rgb_page", (bytes(3), 2**100, 2**100)),
        ("analyze_rgb_page", (bytes(4), 1, 1)),
        ("validate_page_dimensions", ((), 1, 1, 1)),
        ("validate_page_dimensions", ([(1, 1)], 1, 1, 1)),
        ("validate_page_dimensions", ([[1]], 1, 1, 1)),
        ("validate_page_dimensions", ([[1, 1, 1]], 1, 1, 1)),
        ("validate_page_dimensions", ([], float("nan"), 1, 1)),
        ("validate_page_dimensions", ([], float("inf"), 1, 1)),
        ("validate_page_dimensions", ([], 0.99, 1, 1)),
        ("validate_page_dimensions", ([], True, 1, 1)),
        ("validate_page_dimensions", ([], 1, 0, 1)),
        ("validate_page_dimensions", ([], 1, 1.0, 1)),
        ("validate_page_dimensions", ([], 1, 1, -1)),
        ("compute_pdf_page_layout", (False, 1, 72, 1)),
        ("compute_pdf_page_layout", (1, 0, 72, 1)),
        ("compute_pdf_page_layout", (10**400, 1, 72, 1)),
        ("compute_pdf_page_layout", (10**307, 1, 72, 1)),
        ("compute_pdf_page_layout", (1, 1, float("inf"), 1)),
        ("compute_pdf_page_layout", (1, 1, 0, 1)),
        ("compute_pdf_page_layout", (1, 1, 5e-324, 1)),
        ("compute_pdf_page_layout", (1, 1, 72, float("nan"))),
        ("compute_pdf_page_layout", (1, 1, 72, "100")),
        ("compute_pdf_page_layout", (1, 1, 72, -1)),
        ("compute_pdf_page_layout", (600, 900, 300, 5e-324)),
        ("diff_raster_tiles", (bytes(3), bytes(2), 1, 1, 1, 0)),
        ("diff_raster_tiles", (bytes(2), bytes(3), 1, 1, 1, 0)),
        ("diff_raster_tiles", (bytes(3), memoryview(bytes(3)), 1, 1, 1, 0)),
        ("diff_raster_tiles", (bytes(3), bytes(3), -1, 1, 1, 0)),
        ("diff_raster_tiles", (bytes(3), bytes(3), 1, 1, 0, 0)),
        ("diff_raster_tiles", (bytes(3), bytes(3), 1, 1, True, 0)),
        ("diff_raster_tiles", (bytes(3), bytes(3), 1, 1, 1, -1)),
        ("diff_raster_tiles", (bytes(3), bytes(3), 1, 1, 1, 256)),
        ("diff_raster_tiles", (bytes(3), bytes(3), 1, 1, 1, 2.0)),
        ("compute_grayscale_histogram", (bytes(3), 1, 2)),
        ("compute_grayscale_histogram", ([], 1, 1)),
        ("compute_grayscale_histogram", (b"", 0, 0)),
    ],
)
def test_validation_raises_value_error(kernels, name, args):
    with pytest.raises(ValueError, match=".+"):
        getattr(kernels, name)(*args)


def test_generated_rasters_match_reference(kernels):
    rng = random.Random(0x5041434B)
    reference = importlib.import_module("packcore.kernels")
    for width, height, tile in [(1, 1, 1), (17, 9, 4), (3, 31, 6), (41, 29, 16)]:
        original, final = (rng.randbytes(width * height * 3) for _ in range(2))
        for name, args in (
            ("analyze_rgb_page", (original, width, height)),
            ("compute_grayscale_histogram", (original, width, height)),
            ("diff_raster_tiles", (original, final, width, height, tile, 63)),
        ):
            assert getattr(kernels, name)(*args) == getattr(reference, name)(*args)
