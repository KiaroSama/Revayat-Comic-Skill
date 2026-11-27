mod lettering;
pub use lettering::{clean, fullpage, qa, typeset};

use std::{
    fs,
    io::Cursor,
    path::{Component, Path, PathBuf},
    thread,
};

use image::{DynamicImage, GrayImage, ImageEncoder, ImageFormat, Luma, RgbImage};
use revayat_io::{images, inputs::MAX_PAGE_PIXELS};
use revayat_ir::{
    PageRecord, RegionRecord, ir, regions, review, stages,
    workspace::{self, LoadedDocument},
};
use revayat_tools::server::StageError;
use revayat_vision::{Rect, crops, detect, falint, masks, watermark};
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
    if matches!(
        relative
            .components()
            .next()
            .and_then(|part| part.as_os_str().to_str()),
        Some("masks" | "clean" | "rendered" | "crops" | "sheets")
    ) {
        revayat_ir::certify::verify_content_addressed(&root.join(relative)).map_err(failed)?;
    }
    Ok(path)
}

pub fn original(root: &Path, page: &PageRecord) -> Result<RgbImage> {
    Ok(original_native(root, page)?.into_rgb8())
}

fn original_native(root: &Path, page: &PageRecord) -> Result<DynamicImage> {
    let path = asset(root, &page.image)?;
    if ir::sha256_file(&path).map_err(failed)? != page.sha256 {
        return Err(failed("immutable source page changed"));
    }
    let image = images::load_image(&path, MAX_PAGE_PIXELS).map_err(failed)?;
    if (image.width(), image.height()) != (page.width, page.height) {
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
    save_png(root, folder, id, png(&image)?)
}

fn save_mask(root: &Path, id: &str, mask: &GrayImage) -> Result<String> {
    use image::codecs::png::{CompressionType, FilterType, PngEncoder};

    let mut bytes = Vec::new();
    PngEncoder::new_with_quality(&mut bytes, CompressionType::Fast, FilterType::NoFilter)
        .write_image(
            mask.as_raw(),
            mask.width(),
            mask.height(),
            image::ExtendedColorType::L8,
        )
        .map_err(failed)?;
    save_png(root, "masks", id, bytes)
}

fn save_png(root: &Path, folder: &str, id: &str, bytes: Vec<u8>) -> Result<String> {
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

pub fn detect(
    path: &Path,
    mut options: detect::DetectionOptions,
    selection: Option<&[String]>,
) -> Result<Value> {
    write_doc(path, "detect", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let rtl = loaded
            .document
            .meta
            .get("reading_direction")
            .and_then(Value::as_str)
            != Some("ltr");
        options.rtl = rtl;
        let selected: std::collections::BTreeSet<_> =
            workspace::selected_pages(&loaded.document, selection)
                .map_err(failed)?
                .into_iter()
                .map(|page| page.id.clone())
                .collect();
        let mut count = 0;
        let mut processed = Vec::new();
        let mut skipped = Vec::new();
        for page in &mut loaded.document.pages {
            if !selected.contains(&page.id) {
                continue;
            }
            if page
                .regions
                .iter()
                .any(|r| !r.source_text.is_empty() || !r.target_text.is_empty() || r.locked)
            {
                skipped.push(json!({"page":page.id,"reason":"reviewed"}));
                continue;
            }
            let source = original(&root, page)?;
            let found = detect::detect_page(&source, &options).map_err(failed)?;
            let panels = found.panels.clone();
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
                    region
                        .extra
                        .insert("polarity".into(), json!(found.polarity));
                    if let Some(balloon) =
                        resolve_balloon(&source, &region, &panels, &[], found.balloon)?
                    {
                        record_balloon(&source, &mut region, balloon)?;
                    }
                    Ok(region)
                })
                .collect::<Result<Vec<_>>>()?;
            ir::assign_reading_order(page, if rtl { "rtl" } else { "ltr" }, 0.35)
                .map_err(failed)?;
            count += page.regions.len();
            processed.push(page.id.clone());
        }
        stages::stamp_stage(
            &mut loaded.document,
            "detect",
            ir::Fields::new(),
            Some(json!(options)),
            Some(&processed),
        )
        .map_err(failed)?;
        Ok(json!({"regions":count,"pages":processed.len(),"processed":processed,"skipped":skipped}))
    })
}

