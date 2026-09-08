"""Persian typesetting: shaping, fitting, and the floor that must not move."""

from __future__ import annotations

import numpy as np
import pytest

from PIL import Image

import clean
import lettering
import masks
import pageir as ir
import typeset

ZWNJ = "‌"
HAMZA_ABOVE = "ٔ"


# --- Shaping ----------------------------------------------------------------

def test_the_fallback_keeps_the_persian_ezafe_hamza():
    """arabic-reshaper deletes harakat by default, and U+0654 is not decoration
    in Persian: `خانهٔ ما` (our house) silently becomes `خانه ما`."""
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    assert HAMZA_ABOVE in typeset.shape_fallback("خانهٔ ما")


def test_the_fallback_reorders_for_display():
    pytest.importorskip("bidi")
    source = "سلام دنیا"
    shaped = typeset.shape_fallback(source)
    assert shaped != source        # it was reordered and shaped
    assert len(shaped) >= 5


def test_the_zero_width_non_joiner_changes_the_letter_forms():
    """ZWNJ must not survive into the display string — the bidi algorithm
    removes boundary-neutral characters, and that is correct. What must survive
    is its *effect*: `کتاب‌ها` keeps the beh isolated, `کتابها` joins it.
    Asserting on the character itself tests the wrong thing and fails on
    behaviour that is right.
    """
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    assert typeset.shape_fallback(f"کتاب{ZWNJ}ها") != typeset.shape_fallback("کتابها")


def test_the_shaper_reports_which_path_it_took():
    shaper = typeset.Shaper()
    assert shaper.mode in {"raqm", "reshaper"}
    assert (shaper.mode == "raqm") == typeset.raqm_available()


def test_raqm_only_arguments_are_not_passed_in_fallback_mode():
    """`direction` and `language` raise without RAQM rather than degrading."""
    fallback = typeset.Shaper(force_fallback=True)
    assert fallback.draw_kwargs() == {}


def _ink_width(shaper, text: str, *, shape: bool = True) -> tuple[int, int]:
    """Draw one line and return (ink width, ink pixels).

    ``shape=False`` is the deliberately unshaped baseline, and it forces the
    BASIC layout engine to get there. Asking RAQM for "no shaping" is not a
    thing: HarfBuzz shapes from the script it detects, and the direction and
    language arguments only override that detection — so a RAQM baseline would
    come out shaped and the comparison below would prove nothing.
    """
    from PIL import Image, ImageDraw, ImageFont

    layout = shaper.layout if shape else ImageFont.Layout.BASIC
    font = ImageFont.truetype(str(typeset.find_font()), 48, layout_engine=layout)
    canvas = Image.new("L", (1600, 160), 255)
    ImageDraw.Draw(canvas).text(
        (60, 40), shaper.prepare(text) if shape else text,
        font=font, fill=0, **(shaper.draw_kwargs() if shape else {}))
    ink = np.asarray(canvas) < 128
    columns = np.flatnonzero(ink.any(axis=0))
    if columns.size == 0:
        return 0, 0
    return int(columns[-1] - columns[0] + 1), int(ink.sum())


@pytest.mark.skipif(not typeset.raqm_available(),
                    reason="no RAQM in this Pillow; the fallback is the only path here")
def test_raqm_shapes_persian_and_agrees_with_the_fallback():
    """The half of the shaping code that used to be believed unreachable here.

    Pillow carries libraqm everywhere and loads FriBiDi at run time, so this runs
    wherever a FriBiDi library is on the loader's path — Linux CI always, Windows
    once a `fribidi` DLL is on PATH. Until it first ran, nothing checked that
    RAQM *worked*, only that it was switched on. Two things are asserted, and the
    first is the one that matters:

    1. **RAQM actually joins the letters.** Persian drawn without shaping comes
       out as isolated forms, which are markedly wider than the joined ones. If
       a future Pillow silently stopped shaping, the text would still render and
       every other test would still pass — this width comparison is what would
       notice.
    2. **Both paths agree.** Windows ships the reshaper output to readers and
       Linux ships RAQM's; if they disagreed by much, a chapter would look
       different depending on who built it.
    """
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    text = "سلام دنیا، این یک آزمایش است"

    raqm = typeset.Shaper()
    assert raqm.mode == "raqm"
    shaped_width, shaped_ink = _ink_width(raqm, text)
    unshaped_width, _ = _ink_width(raqm, text, shape=False)
    fallback_width, fallback_ink = _ink_width(typeset.Shaper(force_fallback=True), text)

    assert shaped_ink > 0 and fallback_ink > 0
    # Joined is narrower than isolated. A 5% margin only says "not identical".
    assert shaped_width < unshaped_width * 0.95
    assert abs(shaped_width - fallback_width) <= 0.20 * fallback_width
    assert abs(shaped_ink - fallback_ink) <= 0.30 * fallback_ink


