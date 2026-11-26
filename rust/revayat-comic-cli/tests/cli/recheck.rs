use super::*;

fn import_blank_pages(fixture: &Fixture, count: usize) -> Value {
    use image::{Rgb, RgbImage};
    let source = fixture.cwd.join("source");
    fs::create_dir(&source).unwrap();
    for index in 0..count {
        RgbImage::from_pixel(128, 128, Rgb([255; 3]))
            .save(source.join(format!("{index:03}.png")))
            .unwrap();
    }
    let result = fixture.run(&["import", "source", "--out", "work"], b"");
    success(&result);
    serde_json::from_slice(&fs::read(fixture.cwd.join("work/comic.json")).unwrap()).unwrap()
}

#[test]
fn detection_help_exposes_the_documented_tuning_controls() {
    let fixture = Fixture::staged();
    let output = fixture.run(&["detect", "--help"], b"");
    success(&output);
    let help = String::from_utf8(output.stdout).unwrap();
    for flag in [
        "--pages",
        "--no-sfx",
        "--balloon-min-area",
        "--balloon-max-area",
        "--balloon-min-side",
        "--balloon-min-solidity",
        "--ink-min",
        "--ink-max",
        "--glyph-min",
        "--glyph-max",
        "--gutter-max-ink",
        "--gutter-min-span",
        "--panel-min-area",
        "--sfx-min-side",
        "--sfx-min-glyphs",
        "--sfx-size-uniformity",
        "--sfx-max-spread",
    ] {
        assert!(help.contains(flag), "documented option is missing: {flag}");
    }
}

#[test]
fn detection_records_requested_thresholds_and_selected_pages() {
    let fixture = Fixture::staged();
    let imported = import_blank_pages(&fixture, 2);
    let selected = imported["pages"][1]["id"].as_str().unwrap();
    let output = fixture.run(
        &[
            "detect",
            "--doc",
            "work/comic.json",
            "--pages",
            selected,
            "--no-sfx",
            "--balloon-min-area",
            "0.001",
            "--balloon-max-area",
            "0.2",
            "--balloon-min-side",
            "0.06",
            "--balloon-min-solidity",
            "0.5",
            "--ink-min",
            "0.02",
            "--ink-max",
            "0.6",
            "--glyph-min",
            "0.005",
            "--glyph-max",
            "0.25",
            "--gutter-max-ink",
            "0.02",
            "--gutter-min-span",
            "0.025",
            "--panel-min-area",
            "0.03",
            "--sfx-min-side",
            "0.04",
            "--sfx-min-glyphs",
            "2",
            "--sfx-size-uniformity",
            "0.7",
            "--sfx-max-spread",
            "2.0",
        ],
        b"",
    );
    success(&output);
    let document: Value =
        serde_json::from_slice(&fs::read(fixture.cwd.join("work/comic.json")).unwrap()).unwrap();
    let stamp = &document["stages"]["detect"];
    let pages = stamp["pages"].as_object().unwrap();
    assert_eq!(pages.len(), 1);
    assert!(pages.contains_key(selected));
    let options = &stamp["page_options"][selected];
    assert_eq!(options["find_sfx"], false);
    assert_eq!(options["balloon_min_area"], 0.001);
    assert_eq!(options["gutter_max_ink"], 0.02);
    assert_eq!(options["sfx_min_glyphs"], 2);
}

#[test]
fn detection_preserves_reviewed_pages_while_processing_new_pages() {
    let fixture = Fixture::staged();
    let mut document = import_blank_pages(&fixture, 2);
    let first_id = document["pages"][0]["id"].as_str().unwrap().to_owned();
    let second_id = document["pages"][1]["id"].as_str().unwrap().to_owned();
    let mut region = revayat_ir::ir::new_region(
        format!("{first_id}r001"),
        [20.0, 20.0, 30.0, 20.0],
        "speech",
        "horizontal",
        "manual",
        1.0,
    )
    .unwrap();
    region.source_text = "Hello".into();
    region.target_text = "سلام".into();
    region.locked = true;
    document["pages"][0]["regions"] = json!([region]);
    let reviewed = document["pages"][0].clone();
    let path = fixture.cwd.join("work/comic.json");
    fs::write(&path, serde_json::to_vec_pretty(&document).unwrap()).unwrap();
    let output = fixture.run(&["detect", "--doc", "work/comic.json"], b"");
    success(&output);
    let document: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    assert_eq!(document["pages"][0], reviewed);
    let pages = document["stages"]["detect"]["pages"].as_object().unwrap();
    assert!(pages.contains_key(&second_id));
    assert!(!pages.contains_key(&first_id));
    assert_eq!(json_stdout(&output)["skipped"][0]["page"], first_id);
}

