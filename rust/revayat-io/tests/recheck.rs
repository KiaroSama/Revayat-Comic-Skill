#![forbid(unsafe_code)]

use std::fs;

use image::{ImageBuffer, Rgb};
use lopdf::{Document, Object, Stream, dictionary};
use revayat_io::{ImportOptions, IoError, import_input, inspect_pdf_page_density};

fn annotation_pdf(matrix: [i64; 6]) -> Result<Vec<u8>, lopdf::Error> {
    annotation_pdf_with_settings(matrix, 4, false)
}

fn annotation_pdf_with_settings(
    matrix: [i64; 6],
    flags: i64,
    default_appearance: bool,
) -> Result<Vec<u8>, lopdf::Error> {
    let mut pdf = Document::with_version("1.7");
    let pages = pdf.new_object_id();
    let image = pdf.add_object(Stream::new(
        dictionary! {
            "Type" => "XObject", "Subtype" => "Image", "Width" => 100, "Height" => 100,
            "ColorSpace" => "DeviceRGB", "BitsPerComponent" => 8
        },
        ImageBuffer::from_fn(100, 100, |x, y| {
            Rgb([if (x + y) % 2 == 0 { 255 } else { 0 }, 0, 0])
        })
        .into_raw(),
    ));
    let appearance = pdf.add_object(Stream::new(
        dictionary! {
            "Type" => "XObject", "Subtype" => "Form",
            "BBox" => vec![0.into(), 0.into(), 10.into(), 10.into()],
            "Matrix" => matrix.into_iter().map(Object::Integer).collect::<Vec<_>>(),
            "Resources" => dictionary! { "XObject" => dictionary! { "Scan" => image } }
        },
        b"q 10 0 0 10 0 0 cm /Scan Do Q".to_vec(),
    ));
    let normal = if default_appearance {
        Object::Dictionary(dictionary! { "Off" => appearance })
    } else {
        Object::Reference(appearance)
    };
    let annotation = pdf.add_object(dictionary! {
        "Type" => "Annot", "Subtype" => "Stamp",
        "Rect" => vec![10.into(), 10.into(), 20.into(), 20.into()],
        "AP" => dictionary! { "N" => normal }, "F" => flags
    });
    let page = pdf.add_object(dictionary! {
        "Type" => "Page", "Parent" => pages,
        "MediaBox" => vec![0.into(), 0.into(), 50.into(), 50.into()],
        "Resources" => dictionary! {}, "Annots" => vec![annotation.into()]
    });
    pdf.objects.insert(
        pages,
        Object::Dictionary(dictionary! {
            "Type" => "Pages", "Kids" => vec![page.into()], "Count" => 1
        }),
    );
    let root = pdf.add_object(dictionary! { "Type" => "Catalog", "Pages" => pages });
    pdf.trailer.set("Root", root);
    let mut bytes = Vec::new();
    pdf.save_to(&mut bytes)?;
    Ok(bytes)
}

#[test]
fn visible_standard_annotation_with_invisible_flag_participates_in_density()
-> Result<(), Box<dyn std::error::Error>> {
    let data = annotation_pdf_with_settings([1, 0, 0, 1, 0, 0], 1, false)?;
    let page = inspect_pdf_page_density(&data, 0, 72, 250_000)?;
    assert_eq!((page.pixel_width, page.pixel_height), (500, 500));
    assert_eq!(page.images, 1);
    assert!(matches!(
        inspect_pdf_page_density(&data, 0, 72, 249_999),
        Err(IoError::PixelBudget {
            required: 250_000,
            ..
        })
    ));
    Ok(())
}

#[test]
fn fallback_annotation_appearance_participates_in_density() -> Result<(), Box<dyn std::error::Error>>
{
    let data = annotation_pdf_with_settings([1, 0, 0, 1, 0, 0], 4, true)?;
    let page = inspect_pdf_page_density(&data, 0, 72, 250_000)?;
    assert_eq!((page.pixel_width, page.pixel_height), (500, 500));
    assert_eq!(page.images, 1);
    assert!(matches!(
        inspect_pdf_page_density(&data, 0, 72, 249_999),
        Err(IoError::PixelBudget {
            required: 250_000,
            ..
        })
    ));
    Ok(())
}

