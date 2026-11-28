use super::*;
use image::{GrayImage, Rgb, RgbImage};

const DOC: &str = "work/comic.json";
const BADGE: [u32; 4] = [92, 50, 25, 30];

fn setup(source: &RgbImage, regions: Value) -> Fixture {
    let fixture = Fixture::staged();
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    source.save(fixture.cwd.join("source/0.png")).unwrap();
    success(&fixture.run(
        &[
            "import",
            "source",
            "--out",
            "work",
            "--source-language",
            "en",
        ],
        b"",
    ));
    let mut doc = document(&fixture);
    doc["meta"]["sfx_policy"] = json!("translate");
    doc["pages"][0]["regions"] = regions;
    write_doc(&fixture, &doc);
    fixture
}

fn document(fixture: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(fixture.cwd.join(DOC)).unwrap()).unwrap()
}

fn write_doc(fixture: &Fixture, doc: &Value) {
    fs::write(fixture.cwd.join(DOC), serde_json::to_vec(doc).unwrap()).unwrap();
}

fn run(fixture: &Fixture, args: &[&str]) -> Value {
    let out = fixture.run(args, b"");
    success(&out);
    json_stdout(&out)
}

fn stage(fixture: &Fixture, command: &str, extra: &[&str]) -> Value {
    let mut args = vec![command, "--doc", DOC];
    args.extend_from_slice(extra);
    run(fixture, &args)
}

fn qa(fixture: &Fixture) -> Value {
    run(fixture, &["qa", "check", "--strict", "--doc", DOC])
}

fn render(fixture: &Fixture) {
    stage(fixture, "mask", &[]);
    stage(fixture, "clean", &[]);
    stage(fixture, "typeset", &[]);
}

fn rgb(fixture: &Fixture, path: &Value) -> RgbImage {
    image::open(fixture.cwd.join("work").join(path.as_str().unwrap()))
        .unwrap()
        .into_rgb8()
}

fn mask(fixture: &Fixture, path: &Value) -> GrayImage {
    image::open(fixture.cwd.join("work").join(path.as_str().unwrap()))
        .unwrap()
        .into_luma8()
}

fn external(fixture: &Fixture, image: &RgbImage) {
    fs::create_dir(fixture.cwd.join("ext")).unwrap();
    image.save(fixture.cwd.join("ext/p0001.png")).unwrap();
}

fn badge_fixture() -> (Fixture, RgbImage) {
    let source = RgbImage::from_fn(180, 140, |x, y| {
        let ink = (45..62).contains(&x) && (55..70).contains(&y);
        let badge = (99..110).contains(&x) && (57..74).contains(&y);
        Rgb([if ink || badge { 20 } else { 245 }; 3])
    });
    let fixture = setup(
        &source,
        json!([
            {"id":"lettering", "kind":"sfx", "bbox":[30,30,105,75], "source_text":"RUMBLE", "target_text":"غرش", "locked":true},
            {"id":"badge", "kind":"title", "bbox":BADGE, "source_text":"15", "keep":true}
        ]),
    );
    (fixture, source)
}

fn assert_badge_preserved(source: &RgbImage, output: &RgbImage, allowed: &GrayImage) {
    let [x, y, w, h] = BADGE;
    for y in y..y + h {
        for x in x..x + w {
            assert_eq!(
                output.get_pixel(x, y),
                source.get_pixel(x, y),
                "badge at {x},{y}"
            );
            assert_eq!(allowed.get_pixel(x, y)[0], 0, "badge authorized at {x},{y}");
        }
    }
}

#[test]
fn punctured_solid_mask_still_requires_external_cleaning() {
    let (fixture, source) = badge_fixture();
    stage(&fixture, "mask", &["--free-lettering", "solid"]);
    let doc = document(&fixture);
    let page = &doc["pages"][0];
    assert_eq!(page["regions"][0]["solid_mask"], true);
    let allowed = mask(&fixture, &page["mask"]);
    assert_eq!(allowed.get_pixel(50, 60)[0], 255);
    assert_eq!(allowed.get_pixel(104, 63)[0], 0);
    let refused = fixture.run(&["clean", "--doc", DOC], b"");
    assert_eq!(refused.status.code(), Some(4), "{refused:?}");
    assert!(
        String::from_utf8_lossy(&refused.stderr)
            .contains("solid erase mask needs an approved external repair")
    );
    assert_eq!(document(&fixture), doc);

    external(&fixture, &RgbImage::from_pixel(180, 140, Rgb([245; 3])));
    stage(&fixture, "clean", &["--external-dir", "ext"]);
    let doc = document(&fixture);
    let page = &doc["pages"][0];
    let cleaned = rgb(&fixture, &page["clean"]);
    assert_eq!(page["regions"][0]["fill"], "external");
    assert_eq!(cleaned.get_pixel(50, 60), &Rgb([245; 3]));
    assert_badge_preserved(&source, &cleaned, &mask(&fixture, &page["clean_mask"]));

    stage(&fixture, "mask", &[]);
    assert!(
        document(&fixture)["pages"][0]["regions"][0]
            .get("solid_mask")
            .is_none()
    );
}

