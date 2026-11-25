use crate::{IrError, RegionRecord, ir};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::LazyLock;

const ACTIONS: [&str; 3] = ["drop", "keep", "erase"];
const STYLES: [&str; 6] = [
    "bold",
    "italic",
    "bold-italic",
    "outline",
    "shadow",
    "shout",
];
static HEADER: LazyLock<Regex> =
    LazyLock::new(|| crate::matcher(r"^@@\s+(\+?[A-Za-z0-9_#-]+)(?:\s+(.*))?$"));
static FIELD: LazyLock<Regex> = LazyLock::new(|| {
    crate::matcher(
        r"^(src|fa_full|fa|kind|speaker|propose|note|drop|keep|erase|box|polarity|reviewed|style)\s*:\s?(.*)$",
    )
});
static BOX: LazyLock<Regex> =
    LazyLock::new(|| crate::matcher(r"^\s*([0-9]+)[ ,]+([0-9]+)[ ,]+([0-9]+)[ ,]+([0-9]+)\s*$"));

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Block {
    pub id: String,
    pub kind: Option<String>,
    pub orientation: Option<String>,
    pub fields: BTreeMap<String, String>,
    pub notes: Vec<String>,
}
impl Block {
    pub fn value(&self, field: &str) -> Option<&str> {
        self.fields.get(field).map(String::as_str)
    }
    pub fn affirmative(&self, field: &str) -> bool {
        self.value(field)
            .is_some_and(|s| matches!(s.trim().to_ascii_lowercase().as_str(), "yes" | "true" | "1"))
    }
    pub(crate) fn geometry(&self) -> Result<Option<ir::BBox>, IrError> {
        let Some(value) = self.value("box").filter(|s| !s.trim().is_empty()) else {
            return Ok(None);
        };
        let invalid = || {
            IrError::refused(
                if self.id.starts_with('+') {
                    "bad_added_regions"
                } else {
                    "invalid_fields"
                },
                format!(
                    "{}: box requires four nonnegative integer coordinates",
                    self.id
                ),
            )
        };
        let found = BOX.captures(value).ok_or_else(invalid)?;
        let mut result = [0; 4];
        for (i, v) in result.iter_mut().enumerate() {
            *v = found[i + 1].parse().map_err(|_| invalid())?;
        }
        Ok(Some(result))
    }
}
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Reply {
    pub fingerprint: Option<String>,
    pub scheme: Option<String>,
    pub blocks: Vec<Block>,
}

