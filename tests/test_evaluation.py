"""The benchmark and its scorer.

The scorer's whole value is that it refuses to say more than it knows, so most
of what is asserted here is what it declines to claim.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "evaluation"


def _module(name: str):
    spec = importlib.util.spec_from_file_location(
        f"evaluation_{name}", EVALUATION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def score():
    return _module("score")


@pytest.fixture(scope="module")
def cases(score):
    return score.load_cases()


def test_every_case_is_complete(cases):
    """A case without several acceptable renderings measures agreement with one
    reference, not quality."""
    seen = set()
    for case in cases:
        assert case["id"] not in seen, f"duplicate case {case['id']}"
        seen.add(case["id"])
        assert case["source"] and case["gloss"]
        assert case["difficulty"], case["id"]
        assert len(case["accept"]) >= 2, f"{case['id']} has one reference"
        assert case["language"] in {"ja", "ko", "zh", "en"}
        assert 0 < case["balloon"][0] < 1 and 0 < case["balloon"][1] < 1


def test_the_taxonomy_is_covered(cases):
    """The cases exist to cover the difficulties, not to make a round number."""
    tags = {tag for case in cases for tag in case["difficulty"]}
    for wanted in ("plot-critical-negation", "numeric-only-text", "sarcasm",
                   "omitted-subject", "ambiguous-pronoun", "interrupted-balloon",
                   "ellipsis", "names", "honorifics", "tu-vous"):
        assert wanted in tags, f"nothing exercises {wanted}"


def test_all_four_source_languages_appear(cases):
    assert {case["language"] for case in cases} == {"ja", "ko", "zh", "en"}


def test_every_reference_rendering_passes_its_own_checks(score, cases):
    """The set has to be right about itself: a reference that fails the case's
    own machine checks means the case is wrong, not the answer."""
    for case in cases:
        for reference in case["accept"]:
            checks = score.check_preserved(case, reference)
            for name, value in checks.items():
                ok = value.get("ok") if isinstance(value, dict) else value
                assert ok, f"{case['id']}: {reference!r} fails {name}"


def test_a_dropped_negation_is_caught(score, cases):
    """One dropped negation inverts the scene, and it is the thing a machine
    genuinely can see."""
    case = next(c for c in cases if c["id"] == "neg-01")
    assert score.check_preserved(case, "گفتم که می‌روم.")["negation"] is False
    assert score.check_preserved(case, "گفتم که نمی‌روم.")["negation"] is True


def test_a_dropped_number_is_caught(score, cases):
    case = next(c for c in cases if c["id"] == "num-01")
    good = score.check_preserved(case, "ساعت ۳:۱۵، سکوی ۷.")["numbers"]
    assert good["ok"] and not good["missing"]
    # A number spelled out still counts, where the case says which spellings
    # do; a number that is simply gone does not.
    spelled = score.check_preserved(case, "سه و ربع، سکوی هفت.")["numbers"]
    assert spelled["ok"], spelled
    bad = score.check_preserved(case, "همان موقع، همان سکو.")["numbers"]
    assert not bad["ok"] and bad["missing"]


def test_a_missing_locked_name_is_caught(score, cases):
    case = next(c for c in cases if c["id"] == "name-01")
    assert score.check_preserved(case, "او نیامد.")["terms"]["ok"] is False


def test_a_contrastive_subject_that_was_dropped_is_caught(score, cases):
    """Persian drops subjects freely, so *dropping the subject* is not a rule —
    the failure is dropping it where it is the point."""
    case = next(c for c in cases if c["id"] == "sub-01")
    assert score.check_preserved(case, "نگفتم.")["contrastive_subject"] is False
    assert score.check_preserved(case, "من که نگفتم.")["contrastive_subject"] is True


def test_the_human_axes_are_never_invented(score, cases):
    """Fluency, voice and adequacy-in-full are not machine-decidable, and a
    model's opinion of its own work is not evidence."""
    answers = {case["id"]: case["accept"][0] for case in cases}
    report = score.score(answers, cases)
    for row in report["rows"]:
        assert row["fluency"]["human"] is None
        assert row["voice"]["human"] is None
        assert row["adequacy"]["human"] is None
        assert row["fluency"]["ask"] and row["voice"]["ask"]


def test_there_is_no_overall_number(score, cases):
    """Averaging adequacy with fluency hides the trade-off that matters."""
    report = score.score({case["id"]: case["accept"][0] for case in cases},
                         cases)
    for forbidden in ("score", "total", "overall", "average", "percent"):
        assert forbidden not in report, f"{forbidden} is not a thing here"
    assert "rows" in report and report["cases"] == len(cases)


def test_a_human_only_case_is_not_machine_scored(score, cases):
    case = next(c for c in cases if c.get("human_only"))
    row = score.score_one(case, case["accept"][0])
    assert row["adequacy"]["machine_checks"] == {}


def test_an_unanswered_case_is_not_counted_as_passing(score, cases):
    report = score.score({}, cases)
    assert report["answered"] == 0
    assert report["machine_adequacy_failures"] == []
    assert report["awaiting_human_score"] == []


def test_the_fit_axis_uses_the_real_fitter(score, cases):
    """Measured by the pipeline's own `fit_region`, not by counting
    characters — a balloon is not a rectangle and neither is a line of
    Persian."""
    case = next(c for c in cases if c["id"] == "fit-01")
    verdict = score.fits(case, case["accept"][-1])
    if verdict is None:
        pytest.skip("the typesetting stack is not importable here")
    assert verdict is True
    assert score.fits(case, "نه " * 400) is False


def test_a_page_is_drawn_for_every_case(tmp_path, cases):
    """Half the difficult cases are only difficult when you can see the
    drawing."""
    build = _module("build_pages")
    assert build.main(["--out", str(tmp_path)]) == 0
    assert sorted(p.stem for p in tmp_path.glob("*.png")) == sorted(
        case["id"] for case in cases)


def test_the_set_says_where_its_lines_came_from():
    """A set nobody can share is a set nobody can check, and a set whose
    provenance is unstated is worse."""
    payload = json.loads((EVALUATION / "cases.json").read_text(encoding="utf-8"))
    assert "not taken from any published comic" in payload["note"]
    readme = (EVALUATION / "README.md").read_text(encoding="utf-8")
    assert "rights-clean by construction" in readme
    assert "no overall score" in readme.lower()
