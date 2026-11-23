"""Pixel QA behavior and parity checks for the Python and PyO3 kernels."""

import importlib

import pytest


@pytest.fixture(params=["python", "dispatch"])
def kernels(request):
    if request.param == "python":
        return importlib.import_module("pixcore.kernels")
    return importlib.import_module("pixcore")


def test_python_override(monkeypatch):
    dispatch = importlib.import_module("pixcore")
    python = importlib.import_module("pixcore.kernels")
    try:
        with monkeypatch.context() as env:
            env.setenv("REVAYAT_PIXCORE", "python")
            importlib.reload(dispatch)
            assert dispatch.BACKEND == "python"
            for name in dispatch.__all__[1:]:
                assert getattr(dispatch, name) is getattr(python, name)
    finally:
        importlib.reload(dispatch)


def test_outside_mask_ignores_masked_pixels_and_keeps_maximum(kernels):
    assert kernels.outside_mask_diff(
        bytes(9), bytes([0, 8, 0, 0, 0, 9, 255, 0, 0]), b"\0\0\1", 3, 1, 8
    ) == [1, 9]
    assert kernels.outside_mask_diff(bytes(3), b"\1\0\0", b"\0", 1, 1, 1) == [0, 1]


def test_changed_mask_is_binary_bytes_and_threshold_is_strict(kernels):
    assert kernels.changed_mask_rgb(
        bytes([255, 0, 0, 0, 0, 0]), bytes([247, 0, 0, 0, 0, 9]), 2, 1, 8
    ) == b"\0\xff"
    assert kernels.changed_mask_rgb(b"\0\0\0", b"\0\0\0", 1, 1, -1) == b"\xff"


def test_overlap_counts_nonzero_pixels_in_pair_order(kernels):
    changed = bytes([0, 1, 0, 0, 128, 0, 0, 0, 255])
    boxes = [[-1, -1, 3, 3], [1, 0, 3, 3], [0, 1, 3, 3], [5, 5, 2, 2], [2, 2, -1, -1]]
    assert kernels.overlap_changed_pixels(changed, 3, 3, boxes) == [[0, 1, 2], [0, 2, 1], [1, 2, 2]]


@pytest.mark.parametrize(
    ("dark_polarity", "orig"),
    [(True, bytes([40, 40, 40, 40, 40, 41])), (False, bytes([215, 215, 215, 215, 215, 214]))],
)
def test_outline_crossing_respects_gray_boundary_and_safe_mask(kernels, dark_polarity, orig):
    original = orig + orig[3:] * 3
    final = bytes([0, 0, 21] * 3 + [0, 0, 20, 0, 0, 21])
    assert kernels.outline_crossing_pixels(
        original, bytes(15), final, b"\0\0\1\0\0", 5, 1, [-1, 0, 5, 1], dark_polarity, 20
    ) == 1


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("outside_mask_diff", (b"", b"", b"", -1, 0, 8)),
        ("outside_mask_diff", (bytes(3), b"", b"\0", 1, 1, 8)),
        ("outside_mask_diff", (bytes(3), bytes(3), b"", 1, 1, 8)),
        ("changed_mask_rgb", (b"", b"", 0, -1, 8)),
        ("changed_mask_rgb", (b"", bytes(3), 1, 1, 8)),
        ("overlap_changed_pixels", (b"", 1, 1, [])),
        ("overlap_changed_pixels", (b"\0", 1, 1, [[0, 0, 1]])),
        ("overlap_changed_pixels", (b"\0", 1, 1, [[0, 0, 1, 1.5]])),
        ("outline_crossing_pixels", (bytes(3), bytes(3), b"", b"\0", 1, 1, [0, 0, 1, 1], True, 8)),
        ("outline_crossing_pixels", (bytes(3), bytes(3), bytes(3), b"", 1, 1, [0, 0, 1, 1], True, 8)),
        ("outline_crossing_pixels", (bytes(3), bytes(3), bytes(3), b"\0", 1, 1, [0, 0, 1], True, 8)),
    ],
)
def test_malformed_pixel_inputs_raise_value_error(kernels, name, args):
    with pytest.raises(ValueError):
        getattr(kernels, name)(*args)


def test_empty_width_or_height(kernels):
    assert kernels.outside_mask_diff(b"", b"", b"", 0, 5, 8) == [0, 0]
    assert kernels.changed_mask_rgb(b"", b"", 5, 0, 8) == b""
    assert kernels.overlap_changed_pixels(b"", 0, 5, [[0, 0, 1, 1]] * 2) == []
    assert kernels.outline_crossing_pixels(b"", b"", b"", b"", 5, 0, [0, 0, 1, 1], True, 8) == 0


def test_full_page_pixel_parity():
    python = importlib.import_module("pixcore.kernels")
    dispatch = importlib.import_module("pixcore")
    native = importlib.import_module("pixcore_rs") if dispatch.BACKEND == "rust" else python
    width, height = 900, 1291
    size = width * height
    original = b"\xc8\x96\x64" * size
    cleaned = bytearray(original)
    final = bytearray(original)
    safe = bytearray(size)
    for i in range(0, size, 229):
        cleaned[3 * i] = 221
        final[3 * i] = 255
    safe[::458] = b"\xff" * len(safe[::458])
    clean, rendered, safe_mask = bytes(cleaned), bytes(final), bytes(safe)
    boxes = [[87, 142, 237, 179], [179, 220, 275, 147], [width - 60, height - 50, 80, 90]]
    outside = (original, clean, safe_mask, width, height, 20)
    assert native.outside_mask_diff(*outside) == python.outside_mask_diff(*outside) == [2537, 21]

    changed = native.changed_mask_rgb(clean, rendered, width, height, 20)
    assert changed == python.changed_mask_rgb(clean, rendered, width, height, 20)
    assert len(changed) == size and changed.count(255) == 5074

    overlap = (changed, width, height, boxes)
    assert native.overlap_changed_pixels(*overlap) == python.overlap_changed_pixels(*overlap) == [[0, 1, 64]]

    outline = (original, clean, rendered, safe_mask, width, height, boxes[0], True, 20)
    assert native.outline_crossing_pixels(*outline) == python.outline_crossing_pixels(*outline) == 97
