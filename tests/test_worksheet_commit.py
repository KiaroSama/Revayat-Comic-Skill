"""A committed reader reply remains consumable across document/restamp failures."""

import copy
import re

import pytest

import pageir as ir
import worksheet


def _reply(doc_path):
    worksheet.build_document(doc_path)
    doc = ir.load_doc(doc_path)
    page = doc["pages"][0]
    region = page["regions"][0]
    text = worksheet.page_worksheet(doc, page, ir.page_fingerprint(page))
    header = next(line for line in text.splitlines() if line.startswith("@@ " + region["id"]))
    text = text.replace(header, header + "\nkind: thought", 1)
    path = doc_path.parent / "worksheets" / (page["id"] + ".done.txt")
    ir.write_text(path, text)
    return page["id"], region["id"], path


@pytest.mark.parametrize("operation", ["document", "restamp"])
@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize("stamp", ["page_stamp", "document_stamp"])
def test_accepted_merge_retry_converges(translated, monkeypatch, operation, side, stamp):
    page_id, region_id, path = _reply(translated)
    if stamp == "document_stamp":
        header = "# fingerprint: " + ir.fingerprint(ir.load_doc(translated))
        ir.write_text(path, worksheet.FINGERPRINT.sub(header, ir.read_text(path), count=1))
    before = ir.find_region(ir.load_doc(translated), region_id)["target_text"]
    module, name = (ir, "save_doc") if operation == "document" else (worksheet, "_restamp")
    original = getattr(module, name)

    def fail(*args, **kwargs):
        if side == "after":
            original(*args, **kwargs)
        raise OSError("interrupted merge receipt")

    monkeypatch.setattr(module, name, fail)
    with pytest.raises(OSError, match="receipt"):
        worksheet.merge_document(translated, pages=[page_id])
    monkeypatch.setattr(module, name, original)
    for _ in range(2):
        report = worksheet.merge_document(translated, pages=[page_id])
        assert report["ok"], report
        region = ir.find_region(ir.load_doc(translated), region_id)
        assert region["target_text"] == before
        assert region["kind"] == "thought"


def test_refused_stale_reply_cannot_refresh_its_stage(translated):
    page_id, region_id, _ = _reply(translated)
    assert worksheet.merge_document(translated, pages=[page_id])["ok"]
    doc = ir.load_doc(translated)
    ir.find_region(doc, region_id)["bbox"][0] += 1
    ir.save_doc(doc, translated)
    prior = copy.deepcopy(doc["stages"]["worksheet"])
    report = worksheet.merge_document(translated, pages=[page_id])
    assert report["stale_worksheets"] == [page_id]
    assert ir.load_doc(translated)["stages"]["worksheet"] == prior


@pytest.mark.parametrize("header", ["scheme", "all"])
def test_removing_headers_does_not_authorize_old_geometry(translated, header):
    page_id, region_id, path = _reply(translated)
    pattern = r"^# scheme:.*\n" if header == "scheme" else r"^# (?:scheme|fingerprint):.*\n"
    ir.write_text(path, re.sub(pattern, "", ir.read_text(path), flags=re.M))
    doc = ir.load_doc(translated)
    ir.find_region(doc, region_id)["bbox"][0] += 1
    ir.save_doc(doc, translated)
    before = translated.read_bytes()
    report = worksheet.merge_document(translated, pages=[page_id])
    assert report["stale_worksheets"] == [page_id], report
    assert translated.read_bytes() == before
