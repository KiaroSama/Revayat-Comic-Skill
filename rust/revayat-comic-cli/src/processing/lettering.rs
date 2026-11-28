use super::*;
use revayat_vision::{VisionError, clean, fullpage_edit, qa, typeset, typestyle};
use std::collections::BTreeSet;

fn local_mask(root: &Path, region: &RegionRecord) -> Result<Option<masks::RegionMask>> {
    let Some(path) = &region.mask else {
        return Ok(None);
    };
    let bounds: Rect = region
        .extra
        .get("mask_bounds")
        .ok_or_else(|| failed("missing region mask bounds"))
        .and_then(|bounds| serde_json::from_value(bounds.clone()).map_err(failed))?;
    let pixels = images::load_image(&asset(root, path)?, MAX_PAGE_PIXELS)
        .map_err(failed)?
        .into_luma8();
    if pixels.dimensions() != (bounds.width(), bounds.height()) {
        return Err(failed(
            "region mask dimensions do not match mask_bounds; run mask again",
        ));
    }
    Ok(Some(masks::RegionMask { bounds, pixels }))
}

fn on_art_mask(root: &Path, page: &RgbImage, region: &RegionRecord) -> Result<masks::RegionMask> {
    if let Some(mask) = local_mask(root, region)? {
        return Ok(mask);
    }
    region_mask(&masks::page_luminance(page), region, None, false)
}

fn image_at(directory: &Path, page: &PageRecord) -> Result<RgbImage> {
    let name = format!("{}.png", safe_id(&page.id)?);
    Ok(
        images::load_image(&asset(directory, &name)?, MAX_PAGE_PIXELS)
            .map_err(failed)?
            .into_rgb8(),
    )
}

fn external_page(directory: &Path, page: &PageRecord) -> Result<Option<RgbImage>> {
    let filename = format!("{}.png", safe_id(&page.id)?);
    match directory.join(filename).symlink_metadata() {
        Ok(_) => image_at(directory, page).map(Some),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound && directory.is_dir() => Ok(None),
        Err(err) => Err(err.into()),
    }
}

pub(super) fn read_mask(root: &Path, page: &PageRecord, field: &str) -> Result<GrayImage> {
    if let Some(path) = page.extra.get(field).and_then(Value::as_str) {
        Ok(images::load_image(&asset(root, path)?, MAX_PAGE_PIXELS)
            .map_err(failed)?
            .into_luma8())
    } else {
        Ok(GrayImage::new(page.width, page.height))
    }
}

pub(super) fn protected_japanese(source_language: Option<&str>, region: &RegionRecord) -> bool {
    ir::foreign_script_guard(source_language, &region.source_text)
        == ir::ForeignScriptGuard::ProtectedJapanese
}

pub(super) fn preserved_region_bounds(
    page: &PageRecord,
    policy: &str,
    source_language: Option<&str>,
) -> Result<Vec<Rect>> {
    page.regions
        .iter()
        .filter(|region| {
            !region.dropped
                && region.state != Some(regions::RegionState::Dropped)
                && (!editable(region, policy) || protected_japanese(source_language, region))
        })
        .map(bounds)
        .collect()
}

pub(super) fn exclude_page_regions(mask: GrayImage, regions: &[Rect]) -> GrayImage {
    let mut local = masks::RegionMask {
        bounds: Rect([0, 0, mask.width(), mask.height()]),
        pixels: mask,
    };
    local.exclude(regions);
    local.pixels
}

fn clears_balloon(region: &RegionRecord, policy: &str, source_language: Option<&str>) -> bool {
    !protected_japanese(source_language, region)
        && editable(region, policy)
        && (region.erase
            || region.state == Some(revayat_ir::RegionState::Erased)
            || !region.target_text.trim().is_empty())
}

pub(super) fn excluded_balloon_regions(
    page: &PageRecord,
    policy: &str,
    source_language: Option<&str>,
) -> Result<Vec<Rect>> {
    page.regions
        .iter()
        .filter(|region| {
            !region.dropped
                && region.state != Some(revayat_ir::RegionState::Dropped)
                && !clears_balloon(region, policy, source_language)
        })
        .map(bounds)
        .collect()
}

