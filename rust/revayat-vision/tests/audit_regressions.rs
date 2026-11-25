use image::{Rgb, RgbImage};
use revayat_vision::{
    Rect, Result, bidi, lettering,
    masks::{Balloon, balloon_interior, resolve_balloon},
    qa::missing_clusters,
    typefont::Shaper,
    typeset::{TextRegion, typeset_page},
};

fn paired_balloons() -> RgbImage {
    RgbImage::from_fn(180, 100, |x, y| {
        let inside = [45.0, 135.0].into_iter().any(|cx| {
            let dx = (f64::from(x) - cx) / 35.0;
            let dy = (f64::from(y) - 50.0) / 40.0;
            dx * dx + dy * dy < 1.0
        });
        Rgb([if inside { 245 } else { 40 }; 3])
    })
}

#[test]
fn saved_balloon_uses_the_current_text_anchor() -> Result<()> {
    let original = paired_balloons();
    let saved = Balloon {
        bounds: Rect([5, 5, 170, 90]),
        text_bounds: Rect([35, 40, 20, 20]),
        dark: false,
    };
    let current = Rect([125, 40, 20, 20]);
    let resolved = resolve_balloon(&original, current, Some(saved), None, false)?
        .expect("the current text is inside a closed balloon");
    let interior = balloon_interior(&original, resolved, 1)?;
    let active = |x, y| {
        interior.bounds.contains(x, y)
            && interior
                .pixels
                .get_pixel(x - interior.bounds.x(), y - interior.bounds.y())[0]
                != 0
    };
    assert!(
        active(135, 50),
        "the new anchor must select the right balloon"
    );
    assert!(
        !active(45, 50),
        "the old anchor must not authorize the left balloon"
    );
    assert_eq!(resolved.text_bounds, current);
    Ok(())
}

#[test]
fn saved_balloon_cannot_bypass_the_current_panel() -> Result<()> {
    let original = paired_balloons();
    let text = Rect([35, 40, 20, 20]);
    let saved = Balloon {
        bounds: Rect([5, 5, 80, 90]),
        text_bounds: text,
        dark: false,
    };
    assert!(
        resolve_balloon(
            &original,
            text,
            Some(saved),
            Some(Rect([90, 0, 90, 100])),
            false,
        )?
        .is_none(),
        "a cached contour cannot grant permission outside the selected panel"
    );
    Ok(())
}

#[test]
fn glyph_proof_rejects_removed_persian_join_controls() -> Result<()> {
    let clean = RgbImage::from_pixel(220, 100, Rgb([245; 3]));
    let rendered_text = "میرود";
    let request = TextRegion::new("word", Rect([10, 10, 200, 80]), rendered_text);
    let style = request.style.clone();
    let output = typeset_page(&clean, &[request])?;
    let placed = &output.regions[0];
    let mut shaper = Shaper::new()?;
    assert_eq!(
        missing_clusters(
            &mut shaper,
            rendered_text,
            &placed.lines,
            placed.font_size,
            &style,
            &clean,
            &output.image,
        )?,
        0,
    );
    for authored in ["می‌رود", "می رود", "می\u{200d}رود"] {
        assert!(
            missing_clusters(
                &mut shaper,
                authored,
                &placed.lines,
                placed.font_size,
                &style,
                &clean,
                &output.image,
            )? > 0,
            "the rendered proof must not silently accept a changed word: {authored}"
        );
    }
    Ok(())
}

#[test]
fn glyph_proof_accepts_punctuation_after_an_authored_hard_break() -> Result<()> {
    let clean = RgbImage::from_pixel(220, 200, Rgb([245; 3]));
    let target = "سلام\n…";
    let request = TextRegion::new("break", Rect([10, 10, 200, 180]), target);
    let style = request.style.clone();
    let output = typeset_page(&clean, &[request])?;
    let placed = &output.regions[0];
    assert_eq!(placed.lines.len(), 2);
    assert_eq!(
        missing_clusters(
            &mut Shaper::new()?,
            target,
            &placed.lines,
            placed.font_size,
            &style,
            &clean,
            &output.image,
        )?,
        0,
    );
    Ok(())
}

#[test]
fn typesetting_keeps_embedded_latin_isolates_balanced() -> Result<()> {
    let page = RgbImage::from_pixel(420, 150, Rgb([245; 3]));
    let text = "این \u{2066}ABC\u{2069} خوب است.";
    assert!(bidi::has_logical_order(text)?);
    let mut request = TextRegion::new("isolate", Rect([10, 10, 400, 130]), text);
    request.min_size = 24;
    request.max_size = 24;
    let output = typeset_page(&page, &[request])?;
    assert_eq!(output.regions[0].logical_text, text);
    for line in &output.regions[0].lines {
        assert!(bidi::has_logical_order(&line.text)?, "{:?}", line.text);
    }
    assert!(
        output.regions[0]
            .lines
            .iter()
            .any(|line| line.text.contains("\u{2066}ABC\u{2069}")),
        "the authored Latin isolate must survive shaping"
    );
    Ok(())
}

