use crate::{IrError, RegionState, regions, workspace};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

pub type Fields = Map<String, Value>;
pub type BBox = [i64; 4];
pub const SCHEMA_VERSION: u32 = 1;
pub const REGION_KINDS: &[&str] = &[
    "speech",
    "thought",
    "narration",
    "sfx",
    "sign",
    "unknown",
    "balloon",
    "caption",
    "title",
    "watermark",
];
pub const ORIENTATIONS: &[&str] = &["horizontal", "vertical"];
pub const IMAGE_SUFFIXES: &[&str] = &["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif"];

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ComicDocument {
    #[serde(alias = "schema_version")]
    pub version: u32,
    pub meta: Fields,
    pub source: Fields,
    pub pages: Vec<PageRecord>,
    pub glossary: Fields,
    pub stages: Fields,
    #[serde(flatten)]
    pub extra: Fields,
}

impl Default for ComicDocument {
    fn default() -> Self {
        new_doc("auto", "fa", "rtl", "", "")
    }
}

pub fn new_doc(
    source_language: &str,
    target_language: &str,
    reading_direction: &str,
    title: &str,
    chapter: &str,
) -> ComicDocument {
    ComicDocument {
        version: SCHEMA_VERSION,
        meta: Fields::from_iter([
            ("tool".into(), json!("revayat-comic 1.0.0")),
            ("title".into(), json!(title)),
            ("chapter".into(), json!(chapter)),
            ("source_language".into(), json!(source_language)),
            ("target_language".into(), json!(target_language)),
            ("reading_direction".into(), json!(reading_direction)),
            ("sfx_policy".into(), json!("keep")),
        ]),
        source: Fields::new(),
        pages: Vec::new(),
        glossary: Fields::new(),
        stages: Fields::new(),
        extra: Fields::new(),
    }
}

impl ComicDocument {
    pub fn policy(&self) -> &str {
        self.meta
            .get("sfx_policy")
            .and_then(Value::as_str)
            .unwrap_or("keep")
    }
    pub fn find_page(&self, id: &str) -> Option<&PageRecord> {
        self.pages.iter().find(|page| page.id == id)
    }
    pub fn find_page_mut(&mut self, id: &str) -> Option<&mut PageRecord> {
        self.pages.iter_mut().find(|page| page.id == id)
    }
    pub fn iter_regions(&self) -> impl Iterator<Item = (&PageRecord, &RegionRecord)> {
        self.pages
            .iter()
            .flat_map(|page| page.regions.iter().map(move |region| (page, region)))
    }
    pub fn find_region(&self, id: &str) -> Option<(&PageRecord, &RegionRecord)> {
        self.iter_regions().find(|(_, region)| region.id == id)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct PageRecord {
    pub id: String,
    pub index: usize,
    #[serde(alias = "source_path")]
    pub image: String,
    pub sha256: String,
    pub width: u32,
    pub height: u32,
    pub panels: Vec<Value>,
    pub regions: Vec<RegionRecord>,
    pub notes: Vec<Value>,
    #[serde(
        rename = "clean",
        alias = "cleaned",
        alias = "clean_path",
        skip_serializing_if = "Option::is_none"
    )]
    pub cleaned: Option<String>,
    #[serde(
        rename = "final",
        alias = "rendered",
        alias = "final_path",
        skip_serializing_if = "Option::is_none"
    )]
    pub rendered: Option<String>,
    #[serde(flatten)]
    pub extra: Fields,
}

pub fn new_page(
    id: impl Into<String>,
    index: usize,
    image: impl Into<String>,
    width: u32,
    height: u32,
    sha256: impl Into<String>,
) -> PageRecord {
    PageRecord {
        id: id.into(),
        index,
        image: image.into(),
        width,
        height,
        sha256: sha256.into(),
        ..PageRecord::default()
    }
}

