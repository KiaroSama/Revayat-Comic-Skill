# textcore-rs

Pure-Rust Persian text handling and balloon line-breaking kernels. The public
functions live in [`textcore_rs::port`](src/port.rs) and are used by the IR and
vision crates.

- `starts_with_latin_in_persian` and `ensure_rli_pdi` follow the legacy ASCII-leading sentence rules, including its protected code, addresses, and abbreviations.
- `ensure_rlm_rli_pdi` locks paragraph direction on Persian-bearing lines and leaves fenced code intact. The original standalone paragraph helper did not protect fences.
- `normalize_persian_text` protects code, addresses, and versions. Prefix joins use recognized conjugated verbs. Bare plural particles need an explicit joiner or a following object marker or ezafe, so the normalizer does not turn a warning into a plural.
- `balanced_wrap_lines` uses consecutive bands from the first. It minimizes squared unused width on occupied bands and prefers the earliest break on a tie. It returns half-open word ranges or an empty list if the words cannot fit. Words must have positive widths; space and band widths may be zero. The band list cannot be empty.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p textcore-rs
cargo fmt -p textcore-rs --check
cargo clippy --locked -p textcore-rs --all-targets -- -D warnings
cargo test --locked -p textcore-rs
```

Cargo builds an `rlib` linked into the standalone CLI. Crate tests exercise
the functions directly; run `cargo test --workspace --locked` to check their
use in worksheets, normalization, wrapping, and rendered Persian text.
