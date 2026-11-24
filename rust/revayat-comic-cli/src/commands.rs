use std::ffi::{OsStr, OsString};

use num_bigint::BigInt;
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use serde_json::json;

use crate::VERSION;

const ENTRY_LIMIT: usize = 4096;
const BAND_LIMIT: usize = 128;
const GEOMETRY_LIMIT: u64 = 1 << 53;
const HELP: &str = "Usage: revayat-comic <command>\n\
    \nCommands:\n\
    \x20 doctor [--json]     Check all nine Rust kernels (no stdin).\n\
    \x20 normalize-persian   Normalize Persian text from UTF-8 stdin.\n\
    \x20 wrap-lines          Compute line breaks from JSON on stdin.\n\
    \x20 sort-pages          Naturally sort page names from JSON on stdin.\n\
    \x20 check-geometry      Validate page dimensions from JSON on stdin.\n\
    \nOptions: --help, --version\n";

#[derive(Clone, Copy)]
pub enum Command {
    Help,
    Version,
    Doctor { json: bool },
    NormalizePersian,
    WrapLines,
    SortPages,
    CheckGeometry,
}

#[derive(Clone, Copy)]
pub enum Failure {
    Usage(&'static str),
    Runtime(&'static str),
}

impl Failure {
    pub fn code(self) -> u8 {
        match self {
            Self::Usage(_) => 2,
            Self::Runtime(_) => 1,
        }
    }

    pub fn message(self) -> &'static str {
        match self {
            Self::Usage(message) | Self::Runtime(message) => message,
        }
    }
}

impl Command {
    pub fn parse(mut args: impl Iterator<Item = OsString>) -> Result<Self, Failure> {
        let (command, option) = (args.next(), args.next());
        let bad_usage = Failure::Usage("invalid arguments; run --help for usage");
        if args.next().is_some() {
            return Err(bad_usage);
        }
        match (
            command.as_deref().and_then(OsStr::to_str),
            option.as_deref(),
        ) {
            (Some("--help"), None) => Ok(Self::Help),
            (Some("--version"), None) => Ok(Self::Version),
            (Some("doctor"), None) => Ok(Self::Doctor { json: false }),
            (Some("doctor"), Some(flag)) if flag == "--json" => Ok(Self::Doctor { json: true }),
            (Some("normalize-persian"), None) => Ok(Self::NormalizePersian),
            (Some("wrap-lines"), None) => Ok(Self::WrapLines),
            (Some("sort-pages"), None) => Ok(Self::SortPages),
            (Some("check-geometry"), None) => Ok(Self::CheckGeometry),
            _ => Err(bad_usage),
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::Help => "help",
            Self::Version => "version",
            Self::Doctor { .. } => "doctor",
            Self::NormalizePersian => "normalize-persian",
            Self::WrapLines => "wrap-lines",
            Self::SortPages => "sort-pages",
            Self::CheckGeometry => "check-geometry",
        }
    }

    pub fn reads_input(self) -> bool {
        !matches!(self, Self::Help | Self::Version | Self::Doctor { .. })
    }

