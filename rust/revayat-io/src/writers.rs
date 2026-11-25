use std::{
    collections::HashSet,
    fs::{self, File},
    io::{self, Write},
    path::Path,
};

use flate2::{Compression, write::ZlibEncoder};
use image::{DynamicImage, ImageFormat, codecs::jpeg::JpegEncoder};
use pdf_writer::{Filter, Finish, Name, Pdf, Ref, TextStr, types::Predictor};
use zip::{CompressionMethod, ZipWriter, write::SimpleFileOptions};

use crate::{
    IoError,
    archive::check_page_count,
    export::{ExportFormat, ExportOptions, ExportPage, ExportReport, ManifestPage},
    fsutil::{atomic_file, canonical_destination, digest, file_digest, lock, parent, read_file},
    geometry::validate_paper,
    images::{appearance, decode_image, image_extension, pixel_digest},
    inputs::{MAX_MEMBER_BYTES, MAX_PAGE_PIXELS, MAX_TOTAL_BYTES},
    invalid,
};

struct PageData {
    payload: Vec<u8>,
    image: DynamicImage,
    row: ManifestPage,
}

fn check(pages: &[ExportPage], out: &Path, options: &ExportOptions) -> Result<(), IoError> {
    check_page_count(pages.len())?;
    if options.quality > 100 || !matches!(options.reading_direction.as_str(), "rtl" | "ltr") {
        return Err(invalid("Invalid export quality or reading direction"));
    }
    let target = canonical_destination(out)?;
    let mut ids = HashSet::new();
    for page in pages {
        let source = fs::canonicalize(&page.source)?;
        if source == target || source.starts_with(&target) {
            return Err(invalid("Export would overwrite a source page"));
        }
        if let Some(id) = &page.id
            && (id.is_empty() || !ids.insert(id))
        {
            return Err(invalid("Export page IDs must be unique and nonempty"));
        }
    }
    Ok(())
}

fn prepare(
    page: &ExportPage,
    index: usize,
    options: &ExportOptions,
    pdf: bool,
) -> Result<PageData, IoError> {
    let mut payload = read_file(&page.source, MAX_MEMBER_BYTES)?;
    let mut image = decode_image(&payload, MAX_PAGE_PIXELS)?;
    let [width, height] = [image.width(), image.height()];
    if page
        .expected_size
        .is_some_and(|expected| expected != [width, height])
    {
        return Err(invalid(
            "Export page pixel dimensions differ from the immutable source",
        ));
    }
    let mut extension =
        image_extension(&page.source).ok_or_else(|| invalid("Unsupported export page format"))?;
    let mut format = image::guess_format(&payload)?;
    let actual = match format {
        ImageFormat::Png => "png",
        ImageFormat::Jpeg => "jpg",
        ImageFormat::WebP => "webp",
        ImageFormat::Gif => "gif",
        ImageFormat::Tiff => "tiff",
        ImageFormat::Bmp => "bmp",
        _ => return Err(invalid("Unsupported export page format")),
    };
    if extension != actual
        && !(extension == "tif" && actual == "tiff")
        && !(extension == "jpeg" && actual == "jpg")
    {
        return Err(invalid("Page bytes do not match the file extension"));
    }
    if options.quality > 0 && format != ImageFormat::Jpeg {
        payload = Vec::new();
        JpegEncoder::new_with_quality(&mut payload, options.quality)
            .encode_image(&image.to_rgb8())?;
        image = decode_image(&payload, MAX_PAGE_PIXELS)?;
        extension = "jpg".into();
        format = ImageFormat::Jpeg;
    }
    let paper = pdf
        .then_some(page.paper.unwrap_or([f64::from(width), f64::from(height)]))
        .map(validate_paper)
        .transpose()?;
    let rgb = image.to_rgb8();
    let row = ManifestPage {
        page: page
            .id
            .clone()
            .unwrap_or_else(|| format!("p{:04}", index + 1)),
        name: if pdf {
            format!("page {}", index + 1)
        } else {
            format!("{:04}.{extension}", index + 1)
        },
        sha256: digest(&payload),
        pixels: pixel_digest(&rgb),
        appearance: appearance(&rgb),
        width,
        height,
        lossy: format == ImageFormat::Jpeg,
        pdf_points: paper,
    };
    Ok(PageData {
        payload,
        image,
        row,
    })
}

