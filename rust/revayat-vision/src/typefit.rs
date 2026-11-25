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
    pub min_size: u32,
    pub max_size: u32,
    pub spacing: f32,
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
        min_size,
        max_size,
        spacing,
        align,
    } = opts;
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
    for size in (min_size..=max_size).rev() {
        let line_height = (size as f32 * spacing.max(MIN_LINE_HEIGHT)).ceil();
        let effect =
            (if style.outline { (size / 12).max(1) } else { 0 }) + if style.shadow { 3 } else { 0 };
        let pad = effect + 2;
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
            let line_top =
                ((bounds.height() as f32 - line_height * lines.len() as f32) / 2.0).floor() as i32;
            let mut fitted = Vec::new();
            let mut extent: Option<Rect> = None;
            let mut failed = false;
            for (i, text) in lines.into_iter().enumerate() {
                if text.is_empty() {
                    continue;
                }
                let text = bidi::ensure_rli_pdi(&text)?;
                let shaped = shaper.draw(&text, size as f32, style.weight())?;
                if shaped.pixels.width() == 0 {
                    failed = true;
                    break;
                }
                let ink = if style.italic {
                    typestyle::italicize(&shaped.pixels)
                } else {
                    shaped.pixels
                };
                let offset = line_top + (i as f32 * line_height) as i32;
                let local_y = offset + shaped.top;
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
                    let band =
                        &spans[(local_y - pad) as usize..(local_y + ink.height() + pad) as usize];
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
                let x = match (align, shaped.rtl) {
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
                if let Some(mask) = mask
                    && (footprint.y()..footprint.bottom()).any(|y| {
                        (footprint.x()..footprint.right())
                            .any(|x| mask.get_pixel(x - bounds.x(), y - bounds.y())[0] == 0)
                    })
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
                        text,
                        bbox,
                        rtl: shaped.rtl,
                        baseline: bounds.y() as f32 + offset as f32 + size as f32,
                    },
                    ink,
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
    (0..members.len())
        .map(|i| {
            crate::masks::from_raw(
                mask.dimensions(),
                owners
                    .iter()
                    .map(|p| if *p == i as i64 { 255 } else { 0 })
                    .collect(),
            )
        })
        .collect()
}
