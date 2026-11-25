use crate::{
    Rect, Result, VisionError, luminance,
    masks::RegionMask,
    qachecks::rendered_text_overlaps,
    typefit::{Alignment, Fit, FitOptions, MIN_LINE_HEIGHT, PlacedLine, fit_region},
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
    pub align: Alignment,
    pub style: TextStyle,
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
            align: Alignment::Center,
            style: TextStyle::default(),
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
    let mut rendered = Vec::new();
    for (line, ink) in fit.lines {
        let b = line.bbox;
        let border = if style.outline {
            (fit.size as u32 / 12).max(1)
        } else {
            0
        };
        let brush = if border > 0 {
            typestyle::stroke(&ink, border)
        } else {
            ink.clone()
        };
        let x = b.x() - border;
        let y = b.y() - border;
        if style.shadow {
            typestyle::paint(page, &brush, x + 2, y + 2, [0; 3], 72);
        }
        if style.outline {
            let outline = if u32::from(fill[0]) + u32::from(fill[1]) + u32::from(fill[2]) > 384 {
                [0; 3]
            } else {
                [255; 3]
            };
            typestyle::paint(page, &brush, x, y, outline, 255);
        }
        typestyle::paint(page, &ink, b.x(), b.y(), fill, 255);
        for (i, j, _) in brush.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
            mask.put_pixel(x + i, y + j, Luma([255]));
            if style.shadow {
                mask.put_pixel(x + i + 2, y + j + 2, Luma([255]));
            }
        }
        rendered.push(line);
    }
    rendered
}

/// Fits every region before painting, so an overflow or collision never produces a partial page.
pub fn typeset_page(page: &RgbImage, regions: &[TextRegion]) -> Result<TypesetPage> {
    crate::same_geometry(page.dimensions(), page.dimensions())?;
    let mut shaper = Shaper::new()?;
    let mut ids = BTreeSet::new();
    let mut fits = Vec::new();
    for region in regions {
        let bounds = region.bounds.checked(page.dimensions())?;
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
        let cropped = region
            .interior
            .as_ref()
            .map(|m| {
                m.bounds.checked(page.dimensions())?;
                crate::same_geometry((m.bounds.width(), m.bounds.height()), m.pixels.dimensions())?;
                Ok::<_, VisionError>(GrayImage::from_fn(
                    bounds.width(),
                    bounds.height(),
                    |x, y| {
                        let (x, y) = (x + bounds.x(), y + bounds.y());
                        if m.bounds.contains(x, y) {
                            *m.pixels.get_pixel(x - m.bounds.x(), y - m.bounds.y())
                        } else {
                            Luma([0])
                        }
                    },
                ))
            })
            .transpose()?;
        let logical = crate::bidi::ensure_rli_pdi(&region.text)?;
        if !crate::bidi::has_logical_order(&logical)? {
            return Err(VisionError::invalid(format!(
                "{} is not logical Unicode",
                region.id
            )));
        }
        // Wrapping reconstructs an isolate on each shaped line; it must never split an existing pair.
        let wrapping = logical.replace(['\u{200f}', '\u{2067}', '\u{2069}'], "");
        let fit = fit_region(
            &mut shaper,
            &wrapping,
            &region.style,
            FitOptions {
                bounds,
                mask: cropped.as_ref(),
                min_size: region.min_size,
                max_size: region.max_size,
                spacing: region.line_spacing,
                align: region.align,
            },
        )?
        .ok_or_else(|| VisionError::Overflow {
            id: region.id.clone(),
        })?;
        fits.push((region, logical, fit));
    }
    let boxes = fits
        .iter()
        .map(|(r, _, f)| (r.id.as_str(), f.bounds))
        .collect::<Vec<_>>();
    if let Some(overlap) = rendered_text_overlaps(&boxes).first() {
        return Err(VisionError::Overlap {
            first: overlap.first.clone(),
            second: overlap.second.clone(),
        });
    }
    let mut mask = GrayImage::new(page.width(), page.height());
    let mut image = page.clone();
    let mut regions = Vec::new();
    for (region, logical_text, fit) in fits {
        let (ink_box, font_size, line_height) = (fit.bounds, fit.size, fit.line_height);
        let fill = region
            .style
            .color
            .unwrap_or_else(|| color(page, region.bounds));
        let lines = render(&mut image, &mut mask, fit, &region.style, fill);
        regions.push(TypesetRegion {
            id: region.id.clone(),
            logical_text,
            font_size,
            line_height,
            ink_box,
            lines,
        });
    }
    Ok(TypesetPage {
        image,
        regions,
        mask,
    })
}
