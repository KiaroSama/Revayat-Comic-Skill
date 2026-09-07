"""Input normalisation: order, hashing, and the formats people actually have."""

from __future__ import annotations

import struct
import zipfile
import zlib
from pathlib import Path

import pytest

import pageir as ir
import readers
from tests_support import manga_page, page_bytes, write_cbz, write_pages


def test_natural_sort_puts_page_2_before_page_10():
    names = ["page10.png", "page2.png", "page1.png"]
    assert sorted(names, key=readers.natural_key) == [
        "page1.png", "page2.png", "page10.png"
    ]
    # And byte-wise sorting does not, which is the reason this exists.
    assert sorted(names) != ["page1.png", "page2.png", "page10.png"]


def test_import_renames_pages_into_reading_order(imported):
    doc = ir.load_doc(imported)
    assert [page["id"] for page in doc["pages"]] == ["p0001", "p0002", "p0003"]
    assert [page["index"] for page in doc["pages"]] == [0, 1, 2]


def test_every_page_is_hashed_and_the_hash_matches(imported):
    doc = ir.load_doc(imported)
    root = ir.doc_dir(imported)
    for page in doc["pages"]:
        assert len(page["sha256"]) == 64
        assert ir.sha256_file(root / page["image"]) == page["sha256"]


def test_page_size_is_recorded(imported):
    doc = ir.load_doc(imported)
    assert all(page["width"] == 1000 and page["height"] == 1500
               for page in doc["pages"])


def test_macos_metadata_entries_are_not_pages(tmp_path):
    archive = tmp_path / "junk.cbz"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("__MACOSX/._page1.png", b"junk")
        zf.writestr(".DS_Store", b"junk")
        zf.writestr("page1.png", page_bytes(manga_page()))
    report = readers.import_source(archive, tmp_path / "work")
    assert report["pages"] == 1


def test_an_archive_with_no_images_says_so(tmp_path):
    archive = tmp_path / "empty.cbz"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", b"nothing here")
    with pytest.raises(ValueError, match="no images"):
        readers.import_source(archive, tmp_path / "work")


def test_a_folder_of_images_imports(tmp_path):
    folder = write_pages(tmp_path / "pages", pages=2)
    report = readers.import_source(folder, tmp_path / "work")
    assert report["kind"] == "directory" and report["pages"] == 2


def test_a_single_image_imports(sample_page, tmp_path):
    report = readers.import_source(sample_page, tmp_path / "work")
    assert report["pages"] == 1


def test_a_cbz_with_the_wrong_extension_is_still_recognised(tmp_path):
    archive = tmp_path / "chapter.bin"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("001.png", page_bytes(manga_page()))
    assert readers.detect_kind(archive) == "cbz"


def test_an_unknown_file_type_explains_what_is_supported(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="CBZ"):
        readers.detect_kind(path)


def test_a_missing_source_is_reported_as_such(tmp_path):
    with pytest.raises(FileNotFoundError):
        readers.import_source(tmp_path / "nope.cbz", tmp_path / "work")


def test_a_tall_strip_is_flagged_as_a_webtoon(tmp_path):
    from PIL import Image

    folder = tmp_path / "strip"
    folder.mkdir()
    (folder / "001.png").write_bytes(page_bytes(Image.new("RGB", (800, 6000), "white")))
    report = readers.import_source(folder, tmp_path / "work")
    assert report["webtoon_strips"] == ["p0001"]
    assert "webtoon" in report["warning"]


def test_pdf_import_keeps_the_original_page_bytes(tmp_path):
    """A comic PDF is one scan per page; re-rendering it would resample artwork
    that was already at its native resolution."""
    pymupdf = pytest.importorskip("pymupdf")

    source = tmp_path / "chapter.pdf"
    payload = page_bytes(manga_page())
    document = pymupdf.open()
    for _ in range(2):
        page = document.new_page(width=1000, height=1500)
        page.insert_image(pymupdf.Rect(0, 0, 1000, 1500), stream=payload)
    document.save(str(source))
    document.close()

    report = readers.import_source(source, tmp_path / "work")
    assert report["kind"] == "pdf" and report["pages"] == 2
    doc = ir.load_doc(Path(report["document"]))
    assert doc["pages"][0]["width"] == 1000


