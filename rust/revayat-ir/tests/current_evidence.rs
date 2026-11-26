use revayat_ir::{ComicDocument, IrError, PageRecord, RegionRecord, certify, ir, stages};
use serde_json::{Value, json};
use std::{fs, path::Path};

fn asset(root: &Path, folder: &str, id: &str, bytes: &[u8]) -> Result<String, IrError> {
    fs::create_dir_all(root.join(folder))?;
    let name = format!("{folder}/{id}-{}.png", ir::sha256_bytes(bytes));
    fs::write(root.join(&name), bytes)?;
    Ok(name)
}

fn publication_doc(root: &Path) -> Result<ComicDocument, IrError> {
    let image = asset(root, "pages", "p0001", b"original")?;
    let cleaned = asset(root, "clean", "p0001", b"cleaned")?;
    let rendered = asset(root, "rendered", "p0001", b"rendered")?;
    let clean_mask = asset(root, "clean", "p0001-mask", b"clean proof")?;
    let authorized_mask = asset(root, "rendered", "p0001-mask", b"typeset proof")?;
    let mut page = PageRecord {
        id: "p0001".into(),
        width: 100,
        height: 100,
        sha256: ir::sha256_file(root.join(&image))?,
        image,
        cleaned: Some(cleaned.clone()),
        rendered: Some(rendered.clone()),
        panels: vec![json!({"id":"p0001p001", "bbox":[0,0,100,100]})],
        regions: vec![RegionRecord {
            id: "p0001_r001".into(),
            bbox: [10, 10, 30, 30],
            kind: "speech".into(),
            panel: Some(json!("p0001p001")),
            source_text: "Original words".into(),
            target_text: "متن فارسی".into(),
            ..Default::default()
        }],
        ..Default::default()
    };
    page.extra.insert("clean_mask".into(), json!(clean_mask));
    page.extra
        .insert("authorized_mask".into(), json!(authorized_mask));
    page.extra.insert(
        "cleaning".into(),
        json!({
            "size":[100,100], "source":page.sha256, "mask":null,
            "clean":ir::sha256_file(root.join(&cleaned))?,
            "clean_mask":ir::sha256_file(root.join(clean_mask))?,
        }),
    );
    page.extra.insert(
        "delivery".into(),
        json!({
            "size":[100,100], "final":ir::sha256_file(root.join(rendered))?,
            "clean":ir::sha256_file(root.join(cleaned))?, "writable":null,
            "authorized_mask":ir::sha256_file(root.join(authorized_mask))?,
        }),
    );
    let mut doc = ComicDocument {
        pages: vec![page],
        ..Default::default()
    };
    for stage in ["detect", "masks", "clean", "typeset", "export"] {
        stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
    }
    Ok(doc)
}

fn proof_findings(
    root: &Path,
    page: &PageRecord,
    proof: &str,
) -> Result<Vec<certify::Finding>, IrError> {
    if proof == "clean_mask" {
        certify::certify_cleaning(root, page)
    } else {
        certify::certify_delivery(root, page)
    }
}

fn assert_proof_refused(root: &Path, page: &PageRecord, proof: &str) -> Result<(), IrError> {
    let findings = proof_findings(root, page, proof)?;
    assert!(
        findings.iter().any(|finding| {
            finding.code == "delivery-mismatch" && finding.detail.contains(proof)
        }),
        "{proof} was accepted without its committed proof: {findings:?}",
    );
    Ok(())
}

#[test]
fn current_proof_masks_certify_when_their_committed_bytes_match() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let doc = publication_doc(tmp.path())?;
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    Ok(())
}

#[test]
fn changed_clean_mask_bytes_cannot_redefine_the_cleaning_proof() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let doc = publication_doc(tmp.path())?;
    let page = &doc.pages[0];
    fs::write(
        tmp.path().join(page.extra["clean_mask"].as_str().unwrap()),
        b"modified proof",
    )?;
    assert_proof_refused(tmp.path(), page, "clean_mask")
}

#[test]
fn changed_authorized_mask_bytes_cannot_redefine_the_delivery_proof() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let doc = publication_doc(tmp.path())?;
    let page = &doc.pages[0];
    fs::write(
        tmp.path()
            .join(page.extra["authorized_mask"].as_str().unwrap()),
        b"modified proof",
    )?;
    assert_proof_refused(tmp.path(), page, "authorized_mask")
}

#[test]
fn replacement_proof_paths_must_still_match_the_committed_bytes() -> Result<(), IrError> {
    for proof in ["clean_mask", "authorized_mask"] {
        let tmp = tempfile::tempdir()?;
        let mut doc = publication_doc(tmp.path())?;
        let name = asset(
            tmp.path(),
            "masks",
            "p0001-replacement",
            b"replacement proof",
        )?;
        doc.pages[0].extra.insert(proof.into(), json!(name));
        assert_proof_refused(tmp.path(), &doc.pages[0], proof)?;
    }
    Ok(())
}

#[test]
fn removed_or_malformed_current_proof_paths_require_rebuilding() -> Result<(), IrError> {
    for proof in ["clean_mask", "authorized_mask"] {
        for invalid in [None, Some(Value::Null), Some(json!(false)), Some(json!(""))] {
            let tmp = tempfile::tempdir()?;
            let mut doc = publication_doc(tmp.path())?;
            let page = &mut doc.pages[0];
            page.extra.remove(proof);
            if let Some(invalid) = invalid {
                page.extra.insert(proof.into(), invalid);
            }
            assert_proof_refused(tmp.path(), page, proof)?;
        }
    }
    Ok(())
}

