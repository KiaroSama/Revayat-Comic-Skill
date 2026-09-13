"""Turn whatever the user has into an ordered set of immutable page images.

CBZ, CBR, a folder of scans, a PDF and a single image all arrive here and leave
as the same thing: ``$WORK/pages/pNNNN.png`` plus a hash per page. Everything
downstream reads those files and never the original container, so a stage
cannot accidentally depend on a format detail.

Page order is the one thing a comic cannot get wrong, and archive order is not
it — ``page10.jpg`` sorts before ``page9.jpg`` in every byte-wise listing there
is. :func:`natural_key` is what fixes that, and it is used for every container.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import warnings
import zipfile
from pathlib import Path
from typing import Any, Iterable

import pageir as ir

#: The canonical list lives in `pageir`, so the importer, the cleaner, the
#: exporter and the gate cannot drift apart about what a page is.
IMAGE_SUFFIXES = ir.IMAGE_SUFFIXES
ARCHIVE_SUFFIXES = {".cbz", ".zip"}
RAR_SUFFIXES = {".cbr", ".rar"}

#: Rendering resolution for a PDF page that is not simply one embedded image.
#: 300 DPI is the floor at which small furigana survives; below it the crop
#: handed to a reader is a smear.
PDF_DPI = 300

_NUMBER = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple[Any, ...]:
    """Sort ``page2`` before ``page10`` — the order a human numbered them in."""
    parts = _NUMBER.split(name.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _is_junk(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith("__macosx/")
        or "/." in lowered
        or lowered.startswith(".")
        or lowered.endswith("/")
        or Path(lowered).name.startswith("._")
    )


def _image_members(names: Iterable[str]) -> list[str]:
    keep = [
        name for name in names
        if not _is_junk(name) and Path(name).suffix.lower() in IMAGE_SUFFIXES
    ]
    return sorted(keep, key=natural_key)


# --------------------------------------------------------------------------- #
# Limits on an untrusted archive
# --------------------------------------------------------------------------- #
#
# A CBZ or CBR is a file someone downloaded, and both formats can be made
# hostile without being malformed: a few kilobytes of zeros expand to gigabytes,
# and a member count in the millions costs memory before a single byte is read.
# The reader never extracts an attacker-controlled *path* — members are copied
# into generated `pNNNN` names — but nothing bounded what they cost.
#
# These are far above any real comic. A 400-page volume at 4 MB a page is 1.6 GB
# and 400 members; a page that decompresses 200x is not a scan.

#: Most members an archive may declare.
MAX_MEMBERS = 20_000

#: Most pages one run may import, whatever the container. A chapter is tens of
#: pages and a fat volume a few hundred; 2000 is a whole series in one file, and
#: every page past this one costs a model call in a later stage.
MAX_PAGES = 2_000

#: Most bytes an archive may expand to in total. A 400-page volume at 4 MB a
#: page is 1.6 GB, which is the largest genuine import there is; 2 GB clears it
#: and is still inside what a desktop process should ever be asked to write.
MAX_TOTAL_BYTES = 2 * 1024 ** 3

#: Most bytes a single member may expand to. A 300-DPI page scan is single-digit
#: megabytes, and even an uncompressed 600-DPI double spread is about 200 MB, so
#: half a gigabyte is already a hundred pages in one entry. Without this a 6 GB
#: member passed: the running total only fails once it crosses the ceiling, and
#: the first entry never does.
MAX_MEMBER_BYTES = 512 * 1024 ** 2

#: Most pixels one page may decode or render to. A 600-DPI A4 double-page spread
#: is 9920 x 7016 — about 70 megapixels, and the largest scan anyone has. At 80
#: the guard clears that and still refuses the 66-byte PNG whose header declares
#: 60000 x 60000 and costs 10 GB to decode.
MAX_PAGE_PIXELS = 80_000_000

#: How far one member may expand relative to its stored size. Real image formats
#: are already compressed, so a large ratio means the payload is not a page.
MAX_RATIO = 250

#: Smallest stored size worth applying the ratio to. A 40-byte member expanding
#: to 4 KB is not an attack, it is a header.
RATIO_FLOOR = 4096


def check_archive_limits(name: str, members) -> None:
    """Refuse an archive that would cost more than any real comic.

    `members` is an iterable of `(member name, uncompressed, compressed)`.
    Raises ``ValueError``, which the dispatcher turns into a message rather than
    a traceback.
    """
    total = 0
    count = 0
    for member, uncompressed, compressed in members:
        count += 1
        if count > MAX_MEMBERS:
            raise ValueError(
                f"{name} declares more than {MAX_MEMBERS} entries. A comic "
                "chapter has hundreds; this is not one."
            )
        size = max(0, int(uncompressed or 0))
        if size > MAX_MEMBER_BYTES:
            raise ValueError(
                f"{name} holds a {size // 1024 ** 2} MB entry ({member}). A page "
                "scan is single-digit megabytes; nothing in a comic is that big."
            )
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError(
                f"{name} expands to more than {MAX_TOTAL_BYTES // 1024 ** 3} GB. "
                "Extract it yourself and import the folder if it is genuine."
            )
        stored = int(compressed or 0)
        if stored >= RATIO_FLOOR and size > stored * MAX_RATIO:
            raise ValueError(
                f"{name} contains an entry that expands {size // max(1, stored)}x "
                f"({member}). Page images are already compressed; this is not one."
            )


def _check_page_count(name: str, pages: int) -> None:
    """Refuse an import longer than a volume, whatever container it came in.

    The archive limits bound what a *download* costs; this bounds what the rest
    of the pipeline is handed, and it is the only one of them a folder of loose
    scans or a PDF passes through at all.
    """
    if pages > MAX_PAGES:
        raise ValueError(
            f"{name} holds {pages} pages. A chapter is tens of pages and a "
            f"volume a few hundred; split it and import one at a time."
        )


def _load_page(path: Path):
    """Open a page image, refusing one that decodes to an absurd bitmap.

    Sixty-six bytes of PNG header can declare 60000 x 60000 pixels, and Pillow
    will allocate ten gigabytes trying to decode it — nothing upstream can see
    that coming, because the *file* is tiny. Pillow's own guard raises above
    twice ``MAX_IMAGE_PIXELS`` and only warns between the two, and neither
    reaches the user as anything but a traceback or a stray line on stderr, so
    both become one ValueError that names the file.
    """
    ir.require("PIL", "pillow", "reading comic pages")
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            return ir.load_image(path)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError(
            f"{path.name} decodes to more than {MAX_PAGE_PIXELS // 1_000_000} "
            f"megapixels ({error}). A comic page is a scan, not a bitmap that "
            f"size."
        ) from error


def _copy_member(archive, member: str, target: Path) -> None:
    """One archive member onto disk without holding it in memory.

    `archive.read(member)` returns the whole member as one `bytes`, so a legal
    600-DPI double spread cost its full size in RAM before a byte reached the
    page directory. Both `zipfile` and `rarfile` expose the same `open()`, so
    the fix is the stdlib copy and nothing else changes: the destination name
    is still generated (`pNNNN`), so a hostile member name still cannot escape
    the pages directory, and the write is still atomic.
    """
    with archive.open(member) as source:
        ir.write_stream(target, source)


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #

def _from_zip(path: Path, pages_dir: Path) -> list[Path]:
    written: list[Path] = []
    with zipfile.ZipFile(path) as archive:
        check_archive_limits(path.name, (
            (info.filename, info.file_size, info.compress_size)
            for info in archive.infolist()
        ))
        members = _image_members(archive.namelist())
        # A ZIP may legally hold two different members under one name, and
        # `archive.open(name)` gives whichever was written last. The page count
        # still looked right while one page had been replaced by a copy of
        # another. Nothing in the archive says which order was meant, so this
        # refuses instead of choosing.
        repeated = sorted({name for name in members
                           if members.count(name) > 1})
        if repeated:
            raise ValueError(
                f"{path.name} stores {len(repeated)} page name(s) twice "
                f"({', '.join(repeated[:4])}). Reading by name would silently "
                "keep one copy of the last and lose the other. Re-save the "
                "archive with unique page names."
            )
        if not members:
            raise ValueError(
                f"{path.name} contains no images. A CBZ is a ZIP of page "
                f"images; this one holds {len(archive.namelist())} other entries."
            )
        _check_page_count(path.name, len(members))
        for index, member in enumerate(members):
            suffix = Path(member).suffix.lower()
            target = pages_dir / f"{ir.page_id_for(index)}{suffix}"
            _copy_member(archive, member, target)
            written.append(target)
    return written


#: Said in two places, because a RAR5 archive opens without a backend and only
#: fails when a member is read.
_NEEDS_UNRAR = (
    "rarfile needs an unrar binary it can run to read a CBR, and there is none "
    "on PATH.\n"
    "    Linux/macOS: install `unrar` or `libarchive-tools`\n"
    "    Windows:     install WinRAR, then add its folder to PATH — the file\n"
    "                 rarfile needs is UnRAR.exe, beside WinRAR.exe\n"
    "    Either way:  re-saving the file as CBZ needs no extra tool at all\n"
    "({error})"
)


def _from_rar(path: Path, pages_dir: Path) -> list[Path]:
    rarfile = ir.require("rarfile", "rarfile", "reading CBR archives")
    try:
        archive = rarfile.RarFile(str(path))
    except rarfile.RarCannotExec as error:  # pragma: no cover - depends on host
        raise ir.MissingDependency(_NEEDS_UNRAR.format(error=error)) from error
    except rarfile.Error as error:
        # A file named .cbr that is not a RAR, or one that is truncated. Without
        # this the user gets a bare `rarfile.NotRarFile` traceback from inside a
        # dependency, which says nothing about which file or what to do — the
        # dispatcher only translates FileNotFoundError and ValueError.
        raise ValueError(
            f"{path.name} is not a readable RAR archive ({error}). "
            "A .cbr is a RAR of page images; if it opens in a comic reader but "
            "not here, re-save it as CBZ, which is a ZIP and needs no extra "
            "tool."
        ) from error

    written: list[Path] = []
    try:
        with archive:
            check_archive_limits(path.name, (
                (info.filename, info.file_size, info.compress_size)
                for info in archive.infolist()
            ))
            members = _image_members(archive.namelist())
            if not members:
                raise ValueError(f"{path.name} contains no images.")
            _check_page_count(path.name, len(members))
            for index, member in enumerate(members):
                suffix = Path(member).suffix.lower()
                target = pages_dir / f"{ir.page_id_for(index)}{suffix}"
                _copy_member(archive, member, target)
                written.append(target)
    except rarfile.RarCannotExec as error:  # pragma: no cover - depends on host
        # **Opening a RAR5 archive succeeds without a backend; reading one does
        # not.** rarfile defers the tool to the first `read`, so guarding only
        # the constructor above let the failure through as a raw traceback out
        # of a dependency. Found by building a real `.cbr` with WinRAR's
        # `Rar.exe` and importing it on a machine where `UnRAR.exe` was not on
        # PATH — the exact situation a Windows user is in.
        raise ir.MissingDependency(_NEEDS_UNRAR.format(error=error)) from error
    return written


def _from_pdf(path: Path, pages_dir: Path, dpi: int) -> list[Path]:
    pymupdf = ir.require("pymupdf", "pymupdf", "reading comic PDFs")
    written: list[Path] = []
    # A PDF has no member table to check up front the way an archive does, so
    # its total is counted as it is written. Without this the page count and the
    # per-page pixel cap still allow 2000 legitimate-looking pages of 400 MB
    # scans, which is a terabyte nothing refuses.
    total = 0
    with pymupdf.open(str(path)) as document:
        _check_page_count(path.name, document.page_count)
        for index, page in enumerate(document):
            target = pages_dir / f"{ir.page_id_for(index)}.png"
            payload = _single_embedded_image(document, page)
            if payload is not None:
                # A comic PDF is usually one scan per page. Taking those bytes
                # keeps the original pixels; re-rendering resamples artwork that
                # was already at its native resolution and softens screentone.
                ir.write_bytes(target, payload)
            else:
                # A page rectangle is declared, not measured: 200 inches square
                # is a legal PDF and renders to 3.6 gigapixels at 300 DPI, an
                # allocation the process does not come back from. Checked here
                # rather than up front because a page that is one embedded scan
                # is never rendered at all.
                area = (page.rect.width * dpi / 72) * (page.rect.height * dpi / 72)
                if area > MAX_PAGE_PIXELS:
                    raise ValueError(
                        f"{path.name} page {index + 1} would render to "
                        f"{int(area) // 1_000_000} megapixels at {dpi} DPI. "
                        f"Re-export it at a real page size, or lower --dpi."
                    )
                pixmap = page.get_pixmap(dpi=dpi)
                payload = pixmap.tobytes("png")
                ir.write_bytes(target, payload)
            total += len(payload)
            if total > MAX_TOTAL_BYTES:
                raise ValueError(
                    f"{path.name} expands to more than "
                    f"{MAX_TOTAL_BYTES // 1024 ** 3} GB by page {index + 1}. "
                    "Split it and import one volume at a time."
                )
            written.append(target)
    return written


#: How far a placement may sit from the page edge and still be "the page".
#: A point, not a percentage: PDF coordinates are in points and rounding is
#: the only difference worth forgiving.
_PLACEMENT_SLACK = 1.0


def _upright(page, xref: int) -> bool:
    """Whether this image is drawn without rotation, reflection or skew.

    The stored bytes are not transformed. A placement matrix that turns the
    image — or mirrors it — makes the page look nothing like them, and the
    extraction shortcut hands back the bytes.
    """
    try:
        # `xrefs=True` asks for the xref of each placement — the keyword is
        # plural, and the singular spelling raises rather than filtering.
        placements = page.get_image_info(xrefs=True)
    except Exception:  # pragma: no cover - older PyMuPDF, or a malformed page
        return False
    mine = [info for info in placements if info.get("xref") == xref]
    if not mine:
        # An older build that does not report xrefs at all. The caller has
        # already established there is exactly one image on this page, so an
        # unambiguous single placement is still this image's.
        mine = placements if len(placements) == 1 else []
    if len(mine) != 1:
        return False
    transform = mine[0].get("transform")
    if not transform or len(transform) < 4:
        return False
    a, b, c, d = (float(value) for value in transform[:4])
    # `(a, b, c, d, e, f)`: an upright placement reports the image's width and
    # height as `a` and `d` with no shear. A 180° turn reports both negative —
    # which is exactly what was handed back unrotated — and a mirror flips one.
    if abs(b) > 1e-6 or abs(c) > 1e-6:
        return False
    return a > 0 and d > 0


def _single_embedded_image(document, page) -> bytes | None:
    """The page's bytes when the page *is* one image, otherwise ``None``."""
    images = page.get_images(full=True)
    if len(images) != 1:
        return None
    xref = images[0][0]
    # `get_images(full=True)` reports each image's declared size, and that is
    # the only chance to see how big one is before `extract_image` decompresses
    # it into memory. A page that embeds a gigapixel scan renders instead: the
    # render is bounded by the page rectangle below, so the huge image is simply
    # downsampled to the page it was drawn on, which is what it looked like
    # anyway. No new failure, one fewer allocation nothing was guarding.
    if int(images[0][2]) * int(images[0][3]) > MAX_PAGE_PIXELS:
        return None

    # `get_images` counts IMAGES. A page that is one scan plus a line of typeset
    # dialogue, a redaction bar, or a drawn speech tail still answers "one
    # image", and taking those bytes imports the scan with the rest simply gone
    # — no warning, nothing in the file to notice afterwards. The shortcut is
    # only honest when the page IS the image and nothing else.
    if page.get_text("text").strip():
        return None
    try:
        if page.get_drawings():
            return None
    except Exception:  # pragma: no cover - malformed content stream
        return None
    # `/Rotate` is part of how the page looks. The embedded bytes are not
    # rotated, so a landscape spread imported as a portrait page and every
    # balloon measured afterwards was against the wrong axis.
    if page.rotation:
        return None
    # A crop box smaller than the media box means the reader is shown less than
    # the image holds; extracting gives back the part that was cropped away.
    if tuple(page.cropbox) != tuple(page.mediabox):
        return None
    try:
        rects = page.get_image_rects(xref)
    except Exception:  # pragma: no cover - malformed PDF
        return None
    # Drawn once. The same XObject placed twice — a tiled background, a page
    # shown beside its own thumbnail — is a page that does not look like its
    # bytes, however much of it the two placements cover between them.
    if len(rects) != 1:
        return None
    rect = rects[0]
    page_rect = page.rect
    if abs(page_rect.width * page_rect.height) <= 0:
        return None
    # The placement must BE the page, to within a pixel. The old test was that
    # the image covered 92% of it, which passed a scan inset by a centimetre of
    # margin on every side and then imported it as though it filled the page —
    # so every box measured afterwards was offset from the artwork by the
    # margin that had been thrown away.
    if (abs(rect.x0 - page_rect.x0) > _PLACEMENT_SLACK
            or abs(rect.y0 - page_rect.y0) > _PLACEMENT_SLACK
            or abs(rect.x1 - page_rect.x1) > _PLACEMENT_SLACK
            or abs(rect.y1 - page_rect.y1) > _PLACEMENT_SLACK):
        return None
    # And it must be placed the way it was stored. `page.rotation` is one way a
    # page turns; the image's own placement matrix is another, and a 180°
    # placement still handed back unrotated bytes — an upside-down page that
    # every later stage measured as though it were the right way up.
    if not _upright(page, xref):
        return None
    try:
        extracted = document.extract_image(xref)
    except Exception:  # pragma: no cover - malformed PDF
        return None
    payload = extracted.get("image")
    if not payload:
        return None
    # A CMYK or exotic colourspace round-trips badly; render those instead.
    if extracted.get("colorspace", 3) > 3:
        return None
    # An image with its own transparency is composited over whatever is behind
    # it. Extracting it alone gives back the layer, not the page.
    if extracted.get("smask"):
        return None
    return payload