fn comic_info(options: &ExportOptions, pages: usize) -> Result<Vec<u8>, IoError> {
    let mut out = String::from(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<ComicInfo xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">\n",
    );
    let count = pages.to_string();
    let manga = if options.reading_direction == "rtl" {
        "YesAndRightToLeft"
    } else {
        "No"
    };
    let notes = if options.draft {
        "DRAFT - did not pass publication QA"
    } else {
        ""
    };
    for (tag, value) in [
        ("Title", options.title.as_str()),
        ("Number", &options.chapter),
        ("LanguageISO", &options.target_language),
        ("PageCount", &count),
        ("Translator", &options.tool),
        ("Notes", notes),
        ("Manga", manga),
    ] {
        if value.is_empty() {
            continue;
        }
        crate::reviewdocx::valid_xml(value)?;
        out.push_str(&format!(
            "  <{tag}>{}</{tag}>\n",
            quick_xml::escape::escape(value)
        ));
    }
    out.push_str("</ComicInfo>\n");
    Ok(out.into_bytes())
}

fn claim(out: &Path) -> Result<tempfile::NamedTempFile, IoError> {
    let name = out
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| invalid("Output needs a UTF-8 file name"))?;
    if out
        .symlink_metadata()
        .is_ok_and(|m| m.file_type().is_symlink())
    {
        return Err(invalid("Refusing to overwrite an output symlink"));
    }
    lock(parent(out), &format!("{name}.revayat-claim"))
}

fn report(
    format: ExportFormat,
    out: &Path,
    options: &ExportOptions,
    manifest: Vec<ManifestPage>,
) -> Result<ExportReport, IoError> {
    Ok(ExportReport {
        format,
        path: out.to_path_buf(),
        pages: manifest.len(),
        draft: options.draft,
        manifest,
        package_sha256: (format != ExportFormat::Dir)
            .then(|| file_digest(out))
            .transpose()?,
        unrendered_pages: Vec::new(),
    })
}

fn checked_total(total: &mut u64, len: usize) -> Result<(), IoError> {
    *total = total.saturating_add(len as u64);
    if *total > MAX_TOTAL_BYTES {
        return Err(invalid("Export exceeds the 2 GiB chapter budget"));
    }
    Ok(())
}

pub fn export_cbz(
    pages: &[ExportPage],
    out: &Path,
    options: &ExportOptions,
) -> Result<ExportReport, IoError> {
    check(pages, out, options)?;
    let _lock = claim(out)?;
    let mut manifest = Vec::with_capacity(pages.len());
    let mut total = 0;
    atomic_file(out, |file| {
        let mut archive = ZipWriter::new(file);
        let entry = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
        for (index, page) in pages.iter().enumerate() {
            let page = prepare(page, index, options, false)?;
            checked_total(&mut total, page.payload.len())?;
            archive.start_file(&page.row.name, entry)?;
            archive.write_all(&page.payload)?;
            manifest.push(page.row);
        }
        archive.start_file("ComicInfo.xml", entry)?;
        archive.write_all(&comic_info(options, pages.len())?)?;
        archive.finish()?;
        Ok(())
    })?;
    report(ExportFormat::Cbz, out, options, manifest)
}

pub fn export_directory(
    pages: &[ExportPage],
    out: &Path,
    options: &ExportOptions,
) -> Result<ExportReport, IoError> {
    check(pages, out, options)?;
    let _lock = claim(out)?;
    let stage = tempfile::Builder::new()
        .prefix(".revayat-export-")
        .tempdir_in(parent(out))?;
    let backup = stage.path().join("previous");
    fs::create_dir(&backup)?;
    let mut manifest = Vec::with_capacity(pages.len());
    let mut total = 0;
    for (index, page) in pages.iter().enumerate() {
        let page = prepare(page, index, options, false)?;
        checked_total(&mut total, page.payload.len())?;
        fs::write(stage.path().join(&page.row.name), page.payload)?;
        manifest.push(page.row);
    }
    fs::write(
        stage.path().join("ComicInfo.xml"),
        comic_info(options, pages.len())?,
    )?;
    let names = manifest
        .iter()
        .map(|row| row.name.as_str())
        .chain(["ComicInfo.xml"])
        .collect::<Vec<_>>();
    let created = !out.exists();
    if !created {
        for entry in fs::read_dir(out)? {
            let entry = entry?;
            let name = entry.file_name();
            let owns = name.to_str().is_some_and(|name| names.contains(&name));
            if (owns && !entry.file_type()?.is_file())
                || (!owns && image_extension(&entry.path()).is_some())
            {
                return Err(invalid(
                    "Output directory contains a conflicting file or page",
                ));
            }
        }
    } else {
        fs::create_dir(out)?;
    }
    let mut done = Vec::new();
    let publish = (|| -> Result<(), IoError> {
        for name in names {
            let target = out.join(name);
            let had_old = target.exists();
            if had_old {
                fs::rename(&target, backup.join(name))?;
            }
            done.push((name, had_old));
            fs::rename(stage.path().join(name), target)?;
        }
        Ok(())
    })();
    if let Err(error) = publish {
        let restore = (|| -> io::Result<()> {
            for (name, had_old) in done.into_iter().rev() {
                let target = out.join(name);
                if target.exists() {
                    fs::remove_file(&target)?;
                }
                if had_old {
                    fs::rename(backup.join(name), target)?;
                }
            }
            if created {
                fs::remove_dir(out)?;
            }
            Ok(())
        })();
        if let Err(rollback) = restore {
            return Err(invalid(format!(
                "Export failed ({error}); rollback failed ({rollback}). Backup: {}",
                stage.keep().display()
            )));
        }
        return Err(error);
    }
    report(ExportFormat::Dir, out, options, manifest)
}

