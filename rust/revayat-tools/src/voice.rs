//! Persian mechanics and the bundled terminology banks.

use std::collections::{BTreeMap, HashSet};
use std::fmt::Write as _;

use fancy_regex::{Captures, Regex};
use serde::Serialize;

const PL: &str = "ء-يٮ-ەۺ-ۼۿ";
const PLD: &str = "ء-يٮ-ەۺ-ۼۿ\u{064b}-\u{0652}\u{0670}";
const AR: &str = "ء-يٮ-ەۺ-ۼۿ۰-۹٠-٩\u{200c}";
const PROTECT: &str = concat!(
    r"(?s:```.*?```)|`[^`\r\n]*`|(?m:^(?: {4,}|\t)\S[^\r\n]*$)",
    r"|(?:https?://|www\.)[^\s`<>«»\u{2066}-\u{2069}]+",
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
    r"|\bv\d+(?:\.\d+)+\b|\b\d+\.\d+\.\d+\b|\x00"
);
const IDIOMS: &str =
    include_str!("../../../skills/revayat-comic/references/voice/persian/scripts/data/idioms.tsv");
const GLOSSARY: &str = include_str!(
    "../../../skills/revayat-comic/references/voice/persian/scripts/data/glossary.tsv"
);

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum Digits {
    #[default]
    Persian,
    Latin,
    Keep,
}

#[derive(Debug, Serialize)]
pub struct LineChange {
    pub line: usize,
    pub before: String,
    pub after: String,
}

#[derive(Debug, Serialize)]
pub struct Suggestion {
    #[serde(rename = "type")]
    pub kind: &'static str,
    pub hint: &'static str,
    pub context: String,
    #[serde(skip)]
    pub message: String,
}

#[derive(Debug, Serialize)]
pub struct LintReport {
    #[serde(skip)]
    pub fixed: String,
    pub stats: BTreeMap<&'static str, usize>,
    pub changes: Vec<LineChange>,
    #[serde(skip)]
    pub changed_lines: usize,
    pub suggestions: Vec<Suggestion>,
}

impl LintReport {
    pub fn check_status(&self) -> i32 {
        i32::from(!self.stats.is_empty() || !self.suggestions.is_empty())
    }
}

type Stats = BTreeMap<&'static str, usize>;

fn count(stats: &mut Stats, rule: &'static str, n: usize) {
    if n != 0 {
        *stats.entry(rule).or_default() += n;
    }
}

fn alter(
    text: &mut String,
    stats: &mut Stats,
    rule: &'static str,
    pattern: &str,
    mut change: impl FnMut(&Captures<'_, str>) -> Option<String>,
) -> Result<(), fancy_regex::Error> {
    let mut result = String::new();
    let mut last = 0;
    for m in Regex::new(pattern)?.captures_iter(text.as_str()) {
        let m = m?;
        if let Some((whole, new)) = m.get(0).zip(change(&m)) {
            result.push_str(&text[last..whole.start()]);
            result.push_str(&new);
            last = whole.end();
            count(stats, rule, 1);
        }
    }
    if last != 0 {
        result.push_str(&text[last..]);
        *text = result;
    }
    Ok(())
}

fn mask(text: &str) -> Result<(String, Vec<&str>), fancy_regex::Error> {
    let mut spans = Vec::new();
    let mut masked = String::with_capacity(text.len());
    let mut last = 0;
    for hit in Regex::new(PROTECT)?.find_iter(text) {
        let hit = hit?;
        masked.push_str(&text[last..hit.start()]);
        spans.push(hit.as_str());
        masked.push('\0');
        last = hit.end();
    }
    masked.push_str(&text[last..]);
    Ok((masked, spans))
}

fn fa_letter(ch: char) -> bool {
    matches!(ch, 'ء'..='ي' | 'ٮ'..='ە' | 'ۺ'..='ۼ' | 'ۿ')
}

fn persian_majority(text: &str) -> bool {
    text.chars().filter(|&ch| fa_letter(ch)).count()
        > text.bytes().filter(u8::is_ascii_alphabetic).count()
}

pub(crate) fn latin_digit(ch: char) -> char {
    match ch {
        '۰'..='۹' => char::from(b'0' + (ch as u32 - '۰' as u32) as u8),
        '٠'..='٩' => char::from(b'0' + (ch as u32 - '٠' as u32) as u8),
        _ => ch,
    }
}

fn persian_digit(ch: char) -> char {
    match latin_digit(ch) {
        '0' => '۰',
        '1' => '۱',
        '2' => '۲',
        '3' => '۳',
        '4' => '۴',
        '5' => '۵',
        '6' => '۶',
        '7' => '۷',
        '8' => '۸',
        '9' => '۹',
        _ => ch,
    }
}

fn prefix_digits(
    line: &mut String,
    stats: &mut Stats,
    list_marker: &regex::Regex,
    token: &regex::Regex,
) {
    let start = list_marker.find(line).map_or(0, |m| m.end());
    let rest = token.replace_all(&line[start..], |m: &regex::Captures<'_>| {
        let before = &m[0];
        if before.bytes().any(|b| b.is_ascii_alphabetic()) {
            return before.to_owned();
        }
        count(
            stats,
            "digits_to_persian",
            before.bytes().filter(u8::is_ascii_digit).count(),
        );
        before.chars().map(persian_digit).collect()
    });
    *line = format!("{}{rest}", &line[..start]);
}