fn comment(raw: &str) -> bool {
    raw == "#" || raw.starts_with("# ") || raw.starts_with("#\t")
}
fn unescape(line: &str) -> &str {
    if let Some(rest) = line.strip_prefix('\\')
        && (rest.starts_with('\\')
            || rest.starts_with('#')
            || rest.starts_with("@@")
            || FIELD.is_match(rest))
    {
        return rest;
    }
    line
}
fn escaped(line: &str) -> String {
    if line.starts_with('\\') || comment(line) || HEADER.is_match(line) || FIELD.is_match(line) {
        format!("\\{line}")
    } else {
        line.into()
    }
}
pub fn field_lines(name: &str, value: &str) -> String {
    if value.is_empty() {
        return format!("{name}:\n");
    }
    let mut lines = value.split('\n');
    let mut text = format!("{name}: {}\n", escaped(lines.next().unwrap_or_default()));
    for line in lines {
        text.push_str(&escaped(line));
        text.push('\n');
    }
    text
}
fn normalize_style(style: &str) -> Result<String, IrError> {
    let mut values: BTreeSet<_> = style
        .split(',')
        .map(|s| s.trim().to_ascii_lowercase())
        .filter(|s| !s.is_empty())
        .collect();
    if values.iter().any(|s| !STYLES.contains(&s.as_str())) {
        return Err(IrError::refused(
            "invalid_fields",
            "unknown lettering style",
        ));
    }
    if values.contains("bold-italic") || values.contains("bold") && values.contains("italic") {
        values.remove("bold");
        values.remove("italic");
        values.insert("bold-italic".into());
    }
    Ok(STYLES
        .into_iter()
        .filter(|s| values.contains(*s))
        .collect::<Vec<_>>()
        .join(", "))
}
pub fn parse_worksheet(text: &str) -> Result<Reply, IrError> {
    let mut reply = Reply::default();
    let mut ids = BTreeSet::new();
    let mut field: Option<String> = None;
    let mut blanks = 0usize;
    for raw in text.replace("\r\n", "\n").split(['\r', '\n']) {
        if comment(raw) {
            if let Some(value) = raw
                .strip_prefix('#')
                .map(str::trim)
                .and_then(|t| t.strip_prefix("fingerprint:"))
            {
                reply.fingerprint = Some(value.trim().into());
            }
            if let Some(value) = raw
                .strip_prefix('#')
                .map(str::trim)
                .and_then(|t| t.strip_prefix("scheme:"))
            {
                reply.scheme = Some(value.trim().into());
            }
            continue;
        }
        if let Some(header) = HEADER.captures(raw) {
            let id = header[1].to_owned();
            if !ids.insert(id.clone()) {
                return Err(IrError::refused("duplicate_regions", id));
            }
            let mut attributes = header.get(2).map_or("", |m| m.as_str()).split_whitespace();
            let kind = attributes.next().map(str::to_ascii_lowercase);
            let orientation = attributes.next().map(str::to_ascii_lowercase);
            if attributes.next().is_some() {
                return Err(IrError::refused(
                    "invalid_fields",
                    format!("{id}: too many worksheet header fields"),
                ));
            }
            reply.blocks.push(Block {
                id,
                kind,
                orientation,
                ..Block::default()
            });
            field = None;
            continue;
        }
        let Some(block) = reply.blocks.last_mut() else {
            continue;
        };
        if let Some(found) = FIELD.captures(raw) {
            let name = found[1].to_owned();
            let value = unescape(found[2].trim()).to_owned();
            if name == "note" {
                block.notes.push(value);
            } else if block.fields.insert(name.clone(), value).is_some() {
                return Err(IrError::refused(
                    "duplicate_fields",
                    format!("{}: {name}", block.id),
                ));
            }
            field = Some(name);
            blanks = 0;
        } else if let Some(name) = &field {
            let tail = raw.trim();
            if tail.is_empty() {
                blanks += 1;
                continue;
            }
            let target = if name == "note" {
                block.notes.last_mut()
            } else {
                block.fields.get_mut(name)
            };
            if let Some(value) = target {
                if !value.is_empty() {
                    value.extend(std::iter::repeat_n('\n', blanks + 1));
                }
                value.push_str(unescape(tail));
            }
            blanks = 0;
        }
    }
    for block in &mut reply.blocks {
        if let Some(style) = block.fields.get_mut("style")
            && let Ok(normalized) = normalize_style(style)
        {
            *style = normalized;
        }
    }
    Ok(reply)
}

pub fn validate(block: &Block) -> Result<(), IrError> {
    if let Some(kind) = block.kind.as_deref()
        && !ir::REGION_KINDS.contains(&kind)
    {
        return Err(IrError::refused(
            "invalid_fields",
            format!("{}: invalid header kind", block.id),
        ));
    }
    if let Some(o) = block.orientation.as_deref()
        && !ir::ORIENTATIONS.contains(&o)
    {
        return Err(IrError::refused(
            "invalid_fields",
            format!("{}: invalid header orientation", block.id),
        ));
    }
    if let Some(kind) = block.value("kind").filter(|s| !s.is_empty())
        && !ir::REGION_KINDS.contains(&kind)
    {
        return Err(IrError::refused(
            "bad_kind",
            format!("{}: {kind}", block.id),
        ));
    }
    if ACTIONS
        .into_iter()
        .filter(|name| block.affirmative(name))
        .count()
        > 1
    {
        return Err(IrError::refused("conflicting_actions", &block.id));
    }
    for name in ACTIONS.into_iter().chain(["reviewed"]) {
        if block.value(name).is_some_and(|s| {
            !matches!(
                s.trim().to_ascii_lowercase().as_str(),
                "" | "yes" | "true" | "1" | "no" | "false" | "0"
            )
        }) {
            return Err(IrError::refused(
                "invalid_fields",
                format!("{}: {name} requires a boolean", block.id),
            ));
        }
    }
    if block.value("polarity").is_some_and(|s| {
        !matches!(
            s.trim().to_ascii_lowercase().as_str(),
            "" | "dark" | "light"
        )
    }) {
        return Err(IrError::refused(
            "invalid_fields",
            format!("{}: unknown polarity", block.id),
        ));
    }
    normalize_style(block.value("style").unwrap_or_default())?;
    block.geometry()?;
    Ok(())
}

