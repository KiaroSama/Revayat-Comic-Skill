# packcore-rs

Pure-Rust kernels for comic archives, page geometry, and packed RGB pages.
The public functions live in [`packcore_rs::port`](src/port.rs) and are used by
the I/O, IR, and CLI crates.

- `natural_sort_order` returns original indices, compares ASCII, Persian and
  Arabic-Indic digit runs by value, then uses the raw filename and index to
  break ties. Only ASCII letters are case-folded.
- `validate_page_dimensions` checks one width/height pair against edge, area,
  and aspect limits. It returns `Some(true)` or `Some(false)` when the result
  can be determined and `None` when the aspect comparison would lose integer
  precision. Callers must handle the indeterminate case explicitly.
- `compute_pdf_page_layout` returns width and height in points, effective DPI,
  and a uniform scale no greater than one. It rejects non-finite or zero
  intermediate or final sizes.
- `analyze_rgb_page` returns a 32-bit FNV-1a checksum, the luma range, the mean
  luma times 100 rounded down, and the number of pixels with luma below 245.
- `compute_grayscale_histogram` counts all 256 integer luma levels.
- `diff_raster_tiles` returns zero-based tile coordinates in row-major order,
  the number of changed pixels, and the largest channel delta. A pixel counts
  only when the delta exceeds the given tolerance (0 through 255).

Raster functions take tightly packed row-major RGB byte slices. Functions with
width/height arguments validate their geometry; callers of raw slice-only
analysis functions must supply complete RGB triplets.

## Build and verify

Use the repository-pinned Rust 1.100.0 toolchain and a platform linker. Run from
the repository root:

```console
cargo build --locked -p packcore-rs
cargo fmt -p packcore-rs --check
cargo clippy --locked -p packcore-rs --all-targets -- -D warnings
cargo test --locked -p packcore-rs
```

Cargo builds an `rlib`. Crate tests exercise the functions directly; run
`cargo test --workspace --locked` to verify archive ordering, page limits,
export, and package-check integration.
