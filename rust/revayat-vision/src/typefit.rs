use crate::{
    Rect, Result, VisionError, bidi, mask_bounds,
    typefont::Shaper,
    typestyle::{self, TextStyle},
};
use image::GrayImage;
use num_bigint::BigInt;
use serde::{Deserialize, Serialize};

pub const MIN_LINE_HEIGHT: f32 = 1.38;
const PUNCT: &[char] = &[
    '،', '؛', '.', '…', '؟', '!', '?', ',', ':', '»', ')', ']', '}',
];

#[derive(Debug, Clone, Copy, Default, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Alignment {
    Leading,
    #[default]
    Center,
    Trailing,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlacedLine {
    pub text: String,
    pub bbox: Rect,
    pub rtl: bool,
    pub baseline: f32,
}

#[derive(Debug, Clone)]
pub(crate) struct Fit {
    pub lines: Vec<(PlacedLine, GrayImage)>,
    pub rotated: Option<(Rect, GrayImage)>,
    pub size: f32,
    pub line_height: f32,
    pub bounds: Rect,
}

pub fn tokens(text: &str) -> Vec<Vec<String>> {
    text.replace("\r\n", "\n")
        .split(['\r', '\n', '\u{85}', '\u{2028}', '\u{2029}'])
        .map(|line| {
            let mut tokens: Vec<String> = Vec::new();
            for word in line.split_whitespace() {
                if word.starts_with(PUNCT)
                    && let Some(last) = tokens.last_mut()
                {
                    last.push_str(word);
                } else {
                    tokens.push(word.into());
                }
            }
            tokens
        })
        .collect()
}

fn split_persian_hyphen_tokens(words: &[String]) -> Option<Vec<(String, bool)>> {
    let mut expanded = Vec::with_capacity(words.len() + 2);
    let mut changed = false;
    for word in words {
        if word.contains('-')
            && !word.contains("://")
            && !word.contains("www.")
            && word.chars().any(bidi::is_rtl_char)
        {
            let parts: Vec<&str> = word.split('-').collect();
            let valid_parts = parts.len() >= 2
                && parts
                    .iter()
                    .all(|p| !p.is_empty() && p.chars().any(bidi::is_rtl_char));
            if valid_parts {
                changed = true;
                for (idx, part) in parts.iter().enumerate() {
                    if idx + 1 < parts.len() {
                        expanded.push((format!("{part}-"), true));
                    } else {
                        expanded.push(((*part).to_owned(), false));
                    }
                }
                continue;
            }
        }
        expanded.push((word.clone(), false));
    }
    changed.then_some(expanded)
}

fn wrap_pieces(
    shaper: &mut Shaper,
    pieces: &[(String, bool)],
    size: f32,
    style: &TextStyle,
    rtl: bool,
    width: u32,
    rows: usize,
) -> Result<Option<Vec<String>>> {
    let unit = |v: f32| ((v * 64.0).ceil() as u64).into();
    let advances = pieces
        .iter()
        .map(|(w, _)| {
            shaper
                .width_in_direction(w, size, style.weight(), rtl)
                .map(unit)
        })
        .collect::<Result<Vec<BigInt>>>()?;
    if advances
        .iter()
        .any(|w| w > &BigInt::from(u64::from(width) * 64))
    {
        return Ok(None);
    }
    let space = unit(shaper.width_in_direction(" ", size, style.weight(), rtl)?);
    let bands = vec![BigInt::from(u64::from(width) * 64); rows.min(pieces.len())];
    let wrapped = textcore_rs::port::balanced_wrap_lines(advances, space, bands)
        .map_err(VisionError::kernel)?;
    if wrapped.is_empty() {
        return Ok(None);
    }
    let mut lines = Vec::with_capacity(wrapped.len());
    for line in wrapped {
        let [start, end] = <[usize; 2]>::try_from(line)
            .map_err(|_| VisionError::invalid("invalid line range from the wrap kernel"))?;
        let slice = pieces
            .get(start..end)
            .filter(|line| !line.is_empty())
            .ok_or_else(|| VisionError::invalid("invalid line range from the wrap kernel"))?;
        let mut joined = String::new();
        let mut prev_no_space = false;
        for (token, no_space_after) in slice {
            if !joined.is_empty() && !prev_no_space {
                joined.push(' ');
            }
            joined.push_str(token);
            prev_no_space = *no_space_after;
        }
        lines.push(joined);
    }
    Ok(Some(lines))
}

