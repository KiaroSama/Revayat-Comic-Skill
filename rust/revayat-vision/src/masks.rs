use crate::{Rect, Result, VisionError, luminance, mask_bounds, same_geometry};
use image::{GrayImage, Luma, RgbImage, imageops};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

pub const OUTLINE_INSET: f32 = 0.035;
pub(crate) const OPEN_BALLOON_PAD: f32 = 0.3;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Balloon {
    pub bounds: Rect,
    pub text_bounds: Rect,
    #[serde(default)]
    pub dark: bool,
}

pub(crate) fn open_balloon_cleanup_window(balloon: Balloon, size: (u32, u32)) -> Rect {
    let text = balloon.text_bounds;
    let pad = (OPEN_BALLOON_PAD * text.width().min(text.height()) as f32).round() as u32;
    text.expand(pad, size.0, size.1)
}

#[derive(Debug, Clone)]
pub struct RegionMask {
    pub bounds: Rect,
    pub pixels: GrayImage,
}

impl RegionMask {
    pub fn apply_to(&self, page_mask: &mut GrayImage) -> Result<()> {
        self.bounds.checked(page_mask.dimensions())?;
        same_geometry(
            (self.bounds.width(), self.bounds.height()),
            self.pixels.dimensions(),
        )?;
        for (x, y, _) in self.pixels.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
            page_mask.put_pixel(self.bounds.x() + x, self.bounds.y() + y, Luma([255]));
        }
        Ok(())
    }

    pub fn exclude(&mut self, regions: &[Rect]) {
        for area in regions.iter().filter_map(|r| self.bounds.intersection(*r)) {
            for y in area.y()..area.bottom() {
                for x in area.x()..area.right() {
                    self.pixels
                        .put_pixel(x - self.bounds.x(), y - self.bounds.y(), Luma([0]));
                }
            }
        }
    }
}

pub(crate) fn from_raw(size: (u32, u32), bytes: Vec<u8>) -> Result<GrayImage> {
    GrayImage::from_raw(size.0, size.1, bytes)
        .ok_or_else(|| VisionError::invalid("invalid grayscale buffer size"))
}

pub(crate) fn morphology(mask: &GrayImage, radius: u32, erode: bool) -> Result<GrayImage> {
    let w = i128::from(mask.width());
    let h = i128::from(mask.height());
    let f = if erode {
        maskcore_rs::port::erode_linf
    } else {
        maskcore_rs::port::dilate_linf
    };
    from_raw(
        mask.dimensions(),
        f(Some(mask.as_raw()), w, h, i128::from(radius)).map_err(VisionError::kernel)?,
    )
}

fn neighbors(x: u32, y: u32, w: u32, h: u32) -> impl Iterator<Item = (u32, u32)> {
    [
        x.checked_sub(1).map(|x| (x, y)),
        (x + 1 < w).then_some((x + 1, y)),
        y.checked_sub(1).map(|y| (x, y)),
        (y + 1 < h).then_some((x, y + 1)),
    ]
    .into_iter()
    .flatten()
}

fn fill_enclosed(paper: &mut GrayImage) {
    let (w, h) = paper.dimensions();
    let mut outside = GrayImage::new(w, h);
    let border = (0..w)
        .flat_map(|x| [(x, 0), (x, h - 1)])
        .chain((0..h).flat_map(|y| [(0, y), (w - 1, y)]));
    let mut queue = VecDeque::new();
    for (x, y) in border {
        if paper.get_pixel(x, y)[0] == 0 && outside.get_pixel(x, y)[0] == 0 {
            outside.put_pixel(x, y, Luma([255]));
            queue.push_back((x, y));
        }
    }
    while let Some((x, y)) = queue.pop_front() {
        for (xx, yy) in neighbors(x, y, w, h) {
            if paper.get_pixel(xx, yy)[0] == 0 && outside.get_pixel(xx, yy)[0] == 0 {
                outside.put_pixel(xx, yy, Luma([255]));
                queue.push_back((xx, yy));
            }
        }
    }
    for (p, o) in paper.pixels_mut().zip(outside.pixels()) {
        p[0] = 255 - o[0];
    }
}

