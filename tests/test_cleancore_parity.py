"""Cleaning kernel contracts and optional native parity."""

import importlib
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(params=["python", "dispatch"])
def kernels(request):
    name = "cleancore.kernels" if request.param == "python" else "cleancore"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != "cleancore":
            raise
        pytest.fail("cleancore is not implemented")


def mask(*rows):
    return bytes(128 if pixel == "#" else 0 for row in rows for pixel in row)


def gray(*values):
    return bytes(value for value in values for _ in range(3))


def test_ring_uses_chebyshev_distance_and_per_channel_lower_median(kernels):
    rgb = bytes.fromhex("0aff40 f01430 00ffff 5028fe ffffff 00ffff")
    active = mask("#.#", "..#")
    assert kernels.sample_ring_background(rgb, active, 3, 2, 1) == [240, 40, 254, 3]
    assert kernels.sample_ring_background(rgb, mask("#..", "..."), 3, 2, 1) == [240, 40, 254, 3]
    assert kernels.sample_ring_background(gray(9, 1, 4), mask(".#."), 3, 1, 1) == [4, 4, 4, 2]
    assert kernels.sample_ring_background(gray(0, 10, 20, 30), mask("#..."), 4, 1, 2) == [10, 10, 10, 2]
    assert kernels.sample_ring_background(gray(0, 10, 20, 30), mask("#..."), 4, 1, 2**150) == [20, 20, 20, 3]


@pytest.mark.parametrize("active,radius", [(b"\0\0", 1), (b"\x01\x80", 1), (b"\x01\0", 0)])
def test_empty_ring_has_no_samples(kernels, active, radius):
    assert kernels.sample_ring_background(gray(0, 1), active, 2, 1, radius) == [255, 255, 255, 0]
    assert kernels.detect_textured_ring(gray(0, 1), active, 2, 1, radius, 0.0) == [0.0, 0.0, 0.0, 0.0]


def test_feather_uses_virtual_boundary_and_nearest_diagonal(kernels):
    active = mask("#####", "#####", "##.##", "#####", "#####")
    expected = bytes(0 if not pixel else 128 for pixel in active)
    assert kernels.compute_feather_alpha(active, 5, 5, 2) == expected
    solid = b"\xff" * 25
    assert kernels.compute_feather_alpha(solid, 5, 5, 3) == bytes([
        85, 85, 85, 85, 85,
        85, 170, 170, 170, 85,
        85, 170, 255, 170, 85,
        85, 170, 170, 170, 85,
        85, 85, 85, 85, 85,
    ])
    assert kernels.compute_feather_alpha(active, 5, 5, 0) == bytes(255 if value else 0 for value in active)
    assert kernels.compute_feather_alpha(solid, 5, 5, 2**150) == bytes(25)
    assert kernels.compute_feather_alpha(mask(".#."), 3, 1, 4) == b"\0\x40\0"


def test_composite_uses_exact_integer_rounding(kernels):
    orig = bytes.fromhex("123456 00ffff 010203 112233")
    fill = bytes.fromhex("abcdef ff0000 215263 445566")
    assert kernels.composite_masked_rgb(orig, fill, bytes([0, 128, 255, 1]), 4, 1) == bytes.fromhex(
        "123456 807f7f 215263 112233"
    )
    assert kernels.composite_masked_rgb(gray(0, 0), gray(255, 255), bytes([127, 128]), 2, 1) == gray(127, 128)


def test_jacobi_uses_ring_seed_and_previous_pass_with_replicated_edges(kernels):
    orig = gray(0, 99, 101, 200)
    active = mask(".##.")
    assert kernels.diffuse_inpaint_rgb(orig, active, 4, 1, 0) == gray(0, 0, 0, 200)
    assert kernels.diffuse_inpaint_rgb(orig, active, 4, 1, 1) == gray(0, 0, 50, 200)
    assert kernels.diffuse_inpaint_rgb(orig, active, 4, 1, 2) == gray(0, 13, 75, 200)
    assert kernels.diffuse_inpaint_rgb(gray(90), b"\xff", 1, 1, 10) == gray(255)
    assert kernels.diffuse_inpaint_rgb(orig, bytes(4), 4, 1, 10) == orig
    rgb = gray(0, 0, 0, 0, 133, 80, 0, 80, 0)
    assert kernels.diffuse_inpaint_rgb(rgb, mask("...", ".#.", "..."), 3, 3, 1)[12:15] == gray(40)


def test_texture_uses_population_luma_std_and_widest_single_channel(kernels):
    rgb = bytes.fromhex("ff0000 ffffff 0000ff")
    expected_std = (0.299 * 255 - 0.114 * 255) / 2
    values = kernels.detect_textured_ring(rgb, mask(".#."), 3, 1, 1, 20.0)
    assert values == pytest.approx([1.0, expected_std, 255.0, 2.0], abs=1e-12)
    assert all(type(value) is float for value in values)
    assert kernels.detect_textured_ring(gray(6, 0, 14), mask(".#."), 3, 1, 1, 4.0) == [0.0, 4.0, 8.0, 2.0]
    assert kernels.detect_textured_ring(gray(6, 0, 6), mask(".#."), 3, 1, 1, 0.0) == [0.0, 0.0, 0.0, 2.0]


