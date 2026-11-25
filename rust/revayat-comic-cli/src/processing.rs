use std::{
    fs,
    io::Cursor,
    path::{Component, Path, PathBuf},
};

use image::{DynamicImage, GrayImage, ImageFormat, Luma, RgbImage};
use revayat_io::{images, inputs::MAX_PAGE_PIXELS};
use revayat_ir::{
    PageRecord, RegionRecord, ir, regions, stages,
    workspace::{self, LoadedDocument},
};
use revayat_tools::server::StageError;
use revayat_vision::{
    Rect, clean, crops, detect, falint, fullpage_edit, masks, qa, typeset, watermark,
};
use serde_json::{Value, json};

use crate::stage::{failed, usage};

type Result<T> = std::result::Result<T, StageError>;

pub fn write_doc(
    path: &Path,
    stage: &str,
    action: impl FnOnce(&mut LoadedDocument) -> Result<Value>,
) -> Result<Value> {
    let path = fs::canonicalize(path)?;
    let lock = workspace::workspace_lock(ir::doc_dir(&path), stage).map_err(failed)?;
    let mut loaded = LoadedDocument::open(&path).map_err(failed)?;
    let report = action(&mut loaded)?;
    loaded.save_claimed(&lock).map_err(failed)?;
    Ok(report)
}

fn safe_id(id: &str) -> Result<&str> {
    if id.is_empty()
        || !id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
    {
        return Err(failed("invalid page or region id"));
    }
    Ok(id)
}

pub fn asset(root: &Path, relative: &str) -> Result<PathBuf> {
    let relative = Path::new(relative);
    if relative.as_os_str().is_empty()
        || relative
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
    {
        return Err(failed("asset path must stay inside the workspace"));
    }
    let root = fs::canonicalize(root)?;
    let path = fs::canonicalize(root.join(relative))?;
    if !path.starts_with(&root) || !path.is_file() {
        return Err(failed("asset path must stay inside the workspace"));
    }
    Ok(path)
}

pub fn original(root: &Path, page: &PageRecord) -> Result<RgbImage> {
    let path = asset(root, &page.image)?;
    if ir::sha256_file(&path).map_err(failed)? != page.sha256 {
        return Err(failed("immutable source page changed"));
    }
    let image = images::load_image(&path, MAX_PAGE_PIXELS)
        .map_err(failed)?
        .into_rgb8();
    if image.dimensions() != (page.width, page.height) {
        return Err(failed("source page dimensions changed"));
    }
    Ok(image)
}

pub fn png(image: &DynamicImage) -> Result<Vec<u8>> {
    let mut buffer = Cursor::new(Vec::new());
    image
        .write_to(&mut buffer, ImageFormat::Png)
        .map_err(failed)?;
    Ok(buffer.into_inner())
}

fn save_image(root: &Path, folder: &str, id: &str, image: DynamicImage) -> Result<String> {
    let id = safe_id(id)?;
    let dir = root.join(folder);
    match fs::create_dir(&dir) {
        Ok(()) => (),
        Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => (),
        Err(err) => return Err(err.into()),
    }
    if fs::canonicalize(&dir)? != dir || fs::symlink_metadata(&dir)?.file_type().is_symlink() {
        return Err(failed(
            "output directory must not redirect outside its workspace path",
        ));
    }
    let bytes = png(&image)?;
    let digest = ir::sha256_bytes(&bytes);
    let relative = format!("{folder}/{id}-{digest}.png");
    ir::write_bytes(root.join(&relative), &bytes).map_err(failed)?;
    Ok(relative)
}

fn digest(root: &Path, name: Option<&str>) -> Result<Option<String>> {
    name.map(|name| ir::sha256_file(asset(root, name)?).map_err(failed))
        .transpose()
}

fn bounds(region: &RegionRecord) -> Result<Rect> {
    let [x, y, w, h] = region.bbox.map(u32::try_from);
    Ok(Rect([
        x.map_err(failed)?,
        y.map_err(failed)?,
        w.map_err(failed)?,
        h.map_err(failed)?,
    ]))
}

