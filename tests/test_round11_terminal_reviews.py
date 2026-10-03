"""Archived full wording is not a shortened active translation."""
from __future__ import annotations

import pytest

import clean
import falint
import masks
import pageir as ir
import qa
import typeset
import worksheet


def _terminal(path, action):
    doc = ir.load_doc(path)
    region = next(r for _, r in ir.iter_regions(doc) if r.get("target_text"))
    region.update(target_full="سلام دوست من", target_text="سلام")
    falint.record_acknowledgement(region, ["compressed-variant"], "سلام")
    region_id = region["id"]
    ir.save_doc(doc, path)
    worksheet.build_document(path)
    page_id = region_id[:5]
    folder = path.parent / "worksheets"
    body = ir.read_text(folder / (page_id + ".txt"))
    marker = "@@ " + region_id
    start = body.index(marker)
    end = body.find("\n@@ ", start + len(marker))
    if end == -1:
        end = len(body)
    body = body[:end] + "\n" + action + ": yes\n" + body[end:]
    ir.write_text(folder / (page_id + ".done.txt"), body)
    assert worksheet.merge_document(path, pages=[page_id])["ok"]
    return region_id


@pytest.mark.parametrize("action", ["keep", "drop", "erase"])
def test_kept_history_survives_real_pipeline_without_compression_demand(translated, action):
    region_id = _terminal(translated, action)
    for _ in range(2):
        masks.build_document(translated)
        clean.clean_document(translated)
        typeset.typeset_document(translated)
        report = qa.check_document(translated, strict=True, limit=None)
        assert not any(f["code"] == "compressed-variant" and f["where"] == region_id
                       for f in report["findings"])
    region = ir.find_region(ir.load_doc(translated), region_id)
    assert region["target_full"] == "سلام دوست من" and not region["target_text"]


@pytest.mark.parametrize("action", ["keep", "drop", "erase"])
def test_terminal_decisions_preserve_wording_and_review_history(translated, action):
    region_id = _terminal(translated, action)
    r = ir.find_region(ir.load_doc(translated), region_id)
    assert r["target_full"] == "سلام دوست من" and not r["target_text"]
    assert not falint.compression_review_needed(r)
    r.update(keep=False, dropped=False, erase=False, target_text="درود", source_text="Changed")
    assert falint.compression_review_needed(r)
    assert r.get("review_ack") or r.get("review_ack_history")


@pytest.mark.parametrize("policy,needed", [("keep", False), ("translate", True),
                                            ("bilingual", True), ("annotate", True)])
def test_translated_sfx_pairs_still_need_review(policy, needed):
    r = ir.new_region("p0001r001", [0, 0, 20, 20], kind="sfx")
    r.update(target_full="صدای انفجار بزرگ", target_text="بوم")
    assert falint.compression_review_needed(r, policy) is needed
    falint.record_acknowledgement(r, ["compressed-variant"], "بوم")
    assert not falint.compression_review_needed(r, policy)
    r["target_text"] = "بنگ"
    assert falint.compression_review_needed(r, policy) is needed


def test_missing_active_text_keeps_real_qa_error(translated):
    doc = ir.load_doc(translated)
    r = next(r for _, r in ir.iter_regions(doc) if r.get("target_text") and r["kind"] == "speech")
    r.update(target_text="", target_full="سلام دوست من")
    ir.save_doc(doc, translated)
    report = qa.check_document(translated, strict=True, limit=None)
    assert any(f["code"] == "untranslated-region" and f["where"] == r["id"] for f in report["findings"])
    assert not any(f["code"] == "compressed-variant" and f["where"] == r["id"] for f in report["findings"])
