use crate::{Rect, Result, VisionError, mask_bounds, typefont::Shaper, typestyle::TextStyle};
use image::{GrayImage, Luma};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    Flat,
    Rotated,
    Curved,
    Warped,
    Unreliable,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
pub struct Lettering {
    pub bounds: Rect,
    pub center: [f64; 2],
    pub angle: f64,
    pub elongation: f64,
    pub weight: f64,
    pub modulation: f64,
    pub contrast: f64,
    pub curvature: f64,
    pub residual: f64,
    pub taper: f64,
    pub verdict: Verdict,
}

pub fn measure(mask: &GrayImage, origin: [u32; 2]) -> Option<Lettering> {
    let local = mask_bounds(mask)?;
    let bounds = Rect([
        local.x().checked_add(origin[0])?,
        local.y().checked_add(origin[1])?,
        local.width(),
        local.height(),
    ]);
    let points = mask
        .enumerate_pixels()
        .filter(|(_, _, p)| p[0] != 0)
        .map(|(x, y, _)| (f64::from(x), f64::from(y)))
        .collect::<Vec<_>>();
    let n = points.len() as f64;
    if n < 5.0 {
        return None;
    }
    let (sx, sy) = points
        .iter()
        .fold((0.0, 0.0), |(sx, sy), (x, y)| (sx + x, sy + y));
    let (cx, cy) = (sx / n, sy / n);
    let (xx, xy, yy) = points
        .iter()
        .fold((0.0, 0.0, 0.0), |(xx, xy, yy), &(x, y)| {
            let (x, y) = (x - cx, y - cy);
            (xx + x * x, xy + x * y, yy + y * y)
        });
    let angle = (2.0 * xy).atan2(xx - yy) / 2.0;
    let (sin, cos) = angle.sin_cos();
    let (major, minor) = (
        (xx + yy + (xx - yy).hypot(2.0 * xy)) / 2.0,
        (xx + yy - (xx - yy).hypot(2.0 * xy)) / 2.0,
    );
    let elongation = (major / minor.max(1.0)).sqrt();
    let span = (major / n).sqrt() * 3.46;
    let mut bins = [(0.0, 0.0, f64::INFINITY, f64::NEG_INFINITY); 9];
    for &(x, y) in &points {
        let (x, y) = (x - cx, y - cy);
        let u = x * cos + y * sin;
        let v = -x * sin + y * cos;
        let i = ((u / span + 0.5) * 9.0).floor().clamp(0.0, 8.0) as usize;
        let b = &mut bins[i];
        b.0 += v;
        b.1 += 1.0;
        b.2 = b.2.min(v);
        b.3 = b.3.max(v);
    }
    let mean = |i: usize| {
        let (x, n, _, _) = bins[i];
        (n > 0.0).then_some(x / n)
    };
    let (a, m, b) = (mean(1), mean(4), mean(7));
    let curvature = match (a, m, b) {
        (Some(a), Some(m), Some(b)) => (m - (a + b) / 2.0) / span.max(1.0),
        _ => 0.0,
    };
    let thickness = |ids: std::ops::Range<usize>| {
        ids.map(|i| {
            if bins[i].1 > 0.0 {
                bins[i].3 - bins[i].2 + 1.0
            } else {
                0.0
            }
        })
        .sum::<f64>()
            / 3.0
    };
    let (left, right) = (thickness(0..3), thickness(6..9));
    let taper = right.max(1.0) / left.max(1.0);
    let weight = n / bounds.area() as f64;
    let mut residual = 0.0;
    if let (Some(a), Some(m), Some(b)) = (a, m, b) {
        let predict = |u: f64| m + (b - a) * u / 2.0 + ((a + b) / 2.0 - m) * u * u;
        residual = (0..9)
            .filter_map(|i| mean(i).map(|v| (v - predict((i as f64 - 4.0) / 3.0)).abs()))
            .sum::<f64>()
            / 9.0
            / span.max(1.0);
    }
    let angle = angle.to_degrees();
    let verdict = if elongation < 1.25 || curvature.abs() > 0.35 {
        Verdict::Unreliable
    } else if curvature.abs() >= 0.04 && residual < 0.25 {
        Verdict::Curved
    } else if (taper - 1.0).abs() >= 0.25 {
        Verdict::Warped
    } else if angle.abs() >= 5.0 {
        Verdict::Rotated
    } else {
        Verdict::Flat
    };
    Some(Lettering {
        bounds,
        center: [cx + f64::from(origin[0]), cy + f64::from(origin[1])],
        angle,
        elongation,
        weight,
        modulation: (taper - 1.0).abs(),
        contrast: (f64::from(local.width()) / f64::from(local.height())).clamp(0.25, 4.0),
        curvature,
        residual,
        taper,
        verdict,
    })
}

/// Draw the lettering to a transparent mask limited to the caller's approved box.
pub fn render(
    text: &str,
    measured: Lettering,
    style: &TextStyle,
    limit: Rect,
    max_size: u32,
) -> Result<GrayImage> {
    if measured.verdict == Verdict::Unreliable
        || ![measured.angle, measured.curvature, measured.taper]
            .into_iter()
            .all(f64::is_finite)
        || !(1..=512).contains(&max_size)
        || limit.area() == 0
    {
        return Err(VisionError::invalid(
            "on-art lettering geometry needs review",
        ));
    }
    let mut font = Shaper::new()?;
    let text = crate::bidi::ensure_rli_pdi(text)?;
    let angle = measured.angle.to_radians();
    let (sin, cos) = angle.sin_cos();
    for size in (1..=max_size).rev() {
        let body = font.draw(&text, size as f32, style.weight())?.pixels;
        if body.is_empty() {
            break;
        }
        let body = if style.italic {
            crate::typestyle::italicize(&body)
        } else {
            body
        };
        let body = if style.outline {
            crate::typestyle::stroke(&body, (size / 12).max(1))
        } else {
            body
        };
        let (w, h) = (f64::from(body.width()), f64::from(body.height()));
        let c = measured.curvature.clamp(-0.35, 0.35);
        let taper = measured.taper.clamp(0.5, 2.0);
        let span_y = h * taper.max(1.0) + c.abs() * w;
        let rw = w * cos.abs() + span_y * sin.abs();
        let rh = w * sin.abs() + span_y * cos.abs();
        if rw + 2.0 > f64::from(limit.width()) || rh + 2.0 > f64::from(limit.height()) {
            continue;
        }
        let (cx, cy) = (
            f64::from(limit.width()) / 2.0,
            f64::from(limit.height()) / 2.0,
        );
        let out = GrayImage::from_fn(limit.width(), limit.height(), |x, y| {
            let (x, y) = (f64::from(x) - cx, f64::from(y) - cy);
            let u = x * cos + y * sin;
            // The curved envelope is displaced by half its sag; center that envelope in the box.
            let v = -x * sin + y * cos + c * w / 2.0;
            let ratio = (u / w + 0.5).clamp(0.0, 1.0);
            let scale = (1.0 + (taper - 1.0) * ratio).max(0.5);
            let x = u + w / 2.0;
            let y = (v - c * w * (1.0 - (2.0 * ratio - 1.0).powi(2))) / scale + h / 2.0;
            if x >= 0.0 && x < w && y >= 0.0 && y < h {
                *body.get_pixel(x.floor() as u32, y.floor() as u32)
            } else {
                Luma([0])
            }
        });
        if out.pixels().any(|p| p[0] != 0) {
            return Ok(out);
        }
    }
    Err(VisionError::invalid(
        "on-art lettering does not fit its approved box",
    ))
}
