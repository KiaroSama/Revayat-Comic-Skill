//! Archive order, page geometry and raster kernels.
#![forbid(unsafe_code)]

pub(crate) const NAMES_ERROR: &str = "names must be a list of strings";
pub(crate) const ROW_ERROR: &str = "dims must be a list of two-element lists";
pub(crate) const BOUNDS_ERROR: &str =
    "dimension bounds must have a finite aspect ratio >= 1 and positive integer edges and area";
pub(crate) const RGB_DIMENSIONS_ERROR: &str = "width and height must be positive integers";
const RGB_BUFFER_ERROR: &str = "RGB buffer must contain exactly width * height * 3 bytes";
pub(crate) const PDF_DIMENSIONS_ERROR: &str = "page dimensions must be positive integers";
pub(crate) const TILE_ERROR: &str = "tile_size must be a positive integer";
pub(crate) const TOL_ERROR: &str = "tol must be an integer between 0 and 255";

#[derive(Ord, PartialOrd, Eq, PartialEq)]
enum Run {
    Text(Vec<u8>),
    Number(usize, Vec<u8>),
}

fn digit(bytes: &[u8]) -> Option<(u8, usize)> {
    match bytes {
        [d @ b'0'..=b'9', ..] => Some((*d, 1)),
        [0xdb, d @ 0xb0..=0xb9, ..] => Some((b'0' + d - 0xb0, 2)),
        [0xd9, d @ 0xa0..=0xa9, ..] => Some((b'0' + d - 0xa0, 2)),
        _ => None,
    }
}

fn sort_key(mut bytes: &[u8]) -> Vec<Run> {
    let mut key = Vec::new();
    let mut text = Vec::new();
    while let Some((&first, rest)) = bytes.split_first() {
        if digit(bytes).is_none() {
            text.push(first.to_ascii_lowercase());
            bytes = rest;
            continue;
        }
        key.push(Run::Text(std::mem::take(&mut text)));
        let mut number = Vec::new();
        while let Some((d, size)) = digit(bytes) {
            if d != b'0' || !number.is_empty() {
                number.push(d);
            }
            bytes = &bytes[size..];
        }
        // Compare significant digit count, then digits, without ever parsing a machine integer.
        key.push(Run::Number(number.len(), number));
    }
    key.push(Run::Text(text));
    key
}

pub(crate) fn natural_sort_order(names: Vec<Vec<u8>>) -> Vec<usize> {
    let mut keys: Vec<_> = names
        .into_iter()
        .enumerate()
        .map(|(i, name)| (sort_key(&name), name, i))
        .collect();
    keys.sort_unstable();
    keys.into_iter().map(|(_, _, i)| i).collect()
}

pub(crate) fn validate_page_dimensions(
    w: i128,
    h: i128,
    ratio: f64,
    edge: i128,
    area: i128,
) -> Option<bool> {
    let (short, long) = (w.min(h), w.max(h));
    if short < edge || long.checked_mul(short).is_none_or(|n| n > area) {
        return Some(false);
    }
    // For larger operands, integer-to-float rounding before division can change the answer.
    (long <= 1_i128 << f64::MANTISSA_DIGITS).then(|| long as f64 / short as f64 <= ratio)
}

pub(crate) fn compute_pdf_page_layout(
    w: f64,
    h: f64,
    dpi: f64,
    limit: f64,
) -> Result<[f64; 4], &'static str> {
    let positive_finite = |x: f64| x.is_finite() && x > 0.0;
    if ![w, h, dpi, limit].into_iter().all(positive_finite) {
        return Err("page dimensions, DPI and point limit must be finite and positive");
    }
    let (pt_w, pt_h) = (72.0 * w / dpi, 72.0 * h / dpi);
    if ![pt_w, pt_h].into_iter().all(positive_finite) {
        return Err("PDF page dimensions are out of range");
    }
    let scale = (limit / pt_w.max(pt_h)).min(1.0);
    let layout = [
        (pt_w * scale).min(limit),
        (pt_h * scale).min(limit),
        dpi / scale,
        scale,
    ];
    if !layout.into_iter().all(positive_finite) {
        return Err("scaled PDF layout is out of range");
    }
    Ok(layout)
}