fn balloon(region: &RegionRecord) -> Result<Option<masks::Balloon>> {
    region
        .extra
        .get("balloon")
        .filter(|v| !v.is_null())
        .map(|v| serde_json::from_value(v.clone()).map_err(failed))
        .transpose()
}

fn stamp(loaded: &mut LoadedDocument, stage: &str) -> Result<()> {
    stages::stamp_stage(&mut loaded.document, stage, ir::Fields::new(), None, None).map_err(failed)
}

pub fn detect(path: &Path) -> Result<Value> {
    write_doc(path, "detect", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let rtl = loaded
            .document
            .meta
            .get("reading_direction")
            .and_then(Value::as_str)
            != Some("ltr");
        let options = detect::DetectionOptions {
            rtl,
            ..detect::DetectionOptions::default()
        };
        let mut count = 0;
        for page in &mut loaded.document.pages {
            if page
                .regions
                .iter()
                .any(|r| !r.source_text.is_empty() || !r.target_text.is_empty() || r.locked)
            {
                return Err(failed(
                    "detect would replace reviewed regions; import a fresh workspace",
                ));
            }
            let found = detect::detect_page(&original(&root, page)?, &options).map_err(failed)?;
            page.panels = found.panels.iter().map(|panel| json!(panel)).collect();
            page.regions = found
                .regions
                .into_iter()
                .enumerate()
                .map(|(position, found)| {
                    let mut region = ir::new_region(
                        ir::region_id_for(&page.id, position + 1),
                        found.bbox.0.map(f64::from),
                        &found.kind,
                        &found.orientation,
                        &found.detector,
                        found.confidence,
                    )
                    .map_err(failed)?;
                    region.reading_order = i64::try_from(position).map_err(failed)?;
                    if let Some(balloon) = found.balloon {
                        region.extra.insert("balloon".into(), json!(balloon));
                    }
                    region
                        .extra
                        .insert("polarity".into(), json!(found.polarity));
                    Ok(region)
                })
                .collect::<Result<Vec<_>>>()?;
            count += page.regions.len();
        }
        stamp(loaded, "detect")?;
        Ok(json!({"regions":count,"pages":loaded.document.pages.len()}))
    })
}

fn editable(region: &RegionRecord, policy: &str) -> bool {
    !region.dropped && !region.keep && (region.erase || regions::translatable(region, policy))
}

fn region_mask(page: &RgbImage, region: &RegionRecord, solid: bool) -> Result<masks::RegionMask> {
    if region.kind == "watermark" && region.erase {
        if !region.locked {
            return Err(failed("watermark removal requires a locked erase decision"));
        }
        let approved = watermark::mark_page(&region.id, bounds(region)?, page.dimensions())
            .map_err(failed)?
            .bounds;
        return Ok(masks::RegionMask {
            bounds: approved,
            pixels: GrayImage::from_pixel(approved.width(), approved.height(), Luma([255])),
        });
    }
    let dark = region
        .extra
        .get("polarity")
        .is_some_and(|polarity| polarity == "dark");
    let mut selected = balloon(region)?;
    if selected.is_none() && matches!(region.kind.as_str(), "speech" | "thought" | "balloon") {
        selected = masks::find_balloon(page, bounds(region)?, dark).map_err(failed)?;
    }
    masks::region_mask(
        page,
        bounds(region)?,
        selected,
        dark,
        masks::MaskOptions {
            solid_free: solid || region.erase,
            full_balloon: selected.is_some(),
            ..Default::default()
        },
    )
    .map_err(failed)
}