pub fn page_luminance(page: &RgbImage) -> GrayImage {
    crate::gray(page, false)
}

fn oriented_window(b: Rect, dark: bool, luma: impl Fn(u32, u32) -> u8) -> GrayImage {
    GrayImage::from_fn(b.width(), b.height(), |x, y| {
        let l = luma(b.x() + x, b.y() + y);
        Luma([if dark { 255 - l } else { l }])
    })
}

/// The enclosed paper, including ink holes, with a wall clearance in page pixels.
pub fn balloon_interior(page: &RgbImage, balloon: Balloon, inset: u32) -> Result<RegionMask> {
    let (paper, _) = balloon_paper(page, balloon)?;
    inset_balloon(&paper, inset)
}

pub(crate) fn balloon_paper(page: &RgbImage, balloon: Balloon) -> Result<(RegionMask, bool)> {
    balloon.bounds.checked(page.dimensions())?;
    balloon.text_bounds.checked(page.dimensions())?;
    seeded_interior(balloon, None, |x, y| luminance(page.get_pixel(x, y)))
}

fn seeded_interior(
    balloon: Balloon,
    clip: Option<Rect>,
    luma: impl Fn(u32, u32) -> u8,
) -> Result<(RegionMask, bool)> {
    let b = balloon.bounds;
    let empty = || RegionMask {
        bounds: b,
        pixels: GrayImage::new(b.width(), b.height()),
    };
    let Some(seed) = balloon
        .text_bounds
        .intersection(b)
        .filter(|_| b.width().min(b.height()) >= 6)
    else {
        return Ok((empty(), false));
    };
    let oriented = oriented_window(b, balloon.dark, luma);
    let paper = |threshold| {
        GrayImage::from_fn(b.width(), b.height(), |x, y| {
            Luma([if oriented.get_pixel(x, y)[0] >= threshold {
                255
            } else {
                0
            }])
        })
    };
    for (threshold, narrow_tail) in [(220, false), (185, false), (220, true), (185, true)] {
        let bright = paper(threshold);
        // A one-pixel tail opening must not join an otherwise enclosed balloon to the panel.
        let bright = if narrow_tail {
            morphology(&bright, 1, true)?
        } else {
            bright
        };
        let labels = imageproc::region_labelling::connected_components(
            &bright,
            imageproc::region_labelling::Connectivity::Four,
            Luma([0]),
        );
        let mut overlap = std::collections::BTreeMap::<u32, u64>::new();
        for y in seed.y()..seed.bottom() {
            for x in seed.x()..seed.right() {
                let label = labels.get_pixel(x - b.x(), y - b.y())[0];
                if label != 0 {
                    *overlap.entry(label).or_default() += 1;
                }
            }
        }
        let Some((label, coverage)) = overlap.into_iter().max_by_key(|&(_, n)| n) else {
            continue;
        };
        if coverage * 8 < seed.area() {
            continue;
        }
        let mut candidate = empty().pixels;
        let mut count = 0u64;
        for (out, p) in candidate.pixels_mut().zip(labels.pixels()) {
            if p[0] == label {
                out[0] = 255;
                count += 1;
            }
        }
        let Some(tight) = mask_bounds(&candidate) else {
            continue;
        };
        let edges = [
            tight.y() == 0,
            tight.bottom() == b.height(),
            tight.x() == 0,
            tight.right() == b.width(),
        ];
        let edge_count = edges.into_iter().filter(|&edge| edge).count();
        if edge_count == 4
            || (narrow_tail && edge_count != 0)
            || clip.is_some_and(|clip| {
                edges
                    .into_iter()
                    .zip([
                        b.y() == clip.y(),
                        b.bottom() == clip.bottom(),
                        b.x() == clip.x(),
                        b.right() == clip.right(),
                    ])
                    .any(|(hit, boundary)| hit && !boundary)
            })
        {
            continue;
        }
        let area_factor = if count * 20 >= tight.area() * 13 {
            48
        } else {
            6
        };
        if (clip.is_some() || narrow_tail)
            && (count * 2 < tight.area()
                || (edge_count == 0
                    && count > balloon.text_bounds.area().saturating_mul(area_factor)))
        {
            continue;
        }
        if tight.x() > 0
            && tight.y() > 0
            && tight.right() < b.width()
            && tight.bottom() < b.height()
        {
            let mut tight_paper = imageops::crop_imm(
                &candidate,
                tight.x(),
                tight.y(),
                tight.width(),
                tight.height(),
            )
            .to_image();
            fill_enclosed(&mut tight_paper);
            imageops::replace(
                &mut candidate,
                &tight_paper,
                i64::from(tight.x()),
                i64::from(tight.y()),
            );
        } else {
            fill_enclosed(&mut candidate);
        }
        return Ok((
            RegionMask {
                bounds: b,
                pixels: candidate,
            },
            edge_count != 0,
        ));
    }
    Ok((empty(), false))
}

