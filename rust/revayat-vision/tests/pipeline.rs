use image::{GrayImage, Luma, Rgb, RgbImage};
use revayat_vision::{
    Rect, VisionError,
    clean::clean_page_bubbles,
    detect::{DetectionOptions, detect_page},
    fullpage_edit::{FullPageEditRequest, FullPageReplacement, RegionKind, build_fullpage_prompt},
    masks::Balloon,
    qa::{QaPage, compare_outside_mask, run_strict_qa},
    typeset::{TextRegion, typeset_page},
};

fn bubble() -> (RgbImage, Balloon) {
    let mut page = RgbImage::from_pixel(300, 300, Rgb([42; 3]));
    for y in 12..118 {
        for x in 20..140 {
            let dx = (f64::from(x) - 80.0) / 58.0;
            let dy = (f64::from(y) - 65.0) / 50.0;
            let radius = dx * dx + dy * dy;
            if radius < 0.88 {
                page.put_pixel(x, y, Rgb([245; 3]));
            } else if radius <= 1.0 {
                page.put_pixel(x, y, Rgb([12; 3]));
            }
        }
    }
    for y in 59..70 {
        for x in (68..75).chain(84..90) {
            page.put_pixel(x, y, Rgb([20; 3]));
        }
    }
    page.put_pixel(105, 81, Rgb([195; 3]));
    let balloon = Balloon {
        bounds: Rect([22, 15, 117, 101]),
        text_bounds: Rect([66, 58, 25, 13]),
        dark: false,
    };
    (page, balloon)
}

#[test]
fn detects_closed_balloon_and_sweeps_a_dot_outside_the_ocr_box() -> Result<(), VisionError> {
    let (original, balloon) = bubble();
    let detected = detect_page(&original, &DetectionOptions::default())?;
    assert!(
        detected
            .regions
            .iter()
            .any(|region| region.balloon.is_some())
    );
    let cleaned = clean_page_bubbles(&original, &[balloon])?;
    assert_eq!(cleaned.image.get_pixel(105, 81), &Rgb([245; 3]));
    assert_eq!(cleaned.image.get_pixel(68, 60), &Rgb([245; 3]));
    assert_eq!(cleaned.image.get_pixel(80, 16), original.get_pixel(80, 16));
    assert_eq!(
        compare_outside_mask(&original, &cleaned.image, &cleaned.mask)?.changed,
        0
    );
    Ok(())
}

#[test]
fn free_lettering_requires_a_cluster_and_stays_low_confidence() -> Result<(), VisionError> {
    let mut page = RgbImage::from_pixel(260, 160, Rgb([255; 3]));
    for x in [25, 42, 59, 140, 157] {
        for y in 45..57 {
            for col in x..x + 10 {
                page.put_pixel(col, y, Rgb([0; 3]));
            }
        }
    }
    let result = detect_page(&page, &DetectionOptions::default())?;
    let regions = result
        .regions
        .iter()
        .filter(|r| r.kind == "sfx")
        .collect::<Vec<_>>();
    assert_eq!(regions.len(), 1);
    assert!(regions[0].bbox.contains(25, 45));
    assert_eq!(regions[0].confidence, 0.35);
    Ok(())
}

#[test]
fn cleaned_and_mask_fitted_balloon_passes_strict_qa() -> Result<(), VisionError> {
    let (original, balloon) = bubble();
    let cleaned = clean_page_bubbles(&original, &[balloon])?;
    let mut text = TextRegion::new("bubble", balloon.bounds, "سلام، خوبی؟!");
    text.interior = Some(revayat_vision::qachecks::balloon_text_interior(
        &original, balloon,
    )?);
    let typeset = typeset_page(&cleaned.image, &[text])?;
    let item = &typeset.regions[0];
    let mut authorization = cleaned.mask;
    for (clean, text) in authorization.pixels_mut().zip(typeset.mask.pixels()) {
        clean[0] = clean[0].max(text[0]);
    }
    let regions = [revayat_vision::qa::QaRegion {
        id: &item.id,
        target: &item.logical_text,
        ink_box: Some(item.ink_box),
        balloon: Some(balloon),
        font_size: Some(item.font_size),
        line_height: Some(item.line_height),
    }];
    let report = run_strict_qa(QaPage {
        original: &original,
        cleaned: &cleaned.image,
        final_image: &typeset.image,
        authorized: &authorization,
        regions: &regions,
    })?;
    assert!(report.ok, "{:?}", report.findings);
    let mut dotted = cleaned.image;
    dotted.put_pixel(105, 81, Rgb([195; 3]));
    let report = run_strict_qa(QaPage {
        original: &original,
        cleaned: &dotted,
        final_image: &typeset.image,
        authorized: &authorization,
        regions: &regions,
    })?;
    assert!(
        report
            .findings
            .iter()
            .any(|f| f.code == "balloon-ink-survives")
    );
    Ok(())
}

