//! Comic-page geometry kernels shared by the Python extension and Rust tests.
#![forbid(unsafe_code)]

use std::cmp::Reverse;
use std::ops::Range;

const DIMS: &str = "ValueError: image dimensions must be positive integers";
const IMAGE: &str = "ValueError: image must be bytes of length width * height";
const BOXES: &str = "ValueError: boxes must contain valid [x, y, w, h] rectangles";
const STROKE: &str = "ValueError: stroke box must be a valid [x, y, w, h] rectangle";

struct Image<'a> {
    gray: &'a [u8],
    width: usize,
    height: usize,
}

impl<'a> Image<'a> {
    fn new(gray: Option<&'a [u8]>, width: i64, height: i64) -> Result<Self, String> {
        if width <= 0 || height <= 0 {
            return Err(DIMS.into());
        }
        let width = usize::try_from(width).map_err(|_| IMAGE)?;
        let height = usize::try_from(height).map_err(|_| IMAGE)?;
        let gray = gray.ok_or(IMAGE)?;
        if width.checked_mul(height) != Some(gray.len()) {
            return Err(IMAGE.into());
        }
        Ok(Self {
            gray,
            width,
            height,
        })
    }

    fn row(&self, y: usize, x: Range<usize>) -> &[u8] {
        let start = y * self.width;
        &self.gray[start + x.start..start + x.end]
    }

    fn column(&self, x: usize, y: Range<usize>) -> impl Iterator<Item = u8> + '_ {
        y.map(move |row| self.gray[row * self.width + x])
    }

    fn neighbors(&self, x: usize, y: usize, diagonal: bool, mut visit: impl FnMut(usize)) {
        for ny in y.saturating_sub(1)..(y + 2).min(self.height) {
            for nx in x.saturating_sub(1)..(x + 2).min(self.width) {
                if (nx != x || ny != y) && (diagonal || nx == x || ny == y) {
                    visit(ny * self.width + nx);
                }
            }
        }
    }
}

fn luma(value: i64, error: &str) -> Result<u8, String> {
    u8::try_from(value).map_err(|_| error.into())
}

fn trim(len: usize, margin: usize, mut blank: impl FnMut(usize) -> bool) -> Range<usize> {
    let mut start = 0;
    let mut end = len;
    while start < end.min(margin) && blank(start) {
        start += 1;
    }
    while end > start.max(len.saturating_sub(margin)) && blank(end - 1) {
        end -= 1;
    }
    start..end
}

struct Gutters<'a> {
    image: Image<'a>,
    bg: u8,
    gutter: usize,
    minimum: usize,
}

impl Gutters<'_> {
    fn widest(
        &self,
        axis: Range<usize>,
        mut blank: impl FnMut(usize) -> bool,
    ) -> Option<Range<usize>> {
        let extent = axis.len();
        if extent < self.minimum.saturating_mul(2).saturating_add(self.gutter) {
            return None;
        }
        let mut best: Range<usize> = 0..0;
        let mut start = axis.start;
        for position in axis.clone().chain(std::iter::once(axis.end)) {
            if position < axis.end && blank(position) {
                continue;
            }
            let size = position - start;
            if start - axis.start >= self.minimum
                && axis.end - position >= self.minimum
                && size >= self.gutter
                && size > best.len()
            {
                best = start..position;
            }
            start = position + 1;
        }
        (!best.is_empty()).then_some(best)
    }

    fn split(&self, x: Range<usize>, y: Range<usize>, depth: u8, out: &mut Vec<[usize; 4]>) {
        if depth < 8 {
            if let Some(band) = self.widest(y.clone(), |row| {
                self.image.row(row, x.clone()).iter().all(|p| *p >= self.bg)
            }) {
                self.split(x.clone(), y.start..band.start, depth + 1, out);
                self.split(x, band.end..y.end, depth + 1, out);
                return;
            }
            if let Some(band) = self.widest(x.clone(), |col| {
                self.image.column(col, y.clone()).all(|p| p >= self.bg)
            }) {
                self.split(x.start..band.start, y.clone(), depth + 1, out);
                self.split(band.end..x.end, y, depth + 1, out);
                return;
            }
        }
        out.push([x.start, y.start, x.len(), y.len()]);
    }
}

