---
description: Pick up a half-finished Revayat Comic chapter and carry on from wherever it stopped.
argument-hint: [path to comic.json, default work/comic.json]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task, Agent
---

Resume the `revayat-comic` chapter at **$ARGUMENTS** (default
`work/comic.json`).

Work out where it stopped rather than starting again. `comic.json` records which
stages have run under `stages`, and these two commands say what is left:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py worksheet status --doc <document>
$PY $SKILL_DIR/scripts/revayat-comic.py qa check --doc <document>
```

Then continue from the first step in `SKILL.md` that has not been done. Re-running
a completed stage is safe — every one of them is idempotent — but translating a
page twice is wasted work, so use `worksheet status` to see which pages already
have a `.done.txt`.

Two things to watch for:

- **`refused: stale-worksheets`, or `stale_worksheets` in a merge report.**
  Regions moved after those pages were translated, so their ids no longer point
  at the same balloons. Re-translate those pages. Do not pass `--force` unless
  you have checked that the regions really did not move.
- **`overflow` from a previous typeset run.** Those translations are too long
  for their balloons. Shorten them in the worksheet, then re-run merge, falint
  and typeset.

Tell me where it had got to before you carry on.