#[test]
fn an_embedded_isolate_is_reopened_after_wrapping() -> Result<()> {
    let page = RgbImage::from_pixel(150, 350, Rgb([245; 3]));
    let text = "این \u{2066}ABC DEF GHI JKL MNO\u{2069} خوب است.";
    assert!(bidi::has_logical_order(text)?);
    let mut request = TextRegion::new("wrapped-isolate", Rect([5, 5, 140, 340]), text);
    request.min_size = 24;
    request.max_size = 24;
    let output = typeset_page(&page, &[request])?;
    assert!(output.regions[0].lines.len() >= 3);
    for line in &output.regions[0].lines {
        assert!(bidi::has_logical_order(&line.text)?, "{:?}", line.text);
        if line.text.contains("DEF") || line.text.contains("GHI") {
            assert!(
                line.text.contains('\u{2066}') && line.text.contains('\u{2069}'),
                "wrapped Latin words must retain their authored isolate: {:?}",
                line.text
            );
        }
    }
    Ok(())
}

#[test]
fn curved_lettering_keeps_every_glyph_inside_its_approved_canvas() -> Result<()> {
    let measurement = lettering::Lettering {
        bounds: Rect([0, 0, 180, 60]),
        center: [90.0, 30.0],
        angle: 0.0,
        elongation: 3.0,
        weight: 0.3,
        modulation: 0.0,
        contrast: 3.0,
        curvature: 0.35,
        residual: 0.01,
        taper: 1.0,
        verdict: lettering::Verdict::Curved,
    };
    let rendered = lettering::render(
        "سلام سلام سلام",
        measurement,
        &Default::default(),
        Rect([0, 0, 180, 60]),
        60,
    )?;
    assert!(rendered.pixels().any(|pixel| pixel[0] != 0));
    assert!(
        rendered.enumerate_pixels().all(|(x, y, pixel)| {
            pixel[0] == 0 || (x > 0 && y > 0 && x + 1 < 180 && y + 1 < 60)
        }),
        "a successful fit must retain clearance on all sides instead of clipping the curve"
    );
    Ok(())
}

#[test]
fn lint_reviews_are_scoped_to_their_region_and_preserve_pixel_guards() -> Result<()> {
    use revayat_vision::qa::{QaPage, QaRegion, QaTextReview, run_strict_qa_with_reviews};

    let clean = RgbImage::from_pixel(260, 130, Rgb([245; 3]));
    let request = TextRegion::new("reviewed", Rect([10, 10, 240, 110]), "موهایم تر شد.");
    let output = typeset_page(&clean, &[request])?;
    let item = &output.regions[0];
    let regions = [QaRegion {
        id: &item.id,
        target: &item.logical_text,
        ink_box: Some(item.ink_box),
        balloon: None,
        font_size: Some(item.font_size),
        line_height: Some(item.line_height),
    }];
    let page = QaPage {
        original: &clean,
        cleaned: &clean,
        final_image: &output.image,
        authorized: &output.mask,
        regions: &regions,
    };
    let has_review_issue = |report: &revayat_vision::qa::QaReport| {
        report
            .findings
            .iter()
            .any(|finding| finding.code == "zwnj-review")
    };
    assert!(has_review_issue(&run_strict_qa_with_reviews(page, &[])?));
    let acknowledged = ["zwnj-review", "artwork-changed"];
    let review = QaTextReview {
        region: "reviewed",
        acknowledged: &acknowledged,
        spans: None,
    };
    let report = run_strict_qa_with_reviews(page, &[review])?;
    assert!(report.ok, "{:?}", report.findings);
    assert!(has_review_issue(&run_strict_qa_with_reviews(
        page,
        &[QaTextReview {
            region: "other",
            ..review
        }],
    )?));
    let mut damaged = output.image.clone();
    damaged.put_pixel(0, 0, Rgb([0; 3]));
    let report = run_strict_qa_with_reviews(
        QaPage {
            final_image: &damaged,
            ..page
        },
        &[review],
    )?;
    assert!(!report.ok);
    assert_eq!(report.artwork_pixels_changed, 1);
    assert!(
        report
            .findings
            .iter()
            .any(|finding| finding.code == "artwork-changed")
    );
    Ok(())
}

