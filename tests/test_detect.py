"""Detection. Each test here corresponds to a defect that actually shipped.

The fixture draws three balloons and one sound effect per page, so the counts
are known and a regression shows up as a number rather than as a judgement.
"""

from __future__ import annotations

import numpy as np
import pytest

import detect
import pageir as ir


@pytest.fixture(scope="module")
def found(tmp_path_factory):
    from tests_support import manga_page, page_bytes

    path = tmp_path_factory.mktemp("detect") / "p.png"
    path.write_bytes(page_bytes(manga_page()))
    return detect.detect_page(path)


def _speech(found):
    return [r for r in found["regions"] if r["kind"] == "speech"]


def _sfx(found):
    return [r for r in found["regions"] if r["kind"] == "sfx"]


def test_every_drawn_balloon_is_found(found):
    assert len(_speech(found)) == 3


def test_a_balloon_box_is_the_lettering_not_the_whole_balloon(found):
    """The text box has to hug the letters. A box that is the balloon makes the
    mask erase the outline and the artwork in the corners behind it."""
    for region in _speech(found):
        text, balloon = region["bbox"], region["balloon"]
        assert ir.bbox_area(text) < 0.85 * ir.bbox_area(balloon)
        assert ir.bbox_contains(balloon, text, slack=0.98)


def test_the_page_gutters_split_into_four_panels(found):
    assert len(found["panels"]) == 4


def test_a_panel_interior_is_not_reported_as_a_balloon(found):
    """A panel is also a light region inside an outline. On a sparse page the
    two are indistinguishable except by size and by coinciding with a panel."""
    for region in _speech(found):
        for panel in found["panels"]:
            assert ir.bbox_iou(region["balloon"], panel) <= 0.65


def test_white_balloons_survive_the_lettering_fill():
    """Closing the white mask dilates across the outline and welds the balloon
    to the page background, and every white balloon disappears. Hole filling by
    solidity does not."""
    from tests_support import manga_page

    import cv2

    gray = cv2.cvtColor(np.asarray(manga_page()), cv2.COLOR_RGB2GRAY)
    _, light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    filled = detect._fill_lettering(light, np, 0.22 * 1000)

    count, labels, stats = detect._components(filled, np)
    page_area = gray.size
    # At least three components that are balloon-sized and not the whole page.
    balloon_like = [
        label for label in range(1, count)
        if 0.001 * page_area < stats[label][4] < 0.13 * page_area
    ]
    assert len(balloon_like) >= 3


def test_the_gaps_between_letters_are_not_tiny_balloons():
    """Without a size floor every line of text sprouts three dark 'balloons'."""
    from tests_support import manga_page

    import cv2

    gray = cv2.cvtColor(np.asarray(manga_page()), cv2.COLOR_RGB2GRAY)
    dark = detect._balloon_candidates(gray, detect.DEFAULTS, True)
    floor = detect.DEFAULTS["balloon_min_side"] * 1000
    assert all(min(c["bbox"][2], c["bbox"][3]) >= floor for c in dark)


def test_free_lettering_is_found_and_marked_uncertain(found):
    sfx = _sfx(found)
    assert len(sfx) >= 1
    assert all(region["confidence"] < 0.5 for region in sfx)


def test_the_sound_effect_is_one_region_not_four(found):
    """Clustering has to scale with the letters. A fixed reach tuned for small
    dialogue type leaves a large sound effect as separate blobs and drops it."""
    sfx = _sfx(found)
    widest = max(region["bbox"][2] for region in sfx)
    assert widest > 150


def test_clustering_joins_close_marks_and_separates_far_ones():
    near = detect._cluster([[0, 0, 40, 50], [70, 0, 40, 50]])
    assert len(near) == 1
    far = detect._cluster([[0, 0, 40, 50], [900, 0, 40, 50]])
    assert len(far) == 2


def test_clustering_is_bounded_on_a_page_full_of_noise():
    seeds = [[i * 3, j * 3, 6, 6] for i in range(40) for j in range(40)]
    assert len(seeds) > detect.MAX_SEEDS
    detect._cluster(seeds)  # must not take quadratic time in 1600 seeds


def test_dark_balloons_are_detected_with_the_other_polarity(tmp_path):
    from tests_support import manga_page, page_bytes

    path = tmp_path / "dark.png"
    path.write_bytes(page_bytes(manga_page(dark_balloon=True)))
    result = detect.detect_page(path)
    speech = [r for r in result["regions"] if r["kind"] == "speech"]
    assert len(speech) == 3
    assert all(region["polarity"] == "dark" for region in speech)


