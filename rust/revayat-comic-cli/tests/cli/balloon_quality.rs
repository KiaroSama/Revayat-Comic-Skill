use super::*;

#[test]
fn synthetic_cbz_round_trip_preserves_artwork_and_exports_all_formats() {
    use image::{DynamicImage, ImageFormat, Rgb, RgbImage};
    use std::io::{Cursor, Write};
    use zip::{ZipWriter, write::SimpleFileOptions};

    let fixture = Fixture::staged();
    let mut page = RgbImage::from_pixel(300, 300, Rgb([42; 3]));
    for y in 12..118 {
        for x in 20..140 {
            let dx = (f64::from(x) - 80.0) / 58.0;
            let dy = (f64::from(y) - 65.0) / 50.0;
            let distance = dx * dx + dy * dy;
            if distance < 0.88 {
                page.put_pixel(x, y, Rgb([245; 3]));
            } else if distance <= 1.0 {
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
    let mut png = Cursor::new(Vec::new());
    DynamicImage::ImageRgb8(page.clone())
        .write_to(&mut png, ImageFormat::Png)
        .unwrap();
    let mut zip = ZipWriter::new(File::create(fixture.cwd.join("source.cbz")).unwrap());
    zip.start_file("1.png", SimpleFileOptions::default())
        .unwrap();
    zip.write_all(png.get_ref()).unwrap();
    zip.finish().unwrap();

    let run = |args: &[&str]| {
        let output = fixture.run(args, b"");
        assert!(
            output.status.success(),
            "{args:?}: {} {}",
            String::from_utf8_lossy(&output.stderr),
            String::from_utf8_lossy(&output.stdout)
        );
        json_stdout(&output)
    };
    const DOC: &str = "comic work/comic.json";
    let imported = run(&[
        "import",
        "source.cbz",
        "--out",
        "comic work",
        "--direction",
        "rtl",
    ]);
    let id = imported["pages"][0]["id"].as_str().unwrap();
    let original = fixture
        .cwd
        .join("comic work")
        .join(imported["pages"][0]["image"].as_str().unwrap());
    assert_eq!(fs::read(&original).unwrap(), *png.get_ref());
    assert!(run(&["detect", "--doc", DOC])["regions"].as_u64().unwrap() > 0);
    assert!(run(&["mask", "--doc", DOC])["masks"].as_u64().unwrap() > 0);
    assert!(run(&["crops", "--doc", DOC])["crops"].as_u64().unwrap() > 0);
    let built = run(&["worksheet", "build", "--doc", DOC]);
    let draft = PathBuf::from(built["built"][0].as_str().unwrap());
    let text = fs::read_to_string(&draft).unwrap();
    for header in [
        "# overview: sheets/",
        "# sheets: sheets/",
        "# scale:",
        "# source_language: auto",
        "# reading_direction: rtl",
        "# sfx_policy: keep",
    ] {
        assert!(text.contains(header), "{header}: {text}");
    }
    let filled = text
        .replace("src:\n", "src: Hello!\n")
        .replace("fa:\n", "fa: سلام، خوبي؟!\nlock: yes\n");
    assert_ne!(text, filled);
    fs::write(draft.with_file_name(format!("{id}.done.txt")), filled).unwrap();
    run(&["worksheet", "merge", "--doc", DOC]);
    let doc_path = fixture.cwd.join(DOC);
    let read_doc = || serde_json::from_slice::<Value>(&fs::read(&doc_path).unwrap()).unwrap();
    assert!(
        run(&["falint", "fix", "--doc", DOC])["changed"]
            .as_u64()
            .unwrap()
            > 0
    );
    assert!(read_doc()["pages"][0]["regions"][0]["locked"] == true);
    assert!(
        read_doc()["pages"][0]["regions"][0]["target_text"]
            .as_str()
            .unwrap()
            .contains("خوبی")
    );
    run(&["clean", "--doc", DOC, "--bubbles-only"]);
    let default = run(&["fullpage-prompt", "--doc", DOC, "--page", id]);
    assert_eq!(default["model_id"], "antigravity/gemini-3.1-flash-image");
    assert!(
        default["regions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|r| r["kind"] != "balloon")
    );
    let manifest = run(&[
        "fullpage-prompt",
        "--doc",
        DOC,
        "--page",
        id,
        "--all-regions",
    ]);
    assert_eq!(manifest["schema_version"], 1);
    assert_eq!(manifest["page_id"], id);
    assert_eq!(manifest["page_size"], json!([300, 300]));
    assert!(!manifest["regions"].as_array().unwrap().is_empty());
    assert!(manifest["prompt"].as_str().unwrap().contains("سلام"));
    // Read an older work folder whose cleaning proof exists but whose balloon metadata was lost.
    let mut work = read_doc();
    let regions = work["pages"][0]["regions"].as_array_mut().unwrap();
    let bubble = regions
        .iter_mut()
        .find(|r| r.get("balloon").is_some())
        .unwrap();
    let bubble_id = bubble["id"].as_str().unwrap().to_owned();
    let [bx, by, bw, bh]: [u32; 4] =
        serde_json::from_value(bubble["balloon"]["bounds"].clone()).unwrap();
    assert!(bubble["balloon"]["contour"].as_array().unwrap().len() > 4);
    bubble.as_object_mut().unwrap().remove("balloon");
    fs::write(&doc_path, serde_json::to_vec_pretty(&work).unwrap()).unwrap();
    fs::create_dir(fixture.cwd.join("external")).unwrap();
    assert!(
        run(&["typeset", "--doc", DOC, "--external-dir", "external"])["typeset"]
            .as_u64()
            .unwrap()
            > 0
    );
    let output = read_doc();
    let rendered = output["pages"][0]["final"].as_str().unwrap();
    let clean = output["pages"][0]["clean"].as_str().unwrap();
    let rendered = fixture.cwd.join("comic work").join(rendered);
    let clean = fixture.cwd.join("comic work").join(clean);
    let clean = image::open(clean).unwrap().into_rgb8();
    let final_page = image::open(&rendered).unwrap().into_rgb8();
    for (x, y, pixel) in final_page.enumerate_pixels() {
        if (bx..bx + bw).contains(&x)
            && (by..by + bh).contains(&y)
            && clean.get_pixel(x, y)[0] < 180
        {
            assert_eq!(pixel, clean.get_pixel(x, y));
        }
    }
    let mut stale = output;
    let regions = stale["pages"][0]["regions"].as_array_mut().unwrap();
    let bubble = regions.iter_mut().find(|r| r["id"] == bubble_id).unwrap();
    assert!(bubble.get("balloon").is_some());
    bubble.as_object_mut().unwrap().remove("balloon");
    let mut tampered = final_page.clone();
    let (x, y) = page
        .enumerate_pixels()
        .filter(|(x, y, p)| (bx..bx + bw).contains(x) && (by..by + bh).contains(y) && p[0] == 12)
        .map(|(x, y, _)| (x, y))
        .next()
        .unwrap();
    tampered.put_pixel(x, y, Rgb([199; 3]));
    bubble["typeset"]["ink_box"] = json!([bx, by, bw, bh]);
    fs::write(&doc_path, serde_json::to_vec_pretty(&stale).unwrap()).unwrap();
    tampered.save(&rendered).unwrap();
    let report = fixture.run(&["qa", "check", "--strict", "--doc", DOC], b"");
    assert!(!report.status.success());
    let report = json_stdout(&report);
    assert!(
        report["findings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|f| f["finding"]["code"] == "text-crosses-outline"
                && f["finding"]["region"] == bubble_id),
        "{report}"
    );
    clean.save(&rendered).unwrap();
    let report = fixture.run(&["qa", "check", "--strict", "--doc", DOC], b"");
    assert!(!report.status.success());
    let report = json_stdout(&report);
    assert!(
        report["findings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|f| f["code"] == "missing-glyph-coverage" && f["region"] == bubble_id),
        "{report}"
    );
    run(&["typeset", "--doc", DOC]);
    let qa = run(&["qa", "check", "--strict", "--doc", DOC]);
    assert_eq!(qa["artwork_pixels_changed"], 0);
    run(&[
        "export",
        "--doc",
        DOC,
        "--out",
        "translated.cbz",
        "--review-docx",
        "review.docx",
    ]);
    run(&["export", "--doc", DOC, "--out", "translated.pdf"]);
    for path in ["translated.cbz", "translated.pdf"] {
        assert_eq!(
            run(&["qa", "package", "--doc", DOC, "--package", path])["ok"],
            true
        );
    }
    let review = File::open(fixture.cwd.join("review.docx")).unwrap();
    assert!(
        zip::ZipArchive::new(review)
            .unwrap()
            .by_name("word/document.xml")
            .is_ok()
    );
    assert_eq!(fs::read(original).unwrap(), *png.get_ref());
}

#[test]
fn hybrid_edits_replace_only_on_art_ink_and_keep_gloss_policies_nondestructive() {
    use image::{Rgb, RgbImage};
    let fixture = Fixture::staged();
    let mut source = RgbImage::from_pixel(260, 140, Rgb([230; 3]));
    for (x, y, pixel) in source.enumerate_pixels_mut() {
        let (dx, dy) = ((f64::from(x) - 70.) / 53., (f64::from(y) - 70.) / 46.);
        let d = dx * dx + dy * dy;
        if d < 0.86 {
            *pixel = Rgb([245; 3]);
        } else if d <= 1. {
            *pixel = Rgb([18; 3]);
        }
        if (62..78).contains(&x) && (64..75).contains(&y)
            || (176..208).contains(&x) && (54..78).contains(&y)
        {
            *pixel = Rgb([22; 3]);
        }
    }
    let input = fixture.cwd.join("source");
    fs::create_dir(&input).unwrap();
    source.save(input.join("page.png")).unwrap();
    fs::create_dir(fixture.cwd.join("external")).unwrap();
    let run = |args: &[&str]| {
        let output = fixture.run(args, b"");
        success(&output);
        json_stdout(&output)
    };
    const DOC: &str = "work/comic.json";
    let imported = run(&["import", "source", "--out", "work"]);
    let id = imported["pages"][0]["id"].as_str().unwrap();
    let external = fixture.cwd.join("external").join(format!("{id}.png"));
    let path = fixture.cwd.join(DOC);
    let read_doc = || serde_json::from_slice::<Value>(&fs::read(&path).unwrap()).unwrap();
    let mut doc = read_doc();
    doc["meta"]["sfx_policy"] = json!("translate");
    doc["pages"][0]["regions"] = json!([
        {"id":format!("{id}r001"), "bbox":[59,60,22,22], "kind":"speech", "orientation":"horizontal", "reading_order":0, "source_text":"Yes", "target_text":"باشه."},
        {"id":format!("{id}r002"), "bbox":[171,50,44,34], "kind":"sfx", "orientation":"horizontal", "reading_order":1, "source_text":"Boom", "target_text":"بوم!"}
    ]);
    fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    run(&["mask", "--doc", DOC, "--free-lettering", "solid"]);
    run(&["clean", "--doc", DOC, "--bubbles-only"]);
    let manifest = run(&["fullpage-prompt", "--doc", DOC, "--page", id]);
    assert_eq!(manifest["regions"].as_array().unwrap().len(), 1);
    assert_eq!(manifest["regions"][0]["kind"], "sfx");
    RgbImage::from_pixel(130, 70, Rgb([80; 3]))
        .save(&external)
        .unwrap();
    let rejected = fixture.run(
        &["typeset", "--doc", DOC, "--external-dir", "external"],
        b"",
    );
    assert!(!rejected.status.success());
    assert!(String::from_utf8_lossy(&rejected.stderr).contains("expected 260x140"));
    RgbImage::from_pixel(260, 140, Rgb([200, 40, 90]))
        .save(&external)
        .unwrap();
    assert_eq!(
        run(&["typeset", "--doc", DOC, "--external-dir", "external"])["typeset"],
        1
    );
    let rendered = || {
        let doc = read_doc();
        image::open(
            fixture
                .cwd
                .join("work")
                .join(doc["pages"][0]["final"].as_str().unwrap()),
        )
        .unwrap()
        .into_rgb8()
    };
    let page = rendered();
    assert_eq!(page.get_pixel(191, 67), &Rgb([200, 40, 90]));
    assert_eq!(page.get_pixel(0, 0), source.get_pixel(0, 0));
    assert!(
        page.enumerate_pixels()
            .any(|(x, y, p)| (38..100).contains(&x) && (45..95).contains(&y) && p[0] < 10)
    );
    for policy in ["annotate", "bilingual"] {
        let mut doc = read_doc();
        doc["meta"]["sfx_policy"] = json!(policy);
        fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
        run(&["mask", "--doc", DOC, "--free-lettering", "solid"]);
        run(&["clean", "--doc", DOC]);
        run(&["typeset", "--doc", DOC, "--external-dir", "external"]);
        assert_eq!(rendered().get_pixel(191, 67), source.get_pixel(191, 67));
        assert_eq!(read_doc()["pages"][0]["sfx_notes"][0]["fa"], "بوم!");
    }
}

#[test]
fn small_title_badge_keeps_its_colored_background_and_renders_two_digits() {
    use image::{Rgb, RgbImage};
    let fixture = Fixture::staged();
    let input = fixture.cwd.join("source");
    fs::create_dir(&input).unwrap();
    let mut source = RgbImage::from_pixel(120, 100, Rgb([164, 131, 163]));
    for y in 32u32..64 {
        for x in 40u32..72 {
            let d = x.abs_diff(55).pow(2) + y.abs_diff(47).pow(2);
            if (193..=225).contains(&d) {
                source.put_pixel(x, y, Rgb([250; 3]));
            }
        }
    }
    source.save(input.join("page.png")).unwrap();
    let run = |args: &[&str]| {
        let output = fixture.run(args, b"");
        success(&output);
        json_stdout(&output)
    };
    const DOC: &str = "work/comic.json";
    run(&["import", "source", "--out", "work"]);
    let path = fixture.cwd.join(DOC);
    let mut doc: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    doc["pages"][0]["regions"] = json!([{ "id":"p0001_r001", "bbox":[39,31,34,34], "kind":"title", "orientation":"horizontal", "source_text":"15", "target_text":"۱۵", "style":"bold" }]);
    fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    run(&["clean", "--doc", DOC, "--bubbles-only"]);
    assert_eq!(run(&["typeset", "--doc", DOC])["typeset"], 1);
    let output: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    let rendered = image::open(
        fixture
            .cwd
            .join("work")
            .join(output["pages"][0]["final"].as_str().unwrap()),
    )
    .unwrap()
    .into_rgb8();
    assert!(
        rendered
            .pixels()
            .zip(source.pixels())
            .any(|(a, b)| a[0].saturating_add(10) < b[0])
    );
    assert!(
        rendered
            .pixels()
            .zip(source.pixels())
            .all(|(a, b)| b[0] != 250 || a == b)
    );
    run(&["qa", "check", "--strict", "--doc", DOC]);
}

#[test]
fn multipage_mask_repeats_exact_geometry_pixels_and_document_order() {
    use image::{GrayImage, Rgb, RgbImage};
    use revayat_vision::{Rect, masks};

    let fixture = Fixture::staged();
    let input = fixture.cwd.join("source");
    fs::create_dir(&input).unwrap();
    let (width, height) = (184, 140);
    let sources: Vec<_> = [62u32, 87, 115]
        .into_iter()
        .enumerate()
        .map(|(i, cx)| {
            let page = RgbImage::from_fn(width, height, |x, y| {
                let balloon = x.abs_diff(cx).pow(2) + y.abs_diff(70).pow(2) < 47 * 47;
                let ink = x.abs_diff(cx) < 6 && y.abs_diff(70) < 5;
                Rgb([if balloon && !ink { 245 } else { 30 }; 3])
            });
            page.save(input.join(format!("{i}.png"))).unwrap();
            page
        })
        .collect();
    let run = |args: &[&str]| {
        let output = fixture.run(args, b"");
        success(&output);
        json_stdout(&output)
    };
    const DOC: &str = "work/comic.json";
    let imported = run(&["import", "source", "--out", "work"]);
    let path = fixture.cwd.join(DOC);
    let read_doc = || serde_json::from_slice::<Value>(&fs::read(&path).unwrap()).unwrap();
    let mut doc = read_doc();
    let mut expected = Vec::new();
    for (index, (image, cx)) in sources.iter().zip([62, 87, 115]).enumerate() {
        let page = &mut doc["pages"][index];
        let id = page["id"].as_str().unwrap();
        let bbox = Rect([cx - 14, 58, 28, 24]);
        page["regions"] = json!([{ "id":format!("{id}r001"), "bbox":bbox, "kind":"speech", "source_text":"Yes" }]);
        let balloon = masks::resolve_balloon(image, bbox, None, None, false)
            .unwrap()
            .unwrap();
        let geometry = masks::balloon_geometry(image, balloon).unwrap();
        let local = masks::region_mask(
            image,
            bbox,
            Some(balloon),
            false,
            masks::MaskOptions::default(),
        )
        .unwrap();
        let mut union = GrayImage::new(width, height);
        local.apply_to(&mut union).unwrap();
        expected.push((geometry, local, union));
    }
    fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    let mut previous = None;
    for _ in 0..2 {
        assert_eq!(run(&["mask", "--doc", DOC])["masks"], 3);
        let bytes = fs::read(&path).unwrap();
        let masked: Value = serde_json::from_slice(&bytes).unwrap();
        for (index, (geometry, local, union)) in expected.iter().enumerate() {
            let page = &masked["pages"][index];
            assert_eq!(page["id"], imported["pages"][index]["id"]);
            let region = &page["regions"][0];
            assert_eq!(&region["balloon"], geometry);
            assert_eq!(region["mask_bounds"], json!(local.bounds));
            let read_mask = |name: &Value| {
                image::open(fixture.cwd.join("work").join(name.as_str().unwrap()))
                    .unwrap()
                    .into_luma8()
            };
            assert_eq!(read_mask(&region["mask"]), local.pixels);
            assert_eq!(&read_mask(&page["mask"]), union);
        }
        if let Some(previous) = &previous {
            assert_eq!(&bytes, previous);
        }
        previous = Some(bytes);
    }
}

#[test]
fn open_speech_and_caption_fit_without_repainting_dark_artwork() {
    use image::{Rgb, RgbImage};

    let fixture = Fixture::staged();
    let input = fixture.cwd.join("source");
    fs::create_dir(&input).unwrap();
    let source = RgbImage::from_fn(240, 319, |x, y| {
        let frame = (53..=55).contains(&x);
        let hair = x >= 168 && (x + y / 3) % 13 <= 3;
        let glyph =
            (113..=124).contains(&x) && ((64..=73).contains(&y) || (254..=263).contains(&y));
        Rgb([if frame || hair || glyph { 20 } else { 245 }; 3])
    });
    source.save(input.join("page.png")).unwrap();
    let run = |args: &[&str]| {
        let output = fixture.run(args, b"");
        success(&output);
        json_stdout(&output)
    };
    const DOC: &str = "work/comic.json";
    run(&["import", "source", "--out", "work"]);
    let path = fixture.cwd.join(DOC);
    let read_doc = || serde_json::from_slice::<Value>(&fs::read(&path).unwrap()).unwrap();
    let mut doc = read_doc();
    doc["pages"][0]["regions"] = json!([
        {"id":"open", "bbox":[56,32,121,77], "kind":"speech", "source_text":"Yes", "target_text":"خیلی دوره!"},
        {"id":"caption", "bbox":[56,224,121,77], "kind":"caption", "source_text":"Later", "target_text":"بعدتر"}
    ]);
    fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    run(&["mask", "--doc", DOC]);
    assert!(read_doc()["pages"][0]["regions"][0]["balloon"].is_null());
    run(&["clean", "--doc", DOC]);
    assert_eq!(run(&["typeset", "--doc", DOC])["typeset"], 2);
    let doc = read_doc();
    let page = &doc["pages"][0];
    let rendered = image::open(
        fixture
            .cwd
            .join("work")
            .join(page["final"].as_str().unwrap()),
    )
    .unwrap()
    .into_rgb8();
    for (x, y, p) in source.enumerate_pixels() {
        if x <= 55 || x >= 168 {
            assert_eq!(rendered.get_pixel(x, y), p, "{x}, {y}");
        }
    }
}

#[test]
fn closed_and_twin_lobe_balloons_clean_and_letter_without_touching_neighbors() {
    use image::{Rgb, RgbImage};

    let fixture = Fixture::staged();
    let input = fixture.cwd.join("source");
    fs::create_dir(&input).unwrap();
    let source = RgbImage::from_fn(220, 210, |x, y| {
        let closed = (40..144).contains(&x) && (21..86).contains(&y);
        let lobes = [60, 151]
            .into_iter()
            .any(|cx| x.abs_diff(cx).pow(2) + y.abs_diff(150).pow(2) < 40 * 40);
        let neck = (60..151).contains(&x) && y.abs_diff(150) <= 4;
        let kept = (123..130).contains(&x) && (41..46).contains(&y);
        let ink = (74..79).contains(&x) && (46..51).contains(&y)
            || (33..38).contains(&x) && (147..151).contains(&y)
            || (123..128).contains(&x) && (147..151).contains(&y);
        let stray = x == 43 && (31..78).contains(&y);
        Rgb([if kept || ink || !(closed || lobes || neck) {
            24
        } else if stray {
            207
        } else {
            245
        }; 3])
    });
    source.save(input.join("page.png")).unwrap();
    let run = |args: &[&str]| {
        let output = fixture.run(args, b"");
        success(&output);
        json_stdout(&output)
    };
    const DOC: &str = "work/comic.json";
    run(&["import", "source", "--out", "work"]);
    let path = fixture.cwd.join(DOC);
    let read_doc = || serde_json::from_slice::<Value>(&fs::read(&path).unwrap()).unwrap();
    let mut doc = read_doc();
    doc["pages"][0]["panels"] = json!([{"bbox":[0,0,220,210]}]);
    doc["pages"][0]["regions"] = json!([
        {"id":"closed", "bbox":[68,41,20,18], "kind":"speech", "source_text":"Yes", "target_text":"باشه."},
        {"id":"dropped_overlap", "bbox":[48,30,52,45], "kind":"speech", "dropped":true},
        {"id":"kept", "bbox":[119,38,15,12], "kind":"speech", "source_text":"Keep", "keep":true},
        {"id":"left", "bbox":[29,141,16,17], "kind":"speech", "source_text":"Are you there?", "target_text":"کجا رفتی؟"},
        {"id":"right", "bbox":[119,141,16,17], "kind":"speech", "source_text":"Are you there?", "target_text":"کجا رفتی؟"}
    ]);
    fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    run(&["mask", "--doc", DOC]);
    run(&["clean", "--doc", DOC]);
    let load =
        |name: &Value| image::open(fixture.cwd.join("work").join(name.as_str().unwrap())).unwrap();
    let doc = read_doc();
    let page = &doc["pages"][0];
    let cleaned = load(&page["clean"]).into_rgb8();
    let mask = load(&page["clean_mask"]).into_luma8();
    for (x, y, p) in source.enumerate_pixels() {
        let kept = (119..134).contains(&x) && (38..50).contains(&y);
        if kept
            || (40..42).contains(&x) && (21..86).contains(&y)
            || p[0] == 24
                && !((68..88).contains(&x) && (41..59).contains(&y)
                    || y > 140 && y < 158 && ((29..45).contains(&x) || (119..135).contains(&x)))
        {
            assert_eq!(cleaned.get_pixel(x, y), p, "{x}, {y}");
            assert_eq!(mask.get_pixel(x, y)[0], 0, "{x}, {y}");
        } else if (42..142).contains(&x) && (23..84).contains(&y) {
            assert_eq!(cleaned.get_pixel(x, y), &Rgb([245; 3]), "{x}, {y}");
            assert_eq!(mask.get_pixel(x, y)[0], 255, "{x}, {y}");
        }
    }
    assert_eq!(run(&["typeset", "--doc", DOC])["typeset"], 3);
    let doc = read_doc();
    let page = &doc["pages"][0];
    let rendered = load(&page["final"]).into_rgb8();
    let sizes = [3, 4].map(|i| page["regions"][i]["typeset"]["font_size"].as_f64().unwrap());
    assert!(sizes.iter().all(|&size| size >= 17.0), "{sizes:?}");
    assert!((sizes[0] - sizes[1]).abs() <= 2.0, "{sizes:?}");
    for (x, y, p) in cleaned
        .enumerate_pixels()
        .filter(|(x, y, p)| *p != rendered.get_pixel(*x, *y))
    {
        if y < 100 {
            assert!(
                !((119..134).contains(&x) && (38..50).contains(&y)),
                "{x}, {y}"
            );
        } else {
            let cx = if x < 105 { 60 } else { 151 };
            assert!(
                x.abs_diff(cx).pow(2) + y.abs_diff(150).pow(2) < 38 * 38,
                "{x}, {y}: {p:?}"
            );
        }
    }
    assert_eq!(
        run(&["qa", "check", "--doc", DOC])["artwork_pixels_changed"],
        0
    );
}

#[test]
fn panel_clipped_balloon_letters_beyond_the_corner_without_touching_the_border() {
    use image::{Rgb, RgbImage};

    let fixture = Fixture::staged();
    let input = fixture.cwd.join("source");
    fs::create_dir(&input).unwrap();
    let source = RgbImage::from_fn(130, 122, |x, y| {
        let wall = x >= 86 - y.abs_diff(60) / 5 && x < 118 && (18..106).contains(&y);
        let ink = (28..32).contains(&x) && (26..29).contains(&y);
        Rgb([if wall || ink { 24 } else { 245 }; 3])
    });
    source.save(input.join("page.png")).unwrap();
    let run = |args: &[&str]| {
        let output = fixture.run(args, b"");
        success(&output);
        json_stdout(&output)
    };
    const DOC: &str = "work/comic.json";
    run(&["import", "source", "--out", "work"]);
    let path = fixture.cwd.join(DOC);
    let read_doc = || serde_json::from_slice::<Value>(&fs::read(&path).unwrap()).unwrap();
    let mut doc = read_doc();
    doc["pages"][0]["panels"] = json!([{"bbox":[18,18,100,88]}]);
    doc["pages"][0]["regions"] = json!([
        {"id":"edge", "bbox":[26,23,9,9], "kind":"speech", "source_text":"Yes", "target_text":"باشه."}
    ]);
    fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    run(&["mask", "--doc", DOC]);
    let doc = read_doc();
    let balloon = &doc["pages"][0]["regions"][0]["balloon"];
    assert_eq!(balloon["bounds"][0], 18);
    assert_eq!(balloon["bounds"][3], 88);
    run(&["clean", "--doc", DOC]);
    assert_eq!(run(&["typeset", "--doc", DOC])["typeset"], 1);
    let doc = read_doc();
    let page = &doc["pages"][0];
    let layout = &page["regions"][0]["typeset"];
    assert!(layout["font_size"].as_f64().unwrap() >= 16.0);
    assert!(layout["ink_box"][1].as_u64().unwrap() > 32);
    let rendered = image::open(
        fixture
            .cwd
            .join("work")
            .join(page["final"].as_str().unwrap()),
    )
    .unwrap()
    .into_rgb8();
    for (x, y, p) in source.enumerate_pixels() {
        if x < 18 || x >= 86 - y.abs_diff(60) / 5 || !(18..106).contains(&y) {
            assert_eq!(rendered.get_pixel(x, y), p, "{x}, {y}");
        }
    }
}

#[test]
fn install_scope_and_path_aliases_reach_the_installer() {
    let fixture = Fixture::staged();
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .unwrap();
    fs::create_dir(fixture.cwd.join("project path")).unwrap();
    let output = fixture.run(
        &[
            "install",
            "--repo",
            source.to_str().unwrap(),
            "--scope",
            "project",
            "--path",
            "project path",
            "--agent",
            "claude",
        ],
        b"",
    );
    success(&output);
    assert!(
        fixture
            .cwd
            .join("project path/.claude/skills/revayat-comic/SKILL.md")
            .is_file()
    );
}
