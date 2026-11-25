use revayat_ir::{ComicDocument, IrError, PageRecord, RegionRecord, RegionState};
use revayat_ir::{batch, certify, ir, journal, replies, review, stages, worksheet};
use serde_json::json;
use std::{collections::BTreeMap, fs, io::Cursor, path::Path};

fn translated_page() -> PageRecord {
    PageRecord {
        id: "p0001".into(),
        width: 100,
        height: 100,
        regions: vec![RegionRecord {
            id: "p0001_r001".into(),
            bbox: [10, 10, 30, 30],
            kind: "speech".into(),
            source_text: "The original words".into(),
            target_text: "متن فارسی".into(),
            ..Default::default()
        }],
        ..Default::default()
    }
}

#[test]
fn worksheet_deleting_all_reader_notes_preserves_stage_audit() -> Result<(), IrError> {
    let mut page = translated_page();
    page.regions[0].review = vec!["Resolve this speaker".into()];
    page.regions[0]
        .extra
        .insert("audit".into(), json!(["clean refused an unsafe patch"]));
    let text = worksheet::page_worksheet(&ComicDocument::default(), &page)
        .replace("note: Resolve this speaker\n", "");
    worksheet::merge_page(&mut page, &worksheet::parse(&text)?)?;
    assert!(page.regions[0].review.is_empty());
    assert_eq!(
        page.regions[0].extra["audit"],
        json!(["clean refused an unsafe patch"])
    );
    Ok(())
}

#[test]
fn worksheet_deleting_the_translation_cannot_reuse_an_older_answer() -> Result<(), IrError> {
    let mut page = translated_page();
    let before = page.clone();
    let text =
        worksheet::page_worksheet(&ComicDocument::default(), &page).replace("fa: متن فارسی\n", "");
    assert_eq!(
        worksheet::merge_page(&mut page, &worksheet::parse(&text)?)
            .err()
            .map(|error| error.code()),
        Some("empty_translation")
    );
    assert_eq!(page, before);
    Ok(())
}

#[test]
fn worksheet_deleting_full_text_and_speaker_replaces_saved_values() -> Result<(), IrError> {
    let mut page = translated_page();
    page.regions[0].speaker = Some("Alice".into());
    page.regions[0]
        .extra
        .insert("target_full".into(), json!("متن کامل فارسی"));
    let text = worksheet::page_worksheet(&ComicDocument::default(), &page)
        .replace("speaker: Alice\n", "")
        .replace("fa_full: متن کامل فارسی\n", "");
    worksheet::merge_page(&mut page, &worksheet::parse(&text)?)?;
    assert!(page.regions[0].speaker.is_none());
    assert!(!page.regions[0].extra.contains_key("target_full"));
    Ok(())
}

#[test]
fn worksheet_roundtrip_preserves_explicit_blank_paragraphs() -> Result<(), IrError> {
    let value = "\nآغاز\n\nپایان\n";
    let text = format!("@@ p0001_r001\n{}", replies::field_lines("fa", value));
    assert_eq!(worksheet::parse(&text)?.blocks[0].value("fa"), Some(value));
    assert_eq!(
        worksheet::parse("@@ p0001_r001\nfa: آغاز\n\\\nپایان\n")?.blocks[0].value("fa"),
        Some("آغاز\n\nپایان")
    );
    Ok(())
}

#[test]
fn worksheet_carriage_returns_cannot_turn_value_text_into_actions() -> Result<(), IrError> {
    let value = "متن\rkeep: yes\r@@ p0002_r001";
    let text = format!("@@ p0001_r001\n{}", replies::field_lines("fa", value));
    let reply = worksheet::parse(&text)?;
    assert_eq!(reply.blocks.len(), 1);
    assert_eq!(
        reply.blocks[0].value("fa"),
        Some("متن\nkeep: yes\n@@ p0002_r001")
    );
    assert!(!reply.blocks[0].affirmative("keep"));
    Ok(())
}

