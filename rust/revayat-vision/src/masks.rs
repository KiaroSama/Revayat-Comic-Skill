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
    let center = text.center();
    let wall = 125;
    let seed_area = text
        .expand(
            text.width().max(text.height()) / 2 + 3,
            page.width(),
            page.height(),
        )
        .intersection(b)
        .unwrap_or(b);
    let best = oriented
        .enumerate_pixels()
        .filter(|(x, y, p)| p[0] >= 185 && seed_area.contains(x + b.x(), y + b.y()))
        .min_by_key(|(x, y, p)| {
            (
                u64::from((x + b.x()).abs_diff(center[0]))
                    .pow(2)
                    .saturating_add(u64::from((y + b.y()).abs_diff(center[1])).pow(2)),
                255 - p[0],
            )
        });
    let Some((sx, sy, _)) = best else {
        return Ok(RegionMask {
            bounds: b,
            pixels: empty,
        });
    };
    let mut paper = from_raw(
        oriented.dimensions(),
        maskcore_rs::port::flood_balloon_interior(
            Some(oriented.as_raw()),
            i128::from(b.width()),
            i128::from(b.height()),
            i128::from(sx),
            i128::from(sy),
            wall,
            70,
            0,
        )
        .map_err(VisionError::kernel)?,
    )?;
    let hits = (0..b.width()).any(|x| paper.get_pixel(x, 0)[0] != 0) as u8
        + (0..b.width()).any(|x| paper.get_pixel(x, b.height() - 1)[0] != 0) as u8
        + (0..b.height()).any(|y| paper.get_pixel(0, y)[0] != 0) as u8
        + (0..b.height()).any(|y| paper.get_pixel(b.width() - 1, y)[0] != 0) as u8;
    if hits > 2 {
        return Ok(RegionMask {
            bounds: b,
            pixels: empty,
        });
    }
    fill_enclosed(&mut paper);
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

pub fn find_balloon(page: &RgbImage, text: Rect, dark: bool) -> Result<Option<Balloon>> {
    text.checked(page.dimensions())?;
    let page_gray = gray(page, dark);
    let candidates = detectcore_rs::port::detect_speech_balloons(
        Some(page_gray.as_raw()),
        i64::from(page.width()),
        i64::from(page.height()),
        185,
        24,
        0.35,
        0.40,
    )
    .map_err(VisionError::kernel)?;
    let center = text.center();
    let mut candidates = candidates
        .into_iter()
        .filter_map(|[x, y, w, h, _]| {
            let b = Rect([x as u32, y as u32, w as u32, h as u32]).expand(
                2,
                page.width(),
                page.height(),
            );
            b.contains(center[0], center[1]).then_some(b)
        })
        .collect::<Vec<_>>();
    candidates.sort_unstable_by_key(|b| b.area());
    for bounds in candidates {
        let b = Balloon {
            bounds,
            text_bounds: text,
            dark,
        };
        let mask = balloon_interior(page, b, 1)?;
        let covered = mask
            .pixels
            .enumerate_pixels()
            .filter(|(x, y, p)| p[0] != 0 && text.contains(x + bounds.x(), y + bounds.y()))
            .count();
        if covered as f64 >= 0.35 * text.area() as f64 {
            return Ok(Some(b));
        }
    }
    Ok(None)
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
