"""Compression approval belongs to both Persian texts and their source."""

import pytest

import falint
import pageir as ir
import qa
import typeset
import worksheet


@pytest.mark.parametrize("field,value", [
    ("target_full", "من می‌خواهم بروم."),
    ("target_text", "می‌روم."),
    ("source_text", "I want to go."),
    (None, None),
])
def test_compression_review_remains_bound_after_rerender(finished, field, value):
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    region = next(r for r in page["regions"] if r["kind"] == "speech")
    region.update(target_text="نمی‌روم.", target_full="من نمی‌خواهم بروم.",
                  source_text="I do not want to go.")
    falint.record_acknowledgement(region, ["compressed-variant"], region["target_text"])
    if field:
        region[field] = value
    ir.save_doc(doc, finished)
    typeset.typeset_document(finished, pages=[page["id"]])
    report = qa.check_document(finished, limit=None)
    reopened = any(item["code"] == "compressed-variant" and item["where"] == region["id"]
                   for item in report["findings"])
    assert reopened == bool(field), report["findings"]
    if field:
        current = ir.load_doc(finished)
        text = worksheet.page_worksheet(current, current["pages"][0], ir.page_fingerprint(page))
        block = worksheet.parse_worksheet(text)[region["id"]]
        assert "compressed-variant" not in block.get("reviewed", "")


def test_new_approval_retains_the_previous_pair():
    region = ir.new_region("p0001r001", [10, 10, 50, 50], kind="speech")
    region.update(source_text="Do not go.", target_text="نرو.", target_full="لطفاً نرو.")
    falint.record_acknowledgement(region, ["compressed-variant"], region["target_text"])
    region["target_full"] = "هیچ وقت نرو."
    falint.record_acknowledgement(region, ["compressed-variant"], region["target_text"])
    assert "لطفاً نرو." in ir.dumps(region.get("review_ack_history", []))


@pytest.mark.parametrize("field,old,new", [
    ("fa_full", "من نمی‌خواهم بروم.", "من می‌خواهم بروم."),
    ("fa", "نمی‌روم.", "می‌روم."),
    ("src", "I do not want to go.", "I want to go."),
])
def test_a_carried_approval_does_not_approve_an_edited_worksheet(finished, field, old, new):
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    region = next(r for r in page["regions"] if r["kind"] == "speech")
    region.update(target_text="نمی‌روم.", target_full="من نمی‌خواهم بروم.",
                  source_text="I do not want to go.")
    falint.record_acknowledgement(region, ["compressed-variant"], region["target_text"])
    ir.save_doc(doc, finished)
    worksheet.build_document(finished, pages=[page["id"]])
    folder = finished.parent / "worksheets"
    text = ir.read_text(folder / (page["id"] + ".txt"))
    text = text.replace(f"{field}: {old}", f"{field}: {new}", 1)
    ir.write_text(folder / (page["id"] + ".done.txt"), text)
    assert worksheet.merge_document(finished, pages=[page["id"]])["ok"]
    typeset.typeset_document(finished, pages=[page["id"]])
    report = qa.check_document(finished, limit=None)
    assert any(item["code"] == "compressed-variant" and item["where"] == region["id"]
               for item in report["findings"]), report
