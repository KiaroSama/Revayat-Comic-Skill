use revayat_ir::{ComicDocument, IrError, PageRecord, RegionRecord, RegionState};
use revayat_ir::{batch, glossary, ir, regions, runlog, stages, wire_json, worksheet};
use serde_json::json;
use std::fs;

#[test]
fn sha256_file_and_bytes_keep_the_same_lowercase_wire_digest() -> Result<(), IrError> {
    let input = b"block\0\xff".repeat(2400);
    let expected = "333fbe53a7e71cc19976f21b30e9e5685cbdebe22ee93bef9b93f53cfd36386a";
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("digest sample.bin");
    fs::write(&path, &input)?;
    assert_eq!(ir::sha256_bytes(&input), expected);
    assert_eq!(ir::sha256_file(&path)?, expected);
    assert_eq!(
        ir::sha256_bytes(b""),
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
    Ok(())
}

#[test]
fn original_records_keep_their_wire_fields() -> Result<(), IrError> {
    let doc: ComicDocument = serde_json::from_value(
        json!({"version":1,"pages":[{"id":"p0001","image":"pages/1.png","regions":[{"id":"p0001r003","source_text":"こんにちは","bbox":[1,2,3,4],"provider":"saved"}]}]}),
    )?;
    assert_eq!(doc.pages[0].regions[0].id, "p0001r003");
    assert_eq!(
        serde_json::to_value(&doc)?["pages"][0]["regions"][0]["provider"],
        "saved"
    );
    assert_eq!(ir::region_id_for(&doc.pages[0].id, 4), "p0001_r004");
    Ok(())
}

#[test]
fn erasure_reaches_terminal_only_after_cleaning() -> Result<(), IrError> {
    let mut region = RegionRecord {
        erase: true,
        ..RegionRecord::default()
    };
    assert_eq!(
        regions::region_state(&region, "keep")?,
        RegionState::Pending
    );
    region.fill = "inpaint".into();
    assert_eq!(regions::region_state(&region, "keep")?, RegionState::Erased);
    region.keep = true;
    assert_eq!(
        regions::region_state(&region, "keep")
            .err()
            .map(|e| e.code()),
        Some("conflicting_actions")
    );
    Ok(())
}

#[test]
fn worksheets_round_trip_and_refuse_moved_geometry() -> Result<(), IrError> {
    let mut page = PageRecord {
        id: "p0001".into(),
        regions: vec![RegionRecord {
            id: "p0001_r001".into(),
            source_text: "Hello".into(),
            ..RegionRecord::default()
        }],
        ..PageRecord::default()
    };
    let doc = ComicDocument::default();
    let draft = worksheet::page_worksheet(&doc, &page).replace("fa:\n", "fa: سلام\nدوباره\n");
    let reply = worksheet::parse(&draft)?;
    assert_eq!(reply.blocks[0].fields["fa"], "سلام\nدوباره");
    let mut moved = page.clone();
    moved.regions[0].bbox[0] += 1;
    assert_eq!(
        worksheet::merge_page(&mut moved, &reply)
            .err()
            .map(|e| e.code()),
        Some("stale-worksheets")
    );
    worksheet::merge_page(&mut page, &reply)?;
    assert_eq!(page.regions[0].target_text, "سلام\nدوباره");
    Ok(())
}

#[test]
fn shared_snapshot_normalizes_legacy_metadata_without_hiding_drift() -> Result<(), IrError> {
    let a = json!({"version":1,"meta":{"sfx_policy":"keep","stage_seq":12},"pages":[],"stages":{}});
    let b = json!({"version":1,"meta":{"sfx_policy":"keep"},"source":{"page_count":4},"pages":[{}],"stages":{"ocr":{"pages":4}}});
    assert_eq!(
        batch::shared_digest(&a, false)?,
        batch::shared_digest(&b, false)?
    );
    let mut drift = b;
    drift["source"]["sha256"] = json!("new source");
    assert_ne!(
        batch::shared_digest(&a, false)?,
        batch::shared_digest(&drift, false)?
    );
    Ok(())
}

#[test]
fn stage_revisions_treat_missing_and_unknown_dependency_as_equivalent() -> Result<(), IrError> {
    let doc: ComicDocument = serde_json::from_value(
        json!({"version":1,"pages":[{"id":"p0001"}],"stages":{"mask":{"pages":2},"clean":{"pages":2,"needs":{"mask":{"p0001":"unknown"}}}}}),
    )?;
    assert!(stages::stale_pages(&doc, "mask")?.is_empty());
    assert_eq!(
        stages::why_stale(
            "clean",
            "p0001",
            &json!({"pages":{"p0001":"revision"},"needs":{"mask":{"p0001":"unknown"}}}),
            &doc.stages
        ),
        "the inputs changed after it ran, for"
    );
    Ok(())
}

#[test]
fn repeated_names_appear_in_glossary_and_bad_renderings_conflict() -> Result<(), IrError> {
    let mut doc: ComicDocument = serde_json::from_value(
        json!({"version":1,"pages":[{"id":"p0001","regions":[{"id":"p0001_r001","source_text":"Alice","target_text":"آلیس"},{"id":"p0001_r002","source_text":"Alice","target_text":"الیس"}]}]}),
    )?;
    glossary::scan(&mut doc, 2)?;
    assert!(doc.glossary["entries"].get("Alice").is_some());
    glossary::set_target(&mut doc, "Alice", "آلیس", true)?;
    assert!(!glossary::check(&doc).is_empty());
    Ok(())
}

#[test]
fn exact_replay_never_calls_publication() -> Result<(), IrError> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("comic.json");
    let doc = ComicDocument::default();
    ir::save_doc(&doc, &path)?;
    let snapshot = batch::snapshot(dir.path(), &doc)?;
    let mut published = false;
    assert!(!batch::publish_if_changed(
        dir.path(),
        &doc,
        &snapshot,
        &Default::default(),
        || {
            published = true;
            Ok(())
        }
    )?);
    assert!(!published);
    Ok(())
}

