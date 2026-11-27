use image::{GrayImage, Luma};
use revayat_vision::{
    Rect, Result, bidi, falint,
    fullpage_edit::{FullPageEditRequest, FullPageReplacement, RegionKind, build_fullpage_prompt},
    typefit::partition_shared_interiors,
};

#[test]
fn digit_modes_preserve_links_logical_marks_and_are_idempotent() -> Result<()> {
    let source = "خانهٔ ما ۱۵ اتاق و ٠٥ در دارد. https://example.test/۱۵ a۱۵@example.test";
    for (digits, expected) in [
        (
            falint::Digits::Latin,
            "خانهٔ ما 15 اتاق و 05 در دارد. https://example.test/۱۵ a۱۵@example.test",
        ),
        (
            falint::Digits::Persian,
            "خانهٔ ما ۱۵ اتاق و ۰۵ در دارد. https://example.test/۱۵ a۱۵@example.test",
        ),
        (falint::Digits::Keep, source),
    ] {
        let options = falint::Options {
            digits,
            ..Default::default()
        };
        let fixed = falint::fix_text(source, options)?;
        assert_eq!(fixed, expected);
        assert_eq!(falint::fix_text(&fixed, options)?, fixed);
        assert!(bidi::has_logical_order(&fixed)?);
        assert!(
            !falint::lint_with_digits(&fixed, &[], None, digits)?
                .iter()
                .any(|issue| issue.code == "arabic-forms")
        );
    }
    let mixed = "\u{2067}GPU ۱۵ تست را گذراند.\u{2069}";
    let fixed = falint::fix_text(mixed, Default::default())?;
    assert_eq!(fixed, "\u{2067}GPU 15 تست را گذراند.\u{2069}");
    assert!(bidi::has_logical_order(&fixed)?);
    assert_eq!(falint::fix_text(&fixed, Default::default())?, fixed);
    Ok(())
}

#[test]
fn numeric_art_prompt_filter_preserves_dialogue_and_exact_targets() -> Result<()> {
    let mut request = FullPageEditRequest {
        page_id: "p1".into(),
        cleaned_page_path: "clean/page.png".into(),
        original_page_path: "pages/page.png".into(),
        page_size: [300, 300],
        model_id: "test-model".into(),
        replacements: Vec::new(),
    };
    for (index, kind) in [
        RegionKind::Sfx,
        RegionKind::Title,
        RegionKind::Cover,
        RegionKind::OnArt,
        RegionKind::Balloon,
    ]
    .into_iter()
    .enumerate()
    {
        request.replacements.push(FullPageReplacement {
            id: format!("r{index}"),
            source_text: "\u{2067}00 : 00\u{2069}".into(),
            target_persian: "00:00".into(),
            bbox: Rect([10, 10 + index as u32 * 20, 30, 10]),
            location_cue: String::new(),
            style_cue: String::new(),
            kind,
        });
    }
    let target = "خانهٔ ما 15 اتاق دارد؛ می‌آیی؟";
    request.replacements.push(FullPageReplacement {
        id: "caption".into(),
        source_text: "15 rooms".into(),
        target_persian: target.into(),
        bbox: Rect([10, 130, 100, 20]),
        location_cue: String::new(),
        style_cue: String::new(),
        kind: RegionKind::OnArt,
    });
    let manifest = build_fullpage_prompt(&request)?;
    assert_eq!(manifest.regions.len(), 2);
    assert_eq!(manifest.regions[0].replacement.id, "r4");
    assert_eq!(manifest.regions[0].replacement.kind, RegionKind::Balloon);
    assert_eq!(manifest.regions[1].replacement.target_persian, target);
    assert_eq!(manifest, build_fullpage_prompt(&request)?);
    assert_eq!(
        manifest.edit_image_arguments()["reference_images"][0]["path"],
        "clean/page.png"
    );
    Ok(())
}

