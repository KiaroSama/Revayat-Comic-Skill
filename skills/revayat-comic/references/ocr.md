# Reading the text

Why there is no OCR engine in the default pipeline, and when to add one.

## The reader is the OCR

`crops` renders a numbered overview and one or more enlarged crop sheets for
each page. The agent running this skill reads them.

That is not a compromise. It is better than an OCR engine for this particular
job, for a reason that has nothing to do with model quality:

**An OCR engine reads a crop. You read a page.**

A crop of `やめろ` is unambiguous. A crop of `そうか` is not — it is `که این‌طور`
or `آها` or `پس این‌طور` depending on whether the character is realising
something, conceding a point, or being sarcastic, and the only way to know is
the face above the balloon. The pipeline that reads the crop in isolation cannot
have that, and no amount of accuracy on the characters fixes it.

The same applies to:

- **furigana** — small readings printed beside kanji. An OCR engine mixes them
  into the line; you can see they are furigana.
- **handwriting** — a margin note, an aside scrawled outside the balloon.
- **broken or stylised lettering** — a balloon drawn shaking.
- **who is speaking** — the tail of the balloon points at somebody.
- **a balloon that continues into the next one** — a sentence split across two
  balloons is one sentence, and only the page shows that.

So the transcription and the translation happen in one pass, with the page in
front of you, and both go into the worksheet.

## Doing it well

- Read `overview.png` first and the crops second. Understand the page, then read
  the text.
- Fill in `src:`. It is how the glossary finds recurring names, it is what
  `glossary check` compares against, and it makes a mistake reviewable later.
- If a crop is genuinely unreadable, say so in `note:` and leave `fa:` empty.
  QA will report it. That is a better outcome than a plausible invention.
- Vertical Japanese reads top to bottom, right column first. The worksheet says
  which orientation the detector measured.

## When to use an OCR cross-check

An independently read crop can help investigate a doubtful transcription or a
poor scan. Keep the page context in view and resolve disagreements from the
visible source. A second model's answer is review material, not proof that a
reading is correct. No OCR engine or model weights are installed by the default
pipeline.

## The `ocr` stage

There is an optional OpenAI-compatible OCR stage, off by default:

```bash
revayat-comic ocr --doc work/comic.json --provider openai --model MODEL
```

Use it to cross-check a transcription, never to replace visually reading the
crops (`overview.png` and `sheet*.png`). Where OCR and your eyes disagree,
look at the crop and decide. It is not part of the default pipeline and nothing
runs it automatically.

The current Rust command fills eligible empty source fields:

| Situation | What happens |
| --- | --- |
| unlocked, translatable region with empty `source_text` and a nonempty provider answer | stores the reading and adds `review-hosted-ocr` |
| locked region, existing source text, or a region kept/dropped/erased by policy | skips the region without a request |
| empty or declined answer | leaves the source field empty |
| transport, timeout, or invalid-response error | fails the operation; the document is not partially committed |
| a second run after source fields were filled | skips those filled fields; this is not a crop-content cache |

Set `REVAYAT_API_BASE` to the compatible API base, such as an HTTPS endpoint
ending in `/v1`. Supply `REVAYAT_API_KEY` when required. `--model` can be omitted
when `REVAYAT_OCR_MODEL` is set. A local endpoint can use loopback HTTP; a Bearer
key is never sent over cleartext HTTP to a non-loopback host. Redirects are
refused, so configure the canonical endpoint.

There is no confidence-threshold flag, locked-text disagreement pass, or second
vision-provider flag in this command. To compare OCR with a committed reading,
review the current crops separately and preserve the accepted text until a
human or reading agent resolves the difference. Do not clear accepted source
text just to force a request.

The request implementation is `rust/revayat-tools/src/providers.rs`; eligibility
and document writes are in `rust/revayat-comic-cli/src/providers.rs`. Python
adapter registration is not part of this runtime. Other OCR tools can consume
the exported crops as a separate review step; record their result and any
accepted correction in the worksheet and translation activity log.

## What never to do

- Never write a transcription you did not read. An invented `src:` is worse than
  an empty one: it is wrong and it looks fine.
- Never leave source-script characters inside `fa:`. QA reports it as
  `source-script-left` and it is an error, not a warning.
- Never translate the `src:` field. It is the original, and it is what makes the
  work reviewable.
