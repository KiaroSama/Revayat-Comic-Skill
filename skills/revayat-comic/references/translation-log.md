# The translation activity log

Every agent **using this skill** must write a durable activity log throughout
translation, correction and delivery. This is part of the translation project,
not a coding-session log and not merely the CLI's diagnostic output.

## Location and lifetime

Resolve `OUTPUT` before step 1. For a CBZ/PDF, place the log directly in its
parent folder. For a folder of translated pages, place it directly inside that
folder. Example: `out/chapter-fa.cbz` and
`out/revayat-translation_2026-09-15_09-10-11_UTC.log` are siblings.
Do not put the only copy in the installed skill, `.ai/`, a system temp folder,
or a nested `logs/` folder. If outputs go to different folders, each delivered
folder gets the activity record for its artifact.

Create a new UTF-8 file exclusively for each session, named
`revayat-translation_YYYY-MM-DD_HH-mm-ss_UTC.log`; add a short unique suffix on
collision. Use real UTC timestamps, never fabricated execution times. On
resume, preserve the previous log and identify it in the new log. If `OUTPUT`
changes, copy the current log next to the new output, record the relocation,
and continue there. Never overwrite another run's log.

Append and persist after each meaningful stage/page/revision, not only at the
end. Close file handles after writing. For cooperating agents, the coordinator
is the single writer; each worker returns structured events with its actual
status. A worker's claim is not proof a CLI stage succeeded.

If the output folder cannot be written, report that and resolve the destination
before continuing. If a later append fails, retain the pending events, report
the failure, and restore logging before further translation or delivery. Never
claim the logging requirement passed because a file exists but is empty.

## Event format

Use one escaped, single-line event:

```text
[YYYY-MM-DDTHH:mm:ssZ] [INFO|WARN|ERROR] [STAGE] run=<id> page=<id|-> region=<id|-> action=<name> status=<value> detail=<brief evidence>
```

`STAGE` is `START`, `IMPORT`, `READ`, `TRANSLATE`, `REVIEW`, `GLOSSARY`,
`MASK`, `CLEAN`, `TYPESET`, `QUALITY`, `QA`, `EXPORT`, `RECOVERY`, or `END`.
Use English event keys/messages; short Persian examples are allowed when a
specific spelling or voice decision needs them. Escape embedded newlines and
control characters in values so page text cannot forge an event.

Record these events at the time they happen:

- Start: agent/skill version, source and output basenames, source hash, source
  language/locale, reading direction, page count, chosen SFX policy and log path.
- Import/quality: original pixel dimensions, PDF point dimensions when known,
  low-quality findings, enhancement decision/tool/settings, derivative paths
  and before/after dimensions. A decision to retain an already good scan counts.
- Reading/translation/review: inspected page and region IDs, uncertain readings,
  speaker/addressee and voice changes, glossary decisions, kept/dropped regions
  with reasons, correction category and result, and compression pair approval.
- Processing/recovery: actual stage result, changed page IDs, exit status,
  useful warning/error codes, retries and what changed between attempts.
  Reference worksheet/report paths or hashes instead of copying whole dialogue.
- Delivery: actual strict QA/package results, original hash recheck, final
  artifact name/hash/page count/dimensions, log path, and unresolved items.

Never write credentials, authorization headers, endpoint query strings,
environment dumps, private reasoning, or wholesale comic transcripts to the
log. Report observable decisions and short reasons. Keep the source and full
Persian in their worksheets, where they belong.

## Completion gate

Read back the log as UTF-8 before handoff. Confirm it is beside the delivered
file, has the current run's start, page/revision events, actual QA and export
outcomes, and a final status matching those outcomes. Link both output and log
in the response. An interrupted or failed run ends with its real status, never
`success`. Existing CLI logs under the work folder are useful diagnostics but
do **not** satisfy this agent activity-log requirement.
