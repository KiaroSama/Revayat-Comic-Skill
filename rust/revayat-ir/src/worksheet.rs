pub use crate::replies::{Block, Reply, parse_worksheet as parse};
use crate::replies::{apply, field_lines, reply_digest};
use crate::worksheet_paths::worksheet_folder;
use crate::{
    ComicDocument, IrError, PageRecord, RegionRecord, ir, regions, review, stages, workspace,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

pub const STAMP_SCHEME: &str = "2";

fn content_fingerprint(page: &PageRecord) -> String {
    let regions: Vec<_> = page
        .regions
        .iter()
        .map(|region| {
            json!({
                "id": region.id,
                "source": region.source_text,
                "source_revision": region.extra.get("source_revision"),
                "shown": region.target_text,
                "full": region.extra.get("target_full"),
                "speaker": region.speaker,
                "style": region.extra.get("style"),
                "polarity": region.extra.get("polarity"),
                "proposed": region.extra.get("proposed"),
                "actions": regions::actions(region),
                "notes": region.review,
                "review_ack": region.extra.get("review_ack"),
                "review_ack_text": region.extra.get("review_ack_text"),
                "review_ack_compression": region.extra.get("review_ack_compression"),
                "review_ack_spans": region.extra.get("review_ack_spans"),
            })
        })
        .collect();
    let mut content = json!({
        "geometry": ir::page_fingerprint(page),
        "size": [page.width, page.height],
        "regions": regions,
    });
    // Derived masks and lettering evidence do not change the worksheet content.
    content.sort_all_objects();
    ir::sha256_bytes(content.to_string().as_bytes())
}

pub fn page_worksheet(doc: &ComicDocument, page: &PageRecord) -> String {
    let title = doc
        .meta
        .get("title")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .unwrap_or("comic");
    let mut text = format!(
        "# {title} | page {} ({} of {})\n# fingerprint: {}\n# content-fingerprint: {}\n# scheme: {STAMP_SCHEME}\n# Add Persian after fa: and keep the region IDs.\n",
        page.id,
        page.index.saturating_add(1),
        doc.pages.len(),
        ir::page_fingerprint(page),
        content_fingerprint(page),
        title = title.replace(['\r', '\n', '\u{85}', '\u{2028}', '\u{2029}'], " ")
    );
    let header = |text: &mut String, key: &str, value: &str| {
        let _ = writeln!(
            text,
            "# {key}: {}",
            value.replace(['\r', '\n', '\u{85}', '\u{2028}', '\u{2029}'], " ")
        );
    };
    if let Some(path) = page.extra.get("overview").and_then(Value::as_str) {
        header(&mut text, "overview", path);
    }
    if let Some(sheets) = page.extra.get("sheets").and_then(Value::as_array) {
        let paths = sheets.iter().filter_map(Value::as_str).collect::<Vec<_>>();
        header(&mut text, "sheets", &paths.join(", "));
    }
    if let Some(scale) = page.extra.get("overview_scale").and_then(Value::as_f64) {
        header(&mut text, "scale", &scale.to_string());
    }
    header(
        &mut text,
        "source_language",
        doc.meta
            .get("source_language")
            .and_then(Value::as_str)
            .unwrap_or("auto"),
    );
    header(
        &mut text,
        "reading_direction",
        doc.meta
            .get("reading_direction")
            .and_then(Value::as_str)
            .unwrap_or("rtl"),
    );
    header(&mut text, "sfx_policy", doc.policy());
    if let Some(entries) = doc.glossary.get("entries").and_then(Value::as_object) {
        for (source, entry) in entries
            .iter()
            .filter(|(_, entry)| entry["locked"] == true)
            .take(40)
        {
            if let Some(target) = entry["target"].as_str() {
                let _ = writeln!(
                    text,
                    "# glossary: {} = {}",
                    source.replace(['\r', '\n'], " "),
                    target.replace(['\r', '\n'], " ")
                );
            }
        }
    }
    for region in &page.regions {
        let _ = writeln!(
            text,
            "\n@@ {} {} {}",
            region.id, region.kind, region.orientation
        );
        text.push_str(&field_lines("src", &region.source_text));
        text.push_str(&field_lines("fa", &region.target_text));
        for (field, value) in [
            (
                "fa_full",
                region.extra.get("target_full").and_then(Value::as_str),
            ),
            ("speaker", region.speaker.as_deref()),
            ("style", region.extra.get("style").and_then(Value::as_str)),
            (
                "polarity",
                region.extra.get("polarity").and_then(Value::as_str),
            ),
        ] {
            if let Some(value) = value.filter(|s| !s.is_empty()) {
                text.push_str(&field_lines(field, value));
            }
        }
        let [dropped, kept, erased] = regions::actions(region);
        for (enabled, field) in [(kept, "keep"), (erased, "erase"), (dropped, "drop")] {
            if enabled {
                text.push_str(&field_lines(field, "yes"));
            }
        }
        for note in &region.review {
            text.push_str(&field_lines("note", note));
        }
        let carried = review::carried_acknowledgements(region);
        if !carried.is_empty() {
            text.push_str(&field_lines("reviewed", &carried.join(", ")));
        }
    }
    text
}

fn addresses(reply: &Reply, page: &PageRecord) -> Result<(), IrError> {
    let mut addressed = BTreeSet::new();
    for block in &reply.blocks {
        let id = if let Some(slug) = block.id.strip_prefix('+') {
            let Some(region) = page
                .regions
                .iter()
                .find(|r| r.extra.get("added_as").and_then(Value::as_str) == Some(slug))
            else {
                continue;
            };
            &region.id
        } else {
            &block.id
        };
        if !addressed.insert(id.as_str()) {
            return Err(IrError::refused("duplicate_regions", id));
        }
    }
    let expected: BTreeSet<_> = page.regions.iter().map(|r| r.id.as_str()).collect();
    if let Some(id) = addressed.difference(&expected).next() {
        return Err(IrError::refused("unknown_regions", *id));
    }
    if let Some(id) = expected.difference(&addressed).next() {
        return Err(IrError::refused("missing_regions", *id));
    }
    Ok(())
}
fn check_stamp(
    reply: &Reply,
    page: &PageRecord,
    document_stamp: Option<&str>,
) -> Result<(), IrError> {
    let Some(stamp) = &reply.fingerprint else {
        return Err(IrError::refused(
            "stale-worksheets",
            format!("{}: missing fingerprint", page.id),
        ));
    };
    if (stamp == &ir::page_fingerprint(page) || document_stamp == Some(stamp))
        && reply
            .content_fingerprint
            .as_deref()
            .is_none_or(|content| content == content_fingerprint(page))
    {
        return Ok(());
    }
    Err(IrError::refused(
        "stale-worksheets",
        format!(
            "{}: worksheet fingerprint no longer matches the page content or geometry",
            page.id
        ),
    ))
}

pub fn merge_page(page: &mut PageRecord, reply: &Reply) -> Result<(), IrError> {
    merge(page, reply, "keep", "rtl", None, false)
}
fn merge(
    page: &mut PageRecord,
    reply: &Reply,
    policy: &str,
    direction: &str,
    document_stamp: Option<&str>,
    force: bool,
) -> Result<(), IrError> {
    if !force {
        check_stamp(reply, page, document_stamp)?;
    }
    addresses(reply, page)?;
    let mut revised = page.clone();
    let mut ordinal = page
        .regions
        .iter()
        .filter_map(|r| r.id.strip_prefix(&page.id))
        .filter_map(|s| s.trim_start_matches('_').strip_prefix('r'))
        .filter_map(|s| s.parse::<usize>().ok())
        .max()
        .unwrap_or(0);
    for block in &reply.blocks {
        let region = if let Some(slug) = block.id.strip_prefix('+') {
            if let Some(index) = revised
                .regions
                .iter()
                .position(|r| r.extra.get("added_as").and_then(Value::as_str) == Some(slug))
            {
                &mut revised.regions[index]
            } else {
                if block.geometry()?.is_none() {
                    return Err(IrError::refused(
                        "bad_added_regions",
                        format!("{}: missing box", block.id),
                    ));
                }
                ordinal = ordinal
                    .checked_add(1)
                    .ok_or_else(|| IrError::refused("bad_added_regions", "region IDs exhausted"))?;
                let mut region = RegionRecord {
                    id: ir::region_id_for(&page.id, ordinal),
                    kind: block.kind.as_deref().unwrap_or("unknown").into(),
                    orientation: block.orientation.as_deref().unwrap_or("horizontal").into(),
                    detector: "worksheet".into(),
                    reading_order: revised
                        .regions
                        .iter()
                        .map(|r| r.reading_order)
                        .max()
                        .unwrap_or(0)
                        .saturating_add(1),
                    ..RegionRecord::default()
                };
                region.extra.insert("added_as".into(), json!(slug));
                revised.regions.push(region);
                revised
                    .regions
                    .last_mut()
                    .ok_or_else(|| IrError::refused("bad_added_regions", slug))?
            }
        } else {
            revised
                .regions
                .iter_mut()
                .find(|r| r.id == block.id)
                .ok_or_else(|| IrError::refused("unknown_regions", &block.id))?
        };
        apply(region, block, page.width, page.height)?;
        if regions::translatable(region, policy) && region.target_text.trim().is_empty() {
            return Err(IrError::refused("empty_translation", &region.id));
        }
    }
    if revised.regions.len() != page.regions.len()
        || revised
            .regions
            .iter()
            .zip(&page.regions)
            .any(|(new, old)| new.bbox != old.bbox)
    {
        ir::assign_reading_order(&mut revised, direction, 0.35)?;
    }
    revised
        .extra
        .insert("worksheet_digest".into(), json!(reply_digest(reply)?));
    revised.extra.insert("worksheet_clean".into(), json!(true));
    revised.extra.insert(
        "worksheet_content".into(),
        json!(content_fingerprint(&revised)),
    );
    *page = revised;
    Ok(())
}

fn reply_path(folder: &Path, id: &str, suffix: &str) -> Result<PathBuf, IrError> {
    if !id.starts_with('p') || id.len() < 2 || !id.as_bytes()[1..].iter().all(u8::is_ascii_digit) {
        return Err(IrError::refused("invalid_page_id", id));
    }
    Ok(folder.join(format!("{id}.{suffix}")))
}
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorksheetStatus {
    pub pending: Vec<String>,
    pub completed: Vec<String>,
    pub merged: Vec<String>,
    pub stale: Vec<String>,
}
fn already_applied(page: &PageRecord, reply: &Reply, digest: &str) -> bool {
    page.extra.get("worksheet_digest").and_then(Value::as_str) == Some(digest)
        && page.extra.get("worksheet_clean") == Some(&json!(true))
        && page
            .extra
            .get("worksheet_content")
            .and_then(Value::as_str)
            .map_or_else(
                || reply.content_fingerprint.is_none(),
                |content| content == content_fingerprint(page),
            )
}

pub fn status(doc_path: &Path, worksheets: Option<&Path>) -> Result<WorksheetStatus, IrError> {
    let doc = ir::load_doc(doc_path)?;
    let folder = worksheet_folder(doc_path, &doc, worksheets);
    let mut result = WorksheetStatus::default();
    let stamp = ir::fingerprint(&doc);
    for page in &doc.pages {
        let path = reply_path(&folder, &page.id, "done.txt")?;
        if !path.is_file() {
            result.pending.push(page.id.clone());
            continue;
        }
        let reply = parse(&fs::read_to_string(path)?)?;
        if check_stamp(&reply, page, Some(&stamp)).is_err() {
            result.stale.push(page.id.clone());
        } else if already_applied(page, &reply, &reply_digest(&reply)?) {
            result.merged.push(page.id.clone());
        } else {
            result.completed.push(page.id.clone());
        }
    }
    Ok(result)
}
pub fn build_document(
    doc_path: &Path,
    worksheets: Option<&Path>,
    pages: Option<&[String]>,
    force: bool,
) -> Result<Vec<PathBuf>, IrError> {
    let claim = workspace::workspace_lock(ir::doc_dir(doc_path), "worksheet")?;
    let mut loaded = workspace::LoadedDocument::open(doc_path)?;
    let doc = &loaded.document;
    let folder = worksheet_folder(doc_path, doc, worksheets);
    let selected = workspace::selected_pages(doc, pages)?;
    let stamp = ir::fingerprint(doc);
    let mut drafts = Vec::new();
    for page in selected {
        let done = reply_path(&folder, &page.id, "done.txt")?;
        if done.exists() && !force {
            check_stamp(&parse(&fs::read_to_string(done)?)?, page, Some(&stamp))?;
        }
        drafts.push((
            reply_path(&folder, &page.id, "txt")?,
            page_worksheet(doc, page),
        ));
    }
    let result = drafts.iter().map(|(path, _)| path.clone()).collect();
    for (path, text) in drafts {
        if fs::read_to_string(&path).ok().as_deref() != Some(&text) {
            ir::write_text(path, &text)?;
        }
    }
    if worksheets.is_some() && pages.is_none_or(|selection| !selection.is_empty()) {
        let recorded = json!(std::path::absolute(&folder)?);
        if loaded.document.meta.get("worksheets") != Some(&recorded) {
            loaded.document.meta.insert("worksheets".into(), recorded);
            loaded.save_claimed(&claim)?;
        }
    }
    Ok(result)
}
pub fn merge_document(
    doc_path: &Path,
    worksheets: Option<&Path>,
    selection: Option<&[String]>,
    force: bool,
) -> Result<Vec<String>, IrError> {
    let claim = workspace::workspace_lock(ir::doc_dir(doc_path), "merge")?;
    let mut loaded = workspace::LoadedDocument::open(doc_path)?;
    let doc = &mut loaded.document;
    let selected: BTreeSet<_> = workspace::selected_pages(doc, selection)?
        .into_iter()
        .map(|p| p.id.clone())
        .collect();
    let folder = worksheet_folder(doc_path, doc, worksheets);
    let policy = doc.policy().to_owned();
    let source_lang = doc
        .meta
        .get("source_language")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let direction = doc
        .meta
        .get("reading_direction")
        .and_then(Value::as_str)
        .unwrap_or("rtl")
        .to_owned();
    let stamp = ir::fingerprint(doc);
    let mut receipts = Vec::new();
    for page in &mut doc.pages {
        if !selected.contains(&page.id) {
            continue;
        }
        let path = reply_path(&folder, &page.id, "done.txt")?;
        if !path.is_file() {
            return Err(IrError::refused(
                "missing_outputs",
                path.display().to_string(),
            ));
        }
        let raw = fs::read_to_string(&path)?;
        let reply = parse(&raw)?;
        addresses(&reply, page)?;
        for block in &reply.blocks {
            crate::replies::validate(block)?;
        }
        let digest = reply_digest(&reply)?;
        let before = ir::page_fingerprint(page);
        let content_before = content_fingerprint(page);
        if already_applied(page, &reply, &digest) {
            if check_stamp(&reply, page, Some(&stamp)).is_err() {
                let receipt = page
                    .extra
                    .get("worksheet_receipt")
                    .ok_or_else(|| IrError::refused("stale-worksheets", &page.id))?;
                if receipt["after"] != before
                    || receipt
                        .get("content_after")
                        .is_some_and(|content| content != &content_before)
                    || receipt["raw"] != ir::sha256_bytes(raw.as_bytes())
                    || receipt["digest"] != digest
                    || receipt["path"] != json!(std::path::absolute(&path)?)
                    || receipt
                        .get("accepted")
                        .or_else(|| receipt.get("before"))
                        .and_then(Value::as_str)
                        != reply.fingerprint.as_deref()
                    || receipt.get("accepted_content").and_then(Value::as_str)
                        != reply.content_fingerprint.as_deref()
                    || fs::read_to_string(&path)? != raw
                {
                    return Err(IrError::refused("stale-worksheets", &page.id));
                }
                ir::write_text(&path, &restamp(&raw, &before, &content_before))?;
            }
            continue;
        }
        if !force
            && reply.content_fingerprint.is_none()
            && page.extra.get("worksheet_digest").and_then(Value::as_str) == Some(&digest)
            && page
                .extra
                .get("worksheet_content")
                .and_then(Value::as_str)
                .is_some_and(|content| content != content_before)
        {
            return Err(IrError::refused(
                "stale-worksheets",
                format!(
                    "{}: rebuild the worksheet before renewing changed content",
                    page.id
                ),
            ));
        }
        merge(page, &reply, &policy, &direction, Some(&stamp), force)?;
        for region in &page.regions {
            if ir::foreign_script_guard(source_lang.as_deref(), &region.source_text)
                == ir::ForeignScriptGuard::ProtectedJapanese
                && (regions::translatable(region, &policy)
                    || region.erase
                    || region.state == Some(regions::RegionState::Erased))
            {
                return Err(IrError::refused(
                    "protected_japanese_artwork",
                    format!(
                        "{}: Japanese kana/SFX on an English-source edition must be kept untouched",
                        region.id
                    ),
                ));
            }
        }
        let after = ir::page_fingerprint(page);
        let content_after = content_fingerprint(page);
        page.extra.insert(
            "worksheet_receipt".into(),
            json!({
                "path":std::path::absolute(&path)?, "raw":ir::sha256_bytes(raw.as_bytes()),
                "before":before, "after":after, "accepted":reply.fingerprint, "digest":digest,
                "content_after":content_after, "accepted_content":reply.content_fingerprint,
            }),
        );
        receipts.push((page.id.clone(), path, raw, after, content_after));
    }
    let changed: Vec<_> = receipts.iter().map(|(id, _, _, _, _)| id.clone()).collect();
    if changed.is_empty() {
        return Ok(changed);
    }
    if worksheets.is_some() {
        doc.meta
            .insert("worksheets".into(), json!(std::path::absolute(&folder)?));
    }
    stages::stamp_stage(doc, "worksheet", Default::default(), None, Some(&changed))?;
    for (_, path, raw, _, _) in &receipts {
        if fs::read_to_string(path)? != *raw {
            return Err(IrError::refused(
                "worksheet_changed",
                path.display().to_string(),
            ));
        }
    }
    loaded.save_claimed(&claim)?;
    for (_, path, raw, after, content_after) in receipts {
        if fs::read_to_string(&path)? != raw {
            return Err(IrError::refused(
                "worksheet_changed",
                path.display().to_string(),
            ));
        }
        let stamped = restamp(&raw, &after, &content_after);
        if stamped != raw {
            ir::write_text(path, &stamped)?;
        }
    }
    Ok(changed)
}
fn restamp(raw: &str, stamp: &str, content: &str) -> String {
    let body = raw
        .split_inclusive('\n')
        .filter(|line| {
            !line.starts_with("# fingerprint:")
                && !line.starts_with("# content-fingerprint:")
                && !line.starts_with("# scheme:")
        })
        .collect::<String>();
    format!(
        "# fingerprint: {stamp}\n# content-fingerprint: {content}\n# scheme: {STAMP_SCHEME}\n{body}"
    )
}
pub fn reconcile_document(
    doc_path: &Path,
    worksheets: Option<&Path>,
    pages: &[String],
) -> Result<Vec<String>, IrError> {
    if pages.is_empty() {
        return Err(IrError::refused(
            "missing_pages",
            "reconciliation requires explicit page IDs",
        ));
    }
    let _claim = workspace::workspace_lock(ir::doc_dir(doc_path), "reconcile")?;
    let doc = ir::load_doc(doc_path)?;
    let folder = worksheet_folder(doc_path, &doc, worksheets);
    let mut changes = Vec::new();
    for page in workspace::selected_pages(&doc, Some(pages))? {
        let path = reply_path(&folder, &page.id, "done.txt")?;
        let raw = fs::read_to_string(&path)?;
        let reply = parse(&raw)?;
        addresses(&reply, page)?;
        for block in &reply.blocks {
            crate::replies::validate(block)?;
        }
        changes.push((
            page.id.clone(),
            path,
            raw,
            ir::page_fingerprint(page),
            content_fingerprint(page),
        ));
    }
    let ids = changes.iter().map(|(id, _, _, _, _)| id.clone()).collect();
    for (_, path, raw, stamp, content) in changes {
        if fs::read_to_string(&path)? != raw {
            return Err(IrError::refused(
                "worksheet_changed",
                path.display().to_string(),
            ));
        }
        let output = restamp(&raw, &stamp, &content);
        if output != raw {
            ir::write_text(path, &output)?;
        }
    }
    Ok(ids)
}

#[cfg(test)]
mod header_tests {
    use super::*;

    #[test]
    fn header_lists_workspace_metadata() -> Result<(), Box<dyn std::error::Error>> {
        let mut doc = ComicDocument::default();
        doc.meta.insert("source_language".into(), json!("ja"));
        doc.meta.insert("reading_direction".into(), json!("rtl"));
        doc.meta.insert("sfx_policy".into(), json!("annotate"));
        let mut page: PageRecord = serde_json::from_value(
            json!({"id":"p0000", "width":100, "height":100, "image":"pages/p0000.png"}),
        )?;
        page.extra
            .insert("overview".into(), json!("overviews/p0000.png"));
        page.extra
            .insert("sheets".into(), json!(["sheets/p0000-01.png"]));
        page.extra.insert("overview_scale".into(), json!(0.5));
        let text = page_worksheet(&doc, &page);
        for expected in [
            "overview: overviews/p0000.png",
            "sheets: sheets/p0000-01.png",
            "scale: 0.5",
            "source_language: ja",
            "reading_direction: rtl",
            "sfx_policy: annotate",
        ] {
            assert!(text.contains(expected), "missing {expected}: {text}");
        }
        Ok(())
    }
}
