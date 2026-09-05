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
import zipfile
from pathlib import Path
from typing import Any, Iterable

import pageir as ir

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
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
# Sources
# --------------------------------------------------------------------------- #

def _from_zip(path: Path, pages_dir: Path) -> list[Path]:
    written: list[Path] = []
    with zipfile.ZipFile(path) as archive:
        members = _image_members(archive.namelist())
        if not members:
            raise ValueError(
                f"{path.name} contains no images. A CBZ is a ZIP of page "
                f"images; this one holds {len(archive.namelist())} other entries."
            )
        for index, member in enumerate(members):
            suffix = Path(member).suffix.lower()
            target = pages_dir / f"{ir.page_id_for(index)}{suffix}"
            ir.write_bytes(target, archive.read(member))
            written.append(target)
    return written


def _from_rar(path: Path, pages_dir: Path) -> list[Path]:
    rarfile = ir.require("rarfile", "rarfile", "reading CBR archives")
    try:
        archive = rarfile.RarFile(str(path))
    except rarfile.RarCannotExec as error:  # pragma: no cover - depends on host
        raise ir.MissingDependency(
            "rarfile needs an unrar/bsdtar binary on PATH to open a CBR.\n"
            "    Linux/macOS: install `unrar` or `libarchive-tools`\n"
            "    Windows:     install WinRAR, or convert the file to CBZ\n"
            f"({error})"
        ) from error
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
    with archive:
        members = _image_members(archive.namelist())
        if not members:
            raise ValueError(f"{path.name} contains no images.")
        for index, member in enumerate(members):
            suffix = Path(member).suffix.lower()
            target = pages_dir / f"{ir.page_id_for(index)}{suffix}"
            ir.write_bytes(target, archive.read(member))
            written.append(target)
    return written


def _from_pdf(path: Path, pages_dir: Path, dpi: int) -> list[Path]:
    pymupdf = ir.require("pymupdf", "pymupdf", "reading comic PDFs")
    written: list[Path] = []
    with pymupdf.open(str(path)) as document:
        for index, page in enumerate(document):
            target = pages_dir / f"{ir.page_id_for(index)}.png"
            payload = _single_embedded_image(document, page)
            if payload is not None:
                # A comic PDF is usually one scan per page. Taking those bytes
                # keeps the original pixels; re-rendering resamples artwork that
                # was already at its native resolution and softens screentone.
                ir.write_bytes(target, payload)
            else:
                pixmap = page.get_pixmap(dpi=dpi)
                ir.write_bytes(target, pixmap.tobytes("png"))
            written.append(target)
    return written


def _single_embedded_image(document, page) -> bytes | None:
    """The page's bytes when the page *is* one image, otherwise ``None``."""
    images = page.get_images(full=True)
    if len(images) != 1:
        return None
    xref = images[0][0]
    try:
        rects = page.get_image_rects(xref)
    except Exception:  # pragma: no cover - malformed PDF
        return None
    if not rects:
        return None
    page_area = abs(page.rect.width * page.rect.height)
    covered = sum(abs(rect.width * rect.height) for rect in rects)
    if page_area <= 0 or covered / page_area < 0.92:
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
    return payload


def _from_directory(path: Path, pages_dir: Path) -> list[Path]:
    candidates = sorted(
        (child for child in path.iterdir()
         if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda child: natural_key(child.name),
    )
    if not candidates:
        raise ValueError(f"No page images in {path}")
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
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    kind = detect_kind(path)
    readers = {
        "cbz": lambda: _from_zip(path, pages_dir),
        "cbr": lambda: _from_rar(path, pages_dir),
        "pdf": lambda: _from_pdf(path, pages_dir, dpi),
        "directory": lambda: _from_directory(path, pages_dir),
        "image": lambda: _from_image(path, pages_dir),
    }
    files = readers[kind]()

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
    for index, file in enumerate(files):
        image = ir.load_image(file)
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

    doc_path = work / "comic.json"
    ir.save_doc(doc, doc_path)

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
