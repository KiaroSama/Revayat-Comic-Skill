use std::{
    collections::BTreeMap,
    fs::{self, File},
    path::{Path, PathBuf},
};

use revayat_ir::{
    PageRecord, certify, ir, journal,
    regions::{self, Artifact, RegionState},
    stages, workspace,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::{
    IoError,
    fsutil::{canonical_destination, file_digest, parent, read_file, workspace_asset},
    geometry::pdf_points,
    invalid,
    writers::{export_cbz, export_directory, export_pdf},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ExportFormat {
    Cbz,
    Pdf,
    Dir,
}

impl ExportFormat {
    pub fn from_destination(out: &Path) -> Self {
        match out
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str()
        {
            "cbz" | "zip" => Self::Cbz,
            "pdf" => Self::Pdf,
            _ => Self::Dir,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ExportOptions {
    pub title: String,
    pub chapter: String,
    pub target_language: String,
    pub reading_direction: String,
    pub tool: String,
    pub quality: u8,
    pub draft: bool,
}

impl Default for ExportOptions {
    fn default() -> Self {
        Self {
            title: String::new(),
            chapter: String::new(),
            target_language: "fa".into(),
            reading_direction: "rtl".into(),
            tool: "revayat-comic".into(),
            quality: 0,
            draft: false,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ExportPage {
    pub source: PathBuf,
    pub id: Option<String>,
    pub paper: Option<[f64; 2]>,
    pub expected_size: Option<[u32; 2]>,
}

impl ExportPage {
    pub fn new(source: impl Into<PathBuf>) -> Self {
        Self {
            source: source.into(),
            id: None,
            paper: None,
            expected_size: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ManifestPage {
    pub page: String,
    pub name: String,
    pub sha256: String,
    pub pixels: String,
    pub appearance: String,
    pub width: u32,
    pub height: u32,
    pub lossy: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pdf_points: Option<[f64; 2]>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportReport {
    pub format: ExportFormat,
    pub path: PathBuf,
    pub pages: usize,
    pub draft: bool,
    pub manifest: Vec<ManifestPage>,
    pub package_sha256: Option<String>,
    #[serde(default)]
    pub unrendered_pages: Vec<String>,
}

fn read_page(
    root: &Path,
    page: &PageRecord,
    policy: &str,
    draft: bool,
) -> Result<(ExportPage, bool), IoError> {
    let id = &page.id;
    if id.is_empty() {
        return Err(invalid("Page is missing an ID"));
    }
    if page.image.is_empty() {
        return Err(invalid("Page is missing its immutable source"));
    }
    let original = workspace_asset(root, Path::new(&page.image))?;
    if file_digest(&original)? != page.sha256 {
        return Err(invalid(format!("Immutable source changed for {id}")));
    }
    let mut reviewed = true;
    for region in &page.regions {
        reviewed &= regions::region_state(region, policy)? != RegionState::Pending;
    }
    let mut source = original;
    let mut shipped = Artifact::Original;
    for (artifact, path) in [
        (Artifact::Rendered, page.rendered.as_deref()),
        (Artifact::Cleaned, page.cleaned.as_deref()),
    ]
    .into_iter()
    .filter_map(|(artifact, path)| path.map(|path| (artifact, path)))
    {
        match workspace_asset(root, Path::new(path)) {
            Ok(path) => {
                source = path;
                shipped = artifact;
                break;
            }
            Err(IoError::File(e)) if draft && e.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
    }
    let pending = shipped < regions::required_artifact(page, policy) || !reviewed;
    if pending && !draft {
        return Err(invalid(format!(
            "{id} does not pass publication preflight; finish its edits or export a draft"
        )));
    }
    if page.width == 0 || page.height == 0 {
        return Err(invalid("Invalid page pixel dimensions"));
    }
    let paper = page
        .extra
        .get("pdf_points")
        .map(|points| pdf_points(&json!({"pdf_points": points})))
        .transpose()?;
    Ok((
        ExportPage {
            source,
            id: Some(id.into()),
            paper,
            expected_size: Some([page.width, page.height]),
        },
        pending,
    ))
}

fn refuse_collisions(
    doc: &Value,
    root: &Path,
    doc_path: &Path,
    out: &Path,
    format: ExportFormat,
) -> Result<(), IoError> {
    let target = canonical_destination(out)?;
    let root = fs::canonicalize(root)?;
    let work_folders = [
        "pages",
        "clean",
        "cleaned",
        "rendered",
        "final",
        "masks",
        "sheets",
        "crops",
        "worksheets",
    ];
    let built_in_collision = target == root
        || work_folders
            .into_iter()
            .any(|dir| target.starts_with(root.join(dir)));
    let dependencies = std::iter::once(fs::canonicalize(doc_path)?).chain(
        doc["source"]["path"]
            .as_str()
            .and_then(|source| canonical_destination(Path::new(source)).ok()),
    );
    if built_in_collision
        || dependencies.into_iter().any(|source| {
            source == target
                || (format == ExportFormat::Dir && source.starts_with(&target))
                || (source.is_dir() && target.starts_with(&source))
        })
    {
        return Err(invalid("Export overlaps the source or workspace assets"));
    }
    Ok(())
}

pub fn export_document(
    doc_path: &Path,
    out: &Path,
    format: Option<ExportFormat>,
    options: &ExportOptions,
) -> Result<ExportReport, IoError> {
    export_document_with_preflight(doc_path, out, format, options, |_| Ok(()))
}

/// Run application QA under the same workspace claim as publication.
///
/// The compatibility `export_document` API retains artifact-level certification.
/// Applications with image/linguistic QA should supply it here; drafts explicitly
/// skip application QA and are labelled as drafts by the existing writers.
pub fn export_document_with_preflight(
    doc_path: &Path,
    out: &Path,
    format: Option<ExportFormat>,
    options: &ExportOptions,
    preflight: impl FnOnce(&Path) -> Result<(), IoError>,
) -> Result<ExportReport, IoError> {
    let doc_path = fs::canonicalize(doc_path)?;
    let doc_path = doc_path.as_path();
    let root = parent(doc_path);
    let _lock = workspace::workspace_lock(root, "export")?;
    recover_pending_claimed(doc_path)?;
    if !options.draft {
        preflight(doc_path)?;
    }
    let raw = read_file(doc_path, 64 << 20)?;
    let mut typed = ir::decode_doc(&raw)?;
    let doc: Value = serde_json::from_slice(&raw)?;
    let format = format.unwrap_or_else(|| ExportFormat::from_destination(out));
    if out
        .symlink_metadata()
        .is_ok_and(|meta| meta.file_type().is_symlink())
    {
        return Err(invalid("Refusing to overwrite an output symlink"));
    }
    refuse_collisions(&doc, root, doc_path, out, format)?;
    let meta = doc["meta"]
        .as_object()
        .ok_or_else(|| invalid("Chapter is missing metadata"))?;
    let policy = meta
        .get("sfx_policy")
        .and_then(Value::as_str)
        .unwrap_or("keep");
    let mut resolved = options.clone();
    if !resolved.draft
        && let Some(finding) = certify::certify_publication(root, &typed)?.first()
    {
        return Err(invalid(format!(
            "{}: {}: {}",
            finding.page, finding.code, finding.detail
        )));
    }
    for (key, target) in [
        ("title", &mut resolved.title),
        ("chapter", &mut resolved.chapter),
        ("target_language", &mut resolved.target_language),
        ("reading_direction", &mut resolved.reading_direction),
        ("tool", &mut resolved.tool),
    ] {
        if let Some(text) = meta.get(key).and_then(Value::as_str) {
            *target = text.to_owned();
        }
    }
    let mut pages = Vec::new();
    let mut unrendered = Vec::new();
    let entries = doc["pages"]
        .as_array()
        .ok_or_else(|| invalid("Chapter is missing its page list"))?;
    for (index, (raw_page, page)) in entries.iter().zip(&typed.pages).enumerate() {
        if raw_page["index"].as_u64() != Some(index as u64) {
            return Err(invalid("Chapter page indices are not ordered"));
        }
        if !raw_page["regions"].is_array() {
            return Err(invalid("Page is missing its region list"));
        }
        let (page, pending) = read_page(root, page, policy, resolved.draft)?;
        if pending && let Some(id) = &page.id {
            unrendered.push(id.clone());
        }
        let target = canonical_destination(out)?;
        if page.source == target
            || (format == ExportFormat::Dir && page.source.starts_with(&target))
        {
            return Err(invalid("Export overlaps a page artifact"));
        }
        pages.push(page);
    }
    let writer = match format {
        ExportFormat::Cbz => export_cbz,
        ExportFormat::Pdf => export_pdf,
        ExportFormat::Dir => export_directory,
    };
    let dest = canonical_destination(out)?;
    let mut claim = workspace::destination_claim(&dest, doc_path)?;
    let name = dest
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| invalid("Export needs a UTF-8 filename"))?;
    let stage = dest.with_file_name(format!("{name}.revayat-part"));
    if format == ExportFormat::Dir {
        fs::create_dir(&stage)?;
    } else {
        File::options().write(true).create_new(true).open(&stage)?;
    }
    let prepared = (|| -> Result<(ExportReport, journal::Journal), IoError> {
        claim.remember_staging(&stage)?;
        let mut report = writer(&pages, &stage, &resolved)?;
        report.path = out.to_path_buf();
        report.unrendered_pages = unrendered;
        let mut published = BTreeMap::new();
        if format == ExportFormat::Dir {
            for row in &report.manifest {
                published.insert(row.name.clone(), row.sha256.clone());
            }
            published.insert(
                "ComicInfo.xml".into(),
                file_digest(&stage.join("ComicInfo.xml"))?,
            );
        } else {
            let hash = report
                .package_sha256
                .as_ref()
                .ok_or_else(|| invalid("Export package digest is missing"))?;
            published.insert(name.to_owned(), hash.clone());
        }
        let result = serde_json::to_value(&report)?;
        let mut stamp = result
            .as_object()
            .cloned()
            .ok_or_else(|| invalid("Invalid export result"))?;
        let old = &doc["stages"]["export"];
        let mut editions = old["editions"].as_object().cloned().unwrap_or_default();
        if editions.is_empty()
            && old["manifest"].is_array()
            && let Some(path) = old["path"].as_str()
        {
            let path = canonical_destination(Path::new(path))?;
            if let Some(path) = path.to_str() {
                editions.insert(path.to_owned(), old.clone());
            }
        }
        editions.insert(
            dest.to_str()
                .ok_or_else(|| invalid("Export path is not UTF-8"))?
                .to_owned(),
            result.clone(),
        );
        stamp.insert("editions".into(), Value::Object(editions));
        let options =
            json!({"format": format, "quality": resolved.quality, "draft": resolved.draft});
        stages::stamp_stage(&mut typed, "export", stamp, Some(options.clone()), None)?;
        let mut inputs = BTreeMap::new();
        for (record, page) in typed.pages.iter().zip(&pages) {
            let immutable = workspace_asset(root, Path::new(&record.image))?;
            inputs.insert(immutable, record.sha256.clone());
            inputs.insert(page.source.clone(), file_digest(&page.source)?);
        }
        if file_digest(doc_path)? != crate::fsutil::digest(&raw) {
            return Err(invalid("Chapter changed during export"));
        }
        let record = journal::write(doc_path, &dest, published, result, options, &typed, inputs)?;
        Ok((report, record))
    })();
    let (report, mut record) = match prepared {
        Ok(prepared) => prepared,
        Err(error) => {
            if journal::read(doc_path)?.is_none() && claim.owns() {
                if format == ExportFormat::Dir {
                    fs::remove_dir_all(stage)?;
                } else {
                    fs::remove_file(stage)?;
                }
            }
            return Err(error);
        }
    };
    let committed = journal::promote(doc_path, &mut record)
        .and_then(|()| ir::write_bytes(doc_path, &ir::json_bytes(&typed)?));
    if let Err(error) = committed {
        journal::rollback(&record)?;
        journal::finish(doc_path, &record, false)?;
        return Err(error.into());
    }
    journal::finish(doc_path, &record, true)?;
    Ok(report)
}

pub fn reconcile_pending(doc_path: &Path) -> Result<bool, IoError> {
    let doc_path = fs::canonicalize(doc_path)?;
    let _claim = workspace::workspace_lock(parent(&doc_path), "export recovery")?;
    recover_pending_claimed(&doc_path)
}

fn recover_pending_claimed(doc_path: &Path) -> Result<bool, IoError> {
    let Some(mut record) = journal::read(doc_path)? else {
        return Ok(false);
    };
    let _claim = workspace::destination_claim(&record.destination, doc_path)?;
    if matches!(
        journal::resume(doc_path, &mut record)?,
        journal::Recovery::Published
    ) {
        if file_digest(doc_path)? != record.document_after {
            let mut document = ir::decode_doc(&read_file(doc_path, 64 << 20)?)?;
            document
                .stages
                .insert("export".into(), record.export_stamp.clone());
            let bytes = ir::json_bytes(&document)?;
            if crate::fsutil::digest(&bytes) != record.document_after {
                return Err(invalid(
                    "Recovered export metadata differs from the pending journal",
                ));
            }
            ir::write_bytes(doc_path, &bytes)?;
        }
        journal::finish(doc_path, &record, true)?;
    }
    Ok(true)
}
