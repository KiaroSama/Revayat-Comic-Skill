"""Delayed workers cannot silently replace newer chapter decisions."""

import json
from copy import deepcopy

import pytest

import batch
import crops
import masks
import pageir as ir
import stages
import test_batch_orchestration

chapter = test_batch_orchestration.chapter


def _plan(chapter, tmp_path):
    folder = tmp_path / "parallel"
    batch.plan_shards(chapter, 2, folder)
    return folder


def _legacy_shared_snapshot(folder, doc):
    """Reproduce the shared-hash contract emitted before this compatibility fix."""
    shared = deepcopy({key: value for key, value in doc.items()
                       if key not in {"pages", "stages"}})
    shared.get("meta", {}).pop("worksheets", None)
    shared.get("meta", {}).pop("free_lettering_mask", None)
    shared.get("source", {}).pop("page_count", None)
    payload = json.dumps(shared, ensure_ascii=False, sort_keys=True, allow_nan=False)
    path = folder / batch.MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["snapshot"]["shared"] = ir.sha256_bytes(payload.encode("utf-8"))
    ir.write_text(path, ir.dumps(manifest) + "\n")


@pytest.mark.parametrize("source", [{}, {"page_count": 5}, {"path": "original.cbz"}])
@pytest.mark.parametrize("counter", [False, True])
def test_preexisting_snapshot_survives_normalization_and_worker_rerun(
        chapter, tmp_path, monkeypatch, source, counter):
    document = chapter / "comic.json"
    doc = ir.load_doc(document)
    doc["source"] = source
    if counter:
        doc["meta"]["stage_seq"] = 7
        doc["stages"]["crops"] = {"fingerprint": "old-build", "pages": 5, "seq": 7}
    ir.save_doc(doc, document)
    folder = _plan(chapter, tmp_path)
    _legacy_shared_snapshot(folder, doc)
    batch.merge_shards(folder, chapter)

    crops.build_document(folder / "shard-001" / "comic.json")
    batch.merge_shards(folder, chapter)
    merged = ir.load_doc(document)
    assert set(merged["stages"]["crops"]["pages"]) == {"p0031", "p0029", "p0034"}
    before = document.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("an exact old-manifest replay republished assets")

    monkeypatch.setattr(batch, "_publish", forbidden)
    batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before


@pytest.mark.parametrize("side", ["chapter", "worker", "asset"])
def test_preexisting_snapshot_still_rejects_meaningful_drift(chapter, tmp_path, side):
    document = chapter / "comic.json"
    doc = ir.load_doc(document)
    doc["meta"]["stage_seq"] = 7
    ir.save_doc(doc, document)
    folder = _plan(chapter, tmp_path)
    _legacy_shared_snapshot(folder, doc)
    if side == "asset":
        changed = chapter / "notes" / "p0031.txt"
        ir.write_text(changed, "New canonical draft\n")
    else:
        changed = document if side == "chapter" else folder / "shard-001" / "comic.json"
        changed_doc = ir.load_doc(changed)
        changed_doc["source"]["path"] = "different-source.cbz"
        ir.save_doc(changed_doc, changed)
    before = document.read_bytes()
    draft = changed.read_bytes()
    with pytest.raises(ValueError, match="shared|snapshot"):
        batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before
    assert changed.read_bytes() == draft


def test_untouched_batch_replay_does_not_republish(chapter, tmp_path, monkeypatch):
    folder = _plan(chapter, tmp_path)
    batch.merge_shards(folder, chapter)

    def forbidden(*args, **kwargs):
        pytest.fail("an untouched batch replay republished identical assets")

    monkeypatch.setattr(batch, "_publish", forbidden)
    batch.merge_shards(folder, chapter)