#[test]
fn worksheet_multiline_title_cannot_create_protocol_blocks() -> Result<(), IrError> {
    let page = translated_page();
    let mut doc = ComicDocument::default();
    doc.meta
        .insert("title".into(), json!("Chapter\r\n@@ injected\nfa: ignored"));
    let text = worksheet::page_worksheet(&doc, &page);
    let reply = worksheet::parse(&text)?;
    assert_eq!(reply.blocks.len(), 1);
    assert_eq!(reply.blocks[0].id, page.regions[0].id);
    Ok(())
}

#[test]
fn worksheet_legacy_explicit_action_roundtrips_without_losing_the_decision() -> Result<(), IrError>
{
    for state in [RegionState::Kept, RegionState::Dropped, RegionState::Erased] {
        let mut page = translated_page();
        page.regions[0].state = Some(state);
        page.regions[0].target_text.clear();
        let text = worksheet::page_worksheet(&ComicDocument::default(), &page);
        worksheet::merge_page(&mut page, &worksheet::parse(&text)?)?;
        assert!(page.regions[0].locked);
        assert!(match state {
            RegionState::Kept => page.regions[0].keep,
            RegionState::Dropped => page.regions[0].dropped,
            RegionState::Erased => page.regions[0].erase,
            _ => false,
        });
    }
    Ok(())
}

#[test]
fn explicit_region_actions_invalidate_every_rendering_stage() -> Result<(), IrError> {
    for state in [RegionState::Kept, RegionState::Dropped, RegionState::Erased] {
        let mut doc = ComicDocument {
            pages: vec![translated_page()],
            ..Default::default()
        };
        for stage in ["masks", "clean", "typeset", "export"] {
            stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
        }
        doc.pages[0].regions[0].state = Some(state);
        for stage in ["masks", "clean", "typeset", "export"] {
            assert_eq!(
                stages::stale_pages(&doc, stage)?,
                ["p0001"],
                "{stage} did not observe {state:?}"
            );
        }
    }
    Ok(())
}

#[test]
fn mask_placement_used_by_the_rust_cleaner_invalidates_cleaning() -> Result<(), IrError> {
    let mut doc = ComicDocument {
        pages: vec![translated_page()],
        ..Default::default()
    };
    doc.pages[0].regions[0].mask = Some("masks/p0001_r001.png".into());
    doc.pages[0].regions[0]
        .extra
        .insert("mask_bounds".into(), json!([10, 10, 30, 30]));
    stages::stamp_stage(&mut doc, "clean", Default::default(), None, None)?;
    doc.pages[0].regions[0]
        .extra
        .insert("mask_bounds".into(), json!([11, 10, 30, 30]));
    assert_eq!(stages::stale_pages(&doc, "clean")?, ["p0001"]);
    Ok(())
}

#[test]
fn worksheet_accepts_named_lint_review_and_emits_bound_evidence() -> Result<(), IrError> {
    let mut page = translated_page();
    page.regions[0].target_text = "می ناب".into();
    let text = format!(
        "{}reviewed: zwnj-review\n",
        worksheet::page_worksheet(&ComicDocument::default(), &page)
    );
    worksheet::merge_page(&mut page, &worksheet::parse(&text)?)?;
    assert_eq!(page.regions[0].extra["review_ack"], json!(["zwnj-review"]));
    let rebuilt = worksheet::page_worksheet(&ComicDocument::default(), &page);
    assert!(rebuilt.contains("reviewed: zwnj-review@"));
    Ok(())
}

fn reviewed_page() -> Result<PageRecord, IrError> {
    let mut page = translated_page();
    page.regions[0].target_text = "می ناب".into();
    let text = format!(
        "{}reviewed: zwnj-review\n",
        worksheet::page_worksheet(&ComicDocument::default(), &page)
    );
    worksheet::merge_page(&mut page, &worksheet::parse(&text)?)?;
    Ok(page)
}

fn reviewed_document(root: &Path) -> Result<(), IrError> {
    let mut page = translated_page();
    page.regions[0]
        .extra
        .insert("target_full".into(), json!("متن کامل فارسی"));
    page.regions[0]
        .extra
        .insert("source_revision".into(), json!(1));
    let doc = ComicDocument {
        pages: vec![page],
        ..Default::default()
    };
    let path = root.join("comic.json");
    ir::save_doc(&doc, &path)?;
    write_current_review(root)?;
    worksheet::merge_document(&path, None, None, false)?;
    Ok(())
}

