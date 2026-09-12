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


def test_a_member_is_streamed_onto_disk_not_read_whole(tmp_path, monkeypatch):
    """A page is capped at 512 MB, so reading a member whole was bounded — at
    half a gigabyte of resident memory for one page of one comic.

    `ZipFile.read` is made to fail, so the only way the import can succeed is
    through `open()` and the stdlib copy. Without the change every page here
    would go through `read` and this test would fail on the first one.
    """
    original = zipfile.ZipFile.read

    def _refuse(self, *args, **kwargs):
        raise AssertionError("the whole member was read into memory")

    monkeypatch.setattr(zipfile.ZipFile, "read", _refuse)

    archive = write_cbz(tmp_path / "chapter.cbz", pages=2)
    report = readers.import_source(archive, tmp_path / "work")
    assert report["pages"] == 2

    # And the bytes are the bytes: streaming is only worth anything if the page
    # that lands is the page that was in the archive.
    monkeypatch.setattr(zipfile.ZipFile, "read", original)
    with zipfile.ZipFile(archive) as zf:
        expected = zf.read("page1.png")
    landed = (ir.doc_dir(Path(report["document"])) / "pages" / "p0001.png")
    assert landed.read_bytes() == expected


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

    work = tmp_path / "work"
    with pytest.raises(ValueError, match="pages"):
        readers.import_source(source, work)
    # Rendering even the first page would have left a file behind. Asserted
    # against the whole work folder rather than `work/pages`, because import is
    # transactional now and a refused source never gets a pages folder at all —
    # a stronger outcome than an empty one, and the point stands either way.
    written = [child for child in work.rglob("*") if child.is_file()]
    assert not written, f"a refused PDF still wrote {written}"


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


def test_a_pdf_that_writes_more_than_the_ceiling_stops(tmp_path, monkeypatch):
    """A PDF has no member table to check up front, so its total is counted as
    it is written. The page cap and the per-page pixel cap both pass here and
    neither one bounds the total: 2000 legitimate pages of large scans is a
    terabyte that nothing else refuses."""
    pymupdf = pytest.importorskip("pymupdf")

    source = tmp_path / "big.pdf"
    document = pymupdf.open()
    for _ in range(4):
        document.new_page(width=600, height=900)
    document.save(str(source))
    document.close()

    # Small enough that four ordinary rendered pages cross it.
    monkeypatch.setattr(readers, "MAX_TOTAL_BYTES", 2_000)
    with pytest.raises(ValueError, match="expands to more than"):
        readers.import_source(source, tmp_path / "work")


def test_a_gigapixel_embedded_image_is_rendered_instead_of_extracted():
    """`extract_image` decompresses before anything can measure the result, and
    `get_images(full=True)` is the only place the declared size is visible
    first. Over the cap the page renders instead \u2014 bounded by the page
    rectangle, and the huge image is downsampled to the page it was drawn on,
    which is how it looked anyway."""
    class _Page:
        rect = type("R", (), {"width": 600.0, "height": 900.0})()

        def get_images(self, full=True):
            #  (xref, smask, width, height, ...) \u2014 60000 x 60000
            return [(7, 0, 60_000, 60_000, 8, "DeviceRGB", "", "Im0", "Flate")]

        def get_image_rects(self, xref):  # pragma: no cover - never reached
            raise AssertionError("the declared size should have stopped this")

    assert readers._single_embedded_image(object(), _Page()) is None



# --- R01: import is transactional, and paths may not overlap ------------------

