//! Synthetic page generation and per-axis scoring. Human judgments stay unscored.

use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use cosmic_text::{
    Align, Attrs, Buffer, Color, Family, FontSystem, Metrics, Shaping, SwashCache, Wrap, fontdb,
};
use image::{Rgb, RgbImage};
use imageproc::{drawing as draw, point::Point, rect::Rect};
use serde::Deserialize;
use serde_json::{Map, Value, json};

mod numbers;

const CASES: &str = include_str!("../../../evaluation/cases.json");
const VAZIR: &[u8] = include_bytes!("../../../skills/revayat-comic/assets/fonts/Vazir-Regular.ttf");
const WIDTH: u32 = 1000;
const HEIGHT: u32 = 1500;
const INK: Rgb<u8> = Rgb([20, 20, 20]);
const WHITE: Rgb<u8> = Rgb([255, 255, 255]);

#[derive(Debug, thiserror::Error)]
pub enum EvalError {
    #[error("{0}")]
    Invalid(&'static str),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] io::Error),
    #[error(transparent)]
    Image(#[from] image::ImageError),
    #[error(transparent)]
    Pattern(#[from] fancy_regex::Error),
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum NumberForms {
    One(String),
    Alternatives(Vec<String>),
}

impl NumberForms {
    fn choices(&self) -> &[String] {
        match self {
            Self::One(one) => std::slice::from_ref(one),
            Self::Alternatives(many) => many,
        }
    }
}

#[derive(Debug, Default, Deserialize)]
pub struct Preservation {
    #[serde(default)]
    pub negation: bool,
    #[serde(default)]
    pub ellipsis: bool,
    #[serde(default)]
    pub contrastive_subject: bool,
    #[serde(default)]
    pub question: bool,
    #[serde(default)]
    pub terms: Vec<String>,
    #[serde(default)]
    pub numbers: Vec<NumberForms>,
}

#[derive(Debug, Deserialize)]
pub struct EvalCase {
    pub id: String,
    pub source: Option<String>,
    pub language: Option<String>,
    #[serde(default)]
    pub context: String,
    #[serde(default)]
    pub human_note: String,
    pub continues_into: Option<String>,
    pub continues_from: Option<String>,
    #[serde(default)]
    pub accept: Vec<String>,
    #[serde(default)]
    pub difficulty: Vec<String>,
    #[serde(default)]
    pub human_only: bool,
    pub units: Option<u64>,
    pub balloon: Option<[f64; 2]>,
    pub must_preserve: Option<Preservation>,
}

#[derive(Deserialize)]
struct CaseFile {
    cases: Vec<EvalCase>,
}

pub fn load_cases(path: Option<&Path>) -> Result<Vec<EvalCase>, EvalError> {
    let text = match path {
        Some(path) => fs::read_to_string(path)?,
        None => CASES.to_owned(),
    };
    let CaseFile { cases } = serde_json::from_str(&text)?;
    validate_cases(&cases, false)?;
    Ok(cases)
}

pub fn validate_cases(cases: &[EvalCase], drawing: bool) -> Result<(), EvalError> {
    if cases.is_empty() {
        return Err(EvalError::Invalid(
            "evaluation cases must be a nonempty list",
        ));
    }
    let mut seen = HashSet::new();
    for case in cases {
        let id = case.id.as_bytes();
        if id.is_empty()
            || id.len() > 128
            || !id[0].is_ascii_alphanumeric()
            || !id
                .iter()
                .all(|b| b.is_ascii_alphanumeric() || *b == b'_' || *b == b'-')
            || crate::install::reserved(&case.id)
            || !seen.insert(case.id.to_ascii_lowercase())
        {
            return Err(EvalError::Invalid(
                "evaluation case IDs must be unique safe ASCII names",
            ));
        }
        if case
            .balloon
            .is_some_and(|f| f.iter().any(|v| !v.is_finite() || *v <= 0.0 || *v > 1.0))
        {
            return Err(EvalError::Invalid(
                "evaluation balloon must contain two finite fractions in (0, 1]",
            ));
        }
        if drawing && (case.source.is_none() || case.language.is_none() || dims(case).is_none()) {
            return Err(EvalError::Invalid(
                "page generation requires source, language and a balloon at least 2x2 pixels",
            ));
        }
        if case
            .must_preserve
            .as_ref()
            .is_some_and(|wanted| wanted.numbers.iter().any(|n| n.choices().is_empty()))
        {
            return Err(EvalError::Invalid("number alternatives must be nonempty"));
        }
    }
    Ok(())
}

pub fn validate_answers(
    payload: Value,
    cases: &[EvalCase],
) -> Result<BTreeMap<String, String>, EvalError> {
    let answers: BTreeMap<String, String> = serde_json::from_value(payload)?;
    if answers
        .keys()
        .any(|id| !cases.iter().any(|case| case.id == *id))
    {
        return Err(EvalError::Invalid(
            "evaluation answers contain unknown case IDs",
        ));
    }
    Ok(answers)
}

pub fn check_preserved(case: &EvalCase, answer: &str) -> Result<Map<String, Value>, EvalError> {
    use fancy_regex::Regex;
    let mut checks = Map::new();
    let Some(want) = case.must_preserve.as_ref().filter(|_| !case.human_only) else {
        return Ok(checks);
    };
    if want.negation {
        let certain = Regex::new(
            r"(?:^|\s)(?:نمی|نَمی)[ء-ۿ‌]{2,}|(?:^|\s)(?:نه|هیچ|هرگز|بدون)(?![ء-ۿ])|(?:^|\s)بی‌[ء-ۿ]{2,}",
        )?;
        let maybe = Regex::new(r"(?:^|\s)ن[ء-ۿ‌]{2,}")?;
        checks.insert(
            "negation".into(),
            if certain.is_match(answer)? {
                json!(true)
            } else if maybe.is_match(answer)? {
                json!("review")
            } else {
                json!(false)
            },
        );
    }
    if !want.numbers.is_empty() {
        let missing = numbers::missing(&want.numbers, answer)?;
        checks.insert(
            "numbers".into(),
            json!({"ok":missing.is_empty(),"missing":missing}),
        );
    }
    if !want.terms.is_empty() {
        let mut missing = Vec::new();
        for term in &want.terms {
            if !numbers::term_used(answer, term)? {
                missing.push(term);
            }
        }
        checks.insert(
            "terms".into(),
            json!({"ok":missing.is_empty(),"missing":missing}),
        );
    }
    if want.ellipsis {
        checks.insert(
            "ellipsis".into(),
            json!(answer.contains('…') || answer.contains("..")),
        );
    }
    if want.contrastive_subject {
        checks.insert(
            "contrastive_subject".into(),
            json!(numbers::term_used(answer, "من")?),
        );
    }
    if want.question {
        checks.insert("question".into(), json!(answer.contains(['?', '؟'])));
    }
    Ok(checks)
}

fn dims(case: &EvalCase) -> Option<(i32, i32)> {
    let [width, height] = case.balloon?;
    let (width, height) = (
        (f64::from(WIDTH) * width) as i32,
        (f64::from(HEIGHT) * height) as i32,
    );
    (width >= 2 && height >= 2).then_some((width, height))
}

struct Fitter {
    fonts: FontSystem,
    family: String,
    cache: SwashCache,
}

impl Fitter {
    fn new() -> Option<Self> {
        let mut db = fontdb::Database::new();
        db.load_font_data(VAZIR.to_vec());
        let family = db.faces().next()?.families.first()?.0.clone();
        let fonts = FontSystem::new_with_locale_and_db("fa".into(), db);
        Some(Self {
            fonts,
            family,
            cache: SwashCache::new(),
        })
    }

    fn fits(&mut self, case: &EvalCase, answer: &str) -> Option<bool> {
        let (width, height) = dims(case)?;
        if answer.is_empty() {
            return None;
        }
        let (rx, ry) = (width as f32 / 2.0 - 1.0, height as f32 / 2.0 - 1.0);
        if rx <= 0.0 || ry <= 0.0 {
            return Some(false);
        }
        let mut buffer = Buffer::new(&mut self.fonts, Metrics::new(13.0, 15.0));
        buffer.set_wrap(Wrap::WordOrGlyph);
        buffer.set_text(
            answer,
            &Attrs::new().family(Family::Name(&self.family)),
            Shaping::Advanced,
            Some(Align::Center),
        );
        // Measure rendered ink against the ellipse, not every line's rectangle.
        for size in (13..=48).rev() {
            buffer.set_metrics(Metrics::new(size as f32, (size as f32 * 1.15).ceil()));
            buffer.set_size(Some(width as f32), None);
            buffer.shape_until_scroll(&mut self.fonts, false);
            let h = buffer.layout_runs().last()?.line_top + buffer.metrics().line_height;
            if h > height as f32 {
                continue;
            }
            let y_offset = ((height as f32 - h) / 2.0).round();
            let mut ink = false;
            let mut inside = true;
            buffer.draw(
                &mut self.fonts,
                &mut self.cache,
                Color::rgb(0, 0, 0),
                |x, y, _, _, color| {
                    if color.a() < 16 {
                        return;
                    }
                    ink = true;
                    let dx = (x as f32 - width as f32 / 2.0) / rx;
                    let dy = (y as f32 + y_offset - height as f32 / 2.0) / ry;
                    inside &= dx * dx + dy * dy <= 1.0;
                },
            );
            if ink && inside {
                return Some(true);
            }
        }
        Some(false)
    }
}

pub fn fits(case: &EvalCase, answer: &str) -> Option<bool> {
    Fitter::new()?.fits(case, answer)
}

pub fn score(cases: &[EvalCase], answers: &BTreeMap<String, String>) -> Result<Value, EvalError> {
    validate_cases(cases, false)?;
    if answers
        .keys()
        .any(|id| !cases.iter().any(|case| case.id == *id))
    {
        return Err(EvalError::Invalid(
            "evaluation answers contain unknown case IDs",
        ));
    }
    let mut fitter = Fitter::new();
    let mut rows = Vec::new();
    for case in cases {
        let answer = answers.get(&case.id).map_or("", |s| s.trim());
        let checks = check_preserved(case, answer)?;
        let failed = checks
            .values()
            .any(|value| value == false || value.get("ok").is_some_and(|v| v == false));
        let review: Vec<_> = checks
            .iter()
            .filter(|(_, value)| *value == "review")
            .map(|(name, _)| name)
            .collect();
        let units = answer
            .split(['.', '!', '?', '؟', '؛', '،', '…'])
            .filter(|s| !s.trim().is_empty())
            .count()
            .max(1);
        let measured = fitter.as_mut().and_then(|fit| fit.fits(case, answer));
        rows.push(json!({
            "case":case.id,"language":case.language,"source":case.source.as_deref().unwrap_or_default(),
            "context":case.context,"human_note":case.human_note,"answer":answer,"difficulty":case.difficulty,
            "answered":!answer.is_empty(),
            "adequacy":{"machine_checks":checks,"machine_ok":!answer.is_empty() && !failed,"needs_review":review,"human":null,"ask":"does it say what the source says? read both."},
            "fluency":{"human":null,"ask":"read it aloud: does it sound like Persian someone would say?"},
            "voice":{"human":null,"ask":"does this character sound like the same person, and unlike the others?"},
            "omissions_additions":{"source_units":case.units,"answer_units":units,"flag":case.units.is_some_and(|n| n.abs_diff(units as u64)>1),"human":null,"ask":"count the clauses that went missing or appeared."},
            "visual_fit":{"fits":measured},"matches_a_reference":case.accept.iter().any(|s| s == answer),
        }));
    }
    let collect = |filter: fn(&Value) -> bool| {
        rows.iter()
            .filter(|v| filter(v))
            .map(|v| v["case"].clone())
            .collect::<Vec<_>>()
    };
    let answered = collect(|v| v["answered"] == true);
    Ok(json!({
        "cases":rows.len(),"answered":answered.len(),
        "machine_adequacy_failures":collect(|v| v["answered"] == true && v["adequacy"]["machine_ok"] == false),
        "unit_count_flags":collect(|v| v["omissions_additions"]["flag"] == true),
        "unanswered":collect(|v| v["answered"] == false),
        "needs_review":collect(|v| v["adequacy"]["needs_review"].as_array().is_some_and(|v| !v.is_empty())),
        "does_not_fit":collect(|v| v["visual_fit"]["fits"] == false),
        "fit_not_measured":collect(|v| v["answered"] == true && v["visual_fit"]["fits"].is_null()),
        "awaiting_human_score":answered,"rows":rows,
        "note":"Fluency, voice and adequacy-in-full are not scored here and must not be inferred from what is. A model's opinion of its own work is not evidence."
    }))
}

pub fn run_eval(answers: &Path, cases: Option<&Path>) -> Result<Value, EvalError> {
    let cases = load_cases(cases)?;
    let answers = validate_answers(serde_json::from_slice(&fs::read(answers)?)?, &cases)?;
    score(&cases, &answers)
}

pub fn status(report: &Value, complete: bool) -> i32 {
    let nonempty = |field: &str| {
        report[field]
            .as_array()
            .is_some_and(|list| !list.is_empty())
    };
    i32::from(nonempty("machine_adequacy_failures") || (complete && nonempty("unanswered")))
}

fn polygon(page: &mut RgbImage, points: &[(i32, i32)]) {
    let fill: Vec<_> = points.iter().map(|&(x, y)| Point::new(x, y)).collect();
    let outline: Vec<_> = points
        .iter()
        .map(|&(x, y)| Point::new(x as f32, y as f32))
        .collect();
    draw::draw_polygon_mut(page, &fill, WHITE);
    draw::draw_hollow_polygon_mut(page, &outline, INK);
}

fn ellipse(page: &mut RgbImage, center: (i32, i32), radii: (i32, i32), fill: Rgb<u8>, stroke: i32) {
    draw::draw_filled_ellipse_mut(
        page,
        center,
        radii.0,
        radii.1,
        if stroke > 0 { INK } else { fill },
    );
    if radii.0 > stroke && radii.1 > stroke && stroke > 0 {
        draw::draw_filled_ellipse_mut(page, center, radii.0 - stroke, radii.1 - stroke, fill);
    }
}

fn balloon(page: &mut RgbImage, y: i32, size: (i32, i32), tail: (i32, i32)) {
    let center = (WIDTH as i32 / 2, y);
    ellipse(page, center, (size.0 / 2, size.1 / 2), WHITE, 3);
    polygon(
        page,
        &[
            (center.0, y + size.1 / 2 - 4),
            (center.0 + 18, y + size.1 / 2 - 10),
            tail,
        ],
    );
}

pub fn draw_case(case: &EvalCase) -> Result<RgbImage, EvalError> {
    let size = dims(case).ok_or(EvalError::Invalid(
        "page generation requires a balloon at least 2x2 pixels",
    ))?;
    let mut page = RgbImage::from_pixel(WIDTH, HEIGHT, Rgb([248, 246, 240]));
    for (top, bottom) in [(40, 640), (680, 1460)] {
        draw::draw_filled_rect_mut(
            &mut page,
            Rect::at(40, top).of_size(921, (bottom - top + 1) as u32),
            INK,
        );
        draw::draw_filled_rect_mut(
            &mut page,
            Rect::at(44, top + 4).of_size(913, (bottom - top - 7) as u32),
            Rgb([236, 233, 226]),
        );
    }
    for (cx, top, facing) in [(240, 300, 1), (740, 320, -1)] {
        ellipse(&mut page, (cx, top + 66), (66, 66), WHITE, 3);
        polygon(
            &mut page,
            &[
                (cx - 100, 620),
                (cx + 100, 620),
                (cx + 66, top + 132),
                (cx - 66, top + 132),
            ],
        );
        ellipse(&mut page, (cx + 33 * facing, top + 66), (4, 4), INK, 0);
    }
    balloon(&mut page, 180, size, (260, 320));
    if [&case.continues_into, &case.continues_from]
        .into_iter()
        .any(|s| s.as_ref().is_some_and(|s| !s.is_empty()))
    {
        balloon(&mut page, 820, size, (660, 960));
    }
    Ok(page)
}

pub fn build_pages(cases: Option<&Path>, out: &Path) -> Result<Vec<PathBuf>, EvalError> {
    let cases = load_cases(cases)?;
    validate_cases(&cases, true)?;
    fs::create_dir_all(out)?;
    let mut paths = Vec::new();
    for case in cases {
        let path = out.join(format!("{}.png", case.id));
        let page = draw_case(&case)?;
        let mut image = tempfile::NamedTempFile::new_in(out)?;
        page.write_to(image.as_file_mut(), image::ImageFormat::Png)?;
        image.persist(&path).map_err(|e| e.error)?;
        let mut task = json!({"id":case.id,"source":case.source,"language":case.language});
        if !case.context.is_empty() {
            task["context"] = case.context.into();
        }
        if let Some(next) = case.continues_into {
            task["continues_into"] = next.into();
        }
        if let Some(prev) = case.continues_from {
            task["continues_from"] = prev.into();
        }
        let mut file = tempfile::NamedTempFile::new_in(out)?;
        serde_json::to_writer_pretty(&mut file, &task)?;
        file.write_all(b"\n")?;
        file.persist(out.join(format!("{}.input.json", case.id)))
            .map_err(|e| e.error)?;
        paths.push(path);
    }
    Ok(paths)
}