pub fn mask(path: &Path, solid: bool) -> Result<Value> {
    write_doc(path, "masks", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let policy = loaded.document.policy().to_owned();
        let mut total = 0;
        for page in &mut loaded.document.pages {
            let image = original(&root, page)?;
            let mut mask = GrayImage::new(page.width, page.height);
            for region in &mut page.regions {
                if editable(region, &policy) {
                    let local = region_mask(&image, region, solid)?;
                    local.apply_to(&mut mask).map_err(failed)?;
                    region.mask = Some(save_image(
                        &root,
                        "masks",
                        &region.id,
                        DynamicImage::ImageLuma8(local.pixels),
                    )?);
                    region
                        .extra
                        .insert("mask_bounds".into(), json!(local.bounds));
                    total += 1;
                } else {
                    region.mask = None;
                    region.extra.remove("mask_bounds");
                }
            }
            page.extra.insert(
                "mask".into(),
                json!(save_image(
                    &root,
                    "masks",
                    &page.id,
                    DynamicImage::ImageLuma8(mask)
                )?),
            );
        }
        stamp(loaded, "masks")?;
        Ok(json!({"masks":total}))
    })
}

pub fn crop_region(region: &RegionRecord) -> Result<crops::CropRegion> {
    Ok(crops::CropRegion {
        id: region.id.clone(),
        bounds: bounds(region)?,
        balloon: balloon(region)?.map(|b| b.bounds),
        kind: region.kind.clone(),
    })
}

pub fn crops(path: &Path) -> Result<Value> {
    write_doc(path, "crops", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let mut count = 0;
        for page in &mut loaded.document.pages {
            let image = original(&root, page)?;
            let regions = page
                .regions
                .iter()
                .map(crop_region)
                .collect::<Result<Vec<_>>>()?;
            for (record, region) in page.regions.iter_mut().zip(&regions) {
                let crop = crops::crop_for(&image, region).map_err(failed)?;
                record.extra.insert(
                    "crop".into(),
                    json!(save_image(
                        &root,
                        "crops",
                        &record.id,
                        DynamicImage::ImageRgb8(crop)
                    )?),
                );
                count += 1;
            }
            let overview = crops::render_overview(&image, &regions).map_err(failed)?;
            page.extra.insert(
                "overview".into(),
                json!(save_image(
                    &root,
                    "sheets",
                    &page.id,
                    DynamicImage::ImageRgb8(overview.image)
                )?),
            );
            page.extra
                .insert("overview_scale".into(), json!(overview.scale));
            let paths = crops::render_sheets(&image, &regions)
                .map_err(failed)?
                .into_iter()
                .enumerate()
                .map(|(i, sheet)| {
                    save_image(
                        &root,
                        "sheets",
                        &format!("{}-sheet-{}", page.id, i + 1),
                        DynamicImage::ImageRgb8(sheet),
                    )
                })
                .collect::<Result<Vec<_>>>()?;
            page.extra.insert("sheets".into(), json!(paths));
        }
        stamp(loaded, "crops")?;
        Ok(json!({"crops":count}))
    })
}

pub fn falint(path: &Path, fix: bool) -> Result<(Value, i32)> {
    let apply = |document: &mut revayat_ir::ComicDocument| -> Result<Value> {
        let mut findings = Vec::new();
        let mut changed = 0;
        for region in document.pages.iter_mut().flat_map(|p| &mut p.regions) {
            if region.target_text.is_empty() {
                continue;
            }
            if fix && !region.locked {
                let fixed = falint::fix_text(&region.target_text, falint::Options::default())
                    .map_err(failed)?;
                changed += usize::from(fixed != region.target_text);
                region.target_text = fixed;
            }
            let issues = falint::lint_text(&region.target_text).map_err(failed)?;
            if !issues.is_empty() {
                findings.push(json!({"region":region.id,"issues":issues}));
            }
        }
        Ok(json!({"ok":findings.is_empty(),"changed":changed,"findings":findings}))
    };
    let value = if fix {
        write_doc(path, "falint", |loaded| apply(&mut loaded.document))?
    } else {
        apply(&mut ir::load_doc(path).map_err(failed)?)?
    };
    let code = i32::from(value["ok"] != true);
    Ok((value, code))
}

