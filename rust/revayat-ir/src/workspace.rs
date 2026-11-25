use crate::{ComicDocument, IrError, PageRecord, ir};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs::{self, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

static NEXT_TOKEN: AtomicU64 = AtomicU64::new(0);
const CLAIM_LIMIT: u64 = 65_536;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ClaimRecord {
    pub owner: String,
    pub token: String,
    pub pid: u32,
    pub host: String,
    pub what: String,
    pub document: Option<PathBuf>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scratch: Option<PathBuf>,
}

pub struct Claim {
    path: PathBuf,
    record: ClaimRecord,
}

fn host() -> Option<String> {
    std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .ok()
        .filter(|name| !name.is_empty())
}

impl Claim {
    fn create(path: PathBuf, what: &str, document: Option<PathBuf>) -> Result<Self, IrError> {
        fs::create_dir_all(ir::doc_dir(&path))?;
        let pid = std::process::id();
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let sequence = NEXT_TOKEN.fetch_add(1, Ordering::Relaxed);
        let record = ClaimRecord {
            owner: "revayat-comic".into(),
            token: format!("{pid:x}{nanos:x}{sequence:x}"),
            pid,
            host: host().unwrap_or_default(),
            what: what.into(),
            document,
            scratch: None,
        };
        let bytes = ir::json_bytes(&record)?;
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&path).map_err(|err| {
            if err.kind() == io::ErrorKind::AlreadyExists {
                IrError::refused(
                    "workspace_busy",
                    format!(
                        "another run is writing {}; claim {}",
                        ir::doc_dir(&path).display(),
                        path.display()
                    ),
                )
            } else {
                err.into()
            }
        })?;
        if let Err(error) = file.write_all(&bytes).and_then(|()| file.sync_all()) {
            drop(file);
            let _ = fs::remove_file(&path);
            return Err(error.into());
        }
        Ok(Self { path, record })
    }
    pub fn path(&self) -> &Path {
        &self.path
    }
    pub fn owns(&self) -> bool {
        read_claim(&self.path).is_ok_and(|current| current.token == self.record.token)
    }
    pub fn remember_staging(&mut self, path: &Path) -> Result<(), IrError> {
        if !self.owns() {
            return Err(IrError::refused(
                "ownership_changed",
                "destination ownership changed before assembly",
            ));
        }
        self.record.scratch = Some(std::path::absolute(path)?);
        ir::write_bytes(&self.path, &ir::json_bytes(&self.record)?)
    }
}
impl Drop for Claim {
    fn drop(&mut self) {
        if self.owns() {
            let _ = fs::remove_file(&self.path);
        }
    }
}

pub fn workspace_lock(folder: impl AsRef<Path>, what: &str) -> Result<Claim, IrError> {
    Claim::create(
        std::path::absolute(folder)?.join(".revayat-lock"),
        what,
        None,
    )
}
pub fn destination_claim(path: &Path, doc_path: &Path) -> Result<Claim, IrError> {
    Claim::create(
        suffix(path, ".revayat-claim")?,
        "export",
        Some(std::path::absolute(doc_path)?),
    )
}
pub(crate) fn suffix(path: &Path, suffix: &str) -> Result<PathBuf, IrError> {
    let mut filename = path
        .file_name()
        .ok_or_else(|| IrError::refused("invalid_path", path.display().to_string()))?
        .to_os_string();
    filename.push(suffix);
    Ok(path.with_file_name(filename))
}
pub fn read_claim(path: &Path) -> Result<ClaimRecord, IrError> {
    if !fs::symlink_metadata(path)?.is_file() {
        return Err(IrError::refused(
            "invalid_claim",
            "claim is not a regular file",
        ));
    }
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take(CLAIM_LIMIT + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > CLAIM_LIMIT {
        return Err(IrError::refused("invalid_claim", "claim is too large"));
    }
    let claim: ClaimRecord = serde_json::from_slice(&bytes)?;
    if claim.owner != "revayat-comic" || claim.token.is_empty() || claim.pid == 0 {
        return Err(IrError::refused(
            "invalid_claim",
            "unrecognized claim; preserve it for inspection",
        ));
    }
    Ok(claim)
}

pub fn recover_claim(
    path: &Path,
    document: Option<&Path>,
    owner_absent: impl FnOnce(u32) -> bool,
) -> Result<Option<ClaimRecord>, IrError> {
    let record = match read_claim(path) {
        Err(IrError::Io(error)) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        result => result?,
    };
    if host().as_deref() != Some(&record.host)
        || record.pid == std::process::id()
        || !owner_absent(record.pid)
    {
        return Err(IrError::refused(
            "workspace_busy",
            "owner is live or cannot be proven absent",
        ));
    }
    if let Some(doc) = document
        && record.document != Some(std::path::absolute(doc)?)
    {
        return Err(IrError::refused(
            "invalid_claim",
            "claim belongs to another document",
        ));
    }
    if read_claim(path)? != record {
        return Err(IrError::refused(
            "ownership_changed",
            "ownership changed during recovery",
        ));
    }
    fs::remove_file(path)?;
    Ok(Some(record))
}

pub fn selected_pages<'a>(
    doc: &'a ComicDocument,
    pages: Option<&[String]>,
) -> Result<Vec<&'a PageRecord>, IrError> {
    let Some(pages) = pages else {
        return Ok(doc.pages.iter().collect());
    };
    let selection: BTreeSet<_> = pages.iter().map(String::as_str).collect();
    let present: BTreeSet<_> = doc.pages.iter().map(|p| p.id.as_str()).collect();
    let missing: Vec<_> = selection.difference(&present).copied().collect();
    if !missing.is_empty() {
        return Err(IrError::refused(
            "unknown_pages",
            format!("unknown page IDs: {}", missing.join(", ")),
        ));
    }
    Ok(doc
        .pages
        .iter()
        .filter(|p| selection.contains(p.id.as_str()))
        .collect())
}
pub fn parse_pages(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .collect()
}

pub struct LoadedDocument {
    pub document: ComicDocument,
    path: PathBuf,
    generation: String,
}
impl LoadedDocument {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, IrError> {
        let path = std::path::absolute(path)?;
        let bytes = fs::read(&path)?;
        Ok(Self {
            document: ir::decode_doc(&bytes)?,
            path,
            generation: ir::sha256_bytes(&bytes),
        })
    }
    pub fn path(&self) -> &Path {
        &self.path
    }
    pub fn save(&mut self) -> Result<(), IrError> {
        let claim = workspace_lock(ir::doc_dir(&self.path), "save")?;
        self.save_claimed(&claim)
    }
    pub fn save_claimed(&mut self, claim: &Claim) -> Result<(), IrError> {
        if claim.path != ir::doc_dir(&self.path).join(".revayat-lock") || !claim.owns() {
            return Err(IrError::refused(
                "ownership_changed",
                "save requires the document workspace claim",
            ));
        }
        if !self.path.is_file() || ir::sha256_file(&self.path)? != self.generation {
            return Err(IrError::refused(
                "document_changed",
                "the document changed after it was loaded; reload before saving",
            ));
        }
        let bytes = ir::json_bytes(&self.document)?;
        ir::write_bytes(&self.path, &bytes)?;
        self.generation = ir::sha256_bytes(&bytes);
        Ok(())
    }
}
