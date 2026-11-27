use super::*;
use image::{Rgb, imageops};
use std::collections::{BTreeMap, BTreeSet};

pub struct ReviewPackOptions {
    pub out: Option<PathBuf>,
    pub scale: u32,
    pub verify_ledger: bool,
}

pub fn review_pack(doc_path: &Path, opts: ReviewPackOptions) -> Result<Value> {
    let document = ir::load_doc(doc_path).map_err(failed)?;
    let root = ir::doc_dir(doc_path);
    let out_dir = opts.out.unwrap_or_else(|| root.join("review"));
    let flags_path = out_dir.join("flags.json");
    let ledger_path = out_dir.join("ledger.tsv");
    if opts.verify_ledger {
        return verify_ledger(&document, &flags_path, &ledger_path);
    }
    let crops_dir = out_dir.join("crops");
    fs::create_dir_all(&crops_dir)?;
    let scale = opts.scale.clamp(1, 2);
    let policy = document.policy().to_owned();
    let source_lang = document.meta.get("source_language").and_then(Value::as_str);
    let mut items = Vec::new();
    let mut template_rows =
        vec!["page_id\tregion_id\tstage\tverdict\tdefect_codes\tnotes".to_owned()];

    for page in &document.pages {
        let source = original(root, page)?;
        let final_img = if let Some(path) = page.rendered.as_deref().or(page.cleaned.as_deref()) {
            images::load_image(&asset(root, path)?, MAX_PAGE_PIXELS)
                .map_err(failed)?
                .into_rgb8()
        } else {
            source.clone()
        };
        let mut ink_boxes: Vec<(&str, Rect)> = Vec::new();
        for r in &page.regions {
            if let Some(b) = r
                .typeset
                .get("ink_box")
                .and_then(|v| serde_json::from_value::<Rect>(v.clone()).ok())
            {
                ink_boxes.push((&r.id, b));
            }
        }
        let mut overlapping = BTreeSet::new();
        for o in revayat_vision::qachecks::rendered_text_overlaps(&ink_boxes) {
            overlapping.insert(o.first);
            overlapping.insert(o.second);
        }
        let mut page_flagged = 0usize;
        let mut first_clean_speech: Option<&RegionRecord> = None;
        for r in &page.regions {
            if r.dropped || r.state == Some(regions::RegionState::Dropped) {
                continue;
            }
            let mut reasons = Vec::new();
            let status = r
                .typeset
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("");
            if status == "external" {
                reasons.push("external_on_art");
            }
            if status == "unreliable" {
                reasons.push("unreliable");
            }
            if let Some(fs) = r.typeset.get("font_size").and_then(Value::as_f64)
                && fs < 15.0
            {
                reasons.push("tiny_font");
            }
            if r.erase || r.state == Some(regions::RegionState::Erased) {
                reasons.push("erased_balloon");
            }
            if overlapping.contains(&r.id) {
                reasons.push("overlap");
            }
            if ir::foreign_script_guard(source_lang, &r.source_text)
                != ir::ForeignScriptGuard::Translatable
            {
                reasons.push("japanese_on_english");
            }
            let target = r.target_text.trim();
            if !target.is_empty()
                && target.chars().any(|c| c.is_ascii_digit())
                && !target.chars().any(char::is_alphabetic)
                && target
                    .chars()
                    .any(|c| !c.is_ascii_digit() && !c.is_whitespace())
            {
                reasons.push("numeric_punctuation");
            }
            if !bubble_kind(r) && editable(r, &policy) && !reasons.contains(&"external_on_art") {
                reasons.push("non_balloon_edit");
            }
            if reasons.is_empty() {
                if first_clean_speech.is_none() && bubble_kind(r) && status == "fit" {
                    first_clean_speech = Some(r);
                }
                continue;
            }
            emit_crop(
                &source,
                &final_img,
                page,
                r,
                &reasons,
                scale,
                &crops_dir,
                &mut items,
                &mut template_rows,
            )?;
            page_flagged += 1;
        }
        if let Some(spot) = first_clean_speech {
            emit_crop(
                &source,
                &final_img,
                page,
                spot,
                &["spot_check"],
                scale,
                &crops_dir,
                &mut items,
                &mut template_rows,
            )?;
            page_flagged += 1;
        }
        if page_flagged == 0 {
            let crop_path = crops_dir.join(format!("{}_page.png", safe_id(&page.id)?));
            let sbs = side_by_side(&source, &final_img, 1, 1500);
            sbs.save(&crop_path).map_err(failed)?;
            items.push(json!({
                "page_id": page.id,
                "region_id": "*",
                "crop_path": crop_path.to_string_lossy(),
                "reasons": ["page_spot_check"],
            }));
            template_rows.push(format!("{}\t*\t5a\tPENDING\t\t", page.id));
        }
    }

    let payload = json!({
        "version": 1,
        "page_count": document.pages.len(),
        "items": items,
    });
    ir::write_text(
        &flags_path,
        &serde_json::to_string_pretty(&payload).map_err(failed)?,
    )
    .map_err(failed)?;
    let template_path = out_dir.join("ledger.template.tsv");
    ir::write_text(&template_path, &format!("{}\n", template_rows.join("\n"))).map_err(failed)?;
    Ok(json!({
        "ok": true,
        "out": out_dir.to_string_lossy(),
        "flags": flags_path.to_string_lossy(),
        "ledger_template": template_path.to_string_lossy(),
        "pages": document.pages.len(),
        "crops": items.len(),
    }))
}

