use std::{
    collections::HashSet,
    fs::{self, File},
    path::{Path, PathBuf},
};

use serde_json::json;
use zip::ZipArchive;

use crate::{
    IoError,
    archive::{check_page_count, extract_rar, zip_pages, zip_read},
    fsutil::{
        bounded_read, canonical_destination, digest, file_digest, move_into_place, read_file,
        write_file,
    },
    images::{decode_image, image_extension},
    inputs::{
        ImportOptions, ImportReport, ImportedPage, InputKind, MAX_MEMBER_BYTES, MAX_PAGE_PIXELS,
        MAX_TOTAL_BYTES,
    },
    invalid,
    order::natural_sort_order,
    pdf::PdfDocument,
};

pub use crate::archive::check_archive_limits;

pub fn detect_kind(path: &Path) -> Result<InputKind, IoError> {
    if path.is_dir() {
        return Ok(InputKind::Directory);
    }
    let suffix = path
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    match suffix.as_str() {
        "zip" | "cbz" => Ok(InputKind::Cbz),
        "rar" | "cbr" => Ok(InputKind::Cbr),
        "pdf" => Ok(InputKind::Pdf),
        _ if image_extension(path).is_some() => Ok(InputKind::Image),
        _ if File::open(path).is_ok_and(|file| ZipArchive::new(file).is_ok()) => Ok(InputKind::Cbz),
        _ => Err(invalid(
            "Supported inputs are CBZ, CBR, PDF, an image folder or a single image",
        )),
    }
}

fn id(index: usize) -> String {
    format!("p{:04}", index + 1)
}

struct ImportStage<'a> {
    directory: &'a Path,
    options: &'a ImportOptions,
    pages: Vec<ImportedPage>,
    bytes: u64,
}

impl ImportStage<'_> {
    fn admit(
        &mut self,
        extension: &str,
        payload: &[u8],
        paper: Option<[f64; 2]>,
        staged: bool,
    ) -> Result<(), IoError> {
        let index = self.pages.len();
        let page = id(index);
        let name = format!("{page}.{extension}");
        let target = self.directory.join(&name);
        self.bytes = self.bytes.saturating_add(payload.len() as u64);
        if self.bytes > MAX_TOTAL_BYTES {
            return Err(invalid("Chapter expands beyond the 2 GiB input budget"));
        }
        let image = decode_image(payload, self.options.max_pixels)?;
        let (width, height) = (image.width(), image.height());
        let hash = digest(payload);
        if !staged {
            fs::write(&target, payload)?;
        }
        if file_digest(&target)? != hash {
            return Err(invalid("Staged page SHA-256 does not match the input"));
        }
        self.pages.push(ImportedPage {
            id: page,
            index,
            image: PathBuf::from(format!("pages/{name}")),
            sha256: hash,
            width,
            height,
            pdf_points: paper,
            is_spread: paper.map_or(width > height, |p| p[0] > p[1]),
            panels: Vec::new(),
            regions: Vec::new(),
            notes: Vec::new(),
        });
        Ok(())
    }

    fn loose(&mut self, source: &Path, single: bool) -> Result<(), IoError> {
        let mut candidates = if single {
            vec![source.to_path_buf()]
        } else {
            fs::read_dir(source)?
                .filter_map(|entry| match entry {
                    Ok(e)
                        if e.file_name().to_string_lossy().starts_with('.')
                            || image_extension(&e.path()).is_none() =>
                    {
                        None
                    }
                    Ok(e) => Some(e.file_type().map(|kind| (kind, e.path()))),
                    Err(e) => Some(Err(e)),
                })
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .filter_map(|(kind, path)| kind.is_file().then_some(path))
                .collect()
        };
        check_page_count(candidates.len())?;
        let names = candidates
            .iter()
            .map(|path| {
                path.file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned()
            })
            .collect::<Vec<_>>();
        let order = natural_sort_order(&names);
        let mut sources = HashSet::new();
        for i in order {
            let page = std::mem::take(&mut candidates[i]);
            let page = fs::canonicalize(page)?;
            if !sources.insert(page.clone()) {
                return Err(invalid("Duplicate loose page"));
            }
            let extension =
                image_extension(&page).ok_or_else(|| invalid("Unsupported page extension"))?;
            let payload = bounded_read(
                File::open(page)?,
                MAX_MEMBER_BYTES.min(MAX_TOTAL_BYTES - self.bytes),
            )?;
            self.admit(&extension, &payload, None, false)?;
        }
        Ok(())
    }

    fn archive(&mut self, source: &Path, kind: InputKind) -> Result<(), IoError> {
        if kind == InputKind::Cbr {
            for (name, _) in extract_rar(source, self.directory)? {
                let path = self.directory.join(&name);
                let extension =
                    image_extension(&path).ok_or_else(|| invalid("Unsupported page extension"))?;
                self.admit(&extension, &read_file(&path, MAX_MEMBER_BYTES)?, None, true)?;
            }
        } else {
            let mut archive = ZipArchive::new(File::open(source)?)?;
            for member in zip_pages(&mut archive)? {
                self.admit(
                    &member.extension,
                    &zip_read(&mut archive, &member)?,
                    None,
                    false,
                )?;
            }
        }
        Ok(())
    }

    fn pdf(&mut self, source: &Path) -> Result<(), IoError> {
        let pdf = PdfDocument::open(read_file(source, MAX_TOTAL_BYTES)?)?;
        check_page_count(pdf.len())?;
        for index in 0..pdf.len() {
            let (png, paper) = pdf.import_page(index, self.options.dpi, self.options.max_pixels)?;
            self.admit("png", &png, Some(paper), false)?;
        }
        Ok(())
    }
}

