# cleancore-rs

Pure-Rust cleaning kernels used by `revayat-vision`. The public functions live
in [`cleancore_rs::port`](src/port.rs) and are linked into the standalone CLI.

Give the kernels tightly packed row-major byte slices and positive integer image
dimensions. Every nonzero mask byte marks an active pixel. Ring sampling uses
unmasked pixels within the given Chebyshev radius and returns the lower median
of each channel. The default when the ring is empty is white with sample count
zero. Texture detection reports the population luma deviation and the widest
individual RGB channel span. It flags a ring when its deviation exceeds the
threshold.

Feathering measures inward from unmasked pixels or the virtual border just
outside the image. A zero radius gives full opacity inside. Flat fill and
inpainting preserve unmasked pixels byte for byte. Inpainting seeds from the
one-pixel ring and runs Jacobi passes with four cardinal neighbors. At image
edges, an off-image neighbor uses the current pixel. Zero passes return the
seeded image. A fully masked image fills with white. The composite uses integer
rounding and leaves every zero-alpha pixel unchanged.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p cleancore-rs
cargo fmt -p cleancore-rs --check
cargo clippy --locked -p cleancore-rs --all-targets -- -D warnings
cargo test --locked -p cleancore-rs
```

Cargo builds an `rlib`. Crate tests exercise the kernels directly; run
`cargo test --workspace --locked` to verify their use throughout the comic
pipeline. Preserve borrowed buffers, input validation, and mask boundaries
when changing these functions.
