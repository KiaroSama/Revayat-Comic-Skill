"""A PDF's recorded page evidence must be complete before it can certify bytes."""

import copy
import shutil

import pytest
from PIL import Image

import export
import package
import pageir as ir
import readers


@pytest.fixture
def pdf_edition(tmp_path):
    source = tmp_path / "inputs"
    source.mkdir()
    for index, color in enumerate(("white", "black"), 1):
        Image.new("RGB", (40, 60), color).save(source / f"{index}.png")
    report = readers.import_source(source, tmp_path / "work")
    document = tmp_path / "work" / "comic.json"
    destination = tmp_path / "edition.pdf"
    export.export_document(report["document"], destination, draft=True)
    return document, destination


@pytest.mark.parametrize("tampered", [False, True])
@pytest.mark.parametrize("damage", [
    "missing", "empty", "short", "extra", "duplicate-name", "row",
    "wrong-page", "dimensions", "points", "points-overflow", "width-overflow",
])
def test_incomplete_pdf_evidence_never_certifies_a_package(pdf_edition, damage, tampered):
    pymupdf = pytest.importorskip("pymupdf")
    document, destination = pdf_edition
    doc = ir.load_doc(document)
    selected = doc["stages"]["export"]["editions"][str(destination.resolve())]
    rows = selected["manifest"]
    if damage == "missing":
        selected.pop("manifest")
    elif damage == "empty":
        selected["manifest"] = []
    elif damage == "short":
        selected["manifest"] = rows[:1]
    elif damage == "extra":
        selected["manifest"] = rows + copy.deepcopy(rows[:1])
    elif damage == "duplicate-name":
        rows[1]["name"] = rows[0]["name"]
    elif damage == "row":
        rows[0] = None
    elif damage == "wrong-page":
        rows[0]["page"] = rows[1]["page"]
    elif damage == "dimensions":
        rows[0]["width"] = "40"
    elif damage == "points-overflow":
        rows[0]["pdf_points"] = [10**400, 60]
    elif damage == "width-overflow":
        rows[0].pop("pdf_points", None)
        rows[0]["width"] = 10**400
    else:
        rows[0]["pdf_points"] = [0, 60]
    ir.save_doc(doc, document)
    if tampered:
        with pymupdf.open(destination) as pdf:
            pdf[0].draw_rect(pdf[0].rect, fill=(1, 0, 0), color=None)
            pdf.saveIncr()

    before = document.read_bytes()
    report = package.check_package(destination, document)
    assert not report["ok"], report
    assert any(item["code"] == "archive-unverified" for item in report["findings"]), report
    assert document.read_bytes() == before


@pytest.mark.parametrize("proof", ["container", "visible", "pixels"])
def test_complete_pdf_evidence_keeps_supported_proof_paths(pdf_edition, tmp_path, proof):
    document, destination = pdf_edition
    doc = ir.load_doc(document)
    selected = doc["stages"]["export"]["editions"][str(destination.resolve())]
    if proof != "container":
        selected.pop("package_sha256")
    for row in selected["manifest"]:
        if proof == "visible":
            row.pop("pixels")
        elif proof == "pixels":
            row.pop("visible")
            row.pop("pdf_points")
    ir.save_doc(doc, document)
    copied = tmp_path / "copied.pdf"
    shutil.copyfile(destination, copied)
    assert package.check_package(destination, document)["ok"]
    assert package.check_package(copied, document)["ok"]


def test_legacy_pdf_with_no_page_evidence_is_unverified(pdf_edition):
    document, destination = pdf_edition
    doc = ir.load_doc(document)
    stamp = doc["stages"]["export"]
    stamp.pop("editions")
    stamp.pop("manifest")
    ir.save_doc(doc, document)
    report = package.check_package(destination, document)
    assert not report["ok"]
    assert any(item["code"] == "archive-unverified" for item in report["findings"])


def test_missing_row_points_cannot_hide_changed_known_paper_size(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    image = tmp_path / "page.png"
    Image.new("RGB", (120, 160), (30, 60, 90)).save(image)
    source = tmp_path / "source.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=60, height=80)
        page.insert_image(page.rect, filename=str(image))
        pdf.save(source)
    readers.import_source(source, tmp_path / "work")
    document = tmp_path / "work" / "comic.json"
    destination = tmp_path / "edition.pdf"
    export.export_document(document, destination, draft=True)
    doc = ir.load_doc(document)
    selected = doc["stages"]["export"]["editions"][str(destination.resolve())]
    selected.pop("package_sha256")
    selected["manifest"][0].pop("visible")
    selected["manifest"][0].pop("pdf_points")
    ir.save_doc(doc, document)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=120, height=160)
        page.insert_image(page.rect, filename=str(image))
        pdf.save(destination)
    report = package.check_package(destination, document)
    assert not report["ok"], report
    assert any(item["code"] == "archive-page-size" for item in report["findings"])