#[test]
fn annotation_appearance_matrix_is_fitted_before_density_measurement()
-> Result<(), Box<dyn std::error::Error>> {
    for matrix in [
        [1, 0, 0, 1, 0, 0],
        [10, 0, 0, 10, 0, 0],
        [0, 10, -10, 0, 100, 0],
        [10, 0, 0, 5, -30, 25],
    ] {
        let data = annotation_pdf(matrix)?;
        let page = inspect_pdf_page_density(&data, 0, 72, 250_000)?;
        assert_eq!(page.paper, [50.0, 50.0]);
        assert_eq!(page.images, 1);
        assert_eq!(
            (page.pixel_width, page.pixel_height),
            (500, 500),
            "appearance matrix {matrix:?} must not change the annotation's native density"
        );
        assert_eq!(page.required_pixels, 250_000);
    }
    Ok(())
}

#[test]
fn annotation_density_budget_refusal_preserves_the_existing_import()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let work = temp.path().join("chapter");
    let original = temp.path().join("source.png");
    ImageBuffer::from_pixel(8, 6, Rgb([0_u8, 20, 200])).save(&original)?;
    let report = import_input(&original, &work, &ImportOptions::default())?;
    let document_before = fs::read(&report.document)?;
    let page_before = fs::read(work.join(&report.pages[0].image))?;
    let incoming = temp.path().join("annotated.pdf");
    fs::write(&incoming, annotation_pdf([10, 0, 0, 10, 0, 0])?)?;
    let options = ImportOptions {
        dpi: 72,
        max_pixels: 249_999,
        ..ImportOptions::default()
    };
    assert!(matches!(
        import_input(&incoming, &work, &options),
        Err(IoError::PixelBudget {
            required: 250_000,
            limit: 249_999
        })
    ));
    assert_eq!(fs::read(&report.document)?, document_before);
    assert_eq!(fs::read(work.join(&report.pages[0].image))?, page_before);
    assert!(!work.join(".revayat-lock").exists());
    Ok(())
}

#[test]
fn annotation_import_keeps_native_pixels_and_paper_dimensions()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("annotated.pdf");
    let work = temp.path().join("chapter");
    fs::write(&source, annotation_pdf([10, 0, 0, 10, 0, 0])?)?;
    let options = ImportOptions {
        dpi: 72,
        max_pixels: 250_000,
        ..ImportOptions::default()
    };
    let report = import_input(&source, &work, &options)?;
    assert_eq!((report.pages[0].width, report.pages[0].height), (500, 500));
    assert_eq!(report.pages[0].pdf_points, Some([50.0, 50.0]));
    let image = image::open(work.join(&report.pages[0].image))?.to_rgb8();
    assert!(image.pixels().any(|pixel| pixel[0] > 200 && pixel[1] < 30));
    Ok(())
}

#[test]
fn corrupt_pdf_image_is_refused_without_replacing_the_import()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("source.png");
    let work = temp.path().join("chapter");
    ImageBuffer::from_pixel(8, 6, Rgb([0_u8, 20, 200])).save(&source)?;
    let original = import_input(&source, &work, &ImportOptions::default())?;
    let before = fs::read(&original.document)?;
    let original_page = fs::read(work.join(&original.pages[0].image))?;
    let mut pdf = Document::load_mem(&annotation_pdf([1, 0, 0, 1, 0, 0])?)?;
    for object in pdf.objects.values_mut() {
        if let Ok(stream) = object.as_stream_mut()
            && stream.dict.get(b"Subtype").and_then(Object::as_name).ok() == Some(b"Image")
        {
            stream.dict.set("Filter", "DCTDecode");
            stream.content = b"This is not a JPEG image".to_vec();
        }
    }
    let input = temp.path().join("damaged.pdf");
    pdf.save(&input)?;
    let result = import_input(
        &input,
        &work,
        &ImportOptions {
            dpi: 72,
            max_pixels: 250_000,
            ..ImportOptions::default()
        },
    );
    assert!(
        result.is_err(),
        "a skipped PDF image must not become a blank immutable page"
    );
    assert_eq!(fs::read(&original.document)?, before);
    assert_eq!(
        fs::read(work.join(&original.pages[0].image))?,
        original_page
    );
    assert!(!work.join(".revayat-lock").exists());
    Ok(())
}

