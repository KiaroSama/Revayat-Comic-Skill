"""Does this package hold the chapter the document describes?

Counting pages proves a package has the right number of sheets. Every test here
substitutes something that keeps the count, the names and the shape and changes
what the reader would actually see — which is the whole class of failure a
completeness check passes.
"""
from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

import export
import package as package_check
import pageir as ir
import qa


def _same_shape_image(width, height, colour=(255, 0, 0), fmt="PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, fmt)
    return buffer.getvalue()


def _page_shape(doc_path, index=0):
    page = ir.load_doc(doc_path)["pages"][index]
    return page["width"], page["height"]


# --------------------------------------------------------------------------- #
# The controls: a real export verifies
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,quality", [
    ("chapter.cbz", 0), ("chapter.cbz", 80), ("edition", 0), ("book.pdf", 0),
])
def test_a_real_export_verifies(finished, tmp_path, name, quality):
    out = tmp_path / name
    export.export_document(finished, out, quality=quality)

    report = qa.check_package(out, finished)

    assert report["ok"], report["findings"]


# --------------------------------------------------------------------------- #
# Substitution
# --------------------------------------------------------------------------- #

def test_a_same_size_page_swapped_into_an_archive_is_caught(finished, tmp_path):
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    width, height = _page_shape(finished)

    with zipfile.ZipFile(out) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    first = sorted(n for n in members if n.lower().endswith(".png"))[0]
    members[first] = _same_shape_image(width, height)
    with zipfile.ZipFile(out, "w") as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("not the bytes that were exported" in item["detail"]
               for item in report["findings"]), report["findings"]


def test_a_jpeg_page_is_verified_too(finished, tmp_path):
    """A control, and it passed before this repair — by accident. The hash was
    gated behind `lossy` and the flag was inverted, so a JPEG was recorded as
    lossless and therefore checked. Both halves are corrected here: the flag is
    truthful now AND the gate is gone, so this keeps passing for the right
    reason. The bypass it did not cover is the next test."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out, quality=80)
    manifest = ir.load_doc(finished)["stages"]["export"]["manifest"]
    assert any(row["name"].lower().endswith((".jpg", ".jpeg"))
               for row in manifest), manifest
    assert all(row["lossy"] for row in manifest
               if row["name"].lower().endswith((".jpg", ".jpeg")))

    width, height = _page_shape(finished)
    with zipfile.ZipFile(out) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    first = sorted(members)[0]
    members[first] = _same_shape_image(width, height, fmt="JPEG")
    with zipfile.ZipFile(out, "w") as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)

    assert not qa.check_package(out, finished)["ok"]


def test_a_lossy_manifest_row_is_still_hashed(finished, tmp_path):
    """THE bypass. `lossy` was read as "these bytes cannot be compared", so a
    row carrying it skipped the hash entirely — and `sha256` is the hash of the
    bytes the export WROTE, which is always comparable."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    doc = ir.load_doc(finished)
    for row in doc["stages"]["export"]["manifest"]:
        row["lossy"] = True
    ir.save_doc(doc, finished)
    width, height = _page_shape(finished)

    with zipfile.ZipFile(out) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    first = sorted(n for n in members if n.lower().endswith(".png"))[0]
    members[first] = _same_shape_image(width, height)
    with zipfile.ZipFile(out, "w") as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)

    assert not qa.check_package(out, finished)["ok"]


def test_a_pdf_replaced_by_an_unrelated_image_is_caught(finished, tmp_path):
    """The check asked whether each sheet's resource dictionary mentioned an
    image. A picture of the same shape satisfied it."""
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    export.export_document(finished, out)
    width, height = _page_shape(finished)

    forged = pymupdf.open()
    for page in ir.load_doc(finished)["pages"]:
        sheet = forged.new_page(width=page["width"], height=page["height"])
        sheet.insert_image(pymupdf.Rect(0, 0, page["width"], page["height"]),
                           stream=_same_shape_image(width, height))
    forged.save(str(out))
    forged.close()

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("does not show the page this export wrote" in item["detail"]
               for item in report["findings"]), report["findings"]


