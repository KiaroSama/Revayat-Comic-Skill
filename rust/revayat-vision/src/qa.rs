use crate::{
    Rect, Result, VisionError, bidi, falint, gray,
    masks::{Balloon, from_raw},
    qachecks, same_geometry,
};
use image::{GrayImage, RgbImage, imageops};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diff {
    pub changed: u64,
    pub total: u64,
    pub worst_delta: u8,
}

pub fn compare_outside_mask(
    original: &RgbImage,
    edited: &RgbImage,
    mask: &GrayImage,
) -> Result<Diff> {
    same_geometry(original.dimensions(), edited.dimensions())?;
    same_geometry(original.dimensions(), mask.dimensions())?;
    let [changed, worst_delta] = pixcore_rs::port::outside_mask_diff(
        original.as_raw(),
        edited.as_raw(),
        mask.as_raw(),
        i64::from(original.width()),
        i64::from(original.height()),
        0,
    )
    .map_err(VisionError::kernel)?
    .try_into()
    .map_err(|_| VisionError::invalid("invalid pixel diff result"))?;
    Ok(Diff {
        changed: changed as u64,
        total: u64::from(original.width()) * u64::from(original.height()),
        worst_delta: worst_delta as u8,
    })
}

#[derive(Debug, Clone)]
pub struct QaRegion<'a> {
    pub id: &'a str,
    pub target: &'a str,
    pub ink_box: Option<Rect>,
    pub balloon: Option<Balloon>,
    pub font_size: Option<f32>,
    pub line_height: Option<f32>,
}

