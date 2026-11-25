#![forbid(unsafe_code)]

use std::{
    fs,
    io::{Cursor, Read, Write},
};

use image::{
    DynamicImage, Frame, ImageBuffer, ImageFormat, Rgb, RgbaImage, codecs::gif::GifEncoder,
};
use lopdf::{Document, Object, Stream, dictionary};
use revayat_io::{
    ExportOptions, ExportPage, ImportOptions, IoError, export_cbz, export_pdf, export_review_docx,
    import_input, inspect_pdf_page_density,
};
use serde_json::json;
use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};

fn png() -> Result<Vec<u8>, image::ImageError> {
    let image = DynamicImage::ImageRgb8(ImageBuffer::from_fn(8, 6, |x, y| {
        Rgb([x as u8 * 20, y as u8 * 20, 70])
    }));
    let mut bytes = Cursor::new(Vec::new());
    image.write_to(&mut bytes, ImageFormat::Png)?;
    Ok(bytes.into_inner())
}

fn stencil_pdf(nested: bool) -> Result<Vec<u8>, lopdf::Error> {
    let mut pdf = Document::with_version("1.7");
    let pages = pdf.new_object_id();
    let mask = pdf.add_object(Stream::new(dictionary! {"Type"=> "XObject", "Subtype" => "Image", "Width" => 160, "Height" => 120, "ImageMask"=> true, "BitsPerComponent" => 1}, vec![0; 20 * 120]));
    let pattern = pdf.add_object(Stream::new(dictionary! {"Type" => "Pattern", "PatternType" => 1, "PaintType" => 1, "TilingType" => 1, "BBox" => vec![0.into(),0.into(),5.into(),5.into()], "XStep" => 5, "YStep" => 5, "Resources"=>dictionary!{}}, b"1 0 0 rg 0 0 5 5 re f".to_vec()));
    let resources = dictionary! {"XObject" => dictionary!{"Mask"=>mask}, "Pattern" => dictionary!{"Tile"=>pattern}};
    let draw = b"q 20 0 0 15 10 10 cm /Pattern cs /Tile scn /Mask Do Q".to_vec();
    let (resources, draw) = if nested {
        let form = pdf.add_object(Stream::new(dictionary!{"Type"=>"XObject", "Subtype"=>"Form", "BBox" => vec![0.into(),0.into(),50.into(),50.into()], "Matrix" => vec![0.5.into(),0.into(),0.into(),0.5.into(),0.into(),0.into()], "Resources"=>resources},draw));
        (
            dictionary! {"XObject"=>dictionary!{"Form"=>form}},
            b"/Form Do".to_vec(),
        )
    } else {
        (resources, draw)
    };
    let content = pdf.add_object(Stream::new(dictionary! {}, draw));
    let page = pdf.add_object(dictionary!{"Type"=>"Page", "Parent"=>pages,"MediaBox"=>vec![0.into(),0.into(),50.into(),50.into()],"Contents"=>content, "Resources"=>resources});
    pdf.objects.insert(
        pages,
        Object::Dictionary(dictionary! {"Type"=>"Pages", "Kids"=>vec![page.into()], "Count"=>1}),
    );
    let root = pdf.add_object(dictionary! {"Type"=>"Catalog", "Pages"=>pages});
    pdf.trailer.set("Root", root);
    let mut result = Vec::new();
    pdf.save_to(&mut result)?;
    Ok(result)
}

#[test]
fn pattern_painted_stencil_bounds_native_resolution() -> Result<(), Box<dyn std::error::Error>> {
    let data = stencil_pdf(false)?;
    let page = inspect_pdf_page_density(&data, 0, 72, 160_000)?;
    assert_eq!((page.pixel_width, page.pixel_height), (400, 400));
    assert_eq!(page.stencils, 1);
    Ok(())
}