#[test]
fn batch_refuses_a_different_document_filename_before_creating_output() {
    let fixture = Fixture::staged();
    import_blank_pages(&fixture, 1);
    let canonical = fixture.cwd.join("work/comic.json");
    let before = fs::read(&canonical).unwrap();
    fs::write(fixture.cwd.join("work/different.json"), &before).unwrap();
    let output = fixture.run(
        &[
            "batch",
            "plan",
            "--doc",
            "work/different.json",
            "--out",
            "batch-output",
            "--shards",
            "1",
        ],
        b"",
    );
    usage_error(&output);
    assert!(
        String::from_utf8(output.stderr)
            .unwrap()
            .contains("comic.json")
    );
    assert!(!fixture.cwd.join("batch-output").exists());
    assert_eq!(fs::read(canonical).unwrap(), before);
}

fn put_document(fixture: &Fixture, document: &Value) {
    fs::write(
        fixture.cwd.join("work/comic.json"),
        serde_json::to_vec_pretty(document).unwrap(),
    )
    .unwrap();
}

fn document(fixture: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(fixture.cwd.join("work/comic.json")).unwrap()).unwrap()
}

fn approve(fixture: &Fixture, codes: &str) {
    let built = fixture.run(
        &["worksheet", "build", "--doc", "work/comic.json", "--force"],
        b"",
    );
    success(&built);
    let built = json_stdout(&built);
    let draft = PathBuf::from(built["built"][0].as_str().unwrap());
    let page = document(fixture)["pages"][0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let text = fs::read_to_string(&draft).unwrap();
    let text = format!("{text}reviewed: {codes}\n");
    fs::write(draft.with_file_name(format!("{page}.done.txt")), text).unwrap();
    success(&fixture.run(&["worksheet", "merge", "--doc", "work/comic.json"], b""));
    let current: revayat_ir::ComicDocument =
        revayat_ir::ir::decode_doc(&fs::read(fixture.cwd.join("work/comic.json")).unwrap())
            .unwrap();
    assert!(
        revayat_ir::review::settled(&current.pages[0].regions[0], codes),
        "approval was not bound to the current region: {:?}",
        current.pages[0].regions[0]
    );
}

#[test]
fn worksheet_review_reaches_falint_and_qa_and_expires_with_source() {
    let fixture = Fixture::staged();
    let mut doc = import_blank_pages(&fixture, 1);
    let id = doc["pages"][0]["id"].as_str().unwrap();
    let mut region = revayat_ir::ir::new_region(
        format!("{id}r001"),
        [20., 20., 80., 30.],
        "speech",
        "horizontal",
        "manual",
        1.,
    )
    .unwrap();
    region.source_text = "A reviewed ambiguous phrase".into();
    region.target_text = "خانه تر".into();
    doc["pages"][0]["regions"] = json!([region]);
    put_document(&fixture, &doc);
    let before = fixture.run(&["falint", "check", "--doc", "work/comic.json"], b"");
    assert_eq!(before.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&before.stdout).contains("zwnj-review"));
    approve(&fixture, "zwnj-review");
    success(&fixture.run(&["falint", "check", "--doc", "work/comic.json"], b""));
    let reviewed_qa = fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    );
    assert!(!String::from_utf8_lossy(&reviewed_qa.stdout).contains("zwnj-review"));
    let mut doc = document(&fixture);
    doc["pages"][0]["regions"][0]["source_text"] = json!("Changed source");
    put_document(&fixture, &doc);
    let stale = fixture.run(&["falint", "check", "--doc", "work/comic.json"], b"");
    assert_eq!(stale.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&stale.stdout).contains("zwnj-review"));
    let stale_qa = fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    );
    assert!(String::from_utf8_lossy(&stale_qa.stdout).contains("zwnj-review"));
}