#[test]
fn atomic_write_preserves_utf8_and_replaces_the_existing_file() -> Result<(), IrError> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("chapter draft.txt");
    ir::write_text(&path, "old")?;
    ir::write_text(&path, "خانهٔ ما")?;
    assert_eq!(fs::read_to_string(path)?, "خانهٔ ما");
    assert_eq!(fs::read_dir(dir.path())?.count(), 1);
    Ok(())
}

#[test]
fn wire_json_refuses_excessive_depth_and_unpaired_surrogates() -> Result<(), IrError> {
    assert!(wire_json::loads(&format!("{}0{}", "[".repeat(129), "]".repeat(129))).is_err());
    assert!(wire_json::loads(r#""\ud800""#).is_err());
    assert_eq!(wire_json::loads(r#"{"fa":"سلام"}"#)?["fa"], "سلام");
    Ok(())
}

#[test]
fn runlog_redacts_credentials_and_uses_utc() -> Result<(), IrError> {
    let dir = tempfile::tempdir()?;
    let log = runlog::RunLog::open_at(
        dir.path(),
        "revayat",
        runlog::Level::Debug,
        time::OffsetDateTime::now_utc(),
    )?;
    log.event(
        runlog::Level::Info,
        "stage",
        "token=sensitive https://example.invalid/private",
    )?;
    let filename = log
        .path()
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or_default();
    assert!(filename.starts_with("revayat_"));
    assert!(filename.ends_with("_UTC.log"));
    let text = fs::read_to_string(log.path())?;
    assert!(text.contains(" UTC] [INFO] [stage]"));
    assert!(text.contains("[REDACTED]"));
    assert!(!text.contains("sensitive"));
    assert!(!text.contains("example.invalid"));
    Ok(())
}
