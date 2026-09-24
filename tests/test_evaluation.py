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
        assert case["language"] in {"ja", "ko", "zh", "en", "fr", "es"}
        assert 0 < case["balloon"][0] < 1 and 0 < case["balloon"][1] < 1


def test_the_taxonomy_is_covered(cases):
    """The cases exist to cover the difficulties, not to make a round number."""
    tags = {tag for case in cases for tag in case["difficulty"]}
    for wanted in ("plot-critical-negation", "numeric-only-text", "sarcasm",
                   "omitted-subject", "ambiguous-pronoun", "interrupted-balloon",
                   "ellipsis", "names", "honorifics", "tu-vous"):
        assert wanted in tags, f"nothing exercises {wanted}"


def test_all_six_source_languages_appear(cases):
    assert {case["language"] for case in cases} == {"ja", "ko", "zh", "en", "fr", "es"}


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
        assert row["omissions_additions"]["human"] is None
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
    for case in cases:
        task = json.loads((tmp_path / f"{case['id']}.input.json").read_text(encoding="utf-8"))
        assert task["id"] == case["id"]
        assert task["source"] == case["source"]
        assert task["language"] == case["language"]
        assert task.get("context", "") == case.get("context", "")
        for relationship in ("continues_into", "continues_from"):
            assert task.get(relationship) == case.get(relationship)
        for answer_key in ("accept", "gloss", "human_note", "must_preserve"):
            assert answer_key not in task, "reference material leaked into translator input"


def test_the_set_says_where_its_lines_came_from():
    """A set nobody can share is a set nobody can check, and a set whose
    provenance is unstated is worse."""
    payload = json.loads((EVALUATION / "cases.json").read_text(encoding="utf-8"))
    assert "not taken from any published comic" in payload["note"]
    readme = (EVALUATION / "README.md").read_text(encoding="utf-8")
    assert "rights-clean by construction" in readme
    assert "no overall score" in readme.lower()


# --- C11: what the scorer may decide, and what it may not -------------------

def test_a_name_beginning_with_nun_is_not_evidence_of_negation(score):
    """`نادر آمد.` is *Nader came*, an affirmative sentence about a man. The
    bare `ن`-prefix heuristic read it as a preserved negation."""
    checked = score.check_preserved({"must_preserve": {"negation": True}},
                                    "نادر آمد.")

    assert checked["negation"] == "review"


@pytest.mark.parametrize("answer", [
    "نمی‌آیم.", "نه، نمی‌شود.", "به هیچ وجه.", "هرگز نخواهم رفت.",
])
def test_a_real_negation_is_decided(score, answer):
    checked = score.check_preserved({"must_preserve": {"negation": True}},
                                    answer)

    assert checked["negation"] is True, answer


def test_an_undecidable_check_neither_passes_nor_fails(score):
    row = score.score_one({"id": "x", "must_preserve": {"negation": True}},
                          "نادر آمد.")

    assert row["adequacy"]["needs_review"] == ["negation"]
    assert row["adequacy"]["machine_ok"] is True     # not a failure
    report = score.score({"x": "نادر آمد."},
                         [{"id": "x", "must_preserve": {"negation": True}}])
    assert report["needs_review"] == ["x"]
    assert report["machine_adequacy_failures"] == []


@pytest.mark.parametrize("answer,ok", [
    ("سه نفر دیگر مانده.", False),      # no digit at all, and no spelling
    ("۳ نفر دیگر مانده.", True),
    ("3 نفر دیگر مانده.", True),
    ("۳۰ نفر دیگر مانده.", False),      # THE bug: `30` satisfied `3`
    ("سی نفر دیگر مانده.", False),
])
def test_a_quantity_is_a_token_not_a_substring(score, answer, ok):
    checked = score.check_preserved({"must_preserve": {"numbers": ["3"]}},
                                    answer)

    assert checked["numbers"]["ok"] is ok, answer


def test_a_written_out_spelling_the_case_supplies_still_counts(score):
    checked = score.check_preserved(
        {"must_preserve": {"numbers": [["12.5", "دوازده و نیم"]]}},
        "ساعت دوازده و نیم می‌بینمت.")

    assert checked["numbers"]["ok"] is True


def test_formatting_does_not_change_the_verdict(score, tmp_path, capsys):
    """The same failing evaluation exited 1 as text and 0 as JSON — and a
    machine reading it, which is who asks for JSON, was told it passed."""
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({
        "scheme": "1", "note": "",
        "cases": [{"id": "x", "must_preserve": {"numbers": ["3"]}}],
    }, ensure_ascii=False), encoding="utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"x": "سی تا."}, ensure_ascii=False),
                       encoding="utf-8")

    plain = score.main(["--answers", str(answers), "--cases", str(cases)])
    as_json = score.main(["--answers", str(answers), "--cases", str(cases),
                          "--json"])

    capsys.readouterr()
    assert plain == as_json == 1


def test_complete_mode_fails_on_a_missing_answer(score, tmp_path, capsys):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({
        "scheme": "1", "note": "",
        "cases": [{"id": "x"}, {"id": "y"}],
    }, ensure_ascii=False), encoding="utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"x": "سلام."}, ensure_ascii=False),
                       encoding="utf-8")

    lenient = score.main(["--answers", str(answers), "--cases", str(cases)])
    strict = score.main(["--answers", str(answers), "--cases", str(cases),
                         "--complete"])

    capsys.readouterr()
    assert lenient == 0 and strict == 1


def test_the_case_set_was_extended_not_rebuilt(score):
    cases = score.load_cases()
    ids = [case["id"] for case in cases]

    # The original fifteen and all five adversarial controls remain intact.
    for original in ("neg-01", "neg-02", "num-01", "num-02", "sarc-01",
                     "sub-01", "pron-01", "form-01", "form-02", "cont-01a",
                     "cont-01b", "ell-01", "name-01", "mod-01", "fit-01",
                     "neg-03", "neg-04", "num-03", "num-04", "cont-02"):
        assert original in ids, original
    assert len(cases) == 34
    # And every new one carries more than one acceptable Persian form.
    for case in cases:
        assert len(case.get("accept") or []) >= 2, case["id"]


def test_context_reaches_review_without_automated_semantic_scores(score, cases, monkeypatch):
    contextual = [case for case in cases if case["id"].startswith("ctx-")]
    assert len(contextual) == 14
    for language in ("fr", "es", "ja", "zh", "ko"):
        assert sum(case["language"] == language for case in contextual) >= 2
    monkeypatch.setattr(score, "fits", lambda *_args, **_kwargs: None)
    for case in contextual:
        assert case.get("context") and case.get("human_note")
        assert case.get("human_only") is True
        answer = case["accept"][0]
        row = score.score_one(case, answer)
        assert row["source"] == case["source"] and row["answer"] == answer
        assert row["context"] == case["context"]
        assert row["human_note"] == case["human_note"]
        assert row["adequacy"]["machine_checks"] == {}
        for axis in ("adequacy", "fluency", "voice", "omissions_additions"):
            assert row[axis]["human"] is None


def test_every_adversarial_control_passes_on_its_own_references(score):
    """The controls have to be satisfiable, or they are not controls."""
    cases = {case["id"]: case for case in score.load_cases()}
    for case_id in ("neg-03", "neg-04", "num-03", "num-04", "cont-02"):
        case = cases[case_id]
        for answer in case["accept"]:
            row = score.score_one(case, answer)
            assert row["adequacy"]["machine_ok"], (case_id, answer,
                                                   row["adequacy"])
