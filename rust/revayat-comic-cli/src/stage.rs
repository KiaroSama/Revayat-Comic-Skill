use std::{
    io::{self, Write},
    net::SocketAddr,
    path::PathBuf,
    sync::{Arc, OnceLock},
};

use clap::{Args, Parser, Subcommand, ValueEnum};
use revayat_io::{
    export::{self, ExportOptions},
    inputs::{ImportOptions, MAX_PAGE_PIXELS},
    package, readers, reviewdocx,
};
use revayat_ir::{
    batch, glossary, ir, worksheet,
    workspace::{self, LoadedDocument},
};
use revayat_tools::{
    eval, install,
    server::{self, StageDescriptor, StageDispatcher, StageError},
    voice,
};
use serde::Serialize;
use serde_json::json;

use crate::{processing, providers};

fn stage_registry() -> Vec<StageDescriptor> {
    use clap::CommandFactory;
    StageCli::command()
        .get_subcommands()
        .filter(|command| command.get_name() != "help")
        .map(|command| {
            StageDescriptor::new(
                command.get_name(),
                command
                    .get_about()
                    .map(ToString::to_string)
                    .unwrap_or_default(),
            )
        })
        .collect()
}

#[derive(Parser)]
#[command(name = "revayat-comic")]
struct StageCli {
    #[command(subcommand)]
    stage: Stage,
}

#[derive(Args)]
struct Doc {
    #[arg(long)]
    doc: PathBuf,
}

#[derive(Clone, Copy, ValueEnum)]
enum Direction {
    Rtl,
    Ltr,
}

#[derive(Clone, Copy, ValueEnum)]
enum WorksheetAction {
    Build,
    Merge,
    Status,
}

#[derive(Clone, Copy, ValueEnum)]
enum GlossaryAction {
    Scan,
    Check,
}

#[derive(Clone, Copy, ValueEnum)]
enum FalintAction {
    Check,
    Fix,
}

#[derive(Clone, Copy, ValueEnum)]
enum QaAction {
    Check,
    Package,
}

#[derive(Clone, Copy, ValueEnum)]
enum BatchAction {
    Plan,
    Merge,
    Status,
}

#[derive(Subcommand)]
enum VoiceAction {
    Lint {
        path: Option<PathBuf>,
        #[arg(long, conflicts_with = "fix")]
        check: bool,
        #[arg(long)]
        fix: bool,
        #[arg(long)]
        style: bool,
    },
    Lookup {
        text: Vec<String>,
        #[arg(long)]
        reverse: bool,
    },
}

#[derive(Subcommand)]
enum EvalAction {
    Build {
        #[arg(long)]
        out: PathBuf,
        #[arg(long)]
        cases: Option<PathBuf>,
    },
    Score {
        answers: PathBuf,
        #[arg(long)]
        cases: Option<PathBuf>,
        #[arg(long)]
        complete: bool,
    },
}

