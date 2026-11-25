use crate::{Rect, Result, VisionError};
use cosmic_text::{
    Align, Attrs, Buffer, Color, Family, FontSystem, Metrics, Shaping, SwashCache, Weight, Wrap,
};
use image::{GrayImage, Luma};

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
        Ok(self
            .buffer(text, size, weight)?
            .layout_runs()
            .next()
            .map_or(0.0, |run| run.line_w))
    }

    pub fn draw(&mut self, text: &str, size: f32, weight: Weight) -> Result<ShapedLine> {
        let mut buffer = self.buffer(text, size, weight)?;
        let run = buffer.layout_runs().next();
        let advance = run.as_ref().map_or(0.0, |r| r.line_w);
        let rtl = run.as_ref().is_some_and(|r| r.rtl);
        let clusters = run.map_or_else(Vec::new, |r| {
            r.glyphs.iter().map(|g| (g.start, g.end)).collect()
        });
        let mut points = Vec::new();
        buffer.draw(
            &mut self.fonts,
            &mut self.cache,
            Color::rgb(255, 255, 255),
            |x, y, w, h, c| {
                if c.a() != 0 {
                    for dy in 0..h {
                        for dx in 0..w {
                            points.push((x + dx as i32, y + dy as i32, c.a()));
                        }
                    }
                }
            },
        );
        if points.is_empty() {
            return Ok(ShapedLine {
                pixels: GrayImage::new(0, 0),
                left: 0,
                top: 0,
                advance,
                rtl,
                clusters,
            });
        }
        let (l, t, r, b) = points.iter().fold(
            (i32::MAX, i32::MAX, i32::MIN, i32::MIN),
            |(l, t, r, b), &(x, y, _)| (l.min(x), t.min(y), r.max(x), b.max(y)),
        );
        let bounds = Rect([0, 0, (r - l + 1) as u32, (b - t + 1) as u32]);
        let mut pixels = GrayImage::new(bounds.width(), bounds.height());
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
        })
    }
}
