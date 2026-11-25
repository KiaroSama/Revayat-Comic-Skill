use revayat_ir::{ComicDocument, IrError, PageRecord, RegionRecord};
use revayat_ir::{
    batch, certify, context, ir, journal, languages, replies, runlog, stages, textmatch, wire_json,
    worksheet, worksheet_paths, workspace,
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, fs, io, path::Path};

fn chapter(root: &Path) -> Result<(), IrError> {
    fs::create_dir_all(root.join("pages"))?;
    for name in ["one", "two"] {
        image::RgbImage::new(4, 5)
            .save(root.join(format!("pages/{name}.png")))
            .map_err(|e| IrError::refused("fixture", e.to_string()))?;
    }
    let raw = json!({"version":1,"meta":{"sfx_policy":"keep","stage_seq":17},"glossary":{},"stages":{"masks":{"pages":2}},"pages":[
        {"id":"p0001","index":0,"image":"pages/one.png","width":4,"height":5,"regions":[]},
        {"id":"p0002","index":1,"image":"pages/two.png","width":4,"height":5,"regions":[]}
    ]});
    ir::write_bytes(root.join("comic.json"), &ir::json_bytes(&raw)?)
}

#[test]
fn source_less_legacy_plan_and_untouched_replay_keep_original_bytes() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    chapter(tmp.path())?;
    let path = tmp.path().join("comic.json");
    let before = fs::read(&path)?;
    let plan = batch::plan_shards(tmp.path(), 2, None)?;
    assert_eq!(
        plan.items.iter().map(|i| i.pages).collect::<Vec<_>>(),
        [Some([0, 1]), Some([1, 2])]
    );
    let dir = tmp.path().join("batch");
    for _ in 0..2 {
        assert_eq!(batch::merge_shards(&dir, tmp.path())?.pages, 2);
    }
    assert_eq!(fs::read(&path)?, before);
    let worker = dir.join("shard-001/comic.json");
    let mut raw: Value = serde_json::from_str(&fs::read_to_string(&worker)?)?;
    raw["source"]["sha256"] = json!("new hash");
    ir::write_bytes(worker, &ir::json_bytes(&raw)?)?;
    assert_eq!(
        batch::merge_shards(&dir, tmp.path())
            .err()
            .map(|e| e.code()),
        Some("shared_drift")
    );
    assert_eq!(fs::read(path)?, before);
    Ok(())
}

#[test]
fn legacy_integer_stage_count_recomputes_only_the_worker_page() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    chapter(tmp.path())?;
    batch::plan_shards(tmp.path(), 2, None)?;
    let dir = tmp.path().join("batch");
    let worker = dir.join("shard-002/comic.json");
    let mut local = ir::load_doc(&worker)?;
    stages::stamp_stage(
        &mut local,
        "masks",
        Default::default(),
        Some(json!({"grow":2})),
        None,
    )?;
    ir::save_doc(&local, worker)?;
    batch::merge_shards(&dir, tmp.path())?;
    let merged = ir::load_doc(tmp.path().join("comic.json"))?;
    assert_eq!(stages::stale_pages(&merged, "masks")?, ["p0001"]);
    assert_eq!(
        merged.stages["masks"]["pages"]["p0002"],
        local.stages["masks"]["pages"]["p0002"]
    );
    let doc_path = tmp.path().join("comic.json");
    let before = fs::read(&doc_path)?;
    batch::merge_shards(&dir, tmp.path())?;
    assert_eq!(fs::read(doc_path)?, before);
    Ok(())
}

#[test]
fn replay_refuses_an_altered_asset_even_when_document_is_identical() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    chapter(tmp.path())?;
    let dir = tmp.path().join("batch");
    batch::plan_shards(tmp.path(), 2, None)?;
    let worker = dir.join("shard-001/worksheets/p0001.done.txt");
    ir::write_text(&worker, "approved")?;
    batch::merge_shards(&dir, tmp.path())?;
    let path = tmp.path().join("worksheets/p0001.done.txt");
    ir::write_text(&path, "local edit")?;
    assert_eq!(
        batch::merge_shards(&dir, tmp.path())
            .err()
            .map(|e| e.code()),
        Some("snapshot_drift")
    );
    assert_eq!(fs::read_to_string(path)?, "local edit");
    Ok(())
}

