# Revayat Comic CLI 2.0.0

`revayat-comic` imports comic pages, prepares translation worksheets, sets Persian lettering in the cleaned artwork, and exports CBZ, PDF, or page images. The executable uses Rust for the local pipeline and includes the Vazir fonts and Persian terminology data. Hosted OCR and translation are optional.

## Build and stage

Use Rust 1.100.0 and the host linker. The workspace targets 64-bit Windows and Linux on x64 and arm64. Build from the repository root.

Windows, in PowerShell 7 with the MSVC build tools:

```powershell
cargo build --release --locked -p revayat-comic-cli
New-Item -ItemType Directory -Force bin | Out-Null
Copy-Item target/release/revayat-comic.exe bin/revayat-comic.exe
./bin/revayat-comic.exe doctor --json
```

Linux:

```sh
cargo build --release --locked -p revayat-comic-cli
mkdir -p bin
cp target/release/revayat-comic bin/revayat-comic
./bin/revayat-comic doctor --json
```

## Translate a chapter

Run `revayat-comic <command> --help` for flags. The examples assume `revayat-comic` is on your PATH; otherwise use the executable path above.

```sh
revayat-comic import chapter.cbz --out work --source-language ja --direction rtl
revayat-comic detect --doc work/comic.json
revayat-comic mask --doc work/comic.json
revayat-comic crops --doc work/comic.json
revayat-comic worksheet build --doc work/comic.json
```

Keep each worksheet's fingerprint and region IDs. Fill in the source text and the Persian `fa:` fields, then save a sibling `<page>.done.txt` for each page. Use `worksheet status` to inspect the handoff before merging.

```sh
revayat-comic worksheet merge --doc work/comic.json
revayat-comic falint fix --doc work/comic.json
revayat-comic clean --doc work/comic.json --bubbles-only
revayat-comic typeset --doc work/comic.json
revayat-comic qa check --strict --doc work/comic.json
revayat-comic export --doc work/comic.json --out translated.cbz --review-docx review.docx
revayat-comic qa package --doc work/comic.json --package translated.cbz
```

Use `.pdf` for a PDF or a directory path for page images. Export checks the original and rendered artifacts against their committed digests. Use `--draft` only for an unfinished edition. `review-docx --doc work/comic.json --out review.docx` creates the bilingual review file separately.

- `glossary scan` adds recurring terms and `glossary check` reports drift. Both take `--doc`. `falint check` reports text issues without writing.
- `watermark --doc work/comic.json --box x,y,w,h` marks a fixed erase rectangle. Run `mask` again before `clean`; omit `--bubbles-only` to process the watermark.
- `fullpage-prompt --doc work/comic.json --page p0001` emits the full-page edit manifest after cleaning. It does not contact an image service. Use `<page>.png` filenames for `typeset --external-dir`; imported edits are confined to the lettering mask and remain unverified until the lettering is reviewed. The CLI will not certify them as locally fitted text.
- `context --doc work/comic.json --page p0001` prints page context. `ocr` and `translate` use an OpenAI-compatible endpoint configured through `REVAYAT_API_BASE`, `REVAYAT_API_KEY`, and the relevant `REVAYAT_OCR_MODEL` or `REVAYAT_TRANSLATION_MODEL` variable. Set `--model` to override the model. Hosted transcription and translation send source material to that endpoint. Local manga-OCR is not included.
- `batch plan --doc work/comic.json --shards 2`, `batch status --batch <dir>`, and `batch merge --doc work/comic.json --batch <dir>` manage local translation shards.
- `voice lint --check --style lines.txt`, `voice lookup <text>`, `install --repo <checkout> --base <target> --agent <name>`, and `eval build --out <dir>` / `eval score <answers.json>` run the corresponding support tools.

## Clients

`revayat-comic serve --stdio` uses newline-delimited MCP JSON-RPC. Each tool's `arguments.args` array contains the same flags and values as the CLI subcommand. `revayat-comic serve --http 127.0.0.1:8080` runs loopback REST. Set `REVAYAT_HTTP_TOKEN` before starting it and send that value in `X-Revayat-Token`. Use `GET /tools` or `POST /tools/<stage>` with `{"args":[...]}`.

## Kernel commands

| Command | Standard input | Standard output |
|---|---|---|
| `doctor [--json]` | None | Version, overall status and one result per kernel. JSON fields are `version`, `ok`, and `kernels`. |
| `normalize-persian` | UTF-8 text | Normalized text in logical order. |
| `wrap-lines` | `{"word_widths":["5","5"],"space_width":"1","band_widths":["11"]}` | Zero-based `[start, end)` word-index pairs, or `[]` when the words do not fit. |
| `sort-pages` | `["page10.png","page2.png","page2.png"]` | Names in natural order, including duplicates. Does not touch files. |
| `check-geometry` | `{"dimensions":[[1200,1800]],"max_aspect_ratio":2,"min_edge":100,"max_pixels":4000000}` | JSON with `ok` and zero-based `invalid_pages`. |

The kernel commands cap stdin at 1 MiB. `wrap-lines` accepts 4,096 word widths and up to 128 band widths. Supply widths as strings of up to 128 ASCII digits. `sort-pages` and `check-geometry` each accept at most 4,096 entries.

## Status and logs

Exit `0` means success; exit `1` means a check reported findings or a kernel failed. Exit `2` means invalid arguments or malformed kernel input. Exit `4` means a pipeline stage could not finish. Commands emit machine-readable reports to stdout when available and diagnostics to stderr.

The executable creates UTF-8 `logs/revayat-comic_YYYY-MM-DD_HH-mm-ss_UTC.log` files beside its directory, or one level above if installed in `bin/`. Logs record command names, versions, results, and duration, without arguments, source text or credentials. If file logging fails, the CLI reports it on stderr and preserves the command's exit status. It does not rotate logs; remove old logs when you no longer need them.

## Test

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
```
