use std::{
    fs::{self, File},
    io::{self, Read, Write},
    path::{Component, Path, PathBuf},
};

use crate::{IoError, invalid};

pub use revayat_ir::ir::sha256_bytes as digest;

pub fn file_digest(path: &Path) -> Result<String, IoError> {
    Ok(revayat_ir::ir::sha256_reader(File::open(path)?)?)
}

pub fn parent(path: &Path) -> &Path {
    path.parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."))
}

pub fn bounded_read(mut source: impl Read, max: u64) -> Result<Vec<u8>, IoError> {
    let mut data = Vec::new();
    source
        .by_ref()
        .take(max.saturating_add(1))
        .read_to_end(&mut data)?;
    if data.len() as u64 > max {
        return Err(invalid("Input exceeds the encoded-byte limit"));
    }
    Ok(data)
}

pub fn read_file(path: &Path, max: u64) -> Result<Vec<u8>, IoError> {
    let file = File::open(path)?;
    if file.metadata()?.len() > max {
        return Err(invalid("Input exceeds the encoded-byte limit"));
    }
    bounded_read(file, max)
}

pub fn atomic_file(
    path: &Path,
    write: impl FnOnce(&mut File) -> Result<(), IoError>,
) -> Result<(), IoError> {
    let dir = parent(path);
    fs::create_dir_all(dir)?;
    let mut stage = tempfile::NamedTempFile::new_in(dir)?;
    write(stage.as_file_mut())?;
    stage.as_file().sync_all()?;
    stage.persist(path).map_err(|error| error.error)?;
    Ok(())
}

pub fn write_file(path: &Path, bytes: &[u8]) -> Result<(), IoError> {
    atomic_file(path, |file| Ok(file.write_all(bytes)?))
}

pub fn canonical_destination(path: &Path) -> Result<PathBuf, IoError> {
    match fs::canonicalize(path) {
        Ok(path) => Ok(path),
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            let name = path.file_name().ok_or(error)?;
            Ok(canonical_destination(parent(path))?.join(name))
        }
        Err(error) => Err(error.into()),
    }
}

pub fn workspace_asset(root: &Path, relative: &Path) -> Result<PathBuf, IoError> {
    if relative.as_os_str().is_empty()
        || relative
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(invalid("Page paths must stay inside the workspace"));
    }
    let root = fs::canonicalize(root)?;
    let path = fs::canonicalize(root.join(relative))?;
    if !path.starts_with(&root) || !path.is_file() {
        return Err(invalid("Page paths must stay inside the workspace"));
    }
    Ok(path)
}

pub fn lock(directory: &Path, name: &str) -> Result<tempfile::NamedTempFile, IoError> {
    fs::create_dir_all(directory)?;
    let path = directory.join(name);
    let file = File::options()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)?;
    Ok(tempfile::NamedTempFile::from_parts(
        file,
        tempfile::TempPath::try_from_path(path)?,
    ))
}

pub fn move_into_place(staging: &Path, target: &Path, backup: &Path) -> Result<bool, IoError> {
    let replaced = target.symlink_metadata().is_ok();
    if replaced {
        fs::rename(target, backup)?;
    }
    if let Err(error) = fs::rename(staging, target) {
        if replaced && let Err(rollback) = fs::rename(backup, target) {
            return Err(invalid(format!(
                "Publish failed ({error}); rollback failed ({rollback}). Original remains at {}",
                backup.display()
            )));
        }
        return Err(error.into());
    }
    Ok(replaced)
}
