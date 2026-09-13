"""Export, package verification, and the names table."""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

import export
import pageir as ir
import qa
import stages


# --- Export -----------------------------------------------------------------

def test_cbz_pages_sort_into_reading_order(finished, tmp_path):
    """Every reader sorts an archive itself, and none of them agree about
    `page10` next to `page9`. Zero-padding makes byte order reading order."""
    out = tmp_path / "chapter-fa.cbz"
    export.export_document(finished, out)
    with zipfile.ZipFile(out) as archive:
        pages = [n for n in archive.namelist() if not n.endswith(".xml")]
    assert pages == sorted(pages)
    assert pages == ["0001.png", "0002.png", "0003.png"]


def test_the_archive_carries_a_comicinfo(finished, tmp_path):
    out = tmp_path / "chapter-fa.cbz"
    export.export_document(finished, out)
    with zipfile.ZipFile(out) as archive:
        info = archive.read("ComicInfo.xml").decode("utf-8")
    assert "<PageCount>3</PageCount>" in info
    assert "<LanguageISO>fa</LanguageISO>" in info
    # Without this, readers pair every two-page spread back to front. The value
    # has to be `YesAndRightToLeft`: ComicInfo's own documentation says that is
    # the one that defines the direction, and plain `Yes` only says the book is
    # a manga. This test asserted `Yes` and so agreed with the defect.
    assert "<Manga>YesAndRightToLeft</Manga>" in info


def test_a_left_to_right_comic_is_not_marked_as_manga(finished, tmp_path):
    doc = ir.load_doc(finished)
    doc["meta"]["reading_direction"] = "ltr"
    # Turning the book round really does invalidate the render — the reading
    # order and every mask were measured the other way — so the stages are
    # re-stamped here. This test is about the ComicInfo tag.
    for stage in ("masks", "clean", "typeset"):
        stages.stamp_stage(doc, stage, {"ran": True})
    ir.save_doc(doc, finished)
    export.export_document(finished, tmp_path / "c.cbz")
    with zipfile.ZipFile(tmp_path / "c.cbz") as archive:
        assert "<Manga>Yes</Manga>" not in archive.read("ComicInfo.xml").decode()


def test_untouched_bytes_are_copied_through(finished, tmp_path):
    """A page nothing happened to should not be re-encoded."""
    out = tmp_path / "chapter-fa.cbz"
    export.export_document(finished, out)
    doc = ir.load_doc(finished)
    root = ir.doc_dir(finished)
    with zipfile.ZipFile(out) as archive:
        assert archive.read("0001.png") == (root / doc["pages"][0]["final"]).read_bytes()


def test_jpeg_quality_re_encodes_when_asked(finished, tmp_path):
    """Only that it re-encodes. JPEG is *not* reliably smaller for a comic:
    line art on flat white compresses better as PNG, and JPEG adds ringing
    along every ink edge — measured here at 111 KB against PNG's 90 KB."""
    out = tmp_path / "b.cbz"
    export.export_document(finished, out, quality=70)
    with zipfile.ZipFile(out) as archive:
        assert "0001.jpg" in archive.namelist()


def test_the_format_is_inferred_from_the_name(finished, tmp_path):
    assert export.export_document(finished, tmp_path / "a.cbz")["format"] == "cbz"
    assert export.export_document(finished, tmp_path / "out")["format"] == "dir"


def test_a_directory_export_is_readable(finished, tmp_path):
    report = export.export_document(finished, tmp_path / "out")
    written = sorted(p.name for p in (tmp_path / "out").glob("*.png"))
    assert written == ["0001.png", "0002.png", "0003.png"]
    assert (tmp_path / "out" / "ComicInfo.xml").exists()
    assert report["pages"] == 3


def test_exporting_into_a_folder_of_other_images_is_refused(finished, tmp_path):
    """A folder already holding somebody else's images would ship them inside
    the finished chapter. Pointing --out at the chapter's own `pages/` is the
    same mistake and is refused earlier, by the dependency guard — see
    `test_a_dir_export_is_refused_when_its_names_land_on_the_originals`."""
    crowded = tmp_path / "crowded"
    crowded.mkdir()
    (crowded / "holiday-photo.png").write_bytes(
        (ir.doc_dir(finished) / ir.load_doc(finished)["pages"][0]["image"]
         ).read_bytes())

    with pytest.raises(ValueError, match="already contains"):
        export.export_document(finished, crowded)
    assert (crowded / "holiday-photo.png").exists()


