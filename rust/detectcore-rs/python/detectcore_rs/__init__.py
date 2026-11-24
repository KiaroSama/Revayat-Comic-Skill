"""Native comic detection kernels."""

from ._native import (
    connected_components_boxes,
    detect_speech_balloons,
    estimate_stroke_width,
    find_panel_gutters,
    merge_text_lines,
    sort_reading_order,
)

__all__ = [
    "connected_components_boxes",
    "detect_speech_balloons",
    "estimate_stroke_width",
    "find_panel_gutters",
    "merge_text_lines",
    "sort_reading_order",
]
