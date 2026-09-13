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


def test_a_japanese_page_gives_up_its_balloons_and_its_effect(japanese_chapter):
    """Both balloons and the drawn effect, on a page drawn with a real face.

    The column is the one that matters: it is the case `orientation` exists
    for, and it is measured from the ink rather than assumed from the language.

    The counts were briefly weakened to "three pieces of lettering, one of them
    a balloon", because the vertical balloon was found on one machine's face
    and not on another's. That was a real detector defect, not a fact about
    Japanese, and it is fixed:
    `test_a_balloon_full_of_thin_strokes_is_still_a_balloon` below holds it.
    """
    totals = detect.detect_document(japanese_chapter)["totals"]
    doc = ir.load_doc(japanese_chapter)
    regions = doc["pages"][0]["regions"]
    # What was found, in the failure message: a bare `assert 1 == 2` says
    # nothing about WHICH balloon a runner lost.
    found = ", ".join(
        f"{region['kind']}/{region['orientation']} at {region['bbox']} "
        f"conf={region.get('confidence', 0):.2f}"
        for region in regions)
    where = f"{totals} — {found}"

    assert totals["panels"] == 4, where
    assert totals["speech"] == 2, where
    assert totals["sfx"] == 1, f"the katakana effect was not found: {where}"

    orientations = {r["id"]: r["orientation"] for r in regions
                    if r["kind"] == "speech"}
    assert "vertical" in orientations.values(), f"the column read across: {where}"
    assert "horizontal" in orientations.values(), where


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


def _lightened(page, keep: float):
    """The same page with its lettering thinned to `keep` of its ink.

    Not "eroded by N pixels": N pixels off a heavy gothic face is a light face,
    and N pixels off an already-light one is a blank page — which is exactly
    what a fixed kernel did when this test first ran on a runner carrying Noto
    Sans CJK. Thinning to a share of the original ink is the same condition
    whatever face the machine has.

    Returns `(page, achieved share)`; the caller asserts against a page it
    knows the weight of.
    """
    import cv2
    import numpy as np
    from PIL import Image

    array = np.asarray(page.convert("L"))
    ink = np.where(array < 128, np.uint8(255), np.uint8(0))
    total = float(ink.sum()) or 1.0

    best, achieved = ink, 1.0
    for size in range(2, 10):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        thinner = cv2.erode(ink, kernel)
        share = float(thinner.sum()) / total
        if share < keep:
            break
        best, achieved = thinner, share

    out = np.asarray(page.convert("RGB")).copy()
    out[ink > 0] = 255                      # lift every mark off the page
    out[best > 0] = 0                       # and put the thinned ones back
    return Image.fromarray(out), achieved


@pytest.mark.parametrize("keep", [1.0, 0.6, 0.4])
def test_a_balloon_full_of_thin_strokes_is_still_a_balloon(keep):
    """THE REGRESSION, at the level it actually happens.

    `_fill_lettering` absorbs a hole into the balloon interior only when its
    solidity is at least 0.30, on the premise that "a letter is a solid blob".
    Hiragana are thin strokes in a square em: **four of the seven holes in this
    fixture are already under 0.30 on a heavy gothic face**, and all of them
    are under it on a light one. The letters then stayed OUTSIDE the interior,
    the ink measured inside it was the bare paper around them, and a balloon
    that was the right size, the right shape and in the right place was
    rejected for holding 0.19% ink.

    Measured on this fixture, thinning its own strokes:

        before the fix   full weight: 0.0463   thinned: 0.00007   <- a cliff
        after            full weight: 0.0631   thinned: 0.0280

    `_balloon_candidates` asks for the component PLUS what it encloses now,
    which is what a balloon's interior means and needs no threshold at all.
    """
    import cv2
    import numpy as np

    page = japanese_page()
    if keep < 1.0:
        page, achieved = _lightened(page, keep)
        assert achieved <= 1.0
    gray = cv2.cvtColor(np.asarray(page.convert("RGB")), cv2.COLOR_RGB2GRAY)

    column = [balloon
              for balloon in detect._balloon_candidates(
                  gray, detect.DEFAULTS, invert=False)
              # The first panel, and taller than it is wide.
              if balloon["bbox"][0] < page.width // 2
              and balloon["bbox"][1] < page.height // 2
              and balloon["bbox"][3] > balloon["bbox"][2]]

    assert column, (
        f"the column's balloon disappeared with its strokes thinned to "
        f"{keep:.0%} of their ink; a lighter face is not a missing balloon")
    assert column[0]["ink_share"] >= detect.DEFAULTS["ink_min"], column


def test_the_interior_of_a_balloon_includes_what_it_encloses():
    """The mechanism, on a shape with a known answer.

    A ring of ink around a square of paper with one blob in it: the interior is
    the paper AND the blob, never the paper alone.
    """
    import numpy as np

    region = np.zeros((40, 40), bool)
    region[5:35, 5:35] = True
    region[15:25, 15:25] = False          # a letter-shaped hole

    filled = detect._enclosed(region, np)

    assert filled[20, 20], "the hole was not counted as inside"
    assert filled.sum() == 30 * 30
    assert not filled[2, 2], "something outside the region was swallowed"
