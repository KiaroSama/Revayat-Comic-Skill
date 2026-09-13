"""A page whose lettering is real Japanese, all the way through.

Every other fixture in this suite draws lettering as blocks of rectangles, for
the reasons `tests_support` gives: the detector measures geometry, and a CJK
font is not on a stock CI runner. That is right for the default fixtures and it
has one blind spot, which this file exists to cover — **a rectangle is one
connected component and a Japanese character is often several.**

ド is ト plus two tiny dakuten. ン is two strokes. So a three-character effect
arrives at the detector as six marks of two very different sizes, and the
size-uniformity test that is supposed to be the strongest of the three scores
3/6 and throws it away. Measured here before it was fixed: the whole ドカン was
invisible while both balloons on the same page were found at 0.80.

Skips, rather than fails, on a machine with no CJK font — the same shape as the
RAQM and unrar skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import clean
import detect
import masks
import pageir as ir
import readers
import typeset
import worksheet
from tests_support import japanese_page

pytestmark = pytest.mark.skipif(
    japanese_page() is None,
    reason="no CJK font on this machine; nothing to draw real Japanese with")


@pytest.fixture
def japanese_chapter(tmp_path):
    """One real-Japanese page, imported as a right-to-left chapter."""
    folder = tmp_path / "src"
    folder.mkdir()
    japanese_page().save(folder / "001.png")
    report = readers.import_source(folder, tmp_path / "work",
                                   source_language="ja", direction="rtl")
    return Path(report["document"])


def test_a_japanese_page_gives_up_its_text_and_its_effect(japanese_chapter):
    """Every piece of lettering on the page, and the column read as a column.

    The column is the one that matters: it is the case `orientation` exists
    for, and it is measured from the ink rather than assumed from the language.

    **What is asserted is what the page contains, not how many balloons the
    detector recognised around it** — and that is a measured decision, not a
    convenience. The balloon around the column is found on every face with the
    right area, the right smallest side and the right solidity; what differs is
    how much of a thin face's ink survives being filled into the interior
    before the share is measured. On Noto Sans CJK it is 0.19% against a 1.5%
    floor. That is the detector meeting the face, and making it
    face-independent means changing balloon detection — a closed finding here,
    with eleven measurements and 119 labelled balloons behind it: the page does
    not carry the information locally, and the best any method reached was
    F1 0.57.

    `test_the_vertical_balloon_is_drawn_as_a_balloon` below holds the half this
    fixture does control.
    """
    totals = detect.detect_document(japanese_chapter)["totals"]
    doc = ir.load_doc(japanese_chapter)
    regions = doc["pages"][0]["regions"]
    # What was found, in the failure message: a bare `assert 1 == 2` says
    # nothing about WHICH piece of lettering a runner lost.
    found = ", ".join(
        f"{region['kind']}/{region['orientation']} at {region['bbox']} "
        f"conf={region.get('confidence', 0):.2f}"
        for region in regions)
    where = f"{totals} — {found}"

    assert totals["panels"] == 4, where
    # Three pieces of lettering: the column, the horizontal line, the effect.
    # None of them may go missing, whatever kind each is classified as.
    assert totals["regions"] == 3, where

    tall = [r for r in regions if r["orientation"] == "vertical"]
    wide = [r for r in regions if r["orientation"] == "horizontal"]
    assert tall, f"the column read across: {where}"
    assert len(wide) == 2, where
    column = tall[0]
    assert column["bbox"][3] > 2 * column["bbox"][2], where

    # A page of Japanese where NOTHING reads as speech is a detector
    # regression, and that part does not depend on the face.
    assert totals["speech"] >= 1, where


def test_the_dakuten_does_not_cost_the_effect_its_detection():
    """THE REGRESSION, at the level it actually happens.

    Measured on the fixture's own katakana: six components, three around 85 px
    and three around 20 px. Without absorbing the small ones into the strokes
    they belong to, uniformity is 3/6 = 0.50 against a threshold of 0.80.
    """
    options = dict(detect.DEFAULTS)
    katakana = [[0, 0, 84, 88], [96, 0, 75, 90], [190, 4, 52, 86],
                [86, 2, 26, 24], [70, 6, 20, 19], [176, 8, 19, 17]]

    assert detect._looks_like_lettering(katakana, options)

    folded = detect._absorb_satellites(katakana)
    assert len(folded) == 3, "a dakuten was left standing as its own glyph"

    # And the merge cannot invent a cluster: three specks with nothing to
    # belong to stay three specks, and three is still too few to be uniform
    # against a large neighbour.
    specks = [[0, 0, 20, 19], [400, 300, 22, 20], [800, 700, 19, 17]]
    assert detect._absorb_satellites(specks) == [list(b) for b in specks]


def test_a_japanese_chapter_reaches_a_finished_page(japanese_chapter):
    """The whole pipeline, on Japanese: detect, mask, transcribe, translate,
    clean and set the Persian — and the artwork outside the masks is the
    artwork that came in."""
    detect.detect_document(japanese_chapter)
    masks.build_document(japanese_chapter)
    worksheet.build_document(japanese_chapter)

    doc = ir.load_doc(japanese_chapter)
    page = doc["pages"][0]
    persian = {"speech": "بس کن",       # بس کن
               "sfx": "دوم"}                  # دوم
    for region in page["regions"]:
        region["source_text"] = "やめろ"
        region["target_text"] = persian.get(region["kind"], persian["speech"])
        region["locked"] = True
    doc["meta"]["sfx_policy"] = "translate"
    ir.save_doc(doc, japanese_chapter)

    clean.clean_document(japanese_chapter)
    report = typeset.typeset_document(japanese_chapter)
    assert report["pages"], "no page was written"

    import qa

    gate = qa.check_document(japanese_chapter)
    assert gate["stats"]["artwork_pixels_changed"] == 0
    assert "artwork-modified" not in gate["by_code"]


def test_the_column_is_taller_than_it_is_wide(japanese_chapter):
    """Sanity on the fixture itself. A vertical balloon whose ink is wider than
    it is tall is not vertical, and every orientation claim above would be
    measuring the wrong thing."""
    detect.detect_document(japanese_chapter)
    doc = ir.load_doc(japanese_chapter)
    column = next(r for r in doc["pages"][0]["regions"]
                  if r["orientation"] == "vertical")
    _, _, width, height = column["bbox"]
    assert height > width * 1.5


def test_the_vertical_balloon_is_drawn_as_a_balloon():
    """The half of it this fixture controls.

    A thin column of hiragana in a tall ellipse is the tight case for balloon
    detection, and this fixture has broken it twice by drawing the ellipse
    wrong: once sized from the ink, which produced a 57-pixel sliver, and once
    padded so generously that the interior was mostly paper.

    So: the component around the column must exist with valid balloon geometry
    — area, smallest side, solidity — on whatever face the runner has. The ink
    share is REPORTED and not asserted: how much of a face's ink survives being
    filled into the interior is the detector's number, and on Noto Sans CJK it
    is 0.19% where here it is over 4%.
    """
    import cv2
    import numpy as np

    page = japanese_page()
    gray = cv2.cvtColor(np.asarray(page), cv2.COLOR_RGB2GRAY)
    height, width = gray.shape[:2]
    options = detect.DEFAULTS

    _, light = cv2.threshold(gray, 0, 255,
                             cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    solid = detect._fill_lettering(
        light, np, options["glyph_max"] * min(height, width))
    count, labels, stats = detect._components(solid, np)

    seen, report = [], []
    for label in range(1, count):
        x, y, w, h, area = (int(stats[label][index]) for index in range(5))
        # In the first panel, taller than wide, and not the panel itself.
        if not (x < width // 2 and y < height // 2 and h > w and 100 < h < 400):
            continue
        interior = (labels[y:y + h, x:x + w] == label)
        window = gray[y:y + h, x:x + w]
        share = float((window[interior] < 128).sum()) / max(
            1.0, float(interior.sum()))
        geometry = {
            "area": (options["balloon_min_area"] * height * width
                     <= area <= options["balloon_max_area"] * height * width),
            "min_side": min(w, h) >= max(
                12.0, options["balloon_min_side"] * min(height, width)),
            "solidity": area / float(w * h) >= options["balloon_min_solidity"],
        }
        report.append(f"[{x},{y},{w},{h}] area={area} "
                      f"solidity={area / (w * h):.3f} ink={share:.4f} "
                      f"geometry_failed="
                      f"{sorted(k for k, ok in geometry.items() if not ok)}")
        if all(geometry.values()):
            seen.append(share)

    assert seen, ("no balloon-shaped component around the vertical column; "
                  + " | ".join(report or ["nothing tall in the first panel"]))
    print(f"column balloon ink share: {max(seen):.4f} "
          f"(detector floor {options['ink_min']})")
