use image::{Rgb, RgbImage};
use revayat_vision::{Rect, clean, masks};

fn oriented(value: u8, dark: bool) -> Rgb<u8> {
    Rgb([if dark { 255 - value } else { value }; 3])
}

fn tiny_source(dark: bool) -> (RgbImage, masks::Balloon) {
    let panel = Rect([20, 20, 120, 100]);
    let text = Rect([40, 50, 2, 2]);
    let page = RgbImage::from_fn(160, 140, |x, y| {
        let paper = (20..100).contains(&x) && (20..120).contains(&y);
        let ink = [(40, 50), (40, 51), (41, 51)].contains(&(x, y));
        oriented(if paper && !ink { 245 } else { 20 }, dark)
    });
    let balloon = masks::resolve_balloon(&page, text, None, Some(panel), dark)
        .unwrap()
        .expect("the open component contains the entire source glyph");
    (page, balloon)
}

fn assert_only_authorized_pixels_changed(original: &RgbImage, result: &clean::CleanedPage) {
    for (x, y, pixel) in original.enumerate_pixels() {
        if result.mask.get_pixel(x, y)[0] == 0 {
            assert_eq!(result.image.get_pixel(x, y), pixel);
        }
    }
}

#[test]
fn dense_ink_in_an_open_balloon_cannot_be_reported_as_no_ink() {
    let panel = Rect([20, 20, 120, 100]);
    let text = Rect([40, 50, 20, 20]);
    let page = RgbImage::from_fn(160, 140, |x, y| {
        let paper = (20..100).contains(&x) && (20..120).contains(&y);
        let ink = (30..70).contains(&x) && (40..80).contains(&y) && x % 3 != 0;
        Rgb([if paper && !ink { 245 } else { 20 }; 3])
    });
    let balloon = masks::resolve_balloon(&page, text, None, Some(panel), false)
        .unwrap()
        .expect("the paper component is safely clipped to the declared panel");
    let result = clean::clean_page_bubbles(&page, &[balloon]);
    assert!(
        result.is_err(),
        "a fully ink-covered local mask requires a repair, not successful NoInk completion"
    );
}

#[test]
fn a_fully_bounded_tiny_source_glyph_is_not_no_ink_after_mask_growth() {
    for dark in [false, true] {
        let (page, balloon) = tiny_source(dark);
        assert!(
            clean::clean_page_bubbles(&page, &[balloon]).is_err(),
            "mask dilation can fill a small valid crop; the nonempty result must not be skipped"
        );
    }
}

#[test]
fn open_balloon_dot_sweep_preserves_art_outside_the_text_window() {
    for dark in [false, true] {
        for ink_luma in [20, 200] {
            let panel = Rect([20, 20, 120, 100]);
            let text = Rect([36, 46, 20, 20]);
            let page = RgbImage::from_fn(160, 140, |x, y| {
                let paper = (20..100).contains(&x) && (20..120).contains(&y);
                let ink = (42..48).contains(&x) && (52..58).contains(&y);
                let art = (79..83).contains(&x) && (99..103).contains(&y);
                oriented(
                    if ink {
                        ink_luma
                    } else if paper && !art {
                        245
                    } else {
                        20
                    },
                    dark,
                )
            });
            let balloon = masks::resolve_balloon(&page, text, None, Some(panel), dark)
                .unwrap()
                .expect("the open component is bounded by the declared panel");
            let result = clean::clean_page_bubbles(&page, &[balloon]).unwrap();
            assert_eq!(result.image.get_pixel(44, 54), &oriented(245, dark));
            assert_eq!(
                result.image.get_pixel(80, 100),
                page.get_pixel(80, 100),
                "open paper connected to a panel is not authority to erase distant artwork"
            );
            assert_eq!(result.mask.get_pixel(80, 100)[0], 0);
            assert_only_authorized_pixels_changed(&page, &result);
        }
    }
}

#[test]
fn solid_balloon_masks_accept_confined_external_recovery() {
    for dark in [false, true] {
        let (page, balloon) = tiny_source(dark);
        let repair = RgbImage::from_pixel(160, 140, oriented(245, dark));
        let result =
            clean::clean_page_bubbles_with_external(&page, &[balloon], &[], Some(&repair)).unwrap();
        assert_eq!(result.strategies, [clean::CleanStrategy::External]);
        for (x, y) in [(40, 50), (40, 51), (41, 51)] {
            assert_eq!(result.image.get_pixel(x, y), &oriented(245, dark));
            assert_eq!(result.mask.get_pixel(x, y)[0], 255);
        }
        assert_only_authorized_pixels_changed(&page, &result);
        assert_eq!(result.image.get_pixel(120, 80), page.get_pixel(120, 80));
        let excluded = [Rect([39, 49, 4, 4])];
        let result =
            clean::clean_page_bubbles_with_external(&page, &[balloon], &excluded, Some(&repair))
                .unwrap();
        assert_eq!(result.strategies, [clean::CleanStrategy::NoInk]);
        assert_eq!(result.image, page);
        assert!(result.mask.iter().all(|&pixel| pixel == 0));
    }
}

