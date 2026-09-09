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

    The column is the one that matters: it is the case `orientation` exists for,
    and it is measured from the ink rather than assumed from the language.
    """
    totals = detect.detect_document(japanese_chapter)["totals"]
    assert totals["panels"] == 4
    assert totals["speech"] == 2
    assert totals["sfx"] == 1, "the katakana effect was not found"

    doc = ir.load_doc(japanese_chapter)
    regions = doc["pages"][0]["regions"]
    orientations = {r["id"]: r["orientation"] for r in regions
                    if r["kind"] == "speech"}
    assert "vertical" in orientations.values(), "the column read as horizontal"
    assert "horizontal" in orientations.values()


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
