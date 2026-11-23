# November 23, 2026 audit implementation plan

First obey the owner's applicable Rules, AGENTS.md, CLAUDE.md, CONTEXT.md and
hooks. The author's authorization is to investigate, repair and open reviewed
pull requests with dedicated issues. Do not merge, close, enable auto-merge or
rewrite shared history during this authoring session.

**Goal:** Close reproducible defects on baseline
`4e6f8663016421171e782ea1f685ec040d55981f` with practical regression evidence.

**Architecture:** Preserve the immutable source, mask-bounded processing and
transactional output contracts. Reuse existing validation and visibility
boundaries. Native extensions remain optional; a native CI lane must prove that
the native implementation actually loaded.

**Tech stack:** Python 3.12–3.14, Pillow, NumPy, OpenCV, PyMuPDF, pytest, PyO3,
maturin, GitHub Actions; Linux/macOS/Windows.

**Spec and process:** The owner's current 24-point request and repository
invariants are the specification. Follow specify → clarify from evidence → plan
→ tasks → analyze → implement → verify. No checked-in Rules directory,
Spec Kit configuration or non-sample Git hooks were found in this checkout;
do not claim an unavailable slash command was executed. The integration agent
must also read owner-side Rules and run the real Spec Kit chain where installed.

## Global constraints

- Every change needs a realistic failing control before its production repair.
- Preserve all existing regression tests and CI capability/skip evidence.
- Use English code comments and timestamped INFO/WARNING/ERROR/DEBUG logging
  through the existing run logger for executable entry points. Never log secrets.
- All new human-authored commits use `Kiaro.Sama.Dev@gmail.com`; bots are exempt.
- A PR branch is necessary for the expressly requested PR-only delivery.
- Tests must be visible for the current PR revision, not only a manual run.
- A future authorized integration agent reviews every open PR under owner Rules;
  this authoring session cannot merge or close them.

## Task ledger

- [x] Inspect the initial full-suite diagnostics and current CI. The initial
  run was concurrent with edits and is not an immutable baseline result.
- [x] CI: restore automatic PR/main checks; retain existing gates and add a
  genuine installed-native lane, with failure evidence and accurate provenance.
- [x] PDF import: reproduce clipping loss, reuse conservative visible-page
  admission, and verify safe plain-image extraction plus rendered fallback.
- [x] Native packages: reproduce wheel installation failure, supply correct
  maturin metadata, install both real extensions and verify native parity.
- [x] Provider and HTTP boundaries: reproduce invalid Unicode answer failure
  and non-ASCII authentication crash; reject safely and continue healthy work.
- [x] Batch merge: examine snapshot conflicts and glossary/state preservation;
  only report and repair behavior supported by a failing public-path control.
- [x] Review remaining modules and recent changes; distinguish confirmed bugs,
  rejected hypotheses, improvement proposals and external validation limits.
- [x] Independently review the combined diff and run the actual CLI pipeline.
- [x] Create the dedicated tracking issue, #20. Publish the repair PR and
  record final full-suite and hosted exact-revision results in its body.
- [x] Prepare the English repair/review handoff; finalize its PR links, counts
  and hosted results after publication. Do not commit a documentation-only
  update solely to record the CI status of the preceding commit.

## Review focus

1. PDF graphics state must never silently turn hidden pixels into source artwork.
2. A successful native parity check must not compare two Python fallbacks.
3. Malformed provider text must fail one answer without losing healthy progress.
4. Invalid HTTP credentials must produce a controlled refusal and no traceback.
5. A delayed shard must not overwrite a newer canonical decision or hide changes
   to the glossary/context under a successful merge.

Each responsible task adds persistent controls for its relevant focus and
records the pre-fix failure and post-fix outcome in the final review handoff.

## Implemented findings

The linked issue and PR describe F01-F14: visible PDF extraction; native PDF
sampling (faint images, shear and soft masks); complete PDF package evidence
and known paper size; clean-only preservation; transactional multi-frame
refusal; frozen batch snapshots and shared decisions; installable native
packages; native buffer/overflow parity; empty balloon authority; Markdown
fence boundaries; provider/advisory Unicode; HTTP authentication refusal;
late MCP stdout/stderr isolation; automatic final-revision CI and native lanes.

Independent review also required a compatibility control for batch modes:
modern per-page modes merge normally, but a legacy page whose implicit mask
mode would change when canonical metadata is restored must be rebuilt first.
The canonical document, worker drafts and assets remain untouched on refusal.

Measured local gates before publication include the actual CBZ/PDF CLI
pipeline, real installed native backends, 55 native/text focused cases,
7 hotcore and 4 pixcore Rust tests, both Rust fmt/clippy checks, 68 PDF/import
regressions on PyMuPDF 1.24.3 and 2.1, full lint and actionlint. Final full-suite
counts and hosted matrix outcomes are recorded against the published SHA in
the PR and handoff, rather than being inferred from an earlier run.

## Primary research

- [GitHub required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
- [Workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Maturin mixed project layout](https://github.com/PyO3/maturin/blob/main/guide/src/project_layout.md)
- [PyMuPDF device interface discussion](https://github.com/pymupdf/PyMuPDF/discussions/3633)
- [Python constant-time comparison](https://docs.python.org/3/library/hmac.html#hmac.compare_digest)
- [CommonMark fenced blocks](https://spec.commonmark.org/0.31.2/#fenced-code-blocks)
- [Pillow frame seeking](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.seek)
- [Spec Kit workflow reference](https://github.com/github/spec-kit/blob/main/docs/reference/agentic-sdd.md)
