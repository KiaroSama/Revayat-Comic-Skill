# layoutcore-rs

Optional layout kernels for shaped speech balloons. The Python reference in
`skills/revayat-comic/scripts/layoutcore/kernels.py` has no third-party
requirements. Set `REVAYAT_LAYOUTCORE=python` before importing `layoutcore` to
force the fallback.

Masks are packed, row-major `bytes` with positive dimensions. Any nonzero byte
is active. Spans and word slices use exclusive right/end indices. Each line band
intersects all covered rows before applying horizontal padding, so shifted spans
do not admit text that will cross a wall. Paragraph wrapping minimizes summed
squared slack, including the last line. Equal scores favor placements closer to
the vertical center; if still tied, the topmost placement wins.

Font harmonization uses the lower area-weighted median and never enlarges text.
Ink closer to a wall than the threshold violates clearance; equality passes.
The clearance kernel reports the first worst pixel in row-major order. Rectangle
ties favor the topmost, then leftmost position.

## Build and verify

Use Python 3.12 or later, Rust 1.100.0 or later, and a platform linker. From the
repository root, run these commands in the intended Python environment:

```console
python -m pip install ./rust/layoutcore-rs
cargo fmt --manifest-path rust/layoutcore-rs/Cargo.toml --check
cargo clippy --manifest-path rust/layoutcore-rs/Cargo.toml --locked -- -D warnings
cargo test --manifest-path rust/layoutcore-rs/Cargo.toml --locked
python -m pytest -q tests/test_layoutcore_parity.py
```

Maturin installs `layoutcore_rs._native` through PEP 517. To require the native
backend during parity tests, set `REVAYAT_TEST_LAYOUTCORE_RUST=1`. The PyO3
boundary borrows mask buffers and validates exact Python types. Preserve both if
you regenerate the bridge with `rust-anything refresh`.