pub fn export_pdf(
    pages: &[ExportPage],
    out: &Path,
    options: &ExportOptions,
) -> Result<ExportReport, IoError> {
    check(pages, out, options)?;
    let _lock = claim(out)?;
    let root = Ref::new(1);
    let tree = Ref::new(2);
    let info = Ref::new(3);
    let mut ids = Ref::new(4);
    let page_ids = (0..pages.len()).map(|_| ids.bump()).collect::<Vec<_>>();
    let mut pdf = Pdf::new();
    pdf.catalog(root).pages(tree);
    pdf.pages(tree)
        .kids(page_ids.iter().copied())
        .count(pages.len() as i32);
    pdf.document_info(info)
        .title(TextStr(&options.title))
        .producer(TextStr(&options.tool));
    let mut edits = Vec::new();
    let mut manifest = Vec::new();
    let mut total = 0;
    for (index, page) in pages.iter().enumerate() {
        let data = prepare(page, index, options, true)?;
        checked_total(&mut total, data.payload.len())?;
        let image_id = ids.bump();
        let content_id = ids.bump();
        let [width, height] = data
            .row
            .pdf_points
            .ok_or_else(|| invalid("Missing PDF paper dimensions"))?;
        let paper = format!("[0 0 {width} {height}]");
        // pdf-writer accepts f32 PDF numbers. A same-length placeholder preserves its xref offsets.
        let marker = "x".repeat(paper.len() - 1);
        let start = pdf.as_bytes().len();
        let mut sheet = pdf.page(page_ids[index]);
        sheet
            .parent(tree)
            .contents(content_id)
            .pair(Name(b"MediaBox"), Name(marker.as_bytes()));
        sheet.resources().x_objects().pair(Name(b"Scan"), image_id);
        sheet.finish();
        let marker = format!("/{marker}");
        let offset = pdf.as_bytes()[start..]
            .windows(marker.len())
            .position(|window| window == marker.as_bytes())
            .ok_or_else(|| invalid("PDF writer omitted the media box"))?;
        edits.push((start + offset, paper.into_bytes()));
        embed(&mut pdf, image_id, &mut ids, &data)?;
        pdf.stream(
            content_id,
            format!("q\n{width} 0 0 {height} 0 0 cm\n/Scan Do\nQ\n").as_bytes(),
        );
        manifest.push(data.row);
    }
    let mut bytes = pdf.finish();
    for (offset, data) in edits {
        bytes[offset..offset + data.len()].copy_from_slice(&data);
    }
    atomic_file(out, |file: &mut File| Ok(file.write_all(&bytes)?))?;
    report(ExportFormat::Pdf, out, options, manifest)
}

fn zlib(bytes: &[u8]) -> Result<Vec<u8>, IoError> {
    let mut enc = ZlibEncoder::new(Vec::new(), Compression::default());
    enc.write_all(bytes)?;
    Ok(enc.finish()?)
}