fn rendered_balloon(fixture: &Fixture) {
    use image::{Rgb, RgbImage};
    let mut page = RgbImage::from_pixel(300, 300, Rgb([42; 3]));
    for y in 12..118 {
        for x in 20..140 {
            let distance =
                ((f64::from(x) - 80.) / 58.).powi(2) + ((f64::from(y) - 65.) / 50.).powi(2);
            if distance < 0.88 {
                page.put_pixel(x, y, Rgb([245; 3]));
            } else if distance <= 1. {
                page.put_pixel(x, y, Rgb([12; 3]));
            }
        }
    }
    for y in 59..70 {
        for x in (68..75).chain(84..90) {
            page.put_pixel(x, y, Rgb([20; 3]));
        }
    }
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    page.save(fixture.cwd.join("source/001.png")).unwrap();
    success(&fixture.run(&["import", "source", "--out", "work"], b""));
    let mut doc = document(fixture);
    let id = doc["pages"][0]["id"].as_str().unwrap();
    let mut region = revayat_ir::ir::new_region(
        format!("{id}r001"),
        [65., 56., 29., 18.],
        "speech",
        "horizontal",
        "manual",
        1.,
    )
    .unwrap();
    region.source_text = "Hello".into();
    region.target_text = "سلام".into();
    doc["pages"][0]["regions"] = json!([region]);
    put_document(fixture, &doc);
    for stage in ["mask", "crops", "clean", "typeset"] {
        success(&fixture.run(&[stage, "--doc", "work/comic.json"], b""));
    }
    success(&fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    ));
}

#[test]
fn publication_requires_current_compression_review_and_stage_inputs() {
    let fixture = Fixture::staged();
    rendered_balloon(&fixture);
    let mut doc = document(&fixture);
    doc["pages"][0]["regions"][0]["target_full"] = json!("سلام دوست من");
    put_document(&fixture, &doc);
    // Re-render to isolate the missing content-review gate from freshness.
    success(&fixture.run(&["typeset", "--doc", "work/comic.json"], b""));
    let report = fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    );
    assert!(
        String::from_utf8_lossy(&report.stdout).contains("compressed-variant"),
        "{report:?}"
    );
    assert_eq!(report.status.code(), Some(1));
    let refused = fixture.run(
        &[
            "export",
            "--doc",
            "work/comic.json",
            "--out",
            "unreviewed.cbz",
        ],
        b"",
    );
    assert!(!refused.status.success());
    assert!(!fixture.cwd.join("unreviewed.cbz").exists());
    approve(&fixture, "compressed-variant");
    success(&fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    ));
    success(&fixture.run(
        &[
            "export",
            "--doc",
            "work/comic.json",
            "--out",
            "approved.cbz",
        ],
        b"",
    ));
    let approved = fs::read(fixture.cwd.join("approved.cbz")).unwrap();
    let mut doc = document(&fixture);
    doc["pages"][0]["regions"][0]["bbox"][0] = json!(66);
    put_document(&fixture, &doc);
    let stale = fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    );
    assert!(!stale.status.success());
    assert!(
        String::from_utf8_lossy(&stale.stdout).contains("stale-stage"),
        "{stale:?}"
    );
    let stale_export = fixture.run(
        &[
            "export",
            "--doc",
            "work/comic.json",
            "--out",
            "approved.cbz",
        ],
        b"",
    );
    assert!(!stale_export.status.success());
    assert_eq!(
        fs::read(fixture.cwd.join("approved.cbz")).unwrap(),
        approved
    );
    for stage in ["mask", "clean", "typeset"] {
        success(&fixture.run(&[stage, "--doc", "work/comic.json"], b""));
    }
    approve(&fixture, "compressed-variant");
    success(&fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    ));
    success(&fixture.run(
        &[
            "export",
            "--doc",
            "work/comic.json",
            "--out",
            "approved.cbz",
        ],
        b"",
    ));
}

