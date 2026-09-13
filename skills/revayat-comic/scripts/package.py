"""Verifying a package: what actually shipped, against what the export wrote.

Separate from `qa.py`, which verifies the working chapter. The questions are
different — one asks whether the pages on disk are finished, the other whether
the file somebody will hand to a reader opens, holds the right pages, in the
right order, and carries the bytes that were exported.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pageir as ir
from qa import IMAGE_SUFFIXES, Findings

def _page_size(payload: bytes) -> tuple[tuple[int, int] | None, str]:
    """``(size, problem)``. `problem` is "" when the page really decoded.

    DECODED, not merely parsed. `Image.open` is lazy: it reads the header and
    stops, so a PNG whose chunk CRCs are correct and whose compressed pixels
    are rubbish reported its declared size and passed. `load()` is what a
    reader will do to it, and it is what fails.

    A page over the decode limit is REFUSED, not measured. It used to return
    the declared size and nothing else looked at it, so the one input designed
    to make a checker give up — a decompression bomb — turned a resource limit
    into a passing verification. A limit that cannot be reached safely is an
    unknown, and an unknown is not a pass.
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(payload)) as image:
            size = image.size
            if size[0] * size[1] > MAX_DECODE_PIXELS:
                return size, (
                    f"declares {size[0]}x{size[1]}, over the "
                    f"{MAX_DECODE_PIXELS:,}-pixel decode limit, so it was not "
                    f"opened and cannot be verified")
            image.load()
            return image.size, ""
    except Exception:
        return None, "is not an image the reader can open"


#: Refuse to decode more than this in one page. A packaged chapter is checked
#: page by page, so nothing here holds the whole of it in memory.
MAX_DECODE_PIXELS = 80_000_000