fn write_current_review(root: &Path) -> Result<(), IrError> {
    let draft = worksheet::build_document(&root.join("comic.json"), None, None, true)?;
    ir::write_text(
        root.join("worksheets/p0001.done.txt"),
        &format!(
            "{}reviewed: compressed-variant\n",
            fs::read_to_string(&draft[0])?
        ),
    )
}

#[test]
fn worksheet_reapproval_applies_the_same_reply_after_a_fresh_geometry_rebuild()
-> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    reviewed_document(tmp.path())?;
    let path = tmp.path().join("comic.json");
    let mut changed = ir::load_doc(&path)?;
    changed.pages[0].regions[0].bbox[2] += 1;
    ir::save_doc(&changed, &path)?;
    assert_eq!(
        worksheet::merge_document(&path, None, None, false)
            .err()
            .map(|error| error.code()),
        Some("stale-worksheets")
    );
    write_current_review(tmp.path())?;
    assert_eq!(
        worksheet::merge_document(&path, None, None, false)?,
        ["p0001"]
    );
    let approved = ir::load_doc(&path)?;
    assert!(review::settled(
        &approved.pages[0].regions[0],
        "compressed-variant"
    ));
    let before = fs::read(&path)?;
    assert!(worksheet::merge_document(&path, None, None, false)?.is_empty());
    assert_eq!(fs::read(path)?, before);
    Ok(())
}

#[test]
fn worksheet_old_bare_review_cannot_replay_after_a_source_revision_changes() -> Result<(), IrError>
{
    let tmp = tempfile::tempdir()?;
    reviewed_document(tmp.path())?;
    let path = tmp.path().join("comic.json");
    let mut changed = ir::load_doc(&path)?;
    changed.pages[0].regions[0]
        .extra
        .insert("source_revision".into(), json!(2));
    ir::save_doc(&changed, &path)?;
    let before = fs::read(&path)?;
    assert_eq!(
        worksheet::merge_document(&path, None, None, false)
            .err()
            .map(|error| error.code()),
        Some("stale-worksheets")
    );
    assert_eq!(fs::read(path)?, before);
    Ok(())
}

#[test]
fn worksheet_current_bare_review_can_renew_a_changed_source_revision() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    reviewed_document(tmp.path())?;
    let path = tmp.path().join("comic.json");
    let mut changed = ir::load_doc(&path)?;
    changed.pages[0].regions[0]
        .extra
        .insert("source_revision".into(), json!(2));
    ir::save_doc(&changed, &path)?;
    write_current_review(tmp.path())?;
    assert_eq!(
        worksheet::merge_document(&path, None, None, false)?,
        ["p0001"]
    );
    let approved = ir::load_doc(&path)?;
    assert!(review::settled(
        &approved.pages[0].regions[0],
        "compressed-variant"
    ));
    let before = fs::read(&path)?;
    assert!(worksheet::merge_document(&path, None, None, false)?.is_empty());
    assert_eq!(fs::read(path)?, before);
    Ok(())
}

#[test]
fn worksheet_moving_a_region_reassigns_its_panel_and_reading_order() -> Result<(), IrError> {
    let mut page = translated_page();
    page.panels = vec![
        json!({"id":"left", "bbox":[0,0,45,100]}),
        json!({"id":"right", "bbox":[55,0,45,100]}),
    ];
    let mut moved = page.regions[0].clone();
    moved.bbox = [5, 10, 10, 8];
    moved.panel = Some(json!("left"));
    moved.reading_order = 2;
    let mut right = moved.clone();
    right.id = "p0001_r002".into();
    right.bbox = [60, 20, 10, 8];
    right.panel = Some(json!("right"));
    right.reading_order = 1;
    page.regions = vec![right, moved];
    let text = worksheet::page_worksheet(&ComicDocument::default(), &page);
    let mut reply = worksheet::parse(&text)?;
    reply.blocks[1]
        .fields
        .insert("box".into(), "80 2 10 8".into());
    worksheet::merge_page(&mut page, &reply)?;
    assert_eq!(page.regions[0].id, "p0001_r001");
    assert_eq!(page.regions[0].panel, Some(json!("right")));
    assert_eq!(page.regions[0].reading_order, 1);
    assert_eq!(page.regions[1].id, "p0001_r002");
    assert_eq!(page.regions[1].reading_order, 2);
    Ok(())
}

