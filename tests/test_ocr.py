"""The optional OCR stage, and the rule that makes a second opinion safe.

Split out of `test_providers.py`, which had grown past a thousand lines holding
two different subjects: the provider *boundary* — fakes, timeouts, the hard-mask
composite guarantee — and the stages built on top of it. This file is the OCR
stage: filling an empty region, refusing to overwrite a committed one, resuming
without re-reading, and recording a disagreement instead of resolving it.

The rule underneath every test here is one sentence: **a provider fills a hole;
it never replaces content.** Locking, resume and disagreement are all the same
rule seen from three directions.

Everything runs offline against a fake. `manga-ocr` is the one real adapter the
project ships, and even its tests never load the model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import pageir as ir
import providers


# --- the optional OCR stage --------------------------------------------------
# Off by default, and the tests are mostly about what it refuses to do. The
# reading model is the primary transcriber; this is a second opinion, and a
# second opinion that overwrites the first is not a second opinion.

def _fake_ocr(monkeypatch, **kwargs):
    monkeypatch.setitem(providers._REGISTRY["ocr"], "probe",
                        lambda: providers.FakeOCR(**kwargs))
    return "probe"


def test_ocr_fills_a_region_nobody_has_transcribed(detected, monkeypatch):
    import ocr

    name = _fake_ocr(monkeypatch, text="やめろ！", confidence=0.95)
    report = ocr.read_document(detected, provider=name)
    assert report["totals"]["applied"] > 0

    doc = ir.load_doc(detected)
    _, region = next(iter(ir.iter_regions(doc)))
    assert region["source_text"] == "やめろ！"
    # The provenance records the name the user typed, not the adapter class's
    # own — that is what "which provider produced this" means to a reader.
    assert region["provenance"][-1]["provider"] == name
    assert region["provenance"][-1]["confidence"] == pytest.approx(0.95)


def test_ocr_never_overwrites_what_the_reader_committed(translated, monkeypatch):
    """`translated` locks every region. The engine reads something else, and the
    reader's value survives with the disagreement recorded beside it."""
    import ocr

    doc = ir.load_doc(translated)
    _, region = next(iter(ir.iter_regions(doc)))
    committed = region["source_text"]

    name = _fake_ocr(monkeypatch, text="まったく違う", confidence=0.99)
    report = ocr.read_document(translated, provider=name)

    after = ir.load_doc(translated)
    _, after_region = next(iter(ir.iter_regions(after)))
    assert after_region["source_text"] == committed
    assert report["disagreement_count"] > 0
    assert report["totals"]["applied"] == 0


def test_ocr_writes_nothing_when_it_is_not_sure(detected, monkeypatch):
    """The one failure the pipeline cannot recover from is invented source
    text, because glossary, translation and every gate downstream trust it."""
    import ocr

    name = _fake_ocr(monkeypatch, text="???", confidence=0.2)
    report = ocr.read_document(detected, provider=name)
    assert report["totals"]["applied"] == 0
    assert report["totals"]["needs_review"] > 0

    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        assert not (region.get("source_text") or "").strip()
        assert region.get("review")


def test_ocr_survives_an_engine_that_cannot_read_the_crop(detected, monkeypatch):
    import ocr

    name = _fake_ocr(monkeypatch, fail="none")
    report = ocr.read_document(detected, provider=name)
    assert report["totals"]["failed"] > 0
    assert report["totals"]["applied"] == 0
    # The document is still valid and every region still reachable.
    assert ir.load_doc(detected)["pages"]


def test_ocr_survives_an_engine_that_hangs(detected, monkeypatch):
    """A stalled engine must cost its timeout and then get out of the way."""
    import ocr

    # One page, not the whole chapter. Every region waits out its own timeout,
    # so running all three pages proved the same thing fifteen times over and
    # cost three seconds of the suite to do it.
    page = ir.load_doc(detected)["pages"][0]["id"]
    name = _fake_ocr(monkeypatch, fail="hang")
    report = ocr.read_document(detected, provider=name, timeout=0.2,
                               pages=[page])
    assert report["totals"]["failed"] > 0
    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        if region["id"].startswith(page):
            assert region["provenance"][-1]["status"] == "timeout"


def test_the_ocr_stage_records_which_engine_ran(detected, monkeypatch):
    import ocr

    name = _fake_ocr(monkeypatch, text="やめろ")
    ocr.read_document(detected, provider=name)
    assert ir.load_doc(detected)["stages"]["ocr"]["provider"] == name


# --- resume, disagreement, and the rule underneath both ----------------------
# A provider fills a hole; it never replaces content. That one rule is what
# makes the stage resumable, what protects a reader's decision, and what turns a
# second reading into a disagreement instead of a silent overwrite.