def _from_directory(path: Path, pages_dir: Path) -> list[Path]:
    candidates = sorted(
        (child for child in path.iterdir()
         if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda child: natural_key(child.name),
    )
    if not candidates:
        raise ValueError(f"No page images in {path}")
    _check_page_count(path.name, len(candidates))
    written: list[Path] = []
    for index, source in enumerate(candidates):
        target = pages_dir / f"{ir.page_id_for(index)}{source.suffix.lower()}"
        shutil.copyfile(source, target)
        written.append(target)
    return written


def _from_image(path: Path, pages_dir: Path) -> list[Path]:
    target = pages_dir / f"{ir.page_id_for(0)}{path.suffix.lower()}"
    shutil.copyfile(path, target)
    return [target]


def detect_kind(path: Path) -> str:
    if path.is_dir():
        return "directory"
    suffix = path.suffix.lower()
    if suffix in ARCHIVE_SUFFIXES:
        return "cbz"
    if suffix in RAR_SUFFIXES:
        return "cbr"
    if suffix == ".pdf":
        return "pdf"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    # A CBZ renamed to something else is common enough to be worth the probe.
    if zipfile.is_zipfile(path):
        return "cbz"
    raise ValueError(
        f"Cannot tell what {path.name} is. Supported: CBZ, CBR, PDF, a folder "
        f"of images, or a single image."
    )


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def _refuse_overlap(source: Path, pages_dir: Path) -> None:
    """Refuse a source and a destination that sit inside one another.

    `import` replaces `work/pages` wholesale. If the source lives in there it is
    deleted before it can be read; if `work` sits under the source, a folder
    import walks into its own output and then deletes it. Neither is recoverable,
    and neither is worth trying to be clever about — say so and stop.
    """
    src = source.expanduser().resolve()
    dst = pages_dir.expanduser().resolve()
    # The scratch and backup folders live in the working directory beside
    # `pages`, so a source inside the working directory is inside the blast
    # radius even when it is not inside `pages` itself.
    work = dst.parent
    if src == work or work in src.parents:
        raise ValueError(
            f"the source {src} is inside the working folder this import "
            f"writes to ({work}). Move the source, or pick a different --out."
        )
    if src == dst or dst in src.parents:
        raise ValueError(
            f"the source {src} is inside the pages folder this import replaces "
            f"({dst}). Importing it would delete it. Move the source, or pick a "
            f"different --out."
        )
    if src in dst.parents:
        raise ValueError(
            f"the output folder {dst} is inside the source {src}. The import "
            f"would read its own output and then delete it. Pick a --out that "
            f"is not under the source."
        )


def scratch(work: Path, label: str) -> Path:
    """A scratch path this run owns, and nobody else could already be using.

    The names were fixed — `.pages-incoming`, `pages.previous` — and both were
    deleted on sight. A folder of that name that belonged to the operator, or
    to another import running at the same time, went with them. A random
    suffix costs nothing and makes ownership a fact rather than a hope.
    """
    import secrets

    for _ in range(8):
        candidate = work / f".{label}-{secrets.token_hex(6)}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find an unused scratch name under {work}")


