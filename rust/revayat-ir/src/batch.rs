use crate::{ComicDocument, IrError, PageRecord, ir, stages, workspace};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};

pub const MANIFEST: &str = "batch-manifest.json";
pub type PendingAssets = BTreeMap<PathBuf, PathBuf>;
pub type AssetSnapshot = BTreeMap<String, Option<String>>;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Snapshot {
    pub document: String,
    pub shared: String,
    pub assets: AssetSnapshot,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct BatchItem {
    pub id: String,
    pub workdir: String,
    pub pages: Option<[usize; 2]>,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input: Option<PathBuf>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct BatchPlan {
    pub mode: String,
    pub source: PathBuf,
    pub workers: usize,
    pub items: Vec<BatchItem>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub snapshot: Option<Snapshot>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MergeReport {
    pub document: PathBuf,
    pub pages: usize,
    pub shards: usize,
}

fn bad(code: &'static str, message: impl Into<String>) -> IrError {
    IrError::refused(code, message)
}
pub fn shared_digest(doc: &Value, legacy: bool) -> Result<String, IrError> {
    let mut shared = doc
        .as_object()
        .cloned()
        .ok_or_else(|| bad("invalid_document", "expected a chapter object"))?;
    for key in ["pages", "stages"] {
        shared.remove(key);
    }
    if let Some(meta) = shared.get_mut("meta").and_then(Value::as_object_mut) {
        meta.remove("worksheets");
        meta.remove("free_lettering_mask");
        if !legacy {
            meta.remove("stage_seq");
        }
    }
    if let Some(source) = shared.get_mut("source").and_then(Value::as_object_mut) {
        source.remove("page_count");
    }
    if !legacy
        && shared
            .get("source")
            .is_some_and(|v| v.is_null() || v.as_object().is_some_and(ir::Fields::is_empty))
    {
        shared.remove("source");
    }
    Ok(ir::sha256_bytes(
        stages::sorted_json(&Value::Object(shared))?.as_bytes(),
    ))
}
pub(crate) fn owned(root: &Path, path: &Path) -> Result<PathBuf, IrError> {
    let relative = if path.is_absolute() {
        path.strip_prefix(root)
            .map_err(|_| bad("unsafe_asset", path.display().to_string()))?
    } else {
        path
    };
    let mut current = root.to_path_buf();
    for part in relative.components() {
        let Component::Normal(part) = part else {
            return Err(bad("unsafe_asset", path.display().to_string()));
        };
        current.push(part);
        match fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err(bad("unsafe_asset", current.display().to_string()));
            }
            Ok(_) => (),
            Err(e) if e.kind() == io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.into()),
        }
    }
    if current == root {
        return Err(bad("unsafe_asset", "asset must be beneath its workspace"));
    }
    Ok(current)
}
pub(crate) fn digest(path: &Path) -> Result<Option<String>, IrError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_file() => Ok(Some(ir::sha256_file(path)?)),
        Ok(_) => Err(bad(
            "unsafe_asset",
            format!("expected a regular file: {}", path.display()),
        )),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.into()),
    }
}
fn rel(root: &Path, path: &Path) -> Result<String, IrError> {
    let path = path
        .strip_prefix(root)
        .map_err(|_| bad("unsafe_asset", path.display().to_string()))?;
    Ok(path
        .components()
        .map(|p| p.as_os_str().to_string_lossy())
        .collect::<Vec<_>>()
        .join("/"))
}
fn page_id(id: &str) -> bool {
    id.strip_prefix('p')
        .is_some_and(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
}
fn check_page(page: &PageRecord) -> Result<(), IrError> {
    if !page_id(&page.id) {
        return Err(bad("invalid_page_id", &page.id));
    }
    let mut ids = BTreeSet::new();
    for r in &page.regions {
        if r.id.is_empty()
            || !r
                .id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
            || !ids.insert(&r.id)
        {
            return Err(bad("invalid_region_id", &r.id));
        }
    }
    Ok(())
}
fn folder(root: &Path, doc: &ComicDocument) -> Result<PathBuf, IrError> {
    owned(
        root,
        &crate::worksheet_paths::worksheet_folder(&root.join("comic.json"), doc, None),
    )
}
fn page_asset(
    root: &Path,
    name: &str,
    dir: &str,
    id: &str,
    nested: bool,
) -> Result<PathBuf, IrError> {
    if name.is_empty() {
        return Err(bad("missing_asset", format!("{id}: missing {dir} asset")));
    }
    let path = owned(root, Path::new(name))?;
    let parent = root.join(dir);
    let valid = if nested {
        path.parent() == Some(parent.join(id).as_path())
    } else {
        path.parent() == Some(parent.as_path())
            && (dir == "pages" || path.file_stem().and_then(|s| s.to_str()) == Some(id))
    };
    if !valid {
        return Err(bad(
            "unsafe_asset",
            format!("{id}: {dir} asset not in page scope: {name}"),
        ));
    }
    Ok(path)
}
fn children(path: &Path) -> Result<Vec<PathBuf>, IrError> {
    match fs::read_dir(path) {
        Ok(dir) => {
            let mut out = dir
                .map(|e| e.map(|x| x.path()))
                .collect::<Result<Vec<_>, _>>()?;
            out.sort();
            Ok(out)
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(e) => Err(e.into()),
    }
}
fn page_files(
    root: &Path,
    page: &PageRecord,
    worksheets: &Path,
    include_source: bool,
) -> Result<BTreeSet<PathBuf>, IrError> {
    let mut files = BTreeSet::new();
    let id = &page.id;
    if include_source {
        files.insert(page_asset(root, &page.image, "pages", id, false)?);
    }
    for (dir, name) in [
        ("clean", page.cleaned.as_deref()),
        ("final", page.rendered.as_deref()),
    ] {
        if let Some(name) = name {
            files.insert(page_asset(root, name, dir, id, false)?);
        }
    }
    for name in ["mask", "writable"]
        .into_iter()
        .filter_map(|key| page.extra.get(key).and_then(Value::as_str))
        .chain(page.regions.iter().filter_map(|r| r.mask.as_deref()))
    {
        page_asset(root, name, "masks", id, true)?;
    }
    for name in page
        .extra
        .get("overview")
        .and_then(Value::as_str)
        .into_iter()
        .chain(
            page.extra
                .get("sheets")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str),
        )
    {
        page_asset(root, name, "crops", id, true)?;
    }
    for dir in ["masks", "crops"] {
        for path in children(&owned(root, &Path::new(dir).join(id))?)? {
            if path.extension().is_some_and(|e| e == "png") {
                files.insert(owned(root, &path)?);
            }
        }
    }
    for path in children(worksheets)? {
        if path
            .file_name()
            .and_then(|n| n.to_str())
            .is_some_and(|n| n.starts_with(&format!("{id}.")))
            && path
                .extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| matches!(e, "txt" | "md" | "json"))
        {
            files.insert(owned(root, &path)?);
        }
    }
    Ok(files)
}
fn asset_snapshot(root: &Path, doc: &ComicDocument) -> Result<AssetSnapshot, IrError> {
    let worksheets = folder(root, doc)?;
    let mut files = BTreeSet::from([owned(root, Path::new("glossary.json"))?]);
    for page in &doc.pages {
        check_page(page)?;
        files.extend(page_files(root, page, &worksheets, true)?);
    }
    files
        .into_iter()
        .map(|p| Ok((rel(root, &p)?, digest(&p)?)))
        .collect()
}
pub fn snapshot(root: &Path, doc: &ComicDocument) -> Result<Snapshot, IrError> {
    let root = fs::canonicalize(root)?;
    let raw = fs::read(owned(&root, Path::new("comic.json"))?)?;
    Ok(Snapshot {
        document: ir::sha256_bytes(&raw),
        shared: shared_digest(&serde_json::from_slice(&raw)?, false)?,
        assets: asset_snapshot(&root, doc)?,
    })
}
fn valid_digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub fn publish_if_changed(
    root: &Path,
    doc: &ComicDocument,
    snapshot: &Snapshot,
    pending: &PendingAssets,
    publish: impl FnOnce() -> Result<(), IrError>,
) -> Result<bool, IrError> {
    let root = fs::canonicalize(root)?;
    if !valid_digest(&snapshot.document)
        || !valid_digest(&snapshot.shared)
        || snapshot.assets.values().flatten().any(|v| !valid_digest(v))
    {
        return Err(bad(
            "invalid_snapshot",
            "batch has no valid frozen snapshot; preserve drafts and create a new plan",
        ));
    }
    let raw = fs::read(owned(&root, Path::new("comic.json"))?)?;
    let current_doc = ir::decode_doc(&raw)?;
    let untyped: Value = serde_json::from_slice(&raw)?;
    if snapshot.shared != shared_digest(&untyped, false)?
        && snapshot.shared != shared_digest(&untyped, true)?
    {
        return Err(bad(
            "shared_drift",
            "shared chapter inputs changed after the batch snapshot",
        ));
    }
    if shared_digest(&serde_json::to_value(doc)?, false)?
        != shared_digest(&serde_json::to_value(&current_doc)?, false)?
    {
        return Err(bad("shared_drift", "worker changed shared chapter inputs"));
    }
    let assets = asset_snapshot(&root, &current_doc)?;
    let mut expected = snapshot.assets.clone();
    for (target, source) in pending {
        let path = owned(&root, target)?;
        expected.insert(
            rel(&root, &path)?,
            Some(
                digest(source)?
                    .ok_or_else(|| bad("missing_asset", source.display().to_string()))?,
            ),
        );
    }
    if current_doc == *doc && assets.keys().all(|name| expected.contains_key(name)) {
        let mut identical = true;
        for (name, wanted) in &expected {
            if digest(&owned(&root, Path::new(name))?)? != *wanted {
                identical = false;
                break;
            }
        }
        if identical {
            return Ok(false);
        }
    }
    if ir::sha256_bytes(&raw) != snapshot.document || assets != snapshot.assets {
        return Err(bad(
            "snapshot_drift",
            "chapter changed after the batch snapshot; preserve drafts and reconcile before replanning",
        ));
    }
    for target in pending.keys() {
        let path = owned(&root, target)?;
        if !snapshot.assets.contains_key(&rel(&root, &path)?) && path.exists() {
            return Err(bad(
                "snapshot_drift",
                format!(
                    "chapter asset changed after the batch snapshot: {}",
                    path.display()
                ),
            ));
        }
    }
    publish()?;
    Ok(true)
}

