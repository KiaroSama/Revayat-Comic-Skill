# Round 11 — progress, literal typography and safe diagnostics

Baseline: `86f3e7ea209af41984dc19bb4c2d734adb7282c5`. Four reported repair
areas were independently reconstructed against the real repository. No external
patch or its claimed test results were imported as local execution evidence.

## Sequential context progress

Worksheet stage freshness includes glossary/header constraints, so using it as
proof of moved regions incorrectly blocked ordinary terminology work after a
page was merged. Context now compares a well-formed accepted receipt's isolated
page identity. Its page hash and reply digest are validated before comparison;
legacy or malformed records retain the conservative stage guard. Only answered
pages through the current page are checked. Box, kind, orientation and source-image
changes still block, including under `--allow-unmerged`; edited replies still need
merging. Locked terminology and rendering freshness keep their own gates.

## Literal quantities and physical lines

The shared typography lexer protects complete signed structured numeric notation:
decimal/grouping separators, time/date-like components, exponents, leading decimal
points and Unicode digits. These spans remain literal under both digit options;
ordinary prose digits and punctuation keep their prior behavior. A comma is not
interpreted as a locale-specific grouping or decimal marker. Protecting a literal
is not adding scientific-value conversion to the evaluation scorer.

Explicit CR/LF/CRLF physical lines normalize to logical LF, including blank lines.
A standalone CR can no longer disappear and join two words. Broad Unicode
`splitlines()` is deliberately not used.

## Terminal recovery history

The shared compression applicability predicate requires a non-dropped translatable
region, nonempty differing full/displayed text, and no valid current pair approval.
Kept/dropped/erased regions can retain their full wording without demanding approval
of an empty translation. Returning to an active changed pair requires review again.
Missing active translation and unfinished cleaning remain errors; no QA code or
severity was removed. Bilingual/annotated translated effects still require review.

## Credential-safe provider failures

Unknown network/SDK exception messages no longer enter public failure details,
chapter provenance or factory tracebacks. The boundary keeps a safe exception type
and fixed configuration/service guidance. Unknown exception stringification is not
invoked; even an exception whose `__str__` exits cannot break this reporting path.
Trusted first-party `PublicProviderError` guidance is bounded and single-line;
only an exact legacy missing-setting message remains public. Factory errors suppress
the standard original traceback chain, not introspection of arbitrary Python objects.

Raw nonempty bearer keys must be printable ASCII without whitespace before any
request/opener construction. Values are never trimmed, repaired or echoed. Valid
keys, keyless local services, TLS/loopback restrictions, redirects and response-size
limits remain intact. First-party messages do not interpolate credential-bearing
endpoint fallbacks. Existing structured UTC logs remain the logging mechanism.
A trusted public error is a programming contract, not a malicious plugin sandbox.
Already-exposed data is not silently rewritten; owner-controlled rotation and
quarantine are separate actions.

## Verification boundaries

Each root cause has an observed failing-then-passing bounded public seam: provider
failure through saved chapter provenance, typography through document/worksheet
round trip and exact scorer, two-page glossary progress with counted translation
resume, and terminal decision through masks/clean/typeset/strict QA. Persistent
controls cover compatibility and malformed/negative inputs; the complete existing
CI discovery retains OS/runtime/floor, E2E, installer, encoding and skip-policy lanes.
The final exact published revision's checks are authoritative, not baseline CI.

No new runtime dependency, model or raised floor is required. Generated fixtures
and synthetic credentials are used; no paid provider or live credential is needed.
These mechanical checks do not certify translation fluency, real-comic OCR quality
or universal absence of future defects.

Primary documentation checked for this repair:
- [Python3.13 physical/string boundaries](https://docs.python.org/3.13/library/stdtypes.html#str.splitlines).
- [Python3.13 HTTP client](https://docs.python.org/3.13/library/http.client.html) and [CPython source](https://github.com/python/cpython/blob/3b55c23ff4a6aa32f77be661802a3978d7324f88/Lib/http/client.py).
- [Python exception context](https://docs.python.org/3.13/library/exceptions.html#exception-context).
- [OWASP logging exclusions](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude).
