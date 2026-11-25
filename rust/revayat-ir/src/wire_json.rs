use crate::IrError;
use serde::Deserialize;
use serde_json::Value;

pub const MAX_DEPTH: usize = 128;
pub const MAX_INTEGER_DIGITS: usize = 1024;

pub fn loads(text: &str) -> Result<Value, IrError> {
    let mut depth = 0usize;
    let mut quoted = false;
    let mut escaped = false;
    let mut bytes = text.bytes().peekable();
    while let Some(byte) = bytes.next() {
        if quoted {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                quoted = false;
            }
            continue;
        }
        match byte {
            b'"' => quoted = true,
            b'[' | b'{' => {
                depth += 1;
                if depth > MAX_DEPTH {
                    return Err(IrError::refused(
                        "wire_json",
                        "JSON nesting exceeds the supported depth",
                    ));
                }
            }
            b']' | b'}' => depth = depth.saturating_sub(1),
            b'N' if bytes.clone().take(2).eq(b"aN".iter().copied()) => {
                return Err(IrError::refused("wire_json", "nonstandard JSON number"));
            }
            b'I' if bytes.clone().take(7).eq(b"nfinity".iter().copied()) => {
                return Err(IrError::refused("wire_json", "nonstandard JSON number"));
            }
            b'0'..=b'9' | b'-' => {
                let mut token = vec![byte];
                while bytes
                    .peek()
                    .is_some_and(|b| matches!(b, b'0'..=b'9' | b'.' | b'e' | b'E' | b'-' | b'+'))
                {
                    if let Some(next) = bytes.next() {
                        token.push(next);
                    }
                }
                if token.iter().any(|b| matches!(b, b'.' | b'e' | b'E')) {
                    if std::str::from_utf8(&token)
                        .ok()
                        .and_then(|s| s.parse::<f64>().ok())
                        .is_some_and(|n| !n.is_finite())
                    {
                        return Err(IrError::refused("wire_json", "JSON number is not finite"));
                    }
                } else if token.len() - usize::from(byte == b'-') > MAX_INTEGER_DIGITS {
                    return Err(IrError::refused(
                        "wire_json",
                        "JSON integer exceeds the supported digit limit",
                    ));
                }
            }
            _ => {}
        }
    }
    let mut deserializer = serde_json::Deserializer::from_str(text);
    deserializer.disable_recursion_limit();
    let value = Value::deserialize(&mut deserializer)?;
    deserializer.end()?;
    Ok(value)
}
