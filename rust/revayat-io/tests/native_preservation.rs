#![forbid(unsafe_code)]

use image::{DynamicImage, GrayImage, ImageBuffer, Luma, LumaA, Rgb, RgbImage, Rgba};
use revayat_io::images::{
    compose_original, count_changed_outside_mask, validate_preservation_image,
};

fn variants() -> Vec<DynamicImage> {
    vec![
        DynamicImage::ImageLuma8(ImageBuffer::from_fn(3, 2, |x, y| {
            Luma([37 + x as u8 + y as u8])
        })),
        DynamicImage::ImageLumaA8(ImageBuffer::from_fn(3, 2, |x, y| {
            LumaA([37 + x as u8, y as u8 * 127])
        })),
        DynamicImage::ImageRgb8(ImageBuffer::from_fn(3, 2, |x, y| {
            Rgb([37 + x as u8, 90 + y as u8, 150])
        })),
        DynamicImage::ImageRgba8(ImageBuffer::from_fn(3, 2, |x, y| {
            Rgba([37 + x as u8, 90 + y as u8, 150, x as u8 * 127])
        })),
        DynamicImage::ImageLuma16(ImageBuffer::from_fn(3, 2, |x, y| {
            Luma([10_001 + x as u16 + y as u16])
        })),
        DynamicImage::ImageLumaA16(ImageBuffer::from_fn(3, 2, |x, y| {
            LumaA([10_001 + x as u16, y as u16 * 32_771])
        })),
        DynamicImage::ImageRgb16(ImageBuffer::from_fn(3, 2, |x, y| {
            Rgb([10_001 + x as u16, 20_003 + y as u16, 50_007])
        })),
        DynamicImage::ImageRgba16(ImageBuffer::from_fn(3, 2, |x, y| {
            Rgba([
                10_001 + x as u16,
                20_003 + y as u16,
                50_007,
                x as u16 * 32_767,
            ])
        })),
    ]
}

#[test]
fn no_op_preserves_every_native_png_sample_and_color_type() -> Result<(), Box<dyn std::error::Error>>
{
    for original in variants() {
        for mask in [0, 255] {
            let before = original.clone();
            let result = compose_original(
                &original,
                &original.to_rgb8(),
                &GrayImage::from_pixel(3, 2, Luma([mask])),
            )?;
            assert_eq!(result.color(), original.color());
            assert_eq!(result.as_bytes(), original.as_bytes());
            assert_eq!(original, before);
        }
    }
    Ok(())
}

#[test]
fn authorized_rgb_edits_retain_native_samples_and_alpha_elsewhere()
-> Result<(), Box<dyn std::error::Error>> {
    for original in variants() {
        let mut edited = original.to_rgb8();
        edited.put_pixel(0, 0, Rgb([210, 80, 30]));
        edited.put_pixel(2, 1, Rgb([0, 0, 0]));
        let mut mask = GrayImage::new(3, 2);
        mask.put_pixel(0, 0, Luma([1]));
        let result = compose_original(&original, &edited, &mask)?;
        let source = original.to_rgba16();
        let actual = result.to_rgba16();
        for (x, y, pixel) in actual.enumerate_pixels() {
            assert_eq!(
                pixel[3],
                source.get_pixel(x, y)[3],
                "alpha must remain exact even inside an edit"
            );
            if (x, y) != (0, 0) {
                assert_eq!(
                    pixel,
                    source.get_pixel(x, y),
                    "native samples outside the mask must remain exact"
                );
            }
        }
        assert_eq!(result.to_rgb8().get_pixel(0, 0), &Rgb([210, 80, 30]));
        assert_eq!(count_changed_outside_mask(&original, &result, &mask)?, 0);
    }
    Ok(())
}

#[test]
fn grayscale_color_promotion_preserves_depth_and_native_alpha()
-> Result<(), Box<dyn std::error::Error>> {
    let original = DynamicImage::ImageLumaA16(
        ImageBuffer::from_raw(2, 1, vec![10_001, 12_345, 40_007, 0]).ok_or("fixture size")?,
    );
    let mut edited = original.to_rgb8();
    edited.put_pixel(0, 0, Rgb([250, 30, 10]));
    let allowed = GrayImage::from_raw(2, 1, vec![255, 0]).ok_or("fixture mask")?;
    let result = compose_original(&original, &edited, &allowed)?;
    let DynamicImage::ImageRgba16(result) = result else {
        return Err("colored grayscale edits must promote at the original 16-bit depth".into());
    };
    assert_eq!(
        result.get_pixel(0, 0),
        &Rgba([250 * 257, 30 * 257, 10 * 257, 12_345])
    );
    assert_eq!(result.get_pixel(1, 0), &Rgba([40_007, 40_007, 40_007, 0]));
    Ok(())
}

