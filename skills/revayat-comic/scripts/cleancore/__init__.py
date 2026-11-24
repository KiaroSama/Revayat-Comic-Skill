"""Page cleaning kernels with optional Rust acceleration."""

import os
import sys
from pathlib import Path

from . import kernels as _python

__all__ = [
    "BACKEND",
    "composite_masked_rgb",
    "compute_feather_alpha",
    "detect_textured_ring",
    "diffuse_inpaint_rgb",
    "fill_flat_rgb",
    "sample_ring_background",
]


def _load_native():
    if os.environ.get("REVAYAT_CLEANCORE", "").strip().lower() == "python":
        return None
    try:
        import cleancore_rs
    except ImportError:
        parents = Path(__file__).resolve().parents
        if len(parents) < 5:
            return None
        crate = parents[4] / "rust" / "cleancore-rs" / "python"
        if not (crate / "cleancore_rs").is_dir():
            return None
        sys.path.insert(0, str(crate))
        try:
            import cleancore_rs
        except ImportError:
            return None
        finally:
            sys.path.remove(str(crate))
    return cleancore_rs if all(callable(getattr(cleancore_rs, name, None)) for name in __all__[1:]) else None


_native = _load_native()
_backend = _native or _python
BACKEND = "rust" if _native is not None else "python"
composite_masked_rgb = _backend.composite_masked_rgb
compute_feather_alpha = _backend.compute_feather_alpha
detect_textured_ring = _backend.detect_textured_ring
diffuse_inpaint_rgb = _backend.diffuse_inpaint_rgb
fill_flat_rgb = _backend.fill_flat_rgb
sample_ring_background = _backend.sample_ring_background
