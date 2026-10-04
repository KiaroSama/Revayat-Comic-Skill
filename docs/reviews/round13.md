# Round 13 — safe installation and preservation of owner instructions

**First fully obey the owner's actual Rules, AGENTS.md, CLAUDE.md, CONTEXT.md,
nested instructions and installed hooks. Use the owner-configured Spec Kit chain
and guarded runner. Never bypass a hook, weaken a test, suppress a failure or
discard another writer's work merely to declare completion.**

## Scope, current state and authority

Repository: `KiaroSama/Revayat-Comic-Skill`. Audited base:
`f635f4a5e4f083e111d5fce3385a73fae1a12d3c`, tree
`4c40b9cbfca6dff6415a6fdebf4c5bf2881dbbc3`.
The previous round's active-region decisions are integrated and retained. This
round addresses **the installers**, not another speculative rewrite of the
translation engine. The complete original suite was run on verified source;
additional tests exercise real installer entry points and transaction failures.

Publish these changes as a reviewable PR. Reuse that PR branch; a branch is
necessary because the owner expressly requires PR-only delivery. The auditing
assistant must not merge/close PRs, enable auto-merge, or change main. The owner or
expressly authorized reviewing agent performs integration and all-PR disposition.
The owner-facing delivery records the actual PR number/head and check results.
Do not infer publication from a local patch or a prepared PR description.

## Required workflow and commit identity

Discover the actual installed Rules/Spec Kit commands first. For a defect whose
specification already exists, follow the owner's `speckit-converge` →
`speckit-implement` repair route and its required validation. For the new shared
installer/bootstrap contract, use the Rules-defined complete specification,
clarification/checklist, plan, tasks, analysis, implementation and convergence
chain. Do not invent success for private slash commands or hooks unavailable in
this environment. The specification, design and acceptance inventory below are
review inputs, not a substitute claim that those commands were executed.

**Both author and committer emails for every past and future published commit
must be exactly `Kiaro.Sama.Dev@gmail.com`. Immediately inventory and reconstruct
wrong-email history according to the owner's Rules.** Inspect raw `%ae`/`%ce`;
Git configuration, a message trailer or `.mailmap` alone does not repair historical
commit objects. Preserve verified code trees, credits, messages and an old/new
SHA map. Back up and coordinate refs before a history rewrite; never blindly
force-push over concurrent work. Recheck the final integrating SHA and its checks.
The authoring assistant does not rewrite shared history. If the connected commit
wrapper cannot set identities, disclose the actual result and retain a Draft
identity gate; do not describe noreply commits as compliant. The supplied native
Git patch uses the approved local author identity; the applying committer must
also use the approved address.

## Reproduced defects and technical resolution

### I-01 — Missing terminal implicitly approves destructive replacement

**Before:** Bash prompted for `[Y/n]` and set `answer="y"` when `/dev/tty` could
not be read. In a detached process, rerunning the installer without `--force`
deleted the prior installation and its local note, then returned success. A
missing input channel is not consent. PowerShell and Bash also maintained
separate replacement behavior.

**Repair:** the shared installer requires explicit `--force` or an affirmative
interactive answer. Noninteractive replacement is refused without changing the
active copy; the wrappers retain their existing command-line names. New installs
do not require replacement consent. A skipped-all invocation exits unsuccessfully
rather than implying that an update occurred.

**Acceptance:** the real platform entry point is run with disconnected input and
an existing skill/local note. It must fail/keep, not prompt indefinitely, delete
or succeed. Explicit force and subsequent successful reinstall are tested.

### I-02 — Updating a pointer can delete owner Rules or another file

**Before:** an unmatched BEGIN marker in `AGENTS.md` caused all remaining lines,
including unrelated owner rules, to be dropped. Repeated/nested delimiters were
not rejected. Bash also overwrote and removed the predictable file
`AGENTS.md.revayat-comic.tmp`, even when it already belonged to the operator.
Both entry points wrote the user instruction file directly rather than treating
it as part of the installation transaction.

