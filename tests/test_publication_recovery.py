"""Publication owns its destination through metadata commitment and recovery."""

import shutil
from pathlib import Path

import pytest

import export
import falint
import journal
import pageir as ir
import writers


def test_every_document_writer_observes_workspace_ownership(translated):
    before = translated.read_bytes()
    with ir.workspace_lock(translated.parent, what="export"):
        with pytest.raises(RuntimeError, match="already writing"):
            falint.fix_document(translated)
    assert translated.read_bytes() == before


def test_staging_cleanup_cannot_delete_the_next_owners_claim(tmp_path):
    path = tmp_path / "claim"
    promoted = tmp_path / "published"
    with writers._claim(path, directory=False):
        path.write_bytes(b"first writer")
        path.replace(promoted)
        path.write_bytes(b"second writer")
    assert path.read_bytes() == b"second writer"
    assert promoted.read_bytes() == b"first writer"


@pytest.mark.parametrize("fmt", ["cbz", "pdf", "dir"])
def test_metadata_recovery_keeps_all_editions(imported, tmp_path, monkeypatch, fmt):
    first = tmp_path / "first.cbz"
    export.export_document(imported, first, draft=True)
    remembered = ir.load_doc(imported)["stages"]["export"]["editions"]
    second = tmp_path / ("second" if fmt == "dir" else "second." + fmt)
    save = ir.save_doc

    def fail(*args, **kwargs):
        raise OSError("document save interrupted")

    monkeypatch.setattr(ir, "save_doc", fail)
    with pytest.raises(OSError, match="interrupted"):
        export.export_document(imported, second, fmt=fmt, draft=True)
    monkeypatch.setattr(ir, "save_doc", save)
    assert export.reconcile_pending(imported)
    editions = ir.load_doc(imported)["stages"]["export"]["editions"]
    assert editions[str(first.resolve())] == remembered[str(first.resolve())]
    assert str(second.resolve()) in editions
    assert export.reconcile_pending(imported) is None


def test_null_pending_result_is_quarantined(imported, tmp_path):
    ir.write_text(journal.path_for(imported), ir.dumps({
        "document": ir.sha256_file(imported), "destination": str(tmp_path / "book.cbz"),
        "published": {"book.cbz": "0" * 64}, "result": None, "options": {}}))
    assert export.reconcile_pending(imported) is None
    assert list(imported.parent.glob("*.export-conflict-*.json"))


def test_second_workspace_cannot_publish_during_metadata_commit(
        imported, tmp_path, tmp_path_factory, monkeypatch):
    other_root = tmp_path_factory.mktemp("second-workspace")
    shutil.copytree(imported.parent, other_root, dirs_exist_ok=True)
    other = other_root / imported.name
    out = tmp_path / "edition.cbz"
    save = ir.save_doc
    attempted = []

    def interleave(doc, path):
        if Path(path) == imported:
            with pytest.raises(RuntimeError, match="already"):
                export.export_document(other, out, draft=True)
            attempted.append(True)
        return save(doc, path)

    monkeypatch.setattr(ir, "save_doc", interleave)
    export.export_document(imported, out, draft=True)
    assert attempted == [True]
    assert ir.load_doc(imported)["stages"]["export"]["package_sha256"] == ir.sha256_file(out)


@pytest.mark.parametrize("change", ["altered", "extra"])
def test_uncertain_staging_is_preserved_when_publication_is_refused(imported, tmp_path, monkeypatch, change):
    out = tmp_path / "edition"
    stage = writers.staging_path(out)
    promote = journal.promote
    filename = "0001.png" if change == "altered" else "operator.txt"

    def interleave(doc_path, record, **kwargs):
        (stage / filename).write_bytes(b"operator-owned bytes")
        return promote(doc_path, record, **kwargs)

    monkeypatch.setattr(journal, "promote", interleave)
    with pytest.raises((ValueError, RuntimeError)):
        export.export_document(imported, out, fmt="dir", draft=True)
    assert (stage / filename).read_bytes() == b"operator-owned bytes"
    assert journal.path_for(imported).exists()
