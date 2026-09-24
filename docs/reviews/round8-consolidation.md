# Round-eight consolidation — PRs #5 and #6

**Obey the owner's Rules, AGENTS.md, CLAUDE.md, CONTEXT.md and required hooks first. The authoring assistant must not merge or close either PR or update main. The reviewer must apply the owner's all-PR disposition and commit-identity Rules.**

## Why this integration is necessary

The final PR inventory found an overlapping [PR #5](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/5), head `dde58149cbaeab65a50bd49c38703439019f1e6e`, alongside [PR #6](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/6). Both start from `21d6924dea76e3fc830f5bab6eef5a74a268ed10`. Treat them as related alternatives, not independent patches to merge blindly.

PR #5 has typed glossary inputs and escaped metadata, plus provider and JSON-boundary fixes. It lacks the shared serializer's CR repair, leaving 5 worksheet tests failing. PR #6 already supplies that serializer repair and the stronger legacy-approval, explicit-header and lookahead repairs. The combined PR #6 retains its implementations of the overlapping files and adopts the three independent production files and both regression modules from #5. No existing test expectation is changed.

| PR #5 finding | Combined finding | Resolution in PR #6 |
| --- | --- | --- |
| R8-01, worksheet serialization | R8-01 | Shared CR/LF writer and escaped proposal/review fields; the 5 previously failing cases pass |
| R8-02, glossary values | R8-03 | Typed write validation plus shared legacy read guard and source-key validation |
| R8-03, numeric confidence | R8-05 | Adopted `providers.py` boundary fix and tests |
| R8-04, JSON/discovery resilience | R8-06 | Adopted `server.py`, `wire_json.py` and transport tests |

The four original PR #6 repairs remain documented in [round8.md](round8.md). This note adds the two independent defects and makes the combined closure scope explicit.

## R8-05 — An oversized confidence value escapes the provider Result boundary

**Reproduction.** A local OCR provider returns a very large integer or Fraction as its confidence. Converting it during `math.isfinite` can raise `OverflowError`; formatting its raw representation can itself raise for an integer beyond the interpreter's conversion limit. The provider call then escapes as an exception instead of a failed Result. Merely catching the first conversion is insufficient if the diagnostic tries to render the same invalid value.

**Implementation.** Keep the existing boolean/Real-type checks. Contain `OverflowError`, `TypeError` and `ValueError` around the numeric checks, and return the bounded reason that the value is not a finite probability. Report that reason without interpolating the raw confidence. Preserve ordinary numeric endpoints, Fraction probabilities, provenance and the existing bounded-worker lifecycle.

**Acceptance.** `test_outsize_confidence_is_a_failed_result_not_an_exception` tests large integer, oversized repr and large Fraction values with a one-slot semaphore. Every call returns a failed Result with a short confidence diagnostic, and the next valid call succeeds. `test_valid_confidence_keeps_its_numeric_contract` preserves 0, 1, .75 and Fraction(1, 2). Do not disable Python's integer conversion guard or stringify arbitrary provider data to produce a message.

## R8-06 — Decoder and discovery failures interrupt an otherwise healthy session

**Reproduction.** Submit a JSON frame containing a 5000-digit integer, excessive nesting, NaN or an overflowing exponent, followed by a valid request. The previous decoder boundary did not consistently reject/contain these shapes. A stage import failure could also abort `tools/list`, and stringifying an oversized direct numeric argument could fail outside the stage boundary.

**Implementation.** `wire_json.loads` scans nesting while respecting quoted strings and escapes, then delegates syntax to the standard decoder with bounded integer, finite-float and nonstandard-constant callbacks. The limits are 128 levels and 1024 integer digits; they complement, not replace, the existing byte limits. Both MCP and HTTP use the same helper and convert decoder failures to protocol errors. Discovery describes an unavailable stage without losing healthy tools and emits a sanitized warning; invocation still reports failure. Argument conversion failures return a structured failure. Do not alter the process-wide recursion/integer settings, authentication, loopback binding, socket deadline or existing bounded frame reads.

**Acceptance.** The companion failure-contract module tests each invalid frame through actual MCP and a loopback HTTP connection, followed by a good request. It also covers failed discovery followed by ping, direct oversized integer arguments, brackets inside strings, escapes, normal JSON and exact depth/digit boundaries. Four positive helper tests are controls for the newly introduced module, not claimed failures against an old module that did not exist.

## Independently repeated evidence

The exact PR #5 archive was verified against **155 Git blobs**, zero mismatches. Five adopted files are byte-identical to that inspected head: `providers.py`, `server.py`, `wire_json.py`, `tests/test_round8_failure_contracts.py` and `tests/test_round8_text_contracts.py`.

- Actual PR #5's focused suite: **50 passed / 5 failed**, with no errors or skips. This confirms, rather than merely repeats, its outstanding serializer failures.
- Its 51 pre-existing-contract tests on PR #6 before adopting the independent fixes: **38 passed / 13 failed**, no errors or skips. The four new-helper controls were intentionally not part of this comparison.
- Combined focused suite: **123 passed**, comprising all 68 PR #6 cases and all 55 PR #5 cases. No skips, expected failures or weakened assertions were used.

The combined full suite, real CLI pipeline, recursive lint and final-head CI are separately recorded in PR #6's final evidence section. Earlier 1405/1411-test results apply to earlier four-group candidates, not to this six-group combined tree. Do not add overlapping execution counts together to manufacture a test total.

## Required reviewer disposition

PR #6 is the combined candidate. Correct both author and committer identities to **`Kiaro.Sama.Dev@gmail.com`**, inspect and reconstruct wrong-email historical/future commits under the owner's Rules, preserve verified trees and backups, and revalidate the final integrating SHA. Connector-created commits use noreply and are not identity-compliant; neither PR should be merged unchanged merely because a functional lane passes.

After the combined repairs, identity, hooks and tests are verified, the authorized reviewer may integrate the complete PR #6 result, then close PR #5 as superseded **with the integrating commit and evidence**. Alternatively, port the full verified equivalent onto the branch selected by the owner's Rules, check it again and dispose of both PRs accordingly. Do not close #5 before its accepted independent fixes are integrated. Do not merge its partial tree first and assume its missing code is resolved. Inventory every other open PR too and assign its Rules-defined disposition. Fix newly found genuine defects in the same review session; do not defer required code or repeatedly retry an unchanged failure. The authoring assistant leaves both PRs open.

## Research record and useful references

Primary documents were consulted for these additional mechanisms. Preserve the original research/optional Persian-quality guidance in `round8.md`; record further research in the location and format prescribed by the owner's Rules. This integration reuses inspected code already in the owner's repository, not an untested external model or a new dependency.

- [Python JSON decoder callbacks and input limitations](https://docs.python.org/3.13/library/json.html): shared strict decoding without changing global interpreter limits.
- [Python numeric classification](https://docs.python.org/3.13/library/math.html#math.isfinite): the numerical operation being guarded; oversized-input behavior is also demonstrated by local tests.
- [Companion PR #5](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/5): exact source and original review context; its old failed status is not the result of the combined tree.