def test_an_off_page_image_does_not_count_as_the_page(finished, tmp_path):
    """An XObject placed outside the sheet is on the page as far as a resource
    listing is concerned, and invisible to a reader."""
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    doc = ir.load_doc(finished)
    export.export_document(finished, out)

    forged = pymupdf.open()
    for page in doc["pages"]:
        sheet = forged.new_page(width=page["width"], height=page["height"])
        # Drawn entirely past the right-hand edge.
        sheet.insert_image(
            pymupdf.Rect(page["width"] + 10, 0,
                         page["width"] + 60, 50),
            stream=_same_shape_image(50, 50))
    forged.save(str(out))
    forged.close()

    report = qa.check_package(out, finished)

    assert not report["ok"]
    # The sheet is blank to a reader, so the question is not which XObject the
    # resource dictionary lists — it is that nothing on it looks like the page.
    assert any("does not look like the page this export wrote" in item["detail"]
               for item in report["findings"]), report["findings"]


# --------------------------------------------------------------------------- #
# Bounded decoding
# --------------------------------------------------------------------------- #

def test_a_page_over_the_decode_limit_is_refused_not_passed(monkeypatch):
    """A resource limit turned into a successful verification: the size was
    returned, the decode was skipped, and nothing looked at the difference."""
    monkeypatch.setattr(package_check, "MAX_DECODE_PIXELS", 16)

    size, problem = package_check._page_size(_same_shape_image(40, 40))

    assert size == (40, 40)
    assert "cannot be verified" in problem


def test_a_corrupt_page_is_refused():
    size, problem = package_check._page_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)

    assert size is None and "not an image" in problem


def test_a_bomb_inside_an_archive_fails_the_package(finished, tmp_path,
                                                    monkeypatch):
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    monkeypatch.setattr(package_check, "MAX_DECODE_PIXELS", 16)

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("cannot be verified" in item["detail"]
               for item in report["findings"])


# --------------------------------------------------------------------------- #
# DRAFT, in the package
# --------------------------------------------------------------------------- #

def test_a_draft_pdf_says_so_inside_itself(translated, tmp_path):
    """A PDF is the format people forward, and a draft one was
    indistinguishable from an approved edition once the report scrolled away."""
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"

    export.export_document(translated, out, draft=True)

    with pymupdf.open(str(out)) as document:
        metadata = document.metadata
    assert "DRAFT" in (metadata.get("title") or "")
    assert "draft" in (metadata.get("keywords") or "").lower()


