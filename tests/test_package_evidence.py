"""Incomplete export provenance never certifies a primary edition."""
from __future__ import annotations

import copy
import pytest
from PIL import Image

import export
import package
import pageir as ir
import readers


@pytest.fixture
def edition(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 40), "white").save(source)
    folder = tmp_path / "inputs"
    folder.mkdir()
    source.replace(folder / "page1.png")
    Image.new("RGB", (32, 40), "black").save(folder / "page2.png")
    readers.import_source(folder, tmp_path / "work", source_language="en")
    return tmp_path / "work" / "comic.json"


@pytest.mark.parametrize("fmt", ["cbz", "dir"])
@pytest.mark.parametrize("damage", ["missing", "empty", "short", "duplicate", "hash", "row"])
def test_incomplete_evidence_is_unverified(edition, tmp_path, fmt, damage):
    out = tmp_path / ("book.cbz" if fmt == "cbz" else "book")
    export.export_document(edition, out, fmt=fmt, draft=True)
    doc = ir.load_doc(edition)
    selected = doc["stages"]["export"]["editions"][str(out.resolve())]
    rows = selected["manifest"]
    if damage == "missing":
        selected.pop("manifest")
    elif damage == "empty":
        selected["manifest"] = []
    elif damage == "short":
        selected["manifest"] = rows[:1]
    elif damage == "duplicate":
        selected["manifest"] = rows + copy.deepcopy(rows)
    elif damage == "hash":
        rows[0]["sha256"] = "not-a-digest"
    else:
        selected["manifest"] = [None]
    ir.save_doc(doc, edition)
    before = edition.read_bytes()
    report = package.check_package(out, edition)
    assert not report["ok"], report
    assert any(item["code"] == "archive-unverified" for item in report["findings"])
    assert edition.read_bytes() == before


@pytest.mark.parametrize("fmt", ["cbz", "dir"])
def test_complete_export_evidence_survives_a_copy(edition, tmp_path, fmt):
    import shutil

    original = tmp_path / ("book.cbz" if fmt == "cbz" else "book")
    export.export_document(edition, original, fmt=fmt, draft=True)
    copied = tmp_path / ("copied.cbz" if fmt == "cbz" else "copied")
    if fmt == "dir":
        shutil.copytree(original, copied)
    else:
        shutil.copyfile(original, copied)
    assert package.check_package(copied, edition)["ok"]
    doc = ir.load_doc(edition)
    assert all(len(row["sha256"]) == 64 for row in doc["stages"]["export"]["manifest"])