#[test]
fn external_typesetting_cannot_overwrite_an_overlapping_keep_region() {
    let (fixture, source) = badge_fixture();
    stage(&fixture, "mask", &["--free-lettering", "solid"]);
    stage(&fixture, "clean", &["--bubbles-only"]);
    let edited = RgbImage::from_fn(180, 140, |x, y| {
        if (65..85).contains(&x) && (55..69).contains(&y) {
            Rgb([12; 3])
        } else {
            Rgb([240, 225, 235])
        }
    });
    external(&fixture, &edited);
    stage(&fixture, "typeset", &["--external-dir", "ext"]);
    let doc = document(&fixture);
    let page = &doc["pages"][0];
    let delivered = rgb(&fixture, &page["final"]);
    assert_eq!(page["regions"][0]["typeset"]["status"], "external");
    assert_eq!(delivered.get_pixel(50, 60), &Rgb([240, 225, 235]));
    assert_eq!(delivered.get_pixel(72, 61), &Rgb([12; 3]));
    assert_badge_preserved(
        &source,
        &delivered,
        &mask(&fixture, &page["authorized_mask"]),
    );
    assert_eq!(qa(&fixture)["artwork_pixels_changed"], 0);
}

#[test]
fn dropped_kana_does_not_protect_an_active_neighbors_pixels() {
    let source = RgbImage::from_fn(230, 150, |x, y| {
        Rgb([if (90..134).contains(&x) && (64..80).contains(&y) {
            20
        } else {
            245
        }; 3])
    });
    let fixture = setup(
        &source,
        json!([
            {"id":"caption", "kind":"caption", "bbox":[35,30,160,90], "source_text":"Hello", "target_text":"سلام", "locked":true},
            {"id":"discarded", "kind":"sfx", "bbox":[86,60,52,24], "source_text":"ゴゴゴ", "state":"dropped"}
        ]),
    );
    render(&fixture);
    let doc = document(&fixture);
    let output = rgb(&fixture, &doc["pages"][0]["final"]);
    assert!((64..80).any(|y| (90..134).any(|x| source.get_pixel(x, y) != output.get_pixel(x, y))));
    assert!(!has_finding(
        &qa(&fixture),
        "protected-japanese-modified",
        "discarded"
    ));
}

fn review(fixture: &Fixture) -> Value {
    run(fixture, &["qa", "review-pack", "--doc", DOC]);
    serde_json::from_slice(&fs::read(fixture.cwd.join("work/review/flags.json")).unwrap()).unwrap()
}

fn review_item<'a>(flags: &'a Value, id: &str) -> &'a Value {
    flags["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["region_id"] == id)
        .unwrap()
}