pub(crate) fn inset_balloon(interior: &RegionMask, inset: u32) -> Result<RegionMask> {
    let b = interior.bounds;
    let mut paper = interior.pixels.clone();
    if inset == 0 {
        return Ok(RegionMask {
            bounds: b,
            pixels: paper,
        });
    }
    // Clear the 1 px crop rim so erosion of radius `inset` leaves `inset` px from every edge.
    for (x, y, p) in paper.enumerate_pixels_mut() {
        if x == 0 || y == 0 || x + 1 == b.width() || y + 1 == b.height() {
            p[0] = 0;
        }
    }
    Ok(RegionMask {
        bounds: b,
        pixels: morphology(&paper, inset, true)?,
    })
}

/// Checked solid padded rectangle mask for external on-art compositing.
pub fn solid_region_patch(page_dims: (u32, u32), bounds: Rect, pad: u32) -> Result<RegionMask> {
    let checked = bounds.checked(page_dims)?;
    let x0 = checked.x().saturating_sub(pad);
    let y0 = checked.y().saturating_sub(pad);
    let x1 = checked.right().saturating_add(pad).min(page_dims.0);
    let y1 = checked.bottom().saturating_add(pad).min(page_dims.1);
    let padded = Rect([x0, y0, x1.saturating_sub(x0), y1.saturating_sub(y0)]).checked(page_dims)?;
    Ok(RegionMask {
        bounds: padded,
        pixels: GrayImage::from_pixel(padded.width(), padded.height(), Luma([255])),
    })
}

/// Resolve a saved contour seed or find an enclosure near the worksheet box.
pub fn resolve_balloon(
    page: &RgbImage,
    text: Rect,
    saved: Option<Balloon>,
    panel: Option<Rect>,
    dark: bool,
) -> Result<Option<Balloon>> {
    Ok(
        resolve_balloon_paper(page.dimensions(), text, saved, panel, dark, |x, y| {
            luminance(page.get_pixel(x, y))
        })?
        .map(|(balloon, _)| balloon),
    )
}

/// Resolve and retain the paper component so geometry and erase masks can reuse it.
pub fn resolve_balloon_with_interior(
    luma: &GrayImage,
    text: Rect,
    saved: Option<Balloon>,
    panel: Option<Rect>,
    dark: bool,
) -> Result<Option<(Balloon, RegionMask)>> {
    resolve_balloon_paper(luma.dimensions(), text, saved, panel, dark, |x, y| {
        luma.get_pixel(x, y)[0]
    })
}

