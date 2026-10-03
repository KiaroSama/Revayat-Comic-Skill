"""Terminology edits are constraints, not movement of accepted regions."""
from __future__ import annotations

import copy

import pytest
from PIL import Image

import context
import glossary
import pageir as ir
import providers
import translate
import worksheet


@pytest.fixture
def merged_first(tmp_path):
    doc = ir.new_doc(source_language="en")
    for number in (1, 2):
        name = f"p{number:04d}"
        image = tmp_path / (name + ".png")
        Image.new("RGB", (120, 80), "white").save(image)
        page = ir.new_page(name, number - 1, image.name, 120, 80, ir.sha256_file(image))
        r = ir.new_region(name + "r001", [10, 10, 80, 40], kind="speech")
        r.update(source_text="Hello", reading_order=1)
        page["regions"] = [r]
        doc["pages"].append(page)
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    worksheet.build_document(path)
    folder = tmp_path / "worksheets"
    text = ir.read_text(folder / "p0001.txt").replace("fa: ", "fa: سلام")
    ir.write_text(folder / "p0001.done.txt", text)
    assert worksheet.merge_document(path, pages=["p0001"])["ok"]
    return path


def test_normal_glossary_progress_and_translation_resume(merged_first, monkeypatch):
    path = merged_first
    doc = ir.load_doc(path)
    glossary.set_entry(doc, "Hello", {"target": "سلام", "locked": True})
    ir.save_doc(doc, path)
    assert context.preflight(path, ir.load_doc(path), "p0002")["ok"]
    calls = []

    class Counting:
        def translate(self, text, package):
            calls.append(package)
            return "سلام"

    monkeypatch.setitem(providers._REGISTRY["translation"], "r11-count", Counting)
    for _ in range(2):
        result = translate.translate_document(path, provider="r11-count", pages=["p0002"])
        assert not result["refused"]
    assert len(calls) == 1 and calls[0]["constraints"]["glossary"]["Hello"] == "سلام"
    assert ir.load_doc(path)["pages"][0]["regions"][0]["target_text"] == "سلام"


@pytest.mark.parametrize("change", ["scan", "suggested", "locked", "title", "language"])
def test_constraint_changes_do_not_move_accepted_page(merged_first, change):
    path = merged_first
    if change == "scan":
        glossary.scan(path)
    else:
        doc = ir.load_doc(path)
        if change in {"suggested", "locked"}:
            glossary.set_entry(doc, "Hello", {"target": "سلام", "locked": change == "locked"})
        elif change == "title":
            doc["meta"]["title_policy"] = {"honorifics": "keep"}
        else:
            doc["meta"]["source_language"] = "ja"
        ir.save_doc(doc, path)
    assert context.preflight(path, ir.load_doc(path), "p0002")["moved"] == []


@pytest.mark.parametrize("field,value", [("bbox", [11, 10, 80, 40]), ("kind", "narration"),
                                          ("orientation", "vertical"), ("sha256", "0" * 64)])
@pytest.mark.parametrize("override", [False, True])
def test_actual_page_identity_changes_always_block(merged_first, field, value, override):
    doc = ir.load_doc(merged_first)
    if field == "sha256":
        doc["pages"][0][field] = value
    else:
        doc["pages"][0]["regions"][0][field] = value
    state = context.preflight(merged_first, doc, "p0002", allow_unmerged=override)
    assert not state["ok"] and state["moved"] == ["p0001"]


@pytest.mark.parametrize("receipt", [None, [], {}, {"after": "bad"}, {"after": "f" * 16, "digest": "bad"}])
def test_missing_or_malformed_receipt_keeps_conservative_guard(merged_first, receipt):
    doc = ir.load_doc(merged_first)
    doc["pages"][0]["worksheet_receipt"] = copy.deepcopy(receipt)
    glossary.set_entry(doc, "Hello", {"target": "سلام", "locked": True})
    assert not context.preflight(merged_first, doc, "p0002")["ok"]


def test_edited_reply_is_still_unmerged(merged_first):
    reply = merged_first.parent / "worksheets" / "p0001.done.txt"
    ir.write_text(reply, ir.read_text(reply).replace("fa: سلام", "fa: درود"))
    state = context.preflight(merged_first, ir.load_doc(merged_first), "p0002")
    assert not state["ok"] and state["unmerged"] == ["p0001"]


def test_equally_malformed_digests_do_not_exempt_geometry(merged_first):
    doc = ir.load_doc(merged_first)
    page = doc['pages'][0]
    page['worksheet_digest'] = page['worksheet_receipt']['digest'] = 'bad'
    glossary.set_entry(doc, 'Hello', {'target': 'سلام', 'locked': True})
    assert context.preflight(merged_first, doc, 'p0002')['moved'] == ['p0001']