def test_a_failed_import_leaves_the_previous_chapter_intact(tmp_path):
    """THE ONE THAT MATTERS HERE. `import` used to delete `work/pages` before it
    had even looked at the new source, so pointing it at a corrupt archive threw
    away a chapter that was already on disk — possibly hours of translated work
    whose only surviving copy was those page files."""
    work = tmp_path / "work"
    good = tmp_path / "good"
    good.mkdir()
    write_pages(good, 2)
    readers.import_source(good, work, source_language="ja", direction="rtl")

    before = sorted(p.name for p in (work / "pages").iterdir())
    digests = {p.name: ir.sha256_file(p) for p in (work / "pages").iterdir()}
    assert len(before) == 2

    broken = tmp_path / "broken.cbz"
    broken.write_bytes(b"not a zip file")
    with pytest.raises(Exception):
        readers.import_source(broken, work, source_language="ja", direction="rtl")

    assert (work / "pages").exists(), "the pages folder itself was destroyed"
    after = sorted(p.name for p in (work / "pages").iterdir())
    assert after == before, f"the failed import took the old chapter: {after}"
    assert {p.name: ir.sha256_file(p) for p in (work / "pages").iterdir()} == digests
    assert (work / "comic.json").exists(), "the old document went too"


def test_a_successful_import_still_replaces_the_old_pages(tmp_path):
    """The other half of the same guarantee: staging must not leave the previous
    chapter's pages mixed into the new one."""
    work = tmp_path / "work"
    first = tmp_path / "first"
    first.mkdir()
    write_pages(first, 3)
    readers.import_source(first, work, source_language="ja", direction="rtl")

    second = tmp_path / "second"
    second.mkdir()
    write_pages(second, 1)
    readers.import_source(second, work, source_language="ja", direction="rtl")

    assert sorted(p.name for p in (work / "pages").iterdir()) == ["p0001.png"]
    assert len(ir.load_doc(work / "comic.json")["pages"]) == 1
    leftovers = [p.name for p in work.iterdir() if p.name.startswith("pages.")]
    assert not leftovers, f"staging residue survived the import: {leftovers}"


def test_a_source_inside_the_work_folder_is_refused(tmp_path):
    """Importing `work/pages/chapter` deleted the source before reading it: the
    chapter was gone and there was nothing to import it from. The paths have to
    be checked before anything is removed."""
    work = tmp_path / "work"
    inside = work / "pages" / "chapter"
    inside.mkdir(parents=True)
    write_pages(inside, 2)

    with pytest.raises(ValueError, match="inside"):
        readers.import_source(inside, work, source_language="ja", direction="rtl")
    assert inside.exists(), "the source folder was destroyed"
    assert len(list(inside.iterdir())) == 2


def test_the_work_folder_inside_the_source_is_refused(tmp_path):
    """The same collision the other way up: `--out` under the folder being read."""
    source = tmp_path / "chapter"
    source.mkdir()
    write_pages(source, 2)

    with pytest.raises(ValueError, match="inside"):
        readers.import_source(source, source / "work",
                              source_language="ja", direction="rtl")
    assert len(list(source.glob("*.png"))) == 2


# --- R02: an import may not silently drop what the page shows ----------------

def _page_image(work):
    from PIL import Image
    return Image.open(sorted((work / "pages").iterdir())[0]).convert("RGB")


def test_a_pdf_page_with_text_over_the_art_is_rendered_whole(tmp_path):
    """The single-image shortcut asks `get_images()`, which counts images and
    knows nothing about text. A page that is one scan plus a line of typeset
    dialogue passed the check and imported as the scan alone — the dialogue
    simply was not in the file any more, and nothing said so."""
    pymupdf = pytest.importorskip("pymupdf")

    source = tmp_path / "overlay.pdf"
    document = pymupdf.open()
    page = document.new_page(width=500, height=700)
    page.insert_image(pymupdf.Rect(0, 0, 500, 700),
                      stream=page_bytes(manga_page(500, 700)))
    page.insert_text((60, 360), "SPOILER TEXT", fontsize=44, color=(1, 0, 0))
    document.save(str(source))
    document.close()

    work = tmp_path / "work"
    readers.import_source(source, work, dpi=72)
    pixels = _page_image(work).load()
    width, height = _page_image(work).size
    red = sum(1 for y in range(height) for x in range(width)
              if pixels[x, y][0] - pixels[x, y][2] > 80)
    assert red > 200, "the red overlay text is not in the imported page"


