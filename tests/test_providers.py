"""The provider boundary, and the guarantee that makes it safe to have one.

Every test here runs offline against a fake. That is not a compromise for CI's
sake — it is the design. A provider is an *optional* second opinion, and what
has to be tested is the boundary's behaviour when one is absent, slow, broken,
lying, or actively hostile. None of those need a network or a credential.

The load-bearing test is `test_a_provider_that_rewrites_every_pixel_changes_none
_outside_the_mask`. Everything else in this file supports it.
"""

from __future__ import annotations

from pathlib import Path

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


# --- the bounded chapter context ---------------------------------------------
# Consistency across pages is what this exists for. The three properties that
# make it usable are boundedness, determinism and locked-decisions-win, and all
# three are cheap to break by accident.

def test_the_context_package_is_bounded(translated):
    import context

    doc = ir.load_doc(translated)
    package = context.build(doc, doc["pages"][-1]["id"], budget=120)
    used = package["budget"]["characters_used"]
    assert used <= 120
    assert len(package["context"]["translation_memory"]) <= context.MAX_PREVIOUS
    assert package["budget"]["truncated"] is True


def test_the_context_package_is_deterministic(translated):
    """A resumed run must continue, not restart. Two builds of the same page
    from the same document have to be byte-identical, which rules out anything
    ordered by frequency, time or dict iteration over mutable state."""
    import json

    import context

    doc = ir.load_doc(translated)
    page = doc["pages"][-1]["id"]
    first = json.dumps(context.build(doc, page), sort_keys=True,
                       ensure_ascii=False)
    second = json.dumps(context.build(ir.load_doc(translated), page),
                        sort_keys=True, ensure_ascii=False)
    assert first == second


def test_constraints_and_context_are_kept_apart(translated):
    """A locked glossary term is a fact; a previous line is information.
    Flattening the two is how a locked term gets quietly improved."""
    import context

    doc = ir.load_doc(translated)
    # The REAL schema: `glossary.entries`, with `target`. The first version of
    # this test invented `meta.glossary` and `context.build` read the same wrong
    # key, so the two agreed with each other and neither agreed with the
    # glossary stage. A test that builds its own fixture can validate a schema
    # that does not exist anywhere else.
    doc["glossary"] = {"entries": {
        "セキレイ": {"target": "سکیره‌ای", "locked": True},
        "loose": {"target": "آزاد"},
        "empty": {"target": "", "locked": True},
    }}
    package = context.build(doc, doc["pages"][0]["id"])
    assert package["constraints"]["glossary"]["セキレイ"] == "سکیره‌ای"
    assert "loose" not in package["constraints"]["glossary"]
    assert "empty" not in package["constraints"]["glossary"]
    assert "one source region becomes exactly one translated region" in \
        package["constraints"]["rules"]
    assert "glossary" not in package["context"]


def test_the_context_carries_lines_not_summaries(translated):
    """It never condenses dialogue. Fewer lines, never shorter ones."""
    import context

    doc = ir.load_doc(translated)
    package = context.build(doc, doc["pages"][-1]["id"])
    originals = {(r.get("target_text") or "").strip()
                 for _, r in ir.iter_regions(doc)}
    for row in package["context"]["translation_memory"]:
        assert row["fa"] in originals


def test_the_next_page_is_mentioned_but_not_translated(translated):
    import context

    doc = ir.load_doc(translated)
    package = context.build(doc, doc["pages"][0]["id"])
    for row in package["context"]["next_page"]:
        assert set(row) == {"region", "kind", "speaker"}
        assert "fa" not in row and "src" not in row


def test_the_last_page_has_no_next(translated):
    import context

    doc = ir.load_doc(translated)
    assert context.build(doc, doc["pages"][-1]["id"])["context"]["next_page"] == []


# --- the optional visual QA pass ---------------------------------------------
# Advisory, and the tests are about the ways it must NOT behave: it cannot fail
# a run, it cannot clear one, and it cannot invent its own vocabulary.

