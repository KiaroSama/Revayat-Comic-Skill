"""What a region ACTION means, and what a worksheet has to survive.

Four answers are possible about a region — translate it, keep it, drop it,
erase it — and exactly one of them stands at a time. Each one replaces what the
previous answer produced: the render, the cleaner's verdict, the measurement
taken off a box that has since moved. Getting that wrong is how a resolved
problem became permanent.

The second half is the protocol's own syntax appearing inside a balloon, which
is not a curiosity: `@@`, `fa:` and `# ` are ordinary characters in a comic.
"""
from __future__ import annotations

import pytest

import pageir as ir
import worksheet
from test_worksheet import (
    _add_fields, _fill, _finish, _set_fields, _sheets,
)
from test_worksheet_replies import _first_region


@pytest.mark.parametrize("first", ["keep", "erase"])
def test_dropping_a_region_replaces_the_answer_before_it(detected, first):
    """A region kept and then dropped carried both flags, the rebuilt sheet
    printed `drop: yes` beside `keep: yes`, and every later merge refused the
    page as contradicting itself — a state no reader could get out of."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id, region_id = _first_region(detected)
    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, _add_fields(ir.read_text(path), region_id,
                                    f"{first}: yes"))
    worksheet.merge_document(detected)
    assert ir.load_doc(detected)["pages"][0]["regions"][0].get(first)

    worksheet.build_document(detected)
    _fill(detected)
    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, _set_fields(ir.read_text(path), region_id,
                                    f"{first}: ", "drop: yes"))
    report = worksheet.merge_document(detected)

    assert not report["conflicting_actions"], report
    region = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert region["dropped"] and not region.get(first)

    # And the sheet built from it is mergeable, rather than contradicting
    # itself for ever.
    worksheet.build_document(detected)
    _finish(detected, page_id)
    assert not worksheet.merge_document(detected)["conflicting_actions"]


def test_a_resolved_cleaning_refusal_stops_blocking_publication(detected,
                                                               monkeypatch):
    """`clean` had a provider and the provider failed, so it refused the solid
    patch rather than reaching the tier that would blank the artwork. The
    reader answers `keep: yes` — and the refusal stayed on the region, so `qa`
    blocked the chapter for ever on a problem that had been answered."""
    import clean
    import providers
    import qa
    from test_lettering import _solid_free_page

    page, region = _solid_free_page(detected)
    monkeypatch.setitem(providers._REGISTRY["image_edit"], "broken",
                        lambda: providers.FakeImageEdit(fail="wrong_size"))
    clean.clean_document(detected, provider="broken", pages=[page["id"]])

    refused = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert refused["clean_status"] == "refused"
    assert any(item["code"] == "clean-refused"
               for item in qa.check_document(detected)["findings"])

    worksheet.build_document(detected)
    _fill(detected)
    path = _sheets(detected) / f"{page['id']}.done.txt"
    ir.write_text(path, _add_fields(ir.read_text(path), region["id"],
                                    "keep: yes"))
    worksheet.merge_document(detected)
    clean.clean_document(detected, provider="broken", pages=[page["id"]])

    after = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert after["clean_status"] == "kept", after
    assert not any(item["code"] == "clean-refused"
                   for item in qa.check_document(detected)["findings"])
    # The record of what happened survives; only the verdict was replaced.
    assert after.get("audit")


def test_an_added_box_that_only_erases_is_not_an_empty_translation(detected):
    """A box added purely to remove a watermark owes no Persian. The added-box
    path asked its own narrower question and reported it as unfinished work."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, ir.read_text(path) + (
        "\n@@ +stamp sign horizontal\n"
        "box: 8 8 140 40\nsrc: SCANLATED BY\nerase: yes\n"))

    report = worksheet.merge_document(detected)

    added = [region for region in ir.load_doc(detected)["pages"][0]["regions"]
             if region.get("added_as") == "stamp"][0]
    assert added["erase"] and not added.get("dropped")
    assert added["id"] not in report["empty_translation"], report


