use crate::{ComicDocument, IrError, PageRecord, RegionRecord, ir, regions, workspace};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

pub const SCHEME: &str = "3";

fn inputs(stage: &str) -> &'static [&'static str] {
    match stage {
        "detect" | "watermark" => &["page"],
        "crops" | "ocr" => &["geometry"],
        "worksheet" => &["geometry", "constraints"],
        "translate" => &["geometry", "source", "constraints"],
        "glossary" => &["source", "text"],
        "falint" => &["text"],
        "mask" | "masks" => &["render", "policy", "source", "source_language"],
        "clean" => &["render", "policy", "masked", "source", "source_language"],
        "typeset" | "export" => &[
            "render",
            "text",
            "lettering",
            "policy",
            "source",
            "source_language",
            "target_language",
        ],
        _ => &[],
    }
}
fn needs(stage: &str) -> &'static [&'static str] {
    match stage {
        "ocr" => &["crops", "detect"],
        "crops" | "worksheet" | "translate" | "mask" | "masks" => &["detect"],
        "clean" => &["masks"],
        "typeset" => &["clean"],
        "export" => &["typeset"],
        _ => &[],
    }
}
pub fn prerequisites(stage: &str) -> BTreeSet<&'static str> {
    let mut set = BTreeSet::new();
    let mut pending = needs(stage).to_vec();
    while let Some(need) = pending.pop() {
        if set.insert(need) {
            pending.extend(needs(need));
        }
    }
    set
}

