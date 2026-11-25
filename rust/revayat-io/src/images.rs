use std::{io::Cursor, path::Path};

use image::{
    AnimationDecoder, DynamicImage, ImageDecoder, ImageFormat, ImageReader, Limits, RgbImage,
    codecs::{gif::GifDecoder, png::PngDecoder, webp::WebPDecoder},
};
use serde::Serialize;

mod native;
pub use native::{compose_original, count_changed_outside_mask, validate_preservation_image};

use crate::{
    IoError,
    fsutil::{digest, read_file},
    geometry::validate_pixels,
    inputs::{MAX_MEMBER_BYTES, MAX_PAGE_PIXELS},
    invalid,
};

pub fn image_extension(path: &Path) -> Option<String> {
    let suffix = path.extension()?.to_str()?.to_ascii_lowercase();
    matches!(
        suffix.as_str(),
        "png" | "jpg" | "jpeg" | "webp" | "bmp" | "tif" | "tiff" | "gif"
    )
    .then_some(suffix)
}

fn reject_extra_frames<'a>(decoder: impl AnimationDecoder<'a>) -> Result<(), IoError> {
    let mut frames = decoder.into_frames();
    frames
        .next()
        .ok_or_else(|| invalid("Image has no frames"))??;
    if frames.next().is_some() {
        return Err(IoError::AnimatedImage);
    }
    Ok(())
}

pub fn decode_image(data: &[u8], max_pixels: u64) -> Result<DynamicImage, IoError> {
    if data.len() as u64 > MAX_MEMBER_BYTES {
        return Err(invalid("Image exceeds the encoded-byte limit"));
    }
    let max_pixels = max_pixels.min(MAX_PAGE_PIXELS);
    let format = image::guess_format(data)?;
    let mut reader = ImageReader::with_format(Cursor::new(data), format);
    let mut limits = Limits::default();
    limits.max_alloc = Some(max_pixels.saturating_mul(12).saturating_add(16 << 20));
    reader.limits(limits.clone());
    let decoder = reader.into_decoder()?;
    let (width, height) = decoder.dimensions();
    validate_pixels(width, height, max_pixels)?;
    match format {
        ImageFormat::Gif => {
            let mut animated = GifDecoder::new(Cursor::new(data))?;
            animated.set_limits(limits)?;
            reject_extra_frames(animated)?;
        }
        ImageFormat::Png => {
            let mut animated = PngDecoder::new(Cursor::new(data))?;
            animated.set_limits(limits)?;
            if animated.is_apng()? {
                reject_extra_frames(animated.apng()?)?;
            }
        }
        ImageFormat::WebP => {
            let mut animated = WebPDecoder::new(Cursor::new(data))?;
            if animated.has_animation() {
                animated.set_limits(limits)?;
                reject_extra_frames(animated)?;
            }
        }
        ImageFormat::Tiff => {
            let tiff = tiff::decoder::Decoder::new(Cursor::new(data))
                .map_err(|e| invalid(format!("Unreadable TIFF: {e}")))?;
            if tiff.more_images() {
                return Err(IoError::AnimatedImage);
            }
        }
        _ => {}
    }
    Ok(DynamicImage::from_decoder(decoder)?)
}

pub fn load_image(path: &Path, max_pixels: u64) -> Result<DynamicImage, IoError> {
    decode_image(&read_file(path, MAX_MEMBER_BYTES)?, max_pixels)
}

pub(crate) fn png_bytes(image: DynamicImage) -> Result<Vec<u8>, IoError> {
    let mut bytes = Cursor::new(Vec::new());
    image.write_to(&mut bytes, ImageFormat::Png)?;
    Ok(bytes.into_inner())
}

pub fn pixel_digest(image: &RgbImage) -> String {
    digest(image.as_raw())
}

pub fn appearance(image: &RgbImage) -> String {
    use std::fmt::Write as _;
    let reduced = image::imageops::resize(image, 16, 16, image::imageops::FilterType::Triangle);
    reduced
        .as_raw()
        .iter()
        .fold(String::with_capacity(1536), |mut out, byte| {
            let _ = write!(out, "{byte:02x}");
            out
        })
}

#[derive(Debug, Serialize)]
pub struct ImageAnalysis {
    pub width: u32,
    pub height: u32,
    pub sha256: String,
    pub pixel_sha256: String,
    pub rgb_metrics: [u64; 5],
    pub grayscale_histogram: Vec<usize>,
}

pub fn analyze_image(data: &[u8], max_pixels: u64) -> Result<ImageAnalysis, IoError> {
    let image = decode_image(data, max_pixels)?.into_rgb8();
    Ok(ImageAnalysis {
        width: image.width(),
        height: image.height(),
        sha256: digest(data),
        pixel_sha256: pixel_digest(&image),
        rgb_metrics: packcore_rs::port::analyze_rgb_page(image.as_raw()),
        grayscale_histogram: packcore_rs::port::compute_grayscale_histogram(image.as_raw())
            .to_vec(),
    })
}

pub fn pixels_identical(a: &RgbImage, b: &RgbImage) -> Result<bool, IoError> {
    if a.dimensions() != b.dimensions() {
        return Ok(false);
    }
    let count = (u64::from(a.width()) * u64::from(a.height())) as usize;
    let mask = vec![0; count];
    let changed = pixcore_rs::port::outside_mask_diff(
        a.as_raw(),
        b.as_raw(),
        &mask,
        i64::from(a.width()),
        i64::from(a.height()),
        0,
    )
    .map_err(invalid)?;
    Ok(changed.first() == Some(&0))
}
