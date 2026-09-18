# LLM workflow integration — 2026-09-16–17

> **Follow-up:** the interrupted Copilot and Claude checks described below
> completed in the [September 17 retry](2026-09-17-host-retry.md). This initial
> log retains the outcomes and limitations observed before that retry.

Local implementation on `llm-workflow`, based on `317930d`. This records observed
behavior and separates it from remaining acceptance work. No remote CI or
release was performed for this branch.

## Environment

- macOS 26.6.2 (25G83), Apple Silicon.
- VS Code 1.137.0; Codex extension 26.908.40401.
- Bundled GitHub Copilot Chat 0.65.0; registered Claude Code extension 2.1.273.
- Native test model: **GPT-5.6 Sol Ultra**, confirmed in the UI.
- Python 3.13.15 from the project venv; Node 26.4.0.
- MLView extension 0.1.0, local development build.
- Isolated test workspace under the gitignored `.mlview` directory. Only
  first-party sample files and the self-contained skill were copied into it.

## Native Codex skill exercise

The native Codex picker discovered the workspace's `mlview` skill. The test
explicitly selected Sol, invoked that skill, and asked it to inspect
`samples/configured_training` with `configs/distill.json`, without executing or
importing the target or using the static analyzer.

Observed UI progress showed the skill being read, native file inspection,
artifact authoring, self-critique, validation, and publication. Its critique
corrected a graph ordering ambiguity before validation: validation follows a
completed epoch, rather than appearing after each optimizer step.

The result is preserved verbatim at
[samples/configured_training.mlview.json](../../samples/configured_training.mlview.json):

- Revision `native-codex-configured-training-r1`.
- 12 nodes, 18 edges, zero severity findings; about six minutes to publication.
- Publication timestamp `2026-09-16T21:49:17.821947Z`.
- SHA-256 `9c1c676604c52e424b3985ab82fdd51d3a7c323316aed5a9a1f22fe6ba6e88d6`.
- First validation succeeded; zero validator repair rounds.
- Six materially inspected files are fingerprinted. External tensors and
  checkpoints remain unknown; the training-to-inference checkpoint handoff is
  explicitly inferred. Usage/token data was not exposed or recorded.

The parent independently revalidated this file against the checked-in source
and JSON Schema. It is a native Codex development example, **not** a held-out
pilot result or human-scored accuracy measurement.

## Real VS Code panel exercise

An Extension Development Host opened **MLView: Open Generated Diagram**,
selected the earlier Sol-authored development artifact, and visibly rendered
the workflow, phases, group, cyclic connections, basis, coverage and findings.
Selecting the KL-loss node displayed its exact source excerpt in the Inspector.

The first real source-button click exposed a capability-handshake bug: a second
`init` frame replaced the viewer's capabilities with an incomplete object.
The implementation now sends the complete authored capability set. An automated
integration test executes the actual panel bootstrap, viewer bundle, and host
handlers together; it verifies real DOM clicks reach source navigation,
refinement clipboard, SVG saving, and revision adoption. This is stronger than
handcrafting independent messages on each side, but still uses a mocked VS Code
API. The subsequent live checks below independently exercised the fix.

The computer-use connection temporarily stopped exposing a VS Code window and
returned `cgWindowNotFound`. Reconnecting by app name and bundle ID, inventory
refresh, and a session reset did not restore it. The published native artifact
was confirmed and validated from disk. Access recovered later in the same
campaign; the following checks then completed in the real development host:

- Reopened the native Codex artifact and followed the KL-loss evidence to
  `engine.py`, line 13. Multiple evidence targets were visible in the Inspector.
- Opened the developer notebook artifact and navigated to cell 4 (zero-based
  cell index 3), with the selected backward/optimizer-step source. No cell ran.
- Exported a 29,199-byte SVG through the native save dialog. The saved file
  contains the native revision provenance.
- Used **Refine**, inspected the copied prompt, and submitted it in the same
  Codex/Sol conversation. It published `native-codex-configured-training-r2`,
  parented to r1, with 15 nodes and 20 edges. All 12 original node IDs survived;
  the additional steps separate blending, backward and optimizer update. The
  live panel displayed the new revision, and independent helper validation
  confirmed current fingerprints and exact citations.