#[test]
fn worksheet_added_regions_follow_the_document_direction_and_preserve_ids() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let path = tmp.path().join("comic.json");
    let mut page = translated_page();
    page.panels = vec![
        json!({"id":"left", "bbox":[0,0,45,100]}),
        json!({"id":"right", "bbox":[55,0,45,100]}),
    ];
    page.regions[0].bbox = [60, 10, 10, 8];
    page.regions[0].panel = Some(json!("right"));
    page.regions[0].reading_order = 1;
    let doc = ComicDocument {
        meta: [("reading_direction".into(), json!("ltr"))]
            .into_iter()
            .collect(),
        pages: vec![page],
        ..Default::default()
    };
    ir::save_doc(&doc, &path)?;
    let text = format!(
        "{}\n@@ +missed speech horizontal\nbox: 5 10 10 8\nsrc: Hello\nfa: سلام\n",
        worksheet::page_worksheet(&doc, &doc.pages[0])
    );
    ir::write_text(tmp.path().join("worksheets/p0001.done.txt"), &text)?;
    worksheet::merge_document(&path, None, None, false)?;
    let merged = ir::load_doc(path)?;
    assert_eq!(merged.pages[0].regions[0].id, "p0001_r002");
    assert_eq!(merged.pages[0].regions[0].panel, Some(json!("left")));
    assert_eq!(merged.pages[0].regions[1].id, "p0001_r001");
    Ok(())
}

#[test]
fn worksheet_text_only_merge_preserves_the_readers_order() -> Result<(), IrError> {
    let mut page = translated_page();
    page.regions[0].reading_order = 17;
    let reply = worksheet::parse(&worksheet::page_worksheet(&ComicDocument::default(), &page))?;
    worksheet::merge_page(&mut page, &reply)?;
    assert_eq!(page.regions[0].reading_order, 17);
    Ok(())
}

#[test]
fn carried_review_only_approves_the_original_source_revision_and_words() -> Result<(), IrError> {
    let approved = reviewed_page()?;
    let carried = worksheet::page_worksheet(&ComicDocument::default(), &approved);
    let mut repeated = approved.clone();
    worksheet::merge_page(&mut repeated, &worksheet::parse(&carried)?)?;
    assert_eq!(review::acknowledged(&repeated.regions[0]), ["zwnj-review"]);
    assert!(!repeated.regions[0].extra.contains_key("review_ack_history"));
    for modified in [
        carried.replace("fa: می ناب", "fa: می رود"),
        carried.replace("src: The original words", "src: Different words"),
    ] {
        let mut edited = approved.clone();
        worksheet::merge_page(&mut edited, &worksheet::parse(&modified)?)?;
        assert!(review::acknowledged(&edited.regions[0]).is_empty());
        assert_eq!(
            edited.regions[0].extra["review_ack_history"][0]["codes"],
            json!(["zwnj-review"])
        );
    }
    let mut revised = approved;
    revised.regions[0]
        .extra
        .insert("source_revision".into(), json!(2));
    assert!(review::acknowledged(&revised.regions[0]).is_empty());
    assert!(!worksheet::page_worksheet(&ComicDocument::default(), &revised).contains("reviewed:"));
    Ok(())
}

