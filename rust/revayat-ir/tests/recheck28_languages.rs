use revayat_ir::{ComicDocument, IrError, ir, languages, stages, worksheet};
use serde_json::json;
use std::{fs, path::Path};

fn rendered_document() -> Result<ComicDocument, IrError> {
    let mut doc: ComicDocument = serde_json::from_value(json!({
        "version": 1,
        "meta": {"source_language": "en", "target_language": "fa", "sfx_policy": "translate"},
        "pages": [{
            "id": "p0001", "width": 220, "height": 180, "sha256": "source-digest",
            "regions": [{
                "id": "p0001_r001", "kind": "sfx", "bbox": [50, 50, 50, 40],
                "source_text": "BOOM", "target_text": "بوم", "locked": true
            }]
        }]
    }))?;
    for stage in ["detect", "mask", "masks", "clean", "typeset", "export"] {
        stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
    }
    Ok(doc)
}

#[test]
fn language_guards_preserve_english_locale_aliases_and_halfwidth_kana() {
    for source_language in ["en", "ENG", "English", "en-US", "en_GB", "eng-US"] {
        assert_eq!(languages::guidance(Some(source_language)).profile, "en");
        for source in ["ゴゴゴ…", "うわあああ", "ｺﾞｺﾞｺﾞ…", "爆発ゴゴ", "爆発ｺﾞｺﾞ"]
        {
            assert_eq!(
                ir::foreign_script_guard(Some(source_language), source),
                ir::ForeignScriptGuard::ProtectedJapanese,
                "supported English tags and halfwidth kana must not bypass artwork protection"
            );
        }
        assert_eq!(
            ir::foreign_script_guard(Some(source_language), "爆発"),
            ir::ForeignScriptGuard::ReviewAmbiguousCjk
        );
        for source in ["BOOM", "3.", "ゴゴ BOOM"] {
            assert_eq!(
                ir::foreign_script_guard(Some(source_language), source),
                ir::ForeignScriptGuard::Translatable
            );
        }
    }
    for source_language in [None, Some("auto"), Some("ja-JP"), Some("fr")] {
        assert_eq!(
            ir::foreign_script_guard(source_language, "ゴゴゴ"),
            ir::ForeignScriptGuard::Translatable
        );
    }
}

#[test]
fn target_direction_uses_language_subtags_without_changing_defaults() {
    for target in [
        None,
        Some(""),
        Some("fa"),
        Some("fa-IR"),
        Some("fa_IR"),
        Some("ar-EG"),
        Some("ur-PK"),
        Some("he-IL"),
    ] {
        assert!(
            ir::is_rtl_language(target),
            "regional RTL language tags retain RTL layout"
        );
    }
    for target in ["en", "en-US", "ja-JP", "fr", "unknown"] {
        assert!(!ir::is_rtl_language(Some(target)));
    }
}

#[test]
fn source_context_invalidates_all_rendering_consumers_but_not_detection() -> Result<(), IrError> {
    for source_text_changes in [false, true] {
        let mut doc = rendered_document()?;
        if source_text_changes {
            doc.pages[0].regions[0].source_text = "ゴゴゴ".into();
        } else {
            doc.meta.insert("source_language".into(), json!("ja"));
        }
        for stage in ["mask", "masks", "clean", "typeset", "export"] {
            assert_eq!(
                stages::stale_pages(&doc, stage)?,
                ["p0001"],
                "rendering must observe changed source protection inputs"
            );
        }
        assert!(stages::stale_pages(&doc, "detect")?.is_empty());
        for stage in ["mask", "masks", "clean", "typeset", "export"] {
            stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
            assert!(stages::stale_pages(&doc, stage)?.is_empty());
        }
    }
    Ok(())
}

#[test]
fn target_direction_freshness_does_not_overinvalidate_masks_or_cleaning() -> Result<(), IrError> {
    let mut doc = rendered_document()?;
    doc.meta.insert("target_language".into(), json!("en"));
    for stage in ["typeset", "export"] {
        assert_eq!(stages::stale_pages(&doc, stage)?, ["p0001"]);
    }
    for stage in ["detect", "mask", "masks", "clean"] {
        assert!(stages::stale_pages(&doc, stage)?.is_empty());
    }
    let mut unchanged = rendered_document()?;
    unchanged
        .meta
        .insert("editor_note".into(), json!("Unrelated note"));
    unchanged.glossary.insert(
        "entries".into(),
        json!({"Alice": {"target": "آلیس", "locked": true}}),
    );
    for stage in ["detect", "mask", "masks", "clean", "typeset", "export"] {
        assert!(stages::stale_pages(&unchanged, stage)?.is_empty());
    }
    Ok(())
}

