use fancy_regex::{Error, Regex};

use super::NumberForms;

const PERSIAN_LETTER: &str = "ء-غف-يٮ-ۓۺ-ۿ";
const NUMBER: &str = r"[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)";

fn escaped_words(text: &str) -> String {
    text.split_whitespace()
        .map(regex::escape)
        .collect::<Vec<_>>()
        .join(r"\s+")
}

pub(super) fn term_used(text: &str, term: &str) -> Result<bool, Error> {
    if term.is_empty() {
        return Ok(false);
    }
    let bounded = Regex::new(
        r"^[A-Za-z\u{00c0}-\u{024f}\u{1e00}-\u{1eff}0-9_\u{0300}-\u{036f} ./:@+#'’\-]+$",
    )?;
    let pattern = if bounded.is_match(term)? && term.chars().any(char::is_alphanumeric) {
        let edge = |ch: Option<char>| {
            ch.filter(|ch| !ch.is_alphanumeric())
                .map_or_else(String::new, |ch| regex::escape(&ch.to_string()))
        };
        let (first, last) = (edge(term.chars().next()), edge(term.chars().next_back()));
        let suffix = if term.bytes().any(|b| b.is_ascii_digit()) {
            r"|[./:\-]\w"
        } else {
            ""
        };
        format!(
            r"(?<![\w\u{{0300}}-\u{{036f}}{first}]){}(?![\w\u{{0300}}-\u{{036f}}{last}]{suffix})",
            escaped_words(term)
        )
    } else if Regex::new(&format!("[{PERSIAN_LETTER}]"))?.is_match(term)? {
        format!(
            "(?<![{PERSIAN_LETTER}]){}(?![{PERSIAN_LETTER}])",
            regex::escape(term)
        )
    } else {
        return Ok(text.contains(term));
    };
    Regex::new(&pattern)?.is_match(text)
}

fn numeric_text(text: &str) -> String {
    text.chars()
        .map(|ch| match ch {
            '٫' => '.',
            '−' => '-',
            _ => crate::voice::latin_digit(ch),
        })
        .collect()
}

fn canonical(token: &str) -> String {
    let token = token.trim_start_matches(['+', '-']);
    let (whole, fraction) = token.split_once(['.', ',']).unwrap_or((token, ""));
    let whole = whole.trim_start_matches('0');
    let whole = if whole.is_empty() { "0" } else { whole };
    let fraction = fraction.trim_end_matches('0');
    if fraction.is_empty() {
        whole.into()
    } else {
        format!("{whole}.{fraction}")
    }
}

fn signed(token: &str) -> String {
    let magnitude = canonical(token);
    if token.starts_with('-') && magnitude != "0" {
        format!("-{magnitude}")
    } else {
        magnitude
    }
}

struct NumberPatterns {
    whole: Regex,
    span: Regex,
    excluded: Regex,
    scientific: Regex,
    gap: Regex,
    before: Regex,
    after: Regex,
}

impl NumberPatterns {
    fn new() -> Result<Self, Error> {
        Ok(Self {
            whole: Regex::new(&format!(r"\A{NUMBER}\z"))?,
            span: Regex::new(&format!(
                r"(?<![\w.,+\-]){NUMBER}(?:[eE][+-]?[0-9]+)?(?![0-9]|[.,][0-9])"
            ))?,
            excluded: Regex::new(
                r"(?<!\w)(?:[A-Za-z_][A-Za-z0-9_./:+\-]*|[0-9]+[A-Za-z_][A-Za-z0-9_]*[./:+\-][A-Za-z0-9_./:+\-]*)|[0-9]+(?:\.[0-9]+){2,}",
            )?,
            scientific: Regex::new(r"[0-9](?:[.,][0-9]+)?[eE][+-]?[0-9]")?,
            gap: Regex::new(r"\s*([:/])\s*")?,
            before: Regex::new(r"\w$|[:/+\-]\s*$")?,
            after: Regex::new(r"^(?:\w|\s*[:/]|\.[0-9])")?,
        })
    }

    fn tokens<'t>(&self, text: &'t str) -> Result<Vec<fancy_regex::Match<'t>>, Error> {
        let excluded = self
            .excluded
            .find_iter(text)
            .collect::<Result<Vec<_>, _>>()?;
        let mut matches = Vec::new();
        for number in self.span.find_iter(text) {
            let number = number?;
            if self.whole.is_match(number.as_str())?
                && !excluded
                    .iter()
                    .any(|x| x.start() < number.end() && number.start() < x.end())
            {
                matches.push(number);
            }
        }
        Ok(matches)
    }

    fn used(
        &self,
        spelling: &str,
        answer: &str,
        tokens: &[fancy_regex::Match<'_>],
    ) -> Result<bool, Error> {
        let normalized = numeric_text(spelling);
        let wanted = normalized.trim();
        if self.whole.is_match(wanted)? {
            let value = signed(wanted);
            return Ok(tokens.iter().any(|m| signed(m.as_str()) == value));
        }
        if wanted.bytes().any(|b| b.is_ascii_digit()) {
            let required = self.tokens(wanted)?;
            if required.first().is_some_and(|m| m.start() == 0)
                && required.last().is_some_and(|m| m.end() == wanted.len())
            {
                let signature = |text: &str, spans: &[fancy_regex::Match<'_>]| {
                    let parts: Vec<_> = spans.iter().map(|m| signed(m.as_str())).collect();
                    let gaps: Vec<_> = spans
                        .windows(2)
                        .map(|p| {
                            self.gap
                                .replace_all(&text[p[0].end()..p[1].start()], "$1")
                                .into_owned()
                        })
                        .collect();
                    (parts, gaps)
                };
                let contract = signature(wanted, &required);
                for window in tokens.windows(required.len()) {
                    let before = &answer[..window[0].start()];
                    let after = &answer[window[window.len() - 1].end()..];
                    if !self.before.is_match(before)?
                        && !self.after.is_match(after)?
                        && signature(answer, window) == contract
                    {
                        return Ok(true);
                    }
                }
                return Ok(false);
            }
            if self.scientific.is_match(wanted)? {
                return Ok(false);
            }
            let phrase = regex::escape(wanted)
                .replace(':', r"\s*:\s*")
                .replace('/', r"\s*/\s*");
            return Regex::new(&format!(r"(?<![\w:/]){phrase}(?!\w|[.:/][0-9])"))?.is_match(answer);
        }
        let phrase = escaped_words(wanted);
        if phrase.is_empty() {
            return Ok(false);
        }
        Regex::new(&format!(r"(?<![\w\u{{200c}}]){phrase}(?![\w\u{{200c}}])"))?.is_match(answer)
    }
}

pub(super) fn missing<'a>(numbers: &'a [NumberForms], answer: &str) -> Result<Vec<&'a str>, Error> {
    let patterns = NumberPatterns::new()?;
    let answer = numeric_text(answer);
    let tokens = patterns.tokens(&answer)?;
    let mut missing = Vec::new();
    'numbers: for number in numbers {
        let choices = number.choices();
        for form in choices {
            if patterns.used(form, &answer, &tokens)? {
                continue 'numbers;
            }
        }
        if let Some(first) = choices.first() {
            missing.push(first.as_str());
        }
    }
    Ok(missing)
}
