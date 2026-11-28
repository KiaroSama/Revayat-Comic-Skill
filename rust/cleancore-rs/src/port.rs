//! Cleaning kernels over tightly packed row-major buffers.
#![forbid(unsafe_code)]

const DIMENSIONS: &str = "ValueError: invalid image dimensions";
const BUFFER: &str = "ValueError: pixel buffer must be bytes and match image dimensions";
const RADIUS: &str = "ValueError: radius must be a nonnegative integer";
const ITERATIONS: &str = "ValueError: iterations must be an integer from 0 to sys.maxsize";
const CHANNEL: &str = "ValueError: fill channels must be integers from 0 to 255";
const THRESHOLD: &str =
    "ValueError: standard deviation threshold must be a finite nonnegative number";

type KernelResult<T> = Result<T, &'static str>;

#[derive(Clone, Copy)]
struct Image {
    width: usize,
    height: usize,
    len: usize,
}

impl Image {
    fn new(width: i128, height: i128) -> KernelResult<Self> {
        let width = usize::try_from(width).map_err(|_| DIMENSIONS)?;
        let height = usize::try_from(height).map_err(|_| DIMENSIONS)?;
        let len = width
            .checked_mul(height)
            .filter(|&len| (1..=isize::MAX as usize).contains(&len))
            .ok_or(DIMENSIONS)?;
        Ok(Self { width, height, len })
    }

    fn buffer(self, bytes: Option<&[u8]>, channels: usize) -> KernelResult<&[u8]> {
        bytes
            .filter(|bytes| self.len.checked_mul(channels) == Some(bytes.len()))
            .ok_or(BUFFER)
    }

    fn distances(self, mask: &[u8], interior: bool) -> Vec<usize> {
        let Self { width, height, len } = self;
        let last_x = width - 1;
        let last_y = height - 1;
        let far = width.max(height);
        let mut distance = vec![0; len];
        // The two raster passes cover all eight directions at unit cost.
        for y in 0..height {
            let row = y * width;
            for x in 0..width {
                let at = row + x;
                if (mask[at] != 0) != interior {
                    continue;
                }
                let mut nearest = if interior {
                    (x + 1).min(y + 1).min(width - x).min(height - y)
                } else {
                    far
                };
                if x > 0 {
                    nearest = nearest.min(distance[at - 1] + 1);
                }
                if y > 0 {
                    let up = at - width;
                    for &neighbor in
                        &distance[up - usize::from(x > 0)..=up + usize::from(x < last_x)]
                    {
                        nearest = nearest.min(neighbor + 1);
                    }
                }
                distance[at] = nearest;
            }
        }
        for y in (0..height).rev() {
            let row = y * width;
            for x in (0..width).rev() {
                let at = row + x;
                let mut nearest = distance[at];
                if nearest <= 1 {
                    continue;
                }
                if x < last_x {
                    nearest = nearest.min(distance[at + 1] + 1);
                }
                if y < last_y {
                    let down = at + width;
                    for &neighbor in
                        &distance[down - usize::from(x > 0)..=down + usize::from(x < last_x)]
                    {
                        nearest = nearest.min(neighbor + 1);
                    }
                }
                distance[at] = nearest;
            }
        }
        distance
    }

    fn ring(self, mask: &[u8], radius: u128) -> impl Iterator<Item = usize> {
        let radius = radius.min((self.width.max(self.height) - 1) as u128) as usize;
        let distance = if radius == 0 || !mask.iter().any(|&v| v != 0) || !mask.contains(&0) {
            Vec::new()
        } else {
            self.distances(mask, false)
        };
        distance
            .into_iter()
            .enumerate()
            .filter_map(move |(i, d)| (d > 0 && d <= radius).then_some(i * 3))
    }
}

fn median(rgb: &[u8], ring: impl Iterator<Item = usize>) -> ([u8; 3], usize) {
    let mut hist = [[0_usize; 256]; 3];
    let mut count = 0;
    for at in ring {
        for (counts, &value) in hist.iter_mut().zip(&rgb[at..at + 3]) {
            counts[usize::from(value)] += 1;
        }
        count += 1;
    }
    let mut medians = [255; 3];
    if count != 0 {
        for (counts, channel) in hist.iter().zip(&mut medians) {
            let mut rank = (count - 1) / 2;
            for (value, &frequency) in counts.iter().enumerate() {
                if frequency > rank {
                    *channel = value as u8;
                    break;
                }
                rank -= frequency;
            }
        }
    }
    (medians, count)
}

