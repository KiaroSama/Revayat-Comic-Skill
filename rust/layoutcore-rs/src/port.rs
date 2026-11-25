//! Integer-pixel geometry and paragraph layout.
#![forbid(unsafe_code)]

use std::collections::VecDeque;

pub type Pixels = Option<usize>;
pub type Span = [usize; 2];
pub type KernelResult<T> = Result<T, &'static str>;

const DIMENSIONS: &str = "invalid image dimensions";
const MASK: &str = "mask buffer must be bytes and match image dimensions";
const SPANS: &str = "spans must contain ordered pairs of nonnegative integer edges";
const METRICS: &str = "invalid line metrics or padding";

fn image_size(width: Pixels, height: Pixels) -> KernelResult<(usize, usize, usize)> {
    let (Some(w @ 1..), Some(h @ 1..)) = (width, height) else {
        return Err(DIMENSIONS);
    };
    let size = w
        .checked_mul(h)
        .filter(|&size| size <= isize::MAX.cast_unsigned())
        .ok_or(DIMENSIONS)?;
    Ok((w, h, size))
}

fn mask_buffer(mask: Option<&[u8]>, size: usize) -> KernelResult<&[u8]> {
    mask.filter(|m| m.len() == size).ok_or(MASK)
}

pub fn scan_mask_spans(
    mask: Option<&[u8]>,
    width: Pixels,
    height: Pixels,
) -> KernelResult<Vec<Span>> {
    let (width, _, size) = image_size(width, height)?;
    let mask = mask_buffer(mask, size)?;
    Ok(mask
        .chunks_exact(width)
        .map(|row| {
            let [mut left, mut right] = [0, 0];
            let mut run_start = 0;
            for (x, &value) in row.iter().enumerate() {
                if value == 0 {
                    run_start = x + 1;
                } else if x + 1 - run_start > right - left {
                    [left, right] = [run_start, x + 1];
                }
            }
            [left, right]
        })
        .collect())
}

fn bands(spans: &[Span], line_height: usize, pad_x: usize) -> Vec<Option<Span>> {
    // Keep each window's maximum left and minimum right without rescanning its rows.
    let mut lefts = VecDeque::<usize>::new();
    let mut rights = VecDeque::<usize>::new();
    let mut out = Vec::with_capacity(spans.len() - line_height + 1);
    for (i, &[left, right]) in spans.iter().enumerate() {
        if i >= line_height {
            let expired = i - line_height;
            if lefts.front() == Some(&expired) {
                lefts.pop_front();
            }
            if rights.front() == Some(&expired) {
                rights.pop_front();
            }
        }
        while lefts.back().is_some_and(|&j| spans[j][0] <= left) {
            lefts.pop_back();
        }
        while rights.back().is_some_and(|&j| spans[j][1] >= right) {
            rights.pop_back();
        }
        lefts.push_back(i);
        rights.push_back(i);
        if i + 1 >= line_height {
            out.push(lefts.front().zip(rights.front()).and_then(|(&a, &b)| {
                let l = spans[a][0].checked_add(pad_x)?;
                let r = spans[b][1].checked_sub(pad_x)?;
                (r > l).then_some([l, r])
            }));
        }
    }
    out
}

#[derive(Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
struct Cost(usize, u128);

impl Cost {
    fn add_slack(self, slack: usize) -> Self {
        // One square fits u128; a paragraph can need more than 128 bits in total.
        let (low, carry) = self.1.overflowing_add((slack as u128).pow(2));
        Self(self.0 + usize::from(carry), low)
    }
}

#[derive(Clone, Copy)]
struct End {
    cost: Cost,
    prev: usize,
}

