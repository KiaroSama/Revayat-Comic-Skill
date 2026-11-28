use super::*;
use image::{Rgb, RgbImage};

const DOC: &str = "work/comic.json";
const FLAGS: &str = "work/review/flags.json";
const LEDGER: &str = "work/review/ledger.tsv";

fn document(fixture: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(fixture.cwd.join(DOC)).unwrap()).unwrap()
}

fn write_document(fixture: &Fixture, doc: &Value) {
    fs::write(fixture.cwd.join(DOC), serde_json::to_vec(doc).unwrap()).unwrap();
}

fn review_fixture(name: &str) -> Fixture {
    let fixture = Fixture::new(name);
    fs::create_dir(fixture.cwd.join("source")).unwrap();
    let page = RgbImage::from_fn(220, 180, |x, y| {
        Rgb([if (20..200).contains(&x) && (20..160).contains(&y) {
            245
        } else {
            20
        }; 3])
    });
    page.save(fixture.cwd.join("source/0.png")).unwrap();
    success(&fixture.run(&["import", "source", "--out", "work"], b""));
    let mut doc = document(&fixture);
    doc["meta"]["source_language"] = json!("en");
    doc["pages"][0]["regions"] = json!([{
        "id": "p0001_r001", "kind": "speech", "bbox": [40, 50, 140, 80],
        "source_text": "3.", "target_text": "3.", "locked": true
    }]);
    write_document(&fixture, &doc);
    render(&fixture);
    fixture
}

fn render(fixture: &Fixture) {
    success(&fixture.run(&["mask", "--doc", DOC], b""));
    success(&fixture.run(&["clean", "--doc", DOC, "--bubbles-only"], b""));
    success(&fixture.run(&["typeset", "--doc", DOC], b""));
}

fn generate(fixture: &Fixture) -> Value {
    success(&fixture.run(&["qa", "review-pack", "--doc", DOC], b""));
    serde_json::from_slice(&fs::read(fixture.cwd.join(FLAGS)).unwrap()).unwrap()
}

fn approve(fixture: &Fixture) -> String {
    let ledger = fs::read_to_string(fixture.cwd.join("work/review/ledger.template.tsv"))
        .unwrap()
        .replace("\tPENDING\t", "\tPASS\t");
    fs::write(fixture.cwd.join(LEDGER), &ledger).unwrap();
    ledger
}

fn verify(fixture: &Fixture) -> Output {
    fixture.run(&["qa", "review-pack", "--doc", DOC, "--verify-ledger"], b"")
}

fn refused(output: &Output) {
    assert!(
        !output.status.success(),
        "expected review refusal: {output:?}"
    );
    assert!(!String::from_utf8_lossy(&output.stderr).contains("panicked"));
}

