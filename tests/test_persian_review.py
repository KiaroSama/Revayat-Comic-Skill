"""Small approval and source-aware Persian review contracts."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

import glossary
import pageir as ir

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_glossary_mutation_requires_an_explicit_boolean_repair():
    doc = ir.new_doc(source_language="en")
    doc["glossary"] = {"entries": {"Anna": {"target": "آنا", "locked": "false"}}}
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError, match="locked"):
        glossary.set_entry(doc, "Anna", {"target": "اَنا"})
    assert doc == before
    outcome = glossary.set_entry(doc, "Anna", {"target": "اَنا", "locked": False})
    entry = doc["glossary"]["entries"]["Anna"]
    assert outcome["was_locked"] is False
    assert entry["locked"] is False and entry["target"] == "اَنا"
    assert not entry.get("previous")


def test_source_aware_review_has_a_shipped_on_demand_route():
    skill = ROOT / "skills/revayat-comic"
    guide = skill / "references/persian-review.md"
    assert guide.is_file()
    assert "references/persian-review.md" in (skill / "SKILL.md").read_text(encoding="utf-8")
    assert "persian-review.md" in (skill / "references/translation-policy.md").read_text(encoding="utf-8")
    text = guide.read_text(encoding="utf-8")
    for contract in ("Persian-only", "source comparison", "suggestions", "region", "locked"):
        assert contract in text


def test_original_persian_review_controls_do_not_invent_semantic_scores(monkeypatch):
    spec = importlib.util.spec_from_file_location("persian_review_score", ROOT / "evaluation/score.py")
    score = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(score)
    cases = json.loads((ROOT / "evaluation/cases.json").read_text(encoding="utf-8"))["cases"]
    added = [case for case in cases if case["id"].startswith("review-")]
    assert len(added) == 4
    monkeypatch.setattr(score, "fits", lambda *_args, **_kwargs: None)
    for case in added:
        assert case["context"] and case["human_note"] and len(case["accept"]) >= 2
        for answer in case["accept"]:
            checks = score.check_preserved(case, answer)
            if case.get("human_only"):
                assert checks == {}
            else:
                assert all(value.get("ok") if isinstance(value, dict) else value
                           for value in checks.values())
            row = score.score_one(case, answer)
            assert row["context"] == case["context"]
            for axis in ("adequacy", "fluency", "voice", "omissions_additions"):
                assert row[axis]["human"] is None
        wrong = score.score_one(case, case["wrong"])
        if case.get("human_only"):
            assert wrong["adequacy"]["human"] is None
            assert wrong["adequacy"]["machine_checks"] == {}
        else:
            assert not wrong["adequacy"]["machine_ok"]
