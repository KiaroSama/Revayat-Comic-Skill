use crate::{Rect, Result, VisionError, luminance};
use cosmic_text::Weight;
use image::{GrayImage, Luma, Rgb, RgbImage};
use serde::{Deserialize, Serialize};

pub const STYLE_TOKENS: [&str; 7] = [
    "bold",
    "italic",
    "bold-italic",
    "outline",
    "shadow",
    "shout",
    "no-outline",
];

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct TextStyle {
    pub bold: bool,
    pub medium: bool,
    pub italic: bool,
    pub outline: bool,
    pub outline_px: Option<u32>,
    pub outline_alpha: Option<u8>,
    pub no_outline: bool,
    pub angle_deg: Option<f32>,
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
    let mut found = [false; STYLE_TOKENS.len()];
    let mut unknown = std::collections::BTreeSet::new();
    let value = value.to_ascii_lowercase();
    for token in value
        .split(|c: char| c == ',' || c.is_whitespace())
        .filter(|x| !x.is_empty())
    {
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
        italic: has("italic") || has("bold-italic"),
        outline: has("outline"),
        no_outline: has("no-outline"),
        shadow: has("shadow"),
        shout: has("shout"),
        ..TextStyle::default()
    })
}

pub fn effective_outline_radius(style: &TextStyle, font_size: f32) -> u32 {
    if !style.outline || style.no_outline {
        return 0;
    }
    style
        .outline_px
        .map_or(((font_size as u32) / 14).clamp(1, 3), |r| r.clamp(1, 6))
}

pub const MIN_ROTATION_DEG: f32 = 0.5;

pub fn effective_angle_deg(style: &TextStyle) -> f32 {
    style
        .angle_deg
        .filter(|deg| deg.is_finite() && deg.abs() >= MIN_ROTATION_DEG)
        .map_or(0.0, |deg| deg.clamp(-45.0, 45.0))
}

/// Bilinear alpha sampling, with positive angles rotating clockwise on the page.
pub fn rotate_mask(mask: &GrayImage, angle_deg: f32) -> GrayImage {
    if !angle_deg.is_finite() || angle_deg == 0.0 || mask.width() == 0 || mask.height() == 0 {
        return mask.clone();
    }
    let (sin, cos) = f64::from(angle_deg).to_radians().sin_cos();
    let (w, h) = (f64::from(mask.width()), f64::from(mask.height()));
    let nw = (w * cos.abs() + h * sin.abs()).ceil() as u32;
    let nh = (w * sin.abs() + h * cos.abs()).ceil() as u32;
    let sample = |x: i64, y: i64| {
        if x >= 0 && y >= 0 && x < i64::from(mask.width()) && y < i64::from(mask.height()) {
            f64::from(mask.get_pixel(x as u32, y as u32)[0])
        } else {
            0.0
        }
    };
    GrayImage::from_fn(nw, nh, |x, y| {
        let dx = f64::from(x) - (f64::from(nw) - 1.0) * 0.5;
        let dy = f64::from(y) - (f64::from(nh) - 1.0) * 0.5;
        let sx = cos * dx + sin * dy + (w - 1.0) * 0.5;
        let sy = -sin * dx + cos * dy + (h - 1.0) * 0.5;
        let (ix, iy) = (sx.floor() as i64, sy.floor() as i64);
        let (fx, fy) = (sx - sx.floor(), sy - sy.floor());
        let top = sample(ix, iy) * (1.0 - fx) + sample(ix + 1, iy) * fx;
        let bottom = sample(ix, iy + 1) * (1.0 - fx) + sample(ix + 1, iy + 1) * fx;
        Luma([(top * (1.0 - fy) + bottom * fy).round() as u8])
    })
}