#[test]
fn review_id_binds_document_identity_and_the_native_full_page_comparison() {
    let source = RgbImage::from_fn(900, 120, |x, y| Rgb([(x % 255) as u8, y as u8, 244]));
    let fixture = setup(&source, json!([]));
    let first = review(&fixture);
    let row = review_item(&first, "*");
    let crop = row["crop_path"].as_str().unwrap();
    assert!(crop.starts_with("crops/p0001-page-"));
    let comparison = rgb(&fixture, &json!(format!("review/{crop}")));
    assert_eq!(comparison.dimensions(), (1804, 120));
    for (x, y, pixel) in source.enumerate_pixels() {
        assert_eq!(pixel, comparison.get_pixel(x, y));
        assert_eq!(pixel, comparison.get_pixel(x + 904, y));
    }

    let ledger = fs::read_to_string(fixture.cwd.join("work/review/ledger.template.tsv")).unwrap();
    assert_eq!(
        ledger.lines().next().unwrap(),
        "page_id\tregion_id\tstage\tverdict\tdefect_codes\tnotes\treview_id"
    );
    fs::write(
        fixture.cwd.join("work/review/ledger.tsv"),
        ledger.replace("\tPENDING\t", "\tPASS\t"),
    )
    .unwrap();
    let verify = || fixture.run(&["qa", "review-pack", "--doc", DOC, "--verify-ledger"], b"");
    success(&verify());
    let base = document(&fixture);
    for field in ["/meta/title", "/meta/chapter", "/source"] {
        let mut doc = base.clone();
        match field {
            "/meta/title" => doc["meta"]["title"] = json!("Another title"),
            "/meta/chapter" => doc["meta"]["chapter"] = json!("Another chapter"),
            _ => doc["source"]["edition"] = json!("Another source"),
        }
        write_doc(&fixture, &doc);
        let changed = review(&fixture);
        assert_ne!(changed["review_id"], first["review_id"], "{field}");
        assert_eq!(changed["items"], first["items"]);
        let out = verify();
        assert_eq!(out.status.code(), Some(1), "{out:?}");
        assert_eq!(json_stdout(&out)["ok"], false);
    }
}

#[test]
fn a_tiny_sfx_does_not_shrink_a_roomy_speech_balloon() {
    let source = RgbImage::from_fn(340, 320, |x, y| {
        let paper = (20..170).contains(&x) && (30..290).contains(&y);
        let ink = (79..111).contains(&x) && (143..168).contains(&y);
        Rgb([if paper && !ink {
            248
        } else if (215..320).contains(&x) {
            210
        } else {
            30
        }; 3])
    });
    let fixture = setup(
        &source,
        json!([
            {"id":"speech", "kind":"speech", "bbox":[69,134,54,48], "balloon":{"bounds":[20,30,150,260], "text_bounds":[69,134,54,48]}, "source_text":"Look!", "target_text":"نگاه کنین!", "locked":true},
            {"id":"sfx", "kind":"sfx", "bbox":[236,130,60,40], "source_text":"STEP", "target_text":"قدم", "locked":true},
            {"id":"other_sfx", "kind":"sfx", "bbox":[236,210,60,40], "source_text":"STEP", "target_text":"قدم", "locked":true}
        ]),
    );
    render(&fixture);
    let doc = document(&fixture);
    let regions = &doc["pages"][0]["regions"];
    assert_eq!(regions[1]["typeset"]["status"], "fit");
    assert_eq!(regions[0]["typeset"]["status"], "fit");
    assert_eq!(regions[0]["typeset"]["weight"], "medium");
    assert!(
        regions[0]["typeset"]["font_size"].as_f64().unwrap() > 24.0,
        "{}",
        regions[0]["typeset"]
    );

    let mut undersized = doc;
    undersized["pages"][0]["regions"][0]["typeset"]["font_size"] = json!(18.0);
    write_doc(&fixture, &undersized);
    assert!(
        review_item(&review(&fixture), "speech")["reasons"]
            .as_array()
            .unwrap()
            .contains(&json!("undersized_balloon"))
    );
}

fn halftone_fixture() -> Fixture {
    let source = RgbImage::from_fn(220, 160, |x, y| {
        let tone = if (82..138).contains(&x) && (69..91).contains(&y) {
            15
        } else if x % 4 == 0 && y % 5 < 2 {
            187
        } else {
            246
        };
        Rgb([tone; 3])
    });
    setup(
        &source,
        json!([
            {"id":"spark", "kind":"sfx", "bbox":[54,45,112,70], "source_text":"SPARK", "target_text":"جرقه", "locked":true}
        ]),
    )
}

#[test]
fn halftone_sfx_cleaning_restores_dots_and_adds_a_thin_outline() {
    let fixture = halftone_fixture();
    render(&fixture);
    let doc = document(&fixture);
    let page = &doc["pages"][0];
    let region = &page["regions"][0];
    let cleaned = rgb(&fixture, &page["clean"]);
    let old_ink = (86..134).flat_map(|x| (73..87).map(move |y| (x, y)));
    let shades = old_ink
        .map(|(x, y)| cleaned.get_pixel(x, y)[0])
        .collect::<std::collections::BTreeSet<_>>();
    assert!(
        shades.contains(&187) && shades.contains(&246),
        "restored shades: {shades:?}"
    );
    assert_eq!(region["fill"], "inpaint");
    assert_eq!(region["typeset"]["status"], "fit");
    let radius = region["typeset"]["outline_px"].as_u64().unwrap();
    assert!((1..=3).contains(&radius));
    assert!(
        review_item(&review(&fixture), "spark")["reasons"]
            .as_array()
            .unwrap()
            .contains(&json!("outlined_text"))
    );
}

