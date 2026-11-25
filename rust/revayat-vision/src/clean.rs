use crate::{
    Result, VisionError, gray, luminance,
    masks::{Balloon, MaskOptions, RegionMask, balloon_interior, region_mask},
    same_geometry,
};
use image::{GrayImage, Luma, Rgb, RgbImage, imageops};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CleanStrategy {
    Flat,
    Inpaint,
    External,
    NoInk,
}

#[derive(Debug, Clone)]
pub struct CleanedPage {
    pub image: RgbImage,
    /// Exact authorization, including the dot sweep, in full-page coordinates.
    pub mask: GrayImage,
    pub strategies: Vec<CleanStrategy>,
}

pub fn choose_strategy(
    crop: &RgbImage,
    mask: &GrayImage,
    allowed: Option<&GrayImage>,
) -> Result<Option<Rgb<u8>>> {
    same_geometry(crop.dimensions(), mask.dimensions())?;
    if let Some(m) = allowed {
        same_geometry(m.dimensions(), mask.dimensions())?;
    }
    let mut count = 0.0;
    let mut sum = [0.0; 3];
    let mut squares = [0.0; 3];
    for (x, y, p) in crop.enumerate_pixels() {
        if mask.get_pixel(x, y)[0] != 0 || allowed.is_some_and(|m| m.get_pixel(x, y)[0] == 0) {
            continue;
        }
        count += 1.0;
        for (i, v) in p.0.into_iter().map(f64::from).enumerate() {
            sum[i] += v;
            squares[i] += v * v;
        }
    }
    if count < 24.0 {
        return Ok(None);
    }
    let mean = sum.map(|x| x / count);
    if (0..3).any(|i| squares[i] / count - mean[i] * mean[i] > 9.0_f64.powi(2)) {
        return Ok(None);
    }
    Ok(Some(Rgb(mean.map(|x| x.round() as u8))))
}

/// Composites an external or locally inpainted result strictly within its authorization.
pub fn composite_external(
    original: &RgbImage,
    edited: &RgbImage,
    mask: &GrayImage,
    feather: u32,
) -> Result<RgbImage> {
    same_geometry(original.dimensions(), edited.dimensions())?;
    same_geometry(original.dimensions(), mask.dimensions())?;
    let (w, h) = (i128::from(original.width()), i128::from(original.height()));
    let alpha = if feather == 0 {
        mask.as_raw()
            .iter()
            .map(|&v| if v != 0 { 255 } else { 0 })
            .collect()
    } else {
        cleancore_rs::port::compute_feather_alpha(Some(mask.as_raw()), w, h, i128::from(feather))
            .map_err(VisionError::kernel)?
    };
    let painted = cleancore_rs::port::composite_masked_rgb(
        Some(original.as_raw()),
        Some(edited.as_raw()),
        Some(&alpha),
        w,
        h,
    )
    .map_err(VisionError::kernel)?;
    RgbImage::from_raw(original.width(), original.height(), painted)
        .ok_or_else(|| VisionError::invalid("invalid RGB composite buffer"))
}

/// Exclude unremoved glyphs, artwork, and colored wall pixels from lettering.
pub fn clear_lettering_area(
    page: &RgbImage,
    mut interior: RegionMask,
    dark: bool,
) -> Result<RegionMask> {
    let b = interior.bounds.checked(page.dimensions())?;
    same_geometry((b.width(), b.height()), interior.pixels.dimensions())?;
    for (x, y, p) in interior.pixels.enumerate_pixels_mut() {
        let light = luminance(page.get_pixel(b.x() + x, b.y() + y));
        if (if dark { 255 - light } else { light }) < 180 {
            p[0] = 0;
        }
    }
    Ok(interior)
}

