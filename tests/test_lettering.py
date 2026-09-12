"""Lettering that was drawn rather than typed, and put back the same way.

Split out of `test_typeset.py`, which had grown to two thirds lettering. The
boundary is a module: `typeset.py` sets Persian into a balloon, and
`lettering.py` measures what a letterer did to a sound effect — its slant, its
arc, how it recedes, how heavy the brush was and whether the weight changed
along the word — and draws the Persian back with the same hand.

Two rules run through every test here. **A measurement that does not hold up is
a request to leave the artwork alone**, never a guess: `unreliable` means the
original stays drawn and a person looks at it. And **a region mask is local to
`mask_box`**, so anything measured in it is meaningless on the page until the
box origin is added back — that shipped once without it and put every rotated
effect near (0, 0), which is why the coordinate test is here by name.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from PIL import Image

import clean
import lettering
import masks
import pageir as ir
import providers
import typeset


# --- lettering that was drawn, not typed ------------------------------------
# A sound effect leans, arcs and recedes. Every number comes out of the region's
# mask, which is the shape of what `clean` erased, and every transform is gated
# on a measurement that says the number means something.
#
# The contract that matters most here is the COORDINATE FRAME. A stored region
# mask is a *local* array covering `region["mask_box"]`; the first version of
# this feature measured in that frame and pasted onto the full page, putting
# every rotated effect near the origin. The integration tests below use a real
# local mask at a deliberately non-zero page position for exactly that reason.

def _bar(angle: float, shape=(120, 300), thickness=20):
    """A local region mask: a long bar, rotated, sized like a real mask_box."""
    height, width = shape
    canvas = np.zeros((height, width), np.uint8)
    top = (height - thickness) // 2
    canvas[top:top + thickness, 20:width - 20] = 255
    if angle:
        canvas = np.asarray(Image.fromarray(canvas).rotate(
            angle, resample=Image.BILINEAR))
    return canvas


def _arc(sagitta: int, shape=(160, 320)):
    """A local mask whose ink follows a parabola — lettering along a curve."""
    height, width = shape
    canvas = np.zeros((height, width), np.uint8)
    for x in range(20, width - 20):
        t = (x - width / 2) / (width / 2)
        y = int(height / 2 + (t * t - 1) * sagitta)
        canvas[max(0, y - 9):y + 9, x] = 255
    return canvas


def _deep_arc(sagitta: int):
    """An arc bent past being lettering. Measured band: about 100-130 trips the
    curvature ceiling, and past ~150 the bounding box is no longer elongated at
    all and the elongation gate takes it first."""
    canvas = np.zeros((420, 320), np.uint8)
    for x in range(30, 290):
        t = (x - 160) / 130
        y = int(200 + (t * t - 1) * sagitta)
        canvas[max(0, y - 8):y + 8, x] = 255
    return canvas


def _wedge(shape=(140, 320)):
    """A local mask that is thick at one end and thin at the other."""
    height, width = shape
    canvas = np.zeros((height, width), np.uint8)
    for x in range(20, width - 20):
        half = int(8 + 20 * (1 - (x - 20) / (width - 40)))
        canvas[height // 2 - half:height // 2 + half, x] = 255
    return canvas


@pytest.mark.parametrize("drawn", [-35, -20, 20, 35, 60])
def test_a_measured_slant_round_trips_through_the_renderer(drawn):
    """`measure` reports the negative of the rotation that made the shape, so
    the renderer turns by `-angle` to put it back. Measured, not read out of
    OpenCV's documentation: a mirrored angle looks deliberate on a page and is
    wrong on every one of them."""
    style = lettering.measure(_bar(drawn), np)
    assert style is not None and style["verdict"] == "rotated"
    assert style["angle"] == pytest.approx(-drawn, abs=1.5)


def test_the_measured_centre_is_in_page_coordinates():
    """THE REGRESSION. A region mask is local to `mask_box`, so a centre
    measured in it is meaningless on the page until the box origin is added.
    Shipped once without this and put every rotated effect near (0, 0)."""
    mask = _bar(-20)
    local = lettering.measure(mask, np)
    placed = lettering.measure(mask, np, origin=(800, 1200))
    assert placed["cx"] == pytest.approx(local["cx"] + 800)
    assert placed["cy"] == pytest.approx(local["cy"] + 1200)


def test_lettering_set_straight_is_flat_not_a_failure():
    style = lettering.measure(_bar(0), np)
    assert style is not None and style["verdict"] == "flat"


def test_a_blob_of_glyphs_is_unreliable_rather_than_guessed_at():
    """minAreaRect always returns an angle. On a shape with no long axis that
    angle is wherever the fit landed, so the verdict is `unreliable` and the
    lettering stays drawn — not a wilder guess, and not a silent flat replace."""
    blob = np.zeros((200, 200), np.uint8)
    blob[70:130, 60:140] = 255
    style = lettering.measure(blob, np)
    assert style["verdict"] == "unreliable" and style["reason"]


def test_an_arc_is_measured_as_curved():
    style = lettering.measure(_arc(34), np)
    assert style["verdict"] == "curved"
    assert style["curvature"] >= lettering.MIN_CURVE


def test_a_gentle_wobble_is_not_an_arc():
    """A quadratic fits any scatter. Without the curvature floor every ragged
    straight effect reads as curved."""
    assert lettering.measure(_arc(3), np)["verdict"] != "curved"


def _middle_row(layer):
    """Where the ink sits in the middle column of a bent strip."""
    alpha = np.asarray(layer)[..., 3]
    return float(np.flatnonzero(alpha[:, alpha.shape[1] // 2]).mean())


def test_an_arc_and_the_same_arc_mirrored_bend_opposite_ways():
    """Which way it bends is half the measurement.

    `_curvature` returned an absolute sagitta, so an effect arching up and one
    sagging down came back as the same positive number — and `_bend`, which has
    always honoured the sign, bent both of them upwards. Two effects curving
    against each other were replaced by two curving the same way.

    Measured: +0.1184 and -0.1184 for one arc and its mirror, and the middle of
    the rendered strip lands at row 4.5 for one and 27.5 for the other.
    """
    hill = lettering.measure(_arc(34), np)
    valley = lettering.measure(_arc(-34), np)

    assert hill["verdict"] == valley["verdict"] == "curved"
    assert hill["curvature"] > 0 > valley["curvature"], \
        f"the bend direction was lost: {hill['curvature']}, {valley['curvature']}"
    assert hill["curvature"] == pytest.approx(-valley["curvature"], abs=0.01)

    strip = np.zeros((40, 160, 4), np.uint8)
    strip[16:24, :] = 255
    up = _middle_row(lettering._bend(
        Image.fromarray(strip, "RGBA"), hill["curvature"], np, Image))
    down = _middle_row(lettering._bend(
        Image.fromarray(strip, "RGBA"), valley["curvature"], np, Image))
    assert up < down, f"both arcs bent the same way ({up} against {down})"


def test_lettering_that_tapers_is_measured_as_receding():
    style = lettering.measure(_wedge(), np)
    assert style["verdict"] == "warped"
    assert abs(style["taper"] - 1.0) >= lettering.MIN_TAPER


def test_a_baseline_that_folds_back_is_refused():
    """Curvature past `MAX_CURVE` is not an arc, it is usually two effects
    caught in one mask. The safe answer is to leave the artwork alone."""
    style = lettering.measure(_deep_arc(108), np)
    assert style["curvature"] > lettering.MAX_CURVE
    assert style["verdict"] == "unreliable"


def test_a_fold_so_deep_it_has_no_long_axis_is_also_refused():
    """The second road to the same answer, and the reason both gates exist. Bend
    a line far enough and its bounding box stops being long at all: the axis
    flips to vertical and every measurement taken along it is meaningless. The
    elongation gate catches that before the curvature gate ever sees it."""
    style = lettering.measure(_deep_arc(200), np)
    assert style["elongation"] < lettering.MIN_ELONGATION
    assert style["verdict"] == "unreliable"


def test_the_renderer_refuses_a_box_the_words_cannot_fill():
    """No font sets 13-point type in eight pixels, so the renderer reports that
    it could not and paints nothing."""
    canvas = Image.new("RGB", (200, 200), "white")
    style = {"cx": 100.0, "cy": 100.0, "width": 8.0, "height": 6.0,
             "angle": 20.0, "curvature": 0.0, "taper": 1.0,
             "verdict": "rotated"}
    assert lettering.render(
        canvas, "\u06cc\u06a9 \u062c\u0645\u0644\u0647\u0654 \u0628\u0644\u0646\u062f", style, typeset.Shaper(),
        typeset.find_font(), (0, 0, 0), None, np, typeset.fit_region,
        typeset._pil(), max_size=64, min_size=13) is None
    assert np.asarray(canvas).min() == 255


def _sfx_page(doc_path, *, mask, box, text="\u0628\u0648\u0645",
              policy="translate", **fields):
    """Put one sound effect on the page with a REAL local mask at `box`."""
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    page = doc["pages"][0]
    doc["meta"]["sfx_policy"] = policy
    # Only the effect under test. These assertions measure what changed on the
    # page, and the fixture's other regions get typeset too — they landed inside
    # the window and read as the effect having been drawn in the wrong place.
    region = page["regions"][0]
    page["regions"] = [region]
    region.update(kind="sfx", target_text=text, balloon=None,
                  bbox=[box[0], box[1], box[2], box[3]], **fields)
    relative = f"masks/{page['id']}/{region['id']}.png"
    ir.write_bytes(root / relative,
                   masks._encode_png(Image.fromarray(mask, mode="L")))
    region["mask"] = relative
    region["mask_box"] = list(box)
    ir.save_doc(doc, doc_path)
    return page, region


def test_a_rotated_effect_lands_where_the_lettering_was(translated):
    """The regression, end to end and on the pixels. The mask is a normal local
    array and its box sits well away from the origin; the ink the typesetter
    adds has to appear there and not at the top-left of the page."""
    doc = ir.load_doc(translated)
    page_w = doc["pages"][0]["width"]
    page_h = doc["pages"][0]["height"]
    box = (page_w // 2, page_h // 2, 300, 120)
    if box[0] + 300 > page_w or box[1] + 120 > page_h:
        pytest.skip("fixture page is too small to place the effect off-origin")
    page, region = _sfx_page(translated, mask=_bar(-20), box=box)
    root = ir.doc_dir(translated)
    before = np.asarray(ir.load_image(root / (page.get("clean") or page["image"])))

    typeset.typeset_document(translated)
    after_doc = ir.load_doc(translated)
    after_region = after_doc["pages"][0]["regions"][0]
    assert after_region["typeset"]["style"] == "rotated"

    final = np.asarray(ir.load_image(root / after_doc["pages"][0]["final"]))
    changed = np.abs(final.astype(int) - before.astype(int)).max(axis=2) > 12
    assert changed.any(), "nothing was drawn at all"
    ys, xs = np.nonzero(changed)
    # Every changed pixel sits around the region, not at the page origin.
    assert xs.min() >= box[0] - 160 and xs.max() <= box[0] + box[2] + 160
    assert ys.min() >= box[1] - 160 and ys.max() <= box[1] + box[3] + 160


def test_an_unreadable_effect_is_left_drawn_and_sent_to_review(translated):
    """`unreliable` must not quietly become ordinary flat Persian. The artwork
    stays as the letterer drew it, the region says why, and the census reports
    `needs_review` rather than claiming a translation that is not on the page."""
    blob = np.zeros((150, 150), np.uint8)
    blob[40:110, 35:115] = 255
    page, region = _sfx_page(translated, mask=blob, box=(120, 140, 150, 150))
    root = ir.doc_dir(translated)
    before = np.asarray(ir.load_image(root / (page.get("clean") or page["image"])))

    report = typeset.typeset_document(translated)
    assert report["unreliable_count"] >= 1

    after_doc = ir.load_doc(translated)
    after_region = after_doc["pages"][0]["regions"][0]
    assert after_region["typeset"]["status"] == "unreliable"
    assert after_region["review"], "the reader was never told why"
    assert ir.region_state(after_region, "translate") == "needs_review"

    final = np.asarray(ir.load_image(root / after_doc["pages"][0]["final"]))
    x, y, w, h = after_region["mask_box"]
    delta = np.abs(final.astype(int) - before.astype(int)).max(axis=2)
    assert delta[y:y + h, x:x + w].max() == 0, "the artwork was written on"


def test_flat_sfx_turns_every_transform_off(translated):
    """The escape hatch, and the control that proves the rotated path above is
    real rather than the flat one wearing a different label."""
    page_w = ir.load_doc(translated)["pages"][0]["width"]
    page_h = ir.load_doc(translated)["pages"][0]["height"]
    box = (min(40, page_w - 300), min(40, page_h - 120), 300, 120)
    _sfx_page(translated, mask=_bar(-20), box=box)
    typeset.typeset_document(translated, stylise=False)
    after = ir.load_doc(translated)["pages"][0]["regions"][0]
    assert after["typeset"]["style"] == "flat"


def test_an_unreliable_effect_survives_the_real_clean_to_typeset_flow(
        translated):
    """THE invariant, measured against the page as it arrived.

    `clean` runs before `typeset`, so a decision made at typeset time to "leave
    the lettering as drawn" is a promise about pixels that were erased two
    stages earlier. The previous version of this test compared the final page to
    `page["clean"]` — the already-cleaned input — and so could not see the loss
    at all. It compares to `page["image"]` now, which is the only comparison
    that means anything.
    """
    blob = np.zeros((150, 150), np.uint8)
    blob[40:110, 35:115] = 255                 # no long axis: unreliable
    page, region = _sfx_page(translated, mask=blob, box=(120, 140, 150, 150))
    root = ir.doc_dir(translated)
    original = np.asarray(ir.load_image(root / page["image"]))

    clean.clean_document(translated)
    typeset.typeset_document(translated)

    after_doc = ir.load_doc(translated)
    after = after_doc["pages"][0]["regions"][0]
    assert after["typeset"]["status"] == "unreliable"
    assert after["fill"] == "keep", "clean erased it before typeset could decide"

    final = np.asarray(ir.load_image(root / after_doc["pages"][0]["final"]))
    x, y, w, h = after["mask_box"]
    delta = np.abs(final.astype(int) - original.astype(int)).max(axis=2)
    assert delta[y:y + h, x:x + w].max() == 0, \
        "the original lettering is not on the final page"


def test_a_stylised_effect_that_will_not_fit_is_restored_not_flattened(
        translated, monkeypatch):
    """A curved effect whose Persian will not fit its arc must not quietly
    become a horizontal line of type across the artwork. `clean` has already
    erased it by then, so the original ink is put back under its own mask."""
    page, region = _sfx_page(translated, mask=_arc(34), box=(60, 60, 320, 160),
                             text="\u0628\u0648\u0645")
    root = ir.doc_dir(translated)
    original = np.asarray(ir.load_image(root / page["image"]))

    clean.clean_document(translated)
    # The measurement stands; only the fitting fails.
    monkeypatch.setattr(lettering, "render", lambda *a, **k: None)
    typeset.typeset_document(translated)

    after_doc = ir.load_doc(translated)
    after = after_doc["pages"][0]["regions"][0]
    assert after["typeset"]["status"] == "unreliable"
    assert after["typeset"]["style"] == "curved"
    assert after.get("review")

    final = np.asarray(ir.load_image(root / after_doc["pages"][0]["final"]))
    x, y, w, h = after["mask_box"]
    delta = np.abs(final.astype(int) - original.astype(int)).max(axis=2)
    assert delta[y:y + h, x:x + w].max() == 0


# --- matching the hand -------------------------------------------------------

def _bar_of_weight(thickness: int, angle: float = -20.0):
    canvas = np.zeros((160, 400), np.uint8)
    top = 80 - thickness // 2
    canvas[top:top + thickness, 40:360] = 255
    return np.asarray(Image.fromarray(canvas).rotate(
        angle, resample=Image.BILINEAR))


def test_the_stroke_weight_of_the_original_is_measured():
    """A delicate effect and a heavy one are drawn with the same letters and
    different weight, and replacing both with one fixed outline throws away
    half of what made them different.

    The distance transform's ridge is the half-width of the stroke it sits in;
    a high percentile rather than the maximum keeps a junction of three strokes
    from speaking for the whole hand.
    """
    light = lettering.measure(_bar_of_weight(4), np)["stroke"]
    medium = lettering.measure(_bar_of_weight(10), np)["stroke"]
    heavy = lettering.measure(_bar_of_weight(22), np)["stroke"]
    assert light < medium < heavy
    assert light < 0.07 and heavy > 0.12


def test_a_heavier_original_gets_a_heavier_outline(monkeypatch):
    """The measurement has to reach the ink.

    Isolated on purpose: two full pipeline runs fit different type sizes, so
    their absolute stroke widths are not comparable — the first version of this
    test compared them anyway and reported the heavy effect as lighter. Here the
    box, the text and the fitted size are identical and only `stroke` differs,
    which is the one thing under test.
    """
    from PIL import ImageDraw

    widths = []
    original = ImageDraw.ImageDraw.text

    def _spy(self, xy, txt, **kw):
        if kw.get("stroke_width"):
            widths.append(kw["stroke_width"])
        return original(self, xy, txt, **kw)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", _spy)

    def _draw(stroke_fraction):
        widths.clear()
        canvas = Image.new("RGB", (600, 400), "white")
        style = {"cx": 300.0, "cy": 200.0, "width": 320.0, "height": 120.0,
                 "angle": -20.0, "curvature": 0.0, "taper": 1.0,
                 "stroke": stroke_fraction, "verdict": "rotated"}
        done = lettering.render(
            canvas, "بوم", style, typeset.Shaper(), typeset.find_font(),
            (18, 18, 18), (250, 250, 250), np, typeset.fit_region,
            typeset._pil(), max_size=64, min_size=13)
        assert done is not None
        return max(widths)

    light = _draw(0.05)
    heavy = _draw(0.40)
    assert heavy > light, f"light {light}, heavy {heavy} - weight was not matched"

    # And it is clamped at both ends rather than tracking the mask blindly.
    assert _draw(0.9) == _draw(0.44), "MAX_STROKE is not holding"


# --- the hand that changes weight along the word -----------------------------
# `stroke` matches how heavy the effect was. This is the other half: how evenly.
# A brush that swells is the difference between hand lettering and type, and one
# uniform weight is exactly what throws it away.

def _comb(widths, height=60, gap=14, pad=20):
    """Vertical strokes of given widths, all the same height.

    Deliberately not a wedge. A wedge changes the ink per column, so `taper`
    sees it too and the test could not tell which measurement fired. Here every
    column with ink has the same amount of it — only the stroke width changes,
    so `taper` stays 1.0 and modulation is measured alone.
    """
    total = pad * 2 + sum(widths) + gap * (len(widths) - 1)
    canvas = np.zeros((height + 2 * pad, total), np.uint8)
    x = pad
    for width in widths:
        canvas[pad:pad + height, x:x + width] = 255
        x += width + gap
    return canvas


def test_a_brush_that_thickens_along_the_word_is_measured():
    """Measured: even 0.000, growing +0.455, falling -0.455, taper 1.00 in all
    three — so the signal is the stroke width and not the silhouette."""
    even = lettering.measure(_comb([8] * 7), np)
    grow = lettering.measure(_comb([4, 6, 8, 10, 12, 14, 16]), np)
    fall = lettering.measure(_comb([16, 14, 12, 10, 8, 6, 4]), np)

    assert abs(even["modulation"]) < lettering.MIN_MODULATION
    assert grow["modulation"] > lettering.MIN_MODULATION
    assert fall["modulation"] < -lettering.MIN_MODULATION
    assert grow["modulation"] == pytest.approx(-fall["modulation"], abs=0.05)
    for style in (even, grow, fall):
        assert style["taper"] == pytest.approx(1.0, abs=0.05)


def test_a_blot_at_one_end_is_not_a_brush_stroke():
    """One heavy stroke among even ones is a splash, an inking slip, or two
    effects caught in one mask. A trend needs the bands in between to agree."""
    blot = lettering.measure(_comb([8, 8, 8, 8, 8, 8, 26]), np)
    assert blot["modulation"] == 0.0


def _swelling_layer(modulation: float):
    shaper = typeset.Shaper()
    font_path = Path(typeset.find_font())
    from PIL import ImageDraw, ImageFont

    style = {"width": 420.0, "height": 120.0, "stroke": 0.16,
             "modulation": modulation}
    layer, _ = lettering._strip(
        "بوووم", style, shaper, font_path, (20, 20, 20, 255),
        (255, 255, 255, 255), np, typeset.fit_region,
        (Image, ImageDraw, ImageFont), max_size=110, min_size=20)
    return np.asarray(layer)[..., 3].astype(float)


def _ends(alpha):
    third = alpha.shape[1] // 3
    return alpha[:, :third].sum(), alpha[:, -third:].sum()


def test_an_effect_that_swells_is_drawn_swelling():
    """Compared against the unmodulated render of the same word, so the word's
    own left-right asymmetry cancels and what is left is the brush.

    Measured on this machine: right/left 0.967 flat, 1.105 swelling to the
    right, 0.844 swelling to the left.
    """
    def ratio(modulation):
        left, right = _ends(_swelling_layer(modulation))
        return right / max(left, 1.0)

    flat = ratio(0.0)
    rightwards = ratio(0.5)
    leftwards = ratio(-0.5)

    assert rightwards > flat * 1.05, "the right end did not get heavier"
    assert leftwards < flat * 0.95, "the left end did not get heavier"


def test_an_evenly_drawn_effect_is_not_put_through_the_second_pass():
    """The gate. Below `MIN_MODULATION` the render must be byte-identical to
    the single-weight path — otherwise every ordinary effect pays for two
    passes and a blend to look exactly the same."""
    plain = _swelling_layer(0.0)
    under = _swelling_layer(lettering.MIN_MODULATION * 0.9)
    assert np.array_equal(plain, under)


# --- the nib, which is the measurable half of "pressure" ----------------------
# Where the pressure went *along* one stroke belongs to the typeface's drawing
# and cannot be recovered from ink already lifted off the page. Which direction
# the pen was wide in can: a broad nib lays a heavy upright and a light flat.

def _nib_grid(upright_width, flat_height, n=5, cell=70, pad=20):
    """Upright stems crossed by flat bars, each drawn at its own thickness."""
    canvas = np.zeros((pad * 2 + cell, pad * 2 + n * cell), np.uint8)
    for index in range(n):
        x = pad + index * cell + cell // 3
        canvas[pad:pad + cell, x:x + upright_width] = 255
        canvas[pad + cell // 2:pad + cell // 2 + flat_height,
               x:x + cell // 2] = 255
    return canvas


def test_the_direction_the_pen_was_wide_in_is_measured():
    """Measured: a round hand 0.000, a broad nib +0.538, a flat nib -0.538 —
    symmetric, and independent of overall weight and of the trend along the
    word, which the same fixture leaves at zero."""
    round_hand = lettering.measure(_nib_grid(10, 10), np)
    broad = lettering.measure(_nib_grid(20, 7), np)
    flat = lettering.measure(_nib_grid(7, 20), np)

    assert abs(round_hand["contrast"]) < lettering.MIN_CONTRAST
    assert broad["contrast"] > lettering.MIN_CONTRAST
    assert flat["contrast"] < -lettering.MIN_CONTRAST
    assert broad["contrast"] == pytest.approx(-flat["contrast"], abs=0.05)
    assert abs(broad["modulation"]) < lettering.MIN_MODULATION


def test_a_thick_stem_is_not_mistaken_for_a_flat_stroke():
    """THE MEASUREMENT BUG. The first version separated the two directions with
    a morphological opening, and a 20 px stem is also a 20 px-wide horizontal
    run — so it survived the horizontal opening too and both directions ended up
    measuring the same ink. Scored 0.001 where it should have scored about 0.5.
    """
    stems = lettering._runs(_nib_grid(20, 7) > 0, np, vertical=True)
    across = lettering._runs(_nib_grid(20, 7) > 0, np, vertical=False)
    # A pixel in the middle of a stem: long down, short across.
    assert stems.max() > across.max()
    assert lettering.measure(_nib_grid(20, 7), np)["contrast"] > 0.3


def _nib_extent(contrast: float):
    shaper = typeset.Shaper()
    font_path = Path(typeset.find_font())
    from PIL import ImageDraw, ImageFont

    style = {"width": 420.0, "height": 120.0, "stroke": 0.16,
             "modulation": 0.0, "contrast": contrast}
    layer, _ = lettering._strip(
        "بوووم", style, shaper, font_path, (20, 20, 20, 255),
        (255, 255, 255, 255), np, typeset.fit_region,
        (Image, ImageDraw, ImageFont), max_size=110, min_size=20)
    alpha = np.asarray(layer)[..., 3] > 0
    return int(alpha.any(axis=0).sum()), int(alpha.any(axis=1).sum())


def test_a_broad_nib_widens_across_and_a_flat_one_widens_down():
    """Measured at type size 92: 211x77 round, 216x77 broad, 211x81 flat. The
    unchanged dimension in each is the point — an isotropic `stroke_width`
    would have moved both."""
    round_cols, round_rows = _nib_extent(0.0)
    broad_cols, broad_rows = _nib_extent(0.6)
    flat_cols, flat_rows = _nib_extent(-0.6)

    assert broad_cols > round_cols and broad_rows == round_rows
    assert flat_rows > round_rows and flat_cols == round_cols


def test_a_round_hand_is_not_put_through_the_nib():
    """Below the gate the render must be byte-identical, so an ordinary effect
    pays nothing."""
    plain = _nib_extent(0.0)
    assert _nib_extent(lettering.MIN_CONTRAST * 0.9) == plain


def test_the_nib_carries_the_ink_into_the_pixels_it_widens_into():
    """A dilated alpha over transparent black is a black fringe.

    A pixel nothing has been drawn on is `(0, 0, 0, 0)` — transparent, and
    *black* underneath. Growing the coverage alone hands those pixels a visible
    alpha while leaving them that colour, so a light outline widened by a broad
    nib gains a dark rim on the side it grew towards.

    Measured on a real render of `بوووم` at size 92 with a 250-level outline:
    1313 newly covered pixels at a mean of 13.3, of which 1231 landed on
    mid-grey artwork DARKER than the un-nibbed render, by up to 128 levels.
    """
    body = np.zeros((60, 60, 4), np.uint8)
    body[20:40, 20:40] = (250, 250, 250, 255)      # a light outline on nothing
    grown = np.asarray(lettering._nib(
        Image.fromarray(body, "RGBA"), 0.6, 100, np, Image))

    widened = (grown[..., 3] > 0) & (body[..., 3] == 0)
    assert widened.any(), "the nib widened nothing, so this proves nothing"
    assert int(grown[..., :3][widened].min()) >= 200, \
        "the widened edge is transparent black, not the ink it grew from"


# --- what `clean` may and may not do to a drawn effect ------------------------
# The other end of the same question. `lettering` decides whether Persian can be
# set the way the original was drawn; `clean` decides whether the original is
# still there to compare against. Both answers are made on the same evidence —
# the region's mask and the policy — and they have to agree.

def _solid_free_page(doc_path, *, box=(120, 140, 300, 120), doc_mode="solid",
                     page_mode=None):
    """One free-lettering region masked the way `--free-lettering solid` does:
    the whole patch filled, no letter shapes, and no balloon behind it.

    The box is deliberately long rather than square: a square patch has no long
    axis, `measure` says `unreliable`, and the region is kept before it ever
    reaches the repair tiers these tests are about.
    """
    page, region = _sfx_page(
        doc_path, mask=np.full((box[3], box[2]), 255, np.uint8), box=box)
    doc = ir.load_doc(doc_path)
    doc["meta"]["free_lettering_mask"] = doc_mode
    if page_mode is not None:
        doc["pages"][0]["free_lettering_mask"] = page_mode
    ir.save_doc(doc, doc_path)
    return page, region


def test_a_missing_external_page_is_not_recorded_as_a_repair(detected, tmp_path):
    """The guard is satisfied by a PROMISE — `--external` was supplied — and the
    promise breaks one function later, when that page turns out not to be in the
    folder. The region then fell through to the classical tier, which on a solid
    patch has no unmasked pixel to read: nothing is repaired, and `inpaint` is
    written into the document anyway. The original lettering ships under the
    Persian and every gate says the page was cleaned."""
    page, _ = _solid_free_page(detected)
    root = ir.doc_dir(detected)
    before = np.asarray(ir.load_image(root / page["image"]))
    folder = tmp_path / "external-pages"       # real, and without THIS page
    folder.mkdir()

    report = clean.clean_document(detected, external=folder,
                                  pages=[page["id"]])

    after_doc = ir.load_doc(detected)
    region = after_doc["pages"][0]["regions"][0]
    assert region["fill"] == "keep", "a repair that never happened was recorded"
    assert region.get("review"), "the reader was never told to act"
    assert report["totals"]["refused"] == 1
    after = np.asarray(ir.load_image(root / after_doc["pages"][0]["clean"]))
    assert np.array_equal(after, before), "the artwork was repainted"


def test_a_provider_that_fails_is_not_recorded_as_a_repair(detected, monkeypatch):
    """The same bypass through the other door. A configured provider satisfies
    the guard before it has answered; when the answer is the wrong size — or an
    exception, or nothing — the region falls through to exactly the tier the
    guard exists to keep a solid patch away from."""
    page, _ = _solid_free_page(detected)
    monkeypatch.setitem(providers._REGISTRY["image_edit"], "broken",
                        lambda: providers.FakeImageEdit(fail="wrong_size"))

    report = clean.clean_document(detected, provider="broken",
                                  pages=[page["id"]])

    assert report["provider_calls"][0]["outcome"] == "wrong_size"
    region = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert region["fill"] == "keep", "a repair that never happened was recorded"
    assert region.get("review"), "the reader was never told to act"
    assert report["totals"]["refused"] == 1


def test_one_pages_mask_mode_is_not_overwritten_by_the_next_page(detected):
    """`mask --free-lettering solid --pages p0001` followed by an ordinary
    `mask --pages p0002` leaves ONE document-level flag, reading `glyphs`. The
    first page's solid patches are then handed to the built-in cleaners the flag
    exists to keep them away from, and the record describes neither page."""
    page, _ = _solid_free_page(detected, doc_mode="glyphs", page_mode="solid")

    with pytest.raises(ValueError, match=page["id"]):
        clean.clean_document(detected, pages=[page["id"]])


def test_the_mask_mode_is_recorded_on_the_page_that_was_cleaned(detected):
    """So the next run's flag cannot rewrite the history of this one."""
    page, _ = _sfx_page(detected, mask=_bar(-20), box=(120, 140, 300, 120))

    clean.clean_document(detected, pages=[page["id"]])

    assert ir.load_doc(detected)["pages"][0]["free_lettering_mask"] == "glyphs"