#[test]
fn monochrome_edit_preserves_grayscale_format() -> Result<(), Box<dyn std::error::Error>> {
    let original = DynamicImage::ImageLuma16(
        ImageBuffer::from_raw(2, 1, vec![10_001, 40_007]).ok_or("fixture size")?,
    );
    let edited = RgbImage::from_pixel(2, 1, Rgb([255, 255, 255]));
    let result = compose_original(
        &original,
        &edited,
        &GrayImage::from_raw(2, 1, vec![255, 0]).ok_or("fixture mask")?,
    )?;
    let DynamicImage::ImageLuma16(result) = result else {
        return Err("monochrome edits must retain grayscale format and depth".into());
    };
    assert_eq!(result.as_raw(), &[65_535, 40_007]);
    Ok(())
}

#[test]
fn native_comparison_detects_hidden_rgb_alpha_and_low_bit_changes()
-> Result<(), Box<dyn std::error::Error>> {
    let original = DynamicImage::ImageRgba16(
        ImageBuffer::from_raw(
            3,
            1,
            vec![
                10_001, 20_003, 50_007, 0, 10_001, 20_003, 50_007, 12_345, 10_001, 20_003, 50_007,
                65_535,
            ],
        )
        .ok_or("fixture size")?,
    );
    let mut candidate = original.to_rgba16();
    candidate.get_pixel_mut(0, 0)[0] += 1;
    candidate.get_pixel_mut(1, 0)[3] += 1;
    candidate.get_pixel_mut(2, 0)[2] += 1;
    let candidate = DynamicImage::ImageRgba16(candidate);
    assert_eq!(original.to_rgb8(), candidate.to_rgb8());
    assert_eq!(
        count_changed_outside_mask(&original, &candidate, &GrayImage::new(3, 1))?,
        3
    );
    assert_eq!(
        count_changed_outside_mask(
            &original,
            &candidate,
            &GrayImage::from_raw(3, 1, vec![0, 255, 0]).ok_or("fixture mask")?
        )?,
        2
    );
    Ok(())
}

#[test]
fn native_comparison_normalizes_equivalent_sample_formats_exactly()
-> Result<(), Box<dyn std::error::Error>> {
    let original = DynamicImage::ImageLuma8(GrayImage::from_pixel(2, 1, Luma([37])));
    let promoted = DynamicImage::ImageRgba16(ImageBuffer::from_pixel(
        2,
        1,
        Rgba([37 * 257, 37 * 257, 37 * 257, 65_535]),
    ));
    assert_eq!(
        count_changed_outside_mask(&original, &promoted, &GrayImage::new(2, 1))?,
        0
    );
    Ok(())
}

#[test]
fn native_helpers_refuse_mismatched_dimensions_and_float_sources() {
    let original = DynamicImage::new_rgb8(2, 2);
    assert!(compose_original(&original, &RgbImage::new(1, 2), &GrayImage::new(2, 2)).is_err());
    assert!(compose_original(&original, &RgbImage::new(2, 2), &GrayImage::new(2, 1)).is_err());
    assert!(
        count_changed_outside_mask(
            &original,
            &DynamicImage::new_rgb8(1, 2),
            &GrayImage::new(2, 2)
        )
        .is_err()
    );
    assert!(count_changed_outside_mask(&original, &original, &GrayImage::new(2, 1)).is_err());
    for original in [
        DynamicImage::new_rgb32f(2, 2),
        DynamicImage::new_rgba32f(2, 2),
    ] {
        assert!(validate_preservation_image(&original).is_err());
        assert!(compose_original(&original, &RgbImage::new(2, 2), &GrayImage::new(2, 2)).is_err());
        assert!(count_changed_outside_mask(&original, &original, &GrayImage::new(2, 2)).is_err());
    }
}