pub fn clean(path: &Path, bubbles_only: bool, external: Option<&Path>) -> Result<Value> {
    write_doc(path, "clean", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let policy = loaded.document.policy().to_owned();
        let source_lang = loaded
            .document
            .meta
            .get("source_language")
            .and_then(Value::as_str)
            .map(str::to_owned);
        for page in &mut loaded.document.pages {
            let native = original_native(&root, page)?;
            images::validate_preservation_image(&native).map_err(failed)?;
            let image = native.to_rgb8();
            let external = external
                .map(|directory| external_page(directory, page))
                .transpose()?
                .flatten();
            let mut balloons = Vec::new();
            let mut balloon_regions = Vec::new();
            let panels = page_panels(page)?;
            let neighbors = on_art_bounds(page)?;
            let excluded = excluded_balloon_regions(page, &policy, source_lang.as_deref())?;
            let preserved = preserved_region_bounds(page, &policy, source_lang.as_deref())?;
            for (index, region) in page.regions.iter_mut().enumerate() {
                if clears_balloon(region, &policy, source_lang.as_deref())
                    && let Some(balloon) =
                        resolve_balloon(&image, region, &panels, &neighbors, None)?
                {
                    record_balloon(&image, region, balloon)?;
                    balloons.push(balloon);
                    balloon_regions.push(index);
                }
            }
            let mut cleaned = clean::clean_page_bubbles_with_external(
                &image,
                &balloons,
                &excluded,
                external.as_ref(),
            )
            .map_err(failed)?;
            for (index, strategy) in balloon_regions.into_iter().zip(&cleaned.strategies) {
                let region = &mut page.regions[index];
                if region.erase || region.state == Some(regions::RegionState::Erased) {
                    region.fill = serde_json::to_value(strategy)
                        .map_err(failed)?
                        .as_str()
                        .unwrap_or("cleaned")
                        .to_owned();
                }
            }
            if !bubbles_only {
                for region in &mut page.regions {
                    if !editable(region, &policy)
                        || protected_japanese(source_lang.as_deref(), region)
                        || (bubble_kind(region)
                            && (!clears_balloon(region, &policy, source_lang.as_deref())
                                || balloon(region)?.is_some()))
                    {
                        continue;
                    }
                    let mut mask = local_mask(&root, region)?
                        .ok_or_else(|| failed("missing region mask; run mask first"))?;
                    // Saved masks must never override a current keep decision.
                    mask.exclude(&preserved);
                    mask.apply_to(&mut cleaned.mask).map_err(failed)?;
                    let require_external = region
                        .extra
                        .get("solid_mask")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    let (image, strategy) = clean::clean_region_with_solid(
                        &cleaned.image,
                        &mask,
                        None,
                        external.as_ref(),
                        require_external,
                    )
                    .map_err(failed)?;
                    cleaned.image = image;
                    region.fill = serde_json::to_value(strategy)
                        .map_err(failed)?
                        .as_str()
                        .unwrap_or("cleaned")
                        .to_owned();
                }
            }
            let native_clean =
                images::compose_original(&native, &cleaned.image, &cleaned.mask).map_err(failed)?;
            page.extra.insert(
                "clean_mask".into(),
                json!(save_image(
                    &root,
                    "clean",
                    &format!("{}-mask", page.id),
                    DynamicImage::ImageLuma8(cleaned.mask)
                )?),
            );
            page.cleaned = Some(save_image(&root, "clean", &page.id, native_clean)?);
            page.extra.insert(
                "cleaning".into(),
                json!({
                    "size": [page.width, page.height], "source": page.sha256,
                    "mask": digest(&root, page.extra.get("mask").and_then(Value::as_str))?,
                    "clean": digest(&root, page.cleaned.as_deref())?,
                    "clean_mask": digest(&root, page.extra.get("clean_mask").and_then(Value::as_str))?,
                }),
            );
            page.rendered = None;
            page.extra.remove("delivery");
            for region in &mut page.regions {
                region.typeset.clear();
            }
        }
        stamp(loaded, "clean")?;
        Ok(json!({"cleaned":loaded.document.pages.len()}))
    })
}

