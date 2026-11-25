use std::{path::Path, time::Duration};

use image::DynamicImage;
use revayat_ir::{context, ir, regions, stages, workspace::LoadedDocument};
use revayat_tools::{
    providers::{OCR_MODEL, ProviderClient, TRANSLATION_MODEL, setting},
    server::StageError,
};
use revayat_vision::{crops, falint};
use serde_json::{Value, json};

use crate::{
    processing,
    stage::{failed, usage},
};

type Result<T> = std::result::Result<T, StageError>;

pub fn context(
    loaded: &LoadedDocument,
    id: &str,
    budget: usize,
    allow_unmerged: bool,
) -> Result<Value> {
    let check = context::preflight(loaded.path(), &loaded.document, id, None, allow_unmerged)
        .map_err(failed)?;
    if !check.ok {
        return Err(failed(context::refusal(&check, loaded.path())));
    }
    context::build(&loaded.document, id, budget).map_err(failed)
}

pub fn ocr(path: &Path, provider: &str, model: Option<String>) -> Result<Value> {
    if provider != "openai" {
        return Err(usage(
            "only the OpenAI-compatible OCR provider is available in this binary",
        ));
    }
    let model = model
        .map_or_else(|| setting(OCR_MODEL), Ok)
        .map_err(failed)?;
    let client = ProviderClient::from_env(Duration::from_secs(30)).map_err(failed)?;
    processing::write_doc(path, "ocr", |loaded| {
        let root = ir::doc_dir(loaded.path()).to_owned();
        let language = loaded
            .document
            .meta
            .get("source_language")
            .and_then(Value::as_str)
            .unwrap_or("auto")
            .to_owned();
        let policy = loaded.document.policy().to_owned();
        let mut transcribed = 0;
        for page in &mut loaded.document.pages {
            if !page
                .regions
                .iter()
                .any(|r| !r.locked && r.source_text.is_empty() && regions::translatable(r, &policy))
            {
                continue;
            }
            let image = processing::original(&root, page)?;
            for region in &mut page.regions {
                if region.locked
                    || !region.source_text.is_empty()
                    || !regions::translatable(region, &policy)
                {
                    continue;
                }
                let crop =
                    crops::crop_for(&image, &processing::crop_region(region)?).map_err(failed)?;
                let bytes = processing::png(&DynamicImage::ImageRgb8(crop))?;
                if let Some(source) = client.ocr(&model, &bytes, &language).map_err(failed)?
                    && !source.trim().is_empty()
                {
                    region.source_text = source;
                    region.review.push("review-hosted-ocr".into());
                    transcribed += 1;
                }
            }
        }
        stages::stamp_stage(&mut loaded.document, "ocr", ir::Fields::new(), None, None)
            .map_err(failed)?;
        Ok(json!({"transcribed":transcribed}))
    })
}

pub fn translate(path: &Path, id: &str, model: Option<String>) -> Result<Value> {
    let model = model
        .map_or_else(|| setting(TRANSLATION_MODEL), Ok)
        .map_err(failed)?;
    let client = ProviderClient::from_env(Duration::from_secs(30)).map_err(failed)?;
    processing::write_doc(path, "translate", |loaded| {
        let data = context(loaded, id, context::CONTEXT_BUDGET, false)?;
        let data = data
            .as_object()
            .ok_or_else(|| failed("invalid translation context"))?;
        let policy = loaded.document.policy().to_owned();
        let page = loaded
            .document
            .find_page_mut(id)
            .ok_or_else(|| usage("unknown page"))?;
        let mut translated = 0;
        for region in &mut page.regions {
            if region.locked
                || region.source_text.is_empty()
                || !region.target_text.is_empty()
                || !regions::translatable(region, &policy)
            {
                continue;
            }
            if let Some(target) = client
                .translate(&model, &region.source_text, data)
                .map_err(failed)?
            {
                let target =
                    falint::fix_text(&target, falint::Options::default()).map_err(failed)?;
                if !ir::looks_like(&target, "fa") {
                    return Err(failed("hosted translation did not return Persian text"));
                }
                region.target_text = target;
                region.review.push("review-hosted-translation".into());
                translated += 1;
            }
        }
        stages::stamp_stage(
            &mut loaded.document,
            "translate",
            ir::Fields::new(),
            None,
            Some(&[id.to_owned()]),
        )
        .map_err(failed)?;
        Ok(json!({"translated":translated}))
    })
}
