#![forbid(unsafe_code)]

use std::io::{Cursor, Write};

#[cfg(unix)]
use revayat_tools::install;
use revayat_tools::{eval, server, voice};
use serde_json::{Value, json};

struct NoStages;

impl server::StageDispatcher for NoStages {
    fn descriptors(&self) -> &[server::StageDescriptor] {
        &[]
    }

    fn dispatch(
        &self,
        _: &str,
        _: &[String],
        _: &mut dyn Write,
    ) -> Result<i32, server::StageError> {
        Err(server::StageError::new("unexpected-call", "no stages"))
    }
}

#[test]
fn rpc_preserves_large_integer_ids_and_rejects_nonfinite_numbers()
-> Result<(), Box<dyn std::error::Error>> {
    let id = "10000000000000000000012345";
    let input = format!(
        "{{\"jsonrpc\":\"2.0\",\"method\":\"ping\",\"id\":{id}}}\n{{\"jsonrpc\":\"2.0\",\"method\":\"ping\",\"id\":1e99999}}\n"
    );
    let mut out = Vec::new();
    server::run_stdio_server(&NoStages, Cursor::new(input), &mut out)?;
    let out = String::from_utf8(out)?;
    let mut replies = out.lines().map(serde_json::from_str::<Value>);
    assert_eq!(
        replies.next().ok_or("missing ping reply")??["id"].to_string(),
        id
    );
    assert_eq!(
        replies.next().ok_or("missing invalid number reply")??["error"]["code"],
        -32700
    );
    assert!(replies.next().is_none());
    Ok(())
}

#[test]
fn voice_keeps_latin_literals_and_ambiguous_comparatives() -> Result<(), Box<dyn std::error::Error>>
{
    let text =
        "1. اين خانه تر است; عدد ٠٥ و 12 و v1.2.3...\n`ي 12` info@example.test\n    echo ي 42";
    let fixed = voice::lint_persian(text, voice::Digits::Persian, false)?;
    assert!(fixed.fixed.contains("1. این خانه تر است؛ عدد ۰۵ و ۱۲"));
    assert!(fixed.fixed.contains("v1.2.3"));
    assert!(
        fixed
            .fixed
            .contains("`ي 12` info@example.test\n    \u{2067}echo ي 42\u{2069}")
    );
    assert!(
        fixed
            .suggestions
            .iter()
            .any(|item| item.kind == "maybe_comparative_tar")
    );
    let latin = voice::lint_persian(&fixed.fixed, voice::Digits::Latin, false)?;
    assert!(latin.fixed.contains("عدد 05 و 12"));
    assert_eq!(
        voice::lint_persian("۱۲ و ٠٥", voice::Digits::Keep, false)?.fixed,
        "۱۲ و ٠٥"
    );
    Ok(())
}

#[test]
fn evaluation_preserves_compounds_and_signed_quantities_without_prefix_matches()
-> Result<(), Box<dyn std::error::Error>> {
    let case: eval::EvalCase = serde_json::from_value(
        json!({"id":"numbers","must_preserve":{"numbers":["3:15", "-12.5", "سه"], "terms":["C++", "من"]}}),
    )?;
    let exact = eval::check_preserved(
        &case,
        "من ساعت ۳ : ۱۵ رسیدم. دما −۱۲٫۵ و نام C++ است. سه بار.",
    )?;
    assert_eq!(exact["numbers"]["ok"], true);
    assert_eq!(exact["terms"]["ok"], true);
    let different = eval::check_preserved(&case, "۳ یا ۱۵، ۱۲٫۵، سه‌شنبه، C+++، دشمن")?;
    assert_eq!(
        different["numbers"]["missing"],
        json!(["3:15", "-12.5", "سه"])
    );
    assert_eq!(different["terms"]["missing"], json!(["C++", "من"]));
    Ok(())
}

#[cfg(unix)]
#[test]
fn installer_rejects_a_symlinked_ancestor() -> Result<(), Box<dyn std::error::Error>> {
    let tree = tempfile::tempdir()?;
    let repo = tree.path().join("source");
    let base = tree.path().join("base");
    let outside = tree.path().join("outside");
    std::fs::create_dir_all(repo.join("install"))?;
    std::fs::create_dir_all(repo.join("skills/revayat-comic"))?;
    std::fs::create_dir_all(&base)?;
    std::fs::create_dir_all(&outside)?;
    std::fs::write(repo.join("install/skill-files.txt"), "SKILL.md\n")?;
    std::fs::write(repo.join("skills/revayat-comic/SKILL.md"), "sample")?;
    std::os::unix::fs::symlink(&outside, base.join(".claude"))?;
    assert!(matches!(
        install::safe_install(&repo, &base, "claude", false, false),
        Err(install::InstallError::UnsafePath(_))
    ));
    assert_eq!(std::fs::read_dir(&outside)?.count(), 0);
    Ok(())
}