#[test]
fn empty_mask_processing_and_export_preserve_native_samples_and_alpha() {
    use image::{DynamicImage, ImageBuffer, Luma, Rgba};
    use std::io::Read;
    let rgba = DynamicImage::ImageRgba8(ImageBuffer::from_fn(64, 48, |x, y| {
        Rgba([
            (x * 3) as u8,
            (y * 5) as u8,
            123,
            [0, 31, 128, 255][((x + y) % 4) as usize],
        ])
    }));
    let gray = DynamicImage::ImageLuma16(ImageBuffer::from_fn(64, 48, |x, y| {
        Luma([((x + y * 64) * 19) as u16])
    }));
    for source in [rgba, gray] {
        let fixture = Fixture::staged();
        fs::create_dir(fixture.cwd.join("source")).unwrap();
        source.save(fixture.cwd.join("source/page.png")).unwrap();
        let source_bytes = fs::read(fixture.cwd.join("source/page.png")).unwrap();
        success(&fixture.run(&["import", "source", "--out", "work"], b""));
        for stage in ["mask", "clean", "typeset"] {
            success(&fixture.run(&[stage, "--doc", "work/comic.json"], b""));
        }
        success(&fixture.run(
            &["qa", "check", "--strict", "--doc", "work/comic.json"],
            b"",
        ));
        let doc = document(&fixture);
        for field in ["image", "clean", "final"] {
            let path = fixture
                .cwd
                .join("work")
                .join(doc["pages"][0][field].as_str().unwrap());
            let actual = image::open(path).unwrap();
            assert_eq!(
                actual.color(),
                source.color(),
                "{field} silently converted the native format"
            );
            assert_eq!(
                actual.as_bytes(),
                source.as_bytes(),
                "{field} changed an unmasked sample"
            );
        }
        success(&fixture.run(
            &["export", "--doc", "work/comic.json", "--out", "native.cbz"],
            b"",
        ));
        let mut archive =
            zip::ZipArchive::new(File::open(fixture.cwd.join("native.cbz")).unwrap()).unwrap();
        let mut bytes = Vec::new();
        archive
            .by_name("0001.png")
            .unwrap()
            .read_to_end(&mut bytes)
            .unwrap();
        let actual = image::load_from_memory(&bytes).unwrap();
        assert_eq!(actual.color(), source.color());
        assert_eq!(actual.as_bytes(), source.as_bytes());
        assert_eq!(
            fs::read(fixture.cwd.join("source/page.png")).unwrap(),
            source_bytes
        );

        // An independently forged RGB8 output must fail the native-channel QA oracle.
        let mut doc = doc;
        let native_final = doc["pages"][0]["final"].clone();
        let native_digest = doc["pages"][0]["delivery"]["final"].clone();
        let forged = fixture.cwd.join("forged.png");
        source.to_rgb8().save(&forged).unwrap();
        let digest = revayat_ir::ir::sha256_file(&forged).unwrap();
        let forged_final = format!("rendered/forged-{digest}.png");
        fs::copy(&forged, fixture.cwd.join("work").join(&forged_final)).unwrap();
        doc["pages"][0]["final"] = json!(forged_final);
        doc["pages"][0]["delivery"]["final"] = json!(digest);
        put_document(&fixture, &doc);
        let qa = fixture.run(
            &["qa", "check", "--strict", "--doc", "work/comic.json"],
            b"",
        );
        assert_eq!(qa.status.code(), Some(1));
        assert!(json_stdout(&qa)["artwork_pixels_changed"].as_u64().unwrap() > 0);
        doc["pages"][0]["final"] = native_final;
        doc["pages"][0]["delivery"]["final"] = native_digest;
        let forged_clean = format!("clean/forged-{digest}.png");
        fs::copy(&forged, fixture.cwd.join("work").join(&forged_clean)).unwrap();
        doc["pages"][0]["clean"] = json!(forged_clean);
        doc["pages"][0]["cleaning"]["clean"] = json!(digest);
        doc["pages"][0]["delivery"]["clean"] = json!(digest);
        put_document(&fixture, &doc);
        let qa = fixture.run(
            &["qa", "check", "--strict", "--doc", "work/comic.json"],
            b"",
        );
        assert_eq!(
            qa.status.code(),
            Some(1),
            "native cleaning loss must not be hidden by an intact final output"
        );
        assert!(json_stdout(&qa)["artwork_pixels_changed"].as_u64().unwrap() > 0);
    }
}