@pytest.mark.parametrize("legacy", ["missing-source", "stage-counter", "both"])
def test_untouched_legacy_shards_merge_and_replay(chapter, tmp_path, legacy):
    document = chapter / "comic.json"
    doc = ir.load_doc(document)
    if legacy in {"missing-source", "both"}:
        doc.pop("source")
    if legacy in {"stage-counter", "both"}:
        doc["stages"]["crops"] = {"fingerprint": "old-build", "pages": 5, "seq": 7}
        doc["meta"]["stage_seq"] = 7
    ir.save_doc(doc, document)
    original_stages = doc["stages"]
    original_pages = doc["pages"]
    folder = _plan(chapter, tmp_path)

    batch.merge_shards(folder, chapter)
    merged = ir.load_doc(document)
    assert merged["stages"] == original_stages
    assert merged["pages"] == original_pages
    before = document.read_bytes()
    batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before


@pytest.mark.parametrize("selection", ["all", "last-shard", "one-page"])
def test_legacy_worker_recomputation_keeps_page_freshness(chapter, tmp_path, selection):
    document = chapter / "comic.json"
    doc = ir.load_doc(document)
    doc.pop("source")
    doc["stages"]["crops"] = {"fingerprint": "old-build", "pages": 5, "seq": 7}
    doc["meta"]["stage_seq"] = 7
    ir.save_doc(doc, document)
    folder = _plan(chapter, tmp_path)
    fresh = set()
    for name in ("shard-001", "shard-002"):
        shard_document = folder / name / "comic.json"
        local = ir.load_doc(shard_document)
        ids = [page["id"] for page in local["pages"]]
        if selection == "last-shard" and name == "shard-001":
            continue
        if selection == "one-page":
            ids = ids[:1]
        crops.build_document(shard_document, pages=ids)
        fresh.update(ids)

    batch.merge_shards(folder, chapter)
    merged = ir.load_doc(document)
    assert merged["stages"]["crops"]["scheme"] == stages.SCHEME
    assert set(merged["stages"]["crops"]["pages"]) == fresh
    assert set(stages.stale_pages(merged, "crops")) == {
        page["id"] for page in merged["pages"]
    } - fresh
    before = document.read_bytes()
    batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before


@pytest.mark.parametrize("side", ["chapter", "worker"])
def test_missing_source_normalization_does_not_hide_real_drift(chapter, tmp_path, side):
    document = chapter / "comic.json"
    doc = ir.load_doc(document)
    doc.pop("source")
    ir.save_doc(doc, document)
    folder = _plan(chapter, tmp_path)
    changed = document if side == "chapter" else folder / "shard-001" / "comic.json"
    doc = ir.load_doc(changed)
    doc.setdefault("source", {})["path"] = "different-source.cbz"
    ir.save_doc(doc, changed)
    before = document.read_bytes()
    draft = changed.read_bytes()
    with pytest.raises(ValueError, match="shared"):
        batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before
    assert changed.read_bytes() == draft


def test_new_worker_stage_imports_only_owned_page_evidence(chapter, tmp_path):
    folder = _plan(chapter, tmp_path)
    shard_document = folder / "shard-002" / "comic.json"
    crops.build_document(shard_document)
    local = ir.load_doc(shard_document)
    owned = {page["id"] for page in local["pages"]}
    record = local["stages"]["crops"]
    # Neither an earlier shard's page nor an unknown page belongs to this worker.
    for pid in ("p0031", "p9999"):
        record["pages"][pid] = "unowned revision"
        record["page_options"][pid] = {"unowned": True}
        record["needs"]["detect"][pid] = "unowned upstream revision"
    ir.save_doc(local, shard_document)

    batch.merge_shards(folder, chapter)
    document = chapter / "comic.json"
    merged = ir.load_doc(document)["stages"]["crops"]
    assert set(merged["pages"]) == owned
    assert set(merged["page_options"]) == owned
    assert set(merged["needs"]["detect"]) == owned
    before = document.read_bytes()
    batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before