fn wrap(
    shaper: &mut Shaper,
    paragraphs: &[Vec<String>],
    size: f32,
    style: &TextStyle,
    rtl: bool,
    width: u32,
    max_rows: usize,
) -> Result<Option<Vec<String>>> {
    let mut result = Vec::new();
    for words in paragraphs {
        if words.is_empty() {
            result.push(String::new());
            continue;
        }
        let rows = max_rows.saturating_sub(result.len());
        if rows == 0 {
            return Ok(None);
        }
        let plain: Vec<(String, bool)> = words.iter().map(|w| (w.clone(), false)).collect();
        let fitted = match wrap_pieces(shaper, &plain, size, style, rtl, width, rows)? {
            Some(lines) => Some(lines),
            None => match split_persian_hyphen_tokens(words) {
                Some(split) => wrap_pieces(shaper, &split, size, style, rtl, width, rows)?,
                None => None,
            },
        };
        let Some(lines) = fitted else {
            return Ok(None);
        };
        result.extend(lines);
    }
    Ok((result.len() <= max_rows).then_some(result))
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct FitOptions<'a> {
    pub bounds: Rect,
    pub mask: Option<&'a GrayImage>,
    pub occupied: &'a GrayImage,
    pub min_size: u32,
    pub max_size: u32,
    pub spacing: f32,
    pub compact: bool,
    pub align: Alignment,
    pub rtl_target: bool,
}

