"""Persian typesetting: shaping, fitting, and the floor that must not move."""

from __future__ import annotations

import numpy as np
import pytest

from PIL import Image, ImageDraw

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
    from PIL import ImageDraw, ImageFont

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
    from PIL import ImageDraw

    image = Image.new("RGB", (width, height), "white")
    return ImageDraw.Draw(image)


def _ellipse_mask(width=400, height=300):
    from PIL import ImageDraw

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


# --- R10: the authorisation may not come from the drawing --------------------

def _writable(doc_path):
    page = ir.load_doc(doc_path)["pages"][0]
    return np.asarray(
        ir.load_image(ir.doc_dir(doc_path) / page["writable"]).convert("L")) > 0


def _retypeset(doc_path, text):
    import typeset as typeset_module

    doc = ir.load_doc(doc_path)
    for _, region in ir.iter_regions(doc):
        if not region.get("dropped"):
            region["target_text"] = text
            region["typeset"] = {}
    ir.save_doc(doc, doc_path)
    typeset_module.typeset_document(doc_path)
    return _writable(doc_path)


def test_the_authorised_area_does_not_depend_on_what_was_drawn(translated):
    """THE ONE THAT MATTERS IN THIS FILE.

    `writable.png` is what the gate compares the finished page against, and it
    was built by drawing the text and then burning every bounding box that came
    out into the mask. That makes the preservation proof circular: whatever the
    typesetter painted became, by definition, the area it was allowed to paint.
    An overflow could not fail, because the evidence was written afterwards by
    the thing on trial.

    So: set a short line and a long one into the same page and the authorised
    area must not move. It is the balloons that authorise, not the ink."""
    import clean

    clean.clean_document(translated)
    small = _retypeset(translated, "بله")
    large = _retypeset(translated, "بله بله بله بله بله بله بله بله بله بله")

    grew = int((large & ~small).sum())
    assert grew == 0, f"the authorised area grew by {grew} px because more was drawn"


def test_text_pushed_off_the_balloon_is_caught_rather_than_authorised(
        translated, monkeypatch):
    """The same defect from the other side: shove the lines off the balloon and
    the gate has to notice. It could not before — the mask followed them."""
    import clean
    import qa
    import typeset as typeset_module

    clean.clean_document(translated)
    real = typeset_module.fit_region

    def shoved(*args, **kwargs):
        fitted = real(*args, **kwargs)
        if fitted:
            for line in fitted.get("lines", []):
                line["y"] = int(line["y"]) + 260
        return fitted

    monkeypatch.setattr(typeset_module, "fit_region", shoved)
    typeset_module.typeset_document(translated)

    report = qa.check_document(translated)
    # Reported as `text-overflow`, not `artwork-modified`, and that is the
    # better outcome: the ink that landed outside is taken back off the page
    # before it is saved, so the words are refused rather than shipped over the
    # artwork. What must never happen is silence.
    assert report["by_code"], "the gate accepted text drawn 260 px off its balloon"
    assert "text-overflow" in report["by_code"] or "artwork-modified" in report["by_code"]
    assert report["stats"]["artwork_pixels_changed"] == 0, (
        "the overflowing ink was left on the artwork")


def test_an_ordinary_page_still_passes_the_gate(translated):
    """The guard has to stay usable: real Persian set in real balloons must not
    start tripping the artwork check."""
    import clean
    import qa
    import typeset as typeset_module

    clean.clean_document(translated)
    typeset_module.typeset_document(translated)

    report = qa.check_document(translated)
    assert "artwork-modified" not in report["by_code"], report["findings"][:3]


# --- R10a/R10b: a font is judged by coverage, not by ink ---------------------

def _a_font_without_persian():
    """A real font on this machine that has no Persian letters, or None.

    Found rather than vendored: shipping a deliberately broken font to prove a
    negative is a strange thing to keep in a repository, and every desktop
    already has several Latin-only faces.
    """
    import glob
    import os

    from PIL import Image, ImageDraw, ImageFont

    roots = [r"C:\Windows\Fonts", "/usr/share/fonts", "/Library/Fonts",
             "/System/Library/Fonts", os.path.expanduser("~/.fonts")]
    seen = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for path in sorted(glob.glob(os.path.join(root, "**", "*.ttf"),
                                     recursive=True)):
            seen += 1
            if seen > 150:
                return None
            try:
                font = ImageFont.truetype(path, 32)
            except OSError:
                continue

            def drawn(text, font=font):
                canvas = Image.new("L", (240, 60), 255)
                ImageDraw.Draw(canvas).text((4, 4), text, font=font, fill=0)
                return canvas.tobytes()

            try:
                word = drawn("چگونه")
                boxes = drawn("\ue000\ue001\ue002\ue003\ue004")
                empty = drawn("")
            except Exception:
                continue
            if word == boxes and word != empty:
                return path
    return None


