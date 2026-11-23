//! Rust pixel kernels for packed RGB and single-channel masks.
#![forbid(unsafe_code)]

use serde_json::Value;

pub const BUFFER: &str = "ValueError: pixel buffer has the wrong length or type";
const BOX: &str = "ValueError: box must contain four integers: [x, y, w, h]";

fn pixel_count(width: i64, height: i64) -> Result<usize, String> {
    if width < 0 || height < 0 {
        return Err("ValueError: width and height must be non-negative".into());
    }
    usize::try_from(i128::from(width) * i128::from(height)).map_err(|_| BUFFER.into())
}

fn check_length(buffer: &[u8], size: usize, channels: usize) -> Result<(), String> {
    if Some(buffer.len()) != size.checked_mul(channels) {
        return Err(BUFFER.into());
    }
    Ok(())
}

#[inline]
fn rgb_diff(a: &[u8], b: &[u8]) -> u8 {
    a[0].abs_diff(b[0])
        .max(a[1].abs_diff(b[1]))
        .max(a[2].abs_diff(b[2]))
}

fn clamp_box(box_: &Value, width: i64, height: i64) -> Result<[usize; 4], String> {
    let Some([x, y, w, h]) = box_.as_array().map(Vec::as_slice) else {
        return Err(BOX.into());
    };
    let clamp = |value: i128, limit: i64| value.clamp(0, i128::from(limit)) as usize;
    let (x, y, w, h) = (integer(x)?, integer(y)?, integer(w)?, integer(h)?);
    Ok([
        clamp(x, width),
        clamp(y, height),
        clamp(x.saturating_add(w), width),
        clamp(y.saturating_add(h), height),
    ])
}

fn integer(value: &Value) -> Result<i128, String> {
    value
        .as_i64()
        .map(i128::from)
        .or_else(|| value.as_u64().map(i128::from))
        .or_else(|| value.get("$int")?.as_str()?.parse::<i128>().ok())
        .ok_or_else(|| BOX.into())
}

pub fn outside_mask_diff(
    orig_rgb: &[u8],
    clean_rgb: &[u8],
    mask_l: &[u8],
    width: i64,
    height: i64,
    threshold: i64,
) -> Result<Vec<i64>, String> {
    let size = pixel_count(width, height)?;
    check_length(orig_rgb, size, 3)?;
    check_length(clean_rgb, size, 3)?;
    check_length(mask_l, size, 1)?;
    let (mut changed, mut max_diff) = (0, 0);
    for ((a, b), &m) in orig_rgb
        .as_chunks::<3>()
        .0
        .iter()
        .zip(clean_rgb.as_chunks::<3>().0)
        .zip(mask_l)
    {
        if m == 0 {
            let diff = i64::from(rgb_diff(a, b));
            changed += i64::from(diff > threshold);
            max_diff = max_diff.max(diff);
        }
    }
    Ok(vec![changed, max_diff])
}

pub fn changed_mask_rgb(
    a_rgb: &[u8],
    b_rgb: &[u8],
    width: i64,
    height: i64,
    threshold: i64,
) -> Result<Vec<u8>, String> {
    let size = pixel_count(width, height)?;
    check_length(a_rgb, size, 3)?;
    check_length(b_rgb, size, 3)?;
    Ok(a_rgb
        .as_chunks::<3>()
        .0
        .iter()
        .zip(b_rgb.as_chunks::<3>().0)
        .map(|(a, b)| {
            if i64::from(rgb_diff(a, b)) > threshold {
                255
            } else {
                0
            }
        })
        .collect())
}

pub fn overlap_changed_pixels(
    changed_mask: &[u8],
    width: i64,
    height: i64,
    boxes: serde_json::Value,
) -> Result<Vec<Vec<i64>>, String> {
    check_length(changed_mask, pixel_count(width, height)?, 1)?;
    let clipped: Vec<_> = boxes
        .as_array()
        .ok_or("ValueError: boxes must be a list")?
        .iter()
        .map(|value| clamp_box(value, width, height))
        .collect::<Result<_, _>>()?;
    let mut overlaps = Vec::new();
    for (i, &[ax0, ay0, ax1, ay1]) in clipped.iter().enumerate() {
        for (j, &[bx0, by0, bx1, by1]) in clipped.iter().enumerate().skip(i + 1) {
            let (x0, y0, x1, y1) = (ax0.max(bx0), ay0.max(by0), ax1.min(bx1), ay1.min(by1));
            if x0 >= x1 || y0 >= y1 {
                continue;
            }
            let mut count = 0;
            for y in y0..y1 {
                let row = y * width as usize;
                count += changed_mask[row + x0..row + x1]
                    .iter()
                    .filter(|&&p| p != 0)
                    .count();
            }
            if count > 0 {
                overlaps.push(vec![i as i64, j as i64, count as i64]);
            }
        }
    }
    Ok(overlaps)
}

#[expect(
    clippy::too_many_arguments,
    reason = "The Python API takes nine arguments"
)]
pub fn outline_crossing_pixels(
    orig_rgb: &[u8],
    clean_rgb: &[u8],
    final_rgb: &[u8],
    safe_mask: &[u8],
    width: i64,
    height: i64,
    r#box: serde_json::Value,
    dark_polarity: bool,
    diff_threshold: i64,
) -> Result<i64, String> {
    let size = pixel_count(width, height)?;
    check_length(orig_rgb, size, 3)?;
    check_length(clean_rgb, size, 3)?;
    check_length(final_rgb, size, 3)?;
    check_length(safe_mask, size, 1)?;
    let [x0, y0, x1, y1] = clamp_box(&r#box, width, height)?;
    if x0 >= x1 || y0 >= y1 {
        return Ok(0);
    }
    let original = orig_rgb.as_chunks::<3>().0;
    let cleaned = clean_rgb.as_chunks::<3>().0;
    let final_ = final_rgb.as_chunks::<3>().0;
    let mut count = 0;
    for y in y0..y1 {
        let start = y * width as usize + x0;
        let end = start + x1 - x0;
        for (offset, &safe) in safe_mask[start..end].iter().enumerate() {
            let i = start + offset;
            if safe != 0 || i64::from(rgb_diff(&final_[i], &cleaned[i])) <= diff_threshold {
                continue;
            }
            let rgb_sum: u16 = original[i].iter().map(|&c| u16::from(c)).sum();
            count += i64::from(if dark_polarity {
                rgb_sum > 120
            } else {
                rgb_sum < 645
            });
        }
    }
    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn strict_rgb_delta_and_buffer_validation() {
        assert_eq!(
            changed_mask_rgb(&[0, 0, 255], &[0, 7, 247], 1, 1, 8),
            Ok(vec![0])
        );
        assert_eq!(
            changed_mask_rgb(&[0, 0, 255], &[0, 7, 247], 1, 1, 7),
            Ok(vec![255])
        );
        assert_eq!(
            changed_mask_rgb(&[], &[0, 0, 0], 1, 1, 7),
            Err(BUFFER.into())
        );
    }

    #[test]
    fn clips_box_ends_without_overflow() {
        assert_eq!(
            clamp_box(&json!([1, -2, i64::MAX, 4]), 8, 5),
            Ok([1, 0, 8, 2])
        );
    }
}
