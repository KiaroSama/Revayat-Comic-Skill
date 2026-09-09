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

`doctor` reports whether it is installed. Use it to *check* a transcription, not
to replace reading the page. Where the two disagree, look at the crop and decide
— a high-confidence OCR result is not automatically right about a stylised
balloon, and a reader who skimmed is not automatically right either.

## The `ocr` stage

There **is** now an executable path, and it is off by default:

```bash
revayat-comic.py ocr --doc work/comic.json --provider <name>
```

It exists for the narrow cases at the top of this file — a host with no vision,
a script the host reads poorly, or a page worth a second pair of eyes. It is not
part of the twelve-stage pipeline and nothing runs it for you.

What it will not do is the point of it:

| Situation | What happens |
| --- | --- |
| region is empty, engine is confident | the reading is written, with provenance |
| region is **locked** | the committed value is kept; the engine's reading is recorded as a disagreement and the region goes to review |
| confidence below `--min-confidence` (0.65) | **nothing is written**; a review note says how unsure it was |
| engine errors, times out or declines | recorded as a failed call; nothing is written; the run continues |
| the stage is run a second time | work it already finished is **not re-requested** — no call, no cost, no chance of a different answer replacing a good one |

`--vision <name>` adds an optional third opinion: a vision provider is shown the
crop and asked to comment on a *disagreement only*. It never writes to the
document; its answer becomes a review note. Everything above works with it
absent, which is the default.

Every outcome lands in `region["provenance"]` with the provider name, the
status, the confidence and a timestamp, so a later run can tell a machine's
guess from a person's decision. That record is what makes the `locked` rule
enforceable rather than aspirational.

**Resumable.** A locked or already-filled region is compared rather than
re-read, so interrupting the stage and running it again costs only the calls it
did not finish.

**A working `manga-ocr` adapter ships with the project.** It is in
`scripts/adapters.py`, it is not imported by the pipeline, and it loads the model
on first read rather than on construction — so registering it costs nothing:

```bash
pip install manga-ocr
revayat-comic ocr --doc work/comic.json --provider manga-ocr
```

It declines anything that is not Japanese rather than answering anyway, and
reports `MANGA_OCR_CONFIDENCE` (0.80) — a judgement about the model, since it
returns no score of its own.

Verified against the package's real call shape with a stub; **not** verified
against the actual 3 GB download on this machine. Writing your own is about
twenty lines — anything with a
`read(crop_path, language) -> (text, confidence)` method qualifies:

```python
import providers
from manga_ocr import MangaOcr

class MangaOcrProvider:
    name = "manga-ocr"
    def __init__(self):
        self._mocr = MangaOcr()
    def read(self, crop_path, language):
        from PIL import Image
        return self._mocr(Image.open(crop_path)), 0.9

providers.register("ocr", "manga-ocr", MangaOcrProvider)
```

Register a *factory*, not an instance: nothing should download 400 MB of model
because a module was imported.

**Optional: `orientation`.** Name a third parameter and the stage will pass the
writing direction the detector measured — `"vertical"` or `"horizontal"`:

```python
    def read(self, crop_path, language, orientation="horizontal"):
        ...
```

It is the one thing an engine reading a lone crop cannot recover, because a
vertical column with furigana beside it looks like two columns. Purely optional:
an engine that does not name the parameter is called exactly as shown above, so
no existing adapter has to change. `manga-ocr` finds the direction itself and
does not ask; PaddleOCR is the case that wants it.

## Other engines

| Engine | Good for | Note |
| --- | --- | --- |
| `manga-ocr` | Japanese manga, vertical, furigana | the specialist; heavy |
| PaddleOCR | Chinese, Korean, English | general; needs a text detector in front of it |
| Tesseract | Latin scripts | poor on vertical CJK and on artwork |

None of them ship with an adapter. The boundary above is what they plug into,
and the crops this pipeline already renders are exactly what they take as input,
so an adapter is the twenty lines shown above rather than a change to the
pipeline — every region carries its `bbox`, its `orientation` and its page image
path.

## What never to do

- Never write a transcription you did not read. An invented `src:` is worse than
  an empty one: it is wrong and it looks fine.
- Never leave source-script characters inside `fa:`. QA reports it as
  `source-script-left` and it is an error, not a warning.
- Never translate the `src:` field. It is the original, and it is what makes the
  work reviewable.
