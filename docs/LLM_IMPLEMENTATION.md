# LLM workflow implementation status

The user approved [the direction plan](LLM_DIRECTION_PLAN.md) on 2026-09-16.
Implementation is on the `llm-workflow` branch. Consult the branch's pull request
checks for revision-specific remote CI results; the local measurements below
are separate evidence. The repository's earlier accuracy measurements and CI
run IDs apply to the legacy static product.

## Implemented components

| Component | Responsibility |
|---|---|
| [Portable skill](../skills/mlview/SKILL.md) | Native assistant discovery, scenario selection, interpretation, citations, critique, bounded repair and refinement |
| [Artifact helper](../skills/mlview/scripts/artifact.py) | Structure/reference checks, exact source excerpts, file hashes, notebook anchors, revision guard and atomic publication |
| [WorkflowDocument contract](WORKFLOW_CONTRACT.md) | Compact model-authored nodes, relationships, groups, phases, findings, uncertainty and coverage |
| [Viewer adapter](../webview/src/workflow.ts) | Separate authored normalization and shared interactive renderer |
| [VS Code authored panel](../vscode-extension/src/authoredPanel.ts) | Artifact open/restore/update, workspace ownership, freshness, source navigation, refinement and exports |
| [Installer](../tools/install_skill.py) | Self-contained workspace skill installation |
| [Distribution checks](../tools/test_package_skill.py) | Reproducible ZIPs, canonical content parity and extracted-helper publication outside the checkout |
| [Evaluation protocol](../evals/workflow/README.md) | Development tasks, pinned held-out pilot tasks and honest run records |

The new artifact lifecycle bypasses legacy static analysis. Legacy MLGraph 1.0,
CLI/MCP tools and reports retain their compatibility contracts. No native host
model API or credential is accessed by the MLView extension.

The September 17 follow-up adds selection-aware refinement for nodes, edges
and findings. The composer captures its target when opened, offers Explain,
Expand, Challenge, Trace and custom intent, and copies a host-validated prompt
with scenario, bounded evidence lists, parent revision and stable-ID guidance.
The viewer displays the artifact's entrypoints and configuration. Its authored
basis labels do not invent numeric confidence scores.

The portable skill now records default scenario assumptions and can publish a
validated partial overview with explicit remaining work. An interrupted host
turn leaves the last published revision intact. The installer has a read-only
`--doctor` check, both ZIP layouts have repeatable bytes, and CI is configured
to upload both ZIPs with the wheel and VSIX. These local installation checks do
not establish discovery or usability in a native assistant.

## Acceptance boundaries

M0's direction and evaluation setup are recorded. The M1–M3 implementation
includes the artifact/viewer slice, rich evidence, configuration and notebook
support, review/refinement, and stale-result handling. Completion of their
live acceptance gates is recorded separately from implementation and unit tests.
M4's 72-run pilot is not complete; no semantic-accuracy percentage is claimed.

The [integration log](demo-logs/2026-09-16-llm-workflow.md) and
[completed retry](demo-logs/2026-09-17-host-retry.md) record native Codex/Sol,
Copilot and Claude Code skill invocations. All three published valid artifacts,
opened them in the real VS Code panel, navigated to source, and refined them in
the same assistant with live revision adoption.
Codex published the [12-node example](../samples/configured_training.mlview.json)
with exact citations and zero validator repair rounds, then refined it to 15
nodes while preserving all original IDs. Live source and notebook navigation,
SVG export, stale evidence, invalid/obsolete updates, and restore checks passed.
The retry completed Copilot r2 (15 nodes, 16 edges) and Claude r2 (16 nodes,
22 edges), each retaining all 13 original node IDs and unchanged source
fingerprints. Both had zero validator repair rounds for r2. Claude's panel
exercise also verified installation of the built VSIX through VS Code.
This is development evidence; notebook, export and fault-injection checks were
not repeated in every host, and no semantic accuracy score is claimed.

Tests run with Python 3.13 and Node 26 here; they are not evidence for the older
supported runtime matrix or another operating system.

## Local verification — September 16–17