**Repair:** one byte-preserving pointer editor validates UTF-8 and exactly one
balanced section. Invalid delimiters cause preflight refusal before replacement.
Only the owned span changes; outside bytes, line-ending convention and BOM are
retained. Staging uses unique, exclusively created paths, never the operator's
fixed-name scratch. Pointer preparation and promotion participate in the same
batch as the skill copies. A pointer changed by another writer is preserved,
not overwritten by a stale preflight buffer.

**Acceptance:** unmatched begin/end, repeated and nested sections; LF/CRLF/CR;
BOM; missing final newline; old scratch-file preservation; idempotent second
installation; failure before/during pointer promotion; concurrent owner edit.
Verify actual bytes and old installation content, not only a marker count.

### I-03 — Delete-first copying destroys a working installation on failure

**Before:** both installers removed the active destination before copying.
Checking only `SKILL.md` allowed an incomplete source bundle lacking the CLI or
other required files to replace a working copy. Interrupted copying or a later
pointer failure could leave no consistent prior version. A successful forced
replacement also permanently discarded untracked local notes/customizations.

**Repair:** validate the tracked bundle manifest, prepare all selected copies,
verify framed file hashes and recheck the source snapshot before publication.
Use same-filesystem staged promotion with a write-ahead journal. Preserve old
copies by rename, not a lossy recopy. Any ordinary error restores matching prior
states as a batch. An explicit `--recover` / `-Recover` verifies a dead local
owner and known journal/artifact states; it rolls back a prepared transaction or
finishes a committed one. Rollback may itself be interrupted and resumed.
Unknown/live owners or independently modified destinations are never displaced.

Backups and pending candidates live in `.revayat-comic-installer`, outside
native skill-discovery folders, so the old `SKILL.md` cannot override the new
one. The journal/history and backups are retained as evidence. Links/junctions
and cross-filesystem promotion are refused conservatively. The backup policy is
intentional, not an uncompleted cleanup task; retention belongs to the operator.

**Acceptance:** remove each required source component before installation;
inject copy failures at early/late/multi-agent positions, every backup/promotion
boundary, and prepared/committed journal writes. Kill a real child process at
five promotion/history boundaries, recover, reinstall, and verify the active
content. Interrupt rollback itself, then recover again. Preserve intervening
edits and unfamiliar journals instead of overwriting them. Ensure backups are
not discoverable as active skill copies.

### I-04 — Recursive copying leaks local source-directory artifacts

**Before:** broad recursive copying was followed by a short cache-name cleanup.
Untracked local reading copies or other private files under the source skill
were still distributed into agent installations. Source validation could not
prove a complete or intentionally bounded payload.

**Repair:** `install/skill-files.txt` lists the complete tracked skill payload.
Only those files are copied. A repository test requires exact agreement with
`git ls-files skills/revayat-comic`, preventing a new helper/reference from being
forgotten. No third-party dependency, model, font or input comic is bundled.

**Acceptance:** add representative caches, logs, virtualenvs and private reading
copies to the local source tree; none may appear in the installed directory.
Check all manifest files and repeat the normal install/doctor/use workflow.

## Design and compatibility decisions

Bash and PowerShell remain native entry points but delegate to one **stdlib-only
Python 3.10+ bootstrap**. This is an explicit installation prerequisite change,
consistent with the runtime's existing floor; unsupported/missing Python must
fail before touching active files. `REVAYAT_PYTHON` selects the interpreter. Do
not silently install a Python distribution, add a Python package, or launch a
network provider. Keep all eight existing agent layouts and the `all` discovery
policy. The compatibility pointer is retained; native OpenCode skill discovery
does not require it. See `install/README.md` for operator/recovery instructions.

The protocol targets local interruption and cooperating writers, not hostile
same-user races or arbitrary storage failure. Unknown ownership is an explicit
review condition, not permission to delete a lock or rewrite a user's changes.
Pre-journal leftovers are retained outside discovery folders. Do not advertise
filesystem-wide power-loss guarantees that the tests do not establish.

## Verification, CI and dependency policy

