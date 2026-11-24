"""Comic detection kernels with optional Rust acceleration."""

import os

from . import kernels as _python

__all__ = [
    "BACKEND",
    "connected_components_boxes",
    "detect_speech_balloons",
    "estimate_stroke_width",
    "find_panel_gutters",
    "merge_text_lines",
    "sort_reading_order",
]


def _load_native():
    if os.environ.get("REVAYAT_DETECTCORE", "").strip().lower() == "python":
        return None
    try:
        import detectcore_rs
    except ImportError:
        return None
    return (
        detectcore_rs
        if all(callable(getattr(detectcore_rs, name, None)) for name in __all__[1:])
        else None
    )


_native = _load_native()
_backend = _native or _python
BACKEND = "rust" if _native is not None else "python"
connected_components_boxes = _backend.connected_components_boxes
detect_speech_balloons = _backend.detect_speech_balloons
estimate_stroke_width = _backend.estimate_stroke_width
find_panel_gutters = _backend.find_panel_gutters
merge_text_lines = _backend.merge_text_lines
sort_reading_order = _backend.sort_reading_order