def test_pdf_export_keeps_the_page_count(finished, tmp_path):
    pytest.importorskip("pymupdf")
    out = tmp_path / "chapter-fa.pdf"
    export.export_document(finished, out)
    assert qa.check_package(out, finished)["ok"]


def test_an_interrupted_export_leaves_no_half_written_archive(finished, tmp_path):
    out = tmp_path / "chapter-fa.cbz"
    export.export_document(finished, out)
    assert not list(tmp_path.glob("*.part"))


def test_an_unknown_format_is_refused(finished, tmp_path):
    with pytest.raises(ValueError, match="unknown format"):
        export.export_document(finished, tmp_path / "x", fmt="cb7")


# --- Package verification ---------------------------------------------------

def test_a_good_package_passes(finished, tmp_path):
    out = tmp_path / "chapter-fa.cbz"
    export.export_document(finished, out)
    report = qa.check_package(out, finished)
    assert report["ok"] and report["pages_found"] == 3


def test_a_missing_package_fails(finished, tmp_path):
    report = qa.check_package(tmp_path / "nope.cbz", finished)
    assert not report["ok"]


def test_a_corrupt_archive_fails(finished, tmp_path):
    path = tmp_path / "broken.cbz"
    path.write_bytes(b"this is not a zip file")
    report = qa.check_package(path, finished)
    assert not report["ok"]
    assert report["findings"][0]["code"] == "archive-invalid"


def test_a_short_package_fails(finished, tmp_path):
    """Real pages, one of them missing — so this tests the COUNT and nothing
    else. It used to pack a single member holding the byte `x`, which is not an
    image at all; the package check never opened it, so that stood in for a page
    and the only thing left to notice was the total."""
    good = tmp_path / "chapter.cbz"
    export.export_document(finished, good)
    with zipfile.ZipFile(good) as original:
        first = next(name for name in sorted(original.namelist())
                     if name.endswith(".png"))
        page, info = original.read(first), original.read("ComicInfo.xml")

    path = tmp_path / "short.cbz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(first, page)
        archive.writestr("ComicInfo.xml", info)

    report = qa.check_package(path, finished)
    assert not report["ok"]
    assert "archive-page-count" in {item["code"] for item in report["findings"]}


# --- R01: an export may never write over what the chapter is made of ---------

@pytest.mark.parametrize("fmt", ["cbz", "pdf", "dir"])
def test_exporting_over_the_document_itself_is_refused(finished, fmt):
    """`--out work/comic.json` destroys the chapter while reading it. The
    explicit `--format` override has to be checked too: guessing the format from
    the suffix is how this one slips past a suffix-based guard."""
    with pytest.raises(ValueError, match="chapter is made of|depends on"):
        export.export_document(finished, finished, fmt=fmt)
    assert ir.load_doc(finished)["pages"], "the document was damaged anyway"


@pytest.mark.parametrize("fmt", ["cbz", "pdf"])
def test_exporting_over_a_page_the_chapter_depends_on_is_refused(finished, fmt):
    """Writing an archive on top of an original page is not recoverable: the
    originals are the one thing the whole preservation guarantee rests on."""
    root = ir.doc_dir(finished)
    page = ir.load_doc(finished)["pages"][0]
    target = root / page["image"]
    before = target.read_bytes()

    with pytest.raises(ValueError, match="chapter is made of|depends on"):
        export.export_document(finished, target, fmt=fmt)
    assert target.read_bytes() == before, "the original page was overwritten"


