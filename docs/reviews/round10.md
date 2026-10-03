# Round 10 — exact preservation and revision identity

**First fully obey the owner's applicable Rules and hooks, including the Spec Kit routing rules. Read the actual local instructions, current operational logs, existing specification and hook configuration before changing or integrating code. Never weaken a test, bypass a gate, overwrite concurrent work or report a tool execution that did not occur.**

Baseline: `451bfaad933ea97221b29a789f0cc8e245223996`; verified source tree:
`c4612c704789f916da5929b161178ca4a79a9c26`. Round-nine review/geometry/Unicode
repairs are already present and retained. This round addresses three new
reproduced invariant groups. It does not claim every possible comic, installed
backend or live translation model has been certified.

## 1. R10-01 — Numeric preservation is approximate and loses compound structure

**Cause and consequence.** The evaluator used `float` to canonicalize written
numbers. Distinct integers `9007199254740992` and `9007199254740993`, or decimals
`0.10000000000000001` and `0.1`, could satisfy each other. A 400-digit number
raised `OverflowError` instead of producing an evaluation. Multi-part spellings
were compared as sets: `12:30` was accepted as `30:12` or scattered `12` and `30`.
Written-out alternatives were substrings, so a person's name could satisfy a
required number word. These are wrong mechanical approvals, not measures of
Persian fluency.

**Implemented solution.** The shared `textmatch.py` normalizes decimal digits,
signs and redundant zeros lexically, without conversion to binary float or an
unbounded integer. Whole numeric spellings compare exactly. Explicit compounds
retain sequence, separators and boundary checks; optional spaces around `:` and
`/` do not change their identity. Simple clock components remain independently
matchable where an existing case explicitly requests them. Scientific tokens
are consumed whole rather than exposing their exponents as quantities; no
scientific-to-decimal conversion is inferred. Written alternatives use whole
words/phrases, including protection against ZWNJ compounds. Units can follow
written quantities without a space. Preserve the existing comma-as-decimal
convention rather than guessing locale-specific thousands separators.

`evaluation/score.py` delegates to this helper and retains its public report
shape, human-only axes and equal text/JSON exit status. The existing reference
in `num-02` uses `سومین`; that exact form was added to its explicit alternatives,
rather than adding an implicit morphology rule or changing the answer.

**Closure tests.** `tests/test_quantity_terms.py` covers precision collisions,
400/5000-digit values, changed signs, leading decimal points, Unicode digits,
redundant zeros, reversed/scattered compounds, exponent fragments, attached
units, named alternatives and both CLI output formats. All pre-existing
reference renderings still pass their mechanical checks. Do not fix this by
using a tolerance, rounding fewer digits, discarding hard cases or asserting
semantic equivalence from an unordered set.

## 2. R10-02 — Approved technical identifiers match larger identifiers

**Cause and consequence.** The glossary bounded alphabetic Latin names but sent
alphanumeric identifiers to its generic substring branch. `UART2` matched
`UART20`, `my_UART2` and `UART2_extra`; `Section 7` matched `Section 70`. The
evaluator separately matched all required terms by substring, accepting `mV`
for `V`. The glossary rename report had another substring implementation, so
changing a canonical form could incorrectly flag unrelated larger names.

**Implemented solution.** `textmatch.used` is the single matcher used by the
glossary, its affected-region report and the evaluator. It recognizes bounded
Latin/alphanumeric identifiers and phrases, escapes regex syntax, permits
phrase whitespace, and handles punctuation-ended names such as `C++` without
accepting `C+++` or `C++20`. Matching remains case-sensitive. Existing Persian
attaching-letter boundaries and intentional CJK substring matching are preserved;
this is not a new universal tokenizer or a guessed alias generator.

`glossary.used` remains available under its old API name through a re-export.
All write-validation, canonical-history, approved-alias and locked-text rules
remain intact. No replacement is performed inside translated dialogue.

