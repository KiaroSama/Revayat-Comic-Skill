# Round 10 — transport recovery and exact preservation

Baseline: `451bfaad933ea97221b29a789f0cc8e245223996`. The existing proposal's
shared quantity/term matcher and structured stage revisions are retained, with
native byte recovery and answer-region scope added in the same repair.

## Native MCP byte framing

Text decoding can read ahead across several physical messages. A malformed byte
inside one JSON string previously raised before the parser's error boundary,
ending the native server instead of answering the next healthy request.

`stdio_frames.py` reads a bounded physical frame from the borrowed unread binary
buffer before strict UTF-8 decoding. Invalid bytes produce a fixed parse error
with null ID, without dispatch, replacement or request echo. The next message
remains usable. No borrowed stream is closed, no wrapper is detached, and no
inactivity timeout is promised for arbitrary stdin. The existing oversized-frame
rejection and finite discard budget remain; decoded-only library stand-ins retain
character caps and a one-chunk byte overshoot. HTTP authentication, loopback binding,
socket deadline and decoded JSON guards are unchanged.

The native CLI regression failed with exit4/UnicodeDecodeError before the repair
and passed afterward with explicit error, healthy ping and clean EOF. Persistent
controls cover strict/surrogateescape wrappers, decoded stand-ins, malformed byte
sequences, no dispatch, LF/CRLF/EOF, ownership and bounded oversized discard.

## Exact quantity and term text

The former float comparator merged different integers beyond binary precision,
rounded neighboring decimals and overflowed on large literals. Compound quantities
lost order when reduced to sets. `textmatch.py` uses exact lexical finite-decimal
normalization, not float/int conversion or context-rounded Decimal arithmetic.
Signs, redundant zeros, Unicode decimal digits and the existing decimal-comma
convention remain supported. Exponent-to-decimal and unit conversions are not inferred.

Compound matches compare ordered canonical components and intervening separators
in a contiguous window: `012:030.00` can preserve `12:30`, but reversed, scattered
or longer clocks cannot. Numeric fragments of ASCII identifiers and dotted versions
are excluded; existing attached-unit and explicitly requested clock-component
compatibility remain. Written alternatives are whole words/phrases, with explicit
inflections rather than guessed morphology.

The shared matcher also bounds Latin/alphanumeric terms for both evaluator and
glossary, including rename reports: `UART20` is not `UART2`, `mV` is not `V`, and
`C++20` is not `C++`. Existing Persian letter and CJK substring contracts remain.
No glossary rewrite inside dialogue or automatic semantic approval is introduced.

## Source region and rendering identity

`review-negative-reply` now has source `I did.` only. Its preceding negative
question is in context. The 38-case count, two Persian proposals, wrong control
and human-only status are unchanged. Generated inputs still omit answers, glosses
and human notes. This fixes scope, not bilingual certification.

Stage text/source facets serialize structured field sequences rather than joining
unrestricted text with `|`. Field redistribution can no longer preserve a revision
accidentally. Comparable scheme3 is retained deliberately: old vulnerable hashes
become stale once rather than gaining a legacy exemption. Unchanged geometry,
mask and cleaning identities remain fresh. A new semantic review cannot certify
an old rendered image; publication/export refuse until real rerender and QA.

## Verification boundaries

The existing 59 proposal controls are retained. New tests use public transports,
evaluator and generation seams, tiny framing limits, a bounded native child, and
existing reusable pipeline fixtures. Full OS/runtime/floor, E2E, installer, encoding,
skip-policy and publication controls remain in the existing CI discovery. No new
runtime dependency or raised floor is needed. Final exact-SHA CI is the integrated
evidence; historical proposal totals are not substituted for the combined candidate.

Generated fixtures and mechanical matches do not certify real-comic OCR robustness,
voice, semantic association or translation fluency. Host-reader-first behavior,
immutable originals, stable region identities and mask-only changes are unchanged.

Primary documentation checked on 2026-10-03:
- [Python3.13 I/O](https://docs.python.org/3.13/library/io.html): binary framing and borrowed-wrapper lifetime.
- [MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports): UTF-8 newline messages.
- [Python3.13 Decimal](https://docs.python.org/3.13/library/decimal.html): exact construction versus context rounding.
- [Python3.13 regular expressions](https://docs.python.org/3.13/library/re.html): Unicode classes versus application-specific boundaries.
