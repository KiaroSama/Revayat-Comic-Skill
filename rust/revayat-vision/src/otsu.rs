use image::GrayImage;

/// Otsu's between-class variance over a permitted pixel mask using wide `u64`/`f64` counts.
pub(crate) fn masked_otsu_threshold(
    oriented: &GrayImage,
    permitted: impl Fn(u32, u32) -> bool,
) -> u8 {
    let mut histogram = [0u64; 256];
    for (x, y, pixel) in oriented.enumerate_pixels() {
        if permitted(x, y) {
            histogram[usize::from(pixel[0])] += 1;
        }
    }
    histogram_otsu_threshold(&histogram)
}

pub(crate) fn histogram_otsu_threshold(histogram: &[u64; 256]) -> u8 {
    let total: u64 = histogram.iter().sum();
    let sum: f64 = histogram
        .iter()
        .enumerate()
        .map(|(value, &count)| value as f64 * count as f64)
        .sum();
    let mut background = 0u64;
    let mut background_sum = 0.0;
    let mut greatest_variance = 0.0;
    let mut threshold = 0;
    for (value, &count) in histogram.iter().enumerate() {
        background += count;
        if background == 0 {
            continue;
        }
        let foreground = total - background;
        if foreground == 0 {
            break;
        }
        background_sum += value as f64 * count as f64;
        let distance =
            background_sum / background as f64 - (sum - background_sum) / foreground as f64;
        let variance = background as f64 * foreground as f64 * distance.powi(2);
        if variance > greatest_variance {
            greatest_variance = variance;
            threshold = value as u8;
        }
    }
    threshold
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn otsu_histogram_keeps_empty_constant_bimodal_and_first_tie_contracts() {
        let mut histogram = [0; 256];
        assert_eq!(histogram_otsu_threshold(&histogram), 0);
        histogram[128] = 100;
        assert_eq!(histogram_otsu_threshold(&histogram), 0);
        histogram.fill(0);
        histogram[200] = 40;
        histogram[245] = 100;
        assert_eq!(histogram_otsu_threshold(&histogram), 200);
        histogram.fill(0);
        for value in [0, 2, 4] {
            histogram[value] = 1;
        }
        assert_eq!(histogram_otsu_threshold(&histogram), 0);
    }

    #[test]
    fn otsu_histogram_handles_supported_large_page_counts_without_u32_products() {
        let mut histogram = [0; 256];
        histogram[245] = 18_000_000;
        assert_eq!(histogram_otsu_threshold(&histogram), 0);
        histogram[245] = 60_000_000;
        histogram[20] = 20_000_000;
        assert_eq!(histogram_otsu_threshold(&histogram), 20);
    }
}
