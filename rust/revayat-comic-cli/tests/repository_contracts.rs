use std::{collections::BTreeSet, fs, path::PathBuf, process::Command};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn tracked_text_and_packaged_skill_have_valid_utf8() {
    let repo = root();
    let output = Command::new("git")
        .args(["ls-files", "-z"])
        .current_dir(&repo)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "repository hygiene requires a Git checkout"
    );
    let mut checked = 0;
    for name in output
        .stdout
        .split(|&byte| byte == 0)
        .filter(|name| !name.is_empty())
    {
        let name = std::str::from_utf8(name).expect("repository path must be UTF-8");
        let path = repo.join(name);
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if matches!(
            extension,
            "rs" | "md"
                | "json"
                | "toml"
                | "lock"
                | "yml"
                | "yaml"
                | "txt"
                | "tsv"
                | "csv"
                | "ps1"
                | "sh"
        ) || matches!(name, ".gitattributes" | ".gitignore" | ".editorconfig")
        {
            let bytes = fs::read(&path).unwrap();
            assert!(
                std::str::from_utf8(&bytes).is_ok(),
                "non-UTF-8 text file: {name}"
            );
            checked += 1;
        }
    }
    assert!(
        checked > 100,
        "did not inspect the complete source checkout"
    );
    let skill = fs::read_to_string(repo.join("skills/revayat-comic/SKILL.md")).unwrap();
    assert!(skill.starts_with("---\nname: revayat-comic\n"));
    let header = skill.split("\n---\n").next().unwrap();
    assert!(header.lines().any(|line| line.starts_with("description: ")));
    assert!(header.contains(concat!("\"version\":\"", env!("CARGO_PKG_VERSION"), "\"")));
    let files = fs::read_to_string(repo.join("install/skill-files.txt")).unwrap();
    let mut seen = BTreeSet::new();
    for file in files.lines() {
        assert!(seen.insert(file), "duplicate packaged skill path: {file}");
        assert!(
            !file.is_empty() && !file.starts_with('/') && !file.split('/').any(|part| part == "..")
        );
        assert!(
            repo.join("skills/revayat-comic").join(file).is_file(),
            "missing packaged skill file: {file}"
        );
    }
}

#[test]
fn readme_badges_and_plugin_versions_match_the_cli_release() {
    let repo = root();
    let version = env!("CARGO_PKG_VERSION");
    let ci = "https://github.com/KiaroSama/Revayat-Comic-Skill/actions/workflows/ci.yml/badge.svg?branch=main";
    let shields = "https://img.shields.io/badge/";
    for (path, size_anchor, tail) in [
        (
            "README.md",
            "#development",
            ["## Author", "## License", "## Donate"],
        ),
        (
            "README.fa.md",
            "#توسعه",
            ["## نویسنده", "## مجوز", "## حمایت مالی"],
        ),
    ] {
        let text = fs::read_to_string(repo.join(path)).unwrap();
        assert!(!text.contains("https://img.shields.io/github/"), "{path}");
        let badges: Vec<_> = text
            .lines()
            .filter(|line| line.starts_with("[!["))
            .map(|line| line.split_once("](").unwrap().1.split_once(")](").unwrap())
            .map(|(image, target)| (image, target.strip_suffix(')').unwrap()))
            .collect();
        assert_eq!(badges.len(), 14, "{path}");
        assert_eq!(badges[0], (ci, ".github/workflows/ci.yml"), "{path}");
        assert_eq!(
            badges[1],
            (
                "https://img.shields.io/badge/license-GPL--3.0-2563eb?style=flat-square",
                "LICENSE"
            ),
            "{path}"
        );
        assert_eq!(
            badges[2],
            (
                format!("{shields}version-v{version}-ea580c?style=flat-square").as_str(),
                "#releases-and-tags"
            ),
            "{path}"
        );
        assert_eq!(
            badges[3],
            (
                format!("{shields}release-v{version}-dc2626?style=flat-square").as_str(),
                "https://github.com/KiaroSama/Revayat-Comic-Skill/releases"
            ),
            "{path}"
        );
        assert_eq!(
            badges[9],
            (
                "https://img.shields.io/badge/repo%20size-2.5%20MiB-ca8a04?style=flat-square",
                size_anchor
            ),
            "{path}"
        );
        assert_eq!(
            badges[13],
            (
                "https://img.shields.io/badge/Support-donations-d04a9a?style=flat-square",
                "#donate"
            ),
            "{path}"
        );
        let colors: BTreeSet<_> = badges[1..]
            .iter()
            .map(|(image, _)| {
                let label = image.strip_prefix(shields).unwrap();
                let payload = label.strip_suffix("?style=flat-square").unwrap();
                let (_, color) = payload.rsplit_once('-').unwrap();
                assert_eq!(color.len(), 6, "{path}: {image}");
                assert!(
                    color.bytes().all(|b| b.is_ascii_hexdigit()),
                    "{path}: {image}"
                );
                color
            })
            .collect();
        assert_eq!(colors.len(), 13, "{path}: duplicate badge colors");
        let headings: Vec<_> = text
            .lines()
            .filter(|line| line.starts_with("## "))
            .collect();
        assert!(headings.ends_with(&tail), "{path}: README ending order");
    }
    for (path, pointer) in [
        ("plugin.json", "/version"),
        (".claude-plugin/plugin.json", "/version"),
        (".claude-plugin/marketplace.json", "/plugins/0/version"),
        (".cursor-plugin/plugin.json", "/version"),
        (".codex-plugin/plugin.json", "/version"),
        (".antigravity-plugin/plugin.json", "/version"),
    ] {
        let manifest: serde_json::Value =
            serde_json::from_slice(&fs::read(repo.join(path)).unwrap()).unwrap();
        assert_eq!(
            manifest
                .pointer(pointer)
                .and_then(serde_json::Value::as_str),
            Some(version),
            "{path}"
        );
    }
}

#[test]
fn every_qa_registry_code_has_a_documented_recovery_action() {
    let guide = fs::read_to_string(root().join("skills/revayat-comic/SKILL.md")).unwrap();
    for codes in [
        revayat_vision::qa::CODES,
        revayat_io::package::CODES,
        revayat_ir::certify::CODES,
    ] {
        assert_eq!(
            codes.iter().copied().collect::<BTreeSet<_>>().len(),
            codes.len(),
            "duplicate QA identifier"
        );
        for code in codes {
            let marker = format!("| `{code}` |");
            let row = guide
                .lines()
                .find(|line| line.starts_with(&marker))
                .unwrap_or_else(|| panic!("undocumented QA code: {code}"));
            let cells = row.split('|').map(str::trim).collect::<Vec<_>>();
            assert!(
                cells.len() >= 5 && !cells[2].is_empty() && !cells[3].is_empty(),
                "QA code needs a meaning and recovery action: {code}"
            );
        }
    }
}