pub(super) fn reading_clean(root: &Path, page: &PageRecord) -> Result<RgbImage> {
    let path = page
        .cleaned
        .as_deref()
        .ok_or_else(|| failed("missing cleaned page; run clean first"))?;
    Ok(images::load_image(&asset(root, path)?, MAX_PAGE_PIXELS)
        .map_err(failed)?
        .into_rgb8())
}

fn lettering_style(region: &RegionRecord) -> Result<typestyle::TextStyle> {
    let mut style = region
        .extra
        .get("style")
        .and_then(Value::as_str)
        .map_or_else(|| Ok(Default::default()), typestyle::style_flags)
        .map_err(failed)?;
    let integer = |key, max| {
        region
            .extra
            .get(key)
            .map(|value| {
                value
                    .as_u64()
                    .filter(|n| (1..=max).contains(n))
                    .ok_or_else(|| {
                        failed(format!(
                            "{}: {key} must be an integer in 1..={max}",
                            region.id
                        ))
                    })
            })
            .transpose()
    };
    style.outline_px = integer("outline_px", 6)?.map(|n| n as u32);
    style.outline_alpha = integer("outline_alpha", 255)?.map(|n| n as u8);
    style.outline = !style.no_outline && (style.outline || style.outline_px.is_some());
    if let Some(value) = region.extra.get("angle") {
        style.angle_deg = Some(
            value
                .as_f64()
                .filter(|a| (-45.0..=45.0).contains(a))
                .ok_or_else(|| {
                    failed(format!("{}: angle must be a number in -45..=45", region.id))
                })? as f32,
        );
    }
    Ok(style)
}

fn needs_backing_outline(page: &RgbImage, area: Rect, dark: bool) -> bool {
    let ink = if dark { [255; 3] } else { [0; 3] };
    let (mut n, mut sum, mut squares, mut weak) = (0, 0.0, 0.0, 0);
    for y in (area.y()..area.bottom()).step_by(3) {
        for x in (area.x()..area.right()).step_by(3) {
            let rgb = page.get_pixel(x, y).0;
            let [r, g, b] = rgb.map(f64::from);
            let luma = 0.299 * r + 0.587 * g + 0.114 * b;
            n += 1;
            sum += luma;
            squares += luma * luma;
            weak += u32::from(qa::rgb_contrast(rgb, ink) < 3.0);
        }
    }
    let count = f64::from(n);
    n > 0 && (weak * 4 >= n || squares / count - (sum / count).powi(2) >= 144.0)
}