fn resolve_balloon_paper(
    size: (u32, u32),
    text: Rect,
    saved: Option<Balloon>,
    panel: Option<Rect>,
    dark: bool,
    luma: impl Fn(u32, u32) -> u8,
) -> Result<Option<(Balloon, RegionMask)>> {
    text.checked(size)?;
    let clip = panel.unwrap_or(Rect([0, 0, size.0, size.1]));
    clip.checked(size)?;
    let Some(seed) = clip.intersection(text) else {
        return Ok(None);
    };
    let mut used = None;
    if let Some(saved) = saved
        && let Some(bounds) = saved.bounds.checked(size)?.intersection(clip)
        && bounds
            .intersection(seed)
            .is_some_and(|overlap| overlap.area() * 3 >= seed.area())
    {
        // Saved geometry is only a search window; current placement determines authorization.
        let candidate = Balloon {
            bounds,
            text_bounds: seed,
            dark,
        };
        let (paper, open) = seeded_interior(candidate, Some(clip), &luma)?;
        if (!open || panel.is_some())
            && resolved_paper_bounds(&paper, seed, clip).is_some()
            && inset_balloon(&paper, 1)?.pixels.iter().any(|&p| p != 0)
        {
            return Ok(Some((candidate, paper)));
        }
        used = Some(bounds);
    }
    let pad = seed.width().max(seed.height()).max(32);
    let window = |pad| {
        seed.expand(pad, size.0, size.1)
            .intersection(clip)
            .unwrap_or(clip)
    };
    let nearby = window(pad);
    for bounds in [nearby, window(pad.saturating_mul(2)), clip] {
        if used.replace(bounds) == Some(bounds) {
            continue;
        }
        let probe = Balloon {
            bounds,
            text_bounds: seed,
            dark,
        };
        let (inside, open) = seeded_interior(probe, Some(clip), &luma)?;
        if open && panel.is_none() {
            continue;
        }
        let Some(tight) = resolved_paper_bounds(&inside, seed, clip) else {
            continue;
        };
        let bounds = tight
            .expand(2, size.0, size.1)
            .intersection(clip)
            .unwrap_or(tight);
        let mut pixels = GrayImage::new(bounds.width(), bounds.height());
        let common = inside.bounds.intersection(bounds).unwrap_or(tight);
        let crop = imageops::crop_imm(
            &inside.pixels,
            common.x() - inside.bounds.x(),
            common.y() - inside.bounds.y(),
            common.width(),
            common.height(),
        );
        imageops::replace(
            &mut pixels,
            &*crop,
            i64::from(common.x() - bounds.x()),
            i64::from(common.y() - bounds.y()),
        );
        return Ok(Some((
            Balloon { bounds, ..probe },
            RegionMask { bounds, pixels },
        )));
    }
    Ok(None)
}

fn resolved_paper_bounds(paper: &RegionMask, seed: Rect, clip: Rect) -> Option<Rect> {
    let tight = mask_bounds(&paper.pixels)?;
    let tight = Rect([
        tight.x() + paper.bounds.x(),
        tight.y() + paper.bounds.y(),
        tight.width(),
        tight.height(),
    ]);
    let area = paper.pixels.iter().filter(|&&p| p != 0).count() as u64;
    (tight.width().min(tight.height()) >= 8
        && area * 10 <= clip.area() * 8
        && tight
            .intersection(seed)
            .is_some_and(|overlap| overlap.area() * 3 >= seed.area()))
    .then_some(tight)
}

pub fn balloon_geometry(page: &RgbImage, balloon: Balloon) -> Result<serde_json::Value> {
    let outline = balloon_interior(page, balloon, 1)?;
    geometry_for_outline(balloon, outline)
}

pub fn balloon_geometry_from_interior(
    balloon: Balloon,
    interior: &RegionMask,
) -> Result<serde_json::Value> {
    geometry_for_outline(balloon, inset_balloon(interior, 1)?)
}

