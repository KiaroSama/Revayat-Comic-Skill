use image::{DynamicImage, GrayImage, RgbImage};

use crate::{IoError, geometry::validate_pixels, inputs::MAX_PAGE_PIXELS, invalid};

/// Refuse source sample formats that cannot be preserved in a PNG processing artifact.
pub fn validate_preservation_image(image: &DynamicImage) -> Result<(), IoError> {
    if !matches!(
        image,
        DynamicImage::ImageLuma8(_)
            | DynamicImage::ImageLumaA8(_)
            | DynamicImage::ImageRgb8(_)
            | DynamicImage::ImageRgba8(_)
            | DynamicImage::ImageLuma16(_)
            | DynamicImage::ImageLumaA16(_)
            | DynamicImage::ImageRgb16(_)
            | DynamicImage::ImageRgba16(_)
    ) {
        return Err(invalid(format!(
            "Native pixel preservation requires 8-bit or 16-bit integer samples; {:?} cannot be processed losslessly",
            image.color()
        )));
    }
    validate_pixels(image.width(), image.height(), MAX_PAGE_PIXELS)
}

enum Samples<'a> {
    Eight(&'a [u8]),
    Sixteen(&'a [u16]),
}

struct NativeImage<'a> {
    samples: Samples<'a>,
    channels: usize,
}

impl<'a> NativeImage<'a> {
    fn new(image: &'a DynamicImage) -> Result<Self, IoError> {
        validate_preservation_image(image)?;
        let (samples, channels) = match image {
            DynamicImage::ImageLuma8(data) => (Samples::Eight(data.as_raw()), 1),
            DynamicImage::ImageLumaA8(data) => (Samples::Eight(data.as_raw()), 2),
            DynamicImage::ImageRgb8(data) => (Samples::Eight(data.as_raw()), 3),
            DynamicImage::ImageRgba8(data) => (Samples::Eight(data.as_raw()), 4),
            DynamicImage::ImageLuma16(data) => (Samples::Sixteen(data.as_raw()), 1),
            DynamicImage::ImageLumaA16(data) => (Samples::Sixteen(data.as_raw()), 2),
            DynamicImage::ImageRgb16(data) => (Samples::Sixteen(data.as_raw()), 3),
            DynamicImage::ImageRgba16(data) => (Samples::Sixteen(data.as_raw()), 4),
            _ => return Err(invalid("Unsupported native image samples")),
        };
        Ok(Self { samples, channels })
    }

    fn rgba16(&self, index: usize) -> [u16; 4] {
        let offset = index * self.channels;
        let sample = |channel| match &self.samples {
            Samples::Eight(data) => u16::from(data[offset + channel]) * 257,
            Samples::Sixteen(data) => data[offset + channel],
        };
        match self.channels {
            1 => [sample(0), sample(0), sample(0), u16::MAX],
            2 => [sample(0), sample(0), sample(0), sample(1)],
            3 => [sample(0), sample(1), sample(2), u16::MAX],
            _ => [sample(0), sample(1), sample(2), sample(3)],
        }
    }
}

fn rgb8_sample(value: u16) -> u8 {
    // Match image's rounded u16-to-u8 conversion without allocating an RGB8 copy.
    ((u32::from(value) + 128) / 257) as u8
}

fn replace_color<T>(
    samples: &mut [T],
    index: usize,
    channels: usize,
    original: [u16; 4],
    edited: &[u8],
    convert: impl Fn(u8) -> T,
) {
    let colors = if channels <= 2 { 1 } else { 3 };
    for channel in 0..colors {
        if rgb8_sample(original[channel]) != edited[channel] {
            samples[index * channels + channel] = convert(edited[channel]);
        }
    }
}