pub fn apply(
    region: &mut RegionRecord,
    block: &Block,
    width: u32,
    height: u32,
) -> Result<(), IrError> {
    validate(block)?;
    if let Some(bbox) = block.geometry()? {
        let clipped = ir::clamp_bbox(bbox, width, height);
        if bbox != clipped || bbox[2] == 0 || bbox[3] == 0 {
            return Err(IrError::refused(
                if block.id.starts_with('+') {
                    "bad_added_regions"
                } else {
                    "invalid_fields"
                },
                format!("{}: box lies outside the page", block.id),
            ));
        }
        if bbox != region.bbox {
            region.bbox = bbox;
            region.mask = None;
            region.polygon.clear();
            region.typeset.clear();
            region.extra.remove("balloon");
            region.extra.remove("mask_box");
        }
    }
    if let Some(kind) = block.value("kind").filter(|s| !s.is_empty()) {
        region.kind = kind.into();
    }
    if let Some(src) = block.value("src") {
        region.source_text = src.into();
    }
    if let Some(fa) = block.value("fa") {
        if fa != region.target_text {
            region.typeset.clear();
        }
        region.target_text = fa.into();
    }
    if let Some(speaker) = block.value("speaker") {
        region.speaker = (!speaker.is_empty()).then(|| speaker.to_owned());
    }
    for (key, field) in [
        ("target_full", "fa_full"),
        ("style", "style"),
        ("polarity", "polarity"),
        ("proposed", "propose"),
    ] {
        if let Some(value) = block.value(field) {
            if value.is_empty() {
                region.extra.remove(key);
            } else if field == "propose" {
                region.extra.insert(
                    key.into(),
                    json!(
                        value
                            .split([',', '،'])
                            .map(str::trim)
                            .filter(|s| !s.is_empty())
                            .collect::<Vec<_>>()
                    ),
                );
            } else {
                region.extra.insert(key.into(), json!(value));
            }
        }
    }
    if block.value("reviewed").is_some() {
        region
            .extra
            .insert("reviewed".into(), json!(block.affirmative("reviewed")));
    }
    if !block.notes.is_empty() {
        region.review.clone_from(&block.notes);
    }
    region.dropped = block.affirmative("drop");
    region.keep = block.affirmative("keep");
    region.erase = block.affirmative("erase");
    region.state = None;
    if region.dropped || region.keep || region.erase {
        region.target_text.clear();
        region.typeset.clear();
        region.extra.remove("target_full");
        region.fill = if region.keep { "keep" } else { "none" }.into();
    }
    region.locked = region.dropped
        || region.keep
        || region.erase
        || !region.source_text.trim().is_empty()
        || !region.target_text.trim().is_empty();
    Ok(())
}

pub fn reply_digest(reply: &Reply) -> Result<String, IrError> {
    let payload: ir::Fields = reply
        .blocks
        .iter()
        .map(|block| {
            let mut fields: ir::Fields = block
                .fields
                .iter()
                .map(|(key, val)| (key.clone(), json!(val)))
                .collect();
            fields.insert("_seen".into(), json!(1));
            if let Some(value) = &block.kind {
                fields.insert("_kind".into(), json!(value));
            }
            if let Some(value) = &block.orientation {
                fields.insert("_orientation".into(), json!(value));
            }
            if !block.notes.is_empty() {
                fields.insert("note".into(), json!(block.notes));
            }
            (block.id.clone(), Value::Object(fields))
        })
        .collect();
    let normalized = format!("3{}", crate::stages::sorted_json(&Value::Object(payload))?);
    Ok(ir::sha256_bytes(normalized.as_bytes())[..16].to_owned())
}
