"""Balloon mask geometry, validation, and native/reference parity."""

import importlib
import random
from itertools import product

import pytest

MAX_I64 = 2**63 - 1
MIN_I64 = -(2**63)


def bitmap(*rows):
    return bytes(255 if pixel == "#" else 0 for row in rows for pixel in row)


@pytest.fixture(params=["maskcore.kernels", "maskcore"])
def kernels(request):
    return importlib.import_module(request.param)


def test_dispatch_reporting_and_override(monkeypatch):
    import maskcore
    from maskcore import kernels as reference

    try:
        monkeypatch.setenv("REVAYAT_MASKCORE", "python")
        importlib.reload(maskcore)
        assert maskcore.BACKEND == "python"
        assert maskcore.flood_balloon_interior is reference.flood_balloon_interior
    finally:
        monkeypatch.undo()
        importlib.reload(maskcore)
    assert maskcore.BACKEND in {"python", "rust"}
    if maskcore.BACKEND == "rust":
        import maskcore_rs

        assert maskcore.flood_balloon_interior is maskcore_rs.flood_balloon_interior


def test_flood_stops_at_thin_grey_wall_and_gradient_is_strict(kernels):
    gray = bytes([250, 250, 250, 235, 250, 250]) * 3
    args = (gray, 6, 3, 0, 1, 230)
    assert kernels.flood_balloon_interior(*args, 15, 0) == bitmap("##....", "##....", "##....")
    assert kernels.flood_balloon_interior(*args, 16, 0) == bitmap("######", "######", "######")
    assert kernels.flood_balloon_interior(*args, 15, 1) == bitmap("#.....", "#.....", "#.....")


def test_flood_uses_cardinal_connectivity_and_rejects_blocked_seed(kernels):
    gray = bitmap("#.#", ".#.", "#.#")
    assert kernels.flood_balloon_interior(gray, 3, 3, 1, 1, 233, 256, 0) == bitmap("...", ".#.", "...")
    assert kernels.flood_balloon_interior(gray, 3, 3, 0, 1, 233, 256, 0) == bytes(9)
    assert kernels.flood_balloon_interior(gray, 3, 3, 0, 0, 233, 0, 0) == bytes(9)


def test_morphology_square_window_clips_at_image_edges(kernels):
    solid = bitmap("###", "###")
    hole = bitmap("###", ".##")
    assert kernels.erode_linf(hole, 3, 2, 1) == bitmap("..#", "..#")
    assert kernels.erode_linf(solid, 3, 2, MAX_I64) == solid
    assert kernels.erode_linf(hole, 3, 2, MAX_I64) == bytes(6)
    assert kernels.dilate_linf(bitmap("#..", "..."), 3, 2, 1) == bitmap("##.", "##.")
    assert kernels.dilate_linf(bitmap("#..", "..."), 3, 2, MAX_I64) == solid
    assert kernels.dilate_linf(hole, 3, 2, 0) == hole


def test_morphology_matches_a_naive_square_window(kernels):
    randomizer = random.Random(1729)
    for width, height, radius in product([1, 2, 5], [1, 3, 4], [0, 1, 2, 9]):
        mask = bytes(randomizer.choice([0, 255]) for _ in range(width * height))
        for kernel, select in [(kernels.erode_linf, min), (kernels.dilate_linf, max)]:
            expected = bytes(
                select(
                    mask[row * width + col]
                    for row in range(max(0, y - radius), min(height, y + radius + 1))
                    for col in range(max(0, x - radius), min(width, x + radius + 1))
                )
                for y, x in product(range(height), range(width))
            )
            assert kernel(mask, width, height, radius) == expected


def test_partition_preserves_outer_edges_and_does_not_jump_over_background(kernels):
    boxes = [[0, 0, 1, 1], [6, 0, 1, 1]]
    assert kernels.partition_voronoi_lobes(bitmap("#######"), 7, 1, 0, 0, boxes, 1) == [0, 0, 0, -1, -1, 1, 1]
    assert kernels.partition_voronoi_lobes(bitmap("###.###"), 7, 1, 0, 0, boxes, MAX_I64) == [0, 0, 0, -1, 1, 1, 1]