pub fn find_panel_gutters(
    gray: Option<&[u8]>,
    width: i64,
    height: i64,
    bg_luma: i64,
    min_gutter: i64,
    margin: i64,
) -> Result<Vec<[usize; 4]>, String> {
    let image = Image::new(gray, width, height)?;
    let bg = luma(bg_luma, "ValueError: background luma must be in 0..255")?;
    if min_gutter <= 0 || margin < 0 {
        return Err("ValueError: minimum gutter must be positive and margin nonnegative".into());
    }
    let gutter = usize::try_from(min_gutter).unwrap_or(usize::MAX);
    let margin = usize::try_from(margin).unwrap_or(usize::MAX);
    let minimum = gutter.saturating_mul(3).max(24);
    // At most floor(4%) of a border line may be dark.
    let y = trim(image.height, margin, |row| {
        image
            .row(row, 0..image.width)
            .iter()
            .filter(|p| **p < bg)
            .count()
            <= image.width / 25
    });
    if y.len() < minimum {
        return Ok(Vec::new());
    }
    let x = trim(image.width, margin, |col| {
        image.column(col, y.clone()).filter(|p| *p < bg).count() <= y.len() / 25
    });
    let mut result = Vec::new();
    if x.len() >= minimum {
        Gutters {
            image,
            bg,
            gutter,
            minimum,
        }
        .split(x, y, 0, &mut result);
    }
    Ok(result)
}

const SEEN: u8 = 1;
const MEMBER: u8 = 2;
const RING: u8 = 4;

fn components(
    image: &Image<'_>,
    threshold: u8,
    diagonal: bool,
    mut component: impl FnMut([usize; 5], &[usize], &mut [u8]),
) {
    let mut marks = vec![0; image.gray.len()];
    let mut queue = Vec::new();
    for (seed, &luma) in image.gray.iter().enumerate() {
        if luma < threshold || marks[seed] & SEEN != 0 {
            continue;
        }
        queue.clear();
        queue.push(seed);
        marks[seed] = SEEN | MEMBER;
        let (mut x0, mut y0) = (seed % image.width, seed / image.width);
        let (mut x1, mut y1) = (x0, y0);
        let mut cursor = 0;
        while let Some(&i) = queue.get(cursor) {
            cursor += 1;
            let (x, y) = (i % image.width, i / image.width);
            (x0, y0) = (x0.min(x), y0.min(y));
            (x1, y1) = (x1.max(x), y1.max(y));
            image.neighbors(x, y, diagonal, |j| {
                if marks[j] & SEEN == 0 && image.gray[j] >= threshold {
                    marks[j] = SEEN | MEMBER;
                    queue.push(j);
                }
            });
        }
        component(
            [x0, y0, x1 - x0 + 1, y1 - y0 + 1, queue.len()],
            &queue,
            &mut marks,
        );
        for &i in &queue {
            marks[i] = SEEN;
        }
    }
}

pub fn connected_components_boxes(
    mask: Option<&[u8]>,
    width: i64,
    height: i64,
    min_area: i64,
    max_area: i64,
) -> Result<Vec<[usize; 5]>, String> {
    let image = Image::new(mask, width, height)?;
    if min_area <= 0 || max_area < min_area {
        return Err("ValueError: component area bounds must be positive and ordered".into());
    }
    let min = usize::try_from(min_area).unwrap_or(usize::MAX);
    let max = usize::try_from(max_area).unwrap_or(usize::MAX);
    let mut boxes = Vec::new();
    components(&image, 1, true, |b, _, _| {
        if (min..=max).contains(&b[4]) {
            boxes.push(b);
        }
    });
    boxes.sort_by_key(|b| (b[1], Reverse(b[0]), b[3], b[2]));
    Ok(boxes)
}

fn ratio(value: f64) -> bool {
    (0.0..=1.0).contains(&value)
}