#[derive(Subcommand)]
enum Stage {
    /// Import comic pages into a workspace.
    Import {
        source: PathBuf,
        #[arg(long)]
        out: PathBuf,
        #[arg(long, default_value_t = MAX_PAGE_PIXELS)]
        max_pixels: u64,
        #[arg(long, default_value = "auto", alias = "source-lang")]
        source_language: String,
        #[arg(long, value_enum, default_value = "rtl")]
        direction: Direction,
        #[arg(long, default_value = "")]
        title: String,
        #[arg(long, default_value = "")]
        chapter: String,
    },
    /// Find panels and lettering regions.
    Detect(Doc),
    /// Build masks for editable lettering.
    Mask {
        #[command(flatten)]
        doc: Doc,
        #[arg(long, value_parser = ["glyph", "solid"])]
        free_lettering: Option<String>,
    },
    /// Render region crops, overview and sheets.
    Crops(Doc),
    /// Build, merge or inspect translation worksheets.
    Worksheet {
        mode: WorksheetAction,
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        worksheets: Option<PathBuf>,
        #[arg(long)]
        pages: Option<String>,
        #[arg(long)]
        force: bool,
    },
    /// Scan terms or check glossary drift.
    Glossary {
        mode: GlossaryAction,
        #[command(flatten)]
        doc: Doc,
        #[arg(long, default_value_t = 2)]
        minimum: usize,
    },
    /// Check or fix Persian text mechanics.
    Falint {
        mode: FalintAction,
        #[command(flatten)]
        doc: Doc,
    },
    /// Remove source lettering inside approved masks.
    Clean {
        #[command(flatten)]
        doc: Doc,
        #[arg(long, conflicts_with = "external_dir")]
        bubbles_only: bool,
        #[arg(long, alias = "external")]
        external_dir: Option<PathBuf>,
    },
    /// Place Persian lettering in the cleaned page.
    Typeset {
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        external_dir: Option<PathBuf>,
    },
    /// Build a full-page image-edit manifest.
    FullpagePrompt {
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        page: String,
        #[arg(long, default_value = revayat_vision::fullpage_edit::DEFAULT_MODEL)]
        model: String,
        #[arg(long)]
        all_regions: bool,
    },
    /// Mark an exact rectangle for erasure.
    Watermark {
        #[command(flatten)]
        doc: Doc,
        #[arg(long = "box")]
        bounds: String,
        #[arg(long)]
        from_overview: bool,
    },
    /// Check pages or an exported package.
    Qa {
        mode: QaAction,
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        strict: bool,
        #[arg(long)]
        package: Option<PathBuf>,
    },
    /// Export the rendered comic.
    Export {
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        out: PathBuf,
        #[arg(long)]
        review_docx: Option<PathBuf>,
        #[arg(long)]
        draft: bool,
    },
    /// Export a bilingual review document.
    ReviewDocx {
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        out: PathBuf,
    },
    /// Plan, merge or inspect shards.
    Batch {
        mode: BatchAction,
        #[arg(long)]
        doc: Option<PathBuf>,
        #[arg(long)]
        batch: Option<PathBuf>,
        #[arg(long)]
        out: Option<PathBuf>,
        #[arg(long, default_value_t = 2)]
        shards: usize,
    },
    /// Request optional hosted transcription.
    Ocr {
        #[command(flatten)]
        doc: Doc,
        #[arg(long, default_value = "openai")]
        provider: String,
        #[arg(long)]
        model: Option<String>,
    },
    /// Print translation context for a page.
    Context {
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        page: String,
        #[arg(long, default_value_t = revayat_ir::context::CONTEXT_BUDGET)]
        budget: usize,
        #[arg(long)]
        allow_unmerged: bool,
    },
    /// Request optional hosted translation.
    Translate {
        #[command(flatten)]
        doc: Doc,
        #[arg(long)]
        page: String,
        #[arg(long)]
        model: Option<String>,
    },
    /// Check Persian mechanics or look up terminology.
    Voice {
        #[command(subcommand)]
        action: VoiceAction,
    },
    /// Install the skill files transactionally.
    Install {
        #[arg(long, default_value = ".")]
        repo: PathBuf,
        #[arg(long, visible_alias = "path")]
        base: Option<PathBuf>,
        #[arg(long, value_parser = ["user", "project"], conflicts_with = "user_scope")]
        scope: Option<String>,
        #[arg(long, default_value = "all")]
        agent: String,
        #[arg(long)]
        user_scope: bool,
        #[arg(long)]
        force: bool,
        #[arg(long)]
        recover: bool,
    },
    /// Build or score synthetic fixtures.
    Eval {
        #[command(subcommand)]
        action: EvalAction,
    },
}

pub struct Dispatcher;

impl StageDispatcher for Dispatcher {
    fn descriptors(&self) -> &[StageDescriptor] {
        static STAGES: OnceLock<Vec<StageDescriptor>> = OnceLock::new();
        STAGES.get_or_init(stage_registry)
    }

    fn dispatch(
        &self,
        stage: &str,
        args: &[String],
        output: &mut dyn Write,
    ) -> Result<i32, StageError> {
        let cli = StageCli::try_parse_from(
            ["revayat-comic", stage]
                .into_iter()
                .chain(args.iter().map(String::as_str)),
        );
        match cli {
            Ok(cli) => stage_output(cli.stage, output),
            Err(error) if error.kind() == clap::error::ErrorKind::DisplayHelp => {
                writeln!(output, "{error}")?;
                Ok(0)
            }
            Err(error) => Err(usage(error.to_string().trim_end())),
        }
    }
}

pub fn registered(name: &str) -> bool {
    Dispatcher
        .descriptors()
        .iter()
        .any(|stage| stage.name == name)
}

pub fn help() -> String {
    use std::fmt::Write as _;
    let mut help = String::from("\nPipeline commands:\n");
    for stage in Dispatcher.descriptors() {
        let _ = writeln!(help, "  {:18} {}", stage.name, stage.description);
    }
    help.push_str(
        "  serve              Expose pipeline commands over MCP stdio or loopback HTTP.\n",
    );
    help
}

#[derive(Parser)]
#[command(name = "revayat-comic serve")]
struct Serve {
    #[arg(long, conflicts_with = "http")]
    stdio: bool,
    #[arg(long)]
    http: Option<SocketAddr>,
}

