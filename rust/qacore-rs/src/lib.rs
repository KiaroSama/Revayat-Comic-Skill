//! PyO3 bridge for `qacore`, scaffolded by rust-anything.
#![forbid(unsafe_code)]

pub mod port;

#[cfg(feature = "python")]
mod python {
    use super::port;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyBytesMethods, PyInt};

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
            .is_exact_instance_of::<PyBytes>()
            .then(|| value.cast::<PyBytes>().ok())
            .flatten()
            .map(PyBytesMethods::as_bytes)
    }

    fn integer(value: &Bound<'_, PyAny>) -> i128 {
        // Saturation preserves validation of huge positive radii and cluster sizes.
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

    #[pyfunction]
    fn detect_outline_bleed(
        orig_gray: &Bound<'_, PyAny>,
        final_gray: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        ink_mask: &Bound<'_, PyAny>,
        wall_thresh: &Bound<'_, PyAny>,
        diff_thresh: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<i64>> {
        port::detect_outline_bleed(
            bytes(orig_gray),
            bytes(final_gray),
            integer(width),
            integer(height),
            bytes(ink_mask),
            integer(wall_thresh),
            integer(diff_thresh),
        )
        .map_err(error)
    }

    #[pyfunction]
    fn measure_region_contrast(
        rgb: &Bound<'_, PyAny>,
        ink_mask: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        pad: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<f64>> {
        port::measure_region_contrast(
            bytes(rgb),
            bytes(ink_mask),
            integer(width),
            integer(height),
            integer(pad),
        )
        .map_err(error)
    }

    #[pyfunction]
    fn detect_halo_artifacts(
        orig_rgb: &Bound<'_, PyAny>,
        clean_rgb: &Bound<'_, PyAny>,
        mask: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        ring_px: &Bound<'_, PyAny>,
        diff_thresh: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<i64>> {
        port::detect_halo_artifacts(
            bytes(orig_rgb),
            bytes(clean_rgb),
            bytes(mask),
            integer(width),
            integer(height),
            integer(ring_px),
            integer(diff_thresh),
        )
        .map_err(error)
    }

    #[pyfunction]
    fn compute_patch_ssim(
        orig_gray: &Bound<'_, PyAny>,
        final_gray: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        mask: &Bound<'_, PyAny>,
    ) -> PyResult<f64> {
        port::compute_patch_ssim(
            bytes(orig_gray),
            bytes(final_gray),
            integer(width),
            integer(height),
            bytes(mask),
        )
        .map_err(error)
    }

    #[pyfunction]
    fn detect_residual_ink(
        clean_gray: &Bound<'_, PyAny>,
        mask: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        bg_luma: &Bound<'_, PyAny>,
        delta_thresh: &Bound<'_, PyAny>,
        min_cluster: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<i64>> {
        port::detect_residual_ink(
            bytes(clean_gray),
            bytes(mask),
            integer(width),
            integer(height),
            integer(bg_luma),
            integer(delta_thresh),
            integer(min_cluster),
        )
        .map_err(error)
    }

    #[pyfunction]
    fn compute_ink_bounds(
        before_rgb: &Bound<'_, PyAny>,
        after_rgb: &Bound<'_, PyAny>,
        width: &Bound<'_, PyAny>,
        height: &Bound<'_, PyAny>,
        diff_thresh: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<i64>> {
        port::compute_ink_bounds(
            bytes(before_rgb),
            bytes(after_rgb),
            integer(width),
            integer(height),
            integer(diff_thresh),
        )
        .map_err(error)
    }

    #[pymodule]
    fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
        module.add_function(wrap_pyfunction!(detect_outline_bleed, module)?)?;
        module.add_function(wrap_pyfunction!(measure_region_contrast, module)?)?;
        module.add_function(wrap_pyfunction!(detect_halo_artifacts, module)?)?;
        module.add_function(wrap_pyfunction!(compute_patch_ssim, module)?)?;
        module.add_function(wrap_pyfunction!(detect_residual_ink, module)?)?;
        module.add_function(wrap_pyfunction!(compute_ink_bounds, module)?)?;
        Ok(())
    }
}