def _fake_vqa(monkeypatch, **kwargs):
    monkeypatch.setitem(providers._REGISTRY["visual_qa"], "eye",
                        lambda: providers.FakeVisualQA(**kwargs))
    return "eye"


def test_visual_findings_are_structured_and_advisory(finished, monkeypatch):
    import qa

    name = _fake_vqa(monkeypatch, findings=[
        {"code": "speaker-mismatch", "region": "p0001r001", "note": "tail points left"},
    ])
    report = qa.visual_review(finished, provider=name)
    assert report["advisory"] is True
    assert report["note_count"] >= 1
    finding = report["notes"][0]
    assert set(finding) == {"code", "page", "region", "note"}
    assert finding["code"] in qa.VISUAL_CODES


def test_a_model_cannot_invent_its_own_codes(finished, monkeypatch):
    """An open vocabulary would let a model define findings a reader has no way
    to learn. Anything outside `VISUAL_CODES` is dropped and counted."""
    import qa

    name = _fake_vqa(monkeypatch, findings=[
        {"code": "vibes-off", "region": "p0001r001", "note": "hmm"},
        {"code": "missed-text", "region": "p0001r002", "note": "sign, top left"},
    ])
    report = qa.visual_review(finished, provider=name)
    assert all(n["code"] in qa.VISUAL_CODES for n in report["notes"])
    assert report["malformed"] >= 1


def test_a_malformed_answer_is_retried_a_bounded_number_of_times(finished,
                                                                monkeypatch):
    import qa

    name = _fake_vqa(monkeypatch, fail="malformed")
    report = qa.visual_review(finished, provider=name)
    per_page = len(ir.load_doc(finished)["pages"])
    assert len(report["calls"]) <= per_page * (qa.VISUAL_RETRIES + 1)
    assert report["note_count"] == 0


def test_a_visual_pass_cannot_clear_a_deterministic_failure(finished, monkeypatch):
    """The asymmetry that makes an advisory pass safe. A model saying the page
    is fine must not clear a real error, so `check` is run separately and its
    verdict is untouched by anything here."""
    import numpy as np
    from PIL import Image

    import qa

    doc = ir.load_doc(finished)
    root = ir.doc_dir(finished)
    page = doc["pages"][0]
    # Sabotage a pixel outside every mask.
    final = np.asarray(ir.load_image(root / page["final"])).copy()
    final[2, 2] = (255, 0, 255)
    Image.fromarray(final).save(root / page["final"])

    gate = qa.check_document(finished)
    assert gate["ok"] is False

    name = _fake_vqa(monkeypatch, findings=[])
    advisory = qa.visual_review(finished, provider=name)
    assert advisory["note_count"] == 0
    # And the gate still fails: the advisory pass has no verdict at all.
    assert "ok" not in advisory
    assert qa.check_document(finished)["ok"] is False


def test_a_visual_provider_that_fails_does_not_break_the_pass(finished,
                                                              monkeypatch):
    import qa

    name = _fake_vqa(monkeypatch, fail="raise")
    report = qa.visual_review(finished, provider=name)
    assert report["note_count"] == 0
    assert all(call["status"] == "error" for call in report["calls"])


# --- the image-edit provider, wired for real ---------------------------------

def test_the_clean_cli_actually_invokes_the_provider(translated, monkeypatch):
    """`--provider` was parsed and never passed to `clean_document`. Every
    provider test called the Python function directly, so nothing noticed. A
    flag is not wired until something runs the *command*."""
    import clean

    seen = []

    class Watched(providers.FakeImageEdit):
        def repair(self, page_png, mask_png, instructions):
            seen.append(len(page_png))
            return super().repair(page_png, mask_png, instructions)

    _needs_the_provider(monkeypatch)
    monkeypatch.setitem(providers._REGISTRY["image_edit"], "watched",
                        lambda: Watched())
    assert clean.main(["--doc", str(translated), "--provider", "watched"]) == 0
    assert seen, "the CLI never reached the provider"


