# Development native retry — 2026-09-17

This retry exercised MLView through native VS Code assistants against isolated source workspaces. Each source workspace contained only the target source and its host-specific installed skill. Prompts prohibited importing or executing the target, invoking the legacy analyzer, using subagents, or inspecting earlier artifacts. The raw machine-local evidence is retained under `.mlview/sprint-20260917/`; this log omits private absolute paths.

## Observed results

By the end of this retry, seven initial skill artifacts had been published and independently validated with the installed helper. Five came from the first attempt; Copilot configured training and Claude grouped cross-validation completed during this retry:

| Host | Task | Revision | Artifact SHA-256 |
|---|---|---|---|
| Codex | configured training | `rev-distill-configured-training-20260917-01` | `8607f0bc268a898294b2fc0dd5ab01a7e11d0917c47947c8d66c703ef4be2ab7` |
| Codex | grouped cross-validation | `rev-group-cv-clean-1` | `a80aae6a88e5d1a603e423cee8c986c635f7efe560457912225406cd549e755a` |
| Codex | DCGAN | `rev-dcgan-loss-cycle-20260917-1` | `feb87853568777b3bc24cef099c7112167574070191c8e5e925b4217a4e7135c` |
| Codex | notebook execution order | `rev-leak-out-of-order-native-1` | `315993b9f909f79b7b03e32aa3d8b60f6ed5cf076239bca753be51e78229ab5a` |
| Copilot | configured training | `rev-distill-1` | `f2ab3caf7a59497a41dc33b356c800c4a67b571fa9cd5892c514ffa7a0f05e78` |
| Claude Code | configured training | `dev-config-distill-r1` | `a5d7ae7311c6ed1d24b8ba3c3449cf5ba3793b275521eb12cad3d71e777c43ab` |
| Claude Code | grouped cross-validation | `dev-sklearn-r1` | `ec84f1eca09cfdc15c1f86523280e25a255165825e4cfd65f4df26aa4e070a7f` |

The original Codex DCGAN artifact remains preserved unchanged. A same-assistant viewer-generated refinement corrected the selected metrics node so cumulative running sums are distinguished from current-batch losses printed by the cited lines. Revision `rev-dcgan-loss-cycle-20260917-2` validated with SHA-256 `e57927985012ab9f45da9c80db9fa5a7025f5a1c54d745011476cfa31c47f175`. All unaffected phase, node, edge, finding, and evidence IDs were preserved.

Copilot's grouped-cross-validation retry was still in progress when desktop control failed. Copilot Auto routed it to `MAI-Code-1.1-Flash`; the assistant reviewed four files, created a draft, and began repairing schema and citation mismatches reported by the helper. No final artifact or response was observed, so this case remains `running` in the raw checkpoint rather than being counted as completed. The Claude Code DCGAN workspace was trusted, but the native assistant never opened and no prompt was submitted; that case is recorded as `not_started`.

## Viewer and lifecycle observations

The first tested VSIX rebuild, SHA-256 `fab55253feba1fbaff42b48322ba905219cc1c5b5ea77972b6c58af0fdbb51a6`, installed successfully over the existing MLView extension in a completed test workspace. Node and finding selection produced host-owned refinement prompts. Edge activation exposed a remount bug: opening cited source and returning to the diagram cleared selection.

An immediate Stop control check showed `You stopped after 0s`; this only proves the control path. A separate meaningful refinement entered a visible working state, opened cited source, and was stopped after roughly 18 seconds of observed inspection before publication. The UI still reported `You stopped after 0s`. The discrepancy is retained verbatim. The published r2 artifact hash and viewer revision remained unchanged, and no child revision was accepted.

A subsequent rebuild fixed selection-state initialization and passed automated edge-remount coverage. Its VSIX SHA-256 is `d2749561f81af9b25030dd74b0b0884302f993d92fa766dc4df9ef9b4f5b0933`. Installation and the live edge-selection → source-open → diagram-return → refinement-prompt acceptance check remain pending because CUA repeatedly returned `cgWindowNotFound` while VS Code was still listed as running.

After the fix, the full local end-to-end run passed all 20 gates with zero failed or skipped gates; existing individual test skips and TODOs remain. It used network access for isolated build dependencies and did not change the VSIX hash. The complete log is `.mlview/sprint-20260917/retry-e2e.log`. These automated results do not replace the pending live remount acceptance check.

## Limits

The cumulative batch contains seven completed initial artifacts, one validated same-assistant child revision, two distinct Stop observations, one partial Copilot run, and one prepared but unstarted Claude Code case. Five skill cases and all three no-skill baselines remain pending. A native partial-overview publication was not observed. Filesystem validation cannot certify native skill discovery, assistant model behavior, extension UI state, or a live remount path; only the UI observations above support those claims. Human semantic adjudication remains pending, and this batch carries no accuracy score.