fn bubble_kind(region: &RegionRecord) -> bool {
    matches!(region.kind.as_str(), "speech" | "thought" | "balloon")
}

fn editable(region: &RegionRecord, policy: &str) -> bool {
    regions::may_be_edited(region, policy)
        && (region.erase
            || region.state == Some(regions::RegionState::Erased)
            || regions::translatable(region, policy))
}

fn page_panels(page: &PageRecord) -> Result<Vec<Rect>> {
    page.panels
        .iter()
        .map(|panel| {
            serde_json::from_value(panel.get("bbox").unwrap_or(panel).clone()).map_err(failed)
        })
        .collect()
}

fn on_art_bounds(page: &PageRecord) -> Result<Vec<Rect>> {
    page.regions
        .iter()
        .filter(|r| !bubble_kind(r) && !r.dropped && r.state != Some(regions::RegionState::Dropped))
        .map(bounds)
        .collect()
}

fn dark(region: &RegionRecord) -> bool {
    region.extra.get("polarity").and_then(Value::as_str) == Some("dark")
}

fn resolve_balloon(
    page: &RgbImage,
    region: &RegionRecord,
    panels: &[Rect],
    neighbors: &[Rect],
    detected: Option<masks::Balloon>,
) -> Result<Option<masks::Balloon>> {
    resolve_region_balloon(
        region,
        panels,
        neighbors,
        detected,
        page.dimensions(),
        |text, saved, panel, dark| {
            masks::resolve_balloon(page, text, saved, panel, dark).map_err(failed)
        },
    )
}

fn resolve_region_balloon<T>(
    region: &RegionRecord,
    panels: &[Rect],
    neighbors: &[Rect],
    detected: Option<masks::Balloon>,
    size: (u32, u32),
    resolve: impl Fn(Rect, Option<masks::Balloon>, Option<Rect>, bool) -> Result<Option<T>>,
) -> Result<Option<T>> {
    if !bubble_kind(region) {
        return Ok(None);
    }
    let text = bounds(region)?;
    let [x, y] = text.center();
    let panel = panels
        .iter()
        .copied()
        .filter(|panel| panel.contains(x, y))
        .min_by_key(|panel| panel.area());
    let saved = detected.or(balloon(region)?);
    if let Some(balloon) = resolve(text, saved, panel, dark(region))? {
        return Ok(Some(balloon));
    }
    let full = panel.unwrap_or(Rect([0, 0, size.0, size.1]));
    let mut clipped = full;
    for &other in neighbors {
        if other.y() >= text.bottom()
            && other.y() - text.bottom() <= text.height()
            && other.x() < text.right()
            && text.x() < other.right()
            && other.y() < clipped.bottom()
        {
            clipped.0[3] = other.y() - clipped.y();
        }
    }
    if clipped != full {
        resolve(text, None, Some(clipped), dark(region))
    } else {
        Ok(None)
    }
}

fn record_balloon(
    page: &RgbImage,
    region: &mut RegionRecord,
    balloon: masks::Balloon,
) -> Result<()> {
    region.extra.insert(
        "balloon".into(),
        masks::balloon_geometry(page, balloon).map_err(failed)?,
    );
    Ok(())
}

