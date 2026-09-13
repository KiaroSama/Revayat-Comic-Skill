"""The guards CI relies on, tested here rather than only in a workflow run.

A check that lives solely in YAML is a check nobody can run before pushing, and
the first time it is wrong is a red build on someone else's machine.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def check_skips():
    spec = importlib.util.spec_from_file_location(
        "check_skips", ROOT / ".github" / "check_skips.py")
    module = importlib.util.module_from_spec(spec)
    # Registered before it is executed, which is what `importlib` asks for and
    # what a module defining a dataclass requires: `@dataclass` looks its own
    # module up in `sys.modules` to resolve annotations, and finds nothing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _junit(tmp_path: Path, *skips: tuple[str, str],
           suite: str = "tests.test_readers") -> Path:
    """A JUnit report, with the class name pytest really writes.

    `tests.t` was fine while the allowlist matched on the message alone. It
    matches on the NODE now — which test, not merely which words — so the
    fixture has to name a real suite or it is testing a document no runner
    produces.
    """
    cases = "".join(
        f'<testcase classname="{suite}" name="{name}">'
        f'<skipped message="{message}"/></testcase>'
        for name, message in skips)
    path = tmp_path / "junit.xml"
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{cases}'
                    f'</testsuite></testsuites>', encoding="utf-8")
    return path


def test_an_allowed_skip_passes(tmp_path, check_skips):
    report = _junit(tmp_path, ("test_cbr", "could not import rarfile"))
    assert check_skips.offenders(report, "Windows", "test") == []


def test_a_skip_nobody_agreed_to_fails(tmp_path, check_skips):
    """A test that quietly stops running is indistinguishable from one that
    never existed."""
    report = _junit(tmp_path, ("test_something", "not today"))
    bad = check_skips.offenders(report, "Linux", "test")
    assert [name for name, _ in bad] == ["tests.test_readers::test_something"]


def test_a_skip_allowed_elsewhere_is_not_allowed_here(tmp_path, check_skips):
    """Linux installs a RAR backend, so the CBR test skipping there is a
    silent loss of coverage — the whole reason the step exists."""
    report = _junit(tmp_path, ("test_cbr", "could not import rarfile"))
    assert check_skips.offenders(report, "Linux", "test")


def test_a_missing_report_is_a_failure(tmp_path, check_skips):
    assert check_skips.main(["check_skips.py", str(tmp_path / "nope.xml")]) == 1


def test_every_test_file_is_claimed_by_ci():
    """`pytest tests` collects the directory, so a new file is picked up — but
    a file that stops being collected (a syntax error at import, a renamed
    directory) would go quiet. This asserts the directory is what CI runs."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pytest tests" in workflow
    assert "--junitxml=" in workflow, "CI keeps no machine-readable evidence"
    assert "check_skips.py" in workflow, "nothing checks the skips"


def test_ci_keeps_its_evidence_on_failure_too():
    """Artifacts uploaded only on success are artifacts for the runs that
    needed them least."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    block = workflow[workflow.index("Keep the evidence"):]
    assert "if: always()" in block[:400], block[:400]


def test_the_floors_are_tested_as_well_as_the_latest():
    """`pillow>=10.0` is a promise that the project works on Pillow 10, and
    nothing tested it: CI resolved the latest of everything."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "minimum-dependencies:" in workflow
    requirements = (ROOT / "skills" / "revayat-comic"
                    / "requirements.txt").read_text(encoding="utf-8")
    floors = {line.split(">=")[0].strip()
              for line in requirements.splitlines()
              if ">=" in line and not line.strip().startswith("#")}
    job = workflow[workflow.index("minimum-dependencies:"):]
    job = job[:job.index("  pipeline:")]
    for package in ("pillow", "numpy", "opencv-python-headless"):
        assert package in floors, f"{package} lost its floor in requirements"
        assert package in job, f"the floors job does not install {package}"