const PAGE_MAPS: [&str; 2] = ["pages", "page_options"];
fn stage_slice(all: &ir::Fields, ids: &BTreeSet<&str>) -> ir::Fields {
    let mut out = all.clone();
    for (_, record) in &mut out {
        for field in PAGE_MAPS {
            if let Some(pages) = record.get_mut(field).and_then(Value::as_object_mut) {
                pages.retain(|id, _| ids.contains(id.as_str()));
            }
        }
        if let Some(needs) = record.get_mut("needs").and_then(Value::as_object_mut) {
            for (_, value) in needs {
                if let Some(rows) = value.as_object_mut() {
                    rows.retain(|id, _| ids.contains(id.as_str()));
                }
            }
        }
    }
    out
}
pub fn merge_page_stages(target: &mut ir::Fields, source: &ir::Fields, id: &str) {
    let names: BTreeSet<_> = target.keys().chain(source.keys()).cloned().collect();
    for name in names {
        let record = source.get(&name).unwrap_or(&Value::Null);
        if !target.contains_key(&name) {
            target.extend(stage_slice(
                &ir::Fields::from_iter([(name.clone(), record.clone())]),
                &BTreeSet::new(),
            ));
        }
        let Some(dst) = target.get_mut(&name) else {
            continue;
        };
        if record["scheme"] == stages::SCHEME && dst["scheme"] != stages::SCHEME {
            *dst = record.clone();
            for field in PAGE_MAPS.into_iter().chain(["needs"]) {
                dst[field] = json!({});
            }
        }
        let same = dst["scheme"] == record["scheme"];
        for field in PAGE_MAPS {
            if let Some(rows) = dst.get_mut(field).and_then(Value::as_object_mut) {
                rows.remove(id);
            }
            if same && let Some(item) = record[field].get(id) {
                if !dst[field].is_object() {
                    dst[field] = json!({});
                }
                dst[field][id] = item.clone();
            }
        }
        if let Some(needs) = dst.get_mut("needs").and_then(Value::as_object_mut) {
            for (_, row) in needs {
                if let Some(pages) = row.as_object_mut() {
                    pages.remove(id);
                }
            }
        }
        if same && let Some(needs) = record["needs"].as_object() {
            for (need, rows) in needs {
                if let Some(value) = rows.get(id) {
                    if !dst["needs"].is_object() {
                        dst["needs"] = json!({});
                    }
                    if !dst["needs"][need].is_object() {
                        dst["needs"][need] = json!({});
                    }
                    dst["needs"][need][id] = value.clone();
                }
            }
        }
    }
}
fn copy(from: &Path, to: &Path) -> Result<(), IrError> {
    fs::create_dir_all(ir::doc_dir(to))?;
    fs::copy(from, to)?;
    Ok(())
}
#[path = "batch_plan.rs"]
mod planning;
pub use planning::{plan_books, plan_shards};

