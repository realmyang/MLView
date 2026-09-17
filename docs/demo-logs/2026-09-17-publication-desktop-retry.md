# Publication and desktop retry — 2026-09-17

GitHub publication succeeded after the credential gained `workflow` scope.
The branch is published in [draft PR #9](https://github.com/realmyang/MLView/pull/9).
The [push run](https://github.com/realmyang/MLView/actions/runs/35263547094)
passed all seven active jobs at code revision `e93c838`. The
[PR run](https://github.com/realmyang/MLView/actions/runs/35264141214), at the
documentation-only revision `9ca50d5`, passed five jobs and failed Windows e2e.
Four extension assertions compared short 8.3 paths with expanded paths. Their
expectations now use asynchronous `realpath`, matching the validator while
retaining exact comparisons. The final matrix at `d1461b4` passed all 13 active
jobs: [push, seven](https://github.com/realmyang/MLView/actions/runs/35267155314)
and [PR, six](https://github.com/realmyang/MLView/actions/runs/35267159574), including
Windows PowerShell end-to-end.

## Desktop investigation and retry

App inventory succeeded and listed VS Code. A Finder attachment probe hung for
about 512.5 seconds despite a requested 20-second timeout, then was interrupted
by the root agent. A subsequent direct Code attachment succeeded in 1.7 seconds
without an app reset, quit or reload. Later direct attachments also succeeded
in under a second. The cause of that intermittent recovery was not established.

The `d2749561…` VSIX installed successfully in the completed Codex GAN workspace;
only that window was reloaded. Activating an edge opened cited source at line 94,
but returning to the diagram and opening Refine showed `Whole diagram`.
This was a valid selection gesture. Source inspection and an immediate-handoff
regression confirmed that the viewer could be destroyed before its delayed
state save. The fix persists state synchronously before navigation; the test
destroys the DOM during the outgoing source message, restores the selected edge
and verifies the copied refinement prompt. Without the fix, the persistence
assertion fails with an undefined selection.

The new VSIX SHA-256 is
`9de5a9d97818a8cd392e6578c21d0c1e400c3d1176d42fe6db0a2948f66e409f`.
Its live installation and acceptance were blocked when attachment failed again.
The final recovery attempt reset only the automation REPL: inventory succeeded
in 1.08 seconds, then Code attachment failed in 0.031 seconds with
`cgWindowNotFound`. Other calls reported `noWindowsAvailable`.
The documented API provides app selection and state refresh, but no explicit
native window selector. Neither a screen-lock diagnosis nor a stale-handle
diagnosis was established. No active assistant session was closed.

One later orchestration interrupt was based on an incorrect inference that a
Code attachment was hanging. The tool transcript showed a successful attachment
and subsequent UI work; it is not counted as another attachment timeout.

## Native run status

The batch initially contained seven validated initial artifacts and one validated
GAN child revision. During this retry, Copilot's grouped-CV task resumed, Claude's
GAN task started with Fable 5.1 Extra high, and a source-only Codex configured-
training baseline started with GPT-5.6 Sol Ultra. The baseline UI unexpectedly
showed `You stopped after 32s`; its cause was not established, and Resume
returned it to an active state. None of these three runs had a final response
or a newly published artifact at the last observation.

After desktop access failed, Claude's GAN artifact appeared on disk and passed
independent validation against the frozen source. Revision
`rev-dev-gan-20260917-1` contains 36 nodes, 72 edges, nine phases, two findings
and 51 evidence records. Its SHA-256 is
`7f2a72ea47471b4ef9fe534fff5daa15146b584a3eef8f07a80eda67fd330737`.
It is preserved unchanged among the
[native snapshots](../../evals/workflow/development/native-artifacts/README.md).
This raises the total to eight validated initial artifacts plus the GAN child.
The final native response and repair count were not observed. Provisional review
found source-supported update ordering and gradient paths, with overbroad
`observed` labels for framework interpretations and a synchronization claim
that needs to distinguish CUDA from the source's CPU fallback. Those model
review notes are not human adjudication or a live UI pass.

Four skill cases and three baselines remain incomplete. All twelve prepared
skill workspaces still match the frozen source and four-file skill content.
Exact prompts, partial UI observations and hashes are retained under the
ignored `.mlview/sprint-20260917` directory. Human semantic review and the
held-out pilot remain pending; this retry supplies no accuracy score.

## Follow-up after the unlocked-desktop confirmation

The user confirmed that VS Code was visible on an unlocked Mac desktop.
A direct bundle-ID attachment then succeeded in 2.68 seconds. That observation
does not establish the cause of the earlier attachment failures.

The final `9de5a9d9…` VSIX installed successfully, and only the completed Codex
GAN workspace was reloaded. Its installed renderer hash matched the packaged
`705218d6…` renderer. Activating `record completed alternating update` opened
source line 94. Returning to the diagram created a new webview and retained the
edge in Inspector. Refine displayed `edge: e-g-step-metrics`; the copied prompt
contained that stable ID, the scenario, both evidence IDs and the correct
parent revision. The prompt was inspected in a temporary unsaved editor, then
discarded without modifying source or publishing another revision.

This is a live pass for installation and the immediate-navigation selection
regression in the macOS Codex GAN workspace. It does not establish other native
host or platform combinations. A command-palette clipboard timeout was worked
around by setting the observed text field; it was separate from the earlier
window-attachment failures. The exact observation and copied prompt are retained
in the ignored `native/codex/dev-gan/remount-retry3/ui.md` evidence record.

The original app handle remained usable across workspace switches and new
windows. A separate attachment attempt made by a Sol subagent remained pending
for 364 seconds before root orchestration interrupted that tool call; it returned
no handle or UI state. The root's existing handle then refreshed successfully
in 1.92 seconds. No native assistant session was stopped by that interruption.

Copilot's grouped-CV run completed after its remaining local draft-generation,
validation and publication command was approved. Its `rev-1` artifact has four
phases, six nodes, five edges, five evidence records and no findings; SHA-256
`19a250761c99a03e9137d7a7b61c9859d4b98c584c236f092b80b5ee3e4e933f`.
The installed helper passed, and the source and skill still matched the frozen
input. Copilot's final response reported two repair categories and its UI showed
19 steps, 4m 36s and 7.3 credits with MAI-Code-1.1-Flash. The displayed duration
does not include the long approval wait and is not total elapsed wall time.
Its library-semantics labels and missing custom encoder/feature implementations
remain provisional-review caveats, not human-adjudicated findings.

The completed Codex no-skill baseline response was recovered and copied unchanged
into ignored evidence. Its UI displayed the final answer with no chats running,
despite retaining the earlier interruption marker. The final Claude GAN and
Codex notebook responses were also recovered: both reported zero validator
repair rounds. Claude's claimed 74 edges differs from the artifact's measured
72; the original artifact remains unchanged.

The batch now has nine of twelve initial publications and one of three baseline
responses. The five remaining isolated workspaces need VS Code trust. Automatic
approval review rejected the first trust action because it enables tasks,
debugging and extensions and requires explicit user approval. An approval
request covering those five folders is pending; no trust workaround was used.

While that approval was pending, a new Codex chat in the already trusted notebook
workspace published a separate partial overview, `partial-data-preprocessing-r1`.
Its SHA-256 is
`765798c9390c46bc070810fa59e6208e7d51371352ccca9bbd16e7c6f45fae0b`;
it contains three phases, five nodes, seven edges, two findings and six evidence
records. Independent validation with the frozen helper passed. It explicitly
covers cells 0–2's inputs and preprocessing, with cell 3's model, loss,
backward/update and evaluation work still unreviewed. The original full notebook
artifact, notebook source and installed skill remained byte-identical. This
separate lifecycle test is preserved in ignored evidence and does not increase
the initial-case or baseline counts.

Around 21:15 UTC, the existing desktop handle failed with `cgWindowNotFound`
in 0.073 seconds. Inventory still listed Code, but a fresh bundle-ID attachment
returned the same error in 0.018 seconds. The partial artifact appeared on disk,
but its final native response, repair count and live diagram acceptance were
not observed. No native assistant session was stopped or window reloaded.

## Retry after explicit trust approval — September 17–18 local time

The user explicitly approved the five prepared workspace-trust changes. Desktop
attachment recovered, and each exact folder was marked trusted through VS Code:
Claude's notebook, Copilot's GAN and notebook, and the two remaining no-skill
baselines. The trust list confirmed all five; no parent folder or global trust
setting was changed. All five native runs were started in their own workspaces.

Both baseline responses completed. Copilot Auto selected MAI-Code-1.1-Flash;
its UI reported four steps, 21 seconds and 0.9 credits. Its native response copy
is preserved unchanged in ignored evidence. Claude used Fable 5.1 Extra high;
its full final response was observed with the assistant idle. Clipboard export
failed, so that response is preserved as an explicitly labelled accessibility
transcription, not a byte-identical Markdown export. No elapsed-time value is
claimed for Claude. Both six-file source workspaces remain unchanged.

Claude's notebook run published `rev-20260917-leak-out-of-order-1`, with four
phases, 16 nodes, 21 edges, four findings and 24 evidence records. SHA-256:
`d66dfe36ea0b78fbd5500e495b8b27013db97be6ac16e8b3754d40c07b75a660`.
The helper passed, and the final response reported zero validator repairs after
one pre-validation critique. A compound publication command's exit code 1 came
from a subsequent check for an absent lock file; publication itself returned
success. Independent provisional review found no material source contradiction
or publication privacy issue, while retaining library-behavior and conditional
next-batch caveats. This remains model review, not human adjudication.

The partial-overview final response was also recovered: zero repairs and
4m 31s displayed. The real panel rendered five nodes and seven edges with the
explicit partial scope; activating its scaling-to-split edge opened notebook
cell 3 of 4 (zero-based cell 2), without executing the notebook. However, the
panel also showed “Graph truncated at 5 nodes” and legacy CLI advice. Authored
partial coverage had incorrectly set the legacy node-cap flag.

The adapter now leaves that flag false for authored documents, while retaining
the partial coverage label and limitations. New regression assertions exercise
normalization and the mounted viewer; existing legacy truncation checks remain.
Viewer tests passed 607 with one existing TODO. After putting the repository
venv first on PATH and refreshing renderer provenance, extension tests passed
437 with no skips. Both TypeScript checks and all ten parity gates passed. The
fixture's only final change is its renderer hash; semantic graph bytes remain
unchanged.

The new VSIX SHA-256 is
`5c769d037e6cde25eb3cd7d15ad60b620b313805f2c5031a7808187ff002fbe8`;
the renderer SHA-256 is
`0dba48e56bd90931415092c07b3262f1eda0a6484020159d3528df795ceedaee`.
Live installation succeeded and the installed renderer matched. Only the
completed Codex notebook window was reloaded. The unchanged partial artifact
then showed its partial status, four limitations, five nodes and seven edges,
with no legacy truncation banner. This is a specific macOS live pass.

All thirteen CI jobs at the preceding `6509e4f` checkpoint passed:
[push, seven jobs](https://github.com/realmyang/MLView/actions/runs/35276066934) and
[PR, six jobs](https://github.com/realmyang/MLView/actions/runs/35276073282), including
Windows end-to-end. That evidence predates the additional partial-display fix.

The matrix now has ten completed skill cases and all three baseline responses;
Copilot GAN and notebook were last observed running after source/interpreter
approvals; neither has a published artifact at the latest filesystem check.
Desktop attachment again returned `cgWindowNotFound` on both the existing
handle and a fresh attachment. Trust is resolved; no native run was stopped.
The user was asked to restore a visible, unlocked desktop. Human semantic
review and the held-out pilot remain pending, with no accuracy score claimed.

## Final two Copilot cases — September 18 local time

The next requested retry recovered desktop access. Only the main repository
window appeared in VS Code's Window menu. The two already trusted isolated
Copilot workspaces were reopened, and their original sessions were selected
from native chat history. GAN had stopped after drafting and a validator
invocation whose terminal was no longer available; the notebook had stopped
after source and helper inspection without a draft. Neither had a published
artifact. The frozen source and complete installed skill trees remained intact.

Both original conversations received a short continuation prompt at 00:18
local time to finish critique, validation and publication under the original
constraints. The GAN prompt explicitly resumed the saved draft. The notebook
prompt resumed the prior source analysis. No semantic-review feedback was
supplied to either run, and no source or skill was edited. Copilot Auto routed
both resumptions to MAI-Code-1.1-Flash, with individual local command approvals.

| Completed case | Published revision | Phases / nodes / edges / findings / evidence | Reported validator repairs | Native resumed-segment display |
|---|---|---|---|---|
| Copilot GAN | `rev-1` | 6 / 11 / 11 / 1 / 17 | 1 | 12 steps, 3m 24s, 7.3 credits |
| Copilot notebook | `dev-notebook-rev-1` | 4 / 4 / 3 / 1 / 4 | 0 | 2m 41s, 4.2 credits |

Both final responses were visible with Send disabled and no active Cancel
button; the footers showed 00:22. These durations exclude the interrupted
original turns and approval delays and are not total elapsed measurements.
The notebook's todo widget still showed its first item despite its successful
publication and final answer; no completion claim relies on that widget.
Ignored observer logs explicitly transcribe selected native accessibility
observations; they are not byte-identical response exports or screenshots.

Published GAN SHA-256:
`6451e734b53fbea73d8f621729b8bfc0c529f9db79209850c4ec9b0251b193fe`.
Published notebook SHA-256:
`6fe4fbd79af4d30f47462a5c9d469c9f1943adca7e37029720f8f3e4f93139d4`.
The GAN repair corrected producer, edge, finding and evidence formatting.
Both originals are preserved as byte-identical public snapshots after privacy
inspection. Machine paths and native transcript details remain in ignored
evidence. Source and installed skill hashes still match the frozen inputs.

The installed extension opened both diagrams with their expected revisions,
counts and three coverage limitations each. GAN's `d_fake_detached_path` node
opened `train_dcgan.py` at line 86, column 1; the Inspector retained the node
and lines 86–89's noise, generation, detach and loss quotation. The notebook's
`train-model` node opened cell 4 of 4 (zero-based cell 3), while its Inspector
retained the selected node and exact training-loop quotation. No target code
or notebook cell was executed. GAN omits the optional model name in its artifact;
the native chat, not the diagram, supplies the observed routed model.

Provisional source review found no privacy issue, but retained semantic caveats.
GAN's metrics sentence can imply running sums are printed, while lines 101–105
print current-batch losses. Several autograd claims are labelled observed even
though they depend on framework semantics. The notebook carefully qualifies
execution metadata but omits whole-data scaling before the split, missing
gradient clearing between batches, and the lack of test evaluation and saved
outputs. These are model-authored review observations, not human verdicts;
the evaluation artifacts were not changed to remove them.

This completes the development batch's twelve initial skill publications and
three no-skill baselines. The challenged Codex GAN child and separate partial
overview retain their distinct roles. Human semantic adjudication and the
held-out pilot remain pending; no LLM accuracy percentage is claimed.

All thirteen remote CI jobs also passed at `0103178`, including the latest
partial-coverage display fix:
[push, seven jobs](https://github.com/realmyang/MLView/actions/runs/35280429266) and
[PR, six jobs](https://github.com/realmyang/MLView/actions/runs/35280432668), including
Windows end-to-end. This is exact-revision evidence, separate from the later
artifact/documentation additions. Draft PR #9 remains open; no merge occurred.
