"""Persian typography. Every rule here has a way of eating text if it is wrong."""

from __future__ import annotations

import pytest

import falint
import pageir as ir

ZWNJ = "‌"


def fix(text: str, **options) -> str:
    return falint.fix_text(text, falint.Options(**options))


# --- Character normalisation ------------------------------------------------

def test_arabic_letters_become_persian_ones():
    assert fix("كتاب ي") == "کتاب ی"


def test_tatweel_is_removed():
    assert "ـ" not in fix("سـلام")


def test_arabic_indic_digits_become_persian_ones():
    assert fix("٣٤") == "۳۴"


# --- Idempotence ------------------------------------------------------------

def test_running_twice_changes_nothing_the_second_time():
    """Python's \\d matches Persian digits too, so a digit rule written with it
    re-matches its own output on the second pass and crashes."""
    once = fix("نسخهٔ 25 صفحه، تازه است")
    assert fix(once) == once


@pytest.mark.parametrize("text", [
    "کتاب‌ها", "می‌روم", "«نقل قول»", "سلام… خوبی؟", "۱۲۳", "بس کن!",
])
def test_already_correct_text_is_left_alone(text):
    assert fix(text) == text


# --- ZWNJ -------------------------------------------------------------------

def test_a_plural_suffix_gets_a_zero_width_non_joiner():
    assert fix("کتاب ها") == f"کتاب{ZWNJ}ها"


def test_a_verb_prefix_gets_one_too():
    assert fix("می روم") == f"می{ZWNJ}روم"


def test_chained_suffixes_settle():
    assert fix("بزرگ تر ین") == f"بزرگ{ZWNJ}تر ین"


def test_zwnj_can_be_switched_off():
    assert fix("کتاب ها", zwnj=False) == "کتاب ها"


# --- Punctuation ------------------------------------------------------------

def test_a_comma_after_persian_becomes_a_persian_comma():
    assert fix("سلام, خوبی") == "سلام، خوبی"


def test_a_comma_inside_latin_text_is_left_alone():
    """`e.g., Smith` in a caption is not a Persian sentence."""
    assert "e.g., Smith" in fix("عنوان: e.g., Smith")


def test_a_url_survives_intact():
    text = "برو به https://example.com/a,b و برگرد"
    assert "https://example.com/a,b" in fix(text)


def test_three_dots_become_an_ellipsis():
    assert fix("خب...") == "خب…"


def test_straight_quotes_become_guillemets():
    assert fix('او گفت "برو"') == "او گفت «برو»"


def test_shouting_is_capped_not_removed():
    """Comic dialogue shouts. Seven marks is a typo; three is emphasis."""
    assert fix("برو!!!!!!!") == "برو!!!"
    assert fix("برو!!!") == "برو!!!"


def test_digits_can_be_kept_latin():
    assert fix("صفحه 25", digits="keep") == "صفحه 25"
    assert fix("صفحه 25") == "صفحه ۲۵"


# --- Line breaks ------------------------------------------------------------

def test_deliberate_line_breaks_in_a_balloon_survive():
    """A balloon that says two things on two lines is meant to."""
    assert fix("سلام\nخوبی؟") == "سلام\nخوبی؟"


# --- Linting ----------------------------------------------------------------

def _codes(text):
    return {issue["code"] for issue in falint.lint_text(text)}


def test_leftover_japanese_is_reported():
    assert "source-script-left" in _codes("بس کن やめろ")


def test_text_with_no_persian_at_all_is_reported():
    assert "untranslated" in _codes("Stop it right there")


def test_unbalanced_guillemets_are_reported():
    assert "guillemets" in _codes("او گفت «برو")


def test_arabic_forms_are_reported():
    assert "arabic-forms" in _codes("كتاب")


def test_clean_persian_reports_nothing():
    assert falint.lint_text("بس کن! این‌جا چه خبر است؟") == []


# --- Document driver --------------------------------------------------------

def test_fixing_a_document_touches_only_what_changed(translated):
    doc = ir.load_doc(translated)
    region = next(r for _, r in ir.iter_regions(doc))
    region["target_text"] = "كتاب ها, 25 تا"
    ir.save_doc(doc, translated)

    report = falint.fix_document(translated)
    assert region["id"] in report["changed"]
    fixed = ir.find_region(ir.load_doc(translated), region["id"])["target_text"]
    assert fixed == f"کتاب{ZWNJ}ها، ۲۵ تا"


def test_linting_a_document_groups_by_code(translated):
    doc = ir.load_doc(translated)
    next(r for _, r in ir.iter_regions(doc))["target_text"] = "やめろ بس"
    ir.save_doc(doc, translated)
    report = falint.lint_document(translated)
    assert report["by_code"].get("source-script-left") == 1


def test_a_leading_ellipsis_keeps_the_space_that_separates_two_sentences():
    """`...آره. ...ببخشید.` is two balloonfuls of speech, and the space between
    them is the only thing holding them apart.

    Stripping whitespace before punctuation is right for a comma and right for a
    full stop, and wrong for an ellipsis that *opens* a phrase — comic dialogue
    is full of those. Welded together the pair became one unbreakable
    thirteen-character token, which no line-wrapper can split, and the balloon
    overflowed. Found on a real page.
    """
    assert falint.fix_text("...آره. ...ببخشید.") == "…آره. …ببخشید."
    assert falint.fix_text("چی؟ ...نمی‌دانم") == "چی؟ …نمی‌دانم"


def test_a_trailing_ellipsis_still_closes_up():
    """The other half: nothing follows it, so the space before it is a typo."""
    assert falint.fix_text("سلام ...") == "سلام…"
    assert falint.fix_text("خوبم ، ممنون") == "خوبم، ممنون"
