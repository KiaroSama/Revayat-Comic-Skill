#![forbid(unsafe_code)]

use image::{Rgb, RgbImage};
use revayat_vision::{
    Rect, Result, qa,
    typefont::Shaper,
    typeset::{self, TextRegion},
};

fn hyphenated_render(target: &str) -> Result<(RgbImage, TextRegion, typeset::TypesetPage)> {
    let clean = RgbImage::from_pixel(200, 400, Rgb([245; 3]));
    let mut region = TextRegion::new("hyphen", Rect([50, 20, 78, 360]), target);
    region.rtl_target = true;
    region.style.medium = true;
    let rendered = typeset::typeset_page(&clean, &[region.clone()])?;
    Ok((clean, region, rendered))
}

fn missing(
    target: &str,
    clean: &RgbImage,
    region: &TextRegion,
    rendered: &typeset::TypesetPage,
) -> Result<usize> {
    let placed = &rendered.regions[0];
    qa::missing_clusters_in_direction(
        &mut Shaper::new()?,
        target,
        &placed.lines,
        placed.font_size,
        &region.style,
        clean,
        &rendered.image,
        true,
    )
}

#[test]
fn a_separate_authored_hyphen_space_does_not_invalidate_compound_wrapping() -> Result<()> {
    let target = "کاگاری-سان؟! نام- خانوادگی";
    let (clean, region, rendered) = hyphenated_render(target)?;
    let placed = &rendered.regions[0];
    assert!(placed.lines.len() >= 3);
    assert!(placed.lines.iter().any(|line| line.text.ends_with('-')));
    assert_eq!(
        missing(target, &clean, &region, &rendered)?,
        0,
        "authored spaces elsewhere do not alter a soft hyphen wrap"
    );
    Ok(())
}

#[test]
fn directional_isolates_do_not_hide_a_soft_hyphen_wrap_from_glyph_proof() -> Result<()> {
    let target = "\u{2067}کاگاری-سان؟!\u{2069}";
    let (clean, region, rendered) = hyphenated_render(target)?;
    let placed = &rendered.regions[0];
    assert!(placed.lines.len() >= 2);
    assert!(
        placed
            .lines
            .iter()
            .any(|line| line.text.contains("-\u{2069}"))
    );
    assert_eq!(
        missing(target, &clean, &region, &rendered)?,
        0,
        "reopened direction isolates are not logical word separators"
    );
    Ok(())
}

#[test]
fn a_digit_prefix_in_a_persian_hyphen_part_keeps_its_glyph_proof() -> Result<()> {
    let target = "کاگاری-3سان؟!";
    let (clean, region, rendered) = hyphenated_render(target)?;
    let placed = &rendered.regions[0];
    assert!(placed.lines.len() >= 2);
    assert!(placed.lines.iter().any(|line| line.text.ends_with('-')));
    assert_eq!(
        missing(target, &clean, &region, &rendered)?,
        0,
        "a digit inside a valid Persian compound is preserved"
    );
    Ok(())
}

#[test]
fn an_authored_hyphen_space_keeps_its_original_boundary() -> Result<()> {
    let target = "نام- خانوادگی";
    let (clean, region, rendered) = hyphenated_render(target)?;
    assert!(rendered.regions[0].lines.len() >= 2);
    assert_eq!(missing(target, &clean, &region, &rendered)?, 0);
    Ok(())
}

#[test]
fn compound_wrap_proof_still_rejects_changed_words_and_join_controls() -> Result<()> {
    let target = "کاگاری-سان؟! میرود";
    let (clean, region, rendered) = hyphenated_render(target)?;
    assert_eq!(missing(target, &clean, &region, &rendered)?, 0);
    for authored in [
        "کاگاریسان؟! میرود",
        "کاگاری-سان؟! می رود",
        "کاگاری-سان؟! می\u{200c}رود",
        "کاگاری-سان؟! می\u{200d}رود",
        "کاگاری-سان؟! میرود!",
    ] {
        assert!(
            missing(authored, &clean, &region, &rendered)? > 0,
            "the delivered raster must not prove changed authored text: {authored}"
        );
    }
    Ok(())
}

#[test]
fn compound_wrap_proof_still_rejects_erased_line_pixels() -> Result<()> {
    let target = "کاگاری-سان؟!";
    let (clean, region, mut rendered) = hyphenated_render(target)?;
    assert_eq!(missing(target, &clean, &region, &rendered)?, 0);
    let erased = rendered.regions[0].lines[0].bbox;
    for y in erased.y()..erased.bottom() {
        for x in erased.x()..erased.right() {
            rendered.image.put_pixel(x, y, *clean.get_pixel(x, y));
        }
    }
    assert!(missing(target, &clean, &region, &rendered)? > 0);
    Ok(())
}