fn wrap(
    words: &[usize],
    space: usize,
    bands: &[Option<Span>],
    step: usize,
    line_height: usize,
    start: usize,
    height: usize,
) -> Vec<[usize; 5]> {
    let n = words.len();
    let mut best = None;
    let mut result = Vec::new();
    let center = (bands.len() - 1) / 2;
    let candidate_tops =
        std::iter::once(center).chain((1..bands.len() - center).flat_map(|offset| {
            center
                .checked_sub(offset)
                .into_iter()
                .chain(std::iter::once(center + offset))
        }));
    let mut layers = Vec::new();
    let mut scores = vec![None::<End>; n + 1];
    for top in candidate_tops {
        scores.fill(None);
        scores[0] = Some(End {
            cost: Cost::default(),
            prev: 0,
        });
        let mut states = scores.clone();
        layers.clear();
        for row in (top..bands.len()).step_by(step) {
            let Some([left, right]) = bands[row] else {
                break;
            };
            scores.fill(None);
            for (i, state) in states.iter().take(n).enumerate() {
                let Some(state) = state else { continue };
                let mut remaining = right - left;
                for (advance, (&word, next)) in
                    words[i..].iter().zip(&mut scores[i + 1..]).enumerate()
                {
                    let Some(row_cost) = word.checked_add(if advance == 0 { 0 } else { space })
                    else {
                        break;
                    };
                    let Some(slack) = remaining.checked_sub(row_cost) else {
                        break;
                    };
                    remaining = slack;
                    let cost = state.cost.add_slack(slack);
                    if next.is_none_or(|old| cost < old.cost) {
                        *next = Some(End { cost, prev: i });
                    }
                }
            }
            layers.push(
                scores
                    .iter()
                    .map(|end| end.map(|e| e.prev))
                    .collect::<Vec<_>>(),
            );
            if let Some(end) = scores[n].take() {
                let footprint = row - top + line_height;
                let centered_top = (height - footprint) / 2;
                let rank = (end.cost, top.abs_diff(centered_top), top, layers.len());
                if best.is_none_or(|old| rank < old) {
                    best = Some(rank);
                    result.clear();
                    let mut end = n;
                    for (layer, parents) in layers.iter().enumerate().rev() {
                        let y = top + layer * step;
                        if let (Some(prev), Some([left, right])) = (parents[end], bands[y]) {
                            result.push([prev, end, start + y, left, right]);
                            end = prev;
                        }
                    }
                    result.reverse();
                }
            }
            if !scores.iter().any(Option::is_some) {
                break;
            }
            std::mem::swap(&mut states, &mut scores);
        }
    }
    result
}

pub fn fit_lines_to_spans(
    word_widths: Option<Vec<usize>>,
    space_width: Pixels,
    line_height: Pixels,
    line_gap: Pixels,
    spans: Option<Vec<Span>>,
    pad_x: Pixels,
    pad_y: Pixels,
) -> KernelResult<Vec<[usize; 5]>> {
    let words = word_widths.ok_or("word widths must be nonnegative integers")?;
    let (Some(space), Some(line_height @ 1..), Some(gap), Some(pad_x), Some(pad_y)) =
        (space_width, line_height, line_gap, pad_x, pad_y)
    else {
        return Err(METRICS);
    };
    let spans = spans.ok_or(SPANS)?;
    if spans.iter().any(|[left, right]| left > right) {
        return Err(SPANS);
    }
    let step = line_height.checked_add(gap).ok_or(METRICS)?;
    if words.is_empty() {
        return Ok(Vec::new());
    }
    let active = |&[left, right]: &Span| left < right;
    let Some(first) = spans.iter().position(active) else {
        return Ok(Vec::new());
    };
    let Some(start) = first.checked_add(pad_y) else {
        return Ok(Vec::new());
    };
    let Some(stop) = spans
        .iter()
        .rposition(active)
        .and_then(|last| (last + 1).checked_sub(pad_y))
    else {
        return Ok(Vec::new());
    };
    if stop.saturating_sub(start) < line_height {
        return Ok(Vec::new());
    }
    let bands = bands(&spans[start..stop], line_height, pad_x);
    Ok(wrap(
        &words,
        space,
        &bands,
        step,
        line_height,
        start,
        stop - start,
    ))
}

pub fn harmonize_font_sizes(
    sizes: Option<Vec<usize>>,
    areas: Option<Vec<usize>>,
    max_step: Pixels,
    floor_size: Pixels,
) -> KernelResult<Vec<usize>> {
    let (Some(mut sizes), Some(areas)) = (sizes, areas) else {
        return Err("font sizes and areas must be nonnegative integers");
    };
    if sizes.len() != areas.len() {
        return Err("sizes and areas must have equal lengths");
    }
    let (Some(max_step), Some(floor)) = (max_step, floor_size) else {
        return Err("font limits must be nonnegative integers");
    };
    let mut eligible: Vec<_> = sizes
        .iter()
        .copied()
        .zip(areas.iter().copied())
        .filter(|&(size, area)| size >= floor && area > 0)
        .collect();
    eligible.sort_unstable_by_key(|&(size, _)| size);
    let mut remaining = eligible
        .iter()
        .map(|&(_, area)| area as u128)
        .sum::<u128>()
        .div_ceil(2);
    for (target, area) in eligible {
        if remaining <= area as u128 {
            let cap = target.saturating_add(max_step);
            for (size, &area) in sizes.iter_mut().zip(&areas) {
                if area != 0 {
                    *size = cap.min(*size);
                }
            }
            break;
        }
        remaining -= area as u128;
    }
    Ok(sizes)
}

