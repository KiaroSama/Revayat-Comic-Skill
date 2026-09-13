"""What survives a failure in the middle of an import or an export.

Every test here injects a failure at a specific boundary and then asks what is
on disk. The answers that matter are never "it raised" — they are "the previous
edition is still there", "the two halves agree", and "the original nobody can
rebuild was not touched".
"""
from __future__ import annotations

import shutil
from pathlib import Path
import zipfile

import pytest

import export
import pageir as ir
import writers
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

    monkeypatch.setattr(writers, "_comic_info",
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


def _journal(doc_path):
    return doc_path.with_name(doc_path.name + ".export-pending.json")


def _interrupted(doc_path, out, monkeypatch):
    """A real journal, left behind the way an interrupted export leaves one.

    The package lands and the document cannot be written, which is the gap the
    record exists for. Written by the pipeline rather than invented here: a
    record this file makes up is a record nothing would ever produce.
    """
    monkeypatch.setattr(ir, "save_doc",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        export.export_document(doc_path, out)
    monkeypatch.undo()
    assert _journal(doc_path).is_file() and Path(out).exists()


def test_a_pending_stamp_is_applied_on_the_next_run(finished, tmp_path,
                                                    monkeypatch):
    """Written before the package and removed after the document, so one left
    behind is an export interrupted between the two. It is applied when — and
    only when — the document it describes and the bytes it published are both
    still there."""
    out = tmp_path / "chapter.cbz"
    _interrupted(finished, out, monkeypatch)

    applied = export.reconcile_pending(finished)

    assert applied is not None
    assert ir.load_doc(finished)["stages"]["export"]["path"] == str(out)
    assert not _journal(finished).exists()


def test_a_clean_export_leaves_no_pending_record(finished, tmp_path):
    out = tmp_path / "chapter.cbz"

    export.export_document(finished, out)

    assert not finished.with_name(
        finished.name + ".export-pending.json").exists()
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist()


# --------------------------------------------------------------------------- #
# The journal is written BEFORE the bytes it describes.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["chapter.cbz", "chapter.pdf", "edition"])
def test_nothing_is_published_before_the_recovery_record_exists(
        finished, tmp_path, monkeypatch, name):
    """The writer promoted the package and the journal was written afterwards,
    so a failure in that gap left new bytes at the destination, the previous
    manifest in the document, and nothing anywhere saying the two disagreed.

    Failing the journal write is the same instant as being killed there."""
    out = tmp_path / name
    real = ir.write_text

    def refuse(path, *args, **kwargs):
        if str(path).endswith(".export-pending.json"):
            raise OSError("full")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(ir, "write_text", refuse)

    with pytest.raises(OSError):
        export.export_document(finished, out)

    # A folder destination is created before anything is encoded, and an empty
    # folder is not a published edition. What must not exist is a page.
    landed = sorted(out.iterdir()) if out.is_dir() else [out] if out.exists() else []
    assert not landed, "the package was published with no way back"


def test_a_journal_for_another_generation_of_the_document_is_not_applied(
        finished, tmp_path, monkeypatch):
    """`reconcile_pending` stamped whatever the record said. A chapter changed
    since is a different edition, and certifying it with the old export's
    manifest is the cross-generation claim the journal exists to prevent."""
    _interrupted(finished, tmp_path / "chapter.cbz", monkeypatch)
    doc = ir.load_doc(finished)
    doc["meta"]["title"] = "a different edition"
    ir.save_doc(doc, finished)

    assert export.reconcile_pending(finished) is None
    assert "manifest" not in (ir.load_doc(finished).get("stages", {})
                              .get("export") or {})


def test_a_journal_whose_package_never_landed_is_not_applied(finished,
                                                             tmp_path,
                                                             monkeypatch):
    """The other half: the destination holds nothing this export wrote."""
    out = tmp_path / "chapter.cbz"
    _interrupted(finished, out, monkeypatch)
    out.unlink()

    assert export.reconcile_pending(finished) is None


def test_a_journal_whose_package_was_replaced_is_not_applied(finished,
                                                             tmp_path,
                                                             monkeypatch):
    out = tmp_path / "chapter.cbz"
    _interrupted(finished, out, monkeypatch)
    out.write_bytes(b"not the package that was published")

    assert export.reconcile_pending(finished) is None


def test_a_rejected_journal_is_kept_as_evidence(finished, tmp_path,
                                                monkeypatch):
    """Refusing to apply it is not a reason to destroy it: it is the only
    record of what the interrupted run was doing."""
    out = tmp_path / "chapter.cbz"
    _interrupted(finished, out, monkeypatch)
    out.unlink()

    export.reconcile_pending(finished)

    kept = list(finished.parent.glob("*.export-conflict*.json"))
    assert kept, "the evidence was thrown away"
    assert not _journal(finished).exists()


def test_a_rejected_journal_does_not_block_the_next_export(finished, tmp_path,
                                                           monkeypatch):
    """A refusal that cannot be cleared is a trap. The next export produces its
    own coherent edition."""
    out = tmp_path / "chapter.cbz"
    _interrupted(finished, out, monkeypatch)
    out.unlink()

    export.export_document(finished, tmp_path / "again.cbz")

    stamp = ir.load_doc(finished)["stages"]["export"]
    assert stamp["path"] == str(tmp_path / "again.cbz")


# --------------------------------------------------------------------------- #
# Two writers at one destination
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["chapter.cbz", "chapter.pdf", "edition"])
def test_a_second_writer_at_the_same_destination_is_refused(finished, tmp_path,
                                                            name):
    """A random scratch name made ownership a fact and serialization
    impossible: two exports of one chapter to one destination each wrote their
    own staging file and both promoted, last writer winning, neither knowing
    the other existed."""
    out = tmp_path / name
    live = export.staging_path(out)
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(b"another writer is here")

    with pytest.raises(RuntimeError, match="already"):
        export.export_document(finished, out)

    assert live.read_bytes() == b"another writer is here"


# --------------------------------------------------------------------------- #
# What the chapter is made of
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("what", ["region-mask", "crops", "worksheets"])
def test_the_working_assets_are_never_exported_over(finished, tmp_path, what):
    """`_dependencies` knew page-level images only. A region mask, the crops a
    reader is looking at and the worksheets carrying their replies are all
    files the chapter is made of, and exporting onto them destroys work the
    package cannot be used to rebuild."""
    import crops as crops_stage
    import worksheet

    root = ir.doc_dir(finished)
    crops_stage.build_document(finished)
    worksheet.build_document(finished)
    page = ir.load_doc(finished)["pages"][0]

    target = {
        "region-mask": root / next(region["mask"] for region in page["regions"]
                                   if region.get("mask")),
        "crops": root / "crops" / page["id"],
        "worksheets": ir.worksheet_folder(finished, ir.load_doc(finished)),
    }[what]

    with pytest.raises(ValueError):
        export.export_document(finished, target,
                               fmt="dir" if target.is_dir() else "cbz")
