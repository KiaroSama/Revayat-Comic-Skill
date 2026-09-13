# Judging a translation

Nothing in this pipeline measures whether the Persian is any good. Every gate
it has is mechanical: `qa` proves the artwork survived, `falint` proves the
typography is Persian, `glossary check` proves a locked name did not drift.
All three can pass on a chapter that reads like a machine wrote it.

**A regex pass rate is not evidence about a translation, and neither is a
model's opinion of its own work.** Both are easy to produce and neither
correlates with a reader understanding the page. This file is what to do
instead.

## You need material, and the material has to be clear

An evaluation set is a small number of **pages** — images, not sentence pairs —
with a source transcription and at least one Persian rendering that a competent
human translator stands behind. Pages, because half the difficult cases here
are only difficult when you can see the drawing.

Rights matter. Put in this set only pages you can legally keep and share:
your own work, public-domain comics, Creative Commons releases, or pages the
rights holder has given you in writing for this purpose. Publisher scans are
not cleared by being easy to download. A set you cannot show anybody is a set
nobody can check, which defeats the point.

Twenty to forty pages is enough to be useful. Two hundred sentence pairs with
no images is not a substitute.

**There is a starter set in this repository**, at `evaluation/`: fifteen
cases across Japanese, Korean, Chinese and English, each with several
acceptable Persian renderings, plus a page generated for each one and a
scorer that grades the axes separately and refuses to produce a total.

Its source lines were written for it rather than taken from a published
comic, and its pages are drawn rather than scanned. That is what makes it
shareable and it is also its limit: it measures translation, not detection
on a real scan. Adding pages you have the right to share is one field in
`evaluation/cases.json` — see `evaluation/README.md`.

## The cases worth collecting

Weight the set towards these. They are where automated translation fails and
where a page-level pass rate hides it.

| Case | What goes wrong |
| --- | --- |
| sarcasm | rendered at face value, so the line means its opposite |
| an omitted subject | Japanese drops it; Persian conjugation forces a choice, and the wrong person acts |
| an ambiguous pronoun | `彼` resolved to whoever was nearest in the text, not whoever is drawn |
| تو vs شما | picked from age or rank instead of the relationship, changing what two characters are to each other |
| an interrupted balloon | a sentence continued in the next balloon, translated twice as two whole sentences |
| an ellipsis | `……` is a pause, a refusal, or a held breath; flattened to nothing or to "..." |
| numeric-only text | a page number, a date, a price, a floor number — reformatted, localised, or "translated" |
| names | transliterated one way on page 3 and another on page 11 |
| honorifics | dropped where the relationship was the point, or kept where they were noise |
| plot-critical negation | the one clause where dropping a `ない` inverts the scene |
| a joke that turns on the drawing | translated as prose, so the punchline is the picture and the words no longer meet it |
| a sound effect that is also dialogue | a character shouting a word that the letterer drew as an effect |

## Score the axes separately

One number hides the trade-off that matters — a fluent Persian sentence that
says something else scores well on exactly one axis and should fail. Score each
of these independently, on whatever scale you like, and **report them
separately**:

| Axis | The question |
| --- | --- |
| **adequacy** | does it say what the original says — propositions, negation, tense and aspect, quantities, causal links, intent, the joke, the intensity? |
| **fluency** | is it Persian somebody would actually write? |
| **voice consistency** | does this character sound like the same person across the chapter, and different from the others? |
| **omissions and additions** | counted, not averaged — every clause that vanished and every one that appeared |
| **visual fit** | does it sit in the balloon at a readable size, and does it match what the panel shows? |

**Allow more than one right answer.** A balloon usually has several valid
Persian renderings, and a set with one reference per line measures agreement
with that reference, not quality. Collect the alternatives you accept, or score
by judgement against the source rather than by string match against a
reference.

## Reading the result

- A rise in fluency with a fall in adequacy is the translation drifting into
  paraphrase. That is the failure this skill exists to avoid.
- Omissions cluster: if they concentrate in one case from the table above, the
  fix is a rule for that case, not a better model.
- Visual fit failing while the other four hold is a typesetting problem. Try a
  line break before rewriting the Persian — see `translation-policy.md`.
- A score that only ever goes up is measuring the thing you tuned against. Keep
  some pages back and do not look at them while changing anything.
