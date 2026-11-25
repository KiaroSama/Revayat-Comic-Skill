use crate::{IrError, RegionRecord, ir, regions};
use serde_json::{Value, json};

fn text_identity(region: &RegionRecord) -> Value {
    json!({
        "region": region.id,
        "source": region.source_text,
        "source_revision": region.extra.get("source_revision"),
        "shown": region.target_text,
    })
}

fn compression_identity(region: &RegionRecord) -> Value {
    json!({
        "type": "compressed-variant",
        "region": region.id,
        "source": region.source_text,
        "source_revision": region.extra.get("source_revision"),
        "full": region.extra.get("target_full").and_then(Value::as_str).unwrap_or_default(),
        "shown": region.target_text,
        "box": region.bbox,
        "kind": region.kind,
        "orientation": region.orientation,
    })
}

pub fn fingerprint(region: &RegionRecord, code: &str) -> Result<String, IrError> {
    let identity = if code == "compressed-variant" {
        compression_identity(region)
    } else {
        text_identity(region)
    };
    Ok(ir::sha256_bytes(ir::dumps(&identity)?.as_bytes()))
}

fn codes(region: &RegionRecord) -> impl Iterator<Item = &str> {
    region
        .extra
        .get("review_ack")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
}

pub fn settled(region: &RegionRecord, code: &str) -> bool {
    if !codes(region).any(|stored| stored == code) {
        return false;
    }
    if code == "compressed-variant" {
        return region.extra.get("review_ack_compression") == Some(&compression_identity(region));
    }
    region
        .extra
        .get("review_ack_text")
        .is_none_or(|identity| identity == &text_identity(region))
}

pub fn acknowledged(region: &RegionRecord) -> Vec<&str> {
    codes(region).filter(|code| settled(region, code)).collect()
}

pub fn acknowledged_spans(region: &RegionRecord) -> Option<Vec<&str>> {
    if !settled(region, "zwnj-review") {
        return Some(Vec::new());
    }
    if region.extra.contains_key("review_ack_text") {
        // Modern evidence already binds every word, including all ambiguous spans.
        return None;
    }
    region.extra.get("review_ack_spans").map(|spans| {
        spans
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect()
    })
}

pub fn carried_acknowledgements(region: &RegionRecord) -> Vec<String> {
    acknowledged(region)
        .into_iter()
        .filter(|code| {
            // A legacy span list cannot establish approval of all current wording.
            *code != "zwnj-review"
                || region.extra.contains_key("review_ack_text")
                || !region.extra.contains_key("review_ack_spans")
        })
        .filter_map(|code| {
            fingerprint(region, code)
                .ok()
                .map(|stamp| format!("{code}@{stamp}"))
        })
        .collect()
}

fn requested(value: &str) -> impl Iterator<Item = &str> {
    value
        .split([',', '،'])
        .map(str::trim)
        .filter(|s| !s.is_empty())
}

pub(crate) fn validate(value: &str) -> Result<(), IrError> {
    for entry in requested(value) {
        let (code, stamp) = entry
            .split_once('@')
            .map_or((entry, None), |(code, stamp)| (code, Some(stamp)));
        if code.is_empty()
            || !code
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
            || stamp.is_some_and(|stamp| {
                stamp.len() != 64
                    || !stamp
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
        {
            return Err(IrError::refused(
                "invalid_fields",
                "reviewed requires comma-separated lint codes with optional SHA-256 evidence",
            ));
        }
    }
    Ok(())
}

pub(crate) fn record(region: &mut RegionRecord, value: &str) -> Result<(), IrError> {
    validate(value)?;
    let mut accepted = Vec::new();
    for entry in requested(value) {
        let code = if let Some((code, stamp)) = entry.split_once('@') {
            if fingerprint(region, code)? != stamp {
                continue;
            }
            code
        } else {
            entry
        };
        if !accepted.contains(&code) {
            accepted.push(code);
        }
    }
    let prior = json!({
        "codes": codes(region).collect::<Vec<_>>(),
        "spans": region.extra.get("review_ack_spans").cloned().unwrap_or_else(|| json!([])),
        "compression": region.extra.get("review_ack_compression"),
        "text": region.extra.get("review_ack_text"),
    });
    let identity = (!accepted.is_empty()).then(|| text_identity(region));
    let compression = accepted
        .contains(&"compressed-variant")
        .then(|| compression_identity(region));
    let current = json!({
        "codes": accepted,
        "spans": [],
        "compression": compression,
        "text": identity,
    });
    if prior["codes"]
        .as_array()
        .is_some_and(|codes| !codes.is_empty())
        && prior != current
    {
        let history = region
            .extra
            .entry("review_ack_history")
            .or_insert_with(|| json!([]))
            .as_array_mut()
            .ok_or_else(|| IrError::refused("invalid_review", "review history must be an array"))?;
        history.push(prior);
    }
    for field in [
        "review_ack",
        "review_ack_text",
        "review_ack_compression",
        "review_ack_spans",
        "reviewed",
    ] {
        region.extra.remove(field);
    }
    if !accepted.is_empty() {
        region.extra.insert("review_ack".into(), json!(accepted));
        region
            .extra
            .insert("review_ack_text".into(), json!(identity));
    }
    if let Some(compression) = compression {
        region
            .extra
            .insert("review_ack_compression".into(), compression);
    }
    Ok(())
}

pub fn compression_review_needed(region: &RegionRecord, policy: &str) -> bool {
    let full = region
        .extra
        .get("target_full")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim();
    let shown = region.target_text.trim();
    regions::translatable(region, policy)
        && !full.is_empty()
        && !shown.is_empty()
        && full != shown
        && !settled(region, "compressed-variant")
}
