"""Balloon mask kernels with optional Rust acceleration."""

import os
import sys
from pathlib import Path

from . import kernels as _python

__all__ = [
    "BACKEND",
    "dilate_linf",
    "erode_linf",
    "flood_balloon_interior",
    "partition_voronoi_lobes",
    "strip_perimeter_contours",
]


def _load_native():
    if os.environ.get("REVAYAT_MASKCORE", "").strip().lower() == "python":
        return None
    try:
        import maskcore_rs
    except ImportError:
        parents = Path(__file__).resolve().parents
        if len(parents) < 5:
            return None
        crate = parents[4] / "rust" / "maskcore-rs" / "python"
        if not (crate / "maskcore_rs").is_dir():
            return None
        sys.path.insert(0, str(crate))
        try:
            import maskcore_rs
        except ImportError:
            return None
        finally:
            sys.path.remove(str(crate))
    return maskcore_rs if all(callable(getattr(maskcore_rs, name, None)) for name in __all__[1:]) else None


_native = _load_native()
_backend = _native or _python
BACKEND = "rust" if _native is not None else "python"
dilate_linf = _backend.dilate_linf
erode_linf = _backend.erode_linf
flood_balloon_interior = _backend.flood_balloon_interior
partition_voronoi_lobes = _backend.partition_voronoi_lobes
strip_perimeter_contours = _backend.strip_perimeter_contours
