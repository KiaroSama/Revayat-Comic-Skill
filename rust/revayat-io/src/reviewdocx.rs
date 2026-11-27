use std::{collections::HashSet, ffi::OsStr, fs, io::Write, path::Path};

use quick_xml::{
    Writer,
    events::{BytesDecl, BytesEnd, BytesStart, BytesText, Event},
};
use revayat_ir::{
    RegionRecord, ir,
    regions::{self, RegionState},
};
use serde::Serialize;
use serde_json::Value;
use unicode_bidi::{BidiClass, bidi_class};
use zip::{CompressionMethod, ZipWriter, write::SimpleFileOptions};

use crate::{
    IoError,
    fsutil::{atomic_file, canonical_destination, digest, parent, read_file},
    geometry::pdf_points,
    inputs::MAX_PAGES,
    invalid,
};

const W: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const CONTENT: &str = r#"<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>"#;
const ROOT_RELS: &str = r#"<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"#;
const DOC_RELS: &str = r#"<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>"#;

#[derive(Debug, Serialize)]
pub struct ReviewReport {
    pub path: std::path::PathBuf,
    pub pages: usize,
    pub regions: usize,
    pub snapshot_sha256: String,
}

pub(crate) fn valid_xml(text: &str) -> Result<(), IoError> {
    if text.chars().any(|c|!matches!(c,'\u{9}'|'\u{a}'|'\u{d}'|'\u{20}'..='\u{d7ff}'|'\u{e000}'..='\u{fffd}'|'\u{10000}'..='\u{10ffff}')){return Err(invalid("Text contains an invalid XML character"));}
    Ok(())
}

fn text(value: &Value) -> Result<&str, IoError> {
    if value.is_null() {
        return Ok("");
    }
    let text = value
        .as_str()
        .ok_or_else(|| invalid("Review fields must be text"))?;
    valid_xml(text)?;
    Ok(text)
}

fn start(
    xml: &mut Writer<Vec<u8>>,
    tag: &str,
    attrs: &[(&str, &str)],
    empty: bool,
) -> Result<(), IoError> {
    let mut node = BytesStart::new(tag);
    for attribute in attrs {
        node.push_attribute(*attribute);
    }
    Ok(xml.write_event(if empty {
        Event::Empty(node)
    } else {
        Event::Start(node)
    })?)
}

fn end(xml: &mut Writer<Vec<u8>>, tag: &str) -> Result<(), IoError> {
    Ok(xml.write_event(Event::End(BytesEnd::new(tag)))?)
}

fn declare() -> Result<Writer<Vec<u8>>, IoError> {
    let mut xml = Writer::new(Vec::new());
    xml.write_event(Event::Decl(BytesDecl::new("1.0", Some("UTF-8"), None)))?;
    Ok(xml)
}

fn rtl(c: char) -> Option<bool> {
    match bidi_class(c) {
        BidiClass::AL | BidiClass::R => Some(true),
        BidiClass::L | BidiClass::EN => Some(false),
        _ => None,
    }
}

struct Review {
    xml: Writer<Vec<u8>>,
    chars: usize,
    paras: usize,
    runs: usize,
    regions: usize,
    ids: HashSet<String>,
}

