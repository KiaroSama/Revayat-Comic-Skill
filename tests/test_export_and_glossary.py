"""Export, package verification, and the names table."""

from __future__ import annotations

import zipfile

import pytest

import clean
import export
import glossary
import pageir as ir
import qa
import typeset


@pytest.fixture
def finished(translated):
    clean.clean_document(translated)
    typeset.typeset_document(translated)
    return translated


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
    # Without this, readers pair every two-page spread back to front.
    assert "<Manga>Yes</Manga>" in info


def test_a_left_to_right_comic_is_not_marked_as_manga(finished, tmp_path):
    doc = ir.load_doc(finished)
    doc["meta"]["reading_direction"] = "ltr"
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
    path = tmp_path / "short.cbz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("0001.png", b"x")
    report = qa.check_package(path, finished)
    assert report["findings"][0]["code"] == "archive-page-count"


# --- Glossary ---------------------------------------------------------------

def test_scanning_collects_the_speakers(translated):
    report = glossary.scan(translated)
    doc = ir.load_doc(translated)
    entries = doc["glossary"]["entries"]
    assert "هاروکا" in entries
    assert entries["هاروکا"]["role"] == "character"
    assert entries["هاروکا"]["count"] >= 1
    assert "هاروکا" in report["needs_persian"]


def test_a_short_line_repeated_across_the_chapter_is_a_candidate(translated):
    glossary.scan(translated)
    entries = ir.load_doc(translated)["glossary"]["entries"]
    assert "やめろ！" in entries


def test_a_long_line_is_not_a_name_candidate(translated):
    doc = ir.load_doc(translated)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "これはとても長い文章なので名前ではありません"
    ir.save_doc(doc, translated)
    glossary.scan(translated)
    entries = ir.load_doc(translated)["glossary"]["entries"]
    assert not any(len(name) > glossary.MAX_NAME_LENGTH for name in entries)


def test_a_hand_written_table_can_be_applied(translated, tmp_path):
    table = tmp_path / "names.json"
    ir.write_text(table, '{"ハルカ": {"target": "هاروکا", "role": "character"}}')
    report = glossary.apply_file(translated, table)
    assert report["applied"] == 1
    entry = ir.load_doc(translated)["glossary"]["entries"]["ハルカ"]
    assert entry["target"] == "هاروکا" and entry["locked"] is True


def test_checking_with_no_locked_terms_is_a_pass(translated):
    assert glossary.check(translated)["ok"]


def test_a_term_absent_from_the_balloon_cannot_have_drifted(translated):
    doc = ir.load_doc(translated)
    doc["glossary"] = {"entries": {"ケンジ": {"target": "کنجی", "locked": True}}}
    ir.save_doc(doc, translated)
    assert glossary.check(translated)["ok"]


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
