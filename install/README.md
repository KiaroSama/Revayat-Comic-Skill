# Install, upgrade and recover

The Bash and PowerShell entry points use one standard-library Python bootstrap.
**Python 3.10 or newer must be available before installation**, not only before
running the translation pipeline. Use a maintained interpreter where possible;
3.10 is retained as the project's tested compatibility floor. No third-party
package, network access, model or GPU is needed to copy the skill. The ordinary
pipeline dependencies are still installed separately from `requirements.txt`.

## Native entry points

PowerShell 7, from the repository root:

```powershell
$env:REVAYAT_PYTHON = 'G:\Program Files\Python\python.exe'
.\install\install.ps1 -Agent codex -Scope project -Path 'G:\Program Files\Portable\Scripts\my-comic' -Force
```

The example interpreter is a placeholder for an existing installation; the
installer does not download or install Python. Omit `REVAYAT_PYTHON` to discover
`python`/`python3` on PATH. POSIX equivalent:

```bash
bash install/install.sh --agent codex --scope project --path /path/to/project --force
```

The selected project directory must already exist. User scope (the default)
uses the current user's home. All eight existing layouts are supported: Claude,
Kiro, Codex, Cursor, Cline, Hermes, OpenCode and Antigravity. `all` considers only
agent configuration roots already present at the selected scope; naming an
agent explicitly creates its missing skill directory. OpenCode keeps its
`.config/opencode` user layout and `.opencode` project layout.

**An unattended update never treats missing input as consent.** Replacing an
existing skill requires `--force` / `-Force`, or an explicit affirmative answer
on an interactive terminal. Refusing every replacement exits unsuccessfully
rather than claiming an update was performed. First-time installation does not
need replacement consent. Force does not bypass source validation, ownership
checks or a pending recovery journal.

## What is preserved

`skill-files.txt` is the exact tracked distribution payload. Only those files
are copied; local virtual environments, diagnostic logs, reading copies and
other untracked files under the source skill are not propagated. The suite checks
this manifest against Git so that a new tracked helper cannot silently disappear
from installations. Update the manifest when adding/removing a tracked skill file.

Candidates are completely prepared and hashed before any active destination is
changed. Existing installations are renamed to backups, preserving operator
files and local customizations rather than deleting them. Successful upgrades
leave those backups for inspection; customizations are **not automatically merged
into the new active version**. Compare and reapply intentional changes explicitly.

State lives inside `.revayat-comic-installer` under the selected home/project:
`staging/`, `backups/`, `history/`, a live `lock.json` and (only during incomplete
publication) `pending.json`. Backups/staged copies are outside native skill
folders, so their `SKILL.md` files cannot be discovered as duplicate active skills.
Retention is intentional. Archive/remove old backups only after reviewing them;
never delete pending recovery evidence or a live/unknown owner's lock.

OpenCode and Antigravity retain the compatibility pointer in `AGENTS.md`.
OpenCode also supports native SKILL.md discovery. An update changes only the
single balanced Revayat marker block, preserves outside bytes and line endings,
and retains pointers to both existing compatible installations when updating
only one. Unbalanced/repeated markers cause refusal; the installer never guesses
which surrounding owner instructions are disposable. The old predictable
`AGENTS.md.revayat-comic.tmp` filename is not used.

## Interruption and recovery

A normal retry refuses an unfinished transaction. After the previous local
installer process has ended, request recovery for **the same scope/base**:

```powershell
.\install\install.ps1 -Scope project -Path 'G:\Program Files\Portable\Scripts\my-comic' -Recover
```

```bash
bash install/install.sh --scope project --path /path/to/project --recover
```

Recovery is a separate operation; rerun the intended installation after it
finishes. A prepared transaction restores its prior complete destinations. A
committed transaction verifies the installed state and retained backups before
finishing its history record. A partially completed rollback is resumable.
Uncommitted staging left before a journal was published is retained and reported;
it never replaced an active skill.

Live/unknown owners, malformed records, links/junctions in artifact paths,
missing backups, or concurrent edits are reasons to **stop and preserve evidence**.
Do not repeatedly force installation or remove a lock to hide those conditions.
Inspect the reported paths and reconcile with the operator. Symlinks/junctions
are refused conservatively, and promotion requires the transaction storage and
destination parent to share a filesystem. Hard-linked instruction files are
updated by replacing the selected name, not writing through another link.

This is recovery from process interruption and detected cooperative edits, not
a guarantee against hostile same-user races, arbitrary disk corruption or every
power-loss/filesystem behavior. Empty parent directories can remain after a
failed preparation; previously active files and owner instructions are the
preservation invariant.

## Diagnostics and validation

`REVAYAT_LOG_LEVEL` selects INFO, WARNING, ERROR or DEBUG. Diagnostics on stderr
carry timestamps, severity and the installer category. No credential is needed
or recorded. Use shell redirection to retain diagnostics when needed; this does
not replace the translation activity log required beside translated output.

After installation, run the installed copy's `scripts/revayat-comic.py doctor`,
then perform a normal pipeline smoke test. The repository tests exercise native
entry points, fault injection, real killed-process recovery and payload integrity.
