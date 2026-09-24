"""Worksheet locations remain stable across independent working directories."""

from __future__ import annotations

import context as chapter_context
import pageir as ir
import worksheet


def _document(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, "page.png", 64, 64, "0" * 64)
    region = ir.new_region("p0001r001", [4, 4, 40, 20], kind="speech")
    region.update(source_text="Hello", reading_order=1, confidence=1.0)
    page["regions"] = [region]
    doc["pages"] = [page]
    path = work / "comic.json"
    ir.save_doc(doc, path)
    return path


def test_external_relative_worksheets_survive_chdir(tmp_path, monkeypatch):
    path = _document(tmp_path)
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.chdir(launch)
    worksheet.build_document(path, out="answers")
    reply = launch / "answers" / "p0001.done.txt"
    text = ir.read_text(reply.with_name("p0001.txt"))
    ir.write_text(reply, text.replace("fa: ", "fa: سلام"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert worksheet.status(path)["present"] == ["p0001"]
    assert worksheet.merge_document(path)["ok"]
    doc = ir.load_doc(path)
    assert doc["meta"]["worksheets"] == str(reply.parent.resolve())
    assert chapter_context.worksheet_folder(path, doc) == reply.parent
    assert doc["pages"][0]["regions"][0]["target_text"] == "سلام"
    assert worksheet.merge_document(path)["unchanged"] == ["p0001"]
    assert not (elsewhere / "answers").exists()


def test_document_relative_recorded_folder_is_not_process_relative(tmp_path, monkeypatch):
    path = _document(tmp_path)
    doc = ir.load_doc(path)
    doc["meta"]["worksheets"] = "proofreader"
    other = tmp_path / "different"
    other.mkdir()
    monkeypatch.chdir(other)

    assert ir.worksheet_folder(path, doc) == path.parent / "proofreader"
    assert chapter_context.worksheet_folder(path, doc) == path.parent / "proofreader"
    doc["meta"].pop("worksheets")
    assert ir.worksheet_folder(path, doc) == path.parent / "worksheets"
    assert ir.worksheet_folder(path, doc, "override") == other / "override"
