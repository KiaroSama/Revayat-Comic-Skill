use std::{
    collections::HashSet,
    fs::{self, File},
    path::Path,
};

use serde::Serialize;
use serde_json::Value;
use zip::ZipArchive;

use crate::{
    IoError,
    archive::{zip_pages, zip_read},
    export::{ExportFormat, ManifestPage},
    fsutil::{canonical_destination, digest, file_digest, read_file},
    images::{decode_image, image_extension, pixel_digest},
    inputs::{MAX_MEMBER_BYTES, MAX_PAGE_PIXELS, MAX_TOTAL_BYTES},
    invalid,
    order::natural_sort_order,
    pdf::PdfDocument,
};

pub const CODES: &[&str] = &[
    "archive-evidence",
    "archive-image-unreadable",
    "archive-invalid",
    "archive-metadata",
    "archive-package-bytes",
    "archive-page-appearance",
    "archive-page-bytes",
    "archive-page-count",
    "archive-page-order",
    "archive-page-size",
    "archive-pdf-page",
];

#[derive(Debug, Serialize)]
pub struct Finding {
    pub code: &'static str,
    pub severity: &'static str,
    pub location: String,
    pub message: String,
}

#[derive(Debug, Serialize)]
pub struct PackageReport {
    pub ok: bool,
    pub package: std::path::PathBuf,
    pub pages_expected: usize,
    pub pages_found: usize,
    pub findings: Vec<Finding>,
}

impl PackageReport {
    fn add(&mut self, code: &'static str, location: impl Into<String>, message: impl Into<String>) {
        debug_assert!(CODES.contains(&code), "undeclared package finding: {code}");
        self.ok = false;
        self.findings.push(Finding {
            code,
            severity: "error",
            location: location.into(),
            message: message.into(),
        });
    }

    fn verify_member(&mut self, name: &str, data: &[u8], row: Option<&ManifestPage>) {
        let (w, h) = match decode_image(data, MAX_PAGE_PIXELS) {
            Ok(image) => (image.width(), image.height()),
            Err(e) => {
                self.add("archive-image-unreadable", name, e.to_string());
                return;
            }
        };
        if let Some(row) = row {
            if name != row.name {
                self.add(
                    "archive-page-order",
                    name,
                    format!("Expected {} at this position", row.name),
                );
            }
            if (w, h) != (row.width, row.height) {
                self.add(
                    "archive-page-size",
                    name,
                    format!("Expected {} x {}, found {w} x {h}", row.width, row.height),
                );
            }
            if digest(data) != row.sha256 {
                self.add(
                    "archive-page-bytes",
                    name,
                    "Page bytes do not match the export manifest",
                );
            }
        }
    }
}

fn format_of(path: &Path) -> Result<ExportFormat, IoError> {
    use std::io::Read;
    if path.is_dir() {
        return Ok(ExportFormat::Dir);
    }
    let mut file = File::open(path)?;
    let mut header = [0; 5];
    let n = file.read(&mut header)?;
    if n == 5 && header == *b"%PDF-" {
        return Ok(ExportFormat::Pdf);
    }
    if ZipArchive::new(File::open(path)?).is_ok() {
        return Ok(ExportFormat::Cbz);
    }
    Err(invalid("Not a readable CBZ, PDF or page directory"))
}

fn evidence<'a>(doc: &'a Value, path: &Path, format: ExportFormat) -> Result<&'a Value, IoError> {
    let destination = canonical_destination(path)?;
    let stamp = &doc["stages"]["export"];
    let format = serde_json::to_value(format)?;
    if let Some(editions) = stamp["editions"]
        .as_object()
        .filter(|editions| !editions.is_empty())
    {
        if let Some(exact) = destination.to_str().and_then(|p| editions.get(p)) {
            if exact["format"] == format {
                return Ok(exact);
            }
            return Err(invalid(
                "Package format does not match the recorded edition",
            ));
        }
        let mut matches = editions
            .values()
            .filter(|edition| edition["format"] == format);
        if let Some(first) = matches.next()
            && matches.next().is_none()
        {
            return Ok(first);
        }
        return Err(invalid("No unique export evidence matches this package"));
    }
    if stamp["manifest"].is_array() && stamp["format"] == format {
        return Ok(stamp);
    }
    Err(invalid("No export manifest matches this package"))
}

fn check_cbz(
    report: &mut PackageReport,
    path: &Path,
    rows: &[ManifestPage],
) -> Result<(), IoError> {
    let mut archive = ZipArchive::new(File::open(path)?)?;
    let members = zip_pages(&mut archive)?;
    let names = members.iter().map(|m| m.name.as_str()).collect::<Vec<_>>();
    let member_indices = members.iter().map(|m| m.index).collect::<Vec<_>>();
    if !member_indices.is_sorted() {
        report.add(
            "archive-page-order",
            path.display().to_string(),
            "ZIP entries are not in natural page order",
        );
    }
    report.pages_found = members.len();
    if archive.by_name("ComicInfo.xml").is_err() {
        report.add(
            "archive-metadata",
            path.display().to_string(),
            "ComicInfo.xml is missing",
        );
    }
    for (i, name) in names.into_iter().enumerate() {
        let payload = zip_read(&mut archive, &members[i])?;
        report.verify_member(name, &payload, rows.get(i));
    }
    Ok(())
}

