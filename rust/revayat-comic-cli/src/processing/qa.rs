use super::lettering::{excluded_balloon_regions, protected_japanese, read_mask, reading_clean};
use super::*;
use revayat_vision::qa;

const MISSING_GLYPH_COVERAGE: &str = "missing-glyph-coverage";
const MISSING_TYPESET_PROOF: &str = "missing-typeset-proof";
const PENDING_REGION: &str = "pending-region";

pub fn qa(path: &Path, strict: bool) -> Result<Value> {
    let document = ir::load_doc(path).map_err(failed)?;
    let root = ir::doc_dir(path);
    let mut findings = Vec::new();
    let mut changed = 0;
    let mut errors = 0;
    let mut warnings = 0;
    let mut shaper = revayat_vision::typefont::Shaper::new().map_err(failed)?;
    for finding in revayat_ir::certify::certify_publication(&root, &document).map_err(failed)? {
        findings.push(json!(finding));
        if strict {
            errors += 1;
        } else {
            warnings += 1;
        }
    }
    for page in &document.pages {
        let native = original_native(&root, page)?;
        let image = native.to_rgb8();
        let native_clean = page
            .cleaned
            .as_deref()
            .map(|path| -> Result<DynamicImage> {
                images::load_image(&asset(&root, path)?, MAX_PAGE_PIXELS).map_err(failed)
            })
            .transpose()?;
        let clean = native_clean.as_ref().unwrap_or(&native).to_rgb8();
        let native_rendered = page
            .rendered
            .as_deref()
            .map(|path| -> Result<DynamicImage> {
                images::load_image(&asset(&root, path)?, MAX_PAGE_PIXELS).map_err(failed)
            })
            .transpose()?;
        let rendered = native_rendered.as_ref().map(DynamicImage::to_rgb8);
        let mask = read_mask(
            &root,
            page,
            if rendered.is_some() {
                "authorized_mask"
            } else {
                "clean_mask"
            },
        )?;
        let native_changed = images::count_changed_outside_mask(
            &native,
            native_rendered
                .as_ref()
                .or(native_clean.as_ref())
                .unwrap_or(&native),
            &mask,
        )
        .map_err(failed)?
        .max(
            images::count_changed_outside_mask(
                &native,
                native_clean.as_ref().unwrap_or(&native),
                &mask,
            )
            .map_err(failed)?,
        );
        let mut regions = Vec::new();
        let panels = page_panels(page)?;
        let source_lang = document.meta.get("source_language").and_then(Value::as_str);
        let rtl_target =
            ir::is_rtl_language(document.meta.get("target_language").and_then(Value::as_str));
        let neighbors = on_art_bounds(page)?;
        for region in &page.regions {
            if protected_japanese(source_lang, region) {
                let tampered = editable(region, document.policy())
                    || region.erase
                    || region.state == Some(regions::RegionState::Erased)
                    || rendered.as_ref().is_some_and(|final_page| {
                        bounds(region).ok().is_some_and(|b| {
                            (b.y()..b.bottom().min(image.height())).any(|y| {
                                (b.x()..b.right().min(image.width())).any(|x| {
                                    revayat_vision::qachecks::pixel_changed(
                                        image.get_pixel(x, y),
                                        final_page.get_pixel(x, y),
                                    )
                                })
                            })
                        })
                    });
                if tampered {
                    findings.push(json!({"code":"protected-japanese-modified","page":page.id,"region":region.id}));
                    if strict {
                        errors += 1;
                    } else {
                        warnings += 1;
                    }
                }
                continue;
            }
            if !editable(region, document.policy()) {
                continue;
            }
            if regions::region_state(region, document.policy()).map_err(failed)?
                == revayat_ir::RegionState::Pending
            {
                findings.push(json!({"code":PENDING_REGION,"page":page.id,"region":region.id}));
                if strict {
                    errors += 1;
                } else {
                    warnings += 1;
                }
            }
            if region.target_text.is_empty() {
                if region.erase || region.state == Some(regions::RegionState::Erased) {
                    regions.push(qa::QaRegion {
                        id: &region.id,
                        target: "",
                        balloon: resolve_balloon(&image, region, &panels, &neighbors, None)?,
                        ink_box: None,
                        font_size: None,
                        line_height: None,
                    });
                }
                continue;
            }
            if rendered.is_none()
                || !matches!(
                    region.typeset.get("status").and_then(Value::as_str),
                    Some("fit" | "external")
                )
            {
                findings
                    .push(json!({"code":MISSING_TYPESET_PROOF,"page":page.id,"region":region.id}));
                if strict {
                    errors += 1;
                } else {
                    warnings += 1;
                }
            }
            if let Some(final_page) = &rendered
                && region.typeset.get("status").and_then(Value::as_str) == Some("fit")
            {
                let lines = region
                    .typeset
                    .get("lines")
                    .cloned()
                    .map_or_else(|| Ok(Vec::new()), serde_json::from_value)
                    .map_err(failed)?;
                let mut style = region
                    .extra
                    .get("style")
                    .and_then(Value::as_str)
                    .map_or_else(
                        || Ok(Default::default()),
                        revayat_vision::typestyle::style_flags,
                    )
                    .map_err(failed)?;
                if region.typeset.get("weight").and_then(Value::as_str) == Some("medium") {
                    style.medium = true;
                }
                let size = region
                    .typeset
                    .get("font_size")
                    .and_then(Value::as_f64)
                    .unwrap_or_default() as f32;
                let missing = qa::missing_clusters_in_direction(
                    &mut shaper,
                    &region.target_text,
                    &lines,
                    size,
                    &style,
                    &clean,
                    final_page,
                    rtl_target,
                );
                if !matches!(missing, Ok(0)) {
                    errors += 1;
                    findings.push(json!({"code":MISSING_GLYPH_COVERAGE, "page":page.id, "region":region.id, "detail":missing.map_or_else(|err| err.to_string(), |count| format!("{count} shaped clusters have no matching ink"))}));
                }
            }
            regions.push(qa::QaRegion {
                id: &region.id,
                target: &region.target_text,
                balloon: resolve_balloon(&image, region, &panels, &neighbors, None)?,
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
        let acknowledged = page
            .regions
            .iter()
            .map(review::acknowledged)
            .collect::<Vec<_>>();
        let spans = page
            .regions
            .iter()
            .map(review::acknowledged_spans)
            .collect::<Vec<_>>();
        let reviews = page
            .regions
            .iter()
            .enumerate()
            .map(|(index, region)| qa::QaTextReview {
                region: &region.id,
                acknowledged: &acknowledged[index],
                spans: spans[index].as_deref(),
            })
            .collect::<Vec<_>>();
        let mut result = qa::run_strict_qa_with_reviews(
            qa::QaPage {
                original: &image,
                cleaned: &clean,
                final_image: rendered.as_ref().unwrap_or(&clean),
                authorized: &mask,
                regions: &regions,
            },
            &reviews,
        )
        .map_err(failed)?;
        let excluded = excluded_balloon_regions(page, document.policy(), source_lang)?;
        for finding in &mut result.findings {
            if finding.code != "balloon-ink-survives" {
                continue;
            }
            let Some(balloon) = regions
                .iter()
                .find(|region| finding.region.as_deref() == Some(region.id))
                .and_then(|region| region.balloon)
            else {
                continue;
            };
            let mut interior = revayat_vision::qachecks::balloon_cleanup_interior(&image, balloon)
                .map_err(failed)?;
            interior.exclude(&excluded);
            let b = interior.bounds;
            let paper =
                image::imageops::crop_imm(&clean, b.x(), b.y(), b.width(), b.height()).to_image();
            let gray = masks::page_luminance(&paper);
            let samples = gray
                .iter()
                .zip(interior.pixels.iter())
                .filter_map(|(&p, &m)| {
                    let luma = if balloon.dark { 255 - p } else { p };
                    (m != 0 && luma > 185).then_some(u64::from(luma))
                });
            let (sum, count) = samples.fold((0u64, 0u64), |(sum, count), v| (sum + v, count + 1));
            let Some(paper_luma) = sum.checked_div(count) else {
                continue;
            };
            let ink = gray
                .iter()
                .zip(interior.pixels.iter())
                .filter(|&(&p, &m)| {
                    let luma = if balloon.dark { 255 - p } else { p };
                    m != 0 && paper_luma.abs_diff(u64::from(luma)) >= 38
                })
                .count();
            if ink == 0 {
                finding.code.clear();
                result.errors -= 1;
            } else {
                finding.detail = format!("{ink} ink pixels remain in the cleared balloon");
            }
        }
        result.findings.retain(|finding| !finding.code.is_empty());
        if native_changed > result.artwork_pixels_changed {
            errors += 1;
            findings.push(json!({"code":"artwork-changed","page":page.id,"detail":format!("{native_changed} pixels changed outside authorized masks, including native precision and alpha")}));
        }
        errors += result.errors;
        warnings += result.warnings;
        changed += native_changed;
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

#[cfg(test)]
mod contract_tests {
    use super::*;

    #[test]
    fn cli_qa_findings_have_documented_recovery_actions() {
        let guide = include_str!("../../../../skills/revayat-comic/SKILL.md");
        for code in [
            MISSING_GLYPH_COVERAGE,
            MISSING_TYPESET_PROOF,
            PENDING_REGION,
        ] {
            assert!(
                guide.contains(&format!("| `{code}` |")),
                "undocumented QA code: {code}"
            );
        }
    }
}