fn sweep(distance: &mut [usize], width: usize, height: usize, backwards: bool) {
    for row in 0..height {
        let y = if backwards { height - 1 - row } else { row };
        for column in 0..width {
            let x = if backwards {
                width - 1 - column
            } else {
                column
            };
            let index = y * width + x;
            let mut d = distance[index];
            if d == 0 {
                continue;
            }
            if column != 0 {
                let prev = if backwards { index + 1 } else { index - 1 };
                d = d.min(distance[prev] + 1);
            }
            if row != 0 {
                let prev = if backwards {
                    index + width
                } else {
                    index - width
                };
                d = d.min(distance[prev] + 1);
                if x != 0 {
                    d = d.min(distance[prev - 1] + 1);
                }
                if x + 1 < width {
                    d = d.min(distance[prev + 1] + 1);
                }
            }
            distance[index] = d;
        }
    }
}

pub fn check_ink_wall_clearance(
    ink: Option<&[u8]>,
    walls: Option<&[u8]>,
    width: Pixels,
    height: Pixels,
    clearance: Pixels,
) -> KernelResult<[i64; 4]> {
    let (w, h, size) = image_size(width, height)?;
    let ink = mask_buffer(ink, size)?;
    let walls = mask_buffer(walls, size)?;
    let clearance = clearance.ok_or("minimum clearance must be a nonnegative integer")?;
    let reported_clearance =
        i64::try_from(clearance).map_err(|_| "minimum clearance exceeds the reportable range")?;
    let mut result = [0, reported_clearance, -1, -1];
    if clearance == 0 || !ink.iter().any(|&byte| byte != 0) || !walls.iter().any(|&byte| byte != 0)
    {
        return Ok(result);
    }
    let mut distance = Vec::new();
    distance
        .try_reserve_exact(size)
        .map_err(|_| "mask is too large for a clearance map")?;
    distance.extend(walls.iter().map(|&v| if v == 0 { w.max(h) } else { 0 }));
    sweep(&mut distance, w, h, false);
    sweep(&mut distance, w, h, true);
    for (index, (d, &pixel)) in distance.into_iter().zip(ink).enumerate() {
        if pixel != 0 && d < clearance {
            result[0] += 1;
            if (d as i64) < result[1] {
                result[1] = d as i64;
                result[2] = (index % w) as i64;
                result[3] = (index / w) as i64;
            }
        }
    }
    Ok(result)
}

pub fn select_largest_inscribed_band(
    spans: Option<Vec<Span>>,
    min_width: Pixels,
    min_height: Pixels,
) -> KernelResult<[usize; 4]> {
    let spans = spans.ok_or(SPANS)?;
    if spans.iter().any(|[left, right]| left > right) {
        return Err(SPANS);
    }
    let (Some(min_width @ 1..), Some(min_height @ 1..)) = (min_width, min_height) else {
        return Err("invalid minimum band size");
    };
    let mut best = [0; 4];
    let mut best_area = 0;
    for (y, &[mut left, mut right]) in spans.iter().enumerate() {
        for (i, &[a, b]) in spans[y..].iter().enumerate() {
            left = left.max(a);
            right = right.min(b);
            let width = right.saturating_sub(left);
            if width < min_width {
                break;
            }
            let height = i + 1;
            let area = (width as u128) * (height as u128);
            if height >= min_height
                && (area > best_area || (area == best_area && y == best[1] && left < best[0]))
            {
                best = [left, y, width, height];
                best_area = area;
            }
        }
    }
    Ok(best)
}

