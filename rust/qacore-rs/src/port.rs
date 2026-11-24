//! Pixel QA over packed grayscale, RGB and mask buffers.
#![forbid(unsafe_code)]

use std::sync::OnceLock;

const DIMENSIONS: &str = "ValueError: invalid image dimensions";
const BUFFER: &str = "ValueError: pixel buffer must be bytes and match image dimensions";
const CHANNEL: &str = "ValueError: luma and difference thresholds must be integers from 0 to 255";
const RADIUS: &str = "ValueError: radius must be a nonnegative integer";
const CLUSTER: &str = "ValueError: minimum cluster size must be a positive integer";

type QaResult<T> = Result<T, &'static str>;

#[derive(Clone, Copy)]
struct Image {
    width: usize,
    height: usize,
    size: usize,
}

impl Image {
    fn new(width: i128, height: i128) -> QaResult<Self> {
        let width = usize::try_from(width).map_err(|_| DIMENSIONS)?;
        let height = usize::try_from(height).map_err(|_| DIMENSIONS)?;
        let size = width.checked_mul(height).ok_or(DIMENSIONS)?;
        if size == 0 || size > isize::MAX as usize {
            return Err(DIMENSIONS);
        }
        Ok(Self {
            width,
            height,
            size,
        })
    }

    fn buffer(self, data: Option<&[u8]>, channels: usize) -> QaResult<&[u8]> {
        let length = self.size.checked_mul(channels).ok_or(BUFFER)?;
        data.filter(|bytes| bytes.len() == length).ok_or(BUFFER)
    }

    fn radius(self, value: i128) -> QaResult<usize> {
        if value < 0 {
            return Err(RADIUS);
        }
        let limit = self.width.max(self.height);
        Ok(value.min(limit as i128) as usize)
    }

    fn xy(self, i: usize) -> (usize, usize) {
        (i % self.width, i / self.width)
    }
}

fn channel(value: i128) -> QaResult<u8> {
    u8::try_from(value).map_err(|_| CHANNEL)
}

struct Bounds {
    left: i64,
    top: i64,
    right: i64,
    bottom: i64,
}

impl Bounds {
    fn new(image: Image) -> Self {
        Self {
            left: image.width as i64,
            top: image.height as i64,
            right: -1,
            bottom: -1,
        }
    }

    fn include(&mut self, image: Image, i: usize) {
        let (x, y) = image.xy(i);
        let (x, y) = (x as i64, y as i64);
        self.left = self.left.min(x);
        self.top = self.top.min(y);
        self.right = self.right.max(x);
        self.bottom = self.bottom.max(y);
    }
}

fn scan_axis(
    mask: &[u8],
    output: &mut [u8],
    lines: usize,
    length: usize,
    line_step: usize,
    pixel_step: usize,
    radius: usize,
) {
    for line in 0..lines {
        let start = line * line_step;
        let mut latest = 0;
        let mut cursor = 0;
        for center in 0..length {
            let stop = length.min(center + radius + 1);
            while cursor < stop {
                if mask[start + cursor * pixel_step] != 0 {
                    latest = cursor + 1;
                }
                cursor += 1;
            }
            if latest > center.saturating_sub(radius) {
                output[start + center * pixel_step] = 1;
            }
        }
    }
}

fn neighborhood(mask: &[u8], image: Image, radius: usize) -> Option<Vec<u8>> {
    if radius == 0 || !mask.contains(&0) || mask.iter().all(|&pixel| pixel == 0) {
        return None;
    }
    let mut rows = vec![0; image.size];
    let mut out = vec![0; image.size];
    scan_axis(
        mask,
        &mut rows,
        image.height,
        image.width,
        image.width,
        1,
        radius,
    );
    scan_axis(
        &rows,
        &mut out,
        image.width,
        image.height,
        1,
        image.width,
        radius,
    );
    Some(out)
}

pub fn detect_outline_bleed(
    orig_gray: Option<&[u8]>,
    final_gray: Option<&[u8]>,
    width: i128,
    height: i128,
    ink_mask: Option<&[u8]>,
    wall_thresh: i128,
    diff_thresh: i128,
) -> QaResult<Vec<i64>> {
    let image = Image::new(width, height)?;
    let original = image.buffer(orig_gray, 1)?;
    let final_pixels = image.buffer(final_gray, 1)?;
    let ink = image.buffer(ink_mask, 1)?;
    let wall = channel(wall_thresh)?;
    let diff = i16::from(channel(diff_thresh)?);
    let (mut erased, mut crossed) = (0, 0);
    let mut bounds = Bounds::new(image);
    for (i, ((&before, &after), &ink)) in original.iter().zip(final_pixels).zip(ink).enumerate() {
        if before >= wall {
            continue;
        }
        if ink != 0 {
            crossed += 1;
        } else if i16::from(after) - i16::from(before) >= diff {
            erased += 1;
        } else {
            continue;
        }
        bounds.include(image, i);
    }
    if bounds.right < 0 {
        bounds.left = -1;
        bounds.top = -1;
    }
    Ok(vec![
        erased,
        crossed,
        bounds.left,
        bounds.top,
        bounds.right,
        bounds.bottom,
    ])
}