pub fn sample_ring_background(
    rgb: Option<&[u8]>,
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    ring_px: i128,
) -> KernelResult<Vec<usize>> {
    let dim = Image::new(width, height)?;
    let rgb = dim.buffer(rgb, 3)?;
    let mask = dim.buffer(mask, 1)?;
    let radius = u128::try_from(ring_px).map_err(|_| RADIUS)?;
    let ([r, g, b], count) = median(rgb, dim.ring(mask, radius));
    Ok(vec![usize::from(r), usize::from(g), usize::from(b), count])
}

pub fn compute_feather_alpha(
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    radius: i128,
) -> KernelResult<Vec<u8>> {
    let dim = Image::new(width, height)?;
    let mask = dim.buffer(mask, 1)?;
    let radius = u128::try_from(radius).map_err(|_| RADIUS)?;
    if radius == 0 {
        return Ok(mask
            .iter()
            .map(|&active| if active == 0 { 0 } else { 255 })
            .collect());
    }
    Ok(dim
        .distances(mask, true)
        .into_iter()
        .map(|d| ((d as u128 * 255 + radius / 2) / radius).min(255) as u8)
        .collect())
}

pub fn composite_masked_rgb(
    orig_rgb: Option<&[u8]>,
    fill_rgb: Option<&[u8]>,
    alpha: Option<&[u8]>,
    width: i128,
    height: i128,
) -> KernelResult<Vec<u8>> {
    let dim = Image::new(width, height)?;
    let orig = dim.buffer(orig_rgb, 3)?;
    let fill = dim.buffer(fill_rgb, 3)?;
    let alpha = dim.buffer(alpha, 1)?;
    let mut result = orig.to_vec();
    let (pixels, _) = result.as_chunks_mut::<3>();
    let (filled, _) = fill.as_chunks::<3>();
    for ((dst, src), &amount) in pixels.iter_mut().zip(filled).zip(alpha) {
        let amount = u16::from(amount);
        if amount != 0 {
            for (base, &paint) in dst.iter_mut().zip(src) {
                let value = u16::from(paint) * amount + u16::from(*base) * (255 - amount);
                *base = ((value + 127) / 255) as u8;
            }
        }
    }
    Ok(result)
}

pub fn diffuse_inpaint_rgb(
    rgb: Option<&[u8]>,
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    iterations: i128,
) -> KernelResult<Vec<u8>> {
    let dim = Image::new(width, height)?;
    let rgb = dim.buffer(rgb, 3)?;
    let mask = dim.buffer(mask, 1)?;
    let iterations = usize::try_from(iterations)
        .ok()
        .filter(|&n| n <= isize::MAX as usize)
        .ok_or(ITERATIONS)?;
    if !mask.iter().any(|&v| v != 0) {
        return Ok(rgb.to_vec());
    }
    if !mask.contains(&0) {
        return Ok(vec![255; rgb.len()]);
    }
    let (seed, _) = median(rgb, dim.ring(mask, 1));
    let mut current = flat_fill(rgb, mask, seed);
    if iterations == 0 {
        return Ok(current);
    }
    let mut paths = Vec::new();
    for (i, _) in mask.iter().enumerate().filter(|(_, value)| **value != 0) {
        let (x, y) = (i % dim.width, i / dim.width);
        paths.push([
            i * 3,
            (i - usize::from(x > 0)) * 3,
            (i + usize::from(x + 1 < dim.width)) * 3,
            (i - dim.width * usize::from(y > 0)) * 3,
            (i + dim.width * usize::from(y + 1 < dim.height)) * 3,
        ]);
    }
    let mut following = current.clone();
    for step in 0..iterations {
        let (mut changed, mut repeats) = (false, false);
        for &[at, left, right, up, down] in &paths {
            for c in 0..3 {
                let sum = u16::from(current[left + c])
                    + u16::from(current[right + c])
                    + u16::from(current[up + c])
                    + u16::from(current[down + c]);
                let value = ((sum + 2) / 4) as u8;
                changed |= value != current[at + c];
                repeats |= value != following[at + c];
                following[at + c] = value;
            }
        }
        std::mem::swap(&mut current, &mut following);
        if !changed {
            break;
        }
        if !repeats {
            // A period-two cycle can fast-forward without changing Jacobi results.
            return Ok(if (iterations - step - 1) % 2 == 0 {
                current
            } else {
                following
            });
        }
    }
    Ok(current)
}

