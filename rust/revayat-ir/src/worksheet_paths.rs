use crate::{ComicDocument, ir};
use serde_json::Value;
use std::path::{Path, PathBuf};

pub fn worksheet_folder(
    doc_path: &Path,
    doc: &ComicDocument,
    override_folder: Option<&Path>,
) -> PathBuf {
    if let Some(folder) = override_folder {
        let folder = expand_home(folder);
        return std::path::absolute(&folder).unwrap_or(folder);
    }
    let folder = doc
        .meta
        .get("worksheets")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .unwrap_or("worksheets");
    let folder = expand_home(Path::new(folder));
    let path = ir::doc_dir(doc_path).join(folder);
    std::path::absolute(&path).unwrap_or(path)
}

fn expand_home(path: &Path) -> PathBuf {
    if let Ok(nested) = path.strip_prefix("~")
        && let Some(home) = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
    {
        return PathBuf::from(home).join(nested);
    }
    path.to_path_buf()
}