fn is_false(value: &bool) -> bool {
    !value
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct RegionRecord {
    pub id: String,
    pub bbox: BBox,
    pub polygon: Vec<Value>,
    pub kind: String,
    pub orientation: String,
    pub reading_order: i64,
    pub panel: Option<Value>,
    pub speaker: Option<String>,
    #[serde(alias = "ocr_text")]
    pub source_text: String,
    #[serde(alias = "fa_text")]
    pub target_text: String,
    pub detector: String,
    pub confidence: f64,
    #[serde(alias = "mask_path")]
    pub mask: Option<String>,
    pub fill: String,
    pub typeset: Fields,
    pub locked: bool,
    pub review: Vec<String>,
    #[serde(skip_serializing_if = "is_false")]
    pub dropped: bool,
    #[serde(skip_serializing_if = "is_false")]
    pub keep: bool,
    #[serde(skip_serializing_if = "is_false")]
    pub erase: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub state: Option<RegionState>,
    #[serde(flatten)]
    pub extra: Fields,
}

impl Default for RegionRecord {
    fn default() -> Self {
        Self {
            id: String::new(),
            bbox: [0; 4],
            polygon: Vec::new(),
            kind: "unknown".into(),
            orientation: "horizontal".into(),
            reading_order: 0,
            panel: None,
            speaker: None,
            source_text: String::new(),
            target_text: String::new(),
            detector: "classical".into(),
            confidence: 0.0,
            mask: None,
            fill: "none".into(),
            typeset: Fields::new(),
            locked: false,
            review: vec![],
            dropped: false,
            keep: false,
            erase: false,
            state: None,
            extra: Fields::new(),
        }
    }
}

pub fn new_region(
    id: impl Into<String>,
    bbox: [f64; 4],
    kind: &str,
    orientation: &str,
    detector: &str,
    confidence: f64,
) -> Result<RegionRecord, IrError> {
    if !REGION_KINDS.contains(&kind) || !ORIENTATIONS.contains(&orientation) {
        return Err(IrError::refused(
            "bad_kind",
            format!("invalid kind or orientation: {kind} {orientation}"),
        ));
    }
    if !confidence.is_finite()
        || bbox
            .iter()
            .any(|x| !x.is_finite() || *x < i64::MIN as f64 || *x >= i64::MAX as f64)
    {
        return Err(IrError::refused(
            "invalid_geometry",
            "non-finite or out-of-range region coordinate",
        ));
    }
    Ok(RegionRecord {
        id: id.into(),
        bbox: bbox.map(|x| x.round_ties_even() as i64),
        kind: kind.into(),
        orientation: orientation.into(),
        detector: detector.into(),
        confidence,
        ..RegionRecord::default()
    })
}

pub fn page_id_for(index: usize) -> String {
    format!("p{:04}", index.saturating_add(1))
}
pub fn region_id_for(page_id: &str, ordinal: usize) -> String {
    format!("{page_id}_r{ordinal:03}")
}

pub fn write_stream(
    path: impl AsRef<Path>,
    write: impl FnOnce(&mut File) -> io::Result<()>,
) -> Result<(), IrError> {
    let path = path.as_ref();
    let parent = doc_dir(path);
    fs::create_dir_all(&parent)?;
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    write(temp.as_file_mut())?;
    temp.as_file().sync_all()?;
    temp.persist(path).map_err(|error| error.error)?;
    Ok(())
}

pub fn write_bytes(path: impl AsRef<Path>, bytes: &[u8]) -> Result<(), IrError> {
    write_stream(path, |file| file.write_all(bytes))
}
pub fn write_text(path: impl AsRef<Path>, text: &str) -> Result<(), IrError> {
    write_bytes(path, text.as_bytes())
}
pub fn read_text(path: impl AsRef<Path>) -> Result<String, IrError> {
    Ok(fs::read_to_string(path)?)
}

pub fn dumps(value: &impl Serialize) -> Result<String, IrError> {
    let mut serializer = serde_json::Serializer::with_formatter(
        Vec::new(),
        serde_json::ser::PrettyFormatter::with_indent(b" "),
    );
    value.serialize(&mut serializer)?;
    String::from_utf8(serializer.into_inner())
        .map_err(|error| IrError::refused("encoding", error.to_string()))
}

pub fn json_bytes(value: &impl Serialize) -> Result<Vec<u8>, IrError> {
    let mut text = dumps(value)?.into_bytes();
    text.push(b'\n');
    Ok(text)
}

fn digest_hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;

    let mut hex = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        let _ = write!(hex, "{b:02x}");
    }
    hex
}

