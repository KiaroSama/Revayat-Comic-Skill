# packcore-rs

Optional native kernels for comic archives and packed RGB pages. The `packcore`
dispatcher loads the installed wheel when available. Set `REVAYAT_PACKCORE=python`
before import to use the dependency-free reference implementation.

- `natural_sort_order` returns original indices, compares ASCII, Persian and
  Arabic-Indic digit runs by value, then uses the raw filename and index to
  break ties. Only ASCII letters are case-folded.
- `validate_page_dimensions` returns invalid row indices. Malformed rows and
  invalid bounds raise `ValueError`.
- `compute_pdf_page_layout` returns width and height in points, effective DPI,
  and a uniform scale no greater than one. It rejects non-finite or zero
  intermediate or final sizes.
- `analyze_rgb_page` returns a 32-bit FNV-1a checksum, the luma range, the mean
  luma times 100 rounded down, and the number of pixels with luma below 245.
- `compute_grayscale_histogram` counts all 256 integer luma levels.
- `diff_raster_tiles` returns zero-based tile coordinates in row-major order,
  the number of changed pixels, and the largest channel delta. A pixel counts
  only when the delta exceeds the given tolerance (0 through 255).

Raster functions take tightly packed row-major RGB `bytes` and positive integer
width and height. The bridge borrows those buffers directly. If you regenerate
it with `rust-anything refresh`, preserve the borrowed buffers and validation.

## Build and verify

Use Python 3.12 or later, Rust 1.100.0 or later, and a platform linker. From the
repository root, run these commands in a disposable virtual environment:

```console
python -m pip install ./rust/packcore-rs
cargo fmt --manifest-path rust/packcore-rs/Cargo.toml --check
cargo clippy --manifest-path rust/packcore-rs/Cargo.toml --locked -- -D warnings
cargo test --manifest-path rust/packcore-rs/Cargo.toml --locked
python -m pytest -q tests/test_packcore_parity.py
```

Maturin builds `packcore_rs._native`. With `skills/revayat-comic/scripts` on
`PYTHONPATH`, assert that `packcore.BACKEND == "rust"` before the parity run to
verify that it exercises the wheel. Keep migration metadata and recordings local.
