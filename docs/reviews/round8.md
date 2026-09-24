# Revayat Comic — round-eight repairs and reviewer work order

**First read and obey every applicable owner Rules file, AGENTS.md, CLAUDE.md, CONTEXT.md, parent/nested instruction and installed hook. Do not bypass hooks, weaken assertions, disable checks or discard another writer's changes. Use the owner's guarded runner wherever required. All code comments, technical explanations and PR records must be in English.**

## 1. Delivery and authority

Baseline: `21d6924dea76e3fc830f5bab6eef5a74a268ed10`, tree `8b07abb4bb71ea9e866668324c30492b07a598ca`. PRs #3 and #4 have already been integrated; their path recovery, decision validation, alias context, publication and recursive lint-discovery fixes are retained. Do not reapply an older audit snapshot over the current repository.

This change implements the four findings below in five production modules, with `tests/test_round8_contracts.py` providing 62 cases. Review the actual PR diff, not only this brief. No existing tests were removed or weakened. The submitted assistant may publish code and open/update the PR, **not merge, close, enable auto-merge, rewrite shared history or update main**. The owner or authorized reviewing agent controls integration and all-PR disposition under the owner's Rules. Reuse this PR's branch; another branch is justified only by a real technical or protection requirement.

### Mandatory commit identity, including history

The owner requires **both author and committer emails on every previous and future published commit to be exactly `Kiaro.Sama.Dev@gmail.com`**. Set and verify that identity before committing. Inspect raw `%ae` and `%ce`, not only a mailmap-rendered log; changing `user.email` does not rewrite existing commits.

The current connector's commit action exposes no author/committer override. An unreferenced same-tree metadata probe confirmed it supplies the GitHub noreply identity. That probe is not a parent of this repair and no branch points to it. The repair PR must disclose its actual identity rather than claiming the connector used the mandated email. **Its email correction is a required integration gate, even when functional tests pass.** The accompanying package supplies an approved-author patch for the reviewer's native Git workflow.

Before integration, immediately identify and reconstruct wrong-email commits according to the owner's history Rules. Preserve code trees, commit messages, attribution, licenses and an old-to-new SHA map. Back up refs and coordinate the history migration before updating shared branches or tags; use the owner-approved expected-ref/lease procedure, never a blind force push. Recheck all affected author/committer fields and run required checks on the rewritten final SHA. Do not call an email change complete merely because Git configuration or a mailmap changed. The authoring assistant does not perform that shared-history operation.

## 2. Findings, implementation and closure tests

### R8-01 — A carriage return inside dialogue can become a worksheet action

**Reproducer and consequence.** Store a field containing `hello\rkeep: yes`, `hello\rdrop: yes`, `hello\r@@ +ghost sign horizontal` or `hello\r# literal`, then build and merge its worksheet. The reader split CR, LF and CRLF through `protocol_lines`, but `field_lines` escaped only LF-separated fragments. A literal continuation could therefore become a real decision, new block or comment. The previous Unicode-separator repair covered parsing and generated commentary, not this field-writing path.

**Fix.** `replies.field_lines` now splits using the same `protocol_lines` function before escaping every fragment. Physical CR/LF/CRLF line endings normalize to logical LF, rather than being reinterpreted as fields. Internal U+0085/U+2028/U+2029 behavior remains unchanged. This is explicit newline normalization, not a claim that original CR bytes are retained.

**Acceptance.** `test_value_line_endings_never_become_worksheet_actions` covers 3 newline forms times 4 syntax-looking continuations. It exercises source text, displayed Persian, full Persian and review notes through build, parse, real merge, reload and two rebuild rounds. Region count and actions remain unchanged; a repeated merge reports unchanged. Preserve existing escape, blank-line, Unicode and comment tests. Do not fix this by stripping content or disabling action parsing.

### R8-02 — Mistyped explicit region headers silently default to another decision

**Reproducer and consequence.** Change an existing or added header to `spech horizontal` or `speech sideways`. The parser previously discarded unrecognized values, so a new speech balloon could default to SFX and be considered kept by policy, or take an inferred orientation. Retaining an invalid orientation without guarding application would instead throw while constructing the candidate region, before a structured refusal could be returned.

**Fix.** `replies.parse_worksheet` retains explicitly supplied kind/orientation values. The shared `invalid_fields` checks them against the existing enums. `worksheet.merge_document` refuses invalid scalars **before applying even a candidate copy** and before the completion shortcut can accept a legacy receipt. It records unfinished worksheet status without changing the real regions. Reconciliation uses the same validator and cannot restamp a malformed answer into freshness. Omitted optional header fields retain existing defaults; valid canonical digest behavior is unchanged.

