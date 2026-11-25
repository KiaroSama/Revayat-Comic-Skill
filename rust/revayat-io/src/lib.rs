//! Immutable comic inputs and portable, verifiable editions.
#![forbid(unsafe_code)]

mod archive;
pub mod export;
mod fsutil;
pub mod geometry;
pub mod images;
pub mod inputs;
pub mod order;
pub mod package;
pub mod pdf;
pub mod readers;
pub mod reviewdocx;
pub mod writers;

pub use export::{ExportFormat, ExportOptions, ExportPage, ExportReport, export_document};
pub use inputs::{ImportOptions, ImportReport, ImportedPage, InputKind};
pub use pdf::{PdfInspection, inspect_pdf_page_density};
pub use readers::import_input;
pub use reviewdocx::{ReviewReport, export_review_docx};
pub use writers::{export_cbz, export_directory, export_pdf};

#[derive(Debug, thiserror::Error)]
pub enum IoError {
    #[error(transparent)]
    File(#[from] std::io::Error),
    #[error(transparent)]
    Image(#[from] image::ImageError),
    #[error(transparent)]
    Zip(#[from] zip::result::ZipError),
    #[error(transparent)]
    Rar(#[from] rars::Error),
    #[error(transparent)]
    Pdf(#[from] lopdf::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Workspace(#[from] revayat_ir::IrError),
    #[error("{0}")]
    Invalid(String),
    #[error("Unsafe archive member: {0}")]
    ArchivePath(String),
    #[error("Multi-frame images are not supported; split the image before importing")]
    AnimatedImage,
    #[error(
        "Native resolution needs {required} pixels; the limit is {limit}. Split or inspect the source instead of lowering its resolution"
    )]
    PixelBudget { required: u64, limit: u64 },
}

pub(crate) fn invalid(message: impl Into<String>) -> IoError {
    IoError::Invalid(message.into())
}