def test_running_ocr_twice_does_not_call_the_engine_again(detected, monkeypatch):
    """Real resume, with nothing locked by hand. The previous version of this
    test locked every region between runs, which skipped the path it claimed to
    cover: the engine was re-called and a differing answer overwrote a good
    one."""
    import ocr

    calls = []

    class Counting(providers.FakeOCR):
        def read(self, crop_path, language):
            calls.append(crop_path)
            return super().read(crop_path, language)

    monkeypatch.setitem(providers._REGISTRY["ocr"], "counted",
                        lambda: Counting(text="やめろ", confidence=0.9))

    first = ocr.read_document(detected, provider="counted")
    assert first["totals"]["applied"] > 0
    after_first = len(calls)

    second = ocr.read_document(detected, provider="counted")
    assert second["totals"]["resumed"] == first["totals"]["applied"]
    assert second["totals"]["applied"] == 0
    assert len(calls) == after_first, "the engine was asked again"


def test_a_second_run_with_a_different_answer_never_overwrites(detected,
                                                               monkeypatch):
    """Nothing is locked here. The first run's own output still has to survive
    a second run that reads the crop differently."""
    import ocr

    monkeypatch.setitem(providers._REGISTRY["ocr"], "first",
                        lambda: providers.FakeOCR(text="やめろ", confidence=0.9))
    ocr.read_document(detected, provider="first")

    # Force a re-read by clearing what marks the work complete, then answer
    # differently — the shape of a better model being pointed at the same page.
    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        region["provenance"] = []
    ir.save_doc(doc, detected)

    monkeypatch.setitem(providers._REGISTRY["ocr"], "second",
                        lambda: providers.FakeOCR(text="やめる", confidence=0.99))
    report = ocr.read_document(detected, provider="second")

    assert report["totals"]["applied"] == 0
    assert report["disagreement_count"] > 0
    after = ir.load_doc(detected)
    for _, region in ir.iter_regions(after):
        assert region["source_text"] == "やめろ", "the earlier reading was replaced"
        assert region["provenance"][-1]["outcome"] == "disagreed"


def test_a_person_can_still_override_what_ocr_wrote(detected, monkeypatch):
    """Resume must not fossilise a bad reading. Editing the text breaks the
    match that marked the region complete, so it is looked at again."""
    import ocr

    monkeypatch.setitem(providers._REGISTRY["ocr"], "engine",
                        lambda: providers.FakeOCR(text="やめろ", confidence=0.9))
    ocr.read_document(detected, provider="engine")

    doc = ir.load_doc(detected)
    _, region = next(iter(ir.iter_regions(doc)))
    region["source_text"] = "やめろ！"          # a person fixed it
    region["locked"] = True
    ir.save_doc(doc, detected)

    assert not providers.completed(
        ir.load_doc(detected)["pages"][0]["regions"][0], "ocr", "source_text")
    report = ocr.read_document(detected, provider="engine")
    after = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert after["source_text"] == "やめろ！"
    assert report["totals"]["applied"] == 0


def test_a_timed_out_region_is_read_on_the_next_run(detected, monkeypatch):
    """A failure leaves nothing behind to mark the work done, so resume picks
    it up rather than skipping it forever."""
    import ocr

    # Both runs scoped to one page, for the same reason as the hang test above,
    # and to the SAME page so the resume count is comparable.
    page = ir.load_doc(detected)["pages"][0]["id"]
    monkeypatch.setitem(providers._REGISTRY["ocr"], "flaky",
                        lambda: providers.FakeOCR(fail="hang"))
    first = ocr.read_document(detected, provider="flaky", timeout=0.2,
                              pages=[page])
    assert first["totals"]["failed"] > 0

    monkeypatch.setitem(providers._REGISTRY["ocr"], "flaky",
                        lambda: providers.FakeOCR(text="やめろ", confidence=0.9))
    second = ocr.read_document(detected, provider="flaky", pages=[page])
    assert second["totals"]["applied"] == first["totals"]["failed"]


def test_a_vision_provider_may_comment_on_a_disagreement_only(detected,
                                                              monkeypatch):
    """Optional, advisory, and it never writes. Everything works with it absent
    — which the rest of this file already proves by not passing one."""
    import ocr

    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
        region["locked"] = True
    ir.save_doc(doc, detected)

    monkeypatch.setitem(providers._REGISTRY["ocr"], "engine",
                        lambda: providers.FakeOCR(text="やめる", confidence=0.99))
    monkeypatch.setitem(providers._REGISTRY["vision"], "eyes",
                        lambda: providers.FakeVision(payload="the first is right"))
    report = ocr.read_document(detected, provider="engine", vision="eyes")

    assert report["disagreement_count"] > 0
    assert "vision" in report["disagreements"][0]
    after = ir.load_doc(detected)["pages"][0]["regions"][0]
    assert after["source_text"] == "やめろ", "vision wrote to the document"


# --- vertical Japanese, which is the reason the stage exists ------------------
# The detector already measures which way a line runs, and it is the one piece
# of page knowledge an engine reading a lone crop cannot recover: a vertical
# column with furigana beside it looks like two columns. So the stage offers it.
# Offers, not imposes — every adapter written against the two-argument shape has
# to keep working, which is what `providers.wants` is for.

