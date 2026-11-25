//! Image stages for comic preparation and Persian lettering.
#![forbid(unsafe_code)]

use image::{GrayImage, Rgb, RgbImage};
use serde::{Deserialize, Serialize};

pub mod bidi;
pub mod clean;
pub mod crops;
pub mod detect;
pub mod falint;
pub mod fullpage_edit;
pub mod lettering;
pub mod masks;
pub mod qa;
pub mod qachecks;
pub mod sheet;
pub mod typefit;
pub mod typefont;
pub mod typeset;
pub mod typestyle;
pub mod watermark;

pub use clean::clean_page_bubbles;
pub use fullpage_edit::{FullPageEditRequest, FullPageReplacement, build_fullpage_prompt};
pub use qa::run_strict_qa;
pub use typeset::typeset_page;

#[derive(Debug, thiserror::Error)]
pub enum VisionError {
    #[error("{0}")]
    Invalid(String),
    #[error("{0}")]
    Kernel(String),
    #[error("opening image {path}: {source}")]
    Image {
        path: std::path::PathBuf,
        source: image::ImageError,
    },
    #[error("text in region {id} does not fit")]
    Overflow { id: String },
    #[error("text regions {first} and {second} overlap")]
    Overlap { first: String, second: String },
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

impl VisionError {
    pub(crate) fn invalid(message: impl Into<String>) -> Self {
        Self::Invalid(message.into())
    }
    pub(crate) fn kernel(error: impl Into<String>) -> Self {
        Self::Kernel(error.into())
    }
}

pub type Result<T> = std::result::Result<T, VisionError>;

/// A half-open rectangle in page pixels, serialized as `[x, y, width, height]`.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(transparent)]
pub struct Rect(pub [u32; 4]);

impl Rect {
    pub fn x(self) -> u32 {
        self.0[0]
    }
    pub fn y(self) -> u32 {
        self.0[1]
    }
    pub fn width(self) -> u32 {
        self.0[2]
    }
    pub fn height(self) -> u32 {
        self.0[3]
    }
    pub fn right(self) -> u32 {
        self.x().saturating_add(self.width())
    }
    pub fn bottom(self) -> u32 {
        self.y().saturating_add(self.height())
    }
    pub fn area(self) -> u64 {
        u64::from(self.width()) * u64::from(self.height())
    }
    pub fn center(self) -> [u32; 2] {
        [self.x() + self.width() / 2, self.y() + self.height() / 2]
    }
    pub fn contains(self, x: u32, y: u32) -> bool {
        x >= self.x() && y >= self.y() && x < self.right() && y < self.bottom()
    }
    pub fn clip(self, width: u32, height: u32) -> Self {
        let x = self.x().min(width);
        let y = self.y().min(height);
        Self([
            x,
            y,
            self.right().min(width) - x,
            self.bottom().min(height) - y,
        ])
    }
    pub fn intersection(self, other: Self) -> Option<Self> {
        let x = self.x().max(other.x());
        let y = self.y().max(other.y());
        let w = self.right().min(other.right()).saturating_sub(x);
        let h = self.bottom().min(other.bottom()).saturating_sub(y);
        (w > 0 && h > 0).then_some(Self([x, y, w, h]))
    }
    pub fn union(self, other: Self) -> Self {
        let x = self.x().min(other.x());
        let y = self.y().min(other.y());
        Self([
            x,
            y,
            self.right().max(other.right()) - x,
            self.bottom().max(other.bottom()) - y,
        ])
    }
    pub fn expand(self, pad: u32, width: u32, height: u32) -> Self {
        let x = self.x().saturating_sub(pad);
        let y = self.y().saturating_sub(pad);
        Self([
            x,
            y,
            self.right().saturating_add(pad) - x,
            self.bottom().saturating_add(pad) - y,
        ])
        .clip(width, height)
    }
    pub(crate) fn checked(self, size: (u32, u32)) -> Result<Self> {
        if self.area() == 0
            || self.x().checked_add(self.width()).is_none()
            || self.y().checked_add(self.height()).is_none()
            || self != self.clip(size.0, size.1)
        {
            return Err(VisionError::invalid(format!(
                "rectangle {:?} is outside {}x{} page",
                self.0, size.0, size.1
            )));
        }
        Ok(self)
    }
}

pub(crate) fn luminance(pixel: &Rgb<u8>) -> u8 {
    let [r, g, b] = pixel.0.map(u32::from);
    ((4899 * r + 9617 * g + 1868 * b + 8192) >> 14) as u8
}

pub(crate) fn gray(page: &RgbImage, dark: bool) -> GrayImage {
    GrayImage::from_fn(page.width(), page.height(), |x, y| {
        let value = luminance(page.get_pixel(x, y));
        image::Luma([if dark { 255 - value } else { value }])
    })
}

pub(crate) fn mask_bounds(mask: &GrayImage) -> Option<Rect> {
    let mut bounds: Option<Rect> = None;
    for (x, y, pixel) in mask.enumerate_pixels().filter(|(_, _, p)| p[0] != 0) {
        let _ = pixel;
        let point = Rect([x, y, 1, 1]);
        bounds = Some(bounds.map_or(point, |prior| prior.union(point)));
    }
    bounds
}

pub(crate) fn same_geometry(a: (u32, u32), b: (u32, u32)) -> Result<()> {
    if a.0 == 0 || a.1 == 0 || a != b {
        return Err(VisionError::invalid(format!(
            "image geometry differs: {a:?} and {b:?}"
        )));
    }
    Ok(())
}
