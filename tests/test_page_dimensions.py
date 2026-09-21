"""A PDF's paper size and its scan resolution are independent contracts."""

import io

import pytest
from PIL import Image, ImageDraw

import export
import pageir as ir
import qa
import readers


def test_pdf_roundtrip_preserves_paper_and_pixels(tmp_path):
    import pymupdf

    image = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 180, 55), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    source = tmp_path / "source.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        page.insert_image(page.rect, stream=buffer.getvalue())
        pdf.save(source)
    readers.import_source(source, tmp_path / "work")
    doc_path = tmp_path / "work" / "comic.json"
    doc = ir.load_doc(doc_path)
    assert (doc["pages"][0]["width"], doc["pages"][0]["height"]) == (400, 600)
    delivered = tmp_path / "delivered.pdf"
    export.export_document(doc_path, delivered, draft=True)
    with pymupdf.open(delivered) as pdf:
        page = pdf[0]
        assert (page.rect.width, page.rect.height) == pytest.approx((200, 300))
        assert page.get_images()[0][2:4] == (400, 600)
    row = ir.load_doc(doc_path)["stages"]["export"]["manifest"][0]
    assert row["visible"]["size"] == [400, 600]
    assert qa.check_package(delivered, doc_path)["ok"]
    with pymupdf.open(delivered) as pdf:
        pdf[0].draw_rect(pymupdf.Rect(15, 20, 90, 28), fill=(1, 1, 1), color=None)
        pdf.saveIncr()
    report = qa.check_package(delivered, doc_path)
    assert not report["ok"]
    assert any(f["code"] == "archive-invalid" for f in report["findings"])


@pytest.mark.parametrize("case", ["rotate", "crop", "undersampled-proof"])
def test_pdf_native_sampling_is_preserved_and_required(tmp_path, case):
    import pymupdf
    import pdfpage

    image = Image.new("RGB", (1200, 1800), "white")
    ImageDraw.Draw(image).rectangle((80, 80, 200, 96), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    source = tmp_path / "source.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=144, height=216)
        page.insert_image(page.rect, stream=buffer.getvalue())
        if case == "rotate":
            page.set_rotation(90)
        elif case == "crop":
            page.set_cropbox(pymupdf.Rect(0, 0, 144, 108))
        pdf.save(source)
    readers.import_source(source, tmp_path / "work")
    doc_path = tmp_path / "work" / "comic.json"
    doc = ir.load_doc(doc_path)
    expected = {"rotate": (1800, 1200), "crop": (1200, 900),
                "undersampled-proof": (1200, 1800)}[case]
    assert (doc["pages"][0]["width"], doc["pages"][0]["height"]) == expected
    output = tmp_path / "output.pdf"
    export.export_document(doc_path, output, draft=True)
    assert qa.check_package(output, doc_path)["ok"]
    if case != "undersampled-proof":
        with pymupdf.open(output) as pdf:
            assert pdf[0].get_images()[0][2:4] == expected
        return
    with pymupdf.open(output) as pdf:
        reference = pdfpage.visible_proof(pdf[0], scale=(1 / 144, 1 / 216))
        assert reference["size"] == [1, 1]
        pdf.set_metadata({"title": "Unchanged pixels, insufficient proof"})
        pdf.saveIncr()
    doc = ir.load_doc(doc_path)
    stamp = doc["stages"]["export"]
    stamp["manifest"][0]["visible"] = reference
    for edition in stamp["editions"].values():
        edition["manifest"][0]["visible"] = reference
    ir.save_doc(doc, doc_path)
    report = qa.check_package(output, doc_path)
    assert not report["ok"], report
    assert any(f["code"] == "archive-unverified" and "native" in f["detail"]
               for f in report["findings"]), report
