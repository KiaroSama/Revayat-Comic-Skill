use super::*;
use image::{Luma, Rgb, RgbImage};
use revayat_ir::{RegionRecord, RegionState, ir, regions};

const DOC: &str = "work/comic.json";

fn read_document(fixture: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(fixture.cwd.join(DOC)).unwrap()).unwrap()
}

fn write_document(fixture: &Fixture, document: &Value) {
    fs::write(
        fixture.cwd.join(DOC),
        serde_json::to_vec_pretty(document).unwrap(),
    )
    .unwrap();
}

fn import_page(fixture: &Fixture, page: &RgbImage, regions: &[RegionRecord]) {
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    page.save(fixture.cwd.join("source/page.png")).unwrap();
    success(&fixture.run(&["import", "source", "--out", "work"], b""));
    let mut document = read_document(fixture);
    document["pages"][0]["regions"] = json!(regions);
    write_document(fixture, &document);
}

fn region(id: &str, bbox: [f64; 4], kind: &str) -> RegionRecord {
    ir::new_region(id, bbox, kind, "horizontal", "manual", 1.0).unwrap()
}

fn free_page() -> RgbImage {
    let mut page = RgbImage::from_pixel(120, 100, Rgb([245; 3]));
    for y in 35..42 {
        for x in 40..46 {
            page.put_pixel(x, y, Rgb([20; 3]));
        }
    }
    page
}

#[test]
fn locked_state_only_watermark_uses_the_approved_solid_external_repair() {
    let fixture = Fixture::staged();
    let original = free_page();
    let mut watermark = region("p0001r001", [35., 30., 20., 20.], "watermark");
    watermark.state = Some(RegionState::Erased);
    watermark.locked = true;
    import_page(&fixture, &original, &[watermark]);
    let masked = fixture.run(&["mask", "--doc", DOC], b"");
    success(&masked);
    assert_eq!(json_stdout(&masked)["masks"], 1);
    let document = read_document(&fixture);
    let record = &document["pages"][0]["regions"][0];
    assert_eq!(record["mask_bounds"], json!([35, 30, 20, 20]));
    let mask = image::open(
        fixture
            .cwd
            .join("work")
            .join(record["mask"].as_str().unwrap()),
    )
    .unwrap()
    .into_luma8();
    assert_eq!(mask.dimensions(), (20, 20));
    assert!(mask.iter().all(|&p| p == 255));

    let before = fs::read(fixture.cwd.join(DOC)).unwrap();
    let refused = fixture.run(&["clean", "--doc", DOC], b"");
    assert!(!refused.status.success(), "{refused:?}");
    assert!(String::from_utf8_lossy(&refused.stderr).contains("approved external repair"));
    assert_eq!(fs::read(fixture.cwd.join(DOC)).unwrap(), before);
    fs::create_dir(fixture.cwd.join("external")).unwrap();
    let page_id = document["pages"][0]["id"].as_str().unwrap();
    RgbImage::from_pixel(120, 100, Rgb([245; 3]))
        .save(fixture.cwd.join(format!("external/{page_id}.png")))
        .unwrap();
    success(&fixture.run(&["clean", "--doc", DOC, "--external-dir", "external"], b""));
    let document = read_document(&fixture);
    assert_eq!(document["pages"][0]["regions"][0]["fill"], "external");
    let cleaned = image::open(
        fixture
            .cwd
            .join("work")
            .join(document["pages"][0]["clean"].as_str().unwrap()),
    )
    .unwrap()
    .into_rgb8();
    assert_eq!(cleaned.get_pixel(42, 38), &Rgb([245; 3]));
    for (x, y, pixel) in original.enumerate_pixels() {
        if !(35..55).contains(&x) || !(30..50).contains(&y) {
            assert_eq!(cleaned.get_pixel(x, y), pixel);
        }
    }
    success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
    success(&fixture.run(&["export", "--doc", DOC, "--out", "erased.cbz"], b""));
}

#[test]
fn unlocked_state_only_watermark_is_refused_without_committing_the_document() {
    let fixture = Fixture::staged();
    let mut watermark = region("p0001r001", [35., 30., 20., 20.], "watermark");
    watermark.state = Some(RegionState::Erased);
    import_page(&fixture, &free_page(), &[watermark]);
    let before = fs::read(fixture.cwd.join(DOC)).unwrap();
    let refused = fixture.run(&["mask", "--doc", DOC], b"");
    assert!(!refused.status.success(), "{refused:?}");
    assert!(String::from_utf8_lossy(&refused.stderr).contains("locked erase decision"));
    assert_eq!(fs::read(fixture.cwd.join(DOC)).unwrap(), before);
}