fn region_mask(
    page: &GrayImage,
    region: &RegionRecord,
    selected: Option<&masks::RegionMask>,
    solid: bool,
) -> Result<masks::RegionMask> {
    if region.kind == "watermark"
        && (region.erase || region.state == Some(regions::RegionState::Erased))
    {
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
    masks::region_mask_with_interior(
        page,
        bounds(region)?,
        selected,
        dark(region),
        masks::MaskOptions {
            solid_free: solid && !bubble_kind(region),
            full_balloon: selected.is_some(),
            ..Default::default()
        },
    )
    .map_err(failed)
}

fn mask_page(root: &Path, page: &mut PageRecord, policy: &str, solid: bool) -> Result<usize> {
    let image = original(root, page)?;
    let luma = masks::page_luminance(&image);
    drop(image);
    let mut mask = GrayImage::new(page.width, page.height);
    let panels = page_panels(page)?;
    let neighbors = on_art_bounds(page)?;
    let mut count = 0;
    for region in &mut page.regions {
        if !editable(region, policy) {
            region.mask = None;
            region.extra.remove("mask_bounds");
            continue;
        }
        let resolved = resolve_region_balloon(
            region,
            &panels,
            &neighbors,
            None,
            luma.dimensions(),
            |text, saved, panel, dark| {
                masks::resolve_balloon_with_interior(&luma, text, saved, panel, dark)
                    .map_err(failed)
            },
        )?;
        if let Some((balloon, paper)) = &resolved {
            let geometry =
                masks::balloon_geometry_from_interior(*balloon, paper).map_err(failed)?;
            region.extra.insert("balloon".into(), geometry);
        }
        let local = region_mask(
            &luma,
            region,
            resolved.as_ref().map(|(_, paper)| paper),
            solid,
        )?;
        local.apply_to(&mut mask).map_err(failed)?;
        region.mask = Some(save_mask(root, &region.id, &local.pixels)?);
        region
            .extra
            .insert("mask_bounds".into(), json!(local.bounds));
        count += 1;
    }
    page.extra
        .insert("mask".into(), json!(save_mask(root, &page.id, &mask)?));
    Ok(count)
}

pub fn mask(path: &Path, solid: bool) -> Result<Value> {
    write_doc(path, "masks", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let policy = loaded.document.policy().to_owned();
        let largest = loaded
            .document
            .pages
            .iter()
            .map(|p| u64::from(p.width) * u64::from(p.height))
            .max()
            .unwrap_or(1)
            .max(1);
        // Keep concurrent decodes and working masks bounded for oversized pages.
        let memory_cap = (MAX_PAGE_PIXELS / largest).clamp(1, 8) as usize;
        let capacity = thread::available_parallelism()
            .map_or(1, usize::from)
            .min(memory_cap);
        let chunk_size = loaded.document.pages.len().div_ceil(capacity).max(1);
        let total = thread::scope(|scope| {
            let mut workers = Vec::new();
            for pages in loaded.document.pages.chunks_mut(chunk_size) {
                let (root, policy) = (&root, &policy);
                workers.push(scope.spawn(move || {
                    pages.iter_mut().try_fold(0, |sum, page| {
                        Ok(sum + mask_page(root, page, policy, solid)?)
                    })
                }));
            }
            let mut result = Ok(0);
            for worker in workers {
                let count = worker
                    .join()
                    .unwrap_or_else(|_| Err(failed("mask page worker panicked")));
                result = result.and_then(|sum| count.map(|count| sum + count));
            }
            result
        })?;
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

pub fn falint(path: &Path, fix: bool, digits: falint::Digits) -> Result<(Value, i32)> {
    let options = falint::Options {
        digits,
        ..Default::default()
    };
    let apply = |document: &mut revayat_ir::ComicDocument| -> Result<Value> {
        let mut findings = Vec::new();
        let mut changed = 0;
        for region in document.pages.iter_mut().flat_map(|p| &mut p.regions) {
            if region.target_text.is_empty() {
                continue;
            }
            if fix {
                let fixed = falint::fix_text(&region.target_text, options).map_err(failed)?;
                if fixed != region.target_text {
                    changed += 1;
                    region.target_text = fixed;
                    region.typeset.clear();
                }
            }
            let acknowledged = review::acknowledged(region);
            let spans = review::acknowledged_spans(region);
            let issues = falint::lint_with_digits(
                &region.target_text,
                &acknowledged,
                spans.as_deref(),
                digits,
            )
            .map_err(failed)?;
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
