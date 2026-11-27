#![forbid(unsafe_code)]

use image::{GrayImage, Luma, Rgb, RgbImage};
use revayat_vision::{
    Rect, Result, clean, masks, qa, qachecks,
    typefont::Shaper,
    typeset::{self, TextRegion},
    typestyle::TextStyle,
};

#[test]
fn rtl_target_places_period_left_of_digit_while_keeping_decimals_intact() -> Result<()> {
    let page = RgbImage::from_pixel(220, 100, Rgb([245; 3]));
    let mut rtl_num = TextRegion::new("num_rtl", Rect([10, 10, 90, 80]), "3.");
    rtl_num.rtl_target = true;
    let mut ltr_num = TextRegion::new("num_ltr", Rect([115, 10, 90, 80]), "3.");
    ltr_num.rtl_target = false;
    let rendered = typeset::typeset_page(&page, &[rtl_num, ltr_num])?;

    let mut shaper = Shaper::new()?;
    let style = TextStyle::default();
    assert_eq!(
        qa::missing_clusters_in_direction(
            &mut shaper,
            "3.",
            &rendered.regions[0].lines,
            rendered.regions[0].font_size,
            &style,
            &page,
            &rendered.image,
            true,
        )?,
        0
    );

    // Compare actual rendered x-centroid of the smaller dot ink vs the larger digit '3'.
    let dot_is_left = |ink_box: Rect| -> bool {
        let mut left_ink = 0usize;
        let mut right_ink = 0usize;
        let mid = ink_box.x() + ink_box.width() / 2;
        for y in ink_box.y()..ink_box.bottom() {
            for x in ink_box.x()..ink_box.right() {
                if rendered.image.get_pixel(x, y)[0] < 200 {
                    if x < mid {
                        left_ink += 1;
                    } else {
                        right_ink += 1;
                    }
                }
            }
        }
        // The tall digit '3' has far more ink than the tiny dot '.'.
        // In RTL (".3"), the smaller dot is on the left, so right_ink > left_ink.
        right_ink > left_ink
    };
    assert!(
        dot_is_left(rendered.regions[0].ink_box),
        "Persian RTL '3.' should place '.' on the left of '3'"
    );
    assert!(
        !dot_is_left(rendered.regions[1].ink_box),
        "LTR '3.' should keep '.' on the right of '3'"
    );

    // Decimal control: 3.14 still fits and passes missing_clusters with rtl_target=true.
    let mut dec = TextRegion::new("dec", Rect([10, 10, 180, 80]), "3.14");
    dec.rtl_target = true;
    let dec_out = typeset::typeset_page(&page, &[dec])?;
    assert_eq!(
        qa::missing_clusters_in_direction(
            &mut shaper,
            "3.14",
            &dec_out.regions[0].lines,
            dec_out.regions[0].font_size,
            &style,
            &page,
            &dec_out.image,
            true,
        )?,
        0
    );
    Ok(())
}

#[test]
fn persian_hyphenated_word_wraps_after_hyphen_without_breaking_glyph_proof() -> Result<()> {
    let page = RgbImage::from_pixel(200, 180, Rgb([245; 3]));
    let mut region = TextRegion::new("hyphen", Rect([50, 20, 78, 140]), "کاگاری-سان؟!");
    region.rtl_target = true;
    region.style.medium = true;
    let rendered = typeset::typeset_page(&page, &[region.clone()])?;
    let placed = &rendered.regions[0];
    assert!(
        placed.lines.len() >= 2,
        "expected hyphen wrap in narrow bubble, got {:?}",
        placed.lines
    );
    assert!(
        placed.font_size >= 16.0,
        "expected generous font size after hyphen wrap, got {}",
        placed.font_size
    );
    let mut shaper = Shaper::new()?;
    assert_eq!(
        qa::missing_clusters_in_direction(
            &mut shaper,
            &region.text,
            &placed.lines,
            placed.font_size,
            &region.style,
            &page,
            &rendered.image,
            true,
        )?,
        0
    );
    Ok(())
}

