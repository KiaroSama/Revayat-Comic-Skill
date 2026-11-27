use crate::{Result, VisionError, bidi};
use fancy_regex::Regex as Fancy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::{borrow::Cow, sync::LazyLock};

const FA: &str = "ء-غف-يٮ-ۓۺ-ۿ";
const LINKS: &str = r"(?:https?://|www\.)\S+|[\w.+-]+@[\w-]+\.[\w.-]+";
const NUMBER: &str = r"(?<![\w.,٫٬])[+\-−]?(?:\d+(?:[.,٫٬:/-]\d+)+(?:[eE][+\-−]?\d+)?|\d+[eE][+\-−]?\d+|[.,٫]\d+(?:[eE][+\-−]?\d+)?)(?!\d)";
static PROTECTED: LazyLock<std::result::Result<Fancy, fancy_regex::Error>> =
    LazyLock::new(|| Fancy::new(&format!(r"(?i){LINKS}|{NUMBER}|\b[A-Za-z][\w.'’-]*\b")));
static ADDRESSES: LazyLock<std::result::Result<Fancy, fancy_regex::Error>> =
    LazyLock::new(|| Fancy::new(&format!(r"(?i){LINKS}|{NUMBER}")));
static LINK: LazyLock<std::result::Result<Fancy, fancy_regex::Error>> =
    LazyLock::new(|| Fancy::new(&format!(r"(?i){LINKS}")));
static RULES: LazyLock<std::result::Result<Vec<Fancy>, fancy_regex::Error>> = LazyLock::new(|| {
    [
    format!(r"(?<=[{FA}0-9۰-۹]) *,"),format!(r"(?<=[{FA}0-9۰-۹]) *;"),format!(r"(?<=[{FA}0-9۰-۹]) *\?"),
    format!(r"[ \t]+(?!…[{FA}])([،؛؟!:.»…])"),format!(r"([،؛؟!:])(?=[{FA}])"),r"«\s+|\s+»".into(),r"([!؟])\1{2,}".into(),
    format!(r"([{FA}]{{2,}}) +(های|ها)(?= +(?:را|ی)\b)"),
    format!(r"([{FA}]{{2,}}) +(هایشان|هایتان|هایمان|هایی|هایم|هایت|هایش)\b"),r"(?<![\w.:/-])[0-9]+(?![\w.:/-])".into(),
    format!(r"[{FA}]{{2,}} +(?:ترین|تری|تر)\b|[{FA}]{{2,}} +(?:های|ها)\b(?! +(?:را|ی)\b)|\b(?:نمی|می) +[{FA}]{{2,}}"),
].iter().map(|p|Fancy::new(p)).collect()
});
static ELLIPSIS: LazyLock<std::result::Result<Regex, regex::Error>> =
    LazyLock::new(|| Regex::new(r"\.{3,}"));
static SPACES: LazyLock<std::result::Result<Regex, regex::Error>> =
    LazyLock::new(|| Regex::new(r"[ \t]{2,}"));
static COLLISION: LazyLock<std::result::Result<Regex, regex::Error>> =
    LazyLock::new(|| Regex::new(&format!(r"[{FA}][A-Za-z]|[A-Za-z][{FA}]")));
static LATIN: LazyLock<std::result::Result<Regex, regex::Error>> =
    LazyLock::new(|| Regex::new(r"[A-Za-z][A-Za-z ,'’-]{20,}"));

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum Digits {
    #[default]
    Latin,
    Persian,
    Keep,
}

#[derive(Debug, Clone, Copy)]
pub struct Options {
    pub digits: Digits,
    pub quotes: bool,
    pub ellipsis: bool,
    pub zwnj: bool,
    pub punctuation: bool,
}
impl Default for Options {
    fn default() -> Self {
        Self {
            digits: Digits::default(),
            quotes: true,
            ellipsis: true,
            zwnj: true,
            punctuation: true,
        }
    }
}

fn regex<T, E: std::fmt::Display>(input: &std::result::Result<T, E>) -> Result<&T> {
    input
        .as_ref()
        .map_err(|e| VisionError::kernel(e.to_string()))
}

pub fn has_persian(text: &str) -> bool {
    text.chars().any(persian)
}
fn persian(c: char) -> bool {
    matches!(c,'ء'..='غ'|'ف'..='ي'|'ٮ'..='ۓ'|'ۺ'..='ۿ')
}

fn parts<'a>(text: &'a str, expression: &Fancy) -> Result<Vec<(bool, &'a str)>> {
    let mut pieces = Vec::new();
    let mut end = 0;
    for m in expression.find_iter(text) {
        let m = m.map_err(|e| VisionError::kernel(e.to_string()))?;
        if m.start() > end {
            pieces.push((false, &text[end..m.start()]));
        }
        pieces.push((true, m.as_str()));
        end = m.end();
    }
    if end < text.len() {
        pieces.push((false, &text[end..]));
    }
    Ok(pieces)
}