#[test]
fn worksheet_addition_preserves_identity_on_replay_and_refuses_duplicate_alias()
-> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let path = tmp.path().join("comic.json");
    let doc = ComicDocument {
        pages: vec![PageRecord {
            id: "p0001".into(),
            width: 40,
            height: 40,
            ..Default::default()
        }],
        ..Default::default()
    };
    ir::save_doc(&doc, &path)?;
    let draft = worksheet::build_document(&path, None, None, false)?;
    assert_eq!(draft, [tmp.path().join("worksheets/p0001.txt")]);
    let reply = tmp.path().join("worksheets/p0001.done.txt");
    let text = format!(
        "{}\n@@ +missed speech horizontal\nbox: 1 2 20 30\nsrc: Hello\nfa: سلام\n",
        fs::read_to_string(&draft[0])?
    );
    ir::write_text(&reply, &text)?;
    worksheet::merge_document(&path, None, None, false)?;
    assert!(worksheet::merge_document(&path, None, None, false)?.is_empty());
    let updated = ir::load_doc(&path)?;
    assert_eq!(updated.pages[0].regions[0].id, "p0001_r001");
    let repeated = format!(
        "{}\n@@ p0001_r001 speech horizontal\nfa: سلام\n",
        fs::read_to_string(&reply)?
    );
    ir::write_text(reply, &repeated)?;
    assert_eq!(
        worksheet::merge_document(&path, None, None, false)
            .err()
            .map(|e| e.code()),
        Some("duplicate_regions")
    );
    Ok(())
}

#[test]
fn worksheet_receipt_repairs_interrupted_restamp_without_reapplying_persian() -> Result<(), IrError>
{
    let tmp = tempfile::tempdir()?;
    let path = tmp.path().join("comic.json");
    let doc = ComicDocument {
        pages: vec![PageRecord {
            id: "p0001".into(),
            width: 40,
            height: 40,
            regions: vec![RegionRecord {
                id: "p0001_r001".into(),
                kind: "speech".into(),
                ..Default::default()
            }],
            ..Default::default()
        }],
        ..Default::default()
    };
    ir::save_doc(&doc, &path)?;
    let raw = format!(
        "# fingerprint: {}\n# scheme: 2\n@@ p0001_r001 speech horizontal\nkind: thought\nfa: سلام\n",
        ir::page_fingerprint(&doc.pages[0])
    );
    let reply = tmp.path().join("worksheets/p0001.done.txt");
    ir::write_text(&reply, &raw)?;
    worksheet::merge_document(&path, None, None, false)?;
    let expected = fs::read_to_string(&reply)?;
    ir::write_text(&reply, &raw)?;
    assert!(worksheet::merge_document(&path, None, None, false)?.is_empty());
    assert_eq!(fs::read_to_string(&reply)?, expected);
    Ok(())
}

#[test]
fn escaped_reply_fields_cannot_be_mistaken_for_commands() -> Result<(), IrError> {
    let text = format!(
        "@@ p0001_r001 speech horizontal\r\n{}note: one\r\nnote: two\r\n",
        replies::field_lines("fa", "سلام\n# شرح\nfa: ادامه\n@@ p0002_r001")
    );
    let result = replies::parse_worksheet(&text)?;
    assert_eq!(
        result.blocks[0].fields["fa"],
        "سلام\n# شرح\nfa: ادامه\n@@ p0002_r001"
    );
    assert_eq!(result.blocks[0].notes, ["one", "two"]);
    assert_eq!(
        replies::parse_worksheet("@@ p0001_r001\nfa: one\nfa: two\n")
            .err()
            .map(|e| e.code()),
        Some("duplicate_fields")
    );
    Ok(())
}

