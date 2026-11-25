//! Pure-Rust `maskcore-rs` kernel crate.

#![forbid(unsafe_code)]

pub mod port;
pub use port::dilate_l2;