fn embed(pdf: &mut Pdf, id: Ref, ids: &mut Ref, data: &PageData) -> Result<(), IoError> {
    let w = data.row.width as i32;
    let h = data.row.height as i32;
    if data.row.lossy && jpeg_components(&data.payload).is_some_and(|n| matches!(n, 1 | 3)) {
        let mut stream = pdf.image_xobject(id, &data.payload);
        stream
            .width(w)
            .height(h)
            .bits_per_component(8)
            .filter(Filter::DctDecode);
        if jpeg_components(&data.payload) == Some(1) {
            stream.color_space().device_gray();
        } else {
            stream.color_space().device_rgb();
        }
        return Ok(());
    }
    if let Some((compressed, colors, depth)) = original_png_stream(&data.payload) {
        let mut stream = pdf.image_xobject(id, &compressed);
        stream
            .width(w)
            .height(h)
            .bits_per_component(depth)
            .filter(Filter::FlateDecode);
        if colors == 1 {
            stream.color_space().device_gray();
        } else {
            stream.color_space().device_rgb();
        }
        stream
            .decode_parms()
            .predictor(Predictor::PngOptimum)
            .columns(w)
            .colors(colors)
            .bits_per_component(depth);
        return Ok(());
    }
    let rgba = data.image.color().has_alpha();
    let gray = matches!(
        data.image.color(),
        image::ColorType::L8
            | image::ColorType::La8
            | image::ColorType::L16
            | image::ColorType::La16
    );
    let depth = if data.image.color().bytes_per_pixel() / data.image.color().channel_count() == 2 {
        16
    } else {
        8
    };
    let mut alpha = None;
    if rgba {
        let samples = if depth == 16 {
            data.image
                .to_rgba16()
                .as_raw()
                .as_chunks::<4>()
                .0
                .iter()
                .flat_map(|pixel| pixel[3].to_be_bytes())
                .collect()
        } else {
            data.image
                .to_rgba8()
                .as_raw()
                .as_chunks::<4>()
                .0
                .iter()
                .map(|pixel| pixel[3])
                .collect::<Vec<u8>>()
        };
        let compressed = zlib(&samples)?;
        let mask = ids.bump();
        let mut stream = pdf.image_xobject(mask, &compressed);
        stream
            .width(w)
            .height(h)
            .bits_per_component(depth)
            .filter(Filter::FlateDecode);
        stream.color_space().device_gray();
        alpha = Some(mask);
    }
    let samples = match (gray, depth) {
        (true, 16) => data
            .image
            .to_luma16()
            .as_raw()
            .iter()
            .flat_map(|s| s.to_be_bytes())
            .collect(),
        (false, 16) => data
            .image
            .to_rgb16()
            .as_raw()
            .iter()
            .flat_map(|s| s.to_be_bytes())
            .collect(),
        (true, _) => data.image.to_luma8().into_raw(),
        (false, _) => data.image.to_rgb8().into_raw(),
    };
    let compressed = zlib(&samples)?;
    let mut stream = pdf.image_xobject(id, &compressed);
    stream
        .width(w)
        .height(h)
        .bits_per_component(depth)
        .filter(Filter::FlateDecode);
    if gray {
        stream.color_space().device_gray();
    } else {
        stream.color_space().device_rgb();
    }
    if let Some(alpha) = alpha {
        stream.s_mask(alpha);
    }
    Ok(())
}

fn original_png_stream(data: &[u8]) -> Option<(Vec<u8>, i32, i32)> {
    let mut bytes = data.strip_prefix(b"\x89PNG\r\n\x1a\n")?;
    let header = bytes.get(8..21)?;
    let depth = i32::from(header[8]);
    let colors = match header[9] {
        0 if matches!(depth, 8 | 16) => 1,
        2 if matches!(depth, 8 | 16) => 3,
        _ => return None,
    };
    if header[10..] != [0, 0, 0] {
        return None;
    }
    let mut compressed = Vec::new();
    while !bytes.is_empty() {
        let length = u32::from_be_bytes(bytes.get(..4)?.try_into().ok()?) as usize;
        let end = length.checked_add(8)?;
        match bytes.get(4..8)? {
            b"tRNS" | b"iCCP" => return None,
            b"IDAT" => compressed.extend_from_slice(bytes.get(8..end)?),
            b"IEND" => break,
            _ => {}
        }
        bytes = bytes.get(end.checked_add(4)?..)?;
    }
    (!compressed.is_empty()).then_some((compressed, colors, depth))
}

fn jpeg_components(data: &[u8]) -> Option<u8> {
    let mut rest = data.strip_prefix(b"\xff\xd8")?;
    loop {
        rest = rest.strip_prefix(b"\xff")?;
        let marker = *rest.first()?;
        rest = &rest[1..];
        if marker == 0xff {
            continue;
        }
        if marker == 0xda || marker == 0xd9 {
            return None;
        }
        let len = usize::from(u16::from_be_bytes(rest.get(..2)?.try_into().ok()?));
        if len < 2 {
            return None;
        }
        let segment = rest.get(..len)?;
        if matches!(marker, 0xc0..=0xc3) {
            return (segment.get(2) == Some(&8))
                .then(|| segment.get(7).copied())
                .flatten();
        }
        rest = &rest[len..];
    }
}