# --- CBR ---------------------------------------------------------------------
# There is no free RAR *writer* — RAR compression is proprietary and libarchive
# is read-only for it — so no test can build one at run time. A genuine archive
# therefore travels as base64 text in `data/real-rar.b64` and is decoded below,
# which gives a real round-trip on every runner that has a RAR *reader*. The
# routing and failure paths come first because they hold on every machine.

def test_a_cbr_extension_routes_to_the_rar_reader(tmp_path):
    path = tmp_path / "chapter.cbr"
    path.write_bytes(b"not really a rar")
    assert readers.detect_kind(path) == "cbr"


def test_a_cbr_that_is_not_a_rar_explains_itself(tmp_path):
    """Found by CI: `rarfile.NotRarFile` escaped as a bare traceback from inside
    a dependency. The dispatcher only translates FileNotFoundError and
    ValueError, so anything else reaches the user as a stack."""
    pytest.importorskip("rarfile")
    path = tmp_path / "chapter.cbr"
    path.write_bytes(b"PK\x03\x04 this is a zip wearing a cbr extension")
    with pytest.raises(ValueError, match="not a readable RAR archive"):
        readers.import_source(path, tmp_path / "work")


def test_a_missing_rarfile_names_the_package(tmp_path, monkeypatch):
    import pageir

    def refuse(module, package, why):
        if module == "rarfile":
            raise pageir.MissingDependency(f"{why} needs the {package} package.")
        return __import__(module)

    monkeypatch.setattr(readers.ir, "require", refuse)
    path = tmp_path / "chapter.cbr"
    path.write_bytes(b"x")
    with pytest.raises(pageir.MissingDependency, match="rarfile"):
        readers.import_source(path, tmp_path / "work")


#: A real RAR, carried as base64 text. See the file's own header for why.
REAL_RAR = Path(__file__).with_name("data") / "real-rar.b64"


def _real_rar_bytes() -> bytes:
    import base64

    body = "".join(line.strip() for line in REAL_RAR.read_text("utf-8").splitlines()
                   if line.strip() and not line.startswith("#"))
    return base64.b64decode(body)


def test_a_real_rar_round_trips(tmp_path):
    """The one this project could not run for its first three weeks.

    RAR compression is proprietary and there is no free writer, so no CI runner
    can build an archive and a fabricated one would test the fabrication. The
    fixture is therefore a **genuine** RAR — written once by `Rar.exe`, stored as
    base64 text so nothing binary is committed — and this only needs a *reader*,
    which CI installs.

    Reading a real one immediately found a defect that three weeks of routing
    tests had not: a RAR5 archive **opens** without an unrar backend and only
    fails when a member is read, so guarding the constructor alone let the
    failure out as a raw traceback from inside rarfile.
    """
    rarfile = pytest.importorskip("rarfile")
    try:
        rarfile.tool_setup()
    except rarfile.RarCannotExec:
        pytest.skip("no unrar/unar/bsdtar backend on this machine")

    archive = tmp_path / "chapter.cbr"
    archive.write_bytes(_real_rar_bytes())
    assert archive.read_bytes()[:4] == b"Rar!", "the fixture is not a RAR"

    doc = readers.import_source(archive, tmp_path / "work")
    assert doc["kind"] == "cbr"
    assert doc["pages"] == 2

    pages = sorted((tmp_path / "work" / "pages").iterdir())
    assert [p.name for p in pages] == ["p0001.png", "p0002.png"]
    assert all(p.stat().st_size > 0 for p in pages)


def test_the_real_rar_fixture_is_text_and_decodes(tmp_path):
    """It is committed as text on purpose; a binary would fail the repository's
    own artwork and UTF-8 gates. If it ever stops decoding, the file was edited
    by something that reflowed it."""
    REAL_RAR.read_text("utf-8")            # must be valid UTF-8
    signature = _real_rar_bytes()[:8]
    assert signature.startswith(b"Rar!")
    assert signature[4] == 0x1A and signature[5] == 0x07   # RAR5 marker


# --- Untrusted archives -----------------------------------------------------

def test_a_zip_bomb_is_refused_before_anything_is_written(tmp_path):
    """A CBZ is a file someone downloaded. A few kilobytes of zeros expand to
    gigabytes, and nothing bounded that: the reader never extracts an
    attacker-controlled *path*, but it would happily write the payload."""
    path = tmp_path / "chapter.cbz"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("001.png", b"\0" * (64 * 1024 * 1024))

    with pytest.raises(ValueError, match="expands"):
        readers.import_source(path, tmp_path / "work")
    # The working folder gets created before the reader runs; what must not
    # happen is 64 MB of it landing on disk.
    pages = tmp_path / "work" / "pages"
    assert not pages.exists() or not any(pages.iterdir())


