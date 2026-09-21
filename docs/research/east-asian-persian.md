# Japanese, Chinese and Korean comics into Persian

Research snapshot: 2026-09-14 UTC. This note separates source-code evidence of
Persian support from techniques evaluated in other language pairs. Repositories,
licenses, prompts, OCR routing and context code were inspected through GitHub;
official language references were checked separately. No upstream application,
model, paid endpoint or translation benchmark was run for this research. The
Persian examples below are original proposed evaluation cases, not measured results.

## Practical conclusion

Keep direct source-to-Persian translation as the task, with the current page and
its ordered regions visible. Use surrounding pages only to answer a concrete
ambiguity. Preserve names, addressees, negation, modality and intentional emphasis
before shortening anything. Natural spoken Persian is appropriate for ordinary
dialogue; narration, ceremonial speech and documents need their own register.

This is an adaptation recommendation, not proof that one model or prompt is best.
The most relevant controlled manga study evaluated Japanese-to-English and
Japanese-to-Polish. Its page-plus-image methods performed strongly, while larger
context was not consistently better; its human assessment still found critical
errors. It did not evaluate Persian, Chinese-to-Persian or Korean-to-Persian.
[Lippmann et al., methodology, results and limitations](https://arxiv.org/html/2411.02589v1).

## What actually supports Persian

| Project and inspected commit | Direct evidence | Reuse decision |
| --- | --- | --- |
| amirwolf5122/Manga-AutoTranslate — fbf56b674fb0d301058ec9d264c8d8d65eb495d8 | Persian-first translation prompt; ja, ko and zh map to PaddleOCR's language names. [Translation and OCR code](https://github.com/amirwolf5122/Manga-AutoTranslate/blob/fbf56b674fb0d301058ec9d264c8d8d65eb495d8/manga.py#L5), [language routing](https://github.com/amirwolf5122/Manga-AutoTranslate/blob/fbf56b674fb0d301058ec9d264c8d8d65eb495d8/manga.py#L1669), [MIT license](https://github.com/amirwolf5122/Manga-AutoTranslate/blob/fbf56b674fb0d301058ec9d264c8d8d65eb495d8/LICENSE). | Useful Persian register, name-glossary and bounded-context ideas. Rewrite the guidance for this project; do not import the script or its assets. |
| ogkalu2/comic-translate — 8977b91a4f7a40c3917c5a268e9e7d78e1d818da | The target catalog includes Persian; language utilities map it to fa and RTL. Japanese, Chinese and Korean source routes exist. [Catalog](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/app/catalog.py), [language utilities](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/modules/utils/language_utils.py), [OCR factory](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/modules/ocr/factory.py), [Apache-2.0 license](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/LICENSE). | Strong reference for separating source OCR from target rendering and translating page text with an optional image. Target support does not establish Persian translation quality. |
| SethRobinson/UGTLive — f647679dcc384aba2ed9178172d227db8e79effd | fa is a selectable language and maps to Persian/Farsi in the translation service; previous original text can be provided as context. [Settings](https://github.com/SethRobinson/UGTLive/blob/f647679dcc384aba2ed9178172d227db8e79effd/src/SettingsWindow.xaml.cs), [service mapping](https://github.com/SethRobinson/UGTLive/blob/f647679dcc384aba2ed9178172d227db8e79effd/src/GoogleTranslateService.cs), [context flow](https://github.com/SethRobinson/UGTLive/blob/f647679dcc384aba2ed9178172d227db8e79effd/src/Logic.Translation.cs). | Comparison source for recent-context handling. Its [custom Proton SDK license](https://github.com/SethRobinson/UGTLive/blob/f647679dcc384aba2ed9178172d227db8e79effd/LICENSE.md) requires attribution and limits its coverage to project-created material; no code is copied here. |

The first project's prompt explicitly addresses Iranian conversational Persian,
formal speakers, names and uncertain speakers. Its batch format distinguishes
items to translate from context-only items; its chapter brief is based on a
bounded sample, not knowledge of an unseen whole chapter.
[Batch request](https://github.com/amirwolf5122/Manga-AutoTranslate/blob/fbf56b674fb0d301058ec9d264c8d8d65eb495d8/manga.py#L4437), [brief and glossary](https://github.com/amirwolf5122/Manga-AutoTranslate/blob/fbf56b674fb0d301058ec9d264c8d8d65eb495d8/manga.py#L4246).

Do not inherit its length-first instruction, blanket removal of diacritics,
blanket exclusion of Latin text, or automatic reconstruction of censored words.
These are poor fits for faithful translation, ezafe, acronyms, URLs and deliberate
censorship. Its RapidOCR wrapper stores the requested language but constructs
the underlying engine without passing that language, so fallback CJK coverage
must be measured rather than inferred from the log label.
[Prompt and output constraints](https://github.com/amirwolf5122/Manga-AutoTranslate/blob/fbf56b674fb0d301058ec9d264c8d8d65eb495d8/manga.py#L5),
[RapidOCR wrapper](https://github.com/amirwolf5122/Manga-AutoTranslate/blob/fbf56b674fb0d301058ec9d264c8d8d65eb495d8/manga.py#L1049).

Comic Translate sends a page's text blocks, extra context and optionally its image
to an LLM. Its generic prompt attends to formality and slang, but also contains a
blanket ban on certain Korean/Japanese pronouns. For Persian, retain contrastive
pronouns when they carry meaning; avoid turning a target-language style preference
into a universal deletion rule.
[Request assembly](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/modules/translation/llm/base.py),
[generic prompt](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/modules/translation/base.py).

### Search scope and rejected leads

Japanese, Chinese and Korean were searched separately with Persian/Farsi terms,
including “ترجمه مانگا ژاپنی فارسی”, “ترجمه مانها چینی فارسی” and
“ترجمه مانهوا کره ای فارسی”; GitHub README searches were followed by source inspection.
Language-list hits, reader apps and download collections were not treated as
translation implementations.

Kthree-K3/K3-Manga-AutoTranslate at 952ae3700b9a68291bd3c01a1335e8258ab150ae
and Kthree-K3/K3-Manga-Translator-Editor-edition at
542bb83ece9d54367d6eb9f2aa5210ca772ab795 describe Persian-oriented products.
Their inspected root trees contained documentation and images, not an inspectable
translation implementation or root license. They are product leads, not source-reuse
recommendations. [AutoTranslate tree](https://github.com/Kthree-K3/K3-Manga-AutoTranslate/tree/952ae3700b9a68291bd3c01a1335e8258ab150ae),
[Editor tree](https://github.com/Kthree-K3/K3-Manga-Translator-Editor-edition/tree/542bb83ece9d54367d6eb9f2aa5210ca772ab795).

## Source-specific reading and translation

### Japanese: vertical text, ruby and unstated participants

Manga OCR is a Japanese recognizer, not a translator. It is designed for vertical
and horizontal manga text, including furigana, and can read a multiline balloon.
Its own documentation warns that long crops are harder, handwriting is unreliable,
and text-free images can produce invented sentences. Its decoder uses a 300-token
maximum; postprocessing removes whitespace. Keep an uncertain crop visible and
do not treat its flattened string as a page-order or ruby-alignment record.
[README](https://github.com/kha-white/manga-ocr/blob/c333b5d36e88d539d6b040b4c4cf90ad5ecd4f69/README.md), [recognition and postprocessing](https://github.com/kha-white/manga-ocr/blob/c333b5d36e88d539d6b040b4c4cf90ad5ecd4f69/manga_ocr/ocr.py).

Ruby is not always redundant pronunciation: Japanese layout guidance documents
both readings and meaning-bearing annotations. For an unusual name or fantasy
term, inspect both the base characters and ruby; record the chosen reading and
Persian spelling. Do not silently discard a second meaning.
[W3C Japanese layout, ruby purposes](https://www.w3.org/TR/jlreq/#ruby_and_emphasis_dots).

Respect and reference are separate questions. The Japan Foundation explains that
Japanese often uses names with -san instead of an explicit second-person pronoun,
and -san is used for women and men. Consequently, -san alone cannot justify
inventing “Mr.” or “Mrs.” in Persian. Decide Persian address from the speaker,
addressee and scene; retain an established honorific policy consistently.
[Japan Foundation grammar notes, introductory lesson 3](https://www.irodori.jpf.go.jp/assets/data/Grammar_all.pdf).

Suggested reading pass: identify balloon order and speaker; transcribe the main
text; inspect small ruby and voicing marks; resolve omitted participants from
visible evidence; translate; check negation and speech register against the crop.
A dialect should not automatically become an unrelated Iranian regional dialect.
For example, Kansai negative and honorific forms are documented as distinct
grammatical signals, not decorative spelling.
[Japan Foundation, dialect notes](https://www.irodori.jpf.go.jp/assets/data/pre-intermediate/pdf/ZZ_L09.pdf).

### Chinese: script variants, segmentation and names

Chinese text can be horizontal or vertical; vertical composition orders characters
top-to-bottom and lines right-to-left. Traditional/Simplified script and writing
direction are independent properties. Keep source characters intact until the
reader has established names and segmentation; do not use script conversion to
guess a proper name.
[W3C Chinese layout, writing modes](https://www.w3.org/TR/clreq/#writing_modes).

The inspected PaddleOCR code contains separate model-version/language routing.
At this commit, unspecified Chinese/Japanese uses the v6 route, while Korean
uses v5; selecting v5 explicitly routes Chinese/Japanese to its shared server
recognizer and Korean to its own recognizer. This is why “PaddleOCR supports CJK”
is insufficient configuration evidence.
[Routing implementation](https://github.com/PaddlePaddle/PaddleOCR/blob/2661c7c0ef5c613e8f93c6e93b2e052399f0f854/paddleocr/_pipelines/ocr.py#L330).
The versioned v5 documentation specifically describes Chinese, Traditional
Chinese, Japanese, vertical text and uncommon characters; it is not a Persian
translation-quality claim.
[PP-OCRv5 documentation](https://paddlepaddle.github.io/PaddleOCR/v3.0.0/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html).

Treat a Han-only crop as ambiguous without chapter-language evidence: it may be
Chinese text, Japanese kanji, or a Korean name/title written in Hanja. Preserve
source-script names and their approved readings in the glossary. A title such as
a sect rank needs the work's established Persian convention, not a fresh literal
translation in each balloon. These are proposed safeguards, not a validated
automatic named-entity algorithm.

### Korean: Hangul, spacing and relationships

Pororo's OCR factory explicitly exposes English and Korean with the brainocr
model. It is not evidence for Japanese, Chinese or Persian OCR. Its upstream
code snapshot is older than the other inspected projects; Comic Translate uses
an ONNX adaptation with bounded-height recognition crops.
[Pororo OCR factory](https://github.com/kakaobrain/pororo/blob/7d05a75e8062b00e6b65364b8ec6c52b6293ab07/pororo/tasks/optical_character_recognition.py),
[ONNX recognition path](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/modules/ocr/pororo/onnx_engine.py).

Hangul contains both precomposed syllables and jamo code ranges. A source validator
that recognizes only precomposed syllables can miss isolated jamo used in effects
or informal writing. Keep meaningful Korean word boundaries and inspect small
syllable components; do not apply Japanese whitespace-stripping as a universal
CJK cleanup. These adaptations follow the script structure, not a measured OCR
improvement in this research.
[W3C Hangul encoding and shaping](https://www.w3.org/TR/klreq/).

Record who addresses whom before choosing تو or شما. Kinship terms can also be
used socially: the official dictionary distinguishes a woman's older sister
from an older woman she addresses affectionately with 언니. Do not infer a
biological relationship from the word alone.
[National Institute of Korean Language, 언니](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=31971&nation=eng).

For names, preserve an established spelling instead of repeatedly regenerating
one from English romanization. The official Korean romanization guidance places
the family name before the given name and allows established personal-name
spellings. It is a reading aid, not a Persian transliteration standard.
[National Institute of Korean Language, romanization](https://www.korean.go.kr/front_eng/roman/roman_01.do).

## Context and terminology ideas worth adapting

BallonsTranslator at 84ba500ea1a4f523ca79f1c77d8c642eea3d1d07 has an
inspectable exact-ID output contract, glossary constraints, immutable request
context, optional page summaries and image context. Its prior page IDs remain
local to those pages. The LLM language map inspected here does **not** include
Persian; a fa entry elsewhere in generic service constants does not prove that
this LLM path supports Persian.
[Contract and assembly](https://github.com/dmMaze/BallonsTranslator/blob/84ba500ea1a4f523ca79f1c77d8c642eea3d1d07/ballontranslator/modules/translators/llm_translation_contract.py),
[language map and context snapshot](https://github.com/dmMaze/BallonsTranslator/blob/84ba500ea1a4f523ca79f1c77d8c642eea3d1d07/ballontranslator/modules/translators/trans_llm.py#L138),
[GPL-3.0 license](https://github.com/dmMaze/BallonsTranslator/blob/84ba500ea1a4f523ca79f1c77d8c642eea3d1d07/LICENSE).

The research implementation at a3b6b530f55105fa04f8a61d8aed99124e50919e
provides page, rolling-summary and neighboring-page variants under MIT. Its
older bracket-based response parsing is not a reason to replace Revayat's
validated worksheet protocol. Adapt the experimental comparison, not the parser
or historical model pins.
[Implementation](https://github.com/PLippmann/multimodal-manga-translation/blob/a3b6b530f55105fa04f8a61d8aed99124e50919e/translation.py), [MIT license](https://github.com/PLippmann/multimodal-manga-translation/blob/a3b6b530f55105fa04f8a61d8aed99124e50919e/LICENSE).

Recommended original adaptation:

1. Give the reader the current page, stable region IDs and ordered source text.
2. Add only verified name spellings, known speaker/addressee relationships and
   immediately relevant preceding context. Mark uncertain facts explicitly.
3. Translate connected balloons together for interpretation, while returning
   each result under its own original ID. Do not move text between IDs.
4. Preserve full meaning and voice; attempt layout changes before proposing
   compression. A changed full/displayed pair needs renewed review.
5. Evaluate adequacy, naturalness, register, terminology and reading order
   separately. A valid JSON/worksheet or matching image hash is not a linguistic
   quality score.

## Original contrast cases for Persian evaluation

These short examples were written for this note. The scene is part of each case;
the Persian is one acceptable proposal, not the only correct wording. They have
not been validated by an independent bilingual human or run through a model.

The Japanese no-obligation construction is documented by the Japan Foundation;
Mandarin 不必 expresses lack of necessity, while 不准 expresses prohibition.
Korean 되다 permits an action/state, including a negated action, while -지 말다
prohibits the action. Preserve those distinctions before judging fluency.
[Japanese grammar, lesson 8, page 23](https://www.irodori.jpf.go.jp/assets/data/pre-intermediate/pdf/ZZ_L08.pdf#page=23),
[Japanese prohibition and casual contractions, lesson 10](https://www.irodori.jpf.go.jp/assets/data/elementary02/pdf/Z_L10.pdf),
[Mandarin 不必](https://dict.revised.moe.edu.tw/dictView.jsp?ID=20100&la=1&powerMode=0),
[Mandarin 不准](https://dict.revised.moe.edu.tw/dictView.jsp?ID=21339&la=1&powerMode=0),
[Korean 되다, sense 20](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=89858&nation=eng&nationCode=6),
[Korean -지, negation/prohibition](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=78636).

| Japanese source | Scene | Proposed Persian | Distinction to preserve |
| --- | --- | --- | --- |
| 行かなくてもいいよ。 | Friend releases an obligation. | لازم نیست بری. | Lack of obligation, not a ban. |
| 行っちゃだめ。 | Friend urgently forbids leaving. | نباید بری. | Prohibition, not optional attendance. |
| 壊したのは僕じゃない。 / 彼だよ。 | Two linked balloons about a broken cup. | من نشکستمش. / کار اون بود. | Contrastive participants; retain both IDs. |
| 先生、少し待ってください。 | Student addresses a teacher. | استاد، لطفاً کمی صبر کنید. | Respectful address; 先生 would need a different rendering for a doctor. |

| Chinese source | Scene | Proposed Persian | Distinction to preserve |
| --- | --- | --- | --- |
| 你不必去。 | Friend releases an obligation. | لازم نیست بری. | Not ممنوعه بری. |
| 你不准去。 | Speaker forbids the listener to leave. | حق نداری بری. | Prohibition is explicit. |
| 我说的是他。 / 不是你。 | Speaker corrects whom a remark concerns. | منظورم اون بود. / نه تو. | Do not drop the contrastive pronouns. |
| 您先请。 | Host invites an older guest through a doorway. | بفرمایید، اول شما. | Natural courtesy rather than word-for-word order. |

| Korean source | Scene | Proposed Persian | Distinction to preserve |
| --- | --- | --- | --- |
| 안 가도 돼요. | Politely releasing an adult's obligation. | لازم نیست برید. | Permission not to go, not a command to stay. |
| 가지 마세요. | Polite request that the listener stay. | لطفاً نرید. | Prohibition/request, not absence of obligation. |
| 제가 아니라 민수예요. | Answer to who spilled the ink; glossary fixes 민수 as مین‌سو. | من نبودم، مین‌سو بود. | Preserve the corrected identity and approved spelling. |
| 언니, 잠깐만! | A woman calls her confirmed older sister. | آبجی، یه لحظه! | Relationship is supplied by the scene; do not assume it in every use of 언니. |

For a held-out set, write new page/context pairs rather than scoring these same
examples after putting them into the prompt. Allow multiple Persian renderings,
but mark swapped participants, lost negation, invented obligation, changed names
and unapproved semantic compression as adequacy failures. Include a quiet scene,
an argument, formal dialogue, inner thought, stylized SFX and an ambiguous crop.

## Reuse and evidence limits

| Upstream | Inspected source license | Boundary |
| --- | --- | --- |
| Manga OCR | [Apache-2.0](https://github.com/kha-white/manga-ocr/blob/c333b5d36e88d539d6b040b4c4cf90ad5ecd4f69/LICENSE) | Japanese OCR only; no direct fa translation evidence. |
| PaddleOCR | [Apache-2.0](https://github.com/PaddlePaddle/PaddleOCR/blob/2661c7c0ef5c613e8f93c6e93b2e052399f0f854/LICENSE) | Language/model/version routing must be explicit; no manga-to-fa quality benchmark inspected. |
| Pororo | [Apache-2.0](https://github.com/kakaobrain/pororo/blob/7d05a75e8062b00e6b65364b8ec6c52b6293ab07/LICENSE) | Inspected OCR code supports en/ko; separately check any redistributed model artifacts. |
| OpenMantra | [CC-BY-NC-4.0](https://github.com/mantra-inc/open-mantra-dataset/blob/59341ad922284a8be219b7784feb5a79779a1447/LICENSE.md) | [Japanese originals with professional English/Chinese translations](https://github.com/mantra-inc/open-mantra-dataset/blob/59341ad922284a8be219b7784feb5a79779a1447/README.md); no Persian references. Do not treat its pages as unrestricted project fixtures. |

The scoped search did not locate an independent public manga benchmark with
verified Japanese/Chinese/Korean-to-Persian references. This is a search result,
not a claim that none exists. General multilingual model support is weaker
evidence: for example, NLLB's own model card describes sentence-level research use,
noncommercial licensing and limitations for document translation.
[NLLB-200 official model card](https://huggingface.co/facebook/nllb-200-distilled-600M).

No upstream prompts, source code, comic pages, fonts or model weights were copied
into this repository. Only this original research note was added. The immediate
useful change is guidance plus independently reviewed Persian contrast cases;
adding a new OCR engine or adopting an upstream prompt needs separate practical
evidence on the actual scans and selected model.
