# hotcore-rs

Pure-Rust geometry and mask-scanning kernels used by the comic pipeline.
The public API is [`hotcore_rs::port`](src/port.rs).

## Functions

- `box_gap`: distance between rectangle edges, returning zero for overlap.
- `cluster_boxes`: group nearby seed rectangles transitively.
- `row_widths`: scan active mask extents by row.
- `band_span`: determine the usable horizontal span for a row band.
- `body_bounds`: locate a usable body inside a mask.
- `candidate_bodies`: enumerate candidate body rectangles for layout.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p hotcore-rs
cargo fmt -p hotcore-rs --check
cargo clippy --locked -p hotcore-rs --all-targets -- -D warnings
cargo test --locked -p hotcore-rs
```

Cargo builds an `rlib` linked into the standalone CLI. Crate tests exercise
the Rust functions directly. Use `cargo test --workspace --locked` to verify
their integration with detection, masking, and layout.
