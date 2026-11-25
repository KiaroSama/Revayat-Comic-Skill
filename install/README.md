# Install, upgrade and recover

The skill installer copies files from a repository checkout. It needs the `revayat-comic` v2 CLI, `install/skill-files.txt`, and `skills/revayat-comic/`. Release ZIPs supply the standalone binary. The installer needs no network access.

## Native entry points

Run the script by absolute path if you are outside the checkout. Both scripts pass the checkout root as `--repo`. They use a built executable from the checkout or one on `PATH`; set `REVAYAT_BIN` to an executable path to override discovery.

```powershell
& 'C:\src\Revayat-Comic-Skill\install\install.ps1' -Agent codex -Scope project -Path 'C:\work\my comic'
```

```bash
bash /path/to/Revayat-Comic-Skill/install/install.sh --agent codex --base '/path/to/my comic'
```

You can also call the CLI directly:

```bash
revayat-comic install --repo /path/to/Revayat-Comic-Skill --agent codex --scope project --path '/path/to/my comic'
revayat-comic install --repo /path/to/Revayat-Comic-Skill --agent codex --scope user
```

The CLI accepts `--path` as an alias for `--base` and `--user-scope` in place of `--scope user`. With no scope flag, the CLI uses project layout. Project installs require an existing destination directory. User installs default to the home directory and accept an explicit base for a different target. PowerShell defaults to user scope; with `-Scope project` and no `-Path`, it uses the current directory.

Supported agents: `claude`, `kiro`, `codex`, `cursor`, `cline`, `hermes`, `opencode`, and `antigravity`. With `--agent all`, the installer only considers agent directories already present at the selected base. Name an agent to create a missing directory. OpenCode installs under `.config/opencode` with user scope and `.opencode` with project scope.

The installer never prompts before replacing files. Pass `--force` or `-Force` to replace an existing copy. `all` can still install into eligible destinations while leaving existing copies alone. If there is nothing to install, the command fails. Force does not bypass path validation or an unfinished transaction.

## What is preserved

The installer copies only the tracked payload listed in `skill-files.txt`. It stages and checks the new copy before replacing an active installation. Backups retain the previous files and any local customizations; reapply any changes you want to keep after comparing the copies.

The transaction state and backups live under `.revayat-comic-installer/` at the selected base, outside the agent's skill directory. OpenCode and Antigravity also use a marked block in `AGENTS.md`. The installer preserves surrounding owner text and refuses malformed or repeated blocks.

## Recovery

After the previous installer process has exited, use the same base and scope with `--recover` or `-Recover`:

```bash
bash /path/to/Revayat-Comic-Skill/install/install.sh --base '/path/to/my comic' --recover
```

This rolls back a prepared transaction or verifies and records a committed one. It does not start a new installation. Leave transaction records and backups in place if recovery reports changed files. Rerun the original install only after recovery succeeds.

## Verification

Run `revayat-comic doctor --json` and check for `"ok": true`. Confirm the installed `SKILL.md` is present at the reported destination. CLI logs go in `logs/` next to `bin/` or alongside a standalone executable in another directory. Review a log before sharing it.
