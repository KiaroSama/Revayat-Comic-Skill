"""Public package checks reject local text loss and unsafe ZIP declarations."""

import zipfile

import pytest

import export
import package
import pageir as ir
import qa


@pytest.mark.parametrize("change", ["rotation", "dialogue", "crop", "overlay", "substitute"])
@pytest.mark.parametrize("quality", [0, 85])
def test_native_pdf_delivered_bytes_are_binding(finished, tmp_path, change, quality):
    import pymupdf

    out = tmp_path / "delivered.pdf"
    export.export_document(finished, out, quality=quality)
    assert qa.check_package(out, finished)["ok"]
    with pymupdf.open(out) as pdf:
        page = pdf[0]
        if change == "rotation":
            page.set_rotation(180)
        elif change == "dialogue":
            region = next(r for r in ir.load_doc(finished)["pages"][0]["regions"]
                          if r.get("target_text") and not r.get("dropped"))
            page.draw_rect(pymupdf.Rect(region["bbox"]), fill=(1, 1, 1), color=None)
        elif change == "crop":
            rect = page.rect
            page.set_cropbox(pymupdf.Rect(0, 0, rect.width - 1, rect.height - 1))
        elif change == "overlay":
            page.draw_rect(page.rect, fill=(1, 1, 1), fill_opacity=0.2, color=None)
        else:
            page.draw_rect(page.rect, fill=(0, 0, 0), color=None)
        pdf.saveIncr()
    report = qa.check_package(out, finished)
    assert not report["ok"], report
    assert any(f["code"] == "archive-invalid" for f in report["findings"])
    assert qa.main(["package", "--doc", str(finished), "--file", str(out)]) != 0


@pytest.mark.parametrize("limit", ["member", "total", "count", "ratio", "duplicate", "directory"])
def test_zip_rejected_declarations_open_zero_members(imported, tmp_path, monkeypatch, limit):
    out = tmp_path / "limited.cbz"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data/" if limit == "directory" else "data.bin", b"x" * 16384)
        if limit == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("data.bin", b"y")
    setting = {"member": ("MAX_MEMBER_BYTES", 1024),
               "directory": ("MAX_MEMBER_BYTES", 1024),
               "total": ("MAX_TOTAL_BYTES", 1024),
               "count": ("MAX_MEMBERS", 0),
               "ratio": ("MAX_COMPRESSION_RATIO", 1)}
    if limit in setting:
        monkeypatch.setattr(package, *setting[limit])
    # Keep each declaration test independent of the highly compressible payload.
    if limit != "ratio":
        monkeypatch.setattr(package, "MAX_COMPRESSION_RATIO", 100000)
    opened = []
    original = zipfile.ZipFile.open

    def observe(self, name, *args, **kwargs):
        opened.append(name)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", observe)
    report = qa.check_package(out, imported)
    assert not report["ok"]
    assert opened == [], "rejected declarations were decompressed before the limit"


def test_a_coarse_reference_cannot_make_modified_pdf_verification_succeed(finished, tmp_path):
    import pymupdf

    out = tmp_path / "legacy.pdf"
    export.export_document(finished, out)
    doc = ir.load_doc(finished)
    edition = doc["stages"]["export"]["editions"][str(out.resolve())]
    edition.pop("package_sha256", None)
    for row in edition["manifest"]:
        row.pop("visible", None)
    ir.save_doc(doc, finished)
    with pymupdf.open(out) as pdf:
        pdf[0].draw_rect(pymupdf.Rect(20, 20, 24, 24), fill=(0, 0, 0), color=None)
        pdf.saveIncr()
    report = qa.check_package(out, finished)
    assert not report["ok"], report
