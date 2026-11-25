use std::{cell::Cell, fs};

use image::{Rgb, RgbImage};
use revayat_io::{
    ExportOptions, ImportOptions, IoError, export::export_document_with_preflight, import_input,
};

#[test]
fn application_preflight_holds_the_workspace_claim_and_refuses_before_publication()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("source.png");
    RgbImage::from_pixel(20, 20, Rgb([255; 3])).save(&source)?;
    let work = temp.path().join("work");
    import_input(&source, &work, &ImportOptions::default())?;
    let doc = work.join("comic.json");
    let before = fs::read(&doc)?;
    let output = temp.path().join("previous.cbz");
    fs::write(&output, b"previous approved output")?;
    let called = Cell::new(false);
    let refusal = export_document_with_preflight(
        &doc,
        &output,
        None,
        &ExportOptions::default(),
        |locked_path| {
            called.set(true);
            assert_eq!(locked_path, fs::canonicalize(&doc).unwrap());
            assert!(revayat_ir::workspace::workspace_lock(&work, "competing edit").is_err());
            Err(IoError::Invalid("synthetic QA refusal".into()))
        },
    );
    assert!(called.get());
    assert!(
        refusal
            .unwrap_err()
            .to_string()
            .contains("synthetic QA refusal")
    );
    assert_eq!(fs::read(&doc)?, before);
    assert_eq!(fs::read(&output)?, b"previous approved output");
    let options = ExportOptions {
        draft: true,
        ..ExportOptions::default()
    };
    let report = export_document_with_preflight(&doc, &output, None, &options, |_| {
        panic!("draft must explicitly skip the application gate")
    })?;
    assert!(report.draft);
    assert!(fs::read(&output)?.starts_with(b"PK"));
    Ok(())
}
