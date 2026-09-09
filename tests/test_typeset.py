"""Persian typesetting: shaping, fitting, and the floor that must not move."""

from __future__ import annotations

import numpy as np
import pytest

from PIL import Image

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