pub(crate) fn sorted_json(value: &Value) -> Result<String, IrError> {
    match value {
        Value::Array(values) => Ok(format!(
            "[{}]",
            values
                .iter()
                .map(sorted_json)
                .collect::<Result<Vec<_>, _>>()?
                .join(", ")
        )),
        Value::Object(values) => {
            let pairs: BTreeMap<_, _> = values.iter().collect();
            let mut parts = Vec::with_capacity(pairs.len());
            for (key, value) in pairs {
                parts.push(format!(
                    "{}: {}",
                    serde_json::to_string(key)?,
                    sorted_json(value)?
                ));
            }
            Ok(format!("{{{}}}", parts.join(", ")))
        }
        _ => Ok(serde_json::to_string(value)?),
    }
}
fn stable(value: Option<&Value>) -> Result<String, IrError> {
    match value {
        None | Some(Value::Null | Value::Bool(false)) => Ok("{}".into()),
        Some(Value::Array(v)) if v.is_empty() => Ok("{}".into()),
        Some(Value::String(v)) if v.is_empty() => Ok("{}".into()),
        Some(v) => sorted_json(v),
    }
}
fn py_str(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => "None".into(),
        Some(Value::String(s)) => s.clone(),
        Some(Value::Bool(b)) => py_bool(*b).into(),
        Some(v) => v.to_string(),
    }
}
fn py_bool(value: bool) -> &'static str {
    if value { "True" } else { "False" }
}
fn str_field<'a>(fields: &'a ir::Fields, name: &str) -> &'a str {
    fields.get(name).and_then(Value::as_str).unwrap_or_default()
}
fn region_text(region: &RegionRecord) -> Result<String, IrError> {
    let [dropped, kept, erased] = regions::actions(region);
    let mut fields = vec![
        region.id.as_str(),
        &region.target_text,
        str_field(&region.extra, "target_full"),
        py_bool(dropped),
        py_bool(kept),
        py_bool(erased),
        region.fill.as_str(),
    ];
    let style = str_field(&region.extra, "style").trim();
    let suffix = format!("style:{style}");
    if !style.is_empty() {
        fields.push(&suffix);
    }
    sorted_json(&json!(fields))
}
fn region_render(region: &RegionRecord) -> Result<String, IrError> {
    let [dropped, kept, erased] = regions::actions(region);
    let bbox = region.bbox.map(|v| v.to_string()).join(",");
    Ok([
        &region.id,
        py_bool(dropped),
        py_bool(kept),
        py_bool(erased),
        &bbox,
        &region.kind,
        &region.orientation,
        str_field(&region.extra, "polarity"),
        &stable(region.extra.get("balloon"))?,
        &stable(Some(&json!(region.polygon)))?,
        &region.reading_order.to_string(),
        &py_str(region.panel.as_ref()),
    ]
    .join("|"))
}
pub fn facet_revision(page: &PageRecord, facet: &str) -> Result<String, IrError> {
    use std::fmt::Write as _;
    let mut data = format!(
        "{}|{}|{}x{}|",
        page.id, page.sha256, page.width, page.height
    );
    match facet {
        "page" => {}
        "geometry" => data.push_str(&ir::page_fingerprint(page)),
        "render" | "text" => {
            if facet == "render" && !page.panels.is_empty() {
                let panels: Vec<_> = page
                    .panels
                    .iter()
                    .map(|panel| panel.get("bbox").unwrap_or(panel))
                    .collect();
                let _ = write!(data, "panels:{}|", sorted_json(&json!(panels))?);
            }
            for region in &page.regions {
                data.push_str(&if facet == "render" {
                    region_render(region)?
                } else {
                    region_text(region)?
                });
                data.push('|');
            }
        }
        "lettering" => {
            let overrides: Vec<_> = page
                .regions
                .iter()
                .map(|region| {
                    ["outline_px", "outline_alpha", "angle"].map(|key| region.extra.get(key))
                })
                .collect();
            data.push_str(&sorted_json(&json!(overrides))?);
        }
        "source" => data.push_str(&stable(Some(&json!(
            page.regions
                .iter()
                .map(|r| [&r.id, &r.source_text])
                .collect::<Vec<_>>()
        )))?),
        "masked" => {
            let _ = write!(
                data,
                "{}|{}|{}|{}|",
                py_str(page.extra.get("free_lettering_mask")),
                stable(page.extra.get("mask_options"))?,
                py_str(page.extra.get("mask")),
                py_str(page.extra.get("mask_coverage"))
            );
            for region in &page.regions {
                let _ = write!(
                    data,
                    "{}|{}|{}|",
                    region.id,
                    region.mask.as_deref().unwrap_or("None"),
                    stable(region.extra.get("mask_box"))?
                );
                if let Some(bounds) = region.extra.get("mask_bounds") {
                    let _ = write!(data, "bounds:{}|", stable(Some(bounds))?);
                }
                if let Some(solid) = region
                    .extra
                    .get("solid_mask")
                    .filter(|v| v.as_bool() == Some(true))
                {
                    let _ = write!(data, "solid:{}|", stable(Some(solid))?);
                }
            }
        }
        _ => return Err(IrError::refused("unknown_facet", facet)),
    }
    Ok(ir::sha256_bytes(data.as_bytes()))
}
fn meta_revision(doc: &ComicDocument, facet: &str) -> Result<String, IrError> {
    use std::fmt::Write as _;
    let mut data = String::new();
    let keys: &[&str] = match facet {
        "policy" => &["sfx_policy", "reading_direction"],
        "source_language" => &["source_language"],
        "target_language" => &["target_language"],
        _ => &["target_language", "source_language"],
    };
    for &key in keys {
        let value = match doc.meta.get(key).and_then(Value::as_str) {
            Some(s) => format!("'{}'", s.replace('\\', "\\\\").replace('\'', "\\'")),
            None => "None".into(),
        };
        let _ = write!(data, "{key}={value}|");
    }
    if facet == "constraints" {
        let _ = write!(
            data,
            "title={}|",
            sorted_json(&json!(ir::title_policy(doc)))?
        );
        if let Some(entries) = doc.glossary.get("entries").and_then(Value::as_object) {
            for (term, entry) in entries.iter().collect::<BTreeMap<_, _>>() {
                let target = entry["target"].as_str().unwrap_or_default();
                let version = entry["version"].as_u64().filter(|n| *n > 0).unwrap_or(1);
                let approval = if entry["locked"] == true { '!' } else { '?' };
                let _ = write!(data, "{term}={target}@{version}{approval}|");
            }
        }
    }
    Ok(ir::sha256_bytes(data.as_bytes()))
}
pub fn page_revisions(record: &Value) -> Option<&ir::Fields> {
    record.get("pages").and_then(Value::as_object)
}
fn revision_at<'a>(map: Option<&'a ir::Fields>, id: &str) -> &'a str {
    map.and_then(|m| m.get(id))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .unwrap_or("unknown")
}
fn upstream<'a>(records: &'a ir::Fields, need: &str, id: &str) -> &'a str {
    let record = records.get(need).or_else(|| {
        if need == "masks" {
            records.get("mask")
        } else {
            None
        }
    });
    revision_at(record.and_then(page_revisions), id)
}
pub fn page_revision(
    doc: &ComicDocument,
    stage: &str,
    page: &PageRecord,
    options: Option<&Value>,
) -> Result<String, IrError> {
    use std::fmt::Write as _;
    let mut data = format!("scheme={SCHEME}|stage={stage}|");
    for facet in inputs(stage) {
        let revision = if matches!(
            *facet,
            "policy" | "constraints" | "source_language" | "target_language"
        ) {
            meta_revision(doc, facet)?
        } else {
            facet_revision(page, facet)?
        };
        let _ = write!(data, "{facet}={revision}|");
    }
    let _ = write!(data, "options={}|", stable(options)?);
    for need in needs(stage) {
        let _ = write!(data, "{need}={}|", upstream(&doc.stages, need, &page.id));
    }
    Ok(ir::sha256_bytes(data.as_bytes()))
}
pub fn stamp_stage(
    doc: &mut ComicDocument,
    stage: &str,
    detail: ir::Fields,
    options: Option<Value>,
    selection: Option<&[String]>,
) -> Result<(), IrError> {
    let selected = workspace::selected_pages(doc, selection)?;
    if selection.is_some() && selected.is_empty() {
        return Ok(());
    }
    let existing = doc.stages.get(stage).unwrap_or(&Value::Null);
    let current: BTreeSet<_> = doc.pages.iter().map(|p| p.id.as_str()).collect();
    let preserve = |fields: Option<&ir::Fields>| -> ir::Fields {
        fields
            .into_iter()
            .flatten()
            .filter(|(id, _)| current.contains(id.as_str()))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    };
    let mut pages = preserve(page_revisions(existing));
    let mut page_options = preserve(existing["page_options"].as_object());
    let options = options.unwrap_or_else(|| json!({}));
    for page in selected {
        pages.insert(
            page.id.clone(),
            json!(page_revision(doc, stage, page, Some(&options))?),
        );
        page_options.insert(page.id.clone(), options.clone());
    }
    let dependency: ir::Fields = needs(stage)
        .iter()
        .map(|need| {
            (
                need.to_string(),
                Value::Object(
                    pages
                        .keys()
                        .map(|id| (id.clone(), json!(upstream(&doc.stages, need, id))))
                        .collect(),
                ),
            )
        })
        .collect();
    let mut record = detail;
    record.extend([
        ("scheme".into(), json!(SCHEME)),
        ("pages".into(), Value::Object(pages)),
        ("page_options".into(), Value::Object(page_options)),
        ("needs".into(), Value::Object(dependency)),
        ("options".into(), options),
    ]);
    doc.stages.insert(stage.into(), Value::Object(record));
    doc.meta.remove("stage_seq");
    Ok(())
}