pub fn serve(args: &[String]) -> Result<i32, StageError> {
    if args == ["mcp"] {
        return Ok(server::run_stdio_server(
            &Dispatcher,
            io::stdin().lock(),
            io::stdout().lock(),
        )?);
    }
    let cli = match Serve::try_parse_from(
        ["revayat-comic serve"]
            .into_iter()
            .chain(args.iter().map(String::as_str)),
    ) {
        Ok(cli) => cli,
        Err(error) if error.kind() == clap::error::ErrorKind::DisplayHelp => {
            print!("{error}");
            return Ok(0);
        }
        Err(error) => return Err(usage(error.to_string().trim_end())),
    };
    if let Some(addr) = cli.http {
        let token = std::env::var("REVAYAT_HTTP_TOKEN")
            .ok()
            .filter(|token| !token.is_empty())
            .ok_or_else(|| usage("set REVAYAT_HTTP_TOKEN before serving HTTP"))?;
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()?
            .block_on(server::run_http_server(
                Arc::new(Dispatcher),
                addr,
                Some(&token),
                |addr, _| {
                    eprintln!("revayat-comic: HTTP listening on {addr}; send X-Revayat-Token");
                },
            ))?;
        Ok(0)
    } else {
        Ok(server::run_stdio_server(
            &Dispatcher,
            io::stdin().lock(),
            io::stdout().lock(),
        )?)
    }
}

pub fn usage(message: impl Into<String>) -> StageError {
    StageError::new("invalid-arguments", message)
}

pub fn failed(error: impl std::fmt::Display) -> StageError {
    StageError::new("stage-failed", error.to_string())
}

fn report(output: &mut dyn Write, result: impl Serialize, status: i32) -> Result<i32, StageError> {
    serde_json::to_writer(&mut *output, &result).map_err(failed)?;
    writeln!(output)?;
    output.flush()?;
    Ok(status)
}