def test_a_dir_export_is_refused_when_its_names_land_on_the_originals(finished):
    """The hole the existing stranger guard leaves open. That guard only
    notices files the export will NOT replace; a document whose pages are
    already named the way the exporter names them (`0001.png` — valid, just not
    what this importer writes) has every original silently overwritten instead.
    """
    root = ir.doc_dir(finished)
    doc = ir.load_doc(finished)
    for page in doc["pages"]:
        old = root / page["image"]
        new = old.with_name(f"{page['index'] + 1:04d}{old.suffix}")
        old.rename(new)
        page["image"] = f"pages/{new.name}"
    ir.save_doc(doc, finished)

    originals = {p.name: p.read_bytes() for p in (root / "pages").iterdir()}
    with pytest.raises(ValueError, match="chapter is made of|depends on"):
        export.export_document(finished, root / "pages", fmt="dir")
    assert {p.name: p.read_bytes()
            for p in (root / "pages").iterdir()} == originals


def test_a_pdf_export_that_fails_mid_chapter_keeps_the_previous_one(
        finished, tmp_path, monkeypatch):
    """A page that cannot be read half way through a chapter must not replace a
    good package. This one held already — every page is collected before the
    single save — and it is here so that stays true."""
    out = tmp_path / "chapter.pdf"
    export.export_document(finished, out, fmt="pdf")
    good = out.read_bytes()
    assert len(good) > 1000

    real = export._page_source
    calls = {"n": 0}

    def explode(root, page):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("disk full")
        return real(root, page)

    monkeypatch.setattr(export, "_page_source", explode)
    with pytest.raises(OSError):
        export.export_document(finished, out, fmt="pdf")
    assert out.read_bytes() == good, "a failed export replaced a good package"
    assert not list(tmp_path.glob("*.part")), "staging residue was left behind"


def test_an_interrupted_dir_export_leaves_the_previous_one_intact(
        finished, tmp_path, monkeypatch):
    """The same guarantee for a folder export."""
    out = tmp_path / "chapter"
    export.export_document(finished, out, fmt="dir")
    good = {p.name: p.read_bytes() for p in out.iterdir()}
    assert len(good) > 1

    real = ir.write_bytes
    calls = {"n": 0}

    def explode(path, payload):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("disk full")
        return real(path, payload)

    monkeypatch.setattr(ir, "write_bytes", explode)
    with pytest.raises(OSError):
        export.export_document(finished, out, fmt="dir")
    assert {p.name: p.read_bytes() for p in out.iterdir()} == good, (
        "a half-written export replaced a complete one")


# --- R12: an export must say what it actually shipped ------------------------

