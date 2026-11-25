use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const MAX_MEMBER_BYTES: u64 = 512 * 1024 * 1024;
pub const MAX_TOTAL_BYTES: u64 = 2 * 1024 * 1024 * 1024;
pub const MAX_PAGE_PIXELS: u64 = 80_000_000;
pub const MAX_PAGES: usize = 2000;
pub const PDF_DPI: u32 = 300;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum InputKind {
    Directory,
    Cbz,
    Cbr,
    Pdf,
    Image,
}

#[derive(Debug, Clone)]
pub struct ImportOptions {
    pub dpi: u32,
    pub max_pixels: u64,
    pub source_language: String,
    pub target_language: String,
    pub reading_direction: String,
    pub title: String,
    pub chapter: String,
}

impl Default for ImportOptions {
    fn default() -> Self {
        Self {
            dpi: PDF_DPI,
            max_pixels: MAX_PAGE_PIXELS,
            source_language: "auto".into(),
            target_language: "fa".into(),
            reading_direction: "rtl".into(),
            title: String::new(),
            chapter: String::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ImportedPage {
    pub id: String,
    pub index: usize,
    pub image: PathBuf,
    pub sha256: String,
    pub width: u32,
    pub height: u32,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub pdf_points: Option<[f64; 2]>,
    pub is_spread: bool,
    pub panels: Vec<Value>,
    pub regions: Vec<Value>,
    pub notes: Vec<Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ImportReport {
    pub document: PathBuf,
    pub kind: InputKind,
    pub pages: Vec<ImportedPage>,
    pub median_size: [f64; 2],
    pub reading_direction: String,
    pub webtoon_strips: Vec<String>,
    pub warning: Option<String>,
}
