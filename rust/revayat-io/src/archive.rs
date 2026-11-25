use std::{
    collections::{HashMap, HashSet},
    fs::File,
    io::{self, Write},
    path::Path,
};

use rars::{ArchiveReadOptions, ArchiveReader};
use zip::ZipArchive;

use crate::{
    IoError,
    fsutil::{bounded_read, read_file},
    images::image_extension,
    inputs::{MAX_MEMBER_BYTES, MAX_PAGES, MAX_TOTAL_BYTES},
    invalid,
    order::natural_sort_order,
};

const MAX_MEMBERS: usize = 20_000;

pub(crate) fn member_name(name: &str) -> Result<String, IoError> {
    let normalized = name.replace('\\', "/");
    let stripped = normalized.strip_suffix('/').unwrap_or(&normalized);
    if stripped.is_empty()
        || stripped.split('/').any(|part| {
            part.is_empty()
                || matches!(part, "." | "..")
                || part.bytes().any(|b| b < 32 || b == b':')
        })
    {
        return Err(IoError::ArchivePath(name.to_owned()));
    }
    Ok(normalized)
}

fn junk(name: &str) -> bool {
    name.split('/')
        .any(|part| part.starts_with('.') || part.eq_ignore_ascii_case("__MACOSX"))
}

pub fn check_archive_limits<'a>(
    name: &str,
    members: impl IntoIterator<Item = (&'a str, u64, u64)>,
) -> Result<(), IoError> {
    let mut total = 0_u64;
    for (index, (member, size, stored)) in members.into_iter().enumerate() {
        if index >= MAX_MEMBERS {
            return Err(invalid(format!("{name} has too many archive members")));
        }
        total = total.saturating_add(size);
        if size > MAX_MEMBER_BYTES
            || total > MAX_TOTAL_BYTES
            || (stored >= 4096 && size > stored.saturating_mul(250))
        {
            return Err(invalid(format!(
                "{name} exceeds archive expansion limits at {member}"
            )));
        }
    }
    Ok(())
}

pub(crate) fn check_page_count(size: usize) -> Result<(), IoError> {
    match size {
        0 => Err(invalid("Input contains no page images")),
        1..=MAX_PAGES => Ok(()),
        _ => Err(invalid(format!(
            "Input has {size} pages; split it into volumes of no more than {MAX_PAGES} pages"
        ))),
    }
}

#[derive(Clone)]
pub(crate) struct Member {
    pub index: usize,
    pub name: String,
    pub extension: String,
    pub size: u64,
}

fn page_members(
    entries: impl IntoIterator<Item = (String, u64, bool)>,
) -> Result<Vec<Member>, IoError> {
    let mut names = HashSet::new();
    let mut pages = Vec::new();
    for (index, (name, size, directory)) in entries.into_iter().enumerate() {
        let name = member_name(&name)?;
        if directory || junk(&name) {
            continue;
        }
        if let Some(extension) = image_extension(Path::new(&name)) {
            if !names.insert(name.to_lowercase()) {
                return Err(invalid(format!("Duplicate archive page: {name}")));
            }
            pages.push(Member {
                index,
                name,
                extension,
                size,
            });
        }
    }
    check_page_count(pages.len())?;
    let names = pages
        .iter()
        .map(|page| page.name.clone())
        .collect::<Vec<_>>();
    Ok(natural_sort_order(&names)
        .into_iter()
        .map(|i| pages[i].clone())
        .collect())
}

pub(crate) fn zip_pages(archive: &mut ZipArchive<File>) -> Result<Vec<Member>, IoError> {
    if archive.len() > MAX_MEMBERS {
        return Err(invalid("Too many ZIP members"));
    }
    let rows = (0..archive.len())
        .map(|i| {
            let member = archive.by_index_raw(i)?;
            let name = member.name()?.into_owned();
            member_name(&name)?;
            if member.is_symlink() {
                return Err(IoError::ArchivePath(name));
            }
            Ok((
                name,
                member.size(),
                member.compressed_size(),
                member.is_dir(),
            ))
        })
        .collect::<Result<Vec<_>, IoError>>()?;
    check_archive_limits(
        "ZIP",
        rows.iter()
            .map(|(name, size, stored, _)| (name.as_str(), *size, *stored)),
    )?;
    page_members(
        rows.into_iter()
            .map(|(name, size, _, dir)| (name, size, dir)),
    )
}

pub(crate) fn zip_read(
    archive: &mut ZipArchive<File>,
    member: &Member,
) -> Result<Vec<u8>, IoError> {
    let bytes = bounded_read(
        archive.by_index(member.index)?,
        member.size.min(MAX_MEMBER_BYTES),
    )?;
    if bytes.len() as u64 != member.size {
        return Err(invalid("ZIP member size changed during extraction"));
    }
    Ok(bytes)
}

pub(crate) fn extract_rar(input: &Path, stage: &Path) -> Result<Vec<(String, String)>, IoError> {
    let options = ArchiveReadOptions::new()
        .with_max_header_count(MAX_MEMBERS as u64)
        .with_max_header_bytes(64 << 20)
        .with_max_reader_workspace_bytes(MAX_MEMBER_BYTES)
        .with_max_member_output_bytes(MAX_MEMBER_BYTES)
        .with_max_total_output_bytes(MAX_TOTAL_BYTES)
        .with_rar50_dictionary_size_limit(MAX_MEMBER_BYTES)
        .with_threads(1);
    let archive =
        ArchiveReader::read_owned_with_options(read_file(input, MAX_TOTAL_BYTES)?, options)?;
    let rows = archive
        .members()
        .map(|member| {
            let name = String::from_utf8_lossy(&member.meta.name).into_owned();
            (
                name,
                member.meta.unpacked_size,
                member.meta.packed_size,
                member.meta.is_directory,
            )
        })
        .collect::<Vec<_>>();
    check_archive_limits(
        "RAR",
        rows.iter()
            .map(|(name, size, stored, _)| (name.as_str(), *size, *stored)),
    )?;
    let pages = page_members(
        rows.into_iter()
            .map(|(name, size, _, dir)| (name, size, dir)),
    )?;
    let names: Vec<_> = pages
        .iter()
        .enumerate()
        .map(|(i, page)| {
            (
                format!("p{:04}.{}", i + 1, page.extension),
                page.name.clone(),
            )
        })
        .collect();
    let mapped: HashMap<_, _> = names
        .iter()
        .zip(&pages)
        .map(|((target, _), member)| (member.name.as_str(), target))
        .collect();
    archive.extract_to_with_options(options, |meta| {
        let name = String::from_utf8_lossy(&meta.name).replace('\\', "/");
        let output: Box<dyn Write> = match mapped.get(name.as_str()) {
            Some(target) if !meta.is_directory => Box::new(
                File::options()
                    .write(true)
                    .create_new(true)
                    .open(stage.join(target))?,
            ),
            _ => Box::new(io::sink()),
        };
        Ok(output)
    })?;
    Ok(names)
}