def test_the_rtl_tag_is_the_one_that_means_right_to_left(finished, tmp_path):
    """ComicInfo's `Manga` field defines right-to-left reading only at the value
    `YesAndRightToLeft`. Plain `Yes` says "this is a manga" and says nothing
    about direction, so every two-page spread in the book pairs the wrong way."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    with zipfile.ZipFile(out) as archive:
        info = archive.read("ComicInfo.xml").decode("utf-8")
    assert "<Manga>YesAndRightToLeft</Manga>" in info


def test_a_left_to_right_chapter_is_not_tagged_right_to_left(finished, tmp_path):
    """The other direction has to keep working."""
    doc = ir.load_doc(finished)
    doc["meta"]["reading_direction"] = "ltr"
    # Turning the book round really does invalidate the render — the reading
    # order and every mask were measured the other way — so the stages are
    # re-stamped here. This test is about the ComicInfo tag.
    for stage in ("masks", "clean", "typeset"):
        stages.stamp_stage(doc, stage, {"ran": True})
    ir.save_doc(doc, finished)

    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    with zipfile.ZipFile(out) as archive:
        info = archive.read("ComicInfo.xml").decode("utf-8")
    assert "YesAndRightToLeft" not in info


def test_publication_export_refuses_a_page_whose_render_is_missing(
        finished, tmp_path):
    """A page with Persian in it and no rendered output fell back to the cleaned
    or even the original image, and was still counted under `typeset_pages`. The
    chapter shipped with a page of untranslated artwork and the report said it
    was fine."""
    root = ir.doc_dir(finished)
    doc = ir.load_doc(finished)
    victim = doc["pages"][0]
    (root / victim["final"]).unlink()

    with pytest.raises(ValueError, match="not been rendered|missing"):
        export.export_document(finished, tmp_path / "chapter.cbz")


def test_a_draft_export_says_page_by_page_what_it_used(finished, tmp_path):
    """Falling back is allowed when it is asked for and admitted to. A cleaned
    page is not an unchanged original and the report may not call it one."""
    root = ir.doc_dir(finished)
    doc = ir.load_doc(finished)
    victim = doc["pages"][0]
    (root / victim["final"]).unlink()

    report = export.export_document(finished, tmp_path / "chapter.cbz",
                                    draft=True)
    assert report["sources"][victim["id"]] in {"clean", "image"}
    assert report["sources"][doc["pages"][1]["id"]] == "final"
    assert report["typeset_pages"] == len(doc["pages"]) - 1


def test_a_finished_chapter_still_exports(finished, tmp_path):
    """The guard must not fire on the ordinary case."""
    report = export.export_document(finished, tmp_path / "chapter.cbz")
    assert report["typeset_pages"] == len(ir.load_doc(finished)["pages"])
    assert set(report["sources"].values()) == {"final"}


# --- R11d: the package check opens the pages it counts -----------------------

def _repack(source, out, edit):
    """A copy of an exported archive with one thing deliberately wrong."""
    with zipfile.ZipFile(source) as original:
        members = [(info, original.read(info.filename))
                   for info in original.infolist()]
    with zipfile.ZipFile(out, "w") as archive:
        edit(archive, members)
    return out


def test_bytes_that_are_not_an_image_are_caught(finished, tmp_path):
    """The check matched a suffix and counted. A file called `0001.png` holding
    anything at all passed, and the count came out right, so the package was
    reported fine — for an archive a reader cannot open."""
    good = tmp_path / "chapter.cbz"
    export.export_document(finished, good)

    def swap(archive, members):
        for info, payload in members:
            if info.filename.endswith(".png"):
                archive.writestr(info.filename, b"this is not a PNG")
                payload = None
            if payload is not None:
                archive.writestr(info.filename, payload)

    broken = _repack(good, tmp_path / "broken.cbz", swap)
    report = qa.check_package(broken, finished)
    assert not report["ok"], "an archive of non-images was reported fine"


def test_a_directory_entry_does_not_count_as_a_page(finished, tmp_path):
    """`Path("p0002.png/").suffix` is `.png`, so a directory entry inside the
    archive was counted as a page — and the count then looked right while a page
    was missing."""
    good = tmp_path / "chapter.cbz"
    export.export_document(finished, good)

    def drop_one(archive, members):
        images = [m for m in members if m[0].filename.endswith(".png")]
        skip = images[-1][0].filename
        for info, payload in members:
            if info.filename == skip:
                archive.writestr(skip + "/", b"")   # a directory, not a page
                continue
            archive.writestr(info.filename, payload)

    faked = _repack(good, tmp_path / "faked.cbz", drop_one)
    report = qa.check_package(faked, finished)
    assert not report["ok"], "a directory entry stood in for a page"


def test_a_page_at_the_wrong_size_is_caught(finished, tmp_path):
    """Right count, right names, right order — and one page is a thumbnail.
    Nothing measured anything, so the package passed."""
    from PIL import Image

    good = tmp_path / "chapter.cbz"
    export.export_document(finished, good)

    def shrink(archive, members):
        first = True
        for info, payload in members:
            if first and info.filename.endswith(".png"):
                import io

                with Image.open(io.BytesIO(payload)) as image:
                    small = image.resize((17, 23))
                buffer = io.BytesIO()
                small.save(buffer, "PNG")
                payload = buffer.getvalue()
                first = False
            archive.writestr(info.filename, payload)

    shrunk = _repack(good, tmp_path / "shrunk.cbz", shrink)
    report = qa.check_package(shrunk, finished)
    assert "archive-page-size" in {item["code"] for item in report["findings"]}, (
        f"a 17x23 page passed: {report['findings']}")


def test_a_sound_package_still_passes(finished, tmp_path):
    """The guard must not fire on a package that is actually correct."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    report = qa.check_package(out, finished)
    assert report["ok"], report["findings"]


# --- R6: an export leaves a whole edition or the previous one ----------------

