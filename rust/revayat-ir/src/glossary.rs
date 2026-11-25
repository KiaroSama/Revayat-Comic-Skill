use crate::{ComicDocument, IrError, ir, regions, stages, textmatch, workspace};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

pub const ROLES: [&str; 3] = ["term", "mentioned", "character"];
pub use crate::textmatch::used;

fn object_entries(doc: &mut ComicDocument) -> Result<&mut ir::Fields, IrError> {
    doc.glossary
        .entry("entries")
        .or_insert_with(|| json!({}))
        .as_object_mut()
        .ok_or_else(|| IrError::refused("invalid_glossary", "entries must be an object"))
}
pub fn entries(doc: &ComicDocument) -> impl Iterator<Item = (&String, &Value)> {
    doc.glossary
        .get("entries")
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
}
pub fn is_locked(entry: &Value) -> Result<bool, IrError> {
    match entry.get("locked") {
        None => Ok(false),
        Some(Value::Bool(b)) => Ok(*b),
        _ => Err(IrError::refused(
            "invalid_glossary",
            "glossary locked must be a boolean; explicitly correct the entry",
        )),
    }
}
fn entry(term: &str, role: &str, first: &str) -> Value {
    json!({"target":"","role":role,"first":first,"count":0,"locked":false,"source":term,"aliases":[],"version":1,"counts":{}})
}
fn forms_of(value: &Value) -> impl Iterator<Item = &str> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
}
pub fn forms(term: &str, entry: &Value) -> Vec<String> {
    let mut seen = BTreeSet::new();
    std::iter::once(term)
        .chain(forms_of(&entry["aliases"]))
        .filter(|s| seen.insert(*s))
        .map(str::to_owned)
        .collect()
}
pub fn target_forms(entry: &Value) -> Vec<String> {
    let mut seen = BTreeSet::new();
    entry["target"]
        .as_str()
        .into_iter()
        .chain(forms_of(&entry["target_forms"]))
        .map(str::trim)
        .filter(|s| !s.is_empty() && seen.insert(*s))
        .map(str::to_owned)
        .collect()
}

