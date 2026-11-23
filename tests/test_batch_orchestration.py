"""Batch plans isolate writer state and merge only validated page results."""

import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

import pageir as ir
import stages
import worksheet

CLI = Path(ir.__file__).with_name("revayat-comic.py")


def _run(*args):
    result = subprocess.run([sys.executable, str(CLI), "batch", *map(str, args)],
                            capture_output=True, encoding="utf-8", timeout=20)
    return result


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _png(path, size=(64, 48), color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


@pytest.fixture
def chapter(tmp_path):
    root = tmp_path / "prepared"
    doc = ir.new_doc(title="Chapter")
    doc["meta"]["worksheets"] = str(root / "notes")
    for ix, page_id in enumerate(["p0031", "p0029", "p0034", "p0032", "p0030"]):
        image = f"pages/{page_id}.png"
        original = _png(root / image, size=(64 + ix, 48))
        page = ir.new_page(page_id, ix, image, 64 + ix, 48, ir.sha256_file(original))
        region = ir.new_region(f"{page_id}r007", [12, 12, 30, 20])
        region["mask"] = f"masks/{page_id}/{region['id']}.png"
        _png(root / region["mask"], size=(30, 20))
        page["regions"].append(region)
        doc["pages"].append(page)
        notes = root / "notes"
        notes.mkdir(exist_ok=True)
        (notes / f"{page_id}.txt").write_text("Original worksheet\n", encoding="utf-8")
    ir.save_doc(doc, root / "comic.json")
    (root / "glossary.json").write_text('{"characters": []}\n', encoding="utf-8")
    return root


def _plan(chapter, batch_dir):
    planned = _run("plan-shards", chapter, "--shards", 2, "--out", batch_dir)
    assert planned.returncode == 0, planned.stderr or planned.stdout
    assert json.loads(planned.stdout)["ok"] is True
    return _json(batch_dir / "batch-manifest.json")


def test_cli_plans_disjoint_shards_and_merges_concurrent_writes(chapter, tmp_path):
    batch_dir = tmp_path / "parallel"
    manifest = _plan(chapter, batch_dir)
    assert manifest["mode"] == "shards"
    assert manifest["workers"] == 2
    assert [item["id"] for item in manifest["items"]] == ["shard-001", "shard-002"]
    assert [item["pages"] for item in manifest["items"]] == [[0, 3], [3, 5]]
    assert {item["status"] for item in manifest["items"]} == {"pending"}
    original = _json(chapter / "comic.json")["pages"]

    def worker(item):
        workdir = batch_dir / item["workdir"]
        doc_file = workdir / "comic.json"
        local = ir.load_doc(doc_file)
        first, stop = item["pages"]
        assert [p["id"] for p in local["pages"]] == [p["id"] for p in original[first:stop]]
        assert {p.name for p in (workdir / "pages").iterdir()} == {
            Path(p["image"]).name for p in local["pages"]
        }
        assert (workdir / "glossary.json").read_bytes() == (chapter / "glossary.json").read_bytes()
        notes = workdir / local["meta"]["worksheets"]
        for page in local["pages"]:
            region, = page["regions"]
            pid = page["id"]
            assert region["id"] == f"{pid}r007"
            assert (workdir / region["mask"]).is_file()
            assert (notes / f"{pid}.txt").read_text(encoding="utf-8") == "Original worksheet\n"
            region.update(target_text=f"سلام {pid}", speaker="آسانو", review=["check"],
                          locked=True, dropped=(pid == "p0032"))
            for stage in ("clean", "final"):
                page[stage] = f"{stage}/{pid}.png"
                _png(workdir / page[stage], (page["width"], page["height"]), "blue")
            (notes / f"{pid}.done.txt").write_text(f"سلام {pid}\n", encoding="utf-8")
        ir.save_doc(local, doc_file)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, manifest["items"]))
    assert not list((chapter / "notes").glob("*.done.txt"))
    assert _json(chapter / "comic.json")["pages"] == original

    # Completion order must not set the order in the merged document.
    manifest["items"].reverse()
    ir.write_text(batch_dir / "batch-manifest.json", ir.dumps(manifest))
    merged = _run("merge-shards", batch_dir, "--into", chapter)
    assert merged.returncode == 0, merged.stderr or merged.stdout
    assert json.loads(merged.stdout)["ok"] is True
    merged_pages = _json(chapter / "comic.json")["pages"]
    assert [p["id"] for p in merged_pages] == [p["id"] for p in original]
    for page in merged_pages:
        pid = page["id"]
        region, = page["regions"]
        assert region["target_text"] == f"سلام {pid}"
        assert region["speaker"] == "آسانو"
        assert region["review"] == ["check"]
        assert region["locked"] is True
        assert region["dropped"] == (pid == "p0032")
        assert (chapter / "notes" / f"{pid}.done.txt").read_text(encoding="utf-8") == f"سلام {pid}\n"
        for stage in ("clean", "final"):
            with Image.open(chapter / page[stage]) as image:
                assert image.size == (page["width"], page["height"])
                assert image.getpixel((0, 0)) == (0, 0, 255)
    payload = (chapter / "comic.json").read_bytes()
    repeated = _run("merge-shards", batch_dir, "--into", chapter)
    assert repeated.returncode == 0, repeated.stderr or repeated.stdout
    assert (chapter / "comic.json").read_bytes() == payload


