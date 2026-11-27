#![forbid(unsafe_code)]

use std::{fs, io::Read, path::Path};

use image::{GrayImage, Luma, Rgb, RgbImage};
use revayat_io::{
    ExportOptions, ImportOptions, export_document, export_review_docx, import_input,
    package::check_package,
};
use revayat_ir::{ComicDocument, certify, ir, stages};
use serde_json::{Value, json};
use zip::ZipArchive;

type Result<T = ()> = std::result::Result<T, Box<dyn std::error::Error>>;

fn chapter(root: &Path, decision: Value) -> Result<ComicDocument> {
    let source = root.join("source.png");
    RgbImage::from_pixel(20, 20, Rgb([255; 3])).save(&source)?;
    let work = root.join("work");
    import_input(&source, &work, &ImportOptions::default())?;
    let mut doc = ir::load_doc(work.join("comic.json"))?;
    let mut region = json!({
        "id": "p0001_r001", "bbox": [4, 4, 12, 12], "kind": "speech"
    });
    region
        .as_object_mut()
        .unwrap()
        .extend(decision.as_object().unwrap().clone());
    doc.pages[0].regions.push(serde_json::from_value(region)?);
    Ok(doc)
}

fn derived(root: &Path, doc: &mut ComicDocument, render: bool) -> Result<Vec<u8>> {
    let work = root.join("work");
    let page = &mut doc.pages[0];
    let clean = "cleaned.png";
    RgbImage::from_pixel(20, 20, Rgb([32, 64, 96])).save(work.join(clean))?;
    page.cleaned = Some(clean.into());
    let clean_hash = ir::sha256_file(work.join(clean))?;
    let mask = "clean-mask.png";
    GrayImage::from_pixel(20, 20, Luma([255])).save(work.join(mask))?;
    let mask_hash = ir::sha256_file(work.join(mask))?;
    page.extra.insert("clean_mask".into(), json!(mask));
    page.extra.insert(
        "cleaning".into(),
        json!({
            "size": [20, 20], "source": page.sha256, "mask": null, "clean_mask": mask_hash,
            "clean": clean_hash
        }),
    );
    let selected = if render {
        let rendered = "rendered.png";
        RgbImage::from_pixel(20, 20, Rgb([96, 64, 32])).save(work.join(rendered))?;
        page.rendered = Some(rendered.into());
        page.extra.insert("authorized_mask".into(), json!(mask));
        page.extra.insert(
            "delivery".into(),
            json!({
                "size": [20, 20], "final": ir::sha256_file(work.join(rendered))?,
                "clean": clean_hash, "writable": null, "authorized_mask": mask_hash
            }),
        );
        rendered
    } else {
        clean
    };
    stages::stamp_stage(doc, "clean", Default::default(), None, None)?;
    if render {
        stages::stamp_stage(doc, "typeset", Default::default(), None, None)?;
    }
    Ok(fs::read(work.join(selected))?)
}

fn published_bytes(root: &Path, doc: &Value, draft: bool) -> Result<(Vec<u8>, Vec<String>)> {
    let doc_path = root.join("work/comic.json");
    ir::write_bytes(&doc_path, &ir::json_bytes(doc)?)?;
    if !draft {
        let typed = ir::load_doc(&doc_path)?;
        assert_eq!(
            certify::certify_publication(&root.join("work"), &typed)?,
            []
        );
    }
    let out = root.join("chapter.cbz");
    let report = export_document(
        &doc_path,
        &out,
        None,
        &ExportOptions {
            draft,
            ..Default::default()
        },
    )?;
    let checked = check_package(&out, &doc_path)?;
    assert!(checked.ok, "{checked:?}");
    let mut archive = ZipArchive::new(fs::File::open(&out)?)?;
    let mut bytes = Vec::new();
    archive
        .by_name(&report.manifest[0].name)?
        .read_to_end(&mut bytes)?;
    Ok((bytes, report.unrendered_pages))
}

