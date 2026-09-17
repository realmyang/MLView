# Publication and desktop retry — 2026-09-17

GitHub publication succeeded after the credential gained `workflow` scope.
The branch is published in [draft PR #9](https://github.com/realmyang/MLView/pull/9).
The [push run](https://github.com/realmyang/MLView/actions/runs/35263547094)
passed all seven active jobs at code revision `e93c838`. The
[PR run](https://github.com/realmyang/MLView/actions/runs/35264141214), at the
documentation-only revision `9ca50d5`, passed five jobs and failed Windows e2e.
Four extension assertions compared short 8.3 paths with expanded paths. Their
expectations now use asynchronous `realpath`, matching the validator while
retaining exact comparisons. Follow-up CI is linked from the PR.

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