/// Estimates opposite-color halo width and opacity from straight runs out of the source ink.
pub fn detect_original_outline(
    original: &RgbImage,
    bounds: Rect,
    ink_dark: bool,
) -> Option<(u32, u8)> {
    let b = bounds.checked(original.dimensions()).ok()?;
    let tone = |x, y| {
        let l = luminance(original.get_pixel(x, y));
        i16::from(if ink_dark { l } else { 255 - l })
    };
    let mut surround = Vec::new();
    for x in b.x()..b.right() {
        surround.extend([tone(x, b.y()), tone(x, b.bottom() - 1)]);
    }
    for y in b.y()..b.bottom() {
        surround.extend([tone(b.x(), y), tone(b.right() - 1, y)]);
    }
    let mid = surround.len() / 2;
    let background = *surround.select_nth_unstable(mid).1;
    let ink_limit = (background - 24).min(128);
    let mut eligible = 0;
    let mut halos = Vec::new();
    for y in b.y()..b.bottom() {
        for x in b.x()..b.right() {
            if tone(x, y) > ink_limit {
                continue;
            }
            for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                let sample = |d| {
                    let x = (i64::from(x) + dx * d) as u32;
                    let y = (i64::from(y) + dy * d) as u32;
                    b.contains(x, y).then(|| tone(x, y))
                };
                let (Some(first), Some(fourth), Some(fifth)) = (sample(1), sample(4), sample(5))
                else {
                    continue;
                };
                if first <= ink_limit
                    || (fourth - fifth).abs() > 16
                    || (fourth - background).abs() > 28
                {
                    continue;
                }
                eligible += 1;
                let paper = (fourth + fifth) / 2;
                let lift = first - paper;
                if lift < 12 || paper >= 243 {
                    continue;
                }
                let radius = (2..=3)
                    .take_while(|&d| sample(d).is_some_and(|v| v - paper >= (lift / 2).max(12)))
                    .count() as u32
                    + 1;
                let paper = i32::from(paper);
                let alpha = ((i32::from(lift) * 255 + (255 - paper) / 2) / (255 - paper)) as u8;
                halos.push((radius, alpha));
            }
        }
    }
    if halos.len() < 8 || halos.len() * 2 < eligible {
        return None;
    }
    halos.sort_unstable();
    Some(halos[halos.len() / 2])
}

/// Estimates tilt from a dominant horizontal edge in the lettering or frame.
pub fn detect_region_angle(original: &RgbImage, bounds: Rect) -> Option<f32> {
    let b = bounds.checked(original.dimensions()).ok()?;
    let step = (b.width() / 160).max(1) as usize;
    let mut edges = Vec::new();
    for x in (0..b.width()).step_by(step) {
        let mut previous = luminance(original.get_pixel(x + b.x(), b.y()));
        for y in 1..b.height() {
            let current = luminance(original.get_pixel(x + b.x(), b.y() + y));
            if previous.abs_diff(current) >= 48 {
                edges.push((f64::from(x), f64::from(y)));
            }
            previous = current;
        }
    }
    if edges.len() < 8 {
        return None;
    }
    let offset = (b.width() / 2 + 2) as usize;
    let mut votes = vec![0; b.height() as usize + 2 * offset];
    let mut best = (0, 0.0, 0);
    let mut flat = 0;
    for deg in -25_i32..=25 {
        let slope = f64::from(deg).to_radians().tan();
        votes.fill(0);
        for &(x, y) in &edges {
            let i = (y - slope * x + offset as f64).round() as usize;
            votes[i] += 1;
        }
        let (index, &score) = votes.iter().enumerate().max_by_key(|&(_, n)| n)?;
        if deg.abs() < 2 {
            flat = flat.max(score);
        } else if score > best.0 {
            best = (score, slope, index);
        }
    }
    let (score, slope, index) = best;
    if score < 8.max(b.width() as usize / step / 4) || score <= flat {
        return None;
    }
    let intercept = index as f64 - offset as f64;
    let mut points: Vec<(f64, f64)> = Vec::new();
    for (x, y) in edges {
        let error = (y - slope * x - intercept).abs();
        if error > 1.0 {
            continue;
        }
        if let Some((last_x, last_y)) = points.last_mut()
            && *last_x == x
        {
            if error < (*last_y - slope * x - intercept).abs() {
                *last_y = y;
            }
        } else {
            points.push((x, y));
        }
    }
    let n = points.len() as f64;
    let (sx, sy) = points
        .iter()
        .fold((0.0, 0.0), |(sx, sy), &(x, y)| (sx + x, sy + y));
    let (xx, yy, xy) = points
        .iter()
        .fold((0.0, 0.0, 0.0), |(xx, yy, xy), &(x, y)| {
            let (dx, dy) = (x - sx / n, y - sy / n);
            (xx + dx * dx, yy + dy * dy, xy + dx * dy)
        });
    let angle = (xy / xx).atan().to_degrees() as f32;
    (xy * xy >= 0.85 * xx * yy && (2.0..=25.0).contains(&angle.abs())).then_some(angle)
}

