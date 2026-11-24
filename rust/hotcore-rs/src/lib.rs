//! Python bindings for `skills/revayat-comic/scripts/hotcore/`: generated from the signatures in `port.rs` by rust-anything.
//! Regenerate with `rust-anything refresh` after changing them.

#![forbid(unsafe_code)]

#[cfg(feature = "python")]
use pyo3::prelude::*;

pub mod js;
pub mod port;
#[cfg(feature = "python")]
pub mod pyconv;
#[cfg(feature = "python")]
pub mod pynum;

#[cfg(feature = "python")]
fn error(message: String) -> PyErr {
    use pyo3::exceptions as e;
    let (kind, text) = message.split_once(": ").unwrap_or(("", message.as_str()));
    let text = text.to_string();
    match kind {
        "TypeError" => e::PyTypeError::new_err(text),
        "KeyError" => e::PyKeyError::new_err(text),
        "IndexError" => e::PyIndexError::new_err(text),
        "OverflowError" => e::PyOverflowError::new_err(text),
        "ZeroDivisionError" => e::PyZeroDivisionError::new_err(text),
        "AttributeError" => e::PyAttributeError::new_err(text),
        "RuntimeError" => e::PyRuntimeError::new_err(text),
        "NotImplementedError" => e::PyNotImplementedError::new_err(text),
        "LookupError" => e::PyLookupError::new_err(text),
        "ArithmeticError" => e::PyArithmeticError::new_err(text),
        "UnicodeError" => e::PyUnicodeError::new_err(text),
        "ValueError" => e::PyValueError::new_err(text),
        _ => e::PyValueError::new_err(message),
    }
}

#[cfg(feature = "python")]
fn box_gap_inner(a: Vec<i64>, b: Vec<i64>) -> Result<f64, String> {
    let out = port::box_gap(a, b)?;
    Ok(out)
}

/// `box_gap`.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "box_gap", signature = (a, b))]
fn box_gap(a: Vec<i64>, b: Vec<i64>) -> PyResult<f64> {
    box_gap_inner(a, b).map_err(error)
}

#[cfg(feature = "python")]
fn cluster_boxes_inner(
    seeds: Bound<'_, PyAny>,
    max_seeds: Option<i64>,
    reach: Option<f64>,
) -> Result<Vec<Vec<Vec<i64>>>, String> {
    let seeds: Vec<Vec<i64>> = crate::pyconv::FromPy::from_py(&seeds)?;
    let out = port::cluster_boxes(seeds, max_seeds, reach)?;
    Ok(out)
}

/// `cluster_boxes`.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "cluster_boxes", signature = (seeds, max_seeds=400, reach=1.6))]
fn cluster_boxes(
    py: Python<'_>,
    seeds: Bound<'_, PyAny>,
    max_seeds: Option<i64>,
    reach: Option<f64>,
) -> PyResult<Py<PyAny>> {
    cluster_boxes_inner(seeds, max_seeds, reach)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

#[cfg(feature = "python")]
fn row_widths_inner(
    mask_flat: Bound<'_, PyAny>,
    width: i64,
    height: i64,
) -> Result<Vec<i64>, String> {
    let mask_flat: serde_json::Value = crate::pyconv::FromPy::from_py(&mask_flat)?;
    let out = port::row_widths(mask_flat, width, height)?;
    Ok(out)
}

/// `row_widths`.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "row_widths", signature = (mask_flat, width, height))]
fn row_widths(mask_flat: Bound<'_, PyAny>, width: i64, height: i64) -> PyResult<Vec<i64>> {
    row_widths_inner(mask_flat, width, height).map_err(error)
}

#[cfg(feature = "python")]
fn band_span_inner(
    mask_flat: Bound<'_, PyAny>,
    width: i64,
    height: i64,
    first: i64,
    last: i64,
) -> Result<Vec<i64>, String> {
    let mask_flat: serde_json::Value = crate::pyconv::FromPy::from_py(&mask_flat)?;
    let out = port::band_span(mask_flat, width, height, first, last)?;
    Ok(out)
}

/// `band_span`.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "band_span", signature = (mask_flat, width, height, first, last))]
fn band_span(
    mask_flat: Bound<'_, PyAny>,
    width: i64,
    height: i64,
    first: i64,
    last: i64,
) -> PyResult<Vec<i64>> {
    band_span_inner(mask_flat, width, height, first, last).map_err(error)
}

#[cfg(feature = "python")]
fn body_bounds_inner(
    widths: Vec<i64>,
    reference: Option<i64>,
    body_width: Option<f64>,
) -> Result<Vec<i64>, String> {
    let out = port::body_bounds(widths, reference, body_width)?;
    Ok(out)
}

/// `body_bounds`.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "body_bounds", signature = (widths, reference=-1, body_width=0.5))]
fn body_bounds(
    widths: Vec<i64>,
    reference: Option<i64>,
    body_width: Option<f64>,
) -> PyResult<Vec<i64>> {
    body_bounds_inner(widths, reference, body_width).map_err(error)
}

#[cfg(feature = "python")]
fn candidate_bodies_inner(
    widths: Vec<i64>,
    body_width: Option<f64>,
) -> Result<Vec<Vec<i64>>, String> {
    let out = port::candidate_bodies(widths, body_width)?;
    Ok(out)
}

/// `candidate_bodies`.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "candidate_bodies", signature = (widths, body_width=0.5))]
fn candidate_bodies(
    py: Python<'_>,
    widths: Vec<i64>,
    body_width: Option<f64>,
) -> PyResult<Py<PyAny>> {
    candidate_bodies_inner(widths, body_width)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

#[cfg(feature = "python")]
#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(box_gap, m)?)?;
    m.add_function(wrap_pyfunction!(cluster_boxes, m)?)?;
    m.add_function(wrap_pyfunction!(row_widths, m)?)?;
    m.add_function(wrap_pyfunction!(band_span, m)?)?;
    m.add_function(wrap_pyfunction!(body_bounds, m)?)?;
    m.add_function(wrap_pyfunction!(candidate_bodies, m)?)?;
    Ok(())
}
