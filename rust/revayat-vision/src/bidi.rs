use crate::{Result, VisionError};
use textcore_rs::port;

pub const RLM: char = '\u{200f}';
pub const RLI: char = '\u{2067}';
pub const PDI: char = '\u{2069}';

pub(crate) fn is_rtl_text(text: &str) -> bool {
    text.chars().any(|c| matches!(c, RLM | RLI | '\u{0600}'..='\u{08ff}' | '\u{fb50}'..='\u{fdff}' | '\u{fe70}'..='\u{fefc}'))
}

pub(crate) fn visible(c: char) -> bool {
    !c.is_whitespace()
        && !c.is_control()
        && !matches!(c, '\u{00ad}' | '\u{061c}' | '\u{200b}'..='\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2060}'..='\u{206f}' | '\u{fe00}'..='\u{fe0f}' | '\u{feff}' | '\u{e0100}'..='\u{e01ef}')
}

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
