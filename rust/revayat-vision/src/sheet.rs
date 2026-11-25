use crate::{Rect, Result, VisionError};
use serde::{Deserialize, Serialize};
use std::fmt::Write as _;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorksheetRegion {
    pub id: String,
    pub kind: String,
    pub orientation: String,
    pub bounds: Rect,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub persian: String,
    #[serde(default)]
    pub notes: String,
}

#[derive(Debug, Clone)]
pub struct Worksheet<'a> {
    pub title: &'a str,
    pub page_id: &'a str,
    pub page_number: usize,
    pub page_count: usize,
    pub size: [u32; 2],
    pub overview_scale: f64,
    pub fingerprint: &'a str,
    pub reading_direction: &'a str,
    pub glossary: &'a [(&'a str, &'a str)],
    pub regions: &'a [WorksheetRegion],
}

fn single(value: &str) -> bool {
    !value.contains(['\r', '\n'])
}

pub fn page_worksheet(sheet: &Worksheet<'_>) -> Result<String> {
    let [w, h] = sheet.size;
    if w == 0
        || h == 0
        || sheet.page_number == 0
        || sheet.page_number > sheet.page_count
        || !(0.0..=1.0).contains(&sheet.overview_scale)
        || sheet.overview_scale == 0.0
        || ![sheet.title, sheet.page_id, sheet.fingerprint]
            .into_iter()
            .all(single)
        || !matches!(sheet.reading_direction, "rtl" | "ltr")
    {
        return Err(VisionError::invalid("invalid worksheet page metadata"));
    }
    let title = if sheet.title.is_empty() {
        "comic"
    } else {
        sheet.title
    };
    let mut text = format!(
        "# {title}, page {} ({} of {})\n# fingerprint: {}\n# scheme: 2\n# Page size: {w} × {h} px. Reading direction: {}.\n# Overview scale: {:.6}. Divide overview coordinates by this scale.\n# Read overview.png and the crop sheets before translating.\n# Put OCR in src:, exact logical Persian in fa:, and context in notes:.\n# Use @@ +slug kind orientation and box: x y w h for a missed region.\n",
        sheet.page_id,
        sheet.page_number,
        sheet.page_count,
        sheet.fingerprint,
        sheet.reading_direction,
        sheet.overview_scale
    );
    let fmt = |error: std::fmt::Error| VisionError::invalid(error.to_string());
    if !sheet.glossary.is_empty() {
        text.push_str("# Glossary (source | Persian)\n");
        for (source, persian) in sheet.glossary {
            if !single(source) || !single(persian) {
                return Err(VisionError::invalid("glossary cells must use one line"));
            }
            writeln!(text, "# {source} | {persian}").map_err(fmt)?;
        }
    }
    for region in sheet.regions {
        region.bounds.checked((w, h))?;
        if [&region.id, &region.kind, &region.orientation]
            .into_iter()
            .any(|s| s.is_empty() || s.chars().any(char::is_whitespace))
        {
            return Err(VisionError::invalid(
                "worksheet region header contains an invalid token",
            ));
        }
        let [x, y, w, h] = region.bounds.0;
        writeln!(
            text,
            "\n@@ {} {} {}\n# box: {x} {y} {w} {h}",
            region.id, region.kind, region.orientation
        )
        .map_err(fmt)?;
        for (key, value) in [
            ("src", &region.source),
            ("fa", &region.persian),
            ("notes", &region.notes),
        ] {
            let normalized = value.replace("\r\n", "\n");
            let mut lines = normalized.split(['\r', '\n']);
            writeln!(text, "{key}: {}", lines.next().unwrap_or_default()).map_err(fmt)?;
            for line in lines {
                writeln!(text, "  {line}").map_err(fmt)?;
            }
        }
    }
    Ok(text)
}
