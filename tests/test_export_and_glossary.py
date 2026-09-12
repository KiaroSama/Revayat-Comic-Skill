"""Export, package verification, and the names table."""

from __future__ import annotations

import zipfile

import pytest

import export
import glossary
import pageir as ir
import qa


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


# --- R06: names, presented honestly and matched sensibly ---------------------

def _entries(doc_path, table):
    doc = ir.load_doc(doc_path)
    doc["glossary"] = {"entries": table}
    ir.save_doc(doc, doc_path)
    return doc


def test_unlocked_names_are_not_presented_as_binding(translated):
    """The table is headed "these are binding. Use exactly the Persian given."
    and then listed every entry that had a `target` — including the ones nobody
    had locked, which are the tool's own guesses. A translator told a guess is
    binding will spell the rest of the chapter to match it."""
    import worksheet

    _entries(translated, {
        "ハルカ": {"target": "هاروکا", "locked": True, "role": "character"},
        "ケンジ": {"target": "کنجی", "locked": False, "role": "character"},
    })
    lines = worksheet._glossary_table(ir.load_doc(translated))
    text = "\n".join(lines)

    assert "هاروکا" in text, "the locked name is missing"
    if "کنجی" in text:
        marks = [text.find(word) for word in
                 ("not binding", "Suggestion", "suggestion")]
        marks = [index for index in marks if index >= 0]
        assert marks and min(marks) < text.index("کنجی"), (
            "an unlocked guess is printed under the binding heading")


def test_a_long_name_is_not_clipped(translated):
    """Names were cut to 21 characters with no ellipsis, so the worksheet asked
    for a spelling that was not the spelling."""
    import worksheet

    long_name = "هاروکا-تاچیبانا-شینومیا"
    assert len(long_name) > 21
    _entries(translated, {"X": {"target": long_name, "locked": True}})
    text = "\n".join(worksheet._glossary_table(ir.load_doc(translated)))
    assert long_name in text, "the binding spelling was truncated"


def test_a_locked_name_is_never_pushed_out_by_suggestions(translated):
    """The table stopped after 40 rows with nothing said about it. Fill it with
    unlocked guesses and the one term that actually matters falls off the end —
    silently, so the chapter spells it two ways."""
    import worksheet

    table = {f"guess{n}": {"target": f"حدس{n}", "locked": False}
             for n in range(60)}
    table["ハナ"] = {"target": "هانا", "locked": True, "role": "character"}
    _entries(translated, table)

    text = "\n".join(worksheet._glossary_table(ir.load_doc(translated)))
    assert "هانا" in text, "the one locked term was pushed out by guesses"
    assert "60" in text or "not shown" in text or "more" in text, (
        "entries were left out with nothing saying so")


def test_a_short_latin_name_does_not_match_inside_a_longer_one(translated):
    """`Ann` inside `Anna` is not an occurrence of `Ann`, and reporting it as
    drift sends a translator to correct something that is already right."""
    import glossary

    doc = _entries(translated, {"Ann": {"target": "آن", "locked": True}})
    region = next(region for _, region in ir.iter_regions(doc))
    region["source_text"] = "Anna went home"
    # Deliberately without `آن` anywhere: otherwise the drift test passes
    # because the expected Persian happens to be a prefix of the real one.
    region["target_text"] = "او به خانه رفت"
    ir.save_doc(doc, translated)

    assert glossary.check(translated)["drift"] == []


def test_a_cjk_term_still_matches_inside_a_phrase(translated):
    """The fix for the line above must not be a word boundary: Japanese has no
    spaces, so `\\b束\\b` never matches anything and every CJK term would stop
    being enforced."""
    import glossary

    doc = _entries(translated, {"束": {"target": "دسته", "locked": True}})
    region = next(region for _, region in ir.iter_regions(doc))
    region["source_text"] = "束の間の休息"
    region["target_text"] = "استراحتی کوتاه"
    ir.save_doc(doc, translated)

    assert glossary.check(translated)["drift"], "a CJK term stopped being enforced"


def test_term_counts_are_refreshed_on_a_rescan(translated):
    """Speaker counts were refreshed and term counts were not, so a term that
    had almost left the chapter still looked like its most common word."""
    import glossary

    doc = ir.load_doc(translated)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
    ir.save_doc(doc, translated)
    glossary.scan(translated)
    before = ir.load_doc(translated)["glossary"]["entries"]["やめろ"]["count"]
    assert before >= 2

    doc = ir.load_doc(translated)
    for index, (_, region) in enumerate(ir.iter_regions(doc)):
        if index:
            region["source_text"] = "べつに"
    ir.save_doc(doc, translated)
    glossary.scan(translated)

    after = ir.load_doc(translated)["glossary"]["entries"]["やめろ"]["count"]
    assert after < before, f"the count stayed at {after} after the text changed"


def test_drift_totals_count_every_finding(translated):
    """`check` caps its list at 30 for display and reports the true total beside
    it. The gate filed one finding per row of the CAPPED list, so a chapter with
    50 drifting regions was reported as having 30."""
    import glossary

    doc = _entries(translated, {"やめろ": {"target": "بس کن", "locked": True}})
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
        region["target_text"] = "چیز دیگری"
    ir.save_doc(doc, translated)

    result = glossary.check(translated)
    report = qa.check_document(translated)
    filed = report["by_code"].get("glossary-drift", 0)
    assert filed == result["drift_count"], (
        f"filed {filed} of {result['drift_count']} drifting regions")


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


# --- a proposal is a candidate, and a canonical form keeps its history --------

def test_a_proposed_name_becomes_a_candidate_without_a_speaker(translated):
    doc = ir.load_doc(translated)
    for _page, region in ir.iter_regions(doc):
        region.pop("speaker", None)
    doc["pages"][0]["regions"][0]["proposed"] = ["Anna"]
    ir.save_doc(doc, translated)

    glossary.scan(translated)

    entry = ir.load_doc(translated)["glossary"]["entries"]["Anna"]
    assert entry["role"] == "mentioned"
    assert entry["count"] == 1


def test_being_mentioned_does_not_demote_a_character(translated):
    """A character who is also named in someone else's balloon must not stop
    being a character because the mention was scanned second."""
    doc = ir.load_doc(translated)
    doc["pages"][0]["regions"][0]["speaker"] = "Anna"
    doc["pages"][0]["regions"][-1]["proposed"] = ["Anna"]
    ir.save_doc(doc, translated)

    glossary.scan(translated)

    assert ir.load_doc(translated)["glossary"]["entries"]["Anna"]["role"] == \
        "character"


def test_changing_a_locked_form_keeps_the_one_it_replaces():
    """An approved spelling is a decision. Re-deciding it must not erase the
    chapter already translated against the first one."""
    entry = glossary._entry("Anna", role="character")
    glossary.set_target(entry, "آنا")
    assert entry["version"] == 1 and "previous" not in entry

    entry["locked"] = True
    glossary.set_target(entry, "آنّا")

    assert entry["target"] == "آنّا"
    assert entry["version"] == 2
    assert entry["previous"] == [{"target": "آنا", "version": 1}]


def test_an_unlocked_suggestion_has_no_history_to_keep():
    entry = glossary._entry("Ken", role="character")
    glossary.set_target(entry, "کن")
    glossary.set_target(entry, "کِن")
    assert entry["version"] == 1 and "previous" not in entry
