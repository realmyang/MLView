# Native-host validation retry — 2026-09-17

This follow-up completes the Copilot refinement and Claude Code panel checks
interrupted by computer-use connection failures in the
[initial integration campaign](2026-09-16-llm-workflow.md). These are live
compatibility checks on the configured-training sample, not held-out pilot
runs or human semantic scores. No product source changes were needed.

## Environment and installation

The environment remains macOS 26.6.2, VS Code 1.137.0, Copilot Chat 0.65.0,
Codex 26.908.40401 and Claude Code 2.1.273. Copilot used **Auto**, with its
resolved model unexposed; Claude used **Fable 5.1 Extra high**. Development
subagents used Sol, separately from these native product-backend exercises.

Copilot ran in the Extension Development Host. For Claude, the existing local
`vscode-extension/mlview-0.1.0.vsix` was installed through VS Code's native
**Extensions: Install from VSIX** command into the current profile. VS Code
reported successful installation. **MLView: Open Generated Diagram** then
opened the artifact in Claude's isolated workspace. This also exercised local
VSIX installation; nothing was published to a marketplace or remote CI.

Installed VSIX SHA-256:
`69dbcd1dfc67413df33346b368696c5c6af7c79134afa6d5f000fa17f7ffea95`.

## Observed round trips

| Check | Copilot | Claude Code |
|---|---|---|
| Resume/open | Approved the pending local helper publication in the existing conversation | Opened r1: 13 nodes, 20 edges |
| Refine through native assistant | Completed the same-chat refinement started in the initial campaign | Clicked the diagram's **Refine**, inspected the copied filename and parent revision, and submitted it in the same Claude conversation |
| Published revision | `native-copilot-rev-2`, parent `native-copilot-rev-1` | `rev-20260917-native-claude-2`, parent `rev-20260917-native-claude-1` |
| Live panel adoption | Automatically displayed r2: 15 nodes, 16 edges | Automatically displayed r2: 16 nodes, 22 edges |
| Source navigation | Selected the refined student-distribution edge and its secondary evidence; editor opened `engine.py`, line 12 | KL node/edge evidence opened `engine.py`, line 13; the new Adam-step child opened line 21 |
| Validator repair rounds for r2 | 0; an earlier patch-context retry is recorded separately | 0 |
| Independent checks | Structure, exact citations, source fingerprints and parent revision passed | Structure, exact citations, source fingerprints and parent revision passed |
| Stable IDs and source | All 13 original node IDs retained; source fingerprints unchanged | All 13 original node IDs retained; source fingerprints unchanged |

The native sessions inspected and authored artifacts without executing the
sample or invoking the legacy static analyzer. Claude's refinement also read
MLView renderer/parent-mapping source to understand grouping. Those additional
reads are compatibility-test friction and exclude this from a blind semantic
comparison. The initial Copilot session's access to the Codex example remains
another reason not to compare these outputs as independent accuracy trials.

## Artifact record

Original r1 backups and independent r2 checks are retained under the ignored
`.mlview/native-retry-baseline` directory. Native conversation workspaces and
their artifacts also remain ignored.

| Host | Publication timestamp (UTC) | r2 artifact SHA-256 |
|---|---|---|
| Copilot | `2026-09-16T23:12:45.082324Z` | `aa9bd7ff3cb7e7b12e0eb7a48a28ce05cccb4d1331722873f642a7545b501766` |
| Claude Code | `2026-09-16T23:18:04.703337Z` | `e0ec46ddb28472e67f48edb60a08f73b81247c75101da46e30d1405151064bb6` |

These timestamps fall on September 17 in the local Europe/Amsterdam timezone.
Active analysis durations and token usage were not reliably measured during
this interrupted/resumed exercise and are not estimated.

## Acceptance boundary

Together with the initial Codex exercise, all three native hosts now have
observed skill publication, real panel rendering, source navigation and
same-assistant refinement with live revision adoption. The previous connection
failures no longer block those checks. No automatic approval-review rejection
occurred during this retry.

A later optional overview-screenshot attempt again returned `cgWindowNotFound`.
That connection issue occurred after the live revision/source checks completed;
no additional screenshot-based visual review is claimed.

This does not establish all-host notebook/export/fault-injection coverage,
Windows or remote-workspace compatibility, budget/cancellation behavior, or
semantic accuracy. The [pilot review packet](../../evals/workflow/reference-candidates/README.md)
prepares the remaining human reference work; its candidates are unadjudicated
and the 72-run matrix remains pending. Automated regression results are
recorded in [LLM_IMPLEMENTATION.md](../LLM_IMPLEMENTATION.md).

## Automated acceptance retry

The full `sh scripts/e2e.sh --skip-npm-install` run initially passed 19 of 20
gates: isolated pip build dependency installation failed because the sandbox
could not resolve PyPI. All test suites and other gates passed. A subsequent
network-enabled run exited successfully: **20 gates passed, zero failed, zero
skipped**. Build completed all six steps, including isolated dependency
installation, editable install and wheel creation. Tests/build requirements
were not weakened, and sync steps reported no regenerated-file drift.

The final run passed 2,654 analyzer, 607 viewer, 434 extension and 475 Claude
plugin tests. Existing individual skips/expected failures and the viewer TODO
remain documented in the implementation record; they are not counted as
passes. The authored host/viewer handshake, parity, legacy accuracy corpus and
documentation gates also passed. Logs are retained at the ignored paths
`.mlview/host-retry-e2e.log` and `.mlview/host-retry-e2e-network.log`.
