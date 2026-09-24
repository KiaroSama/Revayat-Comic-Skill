"""Content stays content, and malformed glossary input never becomes approval."""

import copy
import logging

import pytest
from PIL import Image

import context as chapter_context
import glossary
import pageir as ir
import replies
import sheet
import worksheet

LOG = logging.getLogger(__name__)


@pytest.fixture
def text_doc(tmp_path):
    image = tmp_path / "original.png"
    Image.new("RGB", (120, 80), "white").save(image)
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, image.name, 120, 80, ir.sha256_file(image))
    region = ir.new_region("p0001r001", [10, 10, 60, 40], kind="speech", confidence=1.0)
    region.update(source_text="Hello", target_text="سلام", reading_order=1, locked=True)
    page["regions"] = [region]
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    LOG.info("Created isolated worksheet fixture")
    return path


@pytest.mark.parametrize("ending", ["\r", "\r\n", "\n"])
@pytest.mark.parametrize("literal", ["keep: yes", "fa: literal", "@@ hidden speech horizontal", "# literal"])
def test_all_physical_endings_escape_value_lines(text_doc, ending, literal):
    expected = "سلام\n" + literal
    doc = ir.load_doc(text_doc)
    region = doc["pages"][0]["regions"][0]
    region["target_text"] = "سلام" + ending + literal
    region["source_text"] = "Hello" + ending + literal
    region["review"] = ["Observation" + ending + literal]
    ir.save_doc(doc, text_doc)
    for _ in range(2):
        worksheet.build_document(text_doc)
        page_text = ir.read_text(text_doc.parent / "worksheets/p0001.txt")
        parsed = replies.parse_worksheet(page_text)
        assert set(parsed) == {region["id"]}
        assert parsed[region["id"]]["fa"] == expected
        assert parsed[region["id"]]["src"] == "Hello\n" + literal
        assert parsed[region["id"]]["note"] == ["Observation\n" + literal]
        assert "keep" not in parsed[region["id"]]
        ir.write_text(text_doc.parent / "worksheets/p0001.done.txt", page_text)
        assert worksheet.merge_document(text_doc)["ok"]
        saved = ir.load_doc(text_doc)["pages"][0]["regions"][0]
        assert saved["target_text"] == expected and not saved.get("keep")


@pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"])
def test_proposed_term_cannot_become_a_worksheet_action(text_doc, ending):
    doc = ir.load_doc(text_doc)
    page = doc["pages"][0]
    page["regions"][0]["proposed"] = ["First" + ending + "keep: yes"]
    rendered = sheet.page_worksheet(doc, page, ir.page_fingerprint(page))
    block = replies.parse_worksheet(rendered)["p0001r001"]
    assert "keep" not in block
    assert block["propose"] == "First\nkeep: yes"


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_glossary_lock_requires_a_boolean_before_any_change(text_doc, value):
    doc = ir.load_doc(text_doc)
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError, match="locked"):
        glossary.set_entry(doc, "Anna", {"target": "آنا", "locked": value})
    assert doc == before


@pytest.mark.parametrize("field", ["aliases", "target_forms"])
@pytest.mark.parametrize("value", [None, 7, True, {}, ["nested"]])
def test_glossary_forms_do_not_coerce_objects_into_spellings(text_doc, field, value):
    before = text_doc.read_bytes()
    table = text_doc.parent / "terms.json"
    ir.write_text(table, ir.dumps({"Valid": "معتبر", "Anna": {"target": "آنا", field: ["valid", value]}}))
    with pytest.raises(ValueError, match=field):
        glossary.apply_file(text_doc, table)
    assert text_doc.read_bytes() == before


def test_legacy_forms_are_read_defensively_by_context_and_qa(text_doc):
    doc = ir.load_doc(text_doc)
    entry = {"target": "آنا", "locked": True, "aliases": [None, 7, "Annie"],
             "target_forms": [True, {}, "آنای"]}
    doc["glossary"] = {"entries": {"Anna": entry}}
    assert glossary.forms("Anna", entry) == ["Anna", "Annie"]
    assert glossary.target_forms(entry) == ["آنا", "آنای"]
    constraint = chapter_context.build(doc, "p0001")["constraints"]["glossary"]["Anna"]
    assert constraint == {"target": "آنا", "source_aliases": ["Annie"], "forms": ["آنای"]}


def test_valid_glossary_unlock_and_clear_remain_supported(text_doc):
    doc = ir.load_doc(text_doc)
    glossary.set_entry(doc, "Anna", {"target": "آنا", "locked": True,
                                     "aliases": ["Annie"], "target_forms": ["آنای"]})
    glossary.set_entry(doc, "Anna", {"locked": False, "aliases": [], "target_forms": []})
    entry = doc["glossary"]["entries"]["Anna"]
    assert entry["locked"] is False
    assert entry["aliases"] == [] and entry["target_forms"] == []
