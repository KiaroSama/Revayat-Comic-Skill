use crate::{
    Rect, Result, VisionError,
    clean::{CleanStrategy, clean_region},
    masks::RegionMask,
};
use image::{GrayImage, Luma, RgbImage};
use serde::{Deserialize, Serialize};

pub const MIN_SIDE: u32 = 4;
pub const MAX_AREA_SHARE: f64 = 0.25;

pub fn parse_box(text: &str) -> Result<Rect> {
    let fields = text
        .split(|c: char| c == ',' || c.is_whitespace())
        .filter(|x| !x.is_empty())
        .map(str::parse::<u32>)
        .collect::<std::result::Result<Vec<_>, _>>();
    let rect = fields
        .ok()
        .and_then(|v| <[u32; 4]>::try_from(v).ok())
        .map(Rect)
        .ok_or_else(|| {
            VisionError::invalid(format!(
                "--box wants four numbers, x y w h, in the page's own pixels: {text:?}"
            ))
        })?;
    if rect.width().min(rect.height()) < MIN_SIDE {
        return Err(VisionError::invalid("watermark box is too small"));
    }
    Ok(rect)
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct Watermark {
    pub id: String,
    pub bounds: Rect,
    pub erase: bool,
    pub locked: bool,
}

pub fn mark_page(id: impl Into<String>, bounds: Rect, dimensions: (u32, u32)) -> Result<Watermark> {
    let id = id.into();
    let clamped = bounds.clip(dimensions.0, dimensions.1);
    if id.trim().is_empty()
        || clamped.width().min(clamped.height()) < MIN_SIDE
        || clamped.area() as f64
            > MAX_AREA_SHARE * f64::from(dimensions.0) * f64::from(dimensions.1)
    {
        return Err(VisionError::invalid(
            "watermark label or page-space box is invalid",
        ));
    }
    Ok(Watermark {
        id,
        bounds: clamped,
        erase: true,
        locked: true,
    })
}

pub fn remove_watermark(
    page: &RgbImage,
    mark: &Watermark,
    external: Option<&RgbImage>,
) -> Result<(RgbImage, GrayImage, CleanStrategy)> {
    if !mark.erase || !mark.locked {
        return Err(VisionError::invalid(
            "watermark removal requires a locked erase decision",
        ));
    }
    mark.bounds.checked(page.dimensions())?;
    let b = mark_page(&mark.id, mark.bounds, page.dimensions())?.bounds;
    // Keep sampling context outside the solid erased patch.
    let w = b.expand(10, page.width(), page.height());
    let pixels = GrayImage::from_fn(w.width(), w.height(), |x, y| {
        Luma([if b.contains(w.x() + x, w.y() + y) {
            255
        } else {
            0
        }])
    });
    let local = RegionMask { bounds: w, pixels };
    let (out, strategy) = clean_region(page, &local, None, external)?;
    let mut mask = GrayImage::new(page.width(), page.height());
    local.apply_to(&mut mask)?;
    Ok((out, mask, strategy))
}
