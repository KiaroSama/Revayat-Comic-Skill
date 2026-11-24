"""Balloon layout contracts and Python/native parity."""

import importlib
import itertools
import os
import random

import pytest


@pytest.fixture(params=["reference", "dispatch"])
def backend(request):
    name = "layoutcore.kernels" if request.param == "reference" else "layoutcore"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        pytest.fail(f"Layout kernel module unavailable: {error}")


def bitmap(*rows):
    return bytes(128 if pixel == "#" else 0 for row in rows for pixel in row)


def test_scan_keeps_leftmost_widest_run_and_resets_at_row_boundary(backend):
    mask = bitmap(".##.##", "##.###", "......", ".....#", "#.....")
    assert backend.scan_mask_spans(mask, 6, 5) == [[1, 3], [3, 6], [0, 0], [5, 6], [0, 1]]


def test_wrap_balances_last_line_and_centers_block(backend):
    assert backend.fit_lines_to_spans([3, 3, 3, 3], 1, 2, 1, [[0, 13]] * 9, 1, 1) == [
        [0, 2, 2, 1, 12], [2, 4, 5, 1, 12],
    ]


def test_wrap_scans_past_infeasible_center_and_intersects_every_row(backend):
    spans = [[0, 12], [3, 12], [8, 16], [0, 9], [7, 16], [0, 12]]
    assert backend.fit_lines_to_spans([6], 0, 2, 0, spans, 1, 0) == [[0, 1, 0, 4, 11]]
    assert backend.fit_lines_to_spans([6], 0, 2, 0, spans, 1, 1) == []
    assert backend.fit_lines_to_spans([3], 0, 2, 0, [[0, 4], [3, 7]], 0, 0) == []


def test_wrap_never_letters_an_empty_row_even_with_zero_width_words(backend):
    assert backend.fit_lines_to_spans([0], 0, 1, 0, [[0, 0]], 0, 0) == []
    assert backend.fit_lines_to_spans([], 0, 1, 0, [[0, 1]], 0, 0) == []
    assert backend.fit_lines_to_spans([0], 0, 1, 0, [[4, 5]], 0, 0) == [[0, 1, 0, 4, 5]]


def test_font_target_weights_area_and_never_enlarges(backend):
    assert backend.harmonize_font_sizes([8, 12, 18, 24, 50], [100, 1, 20, 1, 0], 2, 10) == [
        8, 12, 18, 20, 50,
    ]
    assert backend.harmonize_font_sizes([30, 10], [5, 5], 3, 8) == [13, 10]
    assert backend.harmonize_font_sizes([1, 2], [0, 0], 0, 0) == [1, 2]


def test_clearance_uses_chebyshev_distance_and_first_worst_pixel(backend):
    walls = bitmap("#...", "....", "....", "...#")
    ink = bitmap("..#.", ".#..", "..#.", "....")
    assert backend.check_ink_wall_clearance(ink, walls, 4, 4, 2) == [2, 1, 1, 1]
    assert backend.check_ink_wall_clearance(ink, walls, 4, 4, 1) == [0, 1, -1, -1]
    assert backend.check_ink_wall_clearance(walls, walls, 4, 4, 1) == [2, 0, 0, 0]
    assert backend.check_ink_wall_clearance(ink, bytes(16), 4, 4, 7) == [0, 7, -1, -1]
    assert backend.check_ink_wall_clearance(bytes(16), walls, 4, 4, 7) == [0, 7, -1, -1]


def test_inscribed_rectangle_uses_intersection_and_breaks_equal_area_ties(backend):
    spans = [[1, 9], [3, 8], [2, 7], [4, 7], [0, 0], [1, 9]]
    assert backend.select_largest_inscribed_band(spans, 2, 2) == [3, 0, 4, 3]
    assert backend.select_largest_inscribed_band(spans, 5, 3) == [0, 0, 0, 0]
    assert backend.select_largest_inscribed_band([[2, 6], [2, 4]], 1, 1) == [2, 0, 4, 1]


@pytest.mark.parametrize(("mode", "expected"), [(0, [6, 3, 0]), (1, [8, 3, 1]), (2, [4, 3, 0])])
def test_alignment_clamps_oversize_and_rounds_center_down(backend, mode, expected):
    assert backend.align_lines_rtl([3, 9, 0], [4, 3, 0], [11, 7, 1], mode) == expected