def test_detection_numbers_regions_and_assigns_panels(detected):
    doc = ir.load_doc(detected)
    for page in doc["pages"]:
        assert page["regions"]
        assert all(region["id"].startswith(page["id"]) for region in page["regions"])
        speech = [r for r in page["regions"] if r["kind"] == "speech"]
        assert all(region["panel"] for region in speech)


def test_a_reviewed_page_is_not_re_detected(detected):
    """Re-detecting renumbers regions, which silently re-points every worksheet
    already written against the old ids."""
    doc = ir.load_doc(detected)
    doc["pages"][0]["regions"][0]["locked"] = True
    kept = [region["id"] for region in doc["pages"][0]["regions"]]
    ir.save_doc(doc, detected)

    report = detect.detect_document(detected)
    assert report["pages"][0] == {"page": "p0001", "skipped": "locked"}
    after = ir.load_doc(detected)
    assert [r["id"] for r in after["pages"][0]["regions"]] == kept


def test_sfx_can_be_switched_off(sample_page):
    result = detect.detect_page(sample_page, find_sfx=False)
    assert not [r for r in result["regions"] if r["kind"] == "sfx"]


def _fill_lettering_naive(mask, np, max_side):
    """The shape the fill had before it was vectorised, kept as the reference."""
    import cv2

    height, width = mask.shape
    canvas = np.zeros((height + 2, width + 2), np.uint8)
    canvas[1:-1, 1:-1] = mask
    flooded = canvas.copy()
    scratch = np.zeros((height + 4, width + 4), np.uint8)
    cv2.floodFill(flooded, scratch, (0, 0), 255)
    holes = cv2.bitwise_not(flooded)[1:-1, 1:-1]

    count, labels, stats = detect._components(holes, np)
    keep = np.zeros_like(mask)
    for label in range(1, count):
        x, y, w, h, area = (int(stats[label][index]) for index in range(5))
        if max(w, h) > max_side:
            continue
        if area / float(max(1, w * h)) < 0.30:
            continue
        keep[labels == label] = 255
    return cv2.bitwise_or(mask, keep)


@pytest.mark.timeout(60)
def test_the_lettering_fill_is_the_same_answer_and_not_page_squared():
    """Painting each kept hole with `keep[labels == label] = 255` scans the whole
    page once per hole, and a page of screentone has thousands of them.

    Measured on a real 1897x2702 scan: this one function was **419 s of a 420 s
    page**, so a 191-page volume would have taken most of a day. Vectorised it is
    0.25 s, for the same twelve balloons. The naive form is kept here as the
    reference, because the fix is only worth anything if the answer is identical.

    The fixture is deliberately small. At the size where the difference is
    obvious the *reference* cannot finish inside a test timeout, which is the
    point but not a thing to assert on.
    """
    import cv2

    page = np.full((520, 400), 255, np.uint8)
    for y in range(10, 510, 12):                 # screentone: many small holes
        for x in range(10, 390, 12):
            page[y:y + 4, x:x + 4] = 0
    # A balloon: a large thin ring that must NOT be filled, with lettering in it.
    cv2.ellipse(page, (200, 260), (120, 90), 0, 0, 360, 255, -1)
    cv2.ellipse(page, (200, 260), (120, 90), 0, 0, 360, 0, 3)
    for index in range(4):
        x = 130 + index * 32
        page[236:284, x:x + 18] = 0

    _, light = cv2.threshold(page, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    max_side = detect.DEFAULTS["glyph_max"] * 400

    fast = detect._fill_lettering(light, np, max_side)
    reference = _fill_lettering_naive(light, np, max_side)
    assert np.array_equal(fast, reference)
    # What the fill must not do to a balloon is
    # `test_white_balloons_survive_the_lettering_fill`, on a fixture built for it.


def test_a_region_the_reader_kept_survives_re_detection(detected):
    """A `keep: yes` is a review, so it locks the page the same way a
    translation does. Before it locked, re-running detection renumbered the
    region and the decision to leave that lettering alone simply vanished."""
    import worksheet

    doc = ir.load_doc(detected)
    region = doc["pages"][0]["regions"][0]
    worksheet._apply(region, {"keep": "yes", "src": "BUMP"},
                     {"dropped": [], "kept": [], "reclassified": [],
                      "bad_kind": []})
    ir.save_doc(doc, detected)

    detect.detect_document(detected)
    after = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert after["id"] == region["id"] and after.get("keep") is True
