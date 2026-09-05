---
description: Run the quality gate over a Revayat Comic working folder and explain what it found.
argument-hint: [path to comic.json, default work/comic.json]
allowed-tools: Read, Bash, Glob, Grep
---

Run the `revayat-comic` quality gate over **$ARGUMENTS** (default
`work/comic.json`) and tell me what it found.

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py qa check --doc <document>
```

Report, in this order:

1. **`artwork-modified`, if present.** This is the one that matters: pixels
   outside the authorised mask differ from the original page. Name the pages and
   say plainly that they must not ship.
2. Every other error, grouped by code, with the page or region it belongs to and
   the action from `SKILL.md`'s table.
3. Warnings, briefly. Say which ones you would act on and which are expected —
   `sfx-untranslated` under the `keep` policy is expected.
4. The stats line: pages, regions, translated, typeset, and
   `artwork_pixels_changed`.

If a package has already been exported, verify it too:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py qa package --doc <document> --file <package>
```

Do not fix anything unless I ask. This is a report.