#[test]
fn twin_lobe_partitions_are_disjoint_confined_and_offset_invariant() -> Result<()> {
    let mask = GrayImage::from_fn(180, 120, |x, y| {
        let lobe = [49, 135]
            .into_iter()
            .any(|cx| x.abs_diff(cx).pow(2) + y.abs_diff(60).pow(2) < 38 * 38);
        let neck = (49..135).contains(&x) && y.abs_diff(60) <= 3;
        Luma([if lobe || neck { 255 } else { 0 }])
    });
    let local = [Rect([18, 55, 12, 10]), Rect([106, 55, 12, 10])];
    let baseline = partition_shared_interiors(&mask, [0, 0], &local, 1)?;
    assert!(baseline.iter().all(|m| m.pixels().any(|p| p[0] != 0)));
    for origin in [[37, 83], [u32::MAX - 180, u32::MAX - 120]] {
        let anchors =
            local.map(|b| Rect([b.x() + origin[0], b.y() + origin[1], b.width(), b.height()]));
        assert_eq!(
            partition_shared_interiors(&mask, origin, &anchors, 1)?,
            baseline
        );
    }
    for (index, allowed) in mask.as_raw().iter().enumerate() {
        let first = baseline[0].as_raw()[index] != 0;
        let second = baseline[1].as_raw()[index] != 0;
        assert!(!(first && second));
        assert!(!(first || second) || *allowed != 0);
    }
    Ok(())
}

#[test]
fn open_balloon_residual_qa_ignores_preserved_panel_art() -> Result<()> {
    use image::{Rgb, RgbImage};
    use revayat_vision::{clean, masks, qachecks};

    for dark in [false, true] {
        let panel = Rect([20, 20, 120, 100]);
        let text = Rect([36, 46, 20, 20]);
        let original = RgbImage::from_fn(160, 140, |x, y| {
            let paper = (20..100).contains(&x) && (20..120).contains(&y);
            let glyph = (42..48).contains(&x) && (52..58).contains(&y);
            let artwork = (79..83).contains(&x) && (99..103).contains(&y);
            let luminance = if paper && !glyph && !artwork { 245 } else { 20 };
            Rgb([if dark { 255 - luminance } else { luminance }; 3])
        });
        let balloon = masks::resolve_balloon(&original, text, None, Some(panel), dark)?
            .expect("the open component is bounded by the panel");
        assert!(qachecks::full_balloon_surviving_ink(&original, &original, balloon)? > 0);
        let cleaned = clean::clean_page_bubbles(&original, &[balloon])?;
        assert_eq!(cleaned.mask.get_pixel(80, 100)[0], 0);
        assert_eq!(
            cleaned.image.get_pixel(80, 100),
            original.get_pixel(80, 100)
        );
        assert_eq!(
            qachecks::full_balloon_surviving_ink(&original, &cleaned.image, balloon)?,
            0,
            "art outside the open text window is not uncleared source lettering"
        );
    }
    Ok(())
}

#[test]
fn closed_balloon_residual_qa_still_checks_ink_away_from_the_source_anchor() -> Result<()> {
    use image::{Rgb, RgbImage};
    use revayat_vision::{clean, masks, qachecks};

    for dark in [false, true] {
        let original = RgbImage::from_fn(160, 140, |x, y| {
            let paper = (20..100).contains(&x) && (20..120).contains(&y);
            let glyph = (42..48).contains(&x) && (52..58).contains(&y);
            let luminance = if paper && !glyph { 245 } else { 20 };
            Rgb([if dark { 255 - luminance } else { luminance }; 3])
        });
        let balloon = masks::resolve_balloon(&original, Rect([36, 46, 20, 20]), None, None, dark)?
            .expect("the balloon is closed");
        let mut cleaned = clean::clean_page_bubbles(&original, &[balloon])?.image;
        assert_eq!(
            qachecks::full_balloon_surviving_ink(&original, &cleaned, balloon)?,
            0
        );
        for y in 99..103 {
            for x in 79..83 {
                cleaned.put_pixel(x, y, Rgb([if dark { 235 } else { 20 }; 3]));
            }
        }
        assert!(qachecks::full_balloon_surviving_ink(&original, &cleaned, balloon)? > 0);
    }
    Ok(())
}
