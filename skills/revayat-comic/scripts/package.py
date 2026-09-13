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


#: Refuse a package with more members than this before reading any of them.
#: A chapter is a few dozen pages; a hundred thousand members is an attack on
#: the checker, not a comic.
MAX_MEMBERS = 5_000

#: Per page, uncompressed. Checked against the member's DECLARED size before a
#: byte is extracted, so a zip bomb is refused rather than decompressed.
MAX_MEMBER_BYTES = 64 * 1024 * 1024

#: And the whole package, so many just-under-the-limit members cannot add up.
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024

#: Uncompressed divided by compressed. Ordinary PNG and JPEG pages are close to
#: 1; a thousandfold is a file built to be expanded, not read.
MAX_COMPRESSION_RATIO = 200


def _manifest_of(doc: dict[str, Any], package: Path,
                 fmt: str) -> tuple[list[dict[str, Any]], str]:
    """`(manifest, problem)` — what THIS package's export wrote, if it can be
    known.

    There was one manifest, belonging to whichever export ran last. Export a
    chapter as CBZ and then as PDF and the CBZ was verified against the PDF's
    rows: different names, different bytes, every page reported wrong.

    Two ways of finding the right one, in order. The destination it was
    published to, which is exact. Failing that, its FORMAT — a package that has
    been copied, renamed or handed to somebody is still recognisably the
    archive edition or the PDF edition, and refusing to check a file because it
    moved would make the gate useless for the thing people actually do with a
    package. Two editions of one format and no destination match is genuinely
    ambiguous, and says so.
    """
    stamp = ((doc.get("stages") or {}).get("export") or {})
    if not stamp:
        return [], ("this chapter has never been exported, so there is "
                    "nothing to check the package against")

    target = str(package.resolve())
    editions = dict(stamp.get("editions") or {})
    if not editions and stamp.get("manifest"):
        # A document stamped before editions were recorded per destination.
        editions = {str(Path(stamp.get("path") or target).resolve()):
                    {"format": stamp.get("format") or fmt,
                     "manifest": stamp["manifest"]}}
    if target in editions:
        return (editions[target].get("manifest") or []), ""

    matching = [edition for edition in editions.values()
                if edition.get("format") == fmt]
    if len(matching) == 1:
        return (matching[0].get("manifest") or []), ""
    if not matching:
        return [], (f"the document records no {fmt} edition of this chapter, "
                    f"so this package cannot be checked against what was "
                    f"written. Export it again")
    return [], (f"the document records {len(matching)} {fmt} editions and "
                f"this package is at none of their destinations, so which one "
                f"it should match is undecidable. Check the package at the "
                f"destination the document names")


def _verify_members(findings: Findings, where: str, names: list[str],
                    payload_of: Any, doc: dict[str, Any],
                    manifest: list[dict[str, Any]]) -> None:
    """Every page of the package, one page in memory at a time.

    Reading the whole chapter into a list first was a second resource limit
    nobody had set: a folder of forty 8000x12000 pages is several gigabytes
    before a single check runs. Nothing here holds more than one page.

    Three questions, asked together because they all want the same bytes: does
    this page decode, is it the size the document says, and is it the page this
    export wrote.
    """
    expected = [(page["width"], page["height"]) for page in doc["pages"]]
    by_name = {row["name"]: row for row in manifest}
    seen: dict[str, str] = {}

    for index, name in enumerate(names):
        payload = payload_of(name)
        if payload is None:
            continue
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
        if not manifest:
            continue

        digest = ir.sha256_bytes(payload)
        # Two identical pages is how a duplicated spread ships: the count is
        # right, the names are right, and one page of the chapter is simply
        # missing. But a chapter may legitimately hold two identical pages — a
        # black page, a repeated panel — so this is only a defect where the
        # export says those two pages were NOT the same.
        twin = seen.get(digest)
        if twin is not None:
            wanted = (by_name.get(name) or {}).get("sha256")
            other = (by_name.get(twin) or {}).get("sha256")
            if wanted and other and wanted != other:
                findings.add("archive-duplicate-page", where,
                             f"{name} is byte-identical to {twin}, and the "
                             f"export wrote two different pages")
        seen[digest] = name

        row = by_name.get(name)
        if row is None:
            findings.add("archive-invalid", where,
                         f"{name} is not a page this export wrote")
            continue
        # Order is the whole point of a comic archive, and a reader sorts by
        # name. Whether THAT order is the reading order is a question about the
        # manifest, not about the names: the old check sorted them and then
        # asked whether they were sorted.
        if index < len(manifest) and manifest[index]["name"] != name:
            findings.add("archive-invalid", where,
                         f"{name} sorts into position {index + 1}; the export "
                         f"wrote {manifest[index]['name']} there")
        # Every row, lossy or not. `sha256` is the hash of the bytes the export
        # WROTE — the re-encoded JPEG, not the PNG it came from — so it is
        # always comparable, and gating it behind `lossy` left every JPEG page
        # in every package unverified.
        if row.get("sha256") and digest != row["sha256"]:
            findings.add("archive-invalid", where,
                         f"{name} is not the bytes that were exported")


