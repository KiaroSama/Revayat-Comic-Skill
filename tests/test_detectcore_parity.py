"""Detection geometry, input boundaries, and native/reference parity."""

import importlib
import math
import random

import pytest


@pytest.fixture(params=["detectcore.kernels", "detectcore"])
def kernels(request):
    return importlib.import_module(request.param)


def bitmap(*rows):
    return bytes(255 if pixel == "#" else 0 for row in rows for pixel in row)


def test_dispatch_override(monkeypatch):
    import detectcore
    from detectcore import kernels as reference

    if detectcore.BACKEND == "rust":
        import detectcore_rs

        assert detectcore.find_panel_gutters is detectcore_rs.find_panel_gutters
    with monkeypatch.context() as patch:
        patch.setenv("REVAYAT_DETECTCORE", "python")
        importlib.reload(detectcore)
        assert detectcore.BACKEND == "python"
        assert detectcore.find_panel_gutters is reference.find_panel_gutters
    importlib.reload(detectcore)


def test_gutters_trim_and_split_horizontal_first(kernels):
    gray = bytearray([252]) * (60 * 60)
    for y in range(2, 58):
        for x in range(2, 58):
            if not 28 <= x < 32 and not 28 <= y < 32:
                gray[y * 60 + x] = 0
    gray[17] = 0  # The trim accepts one blemish on this border.
    assert kernels.find_panel_gutters(bytes(gray), 60, 60, 240, 4, 2) == [
        [2, 2, 26, 26],
        [32, 2, 26, 26],
        [2, 32, 26, 26],
        [32, 32, 26, 26],
    ]


def test_gutters_require_pure_background_and_minimum_leaves(kernels):
    gray = bytes(26 * 24) + bytes([255]) * (26 * 4) + bytes(26 * 23)
    assert kernels.find_panel_gutters(gray, 26, 51, 240, 4, 0) == [[0, 0, 26, 51]]
    gray += bytes(26)
    blemished = gray[: 26 * 25] + b"\x00" + gray[26 * 25 + 1 :]
    assert kernels.find_panel_gutters(blemished, 26, 52, 240, 4, 0) == [[0, 0, 26, 52]]
    assert kernels.find_panel_gutters(gray, 26, 52, 240, 4, 0) == [
        [0, 0, 26, 24],
        [0, 28, 26, 24],
    ]


def test_components_merge_diagonals_and_sort_right_first(kernels):
    mask = bitmap("#...##", ".#....", "..#...", ".....#")
    assert kernels.connected_components_boxes(mask, 6, 4, 2, 3) == [
        [4, 0, 2, 1, 2],
        [0, 0, 3, 3, 3],
    ]
    assert kernels.connected_components_boxes(b"\x01\x80", 2, 1, 2, 2) == [
        [0, 0, 2, 1, 2]
    ]


def test_balloons_reject_open_paper_and_use_four_neighbors(kernels):
    gray = bitmap("#######", "#......", "#.#....", "#..#...", "#......", ".......")
    assert kernels.detect_speech_balloons(gray, 7, 6, 220, 1, 1.0, 1.0) == [
        [2, 2, 1, 1, 1],
        [3, 3, 1, 1, 1],
    ]


def test_balloons_measure_the_distinct_boundary_ring(kernels):
    gray = bytes([0, 0, 0, 0, 250, 195, 195, 195, 195])
    assert kernels.detect_speech_balloons(gray, 3, 3, 220, 1, 1.0, 1.0) == [
        [1, 1, 1, 1, 1]
    ]
    gray = bytes([195]) + gray[1:]
    assert kernels.detect_speech_balloons(gray, 3, 3, 220, 1, 1.0, 1.0) == []
    l_shape = bitmap("....", ".##.", ".#..", "....")
    assert kernels.detect_speech_balloons(l_shape, 4, 4, 220, 3, 3 / 16, 0.75) == [
        [1, 1, 2, 2, 3]
    ]
    assert kernels.detect_speech_balloons(l_shape, 4, 4, 220, 3, 3 / 16, 0.76) == []
    assert kernels.detect_speech_balloons(l_shape, 4, 4, 220, 3, 2 / 16, 0.75) == []


def test_merge_text_lines_is_transitive_in_both_axes(kernels):
    boxes = [[32, 13, 3, 3], [6, 1, 4, 5], [0, 0, 4, 5], [7, 8, 5, 5]]
    assert kernels.merge_text_lines(boxes, 2, 2, 0.75) == [
        [0, 0, 12, 13],
        [32, 13, 3, 3],
    ]
    assert kernels.merge_text_lines([[0, 0, 4, 4], [1, 8, 4, 4]], 0, 3, 1.0) == [
        [0, 0, 4, 4],
        [1, 8, 4, 4],
    ]


