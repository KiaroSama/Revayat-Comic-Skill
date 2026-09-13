"""Every stage, in order, through the real CLI, against a generated chapter.

The unit tests call the modules. This calls `revayat-comic.py` the way the skill
tells an agent to, so a break in the dispatcher, in an argument name, in a JSON
report field or in the order the stages depend on each other shows up here even
when every module's own tests still pass. The sibling novel project learned that
the hard way: a worksheet id regex that unit tests were happy with silently
failed to merge across a whole book.

    python tests/e2e_pipeline.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "revayat-comic" / "scripts" / "revayat-comic.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "skills" / "revayat-comic" / "scripts"))

FA = [
    "بس کن! این‌جا چه خبر است؟",
    "هیچ‌کس نمی‌داند او کجا رفته.",
    "دوباره برگشتی؟",
]
SOURCES = ["やめろ！", "誰も知らない。", "また来たのか"]


#: Wall bound for one stage. Every stage here runs in a couple of seconds on a
#: three-page chapter; a stage that takes minutes is hung, and an unbounded wait
#: would hand CI a job that never ends instead of a failure it can read.
STAGE_TIMEOUT = 180


def run(*args: str) -> dict:
    """One stage. Returns its JSON report, or raises with what it printed."""
    import os

    try:
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=STAGE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as expired:
        # TimeoutExpired kills the child, but say which stage and what it had
        # printed: "the pipeline hung" is not an actionable failure.
        raise SystemExit(
            f"FAILED: {' '.join(args[:2])} did not finish in {STAGE_TIMEOUT}s\n"
            f"{(expired.stdout or b'')!r}"
        ) from expired
    if result.returncode != 0:
        raise SystemExit(
            f"FAILED: {' '.join(args[:2])} exited {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"{' '.join(args[:2])} did not print JSON:\n{result.stdout}")


def translate(work: Path) -> int:
    """Stand in for the reader: fill every worksheet with plausible Persian."""
    folder = work / "worksheets"
    filled = 0
    for path in sorted(folder.glob("p*.txt")):
        if path.name.endswith(".done.txt"):
            continue
        out, index = [], 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("src:"):
                out.append(f"src: {SOURCES[index % len(SOURCES)]}")
            elif line.startswith("fa:"):
                out.append(f"fa: {FA[index % len(FA)]}")
                out.append(f"speaker: {'هاروکا' if index % 2 == 0 else 'کنجی'}")
                index += 1
                filled += 1
            else:
                out.append(line)
        (folder / f"{path.stem}.done.txt").write_text(
            "\n".join(out) + "\n", encoding="utf-8", newline=""
        )
    return filled


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise SystemExit(f"FAILED: {label}{(' — ' + detail) if detail else ''}")
    print(f"  ok  {label}")


def main() -> int:
    from tests_support import write_cbz

    with tempfile.TemporaryDirectory(prefix="revayat-comic-e2e-") as scratch:
        base = Path(scratch)
        work, out = base / "work", base / "out"
        source = write_cbz(base / "chapter.cbz", pages=3)
        doc = str(work / "comic.json")

        print("doctor")
        report = run("doctor")
        check("the environment is ready", report["ready"], json.dumps(report["persian"]))
        print(f"  shaping: {report['persian']['shaping']}")

        print("import")
        report = run("import", str(source), "--out", str(work),
                     "--source-language", "ja", "--direction", "rtl")
        check("three pages imported", report["pages"] == 3)

        print("detect")
        report = run("detect", "--doc", doc)
        check("balloons were found", report["totals"]["speech"] >= 6,
              json.dumps(report["totals"]))
        check("panels were found", report["totals"]["panels"] >= 8)

        print("mask")
        regions = sum(page["regions"] for page in run("detect", "--doc", doc)["pages"])
        report = run("mask", "--doc", doc)
        # Every region is accounted for, and NOT every region is masked. A
        # sound effect the policy keeps is artwork: masking it would put
        # artwork inside the area the cleaner may rewrite and inside the
        # denominator the preservation proof divides by.
        masked = report["masks_written"]
        unmasked = sum(page["not_masked"] for page in report["pages"])
        check("every region is masked or explicitly left alone",
              masked + unmasked == regions and masked > 0,
              f"{masked} masked + {unmasked} left alone for {regions} regions")
        check("coverage stays sane", not report["excessive_coverage"])

        print("crops")
        report = run("crops", "--doc", doc)
        check("an overview and a sheet per page",
              all(page["overview"] and page["sheets"] for page in report["pages"]))

        print("worksheet build")
        report = run("worksheet", "build", "--doc", doc)
        check("a worksheet per page", report["count"] == 3)

        print("translate (stand-in for the reader)")
        filled = translate(work)
        check("every region answered", filled > 0, f"{filled} regions")

        print("worksheet merge")
        report = run("worksheet", "merge", "--doc", doc)
        check("everything merged", report["ok"], json.dumps(report))

        print("glossary")
        report = run("glossary", "scan", "--doc", doc)
        check("speakers became candidates", report["entries"] > 0)

        print("falint")
        run("falint", "fix", "--doc", doc)
        check("typography pass is idempotent",
              run("falint", "fix", "--doc", doc)["changed_count"] == 0)

        print("clean")
        report = run("clean", "--doc", doc)
        check("flat balloons were filled, not inpainted",
              report["totals"]["flat"] > 0, json.dumps(report["totals"]))

        print("typeset")
        report = run("typeset", "--doc", doc)
        check("Persian was placed", report["placed"] > 0)
        check("nothing overflowed", not report["overflow"], json.dumps(report["overflow"]))

        print("qa check")
        report = run("qa", "check", "--doc", doc)
        check("the gate passes", report["ok"], json.dumps(report["findings"][:4]))
        check("the artwork is untouched outside the masks",
              report["stats"]["artwork_pixels_changed"] == 0)

        print("export")
        package = out / "chapter-fa.cbz"
        report = run("export", "--doc", doc, "--out", str(package))
        check("three pages exported", report["pages"] == 3)

        print("qa package")
        report = run("qa", "package", "--doc", doc, "--file", str(package))
        check("the package opens and is complete", report["ok"])

        print("export pdf")
        pdf = out / "chapter-fa.pdf"
        run("export", "--doc", doc, "--out", str(pdf))
        check("the PDF is complete",
              run("qa", "package", "--doc", doc, "--file", str(pdf))["ok"])

    print("\nend-to-end pipeline: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
