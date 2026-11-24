//! PyO3 bridge for `cleancore`, scaffolded by rust-anything.
#![forbid(unsafe_code)]

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyBytesMethods, PyFloat, PyInt};

mod port;

fn error(message: &str) -> PyErr {
    PyValueError::new_err(
        message
            .strip_prefix("ValueError: ")
            .unwrap_or(message)
            .to_owned(),
    )
}

fn bytes<'a>(value: &'a Bound<'_, PyAny>) -> Option<&'a [u8]> {
    value
        .cast_exact::<PyBytes>()
        .ok()
        .map(PyBytesMethods::as_bytes)
}

fn integer(value: &Bound<'_, PyAny>) -> i128 {
    // Positive values beyond i128 only affect radii, where saturation preserves the result.
    if value.is_exact_instance_of::<PyInt>() {
        if let Ok(integer) = value.extract::<i128>() {
            return integer;
        }
        if value.gt(0).unwrap_or(false) {
            return i128::MAX;
        }
    }
    i128::MIN
}

fn threshold(value: &Bound<'_, PyAny>) -> f64 {
    if value.is_exact_instance_of::<PyFloat>()
        || (value.is_exact_instance_of::<PyInt>() && value.le(f64::MAX).unwrap_or(false))
    {
        value.extract::<f64>().unwrap_or(f64::NAN)
    } else {
        f64::NAN
    }
}

#[pyfunction]
fn sample_ring_background(
    py: Python<'_>,
    rgb: &Bound<'_, PyAny>,
    mask: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    ring_px: &Bound<'_, PyAny>,
) -> PyResult<Vec<usize>> {
    let (rgb, mask, width, height, ring_px) = (
        bytes(rgb),
        bytes(mask),
        integer(width),
        integer(height),
        integer(ring_px),
    );
    py.detach(|| port::sample_ring_background(rgb, mask, width, height, ring_px))
        .map_err(error)
}

#[pyfunction]
fn compute_feather_alpha<'py>(
    py: Python<'py>,
    mask: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    radius: &Bound<'_, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let (mask, width, height, radius) = (
        bytes(mask),
        integer(width),
        integer(height),
        integer(radius),
    );
    let result = py
        .detach(|| port::compute_feather_alpha(mask, width, height, radius))
        .map_err(error)?;
    Ok(PyBytes::new(py, &result))
}

#[pyfunction]
fn composite_masked_rgb<'py>(
    py: Python<'py>,
    orig_rgb: &Bound<'_, PyAny>,
    fill_rgb: &Bound<'_, PyAny>,
    alpha: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let (orig_rgb, fill_rgb, alpha, width, height) = (
        bytes(orig_rgb),
        bytes(fill_rgb),
        bytes(alpha),
        integer(width),
        integer(height),
    );
    let result = py
        .detach(|| port::composite_masked_rgb(orig_rgb, fill_rgb, alpha, width, height))
        .map_err(error)?;
    Ok(PyBytes::new(py, &result))
}

#[pyfunction]
fn diffuse_inpaint_rgb<'py>(
    py: Python<'py>,
    rgb: &Bound<'_, PyAny>,
    mask: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    iterations: &Bound<'_, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let (rgb, mask, width, height, iterations) = (
        bytes(rgb),
        bytes(mask),
        integer(width),
        integer(height),
        integer(iterations),
    );
    let result = py
        .detach(|| port::diffuse_inpaint_rgb(rgb, mask, width, height, iterations))
        .map_err(error)?;
    Ok(PyBytes::new(py, &result))
}

#[pyfunction]
fn detect_textured_ring(
    py: Python<'_>,
    rgb: &Bound<'_, PyAny>,
    mask: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    ring_px: &Bound<'_, PyAny>,
    std_thresh: &Bound<'_, PyAny>,
) -> PyResult<Vec<f64>> {
    let (rgb, mask, width, height, ring_px, std_thresh) = (
        bytes(rgb),
        bytes(mask),
        integer(width),
        integer(height),
        integer(ring_px),
        threshold(std_thresh),
    );
    py.detach(|| port::detect_textured_ring(rgb, mask, width, height, ring_px, std_thresh))
        .map_err(error)
}

#[pyfunction]
#[expect(
    clippy::too_many_arguments,
    reason = "Preserve the Python RGB fill signature"
)]
fn fill_flat_rgb<'py>(
    py: Python<'py>,
    orig_rgb: &Bound<'_, PyAny>,
    mask: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    r: &Bound<'_, PyAny>,
    g: &Bound<'_, PyAny>,
    b: &Bound<'_, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let (orig_rgb, mask, width, height, r, g, b) = (
        bytes(orig_rgb),
        bytes(mask),
        integer(width),
        integer(height),
        integer(r),
        integer(g),
        integer(b),
    );
    let result = py
        .detach(|| port::fill_flat_rgb(orig_rgb, mask, width, height, r, g, b))
        .map_err(error)?;
    Ok(PyBytes::new(py, &result))
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(sample_ring_background, module)?)?;
    module.add_function(wrap_pyfunction!(compute_feather_alpha, module)?)?;
    module.add_function(wrap_pyfunction!(composite_masked_rgb, module)?)?;
    module.add_function(wrap_pyfunction!(diffuse_inpaint_rgb, module)?)?;
    module.add_function(wrap_pyfunction!(detect_textured_ring, module)?)?;
    module.add_function(wrap_pyfunction!(fill_flat_rgb, module)?)?;
    Ok(())
}
