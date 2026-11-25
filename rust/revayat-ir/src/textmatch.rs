use crate::matcher;
use regex::Regex;
use std::collections::BTreeSet;
use std::sync::LazyLock;
use unicode_general_category::{GeneralCategory, get_general_category};

static BOUNDED: LazyLock<Regex> = LazyLock::new(|| {
    matcher(r"^[A-Za-z\u{00c0}-\u{024f}\u{1e00}-\u{1eff}0-9_\u{0300}-\u{036f} ./:@+#'’\-]+$")
});
static PERSIAN: LazyLock<Regex> = LazyLock::new(|| matcher(r"[ء-غف-يٮ-ۓۺ-ۿ]"));
const NUMBER_BODY: &str = r"[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)";
static NUMBER: LazyLock<Regex> =
    LazyLock::new(|| matcher(&format!(r"{NUMBER_BODY}(?:[eE][+-]?[0-9]+)?")));
static WHOLE: LazyLock<Regex> = LazyLock::new(|| matcher(&format!(r"^{NUMBER_BODY}$")));
static NON_QUANTITY: LazyLock<Regex> = LazyLock::new(|| {
    matcher(
        r"[A-Za-z_][A-Za-z0-9_./:+\-]*|[0-9]+[A-Za-z_][A-Za-z0-9_]*[./:+\-][A-Za-z0-9_./:+\-]*|[0-9]+(?:\.[0-9]+){2,}",
    )
});
static SCIENTIFIC: LazyLock<Regex> =
    LazyLock::new(|| matcher(r"[0-9](?:[.,][0-9]+)?[eE][+-]?[0-9]"));
static SPACED_SEPARATOR: LazyLock<Regex> = LazyLock::new(|| matcher(r"\s*([:/])\s*"));

fn word(ch: char) -> bool {
    ch == '_' || ch.is_alphanumeric()
}
fn latin_boundary(ch: char) -> bool {
    word(ch) || ('\u{0300}'..='\u{036f}').contains(&ch)
}
fn persian_letter(ch: char) -> bool {
    matches!(ch,'ء'..='غ'|'ف'..='ي'|'ٮ'..='ۓ'|'ۺ'..='ۿ')
}
fn literal_words(form: &str) -> String {
    form.split_whitespace()
        .map(regex::escape)
        .collect::<Vec<_>>()
        .join(r"\s+")
}
fn around(text: &str, start: usize, end: usize) -> (Option<char>, Option<char>) {
    (
        text[..start].chars().next_back(),
        text[end..].chars().next(),
    )
}

pub fn used<S: AsRef<str>>(text: &str, candidates: &[S]) -> bool {
    candidates.iter().map(AsRef::as_ref).any(|form| {
        if form.is_empty() {
            return false;
        }
        if BOUNDED.is_match(form) && form.chars().any(char::is_alphanumeric) {
            let Ok(regex) = Regex::new(&literal_words(form)) else {
                return false;
            };
            let first = form.chars().next().filter(|ch| !ch.is_alphanumeric());
            let last = form.chars().next_back().filter(|ch| !ch.is_alphanumeric());
            regex.find_iter(text).any(|m| {
                let (before, after) = around(text, m.start(), m.end());
                !before.is_some_and(|ch| latin_boundary(ch) || Some(ch) == first)
                    && !after.is_some_and(|ch| latin_boundary(ch) || Some(ch) == last)
                    && !(form.bytes().any(|b| b.is_ascii_digit())
                        && after.is_some_and(|ch| "./:-".contains(ch))
                        && text[m.end()..].chars().nth(1).is_some_and(word))
            })
        } else if PERSIAN.is_match(form) {
            text.match_indices(form).any(|(start, found)| {
                let (a, b) = around(text, start, start + found.len());
                !a.is_some_and(persian_letter) && !b.is_some_and(persian_letter)
            })
        } else {
            text.contains(form)
        }
    })
}