**Closure tests.** Negative and positive examples exercise both consumers,
including accented names, Persian names, CJK and escaped punctuation. A real
`glossary check`/`apply_file`/reload/reapply sequence verifies exact drift IDs,
source aliases, unchanged dialogue and one canonical-history increment. The
actual `review-protected-measurement` benchmark case rejects a different port
or voltage unit while accepting both of its existing candidate answers.

## 3. R10-03 — A delimiter collision allows stale rendered text to ship

**Cause and consequence.** `_region_text` joined ID, displayed text and full
text with `|`. Display `سلام|دنیا` plus full `دوست` and display `سلام` plus full
`دنیا|دوست` produced identical input bytes. The source facet likewise joined
region IDs and unrestricted source text, allowing text to cross a region-ID
separator without changing the hash. This is an ambiguous serialization, not a
cryptographic SHA-256 collision.

A real finished chapter was rendered, edited to the second pair and explicitly
reviewed again. Before the fix, publication QA still accepted the old image:
a valid new semantic review did not prove that its newly reviewed words had
been rendered. The new test demonstrates the public publication failure, not
only the helper equality.

**Implemented solution.** Encode the text fields as a structured JSON sequence
and the source facet as a sequence of `[region_id, source_text]` pairs. The
comparable stage-record format stays at scheme `3` intentionally. Existing
vulnerable text/source hashes must become **stale**, not gain an
`unverified` legacy exemption after a global scheme bump. Unchanged page,
geometry, policy, mask and cleaning identities stay unchanged. Existing
text/source consumers refresh through their normal commands, once per page;
no new renderer, automatic approval, source mutation or blanket retranslation
is introduced.

**Closure tests.** `tests/test_revision_framing.py` covers field-shift and
cross-region source collisions, unaffected-page isolation, unchanged
mask/clean/detect stamps, old comparable-record refresh, partial refresh and
idempotent repetition. Its real-pipeline test requires: render → change text →
new semantic approval → failed publication/export → real typeset → successful
QA/export → repeated successful typeset. Old text hashes may not remain fresh,
and a signature of the old image alone may not override changed inputs.

## 4. Verification and CI requirements

The original complete repository was retrieved from current GitHub source
evidence and checked against all 165 tracked Git blobs with zero mismatches.
The baseline suite ran locally: **1507 passed, 1 RAR-backend skip**, no failures
or errors. The related post-fix light pass, including existing evaluation,
glossary and stage tests, passed **188 tests**. Final before/after totals,
full-suite logs, source hashes and final-head CI are recorded in the PR and
owner-facing delivery evidence rather than guessed in advance here.

Run through the owner's required runner, with the documented test font:

```powershell
python -m pytest tests/test_quantity_terms.py tests/test_revision_framing.py -q -rs --timeout=60
python -m pytest tests -q -rs --timeout=300 --junitxml=junit-review.xml
python tests/e2e_pipeline.py
python -m ruff check skills/revayat-comic/scripts tests evaluation .github
git diff --check
```

Keep the current OS/Python and literal dependency-floor matrix, real archive
capability tests, RAQM/fallback coverage, exact skip policy, source evidence,
CodeQL and dependency-review checks. The normal suite automatically collects
the two regression files; no redundant workflow is needed. No dependency was
added. The two pip version-update limits of zero are deliberate compatibility
floor policy, not proof that administrative security updates are disabled.
Retain grouped Actions updates; verify account-level security settings where
permissions allow rather than inventing their status.

Tests use repository-generated fixtures and offline provider stubs; they do not
replace a licensed real-comic acceptance run or native-speaker adjudication.
Local RAR executable, native Spec Kit/Graphify and private owner-machine hooks
were unavailable. Test execution and captured logs are real; local planning
notes are not claimed as execution of those absent tools. No font binaries,
private rules, credentials or licensed comic art belong in this PR/evidence.
Runtime logging remains the shared UTC INFO/WARNING/ERROR/DEBUG system.

## 5. Required Spec Kit, identity and all-PR review sequence

