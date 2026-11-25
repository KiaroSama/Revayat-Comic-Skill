#![forbid(unsafe_code)]

pub mod batch;
pub mod certify;
pub mod context;
pub mod glossary;
pub mod ir;
pub mod journal;
pub mod languages;
pub mod regions;
pub mod replies;
pub mod runlog;
pub mod stages;
pub mod textmatch;
pub mod wire_json;
pub mod worksheet;
pub mod worksheet_paths;
pub mod workspace;

pub use batch::BatchPlan;
pub use ir::{ComicDocument, PageRecord, RegionRecord};
pub use regions::RegionState;
pub use runlog::RunLog;
pub use stages::StageFreshness;

#[derive(Debug, thiserror::Error)]
pub enum IrError {
    #[error("{code}: {message}")]
    Refused { code: &'static str, message: String },
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

impl IrError {
    pub fn refused(code: &'static str, message: impl Into<String>) -> Self {
        Self::Refused {
            code,
            message: message.into(),
        }
    }

    pub fn code(&self) -> &'static str {
        match self {
            Self::Refused { code, .. } => code,
            Self::Io(_) => "io",
            Self::Json(_) => "json",
        }
    }
}

pub(crate) fn matcher(pattern: &str) -> regex::Regex {
    // INFALLIBLE: callers use regex literals owned by this crate.
    regex::Regex::new(pattern)
        .unwrap_or_else(|error| unreachable!("invalid internal regex: {error}"))
}
