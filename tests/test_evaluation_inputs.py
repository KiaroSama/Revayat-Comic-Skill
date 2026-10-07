"""Custom evaluation admission precedes computation and page output."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1] / "evaluation"
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("evaluation_inputs_score", HERE / "score.py")
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)


@pytest.mark.parametrize("answer", ["من، می‌آیم", "من؟", "من!", "من"])
def test_punctuation_keeps_whole_contrastive_subject(answer):
    case = {"must_preserve": {"contrastive_subject": True}}
    assert scorer.check_preserved(case, answer)["contrastive_subject"]


@pytest.mark.parametrize("answer", ["دشمن", "منزل", "مناره"])
def test_substrings_are_not_contrastive_subject(answer):
    case = {"must_preserve": {"contrastive_subject": True}}
    assert not scorer.check_preserved(case, answer)["contrastive_subject"]


@pytest.mark.parametrize("answers", [None, [], {"one": 4}])
def test_invalid_answers_refuse_before_scoring(answers):
    with pytest.raises(ValueError, match="answers"):
        scorer.score(answers)


@pytest.mark.parametrize("balloon", [[0.0001, 0.1], [float("nan"), 0.2], [0, 0.2], [True, 0.2]])
def test_invalid_drawing_fraction_creates_no_output(tmp_path, balloon):
    import build_pages

    cases = scorer.load_cases()[:2]
    cases[1]["balloon"] = balloon
    source = tmp_path / "cases.json"
    source.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    destination = tmp_path / "pages"
    with pytest.raises(ValueError, match="balloon"):
        build_pages.main(["--cases", str(source), "--out", str(destination)])
    assert not destination.exists()


def test_subpixel_balloon_fit_is_unmeasured_not_a_crash():
    assert scorer.fits({"balloon": [0.0001, 0.1]}, "سلام") is None


def test_unknown_answer_key_is_rejected():
    with pytest.raises(ValueError, match="unknown case IDs"):
        scorer.score({"unknown": "سلام"}, [{"id": "known"}])


def test_optional_null_measurements_remain_unknown():
    report = scorer.score({"x": "سلام"}, [{"id": "x", "units": None,
                                         "must_preserve": None}])
    assert report["rows"][0]["adequacy"]["human"] is None
    assert report["rows"][0]["omissions_additions"]["source_units"] is None
    assert report["machine_adequacy_failures"] == []


@pytest.mark.parametrize("bad_id", ["../escape", "CON", "nul", "COM1", "NEG-01"])
def test_late_invalid_case_writes_no_pages(tmp_path, bad_id):
    import build_pages

    cases = scorer.load_cases()[:2]
    cases[1]["id"] = bad_id
    source = tmp_path / "cases.json"
    source.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    destination = tmp_path / "pages"
    with pytest.raises(ValueError, match="IDs"):
        build_pages.main(["--cases", str(source), "--out", str(destination)])
    assert not destination.exists()