impl Review {
    fn paragraph(
        &mut self,
        value: &str,
        style: Option<&str>,
        direction: Option<bool>,
    ) -> Result<(), IoError> {
        valid_xml(value)?;
        self.chars = self.chars.saturating_add(value.chars().count());
        if self.chars > 2_000_000 {
            return Err(invalid("Review text exceeds 2,000,000 characters"));
        }
        let value = value.replace("\r\n", "\n").replace('\r', "\n");
        for line in value.split('\n') {
            self.paras += 1;
            if self.paras > 100_000 {
                return Err(invalid("Review document exceeds 100,000 paragraphs"));
            }
            let direction =
                direction.unwrap_or_else(|| line.chars().find_map(rtl).unwrap_or(false));
            start(&mut self.xml, "w:p", &[], false)?;
            start(&mut self.xml, "w:pPr", &[], false)?;
            if let Some(style) = style {
                start(&mut self.xml, "w:pStyle", &[("w:val", style)], true)?;
            }
            if direction {
                start(&mut self.xml, "w:bidi", &[], true)?;
            }
            start(&mut self.xml, "w:jc", &[("w:val", "start")], true)?;
            end(&mut self.xml, "w:pPr")?;
            let mut begin = 0;
            let mut is_rtl = direction;
            for (index, c) in line.char_indices() {
                if let Some(next) = rtl(c)
                    && next != is_rtl
                {
                    if begin < index {
                        self.run(&line[begin..index], is_rtl)?;
                    }
                    begin = index;
                    is_rtl = next;
                }
            }
            if !line.is_empty() {
                self.run(&line[begin..], is_rtl)?;
            }
            end(&mut self.xml, "w:p")?;
            if self.xml.get_ref().len() > 32 << 20 {
                return Err(invalid("Review document XML exceeds 32 MiB"));
            }
        }
        Ok(())
    }

    fn run(&mut self, text: &str, right_to_left: bool) -> Result<(), IoError> {
        self.runs += 1;
        if self.runs > 100_000 {
            return Err(invalid("Review document exceeds 100,000 text runs"));
        }
        start(&mut self.xml, "w:r", &[], false)?;
        start(&mut self.xml, "w:rPr", &[], false)?;
        start(
            &mut self.xml,
            "w:rFonts",
            &[
                ("w:ascii", "Vazir"),
                ("w:hAnsi", "Vazir"),
                ("w:cs", "Vazir"),
            ],
            true,
        )?;
        if right_to_left {
            start(&mut self.xml, "w:rtl", &[], true)?;
        }
        end(&mut self.xml, "w:rPr")?;
        start(&mut self.xml, "w:t", &[("xml:space", "preserve")], false)?;
        self.xml.write_event(Event::Text(BytesText::new(text)))?;
        end(&mut self.xml, "w:t")?;
        end(&mut self.xml, "w:r")
    }

    fn field(&mut self, label: &str, value: &str, persian: bool) -> Result<(), IoError> {
        if !value.is_empty() {
            self.paragraph(&format!("{label}:"), None, Some(false))?;
            self.paragraph(value, None, persian.then_some(true))?;
        }
        Ok(())
    }