#[test]
fn processed_chapter_batch_plan_merge_and_replay_keep_owned_artifacts() {
    let fixture = Fixture::staged();
    rendered_balloon(&fixture);
    let before = document(&fixture);
    success(&fixture.run(
        &[
            "batch",
            "plan",
            "--doc",
            "work/comic.json",
            "--out",
            "shards",
            "--shards",
            "1",
        ],
        b"",
    ));
    success(&fixture.run(
        &[
            "batch",
            "merge",
            "--doc",
            "work/comic.json",
            "--batch",
            "shards",
        ],
        b"",
    ));
    let after = document(&fixture);
    assert_eq!(after["pages"], before["pages"]);
    success(&fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    ));
    let replay = fixture.run(
        &[
            "batch",
            "merge",
            "--doc",
            "work/comic.json",
            "--batch",
            "shards",
        ],
        b"",
    );
    success(&replay);
    assert_eq!(document(&fixture)["pages"], before["pages"]);
}

#[test]
fn detection_refuses_invalid_controls_without_mutating_the_chapter() {
    let fixture = Fixture::staged();
    import_blank_pages(&fixture, 1);
    let path = fixture.cwd.join("work/comic.json");
    let before = fs::read(&path).unwrap();
    for args in [
        vec!["--gutter-max-ink", "NaN"],
        vec!["--balloon-min-area", "0.9", "--balloon-max-area", "0.1"],
        vec!["--sfx-min-glyphs", "0"],
        vec!["--pages", "unknown-page"],
    ] {
        let mut command = vec!["detect", "--doc", "work/comic.json"];
        command.extend(args);
        assert!(!fixture.run(&command, b"").status.success());
        assert_eq!(fs::read(&path).unwrap(), before);
    }
}

#[test]
fn watermark_refuses_partial_boxes_without_committing_earlier_pages() {
    use image::{Rgb, RgbImage};
    let fixture = Fixture::staged();
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    for (name, width) in [("001.png", 128), ("002.png", 64)] {
        RgbImage::from_pixel(width, 128, Rgb([255; 3]))
            .save(fixture.cwd.join("source").join(name))
            .unwrap();
    }
    success(&fixture.run(&["import", "source", "--out", "work"], b""));
    let path = fixture.cwd.join("work/comic.json");
    let before = fs::read(&path).unwrap();
    let refused = fixture.run(
        &[
            "watermark",
            "--doc",
            "work/comic.json",
            "--box",
            "60 10 10 10",
        ],
        b"",
    );
    assert!(!refused.status.success());
    assert!(String::from_utf8_lossy(&refused.stderr).contains("outside"));
    assert_eq!(fs::read(&path).unwrap(), before);
    success(&fixture.run(
        &[
            "watermark",
            "--doc",
            "work/comic.json",
            "--box",
            "60 118 4 10",
        ],
        b"",
    ));
    for page in document(&fixture)["pages"].as_array().unwrap() {
        assert_eq!(page["regions"][0]["bbox"], json!([60, 118, 4, 10]));
    }
}

