"""Does this package hold the chapter the document describes?

Counting pages proves a package has the right number of sheets. Every test here
substitutes something that keeps the count, the names and the shape and changes
what the reader would actually see — which is the whole class of failure a
completeness check passes.
"""
from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

import export
import package as package_check
import pageir as ir
import qa


def _same_shape_image(width, height, colour=(255, 0, 0), fmt="PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, fmt)
    return buffer.getvalue()


def _page_shape(doc_path, index=0):
    page = ir.load_doc(doc_path)["pages"][index]
    return page["width"], page["height"]


# --------------------------------------------------------------------------- #
# The controls: a real export verifies
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,quality", [
    ("chapter.cbz", 0), ("chapter.cbz", 80), ("edition", 0), ("book.pdf", 0),
])
def test_a_real_export_verifies(finished, tmp_path, name, quality):
    out = tmp_path / name
    export.export_document(finished, out, quality=quality)

    report = qa.check_package(out, finished)

    assert report["ok"], report["findings"]


# --------------------------------------------------------------------------- #
# Substitution
# --------------------------------------------------------------------------- #

def test_a_same_size_page_swapped_into_an_archive_is_caught(finished, tmp_path):
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    width, height = _page_shape(finished)

    with zipfile.ZipFile(out) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    first = sorted(n for n in members if n.lower().endswith(".png"))[0]
    members[first] = _same_shape_image(width, height)
    with zipfile.ZipFile(out, "w") as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("not the bytes that were exported" in item["detail"]
               for item in report["findings"]), report["findings"]


def test_a_jpeg_page_is_verified_too(finished, tmp_path):
    """A control, and it passed before this repair — by accident. The hash was
    gated behind `lossy` and the flag was inverted, so a JPEG was recorded as
    lossless and therefore checked. Both halves are corrected here: the flag is
    truthful now AND the gate is gone, so this keeps passing for the right
    reason. The bypass it did not cover is the next test."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out, quality=80)
    manifest = ir.load_doc(finished)["stages"]["export"]["manifest"]
    assert any(row["name"].lower().endswith((".jpg", ".jpeg"))
               for row in manifest), manifest
    assert all(row["lossy"] for row in manifest
               if row["name"].lower().endswith((".jpg", ".jpeg")))

    width, height = _page_shape(finished)
    with zipfile.ZipFile(out) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    first = sorted(members)[0]
    members[first] = _same_shape_image(width, height, fmt="JPEG")
    with zipfile.ZipFile(out, "w") as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)

    assert not qa.check_package(out, finished)["ok"]


def test_a_lossy_manifest_row_is_still_hashed(finished, tmp_path):
    """THE bypass. `lossy` was read as "these bytes cannot be compared", so a
    row carrying it skipped the hash entirely — and `sha256` is the hash of the
    bytes the export WROTE, which is always comparable."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    doc = ir.load_doc(finished)
    for row in doc["stages"]["export"]["manifest"]:
        row["lossy"] = True
    ir.save_doc(doc, finished)
    width, height = _page_shape(finished)

    with zipfile.ZipFile(out) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    first = sorted(n for n in members if n.lower().endswith(".png"))[0]
    members[first] = _same_shape_image(width, height)
    with zipfile.ZipFile(out, "w") as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)

    assert not qa.check_package(out, finished)["ok"]


def test_a_pdf_replaced_by_an_unrelated_image_is_caught(finished, tmp_path):
    """The check asked whether each sheet's resource dictionary mentioned an
    image. A picture of the same shape satisfied it."""
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    export.export_document(finished, out)
    width, height = _page_shape(finished)

    forged = pymupdf.open()
    for page in ir.load_doc(finished)["pages"]:
        sheet = forged.new_page(width=page["width"], height=page["height"])
        sheet.insert_image(pymupdf.Rect(0, 0, page["width"], page["height"]),
                           stream=_same_shape_image(width, height))
    forged.save(str(out))
    forged.close()

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("does not show the page this export wrote" in item["detail"]
               for item in report["findings"]), report["findings"]


def test_an_off_page_image_does_not_count_as_the_page(finished, tmp_path):
    """An XObject placed outside the sheet is on the page as far as a resource
    listing is concerned, and invisible to a reader."""
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    doc = ir.load_doc(finished)
    export.export_document(finished, out)

    forged = pymupdf.open()
    for page in doc["pages"]:
        sheet = forged.new_page(width=page["width"], height=page["height"])
        # Drawn entirely past the right-hand edge.
        sheet.insert_image(
            pymupdf.Rect(page["width"] + 10, 0,
                         page["width"] + 60, 50),
            stream=_same_shape_image(50, 50))
    forged.save(str(out))
    forged.close()

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("shows no image covering the sheet" in item["detail"]
               for item in report["findings"]), report["findings"]


# --------------------------------------------------------------------------- #
# Bounded decoding
# --------------------------------------------------------------------------- #

def test_a_page_over_the_decode_limit_is_refused_not_passed(monkeypatch):
    """A resource limit turned into a successful verification: the size was
    returned, the decode was skipped, and nothing looked at the difference."""
    monkeypatch.setattr(package_check, "MAX_DECODE_PIXELS", 16)

    size, problem = package_check._page_size(_same_shape_image(40, 40))

    assert size == (40, 40)
    assert "cannot be verified" in problem


def test_a_corrupt_page_is_refused():
    size, problem = package_check._page_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)

    assert size is None and "not an image" in problem


def test_a_bomb_inside_an_archive_fails_the_package(finished, tmp_path,
                                                    monkeypatch):
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    monkeypatch.setattr(package_check, "MAX_DECODE_PIXELS", 16)

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("cannot be verified" in item["detail"]
               for item in report["findings"])


# --------------------------------------------------------------------------- #
# DRAFT, in the package
# --------------------------------------------------------------------------- #

def test_a_draft_pdf_says_so_inside_itself(translated, tmp_path):
    """A PDF is the format people forward, and a draft one was
    indistinguishable from an approved edition once the report scrolled away."""
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"

    export.export_document(translated, out, draft=True)

    with pymupdf.open(str(out)) as document:
        metadata = document.metadata
    assert "DRAFT" in (metadata.get("title") or "")
    assert "draft" in (metadata.get("keywords") or "").lower()


def test_an_approved_pdf_does_not_say_draft(finished, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"

    export.export_document(finished, out)

    with pymupdf.open(str(out)) as document:
        metadata = document.metadata
    assert "DRAFT" not in (metadata.get("title") or "")


def test_a_package_without_a_manifest_is_unverified_not_wrong(finished,
                                                              tmp_path):
    """Handled as legacy: an older package is not evidence of anything wrong,
    and re-exporting is the supported route back to a verified one."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    doc = ir.load_doc(finished)
    doc["stages"]["export"].pop("manifest", None)
    ir.save_doc(doc, finished)

    assert qa.check_package(out, finished)["ok"]
