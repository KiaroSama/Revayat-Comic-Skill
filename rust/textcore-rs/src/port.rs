//! Native Persian text and shaped-band line breaking.
#![forbid(unsafe_code)]

use fancy_regex::Regex as FancyRegex;
use num_bigint::{BigInt, Sign};
use regex::Regex;
use std::sync::LazyLock;
use unicode_general_category::{GeneralCategory, get_general_category};

const RLM: char = '\u{200f}';
const RLI: char = '\u{2067}';
const PDI: char = '\u{2069}';
const LOCK: &str = "\u{200f}\u{2067}";
const LINE_PATTERN: &str = r"\r\n|[\r\n\x0b\x0c\x85\u{2028}\u{2029}]";
const FENCE: &str = concat!(
    r"(?ms:^ {0,3}(?P<fence>(?P<marker>[`~])(?P=marker){2,})(?!(?P=marker))[^\n]*\n.*?",
    r"(?:^ {0,3}(?P=fence)(?P=marker)*[ \t]*(?=\r?$)|\z))",
);
const CODE: &str = r"(?P<code>`+)[^\r\n]*?(?P=code)";
const URL: &str = r#"(?i:https?://|www\.)[^\s\x1c-\x1f<>"'«»\u{2066}-\u{2069}`]+"#;
const PY_BOUNDARY: &str =
    r"(?:(?<![\p{L}\p{N}_])(?=[\p{L}\p{N}_])|(?<=[\p{L}\p{N}_])(?![\p{L}\p{N}_]))";
const PY_SPACE: &str = r"[\s\x1c-\x1f]";
const VERSION: &str = concat!(
    r"(?<![\p{L}\p{N}_])(?:[vV]?(?:[0-9٠-٩۰-۹]+[.:/\-])+[0-9٠-٩۰-۹]+",
    r"(?:[-+][A-Za-z0-9][A-Za-z0-9.-]*)?|[vV][0-9]+)(?![\p{L}\p{N}_])",
);
const TRAILING_ADDRESS: &str = ".!?؟…)]}»›\"'”’";
const PERSIAN_LETTERS: &str = r"[ء-غف-يٮ-ۓۺ-ۿ]";
const PERSIAN: &str =
    r"[\u{0600}-\u{06ff}\u{0750}-\u{077f}\u{08a0}-\u{08ff}\u{fb50}-\u{fdff}\u{fe70}-\u{fefc}]";
static PERSIAN_RE: LazyLock<Result<Regex, regex::Error>> = LazyLock::new(|| Regex::new(PERSIAN));
static LINES: LazyLock<Result<Regex, regex::Error>> = LazyLock::new(|| Regex::new(LINE_PATTERN));
static FENCES: LazyLock<Result<FancyRegex, fancy_regex::Error>> = LazyLock::new(|| fancy(FENCE));
static PROTECTED: LazyLock<Result<FancyRegex, fancy_regex::Error>> = LazyLock::new(|| {
    fancy(&format!(
        "{FENCE}|{CODE}|(?P<address>{})|{PY_BOUNDARY}(?:[A-Za-z]\\.){{2,}}|{PY_BOUNDARY}(?i:Mr|Mrs|Ms|Dr|Prof|St|vs)\\.(?={PY_SPACE})",
        addresses(),
    ))
});
static NORMAL_PROTECTED: LazyLock<Result<FancyRegex, fancy_regex::Error>> = LazyLock::new(|| {
    let fences = FENCE
        .replace("^ {0,3}", r"(?:^|(?<=[\x85\u{2028}\u{2029}])) {0,3}")
        .replace(
            r"[^\n]*\n",
            r"[^\n\x85\u{2028}\u{2029}]*[\n\x85\u{2028}\u{2029}]",
        )
        .replace(r"(?=\r?$)", r"(?=\r?(?:$|[\x85\u{2028}\u{2029}]))");
    fancy(&format!("{fences}|{CODE}|{}|{VERSION}", addresses()))
});
static DIGITS: LazyLock<Result<Regex, regex::Error>> = LazyLock::new(|| Regex::new(r"[0-9٠-٩]+"));
static AFFIXES: LazyLock<Result<FancyRegex, fancy_regex::Error>> = LazyLock::new(|| {
    fancy(&format!(
        r"({PERSIAN_LETTERS}+)([ \u{{200c}}]+)(?={PERSIAN_LETTERS})"
    ))
});
static WORD: LazyLock<Result<Regex, regex::Error>> =
    LazyLock::new(|| Regex::new(&format!("^{PERSIAN_LETTERS}+")));

