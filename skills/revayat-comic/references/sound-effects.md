# Sound effects

Why they are treated separately from dialogue, and how to choose a policy.

## They are artwork

A speech balloon is a container with text in it. A sound effect is *drawn* —
stretched along a motion line, wrapped around a fist, outlined three times,
leaning at forty degrees, sometimes forming part of the composition. Replacing
one is a lettering job, not a translation job, and doing it badly is worse than
not doing it: you erase artwork and put a rectangle of Persian where a drawing
was.

So `sfx` is its own region kind, the default policy leaves them alone, and what
`revayat-comic` will match is the slant and nothing more — see the last section
for exactly where that line is drawn.

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
| stretched or perspective-warped | `keep` |
| rotated, on a readable background | `translate` sets it on the same slant |
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

## Slant, and what is still not implemented

Under `translate`, a sound effect whose lettering was drawn **on a slant** is now
set on that slant. The angle is not guessed: `clean` has already erased the
lettering by the time the typesetter runs, so it is measured from the region's
own mask — the shape of what was erased — with `minAreaRect`, which gives the
baseline, the space the words filled upright, and an aspect ratio saying how far
to trust the answer.

That last part is the gate. A word set diagonally is long and thin and gives a
confident angle; a compact cluster of overlapping glyphs gives whatever angle the
fit landed on, so anything below `SFX_MIN_ELONGATION` and any slant under
`SFX_MIN_ANGLE` takes the flat path instead. Straight lettering — most lettering
— is unaffected. `--flat-sfx` turns the whole thing off, and `typeset.style` in
the region records which path ran, `rotated` or `flat`.

The outline is heavier on this path than in a balloon (`size // 8` against
`size // 12`), because a sound effect sits on artwork rather than on paper and
the stroke is the only thing keeping it legible.

**Still not implemented: perspective and curve.** Lettering that recedes into a
panel or bends along an arc needs a mesh warp and a font matched to the
original's hand, and a half-hearted version looks worse than leaving the Japanese
in place. Stroke weight beyond the outline, and matching the original's actual
face, are also out.

**None of this decides whether to replace an effect at all.** That is the
reader's call, and it is `keep: yes` on the region. The code will not quietly
skip lettering somebody asked it to translate: a silent skip is exactly the hole
the five terminal states exist to make visible.
