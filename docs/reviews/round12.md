# Round 12 — current decisions and retained drafts

Baseline: `e52d04882e4749204eebd65f274656d54324c7a1`. Independently reconstructed
one decision-consistency defect with three consequences. External patch/test
claims were not imported as local evidence. Existing tests and prior repairs remain.

## Current drawing, not historical text

The shared `translatable` decision excludes dropped, kept and erased regions and
respects the current SFX policy. Both drawing and text-authorization loops use it.
The renderer retains the cleaning-mask union, adding per-region balloon/lettering
authority only for actual drawing candidates. Bilingual/annotated effects gain no
on-page authority because their gloss has no automatic placement; their unplaced
gloss record and gate remain. Erasure can clean pixels but cannot print an old
Persian target back over them. Historical full/display wording is not deleted.

## Publication reflects the edition

The shared minimum-artifact contract requires `final` for currently translatable
nonempty text, `clean` for completed repair, and otherwise permits the original.
QA certification and export pass the actual document policy. Default keep-policy
arguments preserve older direct calls. Kept census status precedes historical
text or overflow records. Confidence, source integrity, actual erasure completion,
mask bounds, stage freshness and artifact certificates remain checked.

An unchanged kept/dropped page can publish without an empty typeset run. An erased
page still needs its verified cleaned pixels, and active text still needs a render.
Changing policy requires fresh stages; history alone never authorizes an old edition.

## Drafts remain drafts

Typography fix/lint, current glossary enforcement and paired translation memory
consult the same current decision. Inactive drafts and approvals remain untouched;
reactivation restores the applicable checks and paired memory. Historical glossary
rename impact is deliberately unchanged: it names retained nondropped older spellings
for review, not as a current-publication failure. Source images and crops remain
available to understand the scene; omitting a draft pair does not erase source context.

## Verification boundary

Observed bounded public regressions failed then passed for retained erasure through
real masks/clean/typeset, ordinary CBZ publication without a fake render, and inactive
typography/glossary/context. Persistent controls exercise four inactive decisions,
automatic and forced fallback shaping, all three primary formats, repeated operations,
policy changes, reactivation, historical aliases and required-artifact/tamper failures.
Final published-revision CI is authoritative; baseline CI and external counts are not.

No new runtime dependency, model, paid service or compatibility-floor change is needed.
Generated image fixtures prove mechanical decision/pixel/package contracts, not every
real comic, OCR quality or bilingual translation fluency. Publication is a reviewable
PR; integration is a separate owner-authorized action.

Primary sources checked on 2026-10-04:
- [Pillow image IO, arrays and masks](https://pillow.readthedocs.io/en/stable/reference/Image.html).
- [NumPy exact array equality](https://numpy.org/doc/stable/reference/generated/numpy.array_equal.html).
- [Python default arguments](https://docs.python.org/3.13/tutorial/controlflow.html#default-argument-values).
- [Comparable rendering source](https://github.com/zyddnys/manga-image-translator/blob/441d07c59a735c7db3db2e7bb8b07920afd8a9cc/manga_translator/rendering/__init__.py), inspected for separation, not copied or treated as mask-preservation proof.
