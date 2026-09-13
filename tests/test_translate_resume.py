"""What a resumed machine translation is a resume OF.

The stage is optional and off by default — step 5 of the skill is the reading
model, not this. What makes it worth testing carefully is that every defect
here is silent and expensive: a question answered under conditions that have
since changed still looks finished, and a question that can never be recorded
as answered is paid for on every run for ever.
"""
from __future__ import annotations

import pytest

import context as chapter_context
import pageir as ir
import providers
import translate
import worksheet
from test_worksheet import _fill, _set_fields, _sheets


class Engine:
    """A translation provider that counts what it was actually asked."""

    role = "translation"
    name = "counting"

    def __init__(self, answer="بس کن", model="m1"):
        self.answer = answer
        self.model = model
        self.calls: list[str] = []

    def translate(self, text, context=None, **_):
        self.calls.append(text)
        return self.answer


@pytest.fixture
def engine(monkeypatch):
    made = Engine()
    monkeypatch.setitem(providers._REGISTRY["translation"], "counting",
                        lambda: made)
    return made


def _sourced(doc_path, *, speaker="هاروکا"):
    """Source text on every region, no Persian anywhere."""
    doc = ir.load_doc(doc_path)
    for _page, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
        region["target_text"] = ""
        region["speaker"] = speaker
        region["locked"] = False
    ir.save_doc(doc, doc_path)
    return doc


# --------------------------------------------------------------------------- #
# Resume is a resume of THIS question
# --------------------------------------------------------------------------- #

def test_an_unchanged_rerun_costs_nothing(detected, engine):
    _sourced(detected)
    translate.translate_document(detected, provider="counting")
    first = len(engine.calls)
    assert first

    translate.translate_document(detected, provider="counting")

    assert len(engine.calls) == first, "the same question was paid for twice"


@pytest.mark.parametrize("change", ["scene", "dialogue"])
def test_changing_the_context_is_not_resumed(detected, engine, change):
    """The identity covered `constraints` only, so the scene and the previous
    pages' approved dialogue were outside the question — and editing either
    left every line translated before it looking finished."""
    _sourced(detected)
    translate.translate_document(detected, provider="counting")
    before = len(engine.calls)

    doc = ir.load_doc(detected)
    if change == "scene":
        doc["meta"]["scene"] = "شب، روی پشت‌بام، بعد از دعوا"
    else:
        first = doc["pages"][0]["regions"][0]
        first["target_text"] = "یک چیز کاملاً دیگر"
        first["locked"] = True
    ir.save_doc(doc, detected)

    translate.translate_document(detected, provider="counting")

    assert len(engine.calls) > before, "a changed context was resumed"


def test_changing_the_model_is_not_resumed(detected, engine):
    _sourced(detected)
    translate.translate_document(detected, provider="counting")
    before = len(engine.calls)

    engine.model = "m2"
    translate.translate_document(detected, provider="counting")

    assert len(engine.calls) > before, "a different model was resumed"


def test_moving_a_balloon_is_not_resumed(detected, engine):
    _sourced(detected)
    translate.translate_document(detected, provider="counting")
    before = len(engine.calls)

    doc = ir.load_doc(detected)
    doc["pages"][0]["regions"][0]["bbox"] = [11, 12, 130, 140]
    ir.save_doc(doc, detected)

    translate.translate_document(detected, provider="counting")

    assert len(engine.calls) > before, "a re-cropped balloon was resumed"


def test_a_changed_source_confirmed_to_the_same_answer_settles(detected,
                                                               engine):
    """The answer matched what was there, so nothing was written, so no record
    said the new question had been asked — and every later run paid for the
    same call again."""
    _sourced(detected)
    translate.translate_document(detected, provider="counting")

    doc = ir.load_doc(detected)
    for _page, region in ir.iter_regions(doc):
        region["source_text"] = "やめて"        # different source, same Persian
    ir.save_doc(doc, detected)

    translate.translate_document(detected, provider="counting")
    after_first = len(engine.calls)
    translate.translate_document(detected, provider="counting")

    assert len(engine.calls) == after_first, "it never settled"
    # And the human-visible value was not touched by the reconfirmation.
    # Only the regions the policy actually asks Persian of: a sound effect the
    # default policy keeps was never translated and must stay empty.
    after = ir.load_doc(detected)
    policy = after["meta"].get("sfx_policy", "keep")
    owed = [region for _page, region in ir.iter_regions(after)
            if ir.translatable(region, policy)]
    assert owed and all(region["target_text"] == engine.answer
                        for region in owed)