- Supplied the older r1 artifact while r2 was displayed: the panel rejected it
  and retained r2. Restored the valid r2 afterward.
- Supplied malformed notebook JSON: the panel retained its last valid graph
  and displayed the parse error. Restoring the original cleared the error.
- Changed the isolated config's alpha from 0.6 to 0.7: the panel reported one
  stale verified file and stopped the configuration-edge source jump. Restoring
  the original bytes cleared the stale state.
- Reloaded the final extension build: diagrams restored, the status bar read
  **MLView Legacy**, and the unsupported standalone-HTML button was absent.

The original r1 remains the checked-in example. Refinement outputs and transient
fault-injection files stay in the ignored test workspace; sample source was
restored exactly. Windows, remote workspaces and budget/cancellation behavior
were not exercised by this live session.

## Native Copilot skill exercise

VS Code's native Agent chat discovered `/mlview` from the same `.agents` skill.
Model selection was **Auto**; the resolved model was not exposed, so the artifact
omits it. Native source reads and installed-helper validation/publication were
observed, with ordinary per-command approvals and no target execution.

It published `native-copilot-rev-1`: 13 nodes (including a group), 13 edges and
one unadjudicated finding, after one citation-reference repair. The assistant's
prose counted 12 steps; the artifact count here includes its group. Independent
helper validation passed. The common panel rendered its Copilot provenance and
opened its loss evidence at `engine.py`, line 12.

This was a compatibility exercise, not a semantic benchmark: the workspace
already contained the Codex sample, which Copilot reported reading as context.
That contamination excludes it from an independent quality comparison.

A same-chat refinement authored a draft parented to r1 with separate loss
children. A patch-context mismatch was repaired before validation. The final
publication/visible adoption was not completed: computer use again returned
`cgWindowNotFound`, preventing further native approval interaction. The last
published Copilot artifact remains r1; no r2 success is claimed.

## Native Claude Code skill exercise

A separate first-party workspace contains only the configured-training source
and `.claude/skills/mlview`, with no `.agents` duplicate or previous artifacts.
Native Claude Code discovered `/mlview` as a project skill. Its UI showed
**Fable 5.1 Extra high**. The request prohibited subagents, target execution and
static analysis. Source/config inspection and reading the contract/helper were
observed. Publication subsequently completed and was confirmed from the task's
local session record and filesystem while computer use was unavailable:

- Revision `rev-20260917-native-claude-1`; producer `claude-code` /
  `claude-fable-5-1`.
- 13 nodes, 20 edges, one low-severity unadjudicated finding, 32 exact evidence
  records, and six inspected-file fingerprints.
- First validation and publication succeeded; zero repair rounds. Independent
  post-publication validation also passed.
- The finding concerns hard-coded inference construction; the selected config
  is retained as counter-evidence because it currently agrees. This records
  model output, not a verified defect or human severity judgment.

The actual built viewer mounted each of the three native artifacts in jsdom,
rendered every declared node, and exported SVGs with the correct revision
provenance. The full authored bootstrap/host handshake also passed after the
final capability change. These are automated renderer checks. Claude's real
panel navigation and same-chat refinement remain unverified, as does Copilot's
refinement publication. The connection error is a computer-use limitation,
not an automatic approval-review rejection or an observed MLView failure.

## Local automated validation

The current verification totals are recorded in
[LLM_IMPLEMENTATION.md](../LLM_IMPLEMENTATION.md). The initial integration run
caught a renderer-hash fixture update and a stale documentation self-test; both
were corrected without changing the legacy graph's semantic content. Isolated
Python build dependency downloads initially failed under the network sandbox;
the final acceptance run uses approved dependency access.

The deterministic checks cover contract and citations, malformed input and
paths, publication locking and revisions, installed copies, custom phases,
multiple evidence anchors, source-less concepts, unsaved notebook cells,
historical stale artifacts, and actual authored UI/host message compatibility.
They do not score the semantic truth of model outputs.

The [evaluation manifest](../../evals/workflow/tasks.json) reserves eight
development tasks and eight pinned pilot tasks. Development subagent artifacts
are explicitly recorded as such; the 72 native-host pilot runs and human
reference/adjudication work remain outstanding.
