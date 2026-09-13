"""Reading a reply back: what lands, what is refused, and what a second merge
must not undo.

Split out of `test_worksheet.py`, which had grown past the size a file stays
readable at.
"""

from __future__ import annotations

import pytest

import pageir as ir
import worksheet
from test_worksheet import (  # the helpers this half shares with the other
    _add_fields, _fill, _finish, _set_fields, _sheets,
)


# --- a mentioned name is not the speaker -------------------------------------

def test_a_mentioned_name_is_recorded_without_claiming_the_balloon(detected):
    """The glossary was fed from `speaker:` alone, so the only way to get a name
    that is merely talked about — "did you see Anna?" — into the table was to
    write it in `speaker:`. That then told every later page that the wrong
    character was talking, and carried the wrong voice into their context."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    region = page["regions"][0]["id"]

    sheet = ir.read_text(_sheets(detected) / f"{page['id']}.txt")
    sheet = _add_fields(sheet, region,
                        "speaker: Ken", "propose: Anna, the Iron Gate")
    _finish(detected, page["id"], sheet)
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])
    worksheet.merge_document(detected)

    merged = ir.find_region(ir.load_doc(detected), region)
    assert merged["speaker"] == "Ken"
    assert merged["proposed"] == ["Anna", "the Iron Gate"]


def test_a_proposal_round_trips_through_a_rebuilt_worksheet(detected):
    """An absent field resets at the next merge, so a rebuilt worksheet that
    forgets a proposal quietly undoes it — the same defect `drop`, `keep` and
    `erase` already had."""
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    page["regions"][0]["proposed"] = ["Anna", "the Iron Gate"]
    ir.save_doc(doc, detected)

    reloaded = ir.load_doc(detected)
    body = worksheet.page_worksheet(reloaded, reloaded["pages"][0],
                                    ir.page_fingerprint(reloaded["pages"][0]))
    assert "propose: Anna, the Iron Gate" in body


def test_a_proposal_merged_twice_is_not_listed_twice(detected):
    """Merging the same reply again is an ordinary thing to do."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    region = page["regions"][0]["id"]

    sheet = _add_fields(
        ir.read_text(_sheets(detected) / f"{page['id']}.txt"),
        region, "propose: Anna")
    _finish(detected, page["id"], sheet)
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])
    worksheet.merge_document(detected)
    worksheet.merge_document(detected)

    assert ir.find_region(ir.load_doc(detected), region)["proposed"] == ["Anna"]


def test_the_title_policy_is_printed_where_the_reader_is(detected):
    """A policy filed somewhere else is a policy that gets re-decided every
    chapter."""
    doc = ir.load_doc(detected)
    doc["meta"]["title_policy"] = {"honorifics": "keep -senpai, drop -san",
                                   "slang": "   "}
    ir.save_doc(doc, detected)

    reloaded = ir.load_doc(detected)
    body = worksheet.page_worksheet(reloaded, reloaded["pages"][0],
                                    ir.page_fingerprint(reloaded["pages"][0]))
    assert "# This title has settled:" in body
    assert "#   honorifics: keep -senpai, drop -san" in body
    assert "slang" not in body        # an empty entry is not a decision


# --- R2: a page reply lands whole, twice, or not at all ----------------------

def _one_page(detected, *fields, region=0):
    """A complete, finished reply for every page, with `fields` set on one
    region of the first.

    Complete on purpose: a page with an untranslated region is not `clean`, and
    half the behaviour under test here — skipping a reply that has already
    landed whole — only happens for a page that landed whole.
    """
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    region_id = page["regions"][region]["id"]
    path = _sheets(detected) / f"{page['id']}.done.txt"
    ir.write_text(path, _set_fields(ir.read_text(path), region_id, *fields))
    return page["id"], region_id


@pytest.mark.parametrize("pair", [
    ("drop: yes", "keep: yes"),
    ("drop: yes", "erase: yes"),
    ("keep: yes", "erase: yes"),
])
def test_two_opposite_actions_refuse_the_page_and_fail_the_command(detected, pair):
    """`drop` returned before the conflict check even ran, so `drop: yes`
    beside `erase: yes` merged as if the reader had asked for one thing. And
    `keep`+`erase` was reported while the command still exited 0."""
    page_id, region_id = _one_page(detected, *pair)
    report = worksheet.merge_document(detected)

    assert report["conflicting_actions"], report
    assert not report["ok"], "the command reported success on a refused page"

    region = ir.find_region(ir.load_doc(detected), region_id)
    assert not region.get("dropped") and not region.get("keep")
    assert not region.get("erase"), "part of a refused page was committed"
    assert ir.find_page(ir.load_doc(detected), page_id)["worksheet_clean"] is False


