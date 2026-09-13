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

#: Negation this file is willing to DECIDE: the imperfective negative prefix,
#: and the free negative words. Each of these negates and nothing else is
#: spelled that way.
NEGATION_CERTAIN = re.compile(
    # The imperfective negative prefix, attached to a verb.
    r"(?:^|\s)(?:نمی|نَمی)[ء-ۿ‌]{2,}"
    # A free negative word, whole: `نه` is negation, `نهار` is lunch.
    r"|(?:^|\s)(?:نه|هیچ|هرگز|بدون)(?![ء-ۿ])"
    # And the privative prefix, which is attached by definition.
    r"|(?:^|\s)بی‌[ء-ۿ]{2,}")
#: And negation it can only SUSPECT: a bare `ن` in front of a word. It is the
#: perfective negative prefix — `نرفت`, *he did not go* — and it is also the
#: first letter of an enormous number of ordinary words. `نادر آمد.` is
#: *Nader came*, an affirmative sentence about a man, and it was counted as
#: evidence that the negation had been preserved.
#:
#: A guess is reported for review, never scored.
NEGATION_MAYBE = re.compile(r"(?:^|\s)ن[ء-ۿ‌]{2,}")
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


#: A numeric token: an optional sign, digits, and an optional decimal part.
#: Persian and ASCII digits are normalised first, and `٫` — the Arabic decimal
#: separator — reads as a point.
NUMBER = re.compile(r"[-−+]?\d+(?:[.,]\d+)?")


def _digits_in(text: str) -> set[str]:
    """Every numeric token in the line, normalised.

    Whole tokens, because membership was tested with `in` against the raw
    string as well: a case requiring `3` was satisfied by a line that said
    `30`, which is not the same quantity and is exactly the kind of error this
    axis exists to catch.
    """
    normalised = text.translate(DIGITS).replace("٫", ".")
    return {_canonical_number(token) for token in NUMBER.findall(normalised)}


def _canonical_number(token: str) -> str:
    """`+3`, `3`, `3.0` and `۳` are one quantity; `3` and `30` are two."""
    token = token.replace("−", "-").replace(",", ".").lstrip("+")
    try:
        value = float(token)
    except ValueError:              # pragma: no cover - NUMBER cannot produce it
        return token
    return str(int(value)) if value == int(value) else repr(value)


def _units(text: str) -> int:
    return len([piece for piece in UNIT.split(text) if piece.strip()]) or 1


def check_preserved(case: dict, answer: str) -> dict[str, object]:
    """The machine-decidable half of adequacy, item by item."""
    wanted = case.get("must_preserve") or {}
    out: dict[str, object] = {}
    if wanted.get("negation"):
        if NEGATION_CERTAIN.search(answer):
            out["negation"] = True
        elif NEGATION_MAYBE.search(answer):
            # Neither a pass nor a failure. A word beginning with `ن` may be a
            # negated verb or may be a name; this file cannot tell, and a
            # checker that guesses here is worse than one that asks.
            out["negation"] = "review"
        else:
            out["negation"] = False
    if wanted.get("numbers"):
        # Each entry is one number, given as the spellings that count for it.
        # `"سه و ربع"` is 3:15 and `"ساعت ۳:۱۵"` is 3:15, and no rule this file
        # could carry knows that — so the case says so, where a person wrote it.
        present = _digits_in(answer)
        missing = []
        for entry in wanted["numbers"]:
            spellings = [entry] if isinstance(entry, str) else list(entry)
            found = False
            for spelling in spellings:
                digits = _digits_in(spelling)
                if digits:
                    # A numeric spelling matches a numeric TOKEN. `3` is not
                    # satisfied by `30`, and `۳` and `3` are the same number.
                    found = digits <= present
                else:
                    # A written-out spelling — `سه و ربع` — is a phrase, and a
                    # phrase is matched as text.
                    found = spelling in answer
                if found:
                    break
            if not found:
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
    if not case.get("balloon"):
        # No balloon recorded for this case, so there is nothing to fit it in.
        # Unmeasured, which is not the same as "does not fit" — the difference
        # the report keeps under `fit_not_measured`.
        return None
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
    # `"review"` is neither. A check this file cannot decide must not be
    # counted as passed and must not fail the run; it is named so a person
    # looks at it.
    machine_failed = [name for name, value in preserved.items()
                      if value is False or (isinstance(value, dict)
                                            and not value.get("ok"))]
    needs_review = [name for name, value in preserved.items()
                    if value == "review"]
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
            "needs_review": needs_review,
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
        # Named rather than silently absent. An evaluation with four missing
        # answers and no failures reported the same summary as a complete one.
        "unanswered": [row["case"] for row in rows if not row["answered"]],
        "needs_review": [row["case"] for row in rows
                         if row["adequacy"].get("needs_review")],
        "does_not_fit": [row["case"] for row in rows
                         if row["visual_fit"]["fits"] is False],
        # A missing typesetting stack is not a scorer defect and not a failure:
        # the fit could not be measured, and saying which is the difference
        # between "this line does not fit" and "nothing asked".
        "fit_not_measured": [row["case"] for row in rows
                             if row["answered"]
                             and row["visual_fit"]["fits"] is None],
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
    parser.add_argument("--complete", action="store_true",
                        help="require an answer for every case; an unanswered "
                             "one fails the run rather than being skipped")
    args = parser.parse_args(argv)

    answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    report = score(answers, load_cases(Path(args.cases)))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return _status(report, complete=args.complete)

    print(f"{report['answered']}/{report['cases']} answered")
    for name, key in (("machine adequacy failures", "machine_adequacy_failures"),
                      ("unit-count flags", "unit_count_flags"),
                      ("does not fit the balloon", "does_not_fit")):
        print(f"{name}: {', '.join(report[key]) or 'none'}")
    print(f"\nawaiting a human score on fluency, voice and adequacy: "
          f"{len(report['awaiting_human_score'])} case(s)")
    if report["needs_review"]:
        print(f"undecidable, read them: {', '.join(report['needs_review'])}")
    if args.complete and report["unanswered"]:
        print(f"unanswered: {', '.join(report['unanswered'])}")
    print(report["note"])
    return _status(report, complete=args.complete)


def _status(report: dict, *, complete: bool) -> int:
    """One verdict, whatever the output format asked for.

    `--json` returned 0 unconditionally, so the same failing evaluation exited
    1 as text and 0 as JSON — and a machine reading it, which is who asks for
    JSON, was told everything passed.
    """
    if report["machine_adequacy_failures"]:
        return 1
    if complete and report["unanswered"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
