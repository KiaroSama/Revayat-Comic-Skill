use crate::{
    Rect, Result, VisionError, gray, mask_bounds,
    masks::{Balloon, balloon_interior},
};
use image::{GrayImage, Luma, RgbImage};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(default)]
pub struct DetectionOptions {
    pub balloon_min_area: f64,
    pub balloon_max_area: f64,
    pub balloon_min_side: f64,
    pub balloon_min_solidity: f64,
    pub ink_min: f64,
    pub ink_max: f64,
    pub glyph_min: f64,
    pub glyph_max: f64,
    pub gutter_max_ink: f64,
    pub gutter_min_span: f64,
    pub panel_min_area: f64,
    pub sfx_min_side: f64,
    pub sfx_min_glyphs: u32,
    pub sfx_size_uniformity: f64,
    pub sfx_max_spread: f64,
    pub find_sfx: bool,
    pub rtl: bool,
}
impl Default for DetectionOptions {
    fn default() -> Self {
        Self {
            balloon_min_area: 0.0006,
            balloon_max_area: 0.13,
            balloon_min_side: 0.05,
            balloon_min_solidity: 0.42,
            ink_min: 0.015,
            ink_max: 0.55,
            glyph_min: 0.004,
            glyph_max: 0.22,
            gutter_max_ink: 0.008,
            gutter_min_span: 0.012,
            panel_min_area: 0.02,
            sfx_min_side: 0.035,
            sfx_min_glyphs: 3,
            sfx_size_uniformity: 0.80,
            sfx_max_spread: 1.5,
            find_sfx: true,
            rtl: true,
        }
    }
}

