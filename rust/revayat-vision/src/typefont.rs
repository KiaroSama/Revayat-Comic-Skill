use crate::{Rect, Result, VisionError};
use cosmic_text::{
    Align, Attrs, Buffer, Color, Family, FontSystem, Metrics, Shaping, SwashCache, Weight, Wrap,
};
use image::{GrayImage, Luma};
use std::borrow::Cow;

fn shaping_text(text: &str, rtl: bool) -> Cow<'_, str> {
    // cosmic-text 0.19 Wrap::None can drop an initial run at the opposite bidi level.
    if rtl && !text.starts_with(crate::bidi::RLM) {
        Cow::Owned(format!("{}{text}", crate::bidi::RLM))
    } else {
        Cow::Borrowed(text)
    }
}

pub const VAZIR_REGULAR: &[u8] =
    include_bytes!("../../../skills/revayat-comic/assets/fonts/Vazir-Regular.ttf");
pub const VAZIR_MEDIUM: &[u8] =
    include_bytes!("../../../skills/revayat-comic/assets/fonts/Vazir-Medium.ttf");
pub const VAZIR_BOLD: &[u8] =
    include_bytes!("../../../skills/revayat-comic/assets/fonts/Vazir-Bold.ttf");
pub const VAZIR_LICENSE: &str = include_str!("../../../skills/revayat-comic/assets/fonts/OFL.txt");

pub struct Shaper {
    fonts: FontSystem,
    cache: SwashCache,
    family: String,
}

#[derive(Debug, Clone)]
pub struct ShapedLine {
    pub pixels: GrayImage,
    pub left: i32,
    pub top: i32,
    pub advance: f32,
    pub rtl: bool,
    pub clusters: Vec<(usize, usize)>,
    pub(crate) cluster_ink: Vec<Vec<(u32, u32)>>,
}

impl Shaper {
    pub fn new() -> Result<Self> {
        let mut db = fontdb::Database::new();
        for data in [VAZIR_REGULAR, VAZIR_MEDIUM, VAZIR_BOLD] {
            db.load_font_data(data.to_vec());
        }
        let family = db
            .faces()
            .flat_map(|f| &f.families)
            .find(|(n, _)| n.to_lowercase().starts_with("vazir"))
            .map(|(n, _)| n.clone())
            .ok_or_else(|| VisionError::invalid("bundled Vazir font could not be loaded"))?;
        db.set_sans_serif_family(family.clone());
        Ok(Self {
            fonts: FontSystem::new_with_locale_and_db("fa-IR".into(), db),
            cache: SwashCache::new(),
            family,
        })
    }

    fn buffer(&mut self, text: &str, size: f32, weight: Weight) -> Result<Buffer> {
        if !size.is_finite()
            || !(1.0..=512.0).contains(&size)
            || text
                .chars()
                .any(|c| matches!(c, '\n' | '\r' | '\u{85}' | '\u{2028}' | '\u{2029}'))
        {
            return Err(VisionError::invalid(
                "a shaped line needs valid metrics and no hard break",
            ));
        }
        let mut buffer = Buffer::new(
            &mut self.fonts,
            Metrics::new(size, size * crate::typefit::MIN_LINE_HEIGHT),
        );
        buffer.set_wrap(Wrap::None);
        buffer.set_text(
            text,
            &Attrs::new()
                .family(Family::Name(&self.family))
                .weight(weight),
            Shaping::Advanced,
            Some(Align::Left),
        );
        buffer.shape_until_scroll(&mut self.fonts, false);
        Ok(buffer)
    }

    pub fn width(&mut self, text: &str, size: f32, weight: Weight) -> Result<f32> {
        let text = shaping_text(text, crate::bidi::is_rtl_text(text));
        Ok(self
            .buffer(&text, size, weight)?
            .layout_runs()
            .next()
            .map_or(0.0, |run| run.line_w))
    }

    pub fn draw(&mut self, text: &str, size: f32, weight: Weight) -> Result<ShapedLine> {
        self.draw_in_direction(text, size, weight, crate::bidi::is_rtl_text(text))
    }

