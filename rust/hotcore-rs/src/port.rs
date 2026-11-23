//! The Rust port of `skills/revayat-comic/scripts/hotcore/`.

#![forbid(unsafe_code)]

use std::collections::HashMap;

/// Port of `box_gap` (`skills/revayat-comic/scripts/hotcore/geometry.py:13`).
pub fn box_gap(a: Vec<i64>, b: Vec<i64>) -> Result<f64, String> {
    if a.len() < 4 || b.len() < 4 {
        return Err("ValueError: Each box must have four integers: [x, y, w, h]".to_string());
    }
    let [ax0, ay0, aw, ah] = [a[0], a[1], a[2], a[3]].map(i128::from);
    let [bx0, by0, bw, bh] = [b[0], b[1], b[2], b[3]].map(i128::from);
    let dx = 0i128.max(ax0.max(bx0) - (ax0 + aw).min(bx0 + bw)) as f64;
    let dy = 0i128.max(ay0.max(by0) - (ay0 + ah).min(by0 + bh)) as f64;
    Ok(dx.hypot(dy))
}

fn uf_find(parent: &mut [usize], mut index: usize) -> usize {
    while parent[index] != index {
        let next = parent[index];
        parent[index] = parent[next];
        index = parent[index];
    }
    index
}

/// Port of `cluster_boxes` (`skills/revayat-comic/scripts/hotcore/geometry.py:24`).
///
/// `max_seeds` defaults to `400` in the source.
///
/// `reach` defaults to `1.6` in the source.
pub fn cluster_boxes(
    seeds: Vec<Vec<i64>>,
    max_seeds: Option<i64>,
    reach: Option<f64>,
) -> Result<Vec<Vec<Vec<i64>>>, String> {
    if seeds.is_empty() {
        return Ok(Vec::new());
    }
    let Some(max_seeds) = max_seeds else {
        return Err(
            "TypeError: '<' not supported between instances of 'NoneType' and 'int'".to_string(),
        );
    };
    if max_seeds < 1 {
        return Err("ValueError: max_seeds must be positive".to_string());
    }
    for b in &seeds {
        if b.len() < 4 {
            return Err("IndexError: list index out of range".to_string());
        }
    }

    let mut work = seeds;
    let limit_seeds = usize::try_from(max_seeds).unwrap_or(usize::MAX);
    if work.len() > limit_seeds {
        // Python `sorted(..., key=lambda box: -(box[2]*box[3]))` is stable.
        work.sort_by(|a, b| {
            let area_a = i128::from(a[2]) * i128::from(a[3]);
            let area_b = i128::from(b[2]) * i128::from(b[3]);
            area_b.cmp(&area_a)
        });
        work.truncate(limit_seeds);
    }

    let n = work.len();
    let mut parent: Vec<usize> = (0..n).collect();

    for i in 0..n {
        let ax0 = i128::from(work[i][0]);
        let ay0 = i128::from(work[i][1]);
        let aw = i128::from(work[i][2]);
        let ah = i128::from(work[i][3]);
        let ax1 = ax0 + aw;
        let ay1 = ay0 + ah;
        for (j, bj) in work.iter().enumerate().skip(i + 1) {
            let Some(reach_val) = reach else {
                return Err(
                    "TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'"
                        .to_string(),
                );
            };
            let [bx0, by0, bw, bh] = [bj[0], bj[1], bj[2], bj[3]].map(i128::from);
            let dx = 0i128.max(ax0.max(bx0) - ax1.min(bx0 + bw)) as f64;
            let dy = 0i128.max(ay0.max(by0) - ay1.min(by0 + bh)) as f64;
            let scale = aw.max(ah).max(bw).max(bh) as f64;
            let limit = reach_val * scale;
            if limit >= 0.0 && (dx * dx + dy * dy) <= limit * limit + 1e-12 && dx.hypot(dy) <= limit
            {
                let ri = uf_find(&mut parent, i);
                let rj = uf_find(&mut parent, j);
                parent[ri] = rj;
            }
        }
    }

    let mut order: Vec<usize> = Vec::new();
    let mut groups: HashMap<usize, Vec<Vec<i64>>> = HashMap::new();
    for (index, box_item) in work.into_iter().enumerate() {
        let root = uf_find(&mut parent, index);
        if !groups.contains_key(&root) {
            order.push(root);
        }
        groups.entry(root).or_default().push(box_item);
    }

    let mut result = Vec::with_capacity(order.len());
    for root in order {
        if let Some(group) = groups.remove(&root) {
            result.push(group);
        }
    }
    Ok(result)
}