pub fn inpaint_textured_ring_rgb(
    rgb: Option<&[u8]>,
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
) -> KernelResult<Vec<u8>> {
    let dim = Image::new(width, height)?;
    let rgb = dim.buffer(rgb, 3)?;
    let mask = dim.buffer(mask, 1)?;
    if mask.iter().all(|&v| v == 0) {
        return Ok(rgb.to_vec());
    }
    if !mask.contains(&0) {
        return Ok(vec![255; rgb.len()]);
    }
    let distances = dim.distances(mask, false);
    let inner = if distances.iter().any(|d| (3..=14).contains(d)) {
        3
    } else {
        1
    };
    let ring: Vec<_> = distances.iter().map(|d| (inner..=14).contains(d)).collect();
    let [px, py] = [(dim.width, 1), (dim.height, dim.width)].map(|(length, stride)| {
        let sad = |lag: usize| {
            if lag >= length {
                return f64::INFINITY;
            }
            let (mut sum, mut count) = (0.0, 0);
            for (i, &sample) in ring.iter().enumerate() {
                if sample && i / stride % length < length - lag && ring[i + lag * stride] {
                    let j = (i + lag * stride) * 3;
                    for (&a, &b) in rgb[i * 3..][..3].iter().zip(&rgb[j..][..3]) {
                        sum += f64::from(a.abs_diff(b));
                    }
                    count += 1;
                }
            }
            if count < 4 {
                f64::INFINITY
            } else {
                sum / f64::from(count)
            }
        };
        let adjacent = sad(1);
        if !adjacent.is_finite() || adjacent == 0.0 {
            return 1;
        }
        let (mut period, mut best) = (1, adjacent * 0.65);
        for lag in 2..=12 {
            let error = sad(lag);
            if error < best {
                (period, best) = (lag, error);
            }
        }
        period
    });
    let sources = nearest_ring_samples(dim, &ring, px, py);
    let fallback = sources
        .iter()
        .zip(mask)
        .any(|(&i, &active)| i == dim.len && active != 0)
        .then(|| nearest_ring_samples(dim, &ring, 1, 1));
    let mut result = rgb.to_vec();
    for (i, &source) in sources.iter().enumerate() {
        if mask[i] == 0 {
            continue;
        }
        let j = fallback
            .as_ref()
            .filter(|_| source == dim.len)
            .map_or(source, |v| v[i]);
        result[i * 3..][..3].copy_from_slice(&rgb[j * 3..][..3]);
    }
    Ok(result)
}

fn nearest_ring_samples(dim: Image, ring: &[bool], px: usize, py: usize) -> Vec<usize> {
    let mut sources: Vec<_> = ring
        .iter()
        .enumerate()
        .map(|(i, &sample)| if sample { i } else { dim.len })
        .collect();
    let distance = |a: usize, b: usize| {
        a.div_euclid(dim.width).abs_diff(b / dim.width) + (a % dim.width).abs_diff(b % dim.width)
    };
    // Separable Manhattan nearest-neighbor search on each period's phase lattice.
    let prefer = |sources: &mut [usize], at: usize, neighbor: usize| {
        let (a, b) = (sources[at], sources[neighbor]);
        if b != dim.len && (a == dim.len || distance(at, b) < distance(at, a)) {
            sources[at] = b;
        }
    };
    for (step, stride, length) in [(px, 1, dim.width), (py, dim.width, dim.height)] {
        for at in 0..dim.len {
            if at / stride % length >= step {
                prefer(&mut sources, at, at - step * stride);
            }
        }
        for at in (0..dim.len).rev() {
            if at / stride % length < length.saturating_sub(step) {
                prefer(&mut sources, at, at + step * stride);
            }
        }
    }
    sources
}

