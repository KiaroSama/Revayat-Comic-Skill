"""Cheap report/config admission mutations; no workflow or target execution."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import test_ci_guards

check_skips = test_ci_guards.check_skips  # Reuse the existing fixture unchanged.

ROOT = Path(__file__).resolve().parents[1]


def runtime_floors(text):
    floors = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([a-zA-Z0-9_.-]+)>=([0-9]+(?:\.[0-9]+)*)", line)
        if not match:
            raise ValueError(f"unsupported runtime requirement: {line}")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in floors:
            raise ValueError(f"duplicate runtime requirement: {name}")
        floors[name] = match[2]
    return floors


def floor_mismatches(requirements, job):
    pins = dict(re.findall(r'"([a-z0-9.-]+)==([0-9.]+)"', job))
    bad = []
    for name, floor in runtime_floors(requirements).items():
        # OpenCV uses a fourth distribution/build component for release 4.8.1.
        expected = "4.8.1.78" if name == "opencv-python-headless" and floor == "4.8.1" else floor
        actual = pins.get(name, "")
        def release(version):
            values = [int(value) for value in version.split(".")] if version else []
            while values and values[-1] == 0:
                values.pop()
            return values
        if not actual or release(actual) != release(expected):
            bad.append(name)
    return bad


def full_suite_problem(job):
    # Inspect the WHOLE full-suite job: a Python argument array can put its
    # selector on another line. Remove only module-launch syntax, not selectors.
    if not re.search(r'pytest["\']?\s*(?:,\s*["\']|\s+)tests(?:["\']|\s)', job):
        return "full tests directory is not selected"
    text = re.sub(r'\bpython\s+-m\s+[\w.]+|["\']-m["\']\s*,\s*["\']pytest["\']', 'module', job)
    if re.search(r'(?:[\s"\'])(?:-k|-m|--deselect|--ignore(?:-glob)?)(?=[\s"\'=])', text):
        return "full-suite job contains test selection"
    return None


def report(tmp_path, node="test_typeset::test_raqm_shapes_persian_and_agrees_with_the_fallback", message=None):
    from xml.etree.ElementTree import Element, SubElement, ElementTree
    root = Element("testsuites")
    case = SubElement(SubElement(root, "testsuite"), "testcase", classname=node.split("::")[0], name=node.split("::")[1])
    if message is not None:
        SubElement(case, "skipped", message=message)
    path = tmp_path / "evidence.xml"
    ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


@pytest.mark.parametrize("job", ["test", "minimum-dependencies", "cbr"])
@pytest.mark.parametrize("node,message", [
    ("test_readers::test_pdf", "could not import pymupdf"),
    ("test_typeset::test_fallback", "could not import arabic_reshaper"),
    ("test_typeset::test_fallback", "could not import bidi"),
    ("test_typeset::test_raqm_shapes_persian_and_agrees_with_the_fallback", "no RAQM"),
    ("test_readers::test_a_real_rar_round_trips", "no unrar backend"),
])
def test_required_linux_capabilities_cannot_skip(tmp_path, check_skips, job, node, message):
    assert check_skips.offenders(report(tmp_path, node, message), "Linux", job)


@pytest.mark.parametrize("runner", ["Windows", "macOS"])
def test_only_named_platform_raqm_skip_is_accepted(tmp_path, check_skips, runner):
    path = report(tmp_path, message="no RAQM in this Pillow")
    assert check_skips.offenders(path, runner, "test") == []
    assert check_skips.offenders(path, runner, "unrelated-job")
    path = report(tmp_path, "test_typeset::test_unrelated", "no RAQM")
    assert check_skips.offenders(path, runner, "test")


@pytest.mark.parametrize("text", ["", "<testsuites/>", "<testsuites><testsuite/></testsuites>", "<testsuites>"])
def test_missing_empty_or_truncated_evidence_fails(tmp_path, check_skips, text):
    path = tmp_path / "bad.xml"
    path.write_text(text, encoding="utf-8")
    assert check_skips.main(["check_skips.py", str(path)]) == 1


def test_real_cbr_evidence_requires_the_real_case(tmp_path, check_skips, monkeypatch):
    monkeypatch.setenv("RUNNER_OS", "Linux")
    monkeypatch.setenv("GITHUB_JOB", "cbr")
    assert check_skips.main(["check_skips.py", str(report(tmp_path, "test_readers::test_the_real_rar_fixture_is_text_and_decodes"))]) == 1
    assert check_skips.main(["check_skips.py", str(report(tmp_path, "test_readers::test_a_real_rar_round_trips"))]) == 0


def test_missing_capability_can_only_skip_in_deliberate_minimal_job(tmp_path, check_skips):
    path = report(tmp_path, "test_readers::test_pdf", "could not import pymupdf")
    assert check_skips.offenders(path, "Linux", "minimal-runtime") == []
    assert check_skips.offenders(path, "Linux", "test")


def test_changed_runtime_floor_cannot_keep_the_old_ci_pin():
    assert floor_mismatches("pillow>=10.1", '"pillow==10.0.0"') == ["pillow"]
    assert floor_mismatches("pillow>=10.0", '"pillow==10.0.0"') == []
    assert floor_mismatches("opencv-python-headless>=4.8.1", '"opencv-python-headless==4.8.1.78"') == []
    assert floor_mismatches("opencv-python-headless>=4.9.0", '"opencv-python-headless==4.8.1.78"')


@pytest.mark.parametrize("selector", ["-k", "-m", "--deselect", "--ignore"])
def test_multiline_argument_arrays_cannot_hide_full_suite_selection(selector):
    job = f'run = [sys.executable, "-m", "pytest", "tests",\n "{selector}", "some-case"]'
    assert full_suite_problem(job) == "full-suite job contains test selection"
    assert full_suite_problem('python -m pytest tests -q --timeout=300\n --junitxml=x.xml') is None


def test_weekly_cbr_has_one_execution_and_retains_its_report():
    text = (ROOT / ".github/workflows/integration.yml").read_text(encoding="utf-8")
    job = text.split("  cbr:", 1)[1].split("  full_resolution:", 1)[0]
    assert job.count("python -m pytest tests/test_readers.py") == 1
    assert '"-m", "pytest"' not in job
    assert "--junitxml=junit-cbr.xml" in job and "check_skips.py junit-cbr.xml" in job
    assert "if: always()" in job and "actions/upload-artifact@" in job
