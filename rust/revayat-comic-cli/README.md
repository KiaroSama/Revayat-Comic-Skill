# Revayat Comic CLI

This standalone executable runs the existing Rust kernels without Python. It does not run the full comic translation workflow.

## Build and stage

Build from the repository root with Rust 1.100.0 and its host linker. On Windows, use PowerShell 7 and the MSVC build tools:

```powershell
cargo build --release --locked --manifest-path rust/revayat-comic-cli/Cargo.toml
New-Item -ItemType Directory -Force bin | Out-Null
Copy-Item rust/revayat-comic-cli/target/release/revayat-comic.exe bin/revayat-comic.exe
./bin/revayat-comic.exe doctor --json
```

On Linux:

```sh
cargo build --release --locked --manifest-path rust/revayat-comic-cli/Cargo.toml
mkdir -p bin
cp rust/revayat-comic-cli/target/release/revayat-comic bin/revayat-comic
./bin/revayat-comic doctor --json
```

## Commands

| Command | Standard input | Standard output |
|---|---|---|
| `--help`, `--version` | None | Usage or executable version. |
| `doctor [--json]` | None | Version, overall status, and one result per kernel. JSON fields are `version`, `ok`, and `kernels`. |
| `normalize-persian` | UTF-8 text | Normalized UTF-8 text in logical order. Protected spans and newline behavior follow the existing text kernel. |
| `wrap-lines` | JSON object with `word_widths`, `space_width`, and `band_widths` | Zero-based `[start, end)` word-index pairs, or `[]` if the words do not fit. |
| `sort-pages` | JSON array of nonempty names without NUL characters | All original names in natural order, including duplicates. The command does not touch the named files. |
| `check-geometry` | JSON object with `dimensions`, `max_aspect_ratio`, `min_edge`, and `max_pixels` | JSON with boolean `ok` and zero-based `invalid_pages`. |

For example, in PowerShell:

```powershell
'{"word_widths":["5","5"],"space_width":"1","band_widths":["11"]}' | ./bin/revayat-comic.exe wrap-lines
'["page10.png","page2.png","page2.png"]' | ./bin/revayat-comic.exe sort-pages
'{"dimensions":[[1200,1800]],"max_aspect_ratio":2,"min_edge":100,"max_pixels":4000000}' | ./bin/revayat-comic.exe check-geometry
```

Each invocation accepts one input up to 1 MiB. `wrap-lines` accepts up to 4,096 word widths and 1 to 128 band widths. Supply widths as strings of 1 to 128 ASCII digits. Words must be positive; spaces and bands can be zero. `sort-pages` and `check-geometry` each accept up to 4,096 entries. Geometry takes `[width, height]` pairs, positive integers up to `2^53` (including `min_edge` and `max_pixels`), and a finite `max_aspect_ratio` of at least `1`.

Exit `0` means success. Exit `1` means a runtime failure, a failed `doctor` check, or invalid page geometry. Geometry still prints its report when pages fail validation. Exit `2` means invalid arguments or malformed, non-UTF-8, or oversized input. Diagnostics go to stderr.

## Logs

A staged `bin/revayat-comic` or `bin/revayat-comic.exe` writes logs beside `bin/`. For other layouts the executable writes `logs/` inside its own directory. Changing your working directory does not change the log location.

Each run writes a UTF-8 file named `logs/revayat-comic_YYYY-MM-DD_HH-mm-ss_UTC.log`. Runs that collide on the same UTC timestamp get suffixes such as `_01` before `.log`. `INFO` records startup and successful completion; `ERROR` records nonzero outcomes. Logs include the command, version, run ID, exit code, and duration. They exclude arguments, raw input, filenames, and credentials. On Unix, the program creates logs with owner-only permissions. On Windows, keep the installation under a directory with access restricted to the intended users.

If file logging fails, the CLI reports it on stderr and leaves command output and exit status unchanged. The CLI never rotates or deletes logs. Remove old logs when you no longer need them, and review a log before attaching it to a support report.

## Test

```sh
cargo test --manifest-path rust/revayat-comic-cli/Cargo.toml --locked
```
