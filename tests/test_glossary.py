"""Names and recurring terms: what is proposed, what is binding, and what a
change to an approved form is owed.

Split out of `test_export_and_glossary.py`, which had grown past the size a
file stays readable at.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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

def _table(folder, payload):
    """A hand-written table on disk. `folder` so two tables in one test are two
    files: they were both `names.json`, so the second write reached the first
    apply and a test about two revisions applied one table twice."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "names.json"
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
    # Persian is NOT matched as a bare substring any more: `آنا` inside
    # `آنان` is the same shape, and accepting it made a line that never
    # mentions the character count as having rendered her name. An attached
    # spelling counts when a reader has written it down.
    assert not glossary._mentions("هاروکا", "هاروکای عزیز")
    assert glossary._mentions("هاروکا", "هاروکای عزیز",
                              {"aliases": ["هاروکای"]})
    assert glossary._mentions("هاروکا", "هاروکا عزیز است")


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


# --- C07: an approved name keeps its history, its aliases and its forms -----

def _named(doc_path, term="ハルカ", target="هاروکا", line="هاروکا آمد."):
    """One approved name, used by one approved line."""
    doc = ir.load_doc(doc_path)
    for _page, region in ir.iter_regions(doc):
        region["source_text"] = term
        region["target_text"] = line
    glossary.set_entry(doc, term, {"target": target, "locked": True,
                                   "role": "character"})
    ir.save_doc(doc, doc_path)
    return doc


def test_unlocking_and_renaming_in_one_edit_keeps_the_history(translated):
    """The ordinary way a decision gets revised. The caller applied the new
    `locked` first, so by the time the history was considered the entry was
    unlocked, there was "no decision to preserve", and the spelling the chapter
    had been translated against was dropped on the floor."""
    _named(translated)
    doc = ir.load_doc(translated)

    result = glossary.set_entry(doc, "ハルカ",
                                {"locked": False, "target": "هاروکه"})

    entry = doc["glossary"]["entries"]["ハルカ"]
    assert [row["target"] for row in entry["previous"]] == ["هاروکا"]
    assert entry["version"] == 2 and entry["locked"] is False
    assert result["was_locked"] is True


def test_approving_a_guess_does_not_fabricate_a_history(translated):
    """The other direction, and it must stay unchanged: an unlocked `target` is
    a suggestion, and locking one is a first decision, not a second."""
    doc = ir.load_doc(translated)
    glossary.set_entry(doc, "ケンジ", {"target": "کنجی"})

    glossary.set_entry(doc, "ケンジ", {"locked": True, "target": "کنجی"})

    entry = doc["glossary"]["entries"]["ケンジ"]
    assert not entry.get("previous")
    assert entry["version"] == 1


def test_target_forms_survive_apply_save_and_load(translated, tmp_path):
    """`check` enforces `target_forms`; `apply` silently dropped them, so the
    documented route could not write the field the gate reads."""
    table = tmp_path / "names.json"
    table.write_text(ir.dumps({
        "ハルカ": {"target": "هاروکا", "locked": True,
                   "target_forms": ["هاروکای", "هاروکارا"],
                   "aliases": ["ハル"]},
    }), encoding="utf-8")

    glossary.apply_file(translated, table)

    entry = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert entry["target_forms"] == ["هاروکای", "هاروکارا"]
    assert entry["aliases"] == ["ハル"]


def test_an_approved_form_is_not_reported_as_drift(translated):
    doc = ir.load_doc(translated)
    for _page, region in ir.iter_regions(doc):
        region["source_text"] = "ハルカ！"
        region["target_text"] = "هاروکای عزیز آمد."
    glossary.set_entry(doc, "ハルカ", {"target": "هاروکا", "locked": True,
                                      "target_forms": ["هاروکای"]})
    ir.save_doc(doc, translated)

    assert glossary.check(translated)["drift"] == []


def test_a_list_field_can_be_cleared(translated):
    doc = ir.load_doc(translated)
    glossary.set_entry(doc, "ハルカ", {"target": "هاروکا", "locked": True,
                                      "aliases": ["ハル"]})

    glossary.set_entry(doc, "ハルカ", {"aliases": []})

    assert doc["glossary"]["entries"]["ハルカ"]["aliases"] == []


