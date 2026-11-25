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