fn addresses() -> String {
    let word_or_hyphen = r"[\p{L}\p{N}_-]";
    format!(r"{URL}|{PY_BOUNDARY}[\p{{L}}\p{{N}}_.+%\-]+@{word_or_hyphen}+(?:\.{word_or_hyphen}+)+")
}

fn compiled<T, E: std::fmt::Display>(source: &Result<T, E>) -> Result<&T, String> {
    source
        .as_ref()
        .map_err(|err| format!("RuntimeError: {err}"))
}

fn match_error(error: fancy_regex::Error) -> String {
    format!("RuntimeError: {error}")
}

fn fancy(pattern: &str) -> Result<FancyRegex, fancy_regex::Error> {
    // These fixed patterns operate over entire worksheets, not capped field lengths.
    fancy_regex::RegexBuilder::new(pattern)
        .backtrack_limit(usize::MAX)
        .build()
}

fn space(ch: char) -> bool {
    ch.is_whitespace() || matches!(ch, '\x1c'..='\x1f')
}

fn opener(ch: char) -> bool {
    matches!(ch, '\u{2066}'..='\u{2068}')
}

fn leading(ch: char) -> bool {
    space(ch)
        || matches!(
            ch,
            '\u{2066}'..='\u{2069}' | '\u{200e}' | RLM | '\u{061c}' | '\u{feff}' | '"' | '\''
        )
        || (!ch.is_ascii() || matches!(ch, '(' | '[' | '{'))
            && matches!(
                get_general_category(ch),
                GeneralCategory::OpenPunctuation | GeneralCategory::InitialPunctuation
            )
}

pub fn starts_with_latin_in_persian(text: String) -> Result<bool, String> {
    Ok(text
        .chars()
        .find(|&ch| !leading(ch))
        .is_some_and(|ch| ch.is_ascii_alphabetic())
        && compiled(&PERSIAN_RE)?.is_match(&text))
}

