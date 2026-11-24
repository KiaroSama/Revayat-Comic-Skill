//! Balloon mask kernels. The Python oracle is `maskcore/kernels.py`.
#![forbid(unsafe_code)]

use std::collections::VecDeque;

const DIMENSIONS: &str = "ValueError: invalid image dimensions";
const BUFFER: &str = "ValueError: pixel buffer must be bytes and match image dimensions";
const SEED: &str = "ValueError: seed is outside the image";
const WALL: &str = "ValueError: wall_luma must be between 0 and 255";
const GRADIENT: &str = "ValueError: grad_thresh must be between 0 and 256";
const INSET: &str = "ValueError: min_inset must be non-negative";
const RADIUS: &str = "ValueError: radius must be non-negative";
const BINARY: &str = "ValueError: mask must be binary (0 or 255)";
const ORIGIN: &str = "ValueError: union origin must use signed 64-bit coordinates";
pub const BOXES: &str = "ValueError: boxes must be a non-empty list";
pub const BOX: &str =
    "ValueError: box must contain four signed 64-bit integers with positive width and height";
const SEAM: &str = "ValueError: seam_margin must be non-negative";
const AREA: &str = "ValueError: min_area_ratio must be between 0 and 1";
const SPAN: &str = "ValueError: min_span_ratio must be between 0 and 1";

#[derive(Clone, Copy)]
struct Grid {
    width: usize,
    height: usize,
}

impl Grid {
    fn checked(data: Option<&[u8]>, width: i128, height: i128) -> Result<(Self, &[u8]), String> {
        let width = usize::try_from(width).map_err(|_| DIMENSIONS)?;
        let height = usize::try_from(height).map_err(|_| DIMENSIONS)?;
        let size = width
            .checked_mul(height)
            .filter(|&n| n > 0 && n <= isize::MAX as usize)
            .ok_or(DIMENSIONS)?;
        let data = data.filter(|d| d.len() == size).ok_or(BUFFER)?;
        Ok((Self { width, height }, data))
    }

    fn cardinal(self, p: usize) -> impl Iterator<Item = usize> {
        let x = p % self.width;
        let y = p / self.width;
        [
            (x > 0).then(|| p - 1),
            (x + 1 < self.width).then(|| p + 1),
            (y > 0).then(|| p - self.width),
            (y + 1 < self.height).then(|| p + self.width),
        ]
        .into_iter()
        .flatten()
    }

    fn square(self, p: usize) -> impl Iterator<Item = usize> {
        let x = p % self.width;
        let y = p / self.width;
        let left = x.saturating_sub(1);
        let right = (x + 1).min(self.width - 1);
        let top = y.saturating_sub(1);
        let bottom = (y + 1).min(self.height - 1);
        (top..=bottom).flat_map(move |row| {
            let start = row * self.width;
            start + left..=start + right
        })
    }
}

fn nonnegative(value: i128, error: &str) -> Result<usize, String> {
    if value < 0 {
        return Err(error.into());
    }
    Ok(value.min(usize::MAX as i128) as usize)
}

fn scan_lines(
    input: &[u8],
    length: usize,
    step: usize,
    stride: usize,
    radius: usize,
    decisive: u8,
) -> Vec<u8> {
    let mut out = vec![0; input.len()];
    let other = 255 - decisive;
    for line in 0..input.len() / length {
        let start = line * stride;
        let mut cursor = 0;
        let mut last = None;
        for center in 0..length {
            let end = center.saturating_add(radius).min(length - 1);
            // A binary window is decided by its most recent decisive pixel, if still in range.
            while cursor <= end {
                if input[start + cursor * step] == decisive {
                    last = Some(cursor);
                }
                cursor += 1;
            }
            out[start + center * step] = if last.is_some_and(|p| p >= center.saturating_sub(radius))
            {
                decisive
            } else {
                other
            };
        }
    }
    out
}

