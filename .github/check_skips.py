"""Fail the job when a test skipped for a reason nobody has agreed to.

A skip is a test that did not run. Reading the final pytest summary line for
the word "passed" cannot tell "all green" from "half of it was skipped on this
runner", and a test that quietly stops running is indistinguishable from one
that never existed.

So: every skip this project accepts is named below, with the runner it is
acceptable on and why. Anything else fails.

    python .github/check_skips.py junit.xml
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

#: `(pattern the skip message must match, where it is allowed, why)`.
#: `where` is a set of `RUNNER_OS` values, or `None` for any runner.
ALLOWED: list[tuple[str, set[str] | None, str]] = [
    (r"\brarfile\b|\bunrar\b|\bbsdtar\b|RAR",
     {"Windows", "macOS"},
     "no RAR backend on this runner; Linux installs one and must not skip"),
    (r"\bpymupdf\b|\bPyMuPDF\b",
     None,
     "PDF support is optional for users, so the test states its prerequisite"),
    (r"CJK font|MS Gothic|Noto Sans CJK|\bcjk\b",
     None,
     "the Japanese fixture needs a CJK face the runner may not carry"),
    (r"no RAQM|\braqm\b",
     None,
     "Pillow may ship a wheel without libraqm, and the `pipeline` job warns "
     "about that rather than failing — the two must not disagree"),
    (r"arabic_reshaper|python-bidi|\bbidi\b",
     None,
     "the shaping fallback's own dependencies are optional"),
    (r"typesetting stack is not importable",
     None,
     "the evaluation scorer runs without the pipeline installed"),
    (r"only one maskable region|no translated region to correct",
     None,
     "the fixture does not carry the shape this test needs"),
    (r"\bPATH\b",
     {"Windows"},
     "two tests need one directory on PATH that a bare Windows shell lacks"),
]


def offenders(path: Path, runner: str) -> list[tuple[str, str]]:
    root = ElementTree.parse(path).getroot()
    bad: list[tuple[str, str]] = []
    for case in root.iter("testcase"):
        for skipped in case.findall("skipped"):
            message = (skipped.get("message") or "") + " " + (skipped.text or "")
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            for pattern, where, _why in ALLOWED:
                if not re.search(pattern, message, re.I):
                    continue
                if where is None or runner in where:
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
    bad = offenders(path, runner)
    total = sum(len(case.findall("skipped"))
                for case in ElementTree.parse(path).getroot().iter("testcase"))
    print(f"{total} skip(s) on {runner}; {len(bad)} not on the allowlist")
    for name, message in bad:
        print(f"::error::unexpected skip on {runner}: {name} — {message}")
    if bad:
        print("Add it to ALLOWED in .github/check_skips.py with the reason, or "
              "fix the runner so the test can run.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
