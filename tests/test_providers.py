"""The provider boundary, and the guarantee that makes it safe to have one.

Every test here runs offline against a fake. That is not a compromise for CI's
sake — it is the design. A provider is an *optional* second opinion, and what
has to be tested is the boundary's behaviour when one is absent, slow, broken,
lying, or actively hostile. None of those need a network or a credential.

The load-bearing test is `test_a_provider_that_rewrites_every_pixel_changes_none
_outside_the_mask`. Everything else in this file supports it.
"""

from __future__ import annotations

import numpy as np
import pytest

import clean
import masks
import pageir as ir
import providers


# --- the boundary ------------------------------------------------------------

def test_no_provider_is_the_default_and_not_a_failure():
    """The ordinary state of the pipeline. `None` means the host agent does this
    job itself, which is the whole architecture, so it must not read as an
    error anywhere."""
    assert providers.get("ocr", None) is None
    result = providers.call(None, "ocr", "x.png", "ja")
    assert result.ok is False and result.status == "unavailable"
    assert "host agent" in result.detail


def test_an_unregistered_name_is_refused_rather_than_ignored():
    """A user who typed a provider name and silently got the host agent's own
    answer would have no way to tell it had not been used."""
    with pytest.raises(ValueError, match="fake-ocr"):
        providers.get("ocr", "no-such-provider")


def test_every_role_has_a_fake_registered():
    listing = providers.available()
    assert set(listing) == set(providers.ROLES)
    assert all(names for names in listing.values())


def test_a_provider_that_raises_becomes_a_status():
    result = providers.call(providers.FakeOCR(fail="raise"), "ocr", "x.png", "ja")
    assert result.ok is False and result.status == "error"
    assert "RuntimeError" in result.detail


def test_a_provider_that_hangs_is_bounded():
    """Python cannot kill the worker thread; what is guaranteed is that the
    stage is not blocked past the timeout and the answer is never used."""
    result = providers.call(providers.FakeOCR(fail="hang"), "ocr", "x.png", "ja",
                            timeout=0.25)
    assert result.ok is False and result.status == "timeout"
    assert result.elapsed < 5.0


def test_a_provider_that_declines_is_not_an_error():
    result = providers.call(providers.FakeOCR(fail="none"), "ocr", "x.png", "ja")
    assert result.ok is False and result.status == "refused"


def test_an_object_that_cannot_fill_the_role_says_so():
    result = providers.call(object(), "ocr", "x.png", "ja")
    assert result.ok is False and "read()" in result.detail


# --- writing back into the IR ------------------------------------------------

def _region(**over):
    region = ir.new_region("p0001r001", [0, 0, 40, 20], kind="speech")
    region.update(over)
    return region


def test_a_confident_answer_is_applied_with_its_provenance():
    region = _region()
    result = providers.call(providers.FakeOCR(text="やめろ"), "ocr", "x.png", "ja")
    assert providers.apply(region, "source_text", result) == "applied"
    assert region["source_text"] == "やめろ"
    record = region["provenance"][-1]
    assert record["provider"] == "fake-ocr" and record["outcome"] == "applied"
    assert record["confidence"] == pytest.approx(0.92)


def test_a_locked_region_is_never_overwritten():
    """`locked` means a person or the reading model committed to that value. A
    provider is a second opinion and a second opinion does not get to replace a
    decision — it gets recorded so somebody can look."""
    region = _region(locked=True, source_text="やめろ！")
    result = providers.call(providers.FakeOCR(text="やめる"), "ocr", "x.png", "ja")
    assert providers.apply(region, "source_text", result) == "needs_review"
    assert region["source_text"] == "やめろ！"
    assert any("fake-ocr read this as" in note for note in region["review"])
    assert region["provenance"][-1]["outcome"] == "locked"


def test_a_locked_region_that_agrees_needs_no_review():
    region = _region(locked=True, source_text="やめろ")
    result = providers.call(providers.FakeOCR(text="やめろ"), "ocr", "x.png", "ja")
    assert providers.apply(region, "source_text", result) == "locked"
    assert not region.get("review")


def test_a_low_confidence_answer_becomes_a_note_never_text():
    """Inventing source text is the one failure this pipeline cannot recover
    from, because every later stage trusts it."""
    region = _region()
    result = providers.call(providers.FakeOCR(text="???", confidence=0.31),
                            "ocr", "x.png", "ja")
    assert providers.apply(region, "source_text", result,
                           min_confidence=0.6) == "needs_review"
    assert not region.get("source_text")
    assert region["provenance"][-1]["outcome"] == "low_confidence"