pub(crate) fn fit_region(
    shaper: &mut Shaper,
    text: &str,
    style: &TextStyle,
    opts: FitOptions<'_>,
) -> Result<Option<Fit>> {
    let FitOptions {
        bounds,
        mask,
        min_size,
        max_size,
        spacing,
        compact,
        align,
        rtl_target,
        ..
    } = opts;
    let source = text;
    let base_rtl = bidi::should_shape_rtl(source, rtl_target);
    let paragraphs = tokens(text);
    if paragraphs.iter().all(Vec::is_empty) {
        return Ok(None);
    }
    let angle = typestyle::effective_angle_deg(style);
    let spans = mask
        .filter(|_| angle == 0.0)
        .map(|m| {
            layoutcore_rs::port::scan_mask_spans(
                Some(m.as_raw()),
                Some(m.width() as usize),
                Some(m.height() as usize),
            )
            .map_err(VisionError::kernel)
        })
        .transpose()?;
    let max_width = spans.as_ref().map_or(bounds.width(), |v| {
        v.iter().map(|[l, r]| r - l).max().unwrap_or_default() as u32
    });
    let paper_center = spans.as_ref().and_then(|rows| {
        let (weighted_y, weight) =
            rows.iter()
                .enumerate()
                .fold((0.0, 0.0), |(sum, total), (y, [l, r])| {
                    let weight = ((*r - *l) as f32).powi(2);
                    (sum + (y as f32 + 0.5) * weight, total + weight)
                });
        (weight > 0.0).then_some(weighted_y / weight)
    });
    for size in (min_size..=max_size).rev() {
        let line_height = (size as f32 * spacing.max(MIN_LINE_HEIGHT)).ceil();
        let border = typestyle::effective_outline_radius(style, size as f32);
        let effect = border + if style.shadow { 3 } else { 0 };
        let pad = effect + if compact { 1 } else { 2 };
        let max_rows =
            (bounds.height().saturating_sub(pad * 2) as f32 / line_height).floor() as usize;
        if max_rows == 0 {
            continue;
        }
        let attempts = [
            max_width,
            max_width * 9 / 10,
            max_width * 8 / 10,
            max_width * 7 / 10,
            max_width * 6 / 10,
            max_width / 2,
        ];
        for width in attempts {
            let available =
                width.saturating_sub(2 * pad + u32::from(style.italic) * (size / 6 + 1));
            if available == 0 {
                continue;
            }
            let Some(lines) = wrap(
                shaper,
                &paragraphs,
                size as f32,
                style,
                base_rtl,
                available,
                max_rows,
            )?
            else {
                continue;
            };
            let line_count = lines.len();
            let centered = (paper_center.unwrap_or(bounds.height() as f32 / 2.0)
                - line_height * line_count as f32 / 2.0)
                .floor() as i32;
            let mut shaped_lines = Vec::new();
            let mut isolates = Vec::new();
            for (i, text) in lines.into_iter().enumerate() {
                if text.is_empty() {
                    continue;
                }
                // Each visual line closes and reopens authored isolates across a wrap boundary.
                let mut balanced = isolates.iter().collect::<String>();
                balanced.push_str(&text);
                for ch in text.chars() {
                    match ch {
                        '\u{2066}'..='\u{2068}' => isolates.push(ch),
                        bidi::PDI if isolates.pop().is_none() => {
                            return Err(VisionError::invalid("unmatched directional isolate"));
                        }
                        _ => {}
                    }
                }
                balanced.extend(std::iter::repeat_n(bidi::PDI, isolates.len()));
                let text = bidi::ensure_rli_pdi(&balanced)?;
                let shaped =
                    shaper.draw_in_direction(&text, size as f32, style.weight(), base_rtl)?;
                if shaped.pixels.width() == 0 {
                    continue;
                }
                let ink = if style.italic {
                    typestyle::italicize(&shaped.pixels)
                } else {
                    shaped.pixels
                };
                let brush = (angle == 0.0 && border > 0).then(|| typestyle::stroke(&ink, border));
                shaped_lines.push((i, text, shaped.top, shaped.rtl, ink, brush));
            }
            let shift = (size as i32 / 4).max(1);
            let mut candidates = vec![
                centered,
                centered - shift,
                centered + shift,
                centered - 2 * shift,
                centered + 2 * shift,
            ];
            let block_h = (line_height * line_count as f32).ceil() as i32;
            let max_top = bounds.height() as i32 - block_h - pad as i32;
            if max_top > pad as i32 {
                let step = (size as i32 / 3).max(4);
                let mut extras = Vec::new();
                let mut y = pad as i32;
                while y <= max_top {
                    if !candidates.contains(&y) {
                        extras.push(y);
                    }
                    y += step;
                }
                if !candidates.contains(&max_top) && !extras.contains(&max_top) {
                    extras.push(max_top);
                }
                extras.sort_by_key(|&y| (y - centered).abs());
                candidates.extend(extras);
            }
            for line_top in candidates {
                let mut fitted = Vec::new();
                let mut extent: Option<Rect> = None;
                let mut failed = false;
                for (i, text, top, rtl, ink, brush) in &shaped_lines {
                    let offset = line_top + (*i as f32 * line_height) as i32;
                    let local_y = offset + top;
                    if local_y < pad as i32
                        || (local_y as u32)
                            .saturating_add(ink.height())
                            .saturating_add(pad)
                            > bounds.height()
                    {
                        failed = true;
                        break;
                    }
                    let local_y = local_y as u32;
                    let [left, right] = if let Some(spans) = &spans {
                        let band = &spans
                            [(local_y - pad) as usize..(local_y + ink.height() + pad) as usize];
                        [
                            band.iter().map(|s| s[0]).max().unwrap_or(0) as u32,
                            band.iter().map(|s| s[1]).min().unwrap_or(0) as u32,
                        ]
                    } else {
                        [0, bounds.width()]
                    };
                    if right.saturating_sub(left) < ink.width() + 2 * pad {
                        failed = true;
                        break;
                    }
                    let x = match (align, *rtl) {
                        (Alignment::Center, _) => left + (right - left - ink.width()) / 2,
                        (Alignment::Leading, true) | (Alignment::Trailing, false) => {
                            right - ink.width() - pad
                        }
                        _ => left + pad,
                    };
                    let bbox = Rect([
                        bounds.x() + x,
                        bounds.y() + local_y,
                        ink.width(),
                        ink.height(),
                    ]);
                    let footprint = Rect([
                        bbox.x() - effect,
                        bbox.y() - effect,
                        bbox.width() + 2 * effect,
                        bbox.height() + 2 * effect,
                    ]);
                    if angle == 0.0
                        && brush_blocked(
                            brush.as_ref().unwrap_or(ink),
                            bbox,
                            border,
                            style.shadow.then_some([2, 2]),
                            opts,
                        )
                    {
                        failed = true;
                        break;
                    }
                    if fitted
                        .last()
                        .is_some_and(|(line, _): &(PlacedLine, GrayImage)| {
                            line.bbox.bottom() + 2 * effect > bbox.y()
                        })
                    {
                        failed = true;
                        break;
                    }
                    extent = Some(extent.map_or(footprint, |p| p.union(footprint)));
                    fitted.push((
                        PlacedLine {
                            text: text.clone(),
                            bbox,
                            rtl: *rtl,
                            baseline: bounds.y() as f32 + offset as f32 + size as f32,
                        },
                        ink.clone(),
                    ));
                }
                if !failed && let Some(extent) = extent {
                    let (rotated, bounds) = if angle == 0.0 {
                        (None, extent)
                    } else {
                        let Some((bbox, ink, footprint)) =
                            rotate_block(&fitted, angle, border, style.shadow, opts)
                        else {
                            continue;
                        };
                        (Some((bbox, ink)), footprint)
                    };
                    return Ok(Some(Fit {
                        lines: fitted,
                        rotated,
                        size: size as f32,
                        line_height,
                        bounds,
                    }));
                }
            }
        }
    }
    Ok(None)
}