#[test]
fn unresolved_pdf_annotation_is_refused_before_publishing_blank_artwork()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let input = temp.path().join("unresolved.pdf");
    let work = temp.path().join("chapter");
    let mut pdf = Document::load_mem(&annotation_pdf_with_settings([1, 0, 0, 1, 0, 0], 4, true)?)?;
    for object in pdf.objects.values_mut() {
        if let Ok(dict) = object.as_dict_mut()
            && dict.get(b"Type").and_then(Object::as_name).ok() == Some(b"Annot")
        {
            let states = dict
                .get_mut(b"AP")?
                .as_dict_mut()?
                .get_mut(b"N")?
                .as_dict_mut()?;
            let appearance = states.get(b"Off")?.clone();
            states.remove(b"Off");
            states.set("Unselected", appearance);
        }
    }
    pdf.save(&input)?;
    let result = import_input(&input, &work, &ImportOptions::default());
    assert!(
        result.is_err(),
        "an unresolved visible appearance must not be silently dropped"
    );
    assert!(!work.join("comic.json").exists());
    assert!(!work.join("pages").exists());
    Ok(())
}

fn text_pdf(font: lopdf::Dictionary) -> Result<Vec<u8>, lopdf::Error> {
    let mut pdf = Document::with_version("1.7");
    let pages = pdf.new_object_id();
    let font = pdf.add_object(font);
    let content = pdf.add_object(Stream::new(
        dictionary! {},
        b"BT /F1 12 Tf 5 20 Td (Comic) Tj ET".to_vec(),
    ));
    let page = pdf.add_object(dictionary! {
        "Type" => "Page", "Parent" => pages,
        "MediaBox" => vec![0.into(), 0.into(), 50.into(), 50.into()],
        "Resources" => dictionary! { "Font" => dictionary! { "F1" => font } },
        "Contents" => content
    });
    pdf.objects.insert(
        pages,
        Object::Dictionary(dictionary! {
            "Type" => "Pages", "Kids" => vec![page.into()], "Count" => 1
        }),
    );
    let root = pdf.add_object(dictionary! { "Type" => "Catalog", "Pages" => pages });
    pdf.trailer.set("Root", root);
    let mut data = Vec::new();
    pdf.save_to(&mut data)?;
    Ok(data)
}

#[test]
fn unavailable_pdf_font_cannot_silently_remove_text() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("unavailable-font.pdf");
    let work = temp.path().join("chapter");
    let data = text_pdf(dictionary! {
        "Type" => "Font", "Subtype" => "Type0", "BaseFont" => "Missing",
        "Encoding" => "Identity-H", "DescendantFonts" => Vec::<Object>::new()
    })?;
    fs::write(&source, data)?;
    assert!(import_input(&source, &work, &ImportOptions::default()).is_err());
    assert!(!work.join("comic.json").exists());
    assert!(!work.join("pages").exists());
    Ok(())
}

#[test]
fn supported_standard_pdf_font_still_renders_text() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let source = temp.path().join("standard-font.pdf");
    let work = temp.path().join("chapter");
    let data = text_pdf(dictionary! {
        "Type" => "Font", "Subtype" => "Type1", "BaseFont" => "Helvetica"
    })?;
    fs::write(&source, data)?;
    let report = import_input(
        &source,
        &work,
        &ImportOptions {
            dpi: 72,
            ..ImportOptions::default()
        },
    )?;
    let image = image::open(work.join(&report.pages[0].image))?.to_rgb8();
    assert_eq!(image.dimensions(), (50, 50));
    assert!(image.pixels().any(|pixel| pixel[0] < 50));
    Ok(())
}
