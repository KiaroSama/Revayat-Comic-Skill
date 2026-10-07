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
| `cases.json` | 38 cases across Japanese, Korean, Chinese, English, French and Spanish, each with difficulty tags, a semantic-unit count and **several** Persian candidates. The original 20, including five adversarial controls, are retained. Fourteen context-sensitive cases await bilingual review |
| `build_pages.py` | draws a layout template for each case — two speakers, a balloon, a second balloon for a continuation — and exports its source/context in an answer-free `.input.json` companion |
| `score.py` | scores axis by axis, and refuses to produce one number |

```bash
python evaluation/build_pages.py --out evaluation/pages
python evaluation/score.py --answers my-answers.json
```

Custom cases are validated as a complete set before drawing or scoring: unique
safe ASCII IDs unique even under case-insensitive filenames (Windows device
names are refused), string source/language/context when supplied, and finite
balloon fractions in (0, 1]. Drawing requires source/language and a usable
balloon of at least two pixels per side. Optional null unit counts and missing
preservation checks remain unmeasured; subpixel fit is unmeasured rather than a
crash. Invalid records refuse before creating output pages. Answers must be an
object of strings. Unknown answer keys are refused before scoring so a typo
cannot silently make a submitted answer disappear.

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

## Exact textual preservation

Quantity checks compare finite decimal spellings without binary floating-point
rounding. Signs, leading/trailing zeros and Unicode decimal digits normalize;
compound alternatives such as `12:30` or `1/2` retain their order and separators.
Each compound component also normalizes redundant zeros, so `012:030.00`
can preserve `12:30`; a longer clock such as `12:30:45` cannot. Numeric fragments
inside ASCII identifiers (`UART-3`, `HTTP/3`) or dotted versions (`1.2.3`) do not
count as separate quantities. Attached units such as `12.5V` remain supported.
Clock components can still be requested separately by a case. Scientific
notation is unsupported by numeric preservation, not converted to a decimal
value; supply a supported finite-decimal or written-word alternative explicitly. The existing comma-as-decimal
convention is retained; no thousands separator or unit conversion is inferred.
Written-out alternatives are whole words/phrases, not prefixes of names or
weekday compounds. `num-02` explicitly lists `سومین`, which its existing
reference answer already used.

Required terms use the same script-aware matcher as `glossary check`. Latin
identifiers such as `UART2`, `Section 7` and `C++` are bounded forms, not
substrings of `UART20`, `Section 70` or `C++20`. Ordinary Persian attaching-letter
boundaries and the existing CJK substring policy remain unchanged. A retained
`V` is not a retained `mV`; none of these lexical checks establishes that the
quantity belongs to the right object or that the dialogue is semantically sound.

## Context-sensitive expansion

| Added cases | What needs a reader |
| --- | --- |
| `ctx-fr-01`–`ctx-fr-04` | Lack of obligation versus prohibition, a requested `vous`/`tu` transition, expletive `ne`, and ironic praise during a breakdown |
| `ctx-es-01`–`ctx-es-04` | Optional printing, familiar Mexican plural `ustedes`, prohibition without a gloves exception, and an implied arriving courier |
| `ctx-ja-01`–`ctx-ja-02` | First-person responsibility recovered from prior dialogue; a polite promise to consider without inventing acceptance |
| `ctx-zh-01`–`ctx-zh-02` | Negation scope and relationship stance; a delayed return known only by hearsay |
| `ctx-ko-01`–`ctx-ko-02` | Direct kinship address with established family voice; an unconfirmed date that is neither settled nor cancelled |

All fourteen have explicit context, a human review note, and `human_only: true`.
Their wording differs from the research/prompt examples. Their Persian
candidates are authored proposals, not human-validated gold translations.
Adequacy, fluency, voice and omissions/additions stay `null` until a person
scores them. The total language distribution is 16 Japanese, 4 Korean,
4 Chinese, 6 English, 4 French and 4 Spanish cases.

Four original `review-*` microcases add negative-question replies, established
register, scene-selected idioms and an exact technical label/measurement. Each
has multiple Persian candidates and a deliberately wrong control. The first
three remain human-only; the last checks retained numbers/terms, not complete
meaning. Their candidates are not bilingual-certified references. The shipped
`references/persian-review.md` guide supplies the source-first review route.
`review-negative-reply` translates only the answer balloon, `I did.`; the prior
`You didn't send it?` question is context, not a second sentence to translate.
Its two Persian proposals and deliberately wrong control remain human-only.

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
