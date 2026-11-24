# detectcore-rs

Optional PyO3 kernels for panel gutters, connected components, speech balloons,
text grouping, reading order, and stroke width. The `detectcore` dispatcher uses
Rust when the wheel is installed and otherwise uses its standard-library Python
reference. Set `REVAYAT_DETECTCORE=python` before import to force the reference.

Images are row-major `bytes` with positive dimensions. Rectangles are lists of
`[x, y, width, height]` in pixels with nonnegative coordinates and exclusive right
and bottom edges. Integer arguments and rectangle edges must fit in signed 64 bits.
Invalid dimensions, lengths, rectangles, and parameters raise `ValueError`.

The panel cutter prefers horizontal splits and uses the widest qualifying band
on that axis, with ties going to the first band. It returns no panels when the
trimmed page is smaller than the minimum leaf size. The balloon detector counts
unique in-image pixels in the eight-neighbor ring around a four-connected bright
region, including pixels along holes. Text grouping and reading rows both link
transitively. The stroke estimator treats pixels at or below the midpoint as ink
and takes the median over all horizontal and vertical runs within the crop.

## Build and install

Use Python 3.12 or later, Rust 1.97.0 or later, and a platform linker. Run from
this repository's root in the Python environment that runs Revayat Comic:

```console
python -m pip install ./rust/detectcore-rs
```

Maturin installs `detectcore_rs._native` through PEP 517. A plain Cargo build
only builds the Rust library. The PyO3 bridge borrows pixel buffers and releases
the GIL for the kernel calls.

## Verify

```console
cargo fmt --manifest-path rust/detectcore-rs/Cargo.toml --check
cargo clippy --manifest-path rust/detectcore-rs/Cargo.toml --locked -- -D warnings
cargo test --manifest-path rust/detectcore-rs/Cargo.toml --locked
python -c "import detectcore_rs"
python -m pytest -q tests/test_detectcore_parity.py
```

Install the wheel before running native parity tests so none are skipped.
The `rust-anything` replay recordings and bridge metadata are local artifacts.
If you refresh the bridge, retain the borrowed-byte and strict-validation adapters.