def _stage_pages(kind: str, path: Path, staging: Path, dpi: int) -> list[Path]:
    """Read the source into a staging folder, and clean up if it goes wrong.

    Nothing the caller already owns is touched here. A failed read leaves only
    the staging folder to remove.
    """
    # Never `rmtree` a path we did not just name: `scratch()` hands back one
    # that does not exist, and anything sitting there is somebody else's.
    staging.mkdir(parents=True, exist_ok=False)
    readers = {
        "cbz": lambda: _from_zip(path, staging),
        "cbr": lambda: _from_rar(path, staging),
        "pdf": lambda: _from_pdf(path, staging, dpi),
        "directory": lambda: _from_directory(path, staging),
        "image": lambda: _from_image(path, staging),
    }
    try:
        return readers[kind]()
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _commit_pages(staging: Path, pages_dir: Path, previous: Path) -> bool:
    """Swap the validated staging folder into place. Returns whether a previous
    version was moved aside, and LEAVES it there.

    The caller deletes it, and only once `comic.json` has been written. The old
    folder used to be removed at the end of this function, one line before the
    document was saved — so a failed save left the new pages on disk, the
    backup gone, and the old `comic.json` pointing at files that no longer
    existed. Neither version was then complete.
    """
    moved = False
    if pages_dir.exists():
        pages_dir.rename(previous)
        moved = True
    try:
        staging.rename(pages_dir)
    except BaseException:
        if moved:
            previous.rename(pages_dir)
        raise
    return moved


