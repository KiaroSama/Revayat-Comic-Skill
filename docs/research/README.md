# Research incorporated into Revayat

Research window: 2026-09-14, 20:43-21:15 UTC (2026-09-15 in Tehran).
Internet and GitHub searches covered each requested source language separately,
followed by code, language-routing, license and primary grammar inspection.

| Scope | Detailed evidence | Incorporated here |
| --- | --- | --- |
| Japanese, Korean, Chinese to Persian | [East Asian research](east-asian-persian.md) | Original language profiles, ruby/spacing/relationship checks, direct Persian translation and bounded context |
| French and Spanish to Persian | [Romance-language research](romance-persian.md) | Address/locale/modality/negation checks, semantic review and additional contextual evaluation cases |
| Comparable translation skills | Notes above; [translation-agent](https://github.com/andrewyng/translation-agent/tree/e0fc605acbb5d78cb7a58a98bc8bd8f0056df49c), [scientific Persian skill](https://github.com/isArman/scientific-fa-translation-skill/tree/eaded241eb109f3060a7ab7f73a1629cca3f3f07) | Targeted accuracy/fluency/voice/term review, not compulsory model calls or academic prose |
| Round-six GitHub skill comparison | [Comic and image-translation skills](round6-github-skills.md) | Ground implied subjects and irony in the panel exchange; add two original human-review cases without external image uploads |
| Page geometry and restoration | Primary references below | PDF point-size preservation independent of raster size, enhancement provenance and quality inspection |

The active skill loads `references/source-languages.md`; the optional machine
path receives `scripts/languages.py` through `context.build`. The translation
policy retains full meaning before layout. The evaluation set includes original
context-sensitive cases, with semantic/voice axes reserved for human review.

## Additional quality and logging references

[PyMuPDF Page documentation](https://pymupdf.readthedocs.io/en/latest/page.html)
separates page geometry, image placement and rasterization. Export previously
used image pixels as PDF points. The new import/export contract retains visible
paper dimensions and validates delivered appearance at raster density rather
than reducing a high-resolution scan to a 72-DPI proof.

[Real-ESRGAN's official implementation](https://github.com/xinntao/Real-ESRGAN)
and [its research paper](https://arxiv.org/abs/2107.10833) were inspected as
restoration references. The upstream README notes additional resizing for
arbitrary output scales and possible tile inconsistencies in the portable
implementation. Revayat therefore requires native-scale visual comparison and
recorded enhancement settings; it does not install a model or claim upsampling
recovers the true original lettering. No weights or source were copied.

[Manga Translator UI settings](https://github.com/hgmzhn/manga-translator-ui/blob/main/doc/en/SETTINGS.md)
describe output-side diagnostic logs and restoring original dimensions after
upscaling. These are documentation claims, not an executed comparison. Revayat's
rule is stronger for this user's workflow: every using agent records its own
translation and correction decisions directly beside the delivered file.

A [public manga translation skill gist](https://gist.github.com/microaijp/c9991abd133e0e9cc372ac3caec9f5ee)
was also inspected. It suggests recording speaker decisions, but is Japanese
targeted and its example rewrites source meaning to fit inferred speakers;
that behavior is rejected. Its mandatory source-line-count matching, lossy
WebP defaults and external rendering endpoint are not adopted. No explicit
license was visible in the inspected gist, so no code or prompt was copied.

## Boundaries

These changes are original adaptations, not vendored upstream implementations.
The notes pin commits where code capability is claimed, state licenses and
separate a real `fa` route from Arabic or a translated UI. No paid translation
endpoint, new OCR model or upscaler was run. No reviewed public comic-to-Persian
benchmark was found in this bounded search; that is not proof none exists.
The mechanical tests cannot certify bilingual accuracy or literary quality.
