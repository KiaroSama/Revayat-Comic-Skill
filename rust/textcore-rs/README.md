# textcore-rs

This optional PyO3 extension accelerates Persian text handling and balloon line breaking. `skills/revayat-comic/scripts/textcore/kernels.py` is the Python reference.

- `starts_with_latin_in_persian` and `ensure_rli_pdi` follow the legacy ASCII-leading sentence rules, including its protected code, addresses, and abbreviations.
- `ensure_rlm_rli_pdi` locks paragraph direction on Persian-bearing lines and leaves fenced code intact. The original standalone paragraph helper did not protect fences.
- `normalize_persian_text` protects code, addresses, and versions. Prefix joins use recognized conjugated verbs. Bare plural particles need an explicit joiner or a following object marker or ezafe, so the normalizer does not turn a warning into a plural.
- `balanced_wrap_lines` uses consecutive bands from the first. It minimizes squared unused width on occupied bands and prefers the earliest break on a tie. It returns half-open word ranges or an empty list if the words cannot fit. Words must have positive widths; space and band widths may be zero. The band list cannot be empty.

## Build and install

Use Python 3.12 or later, Rust 1.97.0 or later, and a platform linker. From the repository root in the Python environment that runs the skill:

```console
python -m pip install ./rust/textcore-rs
```

The wheel provides `textcore_rs._native`. `textcore.BACKEND` is `rust` when the wheel loads and `python` when the reference is in use. `cargo build` alone does not install a Python package. A bridge refresh can regenerate its bindings; preserve the PyO3 integer and nested list adapters if you refresh it.

## Verify

From the repository root:

```console
cargo fmt --manifest-path rust/textcore-rs/Cargo.toml --check
cargo clippy --manifest-path rust/textcore-rs/Cargo.toml --locked -- -D warnings
cargo test --manifest-path rust/textcore-rs/Cargo.toml --locked
python -m pytest -q tests/test_textcore_parity.py
```

To verify the extension, run the Python tests in an environment where you installed the wheel. A fallback-only run does not exercise PyO3. For bridge verification, use `rust-anything record rust/textcore-rs` with focused inputs, then run `build`, `diff`, `bench`, and `gate` on the same crate directory.