def test_a_provider_does_not_replace_a_flat_fill(translated):
    """Escalation, not replacement. Reading a flat balloon's own colour and
    painting it back is exact; handing it to a model resamples artwork that was
    already right and costs a call to do it."""
    import clean

    baseline = clean.clean_document(translated)
    flat_without = baseline["totals"]["flat"]
    assert flat_without > 0, "the fixture has no flat balloons to protect"

    with_provider = clean.clean_document(translated,
                                         provider="fake-image-edit")
    assert with_provider["totals"]["flat"] == flat_without
    doc = ir.load_doc(translated)
    fills = {r["fill"] for _, r in ir.iter_regions(doc)}
    assert "flat" in fills, "every region went to the provider"


def test_a_solid_free_lettering_mask_accepts_a_native_provider(translated):
    """A solid mask is built *for* a generative cleaner. Refusing it unless the
    pages arrive in a folder rejected the other valid consumer of the same
    thing."""
    import clean

    doc = ir.load_doc(translated)
    doc["meta"]["free_lettering_mask"] = "solid"
    ir.save_doc(doc, translated)

    with pytest.raises(ValueError, match="--provider"):
        clean.clean_document(translated)

    report = clean.clean_document(translated, provider="fake-image-edit")
    assert report["provider"] == "fake-image-edit"


def test_what_the_provider_did_survives_in_the_document(translated, monkeypatch):
    """The CLI report is gone the moment the terminal scrolls. Reconstructing
    what happened later has to be possible from `comic.json` alone."""
    import clean

    _needs_the_provider(monkeypatch)
    clean.clean_document(translated, provider="fake-image-edit")
    stage = ir.load_doc(translated)["stages"]["clean"]
    assert stage["provider"] == "fake-image-edit"
    assert stage["provider_calls"], "no per-page record was persisted"
    assert {"page", "outcome"} <= set(stage["provider_calls"][0])


# --- the optional machine translator -----------------------------------------

def test_translation_fills_only_empty_regions(detected, monkeypatch):
    """The default is that a person translates. This exists for a run with no
    reader at all, and it obeys the same rule every provider does: fill a hole,
    never replace content."""
    import translate

    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
    _, first = next(iter(ir.iter_regions(doc)))
    first["target_text"] = "بس کن!"          # already translated by hand
    first["locked"] = True
    ir.save_doc(doc, detected)

    monkeypatch.setitem(providers._REGISTRY["translation"], "mt",
                        lambda: providers.FakeTranslation(prefix="ترجمهٔ "))
    report = translate.translate_document(detected, provider="mt")

    after = ir.load_doc(detected)
    _, kept = next(iter(ir.iter_regions(after)))
    assert kept["target_text"] == "بس کن!", "a human translation was replaced"
    assert report["totals"]["applied"] > 0


def test_translation_receives_the_bounded_context(translated, monkeypatch):
    """The package is the point: without it a machine translator drifts on
    names and register exactly the way a page-at-a-time human would."""
    import translate

    doc = ir.load_doc(translated)
    doc["glossary"] = {"entries": {"セキレイ": {"target": "سکیره‌ای",
                                              "locked": True}}}
    for _, region in ir.iter_regions(doc):
        region["target_text"] = ""
        region["locked"] = False
    ir.save_doc(doc, translated)

    seen = []

    class Recording(providers.FakeTranslation):
        def translate(self, source, context):
            seen.append(context)
            return super().translate(source, context)

    monkeypatch.setitem(providers._REGISTRY["translation"], "mt",
                        lambda: Recording())
    translate.translate_document(translated, provider="mt")

    assert seen, "the provider was never called"
    package = seen[0]
    assert package["constraints"]["glossary"]["セキレイ"] == "سکیره‌ای"
    assert "translation_memory" in package["context"]
    assert package["budget"]["characters"] > 0
    assert "region" in package and "speaker" in package


