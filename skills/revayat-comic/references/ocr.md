# Reading the text

Why there is no OCR engine in the default pipeline, and when to add one.

## The reader is the OCR

`crops` renders two images per page: the whole page with every region numbered,
and the crops enlarged and labelled. The agent running this skill reads them.

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
- Fill in `src:` even though nothing downstream requires it. It is how the
  glossary finds recurring names, it is what `glossary check` compares against,
  and it is what makes a mistake reviewable later.
- If a crop is genuinely unreadable, say so in `note:` and leave `fa:` empty.
  QA will report it. That is a better outcome than a plausible invention.
- Vertical Japanese reads top to bottom, right column first. The worksheet says
  which orientation the detector measured.

## When to add manga-ocr

`manga-ocr` is a specialist Japanese manga recogniser and it is genuinely good
at exactly this. It is **optional** and not installed by default, because it
pulls in torch and downloads about 400 MB of model on first use — a large cost
for something the reader is already doing.

Add it when:

- you are processing a long series unattended and want a deterministic
  cross-check against the reader's transcription
- the scan quality is poor enough that a second opinion is worth having
- you want a reproducible `src:` field that does not depend on which model ran

```bash
pip install manga-ocr
```

```python
from manga_ocr import MangaOcr
from PIL import Image

mocr = MangaOcr()
text = mocr(Image.open("work/crops/p0001/r001.png"))
```

`doctor` reports whether it is installed. Nothing in the pipeline calls it
automatically; use it to *check* a transcription, not to replace reading the
page. Where the two disagree, look at the crop and decide — a high-confidence
OCR result is not automatically right about a stylised balloon, and a reader who
skimmed is not automatically right either.

## Other engines

| Engine | Good for | Note |
| --- | --- | --- |
| `manga-ocr` | Japanese manga, vertical, furigana | the specialist; heavy |
| PaddleOCR | Chinese, Korean, English | general; needs a text detector in front of it |
| Tesseract | Latin scripts | poor on vertical CJK and on artwork |

None of them are wired in. The region boxes and crops this pipeline produces are
exactly what such an engine needs as input, so wiring one in is a short script
against `comic.json` rather than a change to the pipeline — every region carries
its `bbox`, its `orientation` and its page image path.

## What never to do

- Never write a transcription you did not read. An invented `src:` is worse than
  an empty one: it is wrong and it looks fine.
- Never leave source-script characters inside `fa:`. QA reports it as
  `source-script-left` and it is an error, not a warning.
- Never translate the `src:` field. It is the original, and it is what makes the
  work reviewable.