@pytest.mark.parametrize("policy, retained", [
    ("keep", True), ("annotate", True), ("bilingual", True),
    ("translate", False),
])
def test_the_four_policies_decide_whether_the_drawn_effect_survives(
        detected, policy, retained):
    """`bilingual` and `annotate` both keep the drawing: one adds a Persian
    gloss beside the original, the other records the meaning off the page.
    Erasing the artwork is the one thing neither of them may do, and `bilingual`
    was doing exactly that — it went down the same path as `translate`, so the
    effect it promises to keep was gone before anything could be set beside it.
    """
    page, _ = _sfx_page(detected, mask=_bar(-20), box=(120, 140, 300, 120),
                        policy=policy)
    root = ir.doc_dir(detected)
    before = np.asarray(ir.load_image(root / page["image"]))

    clean.clean_document(detected, pages=[page["id"]])

    after_doc = ir.load_doc(detected)
    region = after_doc["pages"][0]["regions"][0]
    assert (region["fill"] == "keep") is retained, \
        f"`{policy}` recorded fill={region['fill']!r}"
    if retained:
        after = np.asarray(ir.load_image(root / after_doc["pages"][0]["clean"]))
        assert np.array_equal(after, before), \
            f"`{policy}` repainted artwork it promises to keep"


def test_an_explicit_erase_outranks_a_keep_policy_and_needs_no_geometry(detected):
    """`erase: yes` is a reader looking at a watermark and saying: remove this,
    put nothing back. Two things were overruling them. The global SFX policy,
    which is about lettering that belongs to the artwork and has nothing to say
    about a site stamp; and the geometry gate, which exists to decide whether
    Persian can be set the way the original was drawn — a question an erasure
    never asks, since nothing is going back in its place."""
    blob = np.zeros((150, 150), np.uint8)
    blob[40:110, 35:115] = 255                # no long axis: `measure` refuses
    assert lettering.measure(blob, np)["verdict"] == "unreliable"
    page, _ = _sfx_page(detected, mask=blob, box=(120, 140, 150, 150),
                        policy="keep", text="", erase=True)

    report = clean.clean_document(detected, pages=[page["id"]])

    region = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert region["fill"] not in (None, "none", "keep"), \
        "the erasure the reader asked for never happened"
    assert ir.region_state(region, "keep") == "erased"
    assert report["totals"]["keep"] == 0