/// Composite authorized RGB8 edits into an exact copy of the native source samples.
///
/// A nonzero mask value permits edits; RGB8 blending is already complete when this is
/// called. Unchanged color channels retain their exact source values even inside the
/// mask, and alpha is always retained. A colored grayscale edit promotes the result
/// to RGB/RGBA at the original bit depth, preserving every unedited grayscale value.
pub fn compose_original(
    original: &DynamicImage,
    edited: &RgbImage,
    allowed: &GrayImage,
) -> Result<DynamicImage, IoError> {
    let native = NativeImage::new(original)?;
    if (original.width(), original.height()) != edited.dimensions()
        || edited.dimensions() != allowed.dimensions()
    {
        return Err(invalid(
            "Native composition requires matching page and mask dimensions",
        ));
    }
    let count = (u64::from(original.width()) * u64::from(original.height())) as usize;
    let promote = native.channels <= 2
        && (0..count).any(|index| {
            let color = &edited.as_raw()[index * 3..index * 3 + 3];
            allowed.as_raw()[index] != 0 && (color[0] != color[1] || color[1] != color[2])
        });
    let mut output = if promote {
        match original {
            DynamicImage::ImageLuma8(_) => DynamicImage::ImageRgb8(original.to_rgb8()),
            DynamicImage::ImageLumaA8(_) => DynamicImage::ImageRgba8(original.to_rgba8()),
            DynamicImage::ImageLuma16(_) => DynamicImage::ImageRgb16(original.to_rgb16()),
            DynamicImage::ImageLumaA16(_) => DynamicImage::ImageRgba16(original.to_rgba16()),
            _ => original.clone(),
        }
    } else {
        original.clone()
    };
    for index in 0..count {
        if allowed.as_raw()[index] == 0 {
            continue;
        }
        let color = &edited.as_raw()[index * 3..index * 3 + 3];
        let before = native.rgba16(index);
        let same = (0..3).all(|channel| rgb8_sample(before[channel]) == color[channel]);
        if same {
            continue;
        }
        match &mut output {
            DynamicImage::ImageLuma8(data) => {
                replace_color(data.as_mut(), index, 1, before, color, |v| v)
            }
            DynamicImage::ImageLumaA8(data) => {
                replace_color(data.as_mut(), index, 2, before, color, |v| v)
            }
            DynamicImage::ImageRgb8(data) => {
                replace_color(data.as_mut(), index, 3, before, color, |v| v)
            }
            DynamicImage::ImageRgba8(data) => {
                replace_color(data.as_mut(), index, 4, before, color, |v| v)
            }
            DynamicImage::ImageLuma16(data) => {
                replace_color(data.as_mut(), index, 1, before, color, |v| {
                    u16::from(v) * 257
                })
            }
            DynamicImage::ImageLumaA16(data) => {
                replace_color(data.as_mut(), index, 2, before, color, |v| {
                    u16::from(v) * 257
                })
            }
            DynamicImage::ImageRgb16(data) => {
                replace_color(data.as_mut(), index, 3, before, color, |v| {
                    u16::from(v) * 257
                })
            }
            DynamicImage::ImageRgba16(data) => {
                replace_color(data.as_mut(), index, 4, before, color, |v| {
                    u16::from(v) * 257
                })
            }
            _ => return Err(invalid("Unsupported native image samples")),
        }
    }
    Ok(output)
}

/// Count exact sample changes outside the mask, including alpha and hidden colors.
///
/// Integer samples are normalized to RGBA16 without rounding. Grayscale replication
/// and exact 8-to-16-bit expansion compare equal; lost low bits and lost alpha do not.
/// This reads native buffers directly instead of allocating full-page RGBA16 copies.
pub fn count_changed_outside_mask(
    original: &DynamicImage,
    candidate: &DynamicImage,
    allowed: &GrayImage,
) -> Result<u64, IoError> {
    let before = NativeImage::new(original)?;
    let after = NativeImage::new(candidate)?;
    let dimensions = (original.width(), original.height());
    if dimensions != (candidate.width(), candidate.height()) || dimensions != allowed.dimensions() {
        return Err(invalid(
            "Native comparison requires matching page and mask dimensions",
        ));
    }
    let count = (u64::from(original.width()) * u64::from(original.height())) as usize;
    Ok((0..count)
        .filter(|&index| {
            allowed.as_raw()[index] == 0 && before.rgba16(index) != after.rgba16(index)
        })
        .count() as u64)
}