#[test]
fn direct_text_changes_and_explicit_review_clears_reopen_lint() -> Result<(), IrError> {
    let approved = reviewed_page()?;
    let mut edited = approved.clone();
    edited.regions[0].target_text = "می رود".into();
    assert!(review::acknowledged(&edited.regions[0]).is_empty());
    assert_eq!(review::acknowledged_spans(&edited.regions[0]), Some(vec![]));
    let carried = worksheet::page_worksheet(&ComicDocument::default(), &approved);
    let old = worksheet::parse(&carried)?.blocks[0].fields["reviewed"].clone();
    let cleared = carried.replace(&format!("reviewed: {old}"), "reviewed:");
    let mut page = approved;
    worksheet::merge_page(&mut page, &worksheet::parse(&cleared)?)?;
    assert!(review::acknowledged(&page.regions[0]).is_empty());
    assert!(
        page.regions[0].extra["review_ack_history"]
            .as_array()
            .is_some_and(|history| history.len() == 1)
    );
    Ok(())
}

#[test]
fn legacy_span_approvals_are_not_promoted_to_whole_text_approval() {
    let mut page = translated_page();
    page.regions[0].target_text = "می ناب و می رود".into();
    page.regions[0]
        .extra
        .insert("review_ack".into(), json!(["zwnj-review"]));
    page.regions[0]
        .extra
        .insert("review_ack_spans".into(), json!(["می ناب"]));
    assert_eq!(review::acknowledged(&page.regions[0]), ["zwnj-review"]);
    assert_eq!(
        review::acknowledged_spans(&page.regions[0]),
        Some(vec!["می ناب"])
    );
    assert!(!worksheet::page_worksheet(&ComicDocument::default(), &page).contains("reviewed:"));
}

#[test]
fn compression_approval_binds_full_displayed_source_and_layout() -> Result<(), IrError> {
    let mut page = translated_page();
    page.regions[0]
        .extra
        .insert("target_full".into(), json!("متن کامل فارسی"));
    assert!(review::compression_review_needed(&page.regions[0], "keep"));
    let text = format!(
        "{}reviewed: compressed-variant\n",
        worksheet::page_worksheet(&ComicDocument::default(), &page)
    );
    worksheet::merge_page(&mut page, &worksheet::parse(&text)?)?;
    assert!(!review::compression_review_needed(&page.regions[0], "keep"));
    for change in 0..4 {
        let mut changed = page.regions[0].clone();
        match change {
            0 => {
                changed
                    .extra
                    .insert("target_full".into(), json!("متن کامل تازه"));
            }
            1 => changed.target_text.push('!'),
            2 => changed.source_text.push('!'),
            _ => changed.bbox[2] += 1,
        }
        assert!(review::compression_review_needed(&changed, "keep"));
    }
    Ok(())
}

fn prepared_folder_publication(
    root: &Path,
) -> Result<(std::path::PathBuf, journal::Journal), IrError> {
    let doc_path = root.join("comic.json");
    let out = root.join("translated");
    let staged = root.join("translated.revayat-part");
    fs::create_dir(&out)?;
    fs::create_dir(&staged)?;
    let mut doc = ComicDocument::default();
    ir::save_doc(&doc, &doc_path)?;
    ir::write_text(out.join("0001.png"), "old page")?;
    ir::write_text(staged.join("0001.png"), "new page")?;
    doc.stages.insert("export".into(), json!({"files":1}));
    let record = journal::write(
        &doc_path,
        &out,
        BTreeMap::from([("0001.png".into(), ir::sha256_bytes(b"new page"))]),
        json!({"format":"dir","path":out}),
        json!({}),
        &doc,
        BTreeMap::new(),
    )?;
    Ok((doc_path, record))
}

#[test]
fn journal_sidecars_do_not_relax_page_or_private_staging_ownership() -> Result<(), IrError> {
    for unexpected in [
        "translated/unrelated.PNG",
        "translated.revayat-part/unrelated.md",
        "translated.revayat-kept/unrelated.md",
    ] {
        let tmp = tempfile::tempdir()?;
        let (doc_path, mut record) = prepared_folder_publication(tmp.path())?;
        ir::write_text(tmp.path().join(unexpected), "foreign")?;
        assert_eq!(
            journal::promote(&doc_path, &mut record)
                .err()
                .map(|error| error.code()),
            Some("transaction_conflict")
        );
        assert_eq!(fs::read_to_string(tmp.path().join(unexpected))?, "foreign");
        assert_eq!(
            fs::read_to_string(tmp.path().join("translated/0001.png"))?,
            "old page"
        );
    }
    Ok(())
}