pub fn detect_speech_balloons(
    gray: Option<&[u8]>,
    width: i64,
    height: i64,
    white_thresh: i64,
    min_area: i64,
    max_area_ratio: f64,
    min_fill_ratio: f64,
) -> Result<Vec<[usize; 5]>, String> {
    let image = Image::new(gray, width, height)?;
    let white = luma(
        white_thresh,
        "ValueError: white threshold must be in 0..255",
    )?;
    if min_area <= 0 || max_area_ratio <= 0.0 || !ratio(max_area_ratio) || !ratio(min_fill_ratio) {
        return Err("ValueError: balloon area must be positive and ratios in range".into());
    }
    let min = usize::try_from(min_area).unwrap_or(usize::MAX);
    let max = max_area_ratio * (image.gray.len() as f64);
    let dark_limit = white.saturating_sub(25);
    let mut boxes = Vec::new();
    let mut ring = Vec::new();
    components(&image, white, false, |b, pixels, marks| {
        let [x, y, w, h, area] = b;
        let borders = u8::from(x == 0)
            + u8::from(y == 0)
            + u8::from(x + w == image.width)
            + u8::from(y + h == image.height);
        if borders >= 3
            || area < min
            || area as f64 > max
            || area as f64 / ((w * h) as f64) < min_fill_ratio
        {
            return;
        }
        let mut dark = 0usize;
        for &i in pixels {
            image.neighbors(i % image.width, i / image.width, true, |j| {
                if marks[j] & (MEMBER | RING) == 0 {
                    marks[j] |= RING;
                    ring.push(j);
                    dark += usize::from(image.gray[j] < dark_limit);
                }
            });
        }
        if !ring.is_empty() && (dark as u128) * 20 >= (ring.len() as u128) * 9 {
            boxes.push(b);
        }
        for j in ring.drain(..) {
            marks[j] &= !RING;
        }
    });
    Ok(boxes)
}

fn valid_rect([x, y, w, h]: [i64; 4], minimum: i64) -> bool {
    x >= 0
        && y >= 0
        && w >= minimum
        && h >= minimum
        && x.checked_add(w).is_some()
        && y.checked_add(h).is_some()
}

fn validated_boxes(boxes: Option<Vec<[i64; 4]>>) -> Result<Vec<[i64; 4]>, String> {
    let boxes = boxes.ok_or(BOXES)?;
    if boxes.iter().any(|b| !valid_rect(*b, 1)) {
        return Err(BOXES.into());
    }
    Ok(boxes)
}

fn groups(boxes: &[[i64; 4]], linked: impl Fn([i64; 4], [i64; 4]) -> bool) -> Vec<Vec<usize>> {
    fn root(parents: &mut [usize], mut i: usize) -> usize {
        while parents[i] != i {
            parents[i] = parents[parents[i]];
            i = parents[i];
        }
        i
    }
    let mut parents: Vec<_> = (0..boxes.len()).collect();
    let mut sizes = vec![1; boxes.len()];
    for (i, &a) in boxes.iter().enumerate() {
        for (j, &b) in boxes[..i].iter().enumerate() {
            if linked(a, b) {
                let (mut a, mut b) = (root(&mut parents, i), root(&mut parents, j));
                if a == b {
                    continue;
                }
                if sizes[a] < sizes[b] {
                    std::mem::swap(&mut a, &mut b);
                }
                parents[b] = a;
                sizes[a] += sizes[b];
            }
        }
    }
    let mut by_root = vec![usize::MAX; boxes.len()];
    let mut clusters: Vec<Vec<usize>> = Vec::new();
    for i in 0..boxes.len() {
        let slot = &mut by_root[root(&mut parents, i)];
        if *slot == usize::MAX {
            *slot = clusters.len();
            clusters.push(Vec::new());
        }
        clusters[*slot].push(i);
    }
    clusters
}

fn span(a: i64, a_len: i64, b: i64, b_len: i64) -> i64 {
    (a + a_len).min(b + b_len) - a.max(b)
}