def test_both_shaping_paths_are_exercised():
    """The reshaper fallback runs everywhere; RAQM only where libraqm and
    FriBiDi are present, and asserting the two differ is what proves the
    forced-fallback flag does anything."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "force_fallback=True" in workflow
    assert 'assert forced.mode == "reshaper"' in workflow


def test_the_rar_comment_matches_what_the_job_does():
    """A comment that describes a skip CI no longer tolerates is worse than no
    comment: it tells the next reader the coverage gap is expected."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    block = workflow[workflow.index("Install a RAR reader") - 900:
                     workflow.index("Install a RAR reader")]
    assert "check_skips" in block or "not allowed" in block.lower(), textwrap.shorten(
        block, 200)


# --- C12: a skip is allowed to ONE test, on ONE runner, in ONE job ----------

def test_the_right_words_in_the_wrong_test_are_not_allowed(tmp_path,
                                                           check_skips):
    """The allowlist matched the message alone, so any test anywhere could skip
    by saying "pymupdf" — and a required rendering or freshness fixture could
    disappear behind words borrowed from an optional dependency."""
    report = _junit(tmp_path, ("test_qa_reports_a_render_older_than_it_shows",
                               "could not import pymupdf"),
                    suite="tests.test_clean_and_qa")

    assert check_skips.offenders(report, "Linux", "test")


def test_a_cjk_skip_is_refused_in_the_lane_that_installs_the_face(tmp_path,
                                                                  check_skips):
    """Linux installs `fonts-noto-cjk` in the `test` and `minimum-dependencies`
    jobs, so a Japanese skip there is a broken runner, not a limitation."""
    report = _junit(tmp_path, ("test_a_vertical_column_is_read",
                               "no CJK font on this runner"),
                    suite="tests.test_japanese")

    assert check_skips.offenders(report, "Linux", "test")
    # And it stays acceptable where the face genuinely is not installed.
    assert check_skips.offenders(report, "macOS", "test") == []


def test_the_scorer_may_only_disown_the_pipeline_where_none_is_installed(
        tmp_path, check_skips):
    report = _junit(tmp_path, ("test_it_fits",
                               "the typesetting stack is not importable"),
                    suite="tests.test_evaluation")

    assert check_skips.offenders(report, "Linux", "test")
    assert check_skips.offenders(report, "Linux", "evaluation") == []


def test_every_allowed_skip_names_a_suite_that_exists(check_skips):
    """A rule for a file nobody has is a rule that cannot fire, and it looks
    exactly like a rule that is working."""
    import re

    names = [path.stem for path in (ROOT / "tests").glob("test_*.py")]
    for rule in check_skips.ALLOWED:
        assert any(re.search(rule.node.split("::")[0], name, re.I)
                   for name in names), rule.node


def test_no_workflow_deselects_part_of_the_suite():
    """The guard the sibling project learned the hard way: its first version
    matched `-m` anywhere on the line and called `python -m pytest` a
    deselection, so it fired on every job and proved nothing. Anchored after
    the word `pytest`."""
    import re

    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "pytest" not in line:
                continue
            after = line.split("pytest", 1)[1]
            assert not re.search(r"(?:^|\s)-m\s", after), (workflow.name, line)
            assert "--deselect" not in after, (workflow.name, line)
            assert "-k " not in after, (workflow.name, line)


def test_the_floors_job_pins_exact_versions_not_patch_series():
    """`==10.0.*` is a patch series: pip resolves it to the newest 10.0.x, so
    the job tested whichever patch happened to be last rather than the floor
    `pillow>=10.0` promises."""
    import re

    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = workflow[workflow.index("minimum-dependencies:"):]
    job = job[:job.index("  pipeline:")]
    series = re.findall(r'"([a-z0-9_.-]+)==([0-9]+(?:\.[0-9]+)*)\.\*"', job)

    assert not series, f"still pinned to a patch series: {series}"
    for package in ("pillow", "numpy", "opencv-python-headless", "pymupdf"):
        assert re.search(rf'"{re.escape(package)}==[0-9]+\.[0-9]+', job), package
    # And the evidence of what actually resolved is kept.
    assert "floor-versions.txt" in job


def test_the_required_lane_asserts_its_own_capabilities():
    """A lane that installs a face and never checks it is a lane that silently
    stops installing it."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "fonts-noto-cjk" in workflow
    assert 'features.check(' in workflow and "RAQM" in workflow