pub fn align_lines_rtl(
    line_widths: Option<Vec<usize>>,
    band_lefts: Option<Vec<usize>>,
    band_rights: Option<Vec<usize>>,
    mode: Pixels,
) -> KernelResult<Vec<usize>> {
    let (Some(mut widths), Some(lefts), Some(rights)) = (line_widths, band_lefts, band_rights)
    else {
        return Err("line widths and band edges must be nonnegative integers");
    };
    if widths.len() != lefts.len() || lefts.len() != rights.len() {
        return Err("line widths and band edges must have equal lengths");
    }
    if lefts.iter().zip(&rights).any(|(l, r)| l > r) {
        return Err("band edges must be ordered");
    }
    let Some(mode @ 0..=2) = mode else {
        return Err("alignment mode must be 0, 1, or 2");
    };
    for ((width, left), right) in widths.iter_mut().zip(lefts).zip(rights) {
        let spare = (right - left).saturating_sub(*width);
        *width = left
            + match mode {
                0 => spare / 2,
                1 => spare,
                _ => 0,
            };
    }
    Ok(widths)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn oversized_horizontal_padding_cannot_wrap_into_a_writable_band() {
        assert_eq!(
            fit_lines_to_spans(
                Some(vec![1]),
                Some(0),
                Some(1),
                Some(0),
                Some(vec![[1, 4]]),
                Some(usize::MAX),
                Some(0),
            ),
            Ok(vec![])
        );
    }

    #[test]
    fn oversized_vertical_padding_cannot_wrap_into_page_rows() {
        assert_eq!(
            fit_lines_to_spans(
                Some(vec![1]),
                Some(0),
                Some(1),
                Some(0),
                Some(vec![[0, 0], [1, 4]]),
                Some(0),
                Some(usize::MAX),
            ),
            Ok(vec![])
        );
    }

    #[test]
    fn line_stride_overflow_is_a_metric_error() {
        assert!(
            fit_lines_to_spans(
                Some(vec![1, 1]),
                Some(1),
                Some(1),
                Some(usize::MAX),
                Some(vec![[0, 4]; 2]),
                Some(0),
                Some(0),
            )
            .is_err()
        );
    }

    #[test]
    fn oversized_spaces_do_not_make_two_words_fit_on_one_line() {
        assert_eq!(
            fit_lines_to_spans(
                Some(vec![1, 1]),
                Some(usize::MAX),
                Some(1),
                Some(0),
                Some(vec![[0, 4]; 2]),
                Some(0),
                Some(0),
            ),
            Ok(vec![[0, 1, 0, 0, 4], [1, 2, 1, 0, 4]])
        );
    }

    #[test]
    fn font_cap_beyond_machine_range_does_not_reduce_fonts() {
        assert_eq!(
            harmonize_font_sizes(
                Some(vec![8, 12]),
                Some(vec![1, 1]),
                Some(usize::MAX),
                Some(1),
            ),
            Ok(vec![8, 12])
        );
    }

    #[test]
    fn malformed_spans_are_rejected_before_layout() {
        assert!(
            fit_lines_to_spans(
                Some(vec![1]),
                Some(0),
                Some(1),
                Some(0),
                Some(vec![[4, 1], [0, 4]]),
                Some(0),
                Some(0),
            )
            .is_err()
        );
        assert!(
            select_largest_inscribed_band(Some(vec![[4, 1], [0, 4]]), Some(1), Some(1)).is_err()
        );
    }

    #[test]
    fn excessive_clearance_never_becomes_a_negative_distance() {
        assert!(
            check_ink_wall_clearance(
                Some(&[0, 255]),
                Some(&[255, 0]),
                Some(2),
                Some(1),
                Some(usize::MAX),
            )
            .is_err()
        );
    }

    #[test]
    fn scan_resets_rows_and_keeps_the_first_tie() {
        let input = [0, 2, 1, 0, 1, 3, 1, 2, 3, 0, 0, 4];
        assert_eq!(
            scan_mask_spans(Some(&input), Some(6), Some(2)),
            Ok(vec![[1, 3], [0, 3]])
        );
        assert_eq!(scan_mask_spans(Some(&[1]), Some(2), Some(1)), Err(MASK));
        assert_eq!(
            scan_mask_spans(Some(&[]), Some(isize::MAX.cast_unsigned()), Some(2)),
            Err(DIMENSIONS)
        );
    }

    #[test]
    fn layout_balances_the_last_line_and_centers_the_text() {
        let fit = fit_lines_to_spans(
            Some(vec![3; 4]),
            Some(1),
            Some(2),
            Some(1),
            Some(vec![[0, 13]; 9]),
            Some(1),
            Some(1),
        );
        assert_eq!(fit, Ok(vec![[0, 2, 2, 1, 12], [2, 4, 5, 1, 12]]));
    }

    #[test]
    fn shifted_rows_use_the_common_interval_and_include_the_bottom_candidate() {
        let spans = Some(vec![[0, 4], [3, 7], [6, 10], [6, 10]]);
        assert_eq!(
            fit_lines_to_spans(
                Some(vec![3]),
                Some(0),
                Some(2),
                Some(0),
                spans,
                Some(0),
                Some(0)
            ),
            Ok(vec![[0, 1, 2, 6, 10]])
        );
    }

    #[test]
    fn an_empty_row_interrupts_line_bands() {
        let spans = Some(vec![[0, 12], [0, 0], [0, 12]]);
        assert_eq!(
            fit_lines_to_spans(
                Some(vec![2]),
                Some(0),
                Some(2),
                Some(0),
                spans,
                Some(0),
                Some(0)
            ),
            Ok(vec![])
        );
    }

    #[test]
    fn wrapping_cost_keeps_full_precision_across_many_lines() {
        let wide = isize::MAX.cast_unsigned();
        let edge = Cost(0, u128::MAX);
        assert_eq!(edge.add_slack(1), Cost(1, 0));
        assert!(edge.add_slack(1) > edge);
        let fit = fit_lines_to_spans(
            Some(vec![1; 10]),
            Some(wide),
            Some(1),
            Some(0),
            Some(vec![[0, wide]; 10]),
            Some(0),
            Some(0),
        );
        assert_eq!(fit, Ok((0..10).map(|i| [i, i + 1, i, 0, wide]).collect()));
    }

    #[test]
    fn median_weights_area_and_uses_lower_tie_without_upscaling() {
        assert_eq!(
            harmonize_font_sizes(
                Some(vec![3, 30, 10, 80]),
                Some(vec![500, 5, 5, 0]),
                Some(3),
                Some(8)
            ),
            Ok(vec![3, 13, 10, 80])
        );
        assert_eq!(
            harmonize_font_sizes(Some(vec![8]), Some(vec![]), Some(0), Some(0)),
            Err("sizes and areas must have equal lengths")
        );
    }

    #[test]
    fn strict_clearance_counts_diagonals_and_reports_first_tie() {
        let walls = [1, 0, 0, 0, 0, 0, 0, 0, 1];
        let ink = [0, 1, 0, 0, 1, 0, 0, 0, 0];
        assert_eq!(
            check_ink_wall_clearance(Some(&ink), Some(&walls), Some(3), Some(3), Some(2)),
            Ok([2, 1, 1, 0])
        );
        assert_eq!(
            check_ink_wall_clearance(Some(&ink), Some(&walls), Some(3), Some(3), Some(1)),
            Ok([0, 1, -1, -1])
        );
    }

    #[test]
    fn rectangle_intersects_all_rows_and_keeps_topmost_tie() {
        assert_eq!(
            select_largest_inscribed_band(Some(vec![[2, 6], [2, 4]]), Some(1), Some(1)),
            Ok([2, 0, 4, 1])
        );
        assert_eq!(
            select_largest_inscribed_band(Some(vec![[2, 6], [2, 4]]), Some(2), Some(2)),
            Ok([2, 0, 2, 2])
        );
        assert_eq!(
            select_largest_inscribed_band(Some(vec![[2, 6], [2, 4]]), Some(3), Some(2)),
            Ok([0; 4])
        );
    }

    #[test]
    fn alignment_never_wraps_negative_or_rounds_center_up() {
        for (mode, expected) in [(0, [6, 3]), (1, [8, 3]), (2, [4, 3])] {
            assert_eq!(
                align_lines_rtl(
                    Some(vec![3, 9]),
                    Some(vec![4, 3]),
                    Some(vec![11, 7]),
                    Some(mode)
                ),
                Ok(expected.to_vec())
            );
        }
        assert_eq!(
            align_lines_rtl(Some(vec![1]), Some(vec![2]), Some(vec![1]), Some(0)),
            Err("band edges must be ordered")
        );
    }
}
