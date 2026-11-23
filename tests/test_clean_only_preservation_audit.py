"""An erasure that skips typesetting still owes the artwork preservation proof."""

import pytest
from PIL import Image, ImageDraw

import clean
import export
import masks
import pageir as ir
import qa
import readers


def _erasure(tmp_path):
    source = tmp_path / "source.png"
    image = Image.new("RGB", (160, 160), "white")
    ImageDraw.Draw(image).rectangle((60, 60, 80, 80), fill="black")
    image.save(source)
    report = readers.import_source(source, tmp_path / "work")
    document = tmp_path / "work" / "comic.json"
    doc = ir.load_doc(report["document"])
    region = ir.new_region("p0001r001", [50, 50, 40, 40], kind="unknown", confidence=1)
    region.update(erase=True, locked=True)
    doc["pages"][0]["regions"] = [region]
    ir.save_doc(doc, document)
    masks.build_document(document)
    return document


def test_cleaned_only_output_cannot_escape_its_signed_authority(tmp_path):
    document = _erasure(tmp_path)
    page = ir.load_doc(document)["pages"][0]
    # A tightened union or an interrupted mask rebuild can leave region masks
    # wider than page authority. Signing the next clean does not repair that.
    Image.new("L", (160, 160), 0).save(document.parent / page["mask"])
    clean.clean_document(document)
    page = ir.load_doc(document)["pages"][0]
    assert not page.get("final")
    changed, _, _ = qa.compare_outside_mask(
        document.parent / page["image"], document.parent / page["clean"],
        document.parent / page["mask"])
    assert changed == 441
    report = qa.check_document(document, limit=None)
    assert not report["ok"], report
    assert report["stats"]["artwork_pixels_changed"] == changed
    assert any(f["code"] == "artwork-modified" for f in report["findings"])
    with pytest.raises(ValueError, match="artwork-modified"):
        export.export_document(document, tmp_path / "edition.cbz")
    assert ir.sha256_file(document.parent / page["image"]) == page["sha256"]


def test_valid_erasure_only_output_still_publishes(tmp_path):
    document = _erasure(tmp_path)
    clean.clean_document(document)
    report = qa.check_document(document, limit=None)
    assert report["ok"], report
    assert report["stats"]["artwork_pixels_changed"] == 0
    exported = export.export_document(document, tmp_path / "edition.cbz")
    assert exported["approved"]
    assert exported["sources"] == {"p0001": "clean"}