pub fn detect_textured_ring(
    rgb: Option<&[u8]>,
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    ring_px: i128,
    std_thresh: f64,
) -> KernelResult<Vec<f64>> {
    let dim = Image::new(width, height)?;
    let rgb = dim.buffer(rgb, 3)?;
    let mask = dim.buffer(mask, 1)?;
    let radius = u128::try_from(ring_px).map_err(|_| RADIUS)?;
    if !std_thresh.is_finite() || std_thresh < 0.0 {
        return Err(THRESHOLD);
    }
    let (mut low, mut high) = ([255; 3], [0; 3]);
    let (mut count, mut mean, mut squared) = (0_usize, 0.0, 0.0);
    for at in dim.ring(mask, radius) {
        let pixel = &rgb[at..at + 3];
        let luma =
            299 * u32::from(pixel[0]) + 587 * u32::from(pixel[1]) + 114 * u32::from(pixel[2]);
        count += 1;
        let delta = f64::from(luma) - mean;
        mean += delta / count as f64;
        squared += delta * (f64::from(luma) - mean);
        for (channel, &value) in pixel.iter().enumerate() {
            low[channel] = low[channel].min(value);
            high[channel] = high[channel].max(value);
        }
    }
    if count == 0 {
        return Ok(vec![0.0; 4]);
    }
    let deviation = (squared / count as f64).sqrt() / 1000.0;
    let span = (high[0] - low[0])
        .max(high[1] - low[1])
        .max(high[2] - low[2]);
    Ok(vec![
        if deviation > std_thresh { 1.0 } else { 0.0 },
        deviation,
        f64::from(span),
        count as f64,
    ])
}

fn flat_fill(rgb: &[u8], mask: &[u8], fill: [u8; 3]) -> Vec<u8> {
    let mut result = rgb.to_vec();
    let (pixels, _) = result.as_chunks_mut::<3>();
    for (pixel, &active) in pixels.iter_mut().zip(mask) {
        if active != 0 {
            pixel.copy_from_slice(&fill);
        }
    }
    result
}

pub fn fill_flat_rgb(
    orig_rgb: Option<&[u8]>,
    mask: Option<&[u8]>,
    width: i128,
    height: i128,
    r: i128,
    g: i128,
    b: i128,
) -> KernelResult<Vec<u8>> {
    let dim = Image::new(width, height)?;
    let rgb = dim.buffer(orig_rgb, 3)?;
    let mask = dim.buffer(mask, 1)?;
    let channel = |value| u8::try_from(value).map_err(|_| CHANNEL);
    Ok(flat_fill(
        rgb,
        mask,
        [channel(r)?, channel(g)?, channel(b)?],
    ))
}

#[cfg(test)]
mod tests {
    #[test]
    fn textured_fill_keeps_dot_phase_without_copying_the_white_halo() {
        let (w, h) = (48, 48);
        let dot = |x, y| if x % 5 < 2 && y % 7 < 3 { 98 } else { 206 };
        let mut rgb = Vec::new();
        let mut mask = Vec::new();
        for y in 0..h {
            for x in 0..w {
                let active = (17..31).contains(&x) && (17..31).contains(&y);
                let halo = (15..33).contains(&x) && (15..33).contains(&y);
                rgb.extend(
                    [if active {
                        0
                    } else if halo {
                        255
                    } else {
                        dot(x, y)
                    }; 3],
                );
                mask.push(u8::from(active));
            }
        }
        let filled = inpaint_textured_ring_rgb(Some(&rgb), Some(&mask), w, h).unwrap();
        for (i, pixel) in filled.as_chunks::<3>().0.iter().enumerate() {
            let i = i as i128;
            if mask[i as usize] != 0 {
                assert_eq!(*pixel, [dot(i % w, i / w); 3]);
            } else {
                assert_eq!(*pixel, rgb[i as usize * 3..][..3]);
            }
        }
    }

    use super::*;

    #[test]
    fn transforms_match_brute_force_on_every_three_by_three_mask() -> KernelResult<()> {
        let dim = Image::new(3, 3)?;
        for bits in 0..512 {
            let mask: Vec<_> = (0..9)
                .map(|p| if bits & (1 << p) == 0 { 0 } else { 128 })
                .collect();
            for interior in [false, true] {
                let distance = dim.distances(&mask, interior);
                for (i, actual) in distance.into_iter().enumerate() {
                    let (x, y) = (i % 3, i / 3);
                    let border = if interior {
                        (x + 1).min(y + 1).min(3 - x).min(3 - y)
                    } else {
                        3
                    };
                    let expected = (0_usize..9)
                        .filter(|&j| (mask[j] != 0) != interior)
                        .map(|j| x.abs_diff(j % 3).max(y.abs_diff(j / 3)))
                        .fold(border, usize::min);
                    assert_eq!(
                        actual, expected,
                        "mask {bits}, interior {interior}, pixel {i}"
                    );
                }
            }
        }
        Ok(())
    }

