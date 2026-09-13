"""One chapter, all the way round, twice.

Every other suite takes one stage apart. This one does what a person does: it
builds worksheets, edits them the way a reader edits them — a kind, a box, a
polarity, a region added, another kept, another erased, another dropped, a note
cleared — merges, normalises the Persian, rebuilds the sheets, merges the same
reply again, renders, gates and exports.

The defects this shape catches are the ones that live BETWEEN stages: a merge
that undoes what `falint` normalised, a rebuild that forgets which worksheet a
page was consumed from, a second merge of a reply that has already landed, a
page with nothing detected on it falling out of the run, a stamp that belongs
to another document.
"""
from __future__ import annotations

from pathlib import Path


import clean
import crops
import export
import falint
import masks
import pageir as ir
import qa
import typeset
import worksheet
from test_worksheet import _fill, _set_fields, _sheets


def _text(doc_path, page_id, suffix="txt"):
    return ir.read_text(_sheets(doc_path) / f"{page_id}.{suffix}")


def _write(doc_path, page_id, text, suffix="done.txt"):
    ir.write_text(_sheets(doc_path) / f"{page_id}.{suffix}", text)


def test_a_whole_chapter_goes_round_twice_and_converges(detected, tmp_path):
    """The integrated path, end to end, with every kind of edit a reader makes
    in one reply — and then the same reply offered a second time."""
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    page_id = page["id"]
    regions = [region["id"] for region in page["regions"]]
    assert len(regions) >= 3, "the fixture page is too small for this"

    worksheet.build_document(detected)
    crops.build_document(detected)
    _fill(detected)

    # Everything a reader can say, in one reply.
    text = _text(detected, page_id, "done.txt")
    text = _set_fields(text, regions[0], "kind: sfx", "polarity: dark",
                       "box: 10,10,120,60", "note: ")
    text = _set_fields(text, regions[1], "keep: yes")
    text = _set_fields(text, regions[2], "erase: yes", "fa: ")
    if len(regions) > 3:
        text = _set_fields(text, regions[3], "drop: yes", "fa: ")
    text += ("\n@@ +box speech horizontal\n"
             "box: 40,200,150,70\n"
             "src: なに！\n"
             "fa: چه؟\n")
    _write(detected, page_id, text)

    merged = worksheet.merge_document(detected)
    assert page_id not in merged["missing_outputs"], merged
    assert not merged["duplicate_regions"] and not merged["duplicate_fields"]

    after = ir.load_doc(detected)["pages"][0]
    by_id = {region["id"]: region for region in after["regions"]}
    assert by_id[regions[0]]["kind"] == "sfx"
    assert by_id[regions[0]].get("polarity") == "dark"
    assert by_id[regions[1]].get("keep") is True
    assert by_id[regions[2]].get("erase") is True
    assert len(after["regions"]) > len(regions), "the added box did not land"

    # Normalise, rebuild the sheets from the merged document, and offer the
    # SAME reply again. Nothing may move.
    falint.fix_document(detected)
    settled = ir.dumps(ir.load_doc(detected)["pages"])
    worksheet.build_document(detected)
    again = worksheet.merge_document(detected)

    assert page_id in again["unchanged"], again
    # The pages, not the whole document: the stage stamp legitimately records
    # that this run merged nothing, and that is the point of it.
    assert ir.dumps(ir.load_doc(detected)["pages"]) == settled, (
        "a reply that had already landed moved the page")

    # And the rest of the pipeline still runs on it.
    masks.build_document(detected)
    clean.clean_document(detected)
    typeset.typeset_document(detected)
    state = qa.publication_preflight(detected)
    blocking = {item["code"] for item in state["blocking"]}
    # Whatever else is unfinished, the round trip must not have produced a page
    # that claims work it did not do.
    assert not blocking & {"delivery-mismatch", "page-not-cleaned",
                           "artwork-modified", "source-text-survived"}, blocking
    if state["ok"]:
        export.export_document(detected, tmp_path / "chapter.cbz")


def test_a_reply_corrupted_by_a_pasted_duplicate_is_refused_not_shortcut(
        detected):
    """The shortcut compares a digest. A pasted-in duplicate block hashed
    identically to the reply it corrupted, so a merge that should have refused
    reported the page as already landed and told the reader nothing had
    changed."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    worksheet.merge_document(detected)

    text = _text(detected, page_id, "done.txt")
    first = text[text.index("@@"):]
    _write(detected, page_id, text + "\n" + first)

    report = worksheet.merge_document(detected)

    assert report["duplicate_regions"], report
    assert page_id not in report["unchanged"]


def test_re_heading_an_added_block_is_not_an_invisible_edit(detected):
    """`_kind` and `_orientation` are the only place an added region\'s kind is
    written, so leaving them out of the digest made changing the `@@` line an
    edit the shortcut waved through."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    text = _text(detected, page_id, "done.txt")
    added = ("\n@@ +box speech horizontal\nbox: 40,200,150,70\n"
             "src: なに！\nfa: چه؟\n")
    _write(detected, page_id, text + added)
    worksheet.merge_document(detected)

    reheaded = (text + added).replace("@@ +box speech horizontal",
                                      "@@ +box sfx vertical")
    _write(detected, page_id, reheaded)
    report = worksheet.merge_document(detected)

    assert page_id not in report["unchanged"], report


def test_a_page_with_nothing_detected_on_it_stays_in_the_chapter(detected):
    """A page the detector found nothing on is a legitimate page — a splash, a
    title card — and it must not fall out of the run or block it."""
    doc = ir.load_doc(detected)
    page = doc["pages"][-1]
    page["regions"] = []
    ir.save_doc(doc, detected)

    worksheet.build_document(detected)
    _fill(detected)
    report = worksheet.merge_document(detected)

    assert page["id"] not in report["missing_outputs"], report
    masks.build_document(detected)
    clean.clean_document(detected)
    typeset.typeset_document(detected)
    after = ir.load_doc(detected)["pages"][-1]
    assert not after.get("final") and not after.get("clean")


def test_a_custom_worksheet_folder_survives_a_change_of_directory(detected,
                                                                  tmp_path,
                                                                  monkeypatch):
    """`worksheet build --out elsewhere` records the folder in `meta`, and the
    later commands answered the question separately. Resolving a recorded
    relative path against whatever directory the shell happens to be in is the
    same defect wearing a different hat."""
    elsewhere = tmp_path / "sheets"
    worksheet.build_document(detected, out=elsewhere)
    built = sorted(elsewhere.glob("*.txt"))
    assert built
    # An answered sheet, written where the reader was told to write it.
    for sheet in built:
        ir.write_text(sheet.with_suffix(".done.txt"), ir.read_text(sheet))

    monkeypatch.chdir(tmp_path.parent)
    doc = ir.load_doc(detected)
    found = ir.worksheet_folder(detected, doc)

    assert Path(found).resolve() == elsewhere.resolve()
    assert worksheet.status(detected)["present"], (
        "the recorded folder was resolved against the working directory")


def test_a_stamp_from_another_document_is_not_this_one(detected, imported):
    """A worksheet is stamped with the document it was built from. Merging a
    reply written for another chapter is the one mistake that cannot be
    corrected afterwards, because the ids match and the words do not."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    mine = _text(detected, page_id, "done.txt")

    stranger = ir.doc_dir(imported)
    (stranger / "worksheets").mkdir(parents=True, exist_ok=True)
    ir.write_text(stranger / "worksheets" / f"{page_id}.done.txt", mine)
    report = worksheet.merge_document(imported)

    assert not report.get("merged"), report