#[test]
fn workspace_never_drops_a_replaced_claim_or_overwrites_a_new_generation() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let path = tmp.path().join("comic.json");
    ir::save_doc(&ComicDocument::default(), &path)?;
    let mut loaded = workspace::LoadedDocument::open(&path)?;
    let claim = workspace::workspace_lock(tmp.path(), "test")?;
    assert_eq!(
        workspace::workspace_lock(tmp.path(), "other")
            .err()
            .map(|e| e.code()),
        Some("workspace_busy")
    );
    let mut record = workspace::read_claim(claim.path())?;
    record.token = "replacement".into();
    ir::write_bytes(claim.path(), &ir::json_bytes(&record)?)?;
    let lock_path = claim.path().to_path_buf();
    drop(claim);
    assert_eq!(workspace::read_claim(&lock_path)?.token, "replacement");
    fs::remove_file(lock_path)?;
    ir::write_text(&path, "external edit")?;
    assert_eq!(
        loaded.save().err().map(|e| e.code()),
        Some("document_changed")
    );
    assert_eq!(fs::read_to_string(path)?, "external edit");
    Ok(())
}

#[test]
fn journal_can_resume_a_publication_then_retire_backups() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let doc_path = tmp.path().join("comic.json");
    let out = tmp.path().join("chapter.cbz");
    let staged = tmp.path().join("chapter.cbz.revayat-part");
    let mut doc = ComicDocument::default();
    ir::save_doc(&doc, &doc_path)?;
    ir::write_text(&out, "old")?;
    ir::write_text(staged, "new")?;
    doc.stages.insert("export".into(), json!({"files":1}));
    let result = json!({"format":"cbz","path":out,"manifest":[]});
    journal::write(
        &doc_path,
        &out,
        BTreeMap::from([("chapter.cbz".into(), ir::sha256_bytes(b"new"))]),
        result,
        json!({}),
        &doc,
        BTreeMap::new(),
    )?;
    let mut record =
        journal::read(&doc_path)?.ok_or_else(|| IrError::refused("fixture", "missing journal"))?;
    assert_eq!(
        journal::resume(&doc_path, &mut record)?,
        journal::Recovery::Published
    );
    assert_eq!(fs::read_to_string(&out)?, "new");
    assert_eq!(record.progress.entries["chapter.cbz"], "promoted");
    assert!(journal::finish(&doc_path, &record, true).is_err());
    ir::save_doc(&doc, &doc_path)?;
    journal::finish(&doc_path, &record, true)?;
    assert!(journal::read(&doc_path)?.is_none());
    assert!(!tmp.path().join("chapter.cbz.revayat-kept").exists());
    Ok(())
}

#[test]
fn certificate_detects_swapped_cleaning_bytes_and_omitted_fields() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut page = PageRecord {
        image: "source.png".into(),
        cleaned: Some("clean.png".into()),
        width: 4,
        height: 5,
        ..Default::default()
    };
    let root = tmp.path();
    ir::write_text(root.join("source.png"), "original")?;
    ir::write_text(root.join("clean.png"), "approved")?;
    page.extra.insert("cleaning".into(),json!({"size":[4,5],"source":ir::sha256_bytes(b"original"),"mask":null,"clean":ir::sha256_bytes(b"approved")}));
    assert!(certify::certify_cleaning(root, &page)?.is_empty());
    ir::write_text(root.join("clean.png"), "changed")?;
    assert_eq!(
        certify::certify_cleaning(root, &page)?[0].code,
        "delivery-mismatch"
    );
    Ok(())
}

#[test]
fn context_only_includes_prior_translation_and_keeps_locked_terms_outside_budget()
-> Result<(), IrError> {
    let mut doc: ComicDocument = serde_json::from_value(
        json!({"version":1,"meta":{"source_language":"ja-JP"},"pages":[{"id":"p0001","regions":[{"id":"p0001_r001","source_text":"Alice","target_text":"آلیس"}]},{"id":"p0002"},{"id":"p0003","regions":[{"id":"p0003_r001","source_text":"next"}]}]}),
    )?;
    revayat_ir::glossary::set_target(&mut doc, "Alice", "آلیس", true)?;
    let packet = context::build(&doc, "p0002", 1)?;
    assert_eq!(packet["constraints"]["glossary"]["Alice"], "آلیس");
    assert_eq!(packet["budget"]["truncated"], true);
    assert_eq!(packet["context"]["next_page"][0]["source"], "next");
    assert_eq!(packet["context"]["language_guidance"]["profile"], "ja");
    assert_eq!(
        languages::guidance(Some("unknown-script")).profile,
        "generic"
    );
    Ok(())
}