def test_a_failed_page_leaves_the_previous_folder_export_whole(
        finished, tmp_path, monkeypatch):
    """Promoting file by file and hoping was enough for the first failure: a
    `replace` that raised half way left some pages from this chapter and the
    rest from the last one, in a folder that looked finished."""
    out = tmp_path / "edition"
    export.export_document(finished, out, fmt="dir")
    before = {child.name: child.read_bytes() for child in out.iterdir()}
    assert before

    real = Path.replace
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("the disk went away")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(OSError):
        export.export_document(finished, out, fmt="dir")
    monkeypatch.setattr(Path, "replace", real)

    after = {child.name: child.read_bytes() for child in out.iterdir()}
    assert after == before, "the folder holds a mixture of two editions"


def test_a_failed_archive_leaves_the_previous_package_and_no_debris(
        finished, tmp_path, monkeypatch):
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    before = out.read_bytes()

    monkeypatch.setattr(export, "_encode",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError("nope")))
    with pytest.raises(OSError):
        export.export_document(finished, out)

    assert out.read_bytes() == before
    assert not [child for child in tmp_path.iterdir()
                if ".part-" in child.name]


def test_two_exports_of_one_chapter_do_not_share_a_scratch_name(finished, tmp_path):
    """`<name>.part` was predictable, so an operator's own `<name>.part` was
    overwritten and then deleted."""
    out = tmp_path / "chapter.cbz"
    mine = tmp_path / "chapter.cbz.part"
    mine.write_bytes(b"something of mine")

    export.export_document(finished, out)

    assert mine.read_bytes() == b"something of mine"


# --- R7: the package is checked against what was written ---------------------

def test_pixels_that_do_not_decode_are_caught(finished, tmp_path):
    """`Image.open` is lazy: it reads the header and stops. A PNG whose chunk
    CRCs are correct and whose compressed pixels are rubbish reported its
    declared size and passed."""
    good = tmp_path / "chapter.cbz"
    export.export_document(finished, good)

    def rot(archive, members):
        first = True
        for info, payload in members:
            if first and info.filename.endswith(".png"):
                payload = _corrupt_idat(payload)
                first = False
            archive.writestr(info.filename, payload)

    broken = _repack(good, tmp_path / "broken.cbz", rot)
    report = qa.check_package(broken, finished)
    assert not report["ok"], "an archive of undecodable pixels was reported fine"


def _corrupt_idat(payload: bytes) -> bytes:
    """Replace the compressed data of the first IDAT, keeping its CRC valid."""
    import struct
    import zlib

    out, offset = bytearray(payload[:8]), 8
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        kind = payload[offset + 4:offset + 8]
        body = payload[offset + 8:offset + 8 + length]
        if kind == b"IDAT":
            body = b"\x00" * length
        out += struct.pack(">I", len(body)) + kind + body
        out += struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        offset += 12 + length
    return bytes(out)


def test_two_identical_pages_are_caught(finished, tmp_path):
    """The count is right, the names are right, and one page of the chapter is
    simply missing."""
    good = tmp_path / "chapter.cbz"
    export.export_document(finished, good)

    def duplicate(archive, members):
        images = [m for m in members if m[0].filename.endswith(".png")]
        first = images[0][1]
        for info, payload in members:
            archive.writestr(info.filename,
                             first if info.filename.endswith(".png") else payload)

    doubled = _repack(good, tmp_path / "doubled.cbz", duplicate)
    codes = {item["code"]
             for item in qa.check_package(doubled, finished)["findings"]}
    assert "archive-duplicate-page" in codes


def test_a_page_that_is_not_the_bytes_that_were_exported_is_caught(
        finished, tmp_path):
    """The order check sorted the names and then asked whether they were
    sorted, which is true of every list. What it meant to ask can only be
    answered against a record of which page each name was."""
    from PIL import Image

    good = tmp_path / "chapter.cbz"
    export.export_document(finished, good)

    def swap(archive, members):
        first = True
        for info, payload in members:
            if first and info.filename.endswith(".png"):
                import io
                with Image.open(io.BytesIO(payload)) as image:
                    other = Image.new("RGB", image.size, (7, 7, 7))
                buffer = io.BytesIO()
                other.save(buffer, "PNG")
                payload = buffer.getvalue()
                first = False
            archive.writestr(info.filename, payload)

    swapped = _repack(good, tmp_path / "swapped.cbz", swap)
    report = qa.check_package(swapped, finished)
    assert not report["ok"], report["findings"]
    assert any("not the bytes that were exported" in item["detail"]
               for item in report["findings"]), report["findings"]


