"""What the gate asks about the Persian, and what a reader can settle.

Two questions that have to be answered the same way by `falint` and by `qa`,
because a translator runs one and the pipeline runs the other: which part of a
balloon is Persian at all, and what a reader has already looked at. They were
answered separately and disagreed — a long link failed a correct balloon in one
and not the other, and a waiver was permanent in one and span-bound in the
other.
"""
from __future__ import annotations

import falint
import pageir as ir
import qa


def _only_region(doc_path, **fields):
    """Put one region in a known state and save. Returns its id."""
    doc = ir.load_doc(doc_path)
    _page, region = next(iter(ir.iter_regions(doc)))
    region.update(fields)
    ir.save_doc(doc, doc_path)
    return region["id"]


def _codes(doc_path, region_id):
    return {item["code"] for item in qa.check_document(doc_path)["findings"]
            if item["where"] == region_id}


# --------------------------------------------------------------------------- #
# An address is Latin because of what it is
# --------------------------------------------------------------------------- #

def test_a_long_link_does_not_make_a_persian_balloon_untranslated(translated):
    """`falint` blanks addresses before measuring the script mix; the gate
    counted the raw target. A URL longer than the sentence around it outweighed
    the Persian and was filed as `not-persian` — asking a translator to fix
    something no edit can change."""
    region = _only_region(
        translated,
        target_text="برو به https://example.com/a/very/long/path/to/the/thing")

    assert "not-persian" not in _codes(translated, region)


def test_an_address_carrying_arabic_letters_is_still_left_alone(translated):
    """The bytes of a link are the link. Reporting the Arabic yeh inside one
    asks for an edit that produces a dead address that still looks like one."""
    region = _only_region(translated,
                          target_text="بنویس به كتاب@example.com زود")

    assert not _codes(translated, region) & {"not-persian", "typography"}


def test_an_english_sentence_is_still_caught(translated):
    """The narrowing must not switch the check off: a Latin WORD is not an
    address, and an untranslated line is exactly what this exists for."""
    region = _only_region(
        translated, target_text="I told you not to come back here again")

    assert "not-persian" in _codes(translated, region)


def test_a_balloon_of_punctuation_carries_nothing_to_translate(translated):
    """`…`, `!!!` and a bare numeral hold no word in any script."""
    region = _only_region(translated, target_text="…؟!")

    assert "not-persian" not in _codes(translated, region)


# --------------------------------------------------------------------------- #
# A decision is about the words it was taken about
# --------------------------------------------------------------------------- #

def test_a_shortened_line_is_surfaced_until_somebody_reads_both(translated):
    region = _only_region(translated, target_text="برو.",
                          target_full="از این‌جا برو و برنگرد.")

    assert "compressed-variant" in _codes(translated, region)


def test_reading_both_settles_it(translated):
    doc = ir.load_doc(translated)
    _page, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = "برو."
    region["target_full"] = "از این‌جا برو و برنگرد."
    falint.record_acknowledgement(region, ["compressed-variant"],
                                  region["target_text"])
    ir.save_doc(doc, translated)

    assert "compressed-variant" not in _codes(translated, region["id"])


def test_a_different_shortening_has_not_been_read(translated):
    """The waiver was a bare code, so one reading of one pair silenced every
    later shortening of that line for ever. A materially changed span has not
    been reviewed."""
    doc = ir.load_doc(translated)
    _page, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = "برو."
    region["target_full"] = "از این‌جا برو و برنگرد."
    falint.record_acknowledgement(region, ["compressed-variant"],
                                  region["target_text"])
    # The line is shortened differently afterwards.
    region["target_text"] = "بس کن."
    ir.save_doc(doc, translated)

    assert "compressed-variant" in _codes(translated, region["id"])


def test_a_waiver_from_before_span_records_still_stands(translated):
    """An older document is not evidence of anything wrong."""
    region = _only_region(translated, target_text="برو.",
                          target_full="از این‌جا برو و برنگرد.",
                          review_ack=["compressed-variant"])

    assert "compressed-variant" not in _codes(translated, region)
