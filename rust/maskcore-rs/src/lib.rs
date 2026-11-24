//! PyO3 bridge for `maskcore`, scaffolded by rust-anything.
#![forbid(unsafe_code)]

#[cfg(feature = "python")]
use pyo3::exceptions::PyValueError;
#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::{PyBytes, PyBytesMethods, PyFloat, PyInt, PyList, PyListMethods, PyTuple};

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
fn integer(value: &Bound<'_, PyAny>) -> i128 {
    // Keep validation order in the port. Only nonnegative radii/margins may saturate.
    if value.is_instance_of::<PyInt>() {
        if let Ok(integer) = value.extract::<i128>() {
            return integer;
        }
        if value.gt(0).unwrap_or(false) {
            return i128::MAX;
        }
    }
    i128::MIN
}

#[cfg(feature = "python")]
fn ratio(value: &Bound<'_, PyAny>) -> f64 {
    if value.is_instance_of::<PyFloat>() || value.is_instance_of::<PyInt>() {
        value.extract::<f64>().unwrap_or(f64::NAN)
    } else {
        f64::NAN
    }
}

#[cfg(feature = "python")]
fn box_list(value: &Bound<'_, PyAny>) -> Result<Vec<[i64; 4]>, &'static str> {
    let values = value.cast::<PyList>().map_err(|_| port::BOXES)?;
    let mut result = Vec::with_capacity(values.len());
    for value in values.iter() {
        if !value.is_instance_of::<PyList>() && !value.is_instance_of::<PyTuple>() {
            return Err(port::BOX);
        }
        let mut row = [0; 4];
        let mut items = value.try_iter().map_err(|_| port::BOX)?;
        for cell in &mut row {
            let item = items.next().ok_or(port::BOX)?.map_err(|_| port::BOX)?;
            *cell = i64::try_from(integer(&item)).map_err(|_| port::BOX)?;
        }
        if items.next().is_some() {
            return Err(port::BOX);
        }
        result.push(row);
    }
    Ok(result)
}

#[cfg(feature = "python")]
#[pyfunction]
#[expect(
    clippy::too_many_arguments,
    reason = "The bridge preserves the reference signature"
)]
fn flood_balloon_interior<'py>(
    py: Python<'py>,
    gray: &Bound<'py, PyAny>,
    width: &Bound<'py, PyAny>,
    height: &Bound<'py, PyAny>,
    seed_x: &Bound<'py, PyAny>,
    seed_y: &Bound<'py, PyAny>,
    wall_luma: &Bound<'py, PyAny>,
    grad_thresh: &Bound<'py, PyAny>,
    min_inset: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let mask = port::flood_balloon_interior(
        bytes(gray),
        integer(width),
        integer(height),
        integer(seed_x),
        integer(seed_y),
        integer(wall_luma),
        integer(grad_thresh),
        integer(min_inset),
    )
    .map_err(error)?;
    Ok(PyBytes::new(py, &mask))
}

#[cfg(feature = "python")]
#[pyfunction]
fn erode_linf<'py>(
    py: Python<'py>,
    mask: &Bound<'py, PyAny>,
    width: &Bound<'py, PyAny>,
    height: &Bound<'py, PyAny>,
    radius: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let mask = port::erode_linf(
        bytes(mask),
        integer(width),
        integer(height),
        integer(radius),
    )
    .map_err(error)?;
    Ok(PyBytes::new(py, &mask))
}

#[cfg(feature = "python")]
#[pyfunction]
fn dilate_linf<'py>(
    py: Python<'py>,
    mask: &Bound<'py, PyAny>,
    width: &Bound<'py, PyAny>,
    height: &Bound<'py, PyAny>,
    radius: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let mask = port::dilate_linf(
        bytes(mask),
        integer(width),
        integer(height),
        integer(radius),
    )
    .map_err(error)?;
    Ok(PyBytes::new(py, &mask))
}

#[cfg(feature = "python")]
#[pyfunction]
fn partition_voronoi_lobes(
    union_mask: &Bound<'_, PyAny>,
    width: &Bound<'_, PyAny>,
    height: &Bound<'_, PyAny>,
    ux0: &Bound<'_, PyAny>,
    uy0: &Bound<'_, PyAny>,
    boxes: &Bound<'_, PyAny>,
    seam_margin: &Bound<'_, PyAny>,
) -> PyResult<Vec<i64>> {
    port::partition_voronoi_lobes(
        bytes(union_mask),
        integer(width),
        integer(height),
        integer(ux0),
        integer(uy0),
        box_list(boxes),
        integer(seam_margin),
    )
    .map_err(error)
}

#[cfg(feature = "python")]
#[pyfunction]
fn strip_perimeter_contours<'py>(
    py: Python<'py>,
    mask: &Bound<'py, PyAny>,
    width: &Bound<'py, PyAny>,
    height: &Bound<'py, PyAny>,
    min_area_ratio: &Bound<'py, PyAny>,
    min_span_ratio: &Bound<'py, PyAny>,
) -> PyResult<(Bound<'py, PyBytes>, Bound<'py, PyBytes>)> {
    let (kept, stripped) = port::strip_perimeter_contours(
        bytes(mask),
        integer(width),
        integer(height),
        ratio(min_area_ratio),
        ratio(min_span_ratio),
    )
    .map_err(error)?;
    Ok((PyBytes::new(py, &kept), PyBytes::new(py, &stripped)))
}

#[cfg(feature = "python")]
#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(erode_linf, m)?)?;
    m.add_function(wrap_pyfunction!(dilate_linf, m)?)?;
    m.add_function(wrap_pyfunction!(flood_balloon_interior, m)?)?;
    m.add_function(wrap_pyfunction!(partition_voronoi_lobes, m)?)?;
    m.add_function(wrap_pyfunction!(strip_perimeter_contours, m)?)?;
    Ok(())
}
