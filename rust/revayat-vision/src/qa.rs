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

/// Core-stroke WCAG contrast against unchanged surround, avoiding false failures from anti-aliased glyph edges.
fn core_stroke_contrast(after: &RgbImage, changed: &GrayImage) -> f64 {
    let mut bg = Vec::new();
    let mut fg = Vec::new();
    for (p, m) in after.pixels().zip(changed.pixels()) {
        let l = srgb_luminance(p.0);
        if m[0] == 0 {
            bg.push(l);
        } else {
            fg.push(l);
        }
    }
    if bg.is_empty() || fg.len() < 4 {
        return 0.0;
    }
    bg.sort_by(f64::total_cmp);
    let bg_luma = bg[bg.len() / 2];
    fg.sort_by(|a, b| (b - bg_luma).abs().total_cmp(&(a - bg_luma).abs()));
    let core_len = (fg.len() * 3 / 10).max(1);
    let fg_luma = fg[core_len / 2];
    let (hi, lo) = if fg_luma >= bg_luma {
        (fg_luma, bg_luma)
    } else {
        (bg_luma, fg_luma)
    };
    (hi + 0.05) / (lo + 0.05)
}

/// Internal p1-vs-p99 WCAG contrast inside a solid external patch that includes both art and lettering.
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
        if !has_contrast {
            has_contrast = if region.font_size.is_none() && region.balloon.is_none() {
                patch_internal_contrast(&after, &changed) >= 3.0
            } else {
                core_stroke_contrast(&after, &changed) >= 3.0
            };
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

/// Checks that each shaped cluster survives rotation and that the core strokes contrast.
pub fn verify_rotated_ink(
    shaper: &mut crate::typefont::Shaper,
    target: &str,
    region: &crate::typeset::TypesetRegion,
    style: &crate::typestyle::TextStyle,
    clean: &RgbImage,
    rendered: &RgbImage,
    rtl_target: bool,
) -> Result<()> {
    use crate::{mask_bounds, typefit, typestyle};

    same_geometry(clean.dimensions(), rendered.dimensions())?;
    let b = region.ink_box.checked(clean.dimensions())?;
    let angle = region.angle_deg;
    if !angle.is_finite() || !(typestyle::MIN_ROTATION_DEG..=45.0).contains(&angle.abs()) {
        return Err(VisionError::invalid("invalid rotated lettering angle"));
    }
    if missing_line_text(target, &region.lines).is_some() {
        return Err(VisionError::invalid(
            "rotated lines do not match the target text",
        ));
    }
    let rtl = bidi::should_shape_rtl(target, rtl_target);
    let mut lines = Vec::new();
    let mut clusters = Vec::new();
    for line in &region.lines {
        line.bbox.checked(clean.dimensions())?;
        let shaped = shaper.draw_in_direction(&line.text, region.font_size, style.weight(), rtl)?;
        let ink = if style.italic {
            typestyle::italicize(&shaped.pixels)
        } else {
            shaped.pixels
        };
        if ink.dimensions() != (line.bbox.width(), line.bbox.height()) {
            return Err(VisionError::invalid(
                "rotated line bounds do not match the shaped ink",
            ));
        }
        clusters.extend(
            shaped
                .cluster_ink
                .into_iter()
                .filter(|cluster| !cluster.is_empty())
                .map(|cluster| {
                    cluster
                        .into_iter()
                        .map(|(x, y)| {
                            let dx = if style.italic {
                                typestyle::italic_shift(ink.height(), y)
                            } else {
                                0
                            };
                            (line.bbox.x() + x + dx, line.bbox.y() + y)
                        })
                        .collect::<Vec<_>>()
                }),
        );
        lines.push((line.clone(), ink));
    }
    let extent = lines
        .iter()
        .map(|(line, _)| line.bbox)
        .reduce(Rect::union)
        .ok_or_else(|| VisionError::invalid("missing rotated lines"))?;
    let rotated = typefit::rotate_line_ink(&lines, extent, angle);
    let tight = mask_bounds(&rotated)
        .ok_or_else(|| VisionError::invalid("missing expected rotated ink"))?;
    let border = region.outline_px;
    let [dx, dy] = style
        .shadow
        .then(|| typestyle::shadow_offset(angle))
        .unwrap_or_default();
    if border > 6
        || b.width() != tight.width() + 2 * border + dx.unsigned_abs() as u32
        || b.height() != tight.height() + 2 * border + dy.unsigned_abs() as u32
    {
        return Err(VisionError::invalid(
            "rotated ink does not fit its recorded footprint",
        ));
    }
    let glyph_x = b.x() + border + (-dx).max(0) as u32;
    let glyph_y = b.y() + border + (-dy).max(0) as u32;
    let mut coverage = GrayImage::new(rotated.width(), rotated.height());
    let (mut expected, mut changed, mut contrasting) = (0_u64, 0_u64, 0_u64);
    for (x, y, alpha) in rotated.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
        let x_page = glyph_x + (x - tight.x());
        let y_page = glyph_y + (y - tight.y());
        let before = clean.get_pixel(x_page, y_page);
        let after = rendered.get_pixel(x_page, y_page);
        let present = qachecks::pixel_changed(before, after);
        coverage.get_pixel_mut(x, y)[0] = u8::from(present);
        if alpha[0] >= 64 {
            expected += 1;
            changed += u64::from(present);
            contrasting += u64::from(present && rgb_contrast(before.0, after.0) >= 3.0);
        }
    }
    if expected == 0 || changed * 5 < expected * 3 {
        return Err(VisionError::invalid(
            "less than 60% of expected rotated ink is visible",
        ));
    }
    if contrasting < changed.div_ceil(10) {
        return Err(VisionError::invalid(
            "rotated lettering has less than 3:1 core-stroke contrast",
        ));
    }

    // Forward-map the source cluster cores into the same canvas used by the renderer.
    let (sin, cos) = f64::from(angle).to_radians().sin_cos();
    let center = |size| (f64::from(size) - 1.0) * 0.5;
    for cluster in clusters {
        let present = cluster
            .iter()
            .filter(|&&(x, y)| {
                let x = f64::from(x - extent.x()) - center(extent.width());
                let y = f64::from(y - extent.y()) - center(extent.height());
                let rx = (cos * x - sin * y + center(rotated.width())).round() as u32;
                let ry = (sin * x + cos * y + center(rotated.height())).round() as u32;
                coverage
                    .get_pixel_checked(rx, ry)
                    .is_some_and(|pixel| pixel[0] != 0)
            })
            .count();
        if present * 5 < cluster.len() * 3 {
            return Err(VisionError::invalid(
                "a shaped cluster is missing rotated ink",
            ));
        }
    }
    Ok(())
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

fn missing_line_text(target: &str, lines: &[crate::typefit::PlacedLine]) -> Option<usize> {
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
        let part = logical(&line.text);
        if part.is_empty() {
            continue;
        }
        let spaced = logical(&format!("{placed} {part}"));
        if expected.starts_with(&spaced) {
            placed = spaced;
            continue;
        }
        // A wrapped hyphen keeps its authored boundary, independently of other hyphens,
        // directional isolates, or a digit at the start of the following compound part.
        if placed.ends_with('-') {
            placed.push_str(&part);
            if expected.starts_with(&placed) {
                continue;
            }
        }
        return Some(expected.chars().count().max(1));
    }
    (placed != expected).then(|| expected.chars().count().max(1))
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
    if let Some(missing) = missing_line_text(target, lines) {
        return Ok(missing);
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
                        crate::typestyle::italic_shift(shaped.pixels.height(), y)
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
    fn rejects_a_missing_short_line_in_a_rotated_block() -> Result<()> {
        let original = RgbImage::from_pixel(320, 180, Rgb([245; 3]));
        let target = "MIDNIGHT EXPRESS\nA";
        let mut request = TextRegion::new("title", Rect([10, 10, 300, 160]), target);
        request.min_size = 28;
        request.max_size = 28;
        request.style.angle_deg = Some(-5.0);
        let style = request.style.clone();
        let result = typeset::typeset_page(&original, &[request])?;
        let region = &result.regions[0];
        let mut shaper = Shaper::new()?;
        verify_rotated_ink(
            &mut shaper,
            target,
            region,
            &style,
            &original,
            &result.image,
            false,
        )?;

        let mut broken = result.image.clone();
        let split = region.lines[1].bbox.y() - 2;
        for y in split..region.ink_box.bottom() {
            for x in region.ink_box.x()..region.ink_box.right() {
                broken.put_pixel(x, y, *original.get_pixel(x, y));
            }
        }
        assert!(
            verify_rotated_ink(
                &mut shaper,
                target,
                region,
                &style,
                &original,
                &broken,
                false
            )
            .is_err()
        );
        Ok(())
    }

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
