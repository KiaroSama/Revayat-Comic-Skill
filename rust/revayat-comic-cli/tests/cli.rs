#![forbid(unsafe_code)]

#[path = "cli/balloon_quality.rs"]
mod balloon_quality;

#[path = "cli/recheck.rs"]
mod recheck;

use std::{
    fs::{self, File},
    path::PathBuf,
    process::{Child, Command, Output, Stdio},
    sync::{
        RwLock,
        atomic::{AtomicUsize, Ordering},
    },
};

use serde_json::{Value, json};
use time::{OffsetDateTime, PrimitiveDateTime, macros::format_description};

// A concurrent fork can inherit the copy's writable descriptor and cause ETXTBSY.
static STAGE_EXEC_LOCK: RwLock<()> = RwLock::new(());

const KERNELS: [&str; 9] = [
    "cleancore-rs",
    "detectcore-rs",
    "hotcore-rs",
    "layoutcore-rs",
    "maskcore-rs",
    "packcore-rs",
    "pixcore-rs",
    "qacore-rs",
    "textcore-rs",
];

struct Fixture {
    root: PathBuf,
    executable: PathBuf,
    cwd: PathBuf,
}

impl Fixture {
    fn staged() -> Self {
        Self::new("bin")
    }

    fn new(executable_dir: &str) -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let root = loop {
            let path = std::env::temp_dir().join(format!(
                "revayat-cli test {}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed),
            ));
            match fs::create_dir(&path) {
                Ok(()) => break path,
                Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => (),
                Err(err) => panic!("create fixture: {err}"),
            }
        };
        let original = PathBuf::from(env!("CARGO_BIN_EXE_revayat-comic"));
        let executable = root
            .join(executable_dir)
            .join(original.file_name().unwrap());
        let cwd = root.join("unrelated cwd");
        let fixture = Self {
            root,
            executable,
            cwd,
        };
        fs::create_dir(fixture.executable.parent().unwrap()).unwrap();
        fs::create_dir(&fixture.cwd).unwrap();
        {
            let _write_guard = STAGE_EXEC_LOCK.write().unwrap_or_else(|e| e.into_inner());
            if fs::hard_link(&original, &fixture.executable).is_err() {
                fs::copy(&original, &fixture.executable).unwrap();
            }
        }
        fixture
    }

    fn spawn(&self, args: &[&str], stdin: Stdio) -> Child {
        let mut cmd = Command::new(&self.executable);
        cmd.args(args)
            .current_dir(&self.cwd)
            .env("PATH", "")
            .stdin(stdin)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let _read_guard = STAGE_EXEC_LOCK.read().unwrap_or_else(|e| e.into_inner());
        cmd.spawn().unwrap()
    }

    fn run(&self, args: &[&str], input: &[u8]) -> Output {
        let path = self.cwd.join("private input credential-marker.txt");
        fs::write(&path, input).unwrap();
        let output = self
            .spawn(args, Stdio::from(File::open(&path).unwrap()))
            .wait_with_output()
            .unwrap();
        assert_eq!(fs::read(path).unwrap(), input);
        output
    }

    fn run_json(&self, command: &str, input: Value) -> Output {
        self.run(&[command], input.to_string().as_bytes())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let mut last_err = None;
        for attempt in 0..8 {
            match fs::remove_dir_all(&self.root) {
                Ok(()) => return,
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => return,
                Err(err) => {
                    last_err = Some(err);
                    std::thread::sleep(std::time::Duration::from_millis(25 * (attempt + 1)));
                }
            }
        }
        if !std::thread::panicking() {
            panic!(
                "failed to remove test fixture {:?}: {:?}",
                self.root, last_err
            );
        }
    }
}

fn success(output: &Output) {
    assert_eq!(output.status.code(), Some(0), "{output:?}");
    assert!(output.stderr.is_empty(), "{output:?}");
}