#[test]
fn strict_qa_rejects_outside_artwork_changes() -> Result<(), VisionError> {
    let (original, _) = bubble();
    let mut edited = original.clone();
    edited.put_pixel(0, 0, Rgb([43; 3]));
    let mask = GrayImage::from_pixel(original.width(), original.height(), Luma([0]));
    let report = run_strict_qa(QaPage {
        original: &original,
        cleaned: &original,
        final_image: &edited,
        authorized: &mask,
        regions: &[],
    })?;
    assert!(!report.ok);
    assert_eq!(report.artwork_pixels_changed, 1);
    Ok(())
}

#[test]
fn typeset_wraps_narrow_persian_and_leaves_room_between_lines() -> Result<(), VisionError> {
    let original = RgbImage::from_pixel(120, 170, Rgb([255; 3]));
    let region = TextRegion::new("p1r1", Rect([20, 5, 61, 157]), "سلام، خوبی؟! خانهٔ ما...");
    let result = typeset_page(&original, &[region])?;
    assert_eq!(result.regions.len(), 1);
    let region = &result.regions[0];
    assert!(region.lines.len() >= 2);
    assert!(region.line_height >= 1.38 * region.font_size);
    assert!(
        region
            .lines
            .iter()
            .all(|line| !line.text.starts_with(['،', '.', '؟', '!']))
    );
    assert!(region.lines.iter().any(|line| line.text.ends_with("؟!")));
    assert!(result.image.pixels().any(|pixel| pixel[0] < 100));
    Ok(())
}

#[test]
fn layout_refuses_colliding_regions_before_painting() {
    let original = RgbImage::from_pixel(180, 90, Rgb([255; 3]));
    let title = TextRegion::new("title", Rect([20, 15, 130, 60]), "عنوان کتاب");
    let badge = TextRegion::new("badge", Rect([75, 20, 35, 45]), "۲");
    assert!(matches!(
        typeset_page(&original, &[title, badge]),
        Err(VisionError::Overlap { .. })
    ));
}

#[test]
fn manifest_preserves_exact_translation_and_references_only_the_cleaned_full_page()
-> Result<(), VisionError> {
    let request = FullPageEditRequest {
        page_id: "p1".into(),
        cleaned_page_path: "cleaned/p1.png".into(),
        original_page_path: "pages/p1.png".into(),
        page_size: [100, 200],
        model_id: "model".into(),
        replacements: vec![FullPageReplacement {
            id: "p1r1".into(),
            source_text: "Hello".into(),
            target_persian: "سلام، خوبی؟!".into(),
            bbox: Rect([60, 20, 20, 30]),
            location_cue: "first region from left, top-right panel".into(),
            style_cue: "bold lettering".into(),
            kind: RegionKind::OnArt,
        }],
    };
    let manifest = build_fullpage_prompt(&request)?;
    assert_eq!(manifest, build_fullpage_prompt(&request)?);
    assert!(manifest.prompt.contains("FULL PAGE"));
    assert!(manifest.prompt.contains("pixel-for-pixel"));
    assert!(manifest.prompt.contains("سلام، خوبی؟!"));
    assert_eq!(manifest.regions[0].normalized_bounds, [0.6, 0.1, 0.8, 0.25]);
    let payload = manifest.edit_image_arguments();
    assert_eq!(payload["reference_images"][0]["path"], "cleaned/p1.png");
    assert_eq!(
        payload["reference_images"].as_array().map(Vec::len),
        Some(1)
    );
    assert!(payload.get("edit_region").is_none());
    Ok(())
}