#[test]
fn upper_lobe_multi_band_search_avoids_tiny_text_when_lower_neck_is_narrow() -> Result<()> {
    let page = RgbImage::from_pixel(200, 240, Rgb([245; 3]));
    let bounds = Rect([20, 20, 150, 200]);
    // Wide upper lobe (y=0..85, x=5..145) + long thin lower tail (y=85..200, x=60..90).
    let pixels = GrayImage::from_fn(150, 200, |x, y| {
        let inside = if y < 85 {
            (5..145).contains(&x)
        } else {
            (60..90).contains(&x)
        };
        Luma([if inside { 255 } else { 0 }])
    });
    let mut region = TextRegion::new("upper", Rect([50, 35, 80, 40]), "هومورا!");
    region.interior = Some(masks::RegionMask { bounds, pixels });
    region.rtl_target = true;
    let rendered = typeset::typeset_page(&page, &[region])?;
    assert!(
        rendered.regions[0].font_size >= 22.0,
        "expected full-size text in wide upper lobe, got {}",
        rendered.regions[0].font_size
    );
    Ok(())
}

#[test]
fn external_occupied_mask_prevents_deterministic_speech_overlap() -> Result<()> {
    let page = RgbImage::from_pixel(240, 200, Rgb([245; 3]));
    let mut occupied = GrayImage::new(240, 200);
    // Reserve upper half as external caption.
    for y in 20..95 {
        for x in 30..210 {
            occupied.put_pixel(x, y, Luma([255]));
        }
    }
    let bounds = Rect([20, 20, 200, 160]);
    let mut speech = TextRegion::new("speech", Rect([40, 110, 140, 50]), "پس بقیه هم زنده‌ان.");
    speech.interior = Some(masks::RegionMask {
        bounds,
        pixels: GrayImage::from_pixel(200, 160, Luma([255])),
    });
    speech.rtl_target = true;
    let rendered = typeset::typeset_page_with_occupied(&page, &[speech], Some(&occupied))?;
    let ext_box = Rect([30, 20, 180, 75]);
    assert!(
        rendered.regions[0].ink_box.intersection(ext_box).is_none(),
        "speech {:?} overlapped external {:?}",
        rendered.regions[0].ink_box,
        ext_box
    );
    // Deterministic TypesetPage.mask must not include the external region pixels.
    assert_eq!(rendered.mask.get_pixel(50, 40)[0], 0);
    Ok(())
}

#[test]
fn kept_dark_mark_excluded_before_otsu_still_cleans_faint_glyph_in_open_balloon() -> Result<()> {
    // Open balloon (touches right border) with a faint glyph (luma 200) and a kept dark mark (luma 20).
    let page = RgbImage::from_fn(180, 140, |x, y| {
        let in_paper = x >= 20 && (20..120).contains(&y);
        let kept_dark = (30..45).contains(&x) && (30..45).contains(&y);
        let faint_glyph = (80..115).contains(&x) && (60..78).contains(&y);
        let v = if !in_paper || kept_dark {
            20
        } else if faint_glyph {
            200
        } else {
            245
        };
        Rgb([v; 3])
    });
    let balloon = masks::Balloon {
        bounds: Rect([16, 16, 164, 108]),
        text_bounds: Rect([76, 56, 44, 26]),
        dark: false,
    };
    let excluded = [Rect([28, 28, 20, 20])];
    let cleaned = clean::clean_page_bubbles_with_external(&page, &[balloon], &excluded, None)?;
    // Kept dark mark stays untouched.
    assert_eq!(cleaned.image.get_pixel(35, 35), &Rgb([20; 3]));
    // Faint glyph inside text_bounds was actually cleaned (brighter than 230).
    assert!(
        cleaned.image.get_pixel(95, 68)[0] > 230,
        "faint glyph survived: {:?}",
        cleaned.image.get_pixel(95, 68)
    );
    Ok(())
}

#[test]
fn closed_balloon_cleanup_qa_catches_rim_ink_within_two_pixel_cleanup_inset() -> Result<()> {
    // Large 260x260 closed balloon where text_inset (~12 px) is much larger than cleanup inset (2 px).
    let original = RgbImage::from_fn(300, 300, |x, y| {
        let paper = (20..280).contains(&x) && (20..280).contains(&y);
        Rgb([if paper { 245 } else { 20 }; 3])
    });
    let mut cleaned = original.clone();
    // Place residual ink 4 px inside the rim (inside 2 px cleanup inset, outside 12 px text_inset).
    for y in 24..34 {
        for x in 24..34 {
            cleaned.put_pixel(x, y, Rgb([40; 3]));
        }
    }
    let balloon = masks::Balloon {
        bounds: Rect([16, 16, 268, 268]),
        text_bounds: Rect([100, 100, 80, 60]),
        dark: false,
    };
    let surviving = qachecks::full_balloon_surviving_ink(&original, &cleaned, balloon)?;
    assert!(
        surviving >= 50,
        "closed-balloon residual QA should catch rim ink at 4 px inside wall, got {surviving}"
    );
    Ok(())
}
