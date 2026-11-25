# maskcore-rs

Pure-Rust kernels for balloon flood fill, square erosion and dilation,
Voronoi lobe partitioning, and perimeter contour filtering. The public API is
[`maskcore_rs::port`](src/port.rs), used by `revayat-vision`.

Masks are row-major bytes with positive dimensions. Erosion and dilation take
binary masks and clip their square windows to the image. Flood fill checks
cardinal neighbors; it rejects a pixel if any cardinal neighbor differs in luma
by at least `grad_thresh`. Lobe partitions use inclusive rectangles, center
coordinates `x + w/2` and `y + h/2`, and the input order for exact ties. A seam
starts between adjacent owners and widens through active pixels only. Perimeter
filtering returns two binary masks, `(kept, stripped)`, and strips a component
only if it touches the border and meets both the area and either span cutoff.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p maskcore-rs
cargo fmt -p maskcore-rs --check
cargo clippy --locked -p maskcore-rs --all-targets -- -D warnings
cargo test --locked -p maskcore-rs
```

Cargo builds an `rlib` linked into the standalone CLI. Crate tests exercise
the Rust kernels directly; `cargo test --workspace --locked` covers their use
in balloon detection, cleaning, and typesetting. Preserve all geometry and
buffer-length validation when changing the kernels.
