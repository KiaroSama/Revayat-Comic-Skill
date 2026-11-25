use std::{
    collections::HashSet,
    sync::{
        Arc,
        atomic::{AtomicU8, Ordering},
    },
};

#[path = "pdf_density.rs"]
mod density;
use density::Density;

use hayro::{
    RenderCache, RenderSettings,
    hayro_interpret::{InterpreterSettings, InterpreterWarning, TransformExt},
    hayro_syntax::{
        Pdf,
        content::{
            TypedIter,
            ops::{Transform, TypedInstruction},
        },
        object::{Array as PdfArray, Dict as PdfDict, Number, ObjectIdentifier, Rect},
    },
    kurbo::Affine,
    vello_cpu::{
        Pixmap, RasterizerSettings, RenderContext, Resources, TargetInit,
        color::palette::css::WHITE,
    },
};
use image::{DynamicImage, RgbImage, RgbaImage};
use lopdf::{Dictionary, Document, Object, ObjectId, Stream};
use serde::Serialize;

use crate::{
    IoError,
    geometry::{scaled_pixels, validate_paper, validate_pixels},
    images::{decode_image, png_bytes},
    inputs::MAX_PAGE_PIXELS,
    invalid,
};

const MAX_CONTENT: usize = 64 * 1024 * 1024;
const MAX_OPERATORS: usize = 500_000;
const MAX_DEPTH: usize = 32;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PdfInspection {
    pub paper: [f64; 2],
    pub media_box: [f64; 4],
    pub crop_box: [f64; 4],
    pub rotation: i64,
    pub native_scale: f64,
    pub pixel_width: u32,
    pub pixel_height: u32,
    pub required_pixels: u64,
    pub images: usize,
    pub stencils: usize,
}

#[derive(Debug, Clone, Copy)]
struct Sheet {
    paper: [f64; 2],
    media: [f64; 4],
    crop: [f64; 4],
    rotation: i64,
    user_unit: f64,
}

pub(crate) struct PdfDocument {
    doc: Document,
    render: Pdf,
    pages: Vec<ObjectId>,
}

impl PdfDocument {
    pub(crate) fn open(data: Vec<u8>) -> Result<Self, IoError> {
        let doc = Document::load_mem(&data)?;
        if doc.is_encrypted() {
            return Err(invalid("Encrypted PDFs are not supported"));
        }
        let render = Pdf::new(data).map_err(|e| invalid(format!("Cannot parse PDF: {e:?}")))?;
        let pages = doc.get_pages().into_values().collect::<Vec<_>>();
        if pages.len() != render.pages().len() {
            return Err(invalid("PDF parsers disagree about page count"));
        }
        Ok(Self { doc, render, pages })
    }

    pub(crate) fn len(&self) -> usize {
        self.pages.len()
    }

    fn number(&self, object: &Object) -> Result<f64, IoError> {
        match self.doc.dereference(object)?.1 {
            Object::Integer(n) => Ok(*n as f64),
            Object::Real(n) if n.is_finite() => Ok(f64::from(*n)),
            _ => Err(invalid("Invalid PDF graphics number")),
        }
    }

    fn get<'a>(&'a self, dict: &'a Dictionary, key: &[u8]) -> Result<Option<&'a Object>, IoError> {
        if !dict.has(key) {
            return Ok(None);
        }
        Ok(Some(self.doc.dereference(dict.get(key)?)?.1))
    }

