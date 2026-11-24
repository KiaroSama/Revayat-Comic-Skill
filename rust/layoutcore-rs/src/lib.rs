//! Native PyO3 bindings for shaped balloon layout.
#![forbid(unsafe_code)]

pub mod port;

#[cfg(feature = "python")]
mod python {
    use super::port::{self, KernelResult, Pixels, Span};
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyBytesMethods, PyInt, PyList, PyListMethods};

    fn into_python<T>(result: KernelResult<T>) -> PyResult<T> {
        result.map_err(PyValueError::new_err)
    }

    fn bytes<'a>(value: &'a Bound<'_, PyAny>) -> Option<&'a [u8]> {
        value
            .cast_exact::<PyBytes>()
            .ok()
            .map(PyBytesMethods::as_bytes)
    }

    fn pixel(value: &Bound<'_, PyAny>) -> Pixels {
        value
            .cast_exact::<PyInt>()
            .ok()?
            .extract::<isize>()
            .ok()
            .and_then(|v| v.try_into().ok())
    }

    fn vector(value: &Bound<'_, PyAny>) -> Option<Vec<usize>> {
        value
            .cast_exact::<PyList>()
            .ok()?
            .iter()
            .map(|item| pixel(&item))
            .collect()
    }

    fn span_list(value: &Bound<'_, PyAny>) -> Option<Vec<Span>> {
        value
            .cast_exact::<PyList>()
            .ok()?
            .iter()
            .map(|item| {
                let row = item.cast_exact::<PyList>().ok()?;
                if row.len() != 2 {
                    return None;
                }
                let left = pixel(&row.get_item(0).ok()?)?;
                let right = pixel(&row.get_item(1).ok()?)?;
                (left <= right).then_some([left, right])
            })
            .collect()
    }

    #[pyfunction]
    fn scan_mask_spans(
        mask: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<Span>> {
        let input = (bytes(mask), pixel(width), pixel(height));
        into_python(
            mask.py()
                .detach(|| port::scan_mask_spans(input.0, input.1, input.2)),
        )
    }

    #[pyfunction]
    fn fit_lines_to_spans(
        word_widths: &Bound<'_, PyAny>,
        space_width: &Bound<'_, PyAny>,
        line_height: &Bound<'_, PyAny>,
        line_gap: &Bound<'_, PyAny>,
        spans: &Bound<'_, PyAny>,
        pad_x: &Bound<'_, PyAny>,
        pad_y: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<[usize; 5]>> {
        let (words, space, height, gap, rows, x, y) = (
            vector(word_widths),
            pixel(space_width),
            pixel(line_height),
            pixel(line_gap),
            span_list(spans),
            pixel(pad_x),
            pixel(pad_y),
        );
        into_python(
            spans
                .py()
                .detach(|| port::fit_lines_to_spans(words, space, height, gap, rows, x, y)),
        )
    }

    #[pyfunction]
    fn harmonize_font_sizes(
        sizes: &Bound<'_, PyAny>,
        areas: &Bound<'_, PyAny>,
        max_step: &Bound<'_, PyAny>,
        floor_size: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<usize>> {
        into_python(port::harmonize_font_sizes(
            vector(sizes),
            vector(areas),
            pixel(max_step),
            pixel(floor_size),
        ))
    }

    #[pyfunction]
    fn check_ink_wall_clearance(
        ink_mask: &Bound<'_, PyAny>,
        wall_mask: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        min_clearance: &Bound<'_, PyAny>,
    ) -> PyResult<[i64; 4]> {
        let (ink, walls, w, h, limit) = (
            bytes(ink_mask),
            bytes(wall_mask),
            pixel(width),
            pixel(height),
            pixel(min_clearance),
        );
        into_python(
            ink_mask
                .py()
                .detach(|| port::check_ink_wall_clearance(ink, walls, w, h, limit)),
        )
    }

    #[pyfunction]
    fn select_largest_inscribed_band(
        spans: &Bound<'_, PyAny>,
        min_width: &Bound<'_, PyAny>,
        min_height: &Bound<'_, PyAny>,
    ) -> PyResult<[usize; 4]> {
        let (rows, w, h) = (span_list(spans), pixel(min_width), pixel(min_height));
        into_python(
            spans
                .py()
                .detach(|| port::select_largest_inscribed_band(rows, w, h)),
        )
    }

    #[pyfunction]
    fn align_lines_rtl(
        line_widths: &Bound<'_, PyAny>,
        band_lefts: &Bound<'_, PyAny>,
        band_rights: &Bound<'_, PyAny>,
        mode: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<usize>> {
        into_python(port::align_lines_rtl(
            vector(line_widths),
            vector(band_lefts),
            vector(band_rights),
            pixel(mode),
        ))
    }

    #[pymodule]
    #[pyo3(name = "_native")]
    fn native_module(module: &Bound<'_, PyModule>) -> PyResult<()> {
        module.add_function(wrap_pyfunction!(scan_mask_spans, module)?)?;
        module.add_function(wrap_pyfunction!(fit_lines_to_spans, module)?)?;
        module.add_function(wrap_pyfunction!(harmonize_font_sizes, module)?)?;
        module.add_function(wrap_pyfunction!(check_ink_wall_clearance, module)?)?;
        module.add_function(wrap_pyfunction!(select_largest_inscribed_band, module)?)?;
        module.add_function(wrap_pyfunction!(align_lines_rtl, module)?)?;
        Ok(())
    }
}