#[test]
fn current_proof_paths_without_evidence_require_rebuilding() -> Result<(), IrError> {
    for (proof, record) in [("clean_mask", "cleaning"), ("authorized_mask", "delivery")] {
        let tmp = tempfile::tempdir()?;
        let mut doc = publication_doc(tmp.path())?;
        doc.pages[0]
            .extra
            .get_mut(record)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .remove(proof);
        assert_proof_refused(tmp.path(), &doc.pages[0], proof)?;
    }
    Ok(())
}

#[test]
fn null_current_proof_is_not_an_approved_empty_mask() -> Result<(), IrError> {
    for (proof, record) in [("clean_mask", "cleaning"), ("authorized_mask", "delivery")] {
        let tmp = tempfile::tempdir()?;
        let mut doc = publication_doc(tmp.path())?;
        doc.pages[0].extra.remove(proof);
        doc.pages[0].extra[record][proof] = Value::Null;
        assert_proof_refused(tmp.path(), &doc.pages[0], proof)?;
    }
    Ok(())
}

#[test]
fn legacy_evidence_and_untouched_pages_remain_compatible() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut doc = publication_doc(tmp.path())?;
    for (proof, record) in [("clean_mask", "cleaning"), ("authorized_mask", "delivery")] {
        doc.pages[0].extra.remove(proof);
        doc.pages[0]
            .extra
            .get_mut(record)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .remove(proof);
    }
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    let page = &mut doc.pages[0];
    page.cleaned = None;
    page.rendered = None;
    page.regions.clear();
    page.extra.clear();
    doc.stages.clear();
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    Ok(())
}

#[test]
fn panel_geometry_changes_invalidate_rendering_and_rebuilding_recovers() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut doc = publication_doc(tmp.path())?;
    doc.pages[0].panels[0]["bbox"] = json!([5, 5, 90, 90]);
    for stage in ["masks", "clean", "typeset", "export"] {
        assert_eq!(
            stages::stale_pages(&doc, stage)?,
            ["p0001"],
            "{stage} ignored changed panels"
        );
    }
    assert!(stages::stale_pages(&doc, "detect")?.is_empty());
    assert!(
        certify::certify_publication(tmp.path(), &doc)?
            .iter()
            .any(|finding| {
                finding.code == "stale-stages" && finding.detail.contains("typeset")
            })
    );
    for stage in ["masks", "clean", "typeset"] {
        stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
    }
    assert!(certify::certify_publication(tmp.path(), &doc)?.is_empty());
    Ok(())
}

#[test]
fn adding_or_removing_panels_also_invalidates_rendering() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut doc = publication_doc(tmp.path())?;
    doc.pages[0].panels.clear();
    assert_eq!(stages::stale_pages(&doc, "masks")?, ["p0001"]);
    for stage in ["masks", "clean", "typeset"] {
        stages::stamp_stage(&mut doc, stage, Default::default(), None, None)?;
    }
    doc.pages[0].panels.push(json!([0, 0, 100, 100]));
    assert_eq!(stages::stale_pages(&doc, "masks")?, ["p0001"]);
    Ok(())
}

#[test]
fn panel_metadata_and_legacy_shape_do_not_change_render_geometry() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    let mut doc = publication_doc(tmp.path())?;
    let before = stages::facet_revision(&doc.pages[0], "render")?;
    doc.pages[0].panels[0]["note"] = json!("Reader annotation");
    assert_eq!(stages::facet_revision(&doc.pages[0], "render")?, before);
    doc.pages[0].panels[0] = json!([0, 0, 100, 100]);
    assert_eq!(stages::facet_revision(&doc.pages[0], "render")?, before);
    Ok(())
}

#[test]
fn content_addressed_assets_refuse_modified_bytes_and_accept_rebuilt_bytes() -> Result<(), IrError>
{
    let tmp = tempfile::tempdir()?;
    let bytes = b"committed local region mask";
    let name = asset(tmp.path(), "masks", "p0001_r001", bytes)?;
    let path = tmp.path().join(name);
    certify::verify_content_addressed(&path)?;
    fs::write(&path, b"modified local region mask")?;
    let error = certify::verify_content_addressed(&path).unwrap_err();
    assert_eq!(error.code(), "asset_digest_mismatch");
    assert!(error.to_string().contains("re-run"));
    fs::write(&path, bytes)?;
    certify::verify_content_addressed(&path)?;
    Ok(())
}

#[test]
fn content_addressed_guard_preserves_unhashed_legacy_files() -> Result<(), IrError> {
    let tmp = tempfile::tempdir()?;
    for name in [
        "p0001_r001.png".to_owned(),
        "p0001-mask-deadbeef.png".to_owned(),
        format!("p0001-mask-{}.png", "g".repeat(64)),
    ] {
        let path = tmp.path().join(name);
        fs::write(&path, b"legacy pixels")?;
        certify::verify_content_addressed(&path)?;
    }
    let bytes = b"uppercase digest";
    let path = tmp.path().join(format!(
        "p0001-{}.png",
        ir::sha256_bytes(bytes).to_uppercase()
    ));
    fs::write(&path, bytes)?;
    certify::verify_content_addressed(&path)?;
    Ok(())
}
