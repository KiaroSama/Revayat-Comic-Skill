"""Deterministic visual QA checks for balloon ink, overlap, outlines, and dimensions.

Extracted into a cohesive helper module so `qa.py` stays well below the 800-line
ceiling while enforcing hard visual gates for:
- `source-text-survived` across the FULL inset balloon interior
- `rendered-text-overlap` between any two typeset regions on a page
- `text-crosses-outline` when Persian glyphs cross dark outlines or screentone
- `page-dimension-mismatch` when cleaned/final pages diverge from original W x H
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import masks as mask_tools
import pageir as ir
import pixcore


def reconcile_image_dimensions(image, target_size: tuple[int, int], *, max_aspect_drift: float = 0.08):
    """Return `image` at exact `target_size = (W, H)` without stretching artwork.

    If the image already matches `target_size`, returns it unchanged. If its
    aspect ratio is within `max_aspect_drift` of the original page (e.g. a
    generative editor returning `1024x1536` for a `1050x1500` page), resamples
    with Lanczos to exact `(W, H)`. Raises `ValueError` if aspect drift is too
    large so artwork is never distorted silently.
    """
    from PIL import Image

    tw, th = int(target_size[0]), int(target_size[1])
    sw, sh = int(image.width), int(image.height)
    if (sw, sh) == (tw, th):
        return image
    if sw <= 0 or sh <= 0 or tw <= 0 or th <= 0:
        raise ValueError(f"invalid image dimensions {(sw, sh)} -> {(tw, th)}")

    target_ratio = tw / th
    source_ratio = sw / sh
    drift = abs(source_ratio - target_ratio) / target_ratio
    if drift > max_aspect_drift:
        raise ValueError(
            f"external image aspect ratio {sw}x{sh} ({source_ratio:.3f}) drifts "
            f"{drift:.1%} from original {tw}x{th} ({target_ratio:.3f})"
        )
    return image.resize((tw, th), Image.Resampling.LANCZOS)


def check_page_dimensions(
    original_path: Path,
    cleaned_path: Path | None,
    final_path: Path | None,
) -> list[tuple[str, str]]:
    """Return `(stage, detail)` mismatches if cleaned or final sizes differ from original."""
    mismatches: list[tuple[str, str]] = []
    if not original_path.exists():
        return mismatches
    from PIL import Image

    with Image.open(original_path) as orig:
        expected = orig.size
    for label, path in (("clean", cleaned_path), ("final", final_path)):
        if path is None or not path.exists():
            continue
        with Image.open(path) as img:
            actual = img.size
        if actual != expected:
            mismatches.append((
                label,
                f"{label} image dimensions {actual[0]}x{actual[1]} do not match "
                f"original {expected[0]}x{expected[1]}",
            ))
    return mismatches


def full_balloon_surviving_ink(
    original,
    cleaned,
    region: dict[str, Any],
    sibling_regions: list[dict[str, Any]],
    mask,
    page_size: tuple[int, int],
    np,
) -> float:
    """Share of original dark ink still surviving anywhere inside the FULL inset
    balloon interior (excluding sibling active regions' mask boxes)."""
    balloon = region.get("balloon")
    if not balloon:
        return 0.0

    width, height = page_size
    bx, by, bw, bh = ir.clamp_bbox(balloon, width, height)
    if bw < 6 or bh < 6:
        return 0.0

    interior = mask_tools.balloon_interior(
        cleaned,
        balloon,
        region.get("polarity", "light"),
        page_size,
        inset=mask_tools.OUTLINE_INSET,
        seed_box=region.get("bbox"),
    )
    in_balloon = interior[by:by + bh, bx:bx + bw] > 0
    if int(in_balloon.sum()) < 24:
        return 0.0

    # Exclude sibling active regions inside a shared twin balloon so we don't
    # blame region A for ink owned by region B.
    excl = np.zeros((bh, bw), dtype=bool)
    rid = region.get("id")
    for other in sibling_regions:
        if other.get("id") == rid or other.get("dropped"):
            continue
        ob = other.get("mask_box") or other.get("bbox")
        if not ob:
            continue
        ox, oy, ow, oh = ir.clamp_bbox(ob, width, height)
        x0 = max(bx, ox) - bx
        y0 = max(by, oy) - by
        x1 = min(bx + bw, ox + ow) - bx
        y1 = min(by + bh, oy + oh) - by
        if x1 > x0 and y1 > y0:
            excl[y0:y1, x0:x1] = True

    active_interior = in_balloon & ~excl
    if int(active_interior.sum()) < 24:
        return 0.0

    before = original[by:by + bh, bx:bx + bw].astype(np.int16).mean(axis=2)
    after = cleaned[by:by + bh, bx:bx + bw].astype(np.int16).mean(axis=2)

    # Estimate flat balloon paper tone from the cleaned interior.
    paper = float(np.median(after[active_interior]))
    orig_ink = (np.abs(before - paper) > 100) & active_interior
    total_ink = int(orig_ink.sum())
    if total_ink < 12:
        return 0.0

    # Ink that is still dark inside the interior. Exclude dark connected
    # components touching the boundary of `active_interior` because open-edge
    # balloons often border speedlines, hair tips, or panel frames that `clean`
    # rightly preserved; genuine leftover lettering floats inside the paper.
    still_dark = (np.abs(after - paper) > 100) & orig_ink
    if still_dark.any():
        import cv2
        boundary = active_interior & ~(
            cv2.erode(active_interior.astype(np.uint8) * 255, np.ones((3, 3), np.uint8)) > 0
        )
        n_cc, cc_labels = cv2.connectedComponents(still_dark.astype(np.uint8), connectivity=8)
        interior_still = np.zeros_like(still_dark)
        for idx in range(1, n_cc):
            comp = cc_labels == idx
            if not (comp & boundary).any():
                interior_still |= comp
        still_dark = interior_still
    return float(int(still_dark.sum()) / total_ink)


def _region_rendered_box(region: dict[str, Any], page_size: tuple[int, int]) -> list[int] | None:
    """Return `[x, y, w, h]` rendered text footprint for an `ok` typeset region."""
    ts = region.get("typeset") or {}
    if ts.get("status") != "ok":
        return None
    ink_box = ts.get("ink_box")
    if isinstance(ink_box, list) and len(ink_box) == 4 and ink_box[2] > 0 and ink_box[3] > 0:
        return ir.clamp_bbox(ink_box, page_size[0], page_size[1])
    lines = ts.get("lines") or []
    size = int(ts.get("size") or 0)
    if not lines or size <= 0:
        return None
    xs = [float(line["x"]) for line in lines if "x" in line]
    ys = [float(line["y"]) for line in lines if "y" in line]
    if not xs or not ys:
        return None
    # Conservative fallback estimate when `ink_box` wasn't stored by an older run.
    half_h = max(4, int(size * 0.55))
    half_w = max(8, int(size * 0.5))
    x0 = int(min(xs)) - half_w
    y0 = int(min(ys)) - half_h
    x1 = int(max(xs)) + half_w
    y1 = int(max(ys)) + half_h
    return ir.clamp_bbox([x0, y0, max(1, x1 - x0), max(1, y1 - y0)], page_size[0], page_size[1])


def rendered_text_overlaps(
    page: dict[str, Any],
    cleaned_rgb,
    final_rgb,
    np,
) -> list[tuple[str, str, int]]:
    """Detect pairs of active typeset regions whose rendered Persian text collides.

    Returns list of `(region_a_id, region_b_id, overlap_pixels)`.
    """
    page_size = (int(page["width"]), int(page["height"]))
    boxes: list[tuple[str, list[int]]] = []
    for region in page.get("regions", []):
        if region.get("dropped"):
            continue
        rbox = _region_rendered_box(region, page_size)
        if rbox is not None:
            boxes.append((region["id"], rbox))

    if len(boxes) < 2:
        return []

    if pixcore.BACKEND == "rust" and final_rgb.ndim == 3 and final_rgb.shape[2] == 3:
        height, width = int(final_rgb.shape[0]), int(final_rgb.shape[1])
        changed_bytes = pixcore.changed_mask_rgb(
            np.ascontiguousarray(cleaned_rgb, dtype=np.uint8).tobytes(),
            np.ascontiguousarray(final_rgb, dtype=np.uint8).tobytes(),
            width,
            height,
            20,
        )
        hits = pixcore.overlap_changed_pixels(
            changed_bytes,
            width,
            height,
            [[int(v) for v in rbox] for _, rbox in boxes],
        )
        return [(boxes[i][0], boxes[j][0], int(count)) for i, j, count in hits]

    changed = np.abs(
        final_rgb.astype(np.int16) - cleaned_rgb.astype(np.int16)
    ).max(axis=2) > 20

    collisions: list[tuple[str, str, int]] = []
    for i in range(len(boxes)):
        id_a, (ax, ay, aw, ah) = boxes[i]
        ax1, ay1 = ax + aw, ay + ah
        for j in range(i + 1, len(boxes)):
            id_b, (bx, by, bw, bh) = boxes[j]
            ix0 = max(ax, bx)
            iy0 = max(ay, by)
            ix1 = min(ax1, bx + bw)
            iy1 = min(ay1, by + bh)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            ink_overlap = int(changed[iy0:iy1, ix0:ix1].sum())
            if ink_overlap > 0:
                collisions.append((id_a, id_b, ink_overlap))
    return collisions


BALLOON_TEXT_KINDS = frozenset({"speech", "thought", "narration"})
BALLOON_TEXT_INSET = 0.045


def _erode_interior(mask, radius: int):
    cv2, np = mask_tools._cv2(), mask_tools._numpy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    return cv2.erode(mask, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(np.uint8)


def local_white_enclosure(cleaned_rgb, bbox, polarity, page_size, inset=BALLOON_TEXT_INSET, *, panel=None):
    """Find seeded paper bounded by walls and at most two panel or page edges."""
    cv2, np = mask_tools._cv2(), mask_tools._numpy()
    width, height = page_size
    px, py, pw, ph = ir.clamp_bbox(panel or (0, 0, width, height), width, height)
    entire = (px, py, px + pw, py + ph)
    x, y, w, h = ir.clamp_bbox(ir.bbox_intersection(bbox, (px, py, pw, ph)), width, height)
    if not w or not h:
        return None
    pad = max(w, h, 32)
    nearby = (max(px, x - pad), max(py, y - pad), min(px + pw, x + w + pad), min(py + ph, y + h + pad))
    for left, top, right, bottom in dict.fromkeys((nearby, entire)):
        crop = cleaned_rgb[top:bottom, left:right]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if polarity == "dark":
            gray = 255 - gray
        paper = (gray >= 215).astype(np.uint8)
        _, labels, stats, _ = cv2.connectedComponentsWithStats(paper, connectivity=4)
        seed = labels[y - top:y - top + h, x - left:x - left + w]
        counts = np.bincount(seed.ravel())
        if len(counts) < 2:
            return None
        component = 1 + int(counts[1:].argmax())
        bx, by, bw, bh, area = (int(n) for n in stats[component])
        if area >= 0.22 * width * height:
            return None
        edges = (bx == 0, by == 0, bx + bw == right - left, by + bh == bottom - top)
        if any(edge and a != b for edge, a, b in zip(edges, (left, top, right, bottom), entire)):
            continue
        opened = sum(edges)
        if opened > 2:
            return None
        inside = (labels == component).astype(np.uint8)
        ring = cv2.dilate(inside, np.ones((3, 3), np.uint8)) > inside
        wall_luma = 215 if opened else 190
        if not ring.any() or np.count_nonzero((gray < wall_luma) & ring) < 0.55 * ring.sum():
            return None
        if opened:
            # A clip edge is not a wall. Outside the crop counts as paper during erosion.
            radius = max(1, round(inset * min(bw, bh)))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
            safe = cv2.erode(inside, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=1)
        else:
            safe = _erode_interior(inside, max(5, round(inset * min(bw, bh))))
        result = np.zeros((height, width), np.uint8)
        result[top:bottom, left:right] = safe * 255
        return result if safe.any() else None
    return None


def balloon_text_interior(cleaned_rgb, region, page_size, *, panel=None):
    """Use the same wall clearance for fitting and the artwork check."""
    polarity = region.get("polarity", "light")
    bbox = region.get("bbox")
    balloon = region.get("balloon")
    if balloon:
        x, y, w, h = ir.clamp_bbox(balloon, *page_size)
        interior = mask_tools.balloon_interior(cleaned_rgb, balloon, polarity, page_size, seed_box=bbox)
        if w and h:
            interior[y:y + h, x:x + w] = _erode_interior(
                interior[y:y + h, x:x + w], max(5, round(BALLOON_TEXT_INSET * min(w, h))))
        return interior
    if bbox and region.get("kind") in BALLOON_TEXT_KINDS:
        return local_white_enclosure(cleaned_rgb, bbox, polarity, page_size, panel=panel)
    return None


def text_crosses_outline(
    page: dict[str, Any],
    original_rgb,
    cleaned_rgb,
    final_rgb,
    np,
    *,
    max_stray_pixels: int = 2,
) -> list[tuple[str, int]]:
    """Count newly painted ink outside an enclosure on original non-paper pixels."""
    page_size = (int(page["width"]), int(page["height"]))
    use_rust = pixcore.BACKEND == "rust" and final_rgb.ndim == 3 and final_rgb.shape[2] == 3
    orig_b = clean_b = final_b = None
    orig_gray = changed = None
    if not use_rust:
        orig_gray = original_rgb.astype(np.int16).mean(axis=2)
        changed = np.abs(
            final_rgb.astype(np.int16) - cleaned_rgb.astype(np.int16)
        ).max(axis=2) > 25

    offenders: list[tuple[str, int]] = []
    panels = {panel["id"]: panel["bbox"] for panel in page.get("panels", [])}
    for region in page.get("regions", []):
        if region.get("dropped"):
            continue
        rbox = _region_rendered_box(region, page_size)
        if rbox is None:
            continue
        rx, ry, rw, rh = rbox
        if rw <= 0 or rh <= 0:
            continue

        polarity = region.get("polarity", "light")
        safe = balloon_text_interior(cleaned_rgb, region, page_size, panel=panels.get(region.get("panel")))
        if safe is None:
            continue
        if use_rust:
            if orig_b is None:
                orig_b = np.ascontiguousarray(original_rgb, dtype=np.uint8).tobytes()
                clean_b = np.ascontiguousarray(cleaned_rgb, dtype=np.uint8).tobytes()
                final_b = np.ascontiguousarray(final_rgb, dtype=np.uint8).tobytes()
            crossed = int(pixcore.outline_crossing_pixels(
                orig_b,
                clean_b,
                final_b,
                np.ascontiguousarray(safe, dtype=np.uint8).tobytes(),
                int(final_rgb.shape[1]),
                int(final_rgb.shape[0]),
                [int(rx), int(ry), int(rw), int(rh)],
                polarity == "dark",
                25,
            ))
        else:
            safe_crop = safe[ry:ry + rh, rx:rx + rw] > 0
            ink_crop = changed[ry:ry + rh, rx:rx + rw]
            outside_ink = ink_crop & ~safe_crop
            if not outside_ink.any():
                continue

            orig_crop = orig_gray[ry:ry + rh, rx:rx + rw]
            if polarity == "dark":
                non_paper = orig_crop > 40
            else:
                non_paper = orig_crop < 215
            crossed = int((outside_ink & non_paper).sum())
        if crossed > max_stray_pixels:
            offenders.append((region["id"], crossed))
    return offenders