fn srgb_table() -> &'static [f64; 256] {
    static TABLE: OnceLock<[f64; 256]> = OnceLock::new();
    TABLE.get_or_init(|| {
        std::array::from_fn(|channel| {
            let value = channel as f64 / 255.0;
            if value <= 0.04045 {
                value / 12.92
            } else {
                ((value + 0.055) / 1.055).powf(2.4)
            }
        })
    })
}

pub fn measure_region_contrast(
    rgb: Option<&[u8]>,
    ink_mask: Option<&[u8]>,
    width: i128,
    height: i128,
    pad: i128,
) -> QaResult<Vec<f64>> {
    let image = Image::new(width, height)?;
    let rgb = image.buffer(rgb, 3)?;
    let mask = image.buffer(ink_mask, 1)?;
    let radius = image.radius(pad)?;
    let Some(near) = neighborhood(mask, image, radius) else {
        return Ok(vec![1.0, 0.0, 0.0]);
    };
    let table = srgb_table();
    let mut count = [0usize; 2];
    let mut sum = [0.0; 2];
    for ((pixel, ink), included) in rgb.as_chunks::<3>().0.iter().zip(mask).zip(near) {
        if included != 0 {
            let group = usize::from(*ink != 0);
            count[group] += 1;
            sum[group] += 0.2126 * table[usize::from(pixel[0])]
                + 0.7152 * table[usize::from(pixel[1])]
                + 0.0722 * table[usize::from(pixel[2])];
        }
    }
    if count[0] == 0 {
        return Ok(vec![1.0, 0.0, 0.0]);
    }
    let ink = sum[1] / count[1] as f64;
    let bg = sum[0] / count[0] as f64;
    Ok(vec![(ink.max(bg) + 0.05) / (ink.min(bg) + 0.05), ink, bg])
}

fn delta(before: &[u8; 3], after: &[u8; 3]) -> u8 {
    before[0]
        .abs_diff(after[0])
        .max(before[1].abs_diff(after[1]))
        .max(before[2].abs_diff(after[2]))
}

pub fn detect_halo_artifacts(
    orig_rgb: Option<&[u8]>,
    clean_rgb: Option<&[u8]>,
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    ring_px: i128,
    diff_thresh: i128,
) -> QaResult<Vec<i64>> {
    let image = Image::new(width, height)?;
    let original = image.buffer(orig_rgb, 3)?;
    let clean = image.buffer(clean_rgb, 3)?;
    let mask = image.buffer(mask, 1)?;
    let radius = image.radius(ring_px)?;
    let threshold = channel(diff_thresh)?;
    let Some(ring) = neighborhood(mask, image, radius) else {
        return Ok(vec![0, 0, 0]);
    };
    let (mut dirty, mut max_delta, mut total) = (0, 0, 0);
    for (((before, after), &ink), included) in original
        .as_chunks::<3>()
        .0
        .iter()
        .zip(clean.as_chunks::<3>().0.iter())
        .zip(mask)
        .zip(ring)
    {
        if included != 0 && ink == 0 {
            let change = delta(before, after);
            dirty += i64::from(change > threshold);
            max_delta = max_delta.max(change);
            total += 1;
        }
    }
    Ok(vec![dirty, i64::from(max_delta), total])
}

#[derive(Default)]
struct Moments {
    count: usize,
    x: u128,
    y: u128,
    x2: u128,
    y2: u128,
    xy: u128,
}

impl Moments {
    fn add(&mut self, x: u8, y: u8) {
        let x = u128::from(x);
        let y = u128::from(y);
        self.count += 1;
        self.x += x;
        self.y += y;
        self.x2 += x * x;
        self.y2 += y * y;
        self.xy += x * y;
    }

    fn ssim(&self) -> f64 {
        if self.count == 0 {
            return 1.0;
        }
        let n = self.count as f64;
        let (x, y) = (self.x as f64 / n, self.y as f64 / n);
        let x_var = self.x2 as f64 / n - x * x;
        let y_var = self.y2 as f64 / n - y * y;
        let cov = self.xy as f64 / n - x * y;
        ((2.0 * x * y + 6.5025) * (2.0 * cov + 58.5225))
            / ((x * x + y * y + 6.5025) * (x_var + y_var + 58.5225))
    }
}