#[test]
fn nested_pattern_stencil_refuses_before_rendering() -> Result<(), Box<dyn std::error::Error>> {
    let data = stencil_pdf(true)?;
    let page = inspect_pdf_page_density(&data, 0, 72, 640_000)?;
    assert_eq!((page.pixel_width, page.pixel_height), (800, 800));
    assert!(matches!(
        inspect_pdf_page_density(&data, 0, 72, 639_999),
        Err(IoError::PixelBudget {
            required: 640_000,
            ..
        })
    ));
    let temp = tempfile::tempdir()?;
    let src = temp.path().join("masked.pdf");
    let work = temp.path().join("work");
    fs::write(&src, data)?;
    let options = ImportOptions {
        dpi: 72,
        max_pixels: 639_999,
        ..ImportOptions::default()
    };
    assert!(matches!(
        import_input(&src, &work, &options),
        Err(IoError::PixelBudget { .. })
    ));
    assert!(!work.join("pages").exists());
    assert!(!work.join("comic.json").exists());
    Ok(())
}

#[test]
fn cbz_round_trip_preserves_encoded_bytes_and_natural_order()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let a = temp.path().join("page2.png");
    let b = temp.path().join("page10.png");
    let original = png()?;
    let second = DynamicImage::new_rgb8(1, 1);
    fs::write(&a, &original)?;
    second.save(&b)?;
    let cbz = temp.path().join("comic.cbz");
    export_cbz(
        &[ExportPage::new(&a), ExportPage::new(&b)],
        &cbz,
        &ExportOptions::default(),
    )?;
    let report = import_input(&cbz, &temp.path().join("work"), &ImportOptions::default())?;
    assert_eq!(report.pages.len(), 2);
    assert_eq!(
        fs::read(
            report
                .document
                .parent()
                .ok_or("no parent")?
                .join(&report.pages[0].image)
        )?,
        original
    );
    assert_eq!(report.pages[1].width, 1);
    Ok(())
}

#[test]
fn flate_inline_stencil_participates_in_preflight() -> Result<(), Box<dyn std::error::Error>> {
    use flate2::{Compression, write::ZlibEncoder};
    let mut doc = Document::load_mem(&stencil_pdf(false)?)?;
    let page = *doc
        .get_pages()
        .values()
        .next()
        .ok_or("missing fixture page")?;
    let stream = *doc
        .get_page_contents(page)
        .first()
        .ok_or("missing fixture contents")?;
    let mut flate = ZlibEncoder::new(Vec::new(), Compression::fast());
    flate.write_all(&[0u8; 2400])?;
    let mut data =
        b"q 20 0 0 15 10 10 cm /Pattern cs /Tile scn BI /W 160 /H 120 /IM true /BPC 1 /F /Fl ID\n"
            .to_vec();
    data.extend(flate.finish()?);
    data.extend(b"\nEI Q\n");
    doc.get_object_mut(stream)?
        .as_stream_mut()?
        .set_plain_content(data);
    let mut bytes = Vec::new();
    doc.save_to(&mut bytes)?;
    let info = inspect_pdf_page_density(&bytes, 0, 72, 160_000)?;
    assert_eq!(info.stencils, 1);
    assert_eq!(info.required_pixels, 160_000);
    assert!(matches!(
        inspect_pdf_page_density(&bytes, 0, 72, 159_999),
        Err(IoError::PixelBudget {
            required: 160_000,
            ..
        })
    ));
    Ok(())
}

#[test]
fn pattern_stencil_renders_red_without_resampling_native_size()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let input = temp.path().join("stencil.pdf");
    fs::write(&input, stencil_pdf(true)?)?;
    let work = temp.path().join("chapter");
    let report = import_input(
        &input,
        &work,
        &ImportOptions {
            dpi: 72,
            max_pixels: 640_000,
            ..Default::default()
        },
    )?;
    let output = image::open(work.join(&report.pages[0].image))?.to_rgb8();
    assert_eq!(output.dimensions(), (800, 800));
    assert!(
        output
            .pixels()
            .any(|p| p[0] > 200 && p[1] < 50 && p[2] < 50)
    );
    Ok(())
}

fn rar_block(archive: &mut Vec<u8>, body: &[u8]) {
    let crc = rars::crc32::crc32(body) as u16;
    archive.extend_from_slice(&crc.to_le_bytes());
    archive.extend_from_slice(body);
}

