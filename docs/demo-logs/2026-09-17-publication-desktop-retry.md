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
