use crate::{ComicDocument, IrError, batch, ir, stages, workspace};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs, io,
    path::{Component, Path, PathBuf},
};

pub const PENDING_SUFFIX: &str = ".export-pending.json";
const CONFLICT_SUFFIX: &str = ".export-conflict";
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Progress {
    pub phase: String,
    pub entries: BTreeMap<String, String>,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Journal {
    pub document: String,
    pub destination: PathBuf,
    pub published: BTreeMap<String, String>,
    pub result: Value,
    pub options: Value,
    pub schema: u32,
    pub previous: BTreeMap<String, Option<String>>,
    pub inputs: BTreeMap<PathBuf, String>,
    pub export_stamp: Value,
    pub document_after: String,
    pub progress: Progress,
    pub intent: String,
    pub progress_hash: String,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Recovery {
    Published,
    RolledBack,
}
fn bad(message: impl Into<String>) -> IrError {
    IrError::refused("transaction_conflict", message)
}
pub fn path_for(doc_path: &Path) -> Result<PathBuf, IrError> {
    workspace::suffix(doc_path, PENDING_SUFFIX)
}
fn digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn safe_name(s: &str) -> bool {
    !s.is_empty() && !matches!(s, "." | "..") && !s.contains(['/', '\\', ':', '\0'])
}
fn exists(path: &Path) -> Result<bool, IrError> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e.into()),
    }
}
fn unlink(path: &Path) -> Result<(), IrError> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}
fn out_is_dir(record: &Journal) -> bool {
    record.result["format"] == "dir"
}
fn locations(record: &Journal, name: &str) -> Result<(PathBuf, PathBuf, PathBuf), IrError> {
    if !safe_name(name) {
        return Err(bad("invalid published name"));
    }
    let out = &record.destination;
    let stage = workspace::suffix(out, ".revayat-part")?;
    let backup = workspace::suffix(out, ".revayat-kept")?.join(name);
    Ok(if out_is_dir(record) {
        (out.join(name), stage.join(name), backup)
    } else {
        (out.to_path_buf(), stage, backup)
    })
}
fn intent(record: &Journal) -> Result<String, IrError> {
    let mut raw = serde_json::to_value(record)?;
    if let Some(fields) = raw.as_object_mut() {
        for key in ["intent", "progress", "progress_hash"] {
            fields.remove(key);
        }
    }
    Ok(ir::sha256_bytes(stages::sorted_json(&raw)?.as_bytes()))
}
fn persist(doc_path: &Path, record: &mut Journal) -> Result<(), IrError> {
    record.progress_hash = ir::sha256_bytes(ir::dumps(&record.progress)?.as_bytes());
    ir::write_bytes(path_for(doc_path)?, &ir::json_bytes(record)?)
}
pub fn write(
    doc_path: &Path,
    destination: &Path,
    published: BTreeMap<String, String>,
    result: Value,
    options: Value,
    document: &ComicDocument,
    inputs: BTreeMap<PathBuf, String>,
) -> Result<Journal, IrError> {
    let destination = std::path::absolute(destination)?;
    if exists(&path_for(doc_path)?)? || exists(&workspace::suffix(&destination, ".revayat-kept")?)?
    {
        return Err(bad("recovery data already exists; recover it first"));
    }
    let mut entry = Journal {
        document: ir::sha256_file(doc_path)?,
        destination,
        published,
        result,
        options,
        schema: 2,
        previous: BTreeMap::new(),
        inputs,
        export_stamp: document
            .stages
            .get("export")
            .cloned()
            .unwrap_or_else(|| json!({})),
        document_after: ir::sha256_bytes(&ir::json_bytes(document)?),
        progress: Progress {
            phase: "prepared".into(),
            entries: BTreeMap::new(),
        },
        intent: String::new(),
        progress_hash: String::new(),
    };
    for name in entry.published.keys() {
        let (target, _, _) = locations(&entry, name)?;
        entry.previous.insert(name.clone(), batch::digest(&target)?);
    }
    entry.intent = intent(&entry)?;
    entry.progress_hash = ir::sha256_bytes(ir::dumps(&entry.progress)?.as_bytes());
    validate(&entry)?;
    input_problem(&entry)?;
    check_files(&entry)?;
    persist(doc_path, &mut entry)?;
    Ok(entry)
}
pub fn clear(doc_path: &Path) -> Result<(), IrError> {
    unlink(&path_for(doc_path)?)
}
pub fn read(doc_path: &Path) -> Result<Option<Journal>, IrError> {
    let path = path_for(doc_path)?;
    if !exists(&path)? {
        return Ok(None);
    }
    if !fs::symlink_metadata(&path)?.is_file() {
        return Err(bad("journal is not a regular file"));
    }
    let record = serde_json::from_slice(&fs::read(path)?)?;
    Ok(Some(record))
}
pub fn validate(record: &Journal) -> Result<(), IrError> {
    if record.schema != 2
        || !digest(&record.document)
        || !digest(&record.document_after)
        || record.published.is_empty()
        || !record.destination.is_absolute()
        || record
            .destination
            .components()
            .any(|p| matches!(p, Component::ParentDir))
        || !matches!(
            record.result["format"].as_str(),
            Some("cbz" | "pdf" | "dir")
        )
        || !record.export_stamp.is_object()
    {
        return Err(bad("invalid publication record"));
    }
    if !record
        .published
        .iter()
        .all(|(name, sha)| safe_name(name) && digest(sha))
        || record.previous.keys().ne(record.published.keys())
        || record.previous.values().flatten().any(|v| !digest(v))
        || record
            .inputs
            .iter()
            .any(|(path, sha)| !path.is_absolute() || !digest(sha))
    {
        return Err(bad("invalid published name or digest"));
    }
    if !out_is_dir(record)
        && (record.published.len() != 1
            || !record
                .destination
                .file_name()
                .and_then(|s| s.to_str())
                .is_some_and(|n| record.published.contains_key(n)))
    {
        return Err(bad("file publication names another destination"));
    }
    let phase = |state: &str| {
        matches!(
            state,
            "prepared" | "backing-up" | "backed-up" | "promoted" | "published"
        )
    };
    if record.intent != intent(record)?
        || record.progress_hash != ir::sha256_bytes(ir::dumps(&record.progress)?.as_bytes())
        || !phase(&record.progress.phase)
        || record
            .progress
            .entries
            .iter()
            .any(|(name, state)| !record.published.contains_key(name) || !phase(state))
    {
        return Err(bad("publication intent or progress was altered"));
    }
    Ok(())
}
pub fn input_problem(record: &Journal) -> Result<(), IrError> {
    for (path, wanted) in &record.inputs {
        if batch::digest(path)?.as_ref() != Some(wanted) {
            return Err(bad(format!(
                "{} changed since this export ran",
                path.display()
            )));
        }
    }
    Ok(())
}
fn check_files(record: &Journal) -> Result<(), IrError> {
    let mut directories = vec![workspace::suffix(&record.destination, ".revayat-kept")?];
    if out_is_dir(record) {
        directories.extend([
            record.destination.clone(),
            workspace::suffix(&record.destination, ".revayat-part")?,
        ]);
    }
    for folder in directories {
        if !exists(&folder)? {
            continue;
        }
        if !fs::symlink_metadata(&folder)?.is_dir() {
            return Err(bad(format!(
                "{} is not an owned transaction directory",
                folder.display()
            )));
        }
        for file in fs::read_dir(&folder)? {
            let file = file?;
            if !file
                .file_name()
                .to_str()
                .is_some_and(|n| record.published.contains_key(n))
            {
                return Err(bad(format!(
                    "{} contains unowned entries",
                    folder.display()
                )));
            }
        }
    }
    for (name, wanted) in &record.published {
        let (target, stage, backup) = locations(record, name)?;
        let previous = record.previous.get(name).and_then(Option::as_ref);
        if let Some(actual) = batch::digest(&target)?.as_ref()
            && actual != wanted
            && Some(actual) != previous
        {
            return Err(bad(format!(
                "{} changed outside this transaction",
                target.display()
            )));
        }
        if let Some(actual) = batch::digest(&stage)?
            && &actual != wanted
        {
            return Err(bad(format!(
                "{} changed outside this transaction",
                stage.display()
            )));
        }
        if let Some(actual) = batch::digest(&backup)?.as_ref()
            && Some(actual) != previous
        {
            return Err(bad(format!(
                "{} changed outside this transaction",
                backup.display()
            )));
        }
    }
    Ok(())
}
pub fn verifies(doc_path: &Path, record: &Journal) -> Result<(), IrError> {
    validate(record)?;
    let current = ir::sha256_file(doc_path)?;
    if current != record.document && current != record.document_after {
        return Err(bad("the document has changed since this export ran"));
    }
    input_problem(record)?;
    for (name, wanted) in &record.published {
        let (target, _, _) = locations(record, name)?;
        if batch::digest(&target)?.as_ref() != Some(wanted) {
            return Err(bad(format!(
                "{} is not the file this export published",
                target.display()
            )));
        }
    }
    Ok(())
}
pub fn promote(doc_path: &Path, record: &mut Journal) -> Result<(), IrError> {
    validate(record)?;
    input_problem(record)?;
    check_files(record)?;
    let current = ir::sha256_file(doc_path)?;
    if current != record.document && current != record.document_after {
        return Err(bad("the document has changed since this export ran"));
    }
    for (name, wanted) in &record.published {
        let (target, stage, _) = locations(record, name)?;
        if batch::digest(&target)?.as_ref() != Some(wanted)
            && batch::digest(&stage)?.as_ref() != Some(wanted)
        {
            return Err(bad(format!(
                "{} cannot supply the new generation",
                stage.display()
            )));
        }
    }
    for (name, wanted) in &record.published.clone() {
        let (target, stage, backup) = locations(record, name)?;
        if batch::digest(&target)?.as_ref() == Some(wanted) {
            continue;
        }
        progress(doc_path, record, "backing-up", Some(name))?;
        if target.exists() && !backup.exists() {
            fs::create_dir_all(ir::doc_dir(&backup))?;
            fs::rename(&target, &backup)?;
        }
        progress(doc_path, record, "backed-up", Some(name))?;
        fs::create_dir_all(ir::doc_dir(&target))?;
        fs::rename(&stage, &target)?;
        progress(doc_path, record, "promoted", Some(name))?;
    }
    progress(doc_path, record, "published", None)
}
fn progress(
    doc_path: &Path,
    record: &mut Journal,
    state: &str,
    name: Option<&str>,
) -> Result<(), IrError> {
    record.progress.phase = state.into();
    if let Some(name) = name {
        record.progress.entries.insert(name.into(), state.into());
    }
    persist(doc_path, record)
}
pub fn rollback(record: &Journal) -> Result<(), IrError> {
    validate(record)?;
    check_files(record)?;
    for (name, old) in &record.previous {
        let (target, _, backup) = locations(record, name)?;
        if old.is_some() && batch::digest(&target)? != *old && batch::digest(&backup)? != *old {
            return Err(bad(
                "neither generation can be recovered; backups were preserved",
            ));
        }
    }
    for (name, old) in record.previous.iter().rev() {
        let (target, _, backup) = locations(record, name)?;
        if batch::digest(&target)? == *old {
            continue;
        }
        if old.is_some() {
            fs::rename(backup, target)?;
        } else {
            unlink(&target)?;
        }
    }
    Ok(())
}
pub fn finish(doc_path: &Path, record: &Journal, committed: bool) -> Result<(), IrError> {
    validate(record)?;
    check_files(record)?;
    if committed {
        if ir::sha256_file(doc_path)? != record.document_after {
            return Err(bad("publication metadata has not committed"));
        }
        verifies(doc_path, record)?;
    } else {
        if ir::sha256_file(doc_path)? != record.document {
            return Err(bad("rollback has not restored the previous generation"));
        }
        for (name, old) in &record.previous {
            let (target, _, _) = locations(record, name)?;
            if batch::digest(&target)? != *old {
                return Err(bad("rollback has not restored the previous generation"));
            }
        }
    }
    for name in record.published.keys() {
        let (_, stage, backup) = locations(record, name)?;
        unlink(&stage)?;
        unlink(&backup)?;
    }
    let kept = workspace::suffix(&record.destination, ".revayat-kept")?;
    if exists(&kept)? {
        fs::remove_dir(kept)?;
    }
    if out_is_dir(record) {
        let staged = workspace::suffix(&record.destination, ".revayat-part")?;
        if exists(&staged)? {
            fs::remove_dir(staged)?;
        }
    }
    clear(doc_path)
}
pub fn resume(doc_path: &Path, record: &mut Journal) -> Result<Recovery, IrError> {
    validate(record)?;
    input_problem(record)?;
    check_files(record)?;
    let current = ir::sha256_file(doc_path)?;
    if current != record.document && current != record.document_after {
        return Err(bad("the document has changed since this export ran"));
    }
    if current == record.document_after || record.progress.phase == "published" {
        verifies(doc_path, record)?;
        return Ok(Recovery::Published);
    }
    for (name, wanted) in &record.published {
        let (target, staged, _) = locations(record, name)?;
        if batch::digest(&target)?.as_ref() != Some(wanted)
            && batch::digest(&staged)?.as_ref() != Some(wanted)
        {
            rollback(record)?;
            finish(doc_path, record, false)?;
            return Ok(Recovery::RolledBack);
        }
    }
    promote(doc_path, record)?;
    Ok(Recovery::Published)
}
pub fn reject(doc_path: &Path, reason: &str) -> Result<PathBuf, IrError> {
    let path = path_for(doc_path)?;
    let bytes = fs::read(&path)?;
    let mut raw =
        serde_json::from_slice::<Value>(&bytes).unwrap_or_else(|_| json!({"unreadable":true}));
    if let Some(fields) = raw.as_object_mut() {
        fields.insert("rejected_because".into(), json!(reason));
    } else {
        raw = json!({"record":raw,"rejected_because":reason});
    }
    for index in 1..100 {
        let kept = workspace::suffix(doc_path, &format!("{CONFLICT_SUFFIX}-{index:02}.json"))?;
        if !exists(&kept)? {
            ir::write_bytes(&kept, &ir::json_bytes(&raw)?)?;
            clear(doc_path)?;
            return Ok(kept);
        }
    }
    Err(bad(
        "recovery conflict archive is full; preserve and inspect it",
    ))
}
