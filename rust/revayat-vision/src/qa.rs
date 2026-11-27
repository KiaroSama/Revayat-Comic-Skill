use crate::{
    Rect, Result, VisionError, bidi, falint,
    masks::{Balloon, from_raw},
    qachecks, same_geometry,
};
use image::{GrayImage, RgbImage, imageops};
use serde::{Deserialize, Serialize};

/// Stable finding identifiers emitted by the image, typography, and package QA gates.
pub const CODES: &[&str] = &[
    "arabic-forms",
    "artwork-changed",
    "balloon-ink-survives",
    "double-punctuation",
    "guillemets",
    "halo-artifact",
    "latin-quotes",
    "low-contrast",
    "mask-dimensions",
    "missing-rli-pdi",
    "package-image-mismatch",
    "package-page-count",
    "package-page-dimensions",
    "page-dimensions",
    "protected-japanese-modified",
    "script-collision",
    "source-script-left",
    "text-crosses-outline",
    "text-not-rendered",
    "text-overlap",
    "tight-line-spacing",
    "unsafe-balloon",
    "untranslated",
    "zwnj-review",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diff {
    pub changed: u64,
    pub total: u64,
    pub worst_delta: u8,
}

/// WCAG 2.1 relative luminance for an sRGB triple.
fn srgb_luminance(rgb: [u8; 3]) -> f64 {
    let linear = |c: u8| {
        let s = f64::from(c) / 255.0;
        if s <= 0.03928 {
            s / 12.92
        } else {
            ((s + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * linear(rgb[0]) + 0.7152 * linear(rgb[1]) + 0.0722 * linear(rgb[2])
}

/// WCAG 2.1 contrast ratio between two sRGB triples.
pub fn rgb_contrast(a: [u8; 3], b: [u8; 3]) -> f64 {
    let (la, lb) = (srgb_luminance(a), srgb_luminance(b));
    let (hi, lo) = if la >= lb { (la, lb) } else { (lb, la) };
    (hi + 0.05) / (lo + 0.05)
}

/// Internal p5-vs-p95 WCAG contrast inside a solid external patch that includes both art and lettering.
fn patch_internal_contrast(after: &RgbImage, changed: &GrayImage) -> f64 {
    let mut lumas: Vec<f64> = after
        .pixels()
        .zip(changed.pixels())
        .filter(|(_, m)| m[0] != 0)
        .map(|(p, _)| srgb_luminance(p.0))
        .collect();
    if lumas.len() < 4 {
        return 0.0;
    }
    lumas.sort_by(f64::total_cmp);
    let idx = lumas.len() / 100;
    let lo = lumas[idx];
    let hi = lumas[lumas.len() - 1 - idx];
    (hi + 0.05) / (lo + 0.05)
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

/// Lint decisions whose region and content fingerprints have been checked by the caller.
#[derive(Debug, Clone, Copy)]
pub struct QaTextReview<'a> {
    pub region: &'a str,
    pub acknowledged: &'a [&'a str],
    pub spans: Option<&'a [&'a str]>,
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
        debug_assert!(CODES.contains(&code), "undeclared QA finding: {code}");
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
    run_strict_qa_with_reviews(page, &[])
}

pub fn run_strict_qa_with_reviews(
    page: QaPage<'_>,
    reviews: &[QaTextReview<'_>],
) -> Result<QaReport> {
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
        let reviewed = reviews.iter().find(|review| review.region == region.id);
        let issues = match reviewed {
            Some(review) => {
                falint::lint_acknowledged(region.target, review.acknowledged, review.spans)?
            }
            None => falint::lint_text(region.target)?,
        };
        for issue in issues {
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
        let sample = b;
        let crop = |im: &RgbImage| {
            imageops::crop_imm(im, sample.x(), sample.y(), sample.width(), sample.height())
                .to_image()
        };
        let before = crop(cleaned);
        let after = crop(final_image);
        let (sw, sh) = (i64::from(sample.width()), i64::from(sample.height()));
        let changed = from_raw(
            before.dimensions(),
            pixcore_rs::port::changed_mask_rgb(before.as_raw(), after.as_raw(), sw, sh, 8)
                .map_err(VisionError::kernel)?,
        )?;
        let visible = region.target.chars().filter(|&c| bidi::visible(c)).count();
        let ink_count = changed.pixels().filter(|p| p[0] != 0).count();
        let min_ink = region
            .font_size
            .map_or(1, |size| ((size * size) / 100.0).max(1.0) as usize);
        if ink_count < visible.saturating_mul(min_ink) {
            report.add(
                "text-not-rendered",
                Some(region.id),
                format!("{ink_count} ink pixels for {visible} visible characters"),
            );
        }
        let contrast = qacore_rs::port::measure_region_contrast(
            Some(after.as_raw()),
            Some(changed.as_raw()),
            i128::from(sw),
            i128::from(sh),
            3,
        )
        .map_err(VisionError::kernel)?;
        let mut has_contrast = contrast.first().is_some_and(|&x| x >= 3.0);
        if !has_contrast && region.font_size.is_none() && region.balloon.is_none() {
            has_contrast = patch_internal_contrast(&after, &changed) >= 3.0;
        }
        if !has_contrast {
            report.add(
                "low-contrast",
                Some(region.id),
                "rendered lettering has less than 3:1 contrast",
            );
        }
        if let Some(balloon) = region.balloon {
            let crossing =
                qachecks::text_crosses_outline(original, cleaned, final_image, balloon, b)?;
            if crossing > 0 {
                report.add(
                    "text-crosses-outline",
                    Some(region.id),
                    format!("{crossing} pixels outside safe paper or on dark artwork"),
                );
            }
        }
    }
    Ok(report)
}

/// Re-shape the recorded lines and compare each visible cluster with delivered pixels.
pub fn missing_clusters(
    shaper: &mut crate::typefont::Shaper,
    target: &str,
    lines: &[crate::typefit::PlacedLine],
    size: f32,
    style: &crate::typestyle::TextStyle,
    clean: &RgbImage,
    rendered: &RgbImage,
) -> Result<usize> {
    missing_clusters_in_direction(shaper, target, lines, size, style, clean, rendered, false)
}

#[allow(clippy::too_many_arguments)]
pub fn missing_clusters_in_direction(
    shaper: &mut crate::typefont::Shaper,
    target: &str,
    lines: &[crate::typefit::PlacedLine],
    size: f32,
    style: &crate::typestyle::TextStyle,
    clean: &RgbImage,
    rendered: &RgbImage,
    rtl_target: bool,
) -> Result<usize> {
    same_geometry(clean.dimensions(), rendered.dimensions())?;
    let logical = |s: &str| {
        let text = s
            .chars()
            .filter(|c| {
                !matches!(c, '\u{061c}' | '\u{200e}'..='\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
            })
            .collect::<String>();
        // Wrapping may normalize whitespace and punctuation, but never word or join boundaries.
        let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
        crate::typefit::tokens(&text)
            .into_iter()
            .flatten()
            .collect::<Vec<_>>()
            .join(" ")
    };
    let expected = logical(target);
    let mut placed = String::new();
    for line in lines {
        let part = line.text.trim();
        if !placed.is_empty() {
            let hyphen_join = placed.ends_with('-')
                && part.chars().next().is_some_and(bidi::is_rtl_char)
                && !expected.contains("- ");
            if !hyphen_join {
                placed.push(' ');
            }
        }
        placed.push_str(part);
    }
    if logical(&placed) != expected {
        return Ok(expected.chars().count().max(1));
    }
    let rtl = bidi::should_shape_rtl(target, rtl_target);
    let mut missing = 0;
    for line in lines {
        line.bbox.checked(clean.dimensions())?;
        let shaped = shaper.draw_in_direction(&line.text, size, style.weight(), rtl)?;
        let expected_width = shaped.pixels.width()
            + if style.italic {
                (shaped.pixels.height() as f32 * 0.16).ceil() as u32
            } else {
                0
            };
        if line.bbox.width() != expected_width || line.bbox.height() != shaped.pixels.height() {
            missing += shaped.clusters.len().max(1);
            continue;
        }
        for ink in shaped.cluster_ink {
            let present = ink
                .iter()
                .filter(|&&(x, y)| {
                    let italic = if style.italic {
                        ((shaped.pixels.height() - y - 1) as f32 * 0.16).round() as u32
                    } else {
                        0
                    };
                    let (x, y) = (line.bbox.x() + x + italic, line.bbox.y() + y);
                    qachecks::pixel_changed(clean.get_pixel(x, y), rendered.get_pixel(x, y))
                })
                .count();
            if present == 0 || present * 3 < ink.len() {
                missing += 1;
            }
        }
    }
    Ok(missing)
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

#[cfg(test)]
mod coverage_tests {
    use super::*;
    use crate::{
        typefont::Shaper,
        typeset::{self, TextRegion},
    };
    use image::Rgb;

    #[test]
    fn finds_one_missing_leading_digit_when_the_rest_still_has_ink() -> Result<()> {
        let original = RgbImage::from_pixel(220, 100, Rgb([245; 3]));
        let target = "۳ و ۸…";
        let request = TextRegion::new("digit", Rect([10, 10, 200, 80]), target);
        let style = request.style.clone();
        let result = typeset::typeset_page(&original, &[request])?;
        let region = &result.regions[0];
        let mut shaper = Shaper::new()?;
        assert_eq!(
            missing_clusters(
                &mut shaper,
                target,
                &region.lines,
                region.font_size,
                &style,
                &original,
                &result.image
            )?,
            0
        );
        let mut broken = result.image.clone();
        let line = &region.lines[0];
        let shape = shaper.draw(&line.text, region.font_size, style.weight())?;
        for &(x, y) in &shape.cluster_ink[0] {
            broken.put_pixel(line.bbox.x() + x, line.bbox.y() + y, Rgb([245; 3]));
        }
        assert_eq!(
            missing_clusters(
                &mut shaper,
                target,
                &region.lines,
                region.font_size,
                &style,
                &original,
                &broken
            )?,
            1
        );
        Ok(())
    }
}
