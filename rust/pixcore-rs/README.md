# pixcore-rs

Pure-Rust pixel comparison kernels used by `revayat-vision`. The public API is
[`pixcore_rs::port`](src/port.rs).

## Functions

- `outside_mask_diff`: count changed pixels outside the mask and report the
  greatest channel difference there.
- `changed_mask_rgb`: produce a `0`/`255` mask for RGB differences above a threshold.
- `overlap_changed_pixels`: report region-pair indices and changed-pixel counts
  in their intersections.
- `outline_crossing_pixels`: count changed pixels crossing the safe lettering
  mask over the original outline.

Inputs are tightly packed row-major RGB or grayscale mask byte slices. The
kernels validate dimensions and buffer lengths before scanning. Any nonzero
mask byte is active; difference thresholds use a strict greater-than comparison.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p pixcore-rs
cargo fmt -p pixcore-rs --check
cargo clippy --locked -p pixcore-rs --all-targets -- -D warnings
cargo test --locked -p pixcore-rs
```

Cargo builds an `rlib` linked into the standalone CLI. Crate tests exercise
the Rust kernels directly; run `cargo test --workspace --locked` for artwork
preservation and typesetting/QA integration.