def test_merge_refuses_a_newer_canonical_translation(chapter, tmp_path):
    folder = _plan(chapter, tmp_path)
    path = chapter / "comic.json"
    doc = ir.load_doc(path)
    doc["pages"][0]["regions"][0].update(target_text="تصمیم تازه", locked=True)
    ir.save_doc(doc, path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="changed|snapshot"):
        batch.merge_shards(folder, chapter)
    assert path.read_bytes() == before


@pytest.mark.parametrize("scope", ["glossary", "policy", "asset"])
def test_merge_refuses_drift_in_the_frozen_chapter(chapter, tmp_path, scope):
    folder = _plan(chapter, tmp_path)
    path = chapter / "comic.json"
    doc = ir.load_doc(path)
    if scope == "glossary":
        doc["glossary"].setdefault("entries", {})["Tokyo"] = {"target": "توکیو", "locked": True}
    elif scope == "policy":
        doc["meta"]["title_policy"] = {"register": "formal"}
    else:
        ir.write_text(chapter / "notes" / "p0031.txt", "New coordinator draft\n")
    ir.save_doc(doc, path)
    before = path.read_bytes()
    note = (chapter / "notes" / "p0031.txt").read_bytes()
    with pytest.raises(ValueError, match="changed|snapshot"):
        batch.merge_shards(folder, chapter)
    assert path.read_bytes() == before
    assert (chapter / "notes" / "p0031.txt").read_bytes() == note


@pytest.mark.parametrize("field", ["glossary", "meta"])
def test_merge_never_discards_changed_shared_worker_decisions(chapter, tmp_path, field):
    folder = _plan(chapter, tmp_path)
    shard_doc = folder / "shard-001" / "comic.json"
    local = ir.load_doc(shard_doc)
    if field == "glossary":
        local["glossary"].setdefault("entries", {})["Tokyo"] = {"target": "توکیو", "locked": True}
    else:
        local["meta"]["title_policy"] = {"register": "formal"}
    ir.save_doc(local, shard_doc)
    before = (chapter / "comic.json").read_bytes()
    with pytest.raises(ValueError, match="shared|glossary|policy"):
        batch.merge_shards(folder, chapter)
    assert (chapter / "comic.json").read_bytes() == before
    assert json.loads(shard_doc.read_text(encoding="utf-8"))[field] == local[field]


def test_new_canonical_answer_file_is_not_overwritten(chapter, tmp_path):
    folder = _plan(chapter, tmp_path)
    answer = chapter / "notes" / "p0031.done.txt"
    ir.write_text(answer, "New canonical answer\n")
    ir.write_text(folder / "shard-001" / "notes" / answer.name, "Old worker answer\n")
    before = (chapter / "comic.json").read_bytes()
    with pytest.raises(ValueError, match="changed|snapshot"):
        batch.merge_shards(folder, chapter)
    assert answer.read_text(encoding="utf-8") == "New canonical answer\n"
    assert (chapter / "comic.json").read_bytes() == before


def test_replay_refuses_a_modified_already_merged_asset(chapter, tmp_path):
    folder = _plan(chapter, tmp_path)
    answer = chapter / "notes" / "p0031.done.txt"
    ir.write_text(folder / "shard-001" / "notes" / answer.name, "Worker answer\n")
    batch.merge_shards(folder, chapter)
    batch.merge_shards(folder, chapter)
    ir.write_text(answer, "Corrected answer\n")
    with pytest.raises(ValueError, match="changed|snapshot"):
        batch.merge_shards(folder, chapter)
    assert answer.read_text(encoding="utf-8") == "Corrected answer\n"


@pytest.mark.parametrize("snapshot", [None, {}, {"document": "bad", "shared": "bad", "assets": {}}])
def test_legacy_or_invalid_snapshot_requires_a_fresh_plan(chapter, tmp_path, snapshot):
    folder = _plan(chapter, tmp_path)
    manifest_path = folder / batch.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshot"] = snapshot
    ir.write_text(manifest_path, ir.dumps(manifest))
    before = (chapter / "comic.json").read_bytes()
    with pytest.raises(ValueError, match="snapshot"):
        batch.merge_shards(folder, chapter)
    assert (chapter / "comic.json").read_bytes() == before