def test_an_alias_only_mention_is_reported_as_affected(translated):
    """A balloon that calls the character by an approved alias was left out of
    the report, so a rename read as touching fewer lines than it did."""
    doc = ir.load_doc(translated)
    regions = [region for _page, region in ir.iter_regions(doc)]
    for region in regions:
        region["source_text"] = "ハルカ！"
        region["target_text"] = "هاروکا آمد."
    # One balloon uses the alias and nothing else.
    regions[-1]["source_text"] = "ハル！"
    glossary.set_entry(doc, "ハルカ", {"target": "هاروکا", "locked": True,
                                      "aliases": ["ハル"]})
    ir.save_doc(doc, translated)
    doc = ir.load_doc(translated)

    result = glossary.set_entry(doc, "ハルカ", {"target": "هاروکه"})

    assert regions[-1]["id"] in result["affected"], result
    assert len(result["affected"]) == len(regions)


def test_a_rescan_preserves_the_decision_and_refreshes_the_count(translated):
    _named(translated)
    before = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert before["locked"] and before["target"] == "هاروکا"

    glossary.scan(translated)

    after = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert after["locked"] and after["target"] == "هاروکا"
    # The live numbers live in `counts`, and a rescan refreshes them without
    # touching the decision beside them.
    assert after["counts"]["repeated"] >= 1, after


# --- A Persian name is not every word that starts the same way ---------------

def _locked(doc_path, term, target, line, **extra):
    """One locked name and one approved line that is supposed to use it."""
    doc = ir.load_doc(doc_path)
    for _page, region in ir.iter_regions(doc):
        region["source_text"] = term
        region["target_text"] = line
    glossary.set_entry(doc, term, {"target": target, "locked": True, **extra})
    ir.save_doc(doc, doc_path)
    return doc


def test_a_persian_name_inside_a_longer_word_is_not_that_name(translated):
    """The target side was a plain substring test, so the canonical `آنا` was
    found inside `آنان رسیدند` — *they arrived* — and a balloon that never
    mentions Anna counted as having rendered her name correctly."""
    _locked(translated, "Anna", "آنا", "آنان رسیدند")

    report = glossary.check(translated)

    assert not report["ok"], report
    assert report["drift"][0]["term"] == "Anna"


def test_the_name_itself_is_still_found(translated):
    """The control. A check that refuses the word it is looking for is not a
    check."""
    _locked(translated, "Anna", "آنا", "آنا رسید")

    assert glossary.check(translated)["ok"]


@pytest.mark.parametrize("line", [
    "آنا را دیدم",          # the direct-object marker, separated
    "آنا، بیا این‌جا",       # punctuation
    "آنا‌ی کوچک",            # the ezafe, joined by a zero-width non-joiner
    "(آنا)",                # brackets
])
def test_persian_attaches_around_a_name_without_changing_it(translated, line):
    """Persian puts clitics and punctuation straight against a word. A boundary
    test borrowed from Latin would report every one of these as drift."""
    _locked(translated, "Anna", "آنا", line)

    assert glossary.check(translated)["ok"], line


def test_an_attached_spelling_has_to_be_approved(translated):
    """`آناست` is a legitimate Persian form of the name and it is also exactly
    the shape a wrong match takes. Nothing infers it: a reader writes it
    down."""
    _locked(translated, "Anna", "آنا", "آناست که آمد")
    assert not glossary.check(translated)["ok"]

    doc = ir.load_doc(translated)
    glossary.set_entry(doc, "Anna", {"target_forms": ["آناست"]})
    ir.save_doc(doc, translated)

    assert glossary.check(translated)["ok"]


def test_a_cjk_target_is_matched_with_no_boundaries_at_all(translated):
    """A target in a script that has no spaces cannot be bounded, and applying
    a boundary test to one silently stops enforcing it."""
    _locked(translated, "Haruka", "ハルカ", "それはハルカだ")

    assert glossary.check(translated)["ok"]


def test_an_accented_latin_target_matches_itself_and_not_more(translated):
    _locked(translated, "Renee", "Renée", "Renée came back")
    assert glossary.check(translated)["ok"]

    _locked(translated, "Renee", "Renée", "Renéeta came back")
    assert not glossary.check(translated)["ok"]


# --- A payload is checked before any of it is written ------------------------

@pytest.mark.parametrize("field", ["aliases", "target_forms"])
def test_a_bare_string_is_not_a_list_of_forms(translated, field):
    """Iterating a string yields its CHARACTERS, so `aliases: "آنا"` approved
    the three forms `آ`, `ن` and `ا` — each of which appears in most Persian
    lines ever written."""
    doc = ir.load_doc(translated)

    with pytest.raises(ValueError, match="list of written forms"):
        glossary.set_entry(doc, "Anna", {field: "آنا"})

    assert "Anna" not in (doc.get("glossary") or {}).get("entries", {})