class _OrientedOCR:
    """An engine that asks which way the line runs, and says what it was told."""

    name = "oriented"

    def __init__(self):
        self.seen: list[str] = []

    def read(self, crop_path: str, language: str, orientation: str = ""):
        self.seen.append(orientation)
        return ("\u305d\u3046\u304b" if orientation == "vertical"
                else "horizontal text"), 0.95


def test_an_engine_that_asks_for_orientation_is_told_it(detected, monkeypatch):
    """Vertical Japanese with furigana is the standard case for a specialist
    engine, and the detector has already measured it. Passing it along costs
    nothing and is the difference between an engine reading a column and an
    engine guessing at one."""
    import ocr

    engine = _OrientedOCR()
    monkeypatch.setitem(providers._REGISTRY["ocr"], "oriented", lambda: engine)

    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        region["orientation"] = "vertical"
    ir.save_doc(doc, detected)

    report = ocr.read_document(detected, provider="oriented")
    assert engine.seen, "the engine was never called"
    assert set(engine.seen) == {"vertical"}
    assert report["totals"]["applied"] > 0
    assert ir.load_doc(detected)["stages"]["ocr"]["orientation_aware"] is True


def test_an_engine_that_does_not_ask_is_called_exactly_as_before(detected,
                                                                 monkeypatch):
    """The boundary is duck-typed and `adapters.py` documents a two-argument
    `read`. Teaching the stage something new must not break an adapter written
    against the shape that was documented."""
    import ocr

    name = _fake_ocr(monkeypatch, text="\u3084\u3081\u308d", confidence=0.95)
    assert providers.wants(providers.FakeOCR(), "ocr", "orientation") is False

    report = ocr.read_document(detected, provider=name)
    assert report["totals"]["applied"] > 0
    assert ir.load_doc(detected)["stages"]["ocr"]["orientation_aware"] is False


def test_a_disagreement_says_which_way_the_line_ran(translated, monkeypatch):
    """A disagreement over a vertical region is a different kind of
    disagreement — it is where furigana gets folded into the line — and the
    report is what a person reads before deciding which crops to open."""
    import ocr

    doc = ir.load_doc(translated)
    for _, region in ir.iter_regions(doc):
        region["orientation"] = "vertical"
    ir.save_doc(doc, translated)

    name = _fake_ocr(monkeypatch, text="\u307e\u3063\u305f\u304f\u9055\u3046", confidence=0.99)
    report = ocr.read_document(translated, provider=name)

    assert report["disagreements"]
    assert all(row["orientation"] == "vertical"
               for row in report["disagreements"])


def test_an_engine_taking_kwargs_counts_as_asking():
    """A wrapper that forwards `**kwargs` wants everything on offer, and
    refusing it would make the common adapter-wrapping shape the odd one out."""

    class _Wrapper:
        name = "wrapper"

        def read(self, crop_path, language, **kwargs):
            return "x", 0.9

    assert providers.wants(_Wrapper(), "ocr", "orientation") is True
    assert providers.wants(_Wrapper(), "ocr", "anything") is True


# --- the one real adapter this project can ship -------------------------------

def test_the_manga_ocr_adapter_registers_without_the_package():
    """Registering must cost nothing. The point of a lazy factory is that a
    3 GB optional dependency is not imported because a module was."""
    import adapters

    report = adapters.register_all()
    assert "manga-ocr" in report["registered"]
    assert "manga-ocr" in providers.available("ocr")["ocr"]
    # This machine does not have it, and that is reported rather than hidden.
    assert report["installed"] or report["needs_install"]


def test_the_manga_ocr_adapter_reads_through_the_boundary(monkeypatch):
    """Tested against the package's real call shape — `MangaOcr()` returns a
    callable that takes a PIL image and returns a string — with a stub standing
    in for the 3 GB download. That is the honest limit of what can be proved
    here: the adapter and the boundary are verified, the actual model is not.
    """
    import sys
    import types

    import adapters

    seen = []

    class _Stub:
        def __call__(self, image):
            seen.append(image.size)
            return "  やめろ！  "

    module = types.ModuleType("manga_ocr")
    module.MangaOcr = _Stub
    monkeypatch.setitem(sys.modules, "manga_ocr", module)

    from PIL import Image
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        crop = Path(folder) / "r001.png"
        Image.new("RGB", (120, 60), "white").save(crop)

        adapter = adapters.MangaOcr()
        assert adapter._model is None, "the model was loaded before it was needed"

        result = providers.call(adapter, "ocr", str(crop), "ja", name="manga-ocr")

    assert result.ok and result.data == "やめろ！"
    assert result.confidence == pytest.approx(adapters.MANGA_OCR_CONFIDENCE)
    assert seen == [(120, 60)]


def test_the_manga_ocr_adapter_declines_a_language_it_cannot_read(monkeypatch):
    """A Japanese model handed a Korean page must say so, not answer anyway."""
    import adapters

    result = providers.call(adapters.MangaOcr(), "ocr", "x.png", "ko",
                            name="manga-ocr")
    assert result.ok is False and result.status == "refused"
