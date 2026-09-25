# Validation of the native-only product

The static analyzer and its test/release gates were removed on 2026-09-18.
Current gates target skill publication, WorkflowDocument validation, viewer
interaction, workspace navigation and the distributed packages.

Run `sh scripts/e2e.sh` with Python 3.10+ and Node 20.18.1+ on PATH. On Windows
use `powershell -File scripts/e2e.ps1`. The [script guide](../scripts/README.md)
explains each gate and explicit skip options.

## Campaign 1 local checks — 2026-09-25

Campaign 1 ("reliability and trust", version 0.2.0; see the
[changelog](../CHANGELOG.md)) was checked on commit `f4932c7` of the
`c1-integration` branch. **These are local automated checks on one macOS
machine** (Darwin 25.6.0, Node 26.4.0, npm 11.17.0, Python 3.13.15). CI has not
run on this commit, so its result is pending. Node 20.18.1 and 22, Windows,
Linux and Python 3.10–3.12 were not exercised. Nothing here is live-host
(Extension Development Host) validation, a native assistant run, human review
or semantic accuracy.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**. The gate sets `MLVIEW_REQUIRE_PYTHON=1`,
  so the refine-wedge regression ran the real helper instead of skipping.
- Python helper, distribution and evaluation tests: **178 passed, 311 subtests
  passed, 2 skipped**. Both skips need the unavailable Claude CLI; they are not
  plugin validation passes. The conformance runner
  (`tools/test_workflow_conformance.py`, 12 tests, 232 subtests) and the
  recorded-artifact guard (1 test, 23 subtests) are included.
- Viewer: **69 passed**, including the rewritten host, bootstrap and bundle
  handshake, bundle hygiene and the routed-geometry golden.
- Extension: **197 passed**, including revision lineage (31), panel lineage
  (12), the refine wedge with the real helper (6), host protocol (8),
  bootstrap (2), export payloads (4), recorded artifacts (3) and the
  conformance runner (53: every corpus case, the parity checks and the
  helper-publish, viewer-load round trip).
- Both eight-file skill ZIPs were packaged. The actual VSIX had **11 files,
  153,398 bytes**, with no analyzer or Python runtime payload and only
  `mlview.openGeneratedDiagram` contributed.
- Portable skill bundle identity (`sha256-sorted-path-nul-bytes-nul` over the
  eight files): `e54a31355b89c41c6e042fc1c23655405d66877c48ba7702275df8a6d89863d0`.
  Built viewer: `mlview.js` SHA-256
  `3d602e3334c06d90d3886b0be784ca6644bff039e64b7c1944c3bf72db0c85ad`,
  `mlview.css` SHA-256
  `e43c14dec5968faf86c28993dbbe8c39c35b334e9f6589c817d1ed286daa6185`.
- After the gate rebuilt everything, `git diff --exit-code` over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview` was clean.
- The 2026-09-25 review's critic reproductions were re-run on scratch copies
  against this build. A changed installed-skill file no longer makes a diagram
  stale: no banner, and navigation opens `train.py`. A `"parent": null` node is
  rejected by both the helper and the extension. A workflow-level finding stays
  listed under both phase filters and under `stage:train`.

The commit that adds this record changes only this file and STATUS.md. Still
outstanding: CI on this commit, the manual live-host checklist (Refine with
each intent, HC Dark and HC Light, a BOM source open while publishing, a
symlinked root, a mixed-case Windows drive letter), Windows/Linux live
interaction, the human reference review and the held-out pilot.

## Live usability and CI follow-up — 2026-09-18

The maintainer authorized committing/pushing the campaign and completing live
viewer checks. `84ea3a1` published the campaign. Remote CI exposed a Windows
absolute path rejection, fixed in `7182224`; its push run passed. Its PR run
exposed a fixed-delay test race, now replaced with a bounded wait for the
settled state.
These earlier run outcomes do not validate the later changes described below.

The final local command was
`PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
**all 15 exercised gates passed**. Python: **122 passed, 24 subtests passed,
2 skipped** (unavailable Claude CLI). Viewer: **32 passed**. Extension:
**43 passed**. Both skill archives passed; the actual VSIX had **11 files,
141,149 bytes**, with no retired analyzer/runtime payload. Documentation checks
and `git diff --check` passed. At that point the eight-file portable skill SHA-256 was
`b251ac3774a453473ccf501643f56eb2ca826640d713903666add9c9e93c5b7f`.

Live checks used an isolated VS Code 1.138.0 Extension Development Host on
macOS, with the actual extension, built viewer and synthetic source/artifacts.
The workspace stayed in Restricted Mode. Native VS Code API commands opened
the diagram; Chromium debugging controlled its real rendered UI and keyboard
events. The fixture was synthetic; no native assistant or target ML code was
executed.

- The Outline enumerated all three nodes and both directed relationships;
  authored basis labels and search wording were checked in the rendered UI.
- Arrow-key/End navigation selected and focused the correct side tabs; Tab
  moved into the panel. This fixed the missing tablist keyboard behavior.
- The edge inspector displayed both quotes. Source navigation reached line 2;
  Previous evidence returned to line 1 with the expected boundary states.
  The source-column fix kept the diagram visible instead of opening a duplicate
  source tab over it. Notebook column selection has regression coverage, but
  this live exercise used Python source.
