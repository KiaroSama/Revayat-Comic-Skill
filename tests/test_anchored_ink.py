"""Independent expanded-canvas ink checks and real partially missing fonts."""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

import lettering
import typefit
import typefont


@pytest.fixture(scope="module")
def dejavu():
    path = Path(os.environ.get("REVAYAT_TEST_FONT", Path(__file__).resolve().parents[1]
                               / "fonts" / "round5" / "DejaVuSans.ttf"))
    assert path.is_file(), "install the declared DejaVu test font; see tests/README.md"
    return path


@pytest.mark.parametrize("font_kind", ["dejavu", "system"])
@pytest.mark.parametrize("fallback", [False, True], ids=["default-shaper", "forced-fallback"])
@pytest.mark.parametrize("text", ["بوووم", "خانهٔ ما", "سلام", "بدو!\nزود!", "بدو!\n\nزود!"])
@pytest.mark.parametrize("style_name", ["light", "heavy", "nib"])
def test_fitted_anchored_ink_stays_inside_its_strip(dejavu, font_kind, fallback, text, style_name):
    font_path = dejavu if font_kind == "dejavu" else typefont.find_font()
    shaper = typefont.Shaper(force_fallback=fallback)
    style = {"width": 200, "height": 90, "stroke": 0.04 if style_name == "light" else 0.9,
             "modulation": 0 if style_name == "light" else 0.8,
             "contrast": -1.0 if style_name == "nib" else 0}
    layer, fitted = lettering._strip(text, style, shaper, font_path, (10, 10, 10),
                                    (245, 245, 245), np, typefit.fit_region,
                                    (Image, ImageDraw, ImageFont), max_size=80, min_size=13)
    assert layer is not None, (font_path, text, style)
    assert fitted is not None
    size = fitted["size"]
    # An independent canvas catches ink that the production strip would clip
    # before a page-level preservation check could see it.
    pad = 256
    expanded = Image.new("L", (200 + 2 * pad, 90 + 2 * pad))
    draw = ImageDraw.Draw(expanded)
    font = ImageFont.truetype(str(font_path), size, layout_engine=shaper.layout)
    base = max(2, round(size * (0.06 if style_name == "light" else 0.22)))
    stroke = base if style_name == "light" else max(round(base * 0.6) + 1, round(base * 1.4))
    for line in fitted["lines"]:
        xy = (pad + line["x"], pad + line["y"])
        draw.text(xy, shaper.prepare(line["text"]), font=font, fill=255,
                  anchor="mm", stroke_width=stroke, **shaper.draw_kwargs())
        offset = max(1, round(size * 0.11))
        draw.text((xy[0] + offset, xy[1] + offset), shaper.prepare(line["text"]),
                  font=font, fill=255, anchor="mm", **shaper.draw_kwargs())
    ink = np.asarray(expanded).copy()
    if style_name == "nib":
        import cv2

        grow = round(size * 0.07)
        ink = cv2.dilate(ink, np.ones((2 * grow + 1, 1), np.uint8))
    ink[pad:pad + 90, pad:pad + 200] = 0
    assert np.count_nonzero(ink) == 0, (font_path.name, text, fitted, np.count_nonzero(ink))
    assert " ".join(line["text"] for line in fitted["lines"]).split() == text.split()
    assert layer.getchannel("A").getbbox() is not None
    if "\n\n" in text:
        assert any(line["text"] == "" for line in fitted["lines"])


@pytest.mark.parametrize("missing", ["پ", "ژ", "پژ", "ٔ"])
def test_a_real_font_missing_individual_persian_glyphs_is_rejected(dejavu, tmp_path, missing):
    from fontTools import subset
    from fontTools.ttLib import TTFont

    with TTFont(dejavu) as font:
        cmap = font.getBestCmap()
        assert all(ord(char) in cmap for char in missing)
        options = subset.Options()
        options.drop_tables.append("FFTM")
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=set(cmap) - {ord(char) for char in missing})
        subsetter.subset(font)
        reduced = tmp_path / "partial.ttf"
        font.save(reduced)
    assert typefont._supports_persian(dejavu)
    assert not typefont._supports_persian(reduced), f"missing {missing!r} was accepted"
