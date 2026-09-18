# Contributing to MLView

MLView uses the active native assistant to interpret ML code and author
WorkflowDocument diagrams. Start with the [workflow](docs/LLM_WORKFLOW.md) and
[artifact contract](docs/WORKFLOW_CONTRACT.md). The retired static analyzer is
available only in Git history; new contributions target the skill and viewer.

## Set up

Use Python 3.10+ and Node 20.18.1+. Create a virtual environment, activate it,
and install the development test dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
sh scripts/build.sh
```

On Windows activate `.venv\Scripts\Activate.ps1` and run
`powershell -File scripts/build.ps1`. Build scripts use locked `npm ci`
dependencies. The skill helper itself needs only Python's standard library.

## Change and verify

Edit the canonical skill in `skills/mlview/`, then run
`python tools/sync-skill.py`. Edit the viewer in `webview/src/`, run
`npm run build` there, then `python tools/sync-assets.py` from the root.
The extension entrypoint and authored panel live in `vscode-extension/src/`.

```sh
python -m pytest skills/mlview/tests tools evals scripts claude-plugin/tests -q
python tools/verify.py --all
python scripts/check_docs.py
sh scripts/e2e.sh --skip-npm-install
```

The full check type-checks and tests both TypeScript components, validates
skill distribution and evaluation records, packages both skill layouts and the
VSIX, and inspects the actual VSIX for missing assets or retired runtime code.
Use `--skip-build` only when the current outputs have already been built.
The equivalent Windows flags are `-SkipNpmInstall` and `-SkipBuild`.
See [scripts/README.md](scripts/README.md) for the gate boundaries.

## Evaluation and review

Do not execute an analyzed project to make its diagram. The native assistant
reads source; the deterministic helper checks document structure and evidence.
Exact anchors do not establish semantic correctness. Preserve uncertainties,
counter-evidence and explicit scenario choices in model-authored artifacts.

Use [evals/workflow](evals/workflow/README.md) to compare interpretations.
Recorded native outputs and provisional reviews are immutable evidence; do not
edit their hashes or source quotations to make a test pass. Development source
fixtures have a hash-pinned historical path map for replay after relocation.
Human approval and live host exercises must be reported separately from tests.

Capture and verify the full candidate bundle with
`python tools/workflow_candidate.py`; the [candidate protocol](evals/workflow/CANDIDATE_PROTOCOL.md)
explains snapshots and separately planned no-skill sessions. The
[performance harness](docs/PERFORMANCE.md) measures synthetic renderer scale;
its jsdom timings are not VS Code paint or model-quality measurements.

## Pull requests

Use a feature branch based on the current target branch. Describe the user
problem, resulting behavior and validation actually performed. Keep credentials,
private sources, raw assistant histories and local test artifacts out of commits.
Include new redistributed dependency licenses in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Report security defects through [SECURITY.md](SECURITY.md).
