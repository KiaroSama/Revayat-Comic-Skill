"""Score a set of Persian renderings against `cases.json`, axis by axis.

Two rules decide the shape of this file.

**No single number.** Adequacy and fluency pull against each other: a fluent
Persian sentence that says something else scores well on exactly one axis and
should fail. Averaging them hides the trade-off that matters, so nothing here
produces an overall score and `--json` has no field for one.

**The machine scores only what a machine can check.** Negation, numbers,
required terms, an ellipsis, semantic-unit count and whether the line fits the
balloon are all decidable. Adequacy in full, fluency and voice consistency are
not, and a model's opinion of its own work is not evidence — so those axes come
back `null` with the question a person has to answer. A case marked
`human_only` is not machine-scored at all.

    python evaluation/score.py --answers my-answers.json
    python evaluation/score.py --answers my-answers.json --json

`--answers` is `{"case-id": "the Persian"}`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"

#: Persian negation is a prefix on the verb: `نـ` or `نمی‌`. Checked as a
#: prefix on a word, not as a bare letter, because `ن` starts many words that
#: negate nothing.
NEGATION = re.compile(r"(?:^|\s)(?:نمی|نَمی|ن)[ء-ۿ‌]{2,}")
#: Persian and ASCII digits, so a rendering may use either.
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ELLIPSIS = re.compile(r"(?:…|\.{2,})")
#: A semantic unit boundary in Persian: sentence enders and the comma that
#: joins two clauses. A crude count, and it is only ever compared with the
#: case's own number as a "did a unit go missing" signal, never as a target.
UNIT = re.compile(r"[.!?؟؛،…]+")

AXES = ("adequacy", "fluency", "voice", "omissions_additions", "visual_fit")


def load_cases(path: Path = CASES) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["cases"]


def _digits_in(text: str) -> set[str]:
    return set(re.findall(r"\d+", text.translate(DIGITS)))


def _units(text: str) -> int:
    return len([piece for piece in UNIT.split(text) if piece.strip()]) or 1


def check_preserved(case: dict, answer: str) -> dict[str, object]:
    """The machine-decidable half of adequacy, item by item."""
    wanted = case.get("must_preserve") or {}
    out: dict[str, object] = {}
    if wanted.get("negation"):
        out["negation"] = bool(NEGATION.search(answer))
    if wanted.get("numbers"):
        # Each entry is one number, given as the spellings that count for it.
        # `"سه و ربع"` is 3:15 and `"ساعت ۳:۱۵"` is 3:15, and no rule this file
        # could carry knows that — so the case says so, where a person wrote it.
        present = _digits_in(answer)
        missing = []
        for entry in wanted["numbers"]:
            spellings = [entry] if isinstance(entry, str) else list(entry)
            if not any(s in present or s in answer for s in spellings):
                missing.append(spellings[0])
        out["numbers"] = {"missing": missing, "ok": not missing}
    if wanted.get("terms"):
        missing = [t for t in wanted["terms"] if t not in answer]
        out["terms"] = {"missing": missing, "ok": not missing}
    if wanted.get("ellipsis"):
        out["ellipsis"] = bool(ELLIPSIS.search(answer))
    if wanted.get("contrastive_subject"):
        # The subject is what makes the line contrastive; Persian drops it
        # freely, so its ABSENCE here is the failure.
        out["contrastive_subject"] = bool(re.search(r"(?:^|\s)من(?:\s|$)", answer))
    return out


def fits(case: dict, answer: str, *, page=(1000, 1500)) -> object:
    """Whether the line sets inside this case's balloon, measured by the real
    fitter. ``None`` when the typesetting stack is not installed."""
    sys.path.insert(0, str(HERE.parent / "skills" / "revayat-comic" / "scripts"))
    try:
        import numpy as np
        import typeset
        from PIL import Image, ImageDraw
    except Exception:
        return None

    width = int(page[0] * case["balloon"][0])
    height = int(page[1] * case["balloon"][1])
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, width - 1, height - 1], fill=255)
    canvas = ImageDraw.Draw(Image.new("RGB", (width, height), "white"))
    try:
        fitted = typeset.fit_region(
            canvas, answer, np.asarray(mask), np, typeset.Shaper(),
            typeset.find_font(), max_size=48, min_size=13)
    except Exception:
        return None
    return fitted is not None


def score_one(case: dict, answer: str) -> dict[str, object]:
    answer = (answer or "").strip()
    human = bool(case.get("human_only"))
    preserved = {} if human else check_preserved(case, answer)
    machine_failed = [name for name, value in preserved.items()
                      if value is False or (isinstance(value, dict)
                                            and not value.get("ok"))]
    units = _units(answer)
    return {
        "case": case["id"],
        "difficulty": case.get("difficulty", []),
        "answered": bool(answer),
        # Two halves, kept apart. A tick here means nothing was lost that a
        # machine can see — never that the translation is adequate.
        "adequacy": {
            "machine_checks": preserved,
            "machine_ok": bool(answer) and not machine_failed,
            "human": None,
            "ask": "does it say what the source says? read both.",
        },
        "fluency": {"human": None,
                    "ask": "is it Persian somebody would actually write?"},
        "voice": {"human": None,
                  "ask": "does this character sound like the same person, and "
                         "unlike the others?"},
        "omissions_additions": {
            "source_units": case.get("units"),
            "answer_units": units,
            # A signal, not a verdict: one Japanese sentence may legitimately
            # become two Persian ones. A gap of more than one is worth a look.
            "flag": (case.get("units") is not None
                     and abs(units - case["units"]) > 1),
            "human": None,
            "ask": "count the clauses that went missing or appeared.",
        },
        "visual_fit": {"fits": fits(case, answer) if answer else None},
        "matches_a_reference": answer in (case.get("accept") or []),
    }


def score(answers: dict[str, str], cases: list[dict] | None = None) -> dict:
    cases = cases if cases is not None else load_cases()
    rows = [score_one(case, answers.get(case["id"], "")) for case in cases]
    return {
        "cases": len(rows),
        "answered": sum(1 for row in rows if row["answered"]),
        # Per axis, and never combined. There is deliberately no total.
        "machine_adequacy_failures": [row["case"] for row in rows
                                      if row["answered"]
                                      and not row["adequacy"]["machine_ok"]],
        "unit_count_flags": [row["case"] for row in rows
                             if row["omissions_additions"]["flag"]],
        "does_not_fit": [row["case"] for row in rows
                         if row["visual_fit"]["fits"] is False],
        "awaiting_human_score": [row["case"] for row in rows
                                 if row["answered"]],
        "rows": rows,
        "note": ("Fluency, voice and adequacy-in-full are not scored here and "
                 "must not be inferred from what is. A model's opinion of its "
                 "own work is not evidence."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--answers", required=True,
                        help='JSON: {"case-id": "the Persian"}')
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    report = score(answers, load_cases(Path(args.cases)))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    print(f"{report['answered']}/{report['cases']} answered")
    for name, key in (("machine adequacy failures", "machine_adequacy_failures"),
                      ("unit-count flags", "unit_count_flags"),
                      ("does not fit the balloon", "does_not_fit")):
        print(f"{name}: {', '.join(report[key]) or 'none'}")
    print(f"\nawaiting a human score on fluency, voice and adequacy: "
          f"{len(report['awaiting_human_score'])} case(s)")
    print(report["note"])
    return 1 if report["machine_adequacy_failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
