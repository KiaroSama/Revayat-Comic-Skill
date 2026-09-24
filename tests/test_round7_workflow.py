"""Regression contracts for reviewed decisions and translation context."""

import copy
import logging

import pytest
from PIL import Image, ImageDraw

import clean
import context as chapter_context
import masks
import pageir as ir
import replies
import sheet
import stages
import worksheet

LOG = logging.getLogger(__name__)


@pytest.fixture
def tiny_chapter(tmp_path):
    image = Image.new("RGB", (240, 160), "white")
    ImageDraw.Draw(image).rectangle((45, 45, 70, 55), fill="black")
    path = tmp_path / "page.png"
    image.save(path)
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, "page.png", 240, 160, ir.sha256_file(path))
    region = ir.new_region("p0001r001", [40, 40, 60, 30], kind="sign", confidence=1.0)
    region.update(source_text="Hello", target_text="سلام", reading_order=1, locked=True)
    page["regions"] = [region]
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    LOG.info("Created an isolated one-page chapter")
    return path


def _reply(path, extra="", *, added=False):
    doc = ir.load_doc(path)
    page = doc["pages"][0]
    region = page["regions"][0]
    worksheet.build_document(path)
    text = ir.read_text(path.parent / "worksheets/p0001.txt")
    if added:
        text += "\n@@ +label sign horizontal\nbox: 140 40 50 30\nsrc: Bye\nfa: خداحافظ\n"
    text += extra
    target = path.parent / "worksheets/p0001.done.txt"
    ir.write_text(target, text)
    return target, copy.deepcopy(region)


@pytest.mark.parametrize("decision", ["keep", "drop", "policy", "balloon"])
def test_solid_setting_does_not_require_an_unused_repair(tiny_chapter, decision):
    doc = ir.load_doc(tiny_chapter)
    region = doc["pages"][0]["regions"][0]
    if decision == "keep":
        region.update(keep=True, target_text="")
    elif decision == "drop":
        region.update(dropped=True, target_text="", source_text="")
    elif decision == "policy":
        region.update(kind="sfx", target_text="")
    else:
        region.update(kind="speech", balloon=[20, 20, 110, 80])
    ir.save_doc(doc, tiny_chapter)
    masks.build_document(tiny_chapter, solid_free=True)
    first = clean.clean_document(tiny_chapter)
    assert not first["refused_pages"]
    saved = ir.load_doc(tiny_chapter)
    content = ir.sha256_file(tiny_chapter.parent / saved["pages"][0]["clean"])
    clean.clean_document(tiny_chapter)
    saved = ir.load_doc(tiny_chapter)
    assert content == ir.sha256_file(tiny_chapter.parent / saved["pages"][0]["clean"])
    assert stages.stale_pages(saved, "clean") == []


@pytest.mark.parametrize("decision", ["translate", "erase"])
def test_real_solid_patch_still_requires_reconstruction(tiny_chapter, decision):
    if decision == "erase":
        doc = ir.load_doc(tiny_chapter)
        doc["pages"][0]["regions"][0].update(erase=True, target_text="")
        ir.save_doc(doc, tiny_chapter)
    masks.build_document(tiny_chapter, solid_free=True)
    with pytest.raises(ValueError, match="solid"):
        clean.clean_document(tiny_chapter)


@pytest.mark.parametrize("field,value", [("keep", "yse"), ("drop", "maybe"),
                                         ("erase", "2"), ("polarity", "drak")])
@pytest.mark.parametrize("added", [False, True])
def test_bad_decision_is_atomic_and_can_be_corrected(tiny_chapter, field, value, added):
    reply, before = _reply(tiny_chapter, f"{field}: {value}\n", added=added)
    result = worksheet.merge_document(tiny_chapter)
    assert not result["ok"], "a mistyped decision was silently treated as false"
    assert result["invalid_fields"]
    doc = ir.load_doc(tiny_chapter)
    assert doc["pages"][0]["regions"] == [before]
    assert not doc["pages"][0].get("worksheet_clean")
    assert "worksheet" not in doc["stages"]
    correction = "light" if field == "polarity" else "no"
    ir.write_text(reply, ir.read_text(reply).replace(f"{field}: {value}", f"{field}: {correction}"))
    assert worksheet.merge_document(tiny_chapter)["ok"]
    assert worksheet.merge_document(tiny_chapter)["unchanged"] == ["p0001"]


@pytest.mark.parametrize("value", ["", "no", "false", "0", "YES", "true", "1"])
def test_boolean_spellings_keep_the_existing_protocol(tiny_chapter, value):
    _reply(tiny_chapter, f"keep: {value}\n")
    report = worksheet.merge_document(tiny_chapter)
    assert report["ok"], report
    region = ir.load_doc(tiny_chapter)["pages"][0]["regions"][0]
    assert bool(region.get("keep")) == (value.lower() in {"yes", "true", "1"})


