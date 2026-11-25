#![forbid(unsafe_code)]

use std::io::{self, Cursor, Write};
use std::sync::{Arc, Barrier};
use std::time::Duration;

use revayat_tools::{eval, install, providers::ProviderClient, server, voice};
use serde_json::{Value, json};

type TestResult = Result<(), Box<dyn std::error::Error>>;

struct Echo {
    stages: Vec<server::StageDescriptor>,
    barrier: Option<Barrier>,
}

impl server::StageDispatcher for Echo {
    fn descriptors(&self) -> &[server::StageDescriptor] {
        &self.stages
    }

    fn dispatch(
        &self,
        _: &str,
        args: &[String],
        out: &mut dyn Write,
    ) -> Result<i32, server::StageError> {
        write!(out, "{{\"text\":")?;
        if let Some(barrier) = &self.barrier {
            barrier.wait();
        }
        serde_json::to_writer(&mut *out, &args.first()).map_err(io::Error::other)?;
        writeln!(out, "}}")?;
        Ok(0)
    }
}

fn dispatcher(barrier: Option<Barrier>) -> Echo {
    Echo {
        stages: vec![server::StageDescriptor::new("echo", "Echo one argument")],
        barrier,
    }
}

fn rpc(id: usize, text: &str) -> Value {
    json!({"jsonrpc":"2.0", "id":id, "method":"tools/call", "params":{"name":"revayat_echo", "arguments":{"args":[text]}}})
}

#[test]
fn stdio_one_physical_line_per_reply_and_resumes_after_bad_frames() -> TestResult {
    let mut input = vec![0xff, b'\n'];
    input.extend(vec![b' '; (1 << 20) + 1]);
    input.extend(
        format!(
            "\n{{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}}\n{}\n",
            rpc(1, "سلام\n\0دنیا")
        )
        .as_bytes(),
    );
    let mut out = Vec::new();
    assert_eq!(
        server::run_stdio_server(&dispatcher(None), Cursor::new(input), &mut out)?,
        0
    );
    let text = String::from_utf8(out)?;
    let lines = text
        .lines()
        .map(serde_json::from_str::<Value>)
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(lines.len(), 3);
    assert_eq!(lines[0]["error"]["code"], -32700);
    assert_eq!(lines[1]["error"]["code"], -32600);
    let result: Value = serde_json::from_str(
        lines[2]["result"]["content"][0]["text"]
            .as_str()
            .ok_or("no tool text")?,
    )?;
    assert_eq!(result["report"]["text"], "سلام\n\0دنیا");
    Ok(())
}

#[test]
fn overlapping_requests_capture_only_their_own_output() -> TestResult {
    let stages = Arc::new(dispatcher(Some(Barrier::new(2))));
    let workers: Vec<_> = (0..2)
        .map(|n| {
            let stages = Arc::clone(&stages);
            std::thread::spawn(move || {
                server::run_stage(stages.as_ref(), "echo", Some(&json!([n.to_string()])))
            })
        })
        .collect();
    for (n, worker) in workers.into_iter().enumerate() {
        let result = worker.join().map_err(|_| "dispatch thread failed")?;
        assert_eq!(result["report"]["text"], n.to_string());
    }
    Ok(())
}

#[test]
fn bearer_refuses_cleartext_non_loopback_before_io() {
    use revayat_tools::providers::ProviderError;
    for url in [
        "http://example.invalid",
        "http://localhost.example.invalid",
        "http://127.0.0.2",
    ] {
        assert!(matches!(
            ProviderClient::new(url, Some("test-key"), Duration::from_secs(1)),
            Err(ProviderError::InsecureBearer)
        ));
    }
    for url in [
        "https://example.invalid",
        "http://127.0.0.1:1234",
        "http://[::1]:1234",
        "http://localhost:1234",
    ] {
        assert!(ProviderClient::new(url, Some("test-key"), Duration::from_secs(1)).is_ok());
    }
}

#[test]
fn linter_is_idempotent_and_protects_literals() -> TestResult {
    let raw = "كتاب ها را مى خواند, خانه ام؟ https://example.test/v1.2.3 `foo 123`\nلازم به ذکر است كه ۱۲۳";
    let report = voice::lint_persian(raw, voice::Digits::Persian, true)?;
    assert!(report.fixed.contains("کتاب‌ها را می‌خواند، خانه‌ام؟"));
    assert!(
        report
            .fixed
            .contains("https://example.test/v1.2.3 `foo 123`")
    );
    assert!(
        report
            .suggestions
            .iter()
            .any(|hit| hit.message.contains("لازم به ذکر است"))
    );
    let again = voice::lint_persian(&report.fixed, voice::Digits::Persian, true)?;
    assert_eq!(report.fixed, again.fixed);
    assert_eq!(again.changed_lines, 0);
    Ok(())
}

#[test]
fn lexicon_matches_english_inflections_and_reverses_persian() -> TestResult {
    let result = voice::lookup_lexicon("They are business partners.", false)?;
    let row = result
        .glossary
        .iter()
        .find(|row| row.en == "business partner")
        .ok_or("missing term")?;
    let first_form = row
        .fa
        .split('/')
        .next()
        .ok_or("missing Persian term")?
        .trim();
    assert!(
        voice::lookup_lexicon(first_form, true)?
            .glossary
            .iter()
            .any(|reverse| reverse.en == row.en)
    );
    Ok(())
}

