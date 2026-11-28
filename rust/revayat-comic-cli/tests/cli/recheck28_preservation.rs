use super::*;
use image::{GrayImage, Luma, Rgb, RgbImage};
use std::io::Read;

const DOC: &str = "work/comic.json";

fn read_doc(fixture: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(fixture.cwd.join(DOC)).unwrap()).unwrap()
}

fn write_doc(fixture: &Fixture, doc: &Value) {
    fs::write(fixture.cwd.join(DOC), serde_json::to_vec(doc).unwrap()).unwrap();
}

fn import_page(fixture: &Fixture, page: &RgbImage) {
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    page.save(fixture.cwd.join("source/0.png")).unwrap();
    success(&fixture.run(&["import", "source", "--out", "work"], b""));
}

fn load_rgb(fixture: &Fixture, value: &Value) -> RgbImage {
    image::open(fixture.cwd.join("work").join(value.as_str().unwrap()))
        .unwrap()
        .into_rgb8()
}

fn load_mask(fixture: &Fixture, value: &Value) -> GrayImage {
    image::open(fixture.cwd.join("work").join(value.as_str().unwrap()))
        .unwrap()
        .into_luma8()
}

fn assert_preserved(source: &RgbImage, output: &RgbImage, mask: &GrayImage, area: [u32; 4]) {
    for y in area[1]..area[1] + area[3] {
        for x in area[0]..area[0] + area[2] {
            assert_eq!(
                output.get_pixel(x, y),
                source.get_pixel(x, y),
                "preserved pixel {x},{y}"
            );
            assert_eq!(mask.get_pixel(x, y)[0], 0, "preserved mask pixel {x},{y}");
        }
    }
}

#[test]
fn on_art_erasure_preserves_overlapping_kept_ink_through_final_export() {
    for dark in [false, true] {
        for state_only in [false, true] {
            let fixture = Fixture::staged();
            let (paper, ink) = if dark { (20, 245) } else { (245, 20) };
            let source = RgbImage::from_fn(180, 140, |x, y| {
                let glyph = (40..50).contains(&x) && (50..65).contains(&y);
                let badge = (75..85).contains(&x) && (55..65).contains(&y);
                let false_detection = (115..125).contains(&x) && (55..65).contains(&y);
                Rgb([if glyph || badge || false_detection {
                    ink
                } else {
                    paper
                }; 3])
            });
            import_page(&fixture, &source);
            let mut doc = read_doc(&fixture);
            doc["meta"]["sfx_policy"] = json!("translate");
            let mut kept =
                json!({"id":"badge", "kind":"title", "bbox":[70,50,20,25], "source_text":"15"});
            kept[if state_only { "state" } else { "keep" }] = if state_only {
                json!("kept")
            } else {
                json!(true)
            };
            doc["pages"][0]["regions"] = json!([
                {"id":"erase", "kind":"sfx", "bbox":[25,25,135,80], "source_text":"ERASE", "erase":true, "locked":true, "polarity":if dark { "dark" } else { "light" }},
                kept,
                {"id":"false", "kind":"title", "bbox":[110,50,20,25], "source_text":"false detection", "dropped":true}
            ]);
            write_doc(&fixture, &doc);
            success(&fixture.run(&["mask", "--doc", DOC], b""));
            success(&fixture.run(&["clean", "--doc", DOC], b""));
            let doc = read_doc(&fixture);
            let page = &doc["pages"][0];
            let cleaned = load_rgb(&fixture, &page["clean"]);
            let mask = load_mask(&fixture, &page["clean_mask"]);
            assert_preserved(&source, &cleaned, &mask, [70, 50, 20, 25]);
            assert_eq!(cleaned.get_pixel(45, 58), &Rgb([paper; 3]));
            // A false detection does not protect real ink owned by its neighbor.
            assert_eq!(cleaned.get_pixel(120, 60), &Rgb([paper; 3]));
            let writable = load_mask(&fixture, &page["mask"]);
            assert_eq!(writable.get_pixel(80, 60), &Luma([0]));
            success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
            success(&fixture.run(&["export", "--doc", DOC, "--out", "kept.cbz"], b""));
            let mut archive =
                zip::ZipArchive::new(File::open(fixture.cwd.join("kept.cbz")).unwrap()).unwrap();
            let mut bytes = Vec::new();
            archive
                .by_name("0001.png")
                .unwrap()
                .read_to_end(&mut bytes)
                .unwrap();
            let shipped = image::load_from_memory(&bytes).unwrap().into_rgb8();
            assert_preserved(&source, &shipped, &mask, [70, 50, 20, 25]);

            fs::create_dir(fixture.cwd.join("external")).unwrap();
            RgbImage::from_pixel(180, 140, Rgb([paper; 3]))
                .save(fixture.cwd.join("external/p0001.png"))
                .unwrap();
            success(&fixture.run(&["clean", "--doc", DOC, "--external-dir", "external"], b""));
            let doc = read_doc(&fixture);
            let page = &doc["pages"][0];
            assert_preserved(
                &source,
                &load_rgb(&fixture, &page["clean"]),
                &load_mask(&fixture, &page["clean_mask"]),
                [70, 50, 20, 25],
            );
            success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
            success(&fixture.run(&["export", "--doc", DOC, "--out", "kept-external.cbz"], b""));
        }
    }
}

