use crate::{Result, VisionError};
use textcore_rs::port;

pub const RLM: char = '\u{200f}';
pub const RLI: char = '\u{2067}';
pub const PDI: char = '\u{2069}';

pub fn starts_with_latin_in_persian(text: &str) -> Result<bool> {
    port::starts_with_latin_in_persian(text.into()).map_err(VisionError::kernel)
}

pub fn ensure_rli_pdi(text: &str) -> Result<String> {
    port::ensure_rli_pdi(text.into()).map_err(VisionError::kernel)
}

pub fn ensure_rlm_rli_pdi(text: &str) -> Result<String> {
    port::ensure_rlm_rli_pdi(text.into()).map_err(VisionError::kernel)
}

pub fn has_logical_order(text: &str) -> Result<bool> {
    let mut depth = 0usize;
    for ch in text.chars() {
        match ch {
            '\u{2066}'..='\u{2068}' => depth += 1,
            PDI if depth == 0 => return Ok(false),
            PDI => depth -= 1,
            '\u{202a}'..='\u{202e}' | '\u{fb50}'..='\u{fdff}' | '\u{fe70}'..='\u{fefc}' => {
                return Ok(false);
            }
            _ => {}
        }
    }
    Ok(depth == 0 && ensure_rli_pdi(text)? == text)
}