**Acceptance.** `test_invalid_explicit_header_cannot_commit_or_reconcile` covers both bad header components on existing and added regions. Verify region data is unchanged after refusal, reconciliation refuses without modifying the reply, correction merges successfully, and the next merge is unchanged. Preserve the previous action/polarity and reconciliation regression families. Do not add a permissive typo guess or use force as a substitute for validating the decision.

### R8-03 — Glossary approval and aliases are accepted through Python truthiness/stringification

**Reproducer and consequence.** A table with `locked: "false"` could become a binding decision through `bool(...)`. Lists of aliases or target forms could accept nulls, numbers or nested objects and stringify them as approved spellings. A blank/nontext source key was accepted through direct setters. Input-only validation is insufficient: an older or hand-edited document can still contain the malformed approval, and context, worksheets and glossary QA must not reinterpret it independently.

**Fix.** `glossary.validate` accepts only actual boolean approval and text elements in form collections. `_validate_source` requires a nonempty text key before mutation; `apply_file` validates the entire incoming table before applying any entry. `_string_list` ignores nontext legacy forms rather than inventing textual spellings, and `_affected` shares that accessor. `glossary.is_locked` accepts a real boolean (missing means false) and raises an actionable error for malformed legacy approval; it does not silently approve or demote it. Glossary checks, translator context and worksheet binding/suggestion sections share this read boundary. Existing target-history preservation is retained. An explicit valid `set_entry(..., {"locked": False})` repairs the legacy record without rewriting translated dialogue.

**Acceptance.** The regression module covers bad approval types, both form collections, invalid source keys, whole-table atomic refusal, corrected-table application, defensive legacy forms, and all three legacy approval consumers. It verifies the document is unchanged on invalid input; a valid false decision remains nonbinding; and explicit repair restores normal context/QA. Preserve locked-name history and alias matching tests. A generic string cast, bare truthiness test or reader-specific workaround does not close this item.

### R8-04 — Dropped detections consume the next-page dialogue allowance

**Reproducer and consequence.** Put at least `MAX_NEXT` dropped detections before the live dialogue on the next page. `_next` sliced the raw region list before excluding dropped regions, so the translator received no continuation even though real following dialogue existed. This can remove the context needed to resolve a pronoun or unfinished sentence.

**Fix.** Iterate in existing reading order, skip dropped records, and stop only after collecting `MAX_NEXT` live entries. Keep the existing source-length cap and source-only lookahead; do not translate or approve future pages as a side effect.

**Acceptance.** `test_dropped_regions_do_not_consume_next_dialogue_budget` reaches the public `context.build` path, puts dropped entries before more than the live allowance, and requires exactly the first `MAX_NEXT` real source snippets in order. This proves context delivery, not semantic quality of an arbitrary translation model.

## 3. Verification and CI

The source archive used for the frozen original was independently checked against its Git tree: **151 tracked blobs, zero mismatches**, accounting for the declared PowerShell checkout line endings. Its executable code/tests match the current baseline; only the historical round-seven review note differs. The PR is built on the current remote tree so that note is preserved.

Completed local evidence uses separately frozen original and candidate trees, never a suite running while its source changes:

| Check | Result |
| --- | --- |
| 62 new cases on original code | 54 failed, 8 passed, no skips or setup errors |
| Complete candidate suite | 1404 passed, 1 skipped, no failures/errors; 1405 collected |
| Real CLI pipeline | Passed, including preservation QA and CBZ/PDF package verification |
| Configured recursive Ruff checks | Passed |
| Whitespace/diff check | Passed |

The 8 original passes are compatibility controls, not new bugs. The local skip is the unavailable unrar/unar/bsdtar backend. A deliberately duplicate ZIP-name fixture emits the known warning. The installed local DejaVu face was used; this is not a claim that its bytes equal the CI-pinned font. Final remote-head CI and source verification belong in the PR's updated evidence section; do not reuse an earlier SHA's green result as approval of a later edit.

Run these commands with the repository interpreter and any mandatory guarded wrapper; set `REVAYAT_TEST_FONT` according to `tests/README.md` for that machine:

```powershell
python -m pytest tests/test_round8_contracts.py -q -rs --timeout=90
python -m pytest tests -q -rs --timeout=300 --junitxml=junit-review.xml
python tests/e2e_pipeline.py
python -m ruff check skills/revayat-comic/scripts tests evaluation .github
git diff --check
```

