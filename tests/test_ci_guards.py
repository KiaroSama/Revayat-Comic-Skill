"""The guards CI relies on, tested here rather than only in a workflow run.

A check that lives solely in YAML is a check nobody can run before pushing, and
the first time it is wrong is a red build on someone else's machine.
"""

from __future__ import annotations

import importlib.util
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
    spec.loader.exec_module(module)
    return module


def _junit(tmp_path: Path, *skips: tuple[str, str]) -> Path:
    cases = "".join(
        f'<testcase classname="tests.t" name="{name}">'
        f'<skipped message="{message}"/></testcase>'
        for name, message in skips)
    path = tmp_path / "junit.xml"
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{cases}'
                    f'</testsuite></testsuites>', encoding="utf-8")
    return path


def test_an_allowed_skip_passes(tmp_path, check_skips):
    report = _junit(tmp_path, ("test_cbr", "could not import rarfile"))
    assert check_skips.offenders(report, "Windows") == []


def test_a_skip_nobody_agreed_to_fails(tmp_path, check_skips):
    """A test that quietly stops running is indistinguishable from one that
    never existed."""
    report = _junit(tmp_path, ("test_something", "not today"))
    bad = check_skips.offenders(report, "Linux")
    assert [name for name, _ in bad] == ["tests.t::test_something"]


def test_a_skip_allowed_elsewhere_is_not_allowed_here(tmp_path, check_skips):
    """Linux installs a RAR backend, so the CBR test skipping there is a
    silent loss of coverage — the whole reason the step exists."""
    report = _junit(tmp_path, ("test_cbr", "could not import rarfile"))
    assert check_skips.offenders(report, "Linux")


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