fn geometry_for_outline(balloon: Balloon, outline: RegionMask) -> Result<serde_json::Value> {
    use imageproc::contours::{BorderType, find_contours};

    let margin = text_inset(balloon.bounds);
    let mut value = serde_json::to_value(balloon)?;
    let b = outline.bounds;
    if let Some(contour) = find_contours::<i32>(&outline.pixels)
        .into_iter()
        .filter(|c| c.border_type == BorderType::Outer)
        .max_by_key(|c| c.points.len())
    {
        value["contour"] = serde_json::json!(
            contour
                .points
                .into_iter()
                .map(|p| [p.x + b.x() as i32, p.y + b.y() as i32])
                .collect::<Vec<_>>()
        );
    }
    value["bbox"] = serde_json::json!(b);
    value["center"] = serde_json::json!(b.center());
    value["eroded_margin"] = serde_json::json!(margin);
    Ok(value)
}

pub(crate) fn text_inset(b: Rect) -> u32 {
    (b.width().min(b.height()) as f32 * 0.045).round().max(1.0) as u32
}

pub fn find_balloon(page: &RgbImage, text: Rect, dark: bool) -> Result<Option<Balloon>> {
    resolve_balloon(page, text, None, None, dark)
}

#[derive(Debug, Clone, Copy)]
pub struct MaskOptions {
    pub grow: f32,
    pub pad: f32,
    pub solid_free: bool,
    pub full_balloon: bool,
}
impl Default for MaskOptions {
    fn default() -> Self {
        Self {
            grow: 0.025,
            pad: 0.12,
            solid_free: false,
            full_balloon: true,
        }
    }
}

pub fn region_mask(
    page: &RgbImage,
    bounds: Rect,
    balloon: Option<Balloon>,
    dark: bool,
    options: MaskOptions,
) -> Result<RegionMask> {
    bounds.checked(page.dimensions())?;
    let paper = balloon.map(|b| balloon_interior(page, b, 0)).transpose()?;
    region_mask_from_luma(
        page.dimensions(),
        bounds,
        paper.as_ref(),
        balloon.map_or(dark, |b| b.dark),
        options,
        |x, y| luminance(page.get_pixel(x, y)),
    )
}

/// Build the erase mask without finding the balloon's paper component again.
pub fn region_mask_with_interior(
    luma: &GrayImage,
    bounds: Rect,
    interior: Option<&RegionMask>,
    dark: bool,
    options: MaskOptions,
) -> Result<RegionMask> {
    region_mask_from_luma(
        luma.dimensions(),
        bounds,
        interior,
        dark,
        options,
        |x, y| luma.get_pixel(x, y)[0],
    )
}