fn validate_mask_dims(mask_len: usize, width: i64, height: i64) -> Result<(usize, usize), String> {
    if width < 0 || height < 0 {
        return Err("ValueError: width and height must be non-negative".to_string());
    }
    let w = usize::try_from(width)
        .map_err(|_| "ValueError: width and height must be non-negative".to_string())?;
    let h = usize::try_from(height)
        .map_err(|_| "ValueError: width and height must be non-negative".to_string())?;
    let expected = w
        .checked_mul(h)
        .ok_or_else(|| "ValueError: mask_flat length must equal width * height".to_string())?;
    if mask_len != expected {
        return Err("ValueError: mask_flat length must equal width * height".to_string());
    }
    Ok((w, h))
}

fn extract_bytes(mask_flat: &serde_json::Value) -> Result<Vec<u8>, String> {
    let arr = mask_flat
        .as_object()
        .and_then(|obj| obj.get("$bytes"))
        .and_then(|v| v.as_array())
        .ok_or_else(|| "TypeError: mask_flat must be bytes".to_string())?;
    let mut out = Vec::with_capacity(arr.len());
    for item in arr {
        let byte = item
            .as_u64()
            .and_then(|n| u8::try_from(n).ok())
            .ok_or_else(|| "TypeError: mask_flat must be bytes".to_string())?;
        out.push(byte);
    }
    Ok(out)
}

/// Port of `row_widths` (`skills/revayat-comic/scripts/hotcore/geometry.py:70`).
pub fn row_widths(
    mask_flat: serde_json::Value,
    width: i64,
    height: i64,
) -> Result<Vec<i64>, String> {
    let bytes = extract_bytes(&mask_flat)?;
    let (w, h) = validate_mask_dims(bytes.len(), width, height)?;
    if h == 0 {
        return Ok(Vec::new());
    }
    if w == 0 {
        return Ok(vec![0; h]);
    }
    let mut widths = Vec::with_capacity(h);
    for row in 0..h {
        let slice = &bytes[row * w..(row + 1) * w];
        let mut best = 0i64;
        let mut run = 0i64;
        for &value in slice {
            if value != 0 {
                run += 1;
                if run > best {
                    best = run;
                }
            } else {
                run = 0;
            }
        }
        widths.push(best);
    }
    Ok(widths)
}

/// Port of `band_span` (`skills/revayat-comic/scripts/hotcore/geometry.py:98`).
pub fn band_span(
    mask_flat: serde_json::Value,
    width: i64,
    height: i64,
    first: i64,
    last: i64,
) -> Result<Vec<i64>, String> {
    let bytes = extract_bytes(&mask_flat)?;
    let (w, _h) = validate_mask_dims(bytes.len(), width, height)?;
    let clamped_first = first.clamp(0, height) as usize;
    let clamped_last = last.clamp(0, height) as usize;
    if clamped_last <= clamped_first || w == 0 {
        return Ok(vec![0, 0]);
    }

    let mut active = vec![1u8; w];
    for row in clamped_first..clamped_last {
        let slice = &bytes[row * w..(row + 1) * w];
        for col in 0..w {
            if slice[col] == 0 {
                active[col] = 0;
            }
        }
    }

    let mut best_start = 0i64;
    let mut best_len = 0i64;
    let mut run_start = 0i64;
    let mut run_len = 0i64;

    for (col, &on) in active.iter().enumerate() {
        if on != 0 {
            if run_len == 0 {
                run_start = col as i64;
            }
            run_len += 1;
            if run_len > best_len {
                best_start = run_start;
                best_len = run_len;
            }
        } else {
            run_len = 0;
        }
    }

    Ok(vec![best_start, best_len])
}

fn i64_ge_f64(w: i64, threshold: f64) -> bool {
    if threshold.is_nan() {
        return false;
    }
    if threshold <= (i64::MIN as f64) {
        return true;
    }
    if threshold >= 9_223_372_036_854_775_808.0_f64 {
        return false;
    }
    w >= (threshold.ceil() as i64)
}

/// Port of `body_bounds` (`skills/revayat-comic/scripts/hotcore/geometry.py:140`).
///
/// `reference` defaults to `-1` in the source.
///
/// `body_width` defaults to `0.5` in the source.
pub fn body_bounds(
    widths: Vec<i64>,
    reference: Option<i64>,
    body_width: Option<f64>,
) -> Result<Vec<i64>, String> {
    if widths.is_empty() {
        return Ok(vec![0, 0]);
    }
    let Some(reference) = reference else {
        return Err(
            "TypeError: '<' not supported between instances of 'NoneType' and 'int'".to_string(),
        );
    };
    let Some(body_width) = body_width else {
        return Err(
            "TypeError: unsupported operand type(s) for *: 'int' and 'NoneType'".to_string(),
        );
    };
    let ref_val = if reference < 0 {
        widths.iter().copied().max().unwrap_or(0)
    } else {
        reference
    };
    let threshold = (ref_val as f64) * body_width;
    let mut best_start = 0i64;
    let mut best_length = 0i64;
    let mut run_start = 0i64;
    let mut run_length = 0i64;
    for (index, &w) in widths.iter().enumerate() {
        if i64_ge_f64(w, threshold) {
            if run_length == 0 {
                run_start = index as i64;
            }
            run_length += 1;
            if run_length > best_length {
                best_start = run_start;
                best_length = run_length;
            }
        } else {
            run_length = 0;
        }
    }
    Ok(vec![best_start, best_length])
}