def test_translation_resumes_without_re_calling(detected, monkeypatch):
    import translate

    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
    ir.save_doc(doc, detected)

    calls = []

    class Counting(providers.FakeTranslation):
        def translate(self, source, context):
            calls.append(source)
            return super().translate(source, context)

    monkeypatch.setitem(providers._REGISTRY["translation"], "mt",
                        lambda: Counting())
    first = translate.translate_document(detected, provider="mt")
    before = len(calls)
    second = translate.translate_document(detected, provider="mt")

    assert second["totals"]["resumed"] == first["totals"]["applied"]
    assert len(calls) == before


def test_the_context_carries_no_invented_state(translated):
    """`scene`, `register` and the rest are absent unless a person wrote them.
    A guess about how a character talks, handed over as context, reads like
    knowledge and is worse than silence."""
    import context

    doc = ir.load_doc(translated)
    package = context.build(doc, doc["pages"][0]["id"])
    assert package["context"]["scene"] == ""
    assert package["context"]["series_notes"] == []
    for speaker in package["context"]["speakers"]:
        assert "register" not in speaker and "voice" not in speaker

    doc["meta"]["scene"] = "روی پشت‌بام، شب"
    doc["meta"]["cast"] = {speaker["speaker"]: {"register": "محاوره‌ای"}
                           for speaker in package["context"]["speakers"]}
    filled = context.build(doc, doc["pages"][0]["id"])
    assert filled["context"]["scene"] == "روی پشت‌بام، شب"
    assert all(s.get("register") == "محاوره‌ای"
               for s in filled["context"]["speakers"])


# --- laziness, and the two kinds of replacement pixels -----------------------

def _counting_edit(monkeypatch, name="counted"):
    """A provider that records every call, so "it was not called" is provable."""
    calls = []

    class Counting(providers.FakeImageEdit):
        def repair(self, page_png, mask_png, instructions):
            calls.append(len(page_png))
            return super().repair(page_png, mask_png, instructions)

    monkeypatch.setitem(providers._REGISTRY["image_edit"], name,
                        lambda: Counting())
    return calls


def test_an_all_flat_page_never_calls_the_provider(translated, monkeypatch):
    """The fixture's balloons are flat paper, so every region is repaired
    exactly by reading its own colour. Asking a hosted image model to redraw the
    page anyway is money and minutes for pixels that get thrown away."""
    import clean

    calls = _counting_edit(monkeypatch)
    report = clean.clean_document(translated, provider="counted")

    assert report["totals"]["inpaint"] == 0, "fixture is not all-flat any more"
    assert calls == [], f"the provider was called {len(calls)} times"
    assert report["totals"]["flat"] > 0
    # And nothing is recorded that did not happen.
    assert report["provider_calls"] == []


def test_the_provider_is_asked_once_per_page_not_once_per_region(
        translated, monkeypatch):
    """Lazy, but not repeatedly lazy: the first region that needs
    reconstruction fetches the page and the rest of that page reuses it.

    The escalation is forced rather than provoked. Trying to make a generated
    fixture choose `inpaint` by texturing it is a test of the strategy chooser,
    not of the caching — and it skipped when the texture was not enough.
    """
    import clean

    monkeypatch.setattr(clean, "choose_strategy",
                        lambda *a, **k: ("inpaint", None))
    calls = _counting_edit(monkeypatch)
    report = clean.clean_document(translated, provider="counted")

    pages = len(ir.load_doc(translated)["pages"])
    assert report["totals"]["external"] > pages, "not enough regions to prove it"
    assert len(calls) == pages,         f"{len(calls)} calls for {pages} pages — the page is not being reused"