pub fn import_input(
    source: &Path,
    work: &Path,
    options: &ImportOptions,
) -> Result<ImportReport, IoError> {
    if options.max_pixels == 0 || options.max_pixels > MAX_PAGE_PIXELS {
        return Err(invalid(
            "Page pixel budget must be between 1 and 80,000,000",
        ));
    }
    if !matches!(options.reading_direction.as_str(), "rtl" | "ltr") {
        return Err(invalid("Reading direction must be rtl or ltr"));
    }
    let source = fs::canonicalize(source)?;
    let kind = detect_kind(&source)?;
    let target = work.join("pages");
    let doc_path = work.join("comic.json");
    let full_target = canonical_destination(&target)?;
    let full_doc = canonical_destination(&doc_path)?;
    if source == full_doc
        || source.starts_with(&full_target)
        || (kind == InputKind::Directory && full_target.starts_with(&source))
    {
        return Err(invalid(
            "Source overlaps the destination; choose a separate workspace",
        ));
    }
    if target
        .symlink_metadata()
        .is_ok_and(|m| !m.file_type().is_dir())
    {
        return Err(invalid("Workspace pages destination is not a directory"));
    }
    let _lock = revayat_ir::workspace::workspace_lock(work, "import")?;
    let transaction = tempfile::Builder::new()
        .prefix(".revayat-import-")
        .tempdir_in(work)?;
    let incoming = transaction.path().join("incoming");
    let previous = transaction.path().join("previous");
    fs::create_dir(&incoming)?;
    let mut stage = ImportStage {
        directory: &incoming,
        options,
        pages: Vec::new(),
        bytes: 0,
    };
    match kind {
        InputKind::Image => stage.loose(&source, true)?,
        InputKind::Directory => stage.loose(&source, false)?,
        InputKind::Cbz | InputKind::Cbr => stage.archive(&source, kind)?,
        InputKind::Pdf => stage.pdf(&source)?,
    }
    let title = if options.title.is_empty() {
        source
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned()
    } else {
        options.title.clone()
    };
    let document = json!({"version":1,"meta":{"tool":"revayat-comic","title":title,"chapter":options.chapter,"source_language":options.source_language,"target_language":options.target_language,"reading_direction":options.reading_direction,"sfx_policy":"keep"},"source":{"kind":kind,"name":source.file_name().unwrap_or_default().to_string_lossy(),"path":source,"page_count":stage.pages.len(),"dpi":(kind==InputKind::Pdf).then_some(options.dpi)},"pages":stage.pages,"glossary":{},"stages":{}});
    let bytes = serde_json::to_vec_pretty(&document)?;
    let mut widths = stage.pages.iter().map(|p| p.width).collect::<Vec<_>>();
    let mut heights = stage.pages.iter().map(|p| p.height).collect::<Vec<_>>();
    widths.sort_unstable();
    heights.sort_unstable();
    let median_size = [
        f64::from(widths[widths.len() / 2]),
        f64::from(heights[heights.len() / 2]),
    ];
    let webtoon_strips = stage
        .pages
        .iter()
        .filter(|p| p.height >= p.width.saturating_mul(3))
        .map(|p| p.id.clone())
        .collect::<Vec<_>>();
    let warning=(!webtoon_strips.is_empty()).then(||format!("{} page(s) are at least three times taller than they are wide. Use ltr direction for a webtoon strip.",webtoon_strips.len()));
    let replaced = match move_into_place(&incoming, &target, &previous) {
        Ok(value) => value,
        Err(error) => {
            if previous.exists() {
                let _ = transaction.keep();
            }
            return Err(error);
        }
    };
    if let Err(error) = write_file(&doc_path, &bytes) {
        let restored = fs::rename(&target, &incoming).and_then(|()| {
            if replaced {
                fs::rename(&previous, &target)
            } else {
                Ok(())
            }
        });
        if let Err(rollback) = restored {
            let saved = transaction.keep();
            return Err(invalid(format!(
                "Document write failed ({error}); rollback failed ({rollback}). Recovery files are in {}",
                saved.display()
            )));
        }
        return Err(error);
    }
    Ok(ImportReport {
        document: doc_path,
        kind,
        pages: stage.pages,
        median_size,
        reading_direction: options.reading_direction.clone(),
        webtoon_strips,
        warning,
    })
}