pub fn sha256_reader(mut reader: impl Read) -> io::Result<String> {
    let mut digest = Sha256::new();
    let mut buf = [0; 8192];
    loop {
        match reader.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => digest.update(&buf[..n]),
            Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
            Err(err) => return Err(err),
        }
    }
    Ok(digest_hex(&digest.finalize()))
}

pub fn sha256_file(path: impl AsRef<Path>) -> Result<String, IrError> {
    Ok(sha256_reader(File::open(path)?)?)
}

pub fn sha256_bytes(payload: &[u8]) -> String {
    digest_hex(&Sha256::digest(payload))
}
pub fn doc_dir(path: impl AsRef<Path>) -> PathBuf {
    path.as_ref()
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."))
        .to_path_buf()
}
pub fn resolve(doc_path: impl AsRef<Path>, asset: impl AsRef<Path>) -> PathBuf {
    doc_dir(doc_path).join(asset)
}

pub fn decode_doc(raw: &[u8]) -> Result<ComicDocument, IrError> {
    let value: Value = serde_json::from_slice(raw)?;
    let version = value.get("version").or_else(|| value.get("schema_version"));
    if version.and_then(Value::as_u64) != Some(u64::from(SCHEMA_VERSION)) {
        return Err(IrError::refused(
            "schema",
            format!(
                "document schema {version:?}, this build reads {SCHEMA_VERSION}. Re-run import to rebuild it"
            ),
        ));
    }
    Ok(serde_json::from_value(value)?)
}
pub fn load_doc(path: impl AsRef<Path>) -> Result<ComicDocument, IrError> {
    decode_doc(&fs::read(path)?)
}
pub fn save_doc(doc: &ComicDocument, path: impl AsRef<Path>) -> Result<(), IrError> {
    let path = path.as_ref();
    let _claim = workspace::workspace_lock(doc_dir(path), "save")?;
    write_bytes(path, &json_bytes(doc)?)
}

pub fn page_fingerprint(page: &PageRecord) -> String {
    let mut hash = Sha256::new();
    hash.update(format!("{}|{}", page.id, page.sha256));
    for region in &page.regions {
        let bbox = region.bbox.map(|v| v.to_string()).join(",");
        hash.update(format!(
            "{}|{}|{}|{}",
            region.id, bbox, region.kind, region.orientation
        ));
    }
    digest_hex(&hash.finalize())
}
pub fn fingerprint(doc: &ComicDocument) -> String {
    let mut hash = Sha256::new();
    for page in &doc.pages {
        hash.update(page_fingerprint(page));
    }
    digest_hex(&hash.finalize())
}

pub fn state_census(doc: &ComicDocument) -> Result<BTreeMap<RegionState, usize>, IrError> {
    let mut result = RegionState::ALL
        .into_iter()
        .map(|state| (state, 0))
        .collect::<BTreeMap<_, _>>();
    for (_, region) in doc.iter_regions() {
        *result
            .entry(regions::region_state(region, doc.policy())?)
            .or_default() += 1;
    }
    Ok(result)
}

pub fn title_policy(doc: &ComicDocument) -> Fields {
    let written = doc.meta.get("title_policy");
    [
        "honorifics",
        "names",
        "sfx",
        "slang",
        "profanity",
        "register",
    ]
    .into_iter()
    .filter_map(|key| {
        let value = written?.get(key)?;
        let text = value
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| value.to_string());
        (!value.is_null() && !text.trim().is_empty()).then(|| (key.into(), json!(text.trim())))
    })
    .collect()
}

