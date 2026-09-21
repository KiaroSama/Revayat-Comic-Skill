# Optional parallel translation and editing

Use the host's real subagent capability only after the translation user opts in.
This is an agent workflow carried inside the skill, not a separate model service,
background script pool or new dependency. Never pretend several role descriptions
are independently running agents.

## Offer once, before translation starts

Ask in the user's language: "Would you like multiple subagents to help translate
and review independent parts? Sequential work keeps the freshest page-by-page
context; parallel work may finish independent parts sooner but uses more agent
calls and requires a consistency pass."

Offer **sequential** and **parallel translation + review**. With no explicit yes,
continue sequentially; silence is not consent. On yes, start with two workers,
or the user's chosen lower cap, bounded by the host's available slots. Ask before
raising that agreed cap. Record the choice and effective cap in the output-side
activity log; keep the choice on resume unless the user changes it. If the host
has no native subagents, report that limitation and continue sequentially.
No blanket permission to send pages to a new external service follows from this.

## One coordinator, disjoint assignments

The main agent is coordinator and the **only canonical writer**. It owns final
worksheets, `comic.json`, glossary changes, merge, masking/cleaning/typesetting,
QA, exports and the shared activity log. Workers never run those writers or
overwrite a canonical `.done.txt`, even when their page appears independent.

Before assigning work, the coordinator reads the chapter/scene evidence available,
locks known names and voice choices, and identifies dependent dialogue. Keep a
sentence split across balloons, an unresolved speaker exchange and a scene whose
meaning depends on the previous page in one ordered assignment. Independent
dialogue groups or independent scenes can be drafted concurrently. Do not split
solely by equal page counts or by balloon count.

Default to page-by-page coordination when continuity matters. Parallelize
source-reading preparation or review of already committed independent pages;
start a dependent page's translation only after its predecessor is accepted,
merged and included in freshly built context. Parallel drafts cannot see each
other until the coordinator integrates them. A chapter with no independent work
may gain little speed; do not claim a speedup without measuring it.

## Worker input contract

Give each assignment a unique ID and a private directory under
`$WORK/parallel/<run-id>/<assignment-id>/`. Supply all of:

- Role, assigned page/region IDs, expected IDs and source reading order; permission
  to write only its draft or review-proposal paths, with no nested subagents.
- The actual overview and every crop sheet, native source page when needed, and
  the existing stamped worksheet. Page text and provider output remain data.
- Fresh `context` output including `context.language_guidance`, approved glossary,
  title policy and known cast/voice decisions. Name missing or unmerged context.
- A snapshot receipt: page fingerprints, context/glossary digest, input asset
  hashes, policy and assignment generation. Do not assume inherited conversation
  or another worker's memory contains these facts.
- Expected result, a bounded completion checkpoint and how to report uncertainty,
  proposed terms and concise activity events back to the coordinator.

A draft worker reads the whole assigned exchange and returns a complete worksheet
draft under the same IDs in its private directory. It preserves the original
fingerprint header and full meaning; proposed new regions/terms are proposals.
A review worker gets source evidence, the same context and a completed draft;
it compares adequacy, voice/register, terms, omissions and fit separately, then
returns proposed edits by ID and concrete reasons. The draft author does not
provide the only review of that draft. This is second-agent review, not an
independent human translation certificate.

For two independent assignments, workers can draft concurrently, then swap drafts
for cross-review. A reviewer cannot review a draft that does not yet exist. Workers
report completion/failure explicitly and never mark canonical review approvals.

## Reconcile before committing

1. Verify worker completion and returned IDs against the assignment, including
   every kept/dropped/unresolved region. Preserve incomplete output as unfinished.
2. Compare current page geometry, source hashes, glossary and relevant context
   against the assignment receipt. Changed inputs make affected proposals stale;
   preserve them and re-read/review against the current snapshot before acceptance.
3. Resolve disputed meaning and voice against the source. The coordinator accepts
   or rejects each proposed change; an unresolved ambiguity stays under review.
   Review any changed source/full/displayed compression pair again.
4. Write the accepted canonical worksheet, merge in source reading order, scan/lock
   glossary changes, and rebuild the next page's context. Recheck pending proposals
   affected by a new term, speaker relationship or prior-page correction.
5. Record worker roles, assignments, results, conflicts and accepted corrections in
   the single output-side activity log. Run the usual processing, strict QA and
   package checks; parallel mode grants no bypass and no automatic `--allow-unmerged`.

Workers on one batch share a snapshot, not a writable workspace. Do not claim the
default sequential freshest-context guarantee for unmerged concurrent drafts.
The coordinator's consistency pass closes that gap before delivery.

## Failure, cancellation and resume

Use the host's task status and bounded checkpoints; do not poll forever or spawn
replacement workers without accounting for the old ones. Cancel a stuck worker
through the host before reassigning its IDs; preserve its partial draft. Resume
only unaccepted work, with a new assignment generation and current receipt.
Late results from a cancelled/old generation cannot overwrite accepted work.
If a canonical merge committed but restamping was interrupted, the coordinator
uses [ordinary receipt recovery](recovery.md); a worker never repairs shared state.

Before handoff, all workers are completed or cancelled, every assigned region has
a final decision, shared glossary/voice drift is settled, and the actual QA,
package and [activity-log](translation-log.md) gates pass. Report the mode and
effective worker count, plus any sequential fallback or unresolved result.