fn line_break(ch: char) -> bool {
    matches!(
        ch,
        '\r' | '\n' | '\x0b' | '\x0c' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

fn pairs(chars: &[char]) -> Vec<Option<usize>> {
    let mut pending = Vec::new();
    let mut pairs = vec![None; chars.len()];
    for (i, &ch) in chars.iter().enumerate() {
        if opener(ch) {
            pending.push(i);
        } else if ch == PDI
            && let Some(start) = pending.pop()
        {
            pairs[start] = Some(i);
            pairs[i] = Some(start);
        }
    }
    pairs
}

fn sentence_end(ch: char) -> bool {
    matches!(ch, '.' | '!' | '?' | '؟' | '…')
}

fn sentence_closer(ch: char) -> bool {
    matches!(
        ch,
        ']' | ')' | '}' | '»' | '›' | '"' | '\'' | '”' | '’' | PDI
    )
}

fn push_sentence(output: &mut String, text: &str, shadow: &[char]) {
    let first = shadow.iter().copied().find(|&ch| !leading(ch));
    if !first.is_some_and(|ch| ch.is_ascii_alphabetic())
        || !shadow.iter().copied().any(persian_char)
    {
        output.push_str(text);
        return;
    }
    let left = text.len() - text.trim_start_matches(space).len();
    let right = text.trim_end_matches(space).len();
    let body = &text[left..right];
    let start = text[..left].chars().count();
    let visible = &shadow[start..shadow.len() - text[right..].chars().count()];
    let pairs = pairs(visible);
    let mut removed = vec![false; visible.len()];
    for (i, &ch) in visible.iter().enumerate() {
        removed[i] = (opener(ch) || ch == PDI) && pairs[i].is_none();
    }
    for (i, &ch) in visible.iter().enumerate() {
        if removed[i] || space(ch) {
            continue;
        }
        if ch != RLI {
            break;
        }
        if let Some(end) = pairs[i] {
            removed[i] = true;
            removed[end] = true;
        }
    }
    output.push_str(&text[..left]);
    output.push(RLI);
    if removed.iter().any(|&remove| remove) {
        let mut cleaned = String::with_capacity(body.len());
        let mut gap = false;
        for (i, ch) in body.chars().enumerate() {
            if removed[i] {
                gap |= pairs[i].is_none();
            } else {
                if gap
                    && cleaned.chars().next_back().is_some_and(py_alphanumeric)
                    && py_alphanumeric(ch)
                {
                    cleaned.push(' ');
                }
                cleaned.push(ch);
                gap = false;
            }
        }
        output.push_str(cleaned.trim_matches(space));
    } else {
        output.push_str(body);
    }
    output.push(PDI);
    output.push_str(&text[right..]);
}

fn persian_char(ch: char) -> bool {
    matches!(ch, '\u{0600}'..='\u{06ff}' | '\u{0750}'..='\u{077f}' | '\u{08a0}'..='\u{08ff}' | '\u{fb50}'..='\u{fdff}' | '\u{fe70}'..='\u{fefc}')
}

fn py_alphanumeric(ch: char) -> bool {
    if ch.is_ascii() {
        return ch.is_ascii_alphanumeric();
    }
    use GeneralCategory as G;
    matches!(
        get_general_category(ch),
        G::UppercaseLetter
            | G::LowercaseLetter
            | G::TitlecaseLetter
            | G::ModifierLetter
            | G::OtherLetter
            | G::DecimalNumber
            | G::LetterNumber
            | G::OtherNumber
    )
}

fn push_sentences(output: &mut String, line: &str, shadow: &str, persian: &Regex) {
    if !persian.is_match(shadow) {
        output.push_str(line);
        return;
    }
    let visible: Vec<_> = shadow.chars().collect();
    let pairs = pairs(&visible);
    let positions: Vec<_> = line
        .char_indices()
        .map(|(i, _)| i)
        .chain([line.len()])
        .collect();
    let mut active = Vec::new();
    let (mut left, mut i) = (0, 0);
    while i < visible.len() {
        let ch = visible[i];
        if !sentence_end(ch) {
            if pairs[i].is_some() {
                if opener(ch) {
                    active.push(i);
                } else {
                    active.pop();
                }
            }
            i += 1;
            continue;
        }
        let start = i;
        while visible.get(i).is_some_and(|&ch| sentence_end(ch)) {
            i += 1;
        }
        let lone_dot = i == start + 1 && ch == '.';
        let embedded = active
            .last()
            .is_some_and(|&inner| visible[left..inner].iter().any(|&ch| !leading(ch)));
        while visible.get(i).is_some_and(|&ch| sentence_closer(ch)) {
            if visible[i] == PDI && pairs[i].is_some() {
                active.pop();
            }
            i += 1;
        }
        if !active.is_empty() || embedded {
            continue;
        }
        if lone_dot
            && i == start + 1
            && start > 0
            && i < visible.len()
            && visible[start - 1].is_ascii_alphanumeric()
            && visible[i].is_ascii_alphanumeric()
        {
            continue;
        }
        push_sentence(
            output,
            &line[positions[left]..positions[i]],
            &visible[left..i],
        );
        left = i;
    }
    push_sentence(output, &line[positions[left]..], &visible[left..]);
}

pub fn ensure_rli_pdi(text: String) -> Result<String, String> {
    let persian = compiled(&PERSIAN_RE)?;
    if !persian.is_match(&text) {
        return Ok(text);
    }
    let mut shadow = String::with_capacity(text.len());
    let mut last = 0;
    for capture in compiled(&PROTECTED)?.captures_iter(&text) {
        let capture = capture.map_err(match_error)?;
        let token = capture
            .get(0)
            .ok_or("RuntimeError: missing protected match")?;
        let address = capture.name("address").is_some();
        let token_text = token.as_str();
        let body = if address {
            token_text.trim_end_matches(|ch| TRAILING_ADDRESS.contains(ch))
        } else {
            token_text
        };
        shadow.push_str(&text[last..token.start()]);
        for (i, ch) in body.chars().enumerate() {
            let keep = line_break(ch) || i == 0 && (address || ch.is_ascii_alphabetic());
            shadow.push(if keep { ch } else { '\0' });
        }
        shadow.push_str(&token_text[body.len()..]);
        last = token.end();
    }
    let lines = compiled(&LINES)?;
    let mut output = String::with_capacity(text.len());
    if last == 0 {
        push_text_lines(&mut output, &text, &text, lines, persian);
    } else {
        shadow.push_str(&text[last..]);
        push_text_lines(&mut output, &text, &shadow, lines, persian);
    }
    Ok(output)
}

fn push_text_lines(output: &mut String, text: &str, shadow: &str, lines: &Regex, persian: &Regex) {
    let (mut text_start, mut shadow_start) = (0, 0);
    for (original, visible) in lines.find_iter(text).zip(lines.find_iter(shadow)) {
        push_sentences(
            output,
            &text[text_start..original.start()],
            &shadow[shadow_start..visible.start()],
            persian,
        );
        output.push_str(original.as_str());
        text_start = original.end();
        shadow_start = visible.end();
    }
    push_sentences(
        output,
        &text[text_start..],
        &shadow[shadow_start..],
        persian,
    );
}

fn push_locked_lines(output: &mut String, text: &str, lines: &Regex, persian: &Regex) {
    let mut start = 0;
    for separator in lines.find_iter(text) {
        push_locked_line(output, &text[start..separator.start()], persian);
        output.push_str(separator.as_str());
        start = separator.end();
    }
    push_locked_line(output, &text[start..], persian);
}

fn push_locked_line(output: &mut String, line: &str, persian: &Regex) {
    let body = line.trim_matches(space);
    if !persian.is_match(line) || body.starts_with(LOCK) && body.ends_with(PDI) {
        output.push_str(line);
        return;
    }
    let start = line.len() - line.trim_start_matches(space).len();
    let end = line.trim_end_matches(space).len();
    let inner = body.trim_start_matches(RLM);
    let inner = inner
        .strip_prefix(RLI)
        .and_then(|text| text.strip_suffix(PDI))
        .unwrap_or(inner);
    output.push_str(&line[..start]);
    output.push_str(LOCK);
    output.push_str(inner);
    output.push(PDI);
    output.push_str(&line[end..]);
}

pub fn ensure_rlm_rli_pdi(text: String) -> Result<String, String> {
    let persian = compiled(&PERSIAN_RE)?;
    if !persian.is_match(&text) {
        return Ok(text);
    }
    let lines = compiled(&LINES)?;
    let mut out = String::with_capacity(text.len());
    let mut last = 0;
    for fence in compiled(&FENCES)?.find_iter(&text) {
        let fence = fence.map_err(match_error)?;
        push_locked_lines(&mut out, &text[last..fence.start()], lines, persian);
        out.push_str(fence.as_str());
        last = fence.end();
    }
    push_locked_lines(&mut out, &text[last..], lines, persian);
    Ok(out)
}

fn normalized_char(ch: char) -> Option<char> {
    Some(match ch {
        'ي' | 'ى' => 'ی',
        'ك' => 'ک',
        'ة' => 'ه',
        'ـ' => return None,
        '\u{2029}' | '\u{2028}' | '\u{85}' => '\n',
        _ => ch,
    })
}

fn letter(ch: char) -> bool {
    matches!(ch, 'ء'..='غ' | 'ف'..='ي' | 'ٮ'..='ۓ' | 'ۺ'..='ۿ')
}

fn punct_context(ch: char) -> bool {
    letter(ch) || ('۰'..='۹').contains(&ch)
}

fn space_for_normalizer(ch: char) -> bool {
    matches!(ch, ' ' | '\t')
}

fn normalized_digit(ch: char) -> char {
    match ch {
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
        '٠' => '۰',
        '١' => '۱',
        '٢' => '۲',
        '٣' => '۳',
        '٤' => '۴',
        '٥' => '۵',
        '٦' => '۶',
        '٧' => '۷',
        '٨' => '۸',
        '٩' => '۹',
        _ => ch,
    }
}

fn normalize_digits(text: &str) -> Result<String, String> {
    let mut out = String::with_capacity(text.len());
    let mut last = 0;
    for digit in compiled(&DIGITS)?.find_iter(text) {
        let (left, right) = (&text[..digit.start()], &text[digit.end()..]);
        let latin = |ch: char| ch.is_ascii_alphanumeric() || ch == '_';
        out.push_str(&text[last..digit.start()]);
        if !left.chars().next_back().is_some_and(latin)
            && !right.chars().next().is_some_and(latin)
            && (left
                .trim_end_matches(space_for_normalizer)
                .chars()
                .next_back()
                .is_some_and(letter)
                || right
                    .trim_start_matches(space_for_normalizer)
                    .chars()
                    .next()
                    .is_some_and(letter))
        {
            out.extend(digit.as_str().chars().map(normalized_digit));
        } else {
            out.push_str(digit.as_str());
        }
        last = digit.end();
    }
    out.push_str(&text[last..]);
    Ok(out)
}

fn normalize_punctuation(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut left = None;
    for (i, ch) in text.char_indices() {
        let localized = match ch {
            ',' => '،',
            ';' => '؛',
            '?' => '؟',
            _ => ch,
        };
        if localized != ch
            && (left.is_some_and(punct_context)
                || text[i + 1..]
                    .trim_start_matches(space_for_normalizer)
                    .chars()
                    .next()
                    .is_some_and(punct_context))
        {
            out.push(localized);
        } else {
            out.push(ch);
        }
        if !space_for_normalizer(ch) {
            left = Some(ch);
        }
    }
    out
}

const VERB_STEMS: &[&str] = &[
    "رو", "کن", "شو", "خواه", "توان", "دان", "گوی", "بین", "آی", "گیر", "خور", "زن", "آور", "افت",
    "رس", "مان", "نویس", "خوان", "پرس", "ترس", "فهم", "شناس", "ایست", "نشین", "گرد", "کش", "دار",
    "گذار", "ساز", "شکن", "بند", "پوش", "خند", "گری",
];
const POSSESSIVES: &[&str] = &["هایشان", "هایتان", "هایمان", "هایی", "هایم", "هایت", "هایش"];

fn verb_form(word: &str) -> bool {
    VERB_STEMS.iter().any(|stem| {
        word.strip_prefix(stem)
            .is_some_and(|tail| matches!(tail, "م" | "ی" | "د" | "یم" | "ید" | "ند"))
    })
}

fn plural_anchor(tail: &str) -> bool {
    let tail_no_spaces = tail.trim_start_matches(' ');
    tail.len() != tail_no_spaces.len()
        && ["را", "ی"].iter().any(|anchor| {
            tail_no_spaces.strip_prefix(anchor).is_some_and(|rest| {
                rest.chars()
                    .next()
                    .is_none_or(|ch| !py_alphanumeric(ch) && ch != '_')
            })
        })
}

fn normalize_affixes(text: &str) -> Result<String, String> {
    let word = compiled(&WORD)?;
    let mut output = String::with_capacity(text.len());
    let mut last = 0;
    for capture in compiled(&AFFIXES)?.captures_iter(text) {
        let capture = capture.map_err(match_error)?;
        let Some((piece, left, gap)) = capture
            .get(0)
            .zip(capture.get(1))
            .zip(capture.get(2))
            .map(|((p, l), g)| (p, l, g))
        else {
            return Err("RuntimeError: missing affix capture".into());
        };
        output.push_str(&text[last..piece.start()]);
        let left = left.as_str();
        let existing = gap.as_str().contains('\u{200c}');
        let right = &text[piece.end()..];
        let join = word.find(right).is_some_and(|suffix| {
            let value = suffix.as_str();
            matches!(left, "می" | "نمی") && (existing || verb_form(value))
                || left.chars().nth(1).is_some()
                    && (value == "ترین"
                        || POSSESSIVES.contains(&value)
                        || matches!(value, "ها" | "های")
                            && (existing || plural_anchor(&right[suffix.end()..])))
        });
        if join {
            output.push_str(left);
            output.push('\u{200c}');
        } else {
            output.push_str(piece.as_str());
        }
        last = piece.end();
    }
    output.push_str(&text[last..]);
    Ok(output)
}

fn normalize_segment(text: &str) -> Result<String, String> {
    if text.is_ascii() {
        return Ok(text.to_owned());
    }
    let text: String = text.chars().filter_map(normalized_char).collect();
    let digits = normalize_digits(&text)?;
    let punctuation = normalize_punctuation(&digits);
    normalize_affixes(&punctuation)
}

pub fn normalize_persian_text(text: String) -> Result<String, String> {
    if !compiled(&PERSIAN_RE)?.is_match(&text) && !text.contains(['\u{2029}', '\u{2028}', '\u{85}'])
    {
        return Ok(text);
    }
    let mut out = String::with_capacity(text.len());
    let mut last = 0;
    for span in compiled(&NORMAL_PROTECTED)?.find_iter(&text) {
        let span = span.map_err(match_error)?;
        out.push_str(&normalize_segment(&text[last..span.start()])?);
        out.push_str(span.as_str());
        last = span.end();
    }
    out.push_str(&normalize_segment(&text[last..])?);
    Ok(out)
}

pub fn balanced_wrap_lines(
    word_widths: Vec<BigInt>,
    space_width: BigInt,
    band_widths: Vec<BigInt>,
) -> Result<Vec<Vec<usize>>, String> {
    if word_widths.iter().any(|width| width.sign() != Sign::Plus) {
        return Err("ValueError: word widths must be positive".into());
    }
    if space_width.sign() == Sign::Minus {
        return Err("ValueError: space width must be non-negative".into());
    }
    if band_widths.iter().any(|width| width.sign() == Sign::Minus) {
        return Err("ValueError: band widths must be non-negative".into());
    }
    if band_widths.is_empty() {
        return Err("ValueError: band widths must not be empty".into());
    }
    let n = word_widths.len();
    if n == 0 {
        return Ok(Vec::new());
    }
    let mut next_costs = vec![None; n + 1];
    next_costs[n] = Some(BigInt::ZERO);
    let mut choices = Vec::with_capacity(n.min(band_widths.len()));
    for band in band_widths[..n.min(band_widths.len())].iter().rev() {
        let mut costs = vec![None; n + 1];
        costs[n] = Some(BigInt::ZERO);
        let mut ends = vec![0; n];
        for (start, best) in costs[..n].iter_mut().enumerate() {
            let mut width = -&space_width;
            for (j, word) in word_widths.iter().enumerate().skip(start) {
                width += word;
                width += &space_width;
                if &width > band {
                    break;
                }
                if let Some(after) = &next_costs[j + 1] {
                    let unused = band - &width;
                    let cost = &unused * &unused + after;
                    if best.as_ref().is_none_or(|best| cost < *best) {
                        *best = Some(cost);
                        ends[start] = j + 1;
                    }
                }
            }
        }
        choices.push(ends);
        next_costs = costs;
    }
    if next_costs[0].is_none() {
        return Ok(Vec::new());
    }
    let mut output = Vec::new();
    let mut start = 0;
    for ends in choices.iter().rev() {
        let end = ends[start];
        output.push(vec![start, end]);
        if end == n {
            break;
        }
        start = end;
    }
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mixed_sentences() {
        let text = "Dr. Asano گفت: `x. y?` https://ex.org/a.b. Oslo رسید.";
        let fixed =
            "\u{2067}Dr. Asano گفت: `x. y?` https://ex.org/a.b.\u{2069} \u{2067}Oslo رسید.\u{2069}";
        assert_eq!(ensure_rli_pdi(text.into()).as_deref(), Ok(fixed));
        assert_eq!(ensure_rli_pdi(fixed.into()).as_deref(), Ok(fixed));
        assert_eq!(
            starts_with_latin_in_persian("\x1c『A رسید』".into()),
            Ok(true)
        );
        assert_eq!(starts_with_latin_in_persian("É جا".into()), Ok(false));
    }

    #[test]
    fn isolates_preserve_embedded_direction_and_reattach_strays() {
        assert_eq!(
            ensure_rli_pdi("Tokyo گفت \u{2066}OK.\u{2069} همین الان.".into()).as_deref(),
            Ok("\u{2067}Tokyo گفت \u{2066}OK.\u{2069} همین الان.\u{2069}")
        );
        assert_eq!(
            ensure_rli_pdi("Tokyo\u{2067}رسید.".into()).as_deref(),
            Ok("\u{2067}Tokyo رسید.\u{2069}")
        );
        assert_eq!(
            ensure_rli_pdi("\u{2067}\u{2067}Tokyo رسید.\u{2069}\u{2069}".into()).as_deref(),
            Ok("\u{2067}Tokyo رسید.\u{2069}")
        );
    }

    #[test]
    fn fences_close_only_on_the_same_marker_and_enough_of_it() {
        for marker in ['`', '~'] {
            let short = format!(
                "{marker}{marker}{marker}{marker}\nTokyo رسید.\n{marker}{marker}{marker}\nKyoto رسید."
            );
            assert_eq!(ensure_rli_pdi(short.clone()), Ok(short.clone()));
            assert_eq!(ensure_rlm_rli_pdi(short.clone()), Ok(short));
            let block = format!(
                "{marker}{marker}{marker}\nTokyo رسید.\n{marker}{marker}{marker}{marker}\n"
            );
            let input = block.clone() + "Kyoto رسید.";
            assert_eq!(
                ensure_rli_pdi(input.clone()),
                Ok(block.clone() + "\u{2067}Kyoto رسید.\u{2069}")
            );
            assert_eq!(
                ensure_rlm_rli_pdi(input),
                Ok(block + "\u{200f}\u{2067}Kyoto رسید.\u{2069}")
            );
        }
    }

    #[test]
    fn normalization_protects_code_addresses_and_versions() {
        let input = "كتاب ها را ببین؛ مي رود. كي\u{2029}عدد ١٢? v1.2، `كي 12?` https://ex.org/ي12";
        let fixed = "کتاب‌ها را ببین؛ می‌رود. کی\nعدد ۱۲؟ v1.2، `كي 12?` https://ex.org/ي12";
        assert_eq!(normalize_persian_text(input.into()).as_deref(), Ok(fixed));
        assert_eq!(normalize_persian_text(fixed.into()).as_deref(), Ok(fixed));
    }

    fn wrap(words: &[i64], space: i64, bands: &[i64]) -> Result<Vec<Vec<usize>>, String> {
        balanced_wrap_lines(
            words.iter().copied().map(BigInt::from).collect(),
            space.into(),
            bands.iter().copied().map(BigInt::from).collect(),
        )
    }

    #[test]
    fn fits_each_band_and_breaks_cost_ties_early() {
        assert_eq!(
            wrap(&[4, 4, 4], 1, &[10, 5]),
            Ok(vec![vec![0, 2], vec![2, 3]])
        );
        assert_eq!(
            wrap(&[4, 4, 4], 1, &[10, 10]),
            Ok(vec![vec![0, 1], vec![1, 3]])
        );
        assert_eq!(wrap(&[4, 4, 4], 1, &[3, 20]), Ok(vec![]));
        assert_eq!(wrap(&[], 0, &[0]), Ok(vec![]));
    }

    #[test]
    fn rejects_invalid_widths_before_searching() {
        assert_eq!(
            wrap(&[0], 0, &[4]).as_deref(),
            Err(&"ValueError: word widths must be positive".into())
        );
        assert_eq!(
            wrap(&[1], -1, &[4]).as_deref(),
            Err(&"ValueError: space width must be non-negative".into())
        );
        assert_eq!(
            wrap(&[1], 0, &[-1]).as_deref(),
            Err(&"ValueError: band widths must be non-negative".into())
        );
        assert_eq!(
            wrap(&[], 0, &[]).as_deref(),
            Err(&"ValueError: band widths must not be empty".into())
        );
    }

    #[test]
    fn arbitrary_precision_widths_keep_the_same_slices() {
        let big = BigInt::from(1) << 100;
        assert_eq!(
            balanced_wrap_lines(vec![big, 1.into()], 1.into(), vec![BigInt::from(1) << 101]),
            Ok(vec![vec![0, 2]]),
        );
    }
}