def import_source(
    source: str | Path,
    out: str | Path,
    *,
    source_language: str = "auto",
    target_language: str = "fa",
    direction: str = "rtl",
    title: str = "",
    chapter: str = "",
    dpi: int = PDF_DPI,
) -> dict[str, Any]:
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"No such file or folder: {path}")

    work = Path(out).expanduser()
    pages_dir = work / "pages"
    # Before anything is removed. This used to run after `pages_dir` had already
    # been deleted, so importing a folder that lived inside it destroyed the
    # only copy of the thing being imported.
    _refuse_overlap(path, pages_dir)

    kind = detect_kind(path)
    staging = scratch(work, "incoming")
    previous = scratch(work, "previous")
    files = _stage_pages(kind, path, staging, dpi)

    doc = ir.new_doc(
        source_language=source_language,
        target_language=target_language,
        reading_direction=direction,
        title=title or path.stem,
        chapter=chapter,
    )
    doc["source"] = {
        "kind": kind,
        "name": path.name,
        "page_count": len(files),
        "dpi": dpi if kind == "pdf" else None,
    }

    sizes: list[tuple[int, int]] = []
    try:
        # Every page is opened and hashed while it is still only staged, so a
        # source that turns out to be unreadable half way through is refused
        # with the previous chapter still on disk.
        for index, file in enumerate(files):
            image = _load_page(file)
            width, height = image.size
            sizes.append((width, height))
            doc["pages"].append(
                ir.new_page(
                    ir.page_id_for(index),
                    index,
                    f"pages/{file.name}",
                    width,
                    height,
                    ir.sha256_file(file),
                )
            )
        moved = _commit_pages(staging, pages_dir, previous)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # One transaction, pages and document together. Until this succeeds the
    # previous pages are still on disk under `previous`, and a failure puts
    # them back rather than leaving a chapter that references files that are
    # not there.
    doc_path = work / "comic.json"
    try:
        ir.save_doc(doc, doc_path)
    except BaseException:
        shutil.rmtree(pages_dir, ignore_errors=True)
        if moved:
            previous.rename(pages_dir)
        raise
    shutil.rmtree(previous, ignore_errors=True)

    widths = sorted(size[0] for size in sizes)
    heights = sorted(size[1] for size in sizes)
    median = (widths[len(widths) // 2], heights[len(heights) // 2]) if sizes else (0, 0)
    # A webtoon is one very tall strip per file; it needs the vertical reading
    # order and a different crop strategy, so say so rather than letting the
    # detector quietly do the wrong thing on a 20,000-pixel page.
    tall = [
        page["id"] for page in doc["pages"]
        if page["height"] >= 3 * max(1, page["width"])
    ]

    return {
        "document": str(doc_path),
        "kind": kind,
        "pages": len(files),
        "median_size": list(median),
        "reading_direction": direction,
        "webtoon_strips": tall,
        "warning": (
            f"{len(tall)} page(s) are at least three times taller than they are "
            "wide — that is a webtoon strip, not a book page. Pass "
            "`--direction ltr` and expect one long column."
        ) if tall else None,
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic import",
        description="Normalise a comic into immutable page images.",
    )
    parser.add_argument("source", help="CBZ, CBR, PDF, folder of images, or one image")
    parser.add_argument("--out", required=True, help="working folder")
    parser.add_argument("--source-language", default="auto",
                        help="ja, ko, zh, en, or auto")
    parser.add_argument("--target-language", default="fa")
    parser.add_argument("--direction", choices=["rtl", "ltr"], default="rtl",
                        help="how the SOURCE pages are read: rtl for Japanese "
                             "manga, ltr for webtoons and Western comics")
    parser.add_argument("--title", default="")
    parser.add_argument("--chapter", default="")
    parser.add_argument("--dpi", type=int, default=PDF_DPI,
                        help="render resolution for PDF pages that are not a "
                             "single embedded image")
    args = parser.parse_args(argv)

    report = import_source(
        args.source,
        args.out,
        source_language=args.source_language,
        target_language=args.target_language,
        direction=args.direction,
        title=args.title,
        chapter=args.chapter,
        dpi=args.dpi,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