def test_an_archive_with_absurdly_many_entries_is_refused(tmp_path):
    counted = ((f"{i}.png", 10, 10) for i in range(readers.MAX_MEMBERS + 5))
    with pytest.raises(ValueError, match="entries"):
        readers.check_archive_limits("chapter.cbz", counted)


def test_an_archive_that_expands_past_the_ceiling_is_refused():
    huge = (("p.png", readers.MAX_TOTAL_BYTES // 4, readers.MAX_TOTAL_BYTES // 4)
            for _ in range(5))
    with pytest.raises(ValueError, match="GB"):
        readers.check_archive_limits("chapter.cbz", huge)


def test_a_real_chapter_passes_the_limits(tmp_path):
    """The guard must not fire on anything real. Page images are already
    compressed, so their ratio is near 1."""
    write_cbz = pytest.importorskip("tests_support").write_cbz
    path = write_cbz(tmp_path / "chapter.cbz", pages=3)
    doc = readers.import_source(path, tmp_path / "work")
    assert doc["pages"] == 3


def test_a_tiny_member_is_not_judged_by_ratio():
    """A 40-byte entry expanding to 4 KB is a header, not an attack."""
    readers.check_archive_limits("chapter.cbz", [("meta.png", 4096, 40)])


def test_a_single_huge_member_is_refused_on_its_own():
    """The 6 GB member an audit found sitting inside the old limits: the running
    total only fails once it crosses the ceiling, and the first entry never
    does. This one is deliberately under the total, so nothing except the
    per-member cap can be what refuses it."""
    size = readers.MAX_MEMBER_BYTES + 1
    assert size < readers.MAX_TOTAL_BYTES, "the total ceiling would mask this"
    # Stored size equals uncompressed, so the ratio guard cannot fire either.
    with pytest.raises(ValueError, match="MB entry"):
        readers.check_archive_limits("chapter.cbz", [("p.png", size, size)])


def _png_declaring(width: int, height: int) -> bytes:
    """A valid PNG header claiming `width` x `height`, with nothing behind it.

    Sixty-six bytes. Pillow reads the size out of IHDR before it decodes a
    single pixel, which is both the whole of the attack and the whole of the
    defence.
    """
    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body)))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\0")) + chunk(b"IEND", b""))


def test_a_decompression_bomb_is_refused_and_the_message_names_the_file(tmp_path):
    """No archive limit can see this one: the member is 66 bytes and expands to
    66 bytes. It is the *decoded* size that is 3.6 gigapixels, and Pillow only
    raises past twice its own ceiling — under that it warns, which reaches the
    user as a stray line on stderr and a page that quietly costs 10 GB."""
    path = tmp_path / "chapter.cbz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.png", _png_declaring(60_000, 60_000))

    with pytest.raises(ValueError, match=r"p0001\.png") as refused:
        readers.import_source(path, tmp_path / "work")
    assert "megapixels" in str(refused.value)


def test_a_pdf_with_too_many_pages_is_refused_before_rendering(tmp_path):
    """Page count is known from the document; rendering to find out costs a
    pixmap per page."""
    pymupdf = pytest.importorskip("pymupdf")

    source = tmp_path / "everything.pdf"
    document = pymupdf.open()
    for _ in range(readers.MAX_PAGES + 1):
        document.new_page(width=200, height=300)
    document.save(str(source))
    document.close()

    with pytest.raises(ValueError, match="pages"):
        readers.import_source(source, tmp_path / "work")
    # Rendering even the first page would have left a file behind.
    assert not any((tmp_path / "work" / "pages").iterdir())


def test_a_real_chapter_clears_every_new_limit_with_room(tmp_path):
    """A guard that fires on a genuine page is worse than no guard at all. A
    drawn 1000x1500 page is 1.5 of the 80 megapixels allowed and kilobytes of
    the half gigabyte, and the chapter is 3 pages of 2000."""
    path = write_cbz(tmp_path / "chapter.cbz", pages=3)
    report = readers.import_source(path, tmp_path / "work")
    assert report["pages"] == 3

    biggest = max(page.stat().st_size
                  for page in (tmp_path / "work" / "pages").iterdir())
    assert biggest * 100 < readers.MAX_MEMBER_BYTES
    assert 1000 * 1500 * 10 < readers.MAX_PAGE_PIXELS