fn morph(mask: &[u8], grid: Grid, radius: usize, decisive: u8) -> Vec<u8> {
    if radius == 0 {
        return mask.to_vec();
    }
    let rows = scan_lines(mask, grid.width, 1, grid.width, radius, decisive);
    scan_lines(&rows, grid.height, grid.width, 1, radius, decisive)
}

fn checked_morph(
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    radius: i128,
    decisive: u8,
) -> Result<Vec<u8>, String> {
    let (grid, mask) = Grid::checked(mask, width, height)?;
    let radius = nonnegative(radius, RADIUS)?;
    if mask.iter().any(|&p| p != 0 && p != 255) {
        return Err(BINARY.into());
    }
    Ok(morph(mask, grid, radius, decisive))
}

pub fn erode_linf(
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    radius: i128,
) -> Result<Vec<u8>, String> {
    checked_morph(mask, width, height, radius, 0)
}

pub fn dilate_linf(
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    radius: i128,
) -> Result<Vec<u8>, String> {
    checked_morph(mask, width, height, radius, 255)
}

#[expect(
    clippy::too_many_arguments,
    reason = "The bridge preserves the reference signature"
)]
pub fn flood_balloon_interior(
    gray: Option<&[u8]>,
    width: i128,
    height: i128,
    seed_x: i128,
    seed_y: i128,
    wall_luma: i128,
    grad_thresh: i128,
    min_inset: i128,
) -> Result<Vec<u8>, String> {
    let (grid, gray) = Grid::checked(gray, width, height)?;
    let x = usize::try_from(seed_x).map_err(|_| SEED)?;
    let y = usize::try_from(seed_y).map_err(|_| SEED)?;
    if x >= grid.width || y >= grid.height {
        return Err(SEED.into());
    }
    let wall = u8::try_from(wall_luma).map_err(|_| WALL)?;
    if !(0..=256).contains(&grad_thresh) {
        return Err(GRADIENT.into());
    }
    let threshold = grad_thresh as u16;
    let inset = nonnegative(min_inset, INSET)?;
    let seed = y * grid.width + x;
    let mut mask = vec![0; gray.len()];
    if threshold == 0 || gray[seed] < wall {
        return Ok(mask);
    }
    let mut seen = vec![false; gray.len()];
    seen[seed] = true;
    let mut queue = VecDeque::from([seed]);
    while let Some(p) = queue.pop_front() {
        let luma = gray[p];
        if luma < wall
            || grid
                .cardinal(p)
                .any(|n| u16::from(luma.abs_diff(gray[n])) >= threshold)
        {
            continue;
        }
        mask[p] = 255;
        for n in grid.cardinal(p) {
            if !seen[n] {
                seen[n] = true;
                queue.push_back(n);
            }
        }
    }
    Ok(if inset == 0 {
        mask
    } else {
        morph(&mask, grid, inset, 0)
    })
}

/// Signed coordinates fit i128, but their squared distances can exceed u128.
/// Keep the high word so distant boxes still compare exactly instead of tying at saturation.
fn square_distance_word(value: i128) -> (u128, u128) {
    let value = value.unsigned_abs();
    let high = value >> 64;
    let low = u128::from(value as u64);
    let cross = 2 * high * low;
    let (word, carry) = (low * low).overflowing_add(cross << 64);
    (high * high + (cross >> 64) + u128::from(carry), word)
}

fn distance_squared(x: i128, y: i128) -> (u128, u128) {
    let (xh, xl) = square_distance_word(x);
    let (yh, yl) = square_distance_word(y);
    let (low, carry) = xl.overflowing_add(yl);
    (xh + yh + u128::from(carry), low)
}

fn trim_seams(owners: &mut [i64], grid: Grid, margin: usize) {
    let mut queue = VecDeque::new();
    for (p, &owner) in owners.iter().enumerate() {
        if owner >= 0
            && grid
                .cardinal(p)
                .any(|n| owners[n] >= 0 && owners[n] != owner)
        {
            queue.push_back((p, 1));
        }
    }
    for &(p, _) in &queue {
        owners[p] = -1;
    }
    while let Some((p, distance)) = queue.pop_front() {
        if distance < margin {
            for n in grid.cardinal(p) {
                if owners[n] >= 0 {
                    owners[n] = -1;
                    queue.push_back((n, distance + 1));
                }
            }
        }
    }
}

