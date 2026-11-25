# detectcore-rs

Pure-Rust kernels for panel gutters, connected components, speech balloons,
text grouping, reading order, and stroke width. The public functions live in
[`detectcore_rs::port`](src/port.rs) and are used by `revayat-vision`.

Images are row-major byte slices with positive dimensions. Rectangles contain
`[x, y, width, height]` in pixels with nonnegative coordinates and exclusive right
and bottom edges. Integer arguments and rectangle edges must fit in signed 64 bits.
Invalid dimensions, lengths, rectangles, and parameters return an error.

The panel cutter prefers horizontal splits and uses the widest qualifying band
on that axis, with ties going to the first band. It returns no panels when the
trimmed page is smaller than the minimum leaf size. The balloon detector counts
unique in-image pixels in the eight-neighbor ring around a four-connected bright
region, including pixels along holes. Text grouping and reading rows both link
transitively. The stroke estimator treats pixels at or below the midpoint as ink
and takes the median over all horizontal and vertical runs within the crop.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p detectcore-rs
cargo fmt -p detectcore-rs --check
cargo clippy --locked -p detectcore-rs --all-targets -- -D warnings
cargo test --locked -p detectcore-rs
```

Cargo builds an `rlib` linked into the standalone CLI. Crate tests exercise
the kernels directly; run `cargo test --workspace --locked` for their pipeline
integration. Preserve buffer validation and deterministic grouping/tie behavior.
