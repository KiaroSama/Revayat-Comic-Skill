use super::*;
use image::{Rgb, RgbImage};

const DOC: &str = "work/comic.json";

fn read_doc(fixture: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(fixture.cwd.join(DOC)).unwrap()).unwrap()
}

fn write_doc(fixture: &Fixture, doc: &Value) {
    fs::write(fixture.cwd.join(DOC), serde_json::to_vec(doc).unwrap()).unwrap();
}

fn open_page(dark: bool, tiny: bool) -> RgbImage {
    RgbImage::from_fn(160, 140, |x, y| {
        let paper = (20..100).contains(&x) && (20..120).contains(&y);
        let ink = if tiny {
            [(40, 50), (40, 51), (41, 51)].contains(&(x, y))
        } else {
            (42..48).contains(&x) && (52..58).contains(&y)
        };
        let art = (79..83).contains(&x) && (99..103).contains(&y);
        let value = if paper && !ink && !art { 245 } else { 20 };
        Rgb([if dark { 255 - value } else { value }; 3])
    })
}

fn erased_region(tiny: bool, dark: bool, state_only: bool) -> Value {
    let mut region = json!({
        "id":"source", "kind":"speech", "locked":true,
        "bbox":if tiny { [40,50,2,2] } else { [36,46,20,20] },
        "source_text":"Source", "polarity":if dark { "dark" } else { "light" }
    });
    if state_only {
        region["state"] = json!("erased");
    } else {
        region["erase"] = json!(true);
    }
    region
}

fn import_pages(fixture: &Fixture, pages: &[RgbImage]) {
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    for (index, page) in pages.iter().enumerate() {
        page.save(fixture.cwd.join(format!("source/{index}.png")))
            .unwrap();
    }
    success(&fixture.run(&["import", "source", "--out", "work"], b""));
}

fn load_rgb(fixture: &Fixture, field: &Value) -> RgbImage {
    image::open(fixture.cwd.join("work").join(field.as_str().unwrap()))
        .unwrap()
        .into_rgb8()
}

fn clean_args(bubbles_only: bool) -> Vec<&'static str> {
    let mut args = vec!["clean", "--doc", DOC];
    if bubbles_only {
        args.push("--bubbles-only");
    }
    args
}

#[test]
fn open_balloon_cleanup_preserves_distant_art_through_strict_export() {
    for dark in [false, true] {
        for bubbles_only in [false, true] {
            let fixture = Fixture::staged();
            let source = open_page(dark, false);
            import_pages(&fixture, std::slice::from_ref(&source));
            let mut doc = read_doc(&fixture);
            doc["pages"][0]["panels"] = json!([{"bbox":[20,20,120,100]}]);
            doc["pages"][0]["regions"] = json!([erased_region(false, dark, bubbles_only)]);
            write_doc(&fixture, &doc);
            success(&fixture.run(&["mask", "--doc", DOC], b""));
            success(&fixture.run(&clean_args(bubbles_only), b""));
            let doc = read_doc(&fixture);
            let cleaned = load_rgb(&fixture, &doc["pages"][0]["clean"]);
            let mask = image::open(
                fixture
                    .cwd
                    .join("work")
                    .join(doc["pages"][0]["clean_mask"].as_str().unwrap()),
            )
            .unwrap()
            .into_luma8();
            assert_eq!(
                cleaned.get_pixel(44, 54),
                &Rgb([if dark { 10 } else { 245 }; 3])
            );
            assert_eq!(cleaned.get_pixel(80, 100), source.get_pixel(80, 100));
            assert_eq!(mask.get_pixel(80, 100)[0], 0);
            for (x, y, pixel) in source.enumerate_pixels() {
                if !(30..62).contains(&x) || !(40..72).contains(&y) {
                    assert_eq!(cleaned.get_pixel(x, y), pixel);
                    assert_eq!(mask.get_pixel(x, y)[0], 0);
                }
            }
            success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
            success(&fixture.run(&["export", "--doc", DOC, "--out", "result.cbz"], b""));
        }
    }
}

