use crate::{
    Rect, Result, VisionError, luminance,
    masks::RegionMask,
    typefit::{
        Alignment, Fit, FitOptions, MIN_LINE_HEIGHT, PlacedLine, fit_region,
        partition_shared_interiors,
    },
    typefont::Shaper,
    typestyle::{self, TextStyle},
};
use image::{GrayImage, Luma, RgbImage};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Debug, Clone)]
pub struct TextRegion {
    pub id: String,
    pub bounds: Rect,
    pub text: String,
    pub interior: Option<RegionMask>,
    pub min_size: u32,
    pub max_size: u32,
    pub line_spacing: f32,
    pub compact: bool,
    pub is_balloon: bool,
    pub align: Alignment,
    pub style: TextStyle,
    pub rtl_target: bool,
}

impl TextRegion {
    pub fn new(id: impl Into<String>, bounds: Rect, text: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            bounds,
            text: text.into(),
            interior: None,
            min_size: 8,
            max_size: 72,
            line_spacing: MIN_LINE_HEIGHT,
            compact: false,
            is_balloon: false,
            align: Alignment::Center,
            style: TextStyle::default(),
            rtl_target: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TypesetRegion {
    pub id: String,
    pub logical_text: String,
    pub font_size: f32,
    pub line_height: f32,
    pub ink_box: Rect,
    pub lines: Vec<PlacedLine>,
    #[serde(default, skip_serializing_if = "is_zero_f32")]
    pub angle_deg: f32,
    #[serde(default, skip_serializing_if = "is_zero_u32")]
    pub outline_px: u32,
}

#[allow(clippy::trivially_copy_pass_by_ref)]
fn is_zero_f32(value: &f32) -> bool {
    *value == 0.0
}

#[allow(clippy::trivially_copy_pass_by_ref)]
fn is_zero_u32(value: &u32) -> bool {
    *value == 0
}

#[derive(Debug, Clone)]
pub struct TypesetPage {
    pub image: RgbImage,
    pub regions: Vec<TypesetRegion>,
    pub mask: GrayImage,
}

fn color(page: &RgbImage, bounds: Rect) -> [u8; 3] {
    let mut sum = 0u64;
    let mut count = 0u64;
    for y in (bounds.y()..bounds.bottom()).step_by(4) {
        for x in (bounds.x()..bounds.right()).step_by(4) {
            sum += u64::from(luminance(page.get_pixel(x, y)));
            count += 1;
        }
    }
    if sum < 125 * count { [255; 3] } else { [0; 3] }
}

fn render(
    page: &mut RgbImage,
    mask: &mut GrayImage,
    fit: Fit,
    style: &TextStyle,
    fill: [u8; 3],
) -> Vec<PlacedLine> {
    let border = typestyle::effective_outline_radius(style, fit.size);
    let shadow = style
        .shadow
        .then(|| typestyle::shadow_offset(typestyle::effective_angle_deg(style)));
    let mut paint = |b: Rect, ink: &GrayImage| {
        let brush = (border > 0).then(|| typestyle::stroke(ink, border));
        let brush = brush.as_ref().unwrap_or(ink);
        let (x, y) = (b.x() - border, b.y() - border);
        let shadow =
            shadow.map(|[dx, dy]| ((i64::from(x) + dx) as u32, (i64::from(y) + dy) as u32));
        if let Some((sx, sy)) = shadow {
            typestyle::paint(page, brush, sx, sy, [0; 3], 72);
        }
        if border > 0 {
            let outline = if u32::from(fill[0]) + u32::from(fill[1]) + u32::from(fill[2]) > 384 {
                [0; 3]
            } else {
                [255; 3]
            };
            typestyle::paint(
                page,
                brush,
                x,
                y,
                outline,
                style.outline_alpha.unwrap_or(255),
            );
        }
        typestyle::paint(page, ink, b.x(), b.y(), fill, 255);
        for (i, j, _) in brush.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
            mask.put_pixel(x + i, y + j, Luma([255]));
            if let Some((sx, sy)) = shadow {
                mask.put_pixel(sx + i, sy + j, Luma([255]));
            }
        }
    };
    if let Some((bbox, ink)) = &fit.rotated {
        paint(*bbox, ink);
    } else {
        for (line, ink) in &fit.lines {
            paint(line.bbox, ink);
        }
    }
    fit.lines.into_iter().map(|(line, _)| line).collect()
}

/// Returns a page only after every region fits.
pub fn typeset_page(page: &RgbImage, regions: &[TextRegion]) -> Result<TypesetPage> {
    typeset_page_with_occupied(page, regions, None)
}

/// Returns a page only after every region fits, avoiding externally occupied pixels.
pub fn typeset_page_with_occupied(
    page: &RgbImage,
    regions: &[TextRegion],
    occupied_external: Option<&GrayImage>,
) -> Result<TypesetPage> {
    crate::same_geometry(page.dimensions(), page.dimensions())?;
    if let Some(ext) = occupied_external {
        crate::same_geometry(page.dimensions(), ext.dimensions())?;
    }
    let mut shaper = Shaper::new()?;
    let mut ids = BTreeSet::new();
    let mut mask = GrayImage::new(page.width(), page.height());
    let mut occupied = occupied_external
        .cloned()
        .unwrap_or_else(|| GrayImage::new(page.width(), page.height()));
    let mut image = page.clone();
    let mut output = Vec::new();
    let explicit_balloons = regions.iter().any(|r| r.is_balloon);
    let cap = page_font_cap(regions);
    for region in regions {
        region.bounds.checked(page.dimensions())?;
        if let Some(mask) = &region.interior {
            let b = mask.bounds.checked(page.dimensions())?;
            crate::same_geometry((b.width(), b.height()), mask.pixels.dimensions())?;
        }
    }
    let mut interiors = split_shared_interiors(regions)?;
    if let Some(ext) = occupied_external {
        for interior in interiors.iter_mut().flatten() {
            let b = interior.bounds;
            for (x, y, p) in interior.pixels.enumerate_pixels_mut() {
                if ext.get_pixel(b.x() + x, b.y() + y)[0] != 0 {
                    p[0] = 0;
                }
            }
            *interior = trim_interior(interior.clone());
        }
    }
    for (region, interior) in regions.iter().zip(&interiors) {
        let bounds = interior
            .as_ref()
            .map_or(region.bounds, |m| m.bounds)
            .checked(page.dimensions())?;
        if region.id.trim().is_empty()
            || !ids.insert(&region.id)
            || region.min_size < 1
            || region.max_size > 512
            || region.min_size > region.max_size
            || !region.line_spacing.is_finite()
            || region.line_spacing <= 0.0
        {
            return Err(VisionError::invalid(format!(
                "invalid typesetting settings for {}",
                region.id
            )));
        }
        let logical = region.text.clone();
        if !crate::bidi::has_logical_order(&crate::bidi::ensure_rli_pdi(&logical)?)? {
            return Err(VisionError::invalid(format!(
                "{} is not logical Unicode",
                region.id
            )));
        }
        let cap = if uses_balloon_cap(region, explicit_balloons) {
            let room = bounds.width().min(bounds.height());
            cap.min((room.saturating_mul(4) / 10).clamp(18, 72))
        } else {
            region.max_size
        };
        let fit = fit_region(
            &mut shaper,
            &logical,
            &region.style,
            FitOptions {
                bounds,
                mask: interior.as_ref().map(|m| &m.pixels),
                occupied: &occupied,
                min_size: region.min_size,
                max_size: region.max_size.min(cap.max(region.min_size)),
                spacing: region.line_spacing,
                compact: region.compact,
                align: region.align,
                rtl_target: region.rtl_target,
            },
        )?
        .ok_or_else(|| VisionError::Overflow {
            id: region.id.clone(),
        })?;
        let (font_size, line_height, ink_box) = (fit.size, fit.line_height, fit.bounds);
        if interior.is_none()
            && let Some((first, _)) = output.iter().zip(regions).find(
                |(placed, previous): &(&TypesetRegion, &TextRegion)| {
                    previous.interior.is_none() && placed.ink_box.intersection(ink_box).is_some()
                },
            )
        {
            return Err(VisionError::Overlap {
                first: first.id.clone(),
                second: region.id.clone(),
            });
        }
        let fill = region.style.color.unwrap_or_else(|| color(page, bounds));
        let lines = render(&mut image, &mut mask, fit, &region.style, fill);
        for y in ink_box.y()..ink_box.bottom() {
            for x in ink_box.x()..ink_box.right() {
                if mask.get_pixel(x, y)[0] != 0 {
                    occupied.put_pixel(x, y, Luma([255]));
                }
            }
        }
        output.push(TypesetRegion {
            id: region.id.clone(),
            logical_text: logical,
            font_size,
            line_height,
            ink_box,
            lines,
            angle_deg: typestyle::effective_angle_deg(&region.style),
            outline_px: typestyle::effective_outline_radius(&region.style, font_size),
        });
    }
    Ok(TypesetPage {
        image,
        regions: output,
        mask,
    })
}

fn uses_balloon_cap(region: &TextRegion, explicit_balloons: bool) -> bool {
    if explicit_balloons {
        region.is_balloon
    } else {
        region.interior.is_some() && !region.compact
    }
}

fn page_font_cap(regions: &[TextRegion]) -> u32 {
    let explicit_balloons = regions.iter().any(|r| r.is_balloon);
    let mut sizes = regions
        .iter()
        .filter(|r| uses_balloon_cap(r, explicit_balloons))
        .map(|r| {
            let b = r.interior.as_ref().map_or(r.bounds, |m| m.bounds);
            b.width().min(b.height())
        })
        .collect::<Vec<_>>();
    sizes.sort_unstable();
    sizes.get(sizes.len() / 2).map_or(72, |&size| {
        // Legacy callers do not distinguish balloon paper from other interiors.
        let max = if size <= 96 || !explicit_balloons {
            38
        } else {
            52
        };
        (size.saturating_mul(4) / 10).clamp(24, max)
    })
}

fn split_shared_interiors(regions: &[TextRegion]) -> Result<Vec<Option<RegionMask>>> {
    let mut interiors = regions
        .iter()
        .map(|r| r.interior.clone())
        .collect::<Vec<_>>();
    let mut assigned = BTreeSet::new();
    for (i, region) in regions.iter().enumerate() {
        let Some(interior) = &region.interior else {
            continue;
        };
        if !assigned.insert(i) {
            continue;
        }
        let members = regions
            .iter()
            .enumerate()
            .skip(i)
            .filter(|(index, other)| {
                if *index != i && assigned.contains(index) {
                    return false;
                }
                other.interior.as_ref().is_some_and(|m| {
                    m.bounds.intersection(interior.bounds).is_some_and(|b| {
                        b.area() * 10 >= m.bounds.area().max(interior.bounds.area()) * 8
                    })
                })
            })
            .collect::<Vec<_>>();
        if members.len() < 2 {
            continue;
        }
        let anchors = members.iter().map(|(_, r)| r.bounds).collect::<Vec<_>>();
        let partitions = partition_shared_interiors(
            &interior.pixels,
            [interior.bounds.x(), interior.bounds.y()],
            &anchors,
            1,
        )?;
        for ((index, member), pixels) in members.into_iter().zip(partitions) {
            assigned.insert(index);
            let original = member.interior.as_ref().unwrap_or(interior);
            let pixels = GrayImage::from_fn(pixels.width(), pixels.height(), |x, y| {
                let (gx, gy) = (interior.bounds.x() + x, interior.bounds.y() + y);
                if pixels.get_pixel(x, y)[0] != 0 && original.bounds.contains(gx, gy) {
                    *original
                        .pixels
                        .get_pixel(gx - original.bounds.x(), gy - original.bounds.y())
                } else {
                    Luma([0])
                }
            });
            interiors[index] = Some(trim_interior(RegionMask {
                bounds: interior.bounds,
                pixels,
            }));
        }
    }
    for (i, interior) in interiors.iter_mut().enumerate() {
        let Some(mask) = interior.as_mut() else {
            continue;
        };
        let own = regions[i].bounds;
        let foreign = regions
            .iter()
            .enumerate()
            .filter_map(|(j, other)| {
                if i == j || own.intersection(other.bounds).is_some() {
                    return None;
                }
                mask.bounds
                    .intersection(other.bounds)
                    .map(|overlap| (other.bounds, overlap))
            })
            .collect::<Vec<_>>();
        for (sibling, overlap) in foreign {
            // If the paper reached a disjoint box, keep this lobe on its own side of the gap.
            let cutoff = if own.bottom() <= sibling.y() {
                Rect([
                    mask.bounds.x(),
                    mask.bounds.y().min(sibling.y()),
                    mask.bounds.width(),
                    sibling.y().saturating_sub(mask.bounds.y()),
                ])
            } else if sibling.bottom() <= own.y() {
                Rect([
                    mask.bounds.x(),
                    sibling.bottom(),
                    mask.bounds.width(),
                    mask.bounds.bottom().saturating_sub(sibling.bottom()),
                ])
            } else if own.right() <= sibling.x() {
                Rect([
                    mask.bounds.x(),
                    mask.bounds.y(),
                    sibling.x().saturating_sub(mask.bounds.x()),
                    mask.bounds.height(),
                ])
            } else if sibling.right() <= own.x() {
                Rect([
                    sibling.right(),
                    mask.bounds.y(),
                    mask.bounds.right().saturating_sub(sibling.right()),
                    mask.bounds.height(),
                ])
            } else {
                continue;
            };
            let mut overlap_paper = 0u64;
            for y in overlap.y()..overlap.bottom() {
                for x in overlap.x()..overlap.right() {
                    if mask
                        .pixels
                        .get_pixel(x - mask.bounds.x(), y - mask.bounds.y())[0]
                        != 0
                    {
                        overlap_paper += 1;
                    }
                }
            }
            if overlap_paper < 4 {
                continue;
            }
            for (x, y, p) in mask.pixels.enumerate_pixels_mut() {
                if !cutoff.contains(mask.bounds.x() + x, mask.bounds.y() + y) {
                    p[0] = 0;
                }
            }
        }
        *mask = trim_interior(mask.clone());
    }
    Ok(interiors)
}

fn trim_interior(mask: RegionMask) -> RegionMask {
    let Some(local) = crate::mask_bounds(&mask.pixels) else {
        return mask;
    };
    let pixels = image::imageops::crop_imm(
        &mask.pixels,
        local.x(),
        local.y(),
        local.width(),
        local.height(),
    )
    .to_image();
    let bounds = Rect([
        mask.bounds.x() + local.x(),
        mask.bounds.y() + local.y(),
        local.width(),
        local.height(),
    ]);
    RegionMask { bounds, pixels }
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::Rgb;

    #[test]
    fn a_speech_lobe_stays_above_a_neighbor_with_a_different_interior() -> Result<()> {
        let page = RgbImage::from_pixel(220, 300, Rgb([245; 3]));
        let speech_box = Rect([118, 45, 45, 48]);
        let sign_box = Rect([47, 112, 120, 115]);
        let speech_area = Rect([44, 34, 140, 205]);
        let interior = |b: Rect| RegionMask {
            bounds: b,
            pixels: GrayImage::from_pixel(b.width(), b.height(), Luma([255])),
        };
        let mut speech = TextRegion::new("speech", speech_box, "هومورا!");
        speech.interior = Some(interior(speech_area));
        let mut sign = TextRegion::new("sign", sign_box, "اینو به‌عنوان رقیبت می‌گم.");
        sign.interior = Some(interior(sign_box));
        let result = typeset_page(&page, &[speech, sign])?;
        assert!(
            result.regions[0].ink_box.bottom() <= sign_box.y(),
            "{:?}",
            result.regions[0].ink_box
        );
        assert!(
            result.regions[1]
                .ink_box
                .intersection(result.regions[0].ink_box)
                .is_none()
        );
        Ok(())
    }

    #[test]
    fn a_tiny_sfx_does_not_shrink_a_roomy_speech_balloon() -> Result<()> {
        let paper = RgbImage::from_pixel(300, 260, image::Rgb([255; 3]));
        let mut speech = TextRegion::new("speech", Rect([0, 0, 150, 260]), "نگاه کنین!");
        speech.is_balloon = true;
        let mut sfx = TextRegion::new("sfx", Rect([180, 0, 60, 40]), "تق");
        sfx.compact = true;
        let speech_alone = typeset_page(&paper, std::slice::from_ref(&speech))?;
        let together = typeset_page(&paper, &[speech, sfx])?;
        assert!(together.regions[0].font_size >= 30.0);
        assert_eq!(
            together.regions[0].font_size,
            speech_alone.regions[0].font_size
        );
        Ok(())
    }

    #[test]
    fn rotated_persian_keeps_its_outline_and_passes_ink_qa() -> Result<()> {
        let paper = RgbImage::from_pixel(180, 100, image::Rgb([160; 3]));
        let bounds = Rect([9, 8, 150, 80]);
        let mut region = TextRegion::new("title", bounds, "سلام\nدنیا");
        region.interior = Some(RegionMask {
            bounds,
            pixels: GrayImage::from_fn(bounds.width(), bounds.height(), |x, y| {
                Luma([u8::from(
                    x >= 5 && x < bounds.width() - 5 && y >= 4 && y < bounds.height() - 4,
                ) * 255])
            }),
        });
        region.style.angle_deg = Some(-9.0);
        region.style.outline = true;
        region.style.outline_px = Some(2);
        region.style.outline_alpha = Some(120);
        let mut occupied = GrayImage::new(paper.width(), paper.height());
        for x in 105..125 {
            occupied.put_pixel(x, 29, Luma([255]));
        }
        let faint =
            typeset_page_with_occupied(&paper, std::slice::from_ref(&region), Some(&occupied))?;
        let entry = &faint.regions[0];
        assert_eq!(entry.angle_deg, -9.0);
        assert_eq!(entry.outline_px, 2);
        assert_eq!(entry.lines.len(), 2);
        assert_eq!(entry.ink_box.intersection(bounds), Some(entry.ink_box));
        let mut shaper = Shaper::new()?;
        crate::qa::verify_rotated_ink(
            &mut shaper,
            &region.text,
            entry,
            &region.style,
            &paper,
            &faint.image,
            region.rtl_target,
        )?;
        assert!(
            crate::qa::verify_rotated_ink(
                &mut shaper,
                &region.text,
                entry,
                &region.style,
                &paper,
                &paper,
                region.rtl_target
            )
            .is_err()
        );
        assert_eq!(
            crate::qa::compare_outside_mask(&paper, &faint.image, &faint.mask)?.changed,
            0
        );
        assert!(
            faint
                .mask
                .enumerate_pixels()
                .filter(|(_, _, p)| p[0] != 0)
                .all(|(x, y, _)| {
                    (14..154).contains(&x)
                        && (12..84).contains(&y)
                        && occupied.get_pixel(x, y)[0] == 0
                })
        );
        let target = crate::bidi::ensure_rli_pdi(&entry.logical_text)?;
        let report = crate::qa::run_strict_qa(crate::qa::QaPage {
            original: &paper,
            cleaned: &paper,
            final_image: &faint.image,
            authorized: &faint.mask,
            regions: &[crate::qa::QaRegion {
                id: &entry.id,
                target: &target,
                ink_box: Some(entry.ink_box),
                balloon: None,
                font_size: Some(entry.font_size),
                line_height: Some(entry.line_height),
            }],
        })?;
        assert!(report.ok, "{:?}", report.findings);
        region.style.outline_alpha = None;
        let solid = typeset_page_with_occupied(&paper, &[region], Some(&occupied))?;
        assert!(
            solid
                .image
                .pixels()
                .zip(faint.image.pixels())
                .any(|(solid, faint)| { solid[0] == 255 && (161..=205).contains(&faint[0]) })
        );
        Ok(())
    }

    #[test]
    fn shared_paper_is_partitioned_and_short_speech_uses_the_page_cap() -> Result<()> {
        let page = RgbImage::from_pixel(420, 340, Rgb([245; 3]));
        let b = Rect([15, 10, 270, 115]);
        let shared = RegionMask {
            bounds: b,
            pixels: GrayImage::from_pixel(b.width(), b.height(), Luma([255])),
        };
        let mut right = TextRegion::new("right", Rect([205, 55, 20, 12]), "باشه.");
        right.interior = Some(shared.clone());
        right.style.outline = true;
        right.style.shadow = true;
        let mut left = TextRegion::new("left", Rect([55, 55, 20, 12]), "آشیکابی می‌خواین؟");
        left.interior = Some(shared);
        let mut tall = TextRegion::new("tall", Rect([360, 135, 20, 18]), "دست منه.");
        let b = Rect([319, 40, 96, 250]);
        tall.interior = Some(RegionMask {
            bounds: b,
            pixels: GrayImage::from_fn(96, 250, |x, y| {
                let (dx, dy) = ((f64::from(x) - 48.) / 47., (f64::from(y) - 125.) / 124.);
                Luma([if dx * dx + dy * dy < 1. { 255 } else { 0 }])
            }),
        });
        let rendered = typeset_page(&page, &[right, left, tall])?;
        assert_eq!(rendered.regions.len(), 3);
        assert!(rendered.regions[1].ink_box.right() <= rendered.regions[0].ink_box.x());
        assert!(rendered.regions[0].font_size <= 38.0);
        assert!(rendered.regions[2].font_size >= 24.0);
        assert!(rendered.regions[2].lines.len() > 1);
        Ok(())
    }
}