    #[test]
    fn ring_medians_do_not_average_even_sample_counts() {
        let rgb = [7, 13, 99, 1, 1, 1, 99, 7, 13];
        assert_eq!(
            sample_ring_background(Some(&rgb), Some(&[0, 37, 0]), 3, 1, 1),
            Ok(vec![7, 7, 13, 2])
        );
        assert_eq!(
            sample_ring_background(Some(&rgb), Some(&[0, 37, 0]), 3, 1, 0),
            Ok(vec![255, 255, 255, 0])
        );
    }

    #[test]
    fn feather_rounds_and_never_crosses_the_mask() {
        let mask = [0, 128, 1];
        assert_eq!(
            compute_feather_alpha(Some(&mask), 1, 3, 2),
            Ok(vec![0, 128, 128])
        );
        assert_eq!(
            compute_feather_alpha(Some(&mask), 1, 3, i128::MAX),
            Ok(vec![0; 3])
        );
        assert_eq!(
            compute_feather_alpha(Some(&mask), 1, 3, 0),
            Ok(vec![0, 255, 255])
        );
    }

    #[test]
    fn composite_and_flat_fill_preserve_inactive_bytes() {
        let old = [2, 33, 250, 0, 255, 0];
        let new = [254, 255, 1, 255, 0, 255];
        assert_eq!(
            composite_masked_rgb(Some(&old), Some(&new), Some(&[0, 128]), 2, 1),
            Ok(vec![2, 33, 250, 128, 127, 128])
        );
        assert_eq!(
            fill_flat_rgb(Some(&old), Some(&[0, 2]), 2, 1, 255, 0, 37),
            Ok(vec![2, 33, 250, 255, 0, 37])
        );
    }

    #[test]
    fn jacobi_reads_the_previous_pass_and_keeps_original_neighbors() {
        let gray = |values: [u8; 4]| values.into_iter().flat_map(|v| [v; 3]).collect::<Vec<_>>();
        let old = gray([0, 100, 100, 200]);
        let mask = [0, 1, 128, 0];
        for (passes, expected) in [
            (0, [0, 0, 0, 200]),
            (1, [0, 0, 50, 200]),
            (2, [0, 13, 75, 200]),
        ] {
            assert_eq!(
                diffuse_inpaint_rgb(Some(&old), Some(&mask), 4, 1, passes),
                Ok(gray(expected))
            );
        }
        assert_eq!(
            diffuse_inpaint_rgb(Some(&old), Some(&[128; 4]), 4, 1, 30),
            Ok(vec![255; 12])
        );
    }

    #[test]
    fn texture_measures_population_luma_and_retains_single_channel_span() {
        let rgb = [6, 6, 6, 99, 99, 99, 14, 14, 14];
        let mask = [0, 1, 0];
        assert_eq!(
            detect_textured_ring(Some(&rgb), Some(&mask), 3, 1, 1, 4.0),
            Ok(vec![0.0, 4.0, 8.0, 2.0])
        );
        assert_eq!(
            detect_textured_ring(Some(&rgb), Some(&mask), 3, 1, 1, 3.0),
            Ok(vec![1.0, 4.0, 8.0, 2.0])
        );
    }

    #[test]
    fn invalid_arguments_return_errors_before_processing() {
        assert_eq!(
            compute_feather_alpha(Some(&[]), isize::MAX as i128, 2, 1),
            Err(DIMENSIONS)
        );
        assert_eq!(compute_feather_alpha(None, 1, 1, 1), Err(BUFFER));
        assert_eq!(compute_feather_alpha(Some(&[1]), 1, 1, -1), Err(RADIUS));
        assert_eq!(
            diffuse_inpaint_rgb(Some(&[0; 3]), Some(&[1]), 1, 1, -1),
            Err(ITERATIONS)
        );
        assert_eq!(
            detect_textured_ring(Some(&[0; 3]), Some(&[1]), 1, 1, 1, f64::NAN),
            Err(THRESHOLD)
        );
        assert_eq!(
            fill_flat_rgb(Some(&[0; 3]), Some(&[1]), 1, 1, 256, 0, 0),
            Err(CHANNEL)
        );
    }
}
