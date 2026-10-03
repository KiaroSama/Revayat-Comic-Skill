"""Typography must not reinterpret literal quantities or physical lines."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from PIL import Image

import falint
import pageir as ir
import worksheet


@pytest.fixture
def numeric_page(tmp_path):
    Image.new("RGB", (120, 80), "white").save(tmp_path / "page.png")
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, "page.png", 120, 80, ir.sha256_file(tmp_path / "page.png"))
    region = ir.new_region("p0001r001", [10, 10, 80, 40], kind="speech")
    region.update(source_text="Concentration is 3,14 percent.", target_text="غلظت 3,14 درصد است.", locked=True)
    page["regions"] = [region]
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    return path


def test_document_fix_merge_preserves_quantity(numeric_page):
    before = ir.load_doc(numeric_page)["pages"][0]["regions"][0]["target_text"]
    falint.fix_document(numeric_page)
    assert ir.load_doc(numeric_page)["pages"][0]["regions"][0]["target_text"] == before
    worksheet.build_document(numeric_page)
    folder = numeric_page.parent / "worksheets"
    ir.write_text(folder / "p0001.done.txt", ir.read_text(folder / "p0001.txt"))
    assert worksheet.merge_document(numeric_page)["ok"]
    assert falint.fix_document(numeric_page)["changed_count"] == 0
    target = ir.load_doc(numeric_page)["pages"][0]["regions"][0]["target_text"]
    path = Path(__file__).resolve().parents[1] / "evaluation" / "score.py"
    spec = importlib.util.spec_from_file_location("r11_score", path)
    score = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(score)
    assert score.check_preserved({"must_preserve": {"numbers": ["3,14"]}}, target)["numbers"]["ok"]


@pytest.mark.parametrize("digits", ["persian", "keep"])
@pytest.mark.parametrize("literal", ["3,14", "1,200", "-3,14", "+3.14", "−۳٫۱۴", "٣٫١٤",
    "12:30", "2026/10/04", "2026-10-04", "1/2", ".5", "-.5", ",5", "٫۵",
    "1e-3", "1E+03", "-۱٫۲e-۳", "1,234,567", "1.234,56", "12.5"])
def test_structured_numeric_literal_survives_both_digit_options(literal, digits):
    text = f"مقدار {literal} است."
    fixed = falint.fix_text(text, falint.Options(digits=digits))
    assert fixed == text
    assert falint.fix_text(fixed, falint.Options(digits=digits)) == fixed


@pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"])
def test_physical_blank_lines_remain_logical_lines(ending):
    assert falint.fix_text("سلام" + ending * 2 + "دنیا") == "سلام\n\nدنیا"


def test_ordinary_typography_and_unicode_separators_remain_compatible():
    assert falint.fix_text("سلام, خوبی? او 3 بار گفت.") == "سلام، خوبی؟ او ۳ بار گفت."
    assert falint.fix_text("سلام\x00دنیا") == "سلامدنیا"
    assert falint.fix_text("سلام دنیا") == "سلام دنیا"
    assert falint.fix_text("سلام https://example.test/1,200") == "سلام https://example.test/1,200"