pub fn merge_text_lines(
    boxes: Option<Vec<[i64; 4]>>,
    max_dx: i64,
    max_dy: i64,
    min_overlap_ratio: f64,
) -> Result<Vec<[i64; 4]>, String> {
    let boxes = validated_boxes(boxes)?;
    if max_dx < 0 || max_dy < 0 || !ratio(min_overlap_ratio) {
        return Err("ValueError: text gaps must be nonnegative and overlap ratio in 0..1".into());
    }
    let groups = groups(&boxes, |[x, y, w, h], [bx, by, bw, bh]| {
        let dx = span(x, w, bx, bw);
        let dy = span(y, h, by, bh);
        let enough = |overlap: i64, shortest: i64| {
            // Compare the integer overlap without rounding it up to the float threshold.
            i128::from(overlap.max(0)) >= (min_overlap_ratio * shortest as f64).ceil() as i128
        };
        (-dx <= max_dx && enough(dy, h.min(bh))) || (-dy <= max_dy && enough(dx, w.min(bw)))
    });
    let mut merged = Vec::with_capacity(groups.len());
    for group in groups {
        let (mut x0, mut y0, mut x1, mut y1) = (i64::MAX, i64::MAX, 0, 0);
        for i in group {
            let [x, y, w, h] = boxes[i];
            (x0, y0, x1, y1) = (x0.min(x), y0.min(y), x1.max(x + w), y1.max(y + h));
        }
        merged.push([x0, y0, x1 - x0, y1 - y0]);
    }
    merged.sort_by_key(|b| (b[1], b[0]));
    Ok(merged)
}

pub fn sort_reading_order(
    boxes: Option<Vec<[i64; 4]>>,
    rtl: Option<bool>,
    row_tolerance: i64,
) -> Result<Vec<usize>, String> {
    let boxes = validated_boxes(boxes)?;
    let rtl = rtl
        .filter(|_| row_tolerance >= 0)
        .ok_or("ValueError: rtl must be a boolean and row tolerance nonnegative")?;
    let mut rows = groups(&boxes, |[_, y, _, h], [_, by, _, bh]| {
        let centers = (2 * (i128::from(y) - i128::from(by)) + i128::from(h) - i128::from(bh)).abs();
        centers <= 2 * i128::from(row_tolerance)
            || 2 * i128::from(span(y, h, by, bh)) >= i128::from(h.min(bh))
    });
    rows.sort_by_cached_key(|r| r.iter().map(|&i| boxes[i][1]).min());
    let mut order = Vec::with_capacity(boxes.len());
    for mut row in rows {
        row.sort_unstable_by_key(|&i| {
            let [x, _, w, _] = boxes[i];
            (if rtl { -(x + w) } else { x }, i)
        });
        order.extend(row);
    }
    Ok(order)
}

pub fn estimate_stroke_width(
    gray: Option<&[u8]>,
    width: i64,
    height: i64,
    box_rect: Option<[i64; 4]>,
) -> Result<f64, String> {
    let image = Image::new(gray, width, height)?;
    let rect = box_rect.filter(|b| valid_rect(*b, 0)).ok_or(STROKE)?;
    let [x, y, w, h] = rect;
    if x + w > width || y + h > height {
        return Err("ValueError: stroke box must fit in the image".into());
    }
    if w == 0 || h == 0 {
        return Ok(0.0);
    }
    let x = (x as usize)..((x + w) as usize);
    let y = (y as usize)..((y + h) as usize);
    let (mut low, mut high) = (u8::MAX, u8::MIN);
    for row in y.clone() {
        for &p in image.row(row, x.clone()) {
            (low, high) = (low.min(p), high.max(p));
        }
    }
    if high - low < 24 {
        return Ok(0.0);
    }
    let threshold = u8::midpoint(low, high);
    let mut histogram = Vec::new();
    let mut total = 0;
    let mut add_run = |run| {
        if run > 0 {
            if run >= histogram.len() {
                histogram.resize(run + 1, 0usize);
            }
            histogram[run] += 1;
            total += 1;
        }
    };
    for row in y.clone() {
        runs(
            image.row(row, x.clone()).iter().copied(),
            threshold,
            &mut add_run,
        );
    }
    for col in x {
        runs(image.column(col, y.clone()), threshold, &mut add_run);
    }
    let (mut count, mut lo) = (0, None);
    for (length, n) in histogram.into_iter().enumerate() {
        count += n;
        if count > (total - 1) / 2 {
            let lower = *lo.get_or_insert(length);
            if count > total / 2 {
                return Ok(f64::midpoint(lower as f64, length as f64));
            }
        }
    }
    Ok(0.0)
}