def _manifest_of(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """What the last export said it wrote, if it said."""
    return ((doc.get("stages") or {}).get("export") or {}).get("manifest") or []


def _check_identity(findings: Findings, where: str,
                    pages: list[tuple[str, bytes]],
                    doc: dict[str, Any]) -> None:
    """Compare the package with the manifest the export wrote.

    The order check used to sort the names and then ask whether they were
    sorted, which is true of every list. What it meant to ask is whether
    sorting them gives the document's reading order — and that can only be
    answered against a record of which page each name was.
    """
    manifest = _manifest_of(doc)
    if not manifest:
        return
    by_name = {row["name"]: row for row in manifest}

    # Two identical pages is how a duplicated spread ships: the count is right,
    # the names are right, and one page of the chapter is simply missing. But a
    # chapter may legitimately hold two identical pages — a black page, a
    # repeated panel — so this is only a defect where the export says those two
    # pages were NOT the same.
    seen: dict[str, str] = {}
    for name, payload in pages:
        digest = ir.sha256_bytes(payload)
        twin = seen.get(digest)
        if twin is not None:
            expected = (by_name.get(name) or {}).get("sha256")
            other = (by_name.get(twin) or {}).get("sha256")
            if expected and other and expected != other:
                findings.add("archive-duplicate-page", where,
                             f"{name} is byte-identical to {twin}, and the "
                             f"export wrote two different pages")
        seen[digest] = name
    for index, (name, payload) in enumerate(pages):
        row = by_name.get(name)
        if row is None:
            findings.add("archive-invalid", where,
                         f"{name} is not a page this export wrote")
            continue
        if index < len(manifest) and manifest[index]["name"] != name:
            findings.add("archive-invalid", where,
                         f"{name} sorts into position {index + 1}; the export "
                         f"wrote {manifest[index]['name']} there")
        # Every row, lossy or not. `sha256` is the hash of the bytes the
        # export WROTE — the re-encoded JPEG, not the PNG it came from — so it
        # is always comparable, and gating it behind `lossy` left every JPEG
        # page in every package unverified.
        if row.get("sha256") and ir.sha256_bytes(payload) != row["sha256"]:
            findings.add("archive-invalid", where,
                         f"{name} is not the bytes that were exported")


def _check_pages(findings: Findings, where: str, sizes: list[tuple[str, bytes]],
                 doc: dict[str, Any]) -> None:
    """Open every page the package claims to have, and measure it.

    The check used to be a suffix match on a name. Measured against a package
    built by hand: bytes that are not an image passed, a *directory* entry named
    `p0002.png/` passed (its `Path(...).suffix` is `.png`), and a page at the
    wrong size passed. Only the name-ordering test did real work.
    """
    expected = [(page["width"], page["height"]) for page in doc["pages"]]
    for index, (name, payload) in enumerate(sizes):
        size, problem = _page_size(payload)
        if problem:
            findings.add("archive-invalid", where, f"{name} {problem}")
            continue
        if index < len(expected) and size != expected[index]:
            findings.add(
                "archive-page-size", where,
                f"{name} is {size[0]}x{size[1]}; the document says page "
                f"{index + 1} is {expected[index][0]}x{expected[index][1]}",
            )


#: How much of a page an image must cover before it counts as the page's
#: content. A placed thumbnail, a logo, or a resource left in the page's
#: dictionary and never drawn are all "an image on the page" to a resource
#: listing, and none of them is the artwork.
MIN_PAGE_IMAGE_SHARE = 0.5


def _check_pdf_page(findings: Findings, where: str, document: Any, page: Any,
                    index: int, manifest: list[dict[str, Any]]) -> None:
    """Does this sheet actually show the page the export wrote?

    The old test was `page.get_images(full=True)` — does the page's resource
    dictionary mention an image at all. It does not ask whether the image is
    drawn, whether it is on the sheet, or whether it is THIS chapter's page: an
    XObject placed off the edge satisfied it, and so did an unrelated picture
    of the same shape.
    """
    import io

    from PIL import Image

    rect = page.rect
    area = abs(rect.width * rect.height) or 1.0
    placed = []
    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox")
        xref = info.get("xref")
        if not bbox or not xref:
            continue
        drawn = pymupdf_rect(bbox) & rect
        if abs(drawn.width * drawn.height) / area >= MIN_PAGE_IMAGE_SHARE:
            placed.append(xref)
    if not placed:
        findings.add("archive-invalid", where,
                     f"page {index + 1} shows no image covering the sheet")
        return

    row = manifest[index] if index < len(manifest) else None
    wanted = (row or {}).get("pixels")
    if not wanted:
        return          # a package from a build that did not record them
    for xref in placed:
        try:
            payload = document.extract_image(xref)["image"]
            with Image.open(io.BytesIO(payload)) as image:
                if ir.sha256_bytes(image.convert("RGB").tobytes()) == wanted:
                    return
        except Exception:
            continue
    findings.add("archive-invalid", where,
                 f"page {index + 1} does not show the page this export wrote")


def pymupdf_rect(bbox: Any) -> Any:
    """A `Rect` from whatever shape PyMuPDF handed back."""
    import pymupdf

    return pymupdf.Rect(bbox)


def check_package(package: str | Path, doc_path: str | Path) -> dict[str, Any]:
    package = Path(package)
    doc = ir.load_doc(Path(doc_path))
    findings = Findings()
    expected = len(doc["pages"])

    if not package.exists():
        findings.add("archive-invalid", package.name, "the file does not exist")
        return _package_report(findings, package, expected, 0)

    found = 0
    if package.suffix.lower() in {".cbz", ".zip"}:
        if not zipfile.is_zipfile(package):
            findings.add("archive-invalid", package.name, "not a valid ZIP archive")
        else:
            with zipfile.ZipFile(package) as archive:
                bad = archive.testzip()
                if bad:
                    findings.add("archive-invalid", package.name,
                                 f"corrupt member: {bad}")
                # `info.is_dir()`, not the name: a member called `p0002.png/`
                # is a directory, and `Path("p0002.png/").suffix` is `.png`, so
                # counting by name alone let one stand in for a page.
                names = sorted(
                    info.filename for info in archive.infolist()
                    if not info.is_dir()
                    and Path(info.filename).suffix.lower() in IMAGE_SUFFIXES
                )
                found = len(names)
                members = [(name, archive.read(name)) for name in names]
                _check_pages(findings, package.name, members, doc)
                # Order is the whole point of a comic archive, and a reader
                # sorts by name. Whether THAT order is the reading order is a
                # question about the manifest, not about the names: the old
                # check sorted them and then asked whether they were sorted.
                _check_identity(findings, package.name, members, doc)
    elif package.suffix.lower() == ".pdf":
        pymupdf = ir.require("pymupdf", "pymupdf", "verifying a PDF")
        try:
            manifest = _manifest_of(doc)
            with pymupdf.open(str(package)) as document:
                found = document.page_count
                # Counting pages proves the chapter has the right number of
                # sheets of paper. Whether each one is the size the document
                # says — and carries anything at all — is the question a reader
                # would notice, and nothing asked it.
                for index, page in enumerate(document):
                    if index >= len(doc["pages"]):
                        break
                    want = doc["pages"][index]
                    ratio = (want["width"] / want["height"]
                             if want["height"] else 0)
                    shown = (page.rect.width / page.rect.height
                             if page.rect.height else 0)
                    if ratio and abs(shown - ratio) > 0.02:
                        findings.add(
                            "archive-page-size", package.name,
                            f"page {index + 1} is {page.rect.width:.0f}x"
                            f"{page.rect.height:.0f}, a different shape from "
                            f"{want['width']}x{want['height']}")
                    _check_pdf_page(findings, package.name, document, page,
                                    index, manifest)
        except Exception as error:
            findings.add("archive-invalid", package.name, f"cannot open: {error}")
    else:
        children = sorted(
            child for child in package.iterdir()
            if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES
        ) if package.is_dir() else []
        found = len(children)
        members = [(child.name, child.read_bytes()) for child in children]
        _check_pages(findings, package.name, members, doc)
        _check_identity(findings, package.name, members, doc)

    if found != expected:
        findings.add("archive-page-count", package.name,
                     f"{found} page(s) in the package, {expected} in the document")
    return _package_report(findings, package, expected, found)


def _package_report(findings: Findings, package: Path, expected: int,
                    found: int) -> dict[str, Any]:
    errors = [item for item in findings.items if item["severity"] == "error"]
    return {
        "ok": not errors,
        "package": str(package),
        "pages_expected": expected,
        "pages_found": found,
        "findings": findings.items,
    }
