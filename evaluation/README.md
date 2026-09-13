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
| `cases.json` | 15 cases across Japanese, Korean, Chinese and English, each with a difficulty tag, a semantic-unit count, the things that must survive the trip, and **several** acceptable Persian renderings |
| `build_pages.py` | draws a comic page for each case — two speakers, a balloon, a second balloon for a continuation |
| `score.py` | scores axis by axis, and refuses to produce one number |

```bash
python evaluation/build_pages.py --out evaluation/pages
python evaluation/score.py --answers my-answers.json
```

`--answers` is `{"case-id": "the Persian"}`.

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

The scorer decides only what is decidable: negation, numbers, required terms, an
ellipsis, a contrastive subject, the semantic-unit count, and whether the line
sets inside the balloon — that last one measured by the pipeline's real fitter.
Adequacy in full, fluency and voice consistency come back `null` with the
question a person has to answer, and a case tagged `human_only` is not
machine-scored at all.

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
