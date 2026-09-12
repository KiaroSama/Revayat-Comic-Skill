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
    """A chain needs more than one pass: joining the first pair creates the
    next. This used to use `بزرگ تر ین`, which is no longer joined for us —
    `تر` is also the adjective "wet", so that join is reported instead. The
    requirement is unchanged and the plural family still shows it."""
    once = fix("کتاب ها ی")
    assert once.startswith(f"کتاب{ZWNJ}ها")
    assert fix(once) == once, "the chain did not settle in one call"


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


# --- R07: normalisation may not change what the sentence says ----------------

def test_a_separate_word_is_not_glued_into_a_suffix():
    """THE ONE THAT MATTERS. `تر` is both the comparative suffix and the
    ordinary adjective "wet". Gluing it turns "my hair got wet" into "my hair,
    more so, got" — a translation tool that silently rewrites the sentence is
    worse than one that leaves a typo. It is reported instead."""
    sentence = "موهایم تر شد."
    assert fix(sentence) == sentence
    assert any(issue["code"] == "zwnj-review"
               for issue in falint.lint_text(sentence))


def test_an_independent_mi_is_not_glued_to_the_next_word():
    """`می` is the verbal prefix and also the noun "wine"."""
    sentence = "می ناب بنوش."
    assert fix(sentence) == sentence
    assert any(issue["code"] == "zwnj-review"
               for issue in falint.lint_text(sentence))


def test_the_joins_that_cannot_be_ambiguous_still_happen():
    """Narrowing this must not switch the feature off. `نمی` is not a word on
    its own, and neither are the long possessive forms, so those are safe."""
    assert fix("نمی روم") == f"نمی{ZWNJ}روم"
    assert fix("کتاب هایم") == f"کتاب{ZWNJ}هایم"
    assert fix("کتاب هایشان") == f"کتاب{ZWNJ}هایشان"


@pytest.mark.parametrize("opaque", [
    "https://example.com/كتاب",
    "https://example.com/٤٢/page",
    "https://example.com/s?q=٤٢",
    "كتاب@example.com",
    'https://example.com/a"b"c',
    "https://example.com/wide\u0640path",
])
def test_an_opaque_span_keeps_its_exact_bytes(opaque):
    """Character folding, digit conversion and quote pairing all ran BEFORE the
    protection, so a URL came out rewritten: Arabic kaf folded to Persian kaf,
    Arabic-Indic digits turned Persian, straight quotes turned into guillemets,
    tatweel deleted. A rewritten URL is a dead link."""
    out = fix(f"اینجا را ببینید: {opaque} ممنون.")
    assert opaque in out, f"{opaque!r} was rewritten to {out!r}"


def test_a_nul_in_the_input_cannot_corrupt_the_masking():
    """The protection used `\x00<index>\x00` as its sentinel, so input holding
    that shape was unmasked into somebody else's text — or crashed."""
    # The requirement is that nothing is duplicated, swapped or raised — not
    # a particular rendering of a stray digit.
    first = falint.fix_text("\x000\x00 hello سلام")
    assert first.count("hello") == 1, first
    assert "سلام" in first and "\x00" not in first

    second = falint.fix_text("alpha beta \x000\x00")
    assert second.count("alpha") == 1 and second.count("beta") == 1, second

    third = falint.fix_text("سلام \x000\x00 خوبی")
    assert "سلام" in third and "خوبی" in third, third


@pytest.mark.parametrize("sample", [
    "قیمت 1,200 تومان است.",
    "او ۵; بعد رفت",
    "۹۹?ای وای",
    "کتاب ها ی من",
    "سلام… «خوبی؟» — بله!!!!",
    "او 3 بار گفت: نه، نه، نه.",
])
def test_normalisation_settles_in_one_pass(sample):
    """`fix_text` says it is idempotent. It was not: converting `1,200` made the
    comma Persian-adjacent, so a SECOND run turned it into `۱،۲۰۰`. Anything
    that keeps moving has no stable answer to store."""
    once = falint.fix_text(sample)
    assert falint.fix_text(once) == once, f"{sample!r} kept changing"


def test_digits_in_a_latin_sentence_are_left_alone():
    """`Vol. 2, ch. 3` is not Persian and its numerals are not Persian either."""
    assert fix("Vol. 2, ch. 3") == "Vol. 2, ch. 3"
    assert fix("او 3 بار گفت") == "او ۳ بار گفت"