@pytest.mark.parametrize("change", ["changed", "removed", "added"])
def test_worker_glossary_file_changes_are_never_silently_discarded(chapter, tmp_path, change):
    if change == "added":
        (chapter / "glossary.json").unlink()
    folder = _plan(chapter, tmp_path)
    glossary = folder / "shard-001" / "glossary.json"
    if change == "removed":
        glossary.unlink()
    else:
        ir.write_text(glossary, '{"characters": ["New shared decision"]}\n')
    before = (chapter / "comic.json").read_bytes()
    draft = glossary.read_bytes() if glossary.exists() else None
    with pytest.raises(ValueError, match="shared glossary"):
        batch.merge_shards(folder, chapter)
    assert (chapter / "comic.json").read_bytes() == before
    assert (glossary.read_bytes() if glossary.exists() else None) == draft


def test_per_page_mask_modes_merge_and_replay_without_losing_freshness(chapter, tmp_path):
    document = chapter / "comic.json"
    masks.build_document(document, solid_free=False)
    folder = _plan(chapter, tmp_path)
    shard_document = folder / "shard-001" / "comic.json"
    masks.build_document(shard_document, pages=["p0031"], solid_free=True)
    assert ir.load_doc(shard_document)["meta"]["free_lettering_mask"] == "solid"

    batch.merge_shards(folder, chapter)
    merged = ir.load_doc(document)
    assert merged["meta"]["free_lettering_mask"] == "glyphs"
    for page in merged["pages"]:
        solid = page["id"] == "p0031"
        assert page["free_lettering_mask"] == ("solid" if solid else "glyphs")
        assert page["mask_options"]["solid_free"] is solid
        assert merged["stages"]["masks"]["page_options"][page["id"]]["solid_free"] is solid
    assert stages.stale_pages(merged, "masks") == []

    before = document.read_bytes()
    batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before
    assert stages.stale_pages(ir.load_doc(document), "masks") == []


@pytest.mark.parametrize("source_solid", [False, True])
def test_legacy_page_mask_fallback_cannot_change_across_merge(chapter, tmp_path, source_solid):
    document = chapter / "comic.json"
    masks.build_document(document, solid_free=source_solid)
    old = ir.load_doc(document)
    old["pages"][1].pop("free_lettering_mask")
    ir.save_doc(old, document)
    folder = _plan(chapter, tmp_path)
    shard_document = folder / "shard-001" / "comic.json"
    masks.build_document(shard_document, pages=["p0031"], solid_free=not source_solid)
    before = document.read_bytes()
    draft = shard_document.read_bytes()

    with pytest.raises(ValueError, match="legacy.*mask"):
        batch.merge_shards(folder, chapter)
    assert document.read_bytes() == before
    assert shard_document.read_bytes() == draft

    # Rebuilding that page records its actual mode and makes the merge safe.
    masks.build_document(shard_document, pages=["p0029"], solid_free=source_solid)
    batch.merge_shards(folder, chapter)
    assert stages.stale_pages(ir.load_doc(document), "masks") == []


def test_exact_replay_skips_republishing_assets(chapter, tmp_path, monkeypatch):
    document = chapter / "comic.json"
    masks.build_document(document, solid_free=False)
    folder = _plan(chapter, tmp_path)
    shard_document = folder / "shard-001" / "comic.json"
    masks.build_document(shard_document, pages=["p0031"], solid_free=True)

    batch.merge_shards(folder, chapter)
    before = document.read_bytes()

    def _forbid_publish(*_args, **_kwargs):
        raise AssertionError("exact no-op replay must not call _publish")

    monkeypatch.setattr(batch, "_publish", _forbid_publish)
    report = batch.merge_shards(folder, chapter)
    assert report["document"] == str(document.resolve())
    assert document.read_bytes() == before
