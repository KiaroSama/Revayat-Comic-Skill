//! PyO3 bindings scaffolded by rust-anything.
//! Preserve the exact integer and nested-list conversions when refreshing the bridge.
#![forbid(unsafe_code)]

use num_bigint::BigInt;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

pub mod port;

fn error(message: String) -> PyErr {
    if let Some(text) = message.strip_prefix("ValueError: ") {
        PyValueError::new_err(text.to_owned())
    } else {
        PyRuntimeError::new_err(message)
    }
}

#[pyfunction]
fn starts_with_latin_in_persian(text: String) -> PyResult<bool> {
    port::starts_with_latin_in_persian(text).map_err(error)
}

#[pyfunction]
fn ensure_rli_pdi(text: String) -> PyResult<String> {
    port::ensure_rli_pdi(text).map_err(error)
}

#[pyfunction]
fn ensure_rlm_rli_pdi(text: String) -> PyResult<String> {
    port::ensure_rlm_rli_pdi(text).map_err(error)
}

#[pyfunction]
fn normalize_persian_text(text: String) -> PyResult<String> {
    port::normalize_persian_text(text).map_err(error)
}

#[pyfunction]
fn balanced_wrap_lines(
    word_widths: Vec<BigInt>,
    space_width: BigInt,
    band_widths: Vec<BigInt>,
) -> PyResult<Vec<Vec<usize>>> {
    port::balanced_wrap_lines(word_widths, space_width, band_widths).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(starts_with_latin_in_persian, m)?)?;
    m.add_function(wrap_pyfunction!(ensure_rli_pdi, m)?)?;
    m.add_function(wrap_pyfunction!(ensure_rlm_rli_pdi, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_persian_text, m)?)?;
    m.add_function(wrap_pyfunction!(balanced_wrap_lines, m)?)?;
    Ok(())
}
