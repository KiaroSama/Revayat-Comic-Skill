use serde_json::Value;

use crate::{IoError, invalid};

pub fn validate_paper(paper: [f64; 2]) -> Result<[f64; 2], IoError> {
    if paper.into_iter().all(|n| n.is_finite() && n > 0.0) {
        Ok(paper)
    } else {
        Err(invalid(
            "Page PDF dimensions must be two finite positive point values",
        ))
    }
}

pub fn pdf_points(page: &Value) -> Result<[f64; 2], IoError> {
    match page.get("pdf_points") {
        Some(Value::Array(a)) if a.len() == 2 => validate_paper([
            a[0].as_f64().unwrap_or(f64::NAN),
            a[1].as_f64().unwrap_or(f64::NAN),
        ]),
        Some(_) => validate_paper([f64::NAN; 2]),
        None => validate_paper([
            page["width"].as_f64().unwrap_or(f64::NAN),
            page["height"].as_f64().unwrap_or(f64::NAN),
        ]),
    }
}

pub fn validate_pixels(width: u32, height: u32, max_pixels: u64) -> Result<(), IoError> {
    if width == 0 || height == 0 {
        return Err(invalid("Page has zero pixel width or height"));
    }
    let required = u64::from(width) * u64::from(height);
    if required > max_pixels {
        return Err(IoError::PixelBudget {
            required,
            limit: max_pixels,
        });
    }
    Ok(())
}

pub(crate) fn scaled_pixels(paper: [f64; 2], scale: f64, limit: u64) -> Result<[u32; 2], IoError> {
    let width = (paper[0] * scale).ceil();
    let height = (paper[1] * scale).ceil();
    let required = (width * height) as u64;
    if !width.is_finite()
        || !height.is_finite()
        || required > limit
        || width > f64::from(u32::MAX)
        || height > f64::from(u32::MAX)
    {
        return Err(IoError::PixelBudget { required, limit });
    }
    let size = [width as u32, height as u32];
    validate_pixels(size[0], size[1], limit)?;
    Ok(size)
}
