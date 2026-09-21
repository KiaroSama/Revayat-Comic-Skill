# Round-six verification and review record

**First, obey all owner-defined rules and hooks. Read applicable AGENTS.md, CLAUDE.md, CONTEXT.md, nested instructions and the real local hook configuration. Do not bypass hooks, weaken assertions, or disable checks to get a green result.**

PR: https://github.com/KiaroSama/Revayat-Comic-Skill/pull/3

Base: `a9cee3b6e597c2c2d3dfbb8d9529085b9c8bd755`. Continue the existing `audit/round6-verified-repairs` branch; do not create another branch merely by habit. The authoring assistant must not merge or close this PR. Review and integration belong to the owner or explicitly authorized reviewer.

## Implemented and covered by regressions

1. **Provider deadline and worker capacity.** Invalid deadlines reached the worker/join boundary, so invalid input could start work, raise, or remove the intended bound. `validate_timeout` now rejects nonnumeric, boolean, nonpositive, nonfinite and platform-overflow values before a worker starts. A failed `Thread.start` returns a failed result and releases the acquired semaphore. Valid timeout behavior and the existing limit on outstanding daemon workers remain intact; this does not claim Python can kill a running thread.
2. **OCR acceptance and resume.** An invalid confidence floor could pass comparisons; raising a valid floor did not change request identity. Worse, equality with existing text could confirm a weak answer before checking its confidence. The floor is validated before document/crop work, included in request identity, and applied before confirmation. Existing and locked text is preserved; insufficient confidence is recorded for review, not certified as completion.
3. **Provider payload and signature contracts.** OCR/translation results must be nonempty text, rather than arbitrary objects marked successful. Positional-only parameters are not offered as keywords. Genuine provider failures yield nonzero OCR/translation CLI status and unsuccessful transport results. A refused cleaning page also yields nonzero status. Legitimate second-opinion disagreements remain advisory and do not overwrite a decision. Translation refusal reports retain the moved-geometry cause.
4. **Transport failure containment and bounded input.** Module import and doctor execution run inside the request error/capture boundary. Large integer arguments no longer require an overflowing float conversion. MCP reads bounded prefixes and enforces raw UTF-8 byte length before stripping whitespace. An oversized frame produces an error and bounded resynchronization; an excessive unfinished frame ends the session rather than an unlimited discard loop. This is a memory/read-amount bound, not a new inactivity timeout for arbitrary stdio streams. HTTP remains loopback-only with its existing authentication and socket deadline.
5. **Diagnostic levels.** `REVAYAT_LOG_LEVEL` supports INFO, WARNING, ERROR and DEBUG. The active-run event API records sanitized messages; arguments are deliberately absent. Invalid level configuration produces a generic warning. File-log failure warnings include UTC time. This diagnostic log does not replace the separate translation activity log required beside a delivered comic.

Production files: `providers.py`, `ocr.py`, `translate.py`, `clean.py`, `server.py`, `runlog.py` under `skills/revayat-comic/scripts/`. New tests: `tests/test_round6_contracts.py` (31 parametrized cases). Existing tests were not removed, skipped or weakened.

## Open publication blocker: worksheet path fix is local only

The full local candidate also fixes `pageir.worksheet_folder`: resolve an explicit override at invocation, persist that stable location, resolve stored relative paths against the document directory, and use the document directory for the default. Reproduction: build external worksheets with a relative path in working directory A, change to B, then call status/merge/context without the override. The original code looks in B and misses the completed reply.

That candidate and two dedicated regressions passed locally, but attempts to publish the complete `pageir.py` file were rejected by the connected tool with an undetermined safety-status error. **Do not treat this fix as present in the PR.** The downloadable review brief and evidence package contain the exact pending patch and both tests. They are explicitly separate from the 31 cases included in this PR, not hidden with skip/xfail. The reviewer must apply and verify them before declaring the entire round done. Old documents with ambiguous historical working-directory-relative paths may need one explicit `--worksheets` argument; do not guess or relocate their files.

## Evidence and limits

The exact tracked source archive was checked against its Git tree (144 blobs; the declared PowerShell CRLF checkout representation was normalized for Git comparison). Initial tested PR head: `46a0347111cbacf7aba1cbd14489713eb441b4d9`, not a reconstructed subset of helpers.

- Initial full suite: **1266 passed, 1 skipped**; the skip was the unavailable local RAR backend.
- Full local candidate, including the unpublished path fix: **1299 passed, 1 skipped**, with 33 new passing cases.
- The standalone end-to-end CLI pipeline completed successfully on that candidate, including CBZ and PDF validation.
- The exact published subset is tested separately. Consult final PR test evidence for its counts and exact commit; do not attribute the 1299 result to code missing the path patch.

The local skip and the deliberate duplicate-ZIP-name fixture warning are disclosed, not converted into passes. No paid/live translation or image-edit service was tested, and no claim is made that all possible comic layouts or semantic translations have been certified. Owner-machine global hooks are not part of a Git archive and were not executed here.

## Reviewer closure

Keep one ledger for the five implemented groups and the open path item. Review the real diff and regressions; preserve immutable pages, stable IDs, approved text, semantic approval pairs and the existing publication/recovery protections. Resolve a reproduced defect in the same session rather than leaving a placeholder or silently dropping its test. If an unchanged failure repeats, inspect its cause instead of repeating commands blindly.

Run the full suite, real CLI pipeline and configured Ruff checks after the final edit. Keep the current platform/floor CI matrix and exact skip checks; the new tests are automatically collected by it. Verify required CI on the final SHA. Do not alter Dependabot solely because version updates have a zero PR limit: security-update settings are a separate question. Do not add unrelated workflow churn or blind auto-merge.

When the owner-authorized reviewer confirms all mandatory items, including the pending path fix, are integrated and passing, commit and push normally, then merge this PR through the permitted workflow. If direct merge is unsuitable, manually integrate and test the equivalent fixes, record the integrating commit, and only then close the superseded PR. Do not close a PR merely to make the list empty. The authoring assistant leaves this PR open and does not perform those actions.

## Primary references

- Python thread deadlines, platform limit and worker lifecycle: https://docs.python.org/3.13/library/threading.html
- Python parameter kinds: https://docs.python.org/3.13/library/inspect.html#inspect.Parameter.kind
- Bounded stream reads: https://docs.python.org/3.13/library/io.html#io.IOBase.readline
- Logging levels: https://docs.python.org/3/howto/logging.html
- Dependabot options: https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference
