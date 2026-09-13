"""Names and recurring terms: what is proposed, what is binding, and what a
change to an approved form is owed.

Split out of `test_export_and_glossary.py`, which had grown past the size a
file stays readable at.
"""

from __future__ import annotations

import json

import pageir as ir
import glossary
import qa
import sheet


# --- Glossary ---------------------------------------------------------------

def test_scanning_collects_the_speakers(translated):
    report = glossary.scan(translated)
    doc = ir.load_doc(translated)
    entries = doc["glossary"]["entries"]
    assert "هاروکا" in entries
    assert entries["هاروکا"]["role"] == "character"
    assert entries["هاروکا"]["count"] >= 1
    assert "هاروکا" in report["needs_persian"]


def test_a_short_line_repeated_across_the_chapter_is_a_candidate(translated):
    glossary.scan(translated)
    entries = ir.load_doc(translated)["glossary"]["entries"]
    assert "やめろ！" in entries


def test_a_long_line_is_not_a_name_candidate(translated):
    doc = ir.load_doc(translated)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "これはとても長い文章なので名前ではありません"
    ir.save_doc(doc, translated)
    glossary.scan(translated)
    entries = ir.load_doc(translated)["glossary"]["entries"]
    assert not any(len(name) > glossary.MAX_NAME_LENGTH for name in entries)


def test_a_hand_written_table_can_be_applied(translated, tmp_path):
    table = tmp_path / "names.json"
    ir.write_text(table, '{"ハルカ": {"target": "هاروکا", "role": "character"}}')
    report = glossary.apply_file(translated, table)
    assert report["applied"] == 1
    entry = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert entry["target"] == "هاروکا" and entry["locked"] is True


def test_checking_with_no_locked_terms_is_a_pass(translated):
    assert glossary.check(translated)["ok"]


def test_a_term_absent_from_the_balloon_cannot_have_drifted(translated):
    doc = ir.load_doc(translated)
    doc["glossary"] = {"entries": {"ケンジ": {"target": "کنجی", "locked": True}}}
    ir.save_doc(doc, translated)
    assert glossary.check(translated)["ok"]


# --- R06: names, presented honestly and matched sensibly ---------------------

def _entries(doc_path, table):
    doc = ir.load_doc(doc_path)
    doc["glossary"] = {"entries": table}
    ir.save_doc(doc, doc_path)
    return doc


def test_unlocked_names_are_not_presented_as_binding(translated):
    """The table is headed "these are binding. Use exactly the Persian given."
    and then listed every entry that had a `target` — including the ones nobody
    had locked, which are the tool's own guesses. A translator told a guess is
    binding will spell the rest of the chapter to match it."""

    _entries(translated, {
        "ハルカ": {"target": "هاروکا", "locked": True, "role": "character"},
        "ケンジ": {"target": "کنجی", "locked": False, "role": "character"},
    })
    lines = sheet._glossary_table(ir.load_doc(translated))
    text = "\n".join(lines)

    assert "هاروکا" in text, "the locked name is missing"
    if "کنجی" in text:
        marks = [text.find(word) for word in
                 ("not binding", "Suggestion", "suggestion")]
        marks = [index for index in marks if index >= 0]
        assert marks and min(marks) < text.index("کنجی"), (
            "an unlocked guess is printed under the binding heading")


def test_a_long_name_is_not_clipped(translated):
    """Names were cut to 21 characters with no ellipsis, so the worksheet asked
    for a spelling that was not the spelling."""

    long_name = "هاروکا-تاچیبانا-شینومیا"
    assert len(long_name) > 21
    _entries(translated, {"X": {"target": long_name, "locked": True}})
    text = "\n".join(sheet._glossary_table(ir.load_doc(translated)))
    assert long_name in text, "the binding spelling was truncated"


def test_a_locked_name_is_never_pushed_out_by_suggestions(translated):
    """The table stopped after 40 rows with nothing said about it. Fill it with
    unlocked guesses and the one term that actually matters falls off the end —
    silently, so the chapter spells it two ways."""

    table = {f"guess{n}": {"target": f"حدس{n}", "locked": False}
             for n in range(60)}
    table["ハナ"] = {"target": "هانا", "locked": True, "role": "character"}
    _entries(translated, table)

    text = "\n".join(sheet._glossary_table(ir.load_doc(translated)))
    assert "هانا" in text, "the one locked term was pushed out by guesses"
    assert "60" in text or "not shown" in text or "more" in text, (
        "entries were left out with nothing saying so")


