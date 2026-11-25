//! Digest-checked installation with a recoverable rename journal.

use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tempfile::{Builder, NamedTempFile};

const AGENTS: [(&str, &str); 8] = [
    ("claude", ".claude"),
    ("kiro", ".kiro"),
    ("codex", ".codex"),
    ("cursor", ".cursor"),
    ("cline", ".cline"),
    ("hermes", ".hermes"),
    ("opencode", ".opencode"),
    ("antigravity", ".agents"),
];
const CONTROL: &str = ".revayat-comic-installer";
const LIMIT: u64 = 8 * 1024 * 1024;
const BEGIN: &str = "<!-- BEGIN revayat-comic -->";
const END: &str = "<!-- END revayat-comic -->";

#[derive(Debug, thiserror::Error)]
pub enum InstallError {
    #[error("{0}")]
    Invalid(&'static str),
    #[error("refusing an unsafe installer path: {0}")]
    UnsafePath(PathBuf),
    #[error("artifact changed; recovery evidence was kept: {0}")]
    Changed(PathBuf),
    #[error("interrupted installation; run the installer with --recover")]
    Pending,
    #[error(
        "could not install ({cause}); rollback stopped ({rollback}); recovery evidence was kept"
    )]
    Rollback {
        cause: Box<Self>,
        rollback: Box<Self>,
    },
    #[error(transparent)]
    Io(#[from] io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

type Result<T> = std::result::Result<T, InstallError>;

fn metadata(path: &Path) -> Result<Option<fs::Metadata>> {
    match fs::symlink_metadata(path) {
        Ok(meta) if linked(&meta) => Err(InstallError::UnsafePath(path.into())),
        Ok(meta) => Ok(Some(meta)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

fn linked(meta: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if meta.file_attributes() & 0x400 != 0 {
            return true;
        }
    }
    meta.file_type().is_symlink()
}

pub(crate) fn reserved(name: &str) -> bool {
    let upper = name
        .split('.')
        .next()
        .unwrap_or_default()
        .to_ascii_uppercase();
    matches!(
        upper.as_str(),
        "CON" | "PRN" | "AUX" | "NUL" | "CONIN" | "CONOUT" | "CONIN$" | "CONOUT$"
    ) || upper
        .strip_prefix("COM")
        .or_else(|| upper.strip_prefix("LPT"))
        .is_some_and(|suffix| {
            matches!(
                suffix,
                "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
            )
        })
}

fn safe_name(name: &str) -> bool {
    !name.is_empty()
        && name != "."
        && name != ".."
        && !name.ends_with([' ', '.'])
        && !reserved(name)
        && !name
            .chars()
            .any(|ch| ch.is_control() || "\\/:<>\"|?*".contains(ch))
}

fn safe_path(base: &Path, path: &Path) -> Result<()> {
    let rel = path
        .strip_prefix(base)
        .map_err(|_| InstallError::UnsafePath(path.into()))?;
    let mut cursor = base.to_path_buf();
    for part in rel.components() {
        match part {
            Component::Normal(name) if name.to_str().is_some_and(safe_name) => cursor.push(name),
            _ => return Err(InstallError::UnsafePath(path.into())),
        }
        metadata(&cursor)?;
    }
    Ok(())
}

fn unlinked_base(path: &Path) -> Result<PathBuf> {
    if path.components().any(|part| part == Component::ParentDir) {
        return Err(InstallError::UnsafePath(path.into()));
    }
    let absolute = std::path::absolute(path)?;
    for part in absolute.ancestors() {
        if !part.as_os_str().is_empty() {
            metadata(part)?;
        }
    }
    let resolved = absolute.canonicalize()?;
    if !resolved.is_dir() {
        return Err(InstallError::UnsafePath(resolved));
    }
    Ok(resolved)
}

fn read_bounded(path: &Path) -> Result<Vec<u8>> {
    metadata(path)?;
    let mut data = Vec::new();
    File::open(path)?.take(LIMIT + 1).read_to_end(&mut data)?;
    if data.len() > LIMIT as usize {
        return Err(InstallError::Invalid(
            "installer record or pointer exceeds the size limit",
        ));
    }
    Ok(data)
}

fn artifact(hash: &mut Sha256, path: &Path) -> Result<()> {
    let Some(meta) = metadata(path)? else {
        return Err(InstallError::Changed(path.into()));
    };
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        hash.update((meta.permissions().mode() & 0o7777).to_le_bytes());
    }
    if meta.is_file() {
        hash.update(b"F");
        let mut reader = File::open(path)?;
        let mut buf = [0; 32768];
        let mut contents = Sha256::new();
        loop {
            let read = reader.read(&mut buf)?;
            if read == 0 {
                break;
            }
            contents.update(&buf[..read]);
        }
        hash.update(contents.finalize());
    } else if meta.is_dir() {
        hash.update(b"D");
        let mut entries = fs::read_dir(path)?.collect::<io::Result<Vec<_>>>()?;
        entries.sort_by_key(fs::DirEntry::file_name);
        for entry in entries {
            let name = entry.file_name();
            let name = name
                .to_str()
                .filter(|n| safe_name(n))
                .ok_or_else(|| InstallError::UnsafePath(entry.path()))?;
            hash.update((name.len() as u64).to_le_bytes());
            hash.update(name.as_bytes());
            artifact(hash, &entry.path())?;
        }
        hash.update(0_u64.to_le_bytes());
    } else {
        return Err(InstallError::UnsafePath(path.into()));
    }
    Ok(())
}

pub fn digest(path: &Path) -> Result<Option<String>> {
    if metadata(path)?.is_none() {
        return Ok(None);
    }
    let mut hash = Sha256::new();
    artifact(&mut hash, path)?;
    use std::fmt::Write as _;

    let mut hex = String::with_capacity(64);
    for b in hash.finalize() {
        let _ = write!(hex, "{b:02x}");
    }
    Ok(Some(hex))
}

fn verify(path: &Path, expected: Option<&str>) -> Result<()> {
    if digest(path)?.as_deref() != expected {
        return Err(InstallError::Changed(path.into()));
    }
    Ok(())
}

fn checked_copy(source: &Path, target: &Path, expected: &str) -> Result<()> {
    let mut source_file = File::open(source)?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)?;
    io::copy(&mut source_file, &mut output)?;
    output.set_permissions(source_file.metadata()?.permissions())?;
    output.sync_all()?;
    verify(source, Some(expected))?;
    verify(target, Some(expected))
}

fn manifest(repo: &Path) -> Result<(PathBuf, Vec<(PathBuf, String)>)> {
    let source = repo.join("skills/revayat-comic");
    let manifest = repo.join("install/skill-files.txt");
    safe_path(repo, &source)?;
    safe_path(repo, &manifest)?;
    let text = String::from_utf8(read_bounded(&manifest)?)
        .map_err(|_| InstallError::Invalid("skill manifest must be UTF-8"))?;
    let mut seen = HashSet::new();
    let mut files = Vec::new();
    for entry in text.lines() {
        if !entry.split('/').all(safe_name) || !seen.insert(entry.to_lowercase()) {
            return Err(InstallError::Invalid(
                "invalid or duplicate path in skill manifest",
            ));
        }
        let rel = PathBuf::from(entry);
        let path = source.join(&rel);
        safe_path(&source, &path)?;
        if !metadata(&path)?.is_some_and(|meta| meta.is_file()) {
            return Err(InstallError::Invalid("incomplete source bundle"));
        }
        let hash = digest(&path)?.ok_or_else(|| InstallError::Changed(path.clone()))?;
        files.push((rel, hash));
    }
    if files.is_empty() {
        return Err(InstallError::Invalid("empty skill manifest"));
    }
    Ok((source, files))
}

fn pointer(raw: &str, destinations: &[PathBuf]) -> Result<String> {
    let breaks = regex::Regex::new(r"\r\n|\r|\n")
        .map_err(|_| InstallError::Invalid("invalid newline pattern"))?;
    let newline = breaks.find(raw).map_or("\n", |m| m.as_str());
    let mut pos = 0;
    let mut start = None;
    let mut stop = None;
    for (end, next) in breaks
        .find_iter(raw)
        .map(|m| (m.start(), m.end()))
        .chain([(raw.len(), raw.len())])
    {
        let line = &raw[pos..end];
        match line
            .strip_prefix('\u{feff}')
            .filter(|_| pos == 0)
            .unwrap_or(line)
        {
            BEGIN if start.is_none() => {
                start = Some(pos + usize::from(pos == 0 && line.starts_with('\u{feff}')) * 3)
            }
            END if start.is_some() && stop.is_none() => stop = Some(next),
            BEGIN | END => {
                return Err(InstallError::Invalid(
                    "AGENTS.md has unbalanced or repeated Revayat markers",
                ));
            }
            _ => {}
        }
        pos = next;
    }
    let mut lines = vec![
        BEGIN.into(),
        "## Revayat Comic: Persian comic translation".into(),
        String::new(),
        "Use the installed skill below to translate a comic into Persian.".into(),
    ];
    for target in destinations {
        let raw = target
            .to_str()
            .ok_or(InstallError::Invalid("pointer destination is not UTF-8"))?;
        let name = raw.trim_start_matches(r"\\?\").replace('\\', "/");
        if name.contains(['\r', '\n', '`']) {
            return Err(InstallError::Invalid("invalid pointer destination"));
        }
        lines.push(format!(
            "Follow `{name}/SKILL.md`; resolve `{{SKILL_DIR}}` as `{name}`."
        ));
    }
    lines.extend([END.into(), String::new()]);
    let block = lines.join(newline);
    match (start, stop) {
        (Some(a), Some(b)) => Ok(format!("{}{block}{}", &raw[..a], &raw[b..])),
        (None, None) => Ok(format!(
            "{raw}{}{block}",
            if raw.is_empty() {
                String::new()
            } else if raw.ends_with(['\n', '\r']) {
                newline.to_owned()
            } else {
                newline.repeat(2)
            }
        )),
        _ => Err(InstallError::Invalid(
            "AGENTS.md has an unmatched Revayat marker",
        )),
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Item {
    target: PathBuf,
    old: Option<String>,
    new: String,
}

#[derive(Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
enum Phase {
    Prepared,
    Committed,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Record {
    tx: String,
    phase: Phase,
    items: Vec<Item>,
}

impl Record {
    fn paths(&self, base: &Path, i: usize) -> Result<(PathBuf, PathBuf, PathBuf)> {
        let target = base.join(&self.items[i].target);
        let dir = base.join(CONTROL).join(&self.tx);
        let stage = dir.join(format!("stage-{i}"));
        let backup = dir.join(format!("backup-{i}"));
        for path in [&target, &stage, &backup] {
            safe_path(base, path)?;
        }
        Ok((target, stage, backup))
    }

    fn load(file: &Path, valid: &HashSet<PathBuf>) -> Result<Self> {
        let record: Self = serde_json::from_slice(&read_bounded(file)?)?;
        let mut targets = HashSet::new();
        let hash = |s: &str| {
            s.len() == 64
                && s.bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        };
        if !record.tx.starts_with("tx-")
            || !safe_name(&record.tx)
            || record.items.is_empty()
            || record.items.iter().any(|item| {
                !valid.contains(&item.target)
                    || !targets.insert(&item.target)
                    || !hash(&item.new)
                    || item.old.as_deref().is_some_and(|v| !hash(v))
            })
        {
            return Err(InstallError::Invalid(
                "invalid recovery record; preserve it for inspection",
            ));
        }
        Ok(record)
    }
}

fn journal(path: &Path, record: &Record, replace: bool) -> Result<()> {
    let parent = path
        .parent()
        .ok_or(InstallError::Invalid("missing journal directory"))?;
    let mut temp = NamedTempFile::new_in(parent)?;
    serde_json::to_writer(temp.as_file_mut(), record)?;
    temp.as_file().sync_all()?;
    if replace {
        temp.persist(path)
    } else {
        temp.persist_noclobber(path)
    }
    .map_err(|error| error.error)?;
    sync_directory(parent)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<()> {
    Ok(File::open(path)?.sync_all()?)
}

#[cfg(not(unix))]
fn sync_directory(_: &Path) -> Result<()> {
    Ok(())
}

fn rename(source: &Path, target: &Path) -> Result<()> {
    if metadata(target)?.is_some() {
        return Err(InstallError::Changed(target.into()));
    }
    fs::rename(source, target)?;
    if let Some(dir) = source.parent() {
        sync_directory(dir)?;
    }
    if let Some(dir) = target.parent().filter(|dir| Some(*dir) != source.parent()) {
        sync_directory(dir)?;
    }
    Ok(())
}

fn promote(base: &Path, record: &Record) -> Result<()> {
    for (i, item) in record.items.iter().enumerate() {
        let (target, stage, backup) = record.paths(base, i)?;
        verify(&target, item.old.as_deref())?;
        verify(&stage, Some(&item.new))?;
        if item.old.is_some() {
            rename(&target, &backup)?;
        }
        rename(&stage, &target)?;
    }
    verify_commit(base, record)
}

fn verify_commit(base: &Path, record: &Record) -> Result<()> {
    for (i, item) in record.items.iter().enumerate() {
        let (target, stage, backup) = record.paths(base, i)?;
        verify(&target, Some(&item.new))?;
        verify(&stage, None)?;
        verify(&backup, item.old.as_deref())?;
    }
    Ok(())
}

fn rollback(base: &Path, record: &Record) -> Result<()> {
    let mut actions = Vec::new();
    for (i, item) in record.items.iter().enumerate() {
        let (target, stage, backup) = record.paths(base, i)?;
        let (now, staged, old) = (digest(&target)?, digest(&stage)?, digest(&backup)?);
        let staged_new = staged.as_deref() == Some(&item.new);
        let promoted = now.as_deref() == Some(&item.new) && staged.is_none() && old == item.old;
        let backed_up = now.is_none() && staged_new && old.is_some() && old == item.old;
        let untouched = now == item.old && old.is_none() && (staged.is_none() || staged_new);
        if !promoted && !backed_up && !untouched {
            return Err(InstallError::Changed(target));
        }
        actions.push((target, stage, backup, promoted, old.is_some()));
    }
    // Move promoted files back to staging first so an interrupted rollback stays recoverable.
    for (target, stage, backup, promoted, has_backup) in actions.into_iter().rev() {
        if promoted {
            rename(&target, &stage)?;
        }
        if has_backup {
            rename(&backup, &target)?;
        }
    }
    Ok(())
}

fn finish(base: &Path, pending: &Path, record: &Record) -> Result<()> {
    let dir = base.join(CONTROL).join(&record.tx);
    let name = if record.phase == Phase::Prepared {
        "rolled-back.json"
    } else {
        "committed.json"
    };
    rename(pending, &dir.join(name))
}

/// Resolve the CLI install base and select the agent's user or project layout.
pub fn resolve_install_scope(
    base: Option<PathBuf>,
    scope: Option<&str>,
    user_scope: bool,
) -> std::result::Result<(PathBuf, bool), &'static str> {
    let user_scope = match scope {
        Some(_) if user_scope => return Err("use either --scope or --user-scope"),
        Some("user") => true,
        Some("project") => false,
        Some(_) => return Err("--scope must be user or project"),
        None => user_scope,
    };
    let base = match base {
        Some(path) => path,
        None if user_scope => {
            std::env::home_dir().ok_or("home directory unavailable; use --base")?
        }
        None => return Err("project installation requires --base or --path"),
    };
    Ok((base, user_scope))
}

/// Install into an explicit project base. Forced replacement retains the previous copy alongside the journal.
pub fn safe_install(
    repo: &Path,
    base: &Path,
    agent: &str,
    force: bool,
    recover: bool,
) -> Result<Vec<PathBuf>> {
    safe_install_scoped(repo, base, agent, false, force, recover)
}

/// Set `user_scope` for an installation in the supplied home directory.
pub fn safe_install_scoped(
    repo: &Path,
    base: &Path,
    agent: &str,
    user_scope: bool,
    force: bool,
    recover: bool,
) -> Result<Vec<PathBuf>> {
    let base = unlinked_base(base)?;
    let targets: Vec<_> = AGENTS
        .into_iter()
        .map(|(name, folder)| {
            (
                name,
                PathBuf::from(if user_scope && name == "opencode" {
                    ".config/opencode"
                } else {
                    folder
                }),
            )
        })
        .collect();
    if agent != "all" && !targets.iter().any(|(name, _)| *name == agent) {
        return Err(InstallError::Invalid("unknown agent"));
    }
    let mut valid: HashSet<_> = targets
        .iter()
        .map(|(_, dir)| dir.join("skills/revayat-comic"))
        .collect();
    valid.insert("AGENTS.md".into());
    let control = base.join(CONTROL);
    let lock_path = control.join("installer.lock");
    let pending = control.join("pending.json");
    safe_path(&base, &lock_path)?;
    safe_path(&base, &pending)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&control)?;
        fs::set_permissions(&control, fs::Permissions::from_mode(0o700))?;
    }
    #[cfg(not(unix))]
    fs::create_dir_all(&control)?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&lock_path)?;
    lock.try_lock()
        .map_err(|error| InstallError::Io(error.into()))?;
    if metadata(&pending)?.is_some() {
        if !recover {
            return Err(InstallError::Pending);
        }
        let record = Record::load(&pending, &valid)?;
        match record.phase {
            Phase::Prepared => rollback(&base, &record)?,
            Phase::Committed => verify_commit(&base, &record)?,
        }
        finish(&base, &pending, &record)?;
        return Ok(Vec::new());
    }
    if recover {
        return Ok(Vec::new());
    }

    let (source, files) = manifest(&unlinked_base(repo)?)?;
    let mut chosen = Vec::new();
    let mut pointers = Vec::new();
    let mut pointer_changed = false;
    for (name, folder) in targets {
        if agent != "all" && agent != name && !matches!(name, "antigravity" | "opencode") {
            continue;
        }
        let rel = folder.join("skills/revayat-comic");
        let target = base.join(&rel);
        safe_path(&base, &target)?;
        let existing = metadata(&target)?;
        if existing.as_ref().is_some_and(|meta| !meta.is_dir()) {
            return Err(InstallError::UnsafePath(target));
        }
        let selected = agent == name || (agent == "all" && base.join(&folder).is_dir());
        let install = selected && (force || existing.is_none());
        if matches!(name, "antigravity" | "opencode")
            && (install || target.join("SKILL.md").is_file())
        {
            safe_path(&base, &target.join("SKILL.md"))?;
            pointers.push(target.clone());
            pointer_changed |= install;
        }
        if !install {
            continue;
        }
        if target.starts_with(&source) || source.starts_with(&target) {
            return Err(InstallError::Invalid("source and destination overlap"));
        }
        chosen.push((rel, digest(&target)?));
    }
    if chosen.is_empty() {
        return Err(InstallError::Invalid(
            "nothing selected; existing installations were kept",
        ));
    }

    let staged = Builder::new().prefix("tx-").tempdir_in(&control)?;
    let tx = staged
        .path()
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or(InstallError::Invalid("invalid staging name"))?
        .to_owned();
    let installed = chosen.iter().map(|(rel, _)| base.join(rel)).collect();
    let mut record = Record {
        tx,
        phase: Phase::Prepared,
        items: Vec::new(),
    };
    for (i, (target, old)) in chosen.into_iter().enumerate() {
        let stage = staged.path().join(format!("stage-{i}"));
        fs::create_dir(&stage)?;
        for (rel, expected) in &files {
            let from = source.join(rel);
            let to = stage.join(rel);
            safe_path(&source, &from)?;
            if let Some(dir) = to.parent() {
                fs::create_dir_all(dir)?;
            }
            checked_copy(&from, &to, expected)?;
        }
        let new = digest(&stage)?.ok_or_else(|| InstallError::Changed(stage.clone()))?;
        record.items.push(Item { target, old, new });
    }
    if pointer_changed {
        let target = "AGENTS.md".into();
        let pointer_file = base.join(&target);
        safe_path(&base, &pointer_file)?;
        let old = digest(&pointer_file)?;
        let raw = if old.is_some() {
            String::from_utf8(read_bounded(&pointer_file)?)
                .map_err(|_| InstallError::Invalid("AGENTS.md must be UTF-8"))?
        } else {
            String::new()
        };
        verify(&pointer_file, old.as_deref())?;
        let data = pointer(&raw, &pointers)?;
        let stage = staged.path().join(format!("stage-{}", record.items.len()));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&stage)?;
        file.write_all(data.as_bytes())?;
        if let Some(meta) = metadata(&pointer_file)? {
            file.set_permissions(meta.permissions())?;
        }
        file.sync_all()?;
        let new = digest(&stage)?.ok_or_else(|| InstallError::Changed(stage.clone()))?;
        record.items.push(Item { target, old, new });
    }
    for (rel, expected) in &files {
        verify(&source.join(rel), Some(expected))?;
    }
    for (i, item) in record.items.iter().enumerate() {
        let (target, _, _) = record.paths(&base, i)?;
        if let Some(dir) = target.parent() {
            fs::create_dir_all(dir)?;
        }
        verify(&target, item.old.as_deref())?;
    }
    sync_directory(staged.path())?;
    let _staging_path = staged.keep();
    journal(&pending, &record, false)?;
    if let Err(cause) = promote(&base, &record) {
        return match rollback(&base, &record).and_then(|()| finish(&base, &pending, &record)) {
            Ok(()) => Err(cause),
            Err(rollback) => Err(InstallError::Rollback {
                cause: Box::new(cause),
                rollback: Box::new(rollback),
            }),
        };
    }
    record.phase = Phase::Committed;
    if let Err(cause) = journal(&pending, &record, true) {
        let reconcile = (|| {
            let on_disk = Record::load(&pending, &valid)?;
            match on_disk.phase {
                Phase::Prepared => rollback(&base, &on_disk)?,
                Phase::Committed => verify_commit(&base, &on_disk)?,
            }
            finish(&base, &pending, &on_disk)
        })();
        return match reconcile {
            Ok(()) => Err(cause),
            Err(rollback) => Err(InstallError::Rollback {
                cause: Box::new(cause),
                rollback: Box::new(rollback),
            }),
        };
    }
    finish(&base, &pending, &record)?;
    Ok(installed)
}

#[cfg(test)]
mod tests;
