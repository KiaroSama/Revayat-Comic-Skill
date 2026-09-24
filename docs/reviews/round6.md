# Round-six repair review

PR [#3](https://github.com/KiaroSama/Revayat-Comic-Skill/pull/3) began at
`a9cee3b`; its initial reviewed head was `1ad9786`. The original submission
contained five repair groups and 31 regressions. The reviewer also reproduced
a worksheet-location defect in that initial head. The initial CI success
proved the submitted subset, not the then-unpublished worksheet fix. This is
a review record; the final integrating SHA and checks are recorded in the PR
and the project's local repair ledger.

| Area | Failure reproduced | Contract retained in the corrected code |
| --- | --- | --- |
| Provider calls | Invalid timeouts/thresholds reached work; thread-start failure lost capacity | Reject settings before work, bind OCR resume to its acceptance floor, release a permit when startup fails |
| Provider result | Empty or non-text output and positional-only arguments could be mislabeled successful | Only nonempty text is accepted for text roles; a named positional-only argument is never passed by keyword, even with `**kwargs` |
| CLI outcomes | OCR/translation failures and refused cleaning could exit successfully | Return failing process/transport status while preserving accepted document text and refusal cause |
| MCP input | Imports escaped the error boundary; whole or whitespace-trimmed lines defeated the cap | Capture import/doctor errors, reject raw UTF-8 byte oversize and bound line resynchronization |
| Diagnostic log | No selectable level or shared active-run event route | INFO/WARNING/ERROR/DEBUG entries remain sanitized; translation activity beside output is a separate record |
| Worksheet location | A relative external folder was reinterpreted after a process changed CWD | Resolve explicit paths at invocation; anchor stored relative/default paths to the document; require explicit override for ambiguous legacy records |

The cross-directory worksheet regression first failed with `status.present=[]`
after an external reply had been created. The reviewer then moved the path
policy into `worksheet_paths.py`, preserving the public `pageir.worksheet_folder`
entry point while shrinking the over-700-line page document module. The same
regression passed after the change. Existing external worksheets are
operator-owned and must survive export collision checks.

The PR's `source-evidence.yml` captures tracked files and temporary reviewer
tools. Its output is reproducibility evidence only; it never includes licensed
comic pages, untracked user files or credentials. The initial local full-suite
attempt lacked the font expected by 64 anchored-ink tests, so those setup
errors were separately rerun with an installed face. A local missing RAR
backend is an explicit skip, never a pass. No paid/live translation, OCR model
or image-edit service was evaluated here.

The [GitHub skill comparison](../research/round6-github-skills.md) adapts
panel-context and visual-review ideas without importing whole-page image
generation or hosted uploads. Two original, human-review evaluation cases
probe irony and an implied subject. Mechanical scores remain separate from
human Persian adequacy.

Final acceptance for this repair is the current main SHA's Windows/Linux/macOS
matrix, oldest/newest Python, literal dependency floors, CLI E2E, installer,
Ruff, CodeQL, dependency review, source evidence and owner hooks. Inspect
those live results before citing this record as a completed release. A green
structural suite cannot certify every comic layout or translation.