    fn inherited<'a>(
        &'a self,
        mut dict: &'a Dictionary,
        key: &[u8],
    ) -> Result<Option<&'a Object>, IoError> {
        for _ in 0..MAX_DEPTH {
            if let Some(value) = self.get(dict, key)? {
                return Ok(Some(value));
            }
            match self.get(dict, b"Parent")? {
                Some(parent) => dict = parent.as_dict()?,
                None => return Ok(None),
            }
        }
        Err(invalid("PDF page tree is too deep or contains a cycle"))
    }

    fn sheet(&self, index: usize, dict: &Dictionary) -> Result<Sheet, IoError> {
        // Read box coordinates as Numbers; both libraries' Rect conveniences narrow them to f32.
        let (obj, generation) = *self
            .pages
            .get(index)
            .ok_or_else(|| invalid("PDF page index is out of range"))?;
        let exact = self
            .render
            .xref()
            .get::<PdfDict<'_>>(ObjectIdentifier::new(obj, i32::from(generation)))
            .ok_or_else(|| invalid("PDF parsers disagree about the page object"))?;
        let media = precise_box(exact.clone(), b"MediaBox")?
            .ok_or_else(|| invalid("PDF page has no MediaBox"))?;
        let crop = precise_box(exact.clone(), b"CropBox")?
            .unwrap_or(media)
            .intersect(media);
        let rotation = self
            .inherited(dict, b"Rotate")?
            .map(Object::as_i64)
            .transpose()?
            .unwrap_or(0)
            .rem_euclid(360);
        if rotation % 90 != 0 {
            return Err(invalid("PDF rotation must be a multiple of 90 degrees"));
        }
        let user_unit = exact.get::<Number>(b"UserUnit").map_or(1.0, |v| v.as_f64());
        if !user_unit.is_finite() || user_unit <= 0.0 {
            return Err(invalid("Invalid PDF UserUnit"));
        }
        let mut paper = [crop.width() * user_unit, crop.height() * user_unit];
        if rotation == 90 || rotation == 270 {
            paper.swap(0, 1);
        }
        Ok(Sheet {
            paper: validate_paper(paper)?,
            media: [media.x0, media.y0, media.x1, media.y1],
            crop: [crop.x0, crop.y0, crop.x1, crop.y1],
            rotation,
            user_unit,
        })
    }

    fn resources<'a>(&'a self, dict: &'a Dictionary) -> Result<Option<&'a Dictionary>, IoError> {
        self.inherited(dict, b"Resources")?
            .map(Object::as_dict)
            .transpose()
            .map_err(Into::into)
    }

    fn lookup<'a>(
        &'a self,
        resources: Option<&'a Dictionary>,
        category: &[u8],
        name: &[u8],
    ) -> Result<Option<&'a Object>, IoError> {
        match resources
            .map(|r| self.get(r, category))
            .transpose()?
            .flatten()
        {
            Some(group) => self.get(group.as_dict()?, name),
            None => Ok(None),
        }
    }

    fn page_content(&self, dict: &Dictionary) -> Result<Vec<u8>, IoError> {
        let mut data = Vec::new();
        if let Some(contents) = self.get(dict, b"Contents")? {
            match contents {
                Object::Stream(stream) => data = stream_bytes(stream, MAX_CONTENT)?,
                Object::Array(streams) => {
                    for entry in streams {
                        let room = MAX_CONTENT.saturating_sub(data.len()).saturating_sub(1);
                        data.extend(stream_bytes(
                            self.doc.dereference(entry)?.1.as_stream()?,
                            room,
                        )?);
                        data.push(b'\n');
                    }
                }
                _ => return Err(invalid("Invalid PDF page contents")),
            }
        }
        Ok(data)
    }

    pub(crate) fn inspection(
        &self,
        index: usize,
        dpi: u32,
        max_pixels: u64,
    ) -> Result<PdfInspection, IoError> {
        if dpi == 0 {
            return Err(invalid("PDF DPI must be a positive integer"));
        }
        let page = self
            .pages
            .get(index)
            .ok_or_else(|| invalid("PDF page index is out of range"))?;
        let dict = self.doc.get_dictionary(*page)?;
        let sheet = self.sheet(index, dict)?;
        let mut scan = Density {
            pdf: self,
            scale: f64::from(dpi) / 72.0,
            images: 0,
            stencils: 0,
            source_pixels: 0,
            operations: 0,
            active: HashSet::new(),
        };
        let matrix = Affine::scale(sheet.user_unit);
        let resources = self.resources(dict)?;
        scan.program(&self.page_content(dict)?, resources, matrix)?;
        scan.annotations(dict, resources, matrix)?;
        let [pixel_width, pixel_height] = scaled_pixels(sheet.paper, scan.scale, max_pixels)?;
        let required_pixels =
            (u64::from(pixel_width) * u64::from(pixel_height)).max(scan.source_pixels);
        if required_pixels > max_pixels {
            return Err(IoError::PixelBudget {
                required: required_pixels,
                limit: max_pixels,
            });
        }
        Ok(PdfInspection {
            paper: sheet.paper,
            media_box: sheet.media,
            crop_box: sheet.crop,
            rotation: sheet.rotation,
            native_scale: scan.scale,
            pixel_width,
            pixel_height,
            required_pixels,
            images: scan.images,
            stencils: scan.stencils,
        })
    }

    pub(crate) fn raster(
        &self,
        index: usize,
        inspection: &PdfInspection,
    ) -> Result<DynamicImage, IoError> {
        let w = u16::try_from(inspection.pixel_width)
            .map_err(|_| invalid("PDF width exceeds Hayro's raster dimension limit"))?;
        let h = u16::try_from(inspection.pixel_height)
            .map_err(|_| invalid("PDF height exceeds Hayro's raster dimension limit"))?;
        let page = self
            .render
            .pages()
            .get(index)
            .ok_or_else(|| invalid("PDF page index is out of range"))?;
        let dict = self.doc.get_dictionary(self.pages[index])?;
        let unit = self.sheet(index, dict)?.user_unit;
        let warnings = Arc::new(AtomicU8::new(0));
        let recorded = Arc::clone(&warnings);
        let settings = InterpreterSettings {
            warning_sink: Arc::new(move |warning| {
                let flag = match warning {
                    InterpreterWarning::UnsupportedFont => 1,
                    InterpreterWarning::ImageDecodeFailure => 2,
                    InterpreterWarning::UnresolvedAnnotationAppearance => 4,
                    _ => 8,
                };
                recorded.fetch_or(flag, Ordering::Relaxed);
            }),
            ..InterpreterSettings::default()
        };
        let mut context = RenderContext::new(w, h);
        hayro::render_into(
            page,
            &RenderCache::new(),
            &settings,
            &RenderSettings::default(),
            &mut context,
            Affine::scale(inspection.native_scale * unit) * page.initial_transform(true).to_kurbo(),
        );
        context.flush();
        let mut pixmap = Pixmap::new(w, h);
        context.render_with(
            &mut pixmap,
            &mut Resources::default(),
            RasterizerSettings {
                target_init: TargetInit::Clear(WHITE),
                ..Default::default()
            },
        );
        let warnings = warnings.load(Ordering::Relaxed);
        if warnings != 0 {
            let failures = [
                (1, "unsupported font"),
                (2, "image decode failure"),
                (4, "unresolved annotation appearance"),
                (8, "unsupported page content"),
            ]
            .into_iter()
            .filter_map(|(flag, description)| (warnings & flag != 0).then_some(description))
            .collect::<Vec<_>>();
            return Err(invalid(format!(
                "PDF page {} could not be preserved: {}",
                index + 1,
                failures.join(", ")
            )));
        }
        let pixels = pixmap
            .data()
            .iter()
            .flat_map(|color| [color.r, color.g, color.b])
            .collect::<Vec<_>>();
        RgbImage::from_raw(u32::from(w), u32::from(h), pixels)
            .map(DynamicImage::ImageRgb8)
            .ok_or_else(|| invalid("PDF renderer returned an incorrect raster size"))
    }

    pub(crate) fn import_page(
        &self,
        index: usize,
        dpi: u32,
        max_pixels: u64,
    ) -> Result<(Vec<u8>, [f64; 2]), IoError> {
        if dpi == 0 {
            return Err(invalid("PDF DPI must be a positive integer"));
        }
        let dict = self.doc.get_dictionary(self.pages[index])?;
        let sheet = self.sheet(index, dict)?;
        let cap = max_pixels.min(MAX_PAGE_PIXELS);
        let pixels = match self.plain_page(dict, sheet, cap)? {
            Some(image) => image,
            None => self.raster(index, &self.inspection(index, dpi, cap)?)?,
        };
        Ok((png_bytes(pixels)?, sheet.paper))
    }

    pub(crate) fn proof(
        &self,
        index: usize,
        width: u32,
        height: u32,
    ) -> Result<(DynamicImage, [f64; 2], bool), IoError> {
        let dict = self.doc.get_dictionary(
            *self
                .pages
                .get(index)
                .ok_or_else(|| invalid("PDF page index is out of range"))?,
        )?;
        let sheet = self.sheet(index, dict)?;
        if let Some(plain) = self.plain_page(dict, sheet, MAX_PAGE_PIXELS)? {
            return Ok((plain, sheet.paper, true));
        }
        let mut inspection = self.inspection(index, 72, MAX_PAGE_PIXELS)?;
        let scale = (f64::from(width) / sheet.paper[0])
            .max(f64::from(height) / sheet.paper[1])
            .max(inspection.native_scale);
        let [w, h] = scaled_pixels(sheet.paper, scale, MAX_PAGE_PIXELS)?;
        inspection.pixel_width = w;
        inspection.pixel_height = h;
        inspection.native_scale = scale;
        Ok((self.raster(index, &inspection)?, sheet.paper, false))
    }

    fn plain_page(
        &self,
        dict: &Dictionary,
        sheet: Sheet,
        max: u64,
    ) -> Result<Option<DynamicImage>, IoError> {
        if sheet.rotation != 0
            || sheet.crop != sheet.media
            || dict.has(b"Annots")
            || dict.has(b"Group")
        {
            return Ok(None);
        }
        let data = self.page_content(dict)?;
        let mut program = TypedIter::new(&data);
        if !matches!(program.next(), Some(TypedInstruction::SaveState(_))) {
            return Ok(None);
        }
        let Some(TypedInstruction::Transform(Transform(a, b, c, d, x, y))) = program.next() else {
            return Ok(None);
        };
        let [a, b, c, d, x, y] = [a, b, c, d, x, y].map(|n| n.as_f64());
        let Some(TypedInstruction::XObject(image)) = program.next() else {
            return Ok(None);
        };
        let name = image.0.to_vec();
        if !matches!(program.next(), Some(TypedInstruction::RestoreState(_)))
            || program.next().is_some()
        {
            return Ok(None);
        }
        let [x0, y0, x1, y1] = sheet.media;
        if b != 0.0
            || c != 0.0
            || a <= 0.0
            || d <= 0.0
            || [a - (x1 - x0), d - (y1 - y0), x - x0, y - y0]
                .iter()
                .any(|v| v.abs() > 0.0001)
        {
            return Ok(None);
        }
        let Some(stream) = self
            .lookup(self.resources(dict)?, b"XObject", &name)?
            .and_then(|o| o.as_stream().ok())
        else {
            return Ok(None);
        };
        if stream.dict.get(b"Subtype").and_then(Object::as_name).ok() != Some(b"Image")
            || stream.dict.has(b"ImageMask")
            || stream.dict.has(b"Mask")
            || stream.dict.has(b"Decode")
            || stream.dict.has(b"OC")
        {
            return Ok(None);
        }
        self.direct_image(stream, max)
    }

    fn direct_image(&self, stream: &Stream, max: u64) -> Result<Option<DynamicImage>, IoError> {
        let dict = &stream.dict;
        let color = self
            .get(dict, b"ColorSpace")?
            .and_then(|o| o.as_name().ok());
        let channels: u32 = match color {
            Some(b"DeviceRGB") => 3,
            Some(b"DeviceGray") => 1,
            _ => return Ok(None),
        };
        let bytes_per_sample = match self
            .get(dict, b"BitsPerComponent")?
            .and_then(|o| o.as_i64().ok())
        {
            Some(8) => 1,
            Some(16) => 2,
            _ => return Ok(None),
        };
        let [w, h] = self.image_size(dict)?;
        validate_pixels(w, h, max)?;
        let filters = stream.filters().unwrap_or_default();
        let alpha = self.get(dict, b"SMask")?;
        if filters.as_slice() == [b"DCTDecode".as_slice()] && alpha.is_none() {
            let image = decode_image(&stream.content, max)?;
            return if (image.width(), image.height()) == (w, h) {
                Ok(Some(image))
            } else {
                Ok(None)
            };
        }
        if !filters.is_empty() && filters.as_slice() != [b"FlateDecode".as_slice()] {
            return Ok(None);
        }
        let count = usize::try_from(u64::from(w) * u64::from(h))
            .map_err(|_| invalid("PDF image size is invalid"))?;
        let size = count
            .checked_mul(channels as usize * bytes_per_sample)
            .ok_or_else(|| invalid("PDF image size is invalid"))?;
        let bytes = stream_bytes(
            stream,
            size.checked_add(h as usize)
                .ok_or_else(|| invalid("PDF image size is invalid"))?,
        )?;
        if bytes.len() != size {
            return Err(invalid("PDF image stream does not match its dimensions"));
        }
        let alpha = alpha
            .map(|mask| -> Result<Option<Vec<u8>>, IoError> {
                let mask = mask.as_stream()?;
                if !is_plain_alpha(self, mask, w, h, bytes_per_sample)? {
                    return Ok(None);
                }
                let size = count * bytes_per_sample;
                let alpha = stream_bytes(mask, size + h as usize)?;
                if alpha.len() != size {
                    return Err(invalid("PDF alpha stream does not match image dimensions"));
                }
                Ok(Some(alpha))
            })
            .transpose()?;
        if matches!(alpha, Some(None)) {
            return Ok(None);
        }
        let alpha = alpha.flatten();
        let image = if bytes_per_sample == 2 {
            let samples = |bytes: &[u8]| {
                bytes
                    .as_chunks::<2>()
                    .0
                    .iter()
                    .map(|n| u16::from_be_bytes(*n))
                    .collect::<Vec<_>>()
            };
            let bytes = samples(&bytes);
            match (channels, alpha) {
                (1, Some(alpha)) => {
                    image::ImageBuffer::from_raw(w, h, merge_alpha(&bytes, &samples(&alpha), 1))
                        .map(DynamicImage::ImageLumaA16)
                }
                (3, Some(alpha)) => {
                    image::ImageBuffer::from_raw(w, h, merge_alpha(&bytes, &samples(&alpha), 3))
                        .map(DynamicImage::ImageRgba16)
                }
                (1, None) => {
                    image::ImageBuffer::from_raw(w, h, bytes).map(DynamicImage::ImageLuma16)
                }
                (_, _) => image::ImageBuffer::from_raw(w, h, bytes).map(DynamicImage::ImageRgb16),
            }
        } else {
            match (channels, alpha) {
                (1, Some(alpha)) => {
                    image::ImageBuffer::from_raw(w, h, merge_alpha(&bytes, &alpha, 1))
                        .map(DynamicImage::ImageLumaA8)
                }
                (3, Some(alpha)) => RgbaImage::from_raw(w, h, merge_alpha(&bytes, &alpha, 3))
                    .map(DynamicImage::ImageRgba8),
                (1, None) => image::GrayImage::from_raw(w, h, bytes).map(DynamicImage::ImageLuma8),
                (_, _) => RgbImage::from_raw(w, h, bytes).map(DynamicImage::ImageRgb8),
            }
        };
        Ok(image)
    }

    fn image_size(&self, dict: &Dictionary) -> Result<[u32; 2], IoError> {
        let one = |key: &[u8]| -> Result<u32, IoError> {
            let n = self
                .get(dict, key)?
                .ok_or_else(|| invalid("Missing PDF image dimensions"))?
                .as_i64()?;
            u32::try_from(n)
                .ok()
                .filter(|v| *v > 0)
                .ok_or_else(|| invalid("Invalid PDF image dimensions"))
        };
        Ok([one(b"Width")?, one(b"Height")?])
    }
}