pub fn compute_patch_ssim(
    orig_gray: Option<&[u8]>,
    final_gray: Option<&[u8]>,
    width: i128,
    height: i128,
    mask: Option<&[u8]>,
) -> QaResult<f64> {
    let image = Image::new(width, height)?;
    let original = image.buffer(orig_gray, 1)?;
    let final_pixels = image.buffer(final_gray, 1)?;
    let mask = image.buffer(mask, 1)?;
    let mut count = 0usize;
    let mut sum = 0.0;
    for tile_y in 0..image.height / 8 {
        for tile_x in 0..image.width / 8 {
            let rows = (tile_y * 8..tile_y * 8 + 8).map(|y| y * image.width + tile_x * 8);
            if rows.clone().any(|i| mask[i..i + 8].iter().any(|&m| m != 0)) {
                continue;
            }
            let mut moments = Moments::default();
            for i in rows {
                for (&a, &b) in original[i..i + 8].iter().zip(&final_pixels[i..i + 8]) {
                    moments.add(a, b);
                }
            }
            count += 1;
            sum += moments.ssim();
        }
    }
    if count != 0 {
        return Ok(sum / count as f64);
    }
    let mut moments = Moments::default();
    for ((&a, &b), &m) in original.iter().zip(final_pixels).zip(mask) {
        if m == 0 {
            moments.add(a, b);
        }
    }
    Ok(moments.ssim())
}

pub fn detect_residual_ink(
    clean_gray: Option<&[u8]>,
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    bg_luma: i128,
    delta_thresh: i128,
    min_cluster: i128,
) -> QaResult<Vec<i64>> {
    let image = Image::new(width, height)?;
    let gray = image.buffer(clean_gray, 1)?;
    let mask = image.buffer(mask, 1)?;
    let bg = channel(bg_luma)?;
    let threshold = channel(delta_thresh)?;
    if min_cluster < 1 {
        return Err(CLUSTER);
    }
    if min_cluster > image.size as i128 {
        return Ok(vec![0, 0, -1, -1]);
    }
    let mut pending: Vec<_> = gray
        .iter()
        .zip(mask)
        .map(|(&gray, &ink)| ink != 0 && gray.abs_diff(bg) >= threshold)
        .collect();
    let mut stack = Vec::new();
    let (mut total, mut largest) = (0usize, 0);
    let (mut sum_x, mut sum_y) = (0u128, 0u128);
    for i in 0..image.size {
        if !pending[i] {
            continue;
        }
        pending[i] = false;
        stack.push(i);
        let mut count = 0;
        let (mut cluster_x, mut cluster_y) = (0u128, 0u128);
        while let Some(j) = stack.pop() {
            let (x, y) = image.xy(j);
            count += 1;
            cluster_x += x as u128;
            cluster_y += y as u128;
            for ny in y.saturating_sub(1)..(y + 2).min(image.height) {
                for nx in x.saturating_sub(1)..(x + 2).min(image.width) {
                    let k = ny * image.width + nx;
                    if pending[k] {
                        pending[k] = false;
                        stack.push(k);
                    }
                }
            }
        }
        if count >= min_cluster as usize {
            total += count;
            largest = largest.max(count);
            sum_x += cluster_x;
            sum_y += cluster_y;
        }
    }
    if total == 0 {
        return Ok(vec![0, 0, -1, -1]);
    }
    Ok(vec![
        total as i64,
        largest as i64,
        (sum_x / total as u128) as i64,
        (sum_y / total as u128) as i64,
    ])
}

