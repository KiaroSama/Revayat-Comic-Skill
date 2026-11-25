mod lettering;
pub use lettering::{clean, fullpage, qa, typeset};

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
            count += page.regions.len();
        }
        stamp(loaded, "detect")?;
        Ok(json!({"regions":count,"pages":loaded.document.pages.len()}))
    })
}

fn bubble_kind(region: &RegionRecord) -> bool {
    matches!(region.kind.as_str(), "speech" | "thought" | "balloon")
}

fn editable(region: &RegionRecord, policy: &str) -> bool {
    regions::may_be_edited(region, policy)
        && (region.erase || regions::translatable(region, policy))
}

fn page_panels(page: &PageRecord) -> Result<Vec<Rect>> {
    page.panels
        .iter()
        .map(|panel| serde_json::from_value(panel.clone()).map_err(failed))
        .collect()
}

fn on_art_bounds(page: &PageRecord) -> Result<Vec<Rect>> {
    page.regions
        .iter()
        .filter(|r| !bubble_kind(r) && !r.dropped)
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
    if let Some(balloon) =
        masks::resolve_balloon(page, text, saved, panel, dark(region)).map_err(failed)?
    {
        return Ok(Some(balloon));
    }
    let full = panel.unwrap_or(Rect([0, 0, page.width(), page.height()]));
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
        masks::resolve_balloon(page, text, None, Some(clipped), dark(region)).map_err(failed)
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
    page: &RgbImage,
    region: &RegionRecord,
    selected: Option<masks::Balloon>,
    solid: bool,
) -> Result<masks::RegionMask> {
    let dark = dark(region);
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
    masks::region_mask(
        page,
        bounds(region)?,
        selected,
        dark,
        masks::MaskOptions {
            solid_free: solid && !bubble_kind(region),
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
            let panels = page_panels(page)?;
            let neighbors = on_art_bounds(page)?;
            for region in &mut page.regions {
                if editable(region, &policy) {
                    let balloon = resolve_balloon(&image, region, &panels, &neighbors, None)?;
                    if let Some(balloon) = balloon {
                        record_balloon(&image, region, balloon)?;
                    }
                    let local = region_mask(&image, region, balloon, solid)?;
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
            if fix {
                let fixed = falint::fix_text(&region.target_text, falint::Options::default())
                    .map_err(failed)?;
                if fixed != region.target_text {
                    changed += 1;
                    region.target_text = fixed;
                    region.typeset.clear();
                }
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