| Check | Observed result |
|---|---|
| Analyzer suite | 2,654 passed; 9 skipped; 24 expected failures |
| Shared viewer suite | 607 passed; 1 existing TODO; no failures |
| VS Code extension suite, after live UI fixes | 434 passed |
| Claude plugin suite | 475 passed; 6 skipped; 3 expected failures |
| Skill helper, installation, distribution parity and evaluation tests | 24 passed, plus 4 subtests |
| Eight developer workflow scenarios | All published artifacts passed structure, exact citations and current-source fingerprint checks; semantic review pending |
| Authored UI/host integration | Actual bootstrap, viewer bundle and host handlers passed source-click, refinement, SVG-save and revision tests with mocked VS Code APIs |
| Native artifact rendering | Actual built viewer rendered all declared nodes from Codex, Copilot and Claude outputs and exported SVG revision provenance in jsdom |
| Documentation | Self-test and living-document gate passed after removing stale legacy README assumptions |
| Copy/interface parity | All 10 gates passed |
| Distribution build | VSIX and both standalone skill ZIPs built; bundled files match current source |
| Full acceptance retry | All 20 e2e gates passed; zero failed or skipped gates; build completed all six steps |

The September 17 network-enabled retry of
`sh scripts/e2e.sh --skip-npm-install` completed **20 of 20 gates**, with zero
failed or skipped gates. It includes build, all component suites, wheel
installation, rendering, export, authored cross-host handshake, parity, legacy
accuracy and documentation checks. Existing individual test skips, expected
failures and the viewer TODO remain as listed above. The ignored complete log
is `.mlview/host-retry-e2e-network.log`.

Earlier full attempts passed 19 of 20 gates: the initial campaign encountered
a stale documentation self-test, which was corrected; the first September 17
retry encountered PyPI DNS restrictions during isolated build dependency
installation. The final run enabled dependency-download access and passed
without changing tests or removing build isolation. Asset, core, rule-doc and
walkthrough sync reported zero regenerated changes.

The local VSIX is `vscode-extension/mlview-0.1.0.vsix`. Standalone distributions
are `.mlview/dist/mlview-skill-shared.zip` and
`.mlview/dist/mlview-skill-claude-code.zip`. These are ignored build outputs,
not published releases. [The usage guide](LLM_WORKFLOW.md) explains installation.

[Development run notes](../evals/workflow/DEVELOPMENT_RUNS.md) preserve the eight
scenarios' counts, critique corrections and validator repairs. The first smoke
incorrectly framed correct teacher freezing as a finding; this informed the
skill's finding guidance. Successful validation did not detect that semantic
mistake, which is why human adjudication remains a separate gate.

## Follow-up verification — September 17

The quality sprint reproduced all **20 of 20 end-to-end gates**, with zero
failed or skipped gates, after rebuilding the selection-aware viewer and VSIX.
The analyzer and Claude suite totals stayed at 2,654 and 475 passes; the viewer
reported 607 passes and one existing TODO; the extension reported 437 passes.
Existing individual skips and expected failures are unchanged from the table
above. Both TypeScript checks and all 10 parity gates passed. The complete
ignored log is `.mlview/sprint-20260917/e2e.log`.

The helper, installation, packaging, copy-parity and evaluation suite then
passed **41 tests plus four subtests**. This includes a fresh-root review check
with no ignored development artifacts and SHA-bound response/UI evidence for
recorded native runs. Four checked-in artifact snapshots are byte-identical to
their original development outputs; they contain only the repository's own
fixture analysis and have been checked for private paths and credentials.

The VSIX contains 182 files and measures 914.67 KB. Its local SHA-256 is
`fab55253feba1fbaff42b48322ba905219cc1c5b5ea77972b6c58af0fdbb51a6`.
The renderer SHA-256 is
`68175c0f8a41b5a323eda09b8e1be3f3be52d54961c780bf7765791568bdb17b`.
These identify the locally tested build, not a marketplace release.

Four [provisional development reviews](../evals/workflow/development/README.md)
separate false defect claims, overextended evidence, omitted behavior and
usability questions. They are model-authored review drafts with pending human
decisions. The [pilot protocol](../evals/workflow/README.md) now requires an
adjudicated 24-run first stage before the 48 repeats can begin. No held-out
session has been launched by this sprint.

## Remaining validation

- Extend the basic all-host round trip to the remaining notebook, export,
  fault-injection and budget/cancellation checks in [the runbook](LLM_WORKFLOW.md);
  do not infer these untested combinations from the Codex exercise.
- Human semantic adjudication is required for the development tasks and the
  held-out benchmark. Valid citations alone do not establish supported claims.
  Eight source-linked [reference candidates](../evals/workflow/reference-candidates/README.md)
  and a proposed common run policy are ready for review; all 72 pilot records
  remain pending, with no human-reviewed runs.
- Remote workspaces and Windows need live checks before being advertised.
- Authored Problems, CodeLens, static fixes and suppression remain disabled.
  Cross-assistant prompt submission is outside the first release; refinement
  stays in the assistant that authored the diagram.