# --------------------------------------------------------------------------- #
# What a refused page is allowed to claim
# --------------------------------------------------------------------------- #

def test_a_refused_page_is_not_stamped_as_translated(detected, engine):
    """The stage was stamped over the pages it was ASKED for, so the refusal it
    printed was contradicted by the document it wrote."""
    worksheet.build_document(detected)
    _fill(detected)
    worksheet.merge_document(detected)
    doc = ir.load_doc(detected)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    # Page one answered, merged, and then EDITED again: the document holds
    # last time's Persian, so page two may not be translated from it yet.
    path = _sheets(detected) / f"{first}.done.txt"
    region_id = doc["pages"][0]["regions"][0]["id"]
    ir.write_text(path, _set_fields(ir.read_text(path), region_id,
                                    "fa: یک ترجمهٔ تازه"))
    # And page two has nothing yet, so there is work for it to refuse.
    doc = ir.load_doc(detected)
    for region in doc["pages"][1].get("regions", []):
        region.update({"source_text": "やめろ", "target_text": "",
                       "locked": False})
    ir.save_doc(doc, detected)

    report = translate.translate_document(detected, provider="counting")

    refused = [entry["page"] for entry in report["refused"]]
    assert second in refused and first not in refused, report
    recorded = ir.load_doc(detected)["stages"]["translate"]["pages"]
    assert first in recorded, recorded
    assert not (set(refused) & set(recorded)), recorded


def test_a_reply_merged_onto_regions_that_moved_refuses(detected):
    """"Was the reply consumed" is half the question. A page answered and then
    overtaken by a `detect` run describes balloons that are not there."""
    worksheet.build_document(detected)
    _fill(detected)
    worksheet.merge_document(detected)
    doc = ir.load_doc(detected)
    page_id = doc["pages"][0]["id"]
    assert chapter_context.preflight(detected, doc, page_id)["ok"]

    doc["pages"][0]["regions"][0]["bbox"] = [5, 6, 70, 80]
    ir.save_doc(doc, detected)

    state = chapter_context.preflight(detected, ir.load_doc(detected), page_id)

    assert not state["ok"] and state["moved"] == [page_id], state
    assert "moved" in chapter_context.refusal(state, detected)


# --------------------------------------------------------------------------- #
# The bounded package
# --------------------------------------------------------------------------- #

def test_the_budget_keeps_the_people_who_are_talking(detected):
    """`_speakers` is ordered by first appearance and the plain trim pops from
    the end — exactly where the characters who have just walked on are. A long
    chapter spent its whole speaker budget on people who left twenty pages ago
    and dropped the two who are speaking now."""
    doc = ir.load_doc(detected)
    page = doc["pages"][-1]
    everyone = [region for _page, region in ir.iter_regions(doc)]
    history = [f"شخصیت-{index:02d}" for index in range(len(everyone))]
    doc["meta"]["cast"] = {
        # Long enough that the 2000-character speakers budget genuinely bites.
        name: {"register": "خیلی رسمی، با جمله‌های بلند و پرتکلف. " * 12}
        for name in history + ["تازه‌وارد"]
    }
    for index, region in enumerate(everyone):
        region["speaker"] = history[index]
    for region in page.get("regions", []):
        region["speaker"] = "تازه‌وارد"
    ir.save_doc(doc, detected)
    assert len(page.get("regions", [])), "the last page has nobody speaking"

    package = chapter_context.build(doc, page["id"], budget=3000)

    named = {entry["speaker"] for entry in package["context"]["speakers"]}
    assert "تازه‌وارد" in named, "the speaker on this page was trimmed away"
    assert "speakers" in package["budget"]["overflowed"], package["budget"]


def test_the_sfx_prose_survives_beside_the_mode(detected):
    """`sfx` under `title_policy` is a person's prose — "keep the Japanese for
    the big ones" — and it was spread into the same key as the operational
    enum, which then overwrote it."""
    doc = ir.load_doc(detected)
    doc["meta"]["title_policy"] = {
        "sfx": "افکت‌های بزرگ ژاپنی بمانند، کوچک‌ها ترجمه شوند",
    }
    doc["meta"]["sfx_policy"] = "translate"
    ir.save_doc(doc, detected)

    policy = chapter_context.build(doc, doc["pages"][0]["id"])["constraints"]["policy"]

    assert policy["sfx"] == "translate"
    assert policy["sfx_note"] == "افکت‌های بزرگ ژاپنی بمانند، کوچک‌ها ترجمه شوند"