@pytest.mark.parametrize("problem", ["overlap", "metadata-size", "image-size", "schema", "region-schema", "outside"])
def test_merge_rejects_invalid_shards_before_writing(chapter, tmp_path, problem):
    batch_dir = tmp_path / "parallel"
    manifest = _plan(chapter, batch_dir)
    first, second = [batch_dir / x["workdir"] / "comic.json" for x in manifest["items"]]
    before = (chapter / "comic.json").read_bytes()
    current = ir.load_doc(second)
    page = current["pages"][0]
    if problem == "overlap":
        page["id"] = ir.load_doc(first)["pages"][0]["id"]
    elif problem == "metadata-size":
        page["width"] += 1
    elif problem == "image-size":
        page["final"] = f"final/{page['id']}.png"
        _png(second.parent / page["final"], (11, 13))
    elif problem == "schema":
        current["version"] = -1
    elif problem == "region-schema":
        page["regions"][0]["target_text"] = ["سلام"]
    else:
        page["final"] = "../../outside.png"
        _png(tmp_path / "outside.png", (page["width"], page["height"]))
    ir.save_doc(current, second)
    rejected = _run("merge-shards", batch_dir, "--into", chapter)
    assert rejected.returncode != 0
    report = json.loads(rejected.stdout)
    assert report["ok"] is False
    assert {"overlap": "overlap", "metadata-size": "dimensions", "image-size": "dimensions",
            "schema": "schema", "region-schema": "schema", "outside": "outside"
            }[problem] in report["error"].lower()
    assert (chapter / "comic.json").read_bytes() == before
    assert not (chapter / "final").exists()


def test_book_plans_stage_independent_inputs_with_unique_slugs(tmp_path):
    library = tmp_path / "library"
    image = _png(library / "Loose pages" / "page1.png")
    with ZipFile(library / "Story.cbz", "w") as book:
        book.write(image, "page1.png")
    (library / "Story.cbr").write_bytes(b"opaque CBR fixture")
    (library / "Another.pdf").write_bytes(b"opaque PDF fixture")
    (library / "Unrelated.txt").write_text("not a comic", encoding="utf-8")
    out = tmp_path / "batch"
    result = _run("plan-books", library, "--out", out, "--workers", 50)
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout)
    assert report["ok"] is True
    manifest = _json(out / "batch-manifest.json")
    assert manifest["mode"] == "books"
    assert manifest["workers"] == 4
    assert len({item["id"].casefold() for item in manifest["items"]}) == 4
    for item in manifest["items"]:
        workdir = out / item["workdir"]
        assert workdir.parent == out / "books"
        assert item["status"] == "pending" and item["pages"] is None
        assert workdir.is_dir()
        assert item["input"]
    loose = next(item for item in manifest["items"] if item["id"] == "loose-pages")
    workdir = out / loose["workdir"]
    assert (workdir / loose["input"] / "page1.png").read_bytes() == image.read_bytes()
    shutil.rmtree(library)
    assert (workdir / loose["input"] / "page1.png").is_file()


def test_shards_merge_real_worksheet_receipts_and_stage_records(chapter, tmp_path):
    chapter_doc = chapter / "comic.json"
    worksheet.build_document(chapter_doc)
    batch_dir = tmp_path / "parallel"
    manifest = _plan(chapter, batch_dir)
    for item in manifest["items"]:
        shard = batch_dir / item["workdir"]
        shard_doc = shard / "comic.json"
        local = ir.load_doc(shard_doc)
        notes = ir.worksheet_folder(shard_doc, local)
        for page in local["pages"]:
            prompt = notes / f"{page['id']}.txt"
            reply = notes / f"{page['id']}.done.txt"
            text = prompt.read_text(encoding="utf-8")
            text = text.replace("src: \n", "src: Tokyo arrived.\n").replace("fa: \n", "fa: رسید.\n")
            reply.write_text(text, encoding="utf-8")
        merged = worksheet.merge_document(shard_doc)
        assert merged["ok"], merged
        assert not stages.stale_pages(ir.load_doc(shard_doc), "worksheet")

    merged = _run("merge-shards", batch_dir, "--into", chapter)
    assert merged.returncode == 0, merged.stderr or merged.stdout
    doc = ir.load_doc(chapter_doc)
    assert worksheet.status(chapter_doc)["merged"] == [page["id"] for page in doc["pages"]]
    assert not stages.stale_pages(doc, "worksheet")
    for page, region in ir.iter_regions(doc):
        assert region["source_text"] == "Tokyo arrived."
        assert region["target_text"] == "رسید."
        assert Path(page["worksheet_receipt"]["path"]).parent == chapter / "notes"


def test_shard_count_must_be_positive_and_no_larger_than_chapter(chapter):
    for count in (0, 6):
        result = _run("plan-shards", chapter, "--shards", count)
        assert result.returncode != 0
        assert json.loads(result.stdout)["ok"] is False
    assert not (chapter / "batch").exists()