def _zip_members(findings: Findings, where: str,
                 archive: Any) -> list[str] | None:
    """The page members of an archive, or `None` when it must not be read.

    Every limit here is checked against what the archive DECLARES, before a
    byte is extracted. A checker that has to decompress a file to find out it
    is too large has already lost.
    """
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        findings.add("archive-invalid", where,
                     f"{len(infos)} members, over the {MAX_MEMBERS} this will "
                     f"open. Nothing was read")
        return None

    total = 0
    names: list[str] = []
    for info in infos:
        if info.is_dir():
            continue
        total += info.file_size
        if info.file_size > MAX_MEMBER_BYTES:
            findings.add("archive-invalid", where,
                         f"{info.filename} unpacks to {info.file_size:,} "
                         f"bytes, over the {MAX_MEMBER_BYTES:,} limit. "
                         f"Nothing was read")
            return None
        if info.compress_size and (info.file_size / info.compress_size
                                   > MAX_COMPRESSION_RATIO):
            findings.add("archive-invalid", where,
                         f"{info.filename} expands "
                         f"{info.file_size // max(info.compress_size, 1)}x, "
                         f"over the {MAX_COMPRESSION_RATIO}x limit. Nothing "
                         f"was read")
            return None
        # `info.is_dir()`, not the name: a member called `p0002.png/` is a
        # directory, and `Path("p0002.png/").suffix` is `.png`, so counting by
        # name alone let one stand in for a page.
        if Path(info.filename).suffix.lower() in IMAGE_SUFFIXES:
            names.append(info.filename)
    if total > MAX_TOTAL_BYTES:
        findings.add("archive-invalid", where,
                     f"unpacks to {total:,} bytes, over the "
                     f"{MAX_TOTAL_BYTES:,} limit. Nothing was read")
        return None

    # A ZIP may hold two members under one name, and every tool picks a
    # different one — including the reader, which will not pick the one that
    # was checked. There is no safe reading of it.
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        findings.add("archive-invalid", where,
                     f"{len(repeated)} name(s) appear on more than one member "
                     f"({', '.join(repeated[:3])}), so which page a reader "
                     f"opens is undefined")
        return None
    return sorted(names)


def _looks_like_pdf(package: Path) -> bool:
    """Five bytes, so the format is decided by content and not by a suffix."""
    try:
        with package.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _check_cbz(findings: Findings, package: Path, doc: dict[str, Any],
               manifest: list[dict[str, Any]]) -> int:
    with zipfile.ZipFile(package) as archive:
        bad = archive.testzip()
        if bad:
            findings.add("archive-invalid", package.name,
                         f"corrupt member: {bad}")
        names = _zip_members(findings, package.name, archive)
        if names is None:
            return 0
        _verify_members(findings, package.name, names,
                        lambda name: archive.read(name), doc, manifest)
        return len(names)


def _check_dir(findings: Findings, package: Path, doc: dict[str, Any],
               manifest: list[dict[str, Any]]) -> int:
    children = sorted(child for child in package.iterdir()
                      if child.is_file()
                      and child.suffix.lower() in IMAGE_SUFFIXES)
    if len(children) > MAX_MEMBERS:
        findings.add("archive-invalid", package.name,
                     f"{len(children)} page(s), over the {MAX_MEMBERS} this "
                     f"will open. Nothing was read")
        return 0
    total = 0
    for child in children:
        size = child.stat().st_size
        total += size
        if size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
            findings.add("archive-invalid", package.name,
                         f"{child.name} takes the folder over the "
                         f"{MAX_MEMBER_BYTES:,}-byte page limit or the "
                         f"{MAX_TOTAL_BYTES:,}-byte total. Nothing was read")
            return 0
    _verify_members(findings, package.name, [child.name for child in children],
                    lambda name: (package / name).read_bytes(), doc, manifest)
    return len(children)


def _check_pdf(findings: Findings, package: Path, doc: dict[str, Any],
               manifest: list[dict[str, Any]]) -> int:
    import pdfpage

    pymupdf = ir.require("pymupdf", "pymupdf", "verifying a PDF")
    try:
        with pymupdf.open(str(package)) as document:
            found = document.page_count
            if found > MAX_MEMBERS:
                findings.add("archive-invalid", package.name,
                             f"{found} sheets, over the {MAX_MEMBERS} this "
                             f"will open. Nothing was rendered")
                return found
            # Counting pages proves the chapter has the right number of sheets
            # of paper. Whether each one is the size the document says — and
            # carries anything at all — is the question a reader would notice,
            # and nothing asked it.
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
                if not manifest:
                    continue
                row = manifest[index] if index < len(manifest) else {}
                code, message = pdfpage.verify(document, page, row, index)
                if code:
                    findings.add(code, package.name, message)
            return found
    except Exception as error:
        findings.add("archive-invalid", package.name, f"cannot open: {error}")
        return 0


def _format_of(package: Path) -> str:
    """What this package IS, by content. Empty when it is nothing readable.

    Dispatching on the suffix meant `export --format cbz --out chapter.xyz`
    produced an archive the checker then refused to look inside, and a `.cbz`
    that is not a ZIP got as far as the ZIP reader before anything noticed.
    """
    if package.is_dir():
        return "dir"
    if zipfile.is_zipfile(package):
        return "cbz"
    if _looks_like_pdf(package):
        return "pdf"
    return ""


def check_package(package: str | Path, doc_path: str | Path) -> dict[str, Any]:
    package = Path(package)
    doc = ir.load_doc(Path(doc_path))
    findings = Findings()
    expected = len(doc["pages"])

    if not package.exists():
        findings.add("archive-invalid", package.name, "the file does not exist")
        return _package_report(findings, package, expected, 0)

    fmt = _format_of(package)
    if not fmt:
        findings.add(
            "archive-invalid", package.name,
            "not a valid ZIP archive"
            if package.suffix.lower() in {".cbz", ".zip"}
            else f"{package.name} is neither an archive, a PDF nor a folder "
                 f"of pages")
        return _package_report(findings, package, expected, 0)

    manifest, problem = _manifest_of(doc, package, fmt)
    if problem:
        findings.add("archive-unverified", package.name, problem)

    found = {"dir": _check_dir, "cbz": _check_cbz,
             "pdf": _check_pdf}[fmt](findings, package, doc, manifest)

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