#[test]
fn detector_keeps_panel_dialogue_together_in_both_source_directions() {
    use image::{Rgb, RgbImage};
    for direction in ["rtl", "ltr"] {
        let fixture = Fixture::staged();
        fs::create_dir(fixture.cwd.join("source")).unwrap();
        let mut source = RgbImage::from_pixel(500, 420, Rgb([42; 3]));
        for y in 0..420 {
            for x in 244..256 {
                source.put_pixel(x, y, Rgb([255; 3]));
            }
        }
        for (cx, cy) in [(120, 75), (380, 75), (120, 285), (380, 285)] {
            for y in cy - 56..cy + 56 {
                for x in cx - 66..cx + 66 {
                    let distance = ((f64::from(x) - f64::from(cx)) / 65.).powi(2)
                        + ((f64::from(y) - f64::from(cy)) / 55.).powi(2);
                    if distance < 0.88 {
                        source.put_pixel(x, y, Rgb([245; 3]));
                    } else if distance <= 1. {
                        source.put_pixel(x, y, Rgb([12; 3]));
                    }
                }
            }
            for y in cy - 6..cy + 6 {
                for x in (cx - 12..cx - 4).chain(cx + 4..cx + 12) {
                    source.put_pixel(x, y, Rgb([20; 3]));
                }
            }
        }
        source.save(fixture.cwd.join("source/page.png")).unwrap();
        success(&fixture.run(
            &[
                "import",
                "source",
                "--out",
                "work",
                "--direction",
                direction,
            ],
            b"",
        ));
        success(&fixture.run(&["detect", "--doc", "work/comic.json", "--no-sfx"], b""));
        let doc = document(&fixture);
        let regions = doc["pages"][0]["regions"].as_array().unwrap();
        assert_eq!(doc["pages"][0]["panels"].as_array().unwrap().len(), 2);
        assert_eq!(regions.len(), 4);
        let right = regions
            .iter()
            .map(|region| region["bbox"][0].as_u64().unwrap() > 250)
            .collect::<Vec<_>>();
        assert_eq!(
            right,
            if direction == "rtl" {
                vec![true, true, false, false]
            } else {
                vec![false, false, true, true]
            }
        );
        assert_eq!(regions[0]["panel"], regions[1]["panel"]);
        assert_ne!(regions[1]["panel"], regions[2]["panel"]);
        assert!(regions.iter().all(|region| region["panel"].is_string()));
        success(&fixture.run(&["mask", "--doc", "work/comic.json"], b""));
        success(&fixture.run(&["crops", "--doc", "work/comic.json"], b""));
    }
}

#[test]
fn non_draft_export_requires_strict_image_and_linguistic_qa() {
    let fixture = Fixture::staged();
    rendered_balloon(&fixture);
    let mut doc = document(&fixture);
    doc["pages"][0]["regions"][0]["target_text"] = json!("خانه تر");
    put_document(&fixture, &doc);
    success(&fixture.run(&["typeset", "--doc", "work/comic.json"], b""));
    let qa = fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    );
    assert_eq!(qa.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&qa.stdout).contains("zwnj-review"));
    let refused = fixture.run(
        &[
            "export",
            "--doc",
            "work/comic.json",
            "--out",
            "unreviewed.cbz",
        ],
        b"",
    );
    assert!(
        !refused.status.success(),
        "unreviewed output was published: {refused:?}"
    );
    assert!(!fixture.cwd.join("unreviewed.cbz").exists());
    success(&fixture.run(
        &[
            "export",
            "--doc",
            "work/comic.json",
            "--out",
            "draft.cbz",
            "--draft",
        ],
        b"",
    ));
    approve(&fixture, "zwnj-review");
    success(&fixture.run(
        &[
            "export",
            "--doc",
            "work/comic.json",
            "--out",
            "reviewed.cbz",
        ],
        b"",
    ));
}

fn assert_changed_proof_mask_is_rejected(field: &str) {
    let fixture = Fixture::staged();
    rendered_balloon(&fixture);
    let export = [
        "export",
        "--doc",
        "work/comic.json",
        "--out",
        "approved.cbz",
    ];
    success(&fixture.run(&export, b""));
    let before_output = fs::read(fixture.cwd.join("approved.cbz")).unwrap();
    let before_doc = fs::read(fixture.cwd.join("work/comic.json")).unwrap();
    let doc = document(&fixture);
    let path = fixture
        .cwd
        .join("work")
        .join(doc["pages"][0][field].as_str().unwrap());
    let mut mask = image::open(&path).unwrap().into_luma8();
    mask.put_pixel(280, 280, image::Luma([255]));
    mask.save(&path).unwrap();
    let refused = fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    );
    assert!(
        !refused.status.success(),
        "QA accepted changed {field}: {refused:?}"
    );
    assert!(!fixture.run(&export, b"").status.success());
    assert_eq!(
        fs::read(fixture.cwd.join("approved.cbz")).unwrap(),
        before_output
    );
    assert_eq!(
        fs::read(fixture.cwd.join("work/comic.json")).unwrap(),
        before_doc
    );
    for stage in ["mask", "clean", "typeset"] {
        success(&fixture.run(&[stage, "--doc", "work/comic.json"], b""));
    }
    success(&fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    ));
    success(&fixture.run(&export, b""));
}

