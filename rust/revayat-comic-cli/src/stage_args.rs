use clap::{Args, ValueEnum};
use std::path::PathBuf;

#[derive(Args)]
pub(crate) struct Doc {
    #[arg(long)]
    pub(crate) doc: PathBuf,
}

#[derive(Args)]
pub(crate) struct DetectionArgs {
    #[command(flatten)]
    pub(crate) doc: Doc,
    #[arg(long)]
    pub(crate) pages: Option<String>,
    #[arg(long)]
    no_sfx: bool,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().balloon_min_area)]
    balloon_min_area: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().balloon_max_area)]
    balloon_max_area: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().balloon_min_side)]
    balloon_min_side: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().balloon_min_solidity)]
    balloon_min_solidity: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().ink_min)]
    ink_min: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().ink_max)]
    ink_max: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().glyph_min)]
    glyph_min: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().glyph_max)]
    glyph_max: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().gutter_max_ink)]
    gutter_max_ink: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().gutter_min_span)]
    gutter_min_span: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().panel_min_area)]
    panel_min_area: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().sfx_min_side)]
    sfx_min_side: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().sfx_min_glyphs)]
    sfx_min_glyphs: u32,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().sfx_size_uniformity)]
    sfx_size_uniformity: f64,
    #[arg(long, default_value_t = revayat_vision::detect::DetectionOptions::default().sfx_max_spread)]
    sfx_max_spread: f64,
}

impl DetectionArgs {
    pub(crate) fn options(&self) -> revayat_vision::detect::DetectionOptions {
        revayat_vision::detect::DetectionOptions {
            balloon_min_area: self.balloon_min_area,
            balloon_max_area: self.balloon_max_area,
            balloon_min_side: self.balloon_min_side,
            balloon_min_solidity: self.balloon_min_solidity,
            ink_min: self.ink_min,
            ink_max: self.ink_max,
            glyph_min: self.glyph_min,
            glyph_max: self.glyph_max,
            gutter_max_ink: self.gutter_max_ink,
            gutter_min_span: self.gutter_min_span,
            panel_min_area: self.panel_min_area,
            sfx_min_side: self.sfx_min_side,
            sfx_min_glyphs: self.sfx_min_glyphs,
            sfx_size_uniformity: self.sfx_size_uniformity,
            sfx_max_spread: self.sfx_max_spread,
            find_sfx: !self.no_sfx,
            rtl: true,
        }
    }
}

#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum Direction {
    Rtl,
    Ltr,
}

#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum WorksheetAction {
    Build,
    Merge,
    Status,
}

#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum GlossaryAction {
    Scan,
    Check,
}

#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum FalintAction {
    Check,
    Fix,
}

#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum DigitMode {
    Latin,
    Persian,
    Keep,
}

#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum QaAction {
    Check,
    Package,
    ReviewPack,
}

#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum BatchAction {
    Plan,
    Merge,
    Status,
}