def test_a_repeated_field_is_refused_rather_than_silently_last_wins(detected):
    """Two `fa:` lines in one block kept the last. A reader who pasted a
    correction under the original shipped the original."""
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    page_id = doc["pages"][0]["id"]
    region_id = doc["pages"][0]["regions"][0]["id"]
    path = _sheets(detected) / f"{page_id}.done.txt"
    # Deliberately APPENDED, which is what a reader pasting a correction under
    # the line they meant to replace actually produces.
    ir.write_text(path, _add_fields(ir.read_text(path), region_id,
                                    "fa: نسخهٔ دوم"))

    report = worksheet.merge_document(detected)
    assert report["duplicate_fields"], report
    assert not report["ok"]


def test_an_invalid_kind_stops_the_page_being_clean(detected):
    _one_page(detected, "kind: banana")
    report = worksheet.merge_document(detected)
    assert report["bad_kind"] and not report["ok"]
    assert ir.load_doc(detected)["pages"][0]["worksheet_clean"] is False


def test_a_kind_correction_merges_and_is_not_stale_on_the_next_run(detected):
    """A correction moves that page's fingerprint, so the reply that carried it
    reported itself stale to the very next merge and the reader was told to
    redo work they had only corrected."""
    _one_page(detected, "kind: sign")
    first = worksheet.merge_document(detected)
    assert not first["stale_worksheets"], first

    second = worksheet.merge_document(detected)
    assert not second["stale_worksheets"], second
    assert second["unchanged"], "the same reply was applied a second time"


def test_merging_an_unchanged_reply_again_keeps_the_normalised_persian(detected):
    """`falint` rewrites the Persian in place — half-spaces, digits,
    punctuation. Re-merging the same reply overwrote it with the raw text the
    reader typed, so a correction was undone by a merge that changed nothing."""
    worksheet.build_document(detected)
    _fill(detected)
    worksheet.merge_document(detected)
    doc = ir.load_doc(detected)
    region_id = doc["pages"][0]["regions"][0]["id"]
    ir.find_region(doc, region_id)["target_text"] = "می‌روم"      # as falint left it
    doc["pages"][0]["worksheet_clean"] = True
    ir.save_doc(doc, detected)

    worksheet.merge_document(detected)

    assert ir.find_region(ir.load_doc(detected), region_id)["target_text"] == "می‌روم"


def test_an_empty_field_clears_the_decision_it_set(detected):
    """Absent and present-but-empty were the same thing, so a speaker typed on
    the wrong balloon could only be taken back by editing `comic.json`."""
    page_id, region_id = _one_page(detected, "speaker: Ken", "propose: Anna")
    worksheet.merge_document(detected)
    assert ir.find_region(ir.load_doc(detected), region_id)["speaker"] == "Ken"

    worksheet.build_document(detected)
    _fill(detected)
    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, _set_fields(ir.read_text(path), region_id,
                                    "speaker:", "propose:"))
    worksheet.merge_document(detected)

    region = ir.find_region(ir.load_doc(detected), region_id)
    assert "speaker" not in region and "proposed" not in region


def test_a_hash_inside_a_balloon_is_dialogue_not_a_comment(detected):
    """A leading `#` meant comment wherever it appeared, so a balloon reading
    `#1` — or a second line beginning `#2` — was deleted with no word about it.
    """
    blocks = worksheet.parse_worksheet(
        "@@ r1 speech horizontal\n"
        "# panel p0001n02, reading order 1\n"
        "fa: خط اول\n"
        "#2 هم هست\n")
    assert blocks["r1"]["fa"] == "خط اول\n#2 هم هست"
    assert "panel" not in blocks["r1"]["fa"], "a note to the reader was read as speech"


def test_a_balloon_that_really_starts_with_a_hash_space_can_be_escaped():
    blocks = worksheet.parse_worksheet(
        "@@ r1 speech horizontal\nfa: خط اول\n" + chr(92) + "# و بعد\n")
    assert blocks["r1"]["fa"] == "خط اول\n# و بعد"