#[test]
fn deterministic_on_art_lettering_cannot_authorize_kept_or_policy_kept_regions() {
    for policy_kept in [false, true] {
        let fixture = Fixture::staged();
        let source = RgbImage::from_fn(240, 200, |x, y| {
            let badge = (110..120).contains(&x) && (80..87).contains(&y);
            Rgb([if badge { 20 } else { 245 }; 3])
        });
        import_page(&fixture, &source);
        let mut doc = read_doc(&fixture);
        let kept = if policy_kept {
            json!({"id":"badge", "kind":"sfx", "bbox":[95,70,40,35], "source_text":"15"})
        } else {
            json!({"id":"badge", "kind":"title", "bbox":[95,70,40,35], "source_text":"15", "keep":true})
        };
        doc["meta"]["sfx_policy"] = json!("keep");
        doc["pages"][0]["regions"] = json!([
            {"id":"lettering", "kind":"title", "bbox":[30,30,180,140], "source_text":"Hello", "target_text":"سلام!", "locked":true},
            kept
        ]);
        write_doc(&fixture, &doc);
        success(&fixture.run(&["mask", "--doc", DOC, "--free-lettering", "solid"], b""));
        success(&fixture.run(&["clean", "--doc", DOC, "--bubbles-only"], b""));
        success(&fixture.run(&["typeset", "--doc", DOC], b""));
        let doc = read_doc(&fixture);
        let page = &doc["pages"][0];
        assert_eq!(page["regions"][0]["typeset"]["status"], "fit");
        let rendered = load_rgb(&fixture, &page["final"]);
        let allowed = load_mask(&fixture, &page["authorized_mask"]);
        assert_preserved(&source, &rendered, &allowed, [95, 70, 40, 35]);
        success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
        success(&fixture.run(&["export", "--doc", DOC, "--out", "kept.cbz"], b""));
    }
}