def test_a_font_that_draws_boxes_is_not_accepted_for_persian():
    """The check counted ink, and five tofu boxes are more ink than the word is.
    So a Latin-only face passed, `doctor` said the machine was ready, and the
    volume typeset in rectangles."""
    from pathlib import Path as _Path

    path = _a_font_without_persian()
    if path is None:
        pytest.skip("no Latin-only TTF on this machine to test against")
    assert typeset._supports_persian(_Path(path)) is False, path


def test_a_persian_capable_font_is_still_accepted():
    """The other half: narrowing this must not reject a face that works."""
    from pathlib import Path as _Path

    try:
        font = typeset.find_font()
    except Exception:
        pytest.skip("no Persian-capable font installed")
    assert typeset._supports_persian(_Path(font)) is True


# --- R10c/R10e/R10f: the band a line actually lies across ---------------------

def _stepped_mask(height=240, width=360, rows=6):
    """A shape whose rows do not line up: each band of rows is interior over a
    different stretch of columns, marching left to right.

    A real balloon leans like this wherever it has a tail, a slanted side or a
    divider. The point is that `min(width per row)` and `start of the middle
    row` describe two different pieces of the shape.
    """
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    band = height // rows
    for index in range(rows):
        left = 10 + index * 18
        draw.rectangle([left, index * band, left + 200, (index + 1) * band - 1],
                       fill=255)
    return np.asarray(mask)


