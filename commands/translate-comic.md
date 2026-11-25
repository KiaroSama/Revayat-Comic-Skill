---
description: Translate a manga, manhwa, manhua or comic chapter into Persian and produce a finished CBZ or PDF.
argument-hint: <chapter.cbz | chapter.pdf | folder of pages> [--source ja|ko|zh|en] [--sfx keep|translate|bilingual|annotate]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task, Agent, AskUserQuestion
---

Use the `revayat-comic` skill to translate this chapter into Persian: **$ARGUMENTS**

Follow `SKILL.md`, the 6-stage multi-agent workflow (`references/multi-agent-workflow.md`), and the full-page image-edit workflow (`references/fullpage-image-edit.md`) in order.

Two things decide whether the result is good, and both are yours rather than a
script's:

- **Step 5.** Look at `crops/pNNNN/overview.png` and `crops/pNNNN/sheet*.png`
  before writing a single line. The overview is the context — who is speaking,
  which balloon answers which, what the scene is. The sheets are what you read
  the text from. Then fill in the worksheet.
- **Step 11.** `export` runs the whole publication gate itself and refuses
  while `qa check` would report `"ok": false` — `--draft` ships what is there
  and marks the package a draft in its own `ComicInfo.xml`. In
  particular never ship a page flagged `artwork-modified`.

If the source language is not given, work it out from the first page and say
what you decided. Sound-effect policy defaults to `keep`.

When it is finished, tell me where the file is, how many pages and balloons it
has, which sound-effect policy ran, whether shaping used RAQM or the fallback,
and anything QA flagged that you chose not to act on.