#[test]
fn solid_open_balloon_refuses_transactionally_and_recovers_with_approved_repair() {
    for dark in [false, true] {
        for bubbles_only in [false, true] {
            let fixture = Fixture::staged();
            let sources = [open_page(dark, false), open_page(dark, true)];
            import_pages(&fixture, &sources);
            success(&fixture.run(&["export", "--doc", DOC, "--out", "last-good.cbz"], b""));
            let last_good = fs::read(fixture.cwd.join("last-good.cbz")).unwrap();
            let mut doc = read_doc(&fixture);
            for index in 0..2 {
                doc["pages"][index]["panels"] = json!([{"bbox":[20,20,120,100]}]);
                let mut region = erased_region(index == 1, dark, bubbles_only);
                region["id"] = json!(format!("source{index}"));
                doc["pages"][index]["regions"] = json!([region]);
            }
            write_doc(&fixture, &doc);
            success(&fixture.run(&["mask", "--doc", DOC], b""));
            let before = fs::read(fixture.cwd.join(DOC)).unwrap();
            let refused = fixture.run(&clean_args(bubbles_only), b"");
            assert!(
                !refused.status.success(),
                "a solid source mask cannot complete as NoInk"
            );
            assert!(String::from_utf8_lossy(&refused.stderr).contains("approved external repair"));
            assert_eq!(fs::read(fixture.cwd.join(DOC)).unwrap(), before);
            assert_eq!(
                fs::read(fixture.cwd.join("last-good.cbz")).unwrap(),
                last_good
            );

            let doc = read_doc(&fixture);
            fs::create_dir(fixture.cwd.join("external")).unwrap();
            for (index, page) in doc["pages"].as_array().unwrap().iter().enumerate() {
                // Deliberately change every external pixel; only the local authorization may be copied.
                let external =
                    RgbImage::from_pixel(160, 140, Rgb([if dark { 10 } else { 245 }; 3]));
                let page_id = page["id"].as_str().unwrap();
                external
                    .save(fixture.cwd.join(format!("external/{page_id}.png")))
                    .unwrap();
                assert_eq!(sources[index].dimensions(), external.dimensions());
            }
            let mut args = clean_args(bubbles_only);
            args.extend(["--external-dir", "external"]);
            success(&fixture.run(&args, b""));
            let doc = read_doc(&fixture);
            assert_eq!(doc["pages"][1]["regions"][0]["fill"], "external");
            for (index, source) in sources.iter().enumerate() {
                let page = &doc["pages"][index];
                let cleaned = load_rgb(&fixture, &page["clean"]);
                let mask = image::open(
                    fixture
                        .cwd
                        .join("work")
                        .join(page["clean_mask"].as_str().unwrap()),
                )
                .unwrap()
                .into_luma8();
                let ink = if index == 0 { (44, 54) } else { (40, 51) };
                assert_eq!(
                    cleaned.get_pixel(ink.0, ink.1),
                    &Rgb([if dark { 10 } else { 245 }; 3])
                );
                for (x, y, pixel) in source.enumerate_pixels() {
                    if mask.get_pixel(x, y)[0] == 0 {
                        assert_eq!(cleaned.get_pixel(x, y), pixel);
                    }
                }
                assert_eq!(cleaned.get_pixel(80, 100), source.get_pixel(80, 100));
            }
            success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
            success(&fixture.run(&["export", "--doc", DOC, "--out", "last-good.cbz"], b""));
            assert_ne!(
                fs::read(fixture.cwd.join("last-good.cbz")).unwrap(),
                last_good
            );
        }
    }
}

#[test]
fn translated_open_balloon_passes_strict_qa_with_preserved_distant_art() {
    for dark in [false, true] {
        let fixture = Fixture::staged();
        let source = open_page(dark, false);
        import_pages(&fixture, std::slice::from_ref(&source));
        let mut doc = read_doc(&fixture);
        let mut region = erased_region(false, dark, false);
        region.as_object_mut().unwrap().remove("erase");
        region["target_text"] = json!("باشه.");
        doc["pages"][0]["panels"] = json!([{"bbox":[20,20,120,100]}]);
        doc["pages"][0]["regions"] = json!([region]);
        write_doc(&fixture, &doc);
        for stage in ["mask", "clean", "typeset"] {
            success(&fixture.run(&[stage, "--doc", DOC], b""));
        }
        let doc = read_doc(&fixture);
        for field in ["clean", "final"] {
            let page = load_rgb(&fixture, &doc["pages"][0][field]);
            assert_eq!(page.get_pixel(80, 100), source.get_pixel(80, 100));
        }
        success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
        success(&fixture.run(&["export", "--doc", DOC, "--out", "translated.cbz"], b""));
    }
}

#[test]
fn kept_numeric_art_survives_full_interior_cleaning_and_typesetting() {
    for state_only in [false, true] {
        let fixture = Fixture::staged();
        let source = RgbImage::from_fn(220, 180, |x, y| {
            let paper = (30..190).contains(&x) && (30..150).contains(&y);
            let ink = (62..68).contains(&x) && (77..83).contains(&y);
            let badge = (150..160).contains(&x) && (70..88).contains(&y);
            Rgb([if paper && !ink && !badge { 245 } else { 20 }; 3])
        });
        import_pages(&fixture, std::slice::from_ref(&source));
        let mut doc = read_doc(&fixture);
        let mut kept =
            json!({"id":"badge", "bbox":[145,65,20,28], "kind":"title", "source_text":"15"});
        if state_only {
            kept["state"] = json!("kept");
        } else {
            kept["keep"] = json!(true);
        }
        doc["pages"][0]["panels"] = json!([{"bbox":[0,0,220,180]}]);
        doc["pages"][0]["regions"] = json!([
            {"id":"speech", "bbox":[54,68,25,28], "kind":"speech", "source_text":"Yes", "target_text":"باشه."},
            kept
        ]);
        write_doc(&fixture, &doc);
        for stage in ["mask", "clean", "typeset"] {
            success(&fixture.run(&[stage, "--doc", DOC], b""));
        }
        let doc = read_doc(&fixture);
        for field in ["clean", "final"] {
            let page = load_rgb(&fixture, &doc["pages"][0][field]);
            for y in 65..93 {
                for x in 145..165 {
                    assert_eq!(page.get_pixel(x, y), source.get_pixel(x, y));
                }
            }
        }
        success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
        success(&fixture.run(&["export", "--doc", DOC, "--out", "kept.cbz"], b""));
    }
}

