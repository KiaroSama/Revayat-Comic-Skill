use super::*;
use image::{Rgb, imageops};
use std::collections::{BTreeMap, BTreeSet};

const REVIEW_VERSION: u32 = 2;
const LEDGER_HEADER: &str = "page_id\tregion_id\tstage\tverdict\tdefect_codes\tnotes\treview_id";

pub struct ReviewPackOptions {
    pub out: Option<PathBuf>,
    pub scale: u32,
    pub verify_ledger: bool,
}

pub fn review_pack(doc_path: &Path, opts: ReviewPackOptions) -> Result<Value> {
    let doc_path = fs::canonicalize(doc_path)?;
    let root = ir::doc_dir(&doc_path);
    let _claim = workspace::workspace_lock(&root, "review-pack").map_err(failed)?;
    let document = ir::load_doc(&doc_path).map_err(failed)?;
    let out_dir = std::path::absolute(opts.out.unwrap_or_else(|| root.join("review")))?;
    let flags_path = out_dir.join("flags.json");
    let ledger_path = out_dir.join("ledger.tsv");
    if opts.verify_ledger {
        return verify_ledger(&document, &root, &out_dir, &flags_path, &ledger_path);
    }
    fs::create_dir_all(&out_dir)?;
    let out_dir = checked_output_dir(&out_dir)?;
    let crops_dir = out_dir.join("crops");
    fs::create_dir_all(&crops_dir)?;
    checked_output_dir(&crops_dir)?;
    let scale = opts.scale.clamp(1, 2);
    let payload = build_manifest(&document, &root, scale, Some(&out_dir))?;
    let mut template_rows = vec![LEDGER_HEADER.to_owned()];
    for item in payload["items"]
        .as_array()
        .ok_or_else(|| failed("invalid review items"))?
    {
        template_rows.push(format!(
            "{}\t{}\t5a\tPENDING\t\t\t{}",
            item["page_id"].as_str().unwrap_or_default(),
            item["region_id"].as_str().unwrap_or_default(),
            payload["review_id"].as_str().unwrap_or_default(),
        ));
    }
    let template_path = out_dir.join("ledger.template.tsv");
    ir::write_text(&template_path, &format!("{}\n", template_rows.join("\n"))).map_err(failed)?;
    // Publish the manifest last. Crops are immutable, content-addressed files; an interrupted
    // regeneration cannot replace the evidence referenced by an existing approved manifest.
    ir::write_text(
        &flags_path,
        &serde_json::to_string_pretty(&payload).map_err(failed)?,
    )
    .map_err(failed)?;
    Ok(json!({
        "ok": true, "out": out_dir.to_string_lossy(), "flags": flags_path.to_string_lossy(),
        "ledger_template": template_path.to_string_lossy(), "review_id": payload["review_id"],
        "pages": document.pages.len(), "crops": payload["items"].as_array().map_or(0, Vec::len),
    }))
}

fn checked_output_dir(path: &Path) -> Result<PathBuf> {
    let canonical = fs::canonicalize(path)?;
    if fs::symlink_metadata(path)?.file_type().is_symlink() {
        return Err(failed(
            "review output directory must not redirect outside its configured path",
        ));
    }
    Ok(canonical)
}

fn checked_rect(rect: Rect, page: &PageRecord) -> Result<Rect> {
    if rect.area() == 0
        || rect.x().checked_add(rect.width()).is_none()
        || rect.y().checked_add(rect.height()).is_none()
        || rect != rect.clip(page.width, page.height)
    {
        return Err(failed(format!(
            "review rectangle {:?} is outside page {}",
            rect.0, page.id
        )));
    }
    Ok(rect)
}

fn ink_box(region: &RegionRecord, page: &PageRecord) -> Result<Option<Rect>> {
    region
        .typeset
        .get("ink_box")
        .filter(|value| !value.is_null())
        .map(|value| checked_rect(serde_json::from_value(value.clone()).map_err(failed)?, page))
        .transpose()
}