fn local_mask(root: &Path, region: &RegionRecord) -> Result<Option<masks::RegionMask>> {
    let Some(path) = &region.mask else {
        return Ok(None);
    };
    let bounds = region
        .extra
        .get("mask_bounds")
        .ok_or_else(|| failed("missing region mask bounds"))
        .and_then(|bounds| serde_json::from_value(bounds.clone()).map_err(failed))?;
    let pixels = images::load_image(&asset(root, path)?, MAX_PAGE_PIXELS)
        .map_err(failed)?
        .into_luma8();
    Ok(Some(masks::RegionMask { bounds, pixels }))
}

fn image_at(directory: &Path, page: &PageRecord) -> Result<RgbImage> {
    let name = format!("{}.png", safe_id(&page.id)?);
    Ok(
        images::load_image(&asset(directory, &name)?, MAX_PAGE_PIXELS)
            .map_err(failed)?
            .into_rgb8(),
    )
}

fn read_mask(root: &Path, page: &PageRecord, field: &str) -> Result<GrayImage> {
    if let Some(path) = page.extra.get(field).and_then(Value::as_str) {
        Ok(images::load_image(&asset(root, path)?, MAX_PAGE_PIXELS)
            .map_err(failed)?
            .into_luma8())
    } else {
        Ok(GrayImage::new(page.width, page.height))
    }
}