fn worksheet_reply(path: &Path, from: &str, replacement: &str) -> Result<(), IrError> {
    let drafts = worksheet::build_document(path, None, None, true)?;
    let draft = fs::read_to_string(&drafts[0])?;
    assert!(
        draft.contains(from),
        "expected target field in worksheet draft"
    );
    ir::write_text(
        path.parent().unwrap().join("worksheets/p0001.done.txt"),
        &draft.replace(from, replacement),
    )
}

#[test]
fn worksheet_rejects_protected_targets_under_keep_policy_without_partial_writes()
-> Result<(), IrError> {
    for force in [false, true] {
        let tmp = tempfile::tempdir()?;
        let path = tmp.path().join("comic.json");
        let mut doc = rendered_document()?;
        doc.meta.insert("sfx_policy".into(), json!("keep"));
        doc.pages[0].regions[0].source_text = "ゴゴゴ".into();
        doc.pages[0].regions[0].target_text.clear();
        ir::save_doc(&doc, &path)?;
        worksheet_reply(&path, "fa:\n", "fa: غرش\n")?;
        let before = fs::read(&path)?;
        let reply = tmp.path().join("worksheets/p0001.done.txt");
        let reply_before = fs::read(&reply)?;
        assert_eq!(
            worksheet::merge_document(&path, None, None, force)
                .unwrap_err()
                .code(),
            "protected_japanese_artwork"
        );
        assert_eq!(fs::read(&path)?, before);
        assert_eq!(fs::read(&reply)?, reply_before);

        worksheet_reply(&path, "fa:\n", "fa:\nkeep: yes\n")?;
        worksheet::merge_document(&path, None, None, false)?;
        assert!(ir::load_doc(&path)?.pages[0].regions[0].keep);
        assert!(worksheet::merge_document(&path, None, None, false)?.is_empty());
    }
    Ok(())
}

#[test]
fn worksheet_replay_rechecks_changed_source_language_and_allows_keep_repair() -> Result<(), IrError>
{
    let tmp = tempfile::tempdir()?;
    let path = tmp.path().join("comic.json");
    let mut doc = rendered_document()?;
    doc.meta.insert("source_language".into(), json!("ja"));
    doc.pages[0].regions[0].source_text = "ゴゴゴ".into();
    doc.pages[0].regions[0].target_text.clear();
    ir::save_doc(&doc, &path)?;
    worksheet_reply(&path, "fa:\n", "fa: غرش\n")?;
    worksheet::merge_document(&path, None, None, false)?;
    let mut doc = ir::load_doc(&path)?;
    doc.meta.insert("source_language".into(), json!("en-US"));
    ir::save_doc(&doc, &path)?;
    let before = fs::read(&path)?;
    assert_eq!(
        worksheet::merge_document(&path, None, None, false)
            .unwrap_err()
            .code(),
        "protected_japanese_artwork"
    );
    assert_eq!(fs::read(&path)?, before);
    worksheet_reply(&path, "fa: غرش\n", "fa:\nkeep: yes\n")?;
    worksheet::merge_document(&path, None, None, false)?;
    assert!(ir::load_doc(&path)?.pages[0].regions[0].keep);
    Ok(())
}

#[test]
fn worksheet_replay_requires_explicit_keep_after_translation_policy_changes() -> Result<(), IrError>
{
    let tmp = tempfile::tempdir()?;
    let path = tmp.path().join("comic.json");
    let mut doc = rendered_document()?;
    doc.meta.insert("sfx_policy".into(), json!("keep"));
    doc.pages[0].regions[0].source_text = "ゴゴゴ".into();
    doc.pages[0].regions[0].target_text.clear();
    ir::save_doc(&doc, &path)?;
    worksheet_reply(&path, "fa:\n", "fa:\n")?;
    worksheet::merge_document(&path, None, None, false)?;
    let mut doc = ir::load_doc(&path)?;
    doc.meta.insert("sfx_policy".into(), json!("translate"));
    ir::save_doc(&doc, &path)?;
    let before = fs::read(&path)?;
    assert_eq!(
        worksheet::merge_document(&path, None, None, false)
            .unwrap_err()
            .code(),
        "protected_japanese_artwork"
    );
    assert_eq!(fs::read(&path)?, before);
    worksheet_reply(&path, "fa:\n", "fa:\nkeep: yes\n")?;
    worksheet::merge_document(&path, None, None, false)?;
    assert!(ir::load_doc(&path)?.pages[0].regions[0].keep);
    Ok(())
}