fn stage_output(stage: Stage, output: &mut dyn Write) -> Result<i32, StageError> {
    let value = match stage {
        Stage::Import {
            source,
            out,
            max_pixels,
            source_language,
            direction,
            title,
            chapter,
        } => {
            let options = ImportOptions {
                max_pixels,
                source_language,
                title,
                chapter,
                reading_direction: match direction {
                    Direction::Rtl => "rtl",
                    Direction::Ltr => "ltr",
                }
                .into(),
                ..ImportOptions::default()
            };
            json!(readers::import_input(&source, &out, &options).map_err(failed)?)
        }
        Stage::Detect(doc) => processing::detect(&doc.doc)?,
        Stage::Mask {
            doc,
            free_lettering,
        } => processing::mask(&doc.doc, free_lettering.as_deref() == Some("solid"))?,
        Stage::Crops(doc) => processing::crops(&doc.doc)?,
        Stage::Worksheet {
            mode,
            doc,
            worksheets,
            pages,
            force,
        } => {
            let pages = pages.as_deref().map(workspace::parse_pages);
            match mode {
                WorksheetAction::Build => {
                    json!({"built":worksheet::build_document(&doc.doc, worksheets.as_deref(), pages.as_deref(), force).map_err(failed)?})
                }
                WorksheetAction::Merge => {
                    json!({"merged":worksheet::merge_document(&doc.doc, worksheets.as_deref(), pages.as_deref(), force).map_err(failed)?})
                }
                WorksheetAction::Status => {
                    json!(worksheet::status(&doc.doc, worksheets.as_deref()).map_err(failed)?)
                }
            }
        }
        Stage::Glossary { mode, doc, minimum } => match mode {
            GlossaryAction::Scan => processing::write_doc(&doc.doc, "glossary", |loaded| {
                Ok(json!({"added":glossary::scan(&mut loaded.document, minimum).map_err(failed)?}))
            })?,
            GlossaryAction::Check => {
                let document = ir::load_doc(&doc.doc).map_err(failed)?;
                let drift = glossary::check(&document);
                return report(
                    output,
                    json!({"ok":drift.is_empty(),"drift":drift}),
                    i32::from(!drift.is_empty()),
                );
            }
        },
        Stage::Falint { mode, doc } => {
            let (value, status) = processing::falint(&doc.doc, matches!(mode, FalintAction::Fix))?;
            return report(output, value, status);
        }
        Stage::Clean {
            doc,
            bubbles_only,
            external_dir,
        } => processing::clean(&doc.doc, bubbles_only, external_dir.as_deref())?,
        Stage::Typeset { doc, external_dir } => {
            processing::typeset(&doc.doc, external_dir.as_deref())?
        }
        Stage::FullpagePrompt {
            doc,
            page,
            model,
            all_regions,
        } => processing::fullpage(&doc.doc, &page, model, all_regions)?,
        Stage::Watermark {
            doc,
            bounds,
            from_overview,
        } => processing::watermark(&doc.doc, &bounds, from_overview)?,
        Stage::Qa {
            mode,
            doc,
            strict,
            package: path,
        } => {
            let value = match mode {
                QaAction::Check => processing::qa(&doc.doc, strict)?,
                QaAction::Package => json!(
                    package::check_package(
                        &path.ok_or_else(|| usage("qa package requires --package"))?,
                        &doc.doc
                    )
                    .map_err(failed)?
                ),
            };
            let code = i32::from(value["ok"] != true);
            return report(output, value, code);
        }
        Stage::Export {
            doc,
            out,
            review_docx,
            draft,
        } => {
            let options = ExportOptions {
                draft,
                ..ExportOptions::default()
            };
            let comic = export::export_document(&doc.doc, &out, None, &options).map_err(failed)?;
            if let Some(path) = review_docx {
                let review = reviewdocx::export_review_document(&doc.doc, &path).map_err(failed)?;
                json!({"comic":comic,"review":review})
            } else {
                json!(comic)
            }
        }
        Stage::ReviewDocx { doc, out } => {
            json!(reviewdocx::export_review_document(&doc.doc, &out).map_err(failed)?)
        }
        Stage::Batch {
            mode,
            doc,
            batch: folder,
            out,
            shards,
        } => match mode {
            BatchAction::Plan => {
                let doc = doc.ok_or_else(|| usage("batch plan requires --doc"))?;
                json!(
                    batch::plan_shards(&ir::doc_dir(&doc), shards, out.as_deref())
                        .map_err(failed)?
                )
            }
            BatchAction::Merge => {
                let doc = doc.ok_or_else(|| usage("batch merge requires --doc"))?;
                let folder = folder.ok_or_else(|| usage("batch merge requires --batch"))?;
                json!(batch::merge_shards(&folder, &ir::doc_dir(&doc)).map_err(failed)?)
            }
            BatchAction::Status => json!(
                batch::read_manifest(
                    &folder.ok_or_else(|| usage("batch status requires --batch"))?
                )
                .map_err(failed)?
            ),
        },
        Stage::Ocr {
            doc,
            provider,
            model,
        } => providers::ocr(&doc.doc, &provider, model)?,
        Stage::Context {
            doc,
            page,
            budget,
            allow_unmerged,
        } => {
            let loaded = LoadedDocument::open(&doc.doc).map_err(failed)?;
            providers::context(&loaded, &page, budget, allow_unmerged)?
        }
        Stage::Translate { doc, page, model } => providers::translate(&doc.doc, &page, model)?,
        Stage::Voice {
            action:
                VoiceAction::Lint {
                    path,
                    check,
                    fix,
                    style,
                },
        } => {
            let path = path.ok_or_else(|| usage("voice lint requires a UTF-8 input path"))?;
            let text = read_text(&path)?;
            let lint = voice::lint_persian(&text, voice::Digits::Keep, style).map_err(failed)?;
            if fix && lint.changed_lines > 0 {
                ir::write_text(&path, &lint.fixed).map_err(failed)?;
            }
            let code = i32::from(check && (lint.changed_lines > 0 || !lint.suggestions.is_empty()));
            return report(output, lint, code);
        }
        Stage::Voice {
            action: VoiceAction::Lookup { text, reverse },
        } => {
            if text.is_empty() {
                return Err(usage("voice lookup requires search text"));
            }
            json!(voice::lookup_lexicon(&text.join(" "), reverse).map_err(failed)?)
        }
        Stage::Install {
            repo,
            base,
            scope,
            agent,
            user_scope,
            force,
            recover,
        } => {
            let (base, user_scope) =
                install::resolve_install_scope(base, scope.as_deref(), user_scope)
                    .map_err(usage)?;
            json!({"installed":install::safe_install_scoped(&repo, &base, &agent, user_scope, force, recover).map_err(failed)?})
        }
        Stage::Eval {
            action: EvalAction::Build { out, cases },
        } => json!({"pages":eval::build_pages(cases.as_deref(), &out).map_err(failed)?}),
        Stage::Eval {
            action:
                EvalAction::Score {
                    answers,
                    cases,
                    complete,
                },
        } => {
            let value = eval::run_eval(&answers, cases.as_deref()).map_err(failed)?;
            let code = eval::status(&value, complete);
            return report(output, value, code);
        }
    };
    report(output, value, 0)
}

fn read_text(path: &std::path::Path) -> Result<String, StageError> {
    let file = std::fs::File::open(path)?;
    let text = crate::read_input(file).map_err(|err| failed(err.message()))?;
    Ok(text)
}