pub fn partition_voronoi_lobes(
    union_mask: Option<&[u8]>,
    width: i128,
    height: i128,
    ux0: i128,
    uy0: i128,
    boxes: Result<Vec<[i64; 4]>, &'static str>,
    seam_margin: i128,
) -> Result<Vec<i64>, String> {
    let (grid, mask) = Grid::checked(union_mask, width, height)?;
    i64::try_from(ux0)
        .and_then(|_| i64::try_from(uy0))
        .map_err(|_| ORIGIN)?;
    let margin = nonnegative(seam_margin, SEAM)?;
    let boxes = boxes?;
    if boxes.is_empty() {
        return Err(BOXES.into());
    }
    let mut bounds = Vec::with_capacity(boxes.len());
    for b in boxes {
        let [x, y, w, h] = b.map(i128::from);
        if w <= 0 || h <= 0 {
            return Err(BOX.into());
        }
        bounds.push((x, y, x + w - 1, y + h - 1, 2 * x + w, 2 * y + h));
    }
    let mut owners = vec![-1; mask.len()];
    for (p, &active) in mask.iter().enumerate() {
        if active == 0 {
            continue;
        }
        let x = ux0 + (p % grid.width) as i128;
        let y = uy0 + (p / grid.width) as i128;
        let mut best = None;
        for (owner, &(left, top, right, bottom, cx2, cy2)) in bounds.iter().enumerate() {
            let dx = (left - x).max(x - right).max(0);
            let dy = (top - y).max(y - bottom).max(0);
            let score = (
                distance_squared(dx, dy),
                distance_squared(2 * x - cx2, 2 * y - cy2),
            );
            if best.is_none_or(|prior| score < prior) {
                best = Some(score);
                owners[p] = owner as i64;
            }
        }
    }
    if margin > 0 && bounds.len() > 1 {
        trim_seams(&mut owners, grid, margin);
    }
    Ok(owners)
}