#[test]
fn journal_rollback_preserves_later_sidecars_and_foreign_owned_edits() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let (doc_path, mut record) = prepared_folder_publication(tmp.path())?;
    journal::promote(&doc_path, &mut record)?;
    let target = tmp.path().join("translated/0001.png");
    ir::write_text(&target, "outside edit")?;
    assert_eq!(
        journal::rollback(&record).err().map(|error| error.code()),
        Some("transaction_conflict")
    );
    assert_eq!(fs::read_to_string(&target)?, "outside edit");
    ir::write_text(&target, "new page")?;
    let log = tmp.path().join("translated/translation-log.md");
    ir::write_text(&log, "reviewed after publication")?;
    journal::rollback(&record)?;
    journal::finish(&doc_path, &record, false)?;
    assert_eq!(fs::read_to_string(target)?, "old page");
    assert_eq!(fs::read_to_string(log)?, "reviewed after publication");
    Ok(())
}

#[test]
fn journaled_folder_publication_preserves_the_translation_activity_log() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let doc_path = tmp.path().join("comic.json");
    let out = tmp.path().join("translated");
    let staged = tmp.path().join("translated.revayat-part");
    fs::create_dir(&out)?;
    fs::create_dir(&staged)?;
    let mut doc = ComicDocument::default();
    ir::save_doc(&doc, &doc_path)?;
    ir::write_text(out.join("0001.png"), "old page")?;
    ir::write_text(staged.join("0001.png"), "new page")?;
    ir::write_text(out.join("translation-log.md"), "Reviewed page 1\n")?;
    doc.stages.insert("export".into(), json!({"files":1}));
    let mut record = journal::write(
        &doc_path,
        &out,
        BTreeMap::from([("0001.png".into(), ir::sha256_bytes(b"new page"))]),
        json!({"format":"dir","path":out}),
        json!({}),
        &doc,
        BTreeMap::new(),
    )?;
    journal::promote(&doc_path, &mut record)?;
    ir::save_doc(&doc, &doc_path)?;
    journal::finish(&doc_path, &record, true)?;
    assert_eq!(fs::read_to_string(out.join("0001.png"))?, "new page");
    assert_eq!(
        fs::read_to_string(out.join("translation-log.md"))?,
        "Reviewed page 1\n"
    );
    Ok(())
}

fn content_asset(root: &Path, directory: &str, id: &str, color: u8) -> Result<String, IrError> {
    let mut bytes = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(image::RgbImage::from_pixel(4, 5, image::Rgb([color; 3])))
        .write_to(&mut bytes, image::ImageFormat::Png)
        .map_err(|error| IrError::refused("fixture", error.to_string()))?;
    let bytes = bytes.into_inner();
    let name = format!("{directory}/{id}-{}.png", ir::sha256_bytes(&bytes));
    ir::write_bytes(root.join(&name), &bytes)?;
    Ok(name)
}

fn batch_chapter(root: &Path, processed: bool) -> Result<ComicDocument, IrError> {
    let mut doc = ComicDocument::default();
    for index in 0..2 {
        let id = ir::page_id_for(index);
        let image = content_asset(root, "pages", &id, index as u8)?;
        let mut page = ir::new_page(
            &id,
            index,
            &image,
            4,
            5,
            ir::sha256_file(root.join(&image))?,
        );
        if processed {
            let region_id = ir::region_id_for(&id, 1);
            let mut region = ir::new_region(
                &region_id,
                [0., 0., 4., 5.],
                "speech",
                "horizontal",
                "reader",
                1.,
            )?;
            region.mask = Some(content_asset(root, "masks", &region_id, 10)?);
            region.extra.insert(
                "crop".into(),
                json!(content_asset(root, "crops", &region_id, 11)?),
            );
            page.regions.push(region);
            page.cleaned = Some(content_asset(root, "clean", &id, 12)?);
            page.rendered = Some(content_asset(root, "rendered", &id, 13)?);
            for (field, directory, stem, color) in [
                ("mask", "masks", id.clone(), 14),
                ("clean_mask", "clean", format!("{id}-mask"), 15),
                ("authorized_mask", "rendered", format!("{id}-mask"), 16),
                ("overview", "sheets", id.clone(), 17),
            ] {
                page.extra.insert(
                    field.into(),
                    json!(content_asset(root, directory, &stem, color)?),
                );
            }
            page.extra.insert(
                "sheets".into(),
                json!([content_asset(root, "sheets", &format!("{id}-sheet-1"), 18)?]),
            );
        }
        doc.pages.push(page);
    }
    ir::save_doc(&doc, root.join("comic.json"))?;
    Ok(doc)
}

