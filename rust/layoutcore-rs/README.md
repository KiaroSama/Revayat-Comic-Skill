# layoutcore-rs

Pure-Rust layout kernels for shaped speech balloons. The public functions live
in [`layoutcore_rs::port`](src/port.rs) and are used by `revayat-vision`.

Masks are packed, row-major byte slices with positive dimensions. Any nonzero byte
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

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p layoutcore-rs
cargo fmt -p layoutcore-rs --check
cargo clippy --locked -p layoutcore-rs --all-targets -- -D warnings
cargo test --locked -p layoutcore-rs
```

Cargo builds an `rlib` linked into the standalone CLI. Crate tests cover the
kernel contracts; `cargo test --workspace --locked` also checks their use in
typesetting and QA. Preserve mask-buffer validation and deterministic tie rules.
