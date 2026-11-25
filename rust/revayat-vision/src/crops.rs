use crate::{Rect, Result, VisionError, typefont::Shaper, typestyle};
use cosmic_text::Weight;
use image::{
    Rgb, RgbImage,
    imageops::{self, FilterType},
};
use serde::{Deserialize, Serialize};

pub const OVERVIEW_MAX_SIDE: u32 = 1600;
const MIN_CROP_SIDE: u32 = 150;
const MAX_CROP_SIDE: u32 = 1100;
const MAX_SHEET_HEIGHT: u32 = 4200;
const GUTTER: u32 = 14;
const LABEL_WIDTH: u32 = 190;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CropRegion {
    pub id: String,
    pub bounds: Rect,
    pub balloon: Option<Rect>,
    pub kind: String,
}

#[derive(Debug, Clone)]
pub struct Overview {
    pub image: RgbImage,
    pub scale: f64,
}

fn label(
    canvas: &mut RgbImage,
    shaper: &mut Shaper,
    s: &str,
    x: u32,
    y: u32,
    size: f32,
    color: [u8; 3],
) -> Result<()> {
    let line = shaper.draw(s, size, Weight::MEDIUM)?;
    if x.saturating_add(line.pixels.width()) <= canvas.width()
        && y.saturating_add(line.pixels.height()) <= canvas.height()
    {
        typestyle::paint(canvas, &line.pixels, x, y, color, 255);
    }
    Ok(())
}

fn color(kind: &str) -> Rgb<u8> {
    Rgb(match kind {
        "speech" => [0, 122, 204],
        "thought" => [128, 90, 200],
        "narration" => [0, 150, 110],
        "sfx" => [216, 88, 20],
        "sign" => [170, 140, 0],
        _ => [140; 3],
    })
}

fn frame(canvas: &mut RgbImage, b: Rect, color: Rgb<u8>) {
    if b.area() == 0 {
        return;
    }
    let (x, y, r, d) = (b.x(), b.y(), b.right() - 1, b.bottom() - 1);
    for i in x..=r {
        canvas.put_pixel(i, y, color);
        canvas.put_pixel(i, d, color);
    }
    for i in y..=d {
        canvas.put_pixel(x, i, color);
        canvas.put_pixel(r, i, color);
    }
}

pub fn render_overview(page: &RgbImage, regions: &[CropRegion]) -> Result<Overview> {
    let (w, h) = page.dimensions();
    crate::same_geometry((w, h), (w, h))?;
    let scale = (f64::from(OVERVIEW_MAX_SIDE) / f64::from(w.max(h))).min(1.0);
    let project = |v: u32| (f64::from(v) * scale) as u32;
    let mut image = if scale == 1.0 {
        page.clone()
    } else {
        imageops::resize(
            page,
            project(w).max(1),
            project(h).max(1),
            FilterType::Lanczos3,
        )
    };
    let mut shaper = Shaper::new()?;
    for r in regions {
        let b = r.balloon.unwrap_or(r.bounds).checked(page.dimensions())?;
        let projected = Rect([
            project(b.x()),
            project(b.y()),
            project(b.width()).max(1),
            project(b.height()).max(1),
        ])
        .clip(image.width(), image.height());
        frame(&mut image, projected, color(&r.kind));
        label(
            &mut image,
            &mut shaper,
            &r.id,
            projected.x(),
            projected.y().saturating_sub(13),
            12.0,
            color(&r.kind).0,
        )?;
    }
    Ok(Overview { image, scale })
}

pub fn crop_for(page: &RgbImage, region: &CropRegion) -> Result<RgbImage> {
    let b = region
        .balloon
        .unwrap_or(region.bounds)
        .checked(page.dimensions())?;
    let b = b.expand(
        (0.03 * f64::from(b.width().max(b.height()))).round() as u32,
        page.width(),
        page.height(),
    );
    let crop = imageops::crop_imm(page, b.x(), b.y(), b.width(), b.height()).to_image();
    let max = crop.width().max(crop.height());
    let min = crop.width().min(crop.height());
    let scale = (f64::from(MIN_CROP_SIDE) / f64::from(min))
        .max(1.0)
        .min(f64::from(MAX_CROP_SIDE) / f64::from(max));
    if scale == 1.0 {
        return Ok(crop);
    }
    Ok(imageops::resize(
        &crop,
        (f64::from(b.width()) * scale).round().max(1.0) as u32,
        (f64::from(b.height()) * scale).round().max(1.0) as u32,
        FilterType::Lanczos3,
    ))
}

pub fn render_sheets(page: &RgbImage, regions: &[CropRegion]) -> Result<Vec<RgbImage>> {
    if regions.is_empty() {
        return Ok(Vec::new());
    }
    let mut sheets = Vec::new();
    let mut rows = Vec::new();
    let mut used = GUTTER;
    let mut shaper = Shaper::new()?;
    for region in regions {
        let crop = crop_for(page, region)?;
        let row = crop.height().max(64) + GUTTER;
        if used + row > MAX_SHEET_HEIGHT && !rows.is_empty() {
            sheets.push(compose(std::mem::take(&mut rows), used, &mut shaper)?);
            used = GUTTER;
        }
        rows.push((region, crop));
        used += row;
    }
    sheets.push(compose(rows, used, &mut shaper)?);
    Ok(sheets)
}

fn compose(
    rows: Vec<(&CropRegion, RgbImage)>,
    height: u32,
    shaper: &mut Shaper,
) -> Result<RgbImage> {
    let max = rows
        .iter()
        .map(|(_, c)| c.width())
        .max()
        .ok_or_else(|| VisionError::invalid("empty crop sheet"))?;
    let mut out =
        RgbImage::from_pixel(max + LABEL_WIDTH + GUTTER * 2, height, Rgb([250, 250, 248]));
    let mut y = GUTTER;
    for (region, crop) in rows {
        let x = LABEL_WIDTH + GUTTER;
        imageops::replace(&mut out, &crop, i64::from(x), i64::from(y));
        frame(
            &mut out,
            Rect([x - 1, y - 1, crop.width() + 2, crop.height() + 2]),
            Rgb([196, 196, 190]),
        );
        label(&mut out, shaper, &region.id, 22, y + 4, 15.0, [20; 3])?;
        label(
            &mut out,
            shaper,
            &region.kind,
            22,
            y + 21,
            13.0,
            color(&region.kind).0,
        )?;
        let [x0, y0, w, h] = region.bounds.0;
        label(
            &mut out,
            shaper,
            &format!("{x0} {y0} {w} {h}"),
            22,
            y + 38,
            13.0,
            [90; 3],
        )?;
        y += crop.height().max(64) + GUTTER;
    }
    Ok(out)
}
