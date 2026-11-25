# Recovering interrupted work

## Interrupted publication

After the previous export process exits, repeat the original command with the same destination. The CLI checks for a pending journal before it starts a new export:

```bash
revayat-comic export --doc "$WORK/comic.json" --out "$OUTPUT"
```

Recovery validates the original input digests, the document generation, the
publication intent and every old/new file before applying metadata. A known
partial publication is completed when its new bytes remain available; otherwise
an intact previous generation is restored. Existing edition manifests survive.
Unknown or changed bytes are preserved with a conflict record for inspection.
Staging retirement belongs to that same transaction; changed staged files and
unexpected entries are preserved even when rollback is refused.
The presence of a directory is not proof that a recovered edition is complete:
run `qa package` on the actual destination afterward.

If the retry reports a conflicting claim or changed files, stop and keep the journal, backups, and staged files. Do not delete a lock by filename. Once export succeeds, verify the package:

```bash
revayat-comic qa package --doc "$WORK/comic.json" --package "$OUTPUT"
```

All document mutators use the same workspace claim. A stale document loaded by
a library caller is refused on save rather than overwriting a newer edit.
Reload the document and apply the intended edit to that current generation.

## Crop-sheet recovery

Rebuilding crops retires only previously recorded sheets whose bytes still match
owned evidence. Unrecorded operator files remain untouched. Older sheet records
without hashes are accepted only when an exact current rerender proves their
bytes; changed geometry or edited sheets can require manual reconciliation.

Failed publication restores prior derivatives. If restoration itself fails,
original copies remain in a `.crops-*.recovery` directory beside the document,
and another rebuild refuses until that evidence is inspected. Preserve these
copies and the document; do not delete the directory merely to silence refusal.
A failed surplus-sheet deletion retains hash-bound pending retirement in the
page record so the ordinary crops command can retry safely.

## Interrupted worksheet merge

Retry the ordinary `worksheet merge` after resolving the IO failure. Accepted
text and its receipt commit together in the document. The receipt binds the
consumed reply to its verified old/new page mapping, so retry can finish a failed
header update without reapplying the Persian or undoing normalization.

Context progress compares a well-formed accepted receipt's page identity separately
from today's glossary/header constraints. Normal terminology, title-policy or language
updates do not falsely report moved regions. Actual box/kind/orientation/source-image
changes remain blocking, including with `--allow-unmerged`. Older or malformed
receipts keep the conservative stage guard; edited replies still need merging.

For a stale reply, first save the existing `.done.txt` outside the worksheet directory. Build a fresh worksheet and open the current page's overview and crop sheets:

```bash
revayat-comic worksheet build --doc "$WORK/comic.json" --worksheets "$WORK/worksheets" --pages p0003
```

Use the fresh worksheet's header and map each retained Persian line to its verified region. IDs alone cannot establish that a region still points to the same artwork. Save the reviewed reply as `p0003.done.txt`, then merge only that page:

```bash
revayat-comic worksheet merge --doc "$WORK/comic.json" --worksheets "$WORK/worksheets" --pages p0003
```

The merge still checks for duplicate and missing regions. It rejects invalid kind or orientation values before changing a region. Correct the named header rather than
forcing it through. Field CR/LF/CRLF endings normalize to logical LF; action-like
continuations remain literal text. Malformed legacy glossary approval requires
an explicit boolean correction before reading or mutating that entry; the text
`"false"` is not approval and does not create approved revision history.

Rebuilt compression approvals carry a content fingerprint. Editing `fa`,
`fa_full` or `src` leaves the old approval attached to its old meaning. After
reviewing the new pair, replace the stamped entry with bare
`reviewed: compressed-variant` to record a new decision; the earlier one remains
in its history. Retained `fa_full` after an explicit keep/drop/erase decision is
recovery history, not a shortened translation; an empty display does not request
compression approval. Returning to active translation with a different nonempty
full/display pair requires a current review again. Missing active text and unfinished
cleaning still fail their own gates.

A retained displayed draft is also history when the current decision is keep,
drop, erase or SFX keep. It is not drawn, normalized, policed as current Persian
or supplied as a paired translation memory entry. Reactivation restores those
checks without deleting the draft. Glossary rename impact still names historical
nondropped spellings; that advisory is distinct from current glossary enforcement.

Unchanged inactive pages may ship their original without a fake typesetting run;
completed erasures require their verified cleaned image. Active translation still
requires a render. A policy change stales the old edition: rebuild the affected
mask/clean/typeset stages and check QA before exporting. Bilingual/annotated glosses
still need an actual reserved placement; retained text does not invent one.

## Refresh after text-revision hardening

Text/source revision hashing now encodes field boundaries structurally. A pipe
inside `target_text`, `target_full` or source dialogue cannot hide a change by
moving characters across fields or region IDs. Existing comparable stage records
stay comparable: their old text/source hashes become stale, rather than being
accepted as unverified legacy output. The public record scheme remains `3`.

Run the named inexpensive affected stages once; for an old finished page, rerun
`typeset`, check publication QA, then export again. Unchanged detection, masks
and cleaning remain fresh; do not re-detect or retranslate the chapter solely
for this hash upgrade. If a `translate` or `glossary` stamp is inspected, refresh
it through its ordinary command; existing provider request identities still
protect completed answers from unnecessary calls. A partial-page refresh leaves
only the unrefreshed pages stale. Repeating a successful refresh converges.

## Package integrity

CBZ and folder checks require a complete ordered page manifest with a valid
SHA-256 for every page. Missing or malformed evidence is `archive-unverified`,
not approval because the pages happen to open. Restore the original export
record or re-export; never fill missing hashes from an unverified delivered copy.

Unchanged native PDFs are bound to their committed package SHA-256. Modified
containers must match the recorded visible RGB pixels at native resolution,
including rotation and crop state, with a compatible renderer. A legacy plain
single-image page may use its exact image proof only when the drawing program
contains no clipping, transparency or overlays.

Coarse page similarity is diagnostic only. Missing references, incompatible
renderers or a native-resolution recheck above the four-million-pixel budget
produce `archive-unverified` and a failed package check. Large unchanged native
PDFs still verify by their exact package hash. Re-export if a modified container
cannot be proven. Any changed dialogue pixel is an integrity failure.

ZIP declarations, including directory members with data and duplicate metadata
names, are checked before CRC scanning. Validation remains bounded and reads
one page at a time. Export destination checks include external worksheets and
original source-directory members, while preserving separate output folders and
operator-owned extras.

Worksheet locations are resolved by the shared document policy. An explicit
`--worksheets` relative path is resolved when that command runs
and is remembered as an absolute folder, so status/merge/context from another
working directory find the same replies. A relative folder already stored in
document metadata is interpreted beside `comic.json`. If an older record
was created relative to an unknown process directory, pass the actual folder
once with `--worksheets`; do not relocate or overwrite the reply files.

## Selection and diagnostics

In library APIs, `pages=None` selects all pages and `pages=[]` selects none.
Unknown page IDs fail before mutation. The CLI makes the same distinction:
omitting `--pages` selects all; explicitly passing an empty value selects none.
Removing a page's last region restores its original as the terminal output on
the next clean/typeset pass; unrelated files remain untouched.

The CLI writes UTF-8 diagnostics in `logs/` next to `bin/`, or alongside a standalone executable in another directory. The filename includes the UTC timestamp and, if needed, a collision suffix. The CLI records command metadata and exit status. If file logging fails, it warns on stderr and continues. Review a run log before sharing it. Keep the translation activity log separately beside the output.
