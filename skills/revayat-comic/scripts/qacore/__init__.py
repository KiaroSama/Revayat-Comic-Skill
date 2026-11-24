"""Pixel QA kernels with optional Rust acceleration."""

import os
import sys
from pathlib import Path

from . import kernels as _python

__all__ = [
    "BACKEND",
    "compute_ink_bounds",
    "compute_patch_ssim",
    "detect_halo_artifacts",
    "detect_outline_bleed",
    "detect_residual_ink",
    "measure_region_contrast",
]


def _load_native():
    if os.environ.get("REVAYAT_QACORE", "").strip().lower() == "python":
        return None
    try:
        import qacore_rs
    except ImportError:
        parents = Path(__file__).resolve().parents
        if len(parents) < 5:
            return None
        crate = parents[4] / "rust" / "qacore-rs" / "python"
        if not (crate / "qacore_rs").is_dir():
            return None
        sys.path.insert(0, str(crate))
        try:
            import qacore_rs
        except ImportError:
            return None
        finally:
            sys.path.remove(str(crate))
    return qacore_rs if all(callable(getattr(qacore_rs, name, None)) for name in __all__[1:]) else None


_native = _load_native()
_backend = _native or _python
BACKEND = "rust" if _native is not None else "python"
compute_ink_bounds = _backend.compute_ink_bounds
compute_patch_ssim = _backend.compute_patch_ssim
detect_halo_artifacts = _backend.detect_halo_artifacts
detect_outline_bleed = _backend.detect_outline_bleed
detect_residual_ink = _backend.detect_residual_ink
measure_region_contrast = _backend.measure_region_contrast