fn original_decision(decision: Value) -> Result {
    for draft in [false, true] {
        let temp = tempfile::tempdir()?;
        let doc = chapter(temp.path(), decision.clone())?;
        let original = fs::read(temp.path().join("work").join(&doc.pages[0].image))?;
        let (bytes, unrendered) = published_bytes(temp.path(), &serde_json::to_value(doc)?, draft)?;
        assert_eq!(bytes, original);
        assert!(unrendered.is_empty());
    }
    Ok(())
}

#[test]
fn state_only_kept_is_publishable_without_translation_or_edits() -> Result {
    for state in ["kept", "kept_by_policy"] {
        original_decision(json!({"state": state}))?;
    }
    Ok(())
}

#[test]
fn state_only_dropped_is_publishable_without_translation_or_edits() -> Result {
    for state in ["dropped", "dropped_false_detection"] {
        original_decision(json!({"state": state}))?;
    }
    Ok(())
}

#[test]
fn canonical_keep_and_drop_remain_noop_publication_decisions() -> Result {
    for decision in [json!({"keep": true}), json!({"dropped": true})] {
        original_decision(decision)?;
    }
    Ok(())
}

#[test]
fn completed_erase_states_publish_cleaned_pixels_in_both_modes() -> Result {
    for decision in [json!({"erase": true}), json!({"state": "erased"})] {
        for draft in [false, true] {
            let temp = tempfile::tempdir()?;
            let mut doc = chapter(temp.path(), decision.clone())?;
            doc.pages[0].regions[0].fill = "solid".into();
            let expected = derived(temp.path(), &mut doc, false)?;
            let (bytes, unrendered) =
                published_bytes(temp.path(), &serde_json::to_value(doc)?, draft)?;
            assert_eq!(bytes, expected);
            assert!(unrendered.is_empty());
        }
    }
    Ok(())
}

#[test]
fn incomplete_erase_and_translation_refuse_publication_without_mutation() -> Result {
    for decision in [
        json!({"erase": true}),
        json!({"state": "erased"}),
        json!({}),
    ] {
        let temp = tempfile::tempdir()?;
        let doc = chapter(temp.path(), decision)?;
        let doc_path = temp.path().join("work/comic.json");
        ir::save_doc(&doc, &doc_path)?;
        let before = fs::read(&doc_path)?;
        let out = temp.path().join("chapter.cbz");
        fs::write(&out, b"approved edition")?;
        assert!(export_document(&doc_path, &out, None, &ExportOptions::default()).is_err());
        assert_eq!(fs::read(&doc_path)?, before);
        assert_eq!(fs::read(&out)?, b"approved edition");
        let (_, unrendered) = published_bytes(temp.path(), &serde_json::to_value(doc)?, true)?;
        assert_eq!(unrendered, ["p0001"]);
    }
    Ok(())
}

#[test]
fn cleaned_path_aliases_publish_the_certified_artifact() -> Result {
    for alias in ["clean", "cleaned", "clean_path"] {
        for draft in [false, true] {
            let temp = tempfile::tempdir()?;
            let mut doc = chapter(temp.path(), json!({"erase": true, "fill": "solid"}))?;
            let expected = derived(temp.path(), &mut doc, false)?;
            let mut raw = serde_json::to_value(doc)?;
            let page = raw["pages"][0].as_object_mut().unwrap();
            let path = page.remove("clean").unwrap();
            page.insert(alias.into(), path);
            let (bytes, unrendered) = published_bytes(temp.path(), &raw, draft)?;
            assert_eq!(bytes, expected, "{alias}, draft={draft}");
            assert!(unrendered.is_empty());
        }
    }
    Ok(())
}

#[test]
fn rendered_path_and_persian_aliases_publish_the_certified_artifact() -> Result {
    for alias in ["final", "rendered", "final_path"] {
        for target in ["target_text", "fa_text"] {
            for draft in [false, true] {
                let temp = tempfile::tempdir()?;
                let mut doc = chapter(temp.path(), json!({"target_text": "سلام!"}))?;
                let expected = derived(temp.path(), &mut doc, true)?;
                let mut raw = serde_json::to_value(doc)?;
                let page = raw["pages"][0].as_object_mut().unwrap();
                let path = page.remove("final").unwrap();
                page.insert(alias.into(), path);
                let region = page["regions"][0].as_object_mut().unwrap();
                let text = region.remove("target_text").unwrap();
                region.insert(target.into(), text);
                let (bytes, unrendered) = published_bytes(temp.path(), &raw, draft)?;
                assert_eq!(bytes, expected, "{alias}, {target}, draft={draft}");
                assert!(unrendered.is_empty());
            }
        }
    }
    Ok(())
}