pub fn segments(text: &str) -> Result<Vec<(bool, &str)>> {
    parts(text, regex(&*PROTECTED)?)
}
fn blank(text: &str, expression: &Fancy) -> Result<String> {
    Ok(parts(text, expression)?
        .into_iter()
        .map(|(guard, p)| {
            if guard {
                Cow::Owned(" ".repeat(p.chars().count()))
            } else {
                Cow::Borrowed(p)
            }
        })
        .collect())
}
pub fn unprotected(text: &str) -> Result<String> {
    blank(text, regex(&*PROTECTED)?)
}
pub fn without_addresses(text: &str) -> Result<String> {
    blank(text, regex(&*ADDRESSES)?)
}

fn pair_quotes(text: &str) -> Result<String> {
    let mut out = text.chars().collect::<Vec<_>>();
    let mut opening = None;
    for (i, c) in unprotected(text)?.chars().enumerate() {
        if !matches!(c, '"' | '“' | '”') {
            continue;
        }
        if let Some(j) = opening.take() {
            out[j] = '«';
            out[i] = '»';
        } else {
            opening = Some(i);
        }
    }
    Ok(out.into_iter().collect())
}

fn normalize_digits(text: &str, digits: Digits) -> Result<Cow<'_, str>> {
    let convert = |c| match (digits, c) {
        (Digits::Latin, '٠'..='٩') => {
            char::from_u32(c as u32 - '٠' as u32 + '0' as u32).unwrap_or(c)
        }
        (Digits::Latin, '۰'..='۹') => {
            char::from_u32(c as u32 - '۰' as u32 + '0' as u32).unwrap_or(c)
        }
        (Digits::Persian, '٠'..='٩') => {
            char::from_u32(c as u32 - '٠' as u32 + '۰' as u32).unwrap_or(c)
        }
        _ => c,
    };
    if !text.chars().any(|c| convert(c) != c) {
        return Ok(Cow::Borrowed(text));
    }
    Ok(Cow::Owned(
        parts(text, regex(&*LINK)?)?
            .into_iter()
            .flat_map(|(guard, span)| {
                span.chars()
                    .map(move |c| if guard { c } else { convert(c) })
            })
            .collect(),
    ))
}

fn digits_changed(text: &str, fixed: &str) -> bool {
    let is_digit = |c: &char| matches!(c, '0'..='9' | '٠'..='٩' | '۰'..='۹');
    text.chars()
        .filter(is_digit)
        .ne(fixed.chars().filter(is_digit))
}

fn fix_segment(text: &str, o: Options, persian_line: bool) -> Result<String> {
    let mut t = text
        .chars()
        .filter_map(|c| {
            Some(match c {
                'ي' | 'ى' => 'ی',
                'ك' => 'ک',
                '\u{a0}' => ' ',
                'ـ' | '\u{200b}' | '\u{feff}' => return None,
                _ => c,
            })
        })
        .collect::<String>();
    let rules = regex(&*RULES)?;
    if o.ellipsis {
        t = regex(&*ELLIPSIS)?.replace_all(&t, "…").into_owned();
    }
    if o.digits == Digits::Persian && persian_line {
        t = rules[9]
            .replace_all(&t, |c: &fancy_regex::Captures<'_, str>| {
                c[0].chars()
                    .map(|d| char::from_u32(d as u32 - 48 + 0x6f0).unwrap_or(d))
                    .collect::<String>()
            })
            .into_owned();
    }
    if o.punctuation {
        if persian_line {
            for (r, repl) in rules[..3].iter().zip(["،", "؛", "؟"]) {
                t = r.replace_all(&t, repl).into_owned();
            }
        }
        t = rules[3].replace_all(&t, "$1").into_owned();
        t = rules[4].replace_all(&t, "$1 ").into_owned();
        t = rules[5]
            .replace_all(&t, |c: &fancy_regex::Captures<'_, str>| {
                c[0].trim().to_owned()
            })
            .into_owned();
        t = rules[6].replace_all(&t, "$1$1$1").into_owned();
    }
    if o.zwnj {
        for r in &rules[7..9] {
            t = r.replace_all(&t, "${1}\u{200c}${2}").into_owned();
        }
    }
    Ok(regex(&*SPACES)?.replace_all(&t, " ").into_owned())
}

pub fn fix_line(text: &str, options: Options) -> Result<String> {
    let mut text = normalize_digits(text, options.digits)?
        .chars()
        .filter(|c| !matches!(c,'\x00'..='\x08'|'\x0b'..='\x1f'|'\x7f'))
        .collect::<String>();
    for _ in 0..3 {
        let fa = has_persian(&text);
        let paired = if options.quotes {
            Cow::Owned(pair_quotes(&text)?)
        } else {
            Cow::Borrowed(&text)
        };
        let next = segments(&paired)?
            .into_iter()
            .map(|(guard, p)| {
                if guard {
                    Ok(p.to_owned())
                } else {
                    fix_segment(p, options, fa)
                }
            })
            .collect::<Result<String>>()?;
        if next == text {
            break;
        }
        text = next;
    }
    Ok(text.trim().into())
}