#[test]
fn explicit_persian_caption_rotation_stays_authorized_and_gets_reviewed() {
    let source = RgbImage::from_fn(280, 180, |x, y| {
        Rgb([if (101..179).contains(&x) && (80..98).contains(&y) {
            25
        } else {
            245
        }; 3])
    });
    let fixture = setup(
        &source,
        json!([
            {"id":"caption", "kind":"caption", "bbox":[30,30,220,120], "source_text":"That night", "target_text":"آن شب\nتق", "angle":-0.5, "locked":true}
        ]),
    );
    render(&fixture);
    let doc = document(&fixture);
    let page = &doc["pages"][0];
    let typeset = &page["regions"][0]["typeset"];
    assert_eq!(typeset["status"], "fit");
    assert_eq!(typeset["weight"], "medium");
    assert_eq!(typeset["angle_deg"], -0.5);
    let final_page = rgb(&fixture, &page["final"]);
    let clean = rgb(&fixture, &page["clean"]);
    let allowed = mask(&fixture, &page["authorized_mask"]);
    let mut changed = 0;
    for (x, y, pixel) in final_page.enumerate_pixels() {
        if pixel != source.get_pixel(x, y) || pixel != clean.get_pixel(x, y) {
            assert_ne!(allowed.get_pixel(x, y)[0], 0, "unauthorized pixel {x},{y}");
        }
        changed += usize::from(pixel != clean.get_pixel(x, y));
    }
    assert!(changed > 0);
    assert_eq!(qa(&fixture)["errors"], 0);
    assert!(
        review_item(&review(&fixture), "caption")["reasons"]
            .as_array()
            .unwrap()
            .contains(&json!("rotated_text"))
    );

    let mut broken = final_page.clone();
    let second_top = typeset["lines"][1]["bbox"][1].as_u64().unwrap() as u32;
    for y in second_top - 2..broken.height() {
        for x in 0..broken.width() {
            broken.put_pixel(x, y, *clean.get_pixel(x, y));
        }
    }
    let mut doc = doc;
    let path = fixture.cwd.join("work/rendered/broken.png");
    broken.save(&path).unwrap();
    let digest = revayat_ir::ir::sha256_file(&path).unwrap();
    let relative = format!("rendered/broken-{digest}.png");
    fs::rename(path, fixture.cwd.join("work").join(&relative)).unwrap();
    doc["pages"][0]["final"] = json!(relative);
    doc["pages"][0]["delivery"]["final"] = json!(digest);
    write_doc(&fixture, &doc);
    let rejected = fixture.run(&["qa", "check", "--strict", "--doc", DOC], b"");
    assert_eq!(rejected.status.code(), Some(1), "{rejected:?}");
    assert!(has_finding(
        &json_stdout(&rejected),
        "missing-glyph-coverage",
        "caption"
    ));
}

#[test]
fn automatic_tilt_follows_a_slanted_source_and_leaves_flat_captions_level() {
    let source = RgbImage::from_fn(280, 240, |x, y| {
        let slanted = (67..207).contains(&x) && (52..64).contains(&(y + x / 8));
        let flat = (67..207).contains(&x) && (162..174).contains(&y);
        Rgb([if slanted || flat { 25 } else { 245 }; 3])
    });
    let fixture = setup(
        &source,
        json!([
            {"id":"slanted", "kind":"caption", "bbox":[35,15,210,100], "source_text":"That night", "target_text":"آن شب", "locked":true},
            {"id":"level", "kind":"caption", "bbox":[35,128,210,100], "source_text":"That day", "target_text":"آن روز", "locked":true}
        ]),
    );
    render(&fixture);
    let doc = document(&fixture);
    let captions = &doc["pages"][0]["regions"];
    let angle = captions[0]["typeset"]["angle_deg"].as_f64().unwrap();
    assert!((-9.0..-5.0).contains(&angle), "measured angle: {angle}");
    assert_eq!(captions[1]["typeset"]["status"], "fit");
    assert!(captions[1]["typeset"].get("angle_deg").is_none());
}