pub fn clean(path: &Path, bubbles_only: bool, external: Option<&Path>) -> Result<Value> {
    write_doc(path, "clean", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let policy = loaded.document.policy().to_owned();
        for page in &mut loaded.document.pages {
            let image = original(&root, page)?;
            let external = external
                .map(|directory| image_at(directory, page))
                .transpose()?;
            let mut balloons = Vec::new();
            for region in &page.regions {
                if editable(region, &policy)
                    && (bubbles_only || external.is_none())
                    && let Some(balloon) = balloon(region)?
                {
                    balloons.push(balloon);
                }
            }
            let mut cleaned = clean::clean_page_bubbles(&image, &balloons).map_err(failed)?;
            if !bubbles_only {
                for region in &mut page.regions {
                    if !editable(region, &policy)
                        || (external.is_none() && balloon(region)?.is_some())
                    {
                        continue;
                    }
                    let mask = local_mask(&root, region)?
                        .ok_or_else(|| failed("missing region mask; run mask first"))?;
                    mask.apply_to(&mut cleaned.mask).map_err(failed)?;
                    let (image, strategy) =
                        clean::clean_region(&cleaned.image, &mask, None, external.as_ref())
                            .map_err(failed)?;
                    cleaned.image = image;
                    region.fill = serde_json::to_value(strategy)
                        .map_err(failed)?
                        .as_str()
                        .unwrap_or("cleaned")
                        .to_owned();
                }
            }
            page.extra.insert(
                "clean_mask".into(),
                json!(save_image(
                    &root,
                    "clean",
                    &format!("{}-mask", page.id),
                    DynamicImage::ImageLuma8(cleaned.mask)
                )?),
            );
            page.cleaned = Some(save_image(
                &root,
                "clean",
                &page.id,
                DynamicImage::ImageRgb8(cleaned.image),
            )?);
            page.extra.insert(
                "cleaning".into(),
                json!({
                    "size": [page.width, page.height], "source": page.sha256,
                    "mask": digest(&root, page.extra.get("mask").and_then(Value::as_str))?,
                    "clean": digest(&root, page.cleaned.as_deref())?,
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

fn reading_clean(root: &Path, page: &PageRecord) -> Result<RgbImage> {
    let path = page
        .cleaned
        .as_deref()
        .ok_or_else(|| failed("missing cleaned page; run clean first"))?;
    Ok(images::load_image(&asset(root, path)?, MAX_PAGE_PIXELS)
        .map_err(failed)?
        .into_rgb8())
}

pub fn typeset(path: &Path, external: Option<&Path>) -> Result<Value> {
    write_doc(path, "typeset", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let policy = loaded.document.policy().to_owned();
        let mut count = 0;
        for page in &mut loaded.document.pages {
            let cleaned = reading_clean(&root, page)?;
            let source = original(&root, page)?;
            let mut text = Vec::new();
            let mut allowed = read_mask(&root, page, "clean_mask")?;
            for region in &page.regions {
                if !editable(region, &policy) || region.target_text.is_empty() {
                    continue;
                }
                let b = balloon(region)?;
                let mut entry = typeset::TextRegion::new(
                    &region.id,
                    b.map_or(bounds(region)?, |b| b.bounds),
                    &region.target_text,
                );
                if let Some(style) = region.extra.get("style").and_then(Value::as_str) {
                    entry.style = revayat_vision::typestyle::style_flags(style).map_err(failed)?;
                }
                let interior = if let Some(b) = b {
                    revayat_vision::qachecks::balloon_text_interior(&source, b).map_err(failed)?
                } else {
                    let bounds = bounds(region)?;
                    masks::RegionMask {
                        bounds,
                        pixels: GrayImage::from_pixel(bounds.width(), bounds.height(), Luma([255])),
                    }
                };
                interior.apply_to(&mut allowed).map_err(failed)?;
                entry.interior = Some(interior);
                text.push(entry);
            }
            let rendered = if let Some(directory) = external {
                let edited = image_at(directory, page)?;
                clean::composite_external(&cleaned, &edited, &allowed, 0).map_err(failed)?
            } else {
                let output = typeset::typeset_page(&cleaned, &text).map_err(failed)?;
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
                    if let Some(region) = page.regions.iter_mut().find(|r| r.id == decision.id) {
                        region.typeset = serde_json::to_value(decision)
                            .map_err(failed)?
                            .as_object()
                            .cloned()
                            .unwrap_or_default();
                        region.typeset.insert("status".into(), json!("fit"));
                        count += 1;
                    }
                }
                output.image
            };
            if external.is_some() {
                for region in &mut page.regions {
                    if text.iter().any(|entry| entry.id == region.id) {
                        region.typeset =
                            ir::Fields::from_iter([("status".into(), json!("unreliable"))]);
                    }
                }
            }
            page.extra.insert(
                "authorized_mask".into(),
                json!(save_image(
                    &root,
                    "rendered",
                    &format!("{}-mask", page.id),
                    DynamicImage::ImageLuma8(allowed)
                )?),
            );
            page.rendered = Some(save_image(
                &root,
                "rendered",
                &page.id,
                DynamicImage::ImageRgb8(rendered),
            )?);
            page.extra.insert("delivery".into(), json!({
                "size": [page.width, page.height], "final": digest(&root, page.rendered.as_deref())?,
                "clean": digest(&root, page.cleaned.as_deref())?,
                "writable": digest(&root, page.extra.get("writable").and_then(Value::as_str))?,
            }));
        }
        stamp(loaded, "typeset")?;
        Ok(json!({"pages":loaded.document.pages.len(),"typeset":count}))
    })
}

pub fn fullpage(path: &Path, id: &str, model: String) -> Result<Value> {
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
    let replacements = page
        .regions
        .iter()
        .filter(|r| editable(r, document.policy()) && !r.target_text.is_empty())
        .map(|r| {
            Ok(FullPageReplacement {
                id: r.id.clone(),
                source_text: r.source_text.clone(),
                target_persian: r.target_text.clone(),
                bbox: bounds(r)?,
                location_cue: format!("Region {}, reading position {}", r.id, r.reading_order + 1),
                style_cue: r
                    .extra
                    .get("style")
                    .and_then(Value::as_str)
                    .unwrap_or("Match the weight and emphasis of the source lettering")
                    .to_owned(),
                kind: match r.kind.as_str() {
                    "sfx" => RegionKind::Sfx,
                    "title" => RegionKind::Title,
                    "sign" => RegionKind::OnArt,
                    _ => RegionKind::Balloon,
                },
            })
        })
        .collect::<Result<Vec<_>>>()?;
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

pub fn watermark(path: &Path, specification: &str, from_overview: bool) -> Result<Value> {
    let rect = watermark::parse_box(specification).map_err(failed)?;
    write_doc(path, "watermark", |loaded| {
        for page in &mut loaded.document.pages {
            let mut rect = rect;
            if from_overview {
                let scale = page
                    .extra
                    .get("overview_scale")
                    .and_then(Value::as_f64)
                    .filter(|n| (0.0..=1.0).contains(n) && *n > 0.0)
                    .ok_or_else(|| failed("missing overview scale; run crops first"))?;
                rect = Rect(rect.0.map(|n| (f64::from(n) / scale).round() as u32));
            }
            let mark = watermark::mark_page(
                format!("{}-watermark", page.id),
                rect,
                (page.width, page.height),
            )
            .map_err(failed)?;
            let mut region = ir::new_region(
                mark.id,
                mark.bounds.0.map(f64::from),
                "watermark",
                "horizontal",
                "manual",
                1.0,
            )
            .map_err(failed)?;
            region.erase = mark.erase;
            region.locked = mark.locked;
            if let Some(existing) = page.regions.iter_mut().find(|r| r.id == region.id) {
                *existing = region;
            } else {
                page.regions.push(region);
            }
        }
        stamp(loaded, "watermark")?;
        Ok(json!({"marked":loaded.document.pages.len()}))
    })
}

pub fn qa(path: &Path, strict: bool) -> Result<Value> {
    let document = ir::load_doc(path).map_err(failed)?;
    let root = ir::doc_dir(path);
    let mut findings = Vec::new();
    let mut changed = 0;
    let mut errors = 0;
    let mut warnings = 0;
    for page in &document.pages {
        let image = original(&root, page)?;
        let clean = if page.cleaned.is_some() {
            reading_clean(&root, page)?
        } else {
            image.clone()
        };
        let rendered = page
            .rendered
            .as_deref()
            .map(|path| -> Result<RgbImage> {
                Ok(images::load_image(&asset(&root, path)?, MAX_PAGE_PIXELS)
                    .map_err(failed)?
                    .into_rgb8())
            })
            .transpose()?;
        let mask = read_mask(
            &root,
            page,
            if rendered.is_some() {
                "authorized_mask"
            } else {
                "clean_mask"
            },
        )?;
        let mut regions = Vec::new();
        for region in &page.regions {
            if !editable(region, document.policy()) {
                continue;
            }
            if regions::region_state(region, document.policy()).map_err(failed)?
                == revayat_ir::RegionState::Pending
            {
                findings.push(json!({"code":"pending-region","page":page.id,"region":region.id}));
                if strict {
                    errors += 1;
                } else {
                    warnings += 1;
                }
            }
            if region.target_text.is_empty() {
                continue;
            }
            if rendered.is_none()
                || region.typeset.get("status").and_then(Value::as_str) != Some("fit")
            {
                findings.push(
                    json!({"code":"missing-typeset-proof","page":page.id,"region":region.id}),
                );
                if strict {
                    errors += 1;
                } else {
                    warnings += 1;
                }
            }
            regions.push(qa::QaRegion {
                id: &region.id,
                target: &region.target_text,
                balloon: balloon(region)?,
                ink_box: region
                    .typeset
                    .get("ink_box")
                    .map(|b| serde_json::from_value(b.clone()))
                    .transpose()
                    .map_err(failed)?,
                font_size: region
                    .typeset
                    .get("font_size")
                    .and_then(Value::as_f64)
                    .map(|n| n as f32),
                line_height: region
                    .typeset
                    .get("line_height")
                    .and_then(Value::as_f64)
                    .map(|n| n as f32),
            });
        }
        let result = qa::run_strict_qa(qa::QaPage {
            original: &image,
            cleaned: &clean,
            final_image: rendered.as_ref().unwrap_or(&clean),
            authorized: &mask,
            regions: &regions,
        })
        .map_err(failed)?;
        errors += result.errors;
        warnings += result.warnings;
        changed += result.artwork_pixels_changed;
        findings.extend(
            result
                .findings
                .into_iter()
                .map(|finding| json!({"page":page.id,"finding":finding})),
        );
    }
    Ok(
        json!({"ok":errors == 0 && (!strict || warnings == 0),"errors":errors,"warnings":warnings,"artwork_pixels_changed":changed,"findings":findings}),
    )
}
