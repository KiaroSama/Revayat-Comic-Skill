"""Regressions for worksheet framing and typed terminology decisions."""

import copy
import json
import logging

import pytest

import context as chapter_context
import glossary
import pageir as ir
import replies
import worksheet

LOG = logging.getLogger(__name__)


@pytest.fixture
def chapter(tmp_path):
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, "page.png", 240, 160, "0" * 64)
    region = ir.new_region("p0001r001", [10, 10, 60, 30], kind="speech")
    region.update(source_text="Hello", target_text="سلام", locked=True)
    page["regions"] = [region]
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    LOG.info("Created an isolated worksheet chapter")
    return path


def write_reply(path, text=None):
    worksheet.build_document(path)
    folder = path.parent / "worksheets"
    body = ir.read_text(folder / "p0001.txt") if text is None else text
    reply = folder / "p0001.done.txt"
    ir.write_text(reply, body)
    return reply


@pytest.mark.parametrize("newline", ["\r", "\r\n", "\n"])
@pytest.mark.parametrize("literal", ["keep: yes", "drop: yes", "@@ +ghost sign horizontal", "# literal"])
def test_value_line_endings_never_become_worksheet_actions(chapter, newline, literal):
    doc = ir.load_doc(chapter)
    region = doc["pages"][0]["regions"][0]
    value = "سلام" + newline + literal
    expected = "سلام\n" + literal
    region.update(target_text=value, target_full=value, review=[value])
    region["source_text"] = "Hello" + newline + literal
    ir.save_doc(doc, chapter)
    for _ in range(2):
        reply = write_reply(chapter)
        parsed = replies.parse_worksheet(ir.read_text(reply))
        assert list(parsed) == [region["id"]]
        block = parsed[region["id"]]
        assert block["fa"] == expected
        assert block["fa_full"] == expected
        assert block["note"] == [expected]
        assert "keep" not in block and "drop" not in block
        assert worksheet.merge_document(chapter)["ok"]
        saved = ir.load_doc(chapter)["pages"][0]["regions"][0]
        assert saved["target_text"] == expected
        assert saved["source_text"] == "Hello\n" + literal
        assert not saved.get("keep") and not saved.get("dropped")
        assert worksheet.merge_document(chapter)["unchanged"] == ["p0001"]


@pytest.mark.parametrize("header", ["spech horizontal", "speech sideways"])
@pytest.mark.parametrize("added", [False, True])
def test_invalid_explicit_header_cannot_commit_or_reconcile(chapter, header, added):
    reply = write_reply(chapter)
    text = ir.read_text(reply)
    if added:
        text += f"\n@@ +label {header}\nbox: 100 20 40 20\nsrc: Bye\nfa: خداحافظ\n"
    else:
        text = text.replace("@@ p0001r001 speech horizontal", f"@@ p0001r001 {header}")
    ir.write_text(reply, text)
    before = copy.deepcopy(ir.load_doc(chapter)["pages"][0]["regions"])
    result = worksheet.merge_document(chapter)
    assert not result["ok"] and result["invalid_fields"]
    assert ir.load_doc(chapter)["pages"][0]["regions"] == before
    # Explicit reconciliation must not launder a malformed header.
    with pytest.raises(ValueError):
        worksheet.reconcile_document(chapter, pages=["p0001"])
    assert ir.read_text(reply) == text
    ir.write_text(reply, text.replace(header, "speech horizontal"))
    assert worksheet.merge_document(chapter)["ok"]
    assert worksheet.merge_document(chapter)["unchanged"] == ["p0001"]


@pytest.mark.parametrize("bad", ["false", "true", "no", 0, 1, None, [], {}])
def test_glossary_lock_is_a_boolean_decision_not_truthiness(chapter, bad):
    doc = ir.load_doc(chapter)
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError, match="locked"):
        glossary.set_entry(doc, "Anna", {"target": "آنا", "locked": bad})
    assert doc == before


@pytest.mark.parametrize("field", ["aliases", "target_forms"])
@pytest.mark.parametrize("bad", [None, 17, True, {}, ["nested"]])
def test_glossary_forms_never_stringify_nontext(chapter, field, bad):
    doc = ir.load_doc(chapter)
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError, match=field):
        glossary.set_entry(doc, "Anna", {"target": "آنا", "locked": True,
                                         field: ["valid", bad]})
    assert doc == before


@pytest.mark.parametrize("source", ["", "  ", None, 42])
def test_glossary_source_requires_a_nonempty_text_key(chapter, source):
    doc = ir.load_doc(chapter)
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError, match="source"):
        glossary.set_entry(doc, source, {"target": "آنا"})
    assert doc == before