pub fn fix_text(text: &str, options: Options) -> Result<String> {
    let normalized = text.replace("\r\n", "\n");
    let lines = normalized
        .split(['\r', '\n'])
        .map(|l| fix_line(l, options))
        .collect::<Result<Vec<_>>>()?;
    bidi::ensure_rli_pdi(lines.join("\n").trim_matches([' ', '\t', '\r']))
}

pub fn ambiguous_spans(text: &str) -> Result<Vec<String>> {
    let visible = unprotected(text)?;
    regex(&*RULES)?[10]
        .find_iter(&visible)
        .map(|m| {
            m.map(|m| m.as_str().to_owned())
                .map_err(|e| VisionError::kernel(e.to_string()))
        })
        .collect()
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct Issue {
    pub code: String,
    pub detail: String,
}

pub fn lint_text(text: &str) -> Result<Vec<Issue>> {
    lint_acknowledged(text, &[], None)
}

pub fn lint_acknowledged(
    text: &str,
    acknowledged: &[&str],
    spans: Option<&[&str]>,
) -> Result<Vec<Issue>> {
    lint_inner(text, acknowledged, spans, None)
}

pub fn lint_with_digits(
    text: &str,
    acknowledged: &[&str],
    spans: Option<&[&str]>,
    digits: Digits,
) -> Result<Vec<Issue>> {
    lint_inner(text, acknowledged, spans, Some(digits))
}

fn lint_inner(
    text: &str,
    acknowledged: &[&str],
    spans: Option<&[&str]>,
    digits: Option<Digits>,
) -> Result<Vec<Issue>> {
    if text.trim().is_empty() {
        return Ok(Vec::new());
    }
    let mut issues = Vec::new();
    let mut note = |code: &str, detail: &str| {
        if !acknowledged.contains(&code) || (code == "zwnj-review" && spans.is_some()) {
            issues.push(Issue {
                code: code.into(),
                detail: detail.chars().take(140).collect(),
            });
        }
    };
    if !bidi::has_logical_order(text)? {
        note(
            "missing-rli-pdi",
            "Enclose Latin-leading Persian sentences in U+2067 and U+2069",
        );
    }
    let visible = unprotected(text)?;
    let wrong_digits = match digits {
        Some(Digits::Keep) => false,
        Some(Digits::Latin) => normalize_digits(text, Digits::Latin)? != text,
        Some(Digits::Persian) => digits_changed(
            text,
            &fix_text(
                text,
                Options {
                    digits: Digits::Persian,
                    ..Options::default()
                },
            )?,
        ),
        None => visible.chars().any(|c| matches!(c, '٠'..='٩')),
    };
    if visible.contains(['ي', 'ك', 'ى', 'ـ']) || wrong_digits {
        note(
            "arabic-forms",
            "Arabic letter variants or digits outside the selected style remain",
        );
    }
    let (opens, closes) = (visible.matches('«').count(), visible.matches('»').count());
    if opens != closes {
        note(
            "guillemets",
            &format!("unbalanced Persian quotes: {opens} opening vs {closes} closing"),
        );
    }
    if visible.contains(['"', '“', '”']) {
        note("latin-quotes", "Latin quotation marks in Persian dialogue");
    }
    if visible.contains("،،") || visible.contains("؛؛") {
        note("double-punctuation", "repeated punctuation mark");
    }
    if let Some(ambiguous) = ambiguous_spans(text)?
        .into_iter()
        .find(|p| spans.is_none_or(|s| !s.contains(&p.as_str())))
    {
        note(
            "zwnj-review",
            &format!("`{ambiguous}` may want a ZWNJ; review before changing it"),
        );
    }
    let addressless = without_addresses(text)?;
    let (mut latin, mut fa, mut source) = (0, 0, 0);
    for c in addressless.chars() {
        if c.is_ascii_alphabetic() {
            latin += 1;
        } else if persian(c) {
            fa += 1;
        } else if matches!(c,'\u{3040}'..='\u{30ff}'|'\u{3400}'..='\u{9fff}'|'\u{ac00}'..='\u{d7af}'|'\u{ff66}'..='\u{ff9f}')
        {
            source += 1;
        }
    }
    if latin as f64 > 0.35 * f64::from(latin + fa + source)
        && let Some(m) = regex(&*LATIN)?.find(&addressless)
    {
        note(
            "untranslated",
            &format!(
                "long Latin passage: {}",
                m.as_str().chars().take(70).collect::<String>()
            ),
        );
    }
    if source > 0 {
        note(
            "source-script-left",
            &format!("{source} character(s) of the source script survive"),
        );
    }
    if fa == 0 && latin + source > 0 {
        note("untranslated", "no Persian characters at all");
    }
    if regex(&*COLLISION)?.is_match(&addressless) {
        note(
            "script-collision",
            "Latin and Persian letters with no space between",
        );
    }
    Ok(issues)
}
