"""Revision identity is field structure, never an ambiguous joined string."""
from __future__ import annotations

import copy
import hashlib

import pytest

import export
import falint
import pageir as ir
import qa
import stages
import typeset


def chapter():
    doc = ir.new_doc()
    for i in range(2):
        page = ir.new_page(f"p{i+1:04d}", i, "page.png", 200, 200, str(i) * 64)
        region = ir.new_region(f"{page['id']}r001", [0, 0, 100, 100], kind="speech")
        region.update(target_text="سلام|دنیا", target_full="دوست", source_text="Hello")
        page["regions"] = [region]
        doc["pages"].append(page)
    return doc


def test_display_full_delimiter_shift_invalidates_only_affected_page():
    doc = chapter()
    for stage in ("detect", "masks", "clean", "typeset", "export"):
        stages.stamp_stage(doc, stage, {})
    doc["pages"][0]["regions"][0].update(target_text="سلام", target_full="دنیا|دوست")
    assert stages.stale_pages(doc, "typeset") == ["p0001"]
    assert stages.stale_pages(doc, "export") == ["p0001"]
    for unchanged in ("detect", "masks", "clean"):
        assert not stages.stale_pages(doc, unchanged)
    stages.stamp_stage(doc, "typeset", {}, pages=["p0001"])
    stages.stamp_stage(doc, "export", {}, pages=["p0001"])
    before = copy.deepcopy(doc)
    stages.stamp_stage(doc, "typeset", {}, pages=["p0001"])
    stages.stamp_stage(doc, "export", {}, pages=["p0001"])
    assert doc == before and not stages.stale_stages(doc)


def test_source_text_cannot_shift_through_another_region_id():
    doc = chapter()
    page = doc["pages"][0]
    first = page["regions"][0]
    second = ir.new_region("p0001r002", [0, 110, 100, 50], kind="speech")
    page["regions"].append(second)
    first["source_text"], second["source_text"] = "a|p0001r002|b", "c"
    previous = stages.facet_revision(page, "source")
    first["source_text"], second["source_text"] = "a", "b|p0001r002|c"
    assert stages.facet_revision(page, "source") != previous


def legacy_facet(page, name, original):
    if name not in {"source", "text"}:
        return original(page, name)
    digest = hashlib.sha256()
    digest.update(f"{page['id']}|{page['sha256']}|{page.get('width')}x{page.get('height')}|".encode())
    for r in page["regions"]:
        fields = ([r["id"], r.get("source_text") or ""] if name == "source" else
                  [r["id"], r.get("target_text") or "", r.get("target_full") or "",
                   str(bool(r.get("dropped"))), str(bool(r.get("keep"))), str(bool(r.get("erase"))),
                   str(r.get("fill") or "none")])
        digest.update(("|".join(fields) + "|").encode())
    return digest.hexdigest()


def test_old_comparable_records_require_one_refresh_not_an_unverified_exemption(monkeypatch):
    doc = chapter()
    original = stages._page_facet
    with monkeypatch.context() as old:
        old.setattr(stages, "_page_facet", lambda p, n: legacy_facet(p, n, original))
        for stage in ("detect", "masks", "clean", "typeset", "export"):
            stages.stamp_stage(doc, stage, {})
    assert stages.stale_pages(doc, "typeset") == ["p0001", "p0002"]
    assert "typeset" not in stages.unverified_stages(doc)
    for stage in ("detect", "masks", "clean"):
        assert not stages.stale_pages(doc, stage)
    stages.stamp_stage(doc, "typeset", {}, pages=["p0001"])
    assert stages.stale_pages(doc, "typeset") == ["p0002"]
    stages.stamp_stage(doc, "typeset", {}, pages=["p0002"])
    assert not stages.stale_pages(doc, "typeset")


def test_real_render_cannot_ship_after_delimiter_shift(finished, tmp_path):
    doc = ir.load_doc(finished)
    page = next(p for p in doc["pages"] if p.get("final"))
    region = next(r for r in page["regions"] if r.get("target_text"))
    region.update(target_text="سلام|دنیا", target_full="دوست")
    falint.record_acknowledgement(region, ["compressed-variant"], region["target_text"])
    ir.save_doc(doc, finished)
    typeset.typeset_document(finished)
    assert qa.publication_preflight(finished)["ok"]
    doc = ir.load_doc(finished)
    page = ir.find_page(doc, page["id"])
    region = ir.find_region(doc, region["id"])
    rendered_before = ir.sha256_file(ir.doc_dir(finished) / page["final"])
    region.update(target_text="سلام", target_full="دنیا|دوست")
    # A deliberate new semantic approval cannot certify stale rendered bytes.
    falint.record_acknowledgement(region, ["compressed-variant"], region["target_text"])
    ir.save_doc(doc, finished)
    assert not qa.publication_preflight(finished)["ok"]
    with pytest.raises(ValueError, match="publication QA"):
        export.export_document(finished, tmp_path / "stale.cbz")
    for _ in range(2):
        typeset.typeset_document(finished)
        assert qa.publication_preflight(finished)["ok"]
    updated = ir.load_doc(finished)
    assert ir.sha256_file(ir.doc_dir(finished) / ir.find_page(updated, page["id"])["final"]) != rendered_before
    assert export.export_document(finished, tmp_path / "fresh.cbz")["pages"]