fn brush_blocked(
    brush: &GrayImage,
    bbox: Rect,
    border: u32,
    shadow: Option<[i64; 2]>,
    opts: FitOptions<'_>,
) -> bool {
    let blocked = |x: i64, y: i64| {
        let (Ok(x), Ok(y)) = (u32::try_from(x), u32::try_from(y)) else {
            return true;
        };
        !opts.bounds.contains(x, y)
            || opts.occupied.get_pixel(x, y)[0] != 0
            || opts
                .mask
                .is_some_and(|m| m.get_pixel(x - opts.bounds.x(), y - opts.bounds.y())[0] == 0)
    };
    brush.enumerate_pixels().any(|(x, y, p)| {
        let x = i64::from(bbox.x()) - i64::from(border) + i64::from(x);
        let y = i64::from(bbox.y()) - i64::from(border) + i64::from(y);
        p[0] != 0 && (blocked(x, y) || shadow.is_some_and(|[dx, dy]| blocked(x + dx, y + dy)))
    })
}

pub(crate) fn rotate_line_ink(
    lines: &[(PlacedLine, GrayImage)],
    extent: Rect,
    angle: f32,
) -> GrayImage {
    let mut block = GrayImage::new(extent.width(), extent.height());
    for (line, ink) in lines {
        image::imageops::replace(
            &mut block,
            ink,
            i64::from(line.bbox.x() - extent.x()),
            i64::from(line.bbox.y() - extent.y()),
        );
    }
    typestyle::rotate_mask(&block, angle)
}

fn rotate_block(
    lines: &[(PlacedLine, GrayImage)],
    angle: f32,
    border: u32,
    shadow: bool,
    opts: FitOptions<'_>,
) -> Option<(Rect, GrayImage, Rect)> {
    let extent = lines
        .iter()
        .map(|(line, _)| line.bbox)
        .reduce(Rect::union)?;
    let rotated = rotate_line_ink(lines, extent, angle);
    let tight = mask_bounds(&rotated)?;
    let ink = image::imageops::crop_imm(
        &rotated,
        tight.x(),
        tight.y(),
        tight.width(),
        tight.height(),
    )
    .to_image();
    let brush = (border > 0).then(|| typestyle::stroke(&ink, border));
    let brush = brush.as_ref().unwrap_or(&ink);
    let shift = shadow.then(|| typestyle::shadow_offset(angle));
    let [dx, dy] = shift.unwrap_or_default();
    let anchor = |start, fitted, canvas, trim| {
        i64::from(start) + (i64::from(fitted) - i64::from(canvas)).div_euclid(2) + i64::from(trim)
    };
    let x = anchor(extent.x(), extent.width(), rotated.width(), tight.x());
    let y = anchor(extent.y(), extent.height(), rotated.height(), tight.y());
    let footprint = Rect([
        u32::try_from(x - i64::from(border) - (-dx).max(0)).ok()?,
        u32::try_from(y - i64::from(border) - (-dy).max(0)).ok()?,
        brush.width() + dx.unsigned_abs() as u32,
        brush.height() + dy.unsigned_abs() as u32,
    ]);
    let bbox = Rect([
        u32::try_from(x).ok()?,
        u32::try_from(y).ok()?,
        ink.width(),
        ink.height(),
    ]);
    (footprint.intersection(opts.bounds) == Some(footprint)
        && !brush_blocked(brush, bbox, border, shift, opts))
    .then_some((bbox, ink, footprint))
}

