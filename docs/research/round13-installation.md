# Round 13 research record: installation integrity

Accessed 2026-10-04. Apply the owner's actual Rules and private research-record
format where installed; this record documents evidence available in this checkout.
No private Rules file or configured Spec Kit command was present in the source
archive. The reviewer must run those gates in the owner's environment.

## Observed repository mechanism

Baseline `f635f4a5e4f083e111d5fce3385a73fae1a12d3c` had two independent native
installers. Both removed the active directory before copying. Bash treated an
unavailable `/dev/tty` as consent, and its marker parser discarded the rest of
AGENTS.md after an unmatched BEGIN marker. A predictable scratch filename was
reused. Broad recursive copying admitted untracked source artifacts. These are
supported by isolated entry-point tests, not conclusions drawn from another repo.

## Primary sources and decisions

| Source | Mechanism and decision |
| --- | --- |
| [Python `os.rename`, `os.replace`, `fsync`](https://docs.python.org/3.13/library/os.html) | A successful same-filesystem rename is the publication primitive, not a transaction covering several destinations. Adopt explicit journal/backups and recovery; refuse cross-filesystem promotion. Do not infer power-loss durability of an entire batch from one atomic rename. |
| [Python `shutil`](https://docs.python.org/3.13/library/shutil.html) | Copy preparation can fail partway; metadata behavior differs by platform. Keep originals by rename, verify staged content, and copy only a declared payload. Do not use a delete-first recursive copy as rollback. |
| [OpenCode skill discovery](https://opencode.ai/docs/skills/) | Project/global native SKILL.md directories exist; old comments claiming AGENTS.md is the only discovery path were misleading. Retain compatibility pointers without placing backups under discoverable skill roots. No upstream source was copied. |
| [GitHub Spec Kit](https://github.com/github/spec-kit) and [workflow documentation](https://github.github.com/spec-kit/) | Specification/plan/tasks/implementation/convergence form an evidence chain. Follow the owner's installed command variants and additional gates; do not assume the custom `speckit-converge` name or private runner exists in this archive. |
| [GitHub Git commit API](https://docs.github.com/en/rest/git/commits#create-a-commit) | REST supports explicit author/committer objects, but the available connector schema omits them. Its inspected commit uses noreply. Document the identity integration gate; local Git configuration cannot correct that remote object. |
| [Dependabot options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference) | Keep existing manifest coverage and intentional version-update limits. Administrative security-update enablement is distinct from the version PR limit; no unverified security-setting claim is made. |

## Alternative assessment

Keeping two full implementations in shell and PowerShell would double the
journal/recovery state machine and platform-specific error paths. A shared
stdlib-only Python bootstrap is selected, with the existing native entry points
and flags preserved. This deliberately moves the Python prerequisite to install
time; the runtime already requires Python 3.10+. A third-party package manager,
transaction library, model provider or GPU adds no value to this filesystem task.
Tests on each platform must decide compatibility, not assumptions about Windows
rename/link behavior. New helper code is included in recursive Ruff coverage.

## Additional fixes found while resuming

The first draft also required conservative guards for linked recovery storage,
lock cleanup when the pending path is linked, missing committed backups and an
edit arriving after promotion. A single-agent pointer update now retains the
other installed pointer. Six additional reproducers failed on the first draft
and pass on the revised implementation. These are in-session closures, not items
silently deferred to another audit.

## Translation-quality proposals (not measured improvements)

Keep the source-first, Persian-fluency and source-comparison review sequence.
Evaluate paired scenes for pronoun referents, irony, negation, quantities and
relationship-dependent register with bilingual reviewers who see the panels.
Score fidelity separately from readability and typography; preserve alternative
valid Persian renderings. Keep full/display text approval and do not make an
ordinary context-dependent phrase a universal locked term. No live model or
licensed real-comic quality experiment was performed during this installer repair.