def test_partition_uses_rectangle_then_exact_center_then_index(kernels):
    one = b"\x01"
    pick = kernels.partition_voronoi_lobes
    # Rectangle containment outranks a nearer center.
    assert pick(one, 1, 1, 0, 0, [[1, 0, 1, 1], [0, 0, 10, 10]], 0) == [1]
    assert pick(one, 1, 1, 0, 0, [[0, 0, 8, 8], [0, 0, 2, 2]], 0) == [1]
    assert pick(one, 1, 1, 0, 0, [(0, 0, 2, 2), (0, 0, 2, 2)], 0) == [0]
    mask = bitmap("#######")
    assert pick(mask, 7, 1, 0, 0, [[0, 0, 1, 1], [3, 0, 1, 1], [6, 0, 1, 1]], 0) == [0, 0, 1, 1, 1, 2, 2]


def test_partition_keeps_full_i64_distance_order(kernels):
    pick = kernels.partition_voronoi_lobes
    args = (b"\xff", 1, 1)
    assert pick(*args, MAX_I64, MAX_I64, [[MIN_I64, MIN_I64, 1, 1], [MIN_I64 + 1, MIN_I64, 1, 1]], 0) == [1]
    assert pick(*args, MIN_I64, MIN_I64, [[MAX_I64, MAX_I64, 1, 1], [MAX_I64 - 1, MAX_I64, 1, 1]], 0) == [1]
    assert pick(*args, MAX_I64, 0, [[0, 0, MAX_I64, 1], [0, 0, MAX_I64 - 1, 1]], 0) == [0]
    boxes = [[MIN_I64, MIN_I64, 4, 4], [MIN_I64, MIN_I64, 2, 2]]
    assert pick(*args, MIN_I64, MIN_I64, boxes, 0) == [1]
    # Rectangle tie; the off-axis term makes the doubled center sum exceed u128.
    boxes = [[MAX_I64, MAX_I64, MAX_I64, MAX_I64], [MAX_I64, MAX_I64, MAX_I64 - 1, MAX_I64]]
    assert pick(*args, MIN_I64, MIN_I64, boxes, 0) == [1]


def test_strip_uses_8_connectivity_and_both_inclusive_cutoffs(kernels):
    mask = bytes([1, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 7, 0])
    kept = bitmap("....", "....", "....", "..#.")
    stripped = bitmap("#...", ".#..", "....", "....")
    strip = kernels.strip_perimeter_contours
    assert strip(mask, 4, 4, 2 / 16, 0.5) == (kept, stripped)
    all_kept = bitmap("#...", ".#..", "....", "..#.")
    assert strip(mask, 4, 4, 3 / 16, 0.5) == (all_kept, bytes(16))
    assert strip(mask, 4, 4, 2 / 16, 0.75) == (all_kept, bytes(16))
    assert strip(bitmap(".....", ".###.", "....."), 5, 3, 0, 0) == (
        bitmap(".....", ".###.", "....."), bytes(15)
    )
    assert strip(bitmap(".....", "#####", "....."), 5, 3, 0, 1) == (
        bytes(15), bitmap(".....", "#####", ".....")
    )