def test_an_external_page_still_supplies_every_authorised_region(
        translated, tmp_path):
    """`--external` is a page a person handed over, having already decided the
    whole page should be replaced. An escalation gate applied to it silently
    ignored most of what they supplied — which is what this asserts against, by
    checking a flat region actually took the external pixels."""
    import clean
    from PIL import Image

    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    external = tmp_path / "external"
    external.mkdir()
    for page in doc["pages"]:
        Image.new("RGB", (page["width"], page["height"]), (255, 0, 255)).save(
            external / f"{page['id']}.png")

    clean.clean_document(translated, external=external)
    after = ir.load_doc(translated)

    flat_or_all = [r for _, r in ir.iter_regions(after)
                   if r.get("fill") == "external"]
    assert flat_or_all, "no region took the external pixels"

    page = after["pages"][0]
    original = np.asarray(ir.load_image(root / page["image"]))
    cleaned = np.asarray(ir.load_image(root / page["clean"]))
    allowed = masks.load_mask(root / page["mask"]) > 0

    # The magenta reached the masked pixels ...
    inside = cleaned[allowed]
    assert (inside == np.array([255, 0, 255])).all(axis=-1).any()
    # ... and not one pixel outside them.
    delta = np.abs(original.astype(int) - cleaned.astype(int)).max(axis=2)
    delta[allowed] = 0
    assert delta.max() == 0


# --- the wave lifecycle -------------------------------------------------------
# `context` reads `comic.json`, so it only knows what has been MERGED. Launching
# every page at once against an unchanged document hands each sub-agent an empty
# context and gets exactly the drift the context exists to prevent. This is the
# deterministic proof that translating in waves fixes it — and that translating
# all at once does not.

def _translate_page(doc_path, page_id, lines):
    """Stand in for a page sub-agent: write the reply, then merge it."""
    import worksheet

    root = ir.doc_dir(doc_path)
    source = root / "worksheets" / f"{page_id}.txt"
    out, current = [], None
    for line in source.read_text(encoding="utf-8").splitlines():
        header = worksheet.HEADER.match(line)
        if header:
            current = header.group("id")
        if line.startswith("src:") and current:
            out.append("src: やめろ！")
            continue
        if line.startswith("fa:") and current:
            out.append(f"fa: {lines.get(current, 'بس کن!')}")
            continue
        out.append(line)
    (root / "worksheets" / f"{page_id}.done.txt").write_text(
        "\n".join(out) + "\n", encoding="utf-8")
    # `merge_document` merges whatever replies exist, so a wave is simply
    # the replies written so far. `missing_outputs` for the untranslated
    # pages is expected mid-chapter and is not a failure.
    worksheet.merge_document(doc_path)


def test_page_two_sees_page_one_only_after_it_is_merged(detected):
    """The lifecycle bug, and the fix, in one test.

    Before the merge, page 2's context is empty of translation memory no matter
    how correct `context.build` is — the Persian exists only in a `.done.txt`
    file. After it, page 1's exact source and target are there.
    """
    import context
    import glossary
    import worksheet

    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    if len(doc["pages"]) < 2:
        pytest.skip("needs at least two pages")
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]

    # A name settled before any translation starts — chapter 3's decision has to
    # constrain page 1 of chapter 12, not be rediscovered.
    doc = ir.load_doc(detected)
    doc.setdefault("glossary", {}).setdefault("entries", {})["セキレイ"] = {
        "target": "سکیره‌ای", "locked": True}
    ir.save_doc(doc, detected)

    before = context.build(ir.load_doc(detected), second)
    assert before["context"]["translation_memory"] == []
    # ... but the locked name is already a constraint on the very first page.
    assert before["constraints"]["glossary"]["セキレイ"] == "سکیره‌ای"

    _translate_page(detected, first, {})

    after = context.build(ir.load_doc(detected), second)
    memory = after["context"]["translation_memory"]
    assert memory, "page 1 was merged and page 2 still cannot see it"
    assert memory[-1]["page"] == first
    assert memory[-1]["fa"] == "بس کن!"
    assert memory[-1]["src"] == "やめろ！"
    assert after["constraints"]["glossary"]["セキレイ"] == "سکیره‌ای"


