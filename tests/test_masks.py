"""Masks — what may be repainted, and what may not.

The mask is the only thing standing between a translation and a damaged page,
so these tests are about what it must *not* cover as much as what it must.
"""

from __future__ import annotations

import numpy as np

import masks
import pageir as ir


def test_a_mask_is_written_for_every_region(detected):
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    for _, region in ir.iter_regions(doc):
        assert region["mask"], f"{region['id']} has no mask"
        assert (root / region["mask"]).exists()
        assert region["mask_box"][2] > 0 and region["mask_box"][3] > 0


def test_a_mask_covers_the_lettering(detected):
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    rgb = np.asarray(ir.load_image(root / page["image"]))

    for region in page["regions"]:
        if region["kind"] != "speech":
            continue
        mask = masks.load_mask(root / region["mask"])
        mx, my = region["mask_box"][0], region["mask_box"][1]
        # The lettering is the ink inside the text box *and* inside the balloon.
        # A balloon is an ellipse, so the corners of its text box fall outside
        # it — on a page with screentone behind the balloon that is artwork, and
        # the mask is right to leave it alone.
        interior = masks.balloon_interior(
            rgb, region["balloon"], region.get("polarity", "light"),
            (page["width"], page["height"]), inset=masks.OUTLINE_INSET,
        )
        tx, ty, tw, th = region["bbox"]
        window = rgb[ty:ty + th, tx:tx + tw]
        ink = (window.min(axis=2) < 100) & (interior[ty:ty + th, tx:tx + tw] > 0)
        covered_mask = mask[ty - my:ty - my + th, tx - mx:tx - mx + tw]
        # Nearly all of it has to be inside the mask; the few stragglers are the
        # anti-aliased edge of a glyph.
        covered = (covered_mask[ink] > 0).mean() if ink.any() else 1.0
        assert covered > 0.98, f"{region['id']} leaves {1 - covered:.0%} of its ink"


def test_the_balloon_outline_is_never_inside_a_mask(detected):
    """Clipping to the balloon's bounding box repaints the corners of the box,
    which is outside the balloon, and erases the outline that crosses them."""
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    union = masks.load_mask(root / page["mask"])

    for region in page["regions"]:
        balloon = region.get("balloon")
        if not balloon:
            continue
        x, y, w, h = (int(v) for v in balloon)
        ring = np.zeros(union.shape, bool)
        ring[y:y + h, x:x + w] = True
        inset = max(3, int(0.02 * min(w, h)))
        ring[y + inset:y + h - inset, x + inset:x + w - inset] = False
        assert not (union[ring] > 0).any(), (
            f"{region['id']} would repaint the rim of its own balloon"
        )


def test_the_interior_is_the_balloon_shape_not_its_box(detected):
    """The corners of a box around an ellipse are outside the balloon."""
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    rgb = np.asarray(ir.load_image(root / page["image"]))
    region = next(r for r in page["regions"] if r.get("balloon"))

    interior = masks.balloon_interior(
        rgb, region["balloon"], region.get("polarity", "light"),
        (page["width"], page["height"]),
    )
    x, y, w, h = (int(v) for v in region["balloon"])
    box_area = w * h
    covered = int((interior > 0).sum())
    # An inscribed ellipse is pi/4 of its box; anything near 1.0 means the box
    # was used and the corners went with it.
    assert 0.6 * box_area < covered < 0.92 * box_area


def test_the_union_is_the_union(detected):
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    union = masks.load_mask(root / page["mask"])

    total = np.zeros_like(union)
    for region in page["regions"]:
        mask = masks.load_mask(root / region["mask"])
        x, y, w, h = region["mask_box"]
        total[y:y + h, x:x + w] = np.maximum(total[y:y + h, x:x + w], mask)
    assert np.array_equal(total, union)


def test_coverage_stays_small_on_an_ordinary_page(detected):
    doc = ir.load_doc(detected)
    for page in doc["pages"]:
        assert page["mask_coverage"] < 0.15, (
            f"{page['id']} would repaint {page['mask_coverage']:.0%} of the artwork"
        )


def test_excessive_coverage_is_reported(detected):
    """A region that matched artwork rather than lettering must be surfaced
    before cleaning, not discovered in the finished file.

    Note what it takes to provoke: growing the mask is not enough, because a
    balloon's mask is clipped to the balloon and cannot spread past it. It takes
    a detection that was wrong about where the text is.
    """
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    page["regions"].append(
        ir.new_region(f"{page['id']}r900", [10, 10, 900, 1400], kind="sfx")
    )
    ir.save_doc(doc, detected)

    report = masks.build_document(detected, grow=0.01)
    assert "p0001" in report["excessive_coverage"]
    assert "28%" in report["warning"]
