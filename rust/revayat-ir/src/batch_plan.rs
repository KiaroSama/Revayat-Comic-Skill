use super::{
    BatchItem, BatchPlan, bad, check_page, children, copy, digest, folder, owned, page_files, rel,
    retarget, snapshot, stage_slice, write_manifest,
};
use crate::{IrError, ir, workspace};
use serde_json::json;
use std::{collections::BTreeSet, fs, path::Path};

fn prepare_folder<T>(
    out: &Path,
    prepare: impl FnOnce(&Path) -> Result<T, IrError>,
) -> Result<T, IrError> {
    if out.exists() {
        return Err(bad("batch_exists", out.display().to_string()));
    }
    let parent = ir::doc_dir(out);
    fs::create_dir_all(&parent)?;
    let temp = tempfile::Builder::new()
        .prefix(".revayat-plan-")
        .tempdir_in(parent)?;
    let result = prepare(temp.path())?;
    if out.exists() {
        return Err(bad("batch_exists", out.display().to_string()));
    }
    fs::rename(temp.path(), out)?;
    Ok(result)
}
pub fn plan_shards(root: &Path, shards: usize, out: Option<&Path>) -> Result<BatchPlan, IrError> {
    let root = fs::canonicalize(root)?;
    let out = std::path::absolute(
        out.map(Path::to_path_buf)
            .unwrap_or_else(|| root.join("batch")),
    )?;
    let _claim = workspace::workspace_lock(&root, "plan-shards")?;
    let doc = ir::load_doc(owned(&root, Path::new("comic.json"))?)?;
    if shards == 0 || shards > doc.pages.len() {
        return Err(bad(
            "invalid_shard_count",
            format!("shards must be between 1 and {}", doc.pages.len()),
        ));
    }
    let all: BTreeSet<_> = doc.pages.iter().map(|p| p.id.as_str()).collect();
    if all.len() != doc.pages.len() {
        return Err(bad(
            "overlapping_pages",
            "overlapping page IDs in source chapter",
        ));
    }
    let worksheets = folder(&root, &doc)?;
    let worksheet_name = rel(&root, &worksheets)?;
    let mut plan = BatchPlan {
        mode: "shards".into(),
        source: root.clone(),
        workers: shards,
        items: vec![],
        snapshot: Some(snapshot(&root, &doc)?),
    };
    prepare_folder(&out, |staging| {
        let mut start = 0;
        for number in 0..shards {
            let stop =
                start + doc.pages.len() / shards + usize::from(number < doc.pages.len() % shards);
            let id = format!("shard-{:03}", number + 1);
            let shard = staging.join(&id);
            let mut local = doc.clone();
            local.pages = doc.pages[start..stop].to_vec();
            for page in &mut local.pages {
                check_page(page)?;
                for path in page_files(&root, page, &worksheets, true)? {
                    copy(&path, &shard.join(rel(&root, &path)?))?;
                }
                retarget(page, &out.join(&id).join(&worksheet_name));
            }
            let glossary_path = owned(&root, Path::new("glossary.json"))?;
            if digest(&glossary_path)?.is_some() {
                copy(&glossary_path, &shard.join("glossary.json"))?;
            }
            local.stages = stage_slice(
                &doc.stages,
                &local.pages.iter().map(|p| p.id.as_str()).collect(),
            );
            local
                .meta
                .insert("worksheets".into(), json!(worksheet_name));
            local
                .source
                .insert("page_count".into(), json!(local.pages.len()));
            ir::save_doc(&local, shard.join("comic.json"))?;
            plan.items.push(BatchItem {
                id: id.clone(),
                workdir: id,
                pages: Some([start, stop]),
                status: "pending".into(),
                error: None,
                input: None,
            });
            start = stop;
        }
        write_manifest(staging, &plan)
    })?;
    Ok(plan)
}
pub fn plan_books(input: &Path, out: &Path, workers: Option<usize>) -> Result<BatchPlan, IrError> {
    let root = fs::canonicalize(input)?;
    let workers = workers.unwrap_or_else(|| {
        std::thread::available_parallelism()
            .map_or(1, usize::from)
            .min(4)
    });
    if workers == 0 {
        return Err(bad("invalid_worker_count", "workers must be positive"));
    }
    let image_path = |p: &Path| {
        p.is_file()
            && p.extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| ir::IMAGE_SUFFIXES.contains(&e.to_ascii_lowercase().as_str()))
    };
    let entries = children(&root)?;
    let mut books = Vec::new();
    if entries.iter().any(|p| !p.is_symlink() && image_path(p)) {
        books.push(root.clone());
    }
    for path in entries.into_iter().filter(|p| !p.is_symlink()) {
        if path.is_dir()
            && children(&path)?
                .iter()
                .any(|p| !p.is_symlink() && image_path(p))
            || path.is_file()
                && path.extension().and_then(|e| e.to_str()).is_some_and(|e| {
                    matches!(e.to_ascii_lowercase().as_str(), "cbz" | "cbr" | "pdf")
                })
        {
            books.push(path);
        }
    }
    if books.is_empty() {
        return Err(bad("missing_books", "no comic inputs found"));
    }
    let mut plan = BatchPlan {
        mode: "books".into(),
        source: root,
        workers: workers.min(books.len()),
        items: vec![],
        snapshot: None,
    };
    let mut used = BTreeSet::new();
    let safe = crate::matcher("[^a-z0-9]+");
    let reserved = crate::matcher("^(con|prn|aux|nul|com[0-9]|lpt[0-9])$");
    for source in books {
        let lower = (if source.is_dir() {
            source.file_name()
        } else {
            source.file_stem()
        })
        .and_then(|n| n.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
        let clean = safe.replace_all(&lower, "-");
        let clean = clean.trim_matches('-');
        let clean = &clean[..clean.len().min(64)];
        let mut base = if clean.is_empty() {
            "book".to_owned()
        } else {
            clean.to_owned()
        };
        if reserved.is_match(&base) {
            base = format!("book-{base}");
        }
        let mut id = base.clone();
        let mut counter = 2;
        while !used.insert(id.clone()) {
            id = format!("{base}-{counter}");
            counter += 1;
        }
        plan.items.push(BatchItem {
            id: id.clone(),
            workdir: id,
            pages: None,
            status: "pending".into(),
            error: None,
            input: Some(source),
        });
    }
    prepare_folder(out, |staging| write_manifest(staging, &plan))?;
    Ok(plan)
}