@pytest.mark.parametrize(("name", "args", "reason"), [
    ("scan_mask_spans", (b"", 0, 1), "image dimensions"),
    ("scan_mask_spans", (b"", 1, 0), "image dimensions"),
    ("scan_mask_spans", (b"", 2**100, 1), "image dimensions"),
    ("scan_mask_spans", (b"", 2**32, 2**32), "image dimensions"),
    ("scan_mask_spans", (b"x", True, 1), "image dimensions"),
    ("scan_mask_spans", (bytearray(1), 1, 1), "mask buffer"),
    ("scan_mask_spans", (b"", 1, 1), "mask buffer"),
    ("fit_lines_to_spans", ((1,), 0, 1, 0, [[0, 2]], 0, 0), "word widths"),
    ("fit_lines_to_spans", ([True], 0, 1, 0, [[0, 2]], 0, 0), "word widths"),
    ("fit_lines_to_spans", ([-1], 0, 1, 0, [[0, 2]], 0, 0), "word widths"),
    ("fit_lines_to_spans", ([1], -1, 1, 0, [[0, 2]], 0, 0), "line metrics"),
    ("fit_lines_to_spans", ([1], 0, 0, 0, [[0, 2]], 0, 0), "line metrics"),
    ("fit_lines_to_spans", ([1], 0, 1, -1, [[0, 2]], 0, 0), "line metrics"),
    ("fit_lines_to_spans", ([1], 0, 1, 0, [[0, 2]], -1, 0), "line metrics"),
    ("fit_lines_to_spans", ([1], 0, 1, 0, [[0, 2]], 0, -1), "line metrics"),
    ("fit_lines_to_spans", ([1], 0, 1, 0, [[3, 2]], 0, 0), "spans"),
    ("select_largest_inscribed_band", (None, 1, 1), "spans"),
    ("select_largest_inscribed_band", ([[1]], 1, 1), "spans"),
    ("select_largest_inscribed_band", ([[1, 2, 3]], 1, 1), "spans"),
    ("select_largest_inscribed_band", ([(0, 1)], 1, 1), "spans"),
    ("select_largest_inscribed_band", ([[-1, 1]], 1, 1), "spans"),
    ("select_largest_inscribed_band", ([[0, 2**100]], 1, 1), "spans"),
    ("select_largest_inscribed_band", ([[0, 2]], 0, 1), "minimum band size"),
    ("select_largest_inscribed_band", ([[0, 2]], 1, False), "minimum band size"),
    ("harmonize_font_sizes", ([9], [1, 2], 1, 0), "equal lengths"),
    ("harmonize_font_sizes", ([-1], [1], 1, 0), "font sizes and areas"),
    ("harmonize_font_sizes", ([9], [-1], 1, 0), "font sizes and areas"),
    ("harmonize_font_sizes", ([9], [1], -1, 0), "font limits"),
    ("harmonize_font_sizes", ([9], [1], 1, -1), "font limits"),
    ("check_ink_wall_clearance", (b"x", b"", 1, 1, 1), "mask buffer"),
    ("check_ink_wall_clearance", (b"", b"x", 1, 1, 1), "mask buffer"),
    ("check_ink_wall_clearance", (b"x", b"x", 1, 1, -1), "minimum clearance"),
    ("align_lines_rtl", ([1], [0], [], 0), "equal lengths"),
    ("align_lines_rtl", ([1], [2], [1], 0), "band edges"),
    ("align_lines_rtl", ([-1], [0], [1], 0), "line widths and band edges"),
    ("align_lines_rtl", ([1], [0], [1], 3), "alignment mode"),
    ("align_lines_rtl", ([1], [0], [1], True), "alignment mode"),
])
def test_invalid_inputs_raise_value_error(backend, name, args, reason):
    with pytest.raises(ValueError, match=reason):
        getattr(backend, name)(*args)


def test_large_dimensions_and_costs_do_not_overflow(backend):
    maximum = 2**63 - 1
    assert backend.select_largest_inscribed_band([[2, maximum]] * 3, 1, 1) == [2, 0, maximum - 2, 3]
    assert backend.harmonize_font_sizes([10, maximum], [maximum, maximum], maximum, 0) == [10, maximum]
    assert backend.align_lines_rtl([maximum, 2], [maximum - 1, maximum - 4], [maximum] * 2, 0) == [
        maximum - 1, maximum - 3,
    ]
    assert backend.fit_lines_to_spans([1] * 5, maximum, 1, 0, [[0, maximum]] * 5, 0, 0) == [
        [i, i + 1, i, 0, maximum] for i in range(5)
    ]


def test_clearance_matches_brute_force_on_seeded_masks(backend):
    rng = random.Random(7655)
    for width, height in itertools.product(range(1, 7), repeat=2):
        pixels = width * height
        ink = bytes(rng.randrange(4) == 0 for _ in range(pixels))
        walls = bytes(rng.randrange(8) == 0 for _ in range(pixels))
        wall_coords = [(i % width, i // width) for i, value in enumerate(walls) if value]
        distances = [
            (min(max(abs(i % width - x), abs(i // width - y)) for x, y in wall_coords), i)
            for i, value in enumerate(ink) if value and wall_coords
        ]
        for limit in (0, 1, 2, 4):
            bad = [(distance, i) for distance, i in distances if distance < limit]
            if bad:
                distance, i = min(bad)
                expected = [len(bad), distance, i % width, i // width]
            else:
                expected = [0, limit, -1, -1]
            assert backend.check_ink_wall_clearance(ink, walls, width, height, limit) == expected


def test_dispatch_forced_fallback_without_masking_native(monkeypatch):
    dispatch = importlib.import_module("layoutcore")
    original = dispatch.BACKEND
    if os.environ.get("REVAYAT_TEST_LAYOUTCORE_RUST") == "1":
        assert original == "rust"
    with monkeypatch.context() as patch:
        patch.setenv("REVAYAT_LAYOUTCORE", "python")
        importlib.reload(dispatch)
        assert dispatch.BACKEND == "python"
        assert dispatch.scan_mask_spans(b"\x80", 1, 1) == [[0, 1]]
    importlib.reload(dispatch)
    assert dispatch.BACKEND == original