def test_a_pdf_page_with_a_drawing_over_the_art_is_rendered_whole(tmp_path):
    """Same hole, vector side: a redaction bar or a speech tail drawn as a path
    is not an image either."""
    pymupdf = pytest.importorskip("pymupdf")

    source = tmp_path / "drawn.pdf"
    document = pymupdf.open()
    page = document.new_page(width=500, height=700)
    page.insert_image(pymupdf.Rect(0, 0, 500, 700),
                      stream=page_bytes(manga_page(500, 700)))
    page.draw_rect(pymupdf.Rect(80, 300, 420, 400), color=(1, 0, 0),
                   fill=(1, 0, 0))
    document.save(str(source))
    document.close()

    work = tmp_path / "work"
    readers.import_source(source, work, dpi=72)
    image = _page_image(work)
    pixels = image.load()
    red = sum(1 for y in range(image.size[1]) for x in range(image.size[0])
              if pixels[x, y][0] - pixels[x, y][2] > 80)
    assert red > 2000, "the drawn rectangle is not in the imported page"


def test_a_rotated_pdf_page_is_imported_the_way_it_is_displayed(tmp_path):
    """`/Rotate 90` is part of how the page looks. Taking the embedded bytes
    ignores it, so a landscape spread imported as a portrait page and every
    balloon box computed afterwards was against the wrong axis."""
    pymupdf = pytest.importorskip("pymupdf")

    source = tmp_path / "rotated.pdf"
    document = pymupdf.open()
    page = document.new_page(width=500, height=700)
    page.insert_image(pymupdf.Rect(0, 0, 500, 700),
                      stream=page_bytes(manga_page(500, 700)))
    page.set_rotation(90)
    document.save(str(source))
    document.close()

    with pymupdf.open(str(source)) as opened:
        shown = opened[0].rect
    assert shown.width > shown.height, "the fixture is not landscape"

    work = tmp_path / "work"
    readers.import_source(source, work, dpi=72)
    width, height = _page_image(work).size
    assert width > height, f"imported {width}x{height} for a landscape page"


def test_a_plain_scan_page_still_keeps_its_original_bytes(tmp_path):
    """The other half: the shortcut has to survive. A page that really is one
    scan and nothing else must not start being re-rendered, because that
    resamples artwork that was already at its native resolution."""
    pymupdf = pytest.importorskip("pymupdf")

    art = page_bytes(manga_page(500, 700))
    source = tmp_path / "plain.pdf"
    document = pymupdf.open()
    page = document.new_page(width=500, height=700)
    page.insert_image(pymupdf.Rect(0, 0, 500, 700), stream=art)
    document.save(str(source))
    document.close()

    with pymupdf.open(str(source)) as opened:
        taken = readers._single_embedded_image(opened, opened[0])
    assert taken is not None, "the shortcut stopped working on a plain scan"

    work = tmp_path / "work"
    readers.import_source(source, work, dpi=72)
    assert sorted((work / "pages").iterdir())[0].read_bytes() == taken


def test_two_archive_members_with_one_name_are_refused(tmp_path):
    """A ZIP may hold two different members under the same name, and reading by
    name gives whichever came last — so one page was replaced by a copy of
    another and the count still looked right. There is no way to know which
    order was meant, so say so rather than pick."""
    import io
    import zipfile

    first = page_bytes(manga_page(400, 600))
    second = page_bytes(manga_page(400, 600, dark_balloon=True))
    assert first != second

    archive_path = tmp_path / "dupes.cbz"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("page.png", first)
        archive.writestr("page.png", second)
    archive_path.write_bytes(buffer.getvalue())

    with pytest.raises(ValueError, match="twice|duplicate"):
        readers.import_source(archive_path, tmp_path / "work")