    fn id<'a>(&mut self, value: &'a Value) -> Result<&'a str, IoError> {
        let value = text(value)?;
        if value.trim().is_empty() || !self.ids.insert(value.into()) {
            return Err(invalid("Page and region IDs must be nonempty and unique"));
        }
        Ok(value)
    }

    fn notes(&mut self, label: &str, values: &Value) -> Result<(), IoError> {
        if values.is_null() {
            return Ok(());
        }
        for item in values
            .as_array()
            .ok_or_else(|| invalid("Review notes must be lists"))?
        {
            if let Some(text) = item.as_str() {
                self.field(label, text, false)?;
            } else {
                self.field(label, &serde_json::to_string(item)?, false)?;
            }
        }
        Ok(())
    }

    fn page(&mut self, page: &Value, policy: &str) -> Result<(), IoError> {
        let id = self.id(&page["id"])?;
        let [width, height] = ["width", "height"].map(|key| page[key].as_u64().unwrap_or(0));
        if width == 0 || height == 0 {
            return Err(invalid("Page dimensions must be positive integers"));
        }
        if !page["sheets"].is_null()
            && !page["sheets"]
                .as_array()
                .is_some_and(|sheets| sheets.iter().all(Value::is_string))
        {
            return Err(invalid("Page crop sheets must be a list of paths"));
        }
        self.paragraph(&format!("Page {id}"), Some("Heading1"), Some(false))?;
        self.paragraph(
            &format!("Source dimensions: {width} x {height} pixels"),
            None,
            Some(false),
        )?;
        if page.get("pdf_points").is_some() {
            let [w, h] = pdf_points(page)?;
            self.paragraph(
                &format!("Source PDF dimensions: {w} x {h} points"),
                None,
                Some(false),
            )?;
        }
        self.notes("Page note", &page["notes"])?;
        let mut regions = page["regions"]
            .as_array()
            .ok_or_else(|| invalid("Page regions must be a list"))?
            .iter()
            .collect::<Vec<_>>();
        self.regions += regions.len();
        if self.regions > 20_000 {
            return Err(invalid("Review document exceeds 20,000 regions"));
        }
        if regions.is_empty() {
            self.paragraph("No regions recorded.", None, Some(false))?;
        }
        for region in &regions {
            if !region["reading_order"].is_null() && region["reading_order"].as_u64().is_none() {
                return Err(invalid(
                    "Region reading order must be a nonnegative integer",
                ));
            }
        }
        regions.sort_by_key(|r| r["reading_order"].as_u64().unwrap_or_default());
        for region in regions {
            self.region(region, policy)?;
        }
        Ok(())
    }

    fn region(&mut self, region: &Value, policy: &str) -> Result<(), IoError> {
        let id = self.id(&region["id"])?;
        let kind = region["kind"]
            .as_str()
            .filter(|s| ir::REGION_KINDS.contains(s))
            .ok_or_else(|| invalid("Invalid review region kind"))?;
        for key in ["dropped", "erase", "keep", "locked"] {
            if region.get(key).is_some() && !region[key].is_boolean() {
                return Err(invalid("Region flags must be boolean"));
            }
        }
        if region.get("typeset").is_some() && !region["typeset"].is_object() {
            return Err(invalid("Region typesetting state must be an object"));
        }
        text(&region["typeset"]["status"])?;
        text(&region["fill"])?;
        let record = decision_record(region)?;
        self.paragraph(&format!("Region {id}"), Some("Heading2"), Some(false))?;
        self.paragraph(
            &format!("Kind: {kind}; state: {}", state(&record, region, policy)?),
            None,
            Some(false),
        )?;
        self.field("Speaker", text(&region["speaker"])?, false)?;
        self.field("Source", &record.source_text, false)?;
        let target = &record.target_text;
        self.field("Displayed Persian", target, true)?;
        if target.is_empty() {
            self.paragraph("No displayed Persian recorded.", None, Some(false))?;
        }
        self.field("Full Persian", text(&region["target_full"])?, true)?;
        for (label, key) in [
            ("Review note", "review"),
            ("Processing note", "audit"),
            ("Recorded review code", "review_ack"),
        ] {
            self.notes(label, &region[key])?;
        }
        for key in ["review_ack_compression", "review_ack_history"] {
            if !region[key].is_null() {
                self.field(
                    &format!("Recorded review decision: {key}"),
                    &serde_json::to_string(&region[key])?,
                    false,
                )?;
            }
        }
        Ok(())
    }
}

fn decision_record(region: &Value) -> Result<RegionRecord, IoError> {
    // A review snapshot can omit geometry and carry free-form notes. Decode its
    // decision and text fields through the same aliases as a full IR record.
    let mut fields = region
        .as_object()
        .cloned()
        .ok_or_else(|| invalid("Review regions must be objects"))?;
    fields.retain(|key, _| {
        matches!(
            key.as_str(),
            "id" | "kind"
                | "state"
                | "dropped"
                | "keep"
                | "erase"
                | "fill"
                | "typeset"
                | "source_text"
                | "ocr_text"
                | "target_text"
                | "fa_text"
        )
    });
    for (canonical, alias, legacy) in [
        ("source_text", "ocr_text", "source"),
        ("target_text", "fa_text", "target"),
    ] {
        if !fields.contains_key(canonical)
            && !fields.contains_key(alias)
            && let Some(value) = region.get(legacy)
        {
            fields.insert(canonical.into(), value.clone());
        }
    }
    for key in ["source_text", "ocr_text", "target_text", "fa_text", "fill"] {
        if fields.get(key).is_some_and(Value::is_null) {
            fields.remove(key);
        }
    }
    Ok(serde_json::from_value(Value::Object(fields))?)
}