pub(crate) fn check_rgb(
    rgb: Option<&[u8]>,
    width: usize,
    height: usize,
) -> Result<&[u8], &'static str> {
    let expected = width.checked_mul(height).and_then(|n| n.checked_mul(3));
    rgb.filter(|rgb| Some(rgb.len()) == expected)
        .ok_or(RGB_BUFFER_ERROR)
}

#[inline]
fn luma(r: u8, g: u8, b: u8) -> u8 {
    ((77 * u16::from(r) + 150 * u16::from(g) + 29 * u16::from(b)) >> 8) as u8
}

pub(crate) fn analyze_rgb_page(rgb: &[u8]) -> [u64; 5] {
    let mut digest = 2_166_136_261_u32;
    let (mut min, mut max, mut sum, mut nonwhite) = (255, 0, 0_u64, 0_u64);
    for &[r, g, b] in rgb.as_chunks::<3>().0 {
        digest = (digest ^ u32::from(r)).wrapping_mul(16_777_619);
        digest = (digest ^ u32::from(g)).wrapping_mul(16_777_619);
        digest = (digest ^ u32::from(b)).wrapping_mul(16_777_619);
        let level = luma(r, g, b);
        min = min.min(level);
        max = max.max(level);
        sum += u64::from(level);
        nonwhite += u64::from(level < 245);
    }
    // A real slice cannot approach the u64 sum bound; widen the final product too.
    let mean = (u128::from(sum) * 100 / (rgb.len() / 3) as u128) as u64;
    [
        u64::from(digest),
        u64::from(min),
        u64::from(max),
        mean,
        nonwhite,
    ]
}

pub(crate) fn diff_raster_tiles(
    orig: &[u8],
    final_rgb: &[u8],
    width: usize,
    height: usize,
    tile: usize,
    tol: u8,
) -> Vec<[usize; 4]> {
    if tol == 255 || orig == final_rgb {
        return Vec::new();
    }
    let tile = tile.min(width.max(height));
    let mut changed = Vec::new();
    for (ty, y) in (0..height).step_by(tile).enumerate() {
        for (tx, x) in (0..width).step_by(tile).enumerate() {
            let (mut count, mut largest) = (0, 0);
            for row in y..(y + tile).min(height) {
                let start = 3 * (row * width + x);
                let end = 3 * (row * width + (x + tile).min(width));
                for (a, b) in orig[start..end]
                    .as_chunks::<3>()
                    .0
                    .iter()
                    .zip(final_rgb[start..end].as_chunks::<3>().0)
                {
                    let delta = a[0]
                        .abs_diff(b[0])
                        .max(a[1].abs_diff(b[1]))
                        .max(a[2].abs_diff(b[2]));
                    if delta > tol {
                        count += 1;
                        largest = largest.max(delta);
                    }
                }
            }
            if count > 0 {
                changed.push([tx, ty, count, usize::from(largest)]);
            }
        }
    }
    changed
}

