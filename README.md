<div align="center">

# Revayat Comic (روایت کمیک)

**Translate manga, manhwa, manhua and Western comics into Persian, and deliver a lossless CBZ or PDF with verified artwork preservation.**

[![GitHub Actions CI workflow status](https://img.shields.io/github/actions/workflow/status/KiaroSama/Revayat-Comic-Skill/ci.yml?branch=main&style=flat-square&label=CI&color=16a34a)](.github/workflows/ci.yml)
[![GNU General Public License v3.0 or later](https://img.shields.io/github/license/KiaroSama/Revayat-Comic-Skill?style=flat-square&color=2563eb)](LICENSE)
[![Latest GitHub version tag](https://img.shields.io/github/v/tag/KiaroSama/Revayat-Comic-Skill?style=flat-square&label=version&color=ea580c)](#releases-and-tags)
[![Latest GitHub release](https://img.shields.io/github/v/release/KiaroSama/Revayat-Comic-Skill?style=flat-square&label=release&color=dc2626)](https://github.com/KiaroSama/Revayat-Comic-Skill/releases)
[![Automated Cargo workspace tests](https://img.shields.io/badge/tests-Cargo%20workspace-0d9488?style=flat-square)](#development)
[![Rust 1.100.0 pinned toolchain](https://img.shields.io/badge/Rust-1.100.0-8b5cf6?style=flat-square)](rust-toolchain.toml)
[![Supported platforms: Linux and Windows 64-bit x64 and arm64](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%28x64%20%7C%20arm64%29-0891b2?style=flat-square)](.github/workflows/ci.yml)
[![Install via five plugin formats or standalone CLI binary](https://img.shields.io/badge/install-5%20plugins%20%7C%20CLI%20binary-4f46e5?style=flat-square)](#install)
[![Documentation in English and Persian](https://img.shields.io/badge/docs-English%20%7C%20Persian-0284c7?style=flat-square)](README.fa.md)
[![GitHub repository size](https://img.shields.io/github/repo-size/KiaroSama/Revayat-Comic-Skill?style=flat-square&color=ca8a04)](#development)
[![Pure Rust runtime with zero Python dependencies](https://img.shields.io/badge/runtime-pure%20Rust%20%7C%20zero%20Python-059669?style=flat-square)](#architecture)
[![Six-stage multi-agent workflow and cropped image editing](https://img.shields.io/badge/workflow-6%20agents%20%7C%20crop%20edits-7c3aed?style=flat-square)](skills/revayat-comic/references/multi-agent-workflow.md)
[![Bundled Humanizer 4.0 and Persian voice guides](https://img.shields.io/badge/voice-Humanizer%204.0%20%7C%20Persian-b45309?style=flat-square)](skills/revayat-comic/references/voice/index.md)
[![Support donations](https://img.shields.io/badge/Support-donations-d04a9a?style=flat-square)](#donate)

[English](README.md) · [فارسی](README.fa.md) · [Skill spec](skills/revayat-comic/SKILL.md) · [Multi-agent workflow](skills/revayat-comic/references/multi-agent-workflow.md) · [On-art crop edits](skills/revayat-comic/references/fullpage-image-edit.md)

</div>

Revayat Comic is a pure Rust CLI binary (`revayat-comic`) paired with an AI agent skill for translating comics into natural Persian. It accepts CBZ, CBR, PDF, image folders, and single pages, detects panels and balloons, lets you review text directly from rendered crops, removes source lettering inside verified masks, typesets right-to-left Persian with bundled Vazir fonts, checks every page against pixel and layout gates, and exports a lossless CBZ, PDF, image folder, or bilingual review DOCX.

## What makes v2.0 different

- Pure Rust from input to export, compiled with Rust `1.100.0` (`edition = "2024"`, `#![forbid(unsafe_code)]`) and zero Python, PyMuPDF, OpenCV, or external unrar binaries at runtime.
- Pure Rust PDF inspection, rasterization, and lossless PDF writing via `lopdf`, `pdf-writer`, and `hayro`, including stencil-mask and Form XObject pixel-budget checks before raster allocation.
- Pure Rust CBR (`rars`), CBZ (`zip`), and Persian RTL DOCX (`quick-xml`) support.
- Real Persian shaping and bidi layout on every platform via `cosmic-text` (HarfRust shaping, `unicode-bidi`, and Swash rasterization) with bundled Vazir TTF fonts (`Regular`, `Medium`, `Bold`), at least `1.38x` line spacing, zero-dot interior bubble sweeps, and non-overlapping text guards.
- On-art crop edits (`fullpage-prompt`) for covers, speedlines, titles and sound effects. Empty the speech balloons, send a tight crop with the verified source text and exact Persian replacement, then paste the approved lettering back at the original coordinates.
- Six-stage multi-agent workflow with reusable prompt templates for initial translation, typesetting, review, application, recheck and fixing, and final delivery, plus series canon lookup before drafting.

## Architecture

The workspace has 14 crates under `rust/`:

- Core kernels: `hotcore-rs`, `pixcore-rs`, `maskcore-rs`, `textcore-rs`, `detectcore-rs`, `qacore-rs`, `cleancore-rs`, `layoutcore-rs`, `packcore-rs`.
- Domain crates: `revayat-ir` (document state, worksheets, glossary, batching, atomic journaled I/O, UTC run logs), `revayat-io` (CBZ, CBR, PDF, folder, and bilingual DOCX), `revayat-vision` (detection, masking, bubble cleaning, `cosmic-text` typesetting, full-page edit prompt builder, strict QA), and `revayat-tools` (MCP stdio and loopback HTTP server, hosted OCR/translation clients with HTTPS Bearer guards, Persian linter and lexicon lookup, transactional installer, evaluation harness).
- Binary entry point: `revayat-comic-cli`, built to `bin/revayat-comic.exe` on Windows and `bin/revayat-comic` on Linux.

## Supported platforms

Prebuilt release binaries and CI cover four 64-bit targets:

| OS | Architecture | Target triple |
| --- | --- | --- |
| Linux | x64 | `x86_64-unknown-linux-gnu` |
| Linux | arm64 | `aarch64-unknown-linux-gnu` |
| Windows | x64 | `x86_64-pc-windows-msvc` |
| Windows | arm64 | `aarch64-pc-windows-msvc` |

32-bit platforms and macOS are not built by default.

## Releases and Tags

[GitHub Releases](https://github.com/KiaroSama/Revayat-Comic-Skill/releases) has a ZIP for each supported 64-bit target. Extract the standalone `revayat-comic` (Linux) or `revayat-comic.exe` (Windows). For source snapshots, see the [Git tags](https://github.com/KiaroSama/Revayat-Comic-Skill/tags).

## Install

### Prerequisites

- Put the extracted binary on `PATH` when using an agent plugin, or place it in `bin/` at the repository root for the examples below.
- To build from source: Rust `1.100.0` (pinned in `rust-toolchain.toml`), `git`, and PowerShell 7 (`pwsh`) on Windows or Bash on Linux.

### Plugin install

The release ZIP contains the standalone CLI. Install the skill from the repository's plugin manifests or with the [skill installer](install/README.md), and keep `revayat-comic` on `PATH`.

The repository has v2.0.1 manifests for five plugin systems: Agent Plugins (`plugin.json` and `.agents/plugins/marketplace.json`), Claude Code (`.claude-plugin/`), Codex (`.codex-plugin/`), Cursor (`.cursor-plugin/`), and Antigravity (`.antigravity-plugin/`).

In Claude Code:

```text
/plugin marketplace add KiaroSama/Revayat-Comic-Skill
/plugin install revayat-comic@revayat-comic-skill
```

### Build from source

Windows (PowerShell 7):

```powershell
cargo build --release --locked -p revayat-comic-cli
New-Item -ItemType Directory -Force -Path bin | Out-Null
Copy-Item target\release\revayat-comic.exe bin\revayat-comic.exe -Force
.\bin\revayat-comic.exe doctor --json
```

Linux:

```bash
cargo build --release --locked -p revayat-comic-cli
mkdir -p bin
cp target/release/revayat-comic bin/revayat-comic
./bin/revayat-comic doctor --json
```

### Bundled voice guides

Revayat Comic bundles three local writing guides under `skills/revayat-comic/references/voice/`:

- `persian` for comic dialogue, narration, captions, sound effects, and Persian prose (`revayat-comic voice lint` and `revayat-comic voice lookup`).
- `humanizer` v4.0.0 (`revayat-comic:humanizer`) for English documentation and editorial prose.
- `great-russian` (`revayat-comic:great-russian`) for Russian prose when requested.

See [the voice index](skills/revayat-comic/references/voice/index.md) for license attribution and upstream commit pins.

## Usage

### Pipeline commands

`import` creates `comic.json` and stores the original pages in `pages/`. Later stages write their own files and leave those originals untouched.

Windows (PowerShell 7):

```powershell
.\bin\revayat-comic.exe import chapter.cbz --out .\work --direction rtl
.\bin\revayat-comic.exe detect --doc .\work\comic.json
.\bin\revayat-comic.exe mask --doc .\work\comic.json
.\bin\revayat-comic.exe crops --doc .\work\comic.json
.\bin\revayat-comic.exe worksheet build --doc .\work\comic.json --worksheets .\work\worksheets
```

After filling the worksheets (manually or through the six-stage agent workflow):

```powershell
.\bin\revayat-comic.exe worksheet merge --doc .\work\comic.json --worksheets .\work\worksheets
.\bin\revayat-comic.exe glossary check --doc .\work\comic.json
.\bin\revayat-comic.exe falint check --doc .\work\comic.json
.\bin\revayat-comic.exe clean --doc .\work\comic.json
.\bin\revayat-comic.exe typeset --doc .\work\comic.json
.\bin\revayat-comic.exe qa check --doc .\work\comic.json --strict
.\bin\revayat-comic.exe export --doc .\work\comic.json --out .\work\chapter-fa.cbz
.\bin\revayat-comic.exe qa package --doc .\work\comic.json --package .\work\chapter-fa.cbz
```

`export` uses the output path to select the format: `.cbz`, `.pdf`, or a folder.

Additional commands:

- `fullpage-prompt --doc <comic.json> --page <id>`: print the page-level manifest for on-art crop edits to stdout. The default model is `antigravity/gemini-3.1-flash-image`.
- `review-docx --doc <comic.json> --out <review.docx>`: export an RTL Persian bilingual review document.
- `watermark --doc <comic.json> ...`: mark an exact authorized watermark rectangle for removal.
- `batch plan|merge|status`: split long chapters into shards and merge them safely.
- `voice lint <file> --check --style` checks Persian prose; `voice lookup <text>` searches the terminology glossary.
- `serve --stdio` starts the MCP server. For loopback HTTP, set `REVAYAT_HTTP_TOKEN` and run `serve --http 127.0.0.1:8765`.
- `ocr` and `translate`: optional hosted model helpers (require explicit HTTPS endpoint and Bearer token).
- `install`: transactional skill installer.
- `eval`: synthetic fixture generator and scorer.

### Six-stage multi-agent workflow

For full chapters, follow [references/multi-agent-workflow.md](skills/revayat-comic/references/multi-agent-workflow.md):

1. Initial translation (`ترجمه اولیه`): look up official series character names and terminology online first, then translate into natural spoken Persian.
2. Typesetting and layout (`صفحه آرایی`): assign line breaks, punctuation, font scales, and on-art edit zones.
3. Review (`بازبینی`): check fidelity against source crops, terminology consistency, and Persian mechanics.
4. Apply translation (`اعمال ترجمه`): merge worksheets, run `clean` and `typeset`, and paste approved crop edits back at their original coordinates.
5. File recheck and fix (`چک مجدد فایل و اصلاح مشکلات`): inspect every rendered page visually and run `qa check --strict`, fixing all issues in one batch.
6. Final review and delivery (`بازبینی نهایی و تحویل`): export lossless CBZ and PDF and verify outputs with `qa package`.

### Runtime logs

Pipeline commands write UTF-8 logs under `logs/revayat-comic_YYYY-MM-DD_HH-mm-ss_UTC.log`. The `logs/` folder sits next to `bin/` or alongside a standalone binary whose directory is not named `bin`. CLI logs contain command metadata and exit status. Review the log before sharing it with a bug report.

## Documentation

- [SKILL.md](skills/revayat-comic/SKILL.md): full agent workflow and QA codes
- [references/multi-agent-workflow.md](skills/revayat-comic/references/multi-agent-workflow.md): six-stage agent roles and prompt templates
- [references/fullpage-image-edit.md](skills/revayat-comic/references/fullpage-image-edit.md): on-art crop editing, paste-back, and targeted edge repairs
- [references/translation-policy.md](skills/revayat-comic/references/translation-policy.md): translation rules, spoken register, and glossary discipline
- [references/persian-typesetting.md](skills/revayat-comic/references/persian-typesetting.md): RTL shaping, line spacing, and balloon fitting
- [references/detection.md](skills/revayat-comic/references/detection.md): region detection thresholds and manual corrections
- [references/artwork-preservation.md](skills/revayat-comic/references/artwork-preservation.md): masks, cleaning tiers, and pixel QA
- [references/sound-effects.md](skills/revayat-comic/references/sound-effects.md) and [references/sfx-glossary.md](skills/revayat-comic/references/sfx-glossary.md): SFX handling and Persian glossary
- [references/serving.md](skills/revayat-comic/references/serving.md): MCP stdio and loopback HTTP server
- [references/recovery.md](skills/revayat-comic/references/recovery.md): atomic export journal and recovery
- [AGENTS.md](AGENTS.md): contributor and agent repository guide

## Development

Run the full check suite locally with Rust `1.100.0`:

```powershell
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
```

No real copyrighted comic pages are stored in this repository. All test suites generate synthetic fixtures at runtime. GitHub Actions builds and verifies all four 64-bit Linux and Windows targets, checks plugin manifest versions, and runs CodeQL, Gitleaks, Semgrep, and dependency review.

## Author

Author: Kiaro Sama
GitHub: https://github.com/KiaroSama

## License

Copyright (c) Kiaro Sama. Released under the [GNU General Public License v3.0 or later](LICENSE).

## Donate

If this project helps you, donations are appreciated.

| Currency | Network | Address |
| --- | --- | --- |
| Bitcoin (BTC) | Bitcoin | `bc1qmth5m03pu5hujw5xw5jmywam3jj3sqwqupesdt` |
| USDT, BNB, USDC, etc. | BEP20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| USDT, TRX, USDC, etc. | TRC20 | `TWBA3xFTqgZAeAYMxqo85xWnzvty3DcAhw` |
| Ethereum (ETH) | ERC20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| TON | TON | `UQCN8Umo_OfOWqImZetQsrNStPcmLkMAKajFyiCOhso23NDb` |
| Litecoin (LTC) | LTC | `ltc1qntqnnrunadurnw4cshv3qgspywrueyyeyngwuy` |
| Solana (SOL) | Solana | `7B2wkczUjmkDhETwQuknBL8sUsbuV7nErxc317TmQuwR` |
| Polygon (POL) | Polygon | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