def test_an_approved_pdf_does_not_say_draft(finished, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"

    export.export_document(finished, out)

    with pymupdf.open(str(out)) as document:
        metadata = document.metadata
    assert "DRAFT" not in (metadata.get("title") or "")


def test_a_package_without_a_manifest_is_unverified_not_wrong(finished,
                                                              tmp_path):
    """Handled as legacy: an older package is not evidence of anything wrong,
    and re-exporting is the supported route back to a verified one."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    doc = ir.load_doc(finished)
    doc["stages"]["export"].pop("manifest", None)
    doc["stages"]["export"].pop("editions", None)
    ir.save_doc(doc, finished)

    report = qa.check_package(out, finished)
    assert not report["ok"]
    assert any(item["code"] == "archive-unverified" for item in report["findings"])


# --------------------------------------------------------------------------- #
# What the sheet SHOWS, which is not what it contains
# --------------------------------------------------------------------------- #

def _exported_page_bytes(doc_path, index=0):
    """The bytes of a page as the export shipped them, at quality 0."""
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    page = doc["pages"][index]
    return (root / (page.get("final") or page["image"])).read_bytes()


def _forge(doc_path, out, place):
    """A PDF of the right shape, holding THIS chapter's own page images.

    Every hash in the manifest still matches, because the bytes are the bytes
    that were exported. Only the placement differs, which is the whole point:
    `place(sheet, rect, payload)` decides what a reader would actually see.
    """
    import pymupdf

    forged = pymupdf.open()
    for index, page in enumerate(ir.load_doc(doc_path)["pages"]):
        sheet = forged.new_page(width=page["width"], height=page["height"])
        rect = pymupdf.Rect(0, 0, page["width"], page["height"])
        place(sheet, rect, _exported_page_bytes(doc_path, index))
    forged.save(str(out))
    forged.close()


def _place_plain(sheet, rect, payload):
    sheet.insert_image(rect, stream=payload)


def _place_rotated(sheet, rect, payload):
    sheet.insert_image(rect, stream=payload, rotate=90)


def _place_cropped(sheet, rect, payload):
    import pymupdf

    half = pymupdf.Rect(rect.x0, rect.y0, rect.x1 / 2, rect.y1)
    sheet.insert_image(half, stream=payload, keep_proportion=False)


def _place_under_overlay(sheet, rect, payload):
    sheet.insert_image(rect, stream=payload)
    sheet.draw_rect(rect, color=None, fill=(0, 0, 0), fill_opacity=1)


def _place_under_haze(sheet, rect, payload):
    sheet.insert_image(rect, stream=payload)
    sheet.draw_rect(rect, color=None, fill=(1, 1, 1), fill_opacity=0.6)


@pytest.mark.parametrize("place,why", [
    (_place_rotated, "turned on its side"),
    (_place_cropped, "squeezed into half the sheet"),
    (_place_under_overlay, "painted over"),
    (_place_under_haze, "washed out"),
])
def test_a_pdf_page_that_is_not_what_the_reader_sees_is_caught(finished,
                                                               tmp_path,
                                                               place, why):
    """Every one of these holds the correct image, with the correct bytes, and
    hashes correctly. A reader sees something else. The old check compared the
    embedded XObject and asked only that it cover half the sheet."""
    pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    export.export_document(finished, out)
    _forge(finished, out, place)

    report = qa.check_package(out, finished)

    assert not report["ok"], f"a page {why} passed: {report['findings']}"


def test_the_plainly_placed_page_still_passes(finished, tmp_path):
    """The control for the four above: rebuilt the ordinary way, it verifies.
    A check that refuses everything it did not write itself is not a check."""
    pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    export.export_document(finished, out)
    _forge(finished, out, _place_plain)

    report = qa.check_package(out, finished)

    assert report["ok"], report["findings"]


def test_even_a_small_added_mark_changes_the_delivered_page(finished,
                                                                    tmp_path):
    """Added visible ink is a change even when its whole-page average is tiny."""
    pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    export.export_document(finished, out)

    def marked(sheet, rect, payload):
        sheet.insert_image(rect, stream=payload)
        sheet.insert_text((2, 6), "x", fontsize=3)

    _forge(finished, out, marked)

    report = qa.check_package(out, finished)

    assert not report["ok"], report["findings"]


def test_a_sheet_with_no_appearance_reference_is_unverified_not_approved(
        finished, tmp_path):
    """Reporting an unknown, rather than falling back to the dimensions."""
    pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    export.export_document(finished, out)
    doc = ir.load_doc(finished)
    for edition in doc["stages"]["export"]["editions"].values():
        for row in edition["manifest"]:
            row.pop("appearance", None)
            row.pop("visible", None)
    ir.save_doc(doc, finished)

    def marked(sheet, rect, payload):
        sheet.insert_image(rect, stream=payload)
        sheet.insert_text((2, 6), "x", fontsize=3)

    _forge(finished, out, marked)
    report = qa.check_package(out, finished)

    assert any(item["code"] == "archive-unverified"
               for item in report["findings"]), report["findings"]


# --------------------------------------------------------------------------- #
# A manifest belongs to a destination
# --------------------------------------------------------------------------- #

def test_two_editions_are_each_verified_against_their_own_manifest(finished,
                                                                   tmp_path):
    """There was one manifest, belonging to whichever export ran last. The
    archive was then checked against the PDF's rows: different names, different
    bytes, every page reported wrong."""
    pytest.importorskip("pymupdf")
    archive = tmp_path / "chapter.cbz"
    book = tmp_path / "chapter.pdf"
    export.export_document(finished, archive)
    export.export_document(finished, book)

    assert qa.check_package(book, finished)["ok"]
    assert qa.check_package(archive, finished)["ok"], \
        qa.check_package(archive, finished)["findings"]


def test_a_copy_of_the_one_archive_edition_is_still_checked(finished,
                                                            tmp_path):
    """A package gets copied, renamed and handed to somebody. Refusing to check
    it because it moved would make the gate useless for the thing people
    actually do with a package, so one edition of a format is recognised by
    that format."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    copied = tmp_path / "for-the-proofreader.cbz"
    copied.write_bytes(out.read_bytes())

    assert qa.check_package(copied, finished)["ok"]


def test_a_loose_copy_of_one_of_two_editions_is_undecidable(finished,
                                                            tmp_path):
    """Two archive editions and a copy at neither destination: which manifest
    it should match is a guess, and guessing is how the wrong one gets used."""
    export.export_document(finished, tmp_path / "first.cbz")
    second = tmp_path / "second.cbz"
    export.export_document(finished, second)
    loose = tmp_path / "somebody-elses.cbz"
    loose.write_bytes(second.read_bytes())

    report = qa.check_package(loose, finished)

    assert any(item["code"] == "archive-unverified"
               for item in report["findings"]), report["findings"]


def test_an_archive_checked_against_a_chapter_with_only_a_pdf_edition_is_unverified(
        finished, tmp_path):
    """The defect this section exists for, in its plainest form: the archive
    used to be checked against the PDF's rows."""
    pytest.importorskip("pymupdf")
    archive = tmp_path / "chapter.cbz"
    export.export_document(finished, archive)
    doc = ir.load_doc(finished)
    doc["stages"]["export"]["editions"] = {
        str((tmp_path / "chapter.pdf").resolve()): {"format": "pdf",
                                                    "manifest": []}}
    ir.save_doc(doc, finished)

    report = qa.check_package(archive, finished)

    assert any(item["code"] == "archive-unverified"
               for item in report["findings"]), report["findings"]


def test_a_package_written_to_an_unusual_suffix_is_still_read(finished,
                                                              tmp_path):
    """`--format cbz --out chapter.xyz` writes an archive, and dispatching the
    check on the suffix refused to look inside it."""
    out = tmp_path / "chapter.xyz"
    export.export_document(finished, out, fmt="cbz")

    report = qa.check_package(out, finished)

    assert report["ok"], report["findings"]
    assert report["pages_found"] == report["pages_expected"]


# --------------------------------------------------------------------------- #
# What the checker will read at all
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("limit,value", [
    ("MAX_MEMBERS", 1),
    ("MAX_MEMBER_BYTES", 64),
    ("MAX_TOTAL_BYTES", 64),
    ("MAX_COMPRESSION_RATIO", 1),
])
def test_an_archive_over_a_limit_is_refused_before_it_is_read(finished,
                                                              tmp_path,
                                                              monkeypatch,
                                                              limit, value):
    """Small injected thresholds, because proving a limit works must not mean
    building the thing it protects against."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    monkeypatch.setattr(package_check, limit, value)

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("Nothing was read" in item["detail"]
               for item in report["findings"]), report["findings"]


@pytest.mark.parametrize("limit,value", [
    ("MAX_MEMBERS", 1),
    ("MAX_MEMBER_BYTES", 64),
])
def test_a_folder_over_a_limit_is_refused_before_it_is_read(finished, tmp_path,
                                                            monkeypatch,
                                                            limit, value):
    out = tmp_path / "edition"
    export.export_document(finished, out)
    monkeypatch.setattr(package_check, limit, value)

    report = qa.check_package(out, finished)

    assert not report["ok"]
    assert any("Nothing was read" in item["detail"]
               for item in report["findings"]), report["findings"]


def test_two_members_under_one_name_are_refused(finished, tmp_path):
    """A ZIP may hold the same name twice and every tool picks a different one
    — including the reader, which will not pick the one that was checked."""
    out = tmp_path / "chapter.cbz"
    export.export_document(finished, out)
    doubled = tmp_path / "doubled.cbz"
    with zipfile.ZipFile(out) as source, \
            zipfile.ZipFile(doubled, "w") as target:
        first = None
        for name in source.namelist():
            payload = source.read(name)
            target.writestr(name, payload)
            if first is None and name.lower().endswith(".png"):
                first = name
        # Writing the same name twice is the defect being built, so
        # zipfile's own warning about it is the expected outcome here.
        with pytest.warns(UserWarning, match="Duplicate name"):
            target.writestr(first, _same_shape_image(*_page_shape(finished)))

    report = package_check.check_package(doubled, finished)

    assert not report["ok"]
    assert any("more than one member" in item["detail"]
               for item in report["findings"]), report["findings"]


def test_the_appearance_tolerance_has_room_on_both_sides(finished, tmp_path):
    """The tolerance is a measurement, not a guess.

    Below it: the same page, exported and then rendered back out of the PDF
    that carries it — two different resampling paths over identical content.
    Above it: a sheet showing nothing at all. Manga pages are mostly white, so
    the gap is narrower than it would be for photographs, and this is what
    keeps the number honest as the fixtures change.
    """
    import pdfpage

    pymupdf = pytest.importorskip("pymupdf")
    out = tmp_path / "book.pdf"
    export.export_document(finished, out)
    rows = ir.load_doc(finished)["stages"]["export"]["manifest"]

    with pymupdf.open(str(out)) as document:
        same = max(pdfpage.difference(pdfpage.rasterized(sheet),
                                      rows[index]["appearance"])
                   for index, sheet in enumerate(document))

    blank = pymupdf.open()
    for page in ir.load_doc(finished)["pages"]:
        blank.new_page(width=page["width"], height=page["height"])
    empty = max(pdfpage.difference(pdfpage.rasterized(sheet),
                                   rows[index]["appearance"])
                for index, sheet in enumerate(blank))
    blank.close()

    assert same < pdfpage.APPEARANCE_TOLERANCE < empty, (same, empty)