#[test]
fn bubbles_only_external_recovery_does_not_process_on_art_regions() {
    let fixture = Fixture::staged();
    let mut source = open_page(false, true);
    for y in 55..60 {
        for x in 118..123 {
            source.put_pixel(x, y, Rgb([245; 3]));
        }
    }
    import_pages(&fixture, std::slice::from_ref(&source));
    let mut doc = read_doc(&fixture);
    doc["pages"][0]["panels"] = json!([{"bbox":[20,20,120,100]}]);
    doc["pages"][0]["regions"] = json!([
        erased_region(true, false, false),
        {"id":"onart", "bbox":[112,49,20,20], "kind":"title", "polarity":"dark", "erase":true}
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    let doc = read_doc(&fixture);
    let page_id = doc["pages"][0]["id"].as_str().unwrap();
    fs::create_dir(fixture.cwd.join("external")).unwrap();
    let mut external = RgbImage::from_pixel(160, 140, Rgb([220, 80, 30]));
    for y in 48..54 {
        for x in 38..44 {
            external.put_pixel(x, y, Rgb([245; 3]));
        }
    }
    external
        .save(fixture.cwd.join(format!("external/{page_id}.png")))
        .unwrap();
    success(&fixture.run(
        &[
            "clean",
            "--doc",
            DOC,
            "--bubbles-only",
            "--external-dir",
            "external",
        ],
        b"",
    ));
    let doc = read_doc(&fixture);
    assert_eq!(doc["pages"][0]["regions"][0]["fill"], "external");
    assert_eq!(doc["pages"][0]["regions"][1]["fill"], "none");
    let cleaned = load_rgb(&fixture, &doc["pages"][0]["clean"]);
    assert_eq!(cleaned.get_pixel(40, 51), &Rgb([245; 3]));
    for (x, y, pixel) in source.enumerate_pixels() {
        if !(38..44).contains(&x) || !(48..54).contains(&y) {
            assert_eq!(cleaned.get_pixel(x, y), pixel);
        }
    }
}

#[test]
fn large_faint_open_source_is_removed_before_final_publication() {
    for dark in [false, true] {
        for translated in [false, true] {
            let fixture = Fixture::staged();
            let source = RgbImage::from_fn(160, 140, |x, y| {
                let paper = (20..100).contains(&x) && (20..120).contains(&y);
                let ink = (45..65).contains(&x) && (55..75).contains(&y);
                let art = (79..83).contains(&x) && (99..103).contains(&y);
                let value = if !paper || art {
                    20
                } else if ink {
                    200
                } else {
                    245
                };
                Rgb([if dark { 255 - value } else { value }; 3])
            });
            import_pages(&fixture, std::slice::from_ref(&source));
            let mut doc = read_doc(&fixture);
            let mut region = erased_region(false, dark, false);
            region["bbox"] = json!([40, 50, 30, 30]);
            if translated {
                region.as_object_mut().unwrap().remove("erase");
                region["target_text"] = json!("باشه.");
            }
            doc["pages"][0]["panels"] = json!([{"bbox":[20,20,120,100]}]);
            doc["pages"][0]["regions"] = json!([region]);
            write_doc(&fixture, &doc);
            success(&fixture.run(&["mask", "--doc", DOC], b""));
            success(&fixture.run(&["clean", "--doc", DOC], b""));
            let doc = read_doc(&fixture);
            let cleaned = load_rgb(&fixture, &doc["pages"][0]["clean"]);
            assert_eq!(
                cleaned.get_pixel(50, 60),
                &Rgb([if dark { 10 } else { 245 }; 3])
            );
            assert_eq!(cleaned.get_pixel(80, 100), source.get_pixel(80, 100));
            if translated {
                success(&fixture.run(&["typeset", "--doc", DOC], b""));
            }
            success(&fixture.run(&["qa", "check", "--strict", "--doc", DOC], b""));
            success(&fixture.run(&["export", "--doc", DOC, "--out", "faint.cbz"], b""));
        }
    }
}
