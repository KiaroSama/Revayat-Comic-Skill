# Round-six GitHub skill review

Reviewed 2026-09-24 for the user-requested extension of Revayat Comic. These
repositories provide comparison evidence, not authority over source pages or
the project's existing preservation and Persian-translation contracts.

| Source inspected | Useful observation | Decision in Revayat Comic |
| --- | --- | --- |
| [manga-translate-skill](https://github.com/fenghengzhi/manga-translate-skill/blob/main/plugins/translate-manga/skills/translate-manga/SKILL.md) | Numbered source/output pages, immutable originals, count/dimension and visual checks | Existing source hashes and package QA already cover identity and dimensions. Preserve its useful visual-review reminder; do not use whole-page image generation because masked-pixel preservation must remain provable. |
| [TranslateImage skill](https://github.com/translateimage/translate-image-skills/blob/main/skills/translate-image/SKILL.md) | Source URL is fetched only when the user supplied it | Preserve the same provenance caution for external material. Do not add its hosted image-upload workflow or API key to the default local comic path. |
| [manga-translator-ui](https://github.com/hgmzhn/manga-translator-ui/blob/main/doc/en/FEATURES.md) | Multi-page flow and glossary extraction help names stay consistent | Use Revayat's approved glossary and bounded chapter context; keep suggestions distinct from decisions. |
| [mnga-tr](https://github.com/mugenyume/mnga-tr) | Whole-page text and optional image context avoid translating isolated bubbles | Require full panel exchange plus nearby accepted dialogue before resolving an implied subject or irony. |
| [COLING 2025 manga translation study](https://aclanthology.org/2025.coling-main.232/) | Visual context affects translation decisions | Add original scene-dependent French irony and Spanish referent examples. Both remain human-review cases; a string score cannot certify them. |

The prior [multilingual research](README.md) already covers direct
Japanese, Korean, Chinese, French and Spanish into Persian. Its 32-case
evaluation already tests necessity versus prohibition, indirect replies and
omitted subjects, so this round adds two distinct context cases instead of
repeating those contrasts. No third-party code, prompt, corpus, model, page
asset, token or secret was copied or installed.