def test_a_short_latin_name_does_not_match_inside_a_longer_one(translated):
    """`Ann` inside `Anna` is not an occurrence of `Ann`, and reporting it as
    drift sends a translator to correct something that is already right."""
    import glossary

    doc = _entries(translated, {"Ann": {"target": "آن", "locked": True}})
    region = next(region for _, region in ir.iter_regions(doc))
    region["source_text"] = "Anna went home"
    # Deliberately without `آن` anywhere: otherwise the drift test passes
    # because the expected Persian happens to be a prefix of the real one.
    region["target_text"] = "او به خانه رفت"
    ir.save_doc(doc, translated)

    assert glossary.check(translated)["drift"] == []


def test_a_cjk_term_still_matches_inside_a_phrase(translated):
    """The fix for the line above must not be a word boundary: Japanese has no
    spaces, so `\\b束\\b` never matches anything and every CJK term would stop
    being enforced."""
    import glossary

    doc = _entries(translated, {"束": {"target": "دسته", "locked": True}})
    region = next(region for _, region in ir.iter_regions(doc))
    region["source_text"] = "束の間の休息"
    region["target_text"] = "استراحتی کوتاه"
    ir.save_doc(doc, translated)

    assert glossary.check(translated)["drift"], "a CJK term stopped being enforced"


def test_term_counts_are_refreshed_on_a_rescan(translated):
    """Speaker counts were refreshed and term counts were not, so a term that
    had almost left the chapter still looked like its most common word."""
    import glossary

    doc = ir.load_doc(translated)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
    ir.save_doc(doc, translated)
    glossary.scan(translated)
    before = ir.load_doc(translated)["glossary"]["entries"]["やめろ"]["count"]
    assert before >= 2

    doc = ir.load_doc(translated)
    for index, (_, region) in enumerate(ir.iter_regions(doc)):
        if index:
            region["source_text"] = "べつに"
    ir.save_doc(doc, translated)
    glossary.scan(translated)

    after = ir.load_doc(translated)["glossary"]["entries"]["やめろ"]["count"]
    assert after < before, f"the count stayed at {after} after the text changed"


def test_drift_totals_count_every_finding(translated):
    """`check` caps its list at 30 for display and reports the true total beside
    it. The gate filed one finding per row of the CAPPED list, so a chapter with
    50 drifting regions was reported as having 30."""
    import glossary

    doc = _entries(translated, {"やめろ": {"target": "بس کن", "locked": True}})
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
        region["target_text"] = "چیز دیگری"
    ir.save_doc(doc, translated)

    result = glossary.check(translated)
    report = qa.check_document(translated)
    filed = report["by_code"].get("glossary-drift", 0)
    assert filed == result["drift_count"], (
        f"filed {filed} of {result['drift_count']} drifting regions")


# --- a proposal is a candidate, and a canonical form keeps its history --------

def test_a_proposed_name_becomes_a_candidate_without_a_speaker(translated):
    doc = ir.load_doc(translated)
    for _page, region in ir.iter_regions(doc):
        region.pop("speaker", None)
    doc["pages"][0]["regions"][0]["proposed"] = ["Anna"]
    ir.save_doc(doc, translated)

    glossary.scan(translated)

    entry = ir.load_doc(translated)["glossary"]["entries"]["Anna"]
    assert entry["role"] == "mentioned"
    assert entry["count"] == 1


def test_being_mentioned_does_not_demote_a_character(translated):
    """A character who is also named in someone else's balloon must not stop
    being a character because the mention was scanned second."""
    doc = ir.load_doc(translated)
    doc["pages"][0]["regions"][0]["speaker"] = "Anna"
    doc["pages"][0]["regions"][-1]["proposed"] = ["Anna"]
    ir.save_doc(doc, translated)

    glossary.scan(translated)

    assert ir.load_doc(translated)["glossary"]["entries"]["Anna"]["role"] == \
        "character"


def test_changing_a_locked_form_keeps_the_one_it_replaces():
    """An approved spelling is a decision. Re-deciding it must not erase the
    chapter already translated against the first one."""
    entry = glossary._entry("Anna", role="character")
    glossary.set_target(entry, "آنا")
    assert entry["version"] == 1 and "previous" not in entry

    entry["locked"] = True
    glossary.set_target(entry, "آنّا")

    assert entry["target"] == "آنّا"
    assert entry["version"] == 2
    assert entry["previous"] == [{"target": "آنا", "version": 1}]


def test_an_unlocked_suggestion_has_no_history_to_keep():
    entry = glossary._entry("Ken", role="character")
    glossary.set_target(entry, "کن")
    glossary.set_target(entry, "کِن")
    assert entry["version"] == 1 and "previous" not in entry


# --- R5: history on the path the docs tell you to use ------------------------