/// Keep compact badge lettering on a locally uniform backing without touching its border.
pub fn compact_lettering_area(page: &RgbImage, b: crate::Rect) -> Result<RegionMask> {
    let b = b.checked(page.dimensions())?;
    let [cx, cy] = b.center();
    let mut channels = [[0u8; 9]; 3];
    for (i, (dx, dy)) in (-1..=1)
        .flat_map(|dy| (-1..=1).map(move |dx| (dx, dy)))
        .enumerate()
    {
        let p = page.get_pixel(
            cx.saturating_add_signed(dx).min(b.right() - 1),
            cy.saturating_add_signed(dy).min(b.bottom() - 1),
        );
        for (c, v) in channels.iter_mut().zip(p.0) {
            c[i] = v;
        }
    }
    let backing = channels.map(|mut c| {
        c.sort_unstable();
        c[4]
    });
    let paper = GrayImage::from_fn(b.width(), b.height(), |x, y| {
        Luma([
            if page
                .get_pixel(b.x() + x, b.y() + y)
                .0
                .iter()
                .zip(backing)
                .all(|(a, b)| a.abs_diff(b) <= 14)
            {
                255
            } else {
                0
            },
        ])
    });
    let labels = imageproc::region_labelling::connected_components(
        &paper,
        imageproc::region_labelling::Connectivity::Four,
        Luma([0]),
    );
    let label = labels.get_pixel(cx - b.x(), cy - b.y())[0];
    let pixels = GrayImage::from_fn(b.width(), b.height(), |x, y| {
        Luma([if label != 0 && labels.get_pixel(x, y)[0] == label {
            255
        } else {
            0
        }])
    });
    let pixels = crate::masks::morphology(&pixels, (b.width().min(b.height()) / 24).max(1), true)?;
    Ok(RegionMask { bounds: b, pixels })
}

pub fn clean_region(
    page: &RgbImage,
    mask: &RegionMask,
    allowed: Option<&GrayImage>,
    external: Option<&RgbImage>,
) -> Result<(RgbImage, CleanStrategy)> {
    let b = mask.bounds.checked(page.dimensions())?;
    same_geometry((b.width(), b.height()), mask.pixels.dimensions())?;
    if let Some(e) = external {
        same_geometry(page.dimensions(), e.dimensions())?;
    }
    if !mask.pixels.pixels().any(|p| p[0] != 0) {
        return Ok((page.clone(), CleanStrategy::NoInk));
    }
    if external.is_none() && mask.pixels.pixels().all(|p| p[0] != 0) {
        return Err(VisionError::invalid(
            "a solid erase mask needs an approved external repair",
        ));
    }
    let crop = imageops::crop_imm(page, b.x(), b.y(), b.width(), b.height()).to_image();
    let (paint, strategy) = if let Some(external) = external {
        let value = imageops::crop_imm(external, b.x(), b.y(), b.width(), b.height()).to_image();
        (
            composite_external(&crop, &value, &mask.pixels, 2)?,
            CleanStrategy::External,
        )
    } else if let Some(color) = choose_strategy(&crop, &mask.pixels, allowed)? {
        (
            RgbImage::from_fn(b.width(), b.height(), |x, y| {
                if mask.pixels.get_pixel(x, y)[0] == 0 {
                    *crop.get_pixel(x, y)
                } else {
                    color
                }
            }),
            CleanStrategy::Flat,
        )
    } else {
        let pixels = cleancore_rs::port::diffuse_inpaint_rgb(
            Some(crop.as_raw()),
            Some(mask.pixels.as_raw()),
            i128::from(b.width()),
            i128::from(b.height()),
            32,
        )
        .map_err(VisionError::kernel)?;
        let image = RgbImage::from_raw(b.width(), b.height(), pixels)
            .ok_or_else(|| VisionError::invalid("invalid inpaint buffer"))?;
        (
            composite_external(&crop, &image, &mask.pixels, 1)?,
            CleanStrategy::Inpaint,
        )
    };
    let mut output = page.clone();
    imageops::replace(&mut output, &paint, i64::from(b.x()), i64::from(b.y()));
    Ok((output, strategy))
}