fn check_dir(
    report: &mut PackageReport,
    path: &Path,
    rows: &[ManifestPage],
) -> Result<(), IoError> {
    let mut names = Vec::new();
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        if image_extension(&entry.path()).is_some() {
            if !entry.file_type()?.is_file() {
                return Err(invalid("Package contains a non-file page"));
            }
            names.push(
                entry
                    .file_name()
                    .into_string()
                    .map_err(|_| invalid("Package page name is not UTF-8"))?,
            );
        }
    }
    report.pages_found = names.len();
    if !path.join("ComicInfo.xml").is_file() {
        report.add(
            "archive-metadata",
            path.display().to_string(),
            "ComicInfo.xml is missing",
        );
    }
    for (index, i) in natural_sort_order(&names).into_iter().enumerate() {
        let name = &names[i];
        let payload = read_file(&path.join(name), MAX_MEMBER_BYTES)?;
        report.verify_member(name, &payload, rows.get(index));
    }
    Ok(())
}

fn check_pdf(
    report: &mut PackageReport,
    path: &Path,
    rows: &[ManifestPage],
) -> Result<(), IoError> {
    let pdf = PdfDocument::open(read_file(path, MAX_TOTAL_BYTES)?)?;
    report.pages_found = pdf.len();
    for (index, row) in rows.iter().enumerate().take(pdf.len()) {
        let (image, paper, plain) = match pdf.proof(index, row.width, row.height) {
            Ok(value) => value,
            Err(e) => {
                report.add("archive-pdf-page", &row.page, e.to_string());
                continue;
            }
        };
        if row.pdf_points != Some(paper) {
            report.add(
                "archive-page-size",
                &row.page,
                "PDF paper dimensions changed",
            );
        }
        if !plain
            || (image.width(), image.height()) != (row.width, row.height)
            || pixel_digest(&image.to_rgb8()) != row.pixels
        {
            report.add(
                "archive-page-appearance",
                &row.page,
                "PDF page does not match the exported full-page image",
            );
        }
    }
    Ok(())
}

pub fn check_package(package: &Path, doc_path: &Path) -> Result<PackageReport, IoError> {
    let doc: Value = serde_json::from_slice(&read_file(doc_path, 64 << 20)?)?;
    if doc["version"].as_u64() != Some(1) {
        return Err(invalid("Unsupported chapter schema"));
    }
    let pages = doc["pages"]
        .as_array()
        .ok_or_else(|| invalid("Chapter is missing its page list"))?;
    let mut report = PackageReport {
        ok: true,
        package: package.to_path_buf(),
        pages_expected: pages.len(),
        pages_found: 0,
        findings: Vec::new(),
    };
    let location = package.display().to_string();
    let format = match format_of(package) {
        Ok(format) => format,
        Err(e) => {
            report.add("archive-invalid", location, e.to_string());
            return Ok(report);
        }
    };
    let rows = match evidence(&doc, package, format) {
        Ok(evidence) => {
            if let Some(hash) = evidence["package_sha256"].as_str()
                && file_digest(package)? != hash
            {
                report.add(
                    "archive-package-bytes",
                    &location,
                    "Package SHA-256 does not match the export manifest",
                );
            }
            match serde_json::from_value::<Vec<ManifestPage>>(evidence["manifest"].clone()) {
                Ok(rows) => rows,
                Err(error) => {
                    report.add("archive-evidence", &location, error.to_string());
                    Vec::new()
                }
            }
        }
        Err(e) => {
            report.add("archive-evidence", &location, e.to_string());
            Vec::new()
        }
    };
    let mut names = HashSet::new();
    if rows.len() != pages.len()
        || rows.iter().zip(pages).any(|(row, page)| {
            page["id"].as_str() != Some(row.page.as_str())
                || page["width"].as_u64() != Some(u64::from(row.width))
                || page["height"].as_u64() != Some(u64::from(row.height))
                || !names.insert(row.name.as_str())
        })
    {
        report.add(
            "archive-evidence",
            &location,
            "Manifest does not match the chapter page order or dimensions",
        );
    }
    let result = match format {
        ExportFormat::Cbz => check_cbz(&mut report, package, &rows),
        ExportFormat::Dir => check_dir(&mut report, package, &rows),
        ExportFormat::Pdf => check_pdf(&mut report, package, &rows),
    };
    if let Err(e) = result {
        report.add("archive-invalid", &location, e.to_string());
    }
    if report.pages_found != report.pages_expected {
        report.add(
            "archive-page-count",
            &location,
            format!(
                "Found {} pages, expected {}",
                report.pages_found, report.pages_expected
            ),
        );
    }
    Ok(report)
}
