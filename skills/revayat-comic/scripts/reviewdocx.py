"""Write an editable Word companion without changing the primary comic."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

import export as book_export
import pageir as ir
import workspace

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_PAGES = 2000
MAX_REGIONS = 20000
MAX_TEXT_CHARACTERS = 2_000_000
MAX_PARAGRAPHS = 100_000
MAX_TEXT_RUNS = 100_000
MAX_XML_BYTES = 32 * 1024 * 1024

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("w", W)


def _w(parent, name: str, **attributes):
    return ET.SubElement(parent, f"{{{W}}}{name}",
                         {f"{{{W}}}{key}": str(value) for key, value in attributes.items()})


def _xml(root) -> bytes:
    # Literal CR is normalized by XML parsers; its character reference is not.
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).replace(b"\r", b"&#13;")


def _text(value, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if any(not (char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF
                or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF)
           for char in value):
        raise ValueError(f"{field} contains an invalid XML character")
    return value


def _direction(text: str) -> bool:
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in {"L", "R", "AL"}:
            return direction != "L"
    return False


def _runs(text: str, rtl: bool):
    characters = []
    direction = rtl
    for char in text:
        kind = unicodedata.bidirectional(char)
        next_direction = kind != "L" if kind in {"L", "R", "AL"} else direction
        if characters and next_direction != direction:
            yield "".join(characters), direction
            characters = []
        direction = next_direction
        characters.append(char)
    if characters:
        yield "".join(characters), direction


def _styles() -> bytes:
    root = ET.Element(f"{{{W}}}styles")
    defaults = _w(root, "docDefaults")
    run = _w(_w(defaults, "rPrDefault"), "rPr")
    _w(run, "rFonts", ascii="Arial", hAnsi="Arial", cs="Vazirmatn")
    _w(run, "sz", val=24)
    _w(run, "szCs", val=24)
    for name, label, size, level in (
        ("Normal", "Normal", 24, None), ("Heading1", "Heading 1", 32, 0),
        ("Heading2", "Heading 2", 28, 1), ("Label", "Field label", 22, None),
    ):
        style = _w(root, "style", type="paragraph", styleId=name)
        _w(style, "name", val=label)
        if name == "Normal":
            style.set(f"{{{W}}}default", "1")
        else:
            _w(style, "basedOn", val="Normal")
            _w(style, "next", val="Normal")
        paragraph = _w(style, "pPr")
        if name != "Normal":
            _w(paragraph, "keepNext")
        _w(paragraph, "spacing", before=120 if name != "Normal" else 0, after=0)
        if level is not None:
            _w(paragraph, "outlineLvl", val=level)
        run = _w(style, "rPr")
        if name != "Normal":
            _w(run, "b")
            _w(run, "bCs")
        _w(run, "sz", val=size)
        _w(run, "szCs", val=size)
    return _xml(root)


def _document(doc: dict, snapshot: str) -> tuple[bytes, int]:
    root = ET.Element(f"{{{W}}}document")
    body = _w(root, "body")
    characters = 0
    paragraphs = 0
    runs = 0
    identifiers = set()
    region_count = 0

    def paragraph(value, *, style="Normal", rtl=None, field="document text"):
        nonlocal characters, paragraphs, runs
        text = _text(value, field)
        characters += len(text)
        if characters > MAX_TEXT_CHARACTERS:
            raise ValueError(f"review text exceeds {MAX_TEXT_CHARACTERS:,} characters")
        direction = _direction(text) if rtl is None else rtl
        for line in text.split("\n"):
            paragraphs += 1
            if paragraphs > MAX_PARAGRAPHS:
                raise ValueError(f"review document exceeds {MAX_PARAGRAPHS:,} paragraphs")
            node = _w(body, "p")
            properties = _w(node, "pPr")
            _w(properties, "pStyle", val=style)
            if direction:
                _w(properties, "bidi")
            # Word's MS-OE376 alignment is bidi-relative: left is the leading
            # edge, hence the physical right margin for a Persian paragraph.
            _w(properties, "jc", val="left")
            for span, span_rtl in _runs(line, direction):
                runs += 1
                if runs > MAX_TEXT_RUNS:
                    raise ValueError(f"review document exceeds {MAX_TEXT_RUNS:,} text runs")
                run = _w(node, "r")
                run_properties = _w(run, "rPr")
                if span_rtl:
                    _w(run_properties, "rtl")
                    _w(run_properties, "lang", bidi="fa-IR")
                for index, part in enumerate(span.split("\t")):
                    if index:
                        _w(run, "tab")
                    if part:
                        text_node = _w(run, "t")
                        text_node.set(f"{{{XML}}}space", "preserve")
                        text_node.text = part

    def field(label, value, *, rtl=None):
        if value is not None and value != "":
            paragraph(label, style="Label")
            paragraph(value, rtl=rtl, field=label)

    def notes(label, values):
        if not isinstance(values, list):
            raise ValueError(f"{label} must be a list")
        for value in values:
            field(label, value)

    def identity(value, label):
        value = _text(value, label)
        if not value or value in identifiers:
            raise ValueError("page and region IDs must be nonempty and unique")
        identifiers.add(value)
        return value

    meta = doc.get("meta")
    pages = doc.get("pages")
    origin = doc.get("source", {})
    if not isinstance(meta, dict) or not isinstance(pages, list) or not isinstance(origin, dict):
        raise ValueError("document metadata and pages are invalid")
    origin_path = _text(origin.get("path"), "source path")
    _text(meta.get("worksheets"), "worksheet path")
    if len(pages) > MAX_PAGES:
        raise ValueError(f"review document exceeds {MAX_PAGES:,} pages")
    paragraph("Translation review companion", style="Heading1")
    paragraph("Editable snapshot, not a certified primary comic. Apply corrections through stable-ID worksheets.")
    field("Title", meta.get("title"))
    field("Chapter", meta.get("chapter"))
    field("Source container", Path(origin_path).name if origin_path else "")
    field("Source language", meta.get("source_language"))
    field("Target language", meta.get("target_language"))
    field("Snapshot SHA-256", snapshot)
    policy = meta.get("sfx_policy", "keep")
    if not isinstance(policy, str) or policy not in ir.SFX_POLICIES:
        raise ValueError("the document SFX policy is invalid")

    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("each page must be an object")
        page_id = identity(page.get("id"), "page ID")
        if any(type(page.get(key)) is not int or page[key] <= 0 for key in ("width", "height")):
            raise ValueError("page pixel dimensions must be positive integers")
        sheets = page.get("sheets")
        if sheets is not None and (not isinstance(sheets, list)
                                   or any(not isinstance(path, str) for path in sheets)):
            raise ValueError("page crop sheets must be a list of paths")
        paragraph(f"Page {page_id}", style="Heading1")
        paragraph(f"Source dimensions: {page['width']} x {page['height']} pixels")
        if "pdf_points" in page:
            from pagegeometry import pdf_points

            width, height = pdf_points(page)
            paragraph(f"Source PDF dimensions: {width:g} x {height:g} points")
        notes("Page note", page.get("notes", []))
        regions = page.get("regions")
        if not isinstance(regions, list):
            raise ValueError("page regions must be a list")
        region_count += len(regions)
        if region_count > MAX_REGIONS:
            raise ValueError(f"review document exceeds {MAX_REGIONS:,} regions")
        if not regions:
            paragraph("No regions recorded.")
        for region in regions:
            if (not isinstance(region, dict) or not isinstance(region.get("kind"), str)
                    or region["kind"] not in ir.REGION_KINDS):
                raise ValueError("region kind is invalid")
            order = region.get("reading_order")
            if order is not None and (type(order) is not int or order < 0):
                raise ValueError("region reading order must be a nonnegative integer")
            typesetting = region.get("typeset", {})
            if (not isinstance(typesetting, dict) or
                    (typesetting.get("status") is not None and
                     not isinstance(typesetting["status"], str))):
                raise ValueError("region typesetting state must be an object")
            for key in ("source_text", "target_text", "target_full", "speaker"):
                _text(region.get(key), key)
            for key in ("dropped", "erase", "keep", "locked"):
                if key in region and not isinstance(region[key], bool):
                    raise ValueError(f"region {key} must be a boolean")
            if region.get("fill") is not None and not isinstance(region["fill"], str):
                raise ValueError("region fill state must be text")
        for region in sorted(regions, key=lambda item: item.get("reading_order") or 0):
            region_id = identity(region.get("id"), "region ID")
            paragraph(f"Region {region_id}", style="Heading2")
            paragraph(f"Kind: {region['kind']}; state: {ir.region_state(region, policy)}")
            field("Speaker", region.get("speaker"))
            field("Source", region.get("source_text"))
            target = _text(region.get("target_text"), "Displayed Persian")
            field("Displayed Persian", target, rtl=True)
            if not target:
                paragraph("No displayed Persian recorded.")
            field("Full Persian", region.get("target_full"), rtl=True)
            notes("Review note", region.get("review", []))
            notes("Processing note", region.get("audit", []))
            notes("Recorded review code", region.get("review_ack", []))
            for key in ("review_ack_compression", "review_ack_history"):
                if region.get(key):
                    field("Recorded review decision: " + key,
                          json.dumps(region[key], ensure_ascii=False, sort_keys=True))

    section = _w(body, "sectPr")
    _w(section, "pgSz", w=11906, h=16838)
    _w(section, "pgMar", top=1440, right=1440, bottom=1440, left=1440,
       header=720, footer=720, gutter=0)
    document = _xml(root)
    if len(document) > MAX_XML_BYTES:
        raise ValueError(f"Word document XML exceeds {MAX_XML_BYTES // (1024 * 1024)} MiB")
    return document, region_count


def _package(document: bytes) -> bytes:
    content_types = ET.Element(f"{{{CONTENT}}}Types")
    for extension, content_type in (("rels", "application/vnd.openxmlformats-package.relationships+xml"),
                                    ("xml", "application/xml")):
        ET.SubElement(content_types, f"{{{CONTENT}}}Default", Extension=extension, ContentType=content_type)
    for name, kind in (("document", "document.main"), ("styles", "styles")):
        ET.SubElement(content_types, f"{{{CONTENT}}}Override", PartName=f"/word/{name}.xml",
                      ContentType=f"application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml")
    relationships = ET.Element(f"{{{REL}}}Relationships")
    ET.SubElement(relationships, f"{{{REL}}}Relationship", Id="rId1",
                  Type=OFFICE_REL + "officeDocument", Target="word/document.xml")
    document_relationships = ET.Element(f"{{{REL}}}Relationships")
    ET.SubElement(document_relationships, f"{{{REL}}}Relationship", Id="rId1",
                  Type=OFFICE_REL + "styles", Target="styles.xml")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, payload in {
            "[Content_Types].xml": _xml(content_types), "_rels/.rels": _xml(relationships),
            "word/document.xml": document, "word/styles.xml": _styles(),
            "word/_rels/document.xml.rels": _xml(document_relationships),
        }.items():
            package.writestr(name, payload)
    return buffer.getvalue()


def export_document(doc_path: str | Path, out: str | Path) -> dict:
    doc_path = Path(doc_path).expanduser().resolve(strict=True)
    out = Path(out).expanduser().absolute()
    if out.suffix.lower() != ".docx":
        raise ValueError("the review companion destination must end in .docx")
    if os.path.lexists(out):
        raise ValueError("the destination already exists; choose a new .docx path")
    out = out.parent.resolve() / out.name
    with ir.workspace_lock(doc_path.parent, what="review-docx"):
        with doc_path.open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError(f"input document exceeds {MAX_INPUT_BYTES // (1024 * 1024)} MiB")
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict) or doc.get("version") != ir.SCHEMA_VERSION:
            raise ValueError("unsupported PageIR document schema")
        snapshot = ir.sha256_bytes(raw)
        document, regions = _document(doc, snapshot)
        book_export._refuse_collisions(doc, doc_path.parent, doc_path, out, "docx")
        payload = _package(document)
        with workspace.destination_claim(out, doc_path):
            if os.path.lexists(out):
                raise ValueError("the destination already exists; choose a new .docx path")
            descriptor, name = tempfile.mkstemp(prefix=".revayat-review-", suffix=".tmp", dir=out.parent)
            os.close(descriptor)
            staging = Path(name)
            owned = workspace.identity(staging)
            try:
                ir.write_bytes(staging, payload)
                owned = workspace.identity(staging)
                if ir.sha256_file(doc_path) != snapshot:
                    raise RuntimeError("the document changed during export; reload before retrying")
                if (workspace.identity(staging) != owned
                        or ir.sha256_file(staging) != ir.sha256_bytes(payload)):
                    owned = None
                    raise RuntimeError("the staged companion changed before publication")
                # Both operations refuse an existing destination atomically.
                if os.name == "nt":
                    staging.rename(out)
                else:
                    os.link(staging, out)
            finally:
                if staging.exists() and workspace.identity(staging) == owned:
                    staging.unlink()
    return {"ok": True, "path": str(out), "sha256": ir.sha256_bytes(payload),
            "snapshot_sha256": snapshot, "pages": len(doc["pages"]),
            "regions": regions, "review_only": True}


@ir.cli
def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(prog="revayat-comic review-docx", description=__doc__)
    parser.add_argument("--doc", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        report = export_document(args.doc, args.out)
    except (OSError, ValueError, RuntimeError) as error:
        ir.emit({"ok": False, "error": str(error)})
        return 1
    ir.emit(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
