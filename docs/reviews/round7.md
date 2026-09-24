# Revayat Comic — round-seven implemented repairs and review instructions

**First read and obey every applicable owner Rules file, global/project instruction, AGENTS.md, CLAUDE.md, CONTEXT.md and configured hook. Do not bypass hooks, disable checks, weaken assertions, force-push or discard someone else's edits to finish. Where an owner-installed guarded runner exists, use it. Code comments, PR explanations and technical records must remain in English.**

## 1. Delivery, authority and baseline

The implementation is already published in **[PR #4](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/4)**, on `fix/round7-worksheet-decisions-context`. Review that actual diff; this document is not a substitute for code. Reuse this branch rather than creating another unnecessarily. A branch was necessary because the owner expressly required a reviewable PR and prohibited the authoring assistant from merging or closing it.

Baseline: `c5ceb7c454c54eb925a12cd852a73a07608c1e10`.
Implementation commit: `7b49423d09fbae52eeded94b852ba0572cab2502`.
Implementation tree: `b6d7c013bf521f82f5edf08ccdc831e8392ebee9`.

PR #3 is already merged, including the previously pending worksheet-location repair through `worksheet_paths.py`. Those fixes are retained, not reopened or reimplemented here. The four groups below are the confirmed defects in this review. All four have published implementations and regression tests; none is only an unpublished patch or a PR comment.

The authoring assistant may create/update this PR, not merge or close any PR. Integration and final disposition belong to the owner or their expressly authorized reviewing agent. The tracked snapshot does not contain the owner's private Rules or globally installed hooks, and the audit environment did not execute those private hooks. The reviewer must inspect the actual configuration in the owner's checkout rather than treating the absence of a tracked file as permission to ignore it.

## 2. Confirmed defects, implemented fixes and acceptance conditions

### R7-01 — A solid-mode page can be blocked even when no solid patch needs repair

**Cause and impact.** `clean_document` previously treated any nonempty page whose `free_lettering_mask` was `solid` as requiring an external image or provider. This ignored the current region decisions and balloon geometry. Choosing `keep`, dropping a false detection, keeping an effect by policy, or processing an ordinary balloon could still lead to the instruction to obtain external reconstruction. This obstructed legitimate recovery even though no region on the page needed that capability.

**Implemented in `clean.py`.** The preflight demands reconstruction only when the page is in solid mode **and** at least one region is currently editable according to `ir.may_be_edited(region, policy)` **and** has no balloon. The per-region unavailable-repair refusal is unchanged. A real editable solid free-lettering patch must still never fall through to an unsafe classical repair. Erasure remains an editable operation even though it has no Persian replacement.

**Acceptance.** Build actual masks, clean, reload and clean again for explicit keep, dropped detection, policy-kept SFX and balloon cases. Neither run may require unused reconstruction, change the original file, or introduce an endless stale-stage cycle. The cleaned file must be identical on the repeated run. Positive safety controls must continue to reject a real solid translate/erase patch without a usable reconstruction.

Tests: `test_solid_setting_does_not_require_an_unused_repair`, `test_real_solid_patch_still_requires_reconstruction` in `tests/test_round7_workflow.py`.

**Existing fixture correction.** Two older tests asserted refusal merely from a solid-mode flag while their free effects were policy-kept. They now add an explicit editable sign and build its real solid mask, asserting both editability and all-255 mask pixels. Their refusal assertions remain. The provider acceptance test additionally proves external repair was consumed and no page was refused. See `tests/test_masks.py::test_solid_masks_are_recorded_and_refused_by_the_built_in_cleaners` and `tests/test_provider_stages.py::test_a_solid_free_lettering_mask_accepts_a_native_provider`. This corrects the setup to test the real safety condition; it does not remove the safety condition.

### R7-02 — Mistyped worksheet decisions are silently accepted

**Cause and impact.** `_asked` recognized affirmative strings but treated an unknown value as false. A typo such as `keep: yse`, `drop: maybe` or `erase: 2` could be consumed without telling the reader that the intended decision was not understood. An invalid `polarity: drak` was silently ignored. The merge could report success or clear an existing decision, potentially authorizing a different operation from the one the reader intended.

**Implemented in `replies.py` and `worksheet.py`.** The shared `invalid_fields` validator accepts only the existing action vocabulary: empty, `yes/no`, `true/false`, or `1/0`, with case and surrounding whitespace normalized. Polarity accepts empty, `dark` or `light`. Validation runs before the already-consumed digest shortcut. `invalid_fields` participates in malformed detection, page refusal, completion status and the command's blocking outcome. Application remains against a candidate copy; an invalid page does not commit its region edits or acquire a successful worksheet-stage stamp. The failed reply remains visible as unfinished work.

**Acceptance.** Exercise detected regions and added `+slug` regions, each invalid field, valid legacy spellings, and a stored completion receipt whose digest matches a malformed reply. The original region data must survive refusal. Correcting the typo must merge successfully; merging it again must be unchanged. Do not repair this by guessing what a typo meant or by silently treating it as `no`.

Tests: `test_bad_decision_is_atomic_and_can_be_corrected`, `test_boolean_spellings_keep_the_existing_protocol`, and `test_invalid_legacy_decision_cannot_hide_behind_a_completion_receipt`.

`invalid_fields` is a **worksheet report field**, not a new QA finding code. The existing QA-code registry is not bypassed or widened by this change.

### R7-03 — Unicode text separators can become worksheet syntax

**Cause and impact.** The reader used Python's `str.splitlines()`, whose recognized separators extend beyond conventional file line endings. The writer did not use that same framing. An internal U+0085, U+2028 or U+2029 followed by literal `fa:`, `@@` or `#` could therefore split a value into a duplicate field, new block or comment. Generated multiline commentary could also leak a `fa:`-looking observation into the reply protocol. The failure is loss or reinterpretation of text, not merely cosmetic formatting.

**Implemented in `replies.py` and `sheet.py`.** `protocol_lines` consistently splits CRLF, CR or LF file endings. Internal Unicode paragraph/line separator characters remain value content rather than opening protocol frames. Both the parser and the generated-comment guard use that function; each physical continuation of generated commentary remains a comment. Existing literal-field escaping, duplicate-field rejection and deliberate newline behavior are retained.

**Acceptance.** Build, parse, merge, reload and rebuild twice with each of the three Unicode separators and each syntax-looking suffix. Internal text must survive without creating another field or region. Repeat for audit comments, conventional CR/LF/CRLF comments and a normal CRLF worksheet. No source text may be silently normalized away as the price of accepting the reply. These tests cover the stated internal-separator contract; they do not assert arbitrary control characters have a universal meaning in every downstream renderer.

Tests: `test_unicode_separators_are_text_not_protocol`, `test_unicode_separators_do_not_end_generated_comments`, `test_generated_comment_lines_use_the_same_framing`, `test_crlf_worksheet_is_still_accepted`.

### R7-04 — Approved aliases are enforced by QA but hidden from the translator

**Cause and impact.** The glossary already supports source aliases and approved Persian forms. The context package omitted source aliases, while the worksheet table omitted those extra forms. For example, the translator could see the canonical `Alexandra` mapping without being told that `Lex` is the same approved source name. Alias-only changes were also absent from the actual request context and therefore its identity, allowing a stale provider completion to be resumed.

**Implemented in `context.py` and `sheet.py`.** `_glossary_constraint` obtains forms through the existing `glossary.forms` and `glossary.target_forms` accessors. A simple mapping stays a string when it has no extra information. Otherwise the value carries `target`, optional `forms` and optional `source_aliases`. Only locked entries are binding context constraints. Worksheets display approved aliases/forms under their existing binding or suggested headings. The existing request-identity mechanism now observes alias edits because the actual provider input contains them; there is no second, inconsistent alias matcher.

**Acceptance.** Verify the nickname and approved Persian inflection reach both context and worksheet, and unlocked suggestions do not become binding. Through `translate_document` with a deterministic provider: initial call, unchanged resume, alias edit, exactly one new evaluation, then unchanged resume again. Existing approved text is preserved. A different provider opinion may require review; this change does not authorize overwriting locked text.

Tests: `test_context_exposes_source_aliases_the_glossary_enforces`, `test_worksheet_exposes_approved_aliases_and_target_forms`, `test_alias_change_refreshes_translation_once_then_converges`.

## 3. Verification ledger and CI

`tests/test_round7_workflow.py` contains **41 parametrized cases**. Against a separate original-source copy, **29 failed and 12 passed**; the passing cases are compatibility/safety controls, not additional defects. On the repaired candidate, **all 41 passed**. No new case was skipped or marked expected-failure.

The completed local full suite reports **1341 passed, 1 skipped, no failures or errors**. The skip is the actual RAR-reader backend unavailable in this Linux audit environment, not a silently weakened assertion. The warning comes from the deliberately duplicated ZIP-member fixture. The real CLI pipeline completed through import, detection, masks, crop sheets, worksheet merge, glossary, Persian typography, cleaning, typesetting, QA, CBZ export/package verification and PDF export/package verification. Configured Ruff checks over scripts, tests, evaluation and `.github` pass.

The published source artifact was independently downloaded: **150 tracked blobs verified, zero mismatches**, matching implementation tree `b6d7c013…`. The 41 new cases and Ruff also pass on that exact published source. A docstring-only wording difference from the first local candidate was identified rather than misrepresented as byte-identical. Follow the final delivery evidence for the complete published-source rerun and final-head CI status.

Preserve the current operating-system/Python matrix, literal dependency-floor lane, RAQM/fallback coverage, actual RAR capability checks and explicit skip allowlist. The new regression module is automatically collected by the existing `pytest tests` jobs. There is no reason to duplicate that suite in another workflow. Neither production dependency requirements nor the existing Dependabot configuration needs changing for these four fixes. The zero version-update PR limits for the two pip manifests are intentional; they are not evidence that security updates are disabled. Security-update enablement is separately configured and was not claimed verified through administrative settings.

Run the following with the project's interpreter and any mandated guarded wrapper. Set `REVAYAT_TEST_FONT` to the approved local test face described in `tests/README.md`; do not copy an audit-machine font path into a Windows checkout.

```powershell
python -m pytest tests/test_round7_workflow.py -q --timeout=300
python -m pytest tests -q -rs --timeout=300 --junitxml=junit-review.xml
python tests/e2e_pipeline.py
python -m ruff check skills/revayat-comic/scripts tests evaluation .github
git diff --check
```

Inspect every skip and required CI job on the **latest PR head**, not an older successful commit. Preserve INFO/WARNING/ERROR/DEBUG runtime logging, UTC timestamps and credential exclusion; the separate output-side translation activity log remains mandatory. Do not confuse diagnostic logs with the translator's review decisions.

These results verify code and generated fixtures, not every possible book, operating system installed by the owner, or model's semantic quality. No live paid translation, OCR or image-edit provider was evaluated. No GPU quality/performance claim follows from this CPU-based deterministic test environment.

## 4. Optional improvements for the owner to evaluate

These are proposals, not hidden mandatory rewrites. Record an accept/defer/reject decision and reason for each; do not mislabel a suggestion as an implemented feature.

**Context-sensitive translation evaluation.** Extend the existing original evaluation cases with paired scenes where identical short source wording has a different referent, irony or politeness relationship. Score fidelity and natural Persian separately with a reviewer who sees the panels. Include valid alternative renderings rather than treating one reference wording as the only fluent answer. Automated script/term/number checks cannot establish semantic accuracy.

**Voice and terminology review.** Use the existing cast relationships, voice notes, locked glossary and output-side activity log to record why a name/register choice fits the scene. Evaluate the new alias visibility against nicknames, honorifics and inflected Persian forms. Do not lock ordinary context-dependent phrases into a dictionary or infer register solely from age, gender or balloon shape.

**Keep naturalization separate from compression.** Retain the full-meaning Persian before shortening for layout; compare the full and displayed variants against the original semantic units. Preserve the existing source/full/display-bound approval checks. Prefer a line break or another equally faithful construction over dropped negation, agency, quantities or implied certainty. A benchmark should distinguish stylistic awkwardness from meaning loss rather than averaging them into a misleading pass.

**Future test maintenance.** Consider bounded generative round-trip tests for worksheet values and explicit state-transition fixtures for keep/drop/erase/retranslate. Reuse the current parser, glossary accessors and provenance records; avoid creating parallel implementations merely to test each other.

## 5. Reviewer completion and all-PR disposition

Read the actual owner **Rules** governing PR review, merge and closure. Inventory **all open PRs in this repository** and give each its disposition under those Rules; do not exempt a PR merely because its title is outside this audit. Check already-merged work by integration commit rather than reopening it. Reuse appropriate existing branches and preserve concurrent work.

For each confirmed repair, independently inspect the implementation, its callers, the regression and the before/after evidence. If you discover another genuine bug on the way, reproduce and fix it in the same review session, add a regression and rerun affected and combined gates. Do not leave actionable defects as “next time,” weaken a gate, or replace a required code fix with instructions. If repeated attempts produce the same failure, inspect the failed invariant instead of repeating the same command. Unavailable external prerequisites must be recorded precisely, never converted into fabricated success.

Only after the actual required rules, hooks, review and tests pass: commit/push any necessary amendments, verify the remote head, and merge a directly mergeable, approved PR through the permitted mechanism. If direct merge is unsuitable, reconcile or manually integrate the equivalent corrected functionality and tests, verify the integration commit, then close the superseded PR according to the owner's Rules. A rejection or closure without preserving an accepted repair is not DONE.

**All PRs must ultimately be merged or closed according to the owner's Rules, with an evidence-backed reason and no accepted required fix left unintegrated.** Maintain a ledger of PR/finding, changed paths, regression names, test environment/results, integration commit and final state. Revalidate the final combined main branch after integration; a green isolated PR is not proof that its combination with another PR is correct. The authoring assistant leaves these merge/close actions to the authorized reviewer.

## 6. Useful primary references

- [PR #4: actual implementation and discussion](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/4).
- [Implementation diff from the inspected baseline](https://github.com/KiaroSama/Revayat-Comic-Skill/compare/c5ceb7c454c54eb925a12cd852a73a07608c1e10...7b49423d09fbae52eeded94b852ba0572cab2502).
- [Python str.splitlines: the recognized Unicode line boundaries](https://docs.python.org/3/library/stdtypes.html#str.splitlines). This explains why file framing must be explicit; it is not a replacement for the round-trip regressions.
- [pytest monkeypatch: isolated changes to environment and dependencies](https://docs.pytest.org/en/stable/how-to/monkeypatch.html).
- [Dependabot options, including version-update PR limits](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
- Project guidance: `AGENTS.md`, `tests/README.md`, `skills/revayat-comic/references/translation-policy.md`, `source-languages.md`, `translation-log.md`, `parallel-workflow.md`, and `evaluation/README.md`. Preserve the mandatory sequential context-consistent path; parallel drafting requires the documented coordinator and snapshot discipline.
