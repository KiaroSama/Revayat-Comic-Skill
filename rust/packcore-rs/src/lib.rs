//! PyO3 bridge scaffolded by rust-anything, with strict native argument conversion.
#![forbid(unsafe_code)]

pub mod port;

#[cfg(feature = "python")]
mod python {
    use super::port;
    use pyo3::exceptions::{PyOverflowError, PyValueError};
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyFloat, PyInt, PyList, PyString};

    fn positive_int(value: &Bound<'_, PyAny>) -> bool {
        value.is_exact_instance_of::<PyInt>() && value.gt(0).unwrap_or(false)
    }

    fn real(value: &Bound<'_, PyAny>) -> f64 {
        if value.is_exact_instance_of::<PyFloat>() || value.is_exact_instance_of::<PyInt>() {
            value.extract().unwrap_or(f64::NAN)
        } else {
            f64::NAN
        }
    }

    fn rgb_dimensions(
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
    ) -> PyResult<(usize, usize)> {
        if !positive_int(width) || !positive_int(height) {
            return Err(PyValueError::new_err(port::RGB_DIMENSIONS_ERROR));
        }
        // An integer wider than usize cannot describe a packed buffer on this platform.
        Ok((
            width.extract().unwrap_or(usize::MAX),
            height.extract().unwrap_or(usize::MAX),
        ))
    }

    fn rgb_bytes<'a>(rgb: &'a Bound<'_, PyAny>, width: usize, height: usize) -> PyResult<&'a [u8]> {
        port::check_rgb(
            rgb.cast_exact::<PyBytes>()
                .ok()
                .map(PyBytesMethods::as_bytes),
            width,
            height,
        )
        .map_err(PyValueError::new_err)
    }

    #[pyfunction]
    fn natural_sort_order(py: Python<'_>, names: &Bound<'_, PyAny>) -> PyResult<Vec<usize>> {
        let names = names
            .cast_exact::<PyList>()
            .map_err(|_| PyValueError::new_err(port::NAMES_ERROR))?;
        let mut encoded = Vec::with_capacity(names.len());
        for item in names.iter() {
            let name = item
                .cast_exact::<PyString>()
                .map_err(|_| PyValueError::new_err(port::NAMES_ERROR))?;
            // Python filenames can contain surrogate escapes; preserve their code-point order.
            let bytes = name.call_method1("encode", ("utf-8", "surrogatepass"))?;
            encoded.push(bytes.cast_exact::<PyBytes>()?.as_bytes().to_vec());
        }
        Ok(py.detach(move || port::natural_sort_order(encoded)))
    }

    #[pyfunction]
    fn analyze_rgb_page(
        py: Python<'_>,
        rgb: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
    ) -> PyResult<[u64; 5]> {
        let (width, height) = rgb_dimensions(width, height)?;
        let rgb = rgb_bytes(rgb, width, height)?;
        Ok(py.detach(|| port::analyze_rgb_page(rgb)))
    }

    fn within_bounds(
        w: &Bound<'_, PyAny>,
        h: &Bound<'_, PyAny>,
        ratio: f64,
        edge: &Bound<'_, PyAny>,
        area: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        if !positive_int(w) || !positive_int(h) {
            return Ok(false);
        }
        if let (Ok(w), Ok(h), Ok(edge), Ok(area)) =
            (w.extract(), h.extract(), edge.extract(), area.extract())
            && let Some(valid) = port::validate_page_dimensions(w, h, ratio, edge, area)
        {
            return Ok(valid);
        }
        // PyLong handles values beyond i128 and rounds division from the exact integer ratio.
        let (short, long) = if w.le(h)? { (w, h) } else { (h, w) };
        if short.lt(edge)? || long.call_method1("__mul__", (short,))?.gt(area)? {
            return Ok(false);
        }
        match long.call_method1("__truediv__", (short,)) {
            Ok(quotient) => quotient.le(ratio),
            Err(err) if err.is_instance_of::<PyOverflowError>(w.py()) => Ok(false),
            Err(err) => Err(err),
        }
    }

    #[pyfunction]
    fn validate_page_dimensions(
        dims: &Bound<'_, PyAny>,
        max_aspect_ratio: &Bound<'_, PyAny>,
        min_edge: &Bound<'_, PyAny>,
        max_pixels: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<usize>> {
        let ratio = real(max_aspect_ratio);
        if !ratio.is_finite() || ratio < 1.0 || !positive_int(min_edge) || !positive_int(max_pixels)
        {
            return Err(PyValueError::new_err(port::BOUNDS_ERROR));
        }
        let shape_error = |_| PyValueError::new_err(port::ROW_ERROR);
        let dims = dims.cast_exact::<PyList>().map_err(shape_error)?;
        let mut invalid = Vec::new();
        for (i, row) in dims.iter().enumerate() {
            let row = row
                .cast_exact::<PyList>()
                .map_err(|_| PyValueError::new_err(port::ROW_ERROR))?;
            if row.len() != 2 {
                return Err(PyValueError::new_err(port::ROW_ERROR));
            }
            if !within_bounds(
                &row.get_item(0)?,
                &row.get_item(1)?,
                ratio,
                min_edge,
                max_pixels,
            )? {
                invalid.push(i);
            }
        }
        Ok(invalid)
    }

    #[pyfunction]
    fn compute_pdf_page_layout(
        page_w: &Bound<'_, PyAny>,
        page_h: &Bound<'_, PyAny>,
        target_dpi: &Bound<'_, PyAny>,
        max_edge_pt: &Bound<'_, PyAny>,
    ) -> PyResult<[f64; 4]> {
        if !positive_int(page_w) || !positive_int(page_h) {
            return Err(PyValueError::new_err(port::PDF_DIMENSIONS_ERROR));
        }
        port::compute_pdf_page_layout(
            real(page_w),
            real(page_h),
            real(target_dpi),
            real(max_edge_pt),
        )
        .map_err(PyValueError::new_err)
    }

    #[pyfunction]
    fn diff_raster_tiles(
        py: Python<'_>,
        orig_rgb: &Bound<'_, PyAny>,
        final_rgb: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        tile_size: &Bound<'_, PyAny>,
        tol: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<[usize; 4]>> {
        let (width, height) = rgb_dimensions(width, height)?;
        let orig = rgb_bytes(orig_rgb, width, height)?;
        let final_rgb = rgb_bytes(final_rgb, width, height)?;
        if !positive_int(tile_size) {
            return Err(PyValueError::new_err(port::TILE_ERROR));
        }
        let tile = tile_size.extract().unwrap_or(usize::MAX);
        let tol = tol
            .cast_exact::<PyInt>()
            .ok()
            .and_then(|x| x.extract().ok())
            .ok_or_else(|| PyValueError::new_err(port::TOL_ERROR))?;
        Ok(py.detach(|| port::diff_raster_tiles(orig, final_rgb, width, height, tile, tol)))
    }

    #[pyfunction]
    fn compute_grayscale_histogram(
        py: Python<'_>,
        rgb: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
    ) -> PyResult<[usize; 256]> {
        let (width, height) = rgb_dimensions(width, height)?;
        let rgb = rgb_bytes(rgb, width, height)?;
        Ok(py.detach(|| port::compute_grayscale_histogram(rgb)))
    }

    #[pymodule]
    fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
        module.add_function(wrap_pyfunction!(analyze_rgb_page, module)?)?;
        module.add_function(wrap_pyfunction!(compute_grayscale_histogram, module)?)?;
        module.add_function(wrap_pyfunction!(compute_pdf_page_layout, module)?)?;
        module.add_function(wrap_pyfunction!(diff_raster_tiles, module)?)?;
        module.add_function(wrap_pyfunction!(natural_sort_order, module)?)?;
        module.add_function(wrap_pyfunction!(validate_page_dimensions, module)?)?;
        Ok(())
    }
}