fn normalize(text: &str, digits: Digits) -> Result<(String, Stats), fancy_regex::Error> {
    let (mut masked, spans) = mask(text)?;
    let mut stats = Stats::new();
    for (from, to) in [('ي', 'ی'), ('ى', 'ی'), ('ك', 'ک'), ('ة', 'ه')] {
        count(
            &mut stats,
            "arabic_to_persian_letters",
            masked.matches(from).count(),
        );
        masked = masked.replace(from, &to.to_string());
    }
    alter(
        &mut masked,
        &mut stats,
        "kashida_dash_to_en_dash",
        r"(?m)(?:(?<=\s)|^)ـ+(?=\s|$)",
        |_| Some("\u{2013}".into()),
    )?;
    count(&mut stats, "kashida_removed", masked.matches('ـ').count());
    masked = masked.replace('ـ', "");
    let doc_fa = persian_majority(&masked);
    match digits {
        Digits::Persian => {
            count(
                &mut stats,
                "digits_to_persian",
                masked.matches(|ch| matches!(ch, '٠'..='٩')).count(),
            );
            masked = masked
                .chars()
                .map(|ch| {
                    if matches!(ch, '٠'..='٩') {
                        persian_digit(ch)
                    } else {
                        ch
                    }
                })
                .collect();
        }
        Digits::Latin => {
            count(
                &mut stats,
                "digits_to_latin",
                masked
                    .matches(|ch| matches!(ch, '۰'..='۹' | '٠'..='٩'))
                    .count(),
            );
            masked = masked.chars().map(latin_digit).collect();
        }
        Digits::Keep => {}
    }
    let list_marker = regex::Regex::new(r"^\s*\d+[.)]\s")
        .map_err(|e| fancy_regex::CompileError::UnexpectedGeneralError(e.to_string()))?;
    let token = regex::Regex::new(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
        .map_err(|e| fancy_regex::CompileError::UnexpectedGeneralError(e.to_string()))?;
    let lines = masked
        .split('\n')
        .map(|original| {
            let mut line = original.to_owned();
            let fa_line = persian_majority(&line);
            if digits == Digits::Persian
                && (fa_line || (doc_fa && !line.bytes().any(|b| b.is_ascii_alphabetic())))
            {
                prefix_digits(&mut line, &mut stats, &list_marker, &token);
            }
            alter(
                &mut line,
                &mut stats,
                "percent_to_persian",
                r"(?<=[۰-۹])%",
                |_| Some("٪".into()),
            )?;
            for (rule, pattern, substitute) in [
                ("comma_to_persian", r"(?!(?<=[0-9۰-۹]),(?=[0-9۰-۹])),", "،"),
                ("semicolon_to_persian", ";", "؛"),
                ("question_mark_to_persian", r"\?", "؟"),
            ] {
                let pattern = if fa_line {
                    pattern.to_owned()
                } else {
                    format!("(?<=[{AR}]){pattern}(?=[ \\t]*[{AR}])")
                };
                alter(&mut line, &mut stats, rule, &pattern, |_| {
                    Some(substitute.into())
                })?;
            }
            alter(
                &mut line,
                &mut stats,
                "quotes_to_guillemets",
                r#""([^"\n]*)"|“([^“”\n]*)”"#,
                |m| {
                    let inner = m.get(1).or_else(|| m.get(2))?.as_str();
                    (fa_line || persian_majority(inner)).then(|| format!("«{inner}»"))
                },
            )?;
            if fa_line {
                alter(
                    &mut line,
                    &mut stats,
                    "space_before_punct",
                    r"(?<=\S)[ \t]+([.!:،؛؟»])",
                    |m| Some(m[1].into()),
                )?;
                alter(
                    &mut line,
                    &mut stats,
                    "space_after_punct",
                    r"!(?=[^\s»)\]\x00،؛؟!.…])",
                    |_| Some("! ".into()),
                )?;
            }
            Ok(line)
        })
        .collect::<Result<Vec<_>, fancy_regex::Error>>()?;
    masked = lines.join("\n");
    for (rule, pattern, replacement) in [
        ("ellipsis", format!(r"(?<=[{PL}‌])\.[.]{{2,}}"), "…"),
        (
            "zwnj_mi_prefix",
            format!(r"(?<![{PL}‌])(نمی|می)[ \t]+(?=[{PL}])"),
            "$1‌",
        ),
        (
            "zwnj_plural_ha",
            format!(
                r"(?<=[{PLD}])[ \t]+(هایشان|هایتان|هایمان|هایی|هایم|هایت|هایش|های|ها)(?![{PL}]| و هوی)"
            ),
            "‌$1",
        ),
        (
            "zwnj_superlative",
            format!(r"(?<=[{PLD}])[ \t]+(ترین)(?![{PL}])"),
            "‌$1",
        ),
        (
            "space_before_punct",
            format!(r"(?<=[{AR}])[ \t]+([،؛؟»])"),
            "$1",
        ),
        ("space_after_openquote", r"(«)[ \t]+".into(), "$1"),
        (
            "space_after_punct",
            r"([،؛؟])(?=[^\s»)\]\x00،؛؟!.…])".into(),
            "$1 ",
        ),
    ] {
        alter(&mut masked, &mut stats, rule, &pattern, |m| {
            let mut out = String::new();
            m.expand(replacement, &mut out);
            Some(out)
        })?;
    }
    alter(
        &mut masked,
        &mut stats,
        "zwnj_heh_enclitic",
        &format!(r"([{PL}]*ه)[ \t]+(اند|ایم|اید|ام|ات|اش|ای)(?![{PL}])"),
        |m| {
            let word = &m[1];
            (word != "ه"
                && ![
                    "که",
                    "چه",
                    "نه",
                    "به",
                    "سه",
                    "بله",
                    "آنچه",
                    "چنانچه",
                    "اگرچه",
                    "گرچه",
                ]
                .contains(&word))
            .then(|| format!("{word}‌{}", &m[2]))
        },
    )?;
    alter(
        &mut masked,
        &mut stats,
        "collapsed_spaces",
        r"(?<=\S)[ \t]{2,}(?=\S)",
        |_| Some(" ".into()),
    )?;
    alter(
        &mut masked,
        &mut stats,
        "trailing_space",
        r"[ \t]+(\r?\n|$)",
        |m| Some(m[1].into()),
    )?;
    let mut pieces = masked.split('\0');
    let mut restored = pieces.next().unwrap_or_default().to_owned();
    for (span, next) in spans.into_iter().zip(pieces) {
        restored.push_str(span);
        restored.push_str(next);
    }
    let fixed = textcore_rs::port::ensure_rli_pdi(restored.clone())
        .map_err(fancy_regex::CompileError::UnexpectedGeneralError)?;
    count(
        &mut stats,
        "missing-rli-pdi",
        fixed
            .matches('\u{2067}')
            .count()
            .saturating_sub(restored.matches('\u{2067}').count())
            .max(usize::from(fixed != restored)),
    );
    Ok((fixed, stats))
}

const STYLE_FLAGS: &[(&str, &str)] = &[
    (r"می‌باشد|می‌باشند|میباشد", "«می‌باشد» -> «است / هستند»"),
    (r"می‌گردد|می‌گردند", "Use an active verb or «می‌شود»."),
    (
        r"مورد\s+\S+\s+قرار\s+(?:می‌گیرد|گرفت|گرفته|داد|می‌دهد)",
        "Use a plain verb, such as «استفاده می‌شود».",
    ),
    (r"\bدارای\b", "«دارای X است» -> «X دارد»"),
    (
        r"\bتوسط\b",
        "Use an active sentence when the actor is known.",
    ),
    (
        r"\bبه عنوان\b|\bبه‌عنوان\b",
        "«به عنوان» often copies English 'as'; try dropping it.",
    ),
    (
        r"\bبه منظور\b|\bبه‌منظور\b|\bدر راستای\b|\bدر جهت\b",
        "Use «برای» where it fits.",
    ),
    (
        r"لازم به ذکر است|شایان ذکر است|قابل ذکر است|قابل توجه است که",
        "Drop the announcement and state the point.",
    ),
    (
        r"نه تنها .{0,60}? بلکه",
        "Try a plain sentence instead of «نه تنها … بلکه».",
    ),
    (
        r"\bدر نهایت\b|\bدر پایان\b|\bبه طور کلی\b|\bدر مجموع\b",
        "Check whether the summary connector adds anything.",
    ),
    (
        r"\bاین امر\b|\bاین موضوع\b|\bاین مسئله\b",
        "Name the subject directly.",
    ),
    (
        r"\bایفا می‌کند\b|\bنقش (?:مهم|کلیدی|حیاتی)",
        "Say what the subject does.",
    ),
    (
        r"\bیک\s+\S+ی?\s+است\b",
        "«یک X است» -> «Xی است» or «X است» where appropriate.",
    ),
];

const MI_WORDS: &str = "میز میزان میزبان میان میانه میانگین میانبر میدان میوه میهن میهمان میمون میل میلاد میلادی میلیون میلیارد میله میخ میت میثاق میراث میکروب میکرو مینا مینو میش میگو میکده میکس میثم میرزا میر میگرن میناکاری میخانه میخک میدانی میلی میکروفون میکروسکوپ میکروفر میلیمتر میلی‌متر میانی میدانها میوه‌ها میزها میلها میخها میسر میکائیل میناب میامی میگل میلان میکل میکی میترا میثاق‌نامه";

pub fn suggestions(text: &str, style: bool) -> Result<Vec<Suggestion>, fancy_regex::Error> {
    let (masked, _) = mask(text)?;
    let mut out = Vec::new();
    let mut gather = |pattern: &str,
                      kind,
                      hint,
                      before: usize,
                      after: usize|
     -> Result<(), fancy_regex::Error> {
        for hit in Regex::new(pattern)?.find_iter(&masked) {
            let hit = hit?;
            let term = hit.as_str().trim();
            if kind == "maybe_glued_mi" {
                let word = term.strip_prefix('ن').unwrap_or(term);
                if MI_WORDS
                    .split_whitespace()
                    .any(|value| value == word || value == word.trim_end_matches('ی'))
                {
                    continue;
                }
            }
            let start = masked[..hit.start()]
                .char_indices()
                .rev()
                .nth(before - 1)
                .map_or(0, |(i, _)| i);
            let end = masked[hit.end()..]
                .char_indices()
                .nth(after)
                .map_or(masked.len(), |(i, _)| hit.end() + i);
            out.push(Suggestion {
                kind,
                hint,
                message: format!("{term}: {hint}"),
                context: masked[start..end].replace(['\n', '\0'], " "),
            });
        }
        Ok(())
    };
    gather(
        &format!(r"(?<=[{PLD}])[ \t]+تر(?![{PL}])"),
        "maybe_comparative_tar",
        "Join «تر» with ZWNJ if comparative; leave it separate if it means 'wet'.",
        12,
        3,
    )?;
    gather(
        &format!(r"(?<![{PL}‌])ن?می[{PL}]+"),
        "maybe_glued_mi",
        "If «می» is a verb prefix, insert ZWNJ.",
        3,
        3,
    )?;
    gather(
        "\u{2014}",
        "em_dash",
        "Rephrase or use a spaced en dash if a dash is needed.",
        12,
        12,
    )?;
    if style {
        for (pattern, hint) in STYLE_FLAGS {
            gather(pattern, "style", hint, 15, 15)?;
        }
    }
    Ok(out)
}

pub fn lint_persian(
    text: &str,
    digits: Digits,
    style: bool,
) -> Result<LintReport, fancy_regex::Error> {
    let (fixed, stats) = normalize(text, digits)?;
    let changes: Vec<_> = text
        .split('\n')
        .zip(fixed.split('\n'))
        .enumerate()
        .filter(|(_, (before, after))| before != after)
        .map(|(i, (before, after))| LineChange {
            line: i + 1,
            before: before.into(),
            after: after.into(),
        })
        .collect();
    let changed_lines = changes.len();
    Ok(LintReport {
        fixed,
        stats,
        changes,
        changed_lines,
        suggestions: suggestions(text, style)?,
    })
}

#[derive(Debug, Serialize)]
pub struct LexiconEntry {
    pub en: &'static str,
    pub fa: &'static str,
    pub note: &'static str,
}

#[derive(Debug, Serialize)]
pub struct LexiconHits {
    pub idioms: Vec<LexiconEntry>,
    pub glossary: Vec<LexiconEntry>,
}

impl LexiconHits {
    pub fn brief(&self) -> String {
        let n = self.idioms.len() + self.glossary.len();
        if n == 0 {
            return "(no idiom / glossary terms found in source)\n".into();
        }
        let mut out = format!(
            "# Terminology brief ({n} {})\n\n",
            if n == 1 { "entry" } else { "entries" }
        );
        for (title, rows) in [
            ("IDIOMS", &self.idioms),
            ("GLOSSARY / COLLOCATIONS", &self.glossary),
        ] {
            if rows.is_empty() {
                continue;
            }
            let _ = writeln!(out, "## {title}");
            for row in rows {
                let _ = write!(out, "- {}  ->  {}", row.en, row.fa);
                if !row.note.is_empty() {
                    let _ = write!(out, "   ({})", row.note);
                }
                out.push('\n');
            }
            out.push('\n');
        }
        out
    }
}

fn bank(tsv: &'static str, text: &str, reverse: bool) -> Result<Vec<LexiconEntry>, regex::Error> {
    let mut seen = HashSet::new();
    let mut hits = Vec::new();
    for line in tsv.lines().filter(|l| !l.trim_start().starts_with('#')) {
        let mut fields = line.split('\t').map(str::trim);
        let (Some(en), Some(fa)) = (fields.next(), fields.next()) else {
            continue;
        };
        if en.is_empty() || fa.is_empty() {
            continue;
        }
        let matched = if reverse {
            fa.split('/')
                .next()
                .is_some_and(|form| !form.trim().is_empty() && text.contains(form.trim()))
        } else {
            let words = en
                .split_whitespace()
                .map(regex::escape)
                .collect::<Vec<_>>()
                .join(r"\s+");
            let last = en.split_whitespace().next_back().unwrap_or_default();
            let upper =
                last.chars().any(char::is_uppercase) && !last.chars().any(char::is_lowercase);
            let flag = if upper { "" } else { "(?i)" };
            let suffix = if !upper && last.chars().count() > 2 {
                "(?:es|s|ed|ing|d)?"
            } else {
                ""
            };
            regex::Regex::new(&format!(r"{flag}\b{words}{suffix}\b"))?.is_match(text)
        };
        if matched && seen.insert(en) {
            hits.push(LexiconEntry {
                en,
                fa,
                note: fields.next().unwrap_or_default(),
            });
        }
    }
    Ok(hits)
}

pub fn lookup_lexicon(text: &str, reverse: bool) -> Result<LexiconHits, regex::Error> {
    Ok(LexiconHits {
        idioms: bank(IDIOMS, text, reverse)?,
        glossary: bank(GLOSSARY, text, reverse)?,
    })
}