#[test]
fn publication_rejects_changed_clean_mask_and_recovers_after_rebuilding() {
    assert_changed_proof_mask_is_rejected("clean_mask");
}

#[test]
fn publication_rejects_changed_authorized_mask_and_recovers_after_rebuilding() {
    assert_changed_proof_mask_is_rejected("authorized_mask");
}

#[test]
fn cleaning_rejects_a_changed_region_mask_before_consuming_it() {
    let fixture = Fixture::staged();
    let mut doc = import_blank_pages(&fixture, 1);
    let id = doc["pages"][0]["id"].as_str().unwrap();
    let mut region = revayat_ir::ir::new_region(
        format!("{id}r001"),
        [20., 20., 60., 30.],
        "title",
        "horizontal",
        "manual",
        1.,
    )
    .unwrap();
    region.source_text = "Hello".into();
    region.target_text = "سلام".into();
    doc["pages"][0]["regions"] = json!([region]);
    put_document(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", "work/comic.json"], b""));
    let before = fs::read(fixture.cwd.join("work/comic.json")).unwrap();
    let doc = document(&fixture);
    let path = fixture
        .cwd
        .join("work")
        .join(doc["pages"][0]["regions"][0]["mask"].as_str().unwrap());
    let mut mask = image::open(&path).unwrap().into_luma8();
    mask.put_pixel(0, 0, image::Luma([255]));
    mask.save(&path).unwrap();
    let refused = fixture.run(&["clean", "--doc", "work/comic.json"], b"");
    assert!(
        !refused.status.success(),
        "clean consumed a changed mask: {refused:?}"
    );
    assert_eq!(
        fs::read(fixture.cwd.join("work/comic.json")).unwrap(),
        before
    );
    success(&fixture.run(&["mask", "--doc", "work/comic.json"], b""));
    success(&fixture.run(&["clean", "--doc", "work/comic.json"], b""));
}

#[test]
fn publication_rejects_changed_panel_geometry_and_recovers() {
    let fixture = Fixture::staged();
    rendered_balloon(&fixture);
    let export = [
        "export",
        "--doc",
        "work/comic.json",
        "--out",
        "approved.cbz",
    ];
    success(&fixture.run(&export, b""));
    let before_output = fs::read(fixture.cwd.join("approved.cbz")).unwrap();
    let mut doc = document(&fixture);
    doc["pages"][0]["panels"] = json!([{"id":"p0001p001","bbox":[0,0,150,300]}]);
    put_document(&fixture, &doc);
    let before_doc = fs::read(fixture.cwd.join("work/comic.json")).unwrap();
    let refused = fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    );
    assert!(
        !refused.status.success(),
        "QA accepted changed panels: {refused:?}"
    );
    assert!(String::from_utf8_lossy(&refused.stdout).contains("stale-stages"));
    assert!(!fixture.run(&export, b"").status.success());
    assert_eq!(
        fs::read(fixture.cwd.join("approved.cbz")).unwrap(),
        before_output
    );
    assert_eq!(
        fs::read(fixture.cwd.join("work/comic.json")).unwrap(),
        before_doc
    );
    for stage in ["mask", "clean", "typeset"] {
        success(&fixture.run(&[stage, "--doc", "work/comic.json"], b""));
    }
    success(&fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    ));
    success(&fixture.run(&export, b""));
}

