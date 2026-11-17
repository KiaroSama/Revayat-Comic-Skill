# Voice review by output language

Choose the guide by **output language, not the source language**. Select a row
for each passage in mixed-language prose, without changing its quoted text.

| Output language | Local skill | Claude Code plugin key |
| --- | --- | --- |
| `fa` | [persian](persian/SKILL.md) | `revayat-comic:persian` |
| `en` | [humanizer](humanizer/SKILL.md) | `revayat-comic:humanizer` |
| `ru` | [great-russian](great-russian/SKILL.md) | `revayat-comic:great-russian` |

Load only the matching guide. If the host does not expose its plugin key, read
the linked `SKILL.md` and its relevant local references. If there is no matching guide,
review in the language requested using the ordinary workflow.
No download or system installation is needed.

The finished comic edition is Persian-only. Use `persian` for dialogue,
narration, captions and translated effects, including when reading English or
Russian originals. Use the other guides only for prose produced in their
language, such as an editorial note requested by the reader. Source
transcription is evidence and stays as read.

Use the guidance on drafts. Compare any revision with the source and keep the
meaning, cast voice, locked glossary, names, numbers, and emphasis. The existing
worksheet, approval, typography and fit rules still apply. Do not send a whole
worksheet, region IDs, protocol markers, or approved text through a rewriter or
normalizer. The comic's `falint` step stays in charge of committed Persian
mechanics. Style suggestions do not approve compression or replace bilingual
review.

## Upstream sources

- [Humanizer v4.0.0](https://github.com/blader/humanizer/tree/b48c832f0f809c1b5658edbb838c2521b72f2413), [MIT license](humanizer/LICENSE).
- [Great Russian](https://github.com/frolin/great-russian-skill/tree/c9ba8661768927c21b7ba5608e63dce832c568b5), [MIT license](great-russian/LICENSE).
- [Persian](https://github.com/Mojtaba-Alehosseini/persian-skill/tree/4264f6ef03f7568bc15b14287a3db09bc815fc31), [MIT license](persian/LICENSE) and [notice](persian/NOTICE).

These are pinned local copies. Humanizer's front matter uses single-line fields
for this project's loader checks; its instructions are unchanged. The Persian
guide omits the command for an upstream-only test. Upstream installers,
workflows and release tooling are not part of this package.