fn retarget(page: &mut PageRecord, worksheets: &Path) {
    if let Some(receipt) = page
        .extra
        .get_mut("worksheet_receipt")
        .and_then(Value::as_object_mut)
    {
        receipt.insert(
            "path".into(),
            json!(worksheets.join(format!("{}.done.txt", page.id))),
        );
    }
}
pub fn write_manifest(root: &Path, plan: &BatchPlan) -> Result<(), IrError> {
    ir::write_bytes(root.join(MANIFEST), &ir::json_bytes(plan)?)
}
pub fn read_manifest(root: &Path) -> Result<BatchPlan, IrError> {
    Ok(serde_json::from_slice(&fs::read(owned(
        root,
        Path::new(MANIFEST),
    )?)?)?)
}

pub fn merge_shards(batch: &Path, root: &Path) -> Result<MergeReport, IrError> {
    let batch = fs::canonicalize(batch)?;
    let root = fs::canonicalize(root)?;
    let manifest = read_manifest(&batch)?;
    if manifest.mode != "shards"
        || manifest.items.len() != manifest.workers
        || manifest.workers == 0
    {
        return Err(bad("invalid_manifest", "expected a shards manifest"));
    }
    let frozen = manifest.snapshot.ok_or_else(|| {
        bad(
            "invalid_snapshot",
            "batch has no valid frozen snapshot; preserve drafts and create a new plan",
        )
    })?;
    let claim = workspace::workspace_lock(&root, "merge-shards")?;
    let doc_path = owned(&root, Path::new("comic.json"))?;
    let mut loaded = workspace::LoadedDocument::open(&doc_path)?;
    let source = loaded.document.clone();
    let worksheets = folder(&root, &source)?;
    let raw: Value = serde_json::from_slice(&fs::read(&doc_path)?)?;
    let shared = shared_digest(&raw, false)?;
    if frozen.shared != shared && frozen.shared != shared_digest(&raw, true)? {
        return Err(bad(
            "shared_drift",
            "shared chapter inputs changed after the batch snapshot",
        ));
    }
    let mut pending = PendingAssets::new();
    let mut covered = BTreeSet::new();
    let mut ids = BTreeSet::new();
    let mut claims = Vec::new();
    for item in &manifest.items {
        let [start, stop] = item
            .pages
            .ok_or_else(|| bad("invalid_manifest", &item.id))?;
        if start >= stop
            || stop > source.pages.len()
            || item.workdir != item.id
            || !item
                .id
                .strip_prefix("shard-")
                .is_some_and(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
            || !ids.insert(&item.id)
            || !matches!(item.status.as_str(), "pending" | "done")
        {
            return Err(bad(
                "invalid_manifest",
                format!("invalid or unfinished shard: {}", item.id),
            ));
        }
        let shard = owned(&batch, Path::new(&item.workdir))?;
        if root.starts_with(&shard) {
            return Err(bad(
                "invalid_manifest",
                "merge destination must not be inside a shard",
            ));
        }
        claims.push(workspace::workspace_lock(&shard, "merge-shards")?);
        let local_path = owned(&shard, Path::new("comic.json"))?;
        let bytes = fs::read(local_path)?;
        if shared_digest(&serde_json::from_slice(&bytes)?, false)? != shared {
            return Err(bad(
                "shared_drift",
                format!("{}: shared glossary or policy changed", item.id),
            ));
        }
        if digest(&owned(&shard, Path::new("glossary.json"))?)?
            != frozen.assets.get("glossary.json").cloned().flatten()
        {
            return Err(bad(
                "shared_drift",
                format!("{}: shared glossary file changed", item.id),
            ));
        }
        let local = ir::decode_doc(&bytes)?;
        let local_worksheets = folder(&shard, &local)?;
        if local.pages.len() != stop - start {
            return Err(bad(
                "invalid_manifest",
                "shard pages do not match their planned ranges",
            ));
        }
        for (index, mut revised) in (start..stop).zip(local.pages) {
            if !covered.insert(index) {
                return Err(bad("overlapping_pages", &revised.id));
            }
            let original = &source.pages[index];
            check_page(original)?;
            check_page(&revised)?;
            let original_ids: BTreeSet<_> = original.regions.iter().map(|r| &r.id).collect();
            let revised_ids: BTreeSet<_> = revised.regions.iter().map(|r| &r.id).collect();
            if !original_ids.is_subset(&revised_ids) {
                return Err(bad(
                    "region_identity",
                    format!("{}: original region IDs changed", original.id),
                ));
            }
            if (
                original.id.as_str(),
                original.index,
                &original.image,
                &original.sha256,
            ) != (
                revised.id.as_str(),
                revised.index,
                &revised.image,
                &revised.sha256,
            ) {
                return Err(bad(
                    "page_identity",
                    format!("{}: original page identity changed", original.id),
                ));
            }
            let original_path = page_asset(&root, &original.image, "pages", &original.id, false)?;
            let revised_path = page_asset(&shard, &revised.image, "pages", &revised.id, false)?;
            let size = dimensions(&original_path)?;
            let (width, height) = size;
            if dimensions(&revised_path)? != size
                || (original.width != 0 && original.width != width)
                || (original.height != 0 && original.height != height)
                || (revised.width != 0 && revised.width != width)
                || (revised.height != 0 && revised.height != height)
                || digest(&original_path)? != digest(&revised_path)?
            {
                return Err(bad(
                    "page_identity",
                    format!("{}: original bytes or dimensions differ", original.id),
                ));
            }
            let original_mode = original
                .extra
                .get("free_lettering_mask")
                .or_else(|| source.meta.get("free_lettering_mask"));
            let revised_mode = revised
                .extra
                .get("free_lettering_mask")
                .or_else(|| local.meta.get("free_lettering_mask"));
            if !revised.extra.contains_key("free_lettering_mask") && original_mode != revised_mode {
                return Err(bad(
                    "mask_mode_drift",
                    format!(
                        "{}: legacy page mask mode would change during merge",
                        original.id
                    ),
                ));
            }
            for file in page_files(&shard, &revised, &local_worksheets, false)? {
                if [revised.cleaned.as_deref(), revised.rendered.as_deref()]
                    .into_iter()
                    .flatten()
                    .any(|name| shard.join(name) == file)
                    && dimensions(&file)? != size
                {
                    return Err(bad("asset_dimensions", file.display().to_string()));
                }
                let target = if file.parent() == Some(local_worksheets.as_path()) {
                    worksheets.join(
                        file.file_name()
                            .ok_or_else(|| bad("unsafe_asset", file.display().to_string()))?,
                    )
                } else {
                    root.join(rel(&shard, &file)?)
                };
                if pending.insert(owned(&root, &target)?, file).is_some() {
                    return Err(bad("overlapping_assets", target.display().to_string()));
                }
            }
            revised.width = width;
            revised.height = height;
            retarget(&mut revised, &worksheets);
            merge_page_stages(&mut loaded.document.stages, &local.stages, &revised.id);
            loaded.document.pages[index] = revised;
        }
    }
    if covered.len() != source.pages.len() {
        return Err(bad(
            "missing_pages",
            "shard pages do not match the original chapter",
        ));
    }
    let updated = loaded.document.clone();
    publish_if_changed(&root, &updated, &frozen, &pending, || {
        publish(&root, &mut loaded, &claim, &pending)
    })?;
    Ok(MergeReport {
        document: doc_path,
        pages: source.pages.len(),
        shards: manifest.items.len(),
    })
}
fn dimensions(path: &Path) -> Result<(u32, u32), IrError> {
    let kind = image::ImageReader::open(path)?.with_guessed_format()?;
    let (w, h) = kind
        .into_dimensions()
        .map_err(|e| bad("image_dimensions", e.to_string()))?;
    if packcore_rs::port::validate_page_dimensions(
        i128::from(w),
        i128::from(h),
        f64::INFINITY,
        1,
        i128::MAX,
    ) != Some(true)
    {
        return Err(bad("image_dimensions", "image dimensions must be positive"));
    }
    Ok((w, h))
}
fn publish(
    root: &Path,
    loaded: &mut workspace::LoadedDocument,
    claim: &workspace::Claim,
    pending: &PendingAssets,
) -> Result<(), IrError> {
    let dir = tempfile::Builder::new()
        .prefix(".revayat-merge-")
        .tempdir_in(root)?;
    let mut moves = Vec::new();
    for (index, (target, source)) in pending.iter().enumerate() {
        let new = dir.path().join(format!("new/{index}"));
        copy(source, &new)?;
        let old = if digest(target)?.is_some() {
            let p = dir.path().join(format!("old/{index}"));
            copy(target, &p)?;
            Some(p)
        } else {
            None
        };
        moves.push((target, new, old));
    }
    let mut replaced = 0;
    let result = (|| {
        for (target, new, _) in &moves {
            fs::create_dir_all(ir::doc_dir(target))?;
            fs::rename(new, target)?;
            replaced += 1;
        }
        loaded.save_claimed(claim)
    })();
    if let Err(error) = result {
        let mut failed = false;
        for (target, _, backup) in moves[..replaced].iter().rev() {
            failed |= match backup {
                None => fs::remove_file(target),
                Some(old) => fs::rename(old, target),
            }
            .is_err();
        }
        if failed {
            let kept = dir.keep();
            return Err(bad(
                "merge_recovery",
                format!(
                    "could not restore merge assets; backups retained in {}",
                    kept.display()
                ),
            ));
        }
        return Err(error);
    }
    Ok(())
}