fn build_manifest(
    document: &revayat_ir::ComicDocument,
    root: &Path,
    scale: u32,
    output: Option<&Path>,
) -> Result<Value> {
    let policy = document.policy().to_owned();
    let source_lang = document.meta.get("source_language").and_then(Value::as_str);
    let mut items = Vec::new();
    let mut pages = Vec::new();
    let mut page_ids = BTreeSet::new();

    for page in &document.pages {
        safe_id(&page.id)?;
        if !page_ids.insert(&page.id) {
            return Err(failed("duplicate review page id"));
        }
        let source = original(root, page)?;
        let rendered_path = page.rendered.as_deref().or(page.cleaned.as_deref());
        let (final_img, rendered_sha256) = if let Some(path) = rendered_path {
            let path = asset(root, path)?;
            let final_img = images::load_image(&path, MAX_PAGE_PIXELS).map_err(failed)?;
            if (final_img.width(), final_img.height()) != source.dimensions() {
                return Err(failed(format!(
                    "review rendered dimensions differ from source page {}",
                    page.id
                )));
            }
            (
                final_img.into_rgb8(),
                ir::sha256_file(path).map_err(failed)?,
            )
        } else {
            (source.clone(), page.sha256.clone())
        };
        pages.push(json!({
            "page_id": page.id, "source_sha256": page.sha256,
            "rendered_sha256": rendered_sha256, "rendered_path": rendered_path,
            "size": [page.width, page.height],
        }));
        let mut ink_boxes: Vec<(&str, Rect)> = Vec::new();
        let mut region_ids = BTreeSet::new();
        for r in &page.regions {
            safe_id(&r.id)?;
            if !region_ids.insert(&r.id) {
                return Err(failed("duplicate review region id"));
            }
            if r.dropped || r.state == Some(regions::RegionState::Dropped) {
                continue;
            }
            checked_rect(bounds(r)?, page)?;
            if let Some(b) = ink_box(r, page)? {
                ink_boxes.push((&r.id, b));
            }
        }
        let mut overlapping = BTreeSet::new();
        for o in revayat_vision::qachecks::rendered_text_overlaps(&ink_boxes) {
            overlapping.insert(o.first);
            overlapping.insert(o.second);
        }
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
                &source, &final_img, page, r, &reasons, scale, output, &mut items,
            )?;
        }
        if let Some(spot) = first_clean_speech {
            emit_crop(
                &source,
                &final_img,
                page,
                spot,
                &["spot_check"],
                scale,
                output,
                &mut items,
            )?;
        }
        let sbs = side_by_side(&source, &final_img, 1, 1500);
        let (crop_path, crop_sha256) = record_crop(&sbs, &format!("{}-page", page.id), output)?;
        items.push(json!({
            "page_id": page.id, "region_id": "*", "crop_path": crop_path,
            "crop_sha256": crop_sha256, "reasons": ["page_spot_check"],
        }));
    }
    let mut context = json!({
        "source_language": document.meta.get("source_language"),
        "target_language": document.meta.get("target_language"),
        "reading_direction": document.meta.get("reading_direction"),
        "sfx_policy": policy, "pages": document.pages,
    });
    context.sort_all_objects();
    let mut payload = json!({
        "version": REVIEW_VERSION, "scale": scale, "page_count": document.pages.len(),
        "context_sha256": ir::sha256_bytes(context.to_string().as_bytes()),
        "pages": pages, "items": items,
    });
    payload.sort_all_objects();
    let review_id = ir::sha256_bytes(payload.to_string().as_bytes());
    payload["review_id"] = json!(review_id);
    Ok(payload)
}

fn record_crop(crop: &RgbImage, id: &str, output: Option<&Path>) -> Result<(String, String)> {
    let bytes = png(&DynamicImage::ImageRgb8(crop.clone()))?;
    let digest = ir::sha256_bytes(&bytes);
    let relative = format!("crops/{id}-{digest}.png");
    if let Some(root) = output {
        ir::write_bytes(root.join(&relative), &bytes).map_err(failed)?;
    }
    Ok((relative, digest))
}

