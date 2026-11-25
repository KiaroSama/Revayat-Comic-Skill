use crate::{Rect, Result, VisionError, gray, mask_bounds, same_geometry};
use image::{GrayImage, Luma, RgbImage, imageops};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

pub const OUTLINE_INSET: f32 = 0.035;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Balloon {
    pub bounds: Rect,
    pub text_bounds: Rect,
    #[serde(default)]
    pub dark: bool,
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

/// The enclosed paper, including ink holes, with a wall clearance in page pixels.
pub fn balloon_interior(page: &RgbImage, balloon: Balloon, inset: u32) -> Result<RegionMask> {
    seeded_interior(page, balloon, inset, None)
}

fn seeded_interior(
    page: &RgbImage,
    balloon: Balloon,
    inset: u32,
    clip: Option<Rect>,
) -> Result<RegionMask> {
    let b = balloon.bounds.checked(page.dimensions())?;
    let text = balloon.text_bounds.checked(page.dimensions())?;
    let window = imageops::crop_imm(page, b.x(), b.y(), b.width(), b.height()).to_image();
    let oriented = gray(&window, balloon.dark);
    let mut empty = GrayImage::new(b.width(), b.height());
    if b.width().min(b.height()) < 6 {
        return Ok(RegionMask {
            bounds: b,
            pixels: empty,
        });
    }
    let Some(seed) = text.intersection(b) else {
        return Ok(RegionMask {
            bounds: b,
            pixels: empty,
        });
    };
    let paper = |threshold| {
        GrayImage::from_fn(b.width(), b.height(), |x, y| {
            Luma([if oriented.get_pixel(x, y)[0] >= threshold {
                255
            } else {
                0
            }])
        })
    };
    let empty_mask = || GrayImage::new(b.width(), b.height());
    let mut recovered = None;
    for threshold in [220, 185] {
        let bright = paper(threshold);
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
        let mut candidate = empty_mask();
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
        if edges.iter().filter(|&&edge| edge).count() > 2
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
        fill_enclosed(&mut candidate);
        let area_factor = if count * 20 >= tight.area() * 13 {
            48
        } else {
            6
        };
        if clip.is_some()
            && (count * 2 < tight.area() || count > text.area().saturating_mul(area_factor))
        {
            continue;
        }
        recovered = Some(candidate);
        break;
    }
    let Some(mut paper) = recovered else {
        return Ok(RegionMask {
            bounds: b,
            pixels: empty,
        });
    };
    // A crop-edge pixel has no proven clearance from the contour.
    for (x, y, p) in paper.enumerate_pixels_mut() {
        if x < inset
            || y < inset
            || x >= b.width().saturating_sub(inset)
            || y >= b.height().saturating_sub(inset)
        {
            p[0] = 0;
        }
    }
    let paper = if inset > 0 {
        morphology(&paper, inset, true)?
    } else {
        paper
    };
    for (out, p) in empty.pixels_mut().zip(paper.pixels()) {
        *out = *p;
    }
    Ok(RegionMask {
        bounds: b,
        pixels: empty,
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
    text.checked(page.dimensions())?;
    let clip = panel.unwrap_or(Rect([0, 0, page.width(), page.height()]));
    clip.checked(page.dimensions())?;
    let Some(seed) = clip.intersection(text) else {
        return Ok(None);
    };
    if let Some(saved) = saved
        && let Some(bounds) = saved.bounds.checked(page.dimensions())?.intersection(clip)
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
        if mask_bounds(&seeded_interior(page, candidate, 1, Some(clip))?.pixels).is_some() {
            return Ok(Some(candidate));
        }
    }
    let pad = seed.width().max(seed.height()).max(32);
    for pad in [pad, pad * 2] {
        let bounds = seed
            .expand(pad, page.width(), page.height())
            .intersection(clip)
            .unwrap_or(clip);
        let probe = Balloon {
            bounds,
            text_bounds: seed,
            dark,
        };
        let inside = seeded_interior(page, probe, 0, Some(clip))?;
        let Some(tight) = mask_bounds(&inside.pixels) else {
            continue;
        };
        let tight = Rect([
            tight.x() + bounds.x(),
            tight.y() + bounds.y(),
            tight.width(),
            tight.height(),
        ]);
        let area = inside.pixels.pixels().filter(|p| p[0] != 0).count() as u64;
        if tight.width().min(tight.height()) < 8
            || area * 10 > clip.area() * 8
            || !tight
                .intersection(seed)
                .is_some_and(|intersection| intersection.area() * 3 >= seed.area())
        {
            continue;
        }
        let bounds = tight
            .expand(2, page.width(), page.height())
            .intersection(clip)
            .unwrap_or(tight);
        return Ok(Some(Balloon { bounds, ..probe }));
    }
    Ok(None)
}

pub fn balloon_geometry(page: &RgbImage, balloon: Balloon) -> Result<serde_json::Value> {
    use imageproc::contours::{BorderType, find_contours};

    let margin = text_inset(balloon.bounds);
    let outline = balloon_interior(page, balloon, 1)?;
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
    if ![options.grow, options.pad]
        .into_iter()
        .all(|x| (0.0..=1.0).contains(&x))
    {
        return Err(VisionError::invalid(
            "mask grow and padding must be in 0..=1",
        ));
    }
    let side = bounds.width().min(bounds.height());
    let window = bounds.expand(
        (options.pad * side as f32).round() as u32,
        page.width(),
        page.height(),
    );
    let allowed = balloon
        .map(|b| {
            balloon_interior(
                page,
                b,
                (OUTLINE_INSET * b.bounds.width().min(b.bounds.height()) as f32)
                    .round()
                    .max(1.0) as u32,
            )
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
    let crop = imageops::crop_imm(page, b.x(), b.y(), b.width(), b.height()).to_image();
    let oriented = gray(&crop, balloon.map_or(dark, |b| b.dark));
    let permitted = |x: u32, y: u32| {
        allowed.as_ref().is_none_or(|m| {
            let (x, y) = (x + b.x(), y + b.y());
            m.bounds.contains(x, y)
                && m.pixels.get_pixel(x - m.bounds.x(), y - m.bounds.y())[0] != 0
        })
    };
    let threshold = if allowed.is_some() {
        175
    } else {
        imageproc::contrast::otsu_level(&oriented).min(210)
    };
    let raw = GrayImage::from_fn(b.width(), b.height(), |x, y| {
        Luma([
            if permitted(x, y) && oriented.get_pixel(x, y)[0] <= threshold {
                255
            } else {
                0
            },
        ])
    });
    let (raw, guard) = if allowed.is_some() {
        (raw, None)
    } else {
        let (ink, edges) = maskcore_rs::port::strip_perimeter_contours(
            Some(raw.as_raw()),
            i128::from(b.width()),
            i128::from(b.height()),
            0.18,
            0.70,
        )
        .map_err(VisionError::kernel)?;
        (
            from_raw(raw.dimensions(), ink)?,
            Some(morphology(&from_raw(raw.dimensions(), edges)?, 1, false)?),
        )
    };
    let radius = (options.grow * side as f32).round().max(1.0) as u32;
    let expanded = morphology(&raw, radius, false)?;
    let closed = morphology(&morphology(&expanded, radius, false)?, radius, true)?;
    let pixels = GrayImage::from_fn(b.width(), b.height(), |x, y| {
        Luma([
            if permitted(x, y) && guard.as_ref().is_none_or(|m| m.get_pixel(x, y)[0] == 0) {
                closed.get_pixel(x, y)[0].max(raw.get_pixel(x, y)[0])
            } else {
                0
            },
        ])
    });
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
