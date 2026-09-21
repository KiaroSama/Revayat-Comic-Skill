"""None means all pages; empty means no work; unknown names fail before IO."""

import pytest

import clean
import crops
import detect
import masks
import pageir as ir
import typeset
import worksheet


STAGES = [clean.clean_document, crops.build_document, detect.detect_document,
          masks.build_document, typeset.typeset_document, worksheet.build_document,
          worksheet.merge_document]


@pytest.mark.parametrize("stage", STAGES, ids=lambda stage: stage.__module__)
def test_empty_selection_never_mutates_the_document(finished, stage):
    worksheet.build_document(finished)
    for page in ir.load_doc(finished)["pages"]:
        path = finished.parent / "worksheets" / (page["id"] + ".txt")
        ir.write_text(path.with_name(page["id"] + ".done.txt"), ir.read_text(path))
    before = finished.read_bytes()
    report = stage(finished, pages=[])
    if stage is clean.clean_document:
        assert report["pages"] == []
    assert finished.read_bytes() == before


@pytest.mark.parametrize("stage", STAGES, ids=lambda stage: stage.__module__)
def test_unknown_selection_fails_before_any_mutation(finished, stage):
    before = finished.read_bytes()
    with pytest.raises(ValueError, match="page"):
        stage(finished, pages=["p0001", "not-a-page"])
    assert finished.read_bytes() == before


def test_public_clean_restores_a_page_after_its_last_region_is_removed(finished):
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    page["regions"] = []
    page_id, original = page["id"], ir.sha256_file(finished.parent / page["image"])
    ir.save_doc(doc, finished)
    for _ in range(2):
        clean.clean_document(finished, pages=[page_id])
        page = ir.load_doc(finished)["pages"][0]
        assert not page.get("clean") and not page.get("final")
        assert ir.sha256_file(finished.parent / page["image"]) == original


@pytest.mark.parametrize("name,action", [("clean", []), ("mask", []), ("worksheet", ["merge"])])
def test_explicit_empty_cli_selection_is_empty_through_the_transport(finished, name, action):
    import server

    before = finished.read_bytes()
    report = server.run(name, [*action, "--doc", str(finished), "--pages", ""])
    assert report["ok"], report
    assert finished.read_bytes() == before
