# Sound effects

Why they are treated separately from dialogue, and how to choose a policy.

## They are artwork

A speech balloon is a container with text in it. A sound effect is *drawn* —
stretched along a motion line, wrapped around a fist, outlined three times,
leaning at forty degrees, sometimes forming part of the composition. Replacing
one is a lettering job, not a translation job, and doing it badly is worse than
not doing it: you erase artwork and put a rectangle of Persian where a drawing
was.

So `sfx` is its own region kind, the default policy leaves them alone, and
`revayat-comic` does not pretend to redraw hand-lettering.

## The four policies

Set it in `comic.json` under `meta.sfx_policy`, before `clean`.

### `keep` — the default

The original stays exactly as drawn. Nothing is masked, nothing is repainted,
nothing is typeset over it.

Right for: almost every chapter. Readers of translated manga are used to
Japanese sound effects and read them as part of the art.

Still transcribe them in the worksheet. The transcription costs nothing, lands
in the glossary, and helps the next page.

### `translate`

The original lettering is removed and Persian is set in its place, inside the
region the original occupied.

Right for: clean, simple, upright lettering on a plain background — a `ドン` in
its own white gutter. Wrong for: anything stretched, rotated, outlined, or
overlapping a face.

Note what this costs: the artwork under the lettering has to be reconstructed by
the inpainter, and the result is only as good as that reconstruction. Check
`inpaint_heavy_pages` after cleaning.

### `bilingual`

The original stays, and a smaller Persian gloss is added beside it.

Right for: study and reference editions, and readers learning Japanese. Wrong
for: a busy page, where it adds clutter to artwork that is already full.

### `annotate`

The artwork is untouched and the meaning is recorded in the document rather than
drawn on the page.

Right for: pages where you want the information available without touching a
pixel — and for producing a translator's note track separately.

## Choosing

| The lettering is | Use |
| --- | --- |
| stretched, rotated, or perspective-warped | `keep` |
| overlapping a face or detailed artwork | `keep` |
| part of the composition rather than a label | `keep` |
| upright, on flat background, in its own space | `translate` if you want |
| anything you are unsure of the reading of | `keep` |

The rule when in doubt is `keep`. Erasing hand-drawn lettering to replace it
with a guess trades a thing readers understand for a mistake.

## Translating one

An SFX is a *sound*, not a description. `ドドド` is `دادادا` or `غرش` — not
`صدای پای سنگین`.

Some usable equivalents:

| Japanese | Sense | Persian |
| --- | --- | --- |
| ドン | a heavy impact | دام |
| ドドド | rumbling, approach | دادادا / غرش |
| バン | a bang, a slam | بنگ |
| ゴゴゴ | ominous pressure | غررر |
| ザッ | a sudden movement, footsteps | شرررق |
| キラ | a sparkle | برق |
| シーン | *silence* — the sound of nothing | سکوت |
| ドキドキ | a heartbeat | تاپ تاپ |
| ガシャン | breaking glass | شترق |

`シーン` is the one worth knowing: Japanese has a sound effect for silence, and
a literal reading of it makes no sense at all.

If you cannot read a sound effect from the crop, write what you can see in
`note:` and leave `fa:` empty. QA will report it as `sfx-untranslated`, which
under `keep` is expected and harmless.

## What QA says

| Code | When |
| --- | --- |
| `sfx-untranslated` (warning) | an SFX has no Persian and the policy does not require one |
| `untranslated-region` (error) | the policy *is* `translate` and one was left empty |
| `low-confidence-region` (warning) | the detector guessed this was lettering and nobody checked |

The last one is common on textured pages. Look at the crop; `drop: yes` if the
detector found screentone rather than a sound effect.

## The one it did not find at all

Detection misses effects, and a whole panel taken for a balloon silences the
free-lettering pass across everything drawn inside it — which is how a `BUMP`
went undetected on a real page while every count reported success. Add it from
the worksheet rather than accepting the loss:

```
@@ +bump sfx horizontal
box: 760 435 42 24
src: BUMP
fa: تلپ
```

`box:` is `x y w h` in the page's own pixels, read straight off `overview.png`;
add `polarity: dark` for white lettering on black, and re-run `mask` afterwards.
See `detection.md` for the same mechanism used to split a merged pair.

## Reconstructing what was under it

Under `translate` the original lettering has to come off the artwork, and the
built-in cleaners are honest but limited: Telea propagates surrounding structure
inwards and will not redraw a speed line it has erased. For effects that sit on
real drawing, hand the whole patch to a generative cleaner instead of asking it
to paint inside letter shapes:

```bash
revayat-comic mask  --doc work/comic.json --free-lettering solid
revayat-comic clean --doc work/comic.json --external reconstructed/
```

`clean` refuses solid masks without `--external`, because painting one flat
blanks a rectangle out of the drawing. Full reasoning in
`artwork-preservation.md`.

## Leaving one effect as drawn under `translate`

The policy is document-wide; `keep: yes` is the per-region exception to it.

```
@@ p0004r012 sign vertical
src: 出雲荘
keep: yes
note: a background shop sign — artwork, not dialogue
```

The region ends as `kept_by_policy`, `clean` and `typeset` leave it alone, and
QA does not report it as untranslated.

**Do not use `drop: yes` for this.** `drop` means *there is no text here*, and
using it for real lettering makes `stats.states` count that lettering as
`dropped_false_detection` — which is the exact thing the census exists to rule
out. This project made that mistake on its first real chapter, on a Japanese
billboard, because `keep` did not exist yet.

## What is not implemented

Redrawing stylised lettering — matching the original's slant, stroke weight,
outline and perspective — is not here. It needs a lettering pipeline, per-glyph
transforms and a font matched to the original's hand, and a half-hearted version
of it produces pages that look worse than leaving the Japanese in place.

`translate` sets upright Persian in the region the original occupied. That is
honest about what it is, and `keep` remains the default for a reason.