def test_the_document_is_never_reversed_in_place(translated):
    """Rule one: the logical text stays logical. Shaping happens at draw time."""
    typeset.typeset_document(translated)
    doc = ir.load_doc(translated)
    for _, region in ir.iter_regions(doc):
        if region.get("target_text"):
            assert "ﺎ" not in region["target_text"], "presentation forms stored"


# --- Fonts ------------------------------------------------------------------

def test_a_persian_font_is_found_on_this_machine():
    assert typeset.find_font().exists()


def test_the_font_is_checked_for_persian_coverage():
    assert typeset._supports_persian(typeset.find_font())


def test_an_unknown_font_name_falls_back_rather_than_failing():
    assert typeset.find_font("NoSuchFontAnywhere").exists()


# --- Fitting ----------------------------------------------------------------

def _canvas(width=400, height=300):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "white")
    return ImageDraw.Draw(image)


def _ellipse_mask(width=400, height=300):
    from PIL import Image, ImageDraw

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).ellipse([20, 20, width - 20, height - 20], fill=255)
    return np.asarray(mask)


def test_text_fits_inside_the_shape_it_was_given():
    shaper = typeset.Shaper()
    fitted = typeset.fit_region(
        _canvas(), "بس کن! این‌جا چه خبر است؟", _ellipse_mask(), np, shaper,
        typeset.find_font(), max_size=64, min_size=12,
    )
    assert fitted is not None
    assert fitted["line_count"] >= 1
    assert 12 <= fitted["size"] <= 64


def test_a_narrower_shape_takes_a_smaller_size():
    shaper = typeset.Shaper()
    font = typeset.find_font()
    text = "هیچ‌کس نمی‌داند او کجا رفته است."
    wide = typeset.fit_region(_canvas(), text, _ellipse_mask(400, 300), np,
                              shaper, font, max_size=64, min_size=8)
    narrow = typeset.fit_region(_canvas(), text, _ellipse_mask(170, 130), np,
                                shaper, font, max_size=64, min_size=8)
    assert wide and narrow
    assert narrow["size"] < wide["size"]


def test_more_text_takes_more_lines():
    shaper = typeset.Shaper()
    font = typeset.find_font()
    mask = _ellipse_mask()
    short = typeset.fit_region(_canvas(), "برو!", mask, np, shaper, font,
                               max_size=40, min_size=10)
    long = typeset.fit_region(
        _canvas(),
        "هیچ‌کس نمی‌داند او کجا رفته و چرا هیچ خبری از او نیست.",
        mask, np, shaper, font, max_size=40, min_size=10,
    )
    assert short and long
    assert long["line_count"] > short["line_count"]


def test_the_minimum_size_is_a_floor_not_a_suggestion():
    """Rather than shrinking to something unreadable, it refuses and the region
    is reported as overflowing so the translation can be shortened."""
    shaper = typeset.Shaper()
    enormous = " ".join(["هیچ‌کس نمی‌داند او کجا رفته است"] * 30)
    fitted = typeset.fit_region(
        _canvas(120, 90), enormous, _ellipse_mask(120, 90), np, shaper,
        typeset.find_font(), max_size=40, min_size=22,
    )
    assert fitted is None


def test_no_word_is_ever_dropped_at_any_size():
    """**The one that matters most in this file.** Every word goes on the page or
    the region overflows — there is no third outcome, and there used to be.

    A balloon reading `پس بهتره بری خونه، نه؟` came back typeset as `نه؟` at the
    largest size the fitter had, with `status: ok`. When the first word of a line
    was too wide, the guard against it measured the empty accumulator instead of
    the word, an empty string measures zero, and the word was quietly discarded —
    then so was the next, and the next, until some short token at the end fitted
    and was reported as the whole balloon.

    Nothing else would have caught it: the counts were right, QA saw a placed
    region, and the page looked finished. Only reading it did.
    """
    shaper = typeset.Shaper()
    font = typeset.find_font()
    text = "پس بهتره بری خونه، نه؟"
    expected = text.split()

    for width, height in ((400, 300), (170, 130), (116, 154), (90, 200), (300, 60)):
        fitted = typeset.fit_region(
            _canvas(width, height), text, _ellipse_mask(width, height), np,
            shaper, font, max_size=64, min_size=8,
        )
        if fitted is None:
            continue                       # refusing is the other honest answer
        placed = " ".join(line["text"] for line in fitted["lines"]).split()
        assert placed == expected, (
            f"{width}x{height} at size {fitted['size']} dropped "
            f"{[w for w in expected if w not in placed]}"
        )


def test_a_single_word_too_wide_for_the_shape_overflows_rather_than_vanishing():
    """The narrow path of the same bug, isolated: one long word, no room."""
    shaper = typeset.Shaper()
    fitted = typeset.fit_region(
        _canvas(60, 200), "غیرقابل‌پیش‌بینی‌ترین", _ellipse_mask(60, 200), np,
        shaper, typeset.find_font(), max_size=64, min_size=40,
    )
    assert fitted is None


