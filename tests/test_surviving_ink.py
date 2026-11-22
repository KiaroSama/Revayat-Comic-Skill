"""Regression tests for qa.surviving_ink denominator and false positives."""

from __future__ import annotations

import numpy as np

import pageir as ir
import qa


def test_surviving_ink_measures_share_of_total_balloon_ink():
    """A handful of dark fringe pixels outside the mask when 98% of the
    balloon's lettering was erased must report ~2%, not 100%."""
    import cv2

    size = (400, 400)
    original = np.full((400, 400, 3), 255, dtype=np.uint8)
    # Draw an oval speech balloon around (200, 200).
    cv2.ellipse(original, (200, 200), (120, 90), 0, 0, 360, (0, 0, 0), 4)
    # Draw 1,000 pixels of lettering inside the balloon.
    original[180:200, 150:200] = 0
    # Draw a tiny 20-pixel dark fleck inside the interior outside the mask.
    original[215:219, 150:155] = 0

    # Cleaned page erases the 1,000 lettering pixels, leaving the 20-pixel fleck untouched.
    cleaned = original.copy()
    cleaned[180:200, 150:200] = 255

    mask_box = [135, 165, 130, 70]
    mask = np.zeros((mask_box[3], mask_box[2]), dtype=np.uint8)
    # Mask covers the 1,000 lettering pixels only (local coords inside mask_box).
    mask[15:35, 15:65] = 255

    region = ir.new_region("p0001r001", [150, 180, 50, 20], kind="speech")
    region["balloon"] = [80, 110, 240, 180]
    region["mask_box"] = mask_box

    share = qa.surviving_ink(original, cleaned, region, mask, size, np)
    assert share < 0.05, f"expected ~2% surviving ink, got {share:.1%}"
    assert share <= qa.MAX_SURVIVING_INK