pub fn sfx_conflict(doc: &ComicDocument) -> Option<String> {
    let selected = doc.policy().trim().to_ascii_lowercase();
    let rules = title_policy(doc);
    let prose = rules.get("sfx")?.as_str()?.to_lowercase();
    let mentioned: Vec<_> = ["keep", "translate", "bilingual", "annotate"]
        .into_iter()
        .filter(|item| prose.contains(item))
        .collect();
    (!mentioned.is_empty() && !mentioned.contains(&selected.as_str())).then(|| {
        format!(
            "title_policy.sfx says {} while meta.sfx_policy is {selected:?}",
            mentioned.join(" and ")
        )
    })
}

pub use textcore_rs::port::{ensure_rli_pdi, ensure_rlm_rli_pdi, normalize_persian_text};

const SCRIPT_NAMES: [&str; 7] = [
    "arabic", "latin", "hiragana", "katakana", "han", "hangul", "cyrillic",
];
fn script(ch: char) -> Option<&'static str> {
    Some(match u32::from(ch) {
        0x0600..=0x06ff | 0x0750..=0x077f | 0xfb50..=0xfdff | 0xfe70..=0xfeff => "arabic",
        0x0041..=0x005a | 0x0061..=0x007a | 0x00c0..=0x024f => "latin",
        0x3040..=0x309f => "hiragana",
        0x30a0..=0x30ff | 0x31f0..=0x31ff => "katakana",
        0x3400..=0x4dbf | 0x4e00..=0x9fff | 0xf900..=0xfaff => "han",
        0xac00..=0xd7af | 0x1100..=0x11ff | 0x3130..=0x318f => "hangul",
        0x0400..=0x04ff => "cyrillic",
        _ => return None,
    })
}
pub fn script_counts(text: &str) -> BTreeMap<&'static str, usize> {
    let mut counts = SCRIPT_NAMES
        .into_iter()
        .map(|name| (name, 0))
        .collect::<BTreeMap<_, _>>();
    for name in text.chars().filter_map(script) {
        *counts.entry(name).or_default() += 1;
    }
    counts
}
pub fn dominant_script(text: &str) -> &'static str {
    let counts = script_counts(text);
    SCRIPT_NAMES
        .into_iter()
        .rev()
        .max_by_key(|name| counts[name])
        .filter(|name| counts[name] != 0)
        .unwrap_or("none")
}
pub fn looks_like(text: &str, language: &str) -> bool {
    let c = script_counts(text);
    let n = c.values().sum::<usize>();
    if n == 0 {
        return false;
    }
    let fraction = |count| count as f64 / n as f64;
    match language {
        "fa" | "ar" | "fas" | "per" => fraction(c["arabic"]) > 0.5,
        "ja" | "jpn" => fraction(c["hiragana"] + c["katakana"] + c["han"]) > 0.5,
        "ko" | "kor" => fraction(c["hangul"]) > 0.4,
        "zh" | "zho" | "cmn" => fraction(c["han"]) > 0.5,
        "en" | "eng" => fraction(c["latin"]) > 0.5,
        _ => true,
    }
}
pub fn is_persian(text: &str) -> bool {
    text.contains(['گ', 'چ', 'پ', 'ژ', 'ک', 'ی']) && looks_like(text, "fa")
}