fn usage_error(output: &Output) {
    assert_eq!(output.status.code(), Some(2), "{output:?}");
    assert!(output.stdout.is_empty(), "{output:?}");
    let stderr = std::str::from_utf8(&output.stderr).unwrap();
    assert!(stderr.starts_with("revayat-comic: "), "{stderr}");
}

fn json_stdout(output: &Output) -> Value {
    serde_json::from_slice(&output.stdout).unwrap()
}

#[test]
fn help_and_version_report_supported_commands() {
    let fixture = Fixture::staged();
    let output = fixture.run(&["--version"], b"");
    success(&output);
    assert_eq!(output.stdout, b"revayat-comic 2.0.3\n");
    let output = fixture.run(&["--help"], b"");
    success(&output);
    let help = std::str::from_utf8(&output.stdout).unwrap();
    for name in [
        "doctor",
        "normalize-persian",
        "wrap-lines",
        "sort-pages",
        "check-geometry",
    ] {
        assert!(help.contains(name), "{help}");
    }
}

#[test]
fn stdio_advertises_the_same_pipeline_commands_as_help() {
    let fixture = Fixture::staged();
    let help = fixture.run(&["--help"], b"");
    success(&help);
    let help = String::from_utf8(help.stdout).unwrap();
    let reply = fixture.run(
        &["serve", "--stdio"],
        b"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}\n",
    );
    success(&reply);
    let reply = json_stdout(&reply);
    assert_eq!(reply["id"], 1);
    let tools = reply["result"]["tools"].as_array().unwrap();
    for stage in [
        "import",
        "detect",
        "mask",
        "crops",
        "worksheet",
        "glossary",
        "falint",
        "clean",
        "typeset",
        "fullpage-prompt",
        "watermark",
        "qa",
        "export",
        "batch",
        "voice",
        "install",
        "eval",
        "ocr",
        "context",
        "translate",
        "review-docx",
    ] {
        assert!(
            help.lines()
                .any(|line| line.split_whitespace().next() == Some(stage)),
            "{stage}"
        );
        assert!(
            tools
                .iter()
                .any(|tool| tool["name"] == format!("revayat_{stage}")),
            "{stage}"
        );
    }
}

