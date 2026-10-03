"""A carried review is evidence for old wording, not a fresh decision."""

import copy
import logging

import pytest
from PIL import Image

import falint
import pageir as ir
import qa
import replies
import worksheet

LOG = logging.getLogger(__name__)


@pytest.fixture
def reviewed_page(tmp_path):
    image = tmp_path / "page.png"
    Image.new("RGB", (120, 80), "white").save(image)
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, image.name, 120, 80, ir.sha256_file(image))
    region = ir.new_region("p0001r001", [10, 10, 60, 30], kind="speech")
    region.update(source_text="They drank sweet wine.", target_text="می شیرین را نوشید.",
                  reading_order=1, locked=True)
    falint.record_acknowledgement(region, ["zwnj-review"], region["target_text"])
    page["regions"] = [region]
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    LOG.info("Created a minimal reviewed worksheet fixture")
    return path


def _reply(path, edit=lambda text: text):
    worksheet.build_document(path)
    folder = path.parent / "worksheets"
    text = edit(ir.read_text(folder / "p0001.txt"))
    ir.write_text(folder / "p0001.done.txt", text)
    assert worksheet.merge_document(path)["ok"]
    return ir.load_doc(path)["pages"][0]["regions"][0]


def test_carried_review_does_not_approve_edited_worksheet(reviewed_page):
    saved = _reply(reviewed_page, lambda text: text.replace("می شیرین را نوشید.", "می روم خانه."))
    assert any(item["code"] == "zwnj-review" for item in falint.lint_region(saved))
    assert falint.lint_document(reviewed_page)["by_code"]["zwnj-review"] == 1
    findings = qa.check_document(reviewed_page, limit=None)["findings"]
    assert any(item["code"] == "typography" and "zwnj-review" in item["detail"]
               for item in findings)
    assert saved["target_text"] == "می روم خانه."
    assert saved["review_ack_history"][0]["codes"] == ["zwnj-review"]
    assert saved["review_ack_history"][0]["spans"] == ["می شیرین"]


@pytest.mark.parametrize("field,value", [("source_text", "They did not drink wine."),
                                         ("source_revision", 2),
                                         ("target_text", "می روم خانه.")])
def test_direct_edit_reopens_review_before_and_after_rebuild(reviewed_page, field, value):
    doc = ir.load_doc(reviewed_page)
    region = doc["pages"][0]["regions"][0]
    region[field] = value
    ir.save_doc(doc, reviewed_page)
    assert not falint.settled(region, "zwnj-review")
    assert any(item["code"] == "zwnj-review" for item in falint.lint_region(region))
    saved = _reply(reviewed_page)
    assert not falint.settled(saved, "zwnj-review")


def test_source_only_worksheet_edit_needs_new_review(reviewed_page):
    saved = _reply(reviewed_page, lambda t: t.replace("They drank sweet wine.", "Do not drink wine."))
    assert not falint.settled(saved, "zwnj-review")


def test_explicit_reapproval_preserves_history_and_repeats(reviewed_page):
    original = copy.deepcopy(ir.load_doc(reviewed_page)["pages"][0]["regions"][0])
    def edit(text):
        text = text.replace("می شیرین را نوشید.", "می روم خانه.")
        return "\n".join("reviewed: zwnj-review" if line.startswith("reviewed:") else line
                         for line in text.splitlines()) + "\n"
    saved = _reply(reviewed_page, edit)
    assert falint.settled(saved, "zwnj-review")
    assert saved["review_ack_history"][0]["spans"] == original["review_ack_spans"]
    history = copy.deepcopy(saved["review_ack_history"])
    saved = _reply(reviewed_page)
    assert falint.settled(saved, "zwnj-review") and saved["review_ack_history"] == history
    assert worksheet.merge_document(reviewed_page)["unchanged"] == ["p0001"]


@pytest.mark.parametrize("text", ["می شیرین را نوشید.", "می روم خانه."])
def test_legacy_span_review_only_carries_covered_words(reviewed_page, text):
    doc = ir.load_doc(reviewed_page)
    region = doc["pages"][0]["regions"][0]
    region.pop("review_ack_text", None)
    region["target_text"] = text
    ir.save_doc(doc, reviewed_page)
    rendered = worksheet.page_worksheet(doc, doc["pages"][0], ir.page_fingerprint(doc["pages"][0]))
    block = replies.parse_worksheet(rendered)[region["id"]]
    assert ("zwnj-review" in block.get("reviewed", "")) == (text == "می شیرین را نوشید.")


def test_stale_legacy_carry_withdraws_approval_and_keeps_history(reviewed_page):
    doc = ir.load_doc(reviewed_page)
    region = doc["pages"][0]["regions"][0]
    region.pop("review_ack_text", None)
    ir.save_doc(doc, reviewed_page)
    saved = _reply(reviewed_page, lambda t: t.replace("They drank sweet wine.", "Do not drink wine."))
    assert not falint.settled(saved, "zwnj-review")
    assert any(item["code"] == "zwnj-review" for item in falint.lint_region(saved))
    assert saved["review_ack_history"][0]["codes"] == ["zwnj-review"]
    assert saved["review_ack_history"][0]["spans"] == ["می شیرین"]


@pytest.mark.parametrize("code,text,new", [
    ("arabic-forms", "ببين", "ببين اين"),
    ("guillemets", "«سلام", "«خداحافظ"),
    ("latin-quotes", '"سلام', '"خداحافظ'),
    ("double-punctuation", "سلام،،", "خداحافظ،،"),
    ("script-collision", "سلامBob", "خداحافظBob"),
    ("untranslated", "Hello friend", "Goodbye friend"),
    ("source-script-left", "سلام 日", "سلام 月"),
])
def test_all_known_lint_decisions_bind_exact_text(code, text, new):
    region = ir.new_region("p0001r001", [1, 1, 20, 20], kind="speech")
    region.update(source_text="Original", target_text=text)
    falint.record_acknowledgement(region, [code], text)
    assert falint.settled(region, code)
    region["target_text"] = new
    assert not falint.settled(region, code)
    assert any(item["code"] == code for item in falint.lint_region(region))