#[test]
fn qa_registry_covers_emitted_lints_and_package_failures() -> Result<()> {
    use revayat_vision::{falint, qa};

    let mut lint_codes = std::collections::BTreeSet::new();
    for text in [
        "كيان",
        "«سلام",
        "\"سلام\"",
        "سلام،،",
        "می رود",
        "This sentence contains no translated Persian words",
        "سلامあ",
        "Aسلام",
        "Hello سلام",
    ] {
        for issue in falint::lint_text(text)? {
            assert!(qa::CODES.contains(&issue.code.as_str()), "{}", issue.code);
            lint_codes.insert(issue.code);
        }
    }
    assert_eq!(lint_codes.len(), 9);
    let approved = RgbImage::from_pixel(2, 2, Rgb([245; 3]));
    for delivered in [
        Vec::new(),
        vec![RgbImage::from_pixel(1, 2, Rgb([245; 3]))],
        vec![RgbImage::from_pixel(2, 2, Rgb([0; 3]))],
    ] {
        let report = qa::check_package(std::slice::from_ref(&approved), &delivered);
        assert!(!report.ok);
        assert!(
            report
                .findings
                .iter()
                .all(|finding| qa::CODES.contains(&finding.code.as_str()))
        );
    }
    Ok(())
}

#[test]
fn gutter_ink_fraction_includes_its_decimal_threshold() {
    let mut gray = vec![0; 100 * 100];
    for y in 29..100 {
        for x in 48..52 {
            gray[y * 100 + x] = 255;
        }
    }
    let panels =
        detectcore_rs::port::find_panel_gutters_with_ink(Some(&gray), 100, 100, 238, 4, 0, 0.29)
            .expect("valid gutter options");
    assert_eq!(panels, [[0, 0, 48, 100], [52, 0, 48, 100]]);
}

#[test]
fn watermark_rejects_partially_out_of_bounds_boxes() {
    for bounds in [
        Rect([90, 20, 50, 10]),
        Rect([20, 90, 10, 50]),
        Rect([90, 90, 50, 50]),
        Rect([90, 20, u32::MAX, 10]),
    ] {
        assert!(
            revayat_vision::watermark::mark_page("stamp", bounds, (100, 100)).is_err(),
            "an invalid requested box must be refused without clipping: {bounds:?}"
        );
    }
}

#[test]
fn watermark_accepts_an_exact_edge_aligned_box() -> Result<()> {
    let bounds = Rect([90, 90, 10, 10]);
    let mark = revayat_vision::watermark::mark_page("stamp", bounds, (100, 100))?;
    assert_eq!(mark.bounds, bounds);
    assert!(mark.erase && mark.locked);
    Ok(())
}

fn detected_text(name: &str, bbox: Rect) -> revayat_vision::detect::DetectedRegion {
    revayat_vision::detect::DetectedRegion {
        bbox,
        balloon: None,
        kind: "speech".into(),
        orientation: "horizontal".into(),
        confidence: 1.0,
        detector: name.into(),
        polarity: "light".into(),
    }
}

#[test]
fn reading_order_finishes_each_panel_before_crossing_the_gutter() -> Result<()> {
    let panels = [Rect([0, 0, 100, 200]), Rect([120, 0, 100, 200])];
    let regions = [
        detected_text("left-bottom", Rect([15, 125, 30, 20])),
        detected_text("right-top", Rect([135, 25, 30, 20])),
        detected_text("gutter", Rect([102, 0, 16, 20])),
        detected_text("right-bottom", Rect([135, 125, 30, 20])),
        detected_text("left-top", Rect([15, 25, 30, 20])),
    ];
    for (rtl, expected) in [
        (
            true,
            [
                "right-top",
                "right-bottom",
                "left-top",
                "left-bottom",
                "gutter",
            ],
        ),
        (
            false,
            [
                "left-top",
                "left-bottom",
                "right-top",
                "right-bottom",
                "gutter",
            ],
        ),
    ] {
        let order = revayat_vision::detect::order_regions(&regions, &panels, rtl, 200)?;
        let actual: Vec<_> = order
            .iter()
            .map(|&i| regions[i].detector.as_str())
            .collect();
        assert_eq!(actual, expected, "rtl={rtl}");
    }
    Ok(())
}

#[test]
fn reading_order_uses_sixty_percent_membership_and_first_matching_panel() -> Result<()> {
    let regions = [
        detected_text("below-threshold", Rect([70, 0, 51, 20])),
        detected_text("at-threshold", Rect([70, 60, 50, 20])),
        detected_text("right", Rect([150, 120, 20, 20])),
    ];
    let panels = [Rect([0, 0, 100, 200]), Rect([120, 0, 100, 200])];
    let order = revayat_vision::detect::order_regions(&regions, &panels, false, 200)?;
    assert_eq!(order, [1, 2, 0]);

    let overlapping = [Rect([0, 0, 140, 200]), Rect([80, 0, 140, 200])];
    let regions = [
        detected_text("both-panels", Rect([100, 20, 20, 20])),
        detected_text("right-only", Rect([170, 120, 20, 20])),
    ];
    let order = revayat_vision::detect::order_regions(&regions, &overlapping, true, 200)?;
    assert_eq!(order, [1, 0]);
    Ok(())
}
