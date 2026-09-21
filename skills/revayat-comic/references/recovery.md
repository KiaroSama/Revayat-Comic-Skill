# Recovering interrupted work

## Interrupted publication

Run this after an export stops before its package and document agree:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py export --doc $WORK/comic.json --recover
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

If the process stopped before writing a publication record, name its destination:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py export --doc $WORK/comic.json \
  --out out/chapter-fa.cbz --recover
```

This can release a recognized claim only after proving that its local owner
process has exited. Its recorded staging file is moved aside for inspection,
with the published edition unchanged. Live, foreign or unrecognized claims are
refused. Preserve backups and conflict records until the recovered package has
been verified; deleting a lock by filename alone is not a recovery procedure.

All document mutators use the same workspace claim. A stale document loaded by
a library caller is refused on save rather than overwriting a newer edit.
Reload the document and apply the intended edit to that current generation.

## Interrupted worksheet merge

Retry the ordinary `worksheet merge` after resolving the IO failure. Accepted
text and its receipt commit together in the document. The receipt binds the
consumed reply to its verified old/new page mapping, so retry can finish a failed
header update without reapplying the Persian or undoing normalization.

A genuinely stale reply needs review of the named page's current crop sheet.
Match its existing Persian to the current region IDs and geometry, correct only
the affected mappings, then explicitly confirm those reviewed pages:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py worksheet reconcile \
  --doc $WORK/comic.json --pages p0003
$PY $SKILL_DIR/scripts/revayat-comic.py worksheet merge \
  --doc $WORK/comic.json --pages p0003
```

An absent fingerprint, or an old fingerprint with its scheme removed, provides no geometry evidence.
Stable IDs alone do not authorize migration. Reconciliation preserves the reply's
Persian; it does not retranslate the page or waive duplicate/missing-region checks.

Rebuilt compression approvals carry a content fingerprint. Editing `fa`,
`fa_full` or `src` leaves the old approval attached to its old meaning. After
reviewing the new pair, replace the stamped entry with bare
`reviewed: compressed-variant` to record a new decision; the earlier one remains
in its history.

## Package integrity

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

## Selection and diagnostics

In library APIs, `pages=None` selects all pages and `pages=[]` selects none.
Unknown page IDs fail before mutation. The CLI makes the same distinction:
omitting `--pages` selects all; explicitly passing an empty value selects none.
Removing a page's last region restores its original as the terminal output on
the next clean/typeset pass; unrelated files remain untouched.

CLI stages write a new UTF-8 log per execution under the document's `logs/`
folder. Commands without `--doc` use `scripts/logs/` beside the launcher.
Names include the script, UTC date/time and a collision suffix when needed.
Entries use `[timestamp UTC] [LEVEL] [COMPONENT] Message`; nested dispatch uses
one file. Logs contain stage outcomes, durations and sanitized exception locations,
never arguments, dialogue, credentials or exception values. There is no secret-bearing
verbose mode. If log initialization fails, stderr reports that limitation and
the stage still runs. Handlers close on completion. Logs are not packaged or
copied by the installers; retain failure logs for diagnosis and remove old logs
when no longer needed. Attach only the relevant run log when reporting an issue.