The original archive checksum and **180 tracked Git blobs** were verified; no
source mismatch was found. The CI source artifact is a synthetic test-merge
snapshot with the same tree as the audited main commit, not an assistant merge.
The original full suite completed with **1768 passed, 1 RAR-backend skip**, no
failures or errors. The 16 original-entry-point/manifest acceptance cases gave
15 failures and one compatibility pass on the baseline; the manifest-coverage
case asserts the new explicit bundle contract rather than a pre-existing API.
All 47 new cases pass on the final local candidate. The complete combined local
suite gave 1815 passes, one RAR skip and no failures/errors. A subsequent
Windows-specific test refinement was rerun in the focused suite and is also
subject to the final native CI matrix. JUnit, exact published-head comparison
and final CI results are retained separately in the delivery evidence; do not
reuse an old SHA's green result for a new commit.

Tests: `test_installer_safety.py` exercises real Bash/PowerShell entry points;
`test_installer_transactions.py` covers staging, promotion, recovery and ownership
with deterministic faults and actual subprocess exits. The normal matrix runs
them on its native platforms. New-helper tests are not claimed to fail against
a helper that did not previously exist; baseline before/after comparisons use
entry-point tests separately. No skipped/xfail assertion conceals an accepted
repair. A deliberately duplicated archive-member fixture emits the existing
warning. Live model quality and private owner-machine hooks are separate gates.

CI now explicitly provisions Python in its installer job and includes `install`
in recursive Ruff discovery. Keep the existing runtime OS/Python matrix, literal
dependency floors, real archive checks, shaping coverage, source evidence,
CodeQL, dependency review and strict skip inventory. No pip dependency was added.
The intentional zero pip version-update PR limit is not evidence that Dependabot
security updates are disabled; preserve existing coverage/grouping and inspect
administrative settings before alleging a defect.

Underlying validation commands, with the owner's guarded wrapper where required:

```powershell
python -m pytest tests/test_installer_safety.py tests/test_installer_transactions.py -q --timeout=90
python -m pytest tests -q -rs --timeout=300 --junitxml=junit-review.xml
python tests/e2e_pipeline.py
python -m ruff check skills/revayat-comic/scripts tests evaluation .github install
git diff --check
```

Set `REVAYAT_TEST_FONT` exactly as `tests/README.md` requires for that machine.
Validate the installed self-contained CLI, not only source-tree imports. No font
file is supplied in the owner-facing package.

## Research and optional improvements

**Research the repository and current primary documentation, especially relevant
GitHub projects, before further edits. Record access date, version/commit where
applicable, mechanism, alternatives and accept/defer/reject rationale in the
location/format specified by the owner's Rules.** This round chose shared
transaction logic rather than maintaining two destructive platform variants.
See `docs/research/round13-installation.md` and its source links.

Optional translation improvements remain separate from these installer fixes:
retain the current source-first → Persian-only fluency → source comparison route;
expand bilingual-reviewed paired-scene tests for referents, negation, modality
and register. Keep multiple acceptable Persian renderings and separate human
fidelity/voice ratings from typography/layout scores. Never shorten by dropping
meaning or turn a context-dependent phrase into a universal glossary rule.
Evaluate upstream glossary/context strategies on licensed representative pages
before changing providers; no live model-quality improvement is claimed here.
GPU-backed specialists should remain optional and measured, not invoked merely
to copy files or run deterministic bookkeeping.

## One-session review and disposition of all PRs

Inventory **all repository PRs** and apply the owner's actual PR Rules to every
one; do not exempt a PR merely by labeling it unrelated. Keep one closure ledger:
finding → specification/plan → code → before/after test → final SHA → checks →
integration/disposition. Preserve already integrated fixes and concurrent work.

Reproduce and fix any additional genuine bug encountered in the same review
session, add a regression, and revalidate the combination. Do not leave accepted
code work as a next-round placeholder. If a failure repeats unchanged, inspect
its failed invariant instead of blindly retrying commands. Report a genuinely
unavailable external prerequisite rather than fabricating its completion.

After Rules, Spec Kit, hooks, approved commit identities and final-SHA CI pass,
the authorized reviewer commits and pushes with the required email and merges
approved directly mergeable PRs. Otherwise manually integrate the equivalent
verified functionality, identify its commit, then close superseded PRs under the
Rules. **Every PR must reach its Rules-defined merged/closed DONE disposition;
closing an accepted unfixed repair is not completion.** Check the integrated
default branch and raw author/committer emails afterward. The authoring assistant
performs no merge, closure, auto-merge or shared-history rewrite.
