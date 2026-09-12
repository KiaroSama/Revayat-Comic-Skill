# Translation policy

What to hand the sub-agent translating one page, and what it must do. Read this
before step 5 of `SKILL.md`; the sub-agent should read it too.

## The one thing that makes this different

You can see the page. An OCR-then-translate pipeline cannot, and every weakness
of those tools comes from that: a bare string has no speaker, no tone, no face
above it and no balloon answering it back.

So look at both images the worksheet names, in this order:

1. **`overview.png`** — the whole page, every region numbered in reading order.
   Read the page as a page first. Who is in it, what is happening, who is
   talking to whom, which balloon is an answer to which.
2. **`sheet*.png`** — the crops, enlarged and labelled with region ids. Read the
   text from these; the overview is too small to read from.

Then write the worksheet. `src:` is what the balloon says. `fa:` is the Persian.

## Register is most of the job

Comic dialogue is speech, not prose. The commonest failure in a machine
translation of a manga is not a wrong word — it is a correct word in the wrong
register, so that a fifteen-year-old shouting at his brother sounds like a
government notice.

| The art shows | The Persian should be |
| --- | --- |
| shouting, motion lines, a jagged balloon | short, blunt, no polite verb endings |
| a thought balloon | quieter, more interior, often unfinished |
| a narration box | narrative past tense, more formal than any dialogue |
| a small trailing balloon | a mutter; keep it small in words too |
| a child | plain vocabulary, simple structures |
| a formal or older character | full verb forms, no clipping |

**That table is what the art suggests, not a lookup.** Register comes from how
these two characters actually speak *to each other*, and the dialogue overrides
every row of it. An older character who talks like a thug talks like a thug in
Persian too; a narration box written as a wry aside is not narrative past tense
because it is a narration box; a shout is loud, which is not the same as rude.
Age, rank and gender decide nothing on their own — the relationship does, and
`context` hands you the speakers and the recent dialogue so you can see it.

Japanese carries register in verb endings that Persian carries in word choice
and sentence length. `やめろ` and `やめてください` are the same instruction; the
first is `بس کن` and the second is `لطفاً بس کنید`. Losing that flattens every
character into one voice.

## Length

Persian runs longer than Japanese, and a balloon does not grow. If the natural
Persian is too long, the answer is a shorter Persian sentence that still says
everything — not a summary, and not a smaller font.

Practical guidance:

- Prefer the shorter of two accurate renderings.
- Drop filler that Persian does not need: a Japanese sentence-final particle
  usually becomes punctuation or nothing.
- Do not pad. `そうか` is `که این‌طور`, not `آها، پس قضیه از این قرار بوده`.

**Naturalisation and compression are different jobs, in that order.** Writing
natural Persian is the translation; making it fit is layout. When `typeset`
reports a region as overflowing, try them in this order:

1. **A line break.** A newline inside `fa:` is honoured — the fitter treats it
   as a hard break and sets the balloon on two lines. Often the words were
   already right and only the shape was wrong.
2. **A shorter wording** that still carries everything in *Fidelity is not
   literalness* below. Put the original in `note:` so the choice stays
   reviewable; a shortening nobody can see is a shortening nobody can check.

Never a summary, never a dropped clause, and never a smaller font — the size
floor holds for a reason.

## Fidelity is not literalness

A translation can map cleanly onto every word of the original and still be
wrong, because it reads as translated. That failure passes every gate in this
project: the ids match, the script is Persian, nothing overflows, no term
drifted. Only a reader catches it, and the word they use is *stilted*.

Three habits separate Persian that reads natively from Persian that reads
translated. They matter more in a balloon than in prose, because there is no
room to recover:

- **Persian drops subjects that English and Japanese must state.** `او رفت` is
  usually just `رفت`. A pronoun in every balloon makes every character sound
  like they are giving evidence.
- **Persian prefers a verb where English takes a noun.** Not
  `تصمیم به رفتن گرفت` but `تصمیم گرفت برود`. Not `در حال انجام بررسی است` but
  `دارد بررسی می‌کند`.
- **Persian will not carry a long relative clause; break it in two.** A single
  sentence with a `که …` tail that keeps going is the commonest shape of a
  translated-sounding balloon. Two short sentences almost always beat it, and
  they fit better as well.

The test is not "does this match the original word for word" but "would a
Persian speaker say this, in this situation, with this much space". Where those
two pull apart, say what the character means.

Adapted from the sibling novel project, which found it on its first real
translation sample — every automated check green, rejected by its reader in one
word.

## Names and terms