#[test]
fn cbr_reads_rar4_and_refuses_parent_paths() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let payload = png()?;
    for name in ["folder/page.png", "..\\escape.png"] {
        let mut arc = b"Rar!\x1a\x07\x00".to_vec();
        rar_block(&mut arc, &[0x73, 0, 0, 13, 0, 0, 0, 0, 0, 0, 0]);
        let mut file = vec![0x74, 0, 0x80];
        file.extend_from_slice(&((32 + name.len()) as u16).to_le_bytes());
        file.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        file.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        file.push(3);
        file.extend_from_slice(&rars::crc32::crc32(&payload).to_le_bytes());
        file.extend_from_slice(&0u32.to_le_bytes());
        file.extend_from_slice(&[20, 0x30]);
        file.extend_from_slice(&(name.len() as u16).to_le_bytes());
        file.extend_from_slice(&0x81a4u32.to_le_bytes());
        file.extend_from_slice(name.as_bytes());
        rar_block(&mut arc, &file);
        arc.extend_from_slice(&payload);
        rar_block(&mut arc, &[0x7b, 0, 0, 7, 0]);
        let input = temp.path().join("chapter.cbr");
        let work = temp.path().join("chapter");
        fs::write(&input, arc)?;
        let result = import_input(&input, &work, &ImportOptions::default());
        if name.starts_with("..") {
            assert!(matches!(result, Err(IoError::ArchivePath(_))));
        } else {
            let report = result?;
            assert_eq!(fs::read(work.join(&report.pages[0].image))?, payload);
        }
    }
    assert!(!temp.path().join("escape.png").exists());
    Ok(())
}

#[test]
fn journaled_export_keeps_both_editions_checkable() -> Result<(), Box<dyn std::error::Error>> {
    use revayat_io::{export_document, package::check_package};
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("source.png");
    let work = temp.path().join("work");
    fs::write(&source, png()?)?;
    let report = import_input(&source, &work, &ImportOptions::default())?;
    let cbz = temp.path().join("out.cbz");
    let pdf = temp.path().join("out.pdf");
    export_document(&report.document, &cbz, None, &ExportOptions::default())?;
    export_document(&report.document, &pdf, None, &ExportOptions::default())?;
    assert!(check_package(&cbz, &report.document)?.ok);
    assert!(check_package(&pdf, &report.document)?.ok);
    assert!(!revayat_io::export::reconcile_pending(&report.document)?);
    assert!(export_document(&report.document, &source, None, &ExportOptions::default()).is_err());
    assert_eq!(fs::read(source)?, png()?);
    Ok(())
}

#[test]
fn zip_slip_refuses_entire_import() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let cbz = temp.path().join("comic.cbz");
    let mut zip = ZipWriter::new(fs::File::create(&cbz)?);
    zip.start_file("ok.png", SimpleFileOptions::default())?;
    zip.write_all(&png()?)?;
    zip.start_file("../escape.png", SimpleFileOptions::default())?;
    zip.write_all(&png()?)?;
    zip.finish()?;
    let work = temp.path().join("work");
    assert!(matches!(
        import_input(&cbz, &work, &ImportOptions::default()),
        Err(IoError::ArchivePath(_))
    ));
    assert!(!temp.path().join("escape.png").exists());
    assert!(!work.join("pages").exists());
    Ok(())
}

#[test]
fn multiframe_gif_refusal_preserves_existing_chapter() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let work = temp.path().join("work");
    let src = temp.path().join("page.png");
    let original = png()?;
    fs::write(&src, &original)?;
    let report = import_input(&src, &work, &ImportOptions::default())?;
    let document = fs::read(&report.document)?;
    let animated = temp.path().join("animated.gif");
    let mut gif = GifEncoder::new(fs::File::create(&animated)?);
    gif.encode_frame(Frame::new(RgbaImage::from_pixel(
        2,
        2,
        image::Rgba([0, 1, 2, 255]),
    )))?;
    gif.encode_frame(Frame::new(RgbaImage::from_pixel(
        2,
        2,
        image::Rgba([4, 5, 6, 255]),
    )))?;
    drop(gif);
    assert!(matches!(
        import_input(&animated, &work, &ImportOptions::default()),
        Err(IoError::AnimatedImage)
    ));
    assert_eq!(fs::read(&report.document)?, document);
    assert_eq!(fs::read(work.join(&report.pages[0].image))?, original);
    Ok(())
}

