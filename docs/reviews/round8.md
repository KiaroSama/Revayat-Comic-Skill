# Revayat Comic — round-eight code review and completion order

**First read and fully obey the owner's actual Rules files, global/project instructions, AGENTS.md, CLAUDE.md, CONTEXT.md and every applicable hook. Use the owner's guarded runner where configured. Never bypass hooks, disable a safety check, weaken an assertion, discard concurrent edits or claim an unverified result to finish. All code comments and technical records must be English.**

## 1. Actual delivery and authority

Repository: `KiaroSama/Revayat-Comic-Skill`.

**[PR #5 is open](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/5)** on `fix/round8-text-and-input-contracts`. Continue that branch rather than creating another. A new branch was necessary because the owner required a PR and the previous PR was already closed. Baseline: `21d6924dea76e3fc830f5bab6eef5a74a268ed10`, tree `8b07abb4bb71ea9e866668324c30492b07a598ca`.

This is **not a merge-ready delivery**. Three defect groups are implemented in the PR, and the worksheet group is partially published. The complete local candidate passes its tests, but publication of the required `replies.py` change was blocked twice by the tool's undetermined safety-status check. The unpublished correction is given exactly below. All its tests remain in the PR; none is skipped or marked expected-failure to hide it. Commit identity is a separate integration blocker.

The auditing assistant must not merge or close any PR, enable auto-merge or change `main`. Those actions belong only to the owner or expressly authorized reviewing agent. PR #4 was manually integrated as `5524a34901c435a41035200f21901adbab439a01` and closed; its fixes, including reconcile validation and recursive lint discovery, are baseline behavior, not fresh unresolved findings.

## 2. Mandatory commit identity and historical correction

**Every previous and future published commit must use only `Kiaro.Sama.Dev@gmail.com` for both author and committer email, as required by the owner. Immediately identify and correct every other email in the repository history under the owner's Rules. Do not postpone identity repair until another review.**

The current GitHub connector's create-commit action does not expose author/committer parameters. An actual created Git object was inspected: it used the connector's `noreply` identity, not the approved address. Therefore the PR's generated commits are not claimed identity-compliant. Do not merge them unchanged. The local baseline snapshot was configured with the approved email; local configuration cannot change the connector's remote identity.

In the owner's checkout, set the local Git email to the approved address and inspect raw `%ae` and `%ce` for the actual history and PR range. Rebuild affected commits with the approved author and committer identities, preserving their verified source trees and intended ancestry. Inventory branches/tags and take a private recoverable backup before historical rewriting. Follow the actual Rules for coordinated ref updates; never blindly force-push every ref or overwrite new work. Preserve evidence mapping old SHAs to replacement SHAs, rerun final-SHA checks and verify the integrated trees. A `.mailmap`, a commit-message trailer or changing `git config` alone does **not** change existing raw commit objects. Updating signed commits also requires the owner's signing procedure. The auditor has not rewritten default-branch history.

Useful inspection commands in PowerShell 7, from the repository root:

```powershell
git config --local user.email "Kiaro.Sama.Dev@gmail.com"
git log --all --format="%H%x09%ae%x09%ce"
git show -s --format="%H%n%T%n%ae%n%ce" HEAD
```

## 3. Findings, implementations and acceptance criteria

### R8-01 — Writer/reader framing lets literal text become a worksheet action

**Root cause.** The reader splits CR, CRLF and LF through `replies.protocol_lines`, but `field_lines` escaped only the pieces produced by splitting on LF. A stored value such as `سلام\rkeep: yes` therefore became a shorter `fa:` value plus a real `keep` decision. That can suppress a translation instead of retaining literal dialogue. `sheet.py` also wrote `propose` and carried `reviewed` values directly, leaving those routes outside the shared serializer.

**Implemented locally.** Split value text with the same `protocol_lines` helper before escaping every resulting line. Route `propose` and `reviewed` through `field_lines`, just like source text, Persian and notes. The `sheet.py` half is published. The `replies.py` half is **not** published.

**Apply this exact missing edit** in `skills/revayat-comic/scripts/replies.py`, inside `field_lines`:

```diff
-    parts = str(value).split("\n")
+    # Match the reader's CR/LF framing before escaping every value line.
+    # A bare CR must not turn literal text into a keep/drop instruction.
+    parts = protocol_lines(str(value))
```

Keep the next `first = escape(...)` line and all existing escape/parser behavior unchanged. Do not work around the defect by deleting carriage returns, stripping dialogue, or changing the parser's field grammar. Conventional physical line endings become logical LF; the repair does not promise byte-identical CR storage. The previously fixed U+0085/U+2028/U+2029 behavior must remain intact.

**Acceptance.** Run build → parse → merge → rebuild twice using source, Persian and notes containing CR/LF/CRLF followed by literal `keep:`, `fa:`, `@@` and `#` markers. Assert stable region IDs, preserved logical text, no accidental decisions, correct notes and successful repeated merge. Test proposed terms separately across all three endings. The five currently failing CR cases must become green without changing their expectations.

Tests: `test_all_physical_endings_escape_value_lines` and `test_proposed_term_cannot_become_a_worksheet_action` in `tests/test_round8_text_contracts.py`.

### R8-02 — Glossary input coercion turns invalid data into approval and spellings

**Root cause.** `bool("false")` is true, so a JSON table using a string instead of a boolean could approve a spelling that was meant to be unlocked. Alias/form arrays coerced `null`, numbers and objects with `str()`, exposing invented spellings to matching and translator context.

**Published fix.** `glossary.validate` requires an actual boolean when `locked` is supplied and actual strings in `aliases`/`target_forms`. Validation precedes mutation for direct entry updates and the entire table. `_string_list` defensively retains only nonempty strings when reading legacy form arrays; `_affected` uses the same accessor rather than another coercion rule. Missing-field defaults, valid `false`, tuple/list support for library callers and explicit empty-list clearing are preserved. This is table-ingestion and form-array hardening, not a claim that every arbitrary hand-corrupted IR field is schema-validated.

**Acceptance.** Reject string/numeric/null/list/object approval values without modifying the document. In a table containing one valid entry and one invalid mixed-type array, preserve the original document bytes. Preserve valid unlock/clear operations. Verify that legacy mixed form arrays cannot put fabricated names into context or the shared glossary matching accessors.

Tests: `test_glossary_lock_requires_a_boolean_before_any_change`, `test_glossary_forms_do_not_coerce_objects_into_spellings`, `test_legacy_forms_are_read_defensively_by_context_and_qa`, `test_valid_glossary_unlock_and_clear_remain_supported`.

### R8-03 — Oversized confidence escapes the provider failure boundary

**Root cause.** A returned integer or Fraction too large for float conversion makes `math.isfinite` raise. Formatting a huge integer with `repr` can itself fail under Python's digit limit. The provider worker has returned, but the adapter boundary raises instead of returning the promised failed `Result`.

**Published fix.** `_not_a_confidence` contains overflow/type/value failures and returns a fixed reason. Invalid-confidence diagnostics no longer format raw provider values. Existing acceptance range, confidence-floor behavior and locked text preservation remain unchanged. No larger timeout, recursion limit or worker pool was introduced.

**Acceptance.** Exercise oversized integer, oversized printable integer and Fraction results, then a normal provider call using the same one-permit semaphore. Assert a concise failed result, no exception, retained capacity, and correct provenance for valid 0, 1, fractional and ordinary floating probabilities.

Tests: `test_outsize_confidence_is_a_failed_result_not_an_exception`, `test_valid_confidence_keeps_its_numeric_contract` in `tests/test_round8_failure_contracts.py`.

### R8-04 — Decoder and discovery failures terminate otherwise healthy sessions

**Root cause.** MCP/HTTP caught only narrow JSON decode exceptions. Oversized integer conversion can raise plain `ValueError`; excessive structure can raise recursion errors. Nonfinite constants or overflowing exponents were accepted. Separately, discovery imported every stage without containing a missing module, and direct numeric argument conversion could raise outside the request boundary.

**Published fix.** `wire_json.py` provides a shared decoder: maximum 128 container levels, 1024 integer digits, finite floating values, rejection of nonstandard numeric constants. A quote/escape-aware scan limits structure before constructing objects; standard `json.loads` still validates syntax. MCP and HTTP translate decoding failures into existing error responses, preserving the next request. Direct argument conversion returns a structured error. Discovery describes an unavailable stage and emits a sanitized warning through the existing run logger; invocation still reports its failure. Existing authentication, loopback restriction, raw-byte limit, bounded frame discard and socket deadline remain unchanged.

**Acceptance.** Send each malformed frame followed by a healthy request through the real MCP loop and loopback HTTP socket. Assert a response rather than a disconnected session or false success. Verify quoted brackets/escapes are not counted as structure, exact boundaries are accepted, and process-wide recursion/digit settings are untouched. Test discovery → failed invocation → healthy ping with an unavailable module. These are bounded parser/resource contracts, not a promise that every arbitrary custom Python stream or broken output device can recover.

Tests: both `test_bad_*_json*` families, discovery/direct-argument tests and the four `test_json_limits_*` positive/boundary cases. No external API credentials are involved.

## 4. Evidence, test commands and CI assessment

The retrieved baseline archive's 151 Git blobs were verified. The final `main` documentation-only update was applied separately and the reconstructed Git tree checked against `8b07abb4...`; tests ran against the actual complete repository source, not extracted helper approximations.

| Run | Observed result |
|---|---|
| Original full suite | 1342 passed, 1 RAR-backend skip |
| 51 new contract cases on original source | 38 failed, 13 compatibility/control passes |
| Complete local candidate | All 55 new cases passed |
| Complete local candidate, full suite | 1397 passed, 1 RAR-backend skip, no failures/errors |
| Published subset, focused tests | 50 passed, 5 failed CR cases |
| Candidate real CLI pipeline and configured Ruff | Passed |

Four helper-specific positive tests target the newly introduced decoder, so they are not presented as failures against a module that did not exist. The local deliberate duplicate ZIP-member fixture emits its known warning. Linux/Python 3.13.5 used an installed DejaVu font via `REVAYAT_TEST_FONT`; it is not claimed to be the exact CI-pinned binary. No font file is included in the evidence package. Final published-tree full-suite and CI results must be read from the delivery evidence/PR, not inferred from the complete local candidate's successful run.

Run the new tests and then the full suite through the owner's permitted runner. The repository's underlying commands are:

```powershell
python -m pytest tests/test_round8_text_contracts.py tests/test_round8_failure_contracts.py -q
python -m pytest tests -q -rs --timeout=300 --junitxml=junit-round8.xml
python tests/e2e_pipeline.py
python -m ruff check skills/revayat-comic/scripts tests evaluation .github
git diff --check
```

Preserve the existing operating-system/Python matrix, literal dependency floors, RAQM/fallback checks, real RAR capability checks, skip allowlist, manifests, encoding, installer and end-to-end jobs. The two new modules are automatically collected; no duplicate workflow is needed. Verify the new helper ships with the self-contained skill. Do not hide the five blocked-publication cases with skips/xfail or broaden the lint exclusions again.

No runtime dependency was added. Existing Dependabot pip limits of zero deliberately suppress version-update PRs that would unnecessarily raise minimum versions; they do not by themselves disable separately configured security updates. Preserve both pip-manifest coverage and grouped Actions updates. Administrative security-update enablement was not verified. Add or repair CI only for a reproduced coverage/behavior gap, not unrelated version churn.

## 5. Translation-quality and script improvements to evaluate

These are suggestions, not evidence that a live model was benchmarked. Keep optional redesign separate from required fixes and do not delay a verified repair indefinitely.

Extend the current original contextual benchmark with paired scenes where identical source words require different Persian referents or irony, and blind Persian-reader ratings for fidelity, fluency and character voice. Record source language, panel evidence, model/prompt version, terminology snapshot and human adjudication; do not use a high automatic score as semantic approval. Preserve direct source-language → Persian translation, standing honorific/name policy, and full-versus-displayed wording. Review negation, modality, quantities and agency before fitting; shorten only with an approved full/display pair, not by omitting meaning. Never infer a voice only from age or balloon shape.

For engineering, consider a small generated writer/parser round-trip corpus covering every emitted field and newline/control boundary. Add a shared schema only after defining compatibility for historical documents; do not silently coerce broken approvals. Compare transport maintenance against the official MCP SDK's implementation, but adopt a new dependency only if measured benefit justifies changing this lightweight CLI-backed design.

## 6. Research and required completion

**Research this repository and relevant current documentation before modifying it. Search the web, especially GitHub primary repositories, for suitable implementations and changes. Record findings, alternatives, source links, versions and decisions exactly where and how the owner's Rules prescribe. Do not treat an old chat, an external issue anecdote or another project's implementation as proof this repository is correct.**

Useful primary references consulted:

- [Python JSON decoding hooks and numeric behavior](https://docs.python.org/3.13/library/json.html).
- [Python text splitting and truth-value testing](https://docs.python.org/3/library/stdtypes.html#str.splitlines).
- [Official MCP Python SDK stdio implementation](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/server/stdio.py), for implementation comparison rather than automatic migration.
- [GitHub Git commit API author/committer fields](https://docs.github.com/en/rest/git/commits#create-a-commit). The API supports fields the available connector wrapper does not expose.
- [git-filter-repo](https://github.com/newren/git-filter-repo), for a Rules-compliant, backed-up history repair; not permission for an indiscriminate rewrite.
- [Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

**Inventory every open PR in this repository and give all PRs their merge/closure disposition under the owner's actual Rules. Do not exempt a PR merely as unrelated.** Review every accepted fix, its callers, its before/after test and its interaction with existing fixes. Fix genuine additional defects found along the way in the same session, with reproduction and regression coverage; do not leave actionable work for a later round. If a failure repeats unchanged, inspect the cause instead of blindly repeating commands. Record a genuine unavailable external prerequisite explicitly rather than fabricating completion.

For this PR, first integrate the exact missing R8-01 edit and correct commit identities. Then run combined tests, hooks and CI on the final replacement SHA. Only the authorized reviewer may merge directly when the Rules and checks permit. Otherwise reconcile or manually integrate the equivalent tested functionality, record its integration SHA and close the superseded PR only after the accepted repair is present. All PRs must reach their Rules-defined merged/closed DONE state; closing an unfixed accepted repair merely to empty the list is not completion. Verify the combined default branch, not only the PR branch, after integration. The submitting assistant performs none of those merge/closure actions.

Maintain one closure ledger: finding → code paths → tests → candidate/published/integrated SHA → actual result → PR disposition. A green local candidate does not certify a partial remote tree. No universal zero-future-bug claim, live model-quality certification or execution of private owner-machine hooks is made here.
