//! PyO3 bridge scaffolded by rust-anything and adapted to borrow image bytes.
#![forbid(unsafe_code)]

#[cfg(feature = "python")]
use pyo3::exceptions::PyValueError;
#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::{PyBool, PyBytes, PyFloat, PyInt, PyList};

pub mod port;

#[cfg(feature = "python")]
fn error(message: String) -> PyErr {
    PyValueError::new_err(
        message
            .strip_prefix("ValueError: ")
            .unwrap_or(&message)
            .to_owned(),
    )
}

#[cfg(feature = "python")]
fn bytes<'a>(value: &'a Bound<'_, PyAny>) -> Option<&'a [u8]> {
    value.cast::<PyBytes>().ok().map(PyBytesMethods::as_bytes)
}

#[cfg(feature = "python")]
fn integer(value: &Bound<'_, PyAny>) -> i64 {
    // The port rejects negative dimensions, coordinates and parameters in validation order.
    value
        .cast_exact::<PyInt>()
        .ok()
        .and_then(|v| v.extract().ok())
        .unwrap_or(-1)
}

#[cfg(feature = "python")]
fn ratio(value: &Bound<'_, PyAny>) -> f64 {
    if value.is_exact_instance_of::<PyInt>() || value.is_exact_instance_of::<PyFloat>() {
        value.extract().unwrap_or(f64::NAN)
    } else {
        f64::NAN
    }
}

#[cfg(feature = "python")]
fn rect(value: &Bound<'_, PyAny>) -> Option<[i64; 4]> {
    let values = value.cast::<PyList>().ok()?;
    if values.len() != 4 {
        return None;
    }
    let mut rect = [-1; 4];
    for (cell, value) in rect.iter_mut().zip(values.iter()) {
        *cell = integer(&value);
    }
    Some(rect)
}

#[cfg(feature = "python")]
fn rects(value: &Bound<'_, PyAny>) -> Option<Vec<[i64; 4]>> {
    value
        .cast::<PyList>()
        .ok()?
        .iter()
        .map(|v| rect(&v))
        .collect()
}

#[cfg(feature = "python")]
#[pyfunction]
fn find_panel_gutters(
    py: Python<'_>,
    gray: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    bg_luma: &Bound<'_, PyAny>,
    min_gutter: &Bound<'_, PyAny>,
    margin: &Bound<'_, PyAny>,
) -> PyResult<Vec<[usize; 4]>> {
    let args = (
        bytes(gray),
        integer(width),
        integer(height),
        integer(bg_luma),
        integer(min_gutter),
        integer(margin),
    );
    py.detach(|| port::find_panel_gutters(args.0, args.1, args.2, args.3, args.4, args.5))
        .map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn connected_components_boxes(
    py: Python<'_>,
    mask: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    min_area: &Bound<'_, PyAny>,
    max_area: &Bound<'_, PyAny>,
) -> PyResult<Vec<[usize; 5]>> {
    let args = (
        bytes(mask),
        integer(width),
        integer(height),
        integer(min_area),
        integer(max_area),
    );
    py.detach(|| port::connected_components_boxes(args.0, args.1, args.2, args.3, args.4))
        .map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
#[expect(
    clippy::too_many_arguments,
    reason = "Mirrors the seven-argument Python kernel"
)]
fn detect_speech_balloons(
    py: Python<'_>,
    gray: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    white_thresh: &Bound<'_, PyAny>,
    min_area: &Bound<'_, PyAny>,
    max_area_ratio: &Bound<'_, PyAny>,
    min_fill_ratio: &Bound<'_, PyAny>,
) -> PyResult<Vec<[usize; 5]>> {
    let args = (
        bytes(gray),
        integer(width),
        integer(height),
        integer(white_thresh),
        integer(min_area),
        ratio(max_area_ratio),
        ratio(min_fill_ratio),
    );
    py.detach(|| {
        port::detect_speech_balloons(args.0, args.1, args.2, args.3, args.4, args.5, args.6)
    })
    .map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn merge_text_lines(
    py: Python<'_>,
    boxes: &Bound<'_, PyAny>,
    max_dx: &Bound<'_, PyAny>,
    max_dy: &Bound<'_, PyAny>,
    min_overlap_ratio: &Bound<'_, PyAny>,
) -> PyResult<Vec<[i64; 4]>> {
    let args = (
        rects(boxes),
        integer(max_dx),
        integer(max_dy),
        ratio(min_overlap_ratio),
    );
    py.detach(move || port::merge_text_lines(args.0, args.1, args.2, args.3))
        .map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn sort_reading_order(
    py: Python<'_>,
    boxes: &Bound<'_, PyAny>,
    rtl: &Bound<'_, PyAny>,
    row_tolerance: &Bound<'_, PyAny>,
) -> PyResult<Vec<usize>> {
    let args = (
        rects(boxes),
        rtl.cast::<PyBool>().ok().map(PyBoolMethods::is_true),
        integer(row_tolerance),
    );
    py.detach(move || port::sort_reading_order(args.0, args.1, args.2))
        .map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn estimate_stroke_width(
    py: Python<'_>,
    gray: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    box_rect: &Bound<'_, PyAny>,
) -> PyResult<f64> {
    let args = (bytes(gray), integer(width), integer(height), rect(box_rect));
    py.detach(|| port::estimate_stroke_width(args.0, args.1, args.2, args.3))
        .map_err(error)
}

#[cfg(feature = "python")]
#[pymodule]
#[pyo3(name = "_native")]
fn native_module(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(find_panel_gutters, module)?)?;
    module.add_function(wrap_pyfunction!(connected_components_boxes, module)?)?;
    module.add_function(wrap_pyfunction!(detect_speech_balloons, module)?)?;
    module.add_function(wrap_pyfunction!(merge_text_lines, module)?)?;
    module.add_function(wrap_pyfunction!(sort_reading_order, module)?)?;
    module.add_function(wrap_pyfunction!(estimate_stroke_width, module)?)?;
    Ok(())
}
