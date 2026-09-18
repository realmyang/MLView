# Validation of the native-only product

The static analyzer and its test/release gates were removed on 2026-09-18.
Current gates target skill publication, WorkflowDocument validation, viewer
interaction, workspace navigation and the distributed packages.

Run `sh scripts/e2e.sh` with Python 3.10+ and Node 20.18.1+ on PATH. On Windows
use `powershell -File scripts/e2e.ps1`. The [script guide](../scripts/README.md)
explains each gate and explicit skip options.

## Trust/usability campaign results — 2026-09-18

The [campaign](TRUST_USABILITY_CAMPAIGN.md) is local on `llm-workflow` based on
`d40d96e`. On macOS with Python 3.13.15 and Node 26.4.0:

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
- An auxiliary independent Sol skill exercise published and revalidated an
  artifact after one schema repair. Its scope and limitations are recorded in
  the [campaign report](TRUST_USABILITY_CAMPAIGN.md).
- Historical native artifacts, provisional ledgers, held-out source/reference
  pins, task manifest, public schema and shipped sample are unchanged.

Desktop control stalled while preparing the live viewer/browser exercise.
No native VS Code interaction, browser paint timing, screen-reader pass or
human semantic score is claimed for these changes. The task-created isolated
VS Code process and loopback server were stopped. The existing pilot summary
still reports **72 pending, zero completed, zero human-reviewed**. Earlier CI
below belongs to older commits; current local changes have no remote CI run.

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
semantic correctness. Historical host logs remain in [DEMO_LOG.md](DEMO_LOG.md),
and semantic human review remains pending.