pub(crate) fn shadow_offset(angle_deg: f32) -> [i64; 2] {
    let (sin, cos) = angle_deg.to_radians().sin_cos();
    [
        (2.0 * (cos - sin)).round() as i64,
        (2.0 * (sin + cos)).round() as i64,
    ]
}

pub(crate) fn italicize(ink: &GrayImage) -> GrayImage {
    let pad = (ink.height() as f32 * 0.16).ceil() as u32;
    let mut out = GrayImage::new(ink.width() + pad, ink.height());
    for (x, y, p) in ink.enumerate_pixels() {
        out.put_pixel(x + italic_shift(ink.height(), y), y, *p);
    }
    out
}

pub(crate) fn italic_shift(height: u32, y: u32) -> u32 {
    ((height.saturating_sub(y + 1)) as f32 * 0.16).round() as u32
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outlines_scale_to_three_pixels_unless_overridden() -> Result<()> {
        let mut style = style_flags("outline")?;
        assert_eq!(effective_outline_radius(&style, 28.0), 2);
        assert_eq!(effective_outline_radius(&style, 84.0), 3);
        style.outline_px = Some(8);
        assert_eq!(effective_outline_radius(&style, 28.0), 6);
        assert_eq!(
            effective_outline_radius(&style_flags("outline no-outline")?, 28.0),
            0
        );
        Ok(())
    }

    #[test]
    fn negative_rotation_raises_the_right_end_and_expands_the_canvas() {
        let line = GrayImage::from_pixel(21, 3, Luma([255]));
        let rotated = rotate_mask(&line, -20.0);
        assert_eq!(rotated.dimensions(), (21, 11));
        assert!(rotated.get_pixel(1, 8)[0] > 200);
        assert!(rotated.get_pixel(19, 2)[0] > 200);
        assert_eq!(rotated.get_pixel(0, 0)[0], 0);
    }

    #[test]
    fn detects_faint_outline_and_leaves_plain_text_alone() {
        let image = |halo| {
            RgbImage::from_fn(48, 24, |x, y| {
                let value = if (8..20).contains(&x) && (8..16).contains(&y) {
                    20
                } else if (7..21).contains(&x) && (7..17).contains(&y) {
                    halo
                } else {
                    120
                };
                Rgb([value; 3])
            })
        };
        let bounds = Rect([0, 0, 48, 24]);
        assert_eq!(detect_original_outline(&image(120), bounds, true), None);
        let (radius, alpha) = detect_original_outline(&image(180), bounds, true).unwrap();
        assert_eq!(radius, 1);
        assert!((110..=118).contains(&alpha));
    }

    #[test]
    fn manual_angles_keep_the_half_degree_boundary() {
        let angle = |deg| {
            effective_angle_deg(&TextStyle {
                angle_deg: Some(deg),
                ..TextStyle::default()
            })
        };
        assert_eq!(angle(0.49), 0.0);
        assert_eq!(angle(-0.5), -0.5);
        assert_eq!(angle(90.0), 45.0);
    }

    #[test]
    fn detects_rising_frame_edges_without_tilting_flat_frames() {
        let frame = |rise| {
            RgbImage::from_fn(120, 48, |x, y| {
                let top = 17 - x * rise / 120;
                Rgb([if y == top || y == top + 16 { 32 } else { 248 }; 3])
            })
        };
        let bounds = Rect([0, 0, 120, 48]);
        assert_eq!(detect_region_angle(&frame(0), bounds), None);
        assert!((-7.0..-4.0).contains(&detect_region_angle(&frame(12), bounds).unwrap()));
    }
}