fn region_mask_from_luma(
    size: (u32, u32),
    bounds: Rect,
    interior: Option<&RegionMask>,
    dark: bool,
    options: MaskOptions,
    luma: impl Fn(u32, u32) -> u8,
) -> Result<RegionMask> {
    bounds.checked(size)?;
    if ![options.grow, options.pad]
        .into_iter()
        .all(|x| (0.0..=1.0).contains(&x))
    {
        return Err(VisionError::invalid(
            "mask grow and padding must be in 0..=1",
        ));
    }
    let side = bounds.width().min(bounds.height());
    let window = bounds.expand((options.pad * side as f32).round() as u32, size.0, size.1);
    let allowed = interior
        .map(|paper| {
            let b = paper.bounds.checked(size)?;
            same_geometry((b.width(), b.height()), paper.pixels.dimensions())?;
            let inset = (OUTLINE_INSET * b.width().min(b.height()) as f32)
                .round()
                .max(1.0) as u32;
            inset_balloon(paper, inset)
        })
        .transpose()?;
    let b = if options.full_balloon {
        allowed.as_ref().map_or(window, |m| m.bounds.union(window))
    } else {
        window
    };
    if options.solid_free && allowed.is_none() {
        return Ok(RegionMask {
            bounds: b,
            pixels: GrayImage::from_pixel(b.width(), b.height(), Luma([255])),
        });
    }
    let oriented = oriented_window(b, dark, luma);
    let permitted = |x: u32, y: u32| {
        allowed.as_ref().is_none_or(|m| {
            let (x, y) = (x + b.x(), y + b.y());
            m.bounds.contains(x, y)
                && m.pixels.get_pixel(x - m.bounds.x(), y - m.bounds.y())[0] != 0
        })
    };
    let threshold = masked_otsu_threshold(&oriented, permitted);
    let threshold = if allowed.is_some() {
        threshold.clamp(175, 210)
    } else {
        threshold.min(210)
    };
    let radius = (options.grow * side as f32).round().max(1.0) as u32;
    let pixels = if allowed.is_some() {
        let raw = GrayImage::from_fn(b.width(), b.height(), |x, y| {
            Luma([
                if permitted(x, y) && oriented.get_pixel(x, y)[0] <= threshold {
                    255
                } else {
                    0
                },
            ])
        });
        let expanded = morphology(&raw, radius, false)?;
        let closed = morphology(&morphology(&expanded, radius, false)?, radius, true)?;
        GrayImage::from_fn(b.width(), b.height(), |x, y| {
            Luma([if permitted(x, y) {
                closed.get_pixel(x, y)[0].max(raw.get_pixel(x, y)[0])
            } else {
                0
            }])
        })
    } else {
        let guard = free_ink_guard(&oriented, threshold);
        let ink = free_ink(&oriented, b, bounds, threshold, guard);
        let mut pixels = maskcore_rs::dilate_l2(
            Some(ink.as_raw()),
            i128::from(b.width()),
            i128::from(b.height()),
            i128::from(radius),
        )
        .map_err(VisionError::kernel)?;
        for ((p, &luma), &is_ink) in pixels.iter_mut().zip(oriented.iter()).zip(ink.iter()) {
            if luma <= guard && is_ink == 0 {
                *p = 0;
            }
        }
        from_raw(oriented.dimensions(), pixels)?
    };
    if options.full_balloon
        && let Some(local) = mask_bounds(&pixels)
    {
        let fitted = local.expand(
            ((options.pad * side as f32).round() as u32).max(2),
            b.width(),
            b.height(),
        );
        return Ok(RegionMask {
            bounds: Rect([
                b.x() + fitted.x(),
                b.y() + fitted.y(),
                fitted.width(),
                fitted.height(),
            ]),
            pixels: imageops::crop_imm(
                &pixels,
                fitted.x(),
                fitted.y(),
                fitted.width(),
                fitted.height(),
            )
            .to_image(),
        });
    }
    Ok(RegionMask { bounds: b, pixels })
}

pub(crate) use crate::otsu::masked_otsu_threshold;

/// Bright paper inside a rounded footprint, with clearance from dark art.
pub fn elliptical_lettering_area(page: &RgbImage, bounds: Rect, dark: bool) -> Result<RegionMask> {
    let b = bounds.checked(page.dimensions())?;
    let margin = (b.width().min(b.height()) / 48).clamp(1, 2);
    let [rx, ry] = [b.width(), b.height()].map(|side| (f64::from(side) / 2.0 - 0.5).max(0.5));
    let paper = oriented_window(b, dark, |x, y| luminance(page.get_pixel(x, y)));
    let paper = GrayImage::from_fn(b.width(), b.height(), |x, y| {
        let dx = (f64::from(x) + 0.5 - f64::from(b.width()) / 2.0) / rx;
        let dy = (f64::from(y) + 0.5 - f64::from(b.height()) / 2.0) / ry;
        Luma([
            if dx * dx + dy * dy <= 1.0 && paper.get_pixel(x, y)[0] >= 180 {
                255
            } else {
                0
            },
        ])
    });
    Ok(RegionMask {
        bounds: b,
        pixels: morphology(&paper, margin, true)?,
    })
}