INVALID = [
    ("flood_balloon_interior", (b"", 0, 1, 0, 0, 0, 0, 0), "dimensions"),
    ("flood_balloon_interior", (b"", MAX_I64, MAX_I64, 0, 0, 0, 0, 0), "dimensions"),
    ("flood_balloon_interior", (b"", 1, 1, 0, 0, 0, 0, 0), "buffer"),
    ("flood_balloon_interior", (b"0", 1, 1, -1, 0, 0, 0, 0), "seed"),
    ("flood_balloon_interior", (b"0", 1, 1, 0, 1, 0, 0, 0), "seed"),
    ("flood_balloon_interior", (b"0", 1, 1, 0, 0, 256, 0, 0), "wall_luma"),
    ("flood_balloon_interior", (b"0", 1, 1, 0, 0, 0, -1, 0), "grad_thresh"),
    ("flood_balloon_interior", (b"0", 1, 1, 0, 0, 0, 257, 0), "grad_thresh"),
    ("flood_balloon_interior", (b"0", 1, 1, 0, 0, 0, 0, -1), "min_inset"),
    ("erode_linf", (b"", 1, -1, 0), "dimensions"),
    ("erode_linf", (b"", MAX_I64 + 1, 1, 0), "dimensions"),
    ("erode_linf", (b"", 1, 1, 0), "buffer"),
    ("erode_linf", (b"\x01", 1, 1, 0), "binary"),
    ("erode_linf", (b"\xff", 1, 1, -1), "radius"),
    ("dilate_linf", (b"", -1, 1, 0), "dimensions"),
    ("dilate_linf", (b"", 1, 1, 0), "buffer"),
    ("dilate_linf", (b"\x80", 1, 1, 1), "binary"),
    ("dilate_linf", (b"\xff", 1, 1, -1), "radius"),
    ("partition_voronoi_lobes", (b"", 1, 0, 0, 0, [[0, 0, 1, 1]], 0), "dimensions"),
    ("partition_voronoi_lobes", (b"", 1, 1, 0, 0, [[0, 0, 1, 1]], 0), "buffer"),
    ("partition_voronoi_lobes", (b"0", 1, 1, MIN_I64 - 1, 0, [[0, 0, 1, 1]], 0), "origin"),
    ("partition_voronoi_lobes", (b"0", 1, 1, 0, 0, [], 0), "boxes"),
    ("partition_voronoi_lobes", (b"0", 1, 1, 0, 0, [[0, 0, 1]], 0), "box must"),
    ("partition_voronoi_lobes", (b"0", 1, 1, 0, 0, [[0, 0, 0, 1]], 0), "box must"),
    ("partition_voronoi_lobes", (b"0", 1, 1, 0, 0, [[MAX_I64 + 1, 0, 1, 1]], 0), "box must"),
    ("partition_voronoi_lobes", (b"0", 1, 1, 0, 0, [[0, 0, 1, 1]], -1), "seam_margin"),
    ("strip_perimeter_contours", (b"", 1, 0, 0.1, 0.1), "dimensions"),
    ("strip_perimeter_contours", (b"", 1, 1, 0.1, 0.1), "buffer"),
    ("strip_perimeter_contours", (b"0", 1, 1, -0.1, 0.1), "min_area_ratio"),
    ("strip_perimeter_contours", (b"0", 1, 1, 0.1, 1.1), "min_span_ratio"),
    ("strip_perimeter_contours", (b"0", 1, 1, float("nan"), 0.1), "min_area_ratio"),
    ("strip_perimeter_contours", (b"0", 1, 1, 0.1, float("inf")), "min_span_ratio"),
]


@pytest.mark.parametrize(("name", "args", "message"), INVALID)
def test_invalid_input_raises_value_error(kernels, name, args, message):
    with pytest.raises(ValueError, match=message):
        getattr(kernels, name)(*args)


def test_generated_masks_match_the_reference():
    import maskcore
    from maskcore import kernels as reference

    randomizer = random.Random(2981)
    for width, height in [(1, 41), (67, 1), (32, 41), (63, 67)]:
        n = width * height
        gray = bytes(randomizer.randrange(224, 256) for _ in range(n))
        mask = bytes(randomizer.choice([0, 0, 255]) for _ in range(n))
        cases = (
            ("flood_balloon_interior", (gray, width, height, width // 2, height // 2, 230, 14, 2)),
            ("erode_linf", (mask, width, height, 4)),
            ("dilate_linf", (mask, width, height, 4)),
            ("partition_voronoi_lobes", (mask, width, height, -2, 3, [[0, 0, 11, 9], [7, 2, 3, 8]], 3)),
            ("strip_perimeter_contours", (mask, width, height, 0.05, 0.3)),
        )
        for name, args in cases:
            assert getattr(maskcore, name)(*args) == getattr(reference, name)(*args)