fn sweep_speckles(
    original: &RgbImage,
    output: &mut RgbImage,
    authorized: &mut GrayImage,
    interior: &RegionMask,
    dark: bool,
) -> Result<()> {
    let b = interior.bounds;
    let crop = imageops::crop_imm(output, b.x(), b.y(), b.width(), b.height()).to_image();
    let oriented = gray(&crop, dark);
    let light = oriented
        .pixels()
        .zip(interior.pixels.pixels())
        .filter_map(|(p, m)| (m[0] != 0 && p[0] > 185).then_some(p[0]))
        .collect::<Vec<_>>();
    if light.len() < 24 {
        return Ok(());
    }
    let background = light.iter().map(|&v| u64::from(v)).sum::<u64>() / light.len() as u64;
    let residual = GrayImage::from_fn(b.width(), b.height(), |x, y| {
        Luma([
            if interior.pixels.get_pixel(x, y)[0] != 0
                && u64::from(oriented.get_pixel(x, y)[0]) + 38 < background
            {
                255
            } else {
                0
            },
        ])
    });
    let max = (f64::from(b.width().min(b.height())) * 0.12)
        .ceil()
        .max(3.0) as u32;
    let mut seen = GrayImage::new(b.width(), b.height());
    for (x, y, _) in residual.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
        if seen.get_pixel(x, y)[0] != 0 {
            continue;
        }
        let mut component = vec![(x, y)];
        seen.put_pixel(x, y, Luma([255]));
        let mut clear = true;
        let mut index = 0;
        while let Some(&(xx, yy)) = component.get(index) {
            index += 1;
            for v in yy.saturating_sub(1)..=yy.saturating_add(1).min(b.height() - 1) {
                for u in xx.saturating_sub(1)..=xx.saturating_add(1).min(b.width() - 1) {
                    if interior.pixels.get_pixel(u, v)[0] == 0 {
                        clear = false;
                    }
                    if residual.get_pixel(u, v)[0] != 0 && seen.get_pixel(u, v)[0] == 0 {
                        seen.put_pixel(u, v, Luma([255]));
                        component.push((u, v));
                    }
                }
            }
        }
        if !clear || component.len() > u64::from(max).pow(2) as usize {
            continue;
        }
        let mut sum = [0u32; 3];
        let mut n = 0u32;
        for &(xx, yy) in &component {
            for v in yy.saturating_sub(2)..=yy.saturating_add(2).min(b.height() - 1) {
                for u in xx.saturating_sub(2)..=xx.saturating_add(2).min(b.width() - 1) {
                    if interior.pixels.get_pixel(u, v)[0] != 0 && residual.get_pixel(u, v)[0] == 0 {
                        let p = output.get_pixel(u + b.x(), v + b.y());
                        let value = luminance(p);
                        if (if dark { 255 - value } else { value }) > 185 {
                            n += 1;
                            for (s, p) in sum.iter_mut().zip(p.0) {
                                *s += u32::from(p);
                            }
                        }
                    }
                }
            }
        }
        if n == 0 {
            continue;
        }
        let paint = Rgb(sum.map(|s| ((s + n / 2) / n) as u8));
        for (x, y) in component {
            let (x, y) = (x + b.x(), y + b.y());
            if original.get_pixel(x, y) != &paint {
                authorized.put_pixel(x, y, Luma([255]));
            }
            output.put_pixel(x, y, paint);
        }
    }
    Ok(())
}

/// Erase source glyphs and isolated punctuation from the enclosed balloon interiors.
pub fn clean_page_bubbles(original: &RgbImage, balloons: &[Balloon]) -> Result<CleanedPage> {
    same_geometry(original.dimensions(), original.dimensions())?;
    let mut image = original.clone();
    let mut mask = GrayImage::new(original.width(), original.height());
    let mut strategies = Vec::new();
    for &balloon in balloons {
        let interior = balloon_interior(original, balloon, 2)?;
        if !interior.pixels.pixels().any(|p| p[0] != 0) {
            return Err(VisionError::invalid(format!(
                "balloon {:?} has no safe interior",
                balloon.bounds.0
            )));
        }
        let local = region_mask(
            original,
            balloon.text_bounds,
            Some(balloon),
            balloon.dark,
            MaskOptions::default(),
        )?;
        let allowed = GrayImage::from_fn(local.bounds.width(), local.bounds.height(), |x, y| {
            let (x, y) = (x + local.bounds.x(), y + local.bounds.y());
            if interior.bounds.contains(x, y) {
                *interior
                    .pixels
                    .get_pixel(x - interior.bounds.x(), y - interior.bounds.y())
            } else {
                Luma([0])
            }
        });
        let mut local = local;
        for (p, a) in local.pixels.pixels_mut().zip(allowed.pixels()) {
            if a[0] == 0 {
                *p = Luma([0]);
            }
        }
        let (next, strategy) = clean_region(&image, &local, Some(&allowed), None)?;
        image = next;
        strategies.push(strategy);
        local.apply_to(&mut mask)?;
        sweep_speckles(original, &mut image, &mut mask, &interior, balloon.dark)?;
    }
    Ok(CleanedPage {
        image,
        mask,
        strategies,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Rect;

    #[test]
    fn a_solid_mask_does_not_turn_textured_artwork_white() {
        let original = RgbImage::from_fn(36, 40, |x, y| Rgb([(x * 3 + y * 5) as u8, 22, 43]));
        let mask = RegionMask {
            bounds: Rect([8, 9, 18, 20]),
            pixels: GrayImage::from_pixel(18, 20, Luma([255])),
        };
        assert!(matches!(
            clean_region(&original, &mask, None, None),
            Err(VisionError::Invalid(_))
        ));
    }
}
