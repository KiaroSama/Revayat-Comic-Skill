#![forbid(unsafe_code)]

use image::{Rgb, RgbImage};
use revayat_vision::detect::{DetectionOptions, detect_page};
use serde_json::json;

#[test]
fn gutter_ink_tolerance_changes_actual_panel_detection() {
    let mut image = RgbImage::from_pixel(128, 128, Rgb([0; 3]));
    for y in 0..128 {
        for x in 62..66 {
            if y != 64 {
                image.put_pixel(x, y, Rgb([255; 3]));
            }
        }
    }
    let strict: DetectionOptions = serde_json::from_value(json!({
        "find_sfx": false, "gutter_max_ink": 0.0,
    }))
    .unwrap();
    let tolerant: DetectionOptions = serde_json::from_value(json!({
        "find_sfx": false, "gutter_max_ink": 0.02,
    }))
    .unwrap();
    assert!(detect_page(&image, &strict).unwrap().panels.len() < 2);
    assert_eq!(detect_page(&image, &tolerant).unwrap().panels.len(), 2);
}

#[test]
fn minimum_sfx_glyphs_changes_actual_lettering_detection() {
    let mut image = RgbImage::from_pixel(128, 128, Rgb([255; 3]));
    for x0 in [50, 60] {
        for y in 50..60 {
            for x in x0..x0 + 5 {
                image.put_pixel(x, y, Rgb([0; 3]));
            }
        }
    }
    let strict = DetectionOptions::default();
    let relaxed: DetectionOptions = serde_json::from_value(json!({
        "sfx_min_glyphs": 2,
    }))
    .unwrap();
    assert!(
        !detect_page(&image, &strict)
            .unwrap()
            .regions
            .iter()
            .any(|r| r.kind == "sfx")
    );
    assert!(
        detect_page(&image, &relaxed)
            .unwrap()
            .regions
            .iter()
            .any(|r| r.kind == "sfx")
    );
}