    pub fn run(self, input: String) -> Result<(String, u8), Failure> {
        let output = match self {
            Self::Help => HELP.to_owned(),
            Self::Version => format!("revayat-comic {VERSION}\n"),
            Self::Doctor { json } => return doctor(json),
            Self::NormalizePersian => textcore_rs::port::normalize_persian_text(input)
                .map_err(|_| Failure::Runtime("Persian normalization failed"))?,
            Self::WrapLines => wrap_lines(&input)?,
            Self::SortPages => sort_pages(&input)?,
            Self::CheckGeometry => return check_geometry(&input),
        };
        Ok((output, 0))
    }
}

fn doctor(as_json: bool) -> Result<(String, u8), Failure> {
    let checks = [
        (
            "cleancore-rs",
            cleancore_rs::port::compute_feather_alpha(Some(&[0, 128, 1]), 1, 3, 2)
                == Ok(vec![0, 128, 128]),
        ),
        (
            "detectcore-rs",
            detectcore_rs::port::connected_components_boxes(Some(&[1, 0, 0, 2]), 2, 2, 2, 2)
                == Ok(vec![[0, 0, 2, 2, 2]]),
        ),
        (
            "hotcore-rs",
            hotcore_rs::port::box_gap(vec![0, 0, 10, 10], vec![13, 14, 5, 5]) == Ok(5.0),
        ),
        (
            "layoutcore-rs",
            layoutcore_rs::port::scan_mask_spans(Some(&[0, 1, 1]), Some(3), Some(1))
                == Ok(vec![[1, 3]]),
        ),
        (
            "maskcore-rs",
            maskcore_rs::port::dilate_linf(Some(&[255, 0, 0]), 3, 1, 1) == Ok(vec![255, 255, 0]),
        ),
        (
            "packcore-rs",
            packcore_rs::port::natural_sort_order(vec![b"page10".to_vec(), b"page2".to_vec()])
                == [1, 0],
        ),
        (
            "pixcore-rs",
            pixcore_rs::port::changed_mask_rgb(&[0, 0, 255], &[0, 7, 247], 1, 1, 7)
                == Ok(vec![255]),
        ),
        (
            "qacore-rs",
            qacore_rs::port::compute_ink_bounds(Some(&[0, 0, 0]), Some(&[0, 0, 20]), 1, 1, 20)
                == Ok(vec![0, 0, 1, 1, 1]),
        ),
        (
            "textcore-rs",
            textcore_rs::port::normalize_persian_text("كتاب ها را ببین".to_owned()).as_deref()
                == Ok("کتاب‌ها را ببین"),
        ),
    ];
    let ok = checks.iter().all(|&(_, passed)| passed);
    let output = if as_json {
        let kernels: std::collections::BTreeMap<_, _> = checks.into_iter().collect();
        json_line(&json!({ "version": VERSION, "ok": ok, "kernels": kernels }))?
    } else {
        use std::fmt::Write as _;
        let status = if ok { "ok" } else { "failed" };
        let mut output = format!("revayat-comic {VERSION}: {status}\n");
        for (name, passed) in checks {
            let status = if passed { "ok" } else { "failed" };
            let _ = writeln!(output, "{name}: {status}");
        }
        output
    };
    Ok((output, u8::from(!ok)))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WrapInput {
    word_widths: Vec<String>,
    space_width: String,
    band_widths: Vec<String>,
}

fn wrap_lines(input: &str) -> Result<String, Failure> {
    let request: WrapInput = json_object(
        input,
        "expected wrap-lines JSON with word_widths, space_width and band_widths",
    )?;
    if request.word_widths.len() > ENTRY_LIMIT {
        return Err(Failure::Usage("word_widths accepts at most 4096 entries"));
    }
    if !(1..=BAND_LIMIT).contains(&request.band_widths.len()) {
        return Err(Failure::Usage("band_widths requires 1 to 128 entries"));
    }
    let words = request
        .word_widths
        .iter()
        .map(|width| decimal_width(width, true))
        .collect::<Result<_, _>>()?;
    let space = decimal_width(&request.space_width, false)?;
    let bands = request
        .band_widths
        .iter()
        .map(|width| decimal_width(width, false))
        .collect::<Result<_, _>>()?;
    let lines = textcore_rs::port::balanced_wrap_lines(words, space, bands)
        .map_err(|_| Failure::Runtime("line wrapping failed"))?;
    json_line(&lines)
}

fn decimal_width(input: &str, positive: bool) -> Result<BigInt, Failure> {
    let invalid = Failure::Usage(
        "widths must be decimal strings of 1 to 128 ASCII digits; word widths must be positive",
    );
    if !(1..=128).contains(&input.len()) || !input.bytes().all(|b| b.is_ascii_digit()) {
        return Err(invalid);
    }
    let width = BigInt::parse_bytes(input.as_bytes(), 10).ok_or(invalid)?;
    if positive && width == BigInt::ZERO {
        return Err(invalid);
    }
    Ok(width)
}

fn sort_pages(input: &str) -> Result<String, Failure> {
    let pages: Vec<String> = serde_json::from_str(input)
        .map_err(|_| Failure::Usage("expected a JSON array of page-name strings"))?;
    if pages.len() > ENTRY_LIMIT {
        return Err(Failure::Usage("sort-pages accepts at most 4096 entries"));
    }
    if pages
        .iter()
        .any(|name| name.is_empty() || name.contains('\0'))
    {
        return Err(Failure::Usage(
            "page names must be nonempty and contain no NUL",
        ));
    }
    let names = pages.iter().map(|name| name.as_bytes().to_vec()).collect();
    let order = packcore_rs::port::natural_sort_order(names);
    let sorted: Vec<_> = order.into_iter().map(|i| &pages[i]).collect();
    json_line(&sorted)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GeometryInput {
    dimensions: Vec<[u64; 2]>,
    max_aspect_ratio: f64,
    min_edge: u64,
    max_pixels: u64,
}

fn check_geometry(input: &str) -> Result<(String, u8), Failure> {
    let request: GeometryInput = json_object(
        input,
        "expected check-geometry JSON with dimensions, max_aspect_ratio, min_edge and max_pixels",
    )?;
    if request.dimensions.len() > ENTRY_LIMIT {
        return Err(Failure::Usage(
            "check-geometry accepts at most 4096 entries",
        ));
    }
    if !request.max_aspect_ratio.is_finite() || request.max_aspect_ratio < 1.0 {
        return Err(Failure::Usage(
            "max_aspect_ratio must be finite and at least 1",
        ));
    }
    if [request.min_edge, request.max_pixels]
        .into_iter()
        .chain(request.dimensions.iter().flatten().copied())
        .any(|n| !(1..=GEOMETRY_LIMIT).contains(&n))
    {
        return Err(Failure::Usage("geometry integers must be in 1..=2^53"));
    }
    let mut invalid_pages = Vec::new();
    for (i, [width, height]) in request.dimensions.into_iter().enumerate() {
        let valid = packcore_rs::port::validate_page_dimensions(
            i128::from(width),
            i128::from(height),
            request.max_aspect_ratio,
            i128::from(request.min_edge),
            i128::from(request.max_pixels),
        )
        .ok_or(Failure::Runtime("geometry validation failed"))?;
        if !valid {
            invalid_pages.push(i);
        }
    }
    let ok = invalid_pages.is_empty();
    let output = json_line(&json!({ "ok": ok, "invalid_pages": invalid_pages }))?;
    Ok((output, u8::from(!ok)))
}

fn json_object<T: DeserializeOwned>(input: &str, message: &'static str) -> Result<T, Failure> {
    if !input
        .trim_start_matches([' ', '\n', '\r', '\t'])
        .starts_with('{')
    {
        return Err(Failure::Usage(message));
    }
    serde_json::from_str(input).map_err(|_| Failure::Usage(message))
}

fn json_line(value: &impl Serialize) -> Result<String, Failure> {
    let mut text = serde_json::to_string(value)
        .map_err(|_| Failure::Runtime("could not encode JSON output"))?;
    text.push('\n');
    Ok(text)
}