def test_an_added_effect_the_policy_keeps_is_not_an_empty_translation(detected):
    doc = ir.load_doc(detected)
    doc["meta"]["sfx_policy"] = "keep"
    ir.save_doc(doc, detected)
    worksheet.build_document(detected)
    _fill(detected)
    page_id = doc["pages"][0]["id"]
    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, ir.read_text(path) + (
        "\n@@ +boom sfx horizontal\nbox: 40 40 180 90\nsrc: ドーン\n"))

    report = worksheet.merge_document(detected)

    added = [region for region in ir.load_doc(detected)["pages"][0]["regions"]
             if region.get("added_as") == "boom"][0]
    assert added["id"] not in report["empty_translation"], report


def test_moving_an_added_box_drops_the_measurement_of_the_old_one(detected):
    """`lettering` is the shape `typeset` renders the Persian into, measured
    off the ink inside the box. It survived a correction that moved the box
    somewhere else entirely."""
    worksheet.build_document(detected)
    _fill(detected)
    page_id = ir.load_doc(detected)["pages"][0]["id"]
    path = _sheets(detected) / f"{page_id}.done.txt"
    ir.write_text(path, ir.read_text(path) + (
        "\n@@ +fx sfx horizontal\nbox: 20 20 160 70\nsrc: ドン\nfa: بوم\n"))
    worksheet.merge_document(detected)

    doc = ir.load_doc(detected)
    added = [region for region in doc["pages"][0]["regions"]
             if region.get("added_as") == "fx"][0]
    added["lettering"] = {"verdict": "curved", "reason": "measured here"}
    added["clean_status"] = "cleaned"
    ir.save_doc(doc, detected)

    ir.write_text(path, ir.read_text(path).replace("box: 20 20 160 70",
                                                   "box: 600 700 160 70"))
    worksheet.merge_document(detected)

    after = [region for region in ir.load_doc(detected)["pages"][0]["regions"]
             if region.get("added_as") == "fx"][0]
    assert after["bbox"][:2] == [600, 700]
    assert "lettering" not in after and "clean_status" not in after
    assert after["mask"] is None


@pytest.mark.parametrize("payload", [
    "بله\nfa: این یک خط است",
    "چی؟\n@@ p0001r001 speech horizontal",
    "اول\n# دوم",
    "یک\\دو",
])
def test_a_balloon_may_contain_the_protocols_own_syntax(detected, payload):
    """A continuation line reading `fa: ...` was parsed as a second `fa:` and
    refused the page as a duplicate; one reading `@@ ...` started a new block
    and swallowed the rest of the balloon."""
    doc = ir.load_doc(detected)
    region = doc["pages"][0]["regions"][0]
    region["target_text"] = payload
    ir.save_doc(doc, detected)
    worksheet.build_document(detected)
    page_id = doc["pages"][0]["id"]
    _finish(detected, page_id)

    report = worksheet.merge_document(detected)

    assert not report["duplicate_fields"] and not report["unknown_regions"], report
    after = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert after["target_text"] == payload


def test_a_note_containing_a_field_prefix_round_trips(detected):
    doc = ir.load_doc(detected)
    doc["pages"][0]["regions"][0]["review"] = ["دو خط\nspeaker: کسی"]
    ir.save_doc(doc, detected)
    worksheet.build_document(detected)
    _finish(detected, ir.load_doc(detected)["pages"][0]["id"])

    worksheet.merge_document(detected)

    after = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert after["review"] == ["دو خط\nspeaker: کسی"]


# --- C04: one resolver for where the replies live ---------------------------

def test_build_and_status_find_a_persisted_custom_folder(detected, tmp_path):
    """`worksheet build --out elsewhere` records the folder. `build` and
    `status` with no `--out` then looked in the default, found nothing, and
    reported a chapter with a full set of finished replies as having none."""
    elsewhere = tmp_path / "replies"
    worksheet.build_document(detected, elsewhere)
    assert list(elsewhere.glob("*.txt"))

    doc = ir.load_doc(detected)
    for page in doc["pages"]:
        source = elsewhere / f"{page['id']}.txt"
        if source.exists():
            ir.write_text(elsewhere / f"{page['id']}.done.txt",
                          ir.read_text(source))

    state = worksheet.status(detected)

    assert state["present"] == [page["id"] for page in doc["pages"]
                                if page.get("regions")], state
    assert not (ir.doc_dir(detected) / "worksheets").exists()
    # And a rebuild with no `--out` writes there too, rather than starting a
    # second set somewhere the reader is not looking.
    worksheet.build_document(detected)
    assert not (ir.doc_dir(detected) / "worksheets").exists()