pub fn strip_perimeter_contours(
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    min_area_ratio: f64,
    min_span_ratio: f64,
) -> Result<(Vec<u8>, Vec<u8>), String> {
    let (grid, mask) = Grid::checked(mask, width, height)?;
    if !(0.0..=1.0).contains(&min_area_ratio) {
        return Err(AREA.into());
    }
    if !(0.0..=1.0).contains(&min_span_ratio) {
        return Err(SPAN.into());
    }
    let mut unseen = mask.to_vec();
    let mut kept = vec![0; mask.len()];
    let mut stripped = vec![0; mask.len()];
    let area_floor = min_area_ratio * mask.len() as f64;
    let span_x = min_span_ratio * grid.width as f64;
    let span_y = min_span_ratio * grid.height as f64;
    let mut component = Vec::new();
    for seed in 0..mask.len() {
        if unseen[seed] == 0 {
            continue;
        }
        unseen[seed] = 0;
        component.clear();
        component.push(seed);
        let mut left = seed % grid.width;
        let mut right = left;
        let mut top = seed / grid.width;
        let mut bottom = top;
        let mut i = 0;
        while let Some(&p) = component.get(i) {
            i += 1;
            let x = p % grid.width;
            let y = p / grid.width;
            left = left.min(x);
            right = right.max(x);
            top = top.min(y);
            bottom = bottom.max(y);
            for n in grid.square(p) {
                if unseen[n] != 0 {
                    unseen[n] = 0;
                    component.push(n);
                }
            }
        }
        let border = left == 0 || right == grid.width - 1 || top == 0 || bottom == grid.height - 1;
        let span = (right - left + 1) as f64 >= span_x || (bottom - top + 1) as f64 >= span_y;
        let dest = if border && span && component.len() as f64 >= area_floor {
            &mut stripped
        } else {
            &mut kept
        };
        for &p in &component {
            dest[p] = 255;
        }
    }
    Ok((kept, stripped))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gray_wall_blocks_a_threshold_equality() {
        let gray = [250, 250, 235, 250, 250];
        assert_eq!(
            flood_balloon_interior(Some(&gray), 5, 1, 0, 0, 230, 15, 0),
            Ok(vec![255, 0, 0, 0, 0])
        );
        assert_eq!(
            flood_balloon_interior(Some(&gray), 5, 1, 0, 0, 230, 16, 0),
            Ok(vec![255; 5])
        );
    }

    #[test]
    fn blocked_seed_and_diagonal_do_not_flood() {
        let gray = [255, 0, 0, 255];
        assert_eq!(
            flood_balloon_interior(Some(&gray), 2, 2, 0, 0, 230, 256, 0),
            Ok(vec![255, 0, 0, 0])
        );
        assert_eq!(
            flood_balloon_interior(Some(&gray), 2, 2, 1, 0, 230, 256, 0),
            Ok(vec![0; 4])
        );
    }

    #[test]
    fn square_morphology_does_not_pad_with_background() {
        let solid = [255; 6];
        let hole = [255, 255, 255, 0, 255, 255];
        assert_eq!(
            erode_linf(Some(&solid), 3, 2, i128::MAX),
            Ok(solid.to_vec())
        );
        assert_eq!(
            erode_linf(Some(&hole), 3, 2, 1),
            Ok(vec![0, 0, 255, 0, 0, 255])
        );
        assert_eq!(
            dilate_linf(Some(&[255, 0, 0, 0, 0, 0]), 3, 2, 1),
            Ok(vec![255, 255, 0, 255, 255, 0])
        );
    }

    #[test]
    fn validation_orders_dimensions_then_buffer_then_kernel_arguments() {
        assert_eq!(erode_linf(None, i128::MAX, 1, -1), Err(DIMENSIONS.into()));
        assert_eq!(erode_linf(None, 1, 1, -1), Err(BUFFER.into()));
        assert_eq!(erode_linf(Some(&[1]), 1, 1, -1), Err(RADIUS.into()));
        assert_eq!(erode_linf(Some(&[1]), 1, 1, 0), Err(BINARY.into()));
        assert_eq!(
            strip_perimeter_contours(Some(&[1]), 1, 1, f64::NAN, 2.0),
            Err(AREA.into())
        );
    }

    #[test]
    fn distance_retains_carries_past_u128() {
        let limb = 1i128 << 64;
        assert_eq!(
            distance_squared(limb - 1, limb - 1),
            (1, u128::MAX - (1u128 << 66) + 3)
        );
        assert_eq!(distance_squared(limb + 1, limb + 2), (2, (6u128 << 64) + 5));
        let hi = i64::MAX;
        let lo = i128::from(i64::MIN);
        let boxes = vec![[hi, hi, hi, hi], [hi, hi, hi - 1, hi]];
        assert_eq!(
            partition_voronoi_lobes(Some(&[255]), 1, 1, lo, lo, Ok(boxes), 0),
            Ok(vec![1])
        );
    }

    #[test]
    fn seam_does_not_cross_background() {
        let boxes = || Ok(vec![[0, 0, 1, 1], [6, 0, 1, 1]]);
        assert_eq!(
            partition_voronoi_lobes(Some(&[255; 7]), 7, 1, 0, 0, boxes(), 1),
            Ok(vec![0, 0, 0, -1, -1, 1, 1])
        );
        let mask = [255, 255, 255, 0, 255, 255, 255];
        assert_eq!(
            partition_voronoi_lobes(Some(&mask), 7, 1, 0, 0, boxes(), 7),
            Ok(vec![0, 0, 0, -1, 1, 1, 1])
        );
    }

    #[test]
    fn contour_area_and_span_both_include_equality() {
        let mask = [1, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 7, 0];
        let kept = vec![0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0];
        let stripped = vec![255, 0, 0, 0, 0, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
        assert_eq!(
            strip_perimeter_contours(Some(&mask), 4, 4, 0.125, 0.5),
            Ok((kept, stripped))
        );
    }
}