#[allow(clippy::too_many_arguments)]
fn emit_crop(
    source: &RgbImage,
    rendered: &RgbImage,
    page: &PageRecord,
    region: &RegionRecord,
    reasons: &[&str],
    scale: u32,
    crops_dir: &Path,
    items: &mut Vec<Value>,
    template_rows: &mut Vec<String>,
) -> Result<()> {
    let mut box_rect = bounds(region)?;
    if let Some(ink) = region
        .typeset
        .get("ink_box")
        .and_then(|v| serde_json::from_value::<Rect>(v.clone()).ok())
    {
        box_rect = box_rect.union(ink);
    }
    let pad = 28u32;
    let x0 = box_rect.x().saturating_sub(pad);
    let y0 = box_rect.y().saturating_sub(pad);
    let x1 = box_rect.right().saturating_add(pad).min(source.width());
    let y1 = box_rect.bottom().saturating_add(pad).min(source.height());
    let (w, h) = (x1.saturating_sub(x0).max(1), y1.saturating_sub(y0).max(1));
    let left = imageops::crop_imm(source, x0, y0, w, h).to_image();
    let right = imageops::crop_imm(rendered, x0, y0, w, h).to_image();
    let sbs = side_by_side(&left, &right, scale, 1500);
    let crop_path = crops_dir.join(format!("{}.png", safe_id(&region.id)?));
    sbs.save(&crop_path).map_err(failed)?;
    items.push(json!({
        "page_id": page.id,
        "region_id": region.id,
        "crop_path": crop_path.to_string_lossy(),
        "reasons": reasons,
        "status": region.typeset.get("status").and_then(Value::as_str).unwrap_or(""),
        "font_size": region.typeset.get("font_size").and_then(Value::as_f64),
        "source_text": region.source_text,
        "target_text": region.target_text,
    }));
    template_rows.push(format!("{}\t{}\t5a\tPENDING\t\t", page.id, region.id));
    Ok(())
}

fn side_by_side(left: &RgbImage, right: &RgbImage, scale: u32, max_width: u32) -> RgbImage {
    let divider = 4u32;
    let (lw, lh) = left.dimensions();
    let target_w = lw.saturating_mul(scale);
    let target_h = lh.saturating_mul(scale);
    let (w, h) = if target_w.saturating_mul(2).saturating_add(divider) > max_width {
        let fit_w = max_width.saturating_sub(divider) / 2;
        let fit_h = ((u64::from(lh) * u64::from(fit_w)) / u64::from(lw.max(1))) as u32;
        (fit_w.max(1), fit_h.max(1))
    } else {
        (target_w.max(1), target_h.max(1))
    };
    let filter = if w >= lw {
        imageops::FilterType::Nearest
    } else {
        imageops::FilterType::Lanczos3
    };
    let l = imageops::resize(left, w, h, filter);
    let r = imageops::resize(right, w, h, filter);
    let mut out = RgbImage::from_pixel(w * 2 + divider, h, Rgb([210, 40, 120]));
    imageops::replace(&mut out, &l, 0, 0);
    imageops::replace(&mut out, &r, i64::from(w + divider), 0);
    out
}

fn verify_ledger(
    document: &revayat_ir::ComicDocument,
    flags_path: &Path,
    ledger_path: &Path,
) -> Result<Value> {
    if !flags_path.is_file() {
        return Err(failed(
            "missing review flags.json; run qa review-pack first",
        ));
    }
    if !ledger_path.is_file() {
        return Ok(json!({
            "ok": false,
            "error": "missing review ledger.tsv",
            "ledger": ledger_path.to_string_lossy(),
        }));
    }
    let flags: Value = serde_json::from_str(&fs::read_to_string(flags_path)?).map_err(failed)?;
    let items = flags["items"]
        .as_array()
        .ok_or_else(|| failed("invalid flags.json items"))?;
    let mut verdicts: BTreeMap<(String, String), String> = BTreeMap::new();
    let mut page_verdicts: BTreeSet<String> = BTreeSet::new();
    for (idx, line) in fs::read_to_string(ledger_path)?.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty() || (idx == 0 && trimmed.starts_with("page_id\t")) {
            continue;
        }
        let cols: Vec<&str> = trimmed.split('\t').collect();
        if cols.len() < 4 {
            return Ok(json!({
                "ok": false,
                "error": format!("malformed ledger.tsv row {}", idx + 1),
            }));
        }
        let verdict = cols[3].trim().to_ascii_uppercase();
        let key = (cols[0].trim().to_owned(), cols[1].trim().to_owned());
        if matches!(verdict.as_str(), "PASS" | "FIXED") {
            page_verdicts.insert(key.0.clone());
        }
        verdicts.insert(key, verdict);
    }
    let mut missing = Vec::new();
    let mut unresolved = Vec::new();
    for item in items {
        let page_id = item["page_id"].as_str().unwrap_or_default().to_owned();
        let region_id = item["region_id"].as_str().unwrap_or_default().to_owned();
        match verdicts
            .get(&(page_id.clone(), region_id.clone()))
            .map(String::as_str)
        {
            Some("PASS" | "FIXED") => {}
            Some(other) => {
                unresolved.push(json!({"page": page_id, "region": region_id, "verdict": other}))
            }
            None => missing.push(json!({"page": page_id, "region": region_id})),
        }
    }
    for page in &document.pages {
        if !page_verdicts.contains(&page.id) {
            missing.push(json!({"page": page.id, "region": "*"}));
        }
    }
    let ok = missing.is_empty() && unresolved.is_empty();
    Ok(json!({
        "ok": ok,
        "checked": items.len(),
        "missing": missing,
        "unresolved": unresolved,
        "ledger": ledger_path.to_string_lossy(),
    }))
}