pub fn typeset(path: &Path, external: Option<&Path>) -> Result<Value> {
    write_doc(path, "typeset", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let policy = loaded.document.policy().to_owned();
        let source_lang = loaded
            .document
            .meta
            .get("source_language")
            .and_then(Value::as_str)
            .map(str::to_owned);
        let rtl_target = ir::is_rtl_language(
            loaded
                .document
                .meta
                .get("target_language")
                .and_then(Value::as_str),
        );
        let mut count = 0;
        for page in &mut loaded.document.pages {
            let cleaned = reading_clean(&root, page)?;
            let native = original_native(&root, page)?;
            images::validate_preservation_image(&native).map_err(failed)?;
            let source = native.to_rgb8();
            let mut text = Vec::new();
            let mut medium_ids = BTreeSet::new();
            let mut auto_tilt_ids = BTreeSet::new();
            let mut glosses = Vec::new();
            let preserved = preserved_region_bounds(page, &policy, source_lang.as_deref())?;
            let mut allowed =
                exclude_page_regions(read_mask(&root, page, "clean_mask")?, &preserved);
            let mut external_mask = GrayImage::new(page.width, page.height);
            let edited = external
                .map(|dir| external_page(dir, page))
                .transpose()?
                .flatten();
            if let Some(edited) = &edited
                && edited.dimensions() != source.dimensions()
            {
                return Err(failed(format!(
                    "external page {} is {}x{}; expected {}x{}",
                    page.id,
                    edited.width(),
                    edited.height(),
                    source.width(),
                    source.height()
                )));
            }
            let panels = page_panels(page)?;
            let neighbors = on_art_bounds(page)?;
            let excluded = excluded_balloon_regions(page, &policy, source_lang.as_deref())?;
            let mut balloon_rects = Vec::new();
            for region in &page.regions {
                if let Some(b) = resolve_balloon(&source, region, &panels, &neighbors, None)? {
                    let (_, open) = masks::balloon_paper(&source, b).map_err(failed)?;
                    balloon_rects.push(if open { b.text_bounds } else { b.bounds });
                }
            }
            for region in &mut page.regions {
                region.typeset.clear();
                if region.target_text.trim().is_empty()
                    || protected_japanese(source_lang.as_deref(), region)
                {
                    continue;
                }
                if regions::uses_gloss(region, &policy) {
                    glosses.push(json!({"region":region.id, "kind":region.kind, "source":region.source_text, "fa":region.target_text}));
                    continue;
                }
                if !regions::translatable(region, &policy) {
                    continue;
                }
                let resolved = resolve_balloon(&source, region, &panels, &neighbors, None)?;
                if resolved.is_none()
                    && !bubble_kind(region)
                    && let Some(ext_img) = edited.as_ref()
                {
                    let region_box = bounds(region)?;
                    let base_bounds = match local_mask(&root, region)? {
                        Some(m) => region_box.union(m.bounds),
                        None => region_box,
                    };
                    let mut patch = masks::solid_region_patch(source.dimensions(), base_bounds, 6)
                        .map_err(failed)?;
                    patch.exclude(&excluded);
                    patch.exclude(&balloon_rects);
                    let Some(tight) = revayat_vision::mask_bounds(&patch.pixels) else {
                        region.typeset.insert("status".into(), json!("unreliable"));
                        region.typeset.insert(
                            "reason".into(),
                            json!("external patch empty after clipping"),
                        );
                        continue;
                    };
                    let changed = patch.pixels.enumerate_pixels().any(|(x, y, p)| {
                        p[0] != 0
                            && revayat_vision::qachecks::pixel_changed(
                                source.get_pixel(patch.bounds.x() + x, patch.bounds.y() + y),
                                ext_img.get_pixel(patch.bounds.x() + x, patch.bounds.y() + y),
                            )
                    });
                    if changed {
                        let effective_box = Rect([
                            patch.bounds.x() + tight.x(),
                            patch.bounds.y() + tight.y(),
                            tight.width(),
                            tight.height(),
                        ]);
                        patch.apply_to(&mut external_mask).map_err(failed)?;
                        patch.apply_to(&mut allowed).map_err(failed)?;
                        region.typeset.insert("status".into(), json!("external"));
                        region
                            .typeset
                            .insert("ink_box".into(), json!(effective_box));
                        region.typeset.insert(
                            "mask_sha256".into(),
                            json!(ir::sha256_bytes(patch.pixels.as_raw())),
                        );
                        continue;
                    }
                }
                let mut entry =
                    typeset::TextRegion::new(&region.id, bounds(region)?, &region.target_text);
                entry.rtl_target = rtl_target;
                entry.is_balloon = bubble_kind(region);
                entry.style = lettering_style(region)?;
                if (entry.is_balloon || region.kind == "caption")
                    && !entry.style.bold
                    && !entry.style.shout
                {
                    entry.style.medium = true;
                    medium_ids.insert(region.id.clone());
                }
                if !entry.is_balloon && resolved.is_none() {
                    let area = entry.bounds.checked(cleaned.dimensions()).map_err(failed)?;
                    if !entry.style.no_outline && !entry.style.outline {
                        if let Some((px, alpha)) =
                            typestyle::detect_original_outline(&source, area, !dark(region))
                        {
                            entry.style.outline = true;
                            entry.style.outline_px.get_or_insert(px);
                            entry.style.outline_alpha.get_or_insert(alpha);
                        } else if matches!(region.kind.as_str(), "sfx" | "sign" | "title")
                            && (region.fill == "inpaint"
                                || needs_backing_outline(&cleaned, area, dark(region)))
                        {
                            entry.style.outline = true;
                            entry.style.outline_px.get_or_insert(2);
                        }
                    }
                    if entry.style.angle_deg.is_none()
                        && matches!(region.kind.as_str(), "caption" | "sfx" | "sign")
                        && let Some(deg) = typestyle::detect_region_angle(&source, area)
                        && deg.abs() >= 2.0
                    {
                        entry.style.angle_deg = Some(deg);
                        auto_tilt_ids.insert(region.id.clone());
                    }
                }
                if let Some(balloon) = resolved {
                    let interior =
                        revayat_vision::qachecks::balloon_text_interior(&source, balloon)
                            .map_err(failed)?;
                    let mut interior =
                        clean::clear_lettering_area(&cleaned, interior, balloon.dark)
                            .map_err(failed)?;
                    interior.exclude(&excluded);
                    interior.apply_to(&mut allowed).map_err(failed)?;
                    entry
                        .style
                        .color
                        .get_or_insert(if balloon.dark { [255; 3] } else { [0; 3] });
                    entry.interior = Some(interior);
                    record_balloon(&source, region, balloon)?;
                } else if bubble_kind(region) || region.kind == "caption" {
                    let anchor = entry.bounds;
                    let area = panels
                        .iter()
                        .filter(|panel| panel.contains(anchor.center()[0], anchor.center()[1]))
                        .min_by_key(|panel| panel.area())
                        .and_then(|panel| panel.intersection(anchor))
                        .unwrap_or(anchor);
                    let mut interior =
                        masks::elliptical_lettering_area(&cleaned, area, dark(region))
                            .map_err(failed)?;
                    if !interior.pixels.iter().any(|&p| p != 0) && region.kind == "caption" {
                        let flat = clean::compact_lettering_area(&cleaned, area).map_err(failed)?;
                        let covered = flat.pixels.iter().filter(|&&p| p != 0).count();
                        let total = (area.width() as usize) * (area.height() as usize);
                        let ink = if dark(region) { [255u8; 3] } else { [0u8; 3] };
                        let [cx, cy] = area.center();
                        let backing = cleaned.get_pixel(cx, cy).0;
                        if total > 0
                            && covered * 10 >= total * 7
                            && qa::rgb_contrast(backing, ink) >= 3.0
                        {
                            interior = flat;
                        }
                    }
                    interior.exclude(&excluded);
                    if !interior.pixels.iter().any(|&p| p != 0) {
                        region.typeset.insert("status".into(), json!("unreliable"));
                        region
                            .typeset
                            .insert("reason".into(), json!("no safe paper for lettering"));
                        continue;
                    }
                    interior.apply_to(&mut allowed).map_err(failed)?;
                    if dark(region) {
                        entry.style.color.get_or_insert([255; 3]);
                    }
                    entry.interior = Some(interior);
                } else {
                    let anchor = entry.bounds;
                    entry.compact =
                        region.kind == "title" && anchor.width().max(anchor.height()) < 48;
                    let mut interior = if entry.compact {
                        clean::compact_lettering_area(&cleaned, anchor).map_err(failed)?
                    } else {
                        let area = on_art_mask(&root, &source, region)?.bounds;
                        let interior = masks::RegionMask {
                            bounds: area,
                            pixels: GrayImage::from_pixel(area.width(), area.height(), Luma([255])),
                        };
                        clean::clear_lettering_area(&cleaned, interior, dark(region))
                            .map_err(failed)?
                    };
                    interior.exclude(&excluded);
                    if !interior.pixels.pixels().any(|p| p[0] != 0) {
                        region.typeset.insert("status".into(), json!("unreliable"));
                        continue;
                    }
                    interior.apply_to(&mut allowed).map_err(failed)?;
                    entry.interior = Some(interior);
                }
                text.push(entry);
            }
            if glosses.is_empty() {
                page.extra.remove("sfx_notes");
            } else {
                page.extra.insert("sfx_notes".into(), json!(glosses));
            }
            let base = if let Some(edited) = edited {
                clean::composite_external(&cleaned, &edited, &external_mask, 1).map_err(failed)?
            } else {
                cleaned.clone()
            };
            let output = loop {
                match typeset::typeset_page_with_occupied(&base, &text, Some(&external_mask)) {
                    Err(VisionError::Overflow { id }) if auto_tilt_ids.remove(&id) => {
                        if let Some(entry) = text.iter_mut().find(|r| r.id == id) {
                            entry.style.angle_deg = None;
                        }
                    }
                    result => break result.map_err(failed)?,
                }
            };
            if qa::compare_outside_mask(&cleaned, &output.image, &allowed)
                .map_err(failed)?
                .changed
                != 0
            {
                return Err(failed(
                    "typeset changed pixels outside the approved lettering area",
                ));
            }
            for decision in output.regions {
                let is_medium = medium_ids.contains(&decision.id);
                if let Some(region) = page.regions.iter_mut().find(|r| r.id == decision.id) {
                    region.typeset =
                        serde_json::from_value(serde_json::to_value(decision).map_err(failed)?)
                            .map_err(failed)?;
                    region.typeset.insert("status".into(), json!("fit"));
                    if is_medium {
                        region.typeset.insert("weight".into(), json!("medium"));
                    }
                    count += 1;
                }
            }
            let rendered =
                images::compose_original(&native, &output.image, &allowed).map_err(failed)?;
            page.extra.insert(
                "authorized_mask".into(),
                json!(save_image(
                    &root,
                    "rendered",
                    &format!("{}-mask", page.id),
                    DynamicImage::ImageLuma8(allowed)
                )?),
            );
            page.rendered = Some(save_image(&root, "rendered", &page.id, rendered)?);
            page.extra.insert("delivery".into(), json!({
                "size": [page.width, page.height], "final": digest(&root, page.rendered.as_deref())?,
                "clean": digest(&root, page.cleaned.as_deref())?,
                "writable": digest(&root, page.extra.get("writable").and_then(Value::as_str))?,
                "authorized_mask": digest(&root, page.extra.get("authorized_mask").and_then(Value::as_str))?,
            }));
        }
        stamp(loaded, "typeset")?;
        Ok(json!({"pages":loaded.document.pages.len(),"typeset":count}))
    })
}

