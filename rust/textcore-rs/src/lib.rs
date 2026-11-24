//! PyO3 bindings scaffolded by rust-anything.
//! Preserve the exact integer and nested-list conversions when refreshing the bridge.
#![forbid(unsafe_code)]

#[cfg(feature = "python")]
use num_bigint::BigInt;
#[cfg(feature = "python")]
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::{PyBool, PyInt};

pub mod port;

#[cfg(feature = "python")]
fn extract_bigint(obj: &Bound<'_, PyAny>) -> PyResult<BigInt> {
    if obj.is_instance_of::<PyBool>() || !obj.is_instance_of::<PyInt>() {
        return Err(PyTypeError::new_err(format!(
            "'{}' object cannot be interpreted as an integer",
            obj.get_type().name()?
        )));
    }
    if let Ok(value) = obj.extract::<i128>() {
        return Ok(BigInt::from(value));
    }
    let bit_len: usize = obj.call_method0("bit_length")?.extract()?;
    let byte_len = (bit_len / 8) + 1;
    let bytes: Vec<u8> = obj
        .call_method1("to_bytes", (byte_len, "little", true))?
        .extract()?;
    Ok(BigInt::from_signed_bytes_le(&bytes))
}

#[cfg(feature = "python")]
fn extract_bigint_vec(items: Vec<Bound<'_, PyAny>>) -> PyResult<Vec<BigInt>> {
    items.iter().map(extract_bigint).collect()
}

#[cfg(feature = "python")]
fn error(message: String) -> PyErr {
    if let Some(text) = message.strip_prefix("ValueError: ") {
        PyValueError::new_err(text.to_owned())
    } else {
        PyRuntimeError::new_err(message)
    }
}

#[cfg(feature = "python")]
#[pyfunction]
fn starts_with_latin_in_persian(text: String) -> PyResult<bool> {
    port::starts_with_latin_in_persian(text).map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn ensure_rli_pdi(text: String) -> PyResult<String> {
    port::ensure_rli_pdi(text).map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn ensure_rlm_rli_pdi(text: String) -> PyResult<String> {
    port::ensure_rlm_rli_pdi(text).map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn normalize_persian_text(text: String) -> PyResult<String> {
    port::normalize_persian_text(text).map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn balanced_wrap_lines(
    word_widths: Vec<Bound<'_, PyAny>>,
    space_width: &Bound<'_, PyAny>,
    band_widths: Vec<Bound<'_, PyAny>>,
) -> PyResult<Vec<Vec<usize>>> {
    let words = extract_bigint_vec(word_widths)?;
    let space = extract_bigint(space_width)?;
    let bands = extract_bigint_vec(band_widths)?;
    port::balanced_wrap_lines(words, space, bands).map_err(error)
}

#[cfg(feature = "python")]
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