#[derive(Default)]
struct Counts {
    first: String,
    repeated: usize,
    mentioned: usize,
    speaker: usize,
}
impl Counts {
    fn role(&self) -> &str {
        if self.speaker > 0 {
            "character"
        } else if self.mentioned > 0 {
            "mentioned"
        } else {
            "term"
        }
    }
}
fn count<'a>(counts: &'a mut BTreeMap<String, Counts>, term: &str, page: &str) -> &'a mut Counts {
    counts.entry(term.to_owned()).or_insert_with(|| Counts {
        first: page.into(),
        ..Counts::default()
    })
}
pub fn scan(doc: &mut ComicDocument, minimum: usize) -> Result<Vec<String>, IrError> {
    let mut counts = BTreeMap::<String, Counts>::new();
    for (page, region) in doc.iter_regions().filter(|(_, r)| !r.dropped) {
        if let Some(speaker) = region
            .speaker
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            count(&mut counts, speaker, &page.id).speaker += 1;
        }
        for proposed in forms_of(region.extra.get("proposed").unwrap_or(&Value::Null)) {
            count(&mut counts, proposed, &page.id).mentioned += 1;
        }
        let source = region.source_text.trim();
        if !source.is_empty() && source.chars().count() <= 12 && !source.contains('\n') {
            count(&mut counts, source, &page.id).repeated += 1;
        }
    }
    let mut updated = doc.glossary.clone();
    let target = updated
        .entry("entries")
        .or_insert_with(|| json!({}))
        .as_object_mut()
        .ok_or_else(|| IrError::refused("invalid_glossary", "entries must be an object"))?;
    for (term, stats) in &counts {
        if stats.speaker > 0 || stats.mentioned > 0 || stats.repeated >= minimum.max(1) {
            target
                .entry(term.clone())
                .or_insert_with(|| entry(term, stats.role(), &stats.first));
        }
    }
    let mut needed = Vec::new();
    for (term, value) in target {
        let locked = is_locked(value)?;
        let Some(record) = value.as_object_mut() else {
            return Err(IrError::refused("invalid_glossary", term));
        };
        let empty = Counts::default();
        let stats = counts.get(term).unwrap_or(&empty);
        let old = record
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if ROLES.iter().position(|s| *s == stats.role()) > ROLES.iter().position(|s| *s == old)
            && !locked
        {
            record.insert("role".into(), json!(stats.role()));
        }
        let repeated = if record.get("role").and_then(Value::as_str) == Some("term")
            || record
                .get("counts")
                .and_then(|c| c.get("repeated"))
                .is_some()
        {
            stats.repeated
        } else {
            0
        };
        let total = stats.speaker + stats.mentioned + repeated;
        record.insert("count".into(), json!(total));
        record.insert(
            "counts".into(),
            json!({"speaker":stats.speaker,"mentioned":stats.mentioned,"repeated":repeated}),
        );
        record.entry("version").or_insert_with(|| json!(1));
        if record
            .get("target")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .is_empty()
        {
            needed.push((total, term.clone()));
        }
    }
    needed.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
    doc.glossary = updated;
    Ok(needed.into_iter().map(|(_, term)| term).collect())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Drift {
    pub region: String,
    pub term: String,
    pub expected: String,
    pub actual: String,
}
pub fn check(doc: &ComicDocument) -> Vec<Drift> {
    let mut result = Vec::new();
    for (term, entry) in entries(doc) {
        let expected = entry["target"].as_str().unwrap_or_default();
        if expected.is_empty() || is_locked(entry).ok() != Some(true) {
            continue;
        }
        let source_forms = forms(term, entry);
        let target_forms = target_forms(entry);
        for (_, r) in doc.iter_regions() {
            if !regions::translatable(r, doc.policy())
                || r.target_text.trim().is_empty()
                || !(textmatch::used(&r.source_text, &source_forms)
                    || r.speaker
                        .as_deref()
                        .is_some_and(|speaker| source_forms.iter().any(|form| form == speaker)))
                || textmatch::used(&r.target_text, &target_forms)
            {
                continue;
            }
            result.push(Drift {
                region: r.id.clone(),
                term: term.clone(),
                expected: expected.into(),
                actual: r.target_text.clone(),
            });
        }
    }
    result
}
pub fn validate(value: &Value) -> Result<ir::Fields, IrError> {
    let invalid = |why: &str| IrError::refused("invalid_glossary", why);
    let changes = if let Some(target) = value.as_str() {
        ir::Fields::from_iter([("target".into(), json!(target))])
    } else {
        value
            .as_object()
            .cloned()
            .ok_or_else(|| invalid("a glossary entry must be text or an object"))?
    };
    if changes.get("locked").is_some_and(|v| !v.is_boolean()) {
        return Err(invalid("locked must be a JSON boolean"));
    }
    for key in ["aliases", "target_forms"] {
        if let Some(v) = changes.get(key)
            && !v.as_array().is_some_and(|a| a.iter().all(Value::is_string))
        {
            return Err(invalid("aliases and target_forms must contain only text"));
        }
    }
    for key in ["target", "note", "role", "speaker"] {
        if changes.get(key).is_some_and(|v| !v.is_string()) {
            return Err(invalid("target, note, role, and speaker must be text"));
        }
    }
    if changes
        .get("role")
        .and_then(Value::as_str)
        .is_some_and(|r| !r.is_empty() && !ROLES.contains(&r))
    {
        return Err(invalid("unknown role"));
    }
    Ok(changes)
}
pub fn set_entry(doc: &mut ComicDocument, term: &str, value: &Value) -> Result<bool, IrError> {
    if term.trim().is_empty() {
        return Err(IrError::refused(
            "invalid_glossary",
            "glossary source must be nonempty text",
        ));
    }
    let changes = validate(value)?;
    let mut old = entries(doc)
        .find(|(name, _)| name.as_str() == term)
        .map(|(_, value)| value.clone())
        .unwrap_or_else(|| entry(term, "", ""));
    let before = old.clone();
    if !changes.contains_key("locked") {
        is_locked(&old)?;
    }
    let record = old
        .as_object_mut()
        .ok_or_else(|| IrError::refused("invalid_glossary", term))?;
    for key in [
        "locked",
        "target",
        "role",
        "aliases",
        "target_forms",
        "note",
        "speaker",
    ] {
        if let Some(value) = changes.get(key) {
            record.insert(key.into(), value.clone());
        }
    }
    if old == before {
        return Ok(false);
    }
    let version = before["version"].as_u64().unwrap_or(1).saturating_add(1);
    old["version"] = json!(version);
    object_entries(doc)?.insert(term.into(), old);
    Ok(true)
}
pub fn set_target(
    doc: &mut ComicDocument,
    term: &str,
    target: &str,
    locked: bool,
) -> Result<bool, IrError> {
    set_entry(doc, term, &json!({"target":target,"locked":locked}))
}
pub fn apply_file(doc_path: &Path, entries_path: &Path) -> Result<usize, IrError> {
    let claim = workspace::workspace_lock(ir::doc_dir(doc_path), "glossary")?;
    let mut loaded = workspace::LoadedDocument::open(doc_path)?;
    let value: Value = serde_json::from_str(&ir::read_text(entries_path)?)?;
    let payload = value
        .get("entries")
        .unwrap_or(&value)
        .as_object()
        .ok_or_else(|| IrError::refused("invalid_glossary", "expected an object of entries"))?;
    let mut changed = 0;
    for (term, value) in payload {
        changed += usize::from(set_entry(&mut loaded.document, term, value)?);
    }
    if changed > 0 {
        stages::stamp_stage(
            &mut loaded.document,
            "glossary",
            Default::default(),
            None,
            None,
        )?;
        loaded.save_claimed(&claim)?;
    }
    Ok(changed)
}