pub fn why_stale(stage: &str, id: &str, record: &Value, records: &ir::Fields) -> String {
    if !page_revisions(record).is_some_and(|p| p.contains_key(id)) {
        return "it has not run for".into();
    }
    for need in needs(stage) {
        if revision_at(record["needs"][need].as_object(), id) != upstream(records, need, id) {
            return format!("`{need}` has run again since, for");
        }
    }
    "the inputs changed after it ran, for".into()
}
fn is_current(record: &Value) -> bool {
    record["scheme"] == SCHEME && page_revisions(record).is_some_and(|p| !p.is_empty())
}
pub fn unverified_stages(doc: &ComicDocument) -> BTreeMap<String, String> {
    doc.stages.iter().filter(|(_,r)| !is_current(r)).map(|(stage,r)| (stage.clone(),format!("stamped by an older build (freshness scheme {}, this one is {SCHEME}); re-run `{stage}` once to establish it",r["scheme"].as_str().unwrap_or("none")))).collect()
}
pub fn stale_pages(doc: &ComicDocument, stage: &str) -> Result<Vec<String>, IrError> {
    let Some(record) = doc.stages.get(stage).filter(|r| is_current(r)) else {
        return Ok(Vec::new());
    };
    let mut stale = Vec::new();
    for page in &doc.pages {
        let options = record["page_options"]
            .get(&page.id)
            .or_else(|| record.get("options"));
        if record["pages"][&page.id].as_str()
            != Some(page_revision(doc, stage, page, options)?.as_str())
        {
            stale.push(page.id.clone());
        }
    }
    Ok(stale)
}
pub fn stale_stages(
    doc: &ComicDocument,
    needed_for: Option<&str>,
) -> Result<BTreeMap<String, String>, IrError> {
    let prerequisites = needed_for.map(prerequisites);
    let mut stale = BTreeMap::new();
    for (stage, record) in &doc.stages {
        if let Some(wanted) = &prerequisites
            && needed_for != Some(stage)
            && !wanted.contains(stage.as_str())
        {
            continue;
        }
        let pages = stale_pages(doc, stage)?;
        if let Some(first) = pages.first() {
            stale.insert(
                stage.clone(),
                format!(
                    "{} {} page(s): {}{}",
                    why_stale(stage, first, record, &doc.stages),
                    pages.len(),
                    pages[..pages.len().min(4)].join(", "),
                    if pages.len() > 4 { ", …" } else { "" }
                ),
            );
        }
    }
    Ok(stale)
}
#[derive(Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct StageFreshness {
    pub stale: BTreeMap<String, String>,
    pub unverified: BTreeMap<String, String>,
}
impl StageFreshness {
    pub fn check(doc: &ComicDocument, needed_for: Option<&str>) -> Result<Self, IrError> {
        Ok(Self {
            stale: stale_stages(doc, needed_for)?,
            unverified: unverified_stages(doc),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lettering_overrides_invalidate_rendered_pages_only() -> Result<(), IrError> {
        let mut doc: ComicDocument = serde_json::from_value(json!({
            "pages": [{"id": "p0001", "regions": [{"id": "p0001_r001"}]}]
        }))?;
        for stage in ["detect", "mask", "masks", "clean", "typeset", "export"] {
            stamp_stage(&mut doc, stage, Default::default(), None, None)?;
            assert!(stale_pages(&doc, stage)?.is_empty(), "{stage}");
        }

        for (key, value) in [
            ("angle", json!(-8.0)),
            ("outline_px", json!(2)),
            ("outline_alpha", json!(128)),
            ("style", json!("no-outline")),
        ] {
            let mut edited = doc.clone();
            edited.pages[0].regions[0].extra.insert(key.into(), value);
            for stage in ["typeset", "export"] {
                assert_eq!(stale_pages(&edited, stage)?, ["p0001"], "{stage}: {key}");
            }
            for stage in ["mask", "masks", "clean"] {
                assert!(stale_pages(&edited, stage)?.is_empty(), "{stage}: {key}");
            }
        }
        Ok(())
    }
}
