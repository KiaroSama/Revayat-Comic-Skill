# Round 13 — safe installation and preservation of owner instructions

**First fully obey the owner's actual Rules, AGENTS.md, CLAUDE.md, CONTEXT.md, nested instructions and installed hooks. Use the owner-configured Spec Kit chain and guarded runner. Never bypass a hook, weaken a test, suppress a failure or discard another writer's work merely to declare completion. Keep private Rules, `.ai/`, `.specify/` and `specs/` material ignored and out of public commits and attachments.**

## Scope, publication and authority

Repository: `KiaroSama/Revayat-Comic-Skill`. Audited base: `f635f4a5e4f083e111d5fce3385a73fae1a12d3c`, tree `4c40b9cbfca6dff6415a6fdebf4c5bf2881dbbc3`. The previous active-region fixes are integrated and retained. This round repairs the installers, not the translation engine.

**[PR #11 is open](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/11)** on `fix/round13-transactional-installation`. Reuse this branch; the explicit PR requirement justifies one branch, not additional branches by habit. All code, native wrappers, manifest, tests, CI changes and operator/research documentation are in this PR. The final head, independent source verification and native CI results are recorded in its evidence section and the accompanying owner-facing bundle. Do not mistake an earlier green SHA or a local patch for final publication evidence.

The authoring assistant must not merge, close, enable auto-merge, rewrite shared history or change main. Only the owner or expressly authorized reviewing agent performs integration and all-PR disposition. The PR remains Draft pending the actual identity and owner-environment gates below.

## Required workflow and commit identity

Discover the actual installed Rules/Spec Kit commands and existing project specification first. For an already specified defect, use the owner's `speckit-converge` → `speckit-implement` repair route and required validation. For the new shared bootstrap contract or changed specified behavior, follow `speckit-specify` → `speckit-clarify` → `speckit-plan` → `speckit-tasks` → `speckit-analyze` → `speckit-implement`, including required interview, constitution, checklist and final convergence gates. Preserve existing infrastructure; do not reinitialize it to silence errors. These commands and private hooks were not available in the audit container and were not claimed executed. This specification/design/acceptance record is input to that workflow, not a substitute execution claim.

**Both author and committer emails for every past and future published commit must be exactly `Kiaro.Sama.Dev@gmail.com`. Immediately inventory and reconstruct other identities according to the owner's Rules.** Inspect raw `%ae`/`%ce` and the Rules-relevant trailers; configuration, a message trailer or `.mailmap` alone does not repair historical objects. Preserve verified trees, truthful attribution, licenses, messages and an old/new SHA map. Back up and coordinate refs before historical reconstruction; never blindly force-push over concurrent work. Recheck the final integrating SHA and its checks.

The connected commit wrapper exposes no identity override and its inspected remote commit uses the automatic GitHub noreply identity. **That requirement is not satisfied.** The authorized reviewer must reconstruct the affected commits with the approved identities, preserving their verified trees, before integration. The native patch supplied with the evidence uses the approved local author; its applying committer must also use that address. The assistant does not rewrite shared history or claim that a locally correct identity repaired the remote one.

## I-01 — A missing terminal implicitly approved destructive replacement

**Before:** Bash prompted for `[Y/n]` and set `answer="y"` when `/dev/tty` could not be read. A detached update without `--force` deleted the existing installation and local note and returned success. Failure to obtain input is not consent. The two native installers also maintained separate replacement behavior.

**Implementation:** one shared stdlib bootstrap requires explicit force or an affirmative interactive answer. Noninteractive replacement preserves the existing copy. New installs need no replacement consent. If nothing is selected, return nonzero rather than falsely reporting an update. Existing flag names remain supported by both wrappers.

**Acceptance:** run the actual platform entry point with disconnected input and a pre-existing skill/local note. Require refusal and byte preservation, not an indefinite prompt, deletion or success. Verify force, fresh install and subsequent reinstall. Existing successful-install controls remain intact.

## I-02 — Pointer maintenance could erase owner Rules or another file

**Before:** an unmatched Revayat BEGIN marker caused all remaining `AGENTS.md` content to be dropped, including unrelated owner rules. Nested/repeated sections were not rejected. Bash reused and deleted `AGENTS.md.revayat-comic.tmp` even when the operator already owned it. Instruction updates were outside the installation transaction.

**Implementation:** a shared byte-preserving editor validates UTF-8 and exactly one balanced owned block. Invalid markers refuse before replacement. Preserve outside bytes, BOM and the existing newline convention. Prepare pointer bytes with unique exclusive staging, and promote them in the same journaled batch as skill copies. Recheck the pointer snapshot so another writer's new instructions are not overwritten. A one-agent update retains both existing OpenCode/Antigravity compatibility pointers instead of deleting the other installed route.

**Acceptance:** unmatched begin/end, repeated/nested sections, LF/CRLF/CR, BOM, missing final newline, pre-existing scratch, second-install idempotence, pointer promotion failure, concurrent pointer edit and successive one-agent updates. Assert actual bytes and previous installation contents, not only marker counts.

## I-03 — Delete-first copying destroyed recoverable installations

**Before:** both entry points removed active destinations before copying. Checking only `SKILL.md` let incomplete bundles replace working installations. Copy interruption or a later pointer failure left mixed/missing versions. Even a successful forced replacement permanently discarded local operator notes.

**Implementation:** validate the complete tracked manifest and snapshot every source file. Prepare and hash every selected candidate before changing an active target; recheck source and destination snapshots. Keep old installations by same-filesystem rename, not lossy recopy. Write the prepared journal before promotion, verify the whole published batch before marking committed, and retain previous copies and history outside native skill-discovery roots.

An ordinary failure rolls back only verified owned states. Explicit `--recover` / `-Recover` verifies a dead local owner and a recognized journal: roll back a prepared transaction or finish a committed one. Recovery checks target, staging, backup and their ancestors. A missing committed backup is not successful recovery. Rollback can itself be interrupted and resumed. Live/unknown owners, linked paths, foreign records or intervening edits stop the operation and preserve evidence rather than replacing user work.

**Acceptance:** remove each required source component; inject copy errors at early, late and multi-agent positions; fail all six backup/promotion boundaries and prepared/committed record writes; kill a real subprocess at five publication/history boundaries. Recover and reinstall. Interrupt rollback and resume it. Preserve an external edit arriving during staging or after promotion; retain its journal. Verify backups are outside discoverable skills and previous local notes survive there. Backup retention is intentional operator-owned history, not an unfinished automatic cleanup task.

## I-04 — Recursive copying propagated private source artifacts

**Before:** broad recursive copying plus a short list of cache exclusions still propagated arbitrary untracked reading copies and local artifacts. It also could not establish a complete intended payload.

**Implementation:** `install/skill-files.txt` lists the 61 tracked skill files. Copy only those paths. A test requires exact agreement with `git ls-files skills/revayat-comic`, so adding/removing a tracked helper or reference requires updating the manifest. No model, font, personal comic or new third-party package is bundled.

**Acceptance:** create caches, logs, virtualenvs and private reading-copy directories under the local source; none may reach the installed copy. Verify all declared files, the installed self-contained CLI and a repeated installation.

## Architecture and compatibility

Bash and PowerShell remain the native entry points but delegate to a single **stdlib-only Python 3.10+** helper. This explicitly moves the interpreter prerequisite to installation time; unsupported/missing Python fails before active files are changed. `REVAYAT_PYTHON` selects an existing executable. No Python distribution, pip package or network service is automatically installed.

Preserve all eight agent layouts and existing `all` discovery: explicit agents create their skill path, while `all` visits already-existing configuration roots. Preserve OpenCode's user/project layouts. Native OpenCode SKILL.md discovery exists; the compatibility AGENTS pointer is retained without describing it as the only discovery mechanism. See `install/README.md` for exact PowerShell/POSIX usage, backup semantics and recovery.

The state lives under `.revayat-comic-installer` in the selected project/home. Pending candidates and backups are outside native skill folders, preventing duplicate active discovery. Existing customizations are backed up, not automatically merged into the new active version. Links/junctions and cross-filesystem promotion are refused conservatively. Pre-journal residue is reported and retained; empty created parent directories may remain after a preparation failure. This targets process interruption and detected cooperating edits, not hostile same-user races, arbitrary hardware failure or universal power-loss durability.

## Completed verification and CI

The original archive checksum and **180 tracked Git blobs** were verified without mismatches. Its synthetic test-merge snapshot has the audited main tree and is not an assistant-performed merge. Resumed evidence is separately recorded rather than inheriting an interrupted session's claimed counts:

| Check | Actual result |
| --- | --- |
| Original full suite | 1768 passed, 1 unavailable RAR-backend skip |
| 16 baseline native-entry/manifest contracts | 15 failed, 1 passed |
| Six resumed recovery/pointer contracts on initial Draft | 6 failed |
| All installer contracts on repaired candidate | 53 passed, no skips |
| Final complete local suite | 1821 passed, 1 RAR skip; 1822 collected; no failures/errors |
| Real CLI pipeline, preservation checks, CBZ/PDF verification | Passed |
| Recursive Ruff and whitespace checks | Passed |

The baseline manifest assertion is a new bundle contract, not a pre-existing API. New-helper tests are not falsely presented as failures against a helper that did not exist. The only local skip is the absent `unrar/unar/bsdtar` backend; the existing deliberate duplicate ZIP-member fixture emits its known warning. The local installed DejaVu face is not claimed byte-identical to CI's pinned font. No font file is included in delivery.

`test_installer_safety.py` exercises real Bash/PowerShell entry points; `test_installer_transactions.py` covers faults, ownership and actual process exits; `test_installer_resume_guards.py` closes six additional gaps discovered while resuming. Final-head native JUnit results and source read-back are recorded on the PR; local success is not called remote CI success until those checks complete.

CI explicitly provisions Python in the existing installer job and adds `install` to recursive Ruff. Preserve the current OS/Python matrix, literal dependency floors, shaping and real archive capability checks, strict skip inventory, source evidence, CodeQL and dependency review. No tests were removed, weakened or marked expected-failure. No pip dependency or duplicate workflow was added. Keep intentional Dependabot version-update limits and grouping; administrative security updates are a separate setting, not inferred disabled from a zero version-PR limit.

Run through the owner's required guarded wrapper with `REVAYAT_TEST_FONT` configured according to `tests/README.md`:

```powershell
python -m pytest tests/test_installer_safety.py tests/test_installer_transactions.py tests/test_installer_resume_guards.py -q --timeout=90
python -m pytest tests -q -rs --timeout=300 --junitxml=junit-review.xml
python tests/e2e_pipeline.py
python -m ruff check skills/revayat-comic/scripts tests evaluation .github install
git diff --check
```

## Research and optional translation improvements

**Research this repository and current primary documentation, especially relevant GitHub implementations. Record dates, revisions, mechanisms, alternatives and accept/defer/reject decisions in the location/format prescribed by the owner's Rules.** Do not copy private research artifacts into the public repository. This public implementation rationale is in `docs/research/round13-installation.md`; further private research follows the owner's actual research Rules.

Sources: [Python filesystem operations](https://docs.python.org/3.13/library/os.html), [copying semantics](https://docs.python.org/3.13/library/shutil.html), [OpenCode discovery](https://opencode.ai/docs/skills/), [Spec Kit upstream](https://github.com/github/spec-kit), [GitHub commit API](https://docs.github.com/en/rest/git/commits#create-a-commit), and [Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference). Shared stdlib transaction logic avoids maintaining two divergent shell state machines; tests, not platform assumptions, must establish portability.

Optional quality work is separate from the required installer repair. Retain source-first → Persian-only fluency → source comparison. Expand bilingual-reviewed paired-scene cases for referents, negation, modality, quantities, irony and relationship-based register. Keep multiple acceptable Persian renderings and independent fidelity/voice/layout ratings. Preserve full/display approval; never fit by dropping meaning or locking a context-sensitive phrase universally. Evaluate upstream context/glossary strategies on licensed representative pages before changing providers. No live model or real-comic semantic quality improvement was measured here. GPU-backed specialists remain optional measured tools, not a requirement for deterministic file installation.

## One-session closure of all PRs

Inventory **all repository PRs** and apply the owner's actual merge/closure Rules to every one; do not exempt a PR merely as unrelated. Maintain one ledger: finding → specification/plan → code → before/after tests → final SHA/checks → integration/disposition. Preserve prior repairs and concurrent work.

Reproduce and fix any genuine additional defect encountered in the same review session, add a regression and revalidate the combination. Do not leave accepted actionable code as a next-round placeholder. If a failure repeats unchanged, inspect the failed invariant rather than blindly retrying. Record genuinely unavailable external prerequisites without fabricating completion.

After the actual Rules, Spec Kit, hooks, approved identities and final-SHA checks pass, the **authorized reviewer** commits/pushes with the required email and merges approved directly mergeable changes. Otherwise reconcile or manually integrate equivalent verified functionality, identify its integration commit and only then close superseded PRs under the Rules. **Every PR must reach its Rules-defined merged/closed DONE state; closing an accepted unfixed repair is not completion.** Verify the combined default branch and raw identities after integration. The authoring assistant performs none of those merge, closure, auto-merge or shared-history actions.