#[test]
fn completed_balloon_erasure_records_fill_and_reaches_strict_export() {
    for state_only in [false, true] {
        for bubbles_only in [false, true] {
            let fixture = Fixture::staged();
            let original = RgbImage::from_fn(200, 180, |x, y| {
                let radius = ((f64::from(x) - 100.0) / 60.0).powi(2)
                    + ((f64::from(y) - 80.0) / 40.0).powi(2);
                let ink = (93..99).contains(&x) && (75..82).contains(&y);
                Rgb([if radius < 0.9 && !ink {
                    245
                } else if radius <= 1.0 {
                    12
                } else {
                    40
                }; 3])
            });
            let mut kept = region("p0001r001", [10., 10., 20., 10.], "caption");
            kept.keep = true;
            let mut erased = region("p0001r002", [80., 68., 40., 25.], "speech");
            erased.locked = true;
            if state_only {
                erased.state = Some(RegionState::Erased);
            } else {
                erased.erase = true;
            }
            import_page(&fixture, &original, &[kept, erased]);
            success(&fixture.run(&["mask", "--doc", DOC], b""));
            let args = if bubbles_only {
                vec!["clean", "--doc", DOC, "--bubbles-only"]
            } else {
                vec!["clean", "--doc", DOC]
            };
            success(&fixture.run(&args, b""));
            let document = read_document(&fixture);
            let records = &document["pages"][0]["regions"];
            assert_eq!(records[0]["fill"], "none");
            assert_eq!(records[1]["fill"], "flat");
            let erased: RegionRecord = serde_json::from_value(records[1].clone()).unwrap();
            assert_eq!(
                regions::region_state(&erased, "keep").unwrap(),
                RegionState::Erased
            );
            let root = fixture.cwd.join("work");
            let cleaned = image::open(root.join(document["pages"][0]["clean"].as_str().unwrap()))
                .unwrap()
                .into_rgb8();
            let mask = image::open(root.join(document["pages"][0]["clean_mask"].as_str().unwrap()))
                .unwrap()
                .into_luma8();
            assert_eq!(cleaned.get_pixel(96, 78), &Rgb([245; 3]));
            assert_eq!(mask.get_pixel(96, 78), &Luma([255]));
            for (x, y, pixel) in original.enumerate_pixels() {
                if mask.get_pixel(x, y)[0] == 0 {
                    assert_eq!(cleaned.get_pixel(x, y), pixel);
                }
            }
            success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
            success(&fixture.run(&["export", "--doc", DOC, "--out", "erased.cbz"], b""));
        }
    }
}

#[test]
fn dropped_state_cannot_supply_an_on_art_neighbor_clip() {
    let original = RgbImage::from_fn(200, 200, |x, y| {
        let paper = (40..80).contains(&x) && y >= 20;
        let ink = (48..53).contains(&x) && (45..50).contains(&y);
        Rgb([if paper && !ink { 245 } else { 30 }; 3])
    });
    let mut dropped_mask = None;
    for mode in ["live", "flag", "state"] {
        let fixture = Fixture::staged();
        let mut speech = region("p0001r001", [45., 40., 30., 20.], "speech");
        speech.erase = true;
        let mut neighbor = region("p0001r002", [45., 70., 30., 10.], "title");
        neighbor.dropped = mode == "flag";
        neighbor.state = (mode == "state").then_some(RegionState::Dropped);
        import_page(&fixture, &original, &[speech, neighbor]);
        success(&fixture.run(&["mask", "--doc", DOC], b""));
        let document = read_document(&fixture);
        let records = &document["pages"][0]["regions"];
        if mode == "live" {
            assert!(records[0].get("balloon").is_some());
        } else {
            assert!(records[0].get("balloon").is_none(), "{mode}: {records}");
            assert!(records[1]["mask"].is_null());
            let mask = image::open(
                fixture
                    .cwd
                    .join("work")
                    .join(document["pages"][0]["mask"].as_str().unwrap()),
            )
            .unwrap()
            .into_luma8();
            if let Some(expected) = &dropped_mask {
                assert_eq!(&mask, expected);
            } else {
                dropped_mask = Some(mask);
            }
        }
    }
}

#[test]
fn kept_dropped_and_conflicting_actions_do_not_authorize_erase_masks() {
    for mode in [
        "keep",
        "kept",
        "drop",
        "dropped",
        "erase+keep",
        "erase+drop",
    ] {
        let fixture = Fixture::staged();
        let mut record = region("p0001r001", [35., 30., 20., 20.], "title");
        record.keep = matches!(mode, "keep" | "erase+keep");
        record.dropped = matches!(mode, "drop" | "erase+drop");
        record.state = match mode {
            "kept" => Some(RegionState::Kept),
            "dropped" => Some(RegionState::Dropped),
            "erase+keep" | "erase+drop" => Some(RegionState::Erased),
            _ => None,
        };
        if mode.starts_with("erase+") {
            assert!(regions::region_state(&record, "keep").is_err());
        }
        import_page(&fixture, &free_page(), &[record]);
        let masked = fixture.run(&["mask", "--doc", DOC], b"");
        success(&masked);
        assert_eq!(json_stdout(&masked)["masks"], 0, "{mode}");
        let document = read_document(&fixture);
        assert!(document["pages"][0]["regions"][0]["mask"].is_null());
        let mask = image::open(
            fixture
                .cwd
                .join("work")
                .join(document["pages"][0]["mask"].as_str().unwrap()),
        )
        .unwrap()
        .into_luma8();
        assert!(mask.iter().all(|&p| p == 0), "{mode}");
    }
}
