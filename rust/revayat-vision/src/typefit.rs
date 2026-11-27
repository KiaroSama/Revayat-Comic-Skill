use crate::{
    Rect, Result, VisionError, bidi,
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

fn wrap(
    shaper: &mut Shaper,
    paragraphs: &[Vec<String>],
    size: f32,
    style: &TextStyle,
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
        let unit = |v: f32| ((v * 64.0).ceil() as u64).into();
        let advances = words
            .iter()
            .map(|w| shaper.width(w, size, style.weight()).map(unit))
            .collect::<Result<Vec<BigInt>>>()?;
        if advances
            .iter()
            .any(|w| w > &BigInt::from(u64::from(width) * 64))
        {
            return Ok(None);
        }
        let space = unit(shaper.width(" ", size, style.weight())?);
        let bands = vec![BigInt::from(u64::from(width) * 64); rows.min(words.len())];
        let wrapped = textcore_rs::port::balanced_wrap_lines(advances, space, bands)
            .map_err(VisionError::kernel)?;
        if wrapped.is_empty() {
            return Ok(None);
        }
        for line in wrapped {
            let [start, end] = <[usize; 2]>::try_from(line)
                .map_err(|_| VisionError::invalid("invalid line range from the wrap kernel"))?;
            let words = words
                .get(start..end)
                .filter(|line| !line.is_empty())
                .ok_or_else(|| VisionError::invalid("invalid line range from the wrap kernel"))?;
            result.push(words.join(" "));
        }
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
        occupied,
        min_size,
        max_size,
        spacing,
        compact,
        align,
    } = opts;
    let source = text;
    let paragraphs = tokens(text);
    if paragraphs.iter().all(Vec::is_empty) {
        return Ok(None);
    }
    let spans = mask
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
        let effect =
            (if style.outline { (size / 12).max(1) } else { 0 }) + if style.shadow { 3 } else { 0 };
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
            let Some(lines) = wrap(shaper, &paragraphs, size as f32, style, available, max_rows)?
            else {
                continue;
            };
            let centered = (paper_center.unwrap_or(bounds.height() as f32 / 2.0)
                - line_height * lines.len() as f32 / 2.0)
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
                let shaped = shaper.draw_in_direction(
                    &text,
                    size as f32,
                    style.weight(),
                    bidi::is_rtl_text(source),
                )?;
                if shaped.pixels.width() == 0 {
                    continue;
                }
                let ink = if style.italic {
                    typestyle::italicize(&shaped.pixels)
                } else {
                    shaped.pixels
                };
                let border = if style.outline { (size / 12).max(1) } else { 0 };
                let brush = if border > 0 {
                    typestyle::stroke(&ink, border)
                } else {
                    ink.clone()
                };
                shaped_lines.push((i, text, shaped.top, shaped.rtl, ink, brush, border));
            }
            let shift = (size as i32 / 4).max(1);
            for line_top in [
                centered,
                centered - shift,
                centered + shift,
                centered - 2 * shift,
                centered + 2 * shift,
            ] {
                let mut fitted = Vec::new();
                let mut extent: Option<Rect> = None;
                let mut failed = false;
                for (i, text, top, rtl, ink, brush, border) in &shaped_lines {
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
                    let blocked = |x: u32, y: u32| {
                        occupied.get_pixel(x, y)[0] != 0
                            || mask.is_some_and(|m| {
                                m.get_pixel(x - bounds.x(), y - bounds.y())[0] == 0
                            })
                    };
                    if brush.enumerate_pixels().any(|(x, y, p)| {
                        let (x, y) = (bbox.x() - border + x, bbox.y() - border + y);
                        p[0] != 0 && (blocked(x, y) || (style.shadow && blocked(x + 2, y + 2)))
                    }) {
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
                if !failed && let Some(bounds) = extent {
                    return Ok(Some(Fit {
                        lines: fitted,
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