impl DetectionOptions {
    pub fn validate(&self) -> Result<()> {
        if ![
            self.balloon_min_area,
            self.balloon_max_area,
            self.balloon_min_side,
            self.balloon_min_solidity,
            self.ink_min,
            self.ink_max,
            self.glyph_min,
            self.glyph_max,
            self.gutter_max_ink,
            self.gutter_min_span,
            self.panel_min_area,
            self.sfx_min_side,
            self.sfx_size_uniformity,
        ]
        .into_iter()
        .all(|value| (0.0..=1.0).contains(&value))
            || self.balloon_min_area >= self.balloon_max_area
            || self.ink_min >= self.ink_max
            || self.glyph_min >= self.glyph_max
            || self.sfx_min_glyphs == 0
            || !self.sfx_max_spread.is_finite()
            || self.sfx_max_spread <= 0.0
        {
            return Err(VisionError::invalid(
                "invalid panel or text detection ratios",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DetectedRegion {
    pub bbox: Rect,
    pub balloon: Option<Balloon>,
    pub kind: String,
    pub orientation: String,
    pub confidence: f64,
    pub detector: String,
    pub polarity: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Detection {
    pub regions: Vec<DetectedRegion>,
    pub panels: Vec<Rect>,
    pub size: [u32; 2],
}

pub fn find_panels(image: &GrayImage, rtl: bool) -> Result<Vec<Rect>> {
    find_panels_with_options(
        image,
        &DetectionOptions {
            rtl,
            ..DetectionOptions::default()
        },
    )
}

fn find_panels_with_options(image: &GrayImage, options: &DetectionOptions) -> Result<Vec<Rect>> {
    let [w, h] = [image.width(), image.height()];
    if w == 0 || h == 0 {
        return Err(VisionError::invalid("page has no pixels"));
    }
    let gutter = (f64::from(w.min(h)) * options.gutter_min_span)
        .floor()
        .max(2.0) as i64;
    let panels = detectcore_rs::port::find_panel_gutters_with_ink(
        Some(image.as_raw()),
        i64::from(w),
        i64::from(h),
        238,
        gutter,
        0,
        options.gutter_max_ink,
    )
    .map_err(VisionError::kernel)?;
    let mut panels: Vec<_> = panels
        .into_iter()
        .map(|[x, y, w, h]| Rect([x as u32, y as u32, w as u32, h as u32]))
        .filter(|panel| panel.area() as f64 >= options.panel_min_area * f64::from(w) * f64::from(h))
        .collect();
    if panels.len() <= 1 {
        panels.clear();
    }
    order(panels, options.rtl, h)
}

fn order(boxes: Vec<Rect>, rtl: bool, height: u32) -> Result<Vec<Rect>> {
    let keys = boxes.iter().map(|b| b.0.map(i64::from)).collect();
    let sorted = detectcore_rs::port::sort_reading_order(
        Some(keys),
        Some(rtl),
        i64::from((height / 32).max(1)),
    )
    .map_err(VisionError::kernel)?;
    Ok(sorted.into_iter().map(|i| boxes[i]).collect())
}

fn region(bbox: Rect, balloon: Option<Balloon>, dark: bool) -> DetectedRegion {
    let (kind, confidence, detector) = if balloon.is_some() {
        ("speech", 0.85, "balloon")
    } else {
        ("sfx", 0.35, "free")
    };
    DetectedRegion {
        bbox,
        balloon,
        kind: kind.into(),
        orientation: if f64::from(bbox.height()) > 1.6 * f64::from(bbox.width()) {
            "vertical"
        } else {
            "horizontal"
        }
        .into(),
        confidence,
        detector: detector.into(),
        polarity: if dark { "dark" } else { "light" }.into(),
    }
}

fn balloons(
    page: &RgbImage,
    oriented: &GrayImage,
    dark: bool,
    options: &DetectionOptions,
) -> Result<Vec<DetectedRegion>> {
    let (w, h) = page.dimensions();
    let area = f64::from(w) * f64::from(h);
    let side = f64::from(w.min(h));
    let candidates = detectcore_rs::port::detect_speech_balloons(
        Some(oriented.as_raw()),
        i64::from(w),
        i64::from(h),
        190,
        (area * options.balloon_min_area).ceil().max(8.0) as i64,
        options.balloon_max_area,
        options.balloon_min_solidity,
    )
    .map_err(VisionError::kernel)?;
    candidates
        .into_par_iter()
        .filter_map(|[x, y, bw, bh, _]| {
            if (bw.min(bh) as f64) < side * options.balloon_min_side {
                return None;
            }
            let bounds = Rect([x as u32, y as u32, bw as u32, bh as u32]).expand(2, w, h);
            let b = Balloon {
                bounds,
                text_bounds: bounds,
                dark,
            };
            let interior = match balloon_interior(page, b, 1) {
                Ok(m) => m,
                Err(e) => return Some(Err(e)),
            };
            let mut count = 0usize;
            let ink = GrayImage::from_fn(bounds.width(), bounds.height(), |x, y| {
                let inside = interior.pixels.get_pixel(x, y)[0] != 0;
                count += usize::from(inside);
                Luma([
                    if inside && oriented.get_pixel(x + bounds.x(), y + bounds.y())[0] <= 175 {
                        255
                    } else {
                        0
                    },
                ])
            });
            let local = mask_bounds(&ink)?;
            let share = ink.pixels().filter(|p| p[0] != 0).count() as f64 / count.max(1) as f64;
            if !(options.ink_min..=options.ink_max).contains(&share) {
                return None;
            }
            let bbox = Rect([
                local.x() + bounds.x(),
                local.y() + bounds.y(),
                local.width(),
                local.height(),
            ]);
            Some(Ok(region(
                bbox,
                Some(Balloon {
                    text_bounds: bbox,
                    ..b
                }),
                dark,
            )))
        })
        .collect()
}

fn lettering_extent(
    group: Vec<Vec<i64>>,
    min_side: f64,
    options: &DetectionOptions,
) -> Option<Rect> {
    let glyphs = group
        .into_iter()
        .filter_map(|b| <[i64; 4]>::try_from(b).ok())
        .map(|b| Rect(b.map(|x| x as u32)))
        .collect::<Vec<_>>();
    if glyphs.len() < options.sfx_min_glyphs as usize {
        return None;
    }
    let dim = |b: Rect| f64::from(b.width().max(b.height()));
    let mut sizes = glyphs.iter().copied().map(dim).collect::<Vec<_>>();
    sizes.sort_unstable_by(f64::total_cmp);
    let mid = sizes.len() / 2;
    let median = (sizes[mid] + sizes[(sizes.len() - 1) / 2]) / 2.0;
    let (mut body, satellites): (Vec<_>, Vec<_>) =
        glyphs.into_iter().partition(|&b| dim(b) >= 0.55 * median);
    for s in satellites {
        let [x, y] = s.center().map(f64::from);
        let gap = |b: Rect| {
            (f64::from(b.x()).max(x) - f64::from(b.right()).min(x))
                .hypot(f64::from(b.y()).max(y) - f64::from(b.bottom()).min(y))
        };
        if let Some(host) = body
            .iter_mut()
            .filter(|b| gap(**b) <= 0.75 * dim(**b))
            .min_by(|a, b| gap(**a).total_cmp(&gap(**b)))
        {
            *host = host.union(s);
        } else {
            body.push(s);
        }
    }
    let n = body.len() as f64;
    if n < f64::from(options.sfx_min_glyphs)
        || (body
            .iter()
            .filter(|&&b| (0.55 * median..=1.8 * median).contains(&dim(b)))
            .count() as f64)
            / n
            < options.sfx_size_uniformity
    {
        return None;
    }
    let (sx, sy) = body.iter().fold((0.0, 0.0), |(sx, sy), b| {
        let [x, y] = b.center().map(f64::from);
        (sx + x, sy + y)
    });
    let (xx, yy, xy) = body.iter().fold((0.0, 0.0, 0.0), |(xx, yy, xy), b| {
        let [x, y] = b.center().map(f64::from);
        let (x, y) = (x - sx / n, y - sy / n);
        (xx + x * x, yy + y * y, xy + x * y)
    });
    let spread = ((xx + yy - (xx - yy).hypot(2.0 * xy)) / (2.0 * n))
        .max(0.0)
        .sqrt();
    if spread > options.sfx_max_spread * median {
        return None;
    }
    body.into_iter()
        .reduce(Rect::union)
        .filter(|&b| dim(b) >= min_side)
}

fn free_lettering(
    oriented: &GrayImage,
    taken: &[DetectedRegion],
    dark: bool,
    options: &DetectionOptions,
) -> Result<Vec<DetectedRegion>> {
    let (w, h) = oriented.dimensions();
    let side = f64::from(w.min(h));
    let threshold = imageproc::contrast::otsu_level(oriented);
    let ink = GrayImage::from_fn(w, h, |x, y| {
        Luma([if oriented.get_pixel(x, y)[0] <= threshold {
            255
        } else {
            0
        }])
    });
    let parts = detectcore_rs::port::connected_components_boxes(
        Some(ink.as_raw()),
        i64::from(w),
        i64::from(h),
        3,
        (side * options.glyph_max).powi(2).ceil().max(3.0) as i64,
    )
    .map_err(VisionError::kernel)?;
    let mut seeds = Vec::new();
    for [x, y, bw, bh, area] in parts {
        let b = Rect([x as u32, y as u32, bw as u32, bh as u32]);
        if (side * options.glyph_min..=side * options.glyph_max).contains(&(bw.max(bh) as f64))
            && area as f64 / b.area() as f64 >= 0.12
            && !taken.iter().any(|r| {
                r.balloon
                    .map_or(r.bbox, |b| b.bounds)
                    .intersection(b)
                    .is_some()
            })
        {
            seeds.push(b.0.map(i64::from).to_vec());
        }
    }
    let groups = hotcore_rs::port::cluster_boxes(seeds, Some(400), Some(1.1))
        .map_err(VisionError::kernel)?;
    Ok(groups
        .into_iter()
        .filter_map(|g| {
            let extent = lettering_extent(g, side * options.sfx_min_side, options)?;
            let relative = extent.area() as f64 / (f64::from(w) * f64::from(h));
            (0.00015..0.10)
                .contains(&relative)
                .then(|| region(extent, None, dark))
        })
        .collect())
}

/// Orders panels before their text, leaving regions outside every panel last.
pub fn order_regions(
    regions: &[DetectedRegion],
    panels: &[Rect],
    rtl: bool,
    height: u32,
) -> Result<Vec<usize>> {
    let tolerance = i64::from((height / 32).max(1));
    let sort = |indices: &[usize]| -> Result<Vec<usize>> {
        let boxes = indices
            .iter()
            .map(|&i| regions[i].bbox.0.map(i64::from))
            .collect();
        let sorted = detectcore_rs::port::sort_reading_order(Some(boxes), Some(rtl), tolerance)
            .map_err(VisionError::kernel)?;
        Ok(sorted.into_iter().map(|i| indices[i]).collect())
    };
    if panels.is_empty() {
        return sort(&(0..regions.len()).collect::<Vec<_>>());
    }
    let panel_order = detectcore_rs::port::sort_reading_order(
        Some(panels.iter().map(|p| p.0.map(i64::from)).collect()),
        Some(rtl),
        tolerance,
    )
    .map_err(VisionError::kernel)?;
    let mut groups = vec![Vec::new(); panels.len() + 1];
    for (index, region) in regions.iter().enumerate() {
        let panel = panels.iter().position(|panel| {
            region.bbox.intersection(*panel).is_some_and(|overlap| {
                u128::from(overlap.area()) * 5 >= u128::from(region.bbox.area()) * 3
            })
        });
        groups[panel.unwrap_or(panels.len())].push(index);
    }
    let mut result = Vec::with_capacity(regions.len());
    for panel in panel_order.into_iter().chain(std::iter::once(panels.len())) {
        result.extend(sort(&groups[panel])?);
    }
    Ok(result)
}

pub fn detect_page(page: &RgbImage, options: &DetectionOptions) -> Result<Detection> {
    let (w, h) = page.dimensions();
    options.validate()?;
    let light = gray(page, false);
    let panels = find_panels_with_options(&light, options)?;
    let dark = gray(page, true);
    let mut regions = balloons(page, &light, false, options)?;
    for candidate in balloons(page, &dark, true, options)? {
        if !regions
            .iter()
            .any(|r| r.bbox.intersection(candidate.bbox).is_some())
        {
            regions.push(candidate);
        }
    }
    if options.find_sfx {
        regions.extend(free_lettering(&light, &regions, false, options)?);
        regions.extend(free_lettering(&dark, &regions, true, options)?);
    }
    let order = order_regions(&regions, &panels, options.rtl, h)?;
    Ok(Detection {
        regions: order.into_iter().map(|i| regions[i].clone()).collect(),
        panels,
        size: [w, h],
    })
}

pub fn detect_file(path: &Path, options: &DetectionOptions) -> Result<Detection> {
    let image = image::open(path)
        .map_err(|source| VisionError::Image {
            path: path.into(),
            source,
        })?
        .into_rgb8();
    detect_page(&image, options)
}
