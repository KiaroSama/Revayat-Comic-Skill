"""Parity and fallback tests for the `hotcore` Python/Rust geometry kernels."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "revayat-comic" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hotcore  # noqa: E402
from hotcore import geometry as py_geom  # noqa: E402


def test_python_fallback_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVAYAT_HOTCORE", "python")
    reloaded = importlib.reload(hotcore)
    assert reloaded.BACKEND == "python"
    assert reloaded.cluster_boxes is py_geom.cluster_boxes

    monkeypatch.delenv("REVAYAT_HOTCORE", raising=False)
    importlib.reload(hotcore)


def test_cluster_boxes_matches_reference_on_dense_seeds() -> None:
    seeds = [[(i * 17) % 300, (i * 23) % 400, 10 + (i % 8), 14 + (i % 6)] for i in range(120)]
    expected = py_geom.cluster_boxes(seeds, 400, 1.6)
    actual = hotcore.cluster_boxes(seeds, 400, 1.6)
    assert actual == expected


def test_body_bounds_and_candidate_bodies_parity() -> None:
    widths = [0, 4, 180, 12, 60, 66, 70, 68, 64, 10, 3, 0]
    assert hotcore.body_bounds(widths, -1, 0.5) == py_geom.body_bounds(widths, -1, 0.5)
    assert hotcore.candidate_bodies(widths, 0.5) == py_geom.candidate_bodies(widths, 0.5)


def test_native_module_all_six_exports_match_python_when_built() -> None:
    if hotcore._native is None:
        assert hotcore.BACKEND == "python"
        return
    native = hotcore._native

    assert native.box_gap([0, 0, 10, 10], [13, 14, 5, 5]) == pytest.approx(5.0)
    assert native.box_gap([0, 0, 10, 10], [5, 5, 10, 10]) == 0.0

    seeds = [[10, 10, 12, 18], [26, 10, 12, 18], [200, 200, 12, 18]]
    assert native.cluster_boxes(seeds, 400, 1.6) == py_geom.cluster_boxes(seeds, 400, 1.6)

    mask = bytes([0, 255, 255, 0, 255, 255, 255, 255, 255, 0, 0, 255, 255, 255, 0])
    assert native.row_widths(mask, 5, 3) == py_geom.row_widths(mask, 5, 3)
    assert native.band_span(mask, 5, 3, 0, 3) == py_geom.band_span(mask, 5, 3, 0, 3)
    assert native.band_span(mask, 5, 3, 1, 3) == py_geom.band_span(mask, 5, 3, 1, 3)

    widths = [2, 200, 10, 60, 65, 68, 66, 62, 12, 4]
    assert native.body_bounds(widths, -1, 0.5) == py_geom.body_bounds(widths, -1, 0.5)
    assert native.candidate_bodies(widths, 0.5) == py_geom.candidate_bodies(widths, 0.5)
