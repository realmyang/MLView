# Native development-host exercise — 2026-09-17

The [subsequent retry](2026-09-17-development-retry.md) adds two initial
publications, a challenged child revision and live lifecycle checks. This log
preserves the first attempt's observations and interruption.

This run exercised the installed MLView skill in fresh, isolated VS Code workspaces. Each fixture contained only its target source and a canonical skill copy. Prompts prohibited target import or execution, the legacy static analyzer, other workspaces, earlier artifacts, and subagents. Published artifacts were checked again with the workspace's installed helper and Python 3.13.

## Published artifacts

| Host | Task | Native model | Revision | Result |
|---|---|---|---|---|
| Codex | Configured distillation | GPT-5.6 Sol Ultra | `rev-distill-configured-training-20260917-01` | Passed helper validation; 20 nodes, 23 edges, 2 findings, 14 evidence records; 0 reported repair rounds. |
| Codex | Grouped cross-validation | GPT-5.6 Sol Ultra | `rev-group-cv-clean-1` | Passed helper validation; 12 nodes, 15 edges, 1 finding, 12 evidence records; 0 reported repair rounds. |
| Codex | DCGAN update cycle | GPT-5.6 Sol Ultra | `rev-dcgan-loss-cycle-20260917-1` | Passed helper validation; 16 nodes, 19 edges, 1 finding, 16 evidence records; 0 reported repair rounds. |
| Codex | Out-of-order notebook | GPT-5.6 Sol Ultra | `rev-leak-out-of-order-native-1` | Passed helper validation; 10 nodes, 8 edges, 4 findings, 10 evidence records. Final native response and repair count were not observable after UI control failed. |
| Claude Code | Configured distillation | Fable 5.1 Extra high | `dev-config-distill-r1` | Passed helper validation; 28 nodes, 41 edges, 2 findings, 42 evidence records; 0 reported repair rounds. |

The Codex notebook artifact also listed installed skill, contract, example, and helper files in its source manifest. The target notebook hash matched the prepared fixture, but those extra source entries differ from the other runs and remain part of the frozen evaluation evidence.

The [five byte-identical snapshots](../../evals/workflow/development/native-artifacts/README.md)
are checked in for inspection. Each recorded source hash matches commit
`36dbbe5597de496b9807b0e52ef232ceca1df89e`; reconstructing those files and the
frozen helper in clean temporary workspaces passed all five validations.
The installed skill's four-file SHA-256 was
`fbbdf1aa3d203b925fe9068a58e98ebfe60780db1ab3c36c5ce384ac6bc5f6a7`.
Observed host versions remain those in the [earlier same-day exercise](2026-09-17-host-retry.md).
Codex's grouped-CV artifact names its own model as `GPT-5`; the native UI showed
GPT-5.6 Sol Ultra. The UI observation is retained separately from model-authored
metadata.

The native runs used only the same task sources and frozen skill, but invocation
wrappers differed slightly between hosts. Exact submitted prompts are preserved
in the ignored local record, separately from the manifest's task question.
This exploratory batch is not a controlled accuracy comparison.

## Incomplete runs

- Copilot configured-distillation ran in native Agent Auto, which routed to GPT-5.6 Luna. It created a draft, received one validation repair round for contract field and citation issues, and reached a final citation diagnosis. No published artifact or final response was observed.
- Claude Code grouped cross-validation was submitted on Fable 5.1 Extra high and visibly entered its working state. No published artifact or final response was observed.
- The remaining five skill runs, three no-skill baselines, selected-item refinement, and Stop/partial-publication lifecycle exercise were not started or completed.

## Native UI limitation

After the fifth artifact appeared, native control returned `Computer Use server error -10005: cgWindowNotFound` three times for VS Code, including after resetting the CUA session. App inventory still listed VS Code as running, so there was no evidence that the display was locked. A documented Finder recovery attempt hung and was aborted; control of another native app was therefore not established. Existing model sessions were left intact, and UI ownership was returned for an independent recovery attempt.

An independent reconnect also timed out. No new VSIX installation, selected-item
UI round trip, or native Stop test was completed during this batch. Earlier
UI checks are recorded separately and do not stand in for these updated controls.

These results establish native invocation, model-authored publication, and
helper validation for five cases. They do not certify semantic correctness,
native discovery across all hosts, updated extension UI behavior, cancellation
handling, or marketplace installation. Human semantic review remains pending.

Provisional source review found a concrete GAN explanation error: node
`n-metrics-next` can imply that running loss sums are printed, while source lines
101–105 print current batch losses and never read the accumulators. The frozen
output is preserved unchanged as a future selected-item Challenge case.