pub fn compute_ink_bounds(
    before_rgb: Option<&[u8]>,
    after_rgb: Option<&[u8]>,
    width: i128,
    height: i128,
    diff_thresh: i128,
) -> QaResult<Vec<i64>> {
    let image = Image::new(width, height)?;
    let before = image.buffer(before_rgb, 3)?;
    let after = image.buffer(after_rgb, 3)?;
    let threshold = channel(diff_thresh)?;
    if before == after {
        return Ok(vec![0, 0, 0, 0, 0]);
    }
    if threshold == 0 {
        return Ok(vec![
            0,
            0,
            image.width as i64,
            image.height as i64,
            image.size as i64,
        ]);
    }
    let mut count = 0;
    let mut bounds = Bounds::new(image);
    for (i, (before, after)) in before
        .as_chunks::<3>()
        .0
        .iter()
        .zip(after.as_chunks::<3>().0.iter())
        .enumerate()
    {
        if delta(before, after) >= threshold {
            count += 1;
            bounds.include(image, i);
        }
    }
    if count == 0 {
        return Ok(vec![0, 0, 0, 0, 0]);
    }
    Ok(vec![
        bounds.left,
        bounds.top,
        bounds.right - bounds.left + 1,
        bounds.bottom - bounds.top + 1,
        count,
    ])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outline_excludes_light_pixels_and_separates_erasure_from_overlap() {
        assert_eq!(
            detect_outline_bleed(
                Some(&[2, 3, 5, 6]),
                Some(&[7, 255, 0, 7]),
                2,
                2,
                Some(&[0, 1, 2, 0]),
                5,
                5
            ),
            Ok(vec![1, 1, 0, 0, 1, 0])
        );
        assert_eq!(
            detect_outline_bleed(Some(&[255]), Some(&[255]), 1, 1, Some(&[1]), 255, 0),
            Ok(vec![0, 0, -1, -1, -1, -1])
        );
    }

    #[test]
    fn contrast_includes_diagonals_and_ignores_distant_background() {
        let rgb = [
            0, 0, 0, 255, 255, 255, 10, 10, 10, 255, 255, 255, 255, 255, 255, 0, 0, 0,
        ];
        let mask = [1, 0, 0, 0, 0, 0];
        assert_eq!(
            measure_region_contrast(Some(&rgb), Some(&mask), 3, 2, 1),
            Ok(vec![21.0, 0.0, 1.0])
        );
        assert_eq!(
            measure_region_contrast(Some(&rgb), Some(&mask), 3, 2, 0),
            Ok(vec![1.0, 0.0, 0.0])
        );
    }

    #[test]
    fn halo_reports_maximum_even_when_no_change_exceeds_threshold() {
        let mask = [1, 0, 0, 0];
        let mut clean = [0; 12];
        clean[1] = 255;
        clean[11] = 40;
        assert_eq!(
            detect_halo_artifacts(Some(&[0; 12]), Some(&clean), Some(&mask), 2, 2, 1, 40),
            Ok(vec![0, 40, 3])
        );
    }

    #[test]
    fn ssim_ignores_partial_tiles_and_falls_back_when_masked() {
        let original = [0; 72];
        let mut changed = original;
        changed[8] = 255;
        assert_eq!(
            compute_patch_ssim(Some(&original), Some(&changed), 9, 8, Some(&[0; 72])),
            Ok(1.0)
        );
        let mask = [1, 0];
        let ratio = 6.5025 / (255.0 * 255.0 + 6.5025);
        assert!(
            matches!(compute_patch_ssim(Some(&[99, 0]), Some(&[2, 255]), 2, 1, Some(&mask)),
                         Ok(v) if (v - ratio).abs() < 1e-15)
        );
        assert_eq!(
            compute_patch_ssim(Some(&[0]), Some(&[255]), 1, 1, Some(&[8])),
            Ok(1.0)
        );
    }

    #[test]
    fn residual_ink_filters_specks_and_joins_diagonals() {
        let gray = [0, 255, 255, 255, 0, 255, 0, 255, 255, 255];
        let mask = [1; 10];
        assert_eq!(
            detect_residual_ink(Some(&gray), Some(&mask), 5, 2, 255, 255, 2),
            Ok(vec![2, 2, 0, 0])
        );
        assert_eq!(
            detect_residual_ink(Some(&gray), Some(&mask), 5, 2, 255, 255, i128::MAX),
            Ok(vec![0, 0, -1, -1])
        );
    }

    #[test]
    fn ink_bounds_are_inclusive_and_count_coordinates_once() {
        let original = [0; 18];
        let mut changed = original;
        changed[5] = 20;
        changed[13] = 20;
        changed[17] = 19;
        assert_eq!(
            compute_ink_bounds(Some(&original), Some(&changed), 3, 2, 20),
            Ok(vec![1, 0, 1, 2, 2])
        );
        assert_eq!(
            compute_ink_bounds(Some(&original), Some(&changed), 3, 2, 0),
            Ok(vec![0, 0, 3, 2, 6])
        );
        assert_eq!(
            compute_ink_bounds(Some(&original), Some(&original), 3, 2, 0),
            Ok(vec![0, 0, 0, 0, 0])
        );
    }

    #[test]
    fn invalid_dimensions_buffers_and_ranges_return_value_errors() {
        assert_eq!(
            detect_outline_bleed(None, None, i128::MAX, 2, None, 0, 0),
            Err(DIMENSIONS)
        );
        assert_eq!(
            measure_region_contrast(Some(&[0; 3]), None, 1, 1, -1),
            Err(BUFFER)
        );
        assert_eq!(
            detect_halo_artifacts(Some(&[0; 3]), Some(&[0; 3]), Some(&[1]), 1, 1, -1, 0),
            Err(RADIUS)
        );
        assert_eq!(
            compute_patch_ssim(Some(&[0]), Some(&[]), 1, 1, Some(&[0])),
            Err(BUFFER)
        );
        assert_eq!(
            detect_residual_ink(Some(&[0]), Some(&[1]), 1, 1, 0, 0, 0),
            Err(CLUSTER)
        );
        assert_eq!(
            compute_ink_bounds(Some(&[0; 3]), Some(&[0; 3]), 1, 1, 256),
            Err(CHANNEL)
        );
    }
}
