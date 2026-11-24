# maskcore-rs

Optional PyO3 kernels for balloon flood fill, square erosion and dilation,
Voronoi lobe partitioning, and perimeter contour filtering. The reference in
`skills/revayat-comic/scripts/maskcore/kernels.py` runs without the extension.
Set `REVAYAT_MASKCORE=python` before importing `maskcore` to force that path.

Masks are row-major bytes with positive dimensions. Erosion and dilation take
binary masks and clip their square windows to the image. Flood fill checks
cardinal neighbors; it rejects a pixel if any cardinal neighbor differs in luma
by at least `grad_thresh`. Lobe partitions use inclusive rectangles, center
coordinates `x + w/2` and `y + h/2`, and the input order for exact ties. A seam
starts between adjacent owners and widens through active pixels only. Perimeter
filtering returns two binary masks, `(kept, stripped)`, and strips a component
only if it touches the border and meets both the area and either span cutoff.

## Build and install

Use Python 3.12 or later, Rust 1.100.0 or later, and a platform linker. Run from
this repository's root in the Python environment that runs Revayat Comic:

```console
python -m pip install ./rust/maskcore-rs
```

Build with `--no-default-features` for a pure Rust `rlib`. The `port` module does not require Python.

The PEP 517 build uses Maturin and installs `maskcore_rs._native`. A plain
`cargo build` does not install the Python package. The Rust bridge borrows
image buffers and only allocates Python objects for the outputs. If you
regenerate the bridge with `rust-anything refresh`, preserve that adaptation.

## Verify

```console
cargo fmt --manifest-path rust/maskcore-rs/Cargo.toml --check
cargo clippy --manifest-path rust/maskcore-rs/Cargo.toml --locked -- -D warnings
cargo test --manifest-path rust/maskcore-rs/Cargo.toml --locked
python -c "import maskcore_rs"
python -m pytest -q tests/test_maskcore_parity.py
```

Native parity requires the wheel and must run without native tests being skipped.
For migration checks, run `rust-anything record`, `build`, `diff`, `bench`, and
`gate` on `rust/maskcore-rs`. The recordings and bridge metadata are local build
artifacts and are not included in the wheel.
