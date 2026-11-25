use crate::{
    IrError, PageRecord, batch,
    regions::{self, Artifact},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::path::Path;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Finding {
    pub code: String,
    pub page: String,
    pub detail: String,
}
fn finding(code: &str, page: &PageRecord, detail: impl Into<String>) -> Finding {
    Finding {
        code: code.into(),
        page: page.id.clone(),
        detail: detail.into(),
    }
}
pub fn certify_artifact(root: &Path, page: &PageRecord, policy: &str) -> Option<Finding> {
    let required = regions::required_artifact(page, policy);
    let (shipped, _) = regions::shipped_artifact(page, |p| {
        batch::owned(root, Path::new(p)).is_ok_and(|path| path.is_file())
    });
    if shipped >= required {
        return None;
    }
    if required == Artifact::Rendered {
        Some(finding(
            "page-not-rendered",
            page,
            "this page carries Persian that has never been drawn onto it; run typeset",
        ))
    } else {
        Some(finding(
            "page-not-cleaned",
            page,
            "the cleaned image is gone; run clean or restore the file",
        ))
    }
}
fn verify(
    root: &Path,
    page: &PageRecord,
    record: &Value,
    stage: &str,
    files: &[(&str, Option<&str>)],
) -> Result<Vec<Finding>, IrError> {
    let mut issues = Vec::new();
    if record["size"] != json!([page.width, page.height]) {
        issues.push(finding(
            "delivery-mismatch",
            page,
            format!("{stage} committed different page dimensions"),
        ));
    }
    for (key, named) in files {
        let Some(wanted) = record.get(key) else {
            issues.push(finding(
                "delivery-mismatch",
                page,
                format!("{stage} has no {key} evidence"),
            ));
            continue;
        };
        let path = named
            .map(|name| batch::owned(root, Path::new(name)))
            .transpose()?;
        let actual = path.as_deref().map(batch::digest).transpose()?.flatten();
        if wanted != &json!(actual) || actual.is_none() && named.is_some() {
            issues.push(finding(
                "delivery-mismatch",
                page,
                format!("{key} is not the file {stage} committed"),
            ));
        }
    }
    Ok(issues)
}
pub fn certify_delivery(root: &Path, page: &PageRecord) -> Result<Vec<Finding>, IrError> {
    let Some(record) = page
        .extra
        .get("delivery")
        .filter(|v| v.as_object().is_some_and(|o| !o.is_empty()))
    else {
        return Ok(page
            .rendered
            .as_ref()
            .map(|_| {
                finding(
                    "delivery-unverified",
                    page,
                    "the rendered page has no committed evidence; re-run typeset",
                )
            })
            .into_iter()
            .collect());
    };
    verify(
        root,
        page,
        record,
        "typeset",
        &[
            ("final", page.rendered.as_deref()),
            ("clean", page.cleaned.as_deref()),
            (
                "writable",
                page.extra.get("writable").and_then(Value::as_str),
            ),
        ],
    )
}
pub fn certify_cleaning(root: &Path, page: &PageRecord) -> Result<Vec<Finding>, IrError> {
    let Some(record) = page
        .extra
        .get("cleaning")
        .filter(|v| v.as_object().is_some_and(|o| !o.is_empty()))
    else {
        return Ok(page
            .cleaned
            .as_ref()
            .map(|_| {
                finding(
                    "delivery-unverified",
                    page,
                    "the cleaned page has no committed evidence; re-run clean",
                )
            })
            .into_iter()
            .collect());
    };
    verify(
        root,
        page,
        record,
        "clean",
        &[
            ("source", Some(&page.image)),
            ("mask", page.extra.get("mask").and_then(Value::as_str)),
            ("clean", page.cleaned.as_deref()),
        ],
    )
}