fn assert_free_ink_pipeline(contrasts: &[(u8, u8)], state_only: bool) {
    use image::{Luma, Rgb, RgbImage};
    for &(paper, ink) in contrasts {
        let fixture = Fixture::staged();
        fs::create_dir(fixture.cwd.join("source")).unwrap();
        let mut original = RgbImage::from_pixel(100, 80, Rgb([paper; 3]));
        for y in 35..42 {
            for x in 40..46 {
                original.put_pixel(x, y, Rgb([ink; 3]));
            }
        }
        original.save(fixture.cwd.join("source/page.png")).unwrap();
        success(&fixture.run(&["import", "source", "--out", "work"], b""));
        let mut doc = document(&fixture);
        let mut region = revayat_ir::ir::new_region(
            "p0001r001",
            [35., 30., 20., 20.],
            "title",
            "horizontal",
            "manual",
            1.,
        )
        .unwrap();
        if state_only {
            region.state = Some(revayat_ir::RegionState::Erased);
        } else {
            region.erase = true;
        }
        region.locked = true;
        region.extra.insert(
            "polarity".into(),
            json!(if ink > paper { "dark" } else { "light" }),
        );
        doc["pages"][0]["regions"] = json!([region]);
        put_document(&fixture, &doc);
        for stage in ["mask", "clean"] {
            success(&fixture.run(&[stage, "--doc", "work/comic.json"], b""));
        }
        let doc = document(&fixture);
        let root = fixture.cwd.join("work");
        let clean = image::open(root.join(doc["pages"][0]["clean"].as_str().unwrap()))
            .unwrap()
            .into_rgb8();
        let mask = image::open(root.join(doc["pages"][0]["clean_mask"].as_str().unwrap()))
            .unwrap()
            .into_luma8();
        assert_eq!(mask.get_pixel(42, 38), &Luma([255]));
        assert_eq!(clean.get_pixel(42, 38), &Rgb([paper; 3]));
        for (x, y, pixel) in original.enumerate_pixels() {
            if mask.get_pixel(x, y)[0] == 0 {
                assert_eq!(clean.get_pixel(x, y), pixel);
            }
        }
        success(&fixture.run(
            &["qa", "check", "--strict", "--doc", "work/comic.json"],
            b"",
        ));
        success(&fixture.run(
            &["export", "--doc", "work/comic.json", "--out", "erased.cbz"],
            b"",
        ));
    }
}

#[test]
fn free_ink_contrasts_survive_the_public_mask_clean_export_pipeline() {
    assert_free_ink_pipeline(&[(245, 200), (160, 20), (10, 55), (95, 235)], false);
}

#[test]
fn state_only_erasure_runs_the_public_mask_clean_export_pipeline() {
    assert_free_ink_pipeline(&[(245, 20)], true);
}

#[test]
fn source_filenames_with_digest_like_suffixes_are_not_derived_proofs() {
    let fixture = Fixture::staged();
    let mut doc = import_blank_pages(&fixture, 1);
    let root = fixture.cwd.join("work");
    let name = format!("images/source-{}.png", "0".repeat(64));
    fs::create_dir_all(root.join("images")).unwrap();
    fs::copy(
        root.join(doc["pages"][0]["image"].as_str().unwrap()),
        root.join(&name),
    )
    .unwrap();
    doc["pages"][0]["image"] = json!(name);
    put_document(&fixture, &doc);
    for stage in ["mask", "clean", "typeset"] {
        success(&fixture.run(&[stage, "--doc", "work/comic.json"], b""));
    }
    success(&fixture.run(
        &["qa", "check", "--strict", "--doc", "work/comic.json"],
        b"",
    ));
}

#[cfg(unix)]
#[test]
fn typesetting_validates_the_named_mask_before_following_an_internal_symlink() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::staged();
    rendered_balloon(&fixture);
    let doc = document(&fixture);
    let root = fixture.cwd.join("work");
    let path = root.join(doc["pages"][0]["clean_mask"].as_str().unwrap());
    let mut mask = image::open(&path).unwrap().into_luma8();
    mask.put_pixel(280, 280, image::Luma([255]));
    let replacement = root.join("replacement.png");
    mask.save(&replacement).unwrap();
    let replacement_hash = revayat_ir::ir::sha256_file(&replacement).unwrap();
    let renamed = path
        .parent()
        .unwrap()
        .join(format!("replacement-{replacement_hash}.png"));
    fs::rename(replacement, &renamed).unwrap();
    fs::remove_file(&path).unwrap();
    symlink(&renamed, &path).unwrap();
    let before = fs::read(root.join("comic.json")).unwrap();
    let refused = fixture.run(&["typeset", "--doc", "work/comic.json"], b"");
    assert!(
        !refused.status.success(),
        "typeset accepted a substituted proof: {refused:?}"
    );
    assert_eq!(fs::read(root.join("comic.json")).unwrap(), before);
}