#[test]
fn installer_refuses_manifest_traversal_before_modification() -> TestResult {
    let tree = tempfile::tempdir()?;
    let repo = tree.path().join("source");
    let base = tree.path().join("target");
    std::fs::create_dir_all(repo.join("install"))?;
    std::fs::create_dir_all(repo.join("skills/revayat-comic"))?;
    std::fs::create_dir_all(&base)?;
    std::fs::write(repo.join("install/skill-files.txt"), "../../unowned.txt\n")?;
    assert!(install::safe_install(&repo, &base, "claude", false, false).is_err());
    assert!(!base.join(".claude").exists());
    Ok(())
}

#[test]
fn evaluator_distinguishes_missing_and_lost_protected_content() -> TestResult {
    let cases = json!({"cases":[
        {"id":"given", "source":"12?", "balloon":[0.4,0.2], "must_preserve":{"numbers":[["12", "۱۲"]],"question":true}},
        {"id":"missing", "source":"No!", "balloon":[0.4,0.2]}
    ]});
    let dir = tempfile::tempdir()?;
    let case_path = dir.path().join("cases.json");
    let answer_path = dir.path().join("answers.json");
    std::fs::write(&case_path, serde_json::to_vec(&cases)?)?;
    std::fs::write(
        &answer_path,
        serde_json::to_vec(&json!({"given":"کجاست؟"}))?,
    )?;
    let scored = eval::run_eval(&answer_path, Some(&case_path))?;
    assert_eq!(scored["rows"][0]["adequacy"]["machine_ok"], false);
    assert_eq!(scored["rows"][1]["adequacy"]["machine_ok"], false);
    assert_eq!(scored["rows"][0]["visual_fit"]["fits"], true);
    assert_eq!(scored["unanswered"], json!(["missing"]));
    assert_eq!(eval::status(&scored, false), 1);
    Ok(())
}

#[test]
fn generator_creates_images_and_context_without_reference_answers() -> TestResult {
    let cases = json!({"cases":[{"id":"sample", "source":"What?", "language":"en", "context":"Doorway", "continues_into":"second", "accept":["چی؟"], "balloon":[0.4,0.2]}]});
    let dir = tempfile::tempdir()?;
    let case_path = dir.path().join("cases.json");
    std::fs::write(&case_path, serde_json::to_vec(&cases)?)?;
    let paths = eval::build_pages(Some(&case_path), dir.path())?;
    assert_eq!(paths.len(), 1);
    let page = image::open(&paths[0])?.into_rgb8();
    assert_eq!(page.dimensions(), (1000, 1500));
    assert_eq!(page.get_pixel(500, 180).0, [255, 255, 255]);
    assert_eq!(page.get_pixel(500, 820).0, [255, 255, 255]);
    let task: Value =
        serde_json::from_slice(&std::fs::read(dir.path().join("sample.input.json"))?)?;
    assert_eq!(task["continues_into"], "second");
    assert!(task.get("accept").is_none());
    Ok(())
}

#[test]
fn installer_preserves_existing_skill_until_force_and_keeps_backup() -> TestResult {
    let dir = tempfile::tempdir()?;
    let repo = dir.path().join("source");
    let base = dir.path().join("installation base");
    let source = repo.join("skills/revayat-comic");
    std::fs::create_dir_all(repo.join("install"))?;
    std::fs::create_dir_all(&source)?;
    std::fs::create_dir_all(&base)?;
    std::fs::write(repo.join("install/skill-files.txt"), "SKILL.md\n")?;
    std::fs::write(source.join("SKILL.md"), "first")?;
    let first = install::safe_install(&repo, &base, "claude", false, false)?;
    let target = first.first().ok_or("missing target")?;
    assert_eq!(std::fs::read_to_string(target.join("SKILL.md"))?, "first");
    std::fs::write(source.join("SKILL.md"), "second")?;
    assert!(install::safe_install(&repo, &base, "claude", false, false).is_err());
    assert_eq!(std::fs::read_to_string(target.join("SKILL.md"))?, "first");
    install::safe_install(&repo, &base, "claude", true, false)?;
    assert_eq!(std::fs::read_to_string(target.join("SKILL.md"))?, "second");
    let entries = std::fs::read_dir(base.join(".revayat-comic-installer"))?
        .collect::<io::Result<Vec<_>>>()?;
    let backup = entries
        .into_iter()
        .map(|e| e.path().join("backup-0/SKILL.md"))
        .find(|p| p.is_file())
        .ok_or("missing backup")?;
    assert_eq!(std::fs::read_to_string(backup)?, "first");
    Ok(())
}

#[test]
fn provider_declines_incomplete_replies() -> TestResult {
    use revayat_tools::providers::text_reply;
    for reason in ["length", "content_filter", "max_tokens", "refusal", "error"] {
        assert_eq!(
            text_reply(
                &json!({"choices":[{"finish_reason":reason,"message":{"content":"partial"}}]})
            )?,
            None
        );
    }
    assert_eq!(
        text_reply(&json!({"choices":[{"message":{"refusal":"no","content":"partial"}}]}))?,
        None
    );
    assert!(text_reply(&json!({"choices":[{"message":{"content":12}}]})).is_err());
    Ok(())
}
