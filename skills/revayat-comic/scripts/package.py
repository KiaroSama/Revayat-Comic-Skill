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

def _page_size(payload: bytes) -> tuple[int, int] | None:
    """The image's dimensions, or ``None`` when those bytes will not decode.

    DECODED, not merely parsed. `Image.open` is lazy: it reads the header and
    stops, so a PNG whose chunk CRCs are correct and whose compressed pixels
    are rubbish reported its declared size and passed. `load()` is what a
    reader will do to it, and it is what fails.
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(payload)) as image:
            size = image.size
            if size[0] * size[1] > MAX_DECODE_PIXELS:
                # A decompression bomb in a package is not a page; refusing to
                # decode it is the right answer and so is saying its size.
                return size
            image.load()
            return image.size
    except Exception:
        return None


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
        if not row.get("lossy") and row.get("sha256"):
            if ir.sha256_bytes(payload) != row["sha256"]:
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
        size = _page_size(payload)
        if size is None:
            findings.add("archive-invalid", where,
                         f"{name} is not an image the reader can open")
            continue
        if index < len(expected) and size != expected[index]:
            findings.add(
                "archive-page-size", where,
                f"{name} is {size[0]}x{size[1]}; the document says page "
                f"{index + 1} is {expected[index][0]}x{expected[index][1]}",
            )


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
                    if not page.get_images(full=True):
                        findings.add("archive-invalid", package.name,
                                     f"page {index + 1} carries no image")
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