pub fn fullpage(path: &Path, id: &str, model: String, all_regions: bool) -> Result<Value> {
    use fullpage_edit::{FullPageEditRequest, FullPageReplacement, RegionKind};
    let document = ir::load_doc(path).map_err(failed)?;
    let root = ir::doc_dir(path);
    let page = document
        .find_page(id)
        .ok_or_else(|| usage("unknown page"))?;
    let clean_path = page
        .cleaned
        .as_deref()
        .ok_or_else(|| failed("run clean --bubbles-only first"))?;
    let source = original(&root, page)?;
    let panels = page_panels(page)?;
    let neighbors = on_art_bounds(page)?;
    let source_lang = document.meta.get("source_language").and_then(Value::as_str);
    let replacements = page
        .regions
        .iter()
        .filter(|r| {
            !protected_japanese(source_lang, r)
                && regions::translatable(r, document.policy())
                && !regions::uses_gloss(r, document.policy())
                && !r.target_text.trim().is_empty()
        })
        .map(|r| {
            let enclosed = resolve_balloon(&source, r, &panels, &neighbors, None)?.is_some();
            let bbox = bounds(r)?;
            Ok(
                (all_regions || (!enclosed && !bubble_kind(r))).then(|| FullPageReplacement {
                    id: r.id.clone(),
                    source_text: r.source_text.clone(),
                    target_persian: r.target_text.clone(),
                    bbox,
                    location_cue: format!(
                        "Region {}, reading position {}",
                        r.id,
                        r.reading_order + 1
                    ),
                    style_cue: r
                        .extra
                        .get("style")
                        .and_then(Value::as_str)
                        .unwrap_or("Match the weight and emphasis of the source lettering")
                        .to_owned(),
                    kind: match r.kind.as_str() {
                        "sfx" => RegionKind::Sfx,
                        "title" => RegionKind::Title,
                        _ if enclosed => RegionKind::Balloon,
                        _ => RegionKind::OnArt,
                    },
                }),
            )
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect();
    let request = FullPageEditRequest {
        page_id: id.into(),
        cleaned_page_path: asset(&root, clean_path)?,
        original_page_path: asset(&root, &page.image)?,
        page_size: [page.width, page.height],
        model_id: model,
        replacements,
    };
    Ok(json!(
        fullpage_edit::build_fullpage_prompt(&request).map_err(failed)?
    ))
}