fn decimal(c: char) -> Option<u32> {
    if get_general_category(c) != GeneralCategory::DecimalNumber {
        return None;
    }
    let mut start = u32::from(c);
    while start > 0
        && char::from_u32(start - 1)
            .is_some_and(|c| get_general_category(c) == GeneralCategory::DecimalNumber)
    {
        start -= 1;
    }
    Some((u32::from(c) - start) % 10)
}
pub fn numeric_text(text: &str) -> String {
    text.chars()
        .map(|ch| {
            decimal(ch)
                .and_then(|d| char::from_digit(d, 10))
                .unwrap_or(match ch {
                    '٫' => '.',
                    '−' => '-',
                    _ => ch,
                })
        })
        .collect()
}
pub fn canonical_number(token: &str) -> String {
    let token = numeric_text(token).replace(',', ".");
    let (whole, fraction) = token
        .trim_start_matches(['+', '-'])
        .split_once('.')
        .unwrap_or((token.trim_start_matches(['+', '-']), ""));
    let whole = whole.trim_start_matches('0');
    let whole = if whole.is_empty() { "0" } else { whole };
    let fraction = fraction.trim_end_matches('0');
    let sign = if token.starts_with('-') && (whole != "0" || !fraction.is_empty()) {
        "-"
    } else {
        ""
    };
    if fraction.is_empty() {
        format!("{sign}{whole}")
    } else {
        format!("{sign}{whole}.{fraction}")
    }
}
fn spans(text: &str) -> Vec<regex::Match<'_>> {
    let excluded: Vec<_> = NON_QUANTITY
        .find_iter(text)
        .filter(|m| {
            !text[..m.start()].chars().next_back().is_some_and(word)
                || m.as_str().bytes().filter(|b| *b == b'.').count() >= 2
        })
        .collect();
    NUMBER
        .find_iter(text)
        .filter(|m| {
            let (before, after) = around(text, m.start(), m.end());
            WHOLE.is_match(m.as_str())
                && !before.is_some_and(|ch| word(ch) || ".,+-".contains(ch))
                && !after.is_some_and(|ch| ch.is_ascii_digit())
                && !(after.is_some_and(|ch| ".,".contains(ch))
                    && text[m.end()..]
                        .chars()
                        .nth(1)
                        .is_some_and(|ch| ch.is_ascii_digit()))
                && !excluded
                    .iter()
                    .any(|x| x.start() < m.end() && m.start() < x.end())
        })
        .collect()
}
pub fn digits_in(text: &str) -> BTreeSet<String> {
    spans(&numeric_text(text))
        .into_iter()
        .map(|m| canonical_number(m.as_str()))
        .collect()
}
pub fn number_spelling_used(spelling: &str, answer: &str, present: &BTreeSet<String>) -> bool {
    let wanted = numeric_text(spelling);
    let wanted = wanted.trim();
    if WHOLE.is_match(wanted) {
        return present.contains(&canonical_number(wanted));
    }
    if wanted.bytes().any(|b| b.is_ascii_digit()) {
        if SCIENTIFIC.is_match(wanted) {
            return false;
        }
        let clean = numeric_text(answer);
        let parts = spans(wanted);
        if parts.first().is_some_and(|m| m.start() == 0)
            && parts.last().is_some_and(|m| m.end() == wanted.len())
        {
            let signature = |text: &str, matches: &[regex::Match<'_>]| {
                let values: Vec<_> = matches
                    .iter()
                    .map(|m| canonical_number(m.as_str()))
                    .collect();
                let gaps: Vec<_> = matches
                    .windows(2)
                    .map(|pair| {
                        SPACED_SEPARATOR
                            .replace_all(&text[pair[0].end()..pair[1].start()], "$1")
                            .into_owned()
                    })
                    .collect();
                (values, gaps)
            };
            let expected = signature(wanted, &parts);
            return spans(&clean).windows(parts.len()).any(|window| {
                let start = window[0].start();
                let end = window[window.len() - 1].end();
                let (a, b) = around(&clean, start, end);
                !a.is_some_and(word)
                    && !clean[..start].trim_end().ends_with([':', '/', '+', '-'])
                    && !b.is_some_and(word)
                    && !clean[end..].trim_start().starts_with([':', '/'])
                    && signature(&clean, window) == expected
            });
        }
        let pattern = regex::escape(wanted)
            .replace(':', r"\s*:\s*")
            .replace('/', r"\s*/\s*");
        return Regex::new(&pattern).is_ok_and(|r| {
            r.find_iter(&clean).any(|m| {
                let (a, b) = around(&clean, m.start(), m.end());
                !a.is_some_and(|c| word(c) || ":/".contains(c)) && !b.is_some_and(word)
            })
        });
    }
    let pattern = literal_words(spelling);
    !pattern.is_empty()
        && Regex::new(&pattern).is_ok_and(|r| {
            r.find_iter(answer).any(|m| {
                let (a, b) = around(answer, m.start(), m.end());
                let attached = |c| word(c) || c == '\u{200c}';
                !a.is_some_and(attached) && !b.is_some_and(attached)
            })
        })
}
