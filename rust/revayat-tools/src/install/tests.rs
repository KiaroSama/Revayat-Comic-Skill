use super::*;

#[test]
fn resolves_install_scope() {
    let base = PathBuf::from("sandbox");
    let project = resolve_install_scope(Some(base.clone()), Some("project"), false);
    assert_eq!(project, Ok((base.clone(), false)));
    let user = resolve_install_scope(Some(base.clone()), Some("user"), false);
    assert_eq!(user, Ok((base.clone(), true)));
    let inferred = resolve_install_scope(None, Some("user"), false).ok();
    assert_eq!(inferred, std::env::home_dir().map(|path| (path, true)));
    assert!(resolve_install_scope(None, Some("project"), false).is_err());
    assert!(resolve_install_scope(Some(base), Some("project"), true).is_err());
}

#[test]
fn installs_from_explicit_repo_outside_working_directory() -> Result<()> {
    let target = tempfile::tempdir()?;
    let repo = fs::canonicalize(Path::new(env!("CARGO_MANIFEST_DIR")).join("../.."))?;
    let skill = repo.join("skills/revayat-comic/SKILL.md");
    let paths = safe_install(&repo, target.path(), "claude", false, false)?;
    assert_eq!(fs::read(paths[0].join("SKILL.md"))?, fs::read(skill)?);
    Ok(())
}

#[test]
fn recovery_restores_both_promoted_and_backed_up_destinations() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let base = unlinked_base(dir.path())?;
    let control = base.join(CONTROL);
    let tx = "tx-interrupted";
    let pending = control.join("pending.json");
    fs::create_dir_all(control.join(tx))?;
    let mut record = Record {
        tx: tx.into(),
        phase: Phase::Prepared,
        items: Vec::new(),
    };
    for (i, folder) in [".claude", ".cursor"].into_iter().enumerate() {
        let rel = Path::new(folder).join("skills/revayat-comic");
        let target = base.join(&rel);
        let stage = control.join(tx).join(format!("stage-{i}"));
        fs::create_dir_all(&target)?;
        fs::create_dir(&stage)?;
        fs::write(target.join("SKILL.md"), format!("old-{i}"))?;
        fs::write(stage.join("SKILL.md"), format!("new-{i}"))?;
        let old = digest(&target)?;
        let new = digest(&stage)?.ok_or(InstallError::Invalid("missing stage"))?;
        record.items.push(Item {
            target: rel,
            old,
            new,
        });
        let (target, stage, backup) = record.paths(&base, i)?;
        rename(&target, &backup)?;
        if i == 0 {
            rename(&stage, &target)?;
        }
    }
    journal(&pending, &record, false)?;
    assert!(matches!(
        safe_install(&base, &base, "all", true, false),
        Err(InstallError::Pending)
    ));
    safe_install(&base, &base, "all", true, true)?;
    for (i, item) in record.items.iter().enumerate() {
        assert_eq!(
            fs::read_to_string(base.join(&item.target).join("SKILL.md"))?,
            format!("old-{i}")
        );
    }
    assert!(!pending.exists());
    assert!(control.join(tx).join("rolled-back.json").is_file());
    Ok(())
}