#[allow(clippy::too_many_arguments)]
fn emit_crop(
    source: &RgbImage,
    rendered: &RgbImage,
    page: &PageRecord,
    region: &RegionRecord,
    reasons: &[&str],
    scale: u32,
    output: Option<&Path>,
    items: &mut Vec<Value>,
) -> Result<()> {
    let mut box_rect = checked_rect(bounds(region)?, page)?;
    if let Some(ink) = ink_box(region, page)? {
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
    let (crop_path, crop_sha256) =
        record_crop(&sbs, &format!("{}-{}", page.id, region.id), output)?;
    items.push(json!({
        "page_id": page.id,
        "region_id": region.id,
        "crop_path": crop_path,
        "crop_sha256": crop_sha256,
        "reasons": reasons,
        "status": region.typeset.get("status").and_then(Value::as_str).unwrap_or(""),
        "font_size": region.typeset.get("font_size").and_then(Value::as_f64),
        "source_text": region.source_text,
        "target_text": region.target_text,
    }));
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
    root: &Path,
    out_dir: &Path,
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
    if flags["version"] != REVIEW_VERSION || !matches!(flags["scale"].as_u64(), Some(1 | 2)) {
        return Ok(
            json!({"ok": false, "error": "obsolete review pack; regenerate and review the current ledger template"}),
        );
    }
    checked_output_dir(out_dir)?;
    checked_output_dir(&out_dir.join("crops"))?;
    let expected = build_manifest(
        document,
        root,
        flags["scale"].as_u64().unwrap_or(2) as u32,
        None,
    )?;
    if flags != expected {
        return Ok(
            json!({"ok": false, "error": "review evidence changed; regenerate the review pack and independently review its current template"}),
        );
    }
    let items = flags["items"]
        .as_array()
        .ok_or_else(|| failed("invalid flags.json items"))?;
    for item in items {
        let path = asset(out_dir, item["crop_path"].as_str().unwrap_or_default())?;
        if ir::sha256_file(path).map_err(failed)?.as_str()
            != item["crop_sha256"].as_str().unwrap_or_default()
        {
            return Ok(
                json!({"ok": false, "error": "review crop changed; regenerate the review pack"}),
            );
        }
    }
    let expected_keys: BTreeSet<_> = items
        .iter()
        .map(|item| {
            (
                item["page_id"].as_str().unwrap_or_default().to_owned(),
                item["region_id"].as_str().unwrap_or_default().to_owned(),
            )
        })
        .collect();
    let review_id = flags["review_id"].as_str().unwrap_or_default();
    let mut verdicts: BTreeMap<(String, String), String> = BTreeMap::new();
    let mut saw_header = false;
    for (idx, line) in fs::read_to_string(ledger_path)?.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        if !saw_header {
            if line != LEDGER_HEADER {
                return Ok(
                    json!({"ok": false, "error": "ledger header must match the current seven-column template, including review_id"}),
                );
            }
            saw_header = true;
            continue;
        }
        let cols: Vec<&str> = line.split('\t').collect();
        if cols.len() != 7 {
            return Ok(json!({
                "ok": false,
                "error": format!("malformed ledger.tsv row {}", idx + 1),
            }));
        }
        let verdict = cols[3].trim().to_ascii_uppercase();
        let key = (cols[0].trim().to_owned(), cols[1].trim().to_owned());
        if cols[6].trim() != review_id {
            return Ok(
                json!({"ok": false, "error": "ledger approval belongs to different review evidence; review the regenerated template"}),
            );
        }
        if cols[2].trim() != "5a" || !expected_keys.contains(&key) || verdicts.contains_key(&key) {
            return Ok(
                json!({"ok": false, "error": format!("unexpected, duplicate, or non-reviewer ledger row {}", idx + 1)}),
            );
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
    let ok = saw_header && missing.is_empty() && unresolved.is_empty();
    Ok(json!({
        "ok": ok,
        "checked": items.len(),
        "review_id": review_id,
        "missing": missing,
        "unresolved": unresolved,
        "ledger": ledger_path.to_string_lossy(),
    }))
}