#[derive(Debug, Clone, Copy)]
pub struct QaPage<'a> {
    pub original: &'a RgbImage,
    pub cleaned: &'a RgbImage,
    pub final_image: &'a RgbImage,
    pub authorized: &'a GrayImage,
    pub regions: &'a [QaRegion<'a>],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Finding {
    pub code: String,
    pub region: Option<String>,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct QaReport {
    pub ok: bool,
    pub errors: usize,
    pub warnings: usize,
    pub artwork_pixels_changed: u64,
    pub findings: Vec<Finding>,
}

impl QaReport {
    fn new() -> Self {
        Self {
            ok: true,
            errors: 0,
            warnings: 0,
            artwork_pixels_changed: 0,
            findings: Vec::new(),
        }
    }
    fn add(&mut self, code: &str, region: Option<&str>, detail: impl Into<String>) {
        self.findings.push(Finding {
            code: code.into(),
            region: region.map(str::to_owned),
            detail: detail.into(),
        });
        self.errors += 1;
        self.ok = false;
    }
}

pub fn run_strict_qa(page: QaPage<'_>) -> Result<QaReport> {
    let QaPage {
        original,
        cleaned,
        final_image,
        authorized,
        regions,
    } = page;
    let mut report = QaReport::new();
    for stage in qachecks::check_page_dimensions(
        original.dimensions(),
        cleaned.dimensions(),
        final_image.dimensions(),
    ) {
        report.add(
            "page-dimensions",
            None,
            format!("{stage} page dimensions differ from the original"),
        );
    }
    if original.dimensions() != authorized.dimensions() {
        report.add(
            "mask-dimensions",
            None,
            "mask dimensions differ from the original",
        );
    }
    if !report.ok {
        return Ok(report);
    }
    let clean_diff = compare_outside_mask(original, cleaned, authorized)?;
    let final_diff = compare_outside_mask(original, final_image, authorized)?;
    report.artwork_pixels_changed = clean_diff.changed.max(final_diff.changed);
    if report.artwork_pixels_changed != 0 {
        report.add(
            "artwork-changed",
            None,
            format!(
                "outside-mask artwork changed: {} pixels during cleaning, {} on the final page",
                clean_diff.changed, final_diff.changed
            ),
        );
    }
    let (w, h) = (i128::from(original.width()), i128::from(original.height()));
    let halo = qacore_rs::port::detect_halo_artifacts(
        Some(original.as_raw()),
        Some(cleaned.as_raw()),
        Some(authorized.as_raw()),
        w,
        h,
        3,
        8,
    )
    .map_err(VisionError::kernel)?;
    if halo.first().is_some_and(|&p| p > 0) {
        report.add(
            "halo-artifact",
            None,
            format!("{} changed pixels in the mask surround", halo[0]),
        );
    }
    let boxes = regions
        .iter()
        .filter_map(|r| r.ink_box.map(|b| (r.id, b)))
        .collect::<Vec<_>>();
    for o in qachecks::rendered_text_overlaps(&boxes) {
        report.add(
            "text-overlap",
            Some(&o.first),
            format!("overlaps {} by {} pixels", o.second, o.intersection.area()),
        );
    }
    for region in regions {
        if !bidi::has_logical_order(region.target)? {
            report.add(
                "missing-rli-pdi",
                Some(region.id),
                "target does not have logical Persian direction controls",
            );
        }
        for issue in falint::lint_text(region.target)? {
            if issue.code != "missing-rli-pdi" {
                report.add(&issue.code, Some(region.id), issue.detail);
            }
        }
        if let Some((size, spacing)) = region.font_size.zip(region.line_height)
            && (!size.is_finite()
                || !spacing.is_finite()
                || size <= 0.0
                || spacing < size * crate::typefit::MIN_LINE_HEIGHT)
        {
            report.add(
                "tight-line-spacing",
                Some(region.id),
                "line-height ratio is below 1.38",
            );
        }
        if let Some(b) = region.balloon {
            match qachecks::full_balloon_surviving_ink(original, cleaned, b) {
                Ok(0) => {}
                Ok(n) => report.add(
                    "balloon-ink-survives",
                    Some(region.id),
                    format!("{n} ink pixels remain in the cleared balloon"),
                ),
                Err(VisionError::Invalid(detail)) => {
                    report.add("unsafe-balloon", Some(region.id), detail)
                }
                Err(other) => return Err(other),
            }
        }
        let Some(b) = region.ink_box else {
            if !region.target.trim().is_empty() {
                report.add(
                    "text-not-rendered",
                    Some(region.id),
                    "no rendered footprint",
                );
            }
            continue;
        };
        b.checked(original.dimensions())?;
        let sample = b.expand(4, original.width(), original.height());
        let crop = |im: &RgbImage| {
            imageops::crop_imm(im, sample.x(), sample.y(), sample.width(), sample.height())
                .to_image()
        };
        let before = crop(cleaned);
        let after = crop(final_image);
        let (sw, sh) = (i64::from(sample.width()), i64::from(sample.height()));
        let changed = from_raw(
            before.dimensions(),
            pixcore_rs::port::changed_mask_rgb(before.as_raw(), after.as_raw(), sw, sh, 32)
                .map_err(VisionError::kernel)?,
        )?;
        let contrast = qacore_rs::port::measure_region_contrast(
            Some(after.as_raw()),
            Some(changed.as_raw()),
            i128::from(sw),
            i128::from(sh),
            3,
        )
        .map_err(VisionError::kernel)?;
        if contrast.first().is_none_or(|&x| x < 3.0) {
            report.add(
                "low-contrast",
                Some(region.id),
                "rendered lettering has less than 3:1 contrast",
            );
        }
        if let Some(balloon) = region.balloon {
            let crossing =
                qachecks::text_crosses_outline(original, cleaned, final_image, balloon, b)?;
            let outline = |im: &RgbImage| gray(&crop(im), balloon.dark);
            let (mut o, f) = (outline(original), outline(final_image));
            let safe = qachecks::balloon_text_interior(original, balloon)?;
            let mut shown = changed;
            for (x, y, baseline) in o.enumerate_pixels_mut() {
                let (gx, gy) = (x + sample.x(), y + sample.y());
                if safe.bounds.contains(gx, gy)
                    && safe
                        .pixels
                        .get_pixel(gx - safe.bounds.x(), gy - safe.bounds.y())[0]
                        != 0
                {
                    // Original glyphs inside the balloon are supposed to be erased.
                    baseline[0] = 255;
                    shown.get_pixel_mut(x, y)[0] = 0;
                }
            }
            let bleed = qacore_rs::port::detect_outline_bleed(
                Some(o.as_raw()),
                Some(f.as_raw()),
                i128::from(sw),
                i128::from(sh),
                Some(shown.as_raw()),
                90,
                12,
            )
            .map_err(VisionError::kernel)?;
            let affected = crossing.max(bleed.iter().take(2).copied().sum::<i64>() as u64);
            if affected > 0 {
                report.add(
                    "text-crosses-outline",
                    Some(region.id),
                    format!("{affected} pixels outside the safe balloon interior"),
                );
            }
        }
    }
    Ok(report)
}

/// Checks decoded package rasters in manifest order. Container integrity belongs to the reader.
pub fn check_package(expected: &[RgbImage], decoded: &[RgbImage]) -> QaReport {
    let mut report = QaReport::new();
    if expected.len() != decoded.len() || expected.is_empty() {
        report.add(
            "package-page-count",
            None,
            format!(
                "expected {} pages, package has {}",
                expected.len(),
                decoded.len()
            ),
        );
    }
    for (i, (before, after)) in expected.iter().zip(decoded).enumerate() {
        if before.dimensions() != after.dimensions() {
            report.add(
                "package-page-dimensions",
                None,
                format!("page {} has the wrong dimensions", i + 1),
            );
        } else if before.as_raw() != after.as_raw() {
            report.add(
                "package-image-mismatch",
                None,
                format!("page {} differs from its approved raster", i + 1),
            );
        }
    }
    report
}
