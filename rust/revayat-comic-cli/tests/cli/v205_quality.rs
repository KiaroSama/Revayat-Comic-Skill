use super::*;
use image::{Rgb, RgbImage};

const DOC: &str = "work/comic.json";

fn read_doc(fixture: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(fixture.cwd.join(DOC)).unwrap()).unwrap()
}

fn write_doc(fixture: &Fixture, doc: &Value) {
    fs::write(fixture.cwd.join(DOC), serde_json::to_vec(doc).unwrap()).unwrap();
}

fn success_json(out: &Output) -> Value {
    success(out);
    serde_json::from_slice(&out.stdout).unwrap()
}

fn import_one(fixture: &Fixture, page: &RgbImage) {
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    page.save(fixture.cwd.join("source/0.png")).unwrap();
    success(&fixture.run(&["import", "source", "--out", "work"], b""));
}

#[test]
fn solid_external_on_art_patch_transfers_strokes_outside_source_glyphs_without_speckles() {
    let fixture = Fixture::new("v205_solid_external");
    // Textured gray art background with small dark English glyphs at center.
    let page = RgbImage::from_fn(220, 180, |x, y| {
        let glyph = (95..105).contains(&x) && (80..95).contains(&y);
        if glyph {
            Rgb([15, 15, 15])
        } else {
            Rgb([180, 175, 190])
        }
    });
    import_one(&fixture, &page);

    let mut doc = read_doc(&fixture);
    doc["meta"]["sfx_policy"] = json!("translate");
    doc["pages"][0]["regions"] = json!([
        {
            "id": "p0001_r001",
            "kind": "sfx",
            "bbox": [70, 70, 80, 40],
            "source_text": "RUMBLE",
            "target_text": "غرش",
            "locked": true
        }
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    success(&fixture.run(&["clean", "--doc", DOC, "--bubbles-only"], b""));

    // External edited page has subtle JPEG-like shading shift across the solid patch AND paints
    // new Persian strokes OUTSIDE the old 95..105 glyph box (at x=74..88).
    let mut ext = page.clone();
    for y in 64..116 {
        for x in 64..156 {
            ext.put_pixel(x, y, Rgb([192, 187, 202]));
        }
    }
    for y in 80..98 {
        for x in 74..88 {
            ext.put_pixel(x, y, Rgb([10, 10, 10]));
        }
    }
    fs::create_dir(fixture.cwd.join("ext")).unwrap();
    ext.save(fixture.cwd.join("ext/p0001.png")).unwrap();

    success(&fixture.run(&["typeset", "--doc", DOC, "--external-dir", "ext"], b""));
    let doc = read_doc(&fixture);
    assert_eq!(
        doc["pages"][0]["regions"][0]["typeset"]["status"],
        "external"
    );
    let rendered = image::open(
        fixture
            .cwd
            .join("work")
            .join(doc["pages"][0]["final"].as_str().unwrap()),
    )
    .unwrap()
    .into_rgb8();
    // Both the erased English spot (100, 88) and the newly placed Persian stroke (80, 88) must come from ext.
    assert_eq!(rendered.get_pixel(100, 88), &Rgb([192, 187, 202]));
    assert_eq!(rendered.get_pixel(80, 88), &Rgb([10, 10, 10]));
    let qa = success_json(&fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b""));
    assert_eq!(
        qa["ok"], true,
        "solid external patch must pass strict QA: {qa}"
    );
}

#[test]
fn flat_colored_caption_and_untouched_external_page_region_render_deterministically() {
    let fixture = Fixture::new("v206_flat_color_and_fallback");
    // Top half: flat mauve TOC-style backing (contrast with white >= 3.3:1).
    // Bottom half: white paper with an untouched caption on a page that also has --external-dir.
    let page = RgbImage::from_fn(260, 220, |x, y| {
        if y < 110 {
            let old_text = (90..150).contains(&x) && (45..60).contains(&y);
            if old_text {
                Rgb([255, 255, 255])
            } else {
                Rgb([156, 128, 155])
            }
        } else {
            let old_sfx = (90..140).contains(&x) && (155..170).contains(&y);
            Rgb([if old_sfx { 20 } else { 245 }; 3])
        }
    });
    import_one(&fixture, &page);
    let mut doc = read_doc(&fixture);
    doc["pages"][0]["regions"] = json!([
        {
            "id": "p0001_r001",
            "kind": "caption",
            "polarity": "dark",
            "bbox": [30, 20, 200, 75],
            "source_text": "CONTENTS",
            "target_text": "فهرست",
            "locked": true
        },
        {
            "id": "p0001_r002",
            "kind": "caption",
            "polarity": "light",
            "bbox": [40, 130, 180, 70],
            "source_text": "PHEW...",
            "target_text": "آخیش…",
            "locked": true
        }
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    // Sparse external dir without p0001.png must not fail clean; unchanged p0001.png in typeset
    // must fall through to deterministic Vazir (including flat-colored mauve captions).
    fs::create_dir(fixture.cwd.join("ext_sparse")).unwrap();
    success(&fixture.run(
        &["clean", "--doc", DOC, "--external-dir", "ext_sparse"],
        b"",
    ));
    fs::create_dir(fixture.cwd.join("ext")).unwrap();
    page.save(fixture.cwd.join("ext/p0001.png")).unwrap();
    success(&fixture.run(&["typeset", "--doc", DOC, "--external-dir", "ext"], b""));
    let doc = read_doc(&fixture);
    assert_eq!(doc["pages"][0]["regions"][0]["typeset"]["status"], "fit");
    assert_eq!(doc["pages"][0]["regions"][1]["typeset"]["status"], "fit");
    let qa = success_json(&fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b""));
    assert_eq!(
        qa["ok"], true,
        "flat colored caption + fallback must pass strict QA: {qa}"
    );
}

#[test]
fn unresolved_speech_balloon_stays_deterministic_medium_even_with_external_dir() {
    let fixture = Fixture::new("v205_speech_no_hijack");
    // Open white paper page with no closed contour around speech box.
    let page = RgbImage::from_pixel(240, 200, Rgb([245, 245, 245]));
    import_one(&fixture, &page);

    let mut doc = read_doc(&fixture);
    doc["pages"][0]["regions"] = json!([
        {
            "id": "p0001_r001",
            "kind": "speech",
            "bbox": [40, 50, 160, 90],
            "source_text": "Hello",
            "target_text": "سلام!",
            "locked": true
        }
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    success(&fixture.run(&["clean", "--doc", DOC, "--bubbles-only"], b""));

    // Provide an external PNG; speech MUST NOT silently become status="external".
    fs::create_dir(fixture.cwd.join("ext")).unwrap();
    let mut ext = page.clone();
    ext.put_pixel(60, 60, Rgb([10, 200, 10]));
    ext.save(fixture.cwd.join("ext/p0001.png")).unwrap();

    success(&fixture.run(&["typeset", "--doc", DOC, "--external-dir", "ext"], b""));
    let doc = read_doc(&fixture);
    let ts = &doc["pages"][0]["regions"][0]["typeset"];
    assert_eq!(
        ts["status"], "fit",
        "speech must stay deterministic fit, not external"
    );
    assert_eq!(ts["weight"], "medium");

    let qa = success_json(&fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b""));
    assert_eq!(qa["ok"], true, "strict QA failed: {qa}");
}

#[test]
fn english_source_protects_japanese_kana_sfx_from_modification_and_strict_qa_flags_tampering() {
    let fixture = Fixture::new("v205_japanese_guard");
    let page = RgbImage::from_fn(220, 180, |x, y| {
        let kana = (60..90).contains(&x) && (50..80).contains(&y);
        Rgb([if kana { 20 } else { 245 }; 3])
    });
    import_one(&fixture, &page);

    let mut doc = read_doc(&fixture);
    doc["meta"]["source_language"] = json!("en");
    doc["meta"]["sfx_policy"] = json!("translate");
    doc["pages"][0]["regions"] = json!([
        {
            "id": "p0001_r001",
            "kind": "sfx",
            "bbox": [55, 45, 45, 45],
            "source_text": "ゴゴゴ…",
            "target_text": "غرش…",
            "locked": true
        }
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    success(&fixture.run(&["clean", "--doc", DOC], b""));
    success(&fixture.run(&["typeset", "--doc", DOC], b""));

    let doc = read_doc(&fixture);
    let output_rel = doc["pages"][0]["final"]
        .as_str()
        .or_else(|| doc["pages"][0]["clean"].as_str())
        .unwrap();
    let output_img = image::open(fixture.cwd.join("work").join(output_rel))
        .unwrap()
        .into_rgb8();
    assert_eq!(
        output_img.get_pixel(70, 65),
        &Rgb([20, 20, 20]),
        "protected Japanese kana pixels must remain untouched"
    );

    // Strict QA must flag the attempted translation of protected Japanese kana on an English source.
    let qa_out = fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b"");
    assert!(
        !qa_out.status.success(),
        "strict QA must reject translated Japanese SFX on en source"
    );
    let body: Value = serde_json::from_slice(&qa_out.stdout).unwrap();
    assert!(
        body["findings"].as_array().unwrap().iter().any(|f| {
            f.get("code")
                .or_else(|| f["finding"].get("code"))
                .and_then(Value::as_str)
                == Some("protected-japanese-modified")
        }),
        "expected protected-japanese-modified in {body}"
    );
}

#[test]
fn erased_balloon_with_noop_external_repair_fails_strict_qa() {
    let fixture = Fixture::new("v205_erased_noop_qa");
    // Open white balloon touching the panel border with a connected comb of dark bars:
    // >55% of bbox is connected white paper (so resolve_balloon succeeds), yet every pixel
    // in the padded cleanup window is <=1px from ink (so dilation produces a 100% solid mask
    // that requires --external-dir) and the 36x36 connected glyph exceeds sweep_speckles.
    let page = RgbImage::from_fn(160, 140, |x, y| {
        let paper = (20..100).contains(&x) && (20..120).contains(&y);
        let in_box = (33..71).contains(&x) && (41..79).contains(&y);
        let glyph = in_box && (x % 3 == 0 || (58..62).contains(&y));
        Rgb([if paper && !glyph { 245 } else { 20 }; 3])
    });
    import_one(&fixture, &page);
    let mut doc = read_doc(&fixture);
    doc["pages"][0]["panels"] = json!([{"bbox": [20, 20, 120, 100]}]);
    doc["pages"][0]["regions"] = json!([
        {
            "id": "p0001_r001",
            "kind": "speech",
            "bbox": [40, 48, 24, 24],
            "source_text": "NOISE",
            "polarity": "light",
            "erase": true,
            "locked": true
        }
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));

    // Provide an unchanged external PNG (no-op repair that leaves the dark ink inside the balloon).
    fs::create_dir(fixture.cwd.join("ext")).unwrap();
    page.save(fixture.cwd.join("ext/p0001.png")).unwrap();
    success(&fixture.run(
        &[
            "clean",
            "--doc",
            DOC,
            "--bubbles-only",
            "--external-dir",
            "ext",
        ],
        b"",
    ));
    let doc = read_doc(&fixture);
    assert_eq!(doc["pages"][0]["regions"][0]["fill"], "external");

    let qa_out = fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b"");
    assert!(
        !qa_out.status.success(),
        "strict QA must catch surviving ink inside an erased balloon"
    );
    let body: Value = serde_json::from_slice(&qa_out.stdout).unwrap();
    assert!(
        body["findings"].as_array().unwrap().iter().any(|f| {
            f.get("code")
                .or_else(|| f["finding"].get("code"))
                .and_then(Value::as_str)
                == Some("balloon-ink-survives")
        }),
        "expected balloon-ink-survives in {body}"
    );
}

#[test]
fn qa_review_pack_generates_zoomed_crops_and_enforces_ledger_verification() {
    let fixture = Fixture::new("v205_review_pack");
    let page = RgbImage::from_fn(220, 180, |x, y| {
        let paper = (20..200).contains(&x) && (20..160).contains(&y);
        Rgb([if paper { 245 } else { 20 }; 3])
    });
    import_one(&fixture, &page);
    let mut doc = read_doc(&fixture);
    doc["pages"][0]["regions"] = json!([
        {
            "id": "p0001_r001",
            "kind": "speech",
            "bbox": [40, 50, 140, 80],
            "source_text": "3.",
            "target_text": "3.",
            "locked": true
        }
    ]);
    write_doc(&fixture, &doc);
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    success(&fixture.run(&["clean", "--doc", DOC, "--bubbles-only"], b""));
    success(&fixture.run(&["typeset", "--doc", DOC], b""));

    let pack = success_json(&fixture.run(&["qa", "review-pack", "--doc", DOC], b""));
    assert_eq!(pack["ok"], true);
    assert!(pack["crops"].as_u64().unwrap() >= 1);
    let crop_file = fixture.cwd.join("work/review/crops/p0001_r001.png");
    assert!(crop_file.is_file(), "missing 2x side-by-side crop");
    let crop_img = image::open(&crop_file).unwrap();
    assert!(crop_img.width() <= 1500);

    // Without ledger.tsv, --verify-ledger fails closed.
    let fail = fixture.run(&["qa", "review-pack", "--doc", DOC, "--verify-ledger"], b"");
    assert!(!fail.status.success());

    // Write PASS row for p0001_r001 -> --verify-ledger passes.
    fs::write(
        fixture.cwd.join("work/review/ledger.tsv"),
        "page_id\tregion_id\tstage\tverdict\tdefect_codes\tnotes\np0001\tp0001_r001\t5a\tPASS\t\tverified\n",
    )
    .unwrap();
    let pass =
        success_json(&fixture.run(&["qa", "review-pack", "--doc", DOC, "--verify-ledger"], b""));
    assert_eq!(pass["ok"], true);
}
