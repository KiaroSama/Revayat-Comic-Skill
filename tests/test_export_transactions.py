"""What survives a failure in the middle of an import or an export.

Every test here injects a failure at a specific boundary and then asks what is
on disk. The answers that matter are never "it raised" — they are "the previous
edition is still there", "the two halves agree", and "the original nobody can
rebuild was not touched".
"""
from __future__ import annotations

import shutil
import zipfile

import pytest

import export
import pageir as ir
import readers


# --------------------------------------------------------------------------- #
# One writer at a time
# --------------------------------------------------------------------------- #

def test_two_imports_into_one_folder_do_not_interleave(sample_cbz, tmp_path):
    """Each staged its own pages, each promoted them, and whichever saved last
    published ITS document over the other's images."""
    work = tmp_path / "work"
    readers.import_source(sample_cbz, work, source_language="ja")

    with ir.workspace_lock(work, what="test"):
        with pytest.raises(RuntimeError, match="already writing"):
            readers.import_source(sample_cbz, work, source_language="ja")

    # And the lock is released, so the ordinary next run works.
    readers.import_source(sample_cbz, work, source_language="ja")
    assert ir.load_doc(work / "comic.json")["pages"]


def test_the_lock_is_released_when_an_import_fails(sample_cbz, tmp_path,
                                                   monkeypatch):
    work = tmp_path / "work"
    monkeypatch.setattr(readers, "_stage_pages",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no")))

    with pytest.raises(OSError):
        readers.import_source(sample_cbz, work, source_language="ja")

    assert not (work / ".revayat-lock").exists()


# --------------------------------------------------------------------------- #
# The original container
# --------------------------------------------------------------------------- #

def test_the_archive_the_chapter_came_from_is_never_exported_over(finished,
                                                                  sample_cbz,
                                                                  tmp_path):
    """Only its NAME was recorded, so nothing downstream could tell that
    `--out` was about to write over the archive the chapter was imported from
    — the one file in this pipeline that is not reproducible."""
    original = tmp_path / "chapter.cbz"
    shutil.copyfile(sample_cbz, original)
    before = ir.sha256_file(original)
    doc = ir.load_doc(finished)
    doc["source"]["path"] = str(original.resolve())
    ir.save_doc(doc, finished)

    with pytest.raises(ValueError, match="the chapter is made of"):
        export.export_document(finished, original)

    assert ir.sha256_file(original) == before


def test_an_import_records_where_it_came_from(sample_cbz, tmp_path):
    work = tmp_path / "work"
    readers.import_source(sample_cbz, work, source_language="ja")

    recorded = ir.load_doc(work / "comic.json")["source"]["path"]

    assert recorded == str(sample_cbz.resolve())


# --------------------------------------------------------------------------- #
# A folder export that fails half way
# --------------------------------------------------------------------------- #

def _previous_edition(out):
    """A folder holding an older export, byte for byte recorded."""
    return {child.name: child.read_bytes()
            for child in sorted(out.iterdir()) if child.is_file()}


def test_a_failed_promotion_keeps_the_file_it_had_already_moved_aside(
        finished, tmp_path, monkeypatch):
    """The one file whose promotion raised had its previous edition moved
    aside, left out of the rollback list, and then deleted by the cleanup — the
    operator's current file destroyed by a failure that changed nothing else."""
    out = tmp_path / "edition"
    export.export_document(finished, out)
    before = _previous_edition(out)
    assert len(before) > 2

    real = type(out).replace
    seen = {"n": 0}

    def flaky(self, target):
        # The fourth move: the first file has been backed up and promoted, the
        # second has just been backed up, and its promotion is what fails.
        seen["n"] += 1
        if seen["n"] == 4:
            raise OSError("disk full")
        return real(self, target)

    monkeypatch.setattr(type(out), "replace", flaky)
    with pytest.raises(OSError):
        export.export_document(finished, out)
    monkeypatch.undo()

    assert _previous_edition(out) == before, "the previous edition was damaged"


def test_a_folder_export_that_fails_leaves_the_previous_edition_whole(
        finished, tmp_path, monkeypatch):
    out = tmp_path / "edition"
    export.export_document(finished, out)
    before = _previous_edition(out)

    monkeypatch.setattr(export, "_comic_info",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        export.export_document(finished, out)
    monkeypatch.undo()

    assert _previous_edition(out) == before


def test_an_operators_own_files_are_left_where_they_are(finished, tmp_path):
    """Promoted file by file rather than by swapping the folder, because
    anything else in there is not ours."""
    out = tmp_path / "edition"
    out.mkdir()
    keep = out / "notes.txt"
    keep.write_text("mine", encoding="utf-8")

    export.export_document(finished, out)

    assert keep.read_text(encoding="utf-8") == "mine"


# --------------------------------------------------------------------------- #
# The package and the document that describes it
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["chapter.cbz", "edition"])
def test_a_failed_document_save_leaves_a_recoverable_record(finished, tmp_path,
                                                            monkeypatch, name):
    """The package landed and the document could not be written, so the folder
    held this edition while `comic.json` described the last one — and
    `qa package` compared the new files against the old manifest."""
    out = tmp_path / name
    real_save = ir.save_doc
    monkeypatch.setattr(ir, "save_doc",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("full")))

    with pytest.raises(OSError):
        export.export_document(finished, out)
    monkeypatch.setattr(ir, "save_doc", real_save)

    pending = finished.with_name(finished.name + ".export-pending.json")
    assert pending.is_file(), "nothing on disk says the two halves disagree"
    assert out.exists(), "the package was rolled back but the stamp was not"

    # The next export reconciles it before doing anything else.
    export.export_document(finished, tmp_path / "again.cbz")
    assert not pending.exists()


def test_a_pending_stamp_is_applied_on_the_next_run(finished, tmp_path):
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    assert ir.load_doc(finished)["stages"]["export"]["manifest"]

    ir.write_text(finished.with_name(finished.name + ".export-pending.json"),
                  ir.dumps({"result": {"format": "cbz", "path": "somewhere",
                                       "manifest": []},
                            "options": {"format": "cbz", "quality": 0,
                                        "draft": False}}) + "\n")

    applied = export.reconcile_pending(finished)

    assert applied is not None
    assert ir.load_doc(finished)["stages"]["export"]["path"] == "somewhere"


def test_a_clean_export_leaves_no_pending_record(finished, tmp_path):
    out = tmp_path / "chapter.cbz"

    export.export_document(finished, out)

    assert not finished.with_name(
        finished.name + ".export-pending.json").exists()
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist()
