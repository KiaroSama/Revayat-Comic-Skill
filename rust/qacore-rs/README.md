# qacore-rs

Pure-Rust kernels for checking balloon outlines, lettering contrast, cleanup
halos, preserved artwork, residual ink, and changed pixel bounds. The public
functions live in [`qacore_rs::port`](src/port.rs) and are used by `revayat-vision`.

Inputs are tightly packed row-major byte slices with positive dimensions. Any
nonzero mask byte is active. Contrast uses the mean WCAG 2.1 relative luminance
of ink and its nearby background. Contrast and halo neighborhoods use
Chebyshev distance and stop at the image edges. The halo maximum includes all
ring pixels, even those below the dirty threshold.

SSIM averages unmasked 8x8 tiles using population variance and covariance. If
none qualify, it uses all unmasked pixels. The residual ink centroid averages
all pixels in qualifying 8-connected clusters and rounds each coordinate down.
Ink bounds always return an empty result for identical images. With a zero
threshold, non-identical images return the full image bounds and pixel count.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p qacore-rs
cargo fmt -p qacore-rs --check
cargo clippy --locked -p qacore-rs --all-targets -- -D warnings
cargo test --locked -p qacore-rs
```

Cargo builds an `rlib` linked into the standalone CLI. Crate tests exercise
the kernels directly; `cargo test --workspace --locked` also checks publication
and artwork-preservation behavior. Preserve borrowed buffers and input validation.
