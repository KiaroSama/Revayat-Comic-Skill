# AGENTS.md

Repository guide for coding agents working **on** this project. If you want to
*use* the skill to translate a comic, read `skills/revayat-comic/SKILL.md`
instead.

## What this repository is

An agent skill that translates comics into Persian and produces a finished CBZ,
PDF or folder of pages. It ships as three things from one tree:

- a **skill** — `skills/revayat-comic/`, self-contained, copyable into any
  agent's skill directory
- a **plugin** — five manifest formats: root `plugin.json` (Agent Plugins
  1.0.0), `.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`, and
  `.antigravity-plugin/`, plus root `commands/`
- a **marketplace** — `.agents/plugins/marketplace.json`,
  `.claude-plugin/marketplace.json`, and `.cursor-plugin/marketplace.json`, so
  the repo installs directly from GitHub across hosts
  itself

## Layout

```
skills/revayat-comic/
  SKILL.md          the skill; `name: revayat-comic` is the activation key
  scripts/*.py      the pipeline (see below)
  references/*.md   loaded on demand, not up front
  requirements.txt  the runtime dependency manifest
commands/           slash commands for plugin hosts
install/            install.ps1, install.sh — copy the skill into agents
tests/              pytest; fixtures are generated, never committed
evaluation/         the translation benchmark and its scorer — cases, a
                    generated page per case, and axis-by-axis scoring
```

## The pipeline

All runtime code is 100% pure Rust under `rust/` (14 workspace crates,
`edition = "2024"`, `#![forbid(unsafe_code)]`, Rust `1.100.0`):

| Crate | Role |
| --- | --- |
| `hotcore-rs`, `pixcore-rs`, `maskcore-rs`, `textcore-rs`, `detectcore-rs`, `qacore-rs`, `cleancore-rs`, `layoutcore-rs`, `packcore-rs` | nine low-level pixel, mask, layout, text, detection, QA, cleaning, and packaging kernels |
| `revayat-ir` | document IR, atomic UTF-8 I/O, stages, worksheets (`@@` protocol), glossary, batching, certification, journal, UTC run logs |
| `revayat-io` | pure-Rust CBZ (`zip`), CBR (`rars`), PDF (`lopdf` + `pdf-writer` + `hayro` with stencil/XObject pixel-budget guards), folder, and Persian RTL DOCX (`quick-xml`) |
| `revayat-vision` | detection, masking, zero-dot bubble cleaning, `cosmic-text` Vazir RTL typesetting (`>=1.38x` line height), full-page image-edit prompt builder, watermark removal, strict QA |
| `revayat-tools` | MCP stdio and concurrent loopback HTTP server (`axum`), hosted HTTPS OCR/translation clients with Bearer guards, pure-Rust Persian linter and lexicon lookup, transactional installer, synthetic eval |
| `revayat-comic-cli` | unified CLI binary (`bin/revayat-comic` / `bin/revayat-comic.exe`) |

Optional hosted providers (`ocr`, `translate`) are **off by default**: the
agent running this skill reads crops visually, and a provider's output never
overwrites a locked region or unmasked pixels.

## Rules that are load-bearing

1. **The original page is immutable.** Every page records the SHA-256 of the
   file it came from. Nothing writes to that file; a stage that needs different
   pixels writes a new one. `qa` re-hashes it and reports `source-modified`.
2. **Only masked pixels may change.** Repairs are composited as
   `original * (1 - alpha) + repaired * alpha` with `alpha <= mask`, so
   preservation holds by construction. `qa check` proves it and reports
   `artwork_pixels_changed`; on a correct run it is `0`.
3. **A mask is clipped to the balloon's interior, not its bounding box.** The
   corners of a box around an ellipse are outside the balloon. Clipping to the
   box repaints the artwork there and erases the outline crossing it —
   `masks.balloon_interior` exists because that shipped once.
4. **Every region reaches exactly one terminal state.** `pageir.region_state`
   returns `translated`, `kept_by_policy`, `dropped_false_detection`,
   `needs_review` or `unresolved` — and there is deliberately no state meaning
   "it quietly disappeared". Completeness was previously inferred from a scatter
   of fields, so a region falling between them was invisible to every gate. The
   census is reported by `qa`, not gated: `unresolved` is a strict subset of
   what `untranslated-region` already blocks on.
5. **Region ids never move.** They are allocated at detection and are what the
   worksheet, the mask filenames, the glossary and every QA finding refer to. A
   region that has been answered is `locked`, and `detect` skips its page.
6. **Never reverse Persian, and never store presentation forms.** The document
   holds logical text; shaping happens at draw time. `tests/test_typeset.py`
   asserts it.
7. **Every CLI entry point calls `ir.use_utf8_stdio()` first.** A Windows
   console defaults to a legacy code page and raises on the first Persian
   character.
8. **Write files with `ir.write_text` / `ir.write_bytes`.** They are atomic and
   use `newline=""`, so a document written on Windows still hashes the same as
   one written on Linux.
9. **Every QA code is declared in `qa.CODES` and documented in `SKILL.md`.** A
   test enforces both, so a check that emits an undeclared code, or one the
   skill has no action for, fails the build.
10. **Detection thresholds are command-line flags, not constants.** The right
   value is a property of the book. A 900-pixel web scan and a 4000-pixel
   tankobon scan disagree about what "small" means.

## Working on it

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
```

Build the standalone binary to `bin/revayat-comic.exe` (Windows) or
`bin/revayat-comic` (Linux) with `cargo build --release --locked -p revayat-comic-cli`.
CI builds and tests four 64-bit targets: Linux x64, Linux arm64, Windows x64,
and Windows arm64 (no macOS, no 32-bit, no Python).

Fixtures are drawn with plain shapes rather than real Japanese, deliberately:
the detector measures geometry and does not care which script the ink came from,
and drawing with a CJK font would make the suite depend on a font a stock CI
runner does not have.

Do not commit comic pages. They bloat the repository and the content is usually
someone else's.

Merge task feature branches into the repository's default branch after their
required checks pass, and verify the pushed result. Do not leave completed work
only on a side branch. Resolve conflicts and preserve unrelated changes; use a
pull request when branch protection requires one. Never merge failing changes.

When maintaining or using the skill, preserve page/book count, order, native
pixel resolution, aspect ratio and known PDF paper dimensions. Assess poor
source quality and use separately identified reading/enhancement copies when
helpful; never silently replace the immutable preservation baseline.

Every agent using the translation skill must write its translation, correction,
processing, QA and delivery activity log directly beside the translated output
file (inside the delivered page folder for folder output). This is a runtime
skill rule, not merely a coding-agent logging rule. Keep
`skills/revayat-comic/references/translation-log.md` and the skill's startup and
delivery gates aligned. CLI diagnostic logs alone do not fulfill this rule.

Keep the five plugin manifests and the three marketplace entries at the same `version`.
The [voice guide index](skills/revayat-comic/references/voice/index.md) records the
pinned sources and the output-language rule for the three bundled guides.

Every tracked text file must be UTF-8; CI enforces that too.

## Pure-Rust Persian shaping

`revayat-vision` shapes and orders Persian directly via `cosmic-text` (HarfBuzz
and FriBidi) with bundled Vazir TTF fonts (`Regular`, `Medium`, `Bold`). No
external `libraqm`, FriBidi DLL, or Python fallback is required on Linux or
Windows, and both U+0654 (ezafe hamza) and U+200C (ZWNJ) are preserved cleanly.