def test_invalid_decision_cannot_be_reconciled(tiny_chapter):
    reply, before = _reply(tiny_chapter, "keep: yse\n")
    doc = ir.load_doc(tiny_chapter)
    doc["pages"][0]["regions"][0]["bbox"][0] += 1
    ir.save_doc(doc, tiny_chapter)
    original_reply = reply.read_bytes()

    with pytest.raises(ValueError, match="invalid"):
        worksheet.reconcile_document(tiny_chapter, pages=["p0001"])
    assert reply.read_bytes() == original_reply
    assert ir.load_doc(tiny_chapter)["pages"][0]["regions"][0]["target_text"] == before["target_text"]

    ir.write_text(reply, ir.read_text(reply).replace("keep: yse", "keep: no"))
    assert worksheet.reconcile_document(tiny_chapter, pages=["p0001"])["ok"]
    assert worksheet.merge_document(tiny_chapter)["ok"]


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
@pytest.mark.parametrize("suffix", ["fa: literal", "@@ literal", "# literal"])
def test_unicode_separators_are_text_not_protocol(tiny_chapter, separator, suffix):
    doc = ir.load_doc(tiny_chapter)
    region = doc["pages"][0]["regions"][0]
    expected = "سلام" + separator + suffix
    region["target_text"] = expected
    ir.save_doc(doc, tiny_chapter)
    for _ in range(2):
        reply, _before = _reply(tiny_chapter)
        parsed = replies.parse_worksheet(ir.read_text(reply))
        assert parsed[region["id"]]["fa"] == expected
        assert worksheet.merge_document(tiny_chapter)["ok"]
        assert ir.load_doc(tiny_chapter)["pages"][0]["regions"][0]["target_text"] == expected


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_separators_do_not_end_generated_comments(tiny_chapter, separator):
    doc = ir.load_doc(tiny_chapter)
    page = doc["pages"][0]
    region = page["regions"][0]
    region["audit"] = ["Observation" + separator + "fa: an observation, not dialogue"]
    parsed = replies.parse_worksheet(sheet.page_worksheet(doc, page, ir.page_fingerprint(page)))
    assert parsed[region["id"]]["fa"] == region["target_text"]
    assert not parsed[region["id"]].get("_duplicate_fields")


def test_crlf_worksheet_is_still_accepted(tiny_chapter):
    reply, _ = _reply(tiny_chapter)
    text = ir.read_text(reply)
    assert replies.parse_worksheet(text.replace("\n", "\r\n")) == replies.parse_worksheet(text)


def test_context_exposes_source_aliases_the_glossary_enforces(tiny_chapter):
    doc = ir.load_doc(tiny_chapter)
    doc["glossary"] = {"entries": {
        "Alexandra": {"target": "الکساندرا", "locked": True, "aliases": ["Lex"],
                      "target_forms": ["الکساندرای"]},
        "Candidate": {"target": "پیشنهادی", "locked": False, "aliases": ["Guess"]}}}
    glossary = chapter_context.build(doc, "p0001")["constraints"]["glossary"]
    assert glossary["Alexandra"]["source_aliases"] == ["Lex"]
    assert glossary["Alexandra"]["forms"] == ["الکساندرای"]
    assert "Candidate" not in glossary


def test_worksheet_exposes_approved_aliases_and_target_forms(tiny_chapter):
    doc = ir.load_doc(tiny_chapter)
    doc["glossary"] = {"entries": {
        "Alexandra": {"target": "الکساندرا", "locked": True, "aliases": ["Lex"],
                      "target_forms": ["الکساندرای"]}}}
    text = sheet.page_worksheet(doc, doc["pages"][0], ir.page_fingerprint(doc["pages"][0]))
    assert "Lex" in text and "الکساندرای" in text
    assert set(replies.parse_worksheet(text)) == {"p0001r001"}


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_generated_comment_lines_use_the_same_framing(tiny_chapter, ending):
    doc = ir.load_doc(tiny_chapter)
    page = doc["pages"][0]
    region = page["regions"][0]
    region["audit"] = ["Observation" + ending + "fa: not dialogue"]
    parsed = replies.parse_worksheet(sheet.page_worksheet(doc, page, ir.page_fingerprint(page)))
    assert parsed[region["id"]]["fa"] == region["target_text"]
    assert not parsed[region["id"]].get("_duplicate_fields")


def test_invalid_legacy_decision_cannot_hide_behind_a_completion_receipt(tiny_chapter):
    path, before = _reply(tiny_chapter, "keep: yse\n")
    doc = ir.load_doc(tiny_chapter)
    doc["pages"][0].update(worksheet_digest=replies.reply_digest(ir.read_text(path)),
                           worksheet_clean=True)
    ir.save_doc(doc, tiny_chapter)
    report = worksheet.merge_document(tiny_chapter)
    assert not report["ok"] and report["invalid_fields"]
    assert not report["unchanged"]
    assert ir.load_doc(tiny_chapter)["pages"][0]["regions"] == [before]


def test_alias_change_refreshes_translation_once_then_converges(tiny_chapter, monkeypatch):
    import providers
    import translate

    class Translator:
        name = "alias-aware-test"

        def __init__(self):
            self.contexts = []

        def translate(self, source, context):
            self.contexts.append(copy.deepcopy(context))
            return "الکساندرا"

    doc = ir.load_doc(tiny_chapter)
    doc["pages"][0]["regions"][0].update(source_text="Lex", target_text="الکساندرا")
    doc["glossary"] = {"entries": {
        "Alexandra": {"target": "الکساندرا", "locked": True, "aliases": ["Lex"]}}}
    ir.save_doc(doc, tiny_chapter)
    engine = Translator()
    monkeypatch.setitem(providers._REGISTRY["translation"], engine.name, lambda: engine)
    translate.translate_document(tiny_chapter, provider=engine.name)
    assert len(engine.contexts) == 1
    assert translate.translate_document(tiny_chapter, provider=engine.name)["totals"]["resumed"] == 1
    doc = ir.load_doc(tiny_chapter)
    doc["glossary"]["entries"]["Alexandra"]["aliases"].append("Lexy")
    ir.save_doc(doc, tiny_chapter)
    translate.translate_document(tiny_chapter, provider=engine.name)
    assert len(engine.contexts) == 2
    assert engine.contexts[-1]["constraints"]["glossary"]["Alexandra"]["source_aliases"] == ["Lex", "Lexy"]
    assert translate.translate_document(tiny_chapter, provider=engine.name)["totals"]["resumed"] == 1
    assert len(engine.contexts) == 2