def test_malformed_glossary_table_preserves_prior_document(chapter):
    table = chapter.parent / "table.json"
    ir.write_text(table, json.dumps({"Anna": "آنا", "Lex": {"target": "لکس", "locked": "false"}}))
    before = chapter.read_bytes()
    with pytest.raises(ValueError, match="locked"):
        glossary.apply_file(chapter, table)
    assert chapter.read_bytes() == before
    ir.write_text(table, json.dumps({"Anna": "آنا", "Lex": {"target": "لکس", "locked": False}}))
    assert glossary.apply_file(chapter, table)["applied"] == 2
    doc = ir.load_doc(chapter)
    assert "Anna" in chapter_context.build(doc, "p0001")["constraints"]["glossary"]
    assert "Lex" not in chapter_context.build(doc, "p0001")["constraints"]["glossary"]


def test_legacy_nontext_forms_are_not_binding_context(chapter):
    doc = ir.load_doc(chapter)
    doc["glossary"] = {"entries": {"Anna": {"target": "آنا", "locked": True,
                        "aliases": [None, 17, {}, "Ann"], "target_forms": [True, [], "آنای"]}}}
    assert glossary.forms("Anna", doc["glossary"]["entries"]["Anna"]) == ["Anna", "Ann"]
    assert glossary.target_forms(doc["glossary"]["entries"]["Anna"]) == ["آنا", "آنای"]
    constraint = chapter_context.build(doc, "p0001")["constraints"]["glossary"]["Anna"]
    assert constraint["source_aliases"] == ["Ann"]
    assert constraint["forms"] == ["آنای"]


def test_dropped_regions_do_not_consume_next_dialogue_budget(chapter):
    doc = ir.load_doc(chapter)
    page = ir.new_page("p0002", 1, "second.png", 240, 160, "1" * 64)
    for i in range(chapter_context.MAX_NEXT + 2):
        region = ir.new_region(f"p0002r{i:03d}", [0, 0, 10, 10], kind="speech")
        region.update(dropped=True, source_text="discarded")
        page["regions"].append(region)
    for i in range(chapter_context.MAX_NEXT + 1):
        region = ir.new_region(f"p0002r{100+i:03d}", [0, 0, 10, 10], kind="speech")
        region["source_text"] = f"Continuation {i}"
        page["regions"].append(region)
    doc["pages"].append(page)
    following = chapter_context.build(doc, "p0001")["context"]["next_page"]
    assert len(following) == chapter_context.MAX_NEXT
    assert [item["source"] for item in following] == [f"Continuation {i}" for i in range(chapter_context.MAX_NEXT)]


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None, [], {}])
@pytest.mark.parametrize("reader", ["context", "worksheet", "check"])
def test_invalid_legacy_approval_never_becomes_a_binding_decision(chapter, bad, reader):
    import sheet

    doc = ir.load_doc(chapter)
    doc["glossary"] = {"entries": {"Anna": {"target": "آنا", "locked": bad}}}
    ir.save_doc(doc, chapter)
    with pytest.raises(ValueError, match="locked"):
        if reader == "context":
            chapter_context.build(doc, "p0001")
        elif reader == "worksheet":
            sheet.page_worksheet(doc, doc["pages"][0], ir.page_fingerprint(doc["pages"][0]))
        else:
            glossary.check(chapter)
    # An explicit valid decision repairs the record without rewriting dialogue.
    glossary.set_entry(doc, "Anna", {"locked": False})
    ir.save_doc(doc, chapter)
    assert glossary.check(chapter)["ok"]
    assert "Anna" not in chapter_context.build(doc, "p0001")["constraints"]["glossary"]


@pytest.mark.parametrize("field,key", [("propose", "proposed"), ("reviewed", "review_ack")])
@pytest.mark.parametrize("newline", ["\r", "\r\n", "\n"])
def test_dynamic_metadata_cannot_emit_new_worksheet_actions(chapter, field, key, newline):
    doc = ir.load_doc(chapter)
    region = doc["pages"][0]["regions"][0]
    value = "literal" + newline + "keep: yes"
    region[key] = [value]
    ir.save_doc(doc, chapter)
    reply = write_reply(chapter)
    block = replies.parse_worksheet(ir.read_text(reply))[region["id"]]
    assert block[field] == "literal\nkeep: yes"
    assert "keep" not in block
    assert worksheet.merge_document(chapter)["ok"]
    saved = ir.load_doc(chapter)["pages"][0]["regions"][0]
    assert saved["target_text"] == "سلام"
    assert not saved.get("keep")
    assert worksheet.merge_document(chapter)["unchanged"] == ["p0001"]
