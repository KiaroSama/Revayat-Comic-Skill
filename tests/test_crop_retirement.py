"""Shrinking reading derivatives retires only proven stage-owned files."""
import pytest
from PIL import Image

import crops
import pageir as ir
import readers


@pytest.fixture
def chapter(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 150), "white").save(source)
    readers.import_source(source, tmp_path / "work", source_language="en")
    path = tmp_path / "work" / "comic.json"
    doc = ir.load_doc(path)
    doc["pages"][0]["regions"] = [
        ir.new_region(f"p0001r{i:03d}", [10, 10 + i * 15, 30, 10], kind="sign")
        for i in range(1, 4)]
    ir.save_doc(doc, path)
    monkeypatch.setattr(crops, "SHEET_MAX_HEIGHT", 1)
    crops.build_document(path)
    return path


def test_shrink_retires_only_recorded_owned_sheets(chapter):
    folder = chapter.parent / "crops" / "p0001"
    sentinel = folder / "sheet99.png"
    sentinel.write_bytes(b"operator-owned")
    doc = ir.load_doc(chapter)
    assert len(doc["pages"][0]["sheets"]) == 3
    doc["pages"][0]["regions"] = doc["pages"][0]["regions"][:1]
    ir.save_doc(doc, chapter)
    crops.build_document(chapter)
    assert not (folder / "sheet02.png").exists()
    assert not (folder / "sheet03.png").exists()
    assert sentinel.read_bytes() == b"operator-owned"
    assert len(ir.load_doc(chapter)["pages"][0]["sheets"]) == 1


def test_failed_document_save_preserves_old_derivatives(chapter, monkeypatch):
    folder = chapter.parent / "crops" / "p0001"
    before = {file.name: file.read_bytes() for file in folder.iterdir()}
    doc = ir.load_doc(chapter)
    doc["pages"][0]["regions"] = []
    ir.save_doc(doc, chapter)
    record = chapter.read_bytes()

    def fail(*args):
        raise OSError("controlled save failure")

    monkeypatch.setattr(ir, "save_doc", fail)
    with pytest.raises(OSError):
        crops.build_document(chapter)
    assert chapter.read_bytes() == record
    assert {file.name: file.read_bytes() for file in folder.iterdir()} == before


def test_failed_target_write_restores_successfully_promoted_files(chapter, monkeypatch):
    folder = chapter.parent / "crops" / "p0001"
    before = {file.name: file.read_bytes() for file in folder.iterdir()}
    doc = ir.load_doc(chapter)
    doc["pages"][0]["regions"][0]["bbox"] = [20, 20, 40, 10]
    ir.save_doc(doc, chapter)
    write = ir.write_bytes

    def fail(path, payload):
        if str(path).endswith("sheet02.png") and ".crops-" not in str(path):
            raise PermissionError("controlled target failure")
        return write(path, payload)

    monkeypatch.setattr(ir, "write_bytes", fail)
    with pytest.raises(PermissionError):
        crops.build_document(chapter)
    assert {file.name: file.read_bytes() for file in folder.iterdir()} == before


def test_deletion_failure_retries_from_recorded_ownership(chapter, monkeypatch):
    from pathlib import Path

    doc = ir.load_doc(chapter)
    doc["pages"][0]["regions"] = doc["pages"][0]["regions"][:1]
    ir.save_doc(doc, chapter)
    unlink = Path.unlink
    def fail(target, *args, **kwargs):
        if target.name == "sheet02.png":
            raise PermissionError("controlled deletion failure")
        return unlink(target, *args, **kwargs)
    with monkeypatch.context() as temporary:
        temporary.setattr(Path, "unlink", fail)
        with pytest.raises(PermissionError):
            crops.build_document(chapter)
    page = ir.load_doc(chapter)["pages"][0]
    assert "crops/p0001/sheet02.png" in page["sheets_retiring"]
    crops.build_document(chapter)
    assert not (chapter.parent / "crops/p0001/sheet02.png").exists()


def test_failed_rollback_retains_originals_for_inspection(chapter, monkeypatch):
    folder = chapter.parent / "crops" / "p0001"
    old = (folder / "overview.png").read_bytes()
    doc = ir.load_doc(chapter)
    doc["pages"][0]["regions"][0]["bbox"] = [20, 20, 40, 10]
    ir.save_doc(doc, chapter)
    write = ir.write_bytes
    def fail(target, payload):
        if target == folder / "sheet02.png" or (target == folder / "overview.png" and payload == old):
            raise PermissionError("controlled restoration failure")
        return write(target, payload)
    monkeypatch.setattr(ir, "write_bytes", fail)
    with pytest.raises(RuntimeError, match="restoration failed"):
        crops.build_document(chapter)
    retained = list(chapter.parent.glob(".crops-*.recovery"))
    assert len(retained) == 1
    assert (retained[0] / "old/crops/p0001/overview.png").read_bytes() == old
    with pytest.raises(ValueError, match="recovery evidence"):
        crops.build_document(chapter)


def test_unchanged_legacy_sheets_are_admitted_by_exact_rerender(chapter):
    doc = ir.load_doc(chapter)
    doc["pages"][0].pop("sheet_hashes")
    ir.save_doc(doc, chapter)
    crops.build_document(chapter)
    assert len(ir.load_doc(chapter)["pages"][0]["sheet_hashes"]) == 3


def test_changed_recorded_sheet_is_preserved(chapter):
    sheet = chapter.parent / "crops" / "p0001" / "sheet02.png"
    sheet.write_bytes(b"operator changed it")
    doc = ir.load_doc(chapter)
    doc["pages"][0]["regions"] = []
    ir.save_doc(doc, chapter)
    with pytest.raises(ValueError, match="ownership"):
        crops.build_document(chapter)
    assert sheet.read_bytes() == b"operator changed it"
