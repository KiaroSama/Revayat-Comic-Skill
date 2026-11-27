use image::{GrayImage, Luma, Rgb, RgbImage};
use revayat_vision::{
    Rect, Result, clean,
    masks::{self, Balloon, MaskOptions},
};

fn authorization(page: &RgbImage, bounds: Rect, dark: bool) -> Result<(GrayImage, RgbImage)> {
    let mask = masks::region_mask(
        page,
        bounds,
        None,
        dark,
        MaskOptions {
            full_balloon: false,
            ..Default::default()
        },
    )?;
    let mut authorized = GrayImage::new(page.width(), page.height());
    mask.apply_to(&mut authorized)?;
    let (cleaned, _) = clean::clean_region(page, &mask, None, None)?;
    Ok((authorized, cleaned))
}

#[test]
fn free_lettering_preserves_support_for_faint_source_ink() -> Result<()> {
    for dark in [false, true] {
        let [paper, ink] = [245, 200].map(|value| if dark { 255 - value } else { value });
        let mut page = RgbImage::from_pixel(100, 80, Rgb([paper; 3]));
        for y in 35..42 {
            for x in 40..46 {
                page.put_pixel(x, y, Rgb([ink; 3]));
            }
        }
        let (allowed, cleaned) = authorization(&page, Rect([35, 30, 20, 20]), dark)?;
        assert_eq!(allowed.get_pixel(42, 38), &Luma([255]));
        assert_eq!(cleaned.get_pixel(42, 38), &Rgb([paper; 3]));
    }
    Ok(())
}

#[test]
fn free_lettering_does_not_classify_midgray_paper_as_connected_art() -> Result<()> {
    for dark in [false, true] {
        let [paper, ink] = [160, 20].map(|value| if dark { 255 - value } else { value });
        let mut page = RgbImage::from_pixel(100, 80, Rgb([paper; 3]));
        for y in 35..42 {
            for x in 40..46 {
                page.put_pixel(x, y, Rgb([ink; 3]));
            }
        }
        let (allowed, cleaned) = authorization(&page, Rect([35, 30, 20, 20]), dark)?;
        assert_eq!(allowed.get_pixel(42, 38), &Luma([255]));
        assert_eq!(cleaned.get_pixel(42, 38), &Rgb([paper; 3]));
    }
    Ok(())
}

#[test]
fn adaptive_paper_guard_still_protects_art_crossing_the_text_anchor() -> Result<()> {
    for (paper, ink, art) in [(245, 200, 150), (160, 20, 100)] {
        let mut page = RgbImage::from_pixel(100, 80, Rgb([paper; 3]));
        for y in 35..42 {
            for x in 43..49 {
                page.put_pixel(x, y, Rgb([ink; 3]));
            }
        }
        for y in 20..60 {
            page.put_pixel(51, y, Rgb([art; 3]));
        }
        let local = masks::region_mask(
            &page,
            Rect([35, 30, 20, 20]),
            None,
            false,
            MaskOptions {
                grow: 0.2,
                full_balloon: false,
                ..Default::default()
            },
        )?;
        let mut allowed = GrayImage::new(page.width(), page.height());
        local.apply_to(&mut allowed)?;
        let (cleaned, _) = clean::clean_region(&page, &local, None, None)?;
        assert_eq!(allowed.get_pixel(46, 38), &Luma([255]));
        for y in 20..60 {
            assert_eq!(allowed.get_pixel(51, y), &Luma([0]));
            assert_eq!(cleaned.get_pixel(51, y), page.get_pixel(51, y));
        }
        for (x, y, pixel) in page.enumerate_pixels() {
            if allowed.get_pixel(x, y)[0] == 0 {
                assert_eq!(cleaned.get_pixel(x, y), pixel);
            }
        }
    }
    Ok(())
}

#[test]
fn saved_search_window_cannot_promote_the_whole_panel_to_a_balloon() -> Result<()> {
    let panel = Rect([5, 5, 190, 170]);
    let text = Rect([80, 70, 40, 35]);
    let page = RgbImage::from_fn(200, 180, |x, y| {
        let paper = (9..191).contains(&x) && (9..171).contains(&y);
        let source_ink = (85..95).contains(&x) && (80..87).contains(&y);
        let artwork = (40..55).contains(&x) && (35..50).contains(&y);
        Rgb([if paper && !source_ink && !artwork {
            245
        } else {
            20
        }; 3])
    });
    let luma = masks::page_luminance(&page);
    assert!(masks::resolve_balloon_with_interior(&luma, text, None, Some(panel), false)?.is_none());
    let saved = Balloon {
        bounds: panel,
        text_bounds: text,
        dark: false,
    };
    assert!(
        masks::resolve_balloon_with_interior(&luma, text, Some(saved), Some(panel), false)?
            .is_none(),
        "cached search geometry must not waive the live component's size/coverage checks"
    );
    Ok(())
}