fn precise_box(mut dict: PdfDict<'_>, key: &[u8]) -> Result<Option<Rect>, IoError> {
    for _ in 0..MAX_DEPTH {
        if let Some(array) = dict.get::<PdfArray<'_>>(key) {
            let coords = array
                .iter::<Number>()
                .map(|n| n.as_f64())
                .collect::<Vec<_>>();
            let [x0, y0, x1, y1] = *coords.as_slice() else {
                return Err(invalid("Invalid PDF paper box"));
            };
            if !coords.iter().all(|n| n.is_finite()) {
                return Err(invalid("Invalid PDF paper box"));
            }
            return Ok(Some(Rect::new(
                x0.min(x1),
                y0.min(y1),
                x0.max(x1),
                y0.max(y1),
            )));
        }
        if dict.keys().any(|name| name.as_ref() == key) {
            return Err(invalid("Invalid PDF paper box"));
        }
        let Some(parent) = dict.get::<PdfDict<'_>>(b"Parent") else {
            return Ok(None);
        };
        dict = parent;
    }
    Err(invalid("PDF page tree is too deep or contains a cycle"))
}

fn merge_alpha<T: Copy>(pixels: &[T], alpha: &[T], colors: usize) -> Vec<T> {
    pixels
        .chunks_exact(colors)
        .zip(alpha)
        .flat_map(|(pixel, a)| pixel.iter().chain([a]).copied())
        .collect()
}