fn free_ink_guard(oriented: &GrayImage, threshold: u8) -> u8 {
    let mut histogram = [0usize; 256];
    for &luma in oriented.iter() {
        histogram[usize::from(luma)] += 1;
    }
    let lighter = &histogram[usize::from(threshold) + 1..];
    let mut remaining = lighter.iter().sum::<usize>() / 2 + 1;
    let paper = lighter.iter().enumerate().find_map(|(offset, &count)| {
        if remaining <= count {
            Some(threshold + 1 + offset as u8)
        } else {
            remaining -= count;
            None
        }
    });
    // Keep the art guard below the current paper, but include every detected ink shade.
    threshold
        .max(179)
        .min(paper.unwrap_or(255).saturating_sub(1))
}

fn free_ink(
    oriented: &GrayImage,
    window: Rect,
    anchor: Rect,
    threshold: u8,
    guard: u8,
) -> GrayImage {
    use imageproc::region_labelling::{Connectivity, connected_components};

    let (w, h) = oriented.dimensions();
    let dark = GrayImage::from_fn(w, h, |x, y| {
        Luma([if oriented.get_pixel(x, y)[0] <= guard {
            255
        } else {
            0
        }])
    });
    let labels = connected_components(&dark, Connectivity::Eight, Luma([0]));
    let mut components =
        vec![(false, false); labels.iter().copied().max().unwrap_or(0) as usize + 1];
    for (x, y, label) in labels.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
        let (has_ink, hits_art) = &mut components[label[0] as usize];
        *has_ink |= oriented.get_pixel(x, y)[0] <= threshold;
        // A dark component crossing the source text box may be an outline or artwork.
        *hits_art |= x == 0
            || y == 0
            || x + 1 == w
            || y + 1 == h
            || !anchor.contains(window.x() + x, window.y() + y);
    }
    GrayImage::from_fn(w, h, |x, y| {
        let (has_ink, hits_art) = components[labels.get_pixel(x, y)[0] as usize];
        Luma([if has_ink && !hits_art { 255 } else { 0 }])
    })
}

#[cfg(test)]
mod recovery_tests {
    use super::*;
    use image::Rgb;

    #[test]
    fn paper_component_beats_the_white_counter_inside_a_source_glyph() -> Result<()> {
        let mut page = RgbImage::from_pixel(180, 330, Rgb([116, 155, 190]));
        for (x, y, p) in page.enumerate_pixels_mut() {
            let dx = x.abs_diff(90);
            let dy = y.abs_diff(165);
            if dy <= 136 && dx <= 63 && 2 * dx + dy < 224 {
                *p = Rgb([248; 3]);
            }
            if (71..110).contains(&x) && (144..187).contains(&y) {
                *p = if (84..97).contains(&x) && (159..172).contains(&y) {
                    Rgb([247; 3])
                } else {
                    Rgb([24; 3])
                };
            }
        }
        let text = Rect([57, 125, 66, 80]);
        let found = resolve_balloon(&page, text, None, None, false)?;
        assert!(found.is_some_and(|b| b.bounds.height() > 230), "{found:?}");
        Ok(())
    }

    #[test]
    fn accepts_real_panel_clips_and_rejects_a_window_open_to_artwork() -> Result<()> {
        let panel = Rect([30, 50, 140, 120]);
        let art = RgbImage::from_pixel(210, 200, Rgb([40; 3]));
        let mut page = art.clone();
        for y in panel.y()..panel.bottom() {
            for x in panel.x()..panel.right() {
                let dx = (f64::from(x) - 38.) / 48.;
                let dy = (f64::from(y) - 54.) / 43.;
                if dx * dx + dy * dy < 1. {
                    page.put_pixel(x, y, Rgb([244; 3]));
                }
            }
        }
        let text = Rect([40, 59, 20, 20]);
        let found = resolve_balloon(&page, text, None, Some(panel), false)?;
        assert!(found.is_some_and(|b| b.bounds.x() == panel.x() && b.bounds.y() == panel.y()));
        let white = RgbImage::from_pixel(210, 200, Rgb([244; 3]));
        assert_eq!(
            resolve_balloon(&white, text, None, Some(panel), false)?,
            None
        );
        assert_eq!(resolve_balloon(&art, text, None, Some(panel), false)?, None);
        Ok(())
    }
}