**Use the actual Spec Kit chain required in the owner's Rules, not merely its
names in a report.** Inspect the existing `.specify/` and feature artifacts.
For a diagnosed bug in an existing specification, use `speckit-converge` then
`speckit-implement`. For unspecified behavior or a specified-behavior change,
use `speckit-specify` → `speckit-clarify` → `speckit-plan` → `speckit-tasks` →
`speckit-analyze` → `speckit-implement`, with init/constitution only where
missing and checklist/convergence gates as the Rules require. Preserve existing
artifacts; keep local specifications/research and private hooks out of Git.
Unavailable commands or unanswered required gates remain explicit blockers,
not fictitious successes. Do not reinitialize or use force to skip a gate.

**Every previous and future published commit must use only
`Kiaro.Sama.Dev@gmail.com` for author and committer email.** Verify raw metadata
and trailers under the owner's Rules. Immediately identify and reconstruct
noncompliant history with recoverable backups, unchanged intended code trees,
old/new SHA mapping and coordinated expected-ref/lease updates as those Rules
permit. A mailmap, trailer or changed Git setting alone is not history repair.
Never discard somebody else's history or blindly force-push all refs. The
submitting assistant does not rewrite shared/default-branch history.

This task requires a PR, so one side branch is necessary. Continue its branch
rather than creating more. The authoring assistant may publish this review's
fixes and open/update the PR, but **must not merge, close, auto-merge, delete
branches or change main**. The owner/authorized reviewing agent controls those
actions. Inventory **all repository PRs**, with no blanket unrelated-PR
exemption, and apply the actual Rules to every merge/closure disposition.

Review each real diff and regression, run actual Rules/hooks and final-SHA CI,
and fix any additional genuine defect discovered during that review in the same
session with a regression. Do not leave accepted actionable repairs as
next-round placeholders or repeat an unchanged failed attempt. Maintain one
ledger from finding to test to final integrating SHA. If direct merge is
appropriate and all gates pass, the authorized reviewer commits/pushes with the
approved identity and merges. Otherwise integrate the verified equivalent,
record and test that integrating commit, then close the superseded PR according
to the Rules. Every PR must reach its Rules-defined DONE merge/closure state;
closing an unfixed accepted repair is not completion. Revalidate the combined
default branch after integration. The auditing assistant leaves that decision
and operation to the reviewer.

## 6. Research and optional improvements

Research this repository and current primary documentation before further edits;
**search the web, particularly GitHub**, compare relevant implementations, and
record URLs, dates, version/commit, alternatives and decisions exactly where
the owner's Rules require. This round selected shared lexical matching and
structured hashing instead of a heavier NLP/model dependency.

Optional proposals to assess rather than silently implement: extend paired-scene
Persian review cases so identical words carry different referents/irony;
separately adjudicate fluency, fidelity, register and critical negation/quantity
errors; preserve source/full/display approval and do not tune to a single
reference translation. Use real panels cleared for sharing, not only generated
balloons, for human review. Evaluate bounded property-based text/field
round-trip generation in CI while retaining the deterministic public-path
regressions. Compare upstream context/glossary approaches, but do not import
another pipeline's models or GPU dependencies without a measured benefit for
this user's Persian task. The host-reader-first default remains unchanged.

Primary references consulted on 2026-10-03:

- https://docs.python.org/3.13/tutorial/floatingpoint.html — why approximate binary arithmetic cannot certify exact written values.
- https://docs.python.org/3.13/library/decimal.html — exact-decimal alternative; lexical normalization avoids context/exponent concerns for this grammar.
- https://docs.python.org/3.13/library/re.html — escaped patterns and Unicode boundaries.
- https://github.github.com/spec-kit/ and https://github.com/github/spec-kit — current workflows; owner's installed Rules route is authoritative.
- https://github.com/zyddnys/manga-image-translator — upstream context/glossary comparison, not proof of superior Persian quality.
- https://docs.github.com/en/rest/git/commits — actual commit identity fields versus the current connector wrapper.
- https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference — version-update limits and security-update distinction.
