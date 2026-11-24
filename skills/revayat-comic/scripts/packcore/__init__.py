"""Package and raster kernels with optional Rust acceleration."""

import os

from . import kernels as _python

__all__ = [
    "BACKEND",
    "analyze_rgb_page",
    "compute_grayscale_histogram",
    "compute_pdf_page_layout",
    "diff_raster_tiles",
    "natural_sort_order",
    "validate_page_dimensions",
]


def _load_native():
    if os.environ.get("REVAYAT_PACKCORE", "").strip().lower() == "python":
        return None
    try:
        import packcore_rs
    except ImportError:
        return None
    return packcore_rs if all(callable(getattr(packcore_rs, name, None)) for name in __all__[1:]) else None


_native = _load_native()
_backend = _native or _python
BACKEND = "rust" if _native is not None else "python"
analyze_rgb_page = _backend.analyze_rgb_page
compute_grayscale_histogram = _backend.compute_grayscale_histogram
compute_pdf_page_layout = _backend.compute_pdf_page_layout
diff_raster_tiles = _backend.diff_raster_tiles
natural_sort_order = _backend.natural_sort_order
validate_page_dimensions = _backend.validate_page_dimensions
