# Validation of the native-only product

The static analyzer and its test/release gates were removed on 2026-09-18.
Current gates target skill publication, WorkflowDocument validation, viewer
interaction, workspace navigation and the distributed packages.

Run `sh scripts/e2e.sh` with Python 3.10+ and Node 20.18.1+ on PATH. On Windows
use `powershell -File scripts/e2e.ps1`. The [script guide](../scripts/README.md)
explains each gate and explicit skip options.

## Local results — 2026-09-18

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