fn page_asset_names(page: &PageRecord) -> Vec<&str> {
    let mut names = vec![page.image.as_str()];
    names.extend(page.cleaned.as_deref());
    names.extend(page.rendered.as_deref());
    for field in ["mask", "clean_mask", "authorized_mask", "overview"] {
        names.extend(page.extra.get(field).and_then(serde_json::Value::as_str));
    }
    names.extend(
        page.extra
            .get("sheets")
            .and_then(serde_json::Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(serde_json::Value::as_str),
    );
    for region in &page.regions {
        names.extend(region.mask.as_deref());
        names.extend(region.extra.get("crop").and_then(serde_json::Value::as_str));
    }
    names
}

#[test]
fn shards_preserve_current_rust_content_addressed_artifacts_and_replay() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let doc = batch_chapter(tmp.path(), true)?;
    batch::plan_shards(tmp.path(), 2, None)?;
    let batch = tmp.path().join("batch");
    for (index, page) in doc.pages.iter().enumerate() {
        let worker = batch.join(format!("shard-{:03}", index + 1));
        for name in page_asset_names(page) {
            assert_eq!(
                fs::read(worker.join(name))?,
                fs::read(tmp.path().join(name))?,
                "missing {name}"
            );
        }
    }
    let worker = batch.join("shard-001");
    let worker_doc = worker.join("comic.json");
    let mut changed = ir::load_doc(&worker_doc)?;
    changed.pages[0].rendered = Some(content_asset(&worker, "rendered", "p0001", 19)?);
    changed.pages[0].extra.insert(
        "authorized_mask".into(),
        json!(content_asset(&worker, "rendered", "p0001-mask", 20)?),
    );
    ir::save_doc(&changed, &worker_doc)?;
    batch::merge_shards(&batch, tmp.path())?;
    let merged = ir::load_doc(tmp.path().join("comic.json"))?;
    assert_eq!(merged.pages[0], changed.pages[0]);
    for name in page_asset_names(&changed.pages[0]) {
        assert_eq!(
            fs::read(worker.join(name))?,
            fs::read(tmp.path().join(name))?
        );
    }
    let committed = fs::read(tmp.path().join("comic.json"))?;
    batch::merge_shards(&batch, tmp.path())?;
    assert_eq!(fs::read(tmp.path().join("comic.json"))?, committed);
    Ok(())
}

#[test]
fn shards_refuse_cross_page_authorized_mask_before_publication() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    batch_chapter(tmp.path(), false)?;
    batch::plan_shards(tmp.path(), 2, None)?;
    let batch = tmp.path().join("batch");
    let worker = batch.join("shard-001");
    let worker_doc = worker.join("comic.json");
    let mut local = ir::load_doc(&worker_doc)?;
    let foreign = content_asset(&worker, "rendered", "p0002-mask", 21)?;
    local.pages[0]
        .extra
        .insert("authorized_mask".into(), json!(foreign));
    ir::save_doc(&local, worker_doc)?;
    let before = fs::read(tmp.path().join("comic.json"))?;
    assert_eq!(
        batch::merge_shards(&batch, tmp.path())
            .err()
            .map(|error| error.code()),
        Some("unsafe_asset")
    );
    assert_eq!(fs::read(tmp.path().join("comic.json"))?, before);
    assert!(!tmp.path().join(foreign).exists());
    Ok(())
}