def test_the_wave_context_is_stable_across_a_resume(detected):
    """Re-running a wave must produce the same context and must not duplicate
    the work already committed."""
    import context
    import worksheet

    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    if len(doc["pages"]) < 2:
        pytest.skip("needs at least two pages")
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]

    _translate_page(detected, first, {})
    once = context.build(ir.load_doc(detected), second)

    _translate_page(detected, first, {})          # the same wave, run again
    twice = context.build(ir.load_doc(detected), second)

    import json
    assert json.dumps(once, sort_keys=True, ensure_ascii=False) == \
        json.dumps(twice, sort_keys=True, ensure_ascii=False)
    assert len(twice["context"]["translation_memory"]) == \
        len(once["context"]["translation_memory"])


def test_the_documented_default_is_the_order_the_tests_prove():
    """The workflow the skill *recommends* has to be the one the lifecycle test
    above actually verifies.

    `test_page_two_sees_page_one_only_after_it_is_merged` proves continuity for
    a page translated after its predecessor was merged — and only for that. A
    four-page batch was documented as the default anyway, which meant pages 2, 3
    and 4 read the same pre-merge snapshot and the guarantee the instructions
    claimed was true of one page in four.

    Prose is not covered by any other test in this suite, so it drifts from the
    code silently. This is the cheapest possible guard against that: the default
    path is sequential, and any batching is marked as the trade it is.
    """
    from pathlib import Path

    skill = Path(__file__).resolve().parents[1] / "skills" / "revayat-comic" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    step5 = text[text.index("## Step 5"):text.index("## Step 6")]

    # The default is stated, and stated first.
    assert "One page at a time, merged before the next one starts" in step5
    assert "page 1  \u2192  merge" in step5

    # Nothing recommends translating several pages against one snapshot without
    # naming the cost.
    batching = step5.lower()
    if "four" in batching or "6 at a time" in batching or "in parallel" in batching:
        assert "speed-for-consistency" in step5 or "cannot see each other" in step5, (
            "SKILL.md suggests batching pages without saying what it costs")
        assert "<details>" in step5, (
            "batching is presented at the same level as the correct path")


def test_building_a_context_over_an_unmerged_page_is_refused(detected):
    """The lock. Sequential order was a rule in a document and nothing enforced
    it, so the one mistake the context package exists to prevent was still one
    keystroke away — and silent, because the JSON comes out well-formed and
    simply missing the pages that mattered."""
    import context
    import worksheet

    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    if len(doc["pages"]) < 2:
        pytest.skip("needs at least two pages")
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    root = ir.doc_dir(detected)

    # Nothing written yet: nothing to be behind on.
    assert context.unmerged_before(detected, doc, second) == []

    # A reply exists on disk and has not been merged.
    (root / "worksheets" / f"{first}.done.txt").write_text(
        (root / "worksheets" / f"{first}.txt").read_text(encoding="utf-8"),
        encoding="utf-8")
    assert context.unmerged_before(detected, ir.load_doc(detected), second) == [first]

    with pytest.raises(SystemExit, match="not merged"):
        context.main(["--doc", str(detected), "--page", second])

    # The escape hatch exists and says what it costs.
    package = context.build(ir.load_doc(detected), second)
    assert package["context"]["translation_memory"] == []


def test_the_lock_lifts_once_the_page_is_merged(detected):
    import context
    import worksheet

    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    if len(doc["pages"]) < 2:
        pytest.skip("needs at least two pages")
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]

    _translate_page(detected, first, {})
    assert context.unmerged_before(detected, ir.load_doc(detected), second) == []
    assert context.main(["--doc", str(detected), "--page", second]) == 0
