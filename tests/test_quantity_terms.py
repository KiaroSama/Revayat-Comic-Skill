"""Exact lexical quantities and approved identifiers, not semantic certification."""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

import pytest

import glossary
import pageir as ir

LOG = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def scorer():
    path = Path(__file__).resolve().parents[1] / "evaluation" / "score.py"
    spec = importlib.util.spec_from_file_location("round10_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("wanted,answer", [
    ("9007199254740992", "9007199254740993"),
    ("0.10000000000000001", "0.1"),
    ("12:30", "30:12"), ("12:30", "12 people and 30 boxes"),
    ("12:30", "112:30"), ("12:30", "12:300"),
    ("1/2", "2/1"), ("1/2", "1 and 2"),
    ("3", "30"), ("-3", "3"), ("0.5", "5"),
    ("3", "1e3"), ("3", "1e-3"), ("3", "1e+3"),
])
def test_changed_numeric_spelling_is_not_preserved(scorer, wanted, answer):
    verdict = scorer.check_preserved({"must_preserve": {"numbers": [wanted]}}, answer)
    assert verdict["numbers"] == {"ok": False, "missing": [wanted]}


@pytest.mark.parametrize("wanted,answer", [
    ("3", "+003.000"), ("-3.50", "−۳٫۵۰"), ("0", "-0.000"),
    ("12.5", "۱۲٫۵"), ("12.5", "12.5V"), ("12.5", "۱۲٫۵V"), ("12.5", "١٢٫٥"), ("0.5", ".5"),
    ("12:30", "ساعت ۱۲:۳۰."), ("12:30", "ساعت 12 : 30"),
    ("1/2", "۱/۲"), ("3", "ساعت 3:15"),
])
def test_equivalent_number_formatting_remains_valid(scorer, wanted, answer):
    assert scorer.check_preserved({"must_preserve": {"numbers": [wanted]}}, answer)["numbers"]["ok"]


@pytest.mark.parametrize("length", [400, 5000])
def test_large_written_numbers_compare_without_float_or_integer_limits(scorer, length):
    wanted = "9" * length
    check = {"must_preserve": {"numbers": [wanted]}}
    assert scorer.check_preserved(check, wanted)["numbers"]["ok"]
    assert not scorer.check_preserved(check, wanted[:-1] + "8")["numbers"]["ok"]
    LOG.info("Compared %s-digit literals without changing interpreter limits", length)


@pytest.mark.parametrize("answer,ok", [("سه نفر", True), ("سهیل رسید", False),
                                       ("دوازده و نیم", True), ("سه‌شنبه", False)])
def test_written_alternatives_keep_the_existing_persian_word_contract(scorer, answer, ok):
    # Number words are not inferred from unrelated names or weekday compounds.
    result = scorer.check_preserved({"must_preserve": {"numbers": [["3", "سه", "دوازده و نیم"]]}}, answer)
    assert result["numbers"]["ok"] is ok


@pytest.mark.parametrize("term,answer,ok", [
    ("UART2", "UART20", False), ("UART2", "my_UART2", False),
    ("UART2", "UART2_extra", False), ("UART2", "(UART2)", True),
    ("Section 7", "Section 70", False), ("Section 7", "Section\n7", True),
    ("V", "mV", False), ("V", "12 V", True),
    ("C++", "C+++", False), ("C++", "C++20", False), ("C++", "C++.", True),
    ("HTTP/2", "HTTP/20", False), ("HTTP/2", "HTTP/2.", True),
    ("Ann", "Anna", False), ("Renée", "Renée!", True),
    ("آنا", "آنان", False), ("آنا", "آنا را", True),
    ("هاروکا", "هاروکا نیامد", True), ("猫", "黒猫が来た", True),
])
def test_glossary_and_scorer_share_identifier_boundaries(scorer, term, answer, ok):
    assert glossary.used(answer, [term]) is ok
    assert scorer.check_preserved({"must_preserve": {"terms": [term]}}, answer)["terms"]["ok"] is ok


def test_exact_technical_case_rejects_different_port_or_unit(scorer):
    case = next(c for c in scorer.load_cases() if c["id"] == "review-protected-measurement")
    for answer in ("درگاه UART20 را روی 12.5 V بذار.", "درگاه UART2 را روی 12.5 mV بذار."):
        assert not scorer.check_preserved(case, answer)["terms"]["ok"]
    for answer in case["accept"]:
        assert scorer.check_preserved(case, answer)["terms"]["ok"]


def test_public_glossary_check_and_rename_use_same_boundaries(tmp_path):
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, "page.png", 100, 100, "0" * 64)
    for index, (source, target) in enumerate([
            ("UART2", "UART20"), ("UART2", "UART2"),
            ("UART20", "اشتباه"), ("serial", "UART2")]):
        region = ir.new_region(f"p0001r{index:03d}", [0, 0, 10, 10], kind="speech")
        region.update(source_text=source, target_text=target, locked=True)
        page["regions"].append(region)
    doc["pages"] = [page]
    glossary.set_entry(doc, "UART2", {"target": "UART2", "aliases": ["serial"], "locked": True})
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    assert [v["region"] for v in glossary.check(path)["drift"]] == ["p0001r000"]
    table = tmp_path / "table.json"
    ir.write_text(table, json.dumps({"UART2": {"target": "PORT2"}}))
    report = glossary.apply_file(path, table)
    assert report["needs_review"] == ["p0001r001", "p0001r003"]
    assert ir.load_doc(path)["pages"][0]["regions"] == page["regions"]
    glossary.apply_file(path, table)
    entry = ir.load_doc(path)["glossary"]["entries"]["UART2"]
    assert entry["version"] == 2 and len(entry["previous"]) == 1


@pytest.mark.parametrize("as_json", [False, True])
def test_scorer_cli_returns_failure_for_changed_compound(scorer, tmp_path, capsys, as_json):
    cases = tmp_path / "cases.json"
    answers = tmp_path / "answers.json"
    ir.write_text(cases, json.dumps({"cases": [{"id": "clock", "must_preserve": {"numbers": ["12:30"]}}]}))
    ir.write_text(answers, json.dumps({"clock": "30:12"}))
    args = ["--cases", str(cases), "--answers", str(answers)] + (["--json"] if as_json else [])
    assert scorer.main(args) == 1
    capsys.readouterr()