fn publication_doc(root: &Path) -> Result<ComicDocument, IrError> {
    let mut page = translated_page();
    page.width = 4;
    page.height = 5;
    page.regions[0].bbox = [0, 0, 4, 5];
    page.image = content_asset(root, "pages", "p0001", 255)?;
    page.sha256 = ir::sha256_file(root.join(&page.image))?;
    page.cleaned = Some(content_asset(root, "clean", "p0001", 250)?);
    page.rendered = Some(content_asset(root, "rendered", "p0001", 10)?);
    let clean = ir::sha256_file(root.join(page.cleaned.as_deref().unwrap_or_default()))?;
    let rendered = ir::sha256_file(root.join(page.rendered.as_deref().unwrap_or_default()))?;
    page.extra.insert(
        "cleaning".into(),
        json!({"size":[4,5],"source":page.sha256,"mask":null,"clean":clean}),
    );
    page.extra.insert(
        "delivery".into(),
        json!({"size":[4,5],"final":rendered,"clean":clean,"writable":null}),
    );
    let mut doc = ComicDocument {
        pages: vec![page],
        ..Default::default()
    };
    for stage in ["detect", "masks", "clean", "typeset"] {
        stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
    }
    Ok(doc)
}

#[test]
fn publication_ignores_export_history_unrelated_crops_and_shadowed_mask_alias()
-> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut doc = publication_doc(tmp.path())?;
    doc.stages.insert("export".into(), json!({"old":"package"}));
    doc.stages.insert("crops".into(), json!({"pages":1}));
    doc.stages.insert("mask".into(), json!({"pages":1}));
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    Ok(())
}

#[test]
fn publication_rejects_stale_geometry_and_allows_a_refreshed_pipeline() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut doc = publication_doc(tmp.path())?;
    doc.pages[0].regions[0].bbox[2] -= 1;
    let findings = certify::certify_publication(tmp.path(), &doc)?;
    assert!(
        findings
            .iter()
            .any(|finding| finding.code == "stale-stages" && finding.detail.contains("typeset"))
    );
    for stage in ["masks", "clean", "typeset"] {
        stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
    }
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    Ok(())
}

#[test]
fn publication_requires_current_clean_and_typeset_proof_for_derived_pages() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let original = publication_doc(tmp.path())?;
    for stage in ["clean", "typeset"] {
        let mut doc = original.clone();
        doc.stages.remove(stage);
        assert!(
            certify::certify_publication(tmp.path(), &doc)?
                .iter()
                .any(
                    |finding| finding.code == "unverified-stages" && finding.detail.contains(stage)
                )
        );
        doc.stages.insert(stage.into(), json!({"pages":1}));
        assert!(
            certify::certify_publication(tmp.path(), &doc)?
                .iter()
                .any(
                    |finding| finding.code == "unverified-stages" && finding.detail.contains(stage)
                )
        );
    }
    Ok(())
}

#[test]
fn publication_does_not_require_rendering_stamps_for_untouched_pages() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut doc = batch_chapter(tmp.path(), false)?;
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    let mut derived = publication_doc(tmp.path())?;
    derived.pages.push(doc.pages.remove(1));
    assert!(certify::certify_publication(tmp.path(), &derived)?.is_empty());
    Ok(())
}

#[test]
fn publication_blocks_an_unreviewed_shortening_and_accepts_the_reviewed_pair() -> Result<(), IrError>
{
    let tmp = tempfile::tempdir()?;
    let mut doc = publication_doc(tmp.path())?;
    doc.pages[0].regions[0]
        .extra
        .insert("target_full".into(), json!("متن کامل فارسی"));
    assert!(
        certify::certify_publication(tmp.path(), &doc)?
            .iter()
            .any(|finding| finding.code == "compressed-variant")
    );
    let reply = format!(
        "{}reviewed: compressed-variant\n",
        worksheet::page_worksheet(&doc, &doc.pages[0])
    );
    worksheet::merge_page(&mut doc.pages[0], &worksheet::parse(&reply)?)?;
    stages::stamp_stage(&mut doc, "typeset", Default::default(), None, None)?;
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    Ok(())
}