def _table(tmp_path, payload):
    path = tmp_path / "names.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_the_documented_apply_path_keeps_the_form_it_replaces(translated, tmp_path):
    """`set_target` preserved the previous spelling and bumped the version, and
    `glossary apply --table` — the route the docs tell you to use — assigned
    `entry["target"]` directly and preserved nothing. The guarantee existed
    only for callers that already knew about it."""
    glossary.apply_file(translated, _table(tmp_path, {"ハルカ": "هاروکا"}))
    glossary.apply_file(translated, _table(tmp_path, {"ハルカ": "هارُکا"}))

    entry = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert entry["target"] == "هارُکا"
    assert entry["version"] == 2
    assert entry["previous"] == [{"target": "هاروکا", "version": 1}]


def test_lines_translated_against_the_old_spelling_are_named_not_rewritten(
        translated, tmp_path):
    """A translation is a person's work, and a search-and-replace through it is
    how a name ends up inside another word."""
    doc = ir.load_doc(translated)
    region = doc["pages"][0]["regions"][0]
    region["source_text"] = "ハルカ"
    region["target_text"] = "هاروکا آمد"
    ir.save_doc(doc, translated)

    glossary.apply_file(translated, _table(tmp_path, {"ハルカ": "هاروکا"}))
    report = glossary.apply_file(translated, _table(tmp_path, {"ハルカ": "هارُکا"}))

    assert region["id"] in report["needs_review"], report
    assert report["revised"][0]["was"] == "هاروکا"
    # Untouched, on purpose.
    assert ir.find_region(ir.load_doc(translated),
                          region["id"])["target_text"] == "هاروکا آمد"


def test_an_unchanged_apply_is_not_a_new_version(translated, tmp_path):
    glossary.apply_file(translated, _table(tmp_path, {"ハルカ": "هاروکا"}))
    glossary.apply_file(translated, _table(tmp_path, {"ハルカ": "هاروکا"}))
    assert ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]["version"] == 1


def test_each_role_is_counted_separately_instead_of_overwriting(translated):
    """A name that speaks, is mentioned and repeats had its total overwritten
    twice, and whichever loop ran last decided the number."""
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    page["regions"][0]["speaker"] = "ハルカ"
    page["regions"][-1]["proposed"] = ["ハルカ"]
    ir.save_doc(doc, translated)

    glossary.scan(translated)

    entry = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert entry["counts"]["speaker"] == 1
    assert entry["counts"]["mentioned"] == 1
    assert entry["count"] == sum(entry["counts"].values())


def test_a_role_that_stopped_occurring_counts_zero(translated):
    doc = ir.load_doc(translated)
    doc["pages"][0]["regions"][0]["speaker"] = "ハルカ"
    ir.save_doc(doc, translated)
    glossary.scan(translated)

    doc = ir.load_doc(translated)
    doc["pages"][0]["regions"][0].pop("speaker")
    ir.save_doc(doc, translated)
    glossary.scan(translated)

    entry = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert entry["counts"]["speaker"] == 0


def test_a_short_name_is_not_matched_inside_a_longer_one():
    """`Ann` matched inside `Anna` and reported drift on a name the balloon
    never used."""
    assert not glossary._mentions("Ann", "did you see Anna?")
    assert glossary._mentions("Ann", "did you see Ann?")


def test_an_accented_or_multiword_name_matches_itself():
    assert glossary._mentions("Renée", "Renée left")
    assert glossary._mentions("the Iron Gate", "past the  Iron  Gate today")
    assert not glossary._mentions("the Iron Gate", "the gate was iron")


def test_a_cjk_term_is_still_enforced():
    """Japanese has no spaces, so a word-boundary test never matches one at all
    and every CJK term would quietly stop being enforced."""
    assert glossary._mentions("ハルカ", "それでハルカは言った")
    assert glossary._mentions("هاروکا", "هاروکای عزیز")


def test_an_approved_alias_counts_as_the_term(translated, tmp_path):
    """Aliases are written down, never guessed: a guessed inflection enforced
    as a constraint is a wrong name presented as a decision."""
    glossary.apply_file(translated, _table(tmp_path, {
        "Ann": {"target": "آن", "aliases": ["Annie"], "locked": True}}))
    doc = ir.load_doc(translated)
    entry = doc["glossary"]["entries"]["Ann"]
    assert glossary._mentions("Ann", "Annie waved", entry)
    assert not glossary._mentions("Ann", "Anthony waved", entry)


def test_drift_accepts_any_approved_persian_form(translated, tmp_path):
    glossary.apply_file(translated, _table(tmp_path, {
        "ハルカ": {"target": "هاروکا", "target_forms": ["هاروکای"],
                 "locked": True}}))
    doc = ir.load_doc(translated)
    region = doc["pages"][0]["regions"][0]
    region["source_text"] = "ハルカ"
    region["target_text"] = "هاروکای عزیز"
    ir.save_doc(doc, translated)

    assert glossary.check(translated)["ok"], glossary.check(translated)["drift"]