#[test]
fn pdf_write_readback_preserves_pixels_and_paper_geometry() -> Result<(), Box<dyn std::error::Error>>
{
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("scan.png");
    let pdf = temp.path().join("comic.pdf");
    let original = png()?;
    fs::write(&source, &original)?;
    let mut page = ExportPage::new(&source);
    page.paper = Some([513.125, 731.75]);
    export_pdf(&[page], &pdf, &ExportOptions::default())?;
    let inspection = inspect_pdf_page_density(&fs::read(&pdf)?, 0, 72, 1_000_000)?;
    assert_eq!(inspection.paper, [513.125, 731.75]);
    let work = temp.path().join("work");
    let report = import_input(&pdf, &work, &ImportOptions::default())?;
    assert_eq!(report.pages[0].pdf_points, Some([513.125, 731.75]));
    assert_eq!(
        image::open(work.join(&report.pages[0].image))?.to_rgb8(),
        image::load_from_memory(&original)?.to_rgb8()
    );
    Ok(())
}

#[test]
fn lossless_pdf_preserves_png_idat_and_sixteen_bit_samples()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("precision.png");
    let out = temp.path().join("precision.pdf");
    let pixels = ImageBuffer::from_fn(3, 2, |x, y| {
        Rgb([20016u16 + x as u16, 39001u16 + y as u16, 65534u16])
    });
    DynamicImage::ImageRgb16(pixels.clone()).save(&source)?;
    let mut page = ExportPage::new(&source);
    let paper = [513.123_456_789, 73.987_654_321];
    page.paper = Some(paper);
    export_pdf(&[page], &out, &ExportOptions::default())?;
    let pdf = Document::load(&out)?;
    let stream = pdf
        .objects
        .values()
        .filter_map(|obj| obj.as_stream().ok())
        .find(|s| s.dict.get(b"Subtype").and_then(Object::as_name).ok() == Some(b"Image"))
        .ok_or("missing PDF image")?;
    let input = fs::read(source)?;
    let mut cursor = &input[8..];
    let mut expected = Vec::new();
    while cursor.len() >= 12 {
        let len = u32::from_be_bytes(cursor[..4].try_into()?) as usize;
        if &cursor[4..8] == b"IDAT" {
            expected.extend_from_slice(&cursor[8..8 + len]);
        }
        cursor = &cursor[len + 12..];
    }
    assert_eq!(stream.content, expected);
    let work = temp.path().join("chapter");
    let report = import_input(&out, &work, &ImportOptions::default())?;
    assert_eq!(report.pages[0].pdf_points, Some(paper));
    let actual = image::open(work.join(&report.pages[0].image))?.into_rgb16();
    assert_eq!(actual, pixels);
    Ok(())
}

#[test]
fn review_docx_marks_persian_direction_and_font() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let out = temp.path().join("review.docx");
    let doc = json!({"version":1,"meta":{"title":"Chapter 1"},"pages":[{"id":"p0001","width":8,"height":6,"regions":[{"id":"p0001r001","kind":"speech","order":0,"source":"Hi!","target":"سلام!"}]}]});
    export_review_docx(&doc, &out)?;
    let mut zip = ZipArchive::new(fs::File::open(out)?)?;
    let mut xml = String::new();
    zip.by_name("word/document.xml")?.read_to_string(&mut xml)?;
    assert!(xml.contains("<w:bidi"));
    assert!(xml.contains("w:val=\"start\""));
    assert!(xml.contains("w:cs=\"Vazir\""));
    assert!(xml.contains("سلام!"));
    Ok(())
}