#[test]
fn persian_voice_lint_and_lookup_run_without_a_path_tool() {
    let fixture = Fixture::staged();
    let input = fixture.cwd.join("lines.txt");
    fs::write(&input, "من تا ساعت ٠٥ می‌روم و 15 کتاب می‌برم.").unwrap();
    let check = fixture.run(&["voice", "lint", "--check", "--style", "lines.txt"], b"");
    assert_eq!(check.status.code(), Some(1));
    assert!(
        !json_stdout(&check)["changes"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    success(&fixture.run(&["voice", "lint", "--fix", "lines.txt"], b""));
    success(&fixture.run(&["voice", "lint", "--check", "--style", "lines.txt"], b""));
    assert_eq!(
        fs::read_to_string(&input).unwrap(),
        "من تا ساعت 05 می‌روم و 15 کتاب می‌برم."
    );
    success(&fixture.run(
        &["voice", "lint", "--fix", "--digits", "persian", "lines.txt"],
        b"",
    ));
    assert_eq!(
        fs::read_to_string(&input).unwrap(),
        "من تا ساعت ۰۵ می‌روم و ۱۵ کتاب می‌برم."
    );
    let lookup = fixture.run(&["voice", "lookup", "business partners"], b"");
    success(&lookup);
    assert!(
        !json_stdout(&lookup)["glossary"]
            .as_array()
            .unwrap()
            .is_empty()
    );
}

#[test]
fn falint_check_and_fix_apply_the_selected_digits() {
    let fixture = Fixture::staged();
    image::RgbImage::from_pixel(128, 128, image::Rgb([255; 3]))
        .save(fixture.cwd.join("page.png"))
        .unwrap();
    let imported = fixture.run(&["import", "page.png", "--out", "work"], b"");
    success(&imported);
    let path = "work/comic.json";
    let file = fixture.cwd.join(path);
    let mut doc: Value = serde_json::from_slice(&fs::read(&file).unwrap()).unwrap();
    let id = doc["pages"][0]["id"].as_str().unwrap();
    let mut region = revayat_ir::ir::new_region(
        format!("{id}r001"),
        [20., 20., 80., 30.],
        "speech",
        "horizontal",
        "manual",
        1.,
    )
    .unwrap();
    region.source_text = "I have 15 books.".into();
    region.target_text = "من 15 کتاب دارم.".into();
    doc["pages"][0]["regions"] = json!([region]);
    let original = serde_json::to_vec(&doc).unwrap();
    fs::write(&file, &original).unwrap();
    let default_check = fixture.run(&["falint", "check", "--doc", path], b"");
    success(&default_check);
    let check = fixture.run(
        &["falint", "check", "--doc", path, "--digits", "persian"],
        b"",
    );
    assert_eq!(check.status.code(), Some(1));
    assert_eq!(
        fs::read(&file).unwrap(),
        original,
        "check rewrote the document"
    );

    for (args, expected) in [
        (vec!["--digits", "persian"], "من ۱۵ کتاب دارم."),
        (vec![], "من 15 کتاب دارم."),
    ] {
        let mut command = vec!["falint", "fix", "--doc", path];
        command.extend(args);
        let output = fixture.run(&command, b"");
        success(&output);
        assert_eq!(json_stdout(&output)["changed"], 1);
        let fixed: Value = serde_json::from_slice(&fs::read(&file).unwrap()).unwrap();
        assert_eq!(fixed["pages"][0]["regions"][0]["target_text"], expected);
    }
}

#[test]
fn doctor_reports_all_nine_kernels_without_path_tools() {
    let fixture = Fixture::staged();
    let output = fixture.run(&["doctor", "--json"], b"");
    success(&output);
    let report = json_stdout(&output);
    assert_eq!(report["version"], "2.0.3");
    assert_eq!(report["ok"], true);
    assert_eq!(report["kernels"].as_object().unwrap().len(), KERNELS.len());
    for name in KERNELS {
        assert_eq!(report["kernels"][name], true, "{name}");
    }
    let human = fixture.run(&["doctor"], b"");
    success(&human);
    let text = std::str::from_utf8(&human.stdout).unwrap();
    assert!(text.contains("2.0.3"));
    assert!(KERNELS.iter().all(|name| text.contains(name)));
}

#[test]
fn normalize_preserves_logical_order_and_protected_spans() {
    let fixture = Fixture::staged();
    let input = "كتاب ها را ببین؛ مي رود. كي\u{2029}عدد ١٢? v1.2، `كي 12?` https://ex.org/ي12";
    let expected = "کتاب‌ها را ببین؛ می‌رود. کی\nعدد ۱۲؟ v1.2، `كي 12?` https://ex.org/ي12";
    let output = fixture.run(&["normalize-persian"], input.as_bytes());
    success(&output);
    assert_eq!(output.stdout, expected.as_bytes());
    let repeat = fixture.run(&["normalize-persian"], input.as_bytes());
    success(&repeat);
    assert_eq!(repeat.stdout, output.stdout);
    let normalized = fixture.run(&["normalize-persian"], &output.stdout);
    success(&normalized);
    assert_eq!(normalized.stdout, output.stdout);
}

#[test]
fn wrap_lines_preserves_bigint_precision_and_reports_no_fit() {
    let fixture = Fixture::staged();
    let width = "9".repeat(128);
    let input =
        json!({"word_widths": [width, "5"], "space_width": "1", "band_widths": [width, "5"]});
    let output = fixture.run_json("wrap-lines", input.clone());
    success(&output);
    assert_eq!(json_stdout(&output), json!([[0, 1], [1, 2]]));
    let repeat = fixture.run_json("wrap-lines", input);
    success(&repeat);
    assert_eq!(repeat.stdout, output.stdout);
    let no_fit = fixture.run_json(
        "wrap-lines",
        json!({"word_widths": ["5"], "space_width": "0", "band_widths": ["4"]}),
    );
    success(&no_fit);
    assert_eq!(json_stdout(&no_fit), json!([]));
}

#[test]
fn sort_pages_keeps_duplicate_names_and_leaves_files_alone() {
    let fixture = Fixture::staged();
    let files = [
        ("page10.png", b"ten".as_slice()),
        ("page2.png", b"two".as_slice()),
    ];
    for (name, contents) in files {
        fs::write(fixture.cwd.join(name), contents).unwrap();
    }
    let input = json!(["page10.png", "page2.png", "page2.png"]);
    let output = fixture.run_json("sort-pages", input.clone());
    success(&output);
    assert_eq!(
        json_stdout(&output),
        json!(["page2.png", "page2.png", "page10.png"])
    );
    let repeat = fixture.run_json("sort-pages", input);
    success(&repeat);
    assert_eq!(repeat.stdout, output.stdout);
    for (name, contents) in files {
        assert_eq!(fs::read(fixture.cwd.join(name)).unwrap(), contents);
    }
    assert_eq!(fs::read_dir(&fixture.cwd).unwrap().count(), 3);
}

#[test]
fn geometry_returns_report_for_each_out_of_bounds_page() {
    let fixture = Fixture::staged();
    let input = json!({"dimensions": [[8, 6], [3, 6], [20, 20], [4, 10], [6, 8]], "max_aspect_ratio": 2, "min_edge": 4, "max_pixels": 48});
    let output = fixture.run_json("check-geometry", input.clone());
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stderr.is_empty());
    assert_eq!(
        json_stdout(&output),
        json!({"ok": false, "invalid_pages": [1, 2, 3]})
    );
    let repeat = fixture.run_json("check-geometry", input);
    assert_eq!(repeat.status.code(), Some(1));
    assert_eq!(repeat.stdout, output.stdout);
    let valid = fixture.run_json("check-geometry", json!({"dimensions": [[9_007_199_254_740_992_u64, 1]], "max_aspect_ratio": 9_007_199_254_740_992_u64, "min_edge": 1, "max_pixels": 9_007_199_254_740_992_u64}));
    success(&valid);
    assert_eq!(
        json_stdout(&valid),
        json!({"ok": true, "invalid_pages": []})
    );
}

#[test]
fn rejects_invalid_invocations_and_payloads_on_stderr() {
    let fixture = Fixture::staged();
    for args in [
        &[][..],
        &["unknown"],
        &["doctor", "--bad"],
        &["sort-pages", "path"],
    ] {
        usage_error(&fixture.run(args, b""));
    }
    for (command, input) in [
        ("normalize-persian", b"\xff".as_slice()),
        ("sort-pages", b"[\"\xff\"]"),
        ("sort-pages", b"["),
        ("sort-pages", b"[] []"),
        ("sort-pages", br#"[""]"#),
        ("sort-pages", br#"["x\u0000"]"#),
        ("wrap-lines", br#"{"word_widths":[0],"space_width":"0","band_widths":["1"]}"#),
        ("wrap-lines", br#"{"word_widths":["0"],"space_width":"0","band_widths":["1"]}"#),
        ("wrap-lines", br#"{"word_widths":["1"],"space_width":"-1","band_widths":["1"]}"#),
        ("wrap-lines", br#"{"word_widths":["1"],"space_width":"0","band_widths":["-1"]}"#),
        ("wrap-lines", br#"{"word_widths":["+1"],"space_width":"0","band_widths":["1"]}"#),
        ("wrap-lines", br#"{"word_widths":[],"space_width":"0","band_widths":[]}"#),
        ("check-geometry", br#"{"dimensions":[[0,2]],"max_aspect_ratio":1,"min_edge":1,"max_pixels":1}"#),
        ("check-geometry", br#"{"dimensions":[[1,2,3]],"max_aspect_ratio":1,"min_edge":1,"max_pixels":1}"#),
        ("check-geometry", br#"{"dimensions":[[1,2.0]],"max_aspect_ratio":1,"min_edge":1,"max_pixels":1}"#),
        ("check-geometry", br#"{"dimensions":[[1,2]],"max_aspect_ratio":1e999,"min_edge":1,"max_pixels":1}"#),
        ("check-geometry", br#"{"dimensions":[[1,2]],"max_aspect_ratio":0.9,"min_edge":1,"max_pixels":1}"#),
        ("check-geometry", br#"{"dimensions":[[1,2]],"max_aspect_ratio":1,"min_edge":0,"max_pixels":1}"#),
        ("check-geometry", br#"{"dimensions":[[1,2]],"max_aspect_ratio":1,"min_edge":1,"max_pixels":9007199254740993}"#),
        ("check-geometry", br#"{"dimensions":[[1,9007199254740993]],"max_aspect_ratio":1,"min_edge":1,"max_pixels":1}"#),
    ] {
        usage_error(&fixture.run(&[command], input));
    }
    usage_error(&fixture.run_json(
        "wrap-lines",
        json!({"word_widths": ["1".repeat(129)], "space_width": "0", "band_widths": ["1"]}),
    ));
}

#[test]
fn input_byte_and_array_limits_accept_exact_boundaries() {
    let fixture = Fixture::staged();
    let mut text = vec![b'x'; 1 << 20];
    let exact = fixture.run(&["normalize-persian"], &text);
    success(&exact);
    assert_eq!(exact.stdout, text);
    text.push(b'x');
    let oversized = fixture.run(&["normalize-persian"], &text);
    usage_error(&oversized);
    assert!(
        String::from_utf8(oversized.stderr)
            .unwrap()
            .contains("1 MiB")
    );
    for expected in [4096, 4097] {
        let sorted = fixture.run_json("sort-pages", json!(vec!["x"; expected]));
        let geometry = fixture.run_json("check-geometry", json!({"dimensions": vec![[1, 1]; expected], "max_aspect_ratio": 1, "min_edge": 1, "max_pixels": 1}));
        let words = fixture.run_json(
            "wrap-lines",
            json!({"word_widths": vec!["1"; expected], "space_width": "0", "band_widths": ["0"]}),
        );
        for output in [sorted, geometry, words] {
            if expected == 4096 {
                success(&output);
            } else {
                usage_error(&output);
            }
        }
    }
    for count in [128, 129] {
        let bands = fixture.run_json(
            "wrap-lines",
            json!({"word_widths": ["1"], "space_width": "0", "band_widths": vec!["1"; count]}),
        );
        if count == 128 {
            success(&bands);
            assert_eq!(json_stdout(&bands), json!([[0, 1]]));
        } else {
            usage_error(&bands);
        }
    }
}

#[test]
fn run_logs_have_utc_names_and_do_not_leak_input_or_paths() {
    let fixture = Fixture::staged();
    let secret = "credential-marker";
    usage_error(&fixture.run(&[secret], b""));
    let output = fixture.run_json("sort-pages", json!([format!("./{secret}.png")]));
    success(&output);
    usage_error(&fixture.run(&["sort-pages"], format!("\"{secret}\"").as_bytes()));
    let directory = fixture.root.join("logs");
    let mut count = 0;
    let (mut saw_error, mut saw_success) = (false, false);
    for entry in fs::read_dir(directory).unwrap() {
        let entry = entry.unwrap();
        count += 1;
        let name = entry.file_name();
        let stamp = name
            .to_str()
            .unwrap()
            .strip_prefix("revayat-comic_")
            .unwrap();
        PrimitiveDateTime::parse(
            &stamp[..19],
            format_description!("[year]-[month]-[day]_[hour]-[minute]-[second]"),
        )
        .unwrap();
        assert!(stamp[19..].starts_with("_UTC"));
        assert!(stamp.ends_with(".log"));
        let text = fs::read_to_string(entry.path()).unwrap();
        for line in text.lines() {
            PrimitiveDateTime::parse(
                &line[1..20],
                format_description!("[year]-[month]-[day] [hour]:[minute]:[second]"),
            )
            .unwrap();
            assert!(line[20..].starts_with(" UTC] ["));
            assert!(line.contains("] [revayat-comic] "));
        }
        for key in [
            "command=",
            "version=2.0.3",
            "run_id=",
            "exit=",
            "duration_ms=",
        ] {
            assert!(text.contains(key), "{text}");
        }
        assert!(!text.contains(secret));
        assert!(!text.contains("unrelated cwd"));
        saw_error |= text.contains("[ERROR]") && text.contains("exit=2");
        saw_success |= text.contains("[INFO]") && text.contains("exit=0");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(entry.path()).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }
    assert_eq!(count, 3);
    assert!(saw_error && saw_success);
    assert!(!fixture.cwd.join("logs").exists());
}

#[test]
fn simultaneous_invocations_keep_log_files_and_use_collision_suffixes() {
    let fixture = Fixture::staged();
    let directory = fixture.root.join("logs");
    fs::create_dir(&directory).unwrap();
    let now = OffsetDateTime::now_utc();
    let existing: Vec<_> = (-5..=60)
        .map(|offset| {
            let stamp = now + time::Duration::seconds(offset);
            let path = directory.join(format!(
                "revayat-comic_{}_{:02}-{:02}-{:02}_UTC.log",
                stamp.date(),
                stamp.hour(),
                stamp.minute(),
                stamp.second()
            ));
            fs::write(&path, b"existing log").unwrap();
            path
        })
        .collect();
    let children: Vec<_> = (0..4)
        .map(|_| fixture.spawn(&["--version"], Stdio::null()))
        .collect();
    let outputs: Vec<_> = children
        .into_iter()
        .map(|child| child.wait_with_output().unwrap())
        .collect();
    for output in outputs {
        success(&output);
    }
    let mut new_logs = 0;
    for entry in fs::read_dir(directory).unwrap() {
        let path = entry.unwrap().path();
        let text = fs::read_to_string(&path).unwrap();
        if existing.contains(&path) {
            assert_eq!(text, "existing log");
        } else {
            new_logs += 1;
            assert!(text.contains("exit=0"));
            let name = path.file_name().unwrap().to_str().unwrap();
            let (_, suffix) = name.split_once("_UTC_").unwrap();
            assert!(matches!(suffix, "01.log" | "02.log" | "03.log" | "04.log"));
        }
    }
    assert_eq!(new_logs, 4);
}

#[test]
fn non_bin_install_uses_executable_directory_for_logs() {
    let fixture = Fixture::new("tools");
    success(&fixture.run(&["--version"], b""));
    assert_eq!(
        fs::read_dir(fixture.root.join("tools/logs"))
            .unwrap()
            .count(),
        1
    );
    assert!(!fixture.root.join("logs").exists());
    assert!(!fixture.cwd.join("logs").exists());
}

#[test]
fn blocked_log_path_keeps_json_and_exit_code() {
    let fixture = Fixture::staged();
    let blocker = fixture.root.join("logs");
    fs::write(&blocker, b"keep this file").unwrap();
    let output = fixture.run_json("sort-pages", json!(["page10", "page2"]));
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(json_stdout(&output), json!(["page2", "page10"]));
    let stderr = std::str::from_utf8(&output.stderr).unwrap();
    assert!(stderr.contains("file logging unavailable"), "{stderr}");
    assert!(!stderr.contains(fixture.root.to_str().unwrap()), "{stderr}");
    assert_eq!(fs::read(blocker).unwrap(), b"keep this file");
    let error = fixture.run(&["sort-pages"], b"bad JSON");
    assert_eq!(error.status.code(), Some(2));
    assert!(error.stdout.is_empty());
    assert!(
        std::str::from_utf8(&error.stderr)
            .unwrap()
            .contains("file logging unavailable")
    );
    assert!(!fixture.cwd.join("logs").exists());
}
