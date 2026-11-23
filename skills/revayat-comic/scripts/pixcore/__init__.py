"""Pixel QA kernels with optional Rust acceleration and a Python fallback."""

import os
import sys
from pathlib import Path

from . import kernels as _python

__all__ = [
    "BACKEND",
    "changed_mask_rgb",
    "outline_crossing_pixels",
    "outside_mask_diff",
    "overlap_changed_pixels",
]


def _load_native():
    if os.environ.get("REVAYAT_PIXCORE", "").strip().lower() == "python":
        return None
    try:
        import pixcore_rs
    except ImportError:
        parents = Path(__file__).resolve().parents
        if len(parents) < 5:
            return None
        crate = parents[4] / "rust" / "pixcore-rs" / "python"
        if not (crate / "pixcore_rs").is_dir():
            return None
        sys.path.insert(0, str(crate))
        try:
            import pixcore_rs
        except ImportError:
            return None
        finally:
            sys.path.remove(str(crate))
    if all(callable(getattr(pixcore_rs, name, None)) for name in __all__[1:]):
        return pixcore_rs
    return None


_native = _load_native()
_backend = _native or _python
BACKEND = "rust" if _native is not None else "python"
changed_mask_rgb = _backend.changed_mask_rgb
outline_crossing_pixels = _backend.outline_crossing_pixels
outside_mask_diff = _backend.outside_mask_diff
overlap_changed_pixels = _backend.overlap_changed_pixels