fn state(record: &RegionRecord, raw: &Value, policy: &str) -> Result<&'static str, IoError> {
    Ok(match regions::region_state(record, policy)? {
        RegionState::Dropped => "dropped_false_detection",
        RegionState::Kept => "kept_by_policy",
        RegionState::Erased => "erased",
        RegionState::Translated => "translated",
        RegionState::Pending => {
            if record.erase
                || record.state == Some(RegionState::Erased)
                || matches!(
                    record.typeset.get("status").and_then(Value::as_str),
                    Some("overflow" | "unreliable")
                )
                || ["review", "audit"]
                    .into_iter()
                    .any(|key| raw[key].as_array().is_some_and(|items| !items.is_empty()))
            {
                "needs_review"
            } else {
                "unresolved"
            }
        }
    })
}

fn styles() -> Result<Vec<u8>, IoError> {
    let mut xml = declare()?;
    start(&mut xml, "w:styles", &[("xmlns:w", W)], false)?;
    for (name, size, level) in [
        ("Normal", "22", None),
        ("Heading1", "30", Some("0")),
        ("Heading2", "26", Some("1")),
    ] {
        start(
            &mut xml,
            "w:style",
            &[("w:type", "paragraph"), ("w:styleId", name)],
            false,
        )?;
        start(&mut xml, "w:name", &[("w:val", name)], true)?;
        if level.is_some() {
            start(&mut xml, "w:basedOn", &[("w:val", "Normal")], true)?;
        }
        start(&mut xml, "w:pPr", &[], false)?;
        if let Some(level) = level {
            start(&mut xml, "w:keepNext", &[], true)?;
            start(&mut xml, "w:outlineLvl", &[("w:val", level)], true)?;
        }
        end(&mut xml, "w:pPr")?;
        start(&mut xml, "w:rPr", &[], false)?;
        start(
            &mut xml,
            "w:rFonts",
            &[
                ("w:ascii", "Vazir"),
                ("w:hAnsi", "Vazir"),
                ("w:cs", "Vazir"),
            ],
            true,
        )?;
        if level.is_some() {
            start(&mut xml, "w:b", &[], true)?;
            start(&mut xml, "w:bCs", &[], true)?;
        }
        start(&mut xml, "w:sz", &[("w:val", size)], true)?;
        start(&mut xml, "w:szCs", &[("w:val", size)], true)?;
        end(&mut xml, "w:rPr")?;
        end(&mut xml, "w:style")?;
    }
    end(&mut xml, "w:styles")?;
    Ok(xml.into_inner())
}