def test_a_failed_call_still_leaves_a_trace():
    region = _region()
    result = providers.call(providers.FakeOCR(fail="raise"), "ocr", "x.png", "ja")
    assert providers.apply(region, "source_text", result) == "failed"
    assert region["provenance"][-1]["status"] == "error"
    assert not region.get("source_text")


# --- the guarantee -----------------------------------------------------------

def test_a_provider_that_rewrites_every_pixel_changes_none_outside_the_mask(
        translated):
    """THE test. A generative cleaner is only safe to plug in if a provider
    doing the worst possible thing still cannot reach a pixel the mask does not
    authorise — and the fake here is deliberately hostile: it discards the page
    entirely and returns flat red.

    The provider's output is not trusted, sanity-checked and then used. It is
    composited per region through `out = original*(1-alpha) + repaired*alpha`
    with `alpha <= mask`, so every pixel outside the mask is the original byte
    by arithmetic the provider does not participate in.
    """
    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)

    report = clean.clean_document(translated, provider="fake-image-edit")
    assert report["provider"] == "fake-image-edit"
    assert any(call["outcome"] == "composited"
               for call in report["provider_calls"])

    after_doc = ir.load_doc(translated)
    for page in after_doc["pages"]:
        original = np.asarray(ir.load_image(root / page["image"]))
        cleaned = np.asarray(ir.load_image(root / page["clean"]))
        allowed = masks.load_mask(root / page["mask"]) > 0
        delta = np.abs(original.astype(int) - cleaned.astype(int)).max(axis=2)
        delta[allowed] = 0
        assert delta.max() == 0, f"{page['id']} changed outside its mask"

    # And the provider really did reach the pixels it was allowed to: a test
    # that passes because nothing happened proves nothing.
    page = after_doc["pages"][0]
    original = np.asarray(ir.load_image(root / page["image"]))
    cleaned = np.asarray(ir.load_image(root / page["clean"]))
    allowed = masks.load_mask(root / page["mask"]) > 0
    inside = np.abs(original.astype(int) - cleaned.astype(int)).max(axis=2)
    assert inside[allowed].max() > 0


@pytest.mark.parametrize("mode", ["raise", "none", "wrong_size"])
def test_a_failing_image_provider_falls_back_to_the_classical_cleaners(
        translated, mode, monkeypatch):
    """A generative cleaner having a bad day must not be able to stall a
    chapter, and must not leave a half-written page behind."""
    monkeypatch.setitem(providers._REGISTRY["image_edit"], "broken",
                        lambda: providers.FakeImageEdit(fail=mode))
    report = clean.clean_document(translated, provider="broken")

    outcomes = {call["outcome"] for call in report["provider_calls"]}
    assert outcomes and "composited" not in outcomes
    # The page was still cleaned, by the path that runs with no provider at all.
    assert report["totals"]["flat"] + report["totals"]["inpaint"] > 0

    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    for page in doc["pages"]:
        assert (root / page["clean"]).exists()


def test_the_provider_used_is_recorded_in_the_document(translated):
    clean.clean_document(translated, provider="fake-image-edit")
    assert ir.load_doc(translated)["stages"]["clean"]["provider"] ==         "fake-image-edit"


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

    name = _fake_ocr(monkeypatch, fail="hang")
    report = ocr.read_document(detected, provider=name, timeout=0.2)
    assert report["totals"]["failed"] > 0
    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        assert region["provenance"][-1]["status"] == "timeout"


def test_ocr_is_resumable_and_does_not_re_apply(detected, monkeypatch):
    """Running it twice must not double-write or lose the first run's work."""
    import ocr

    name = _fake_ocr(monkeypatch, text="やめろ", confidence=0.9)
    first = ocr.read_document(detected, provider=name)
    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        region["locked"] = True
    ir.save_doc(doc, detected)

    second = ocr.read_document(detected, provider=name)
    assert second["totals"]["locked"] == first["totals"]["applied"]
    assert second["totals"]["applied"] == 0
    after = ir.load_doc(detected)
    for _, region in ir.iter_regions(after):
        assert region["source_text"] == "やめろ"


def test_the_ocr_stage_records_which_engine_ran(detected, monkeypatch):
    import ocr

    name = _fake_ocr(monkeypatch, text="やめろ")
    ocr.read_document(detected, provider=name)
    assert ir.load_doc(detected)["stages"]["ocr"]["provider"] == name