fn is_plain_alpha(
    pdf: &PdfDocument,
    stream: &Stream,
    w: u32,
    h: u32,
    bytes_per_sample: usize,
) -> Result<bool, IoError> {
    Ok(pdf.image_size(&stream.dict)? == [w, h]
        && pdf
            .get(&stream.dict, b"ColorSpace")?
            .and_then(|o| o.as_name().ok())
            == Some(b"DeviceGray")
        && pdf
            .get(&stream.dict, b"BitsPerComponent")?
            .and_then(|o| o.as_i64().ok())
            == Some((bytes_per_sample * 8) as i64)
        && !stream.dict.has(b"Decode")
        && !stream.dict.has(b"Matte")
        && !stream.dict.has(b"SMask")
        && !stream.dict.has(b"Mask"))
}

fn stream_bytes(stream: &Stream, max: usize) -> Result<Vec<u8>, IoError> {
    if stream.dict.has(b"Filter") {
        Ok(stream.decompressed_content_with_limit(max)?)
    } else if stream.content.len() <= max {
        Ok(stream.content.clone())
    } else {
        Err(invalid("PDF stream exceeds the decoding limit"))
    }
}

fn matrix_values(pdf: &PdfDocument, items: &[Object]) -> Result<[f64; 6], IoError> {
    let [a, b, c, d, e, f] = items else {
        return Err(invalid("Invalid PDF transform"));
    };
    Ok([
        pdf.number(a)?,
        pdf.number(b)?,
        pdf.number(c)?,
        pdf.number(d)?,
        pdf.number(e)?,
        pdf.number(f)?,
    ])
}

pub fn inspect_pdf_page_density(
    data: &[u8],
    page_index: usize,
    dpi: u32,
    max_pixels: u64,
) -> Result<PdfInspection, IoError> {
    PdfDocument::open(data.to_vec())?.inspection(page_index, dpi, max_pixels)
}