    pub(crate) fn draw_in_direction(
        &mut self,
        text: &str,
        size: f32,
        weight: Weight,
        rtl: bool,
    ) -> Result<ShapedLine> {
        let shaping = shaping_text(text, rtl);
        let prefix = shaping.len() - text.len();
        let buffer = self.buffer(&shaping, size, weight)?;
        let run = buffer.layout_runs().next();
        let advance = run.as_ref().map_or(0.0, |r| r.line_w);
        let rtl = run.as_ref().is_some_and(|r| r.rtl);
        let mut covered_glyphs = Vec::new();
        let mut points = Vec::new();
        if let Some(run) = run {
            for glyph in run.glyphs {
                let g = glyph.physical((0., run.line_y), 1.0);
                let before = points.len();
                self.cache.with_pixels(
                    &mut self.fonts,
                    g.cache_key,
                    Color::rgb(255, 255, 255),
                    |x, y, c| {
                        if c.a() != 0 {
                            points.push((g.x + x, g.y + y, c.a()));
                        }
                    },
                );
                if points.len() > before && glyph.end > prefix && glyph.glyph_id != 0 {
                    let span = (glyph.start.saturating_sub(prefix), glyph.end - prefix);
                    if text
                        .get(span.0..span.1)
                        .is_some_and(|s| s.chars().any(crate::bidi::visible))
                    {
                        covered_glyphs.push((span, before..points.len()));
                    }
                }
            }
        }
        covered_glyphs.sort_unstable_by_key(|g| g.0);
        let mut clusters = covered_glyphs.iter().map(|g| g.0).collect::<Vec<_>>();
        clusters.dedup();
        let mut runs = clusters.iter().peekable();
        let mut covered = 0;
        for (start, c) in text
            .char_indices()
            .filter(|(_, c)| crate::bidi::visible(*c))
        {
            while let Some(&(_, end)) = runs.next_if(|&&(a, _)| a <= start) {
                covered = covered.max(end);
            }
            if covered < start + c.len_utf8() {
                return Err(VisionError::invalid(format!(
                    "shaping produced no ink for the visible cluster at byte {start}"
                )));
            }
        }
        if points.is_empty() {
            return Ok(ShapedLine {
                pixels: GrayImage::new(0, 0),
                left: 0,
                top: 0,
                advance,
                rtl,
                clusters,
                cluster_ink: Vec::new(),
            });
        }
        let (l, t, r, b) = points.iter().fold(
            (i32::MAX, i32::MAX, i32::MIN, i32::MIN),
            |(l, t, r, b), &(x, y, _)| (l.min(x), t.min(y), r.max(x), b.max(y)),
        );
        let bounds = Rect([0, 0, (r - l + 1) as u32, (b - t + 1) as u32]);
        let mut pixels = GrayImage::new(bounds.width(), bounds.height());
        let mut cluster_ink = Vec::new();
        for glyphs in covered_glyphs.chunk_by(|a, b| a.0 == b.0) {
            let coverage = glyphs
                .iter()
                .flat_map(|(_, indices)| &points[indices.clone()]);
            let peak = coverage.clone().map(|p| p.2).max().unwrap_or(0);
            cluster_ink.push(
                coverage
                    .filter(|p| p.2 >= peak / 2)
                    .map(|&(x, y, _)| ((x - l) as u32, (y - t) as u32))
                    .collect(),
            );
        }
        for (x, y, alpha) in points {
            let p = pixels.get_pixel_mut((x - l) as u32, (y - t) as u32);
            *p = Luma([p[0].max(alpha)]);
        }
        Ok(ShapedLine {
            pixels,
            left: l,
            top: t,
            advance,
            rtl,
            clusters,
            cluster_ink,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn persian_leading_runs_and_punctuation_reach_the_raster() -> Result<()> {
        let mut shaper = Shaper::new()?;
        for text in [
            "۳ و ۸…",
            "…پنج دقیقه.",
            "خیلی دوره!",
            "Sekirei 15 است",
            "۳۸",
        ] {
            let line = shaper.draw(text, 34., Weight::NORMAL)?;
            assert!(line.rtl, "{text}");
            for (start, c) in text.char_indices().filter(|(_, c)| !c.is_whitespace()) {
                assert!(
                    line.clusters
                        .iter()
                        .any(|&(a, b)| a <= start && b >= start + c.len_utf8()),
                    "{text}: missing {c}"
                );
            }
        }
        for (text, terminal) in [
            ("۳ و ۸…", '…'),
            ("…پنج دقیقه.", '.'),
            ("خیلی دوره!", '!'),
            ("نگاه می‌کنی؟", '؟'),
        ] {
            let line = shaper.draw(text, 34., Weight::NORMAL)?;
            let index = text.len() - terminal.len_utf8();
            let cluster = line
                .clusters
                .iter()
                .position(|&(a, b)| a <= index && b == text.len())
                .unwrap();
            let punct_right = line.cluster_ink[cluster].iter().map(|p| p.0).max().unwrap();
            assert!(punct_right < line.pixels.width() / 3, "{text}");
        }
        let line = shaper.draw("۳ و ۸…", 34., Weight::NORMAL)?;
        let digit = shaper.draw("۳", 34., Weight::NORMAL)?;
        let right = line.pixels.width() - digit.pixels.width();
        assert!(
            digit
                .pixels
                .enumerate_pixels()
                .filter(|(_, _, p)| p[0] > 128)
                .all(|(x, y, _)| {
                    (0..line.pixels.height().saturating_sub(digit.pixels.height()) + 1)
                        .any(|dy| line.pixels.get_pixel(right + x, y + dy)[0] > 0)
                })
        );
        Ok(())
    }
}