def test_a_reply_from_an_older_build_is_migrated_rather_than_called_stale(
        detected):
    """The old stamp hashed the whole document; this one hashes the page. After
    the change every genuinely old reply matched nothing, and the reader was
    told to translate the chapter again."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    path = _sheets(detected) / f"{page_id}.done.txt"
    text = ir.read_text(path)
    # An older build: a stamp that is neither hash, and no `# scheme:` line.
    text = worksheet.FINGERPRINT.sub("# fingerprint: " + "b" * 64, text, count=1)
    text = worksheet.SCHEME_LINE.sub("", text, count=1)
    ir.write_text(path, text)

    report = worksheet.merge_document(detected)
    assert page_id in report["legacy_worksheets"], report
    assert page_id not in report["stale_worksheets"]
    # And it is re-stamped, so it is verified from here on.
    assert worksheet.SCHEME_LINE.search(ir.read_text(path))


def test_a_reply_written_against_moved_regions_is_still_refused(detected):
    """Migration must not become "accept anything": a reply that says which
    scheme it was written under and disagrees is stale."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, worksheet.FINGERPRINT.sub(
        "# fingerprint: " + "c" * 64, ir.read_text(path), count=1))

    report = worksheet.merge_document(detected)
    assert page_id in report["stale_worksheets"], report


def test_building_one_page_is_not_blocked_by_another_pages_stale_reply(detected):
    """A completed reply going stale is a fact about THAT page, and it stopped
    a page the reader had never touched from being written at all."""
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    path = _sheets(detected) / f"{first}.done.txt"
    ir.write_text(path, worksheet.FINGERPRINT.sub(
        "# fingerprint: " + "d" * 64, ir.read_text(path), count=1))

    assert worksheet.build_document(detected, pages=[first]).get("refused")
    assert not worksheet.build_document(detected, pages=[second]).get("refused")


def test_merging_one_page_leaves_the_others_alone(detected):
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    second = doc["pages"][1]["id"]
    report = worksheet.merge_document(detected, pages=[second])
    assert report["merged"] > 0
    assert not ir.load_doc(detected)["pages"][0].get("worksheet_digest")


def test_an_added_box_with_no_persian_is_not_reported_clean(detected):
    """A box the reader added with nothing in it is exactly as unfinished as a
    detected balloon with nothing in it."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    sheet = ir.read_text(_sheets(detected) / f"{page['id']}.txt")
    sheet += "\n@@ +missed sfx horizontal\nbox: 100 100 300 120\nsrc: BOOM\nfa: \n"
    _finish(detected, page["id"], sheet)
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])

    report = worksheet.merge_document(detected)
    assert report["empty_translation"], report
    assert not report["ok"]


def test_correcting_an_added_box_refreshes_what_was_derived_from_it(detected):
    """Editing a `+slug` updated the box and nothing else: not the polarity,
    not the orientation, and not the mask, cleaned pixels or lettering that
    were derived from the box it used to be."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    base = ir.read_text(_sheets(detected) / f"{page['id']}.txt")
    _finish(detected, page["id"], base
            + "\n@@ +missed sfx horizontal\nbox: 100 100 300 120\n"
              "src: BOOM\nfa: بوم\n")
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])
    worksheet.merge_document(detected)

    doc = ir.load_doc(detected)
    added = next(r for r in doc["pages"][0]["regions"]
                 if r.get("added_as") == "missed")
    added.update({"mask": "masks/x.png", "mask_box": [1, 2, 3, 4],
                  "fill": "flat", "typeset": {"size": 20},
                  "balloon": {"cx": 1}})
    ir.save_doc(doc, detected)

    worksheet.build_document(detected)
    page_id = doc["pages"][0]["id"]
    base = ir.read_text(_sheets(detected) / f"{page_id}.txt")
    _finish(detected, page_id, base
            + "\n@@ +missed sfx vertical\nbox: 140 160 300 120\n"
              "polarity: dark\nsrc: BOOM\nfa: بوم\n")
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])
    worksheet.merge_document(detected)

    added = next(r for r in ir.load_doc(detected)["pages"][0]["regions"]
                 if r.get("added_as") == "missed")
    assert added["polarity"] == "dark"
    assert added["orientation"] == "vertical"
    assert added["mask"] is None and added["mask_box"] is None
    assert added["fill"] == "none" and added["typeset"] == {}


def test_status_tells_present_from_merged_from_edited_again(detected):
    """"Does the file exist" could not answer "is it in the document", and a
    reply edited after it was merged looked finished."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    assert worksheet.status(detected)["merged"] == []

    worksheet.merge_document(detected)
    after = worksheet.status(detected)
    assert page_id in after["merged"] and after["edited_since_merge"] == []

    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, ir.read_text(path).replace("fa: بس کن! چه خبر است؟",
                                                   "fa: چه خبر شده؟", 1))
    again = worksheet.status(detected)
    assert page_id in again["edited_since_merge"]
    assert page_id not in again["merged"]