fn order_boxes(boxes: &[BBox], rtl: bool, tolerance: f64) -> Vec<usize> {
    let mut positions: Vec<_> = (0..boxes.len()).collect();
    positions.sort_by_key(|i| boxes[*i][1]);
    let mut bands: Vec<(f64, f64, Vec<usize>)> = Vec::new();
    for i in positions {
        let y = boxes[i][1] as f64;
        let h = boxes[i][3] as f64;
        if let Some((_, bottom, members)) = bands
            .iter_mut()
            .find(|(top, bottom, _)| y < *bottom - tolerance * h.min(*bottom - *top))
        {
            *bottom = bottom.max(y + h);
            members.push(i);
        } else {
            bands.push((y, y + h, vec![i]));
        }
    }
    bands
        .into_iter()
        .flat_map(|(_, _, mut band)| {
            band.sort_by(|i, j| {
                let order = bbox_center(boxes[*i])[0].total_cmp(&bbox_center(boxes[*j])[0]);
                if rtl { order.reverse() } else { order }
            });
            band
        })
        .collect()
}
pub fn assign_reading_order(
    page: &mut PageRecord,
    direction: &str,
    tolerance: f64,
) -> Result<(), IrError> {
    let rtl = direction == "rtl";
    let panels: Vec<_> = page
        .panels
        .iter()
        .map(|p| {
            let id = p
                .get("id")
                .ok_or_else(|| IrError::refused("invalid_panel", "missing panel ID"))?;
            let bbox: BBox = serde_json::from_value(p["bbox"].clone())?;
            Ok::<_, IrError>((id, bbox))
        })
        .collect::<Result<_, _>>()?;
    let panel_boxes: Vec<_> = panels.iter().map(|(_, bbox)| *bbox).collect();
    let ordered = order_boxes(&panel_boxes, rtl, tolerance);
    let mut groups = vec![Vec::new(); panels.len() + 1];
    for (i, r) in page.regions.iter().enumerate() {
        let group = r
            .panel
            .as_ref()
            .and_then(|id| panels.iter().position(|(p, _)| id == *p))
            .unwrap_or(panels.len());
        groups[group].push(i);
    }
    let mut count = 0i64;
    for group in ordered.into_iter().chain([panels.len()]) {
        let boxes: Vec<_> = groups[group]
            .iter()
            .map(|i| page.regions[*i].bbox)
            .collect();
        for index in order_boxes(&boxes, rtl, tolerance) {
            count = count.saturating_add(1);
            page.regions[groups[group][index]].reading_order = count;
        }
    }
    page.regions.sort_by_key(|r| r.reading_order);
    Ok(())
}

pub fn bbox_area(b: BBox) -> f64 {
    b[2].max(0) as f64 * b[3].max(0) as f64
}
pub fn bbox_corners([x, y, w, h]: BBox) -> BBox {
    [x, y, x.saturating_add(w), y.saturating_add(h)]
}
pub fn bbox_intersection(a: BBox, b: BBox) -> f64 {
    let [x1, y1, x2, y2] = bbox_corners(a);
    let [u1, v1, u2, v2] = bbox_corners(b);
    x2.min(u2).saturating_sub(x1.max(u1)).max(0) as f64
        * y2.min(v2).saturating_sub(y1.max(v1)).max(0) as f64
}
pub fn bbox_iou(a: BBox, b: BBox) -> f64 {
    let overlap = bbox_intersection(a, b);
    let union = bbox_area(a) + bbox_area(b) - overlap;
    if union > 0.0 { overlap / union } else { 0.0 }
}
pub fn bbox_contains(outer: BBox, inner: BBox, share: f64) -> bool {
    let area = bbox_area(inner);
    area > 0.0 && bbox_intersection(outer, inner) / area >= share
}
pub fn clamp_bbox(b: BBox, width: u32, height: u32) -> BBox {
    let [x, y, r, b] = bbox_corners(b);
    let (w, h) = (i64::from(width), i64::from(height));
    let (x, y) = (x.clamp(0, w), y.clamp(0, h));
    [x, y, r.clamp(x, w) - x, b.clamp(y, h) - y]
}
pub fn expand_bbox([x, y, w, h]: BBox, amount: i64, width: u32, height: u32) -> BBox {
    let doubled = amount.saturating_mul(2);
    clamp_bbox(
        [
            x.saturating_sub(amount),
            y.saturating_sub(amount),
            w.saturating_add(doubled),
            h.saturating_add(doubled),
        ],
        width,
        height,
    )
}
pub fn bbox_center([x, y, w, h]: BBox) -> [f64; 2] {
    [x as f64 + w as f64 / 2.0, y as f64 + h as f64 / 2.0]
}
