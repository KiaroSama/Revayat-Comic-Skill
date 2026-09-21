"""Destination planning protects external inputs and operator-owned entries."""

import pytest

import export
import readers
import worksheet


@pytest.mark.parametrize("fmt", ["cbz", "pdf", "dir"])
@pytest.mark.parametrize("kind", ["original", "worksheet"])
def test_explicit_formats_cannot_replace_external_inputs(tmp_path, sample_page, fmt, kind):
    original = tmp_path / "original"
    original.mkdir()
    page = original / "page.png"
    page.write_bytes(sample_page.read_bytes())
    work = tmp_path / "work"
    readers.import_source(original, work)
    doc_path = work / "comic.json"
    replies = tmp_path / "reader"
    worksheet.build_document(doc_path, replies)
    target = page if kind == "original" else replies / "p0001.txt"
    before = target.read_bytes()
    with pytest.raises((ValueError, OSError)):
        export.export_document(doc_path, target, fmt=fmt, draft=True)
    assert target.read_bytes() == before


def test_directory_named_like_export_metadata_is_never_owned(imported, tmp_path):
    out = tmp_path / "edition"
    note = out / "ComicInfo.xml" / "operator.txt"
    note.parent.mkdir(parents=True)
    note.write_text("Keep my note", encoding="utf-8")
    with pytest.raises(ValueError):
        export.export_document(imported, out, fmt="dir", draft=True)
    assert note.read_text(encoding="utf-8") == "Keep my note"
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*")) == [
        "ComicInfo.xml", "ComicInfo.xml/operator.txt"]
