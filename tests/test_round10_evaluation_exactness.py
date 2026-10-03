"""Quantity spans and answer-region scope through the public evaluator."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def scorer():
    path = Path(__file__).resolve().parents[1] / "evaluation" / "score.py"
    spec = importlib.util.spec_from_file_location("round10_span_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_numeric_spans_are_not_identifier_fragments(scorer):
    case = {"must_preserve": {"numbers": ["3"]}}
    for answer in ("UART-3", "PORT/3", "v1.2.3", "1.2.3", "item_3", "--3", "1e-3"):
        assert not scorer.check_preserved(case, answer)["numbers"]["ok"], answer
    compound = {"must_preserve": {"numbers": ["12:30"]}}
    assert scorer.check_preserved(compound, "ساعت ۰۱۲ : ۰۳۰٫۰۰")["numbers"]["ok"]
    assert not scorer.check_preserved(compound, "12:30:45")["numbers"]["ok"]


def test_negative_reply_carries_only_answer_region(scorer):
    cases = scorer.load_cases()
    case = next(c for c in cases if c["id"] == "review-negative-reply")
    assert len(cases) == 38 and case["source"] == "I did."
    assert "You didn't send it?" in case["context"]
    assert case["units"] == 1 and case["human_only"] is True
    assert case["accept"] == ["فرستادم.", "چرا، فرستادمش."]
    assert case["wrong"] == "نه، نفرستادم."


@pytest.mark.parametrize("wanted,answer,ok", [
    ("3", "2FA/3", False), ("12", "3D/12", False),
    ("3", "HTTP/3", False), ("3", "A-12/3", False),
    ("3", "v1.2.3", False), ("1.2", "1.2.3", False),
    ("3", "(3)", True), ("-3", "−۰۰۳٫۰۰", True),
    ("12.5", "12.5V", True), ("3", "3:15", True),
    ("12:30", "012:030.00", True), ("1/2", "01 / 02.00", True),
    ("1/2", "01 / 02.01", False), ("12:30", "30:12", False),
    ("12:30", "0:12:30", False), ("12:30", "12:30:45", False),
    ("12:30", "x12:30", False), ("12:30", "clock/12:30", False),
    ("12:30", "12:30_extra", False), ("1/2", "1/2/3", False),
    ("12:30", "12 and 30", False), ("1/2", "1:2", False),
    ("3", "1e+3", False), ("3", "1E-3", False),
    ("ساعت ۳:۱۵", "ساعت 3 : 15", True),
    ("ساعت ۳:۱۵", "ساعت 3:150", False),
    ("12.5 V", "12.5 V", True), ("12.5 V", "12.5 Volt", False),
])
def test_complete_numeric_spans_and_normalized_compounds(scorer, wanted, answer, ok):
    result = scorer.check_preserved({"must_preserve": {"numbers": [wanted]}}, answer)
    assert result["numbers"]["ok"] is ok


def test_generated_negative_reply_input_is_answer_free(scorer, tmp_path, capsys):
    import json
    path = Path(__file__).resolve().parents[1] / "evaluation" / "build_pages.py"
    spec = importlib.util.spec_from_file_location("round10_build_pages", path)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    case = next(c for c in scorer.load_cases() if c["id"] == "review-negative-reply")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [case]}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "pages"
    assert generator.main(["--cases", str(cases), "--out", str(out)]) == 0
    task = json.loads((out / (case["id"] + ".input.json")).read_text(encoding="utf-8"))
    assert set(task) == {"id", "language", "source", "context"}
    assert task["source"] == "I did." and "You didn't send it?" in task["context"]
    assert all(word not in json.dumps(task, ensure_ascii=False) for word in case["accept"])
    assert (out / (case["id"] + ".png")).is_file()
    capsys.readouterr()


def test_explicit_numeric_phrases_and_digit_led_identifiers(scorer):
    for spelling in ("ساعت ۳:۱۵", "12.5 V"):
        assert scorer.check_preserved({"must_preserve": {"numbers": [spelling]}}, spelling)["numbers"]["ok"]
    for wanted, answer in (("3", "2FA/3"), ("12", "3D/12")):
        assert not scorer.check_preserved({"must_preserve": {"numbers": [wanted]}}, answer)["numbers"]["ok"]


def test_protected_version_is_not_longer_identifier(scorer):
    import glossary
    for term, answer in (("HTTP/2", "HTTP/2.1"), ("UART2", "UART2/3")):
        assert not glossary.used(answer, [term])
        assert not scorer.check_preserved({"must_preserve": {"terms": [term]}}, answer)["terms"]["ok"]
    assert glossary.used("HTTP/2.", ["HTTP/2"])