def test_a_refused_edit_changes_nothing_at_all(translated):
    """A half-applied entry is worse than a refused one: `locked` was written,
    then the malformed list raised, and the entry was left locked with the old
    target and nothing saying anything had failed."""
    doc = _locked(translated, "Anna", "آنا", "آنا رسید")
    before = dict(doc["glossary"]["entries"]["Anna"])

    with pytest.raises(ValueError):
        glossary.set_entry(doc, "Anna", {"locked": False, "target": "آنّا",
                                         "aliases": "wrong"})

    assert doc["glossary"]["entries"]["Anna"] == before


def test_a_table_that_fails_half_way_is_not_applied_at_all(translated,
                                                           tmp_path):
    """Otherwise the document holds some of somebody's decisions and no record
    of which ones."""
    table = _table(tmp_path, {"ハルカ": "هاروکا",
                              "Anna": {"target": "آنا", "aliases": "wrong"}})

    with pytest.raises(ValueError, match="not applied"):
        glossary.apply_file(translated, table)

    assert not (ir.load_doc(translated).get("glossary") or {}).get("entries")


def test_an_unknown_role_is_refused(translated):
    doc = ir.load_doc(translated)

    with pytest.raises(ValueError, match="role"):
        glossary.set_entry(doc, "Anna", {"role": "protagonist"})


def test_a_form_list_can_be_cleared(translated):
    """A form recorded by mistake has to be removable."""
    doc = ir.load_doc(translated)
    glossary.set_entry(doc, "Anna", {"target": "آنا", "target_forms": ["آناست"]})

    glossary.set_entry(doc, "Anna", {"target_forms": []})

    assert doc["glossary"]["entries"]["Anna"]["target_forms"] == []


def test_a_malformed_list_already_in_a_document_approves_nothing(translated):
    """Read defensively as well: a document may have been written by hand."""
    doc = _locked(translated, "Anna", "آنا", "آنان رسیدند")
    doc["glossary"]["entries"]["Anna"]["target_forms"] = "آنان"
    ir.save_doc(doc, translated)

    assert not glossary.check(translated)["ok"]


# --- Through the command people actually run ---------------------------------

def test_history_survives_the_command_line(translated, tmp_path, capsys):
    """Every supported edit path, which means the one with a `--table` in it."""
    first = _table(tmp_path / "one", {"ハルカ": "هاروکا"})
    second = _table(tmp_path / "two", {"ハルカ": {"target": "هارُکا",
                                                  "target_forms": ["هارُکای"]}})

    assert glossary.main(["apply", "--doc", str(translated),
                          "--table", str(first)]) == 0
    capsys.readouterr()
    assert glossary.main(["apply", "--doc", str(translated),
                          "--table", str(second)]) == 0
    capsys.readouterr()

    entry = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert entry["version"] == 2
    assert entry["previous"] == [{"target": "هاروکا", "version": 1}]
    assert entry["target_forms"] == ["هارُکای"]


def test_a_malformed_table_on_the_command_line_says_so(translated, tmp_path):
    table = _table(tmp_path, {"Anna": {"target": "آنا", "aliases": "wrong"}})

    with pytest.raises(ValueError, match="not applied"):
        glossary.main(["apply", "--doc", str(translated), "--table", str(table)])


# --- What the translator is told ---------------------------------------------

def test_the_approved_forms_reach_the_translator(translated):
    """`check` enforces every approved form and the translator was told only
    the headword, so a line it had no way of knowing was acceptable came back
    reported as drift."""
    import context as chapter_context

    _locked(translated, "Anna", "آنا", "آنا رسید", target_forms=["آنای"])
    doc = ir.load_doc(translated)
    package = chapter_context.build(doc, doc["pages"][0]["id"])

    assert package["constraints"]["glossary"]["Anna"] == {
        "target": "آنا", "forms": ["آنای"]}


def test_a_term_with_no_extra_forms_is_still_sent_as_a_plain_name(translated):
    import context as chapter_context

    _locked(translated, "Anna", "آنا", "آنا رسید")
    doc = ir.load_doc(translated)
    package = chapter_context.build(doc, doc["pages"][0]["id"])

    assert package["constraints"]["glossary"]["Anna"] == "آنا"
