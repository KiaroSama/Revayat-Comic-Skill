use crate::{
    ComicDocument, IrError, glossary, ir, languages, regions, replies, stages, worksheet_paths,
};
use serde::{Deserialize, Serialize};
use serde_json::Map;
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
};

pub const CONTEXT_BUDGET: usize = 3000;
pub use worksheet_paths::worksheet_folder;
fn page_index(doc: &ComicDocument, id: &str) -> Result<usize, IrError> {
    doc.pages
        .iter()
        .position(|p| p.id == id)
        .ok_or_else(|| IrError::refused("unknown_pages", id))
}
#[derive(Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Preflight {
    pub page: String,
    pub worksheets: PathBuf,
    pub unmerged: Vec<String>,
    pub unverified: Vec<String>,
    pub moved: Vec<String>,
    pub allow_unmerged: bool,
    pub ok: bool,
}
pub fn preflight(
    doc_path: &Path,
    doc: &ComicDocument,
    id: &str,
    worksheets: Option<&Path>,
    allow_unmerged: bool,
) -> Result<Preflight, IrError> {
    let stop = page_index(doc, id)?;
    let folder = worksheet_folder(doc_path, doc, worksheets);
    let mut state = Preflight {
        page: id.into(),
        worksheets: folder.clone(),
        allow_unmerged,
        ..Preflight::default()
    };
    let stale: BTreeSet<_> = stages::stale_pages(doc, "worksheet")?.into_iter().collect();
    for (index, page) in doc.pages[..=stop].iter().enumerate() {
        if !page
            .id
            .strip_prefix('p')
            .is_some_and(|id| !id.is_empty() && id.bytes().all(|b| b.is_ascii_digit()))
        {
            return Err(IrError::refused("invalid_page_id", &page.id));
        }
        let current = ir::page_fingerprint(page);
        let receipt = page.extra.get("worksheet_receipt");
        let expected = page.extra.get("worksheet_digest").and_then(Value::as_str);
        if expected.is_some()
            && (receipt
                .and_then(|v| v["after"].as_str())
                .map_or_else(|| stale.contains(&page.id), |prior| prior != current))
        {
            state.moved.push(page.id.clone());
        }
        let path = folder.join(format!("{}.done.txt", page.id));
        if index == stop || !path.is_file() {
            continue;
        }
        match expected {
            Some(expected) => {
                let actual = replies::parse_worksheet(&fs::read_to_string(path)?)
                    .and_then(|reply| replies::reply_digest(&reply));
                if actual.as_deref().ok() != Some(expected)
                    || page.extra.get("worksheet_clean") != Some(&json!(true))
                {
                    state.unmerged.push(page.id.clone());
                }
            }
            None if page
                .regions
                .iter()
                .any(|r| !r.dropped && !r.target_text.trim().is_empty()) =>
            {
                state.unverified.push(page.id.clone())
            }
            None => state.unmerged.push(page.id.clone()),
        }
    }
    state.unmerged.reverse();
    state.unverified.reverse();
    state.ok = (allow_unmerged || state.unmerged.is_empty()) && state.moved.is_empty();
    Ok(state)
}
pub fn refusal(state: &Preflight, doc_path: &Path) -> String {
    if !state.moved.is_empty() {
        format!(
            "Previously merged worksheets refer to moved geometry on {}. Review and reconcile {} before translating.",
            state.moved.join(", "),
            doc_path.display()
        )
    } else {
        format!(
            "Merge earlier worksheet replies for {} before translating {}.",
            state.unmerged.join(", "),
            state.page
        )
    }
}
fn limit(
    value: Value,
    size: usize,
    section: &str,
    overflow: &mut Vec<String>,
) -> Result<Value, IrError> {
    if ir::dumps(&value)?.chars().count() <= size {
        return Ok(value);
    }
    overflow.push(section.into());
    let result = match value {
        Value::String(text) => json!(text.chars().take(size).collect::<String>()),
        Value::Array(mut rows) => {
            while !rows.is_empty() && ir::dumps(&rows)?.chars().count() > size {
                rows.pop();
            }
            json!(rows)
        }
        _ => Value::Null,
    };
    Ok(result)
}
pub fn build(doc: &ComicDocument, id: &str, budget: usize) -> Result<Value, IrError> {
    let index = page_index(doc, id)?;
    let mut terms = ir::Fields::new();
    for (term, entry) in glossary::entries(doc) {
        let Some(target) = entry["target"].as_str().filter(|s| !s.trim().is_empty()) else {
            continue;
        };
        if !glossary::is_locked(entry)? {
            continue;
        }
        let source_aliases = glossary::forms(term, entry)
            .into_iter()
            .skip(1)
            .collect::<Vec<_>>();
        let forms = glossary::target_forms(entry)
            .into_iter()
            .filter(|form| form != target.trim())
            .collect::<Vec<_>>();
        let value = if source_aliases.is_empty() && forms.is_empty() {
            json!(target)
        } else {
            let mut row = json!({"target":target});
            if !source_aliases.is_empty() {
                row["source_aliases"] = json!(source_aliases);
            }
            if !forms.is_empty() {
                row["forms"] = json!(forms);
            }
            row
        };
        terms.insert(term.clone(), value);
    }
    let mut speakers: Map<String, Value> = Map::new();
    let mut active = BTreeSet::new();
    for (position, page) in doc.pages[..=index].iter().enumerate() {
        for region in page.regions.iter().filter(|r| !r.dropped) {
            let Some(name) = region
                .speaker
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
            else {
                continue;
            };
            if position == index {
                active.insert(name);
            }
            let row = speakers
                .entry(name)
                .or_insert_with(|| json!({"speaker":name,"lines":0,"first_page":page.id}));
            row["lines"] = json!(row["lines"].as_u64().unwrap_or(0).saturating_add(1));
        }
    }
    for (name, row) in &mut speakers {
        if let Some(cast) = doc.meta.get("cast").and_then(|v| v.get(name)) {
            for field in ["register", "voice", "relationships", "pronouns"] {
                if let Some(value) = cast
                    .get(field)
                    .filter(|v| !v.is_null() && v.as_str() != Some(""))
                {
                    row[field] = value.clone();
                }
            }
        }
    }
    let mut previous = Vec::new();
    let mut spent = 0usize;
    let mut truncated = false;
    'pages: for page in doc.pages[..index].iter().rev() {
        for r in
            page.regions.iter().rev().filter(|r| {
                regions::translatable(r, doc.policy()) && !r.target_text.trim().is_empty()
            })
        {
            let (source, target) = (r.source_text.trim(), r.target_text.trim());
            let size = source.chars().count() + target.chars().count();
            if spent.saturating_add(size) > budget || previous.len() == 24 {
                truncated = true;
                break 'pages;
            }
            spent += size;
            previous.push(json!({"page":page.id,"region":r.id,"speaker":r.speaker.as_deref().unwrap_or_default().trim(),"src":source,"fa":target}));
        }
    }
    previous.reverse();
    let next=doc.pages.get(index+1).map(|page|page.regions.iter().filter(|r|!r.dropped).take(8).map(|r| {
        let mut entry = json!({"region":r.id,"kind":r.kind,"speaker":r.speaker.as_deref().unwrap_or_default().trim()});
        let source=r.source_text.trim();
        if !source.is_empty() {
            entry["source"]=json!(source.chars().take(80).collect::<String>());
            entry["truncated"]=json!(source.chars().count()>80);
        }
        entry
    }).collect::<Vec<_>>()).unwrap_or_default();
    let mut over = Vec::new();
    let scene = limit(
        doc.meta.get("scene").cloned().unwrap_or(json!("")),
        1200,
        "scene",
        &mut over,
    )?;
    let style = limit(
        doc.meta.get("style_notes").cloned().unwrap_or(json!([])),
        1200,
        "style_notes",
        &mut over,
    )?;
    let series = limit(
        doc.meta.get("series_notes").cloned().unwrap_or(json!([])),
        1200,
        "series_notes",
        &mut over,
    )?;
    let mut speaker_rows: Vec<_> = speakers.into_values().collect();
    if ir::dumps(&speaker_rows)?.chars().count() > 2000 {
        over.push("speakers".into());
        while !speaker_rows.is_empty() && ir::dumps(&speaker_rows)?.chars().count() > 2000 {
            let index = speaker_rows
                .iter()
                .rposition(|row| !active.contains(row["speaker"].as_str().unwrap_or_default()))
                .unwrap_or(speaker_rows.len() - 1);
            speaker_rows.remove(index);
        }
    }
    let lang = doc.meta.get("source_language").and_then(Value::as_str);
    let guidance = languages::guidance(lang);
    let mut policy = ir::title_policy(doc);
    if let Some(note) = policy.shift_remove("sfx") {
        policy.insert("sfx_note".into(), note);
    }
    if let Some(conflict) = ir::sfx_conflict(doc) {
        policy.insert("sfx_conflict".into(), json!(conflict));
    }
    policy.insert("sfx".into(), json!(doc.policy()));
    policy.insert(
        "direction".into(),
        json!(
            doc.meta
                .get("reading_direction")
                .and_then(Value::as_str)
                .unwrap_or("rtl")
        ),
    );
    policy.insert("source_language".into(), json!(lang.unwrap_or("auto")));
    let sizes = json!({"speakers":size(&speaker_rows)?,"translation_memory":size(&previous)?,"scene":scene.as_str().map_or(0,|s|s.chars().count()),"style_notes":size(&style)?,"series_notes":size(&series)?,"glossary":size(&terms)?,"language_guidance":size(&guidance)?});
    let constraints = size(&terms)?;
    let mut budget_report = json!({"characters":budget,"characters_used":spent,"lines":previous.len(),"truncated":truncated,"section_limits":{"scene":1200,"style_notes":1200,"series_notes":1200,"speakers":2000},"sections":sizes,"overflowed":over,"constraints_characters":constraints,"constraints_over_budget":constraints>budget});
    if constraints > budget {
        budget_report["constraints_action"] = json!(format!(
            "the locked glossary alone is {constraints} characters against a {budget}-character budget. Raise --budget, or lock fewer terms: every locked entry is sent on every page."
        ));
    }
    Ok(
        json!({"page":id,"constraints":{"glossary":terms,"policy":policy,"rules":["one source region becomes exactly one translated region","never merge two balloons or split one across two","never summarise, omit, soften or add","a locked glossary term is used as written","keep the propositions, negation, tense and aspect, quantities, causal links, intent, joke and emotional intensity","choose register from how these people actually speak to each other","narration is not automatically past tense, and a shout is not automatically impolite","try a line break first, then a shorter wording that keeps the same meaning"]},"context":{"language_guidance":guidance,"speakers":speaker_rows,"translation_memory":previous,"next_page":next,"scene":scene,"style_notes":style,"series_notes":series},"budget":budget_report}),
    )
}
fn size(value: &impl Serialize) -> Result<usize, IrError> {
    Ok(ir::dumps(value)?.chars().count())
}
