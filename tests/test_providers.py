"""The provider boundary, and the guarantee that makes it safe to have one.

Every test here runs offline against a fake. That is not a compromise for CI's
sake — it is the design. A provider is an *optional* second opinion, and what
has to be tested is the boundary's behaviour when one is absent, slow, broken,
lying, or actively hostile. None of those need a network or a credential.

The load-bearing test is `test_a_provider_that_rewrites_every_pixel_changes_none
_outside_the_mask`. Everything else in this file supports it.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

import clean
import masks
import pageir as ir
import ocr
import providers
import translate
import worksheet


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
    assert any("read this as" in note for note in region["review"])
    # `disagreed` rather than `locked`: the distinction is whether the provider
    # said something different, not whether the field happened to be locked.
    assert region["provenance"][-1]["outcome"] == "disagreed"
    assert region["provenance"][-1]["read"] == "やめる"


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


# --- the return contract -----------------------------------------------------
# A provider is somebody else's code, and the `(payload, confidence)` tuple it
# may return is a contract. Checking only that it is a 2-tuple is what lets a
# document be corrupted: the floor in `apply` is a comparison, `NaN < floor` is
# False, so a NaN confidence cleared every floor, was applied, and serialised
# into comic.json as a bare `NaN` that no standard JSON parser will read back.

class _Confidence:
    """Returns a fixed reading with whatever second element it was built with."""

    name = "out-of-contract"

    def __init__(self, confidence):
        self.confidence = confidence

    def read(self, crop_path: str, language: str):
        return "やめろ", self.confidence


@pytest.mark.parametrize("confidence", [
    "0.92",              # a string: raised TypeError out of `apply`
    float("nan"),        # cleared every floor, and corrupted the document
    float("inf"),
    float("-inf"),
    5.0,                 # no range check at all
    -1.0,
    b"binary",           # a second payload mistaken for a confidence
])
def test_a_confidence_outside_the_contract_is_a_failed_call(confidence):
    result = providers.call(_Confidence(confidence), "ocr", "x.png", "ja")
    assert result.ok is False and result.status == "error"
    assert "confidence" in result.detail
    # And `apply` — where a string confidence used to raise TypeError on
    # `result.confidence < min_confidence` — takes it as an ordinary failure.
    region = _region()
    assert providers.apply(region, "source_text", result,
                           min_confidence=0.6) == "failed"
    assert not region["source_text"]


def test_a_confidence_at_either_end_of_the_range_is_still_accepted():
    """The check is a contract, not a tightening: 0 and 1 are real answers."""
    for confidence in (0.0, 0.5, 1.0):
        result = providers.call(_Confidence(confidence), "ocr", "x.png", "ja")
        assert result.ok is True and result.confidence == confidence


def test_no_provider_answer_can_put_a_bare_nan_in_the_document():
    """THE WORST ONE, because it is not a failed stage — it is a chapter that
    will not load again. `NaN < min_confidence` is False, so the floor let it
    through, `apply` wrote it, and `ir.dumps` emitted a bare `NaN`."""
    def strict(token):
        raise AssertionError(f"comic.json would carry a bare {token}")

    region = _region()
    result = providers.call(_Confidence(float("nan")), "ocr", "x.png", "ja")
    providers.apply(region, "source_text", result, min_confidence=0.6)
    json.loads(ir.dumps(region), parse_constant=strict)


def test_a_field_locked_while_empty_is_still_locked():
    """`locked` was only consulted once a field already had content, so a
    region a person deliberately left empty — an unreadable scribble, a balloon
    that is silent — read as one nobody had reached yet, and was overwritten."""
    region = _region(locked=True)
    assert region["source_text"] == ""
    result = providers.call(providers.FakeOCR(text="やめろ"), "ocr", "x.png", "ja")
    assert providers.apply(region, "source_text", result) == "needs_review"
    assert region["source_text"] == "", "a deliberate empty was overwritten"
    assert region["provenance"][-1]["outcome"] == "disagreed"
    assert any("read this as" in note for note in region["review"])


def test_an_empty_field_nobody_locked_is_still_filled():
    """The other half of the same rule: it is about `locked`, not about empty."""
    region = _region()
    result = providers.call(providers.FakeOCR(text="やめろ"), "ocr", "x.png", "ja")
    assert providers.apply(region, "source_text", result) == "applied"
    assert region["source_text"] == "やめろ"


def test_a_factory_that_cannot_build_is_a_refusal_not_a_traceback(monkeypatch):
    """A provider that needs a key and has not got one raised out of `get`, out
    of the CLI, and out of the MCP loop with it. Construction failure is a
    failure like any other: the same `ValueError` an unknown name already
    raises, which every caller of a stage already turns into a result."""
    def needs_a_key():
        raise RuntimeError("REVAYAT_KEY is not set")

    monkeypatch.setitem(providers._REGISTRY["ocr"], "hosted", needs_a_key)
    with pytest.raises(ValueError, match="hosted") as raised:
        providers.get("ocr", "hosted")
    assert "REVAYAT_KEY is not set" in str(raised.value)


_TIMED_OUT_CALL = '''\
import sys
import time

sys.path.insert(0, sys.argv[1])
import providers


class Slow:
    name = "slow"

    def read(self, crop_path, language):
        time.sleep(5)
        return "too late", 0.9


result = providers.call(Slow(), "ocr", "x.png", "ja", timeout=0.25)
assert result.status == "timeout", result
print("returned")
'''


def test_a_timed_out_call_does_not_hold_the_process_open(tmp_path):
    """Measured on a subprocess on purpose: the call itself always returned on
    time. What did not return was the *process* — a `ThreadPoolExecutor`'s
    workers are not daemons and `shutdown(wait=False)` does not detach them, so
    the interpreter joined a provider nobody was waiting for any more."""
    import subprocess
    import sys

    child = tmp_path / "timed_out_call.py"
    child.write_text(_TIMED_OUT_CALL, encoding="utf-8")
    scripts = str(Path(providers.__file__).resolve().parent)

    started = time.monotonic()
    done = subprocess.run([sys.executable, str(child), scripts],
                          capture_output=True, text=True, timeout=60)
    elapsed = time.monotonic() - started

    assert done.returncode == 0, done.stderr
    assert "returned" in done.stdout
    assert elapsed < 2.5, (f"a call that timed out in 0.25s held the process "
                           f"open for {elapsed:.2f}s")


def test_outstanding_calls_are_capped():
    """A timed-out call leaves its worker running; that is the honest bound.
    What must not happen is an unbounded pile of them — 25 sequential timeouts
    left 25 live workers, and nothing anywhere said stop."""
    release = threading.Event()

    class Blocked:
        name = "blocked"

        def read(self, crop_path, language):
            release.wait(30)
            return "late", 0.5

    try:
        results = [
            providers.call(Blocked(), "ocr", "x.png", "ja", timeout=0.05)
            for _ in range(providers.MAX_OUTSTANDING_CALLS + 2)
        ]
        refused = [r for r in results if r.status == "error"]
        assert refused, "nothing was refused; outstanding calls are unbounded"
        assert all("still running" in r.detail for r in refused)
        assert (sum(r.status == "timeout" for r in results)
                <= providers.MAX_OUTSTANDING_CALLS)
        assert all(r.ok is False for r in results)
    finally:
        release.set()

    # And the bound is not a ratchet: a permit comes back when its worker does.
    deadline = time.monotonic() + 5.0
    later = providers.call(providers.FakeOCR(), "ocr", "x.png", "ja", timeout=1.0)
    while not later.ok and time.monotonic() < deadline:
        later = providers.call(providers.FakeOCR(), "ocr", "x.png", "ja",
                               timeout=1.0)
    assert later.ok, f"the cap never recovered: {later.detail}"


# --- the guarantee -----------------------------------------------------------
# These exercise what happens *when the provider runs*, so they force the branch
# that reaches it. The fixture's balloons are flat paper and a flat balloon is
# repaired exactly by reading its own colour — so on the unmodified fixture the
# provider is correctly never called at all, which is its own test above.

def _needs_the_provider(monkeypatch):
    """Make every region escalate, deterministically."""
    import clean

    monkeypatch.setattr(clean, "choose_strategy",
                        lambda *a, **k: ("inpaint", None))


def test_a_provider_that_rewrites_every_pixel_changes_none_outside_the_mask(
        translated, monkeypatch):
    """THE test. A generative cleaner is only safe to plug in if a provider
    doing the worst possible thing still cannot reach a pixel the mask does not
    authorise — and the fake here is deliberately hostile: it discards the page
    entirely and returns flat red.

    The provider's output is not trusted, sanity-checked and then used. It is
    composited per region through `out = original*(1-alpha) + repaired*alpha`
    with `alpha <= mask`, so every pixel outside the mask is the original byte
    by arithmetic the provider does not participate in.
    """
    _needs_the_provider(monkeypatch)
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
    _needs_the_provider(monkeypatch)
    monkeypatch.setitem(providers._REGISTRY["image_edit"], "broken",
                        lambda: providers.FakeImageEdit(fail=mode))
    report = clean.clean_document(translated, provider="broken")

    outcomes = {call["outcome"] for call in report["provider_calls"]}
    assert outcomes and "composited" not in outcomes
    # The page was still cleaned, by the path that runs with no provider at all.
    assert report["totals"]["flat"] + report["totals"]["inpaint"] > 0
    assert report["totals"]["external"] == 0

    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    for page in doc["pages"]:
        assert (root / page["clean"]).exists()


def test_the_provider_used_is_recorded_in_the_document(translated, monkeypatch):
    _needs_the_provider(monkeypatch)
    clean.clean_document(translated, provider="fake-image-edit")
    assert ir.load_doc(translated)["stages"]["clean"]["provider"] ==         "fake-image-edit"


# --- R11: resume is bound to what the answer was made from -------------------

def test_a_completion_made_from_something_else_is_not_a_completion():
    """"This value is what a provider wrote" was the whole test, so a region
    kept its old reading after the source it was read from had been re-cropped
    and after the model was changed. The answer was still exactly what the
    provider had written; it had simply been written about something else."""
    region = {"source_text": "やめろ", "provenance": [
        {"role": "ocr", "outcome": "applied", "wrote": "やめろ",
         "identity": "aaaaaaaaaaaaaaaa"}]}

    assert providers.completed(region, "ocr", "source_text",
                               identity="aaaaaaaaaaaaaaaa")
    assert not providers.completed(region, "ocr", "source_text",
                                   identity="bbbbbbbbbbbbbbbb")


def test_a_record_from_a_build_that_wrote_no_identity_is_not_trusted():
    """Asking again costs a call. Trusting it costs a wrong reading nobody can
    see."""
    region = {"source_text": "やめろ", "provenance": [
        {"role": "ocr", "outcome": "applied", "wrote": "やめろ"}]}
    assert providers.completed(region, "ocr", "source_text")      # no question
    assert not providers.completed(region, "ocr", "source_text", identity="x")


def test_the_identity_changes_when_the_inputs_do():
    first = providers.request_identity(source="a", provider="p")
    assert first == providers.request_identity(provider="p", source="a")
    assert first != providers.request_identity(source="a", provider="q")
    assert first != providers.request_identity(source="b", provider="p")


def test_a_crop_is_named_for_the_balloon_as_well_as_the_box():
    """The cropper pads to the balloon, so a balloon traced differently
    produces a different picture from the same box."""
    page = {"sha256": "a" * 64}
    box = {"bbox": [1, 2, 3, 4], "orientation": "horizontal"}
    plain = ocr.crop_identity(page, dict(box))
    traced = ocr.crop_identity(page, {**box, "balloon": {"cx": 9}})
    assert plain != traced


def test_translation_writes_down_each_page_as_it_finishes_it(detected,
                                                             monkeypatch):
    """The whole chapter was written at the end, so an interrupted run threw
    away every answer it had already paid for and asked for them again."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    second = doc["pages"][1]["id"]
    for page in doc["pages"]:
        for region in page["regions"]:
            region["source_text"] = "やめろ"
            region["target_text"] = ""
            region["locked"] = False
    ir.save_doc(doc, detected)

    real = translate.chapter_context.build
    seen = {"pages": 0}

    def stop_after_the_first(doc_, page_id, **kwargs):
        if page_id == second:
            raise KeyboardInterrupt("the laptop closed")
        seen["pages"] += 1
        return real(doc_, page_id, **kwargs)

    monkeypatch.setattr(translate.chapter_context, "build", stop_after_the_first)
    with pytest.raises(KeyboardInterrupt):
        translate.translate_document(detected, provider="fake-translation",
                                     allow_unmerged=True)

    saved = ir.load_doc(detected)
    done = [r for r in saved["pages"][0]["regions"]
            if (r.get("target_text") or "").strip()]
    assert done, "the first page's answers were thrown away"