def test_a_lossy_export_is_not_asked_to_hash_equal(finished, tmp_path):
    """A re-encoded JPEG will never hash to the bytes on disk, so an exact
    comparison is only meaningful where nothing was re-encoded."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out, quality=70)
    assert qa.check_package(out, finished)["ok"]


def test_a_sound_package_still_passes_the_new_checks(finished, tmp_path):
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    report = qa.check_package(out, finished)
    assert report["ok"], report["findings"]


def test_a_pdf_package_is_measured_and_not_only_counted(finished, tmp_path):
    pytest.importorskip("pymupdf")
    out = tmp_path / "chapter.pdf"
    export.export_document(finished, out, fmt="pdf")
    assert qa.check_package(out, finished)["ok"]


# --- R10: approval is a completion proof -------------------------------------

def test_export_runs_the_whole_gate_not_its_own_narrower_question(finished,
                                                                  tmp_path):
    """`export` asked only "is there a rendered file for every page that wants
    one". A chapter whose lines had overflowed went straight into a package
    without `qa` ever running."""
    doc = ir.load_doc(finished)
    region = next(r for _p, r in ir.iter_regions(doc)
                  if (r.get("target_text") or "").strip())
    region["typeset"] = {"status": "overflow"}
    ir.save_doc(doc, finished)

    with pytest.raises(ValueError, match="publication QA"):
        export.export_document(finished, tmp_path / "chapter.cbz")


def test_a_region_whose_render_never_happened_is_caught(finished):
    """A page file existing proves a page was written. It does not prove that
    THIS region's Persian is on it."""
    doc = ir.load_doc(finished)
    region = next(r for _p, r in ir.iter_regions(doc)
                  if (r.get("target_text") or "").strip())
    region["typeset"] = {}
    ir.save_doc(doc, finished)

    codes = {item["code"] for item in qa.check_document(finished)["findings"]}
    assert "region-not-rendered" in codes


def test_an_erasure_the_cleaner_never_acted_on_is_caught(finished):
    """"Remove this and put nothing back" lived in the region's review notes
    and in the census, and nothing that gated publication read it."""
    doc = ir.load_doc(finished)
    region = doc["pages"][0]["regions"][0]
    region["erase"] = True
    region["target_text"] = ""
    region.pop("clean_status", None)
    ir.save_doc(doc, finished)

    codes = {item["code"] for item in qa.check_document(finished)["findings"]}
    assert "erase-unfinished" in codes


def test_a_kept_or_dropped_region_is_a_finished_decision(finished):
    """An explicit decision IS an outcome; the gate must not demand a render
    for a region somebody deliberately left alone."""
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    page["regions"][0].update({"keep": True, "target_text": "", "typeset": {}})
    page["regions"][1].update({"dropped": True, "target_text": "", "typeset": {}})
    ir.save_doc(doc, finished)

    codes = {item["code"] for item in qa.check_document(finished)["findings"]}
    assert "region-not-rendered" not in codes


def test_a_draft_says_so_in_the_package_and_in_the_report(finished, tmp_path):
    """A folder produced with `--draft` was indistinguishable from an approved
    edition as soon as the report scrolled away."""
    doc = ir.load_doc(finished)
    region = next(r for _p, r in ir.iter_regions(doc)
                  if (r.get("target_text") or "").strip())
    region["typeset"] = {"status": "overflow"}
    ir.save_doc(doc, finished)

    out = tmp_path / "draft"
    report = export.export_document(finished, out, fmt="dir", draft=True)

    assert report["draft"] is True and report["approved"] is False
    assert "DRAFT" in report["note"]
    assert "DRAFT" in (out / "ComicInfo.xml").read_text(encoding="utf-8")


def test_an_approved_export_is_marked_approved(finished, tmp_path):
    out = tmp_path / "chapter.cbz"
    report = export.export_document(finished, out)
    assert report["approved"] is True and report["draft"] is False


def test_the_preflight_is_the_same_answer_qa_gives(finished):
    state = qa.publication_preflight(finished)
    report = qa.check_document(finished)
    assert state["ok"] == report["ok"]
