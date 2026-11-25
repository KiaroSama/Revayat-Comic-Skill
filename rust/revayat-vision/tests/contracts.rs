use image::{GrayImage, ImageBuffer, Luma, Rgb, RgbImage};
use revayat_vision::{
    Rect, Result, bidi, crops, falint, lettering, qa, qachecks, sheet, watermark,
};

#[test]
fn falint_fixes_persian_but_leaves_structured_spans_and_ambiguous_words() -> Result<()> {
    let normal = falint::fix_text(
        "كيان , گفت: \"سلام Bob\" 25 ... https://example.org/a.2",
        falint::Options::default(),
    )?;
    assert_eq!(normal, "کیان، گفت: «سلام Bob» ۲۵… https://example.org/a.2");
    assert_eq!(
        falint::fix_text("موهایم تر شد.", falint::Options::default())?,
        "موهایم تر شد."
    );
    assert_eq!(falint::ambiguous_spans("موهایم تر شد.")?, ["موهایم تر"]);
    assert!(
        falint::lint_acknowledged("موهایم تر شد.", &["zwnj-review"], Some(&["موهایم تر"]))?
            .is_empty()
    );
    assert_eq!(
        falint::fix_text(&normal, falint::Options::default())?,
        normal
    );
    Ok(())
}

#[test]
fn bidi_isolates_mixed_sentences_without_reversing_ocr_or_punctuation() -> Result<()> {
    let text = "Dr. Asano رسید؟! Oslo نرسید.";
    let isolated = "\u{2067}Dr. Asano رسید؟!\u{2069} \u{2067}Oslo نرسید.\u{2069}";
    assert_eq!(bidi::ensure_rli_pdi(text)?, isolated);
    assert_eq!(bidi::ensure_rli_pdi(isolated)?, isolated);
    assert!(bidi::has_logical_order(isolated)?);
    assert!(!bidi::has_logical_order("سلام\u{2069}")?);
    assert!(!bidi::has_logical_order("\u{fe8e}")?);
    Ok(())
}

#[test]
fn package_qa_checks_page_order_and_raster_bytes() {
    let a = RgbImage::from_pixel(3, 2, Rgb([1, 2, 3]));
    let b = RgbImage::from_pixel(3, 2, Rgb([2, 3, 4]));
    assert!(qa::check_package(&[a.clone(), b.clone()], &[a.clone(), b.clone()]).ok);
    let report = qa::check_package(&[a.clone(), b.clone()], &[b, a]);
    assert!(!report.ok);
    assert_eq!(report.errors, 2);
}

#[test]
fn qa_ignores_touching_bounds_and_locates_real_overlap() {
    let boxes = [
        ("title", Rect([0, 0, 25, 20])),
        ("badge", Rect([20, 2, 5, 12])),
        ("text", Rect([25, 0, 10, 10])),
    ];
    let collisions = qachecks::rendered_text_overlaps(&boxes);
    assert_eq!(collisions.len(), 1);
    assert_eq!(collisions[0].intersection, Rect([20, 2, 5, 12]));
}

#[test]
fn watermark_requires_a_small_locked_patch_and_preserves_neighbors() -> Result<()> {
    let mut page = RgbImage::from_pixel(64, 64, Rgb([255; 3]));
    for y in 8..15 {
        for x in 12..23 {
            page.put_pixel(x, y, Rgb([0; 3]));
        }
    }
    let bounds = watermark::parse_box("12, 8, 11, 7")?;
    assert!(watermark::mark_page("large", Rect([0, 0, 64, 64]), page.dimensions()).is_err());
    let mark = watermark::mark_page("stamp", bounds, page.dimensions())?;
    let (clean, mask, _) = watermark::remove_watermark(&page, &mark, None)?;
    assert_eq!(clean.get_pixel(17, 11), &Rgb([255; 3]));
    assert_eq!(qa::compare_outside_mask(&page, &clean, &mask)?.changed, 0);
    Ok(())
}

#[test]
fn crop_sheets_and_worksheet_keep_page_coordinates() -> Result<()> {
    let page = RgbImage::from_pixel(150, 1800, Rgb([240; 3]));
    let bbox = Rect([10, 100, 24, 35]);
    let crop = crops::CropRegion {
        id: "p1r1".into(),
        bounds: bbox,
        balloon: None,
        kind: "speech".into(),
    };
    let overview = crops::render_overview(&page, std::slice::from_ref(&crop))?;
    assert_eq!(overview.image.height(), 1600);
    assert!((overview.scale - 1600.0 / 1800.0).abs() < 1e-12);
    assert_eq!(crops::render_sheets(&page, &[crop])?.len(), 1);
    let regions = [sheet::WorksheetRegion {
        id: "p1r1".into(),
        kind: "speech".into(),
        orientation: "vertical".into(),
        bounds: bbox,
        source: "Hi".into(),
        persian: "سلام".into(),
        notes: String::new(),
    }];
    let worksheet = sheet::page_worksheet(&sheet::Worksheet {
        title: "Test",
        page_id: "p1",
        page_number: 1,
        page_count: 1,
        size: [150, 1800],
        overview_scale: overview.scale,
        fingerprint: "test",
        reading_direction: "rtl",
        glossary: &[],
        regions: &regions,
    })?;
    assert!(worksheet.contains("@@ p1r1 speech vertical\n# box: 10 100 24 35"));
    assert!(worksheet.contains("# scheme: 2\n"));
    Ok(())
}

#[test]
fn lettering_analysis_keeps_origin_and_refuses_ambiguous_marks() -> Result<()> {
    let ink: GrayImage = ImageBuffer::from_fn(80, 52, |x, y| {
        Luma([if (6..72).contains(&x) && y.abs_diff(6 + x / 3) < 4 {
            255
        } else {
            0
        }])
    });
    let measured = lettering::measure(&ink, [50, 70])
        .ok_or_else(|| revayat_vision::VisionError::Invalid("no lettering measurement".into()))?;
    assert_eq!(measured.verdict, lettering::Verdict::Rotated);
    assert!(measured.center[0] > 50.0 && measured.center[1] > 70.0);
    let output = lettering::render(
        "سلام",
        measured,
        &Default::default(),
        Rect([0, 0, 82, 52]),
        40,
    )?;
    assert_eq!(output.dimensions(), (82, 52));
    assert!(output.pixels().any(|p| p[0] > 0));
    assert!(lettering::measure(&GrayImage::new(20, 20), [0, 0]).is_none());
    Ok(())
}