def _double_run_mask(height=200, width=400):
    """Every row split in two by a vertical divider down the middle."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle([20, 20, 180, height - 20], fill=255)
    draw.rectangle([220, 20, 380, height - 20], fill=255)
    return np.asarray(mask)


def test_a_band_is_the_columns_every_one_of_its_rows_shares():
    """The width came from the narrowest row's own longest run and the position
    came from the middle row's. On a shape whose rows do not line up those are
    different columns, so a line was measured against one span and centred on
    another — and could be declared to fit while lying over the outline."""
    mask = _stepped_mask()
    span = typeset._band_span(mask, np)
    band = 40
    for start in range(0, mask.shape[0] - band, band):
        left, width = span(start, start + band)
        if width <= 0:
            continue
        assert mask[start:start + band, left:left + width].all(), (
            f"rows {start}-{start + band} are not all interior over "
            f"columns {left}-{left + width}")


def test_a_row_split_in_two_does_not_lose_the_half_that_was_dropped():
    """Only the longest run per row survived, and which of two equal runs that
    was came down to a pixel. The intersection uses the whole row."""
    mask = _double_run_mask()
    left, width = typeset._band_span(mask, np)(40, 80)
    assert width == 161, width           # one side, whole, not the gap
    assert left in (20, 220), left
    assert mask[40:80, left:left + width].all()


def test_a_fitted_line_never_leaves_the_shape_it_was_measured_against():
    """The property, end to end: every line `fit_region` places is drawn
    centred on its own band, so its ink has to stay inside the columns that
    band shares. Measured on the stepped shape, where the old answer does not.
    """
    shaper = typeset.Shaper()
    font_path = typeset.find_font()
    mask = _stepped_mask()
    draw = _canvas(mask.shape[1], mask.shape[0])
    fitted = typeset.fit_region(
        draw, "هیچ‌کس نمی‌داند او کجا رفته است و چرا", mask, np, shaper,
        font_path, max_size=40, min_size=10)
    assert fitted is not None

    from PIL import ImageFont

    font = ImageFont.truetype(str(font_path), fitted["size"],
                              layout_engine=shaper.layout)
    step = max(1, int(round(fitted["size"] * typeset.LINE_SPACING)))
    for line in fitted["lines"]:
        width, _ = typeset._measure(draw, line["text"], font, shaper)
        first = int(round(line["y"] - step / 2))
        left = int(line["x"] - width / 2)
        right = int(round(line["x"] + width / 2))
        window = mask[max(0, first):first + step, max(0, left):right]
        assert window.size and window.all(), (
            f"{line['text']!r} at y={line['y']:.0f} covers columns "
            f"{left}-{right} that its band does not share")


def test_a_hard_line_break_is_honoured_and_not_carried_inside_a_word():
    """A newline is not `[ \t]`, so it was not collapsed, and it is not `" "`,
    so `split` left it INSIDE a token. Pillow draws a string containing a
    newline as two lines of its own — below the band the fitter measured, and
    outside a tight balloon."""
    paragraphs = typeset._tokens("خط اول\nخط دوم")
    assert paragraphs == [["خط", "اول"], ["خط", "دوم"]]
    assert not any("\n" in token
                   for paragraph in paragraphs for token in paragraph)


def test_the_break_the_translation_asked_for_becomes_a_line():
    """Two short words that would happily share one line stay on two, because
    the break is a decision about the balloon and not whitespace to reflow."""
    shaper = typeset.Shaper()
    font = typeset.find_font()
    mask = _ellipse_mask()
    together = typeset.fit_region(_canvas(), "بله نه", mask, np, shaper, font,
                                  max_size=40, min_size=10)
    apart = typeset.fit_region(_canvas(), "بله\nنه", mask, np, shaper, font,
                               max_size=40, min_size=10)
    assert together and apart
    assert together["line_count"] == 1
    assert apart["line_count"] == 2
    assert [line["text"] for line in apart["lines"]] == ["بله", "نه"]


def test_blank_lines_do_not_become_empty_rows():
    """A trailing newline or a double break is whitespace, not a request for an
    empty line in the middle of a balloon."""
    assert typeset._tokens("بله\n\n\nنه\n") == [["بله"], ["نه"]]
    assert typeset._tokens("   \n  ") == []


# --- R9: one region's permission is not another's ----------------------------

def test_a_failed_region_does_not_erase_the_ones_already_set(finished):
    """The rollback restored the page as it was before ANY region drew, so one
    balloon that did not fit erased the finished translation of every balloon
    whose ink shared a rectangle with it — and reported only its own
    overflow."""
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    regions = [r for r in page["regions"]
               if not r.get("dropped") and r.get("mask_box")]
    if len(regions) < 2:
        pytest.skip("this fixture has only one maskable region")

    regions[0]["target_text"] = "بله"
    # A sentence nothing will fit, in the region that is set second.
    regions[1]["target_text"] = " ".join(["هیچ‌کس نمی‌داند او کجا رفته است"] * 8)
    ir.save_doc(doc, finished)

    report = typeset.typeset_document(finished, pages=[page["id"]])
    assert regions[1]["id"] in report["overflow"], report

    doc = ir.load_doc(finished)
    survived = ir.find_region(doc, regions[0]["id"])
    assert survived["typeset"].get("status") == "ok", survived["typeset"]

    # And its ink is really on the page: the first region's balloon differs
    # from the cleaned page it was drawn onto.
    root = ir.doc_dir(finished)
    page = doc["pages"][0]
    cleaned = np.asarray(ir.load_image(root / page["clean"]).convert("RGB"))
    final = np.asarray(ir.load_image(root / page["final"]).convert("RGB"))
    x, y, w, h = survived["mask_box"]
    assert (cleaned[y:y + h, x:x + w] != final[y:y + h, x:x + w]).any(), (
        "the surviving region's Persian was rolled back with its neighbour's")


def test_ink_that_lands_in_the_next_balloon_is_not_authorised(finished):
    """The authority was one page-wide union of every region's area, so ink
    from one balloon landing inside the next was authorised — by the
    neighbour's permission, which is not this region's to spend."""
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    regions = [r for r in page["regions"]
               if not r.get("dropped") and r.get("mask_box")]
    if len(regions) < 2:
        pytest.skip("this fixture has only one maskable region")

    # Move the second region's box on top of the first, so anything the first
    # one spills is inside an area the union would have allowed.
    regions[1]["mask_box"] = list(regions[0]["mask_box"])
    regions[1]["balloon"] = None
    for region in regions:
        region["target_text"] = "بله"
    ir.save_doc(doc, finished)

    typeset.typeset_document(finished, pages=[page["id"]])

    # Whatever the outcome, no region may report ink outside its OWN area as
    # acceptable: the page-wide union is gone.
    for region in ir.load_doc(finished)["pages"][0]["regions"]:
        record = region.get("typeset") or {}
        if record.get("outside_authorised"):
            assert record["status"] == "overflow", record
