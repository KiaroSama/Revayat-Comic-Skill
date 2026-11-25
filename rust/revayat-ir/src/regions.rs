use crate::{IrError, PageRecord, RegionRecord};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RegionState {
    #[default]
    #[serde(alias = "needs_review", alias = "unresolved")]
    Pending,
    Translated,
    #[serde(alias = "kept_by_policy")]
    Kept,
    #[serde(alias = "dropped_false_detection")]
    Dropped,
    Erased,
}

impl RegionState {
    pub const ALL: [Self; 5] = [
        Self::Pending,
        Self::Translated,
        Self::Kept,
        Self::Dropped,
        Self::Erased,
    ];
}

pub const SFX_KEEP_POLICIES: &[&str] = &["keep", "bilingual", "annotate"];

pub(crate) fn actions(region: &RegionRecord) -> [bool; 3] {
    [
        region.dropped || region.state == Some(RegionState::Dropped),
        region.keep || region.state == Some(RegionState::Kept),
        region.erase || region.state == Some(RegionState::Erased),
    ]
}

pub fn translatable(region: &RegionRecord, policy: &str) -> bool {
    !(region.dropped
        || region.keep
        || region.erase
        || matches!(
            region.state,
            Some(RegionState::Dropped | RegionState::Kept | RegionState::Erased)
        ))
        && (region.kind != "sfx" || matches!(policy, "translate" | "annotate" | "bilingual"))
}

pub fn uses_gloss(region: &RegionRecord, policy: &str) -> bool {
    region.kind == "sfx"
        && matches!(policy, "annotate" | "bilingual")
        && translatable(region, policy)
}

pub fn may_be_edited(region: &RegionRecord, policy: &str) -> bool {
    !(region.keep
        || region.dropped
        || matches!(region.state, Some(RegionState::Dropped | RegionState::Kept)))
        && (region.erase
            || region.state == Some(RegionState::Erased)
            || region.kind != "sfx"
            || !SFX_KEEP_POLICIES.contains(&policy))
}

pub fn region_state(region: &RegionRecord, policy: &str) -> Result<RegionState, IrError> {
    let states = actions(region);
    if states.into_iter().filter(|flag| *flag).count() > 1 {
        return Err(IrError::refused("conflicting_actions", &region.id));
    }
    Ok(if states[0] {
        RegionState::Dropped
    } else if states[2] {
        if matches!(region.fill.as_str(), "" | "none" | "keep") {
            RegionState::Pending
        } else {
            RegionState::Erased
        }
    } else if !translatable(region, policy) {
        RegionState::Kept
    } else if matches!(
        region.typeset.get("status").and_then(Value::as_str),
        Some("overflow" | "unreliable")
    ) || region.target_text.trim().is_empty()
    {
        RegionState::Pending
    } else {
        RegionState::Translated
    })
}

pub fn add_audit(region: &mut RegionRecord, note: &str) {
    let value = region.extra.entry("audit").or_insert_with(|| json!([]));
    if let Some(notes) = value.as_array_mut()
        && !notes.iter().any(|value| value == note)
    {
        notes.push(json!(note));
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Artifact {
    Original,
    Cleaned,
    Rendered,
}

pub fn required_artifact(page: &PageRecord, policy: &str) -> Artifact {
    if page
        .regions
        .iter()
        .any(|r| translatable(r, policy) && !r.target_text.trim().is_empty())
    {
        Artifact::Rendered
    } else if page.regions.iter().any(|r| {
        !r.dropped
            && r.state != Some(RegionState::Dropped)
            && !matches!(r.fill.as_str(), "" | "none" | "keep")
    }) {
        Artifact::Cleaned
    } else {
        Artifact::Original
    }
}

pub fn shipped_artifact(page: &PageRecord, exists: impl Fn(&str) -> bool) -> (Artifact, &str) {
    for (artifact, path) in [
        (Artifact::Rendered, page.rendered.as_deref()),
        (Artifact::Cleaned, page.cleaned.as_deref()),
    ] {
        if let Some(path) = path.filter(|path| exists(path)) {
            return (artifact, path);
        }
    }
    (Artifact::Original, &page.image)
}

pub fn restore_blank_page(page: &mut PageRecord) -> Vec<&'static str> {
    let mut cleared = Vec::new();
    if page.cleaned.take().is_some() {
        cleared.push("clean");
    }
    if page.rendered.take().is_some() {
        cleared.push("final");
    }
    for field in ["cleaning", "writable", "delivery"] {
        if page.extra.remove(field).is_some() {
            cleared.push(field);
        }
    }
    if page
        .extra
        .get("annotations")
        .and_then(Value::as_array)
        .is_some_and(|rows| !rows.is_empty())
    {
        page.extra.insert("annotations".into(), json!([]));
        cleared.push("annotations");
    }
    cleared
}
