# qacore-rs

Optional PyO3 kernels for checking balloon outlines, lettering contrast, cleanup
halos, preserved artwork, residual ink, and changed pixel bounds. The Python
reference in `skills/revayat-comic/scripts/qacore/kernels.py` runs without the
extension. To force it, set `REVAYAT_QACORE=python` before importing `qacore`.

Inputs are tightly packed row-major `bytes` with positive dimensions. Any
nonzero mask byte is active. Contrast uses the mean WCAG 2.1 relative luminance
of ink and its nearby background. Contrast and halo neighborhoods use
Chebyshev distance and stop at the image edges. The halo maximum includes all
ring pixels, even those below the dirty threshold.

SSIM averages unmasked 8x8 tiles using population variance and covariance. If
none qualify, it uses all unmasked pixels. The residual ink centroid averages
all pixels in qualifying 8-connected clusters and rounds each coordinate down.
Ink bounds always return an empty result for identical images. With a zero
threshold, non-identical images return the full image bounds and pixel count.

## Build and install

Use Python 3.12 or later, Rust 1.97.0 or later, and a platform linker. Run this
from the repository root in the Python environment that runs Revayat Comic:

```console
python -m pip install ./rust/qacore-rs
```

Maturin builds the PEP 517 wheel and installs `qacore_rs._native`. The PyO3
bridge borrows the input buffers. If you regenerate it with `rust-anything
refresh`, preserve the borrowed buffers and the input validation.

## Verify

```console
cargo fmt --manifest-path rust/qacore-rs/Cargo.toml --check
cargo clippy --manifest-path rust/qacore-rs/Cargo.toml --locked -- -D warnings
cargo test --manifest-path rust/qacore-rs/Cargo.toml --locked
python -c "import qacore_rs"
python -m pytest -q tests/test_qacore_parity.py
```

Native parity requires the wheel. Confirm `qacore.BACKEND == "rust"` and run
without native tests being skipped. The migration recordings and bridge metadata
are local artifacts and are not included in the wheel.
