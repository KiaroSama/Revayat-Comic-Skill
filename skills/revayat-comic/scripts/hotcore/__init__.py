"""Hot-path geometry loader with optional compiled Rust PyO3 acceleration.

Set ``REVAYAT_HOTCORE=python`` (or ``RUST_ANYTHING_UNIT_HOTCORE=original``) to
force the pure-Python reference implementation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from . import geometry as _py

box_gap = _py.box_gap
cluster_boxes = _py.cluster_boxes
row_widths = _py.row_widths
band_span = _py.band_span
body_bounds = _py.body_bounds
candidate_bodies = _py.candidate_bodies
BACKEND = "python"


def _load_native() -> Any | None:
    if os.environ.get("REVAYAT_HOTCORE", "").strip().lower() == "python":
        return None
    if os.environ.get("RUST_ANYTHING_UNIT_HOTCORE", "").strip().lower() == "original":
        return None
    try:
        import hotcore_rs  # type: ignore[import-not-found]
        return hotcore_rs
    except Exception:
        pass
    # Also resolve an in-repo built crate at <repo>/rust/hotcore-rs/python.
    candidate = Path(__file__).resolve().parents[4] / "rust" / "hotcore-rs" / "python"
    if (candidate / "hotcore_rs").is_dir():
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
        try:
            import hotcore_rs  # type: ignore[import-not-found]
            return hotcore_rs
        except Exception:
            return None
    return None


_native = _load_native()
if _native is not None:
    # Bind the bench-verified faster hot-path kernels (`cluster_boxes`,
    # `body_bounds`, `candidate_bodies`) to Rust; keep single-call `box_gap`
    # and raw-bytes mask scans on their lower-overhead native/NumPy path.
    cluster_boxes = _native.cluster_boxes
    body_bounds = _native.body_bounds
    candidate_bodies = _native.candidate_bodies
    BACKEND = "rust"

__all__ = [
    "BACKEND",
    "band_span",
    "body_bounds",
    "box_gap",
    "candidate_bodies",
    "cluster_boxes",
    "row_widths",
]
