# CLAUDE.md

Read `AGENTS.md` — it is the full guide for working on this repository and
applies unchanged here.

Three Claude-specific notes:

- **Using the skill**: it activates by the `name:` in
  `skills/revayat-comic/SKILL.md`, which is `revayat-comic` — not the folder
  name.
- **Inside a plugin**, `{SKILL_DIR}` in `SKILL.md` resolves to
  `${CLAUDE_PLUGIN_ROOT}/skills/revayat-comic`.
- **Step 5 of the skill is yours, not a script's.** Read the rendered
  `overview.png` and `sheet*.png` with the Read tool before writing a
  worksheet. Sub-agents work well here — one page each, about six at a time —
  and each one needs both image paths in its prompt.

When changing `SKILL.md`, keep every front-matter field on a single line.
Several agents parse it with a line-oriented reader, and CI checks it.
