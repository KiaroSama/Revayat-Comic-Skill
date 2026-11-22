"""Regression tests for typefit._candidate_bodies and fit_region on balloons
with thin wide edge spikes (open page margins or twin-balloon bridges)."""

from __future__ import annotations

import numpy as np

import typefit


def test_candidate_bodies_keeps_primary_first_and_recovers_main_body_on_spike():
    """A 10-row wide edge spike starves the primary max-width band to 10 rows;
    _candidate_bodies must keep the primary band first and include a fallback
    covering the full 200-row body."""
    widths = [130] * 200 + [300] * 10
    bodies = typefit._candidate_bodies(widths)
    assert bodies[0] == (200, 10)
    assert any(start == 0 and height >= 200 for start, height in bodies[1:])


def test_fit_region_recovers_when_edge_spike_starves_primary_body():
    """fit_region must place text in a 200x130 balloon body even when a 10-row
    300px-wide margin opening sits at the bottom edge."""
    from PIL import Image, ImageDraw
    import typefont

    font_path = typefont.find_font()
    if font_path is None:
        return
    shaper = typefont.Shaper(force_fallback=False)
    mask = np.zeros((240, 340), dtype=np.uint8)
    mask[10:210, 80:210] = 255
    mask[210:220, 20:320] = 255
    canvas = Image.new("RGB", (340, 240), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    fitted = typefit.fit_region(
        draw, "سلام دنیا!", mask, np, shaper, font_path, max_size=48, min_size=13
    )
    assert fitted is not None
    assert fitted["size"] >= 18


def test_body_still_excludes_tall_narrow_tail():
    """Robust fallbacks must not change _body() on a standard balloon with tail."""
    widths = [140] * 100 + [18] * 140
    assert typefit._body(widths) == (0, 100)