def test_flat_fill_treats_any_nonzero_mask_as_active(kernels):
    orig = bytes.fromhex("010203 040506 070809 0a0b0c")
    assert kernels.fill_flat_rgb(orig, bytes([0, 1, 2, 0]), 2, 2, 255, 0, 127) == bytes.fromhex(
        "010203 ff007f ff007f 0a0b0c"
    )


GOOD_RGB = gray(0, 9)
GOOD_MASK = b"\xff\0"
VALID = {
    "sample_ring_background": (GOOD_RGB, GOOD_MASK, 2, 1, 1),
    "compute_feather_alpha": (GOOD_MASK, 2, 1, 2),
    "composite_masked_rgb": (GOOD_RGB, GOOD_RGB, GOOD_MASK, 2, 1),
    "diffuse_inpaint_rgb": (GOOD_RGB, GOOD_MASK, 2, 1, 1),
    "detect_textured_ring": (GOOD_RGB, GOOD_MASK, 2, 1, 1, 1.0),
    "fill_flat_rgb": (GOOD_RGB, GOOD_MASK, 2, 1, 0, 127, 255),
}
LAYOUT = {
    "sample_ring_background": (2, (0, 1)),
    "compute_feather_alpha": (1, (0,)),
    "composite_masked_rgb": (3, (0, 1, 2)),
    "diffuse_inpaint_rgb": (2, (0, 1)),
    "detect_textured_ring": (2, (0, 1)),
    "fill_flat_rgb": (2, (0, 1)),
}


def invalid_calls():
    for name, (width_at, buffers) in LAYOUT.items():
        for index in (width_at, width_at + 1):
            for value in (0, -1, True, 1.0, 2**150):
                yield name, index, value, "dimensions"
        for index in buffers:
            for value in (b"", b"\0" * 9, bytearray(VALID[name][index]), list(VALID[name][index]), ""):
                yield name, index, value, "pixel buffer"
    for name, index in (("sample_ring_background", 4), ("compute_feather_alpha", 3), ("detect_textured_ring", 4)):
        for value in (-1, True, 0.25, "1"):
            yield name, index, value, "radius"
    for value in (-1, True, 1.0, sys.maxsize + 1, None):
        yield "diffuse_inpaint_rgb", 4, value, "iterations"
    for value in (-1, True, "1", math.inf, -math.inf, math.nan, 10**400):
        yield "detect_textured_ring", 5, value, "threshold"
    for index in (4, 5, 6):
        for value in (-1, 256, True, 0.5, "1", 2**150):
            yield "fill_flat_rgb", index, value, "channel"


@pytest.mark.parametrize(("name", "index", "value", "message"), list(invalid_calls()))
def test_invalid_inputs_raise_value_error(kernels, name, index, value, message):
    args = list(VALID[name])
    args[index] = value
    with pytest.raises(ValueError, match=message):
        getattr(kernels, name)(*args)


def test_dimension_product_overflow(kernels):
    with pytest.raises(ValueError, match="dimensions"):
        kernels.compute_feather_alpha(b"", sys.maxsize, 2, 1)


def test_dispatch_can_force_python_fallback():
    import cleancore

    scripts = Path(cleancore.__file__).resolve().parents[1]
    env = dict(os.environ, REVAYAT_CLEANCORE="python", PYTHONPATH=str(scripts))
    subprocess.run(
        [sys.executable, "-B", "-c", "import cleancore; assert cleancore.BACKEND == 'python'"],
        env=env, check=True, timeout=10, stdin=subprocess.DEVNULL,
    )


def test_seeded_native_parity_preserves_outside_mask():
    native = importlib.import_module("cleancore")
    from cleancore import kernels as reference

    rng = random.Random(13004)
    for _ in range(48):
        width, height = rng.randrange(1, 22), rng.randrange(1, 20)
        n = width * height
        rgb = rng.randbytes(n * 3)
        active = bytes(rng.choice((0, 0, 1, 255)) for _ in range(n))
        radius = rng.randrange(6)
        alpha = native.compute_feather_alpha(active, width, height, radius)
        assert alpha == reference.compute_feather_alpha(active, width, height, radius)
        assert native.sample_ring_background(rgb, active, width, height, radius) == reference.sample_ring_background(
            rgb, active, width, height, radius
        )
        assert native.detect_textured_ring(rgb, active, width, height, radius, 32.0) == pytest.approx(
            reference.detect_textured_ring(rgb, active, width, height, radius, 32.0), abs=1e-12
        )
        fill = native.fill_flat_rgb(rgb, active, width, height, 127, 99, 255)
        painted = native.diffuse_inpaint_rgb(rgb, active, width, height, radius)
        merged = native.composite_masked_rgb(rgb, fill, alpha, width, height)
        assert fill == reference.fill_flat_rgb(rgb, active, width, height, 127, 99, 255)
        assert painted == reference.diffuse_inpaint_rgb(rgb, active, width, height, radius)
        assert merged == reference.composite_masked_rgb(rgb, fill, alpha, width, height)
        for index, value in enumerate(active):
            if value == 0:
                offset = index * 3
                assert alpha[index] == 0
                assert fill[offset:offset + 3] == painted[offset:offset + 3] == merged[offset:offset + 3] == rgb[offset:offset + 3]