pub fn partition_shared_interiors(
    mask: &GrayImage,
    origin: [u32; 2],
    members: &[Rect],
    seam: u32,
) -> Result<Vec<GrayImage>> {
    let boxes = members.iter().map(|b| b.0.map(i64::from)).collect();
    let owners = maskcore_rs::port::partition_voronoi_lobes(
        Some(mask.as_raw()),
        i128::from(mask.width()),
        i128::from(mask.height()),
        i128::from(origin[0]),
        i128::from(origin[1]),
        Ok(boxes),
        i128::from(seam),
    )
    .map_err(VisionError::kernel)?;
    use image::Luma;
    use imageproc::region_labelling::{Connectivity, connected_components};

    // An opened core separates lobes at a narrow neck before considering OCR distances.
    let mut core = crate::masks::morphology(mask, 5, true)?;
    for (x, y, p) in core.enumerate_pixels_mut() {
        if x < 5 || y < 5 || mask.width() - x <= 5 || mask.height() - y <= 5 {
            p[0] = 0;
        }
    }
    let labels = connected_components(&core, Connectivity::Four, Luma([0]));
    let mut nearest = vec![(u128::MAX, 0); members.len()];
    for (x, y, p) in labels.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
        for (member, best) in members.iter().zip(&mut nearest) {
            let [cx, cy] = member.center();
            let dx = u128::from((origin[0] as u64 + u64::from(x)).abs_diff(u64::from(cx)));
            let dy = u128::from((origin[1] as u64 + u64::from(y)).abs_diff(u64::from(cy)));
            if dx * dx + dy * dy < best.0 {
                *best = (dx * dx + dy * dy, p[0]);
            }
        }
    }
    let separate = members.len() > 1
        && nearest.iter().enumerate().all(|(i, &(_, label))| {
            label != 0 && nearest[..i].iter().all(|&(_, earlier)| earlier != label)
        });
    let overlap = if separate {
        let lobes = nearest
            .iter()
            .map(|&(_, label)| {
                let core = GrayImage::from_fn(mask.width(), mask.height(), |x, y| {
                    Luma([if labels.get_pixel(x, y)[0] == label {
                        255
                    } else {
                        0
                    }])
                });
                crate::masks::morphology(&core, 3, false)
            })
            .collect::<Result<Vec<_>>>()?;
        let mut count = vec![0u8; owners.len()];
        for lobe in &lobes {
            for (n, &active) in count.iter_mut().zip(lobe.iter()) {
                *n = n.saturating_add(u8::from(active != 0));
            }
        }
        Some((lobes, count))
    } else {
        None
    };
    (0..members.len())
        .map(|i| {
            if let Some((lobes, count)) = &overlap {
                return crate::masks::from_raw(
                    mask.dimensions(),
                    lobes[i]
                        .iter()
                        .zip(count)
                        .map(|(&p, &n)| if n == 1 { p } else { 0 })
                        .collect(),
                );
            }
            let paper = crate::masks::from_raw(
                mask.dimensions(),
                owners
                    .iter()
                    .map(|p| if *p == i as i64 { 255 } else { 0 })
                    .collect(),
            )?;
            let b = Rect([0, 0, mask.width(), mask.height()]);
            Ok(crate::masks::inset_balloon(
                &crate::masks::RegionMask {
                    bounds: b,
                    pixels: paper,
                },
                2,
            )?
            .pixels)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::Luma;

    #[test]
    fn rotated_fit_keeps_alignment_and_tries_other_vertical_positions() -> Result<()> {
        let bounds = Rect([10, 10, 240, 120]);
        let occupied = GrayImage::new(260, 140);
        let style = TextStyle {
            angle_deg: Some(5.0),
            ..TextStyle::default()
        };
        let mut shaper = Shaper::new()?;
        let opts = FitOptions {
            bounds,
            mask: None,
            occupied: &occupied,
            min_size: 28,
            max_size: 28,
            spacing: MIN_LINE_HEIGHT,
            compact: false,
            align: Alignment::Leading,
            rtl_target: false,
        };
        let first = fit_region(&mut shaper, "TITLE", &style, opts)?.unwrap();
        assert!(first.bounds.right() < bounds.center()[0]);
        let (bbox, ink) = first.rotated.unwrap();
        let (x, y, _) = ink.enumerate_pixels().find(|(_, _, p)| p[0] != 0).unwrap();
        let mut blocked = occupied.clone();
        blocked.put_pixel(bbox.x() + x, bbox.y() + y, Luma([255]));
        let moved = fit_region(
            &mut shaper,
            "TITLE",
            &style,
            FitOptions {
                occupied: &blocked,
                ..opts
            },
        )?
        .unwrap();
        assert_eq!(moved.bounds.x(), first.bounds.x());
        assert_ne!(moved.bounds.y(), first.bounds.y());
        Ok(())
    }
}