Keep the existing OS/Python matrix, literal dependency floors, RAQM/fallback coverage, real archive checks, explicit skip allowlist and source evidence. The normal suite already collects these tests; do not duplicate them into a new workflow. The fixes require no new dependency. The two pip Dependabot version-update PR limits of zero are intentional floor-maintenance policies, not proof that security updates are disabled; administrative security-update enablement is separate. Preserve the grouped Actions updates and dependency-review/audit jobs. Do not make unrelated major upgrades or weaken a required lane.

All new execution helpers should retain timestamped INFO/WARNING/ERROR/DEBUG logging and credential exclusion. The existing CLI diagnostic log does not replace the translator's output-side activity log. No live paid translation, OCR or image-edit provider was called; private owner-machine Rules/hooks and native installed environments were not available in the archive. Report such limits accurately, rather than claiming every possible scenario or future defect is covered.

## 4. Research and optional quality improvements

**Required reviewer research:** search the web, especially upstream GitHub repositories and official documentation, for the mechanisms and alternatives relevant to this repository. Record source URL, access date, observed version/commit where relevant, evidence, tradeoff and accept/defer/reject decision in the location and format prescribed by the owner's Rules. Do not substitute unverified model assertions for research or add dependencies solely because a repository is popular.

This round compared the Python framing semantics, GitHub identity/Dependabot documentation and upstream manga-image-translator design. Reusing Revayat's own parser and glossary accessors is the smaller compatible repair; no upstream code or model was imported. The following are **optional proposals**, not undisclosed required rewrites:

- Add human-reviewed paired-scene cases where the same short line has different referents or irony. Evaluate fidelity and natural Persian separately; retain multiple acceptable renderings and fail critical meaning loss independently of style scores. Require a reviewer who sees the panels before calling the references authoritative.
- Use the existing cast/relationship notes and source/full/display approval pair to review register, negation, quantities and honorifics. Keep natural phrasing separate from fitting; do not make an ordinary context-sensitive phrase a permanently locked glossary term.
- Evaluate, rather than automatically adopt, upstream glossary/prompt patterns and optional GPU-backed specialists on a representative Persian corpus. Measure quality, VRAM, latency and preservation behavior before changing the default host-reader workflow.
- The demonstrated framing gap justifies considering bounded property-based round-trip tests. Retain the deterministic reproducers even if a generative harness is later accepted; do not enlarge runtime dependencies or permit unbounded retries.

## 5. One-session review, all-PR disposition and integration

Read the owner's actual PR **Rules** and inventory **all repository PRs**. Assign each an evidence-backed merge or closure disposition; do not exempt a PR merely by calling it unrelated. Respect already-integrated work and preserve concurrent changes.

For each repair, inspect implementation, callers and negative/positive tests. Any additional genuine bug discovered on the way must be reproduced and fixed in the same review session, with a regression and combined revalidation, not left as an actionable next-round placeholder. If the same failure repeats, inspect the failed invariant instead of retrying unchanged commands. Keep one ledger connecting findings, files, tests, before/after results, remaining external gates, integrating SHA and final PR state.

After required Rules, hooks, identity correction, tests and final-SHA CI actually pass, the authorized reviewer commits and pushes with the approved author/committer email and merges directly mergeable approved work. Otherwise repair/reconcile or manually integrate the equivalent tested functionality, verify the integrating commit, then close the superseded PR under the Rules. **Every PR must reach its Rules-defined merge/closure disposition; closing an accepted unfixed item is not DONE.** Verify the combined default branch and raw commit identities after integration. The authoring assistant leaves all merge/closure and shared-history actions to that reviewer.

## 6. Useful primary references

- [Python splitlines and Unicode boundaries](https://docs.python.org/3.13/library/stdtypes.html#str.splitlines): explains why writer and parser need the same explicit framing.
- [pytest parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html): bounded positive and negative contract matrices.
- [manga-image-translator upstream](https://github.com/zyddnys/manga-image-translator): comparison material for translation/glossary and image-pipeline choices, not evidence that it is superior for this user's Persian task.
- [GitHub commit email configuration](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address): distinguish future configuration from existing commit metadata.
- [GitHub REST Git commits](https://docs.github.com/en/rest/git/commits): the REST API supports author/committer metadata; the current connected wrapper does not expose those fields.
- [git-filter-repo author documentation](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt): controlled identity/history migration with backup and commit-map review under owner Rules.
- [Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference): distinguish version-update PR limits from security-update administration.
- Repository references: `AGENTS.md`, `tests/README.md`, `docs/research/README.md`, `references/translation-policy.md`, `source-languages.md`, `parallel-workflow.md` and `translation-log.md` under the skill where applicable.