The table at the top of the worksheet is binding. Use exactly the Persian it
gives, every time. If a name is not in the table, choose a rendering, use it
consistently, and get it into the table for later pages:

- `speaker:` — **who is saying this balloon.** It also feeds voice consistency,
  so it has to be true.
- `propose:` — **a name or term this balloon only mentions.** `propose: Anna`
  for "did you see Anna?". Several are separated by commas.

They were one field, and the only route into the glossary was `speaker:`. A
name that is merely talked about therefore had to be filed as the speaker,
which told every later page that the wrong character was talking.

A locked entry keeps its history: changing an approved Persian form bumps its
`version` and records what it used to be, so an earlier chapter translated
against the old spelling can still be found.

For a Japanese name, transliterate rather than translate: ハルカ is `هاروکا`.
For a title or a technique with a meaning, prefer the meaning when it is a
common noun (`先輩` → `سِنپای` when it is used as a name, `ارشد` when it is a
role) — decide once and stay with it.

Honorifics: `-san`, `-kun`, `-chan`, `-senpai`. Keep them when the relationship
between two characters is part of the story and Persian has no equivalent;
drop them when they are only politeness. Do not switch between the two policies
inside one chapter.

## What the title has already settled

Honorifics, name policy, sound effects, slang and profanity are decisions a
**title** makes once, not decisions a page makes. They live in
`meta.title_policy` in `comic.json`:

```json
"title_policy": {
  "honorifics": "keep -senpai, drop -san",
  "names": "transliterate Japanese given names; translate technique names",
  "sfx": "translate, Persian onomatopoeia",
  "slang": "contemporary Tehran register, no regional dialect",
  "profanity": "render at full strength; this title is not for children",
  "register": "the two leads use تو with each other from chapter 3"
}
```

Every non-empty entry is handed to the translator under `constraints`, beside
the locked glossary, and printed at the top of every worksheet. Nothing invents
one: absent means nobody has decided, and then the page decides, as above.

## Persian specifics

- Natural Persian punctuation: `،` `؛` `؟` `«»`. The typography pass fixes these
  mechanically, so write naturally and do not fight it.
- Persian letters, not Arabic: `ی` and `ک`, never `ي` and `ك`.
- Half-spaces where they belong: `می‌روم`, `کتاب‌ها`. Also mechanical.
- Do not reverse anything, and do not paste text that already looks right-to-left
  in your editor. Write ordinary Persian in ordinary order.
- Do not insert an explanation into the dialogue. A character does not explain
  their own culture mid-sentence.

## Sound effects

An SFX is lettering drawn into the artwork. Under the default `keep` policy it
stays as drawn and you only transcribe it, which is still worth doing: it lands
in the glossary and helps the next page.

When the policy is `translate` or `bilingual`, give a Persian equivalent that is
a *sound*, not a description: `ドドド` is `دادادا` or `غرش`, not
`صدای پای سنگین`. If you are unsure what a sound effect says, say so in `note:`
and leave `fa:` empty rather than inventing one — a wrong SFX replaces artwork
with a mistake.

An effect drawn **on a slant** is set on the same slant; the angle comes from
the mask, not from you, and nothing is asked of the worksheet. If a particular
one should stay drawn anyway, that is `keep: yes` on the region — the decision
is yours, and it is the only thing that stops the replacement.
See `sound-effects.md`.

## Correcting the detector

The detector measured geometry. It did not understand the page, and you do.
Four fields fix what it got wrong:

- `drop: yes` — there is no text in this region. Screentone, a hand, a panel
  border that happened to look like lettering. Common for low-confidence
  regions; use it freely.
- `keep: yes` — there **is** text and it stays in the artwork: a shop sign, a
  logo, an effect you do not want replaced. Not the same claim as `drop`, and
  reaching for `drop` here makes the terminal census file real lettering as a
  false detection. `kind:`, `speaker:` and `note:` all still apply beside it,
  and a `keep` counts as a review — the region locks, so a later `detect` run
  leaves your decision alone.
- `kind:` — it called a narration box `speech`, or a shop sign `sfx`.
- `speaker:` — who is talking. Use a short, stable name and use the *same* one
  on every page. This is what makes a character sound like one person.
- `propose:` — a name or term this balloon only *mentions*. It reaches the
  glossary the same way, without claiming the wrong person is speaking.

## What never to do

- Never merge two balloons into one answer, or split one across two.
- Never leave a balloon untranslated because it is hard. Ask in `note:`.
- Never summarise. A balloon with four sentences gets four sentences.
- Never invent a region id, and never renumber one.
- Never write English into `fa:`.
