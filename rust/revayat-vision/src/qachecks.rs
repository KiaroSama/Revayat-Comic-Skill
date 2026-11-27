use crate::{
    Rect, Result, VisionError, gray,
    masks::{
        Balloon, RegionMask, balloon_interior, balloon_paper, inset_balloon,
        open_balloon_cleanup_window,
    },
    same_geometry,
};
use image::{RgbImage, imageops};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextOverlap {
    pub first: String,
    pub second: String,
    pub intersection: Rect,
}

pub fn rendered_text_overlaps(boxes: &[(&str, Rect)]) -> Vec<TextOverlap> {
    let mut result = Vec::new();
    for (i, (first, a)) in boxes.iter().enumerate() {
        for (second, b) in &boxes[i + 1..] {
            if let Some(intersection) = a.intersection(*b) {
                result.push(TextOverlap {
                    first: (*first).into(),
                    second: (*second).into(),
                    intersection,
                });
            }
        }
    }
    result
}

pub fn check_page_dimensions(
    original: (u32, u32),
    cleaned: (u32, u32),
    final_size: (u32, u32),
) -> Vec<&'static str> {
    [("clean", cleaned), ("typeset", final_size)]
        .into_iter()
        .filter_map(|(stage, size)| {
            (size != original || size.0 == 0 || size.1 == 0).then_some(stage)
        })
        .collect()
}

/// Crop or pad around the middle without resampling any pixel.
pub fn reconcile_image_dimensions(image: &RgbImage, target: (u32, u32)) -> Result<RgbImage> {
    if target.0 == 0 || target.1 == 0 || image.width() == 0 || image.height() == 0 {
        return Err(VisionError::invalid("image dimensions must be positive"));
    }
    let mut result = RgbImage::from_pixel(target.0, target.1, image::Rgb([255; 3]));
    let (w, h) = (image.width().min(target.0), image.height().min(target.1));
    let crop = imageops::crop_imm(
        image,
        (image.width() - w) / 2,
        (image.height() - h) / 2,
        w,
        h,
    );
    imageops::replace(
        &mut result,
        &crop.to_image(),
        i64::from((target.0 - w) / 2),
        i64::from((target.1 - h) / 2),
    );
    Ok(result)
}

pub fn balloon_text_interior(original: &RgbImage, b: Balloon) -> Result<RegionMask> {
    balloon_interior(original, b, crate::masks::text_inset(b.bounds))
}

/// Check balloon cleanup using the same 2 px inset as cleanup itself (and source window for open balloons).
pub fn balloon_cleanup_interior(original: &RgbImage, b: Balloon) -> Result<RegionMask> {
    let (paper, open) = balloon_paper(original, b)?;
    let mut safe = inset_balloon(&paper, 2)?;
    if open {
        let window = open_balloon_cleanup_window(b, original.dimensions());
        for (x, y, pixel) in safe.pixels.enumerate_pixels_mut() {
            if !window.contains(safe.bounds.x() + x, safe.bounds.y() + y) {
                pixel[0] = 0;
            }
        }
    }
    Ok(safe)
}

pub fn full_balloon_surviving_ink(
    original: &RgbImage,
    cleaned: &RgbImage,
    b: Balloon,
) -> Result<u64> {
    same_geometry(original.dimensions(), cleaned.dimensions())?;
    let safe = balloon_cleanup_interior(original, b)?;
    let r = safe.bounds;
    let crop = imageops::crop_imm(cleaned, r.x(), r.y(), r.width(), r.height()).to_image();
    let gray = gray(&crop, b.dark);
    let paper = gray
        .pixels()
        .zip(safe.pixels.pixels())
        .filter_map(|(p, m)| (m[0] != 0 && p[0] > 185).then_some(u64::from(p[0])));
    let (sum, count) = paper.fold((0, 0), |(s, n), v| (s + v, n + 1));
    if count == 0 {
        return Err(VisionError::invalid(
            "no safe balloon paper available for residual ink QA",
        ));
    }
    let counts = qacore_rs::port::detect_residual_ink(
        Some(gray.as_raw()),
        Some(safe.pixels.as_raw()),
        i128::from(r.width()),
        i128::from(r.height()),
        i128::from(sum / count),
        38,
        1,
    )
    .map_err(VisionError::kernel)?;
    Ok(counts.first().copied().unwrap_or_default() as u64)
}

pub fn text_crosses_outline(
    original: &RgbImage,
    cleaned: &RgbImage,
    final_image: &RgbImage,
    b: Balloon,
    footprint: Rect,
) -> Result<u64> {
    same_geometry(original.dimensions(), cleaned.dimensions())?;
    same_geometry(original.dimensions(), final_image.dimensions())?;
    let safe = balloon_text_interior(original, b)?;
    let footprint = footprint.checked(original.dimensions())?;
    let mut crossing = 0;
    for y in footprint.y()..footprint.bottom() {
        for x in footprint.x()..footprint.right() {
            let clean = cleaned.get_pixel(x, y);
            if !pixel_changed(clean, final_image.get_pixel(x, y)) {
                continue;
            }
            let inside = safe.bounds.contains(x, y)
                && safe
                    .pixels
                    .get_pixel(x - safe.bounds.x(), y - safe.bounds.y())[0]
                    != 0;
            let paper = |p| {
                let luma = crate::luminance(p);
                if b.dark { 255 - luma } else { luma }
            };
            // Dark source glyphs legitimately removed inside safe paper are not an outline.
            let dark = paper(clean) < 180 || (!inside && paper(original.get_pixel(x, y)) < 180);
            crossing += u64::from(!inside || dark);
        }
    }
    Ok(crossing)
}

pub fn pixel_changed(before: &image::Rgb<u8>, after: &image::Rgb<u8>) -> bool {
    before.0.iter().zip(after.0).any(|(a, b)| a.abs_diff(b) > 8)
}
