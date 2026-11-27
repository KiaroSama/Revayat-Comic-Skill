use crate::{Result, VisionError};
use cosmic_text::Weight;
use image::{GrayImage, Luma, Rgb, RgbImage};
use serde::{Deserialize, Serialize};

pub const STYLE_TOKENS: [&str; 6] = [
    "bold",
    "italic",
    "bold-italic",
    "outline",
    "shadow",
    "shout",
];

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct TextStyle {
    pub bold: bool,
    pub medium: bool,
    pub italic: bool,
    pub outline: bool,
    pub shadow: bool,
    pub shout: bool,
    pub color: Option<[u8; 3]>,
}

impl TextStyle {
    pub fn weight(&self) -> Weight {
        if self.bold || self.shout {
            Weight::BOLD
        } else if self.medium {
            Weight::MEDIUM
        } else {
            Weight::NORMAL
        }
    }
}

pub fn normalize_style(value: &str) -> Result<String> {
    let mut found = [false; 6];
    let mut unknown = std::collections::BTreeSet::new();
    let value = value.to_ascii_lowercase();
    for token in value.split(',').map(str::trim).filter(|x| !x.is_empty()) {
        if let Some(i) = STYLE_TOKENS.iter().position(|t| *t == token) {
            found[i] = true;
        } else {
            unknown.insert(token);
        }
    }
    if !unknown.is_empty() {
        return Err(VisionError::invalid(format!(
            "Unknown lettering style: {}",
            unknown.into_iter().collect::<Vec<_>>().join(", ")
        )));
    }
    if found[2] || (found[0] && found[1]) {
        found[..3].copy_from_slice(&[false, false, true]);
    }
    Ok(STYLE_TOKENS
        .iter()
        .zip(found)
        .filter_map(|(t, yes)| yes.then_some(*t))
        .collect::<Vec<_>>()
        .join(", "))
}

pub fn style_flags(value: &str) -> Result<TextStyle> {
    let normalized = normalize_style(value)?;
    let has = |t| normalized.split(',').any(|s| s.trim() == t);
    Ok(TextStyle {
        bold: has("bold") || has("bold-italic"),
        medium: false,
        italic: has("italic") || has("bold-italic"),
        outline: has("outline"),
        shadow: has("shadow"),
        shout: has("shout"),
        color: None,
    })
}

pub(crate) fn italicize(ink: &GrayImage) -> GrayImage {
    let pad = (ink.height() as f32 * 0.16).ceil() as u32;
    let mut out = GrayImage::new(ink.width() + pad, ink.height());
    for (x, y, p) in ink.enumerate_pixels() {
        let dx = ((ink.height().saturating_sub(y + 1)) as f32 * 0.16).round() as u32;
        out.put_pixel(x + dx, y, *p);
    }
    out
}

pub(crate) fn blend(out: &mut Rgb<u8>, color: [u8; 3], alpha: u8) {
    let a = u32::from(alpha);
    for (dst, src) in out.0.iter_mut().zip(color) {
        *dst = ((u32::from(*dst) * (255 - a) + u32::from(src) * a + 127) / 255) as u8;
    }
}

pub(crate) fn paint(
    out: &mut RgbImage,
    mask: &GrayImage,
    x: u32,
    y: u32,
    color: [u8; 3],
    opacity: u8,
) {
    for (i, j, p) in mask.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
        blend(
            out.get_pixel_mut(x + i, y + j),
            color,
            (u16::from(p[0]) * u16::from(opacity) / 255) as u8,
        );
    }
}

pub(crate) fn stroke(ink: &GrayImage, radius: u32) -> GrayImage {
    GrayImage::from_fn(
        ink.width() + 2 * radius,
        ink.height() + 2 * radius,
        |x, y| {
            let mut a = 0;
            for yy in y.saturating_sub(2 * radius)..=y.min(ink.height() - 1) {
                for xx in x.saturating_sub(2 * radius)..=x.min(ink.width() - 1) {
                    if (xx + radius).abs_diff(x).pow(2) + (yy + radius).abs_diff(y).pow(2)
                        <= radius.pow(2)
                    {
                        a = a.max(ink.get_pixel(xx, yy)[0]);
                    }
                }
            }
            Luma([a])
        },
    )
}
