# The evaluation set

A small benchmark for the one thing this pipeline does not otherwise measure:
whether the Persian is any good.

Every gate the tool has is mechanical. `qa` proves the artwork survived,
`falint` proves the typography is Persian, `glossary check` proves a locked name
did not drift. All three pass on a chapter that reads like a machine wrote it.
`references/evaluation.md` in the skill says what to measure and why; this
folder is the set and the scorer.

## What is here

| | |
| --- | --- |
| `cases.json` | 32 cases across Japanese, Korean, Chinese, English, French and Spanish, each with difficulty tags, a semantic-unit count and **several** Persian candidates. The original 20, including five adversarial controls, are retained. Twelve new context-sensitive cases await bilingual review |
| `build_pages.py` | draws a layout template for each case — two speakers, a balloon, a second balloon for a continuation — and exports its source/context in an answer-free `.input.json` companion |
| `score.py` | scores axis by axis, and refuses to produce one number |

```bash
python evaluation/build_pages.py --out evaluation/pages
python evaluation/score.py --answers my-answers.json
```

`--answers` is `{"case-id": "the Persian"}`. `--json` prints the report and returns the same status the text form does; `--complete` additionally fails when a case has no answer, so an evaluation cannot pass by leaving the hard ones out.

Give the translator both `pages/<id>.png` and `pages/<id>.input.json`. The
template has empty balloons: it is not an OCR fixture. The companion supplies
the source transcription, language, explicit scene/prior-dialogue context and
any continuation IDs. It deliberately omits the gloss, candidate answers,
mechanical expectations and human review notes. Do not give the translator the
reference-bearing `cases.json` while collecting benchmark answers.

The JSON score report carries source, submitted answer, context and human note
into each row so a reviewer can judge the actual scene. A CLI exit of zero,
`machine_ok`, or `matches_a_reference` is never semantic approval.

## Context-sensitive expansion

| Added cases | What needs a reader |
| --- | --- |
| `ctx-fr-01`–`ctx-fr-03` | Lack of obligation versus prohibition, a requested `vous`/`tu` transition, and expletive `ne` in a before-clause |
| `ctx-es-01`–`ctx-es-03` | Optional printing, familiar Mexican plural `ustedes`, and a prohibition with no gloves exception |
| `ctx-ja-01`–`ctx-ja-02` | First-person responsibility recovered from prior dialogue; a polite promise to consider without inventing acceptance |
| `ctx-zh-01`–`ctx-zh-02` | Negation scope and relationship stance; a delayed return known only by hearsay |
| `ctx-ko-01`–`ctx-ko-02` | Direct kinship address with established family voice; an unconfirmed date that is neither settled nor cancelled |

All twelve have explicit context, a human review note, and `human_only: true`.
Their wording differs from the research/prompt examples. Their Persian
candidates are authored proposals, not human-validated gold translations.
Adequacy, fluency, voice and omissions/additions stay `null` until a person
scores them. The total language distribution is 16 Japanese, 4 Korean,
4 Chinese, 2 English, 3 French and 3 Spanish cases.

A check the scorer cannot decide is reported as `review` rather than scored: a
Persian word beginning with `ن` may be a negated verb or may be a name, and
guessing there is how `نادر آمد.` — *Nader came* — was counted as a preserved
negation.

## What this set is, and what it is not

**The source lines were written for this set.** They are not taken from any
published comic, which is what makes the set shareable, and it is also its
limit: they are clean, short, and chosen to isolate one difficulty each. A real
page mixes five of them in a balloon that is the wrong shape.

**The pages are generated.** That is rights-clean by construction, and it means
they are not scans. No screentone, no scanner noise floor, no letterer's hand,
no page that was printed badly in 1998. What they do carry is the structure the
taxonomy mostly turns on — who is speaking, who they are speaking to, a
sentence that continues into the next balloon.

**So the set measures translation, not the pipeline end to end.** It says
nothing about detection on a real scan, and a good score here is not evidence
that a chapter of a real book came out well.

## Adding pages you have the right to share

Put the image in `pages/` and add a `"page": "pages/<name>.png"` field to the
case. Rights matter: your own work, public domain, a Creative Commons release,
or pages the rights holder has given you in writing for this purpose.
Publisher scans are not cleared by being easy to download, and a set you cannot
show anybody is a set nobody can check.

## Why there is no overall score

Adequacy and fluency pull against each other. A fluent Persian sentence that
says something else scores well on exactly one axis and should fail; averaging
them hides the trade-off that matters. `score.py` has no field for a total and
will not grow one.

The scorer checks limited textual signals: selected negation forms, numbers,
required terms, an ellipsis and a contrastive subject. Its unit count is an
approximation. It also measures whether the line sets inside the balloon with
the pipeline's real fitter. None of these establishes full semantic fidelity.
Adequacy in full, fluency and voice consistency come back `null` with the
question a person has to answer. A case tagged `human_only` has no machine
adequacy checks; layout fit and approximate unit-count warnings can still be
reported separately.

**A second model may advise. It may not certify.** A model's opinion of its own
work is not evidence, and neither is a regex pass rate.

## Reading the result

- Machine adequacy failing while fluency reads well is the translation drifting
  into paraphrase. That is the failure this project exists to avoid.
- Failures clustering on one difficulty tag means the fix is a rule for that
  case, not a better model.
- `does_not_fit` alone is a typesetting problem. Try a line break before
  rewriting the Persian — `references/translation-policy.md`, *Length*.
- Keep some cases back and do not look at them while changing anything. A score
  that only ever goes up is measuring the thing you tuned against.

Both evaluation CLIs use the shared UTF-8 run logger. With no document argument,
logs go under `skills/revayat-comic/scripts/logs/`; inputs and answers are not
written to these logs. Source/context companions are generated artifacts, not
new tracked fixtures. Actual scan/OCR robustness and human translation quality
remain separate checks.