#[test]
fn recorded_worksheet_path_is_relative_to_the_document() -> Result<(), IrError> {
    let d = tempfile::tempdir()?;
    let mut doc = ComicDocument::default();
    doc.meta
        .insert("worksheets".into(), json!("translation drafts"));
    assert_eq!(
        worksheet_paths::worksheet_folder(&d.path().join("comic.json"), &doc, None),
        d.path().join("translation drafts")
    );
    Ok(())
}

#[test]
fn matching_preserves_word_boundaries_and_finite_number_order() {
    assert!(textmatch::used("(C++)", &["C++"]));
    assert!(!textmatch::used("C++20", &["C++"]));
    assert!(!textmatch::used("آلیستا", &["آلیس"]));
    assert!(textmatch::used("她是安娜。", &["安娜"]));
    let present = textmatch::digits_in("−۰۱٫۵۰۰ و ۲؛ 1e+10 and v2.3");
    assert_eq!(
        present.iter().map(String::as_str).collect::<Vec<_>>(),
        ["-1.5", "2"]
    );
    assert!(textmatch::number_spelling_used(
        "12:30",
        "ساعت ۱۲ : ۳۰",
        &Default::default()
    ));
    assert!(!textmatch::number_spelling_used(
        "12:30",
        "ساعت ۳۰ : ۱۲",
        &Default::default()
    ));
}

#[test]
fn wire_json_bounds_numbers_and_permits_exactly_max_depth() -> Result<(), IrError> {
    let valid = "7".repeat(wire_json::MAX_INTEGER_DIGITS);
    assert_eq!(wire_json::loads(&valid)?.to_string(), valid);
    assert!(wire_json::loads(&format!("1{valid}")).is_err());
    assert!(wire_json::loads("1e309").is_err());
    wire_json::loads(&format!("{}0{}", "[".repeat(128), "]".repeat(128)))?;
    Ok(())
}

#[test]
fn failed_atomic_writer_preserves_old_bytes_and_leaves_no_tempfile() -> Result<(), IrError> {
    let d = tempfile::tempdir()?;
    let path = d.path().join("comic.json");
    ir::write_text(&path, "old")?;
    assert!(
        ir::write_stream(&path, |file| {
            use std::io::Write as _;
            file.write_all(b"partial")?;
            Err(io::Error::other("disk failure"))
        })
        .is_err()
    );
    assert_eq!(fs::read_to_string(path)?, "old");
    assert_eq!(fs::read_dir(d.path())?.count(), 1);
    Ok(())
}

#[test]
fn log_collisions_do_not_replace_prior_run() -> Result<(), IrError> {
    let d = tempfile::tempdir()?;
    let now = time::macros::datetime!(2026-11-25 13:21:08 +05:00);
    let first = runlog::RunLog::open_at(d.path(), "comic", runlog::Level::Debug, now)?;
    let second = runlog::RunLog::open_at(d.path(), "comic", runlog::Level::Debug, now)?;
    first.event(runlog::Level::Info, "test", "first record")?;
    second.event(runlog::Level::Critical,"test","Authorization: Bearer fake-secret https://user:pwd@example.invalid/ auth_token=another\nnew line")?;
    assert!(first.path().ends_with("comic_2026-11-25_08-21-08_UTC.log"));
    assert!(
        second
            .path()
            .ends_with("comic_2026-11-25_08-21-08_UTC_001.log")
    );
    assert!(fs::read_to_string(first.path())?.contains("first record"));
    let second = fs::read_to_string(second.path())?;
    assert_eq!(second.lines().count(), 1);
    for secret in ["fake-secret", "example.invalid", "another"] {
        assert!(!second.contains(secret));
    }
    Ok(())
}