#[test]
fn invalid_lettering_overrides_fail_without_saving_partial_results() {
    let fixture = halftone_fixture();
    stage(&fixture, "mask", &[]);
    stage(&fixture, "clean", &[]);
    let clean = document(&fixture);
    for (field, bad) in [
        ("outline_px", json!(7)),
        ("outline_alpha", json!("faint")),
        ("angle", json!(-46.0)),
    ] {
        let mut doc = clean.clone();
        doc["pages"][0]["regions"][0][field] = bad;
        write_doc(&fixture, &doc);
        let output = fixture.run(&["typeset", "--doc", DOC], b"");
        assert_eq!(output.status.code(), Some(4), "{output:?}");
        assert!(String::from_utf8_lossy(&output.stderr).contains(field));
        assert_eq!(document(&fixture), doc);
    }
}

fn has_finding(report: &Value, code: &str, id: &str) -> bool {
    report["findings"]
        .as_array()
        .unwrap()
        .iter()
        .any(|f| f["code"] == code && f["region"] == id)
}

#[test]
fn strict_qa_catches_dropped_english_until_it_is_explained_or_translated() {
    let source = RgbImage::from_pixel(240, 160, Rgb([245; 3]));
    let fixture = setup(
        &source,
        json!([
            {"id":"rumble", "kind":"sfx", "bbox":[30,30,100,80], "source_text":"RUMBLE", "dropped":true, "drop_reason":"  "}
        ]),
    );
    let check = |strict| {
        let mut args = vec!["qa", "check", "--doc", DOC];
        if strict {
            args.push("--strict");
        }
        fixture.run(&args, b"")
    };
    let strict = check(true);
    assert_eq!(strict.status.code(), Some(1), "{strict:?}");
    assert!(has_finding(
        &json_stdout(&strict),
        "dropped-source-text",
        "rumble"
    ));
    let non_strict = check(false);
    success(&non_strict);
    assert_eq!(json_stdout(&non_strict)["warnings"], 1);

    let mut doc = document(&fixture);
    doc["pages"][0]["regions"][0]["drop_reason"] = json!("Repeated lettering outside the panel");
    write_doc(&fixture, &doc);
    assert!(!has_finding(&qa(&fixture), "dropped-source-text", "rumble"));

    doc["pages"][0]["regions"] = json!([
        {"id":"rumble", "kind":"sfx", "bbox":[30,30,100,80], "source_text":"RUMBLE", "target_text":"غرش", "locked":true},
        {"id":"duplicate", "kind":"sfx", "bbox":[80,30,100,80], "source_text":" boom, Rumble! ", "state":"dropped"},
        {"id":"unrelated", "kind":"sfx", "bbox":[30,30,100,80], "source_text":"CRASH", "state":"dropped"}
    ]);
    write_doc(&fixture, &doc);
    render(&fixture);
    let strict = check(true);
    assert_eq!(strict.status.code(), Some(1), "{strict:?}");
    let report = json_stdout(&strict);
    assert!(!has_finding(&report, "dropped-source-text", "duplicate"));
    assert!(has_finding(&report, "dropped-source-text", "unrelated"));
}

#[test]
fn worksheet_no_outline_suppresses_automatic_outlines_on_halftone() {
    let fixture = halftone_fixture();
    let mut doc = document(&fixture);
    doc["pages"][0]["regions"][0]["target_text"] = json!("");
    doc["pages"][0]["regions"][0]["locked"] = json!(false);
    write_doc(&fixture, &doc);
    stage(&fixture, "mask", &[]);
    stage(&fixture, "crops", &[]);
    let worksheet = run(&fixture, &["worksheet", "build", "--doc", DOC]);
    let draft = PathBuf::from(worksheet["built"][0].as_str().unwrap());
    let filled = fs::read_to_string(&draft).unwrap().replace(
        "fa:\n",
        "fa: جرقه\nstyle: italic, bold no-outline\nlock: yes\n",
    );
    fs::write(draft.with_file_name("p0001.done.txt"), filled).unwrap();
    run(&fixture, &["worksheet", "merge", "--doc", DOC]);
    render(&fixture);
    let doc = document(&fixture);
    let region = &doc["pages"][0]["regions"][0];
    assert_eq!(region["style"], "bold-italic, no-outline");
    assert_eq!(region["fill"], "inpaint");
    assert_eq!(region["typeset"]["status"], "fit");
    assert!(region["typeset"].get("outline_px").is_none());
}