- Challenge opened a composer for the selected `output` edge. Support and
  counter-evidence remained distinguishable. A finding without associated nodes
  was inspectable with its coverage limitation.
- A structurally invalid revision retained the valid diagram. The native
  validator now matches the helper's evidence requirement, including the
  conceptual-parent exception. Unsaved source changes blocked a stale update
  and evidence navigation; restoring the source cleared the warning and adopted
  the child revision.
- Dark/high-contrast screenshots were inspected. Light theme switching was
  confirmed. Closing the narrow-screen side drawer and fitting the view put all
  three node rectangles inside the canvas. Accessible names were inspected in
  Chromium's accessibility tree; this is **not a spoken screen-reader pass**.

Focused Chrome cold/warm profiling and native VS Code scale measurements
completed through **2,000 represented nodes** with corrected, canonically
validated synthetic fixtures. The earlier generator had invalid host/evidence
values; it is now corrected and guarded by all-size reference/basis tests.
See [PERFORMANCE.md](PERFORMANCE.md) for source hashes, timing definitions,
the routing bottleneck and measurement limits. No performance optimization or
semantic accuracy gain is claimed from these observations.

Windows/Linux/remote live interaction, spoken assistive-technology testing,
and matched native-model experiments remain separate work. The
[human reference review](../evals/workflow/reference-candidates/REVIEW_GUIDE.md)
and held-out pilot remain pending; neither green tests nor these UI checks
provide semantic adjudication.

## Trust/usability campaign results — 2026-09-18

The initial [campaign](TRUST_USABILITY_CAMPAIGN.md), later committed as `84ea3a1`,
was based on `d40d96e`. On macOS with Python 3.13.15 and Node 26.4.0:

- `PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **15 exercised gates passed**, with a fresh build and generated-copy checks.
- Python: **122 passed, 24 subtests passed, 2 skipped**. The two skips require
  the unavailable Claude CLI; they are not live plugin validation passes.
- Viewer: **30 passed**. Extension: **40 passed**. These include evidence and
  relationship navigation, current-selection challenge prompts, coalescing,
  concurrent-change/disposal guards and notebook freshness behavior.
  The extension suite also passed after adding automatic temporary-workspace
  cleanup to the panel and workflow-validator tests. The latter rerun left
  zero new matching temporary directories.
- Both eight-file skill ZIPs and the actual VSIX passed packaging checks.
  VSIX: **11 files, 140,584 bytes**, no analyzer or Python runtime payload.
- Skill Creator `quick_validate.py`, candidate snapshot creation/drift check,
  and `git diff --check` passed. The snapshot covers all eight portable skill
  files; it explicitly does not approve a pilot.
- Four separate-process jsdom benchmarks completed at 100/500/1,000/2,000 nodes
  with node representation, scope/reset, SVG export and disposal assertions.
  See [exact bundle identity, timings and limits](PERFORMANCE.md).
- An independent skill exercise by an auxiliary Codex agent (gpt-5.6-sol)
  published and revalidated an artifact after one schema repair. Its scope and
  limitations are recorded in the [campaign report](TRUST_USABILITY_CAMPAIGN.md).
- Historical native artifacts, provisional ledgers, held-out source/reference
  pins, task manifest, public schema and shipped sample are unchanged.

The first attempt to automate the live VS Code exercise stalled during setup.
No native VS Code interaction, browser paint timing, screen-reader pass or
human semantic score is claimed for these changes. The isolated VS Code process
and loopback server started for that attempt were stopped. The existing pilot
summary still reports **72 pending, zero completed, zero human-reviewed**.
These initial results are superseded by the follow-up above where explicitly
stated.

## Static-removal baseline — 2026-09-18

On macOS with Python 3.13.15, Node 26.4.0 and npm 11.17.0:

- `sh scripts/e2e.sh --skip-npm-install`: **15 exercised gates passed**.
  Existing locked npm dependencies were reused; the viewer and extension were
  freshly rebuilt, type-checked, tested and packaged.
- Python helper, installer/distribution, evaluation and script tests:
  **102 passed, 16 subtests passed, 2 skipped**. Both skips require the absent
  Claude CLI; they are not plugin CLI validation passes.
- Viewer: **21 passed**, including authored layout, cycles, grouping, search,
  scope, source navigation, refinement, revision updates and SVG export.
- Extension: **30 passed**, including activation, workspace evidence validation,
  authored panels and packaging.
- Both standalone skill ZIPs built successfully. The actual VSIX passed payload
  checks: **11 files, approximately 135 KiB**, required licenses and current
  bundles present, no Python analyzer/runtime or static analysis commands.
- `python tools/verify.py --all`, `python scripts/check_docs.py`, YAML parsing
  and `git diff --check` passed. All retired runtime roots are absent.
- Recorded development/native/follow-up artifacts and the shipped sample are
  unchanged. Relocated example files retain their original SHA-256 values.

The rewritten CI matrix passed all eight jobs for `5319777`: Python 3.10–3.13,
Node 20.18.1/22 and Linux/Windows/macOS package checks, in both the
[push run](https://github.com/realmyang/MLView/actions/runs/35329824132) and
[pull-request run](https://github.com/realmyang/MLView/actions/runs/35329828241).
Earlier analyzer suite counts and CI runs refer to older revisions.

No automatic test claims live assistant discovery, native model execution or
semantic correctness. Dated host logs are in [docs/demo-logs/](demo-logs/),
and semantic human review remains pending.