#[test]
fn draft_reports_missing_required_files_when_falling_back() -> Result {
    for render in [false, true] {
        let temp = tempfile::tempdir()?;
        let decision = if render {
            json!({"target_text": "سلام!"})
        } else {
            json!({"erase": true, "fill": "solid"})
        };
        let mut doc = chapter(temp.path(), decision)?;
        derived(temp.path(), &mut doc, render)?;
        let page = &doc.pages[0];
        let (missing, fallback) = if render {
            (
                page.rendered.as_ref().unwrap(),
                page.cleaned.as_ref().unwrap(),
            )
        } else {
            (page.cleaned.as_ref().unwrap(), &page.image)
        };
        let expected = fs::read(temp.path().join("work").join(fallback))?;
        fs::remove_file(temp.path().join("work").join(missing))?;
        let (bytes, unrendered) = published_bytes(temp.path(), &serde_json::to_value(doc)?, true)?;
        assert_eq!(bytes, expected);
        assert_eq!(unrendered, ["p0001"]);
    }
    Ok(())
}

fn review_xml(region: Value) -> Result<String> {
    let temp = tempfile::tempdir()?;
    let doc = json!({"version": 1, "meta": {}, "pages": [{
        "id": "p0001", "width": 20, "height": 20, "regions": [region]
    }]});
    let out = temp.path().join("review.docx");
    export_review_docx(&doc, &out)?;
    let mut archive = ZipArchive::new(fs::File::open(&out)?)?;
    let mut xml = String::new();
    archive
        .by_name("word/document.xml")?
        .read_to_string(&mut xml)?;
    Ok(xml)
}

#[test]
fn review_companion_supports_every_canonical_region_kind() -> Result {
    for kind in ir::REGION_KINDS {
        let xml = review_xml(json!({
            "id": "p0001_r001", "kind": kind, "erase": true, "fill": "solid"
        }))?;
        assert!(xml.contains(&format!("Kind: {kind}; state: erased")));
    }
    Ok(())
}

#[test]
fn review_companion_normalizes_decisions_and_text_aliases() -> Result {
    for (state, expected) in [
        ("kept", "kept_by_policy"),
        ("kept_by_policy", "kept_by_policy"),
        ("dropped", "dropped_false_detection"),
        ("dropped_false_detection", "dropped_false_detection"),
        ("erased", "erased"),
    ] {
        let xml = review_xml(json!({
            "id": "p0001_r001", "kind": "speech", "state": state, "fill": "solid"
        }))?;
        assert!(
            xml.contains(&format!("state: {expected}")),
            "{state}: {xml}"
        );
    }
    for (source, target) in [
        ("source_text", "target_text"),
        ("ocr_text", "fa_text"),
        ("source", "target"),
    ] {
        let xml = review_xml(json!({
            "id": "p0001_r001", "kind": "speech", source: "Hello", target: "سلام!"
        }))?;
        assert!(
            xml.contains("Hello") && xml.contains("سلام!"),
            "{source}/{target}: {xml}"
        );
        assert!(xml.contains("state: translated"));
    }
    Ok(())
}

#[test]
fn review_companion_rejects_conflicting_actions_without_replacing_output() -> Result {
    let temp = tempfile::tempdir()?;
    let out = temp.path().join("review.docx");
    fs::write(&out, b"approved review")?;
    let doc = json!({"version": 1, "meta": {}, "pages": [{
        "id": "p0001", "width": 20, "height": 20, "regions": [{
            "id": "p0001_r001", "kind": "speech", "state": "kept", "erase": true
        }]
    }]});
    assert!(export_review_docx(&doc, &out).is_err());
    assert_eq!(fs::read(&out)?, b"approved review");
    Ok(())
}