fn runs(pixels: impl Iterator<Item = u8>, threshold: u8, add: &mut impl FnMut(usize)) {
    let mut run = 0;
    for p in pixels {
        if p <= threshold {
            run += 1;
        } else {
            add(run);
            run = 0;
        }
    }
    add(run);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cuts_a_full_horizontal_gutter_and_respects_minimum_size() {
        let mut page = [0; 24 * 52];
        page[24 * 24..28 * 24].fill(230);
        assert_eq!(
            find_panel_gutters(Some(&page), 24, 52, 230, 4, 0),
            Ok(vec![[0, 0, 24, 24], [0, 28, 24, 24]])
        );
        assert_eq!(
            find_panel_gutters(Some(&page), 24, 52, 230, 5, 0),
            Ok(vec![[0, 0, 24, 52]])
        );
    }

    #[test]
    fn eight_connected_component_includes_nonbinary_foreground() {
        assert_eq!(
            connected_components_boxes(Some(&[1, 0, 0, 2]), 2, 2, 2, 2),
            Ok(vec![[0, 0, 2, 2, 2]])
        );
        assert_eq!(
            connected_components_boxes(Some(&[]), i64::MAX, i64::MAX, 1, 1),
            Err(IMAGE.into())
        );
    }

    #[test]
    fn balloon_wall_counts_distinct_ring_pixels_strictly_below_cutoff() {
        let mut pixels = [0, 0, 0, 0, 250, 195, 195, 195, 195];
        assert_eq!(
            detect_speech_balloons(Some(&pixels), 3, 3, 220, 1, 1.0, 1.0),
            Ok(vec![[1, 1, 1, 1, 1]])
        );
        pixels[0] = 195;
        assert_eq!(
            detect_speech_balloons(Some(&pixels), 3, 3, 220, 1, 1.0, 1.0),
            Ok(vec![])
        );
    }

    #[test]
    fn text_links_bridge_both_axes() {
        let boxes = vec![[0, 0, 4, 5], [6, 1, 4, 5], [7, 8, 5, 5]];
        assert_eq!(
            merge_text_lines(Some(boxes), 2, 2, 0.75),
            Ok(vec![[0, 0, 12, 13]])
        );
        assert_eq!(
            merge_text_lines(Some(vec![[i64::MAX, 0, 1, 1]]), 0, 0, 1.0),
            Err(BOXES.into())
        );
    }

    #[test]
    fn reading_order_handles_large_centers_and_ties_by_index() {
        let boxes = vec![[2, i64::MAX - 8, 6, 3], [4, 0, 4, 5], [4, 0, 4, 5]];
        assert_eq!(
            sort_reading_order(Some(boxes), Some(true), i64::MAX),
            Ok(vec![0, 1, 2])
        );
    }

    #[test]
    fn stroke_median_uses_both_axes_and_half_values() {
        assert_eq!(
            estimate_stroke_width(Some(&[0, 0, 0, 255]), 2, 2, Some([0, 0, 2, 2])),
            Ok(1.5)
        );
        assert_eq!(
            estimate_stroke_width(Some(&[8, 31]), 2, 1, Some([0, 0, 2, 1])),
            Ok(0.0)
        );
        assert_eq!(
            estimate_stroke_width(Some(&[8, 32]), 2, 1, Some([0, 0, 2, 1])),
            Ok(1.0)
        );
    }
}