fn crop_path(fixture: &Fixture, flags: &Value) -> PathBuf {
    let item = flags["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["region_id"] == "p0001_r001")
        .unwrap();
    fixture
        .cwd
        .join("work/review")
        .join(item["crop_path"].as_str().unwrap())
}

#[test]
fn review_approvals_are_bound_to_current_document_images_and_regenerated_crops() {
    let fixture = review_fixture("review28_snapshot");
    let first = generate(&fixture);
    refused(&verify(&fixture));
    let old_ledger = approve(&fixture);
    success(&verify(&fixture));
    let old_crop = fs::read(crop_path(&fixture, &first)).unwrap();

    // Regeneration without changed evidence must preserve the review identity.
    let unchanged = generate(&fixture);
    assert_eq!(first, unchanged);
    success(&verify(&fixture));

    let mut doc = document(&fixture);
    doc["pages"][0]["regions"][0]["target_text"] = json!("4.");
    write_document(&fixture, &doc);
    refused(&verify(&fixture));
    render(&fixture);
    let changed = generate(&fixture);
    assert_ne!(old_crop, fs::read(crop_path(&fixture, &changed)).unwrap());
    assert_eq!(
        fs::read_to_string(fixture.cwd.join(LEDGER)).unwrap(),
        old_ledger
    );
    refused(&verify(&fixture));
    approve(&fixture);
    success(&verify(&fixture));

    let crop = crop_path(&fixture, &changed);
    let current_crop = fs::read(&crop).unwrap();
    fs::write(&crop, b"corrupt reviewed image").unwrap();
    refused(&verify(&fixture));
    fs::write(&crop, current_crop).unwrap();
    success(&verify(&fixture));

    let doc = document(&fixture);
    let source = fixture
        .cwd
        .join("work")
        .join(doc["pages"][0]["image"].as_str().unwrap());
    let source_bytes = fs::read(&source).unwrap();
    fs::write(&source, b"changed immutable source").unwrap();
    refused(&verify(&fixture));
    fs::write(source, source_bytes).unwrap();
    success(&verify(&fixture));

    let final_path = fixture
        .cwd
        .join("work")
        .join(doc["pages"][0]["final"].as_str().unwrap());
    let final_bytes = fs::read(&final_path).unwrap();
    fs::write(&final_path, b"changed rendered image").unwrap();
    refused(&verify(&fixture));
    fs::write(final_path, final_bytes).unwrap();
    success(&verify(&fixture));
}

#[test]
fn review_ledger_requires_exact_snapshot_rows_and_explicit_full_page_coverage() {
    let fixture = review_fixture("review28_coverage");
    let flags = generate(&fixture);
    let good = approve(&fixture);
    success(&verify(&fixture));

    let mut omitted = flags.clone();
    omitted["items"] = json!([]);
    fs::write(
        fixture.cwd.join(FLAGS),
        serde_json::to_vec(&omitted).unwrap(),
    )
    .unwrap();
    fs::write(
        fixture.cwd.join(LEDGER),
        good.replace("p0001_r001", "not_a_region"),
    )
    .unwrap();
    refused(&verify(&fixture));
    fs::write(fixture.cwd.join(FLAGS), serde_json::to_vec(&flags).unwrap()).unwrap();

    for invalid in [
        good.replace("\tPASS\t", "\tFAIL\t"),
        good.replace("\tPASS\t", "\tPENDING\t"),
        good.replace("p0001_r001", "not_a_region"),
        format!("{good}{}\n", good.lines().nth(1).unwrap()),
        good.lines().filter(|line| !line.contains("\t*\t")).map(|line| format!("{line}\n")).collect(),
        "page_id\tregion_id\tstage\tverdict\tdefect_codes\tnotes\np0001\tp0001_r001\t5a\tPASS\t\tlegacy\n".into(),
    ] {
        fs::write(fixture.cwd.join(LEDGER), invalid).unwrap();
        refused(&verify(&fixture));
    }
    assert!(
        flags["items"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["region_id"] == "*")
    );
    fs::write(
        fixture.cwd.join(LEDGER),
        good.replace("\tPASS\t", "\tFIXED\t"),
    )
    .unwrap();
    success(&verify(&fixture));
}

#[test]
fn review_generation_rejects_invalid_geometry_without_replacing_a_valid_manifest() {
    let fixture = review_fixture("review28_geometry");
    generate(&fixture);
    approve(&fixture);
    let flags = fs::read(fixture.cwd.join(FLAGS)).unwrap();
    let valid = document(&fixture);
    for field in ["bbox", "ink_box"] {
        let mut invalid = valid.clone();
        if field == "bbox" {
            invalid["pages"][0]["regions"][0][field] = json!([2000, 50, 140, 80]);
        } else {
            invalid["pages"][0]["regions"][0]["typeset"][field] = json!([2000, 50, 10, 10]);
        }
        write_document(&fixture, &invalid);
        refused(&fixture.run(&["qa", "review-pack", "--doc", DOC], b""));
        assert_eq!(fs::read(fixture.cwd.join(FLAGS)).unwrap(), flags);
    }
    let mut invalid = valid.clone();
    RgbImage::from_pixel(10, 10, Rgb([245; 3]))
        .save(fixture.cwd.join("work/small.png"))
        .unwrap();
    invalid["pages"][0]["final"] = json!("small.png");
    write_document(&fixture, &invalid);
    refused(&fixture.run(&["qa", "review-pack", "--doc", DOC], b""));
    refused(&verify(&fixture));
    assert_eq!(fs::read(fixture.cwd.join(FLAGS)).unwrap(), flags);
    write_document(&fixture, &valid);
    success(&verify(&fixture));
}

#[cfg(unix)]
#[test]
fn review_crop_output_rejects_a_redirected_directory() {
    let fixture = review_fixture("review28_symlink");
    fs::create_dir(fixture.cwd.join("outside")).unwrap();
    fs::create_dir(fixture.cwd.join("work/review")).unwrap();
    std::os::unix::fs::symlink(
        fixture.cwd.join("outside"),
        fixture.cwd.join("work/review/crops"),
    )
    .unwrap();
    refused(&fixture.run(&["qa", "review-pack", "--doc", DOC], b""));
    assert_eq!(
        fs::read_dir(fixture.cwd.join("outside")).unwrap().count(),
        0
    );
    assert!(!fixture.cwd.join(FLAGS).exists());
}

#[test]
fn tagged_english_and_halfwidth_kana_preserve_art_and_allow_explicit_keep_recovery() {
    for (language, source) in [
        ("en", "ゴゴゴ"),
        ("en-US", "ゴゴゴ"),
        ("en_GB", "ゴゴゴ"),
        ("en", "ｺﾞｺﾞｺﾞ"),
    ] {
        let fixture = review_fixture("review28_language");
        let mut doc = document(&fixture);
        doc["meta"]["source_language"] = json!(language);
        doc["meta"]["sfx_policy"] = json!("translate");
        doc["pages"][0]["regions"][0]["source_text"] = json!(source);
        doc["pages"][0]["regions"][0]["target_text"] = json!("غرش");
        write_document(&fixture, &doc);
        render(&fixture);
        let doc = document(&fixture);
        let source = image::open(
            fixture
                .cwd
                .join("work")
                .join(doc["pages"][0]["image"].as_str().unwrap()),
        )
        .unwrap()
        .into_rgb8();
        let rendered = image::open(
            fixture
                .cwd
                .join("work")
                .join(doc["pages"][0]["final"].as_str().unwrap()),
        )
        .unwrap()
        .into_rgb8();
        assert_eq!(
            source, rendered,
            "protected {language} / {source:?} must remain unchanged"
        );
        let qa = fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b"");
        refused(&qa);
        assert!(
            json_stdout(&qa)["findings"]
                .as_array()
                .unwrap()
                .iter()
                .any(|item| item["code"] == "protected-japanese-modified")
        );
        let mut doc = document(&fixture);
        doc["pages"][0]["regions"][0]["target_text"] = json!("");
        doc["pages"][0]["regions"][0]["keep"] = json!(true);
        write_document(&fixture, &doc);
        render(&fixture);
        success(&fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b""));
    }
}

#[test]
fn language_context_edits_require_only_affected_stages_and_recover_normally() {
    for field in ["source_text", "source_language", "target_language"] {
        let fixture = review_fixture("review28_freshness");
        success(&fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b""));
        let mut doc = document(&fixture);
        if field == "source_text" {
            doc["pages"][0]["regions"][0][field] = json!("Number three");
        } else {
            doc["meta"][field] = json!(if field == "source_language" {
                "ja"
            } else {
                "en"
            });
        }
        write_document(&fixture, &doc);
        refused(&fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b""));
        if field == "target_language" {
            success(&fixture.run(&["typeset", "--doc", DOC], b""));
        } else {
            render(&fixture);
        }
        success(&fixture.run(&["qa", "check", "--doc", DOC, "--strict"], b""));
    }
}