#[test]
fn closed_full_interior_cleaning_keeps_exclusions_and_contours() {
    for dark in [false, true] {
        let text = Rect([36, 46, 20, 20]);
        let page = RgbImage::from_fn(160, 140, |x, y| {
            let paper = (20..100).contains(&x) && (20..120).contains(&y);
            let ink = (42..48).contains(&x) && (52..58).contains(&y);
            let distant = (79..83).contains(&x) && (99..103).contains(&y);
            let protected = (64..68).contains(&x) && (84..88).contains(&y);
            oriented(
                if paper && !ink && !distant && !protected {
                    245
                } else {
                    20
                },
                dark,
            )
        });
        let balloon = masks::resolve_balloon(&page, text, None, None, dark)
            .unwrap()
            .expect("the paper component is fully enclosed");
        let excluded = [Rect([62, 82, 8, 8])];
        let result = clean::clean_page_bubbles_except(&page, &[balloon], &excluded).unwrap();
        assert_eq!(result.strategies, [clean::CleanStrategy::Flat]);
        assert_eq!(result.image.get_pixel(44, 54), &oriented(245, dark));
        assert_eq!(result.image.get_pixel(80, 100), &oriented(245, dark));
        assert_eq!(result.mask.get_pixel(80, 100)[0], 255);
        assert_eq!(result.image.get_pixel(65, 85), page.get_pixel(65, 85));
        assert_eq!(result.mask.get_pixel(65, 85)[0], 0);
        assert_eq!(result.image.get_pixel(19, 60), page.get_pixel(19, 60));
        assert_only_authorized_pixels_changed(&page, &result);
    }
}

#[test]
fn external_balloon_recovery_rejects_wrong_geometry() {
    let (page, balloon) = tiny_source(false);
    let repair = RgbImage::from_pixel(80, 70, Rgb([245; 3]));
    assert!(
        clean::clean_page_bubbles_with_external(&page, &[balloon], &[], Some(&repair)).is_err()
    );
}

#[test]
fn open_balloon_large_faint_source_is_erased_in_both_polarities() {
    let outcomes: Vec<_> = [false, true]
        .into_iter()
        .flat_map(|dark| [(245, 200), (190, 180)].map(move |colors| (dark, colors)))
        .map(|(dark, (paper_luma, ink_luma))| {
            let panel = Rect([20, 20, 120, 100]);
            let text = Rect([35, 45, 30, 30]);
            let page = RgbImage::from_fn(160, 140, |x, y| {
                let paper = (20..100).contains(&x) && (20..120).contains(&y);
                let ink = (40..60).contains(&x) && (50..70).contains(&y);
                let art = (79..83).contains(&x) && (99..103).contains(&y);
                oriented(
                    if ink {
                        ink_luma
                    } else if paper && !art {
                        paper_luma
                    } else {
                        20
                    },
                    dark,
                )
            });
            let balloon = masks::resolve_balloon(&page, text, None, Some(panel), dark)
                .unwrap()
                .expect("the panel-clipped paper component contains the source");
            let result = clean::clean_page_bubbles(&page, &[balloon]).unwrap();
            assert_only_authorized_pixels_changed(&page, &result);
            assert_eq!(result.image.get_pixel(80, 100), page.get_pixel(80, 100));
            (
                result.image.get_pixel(50, 60)[0],
                result.mask.get_pixel(50, 60)[0],
                result.strategies[0],
            )
        })
        .collect();
    assert_eq!(
        outcomes,
        [
            (245, 255, clean::CleanStrategy::Flat),
            (190, 255, clean::CleanStrategy::Flat),
            (10, 255, clean::CleanStrategy::Flat),
            (65, 255, clean::CleanStrategy::Flat)
        ],
        "larger faint source glyphs must be removed without relying on the small-speckle sweep"
    );
}

#[test]
fn supported_large_page_mask_and_detection_do_not_overflow_their_histograms() {
    let page = RgbImage::from_pixel(6000, 3000, Rgb([245; 3]));
    let mask = masks::region_mask(
        &page,
        Rect([0, 0, 6000, 3000]),
        None,
        false,
        masks::MaskOptions {
            grow: 0.0,
            pad: 0.0,
            full_balloon: false,
            ..Default::default()
        },
    )
    .expect("a supported 18-megapixel image must not panic during thresholding");
    assert!(mask.pixels.iter().all(|&pixel| pixel == 0));
    drop(mask);
    let detected = revayat_vision::detect::detect_page(
        &page,
        &revayat_vision::detect::DetectionOptions::default(),
    )
    .expect("a supported 18-megapixel page must not panic during detection");
    assert_eq!(detected.size, [6000, 3000]);
    assert!(detected.regions.is_empty());
}
