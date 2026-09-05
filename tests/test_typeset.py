"""Persian typesetting: shaping, fitting, and the floor that must not move."""

from __future__ import annotations

import numpy as np
import pytest

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