fn export_snapshot(doc: &Value, out: &Path, snapshot: String) -> Result<ReviewReport, IoError> {
    if !out
        .extension()
        .and_then(OsStr::to_str)
        .is_some_and(|e| e.eq_ignore_ascii_case("docx"))
    {
        return Err(invalid("Review destination must have the .docx extension"));
    }
    if out
        .symlink_metadata()
        .is_ok_and(|md| md.file_type().is_symlink())
    {
        return Err(invalid("Refusing to replace a review symlink"));
    }
    let meta = &doc["meta"];
    let pages = doc["pages"]
        .as_array()
        .ok_or_else(|| invalid("Review needs a page list"))?;
    if !meta.is_object()
        || (!doc["source"].is_null() && !doc["source"].is_object())
        || pages.len() > MAX_PAGES
    {
        return Err(invalid("Invalid review metadata or too many pages"));
    }
    let policy = meta["sfx_policy"].as_str().unwrap_or("keep");
    if !matches!(policy, "keep" | "translate" | "bilingual" | "annotate") {
        return Err(invalid("Invalid sound-effects policy"));
    }
    let mut review = Review {
        xml: declare()?,
        chars: 0,
        paras: 0,
        runs: 0,
        regions: 0,
        ids: HashSet::new(),
    };
    start(&mut review.xml, "w:document", &[("xmlns:w", W)], false)?;
    start(&mut review.xml, "w:body", &[], false)?;
    review.paragraph(
        "Translation review companion",
        Some("Heading1"),
        Some(false),
    )?;
    review.paragraph("Editable snapshot, not a certified primary comic. Apply corrections through stable-ID worksheets.",None,Some(false))?;
    for (label, key) in [
        ("Title", "title"),
        ("Chapter", "chapter"),
        ("Source language", "source_language"),
        ("Target language", "target_language"),
    ] {
        review.field(label, text(&meta[key])?, false)?;
    }
    let source = text(&doc["source"]["path"])?;
    review.field(
        "Source container",
        source.rsplit(['/', '\\']).next().unwrap_or_default(),
        false,
    )?;
    review.field("Snapshot SHA-256", &snapshot, false)?;
    for page in pages {
        review.page(page, policy)?;
    }
    start(&mut review.xml, "w:sectPr", &[], false)?;
    start(
        &mut review.xml,
        "w:pgSz",
        &[("w:w", "11906"), ("w:h", "16838")],
        true,
    )?;
    start(
        &mut review.xml,
        "w:pgMar",
        &[
            ("w:top", "1440"),
            ("w:right", "1440"),
            ("w:bottom", "1440"),
            ("w:left", "1440"),
            ("w:header", "720"),
            ("w:footer", "720"),
            ("w:gutter", "0"),
        ],
        true,
    )?;
    end(&mut review.xml, "w:sectPr")?;
    end(&mut review.xml, "w:body")?;
    end(&mut review.xml, "w:document")?;
    let styles = styles()?;
    atomic_file(out, |file| {
        let mut zip = ZipWriter::new(file);
        let entry = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
        for (name, data) in [
            ("[Content_Types].xml", CONTENT.as_bytes()),
            ("_rels/.rels", ROOT_RELS.as_bytes()),
            ("word/_rels/document.xml.rels", DOC_RELS.as_bytes()),
            ("word/styles.xml", styles.as_slice()),
            ("word/document.xml", review.xml.get_ref().as_slice()),
        ] {
            zip.start_file(name, entry)?;
            zip.write_all(data)?;
        }
        zip.finish()?;
        Ok(())
    })?;
    Ok(ReviewReport {
        path: out.to_path_buf(),
        pages: pages.len(),
        regions: review.regions,
        snapshot_sha256: snapshot,
    })
}

pub fn export_review_docx(doc: &Value, out: &Path) -> Result<ReviewReport, IoError> {
    let target = canonical_destination(out)?;
    if let Some(source) = doc["source"]["path"].as_str()
        && let Ok(source) = canonical_destination(Path::new(source))
        && (target == source || (source.is_dir() && target.starts_with(source)))
    {
        return Err(invalid("Review export overlaps the source"));
    }
    export_snapshot(doc, out, digest(&serde_json::to_vec(doc)?))
}

pub fn export_review_document(doc_path: &Path, out: &Path) -> Result<ReviewReport, IoError> {
    let root = fs::canonicalize(parent(doc_path))?;
    let target = canonical_destination(out)?;
    if target == fs::canonicalize(doc_path)?
        || [
            "pages",
            "crops",
            "sheets",
            "masks",
            "clean",
            "final",
            "worksheets",
        ]
        .into_iter()
        .any(|part| target.starts_with(root.join(part)))
    {
        return Err(invalid("Review export overlaps workspace assets"));
    }
    let payload = read_file(doc_path, 64 << 20)?;
    let doc: Value = serde_json::from_slice(&payload)?;
    if doc["version"].as_u64() != Some(1) {
        return Err(invalid("Unsupported chapter schema"));
    }
    if let Some(source) = doc["source"]["path"].as_str()
        && let Ok(source) = canonical_destination(Path::new(source))
        && (target == source || (source.is_dir() && target.starts_with(source)))
    {
        return Err(invalid("Review export overlaps the source"));
    }
    export_snapshot(&doc, out, digest(&payload))
}
