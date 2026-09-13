"""Fail the job when a test skipped for a reason nobody has agreed to.

A skip is a test that did not run. Reading the final pytest summary line for
the word "passed" cannot tell "all green" from "half of it was skipped on this
runner", and a test that quietly stops running is indistinguishable from one
that never existed.

So: every skip this project accepts is named below — **which test**, on **which
runner**, in **which job**, and why. A message pattern alone was not enough: it
allowed any test on any runner to skip by saying the right words, so a required
rendering, PDF or freshness fixture could disappear behind "not importable" and
the job stayed green.

    python .github/check_skips.py junit.xml
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Allowed:
    """One skip this project accepts, scoped as narrowly as it is true.

    `node` is matched against `<classname>::<name>` as pytest writes it into
    the JUnit report; it is a regular expression so a parametrised test can be
    named once, and it must name the test — `.*` is not a scope.
    """

    node: str
    message: str
    why: str
    #: `RUNNER_OS` values this is acceptable on. `None` means every runner, and
    #: it has to be justified by a fact about the DEPENDENCY rather than about
    #: the runner: an optional package is optional everywhere.
    runners: set[str] | None = None
    #: `GITHUB_JOB` values. `None` means every job in this workflow.
    jobs: set[str] | None = field(default=None)


#: The CJK faces are installed on Linux by the `tests` and
#: `minimum-dependencies` jobs, so a Japanese skip there is a broken runner.
CJK_JOBS = {"test", "minimum-dependencies"}

ALLOWED: list[Allowed] = [
    Allowed(
        node=r"test_readers.*::test_.*(?:cbr|rar)",
        message=r"\brarfile\b|\bunrar\b|\bbsdtar\b|RAR",
        runners={"Windows", "macOS"},
        why="no RAR backend on this runner; Linux installs one and must not skip",
    ),
    Allowed(
        node=r"test_(?:readers|export_and_glossary|package_identity|resolution)"
             r".*::test_.*",
        message=r"\bpymupdf\b|\bPyMuPDF\b",
        why="PDF support is optional for users, so the test states its "
            "prerequisite — but only these suites may state it",
    ),
    Allowed(
        node=r"test_japanese.*::test_.*",
        message=r"CJK font|MS Gothic|Noto Sans CJK|\bcjk\b",
        runners={"Windows", "macOS"},
        jobs=CJK_JOBS,
        why="the Japanese fixture needs a CJK face; Linux installs one in "
            "these jobs and a skip there is a broken runner, not a limit",
    ),
    Allowed(
        node=r"test_(?:typeset|lettering|ink_envelope).*::test_.*",
        message=r"no RAQM|\braqm\b",
        why="Pillow may ship a wheel without libraqm; the `raqm` step in the "
            "`tests` job asserts it is present on Linux, so a skip here can "
            "only happen where that assertion does not run",
    ),
    Allowed(
        node=r"test_(?:typeset|lettering|typefont).*::test_.*",
        message=r"arabic_reshaper|python-bidi|\bbidi\b",
        why="the shaping fallback's own dependencies are optional",
    ),
    Allowed(
        node=r"test_evaluation.*::test_.*",
        message=r"typesetting stack is not importable",
        jobs={"evaluation"},
        why="the scorer is meant to run without the pipeline installed, and "
            "only the job that installs nothing may say so",
    ),
    Allowed(
        node=r"test_masks.*::test_.*",
        message=r"only one maskable region",
        why="the sample chapter does not always carry two maskable regions on "
            "one page",
    ),
    Allowed(
        node=r"test_(?:server|readers).*::test_.*",
        message=r"\bPATH\b",
        runners={"Windows"},
        why="two tests need one directory on PATH that a bare Windows shell "
            "lacks",
    ),
]


def offenders(path: Path, runner: str, job: str) -> list[tuple[str, str]]:
    root = ElementTree.parse(path).getroot()
    bad: list[tuple[str, str]] = []
    for case in root.iter("testcase"):
        for skipped in case.findall("skipped"):
            message = (skipped.get("message") or "") + " " + (skipped.text or "")
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            for rule in ALLOWED:
                if not re.search(rule.node, name, re.I):
                    continue
                if not re.search(rule.message, message, re.I):
                    continue
                if rule.runners is not None and runner not in rule.runners:
                    continue
                if rule.jobs is not None and job not in rule.jobs:
                    continue
                break
            else:
                bad.append((name, message.strip()[:160]))
    return bad


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"::error::no JUnit report at {path}; the test step did not run")
        return 1

    runner = os.environ.get("RUNNER_OS", "unknown")
    job = os.environ.get("GITHUB_JOB", "unknown")
    bad = offenders(path, runner, job)
    total = sum(len(case.findall("skipped"))
                for case in ElementTree.parse(path).getroot().iter("testcase"))
    print(f"{total} skip(s) on {runner} in job {job}; "
          f"{len(bad)} not on the allowlist")
    for name, message in bad:
        print(f"::error::unexpected skip on {runner}/{job}: {name} — {message}")
    if bad:
        print("Add it to ALLOWED in .github/check_skips.py — naming the test, "
              "the runner and the job — or fix the runner so the test can run.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
