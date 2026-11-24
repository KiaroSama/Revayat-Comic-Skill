"""Shaped balloon layout with optional Rust acceleration."""

import os

from . import kernels as _python

__all__ = [
    "BACKEND",
    "align_lines_rtl",
    "check_ink_wall_clearance",
    "fit_lines_to_spans",
    "harmonize_font_sizes",
    "scan_mask_spans",
    "select_largest_inscribed_band",
]


def _load_native():
    if os.environ.get("REVAYAT_LAYOUTCORE", "").strip().lower() == "python":
        return None
    try:
        import layoutcore_rs
    except ImportError:
        return None
    return layoutcore_rs if all(callable(getattr(layoutcore_rs, name, None)) for name in __all__[1:]) else None


_native = _load_native()
_backend = _native or _python
BACKEND = "rust" if _native is not None else "python"
align_lines_rtl = _backend.align_lines_rtl
check_ink_wall_clearance = _backend.check_ink_wall_clearance
fit_lines_to_spans = _backend.fit_lines_to_spans
harmonize_font_sizes = _backend.harmonize_font_sizes
scan_mask_spans = _backend.scan_mask_spans
select_largest_inscribed_band = _backend.select_largest_inscribed_band