/// Port of `candidate_bodies` (`skills/revayat-comic/scripts/hotcore/geometry.py:168`).
///
/// `body_width` defaults to `0.5` in the source.
pub fn candidate_bodies(
    widths: Vec<i64>,
    body_width: Option<f64>,
) -> Result<Vec<Vec<i64>>, String> {
    if widths.is_empty() {
        return Ok(Vec::new());
    }
    let mut ordered = widths.clone();
    ordered.sort_unstable();
    let n = ordered.len();
    let idx85 = (0.85 * ((n - 1) as f64)) as usize;
    let idx75 = (0.75 * ((n - 1) as f64)) as usize;
    let refs = [
        ordered[n - 1],
        ordered[idx85],
        ordered[idx75],
        ordered[n / 2],
    ];

    let mut seen: Vec<(i64, i64)> = Vec::new();
    let mut bodies: Vec<Vec<i64>> = Vec::new();
    for r in refs {
        if r <= 0 {
            continue;
        }
        let band = body_bounds(widths.clone(), Some(r), body_width)?;
        let key = (band[0], band[1]);
        if band[1] > 0 && !seen.contains(&key) {
            seen.push(key);
            bodies.push(band);
        }
    }
    Ok(bodies)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gap_handles_overlap_and_separation() {
        assert_eq!(box_gap(vec![0, 0, 10, 10], vec![5, 5, 10, 10]), Ok(0.0));
        assert_eq!(box_gap(vec![0, 0, 10, 10], vec![13, 14, 5, 5]), Ok(5.0));
        assert!(box_gap(vec![0, 0, 10], vec![0, 0, 10, 10]).is_err());
    }

    #[test]
    fn coordinate_sums_do_not_wrap_at_i64_boundaries() {
        let far = vec![i64::MAX - 5, 0, 10, 10];
        let origin = vec![0, 0, 1, 1];
        assert_eq!(
            box_gap(far.clone(), origin.clone()),
            Ok((i64::MAX - 6) as f64)
        );
        assert_eq!(
            cluster_boxes(vec![far.clone(), origin.clone()], Some(400), Some(1.6)),
            Ok(vec![vec![far], vec![origin]])
        );
    }

    #[test]
    fn cluster_groups_nearby_and_splits_far() {
        let seeds = vec![
            vec![10, 10, 12, 18],
            vec![26, 10, 12, 18],
            vec![200, 200, 12, 18],
        ];
        let groups = cluster_boxes(seeds, Some(400), Some(1.6)).expect("valid cluster");
        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].len(), 2);
        assert_eq!(groups[1].len(), 1);
        assert!(cluster_boxes(vec![vec![0, 0, 5, 5]], Some(0), Some(1.6)).is_err());
    }

    #[test]
    fn row_widths_and_band_span_match_geometry() {
        let mask = serde_json::json!({
            "$bytes": [
                0, 255, 255, 0, 255, // row 0: max 2
                255, 255, 255, 255, 0, // row 1: max 4
                0, 255, 255, 255, 0, // row 2: max 3
            ]
        });
        assert_eq!(row_widths(mask.clone(), 5, 3), Ok(vec![2, 4, 3]));
        assert_eq!(band_span(mask.clone(), 5, 3, 0, 3), Ok(vec![1, 2]));
        assert_eq!(band_span(mask, 5, 3, 1, 3), Ok(vec![1, 3]));
        assert!(row_widths(serde_json::json!({"$bytes": [0, 1]}), 5, 3).is_err());
        assert!(band_span(serde_json::json!({"$bytes": [0]}), -1, 1, 0, 1).is_err());
    }

    #[test]
    fn bodies_handles_tail_and_spike() {
        let widths = vec![2, 200, 10, 60, 65, 68, 66, 62, 12, 4];
        let candidates = candidate_bodies(widths, Some(0.5)).expect("valid bodies");
        assert!(candidates.len() >= 2);
        assert_eq!(candidates[0], vec![1, 1]);
        assert_eq!(candidates[1], vec![3, 5]);
    }
}