pub(crate) fn compute_grayscale_histogram(rgb: &[u8]) -> [usize; 256] {
    let mut histogram = [0; 256];
    for &[r, g, b] in rgb.as_chunks::<3>().0 {
        histogram[usize::from(luma(r, g, b))] += 1;
    }
    histogram
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filename_keys_compare_arbitrary_precision_and_spelling() {
        let giant = "9".repeat(4500);
        let names = [
            "p٣".to_owned(),
            "p۳".to_owned(),
            "P03".to_owned(),
            "p٣".to_owned(),
            format!("p1{}", "0".repeat(4500)),
            format!("p{giant}"),
        ];
        assert_eq!(
            natural_sort_order(names.map(String::into_bytes).to_vec()),
            [2, 0, 3, 1, 5, 4]
        );
    }

    #[test]
    fn filename_order_keeps_case_and_non_decimal_characters_outside_the_key_rules() {
        let names = ["É2", "é1", "a²", "a9", "A09", "a", "a۰", "a0009"];
        assert_eq!(
            natural_sort_order(names.map(|s| s.as_bytes().to_vec()).to_vec()),
            [5, 6, 4, 7, 3, 2, 0, 1]
        );
    }

    #[test]
    fn dimensions_check_area_and_aspect_in_either_orientation() {
        assert_eq!(validate_page_dimensions(6, 8, 1.5, 6, 48), Some(true));
        assert_eq!(validate_page_dimensions(8, 6, 1.5, 6, 47), Some(false));
        assert_eq!(validate_page_dimensions(8, 5, 1.5, 6, 48), Some(false));
        assert_eq!(validate_page_dimensions(7, 5, 1.25, 5, 48), Some(false));
    }

    #[test]
    fn dimensions_never_wrap_and_defer_rounding_if_cast_would_lose_precision() {
        assert_eq!(
            validate_page_dimensions(1 << 63, 1 << 64, 2.0, 1, i128::MAX),
            Some(false)
        );
        assert_eq!(
            validate_page_dimensions(1 << 63, 1 << 63, 1.0, 1, 1 << 126),
            None
        );
    }

    #[test]
    fn layout_cap_scales_both_axes_and_increases_dpi() {
        assert_eq!(
            compute_pdf_page_layout(800.0, 1200.0, 288.0, 150.0),
            Ok([100.0, 150.0, 576.0, 0.5])
        );
        assert_eq!(
            compute_pdf_page_layout(800.0, 1200.0, 288.0, 300.0),
            Ok([200.0, 300.0, 288.0, 1.0])
        );
    }

    #[test]
    fn layout_rejects_nonfinite_intermediate_or_output() {
        assert!(compute_pdf_page_layout(f64::MAX, 1.0, 72.0, 500.0).is_err());
        assert!(compute_pdf_page_layout(1.0, 1.0, f64::MIN_POSITIVE, 1.0).is_err());
        assert!(compute_pdf_page_layout(1.0, 1.0, 300.0, f64::from_bits(1)).is_err());
        assert!(compute_pdf_page_layout(1.0, 1.0, f64::NAN, 1.0).is_err());
    }

    #[test]
    fn rgb_dimensions_cannot_wrap_to_the_buffer_size() {
        assert_eq!(check_rgb(Some(&[0; 3]), 1, 1), Ok(&[0; 3][..]));
        assert!(check_rgb(Some(&[]), usize::MAX / 3 + 1, 1).is_err());
        assert!(check_rgb(Some(&[]), usize::MAX / 4 + 1, 4).is_err());
        assert!(check_rgb(None, 1, 1).is_err());
    }

    #[test]
    fn rgb_summary_matches_fnv_and_luma_cutoff() {
        let rgb = [244, 244, 244, 245, 245, 245, 255, 0, 0];
        assert_eq!(analyze_rgb_page(&rgb), [2_212_677_221, 76, 245, 18833, 2]);
        assert_eq!(analyze_rgb_page(&[255; 3])[1..], [255, 255, 25500, 0]);
    }

    #[test]
    fn diff_handles_partial_tiles_strict_tolerance_and_oversize_tile() {
        let src = [200; 27];
        let mut dest = src;
        dest[0] = 201;
        dest[6] = 198;
        dest[25] = 255;
        assert_eq!(
            diff_raster_tiles(&src, &dest, 3, 3, 2, 1),
            [[1, 0, 1, 2], [1, 1, 1, 55]]
        );
        assert_eq!(
            diff_raster_tiles(&src, &dest, 3, 3, usize::MAX, 1),
            [[0, 0, 2, 55]]
        );
        assert!(diff_raster_tiles(&src, &dest, 3, 3, 2, 255).is_empty());
        assert!(diff_raster_tiles(&src, &src, 3, 3, 2, 0).is_empty());
    }

    #[test]
    fn histogram_counts_primaries_and_full_luma_range() {
        let all = (0..=255).flat_map(|level| [level; 3]).collect::<Vec<u8>>();
        assert_eq!(compute_grayscale_histogram(&all), [1; 256]);
        let hist = compute_grayscale_histogram(&[255, 0, 0, 0, 255, 0, 0, 0, 255]);
        let entries = hist
            .into_iter()
            .enumerate()
            .filter(|&(_, count)| count > 0)
            .collect::<Vec<_>>();
        assert_eq!(entries, [(28, 1), (76, 1), (149, 1)]);
    }
}
