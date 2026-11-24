"""Native page cleaning kernels."""

from ._native import (
    composite_masked_rgb,
    compute_feather_alpha,
    detect_textured_ring,
    diffuse_inpaint_rgb,
    fill_flat_rgb,
    sample_ring_background,
)

__all__ = [
    "composite_masked_rgb",
    "compute_feather_alpha",
    "detect_textured_ring",
    "diffuse_inpaint_rgb",
    "fill_flat_rgb",
    "sample_ring_background",
]
