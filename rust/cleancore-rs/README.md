# cleancore-rs

Optional native cleaning kernels. The `cleancore` dispatcher loads the extension
when available. Set `REVAYAT_CLEANCORE=python` before importing `cleancore` to
use the dependency-free Python reference.

Give the kernels tightly packed row-major `bytes` and positive integer image
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

Use Python 3.12 or later, Rust 1.100.0 or later, and a platform linker. From the
repository root, run these commands in the Python environment that will use the
wheel:

```console
python -m pip install ./rust/cleancore-rs
cargo fmt --manifest-path rust/cleancore-rs/Cargo.toml --check
cargo clippy --manifest-path rust/cleancore-rs/Cargo.toml --locked -- -D warnings
cargo test --manifest-path rust/cleancore-rs/Cargo.toml --locked
python -m pytest -q tests/test_cleancore_parity.py
```

Maturin builds `cleancore_rs._native`. Confirm `cleancore.BACKEND == "rust"` with
`skills/revayat-comic/scripts` on `PYTHONPATH` so the parity run exercises the
wheel. The bridge borrows RGB and mask inputs directly. If you regenerate it
with `rust-anything refresh`, preserve the borrowed buffers and strict
validation. Keep migration metadata and recordings local.