def test_an_empty_shape_fits_nothing():
    shaper = typeset.Shaper()
    assert typeset.fit_region(
        _canvas(), "سلام", np.zeros((300, 400), np.uint8), np, shaper,
        typeset.find_font(), max_size=40, min_size=10,
    ) is None


# --- Whole pages ------------------------------------------------------------

def test_typesetting_writes_a_final_page_for_every_translated_page(translated):
    report = typeset.typeset_document(translated)
    assert report["placed"] > 0
    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    for page in doc["pages"]:
        assert (root / page["final"]).exists()
        assert (root / page["writable"]).exists()


def test_the_final_page_is_the_same_size_as_the_original(translated):
    typeset.typeset_document(translated)
    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    for page in doc["pages"]:
        final = ir.load_image(root / page["final"])
        assert final.size == (page["width"], page["height"])


def test_each_region_records_how_it_was_set(translated):
    typeset.typeset_document(translated)
    doc = ir.load_doc(translated)
    for _, region in ir.iter_regions(doc):
        state = region.get("typeset", {}).get("status")
        if state == "ok":
            assert region["typeset"]["size"] >= typeset.DEFAULT_MIN_SIZE
            assert region["typeset"]["shaping"] in {"raqm", "reshaper"}


def test_an_untranslatable_balloon_is_reported_as_overflow(translated):
    doc = ir.load_doc(translated)
    _, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = " ".join(["کلمهٔ بسیار طولانی"] * 60)
    ir.save_doc(doc, translated)

    report = typeset.typeset_document(translated, min_size=30)
    assert region["id"] in report["overflow"]
    assert "shorten" in report["next"].lower()


def test_a_sound_effect_is_left_alone_under_the_keep_policy(translated):
    doc = ir.load_doc(translated)
    doc["meta"]["sfx_policy"] = "keep"
    ir.save_doc(doc, translated)
    report = typeset.typeset_document(translated)
    assert sum(page["skipped"] for page in report["pages"]) > 0


def test_the_fallback_path_produces_a_page_too(translated):
    report = typeset.typeset_document(translated, force_fallback=True)
    assert report["shaping"] == "reshaper"
    assert report["placed"] > 0
    assert "Windows and macOS" in report["warning"]


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


def _sfx_page(doc_path, *, mask, box, text="\u0628\u0648\u0645"):
    """Put one sound effect on the page with a REAL local mask at `box`."""
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    page = doc["pages"][0]
    doc["meta"]["sfx_policy"] = "translate"
    # Only the effect under test. These assertions measure what changed on the
    # page, and the fixture's other regions get typeset too — they landed inside
    # the window and read as the effect having been drawn in the wrong place.
    region = page["regions"][0]
    page["regions"] = [region]
    region.update(kind="sfx", target_text=text, balloon=None,
                  bbox=[box[0], box[1], box[2], box[3]])
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


# --- the house face ----------------------------------------------------------
# Persian in this project is set in Vazir. Vazirmatn is the current release of
# that family; the older `Vazir-*` files are the same design under its first
# name. A fallback face still produces readable pages, which is precisely why a
# fallback has to announce itself.

@pytest.mark.parametrize("name", [
    "Vazirmatn-Medium.ttf", "Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf",
    "Vazirmatn-VariableFont_wght.ttf", "Vazirmatn[wght].ttf",
    "Vazir.ttf", "Vazir-Medium-FD.ttf",
])
def test_every_shape_of_vazir_is_recognised(name):
    """The list used to hold three filenames. This machine had Vazirmatn
    installed as its variable build the whole time, matched none of the three,
    and every page silently typeset in Tahoma."""
    assert typeset.is_vazir(name)
    assert name in typeset.PERSIAN_FONTS


@pytest.mark.parametrize("name", ["Tahoma.ttf", "NotoNaskhArabic-Regular.ttf",
                                  "Sahel.ttf", "arial.ttf"])
def test_a_fallback_face_is_not_mistaken_for_vazir(name):
    assert not typeset.is_vazir(name)


def test_vazir_outranks_every_fallback():
    """Order is the whole mechanism: `find_font` takes the first name that
    loads, so anything ahead of Vazir in this tuple would quietly win."""
    first_other = next(i for i, n in enumerate(typeset.PERSIAN_FONTS)
                       if not typeset.is_vazir(n))
    assert all(typeset.is_vazir(n)
               for n in typeset.PERSIAN_FONTS[:first_other])
    assert first_other == len(typeset.VAZIR_FONTS)


def test_a_run_on_a_fallback_face_says_so(translated, monkeypatch):
    """Readable is not the same as right. A volume set in the wrong face is
    only noticed once it is printed, so the report carries the fact."""
    monkeypatch.setattr(typeset, "is_vazir", lambda path: False)
    report = typeset.typeset_document(translated)
    assert report["vazir"] is False
    assert "Vazir" in report["font_note"]


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