#[test]
fn pending_editable_regions_still_receive_masks_before_translation() {
    let fixture = Fixture::staged();
    let source = RgbImage::from_fn(100, 80, |x, y| {
        Rgb([if (40..50).contains(&x) && (30..40).contains(&y) {
            20
        } else {
            245
        }; 3])
    });
    import_page(&fixture, &source);
    let mut doc = read_doc(&fixture);
    doc["pages"][0]["regions"] = json!([
        {"id":"pending", "kind":"title", "bbox":[20,20,60,40], "source_text":"Hello"}
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    let doc = read_doc(&fixture);
    let mask = load_mask(&fixture, &doc["pages"][0]["mask"]);
    assert_eq!(mask.get_pixel(45, 35), &Luma([255]));
}

fn save_legacy_artifact(fixture: &Fixture, name: &str, image: &image::DynamicImage) -> Value {
    let mut bytes = std::io::Cursor::new(Vec::new());
    image.write_to(&mut bytes, image::ImageFormat::Png).unwrap();
    let bytes = bytes.into_inner();
    let digest = revayat_ir::ir::sha256_bytes(&bytes);
    fs::create_dir_all(fixture.cwd.join("work/clean")).unwrap();
    let relative = format!("clean/{name}-{digest}.png");
    fs::write(fixture.cwd.join("work").join(&relative), bytes).unwrap();
    json!(relative)
}

#[test]
fn qa_rejects_legacy_authorization_over_kept_native_color_and_alpha() {
    for channel in [0, 3] {
        let fixture = Fixture::staged();
        let source = image::ImageBuffer::from_pixel(100, 80, image::Rgba([50000u16; 4]));
        fs::create_dir(fixture.cwd.join("source")).unwrap();
        source.save(fixture.cwd.join("source/0.png")).unwrap();
        success(&fixture.run(&["import", "source", "--out", "work"], b""));
        let mut doc = read_doc(&fixture);
        doc["pages"][0]["regions"] = json!([
            {"id":"badge", "kind":"title", "bbox":[40,30,20,20], "source_text":"15", "keep":true}
        ]);
        let mut altered = source.clone();
        altered.get_pixel_mut(45, 35)[channel] += 1;
        let image = image::DynamicImage::ImageRgba16(altered);
        // This change disappears in an RGB8 comparison; native QA must still reject it.
        assert_eq!(
            image.to_rgb8(),
            image::DynamicImage::ImageRgba16(source).to_rgb8()
        );
        doc["pages"][0]["clean"] = save_legacy_artifact(&fixture, "legacy", &image);
        doc["pages"][0]["clean_mask"] = save_legacy_artifact(
            &fixture,
            "legacy-mask",
            &image::DynamicImage::ImageLuma8(GrayImage::from_pixel(100, 80, Luma([255]))),
        );
        write_doc(&fixture, &doc);
        let original_doc = fs::read(fixture.cwd.join(DOC)).unwrap();
        let qa = fixture.run(&["qa", "check", "--strict", "--doc", DOC], b"");
        assert_eq!(qa.status.code(), Some(1));
        let report = json_stdout(&qa);
        assert_eq!(report["artwork_pixels_changed"], 1);
        assert!(
            report["findings"]
                .as_array()
                .unwrap()
                .iter()
                .any(|finding| finding["code"] == "artwork-changed")
        );
        let export = fixture.run(&["export", "--doc", DOC, "--out", "refused.cbz"], b"");
        assert!(!export.status.success());
        assert!(!fixture.cwd.join("refused.cbz").exists());
        assert_eq!(fs::read(fixture.cwd.join(DOC)).unwrap(), original_doc);
        // Rebuild from the immutable original instead of accepting the old authorization.
        for stage in ["mask", "clean"] {
            success(&fixture.run(&[stage, "--doc", DOC], b""));
        }
        success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
        success(&fixture.run(&["export", "--doc", DOC, "--out", "recovered.cbz"], b""));
    }
}

#[test]
fn malformed_local_mask_refuses_atomically_before_keep_exclusion_and_recovers() {
    let fixture = Fixture::staged();
    let source = RgbImage::from_fn(100, 80, |x, y| {
        let ink = (30..40).contains(&x) && (30..40).contains(&y);
        let badge = (60..70).contains(&x) && (30..40).contains(&y);
        Rgb([if ink || badge { 20 } else { 245 }; 3])
    });
    import_page(&fixture, &source);
    let mut doc = read_doc(&fixture);
    doc["pages"][0]["regions"] = json!([
        {"id":"erase", "kind":"title", "bbox":[20,20,60,40], "source_text":"Erase", "erase":true, "locked":true},
        {"id":"badge", "kind":"title", "bbox":[55,25,20,20], "source_text":"15", "keep":true}
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    let mut doc = read_doc(&fixture);
    doc["pages"][0]["regions"][0]["mask"] = save_legacy_artifact(
        &fixture,
        "malformed-mask",
        &image::DynamicImage::ImageLuma8(GrayImage::from_pixel(1, 1, Luma([255]))),
    );
    doc["pages"][0]["regions"][0]["mask_bounds"] = json!([20, 20, 60, 40]);
    write_doc(&fixture, &doc);
    let before = fs::read(fixture.cwd.join(DOC)).unwrap();
    let out = fixture.run(&["clean", "--doc", DOC], b"");
    assert_eq!(out.status.code(), Some(4));
    assert!(String::from_utf8_lossy(&out.stderr).contains("region mask dimensions do not match"));
    assert_eq!(fs::read(fixture.cwd.join(DOC)).unwrap(), before);
    for stage in ["mask", "clean"] {
        success(&fixture.run(&[stage, "--doc", DOC], b""));
    }
    success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
}
