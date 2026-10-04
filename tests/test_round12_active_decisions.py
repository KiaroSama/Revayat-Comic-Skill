"""Current decisions outrank retained drafts throughout the real pipeline."""
from __future__ import annotations

import copy
import io
import zipfile

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw

import clean
import context
import export
import falint
import glossary
import masks
import package
import pageir as ir
import qa
import typeset


@pytest.fixture
def draft_page(tmp_path):
    image = Image.new("RGB", (300, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((30, 20, 270, 160), outline="black", width=3)
    for x in range(105, 185, 18):
        draw.rectangle((x, 75, x + 8, 90), fill="black")
    image.save(tmp_path / "page.png")
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, "page.png", 300, 180,
                       ir.sha256_file(tmp_path / "page.png"))
    region = ir.new_region("p0001r001", [95, 65, 110, 40], kind="speech",
                           confidence=1.0)
    region.update(balloon=[30, 20, 240, 140], reading_order=1, locked=True,
                  source_text="Hello", target_text="سلام", target_full="سلام")
    page["regions"] = [region]
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    return path


def _decide(path, action):
    doc = ir.load_doc(path)
    region = doc["pages"][0]["regions"][0]
    region.update(keep=action == "keep", dropped=action == "drop",
                  erase=action == "erase")
    if action == "policy-keep":
        region["kind"] = "sfx"
        doc["meta"]["sfx_policy"] = "keep"
    ir.save_doc(doc, path)
    return copy.deepcopy(region)


def _pixels(path):
    return np.asarray(ir.load_image(path)).copy()


@pytest.mark.parametrize("action", ["erase", "keep", "drop", "policy-keep"])
@pytest.mark.parametrize("fallback", [False, True])
def test_retained_decisions_do_not_redraw_history(draft_page, action, fallback):
    saved = _decide(draft_page, action)
    masks.build_document(draft_page)
    clean.clean_document(draft_page)
    doc = ir.load_doc(draft_page)
    page = doc["pages"][0]
    cleaned = _pixels(draft_page.parent / page["clean"])
    assert np.array_equal(cleaned, _pixels(draft_page.parent / page["image"])) is (action != "erase")
    for _ in range(2):
        report = typeset.typeset_document(draft_page, force_fallback=fallback)
        assert report["placed"] == 0
        page = ir.load_doc(draft_page)["pages"][0]
        assert np.array_equal(_pixels(draft_page.parent / page["final"]), cleaned)
        assert np.array_equal(masks.load_mask(draft_page.parent / page["writable"]),
                              masks.load_mask(draft_page.parent / page["mask"]))
        region = page["regions"][0]
        assert (region["target_text"], region["target_full"]) == (
            saved["target_text"], saved["target_full"])
        assert ir.sha256_file(draft_page.parent / page["image"]) == page["sha256"]


def test_kept_target_exports_without_fake_render(draft_page):
    saved = _decide(draft_page, "keep")
    output = draft_page.parent / "edition.cbz"
    for _ in range(2):
        report = export.export_document(draft_page, output)
        assert report["approved"] and not report["draft"]
        assert report["sources"] == {"p0001": "image"}
        assert report["typeset_pages"] == 0
        assert package.check_package(output, draft_page)["ok"]
        assert ir.load_doc(draft_page)["pages"][0]["regions"][0] == saved


def test_inactive_draft_is_not_current_text_or_memory(draft_page):
    doc = ir.load_doc(draft_page)
    doc["pages"][0]["regions"][0].update(source_text="Kenji", target_text="كيسه ي", target_full="كيسه ي")
    second = ir.new_page("p0002", 1, "page.png", 300, 180, doc["pages"][0]["sha256"])
    doc["pages"].append(second)
    doc["glossary"] = {"entries": {"Kenji": {"target": "کنجی", "locked": True}}}
    ir.save_doc(doc, draft_page)
    saved = _decide(draft_page, "keep")
    for _ in range(2):
        assert falint.fix_document(draft_page)["changed_count"] == 0
        assert not falint.lint_document(draft_page)["findings"]
        assert glossary.check(draft_page)["ok"]
        current = ir.load_doc(draft_page)
        assert current["pages"][0]["regions"][0] == saved
        assert not context.build(current, "p0002")["context"]["translation_memory"]


@pytest.mark.parametrize("action", ["keep", "drop", "erase", "policy-keep"])
@pytest.mark.parametrize("fmt", ["cbz", "pdf", "dir"])
def test_inactive_editions_publish_selected_pixels_twice(draft_page, action, fmt):
    saved = _decide(draft_page, action)
    expected = "image"
    if action == "erase":
        masks.build_document(draft_page)
        clean.clean_document(draft_page)
        expected = "clean"
    page = ir.load_doc(draft_page)["pages"][0]
    expected_pixels = _pixels(draft_page.parent / page[expected])
    if action == "erase":
        assert not np.array_equal(expected_pixels, _pixels(draft_page.parent / page["image"]))
    output = draft_page.parent / ("edition" if fmt == "dir" else "edition." + fmt)
    for _ in range(2):
        report = export.export_document(draft_page, output, fmt=fmt)
        assert report["approved"] and report["sources"] == {"p0001": expected}
        assert report["typeset_pages"] == 0
        if fmt == "dir":
            shipped = _pixels(output / "0001.png")
        elif fmt == "cbz":
            with zipfile.ZipFile(output) as archive:
                with Image.open(io.BytesIO(archive.read("0001.png"))) as image:
                    shipped = np.asarray(image.convert("RGB")).copy()
        else:
            with pymupdf.open(output) as document:
                sheet = document[0]
                pixmap = sheet.get_pixmap(
                    matrix=pymupdf.Matrix(300 / sheet.rect.width, 180 / sheet.rect.height),
                    colorspace=pymupdf.csRGB, alpha=False)
                shipped = np.frombuffer(pixmap.samples, np.uint8).reshape(
                    pixmap.height, pixmap.width, 3)
        assert np.array_equal(shipped, expected_pixels)
        assert package.check_package(output, draft_page)["ok"]
        page = ir.load_doc(draft_page)["pages"][0]
        assert (page["regions"][0]["target_text"], page["regions"][0]["target_full"]) == (
            saved["target_text"], saved["target_full"])
        assert ir.sha256_file(draft_page.parent / page["image"]) == page["sha256"]


@pytest.mark.parametrize("policy", ["keep", "bilingual", "annotate"])
def test_nondrawing_effect_has_no_lettering_authority(draft_page, policy):
    doc = ir.load_doc(draft_page)
    doc["meta"]["sfx_policy"] = policy
    doc["pages"][0]["regions"][0]["kind"] = "sfx"
    ir.save_doc(doc, draft_page)
    masks.build_document(draft_page)
    clean.clean_document(draft_page)
    for _ in range(2):
        report = typeset.typeset_document(draft_page)
        assert report["placed"] == 0
        page = ir.load_doc(draft_page)["pages"][0]
        assert np.array_equal(_pixels(draft_page.parent / page["final"]),
                              _pixels(draft_page.parent / page["clean"]))
        assert np.array_equal(masks.load_mask(draft_page.parent / page["writable"]),
                              masks.load_mask(draft_page.parent / page["mask"]))
        codes = {f["code"] for f in qa.check_document(draft_page, strict=True, limit=None)["findings"]}
        assert ("annotation-unplaced" in codes) is (policy != "keep")


@pytest.mark.parametrize("action", ["keep", "drop", "erase", "policy-keep"])
def test_inactive_draft_reactivation_restores_current_checks(draft_page, action):
    doc = ir.load_doc(draft_page)
    r = doc["pages"][0]["regions"][0]
    r.update(source_text="Kenji", target_text="كيسه ي", target_full="كيسه ي")
    falint.record_acknowledgement(r, ["zwnj-review"], r["target_text"])
    doc["pages"].append(ir.new_page("p0002", 1, "page.png", 300, 180, doc["pages"][0]["sha256"]))
    doc["glossary"] = {"entries": {"Kenji": {"target": "کنجی", "locked": True}}}
    ir.save_doc(doc, draft_page)
    saved = _decide(draft_page, action)
    for _ in range(2):
        assert not falint.lint_document(draft_page)["findings"]
        assert glossary.check(draft_page)["ok"]
        assert falint.fix_document(draft_page)["changed_count"] == 0
        doc = ir.load_doc(draft_page)
        assert doc["pages"][0]["regions"][0] == saved
        assert not context.build(doc, "p0002")["context"]["translation_memory"]
    r = doc["pages"][0]["regions"][0]
    r.update(keep=False, dropped=False, erase=False)
    doc["meta"]["sfx_policy"] = "translate"
    ir.save_doc(doc, draft_page)
    assert falint.lint_document(draft_page)["findings"]
    assert not glossary.check(draft_page)["ok"]
    assert context.build(doc, "p0002")["context"]["translation_memory"][0]["fa"] == saved["target_text"]
    assert falint.fix_document(draft_page)["changed_count"] == 1


@pytest.mark.parametrize("policy", ["translate", "bilingual", "annotate"])
def test_active_effect_remains_subject_to_text_checks(draft_page, policy):
    doc = ir.load_doc(draft_page)
    doc["meta"]["sfx_policy"] = policy
    doc["pages"][0]["regions"][0].update(kind="sfx", source_text="Kenji", target_text="كيسه ي")
    doc["glossary"] = {"entries": {"Kenji": {"target": "کنجی", "locked": True}}}
    ir.save_doc(doc, draft_page)
    assert falint.lint_document(draft_page)["findings"]
    assert not glossary.check(draft_page)["ok"]
    assert falint.fix_document(draft_page)["changed_count"] == 1


def test_alias_rename_preserves_historical_impact_not_current_failure(draft_page):
    doc = ir.load_doc(draft_page)
    doc["pages"][0]["regions"][0].update(source_text="Kenny", target_text="کنجی", target_full="کنجی", keep=True)
    doc["glossary"] = {"entries": {"Kenji": {"target": "کنجی", "aliases": ["Kenny"], "locked": True}}}
    ir.save_doc(doc, draft_page)
    table = draft_page.parent / "names.json"
    ir.write_text(table, ir.dumps({"Kenji": {"target": "کنجى", "aliases": ["Kenny"], "locked": True}}))
    report = glossary.apply_file(draft_page, table)
    assert "p0001r001" in report["needs_review"]
    assert glossary.check(draft_page)["ok"]
    assert ir.load_doc(draft_page)["pages"][0]["regions"][0]["target_text"] == "کنجی"


@pytest.mark.parametrize("action,expected", [("keep", "kept_by_policy"), ("policy-keep", "kept_by_policy"), ("drop", "dropped_false_detection")])
def test_current_census_precedes_retained_overflow(draft_page, action, expected):
    _decide(draft_page, action)
    doc = ir.load_doc(draft_page)
    doc["pages"][0]["regions"][0]["typeset"] = {"status": "overflow"}
    ir.save_doc(doc, draft_page)
    assert qa.check_document(draft_page, strict=True)["stats"]["states"][expected] == 1


def test_missing_clean_artifact_still_blocks_publication(draft_page):
    _decide(draft_page, "erase")
    masks.build_document(draft_page)
    clean.clean_document(draft_page)
    page = ir.load_doc(draft_page)["pages"][0]
    (draft_page.parent / page["clean"]).unlink()
    with pytest.raises(ValueError, match="publication QA"):
        export.export_document(draft_page, draft_page.parent / "missing.cbz")
    assert any(f["code"] == "page-not-cleaned" for f in qa.check_document(draft_page)["findings"])


def test_active_translation_without_render_still_blocks(draft_page):
    with pytest.raises(ValueError, match="publication QA"):
        export.export_document(draft_page, draft_page.parent / "active.cbz")
    assert any(f["code"] == "page-not-rendered" for f in qa.check_document(draft_page)["findings"])


def test_policy_transition_requires_refresh_and_restores_same_translation(draft_page):
    doc = ir.load_doc(draft_page)
    doc["pages"][0]["regions"][0]["kind"] = "sfx"
    doc["meta"]["sfx_policy"] = "translate"
    ir.save_doc(doc, draft_page)
    output = draft_page.parent / "transition.cbz"
    for policy in ("translate", "keep", "translate", "keep"):
        doc = ir.load_doc(draft_page)
        old_policy = doc["meta"]["sfx_policy"]
        doc["meta"]["sfx_policy"] = policy
        ir.save_doc(doc, draft_page)
        if old_policy != policy:
            assert not qa.publication_preflight(draft_page)["ok"]
        masks.build_document(draft_page)
        clean.clean_document(draft_page)
        result = typeset.typeset_document(draft_page, stylise=False)
        assert result["placed"] == (1 if policy == "translate" else 0)
        assert export.export_document(draft_page, output)["approved"]
        assert package.check_package(output, draft_page)["ok"]
        assert ir.load_doc(draft_page)["pages"][0]["regions"][0]["target_text"] == "سلام"


@pytest.mark.parametrize("action", ["erase", "keep", "drop", "policy-keep"])
def test_inactive_retained_bad_text_does_not_fail_current_qa(draft_page, action):
    _decide(draft_page, action)
    doc = ir.load_doc(draft_page)
    doc["pages"][0]["regions"][0].update(target_text="これは古い", target_full="これは古い", typeset={"status": "overflow"})
    ir.save_doc(doc, draft_page)
    if action == "erase":
        masks.build_document(draft_page)
        clean.clean_document(draft_page)
    result = qa.check_document(draft_page, strict=True, limit=None)
    assert result["ok"], result["findings"]
    assert result["stats"]["translated"] == 0
    assert result["stats"]["typeset"] == 0


@pytest.mark.parametrize("policy", ["translate", "bilingual", "annotate"])
def test_active_sfx_requires_render_or_unplaced_gloss_gate(draft_page, policy):
    doc = ir.load_doc(draft_page)
    doc["meta"]["sfx_policy"] = policy
    doc["pages"][0]["regions"][0]["kind"] = "sfx"
    ir.save_doc(doc, draft_page)
    with pytest.raises(ValueError, match="publication QA"):
        export.export_document(draft_page, draft_page.parent / "effect.cbz")


@pytest.mark.parametrize("state", ["missing-text", "unfinished-erase"])
def test_real_missing_outcome_still_blocks(draft_page, state):
    doc = ir.load_doc(draft_page)
    r = doc["pages"][0]["regions"][0]
    if state == "missing-text":
        r["target_text"] = ""
        code = "untranslated-region"
    else:
        r["erase"] = True
        code = "erase-unfinished"
    ir.save_doc(doc, draft_page)
    assert any(f["code"] == code for f in qa.check_document(draft_page)["findings"])
    with pytest.raises(ValueError, match="publication QA"):
        export.export_document(draft_page, draft_page.parent / "unfinished.cbz")


@pytest.mark.parametrize("tamper", ["source", "render"])
def test_current_decisions_do_not_disable_pixel_certificates(draft_page, tamper):
    _decide(draft_page, "erase")
    masks.build_document(draft_page)
    clean.clean_document(draft_page)
    typeset.typeset_document(draft_page)
    page = ir.load_doc(draft_page)["pages"][0]
    target = draft_page.parent / page["image" if tamper == "source" else "final"]
    image = ir.load_image(target)
    image.putpixel((0, 0), (255, 0, 0))
    ir.save_image(image, target)
    result = qa.check_document(draft_page, strict=True, limit=None)
    assert not result["ok"]
    if tamper == "source":
        assert any(f["code"] == "source-modified" for f in result["findings"])
    else:
        assert any(f["code"] == "artwork-modified" for f in result["findings"])