def test_reading_order_uses_row_transitivity_rtl_edges_and_index_ties(kernels):
    boxes = [[4, 7, 10, 3], [8, 4, 6, 3], [2, 1, 7, 3], [0, 20, 20, 4], [8, 4, 6, 3]]
    assert kernels.sort_reading_order(boxes, True, 3) == [0, 1, 4, 2, 3]
    assert kernels.sort_reading_order(boxes, False, 3) == [2, 0, 1, 4, 3]
    assert kernels.sort_reading_order([[3, 1, 2, 2], [0, 0, 2, 2]], True, 0) == [0, 1]


def test_stroke_width_combines_both_axes_within_box(kernels):
    gray = bitmap("...", "..#", ".##")
    assert kernels.estimate_stroke_width(gray, 3, 3, [0, 1, 2, 2]) == 1.5
    assert kernels.estimate_stroke_width(gray, 3, 3, [0, 0, 3, 1]) == 0.0
    assert kernels.estimate_stroke_width(gray, 3, 3, [3, 3, 0, 0]) == 0.0
    assert kernels.estimate_stroke_width(bytes([8, 31]), 2, 1, [0, 0, 2, 1]) == 0.0
    assert kernels.estimate_stroke_width(bytes([8, 32]), 2, 1, [0, 0, 2, 1]) == 1.0
    mixed = bytes([0, 0, 255, 255])
    assert kernels.estimate_stroke_width(mixed, 4, 1, [0, 0, 4, 1]) == 1.0


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("find_panel_gutters", (b"", 0, 1, 1, 1, 0)),
        ("find_panel_gutters", (b"", 1, 1, 1, 1, 0)),
        ("find_panel_gutters", (bytearray(1), 1, 1, 1, 1, 0)),
        ("find_panel_gutters", (b"x", True, 1, 1, 1, 0)),
        ("find_panel_gutters", (b"x", 1, 1, 256, 1, 0)),
        ("find_panel_gutters", (b"x", 1, 1, 0, 0, 0)),
        ("find_panel_gutters", (b"x", 1, 1, 0, 1, -1)),
        ("find_panel_gutters", (b"", 2**63 - 1, 2**63 - 1, 0, 1, 0)),
        ("connected_components_boxes", (b"x", 1, 1, 2, 1)),
        ("detect_speech_balloons", (b"x", 1, 1, -1, 1, 1.0, 0.0)),
        ("detect_speech_balloons", (b"x", 1, 1, 0, 0, 1.0, 0.0)),
        ("detect_speech_balloons", (b"x", 1, 1, 0, 1, 0.0, 0.0)),
        ("detect_speech_balloons", (b"x", 1, 1, 0, 1, 1.0, math.nan)),
        ("merge_text_lines", ([[0, 0, 1]], 0, 0, 1.0)),
        ("merge_text_lines", ([[2**63 - 1, 0, 1, 1]], 0, 0, 1.0)),
        ("merge_text_lines", ([], -1, 0, 1.0)),
        ("merge_text_lines", ([], 0, -1, 1.0)),
        ("merge_text_lines", ([], 0, 0, math.inf)),
        ("sort_reading_order", ([[0, 0, 0, 1]], True, 0)),
        ("sort_reading_order", ([], 1, 0)),
        ("sort_reading_order", ([], False, -1)),
        ("estimate_stroke_width", (b"x", 1, 1, [0, 0, 2, 1])),
        ("estimate_stroke_width", (b"x", 1, 1, [-1, 0, 0, 0])),
    ],
)
def test_invalid_arguments_raise_value_error(kernels, name, args):
    with pytest.raises(ValueError):
        getattr(kernels, name)(*args)


def test_random_small_images_and_boxes_match_native():
    native = importlib.import_module("detectcore")
    from detectcore import kernels as reference

    randomizer = random.Random(381)
    for _ in range(30):
        w, h = (randomizer.randint(1, 16) for _ in range(2))
        gray = bytes(randomizer.choice((0, 180, 219, 255)) for _ in range(w * h))
        boxes = [
            [randomizer.randrange(40) for _ in range(2)] + [4, 6] for _ in range(20)
        ]
        calls = [
            ("find_panel_gutters", (gray, w, h, 240, 3, 4)),
            ("connected_components_boxes", (gray, w, h, 1, w * h)),
            ("detect_speech_balloons", (gray, w, h, 220, 1, 0.8, 0.4)),
            ("merge_text_lines", (boxes, 4, 5, 0.5)),
            ("sort_reading_order", (boxes, True, 3)),
            ("estimate_stroke_width", (gray, w, h, [0, 0, w, h])),
        ]
        for name, args in calls:
            assert getattr(native, name)(*args) == getattr(reference, name)(*args), name
