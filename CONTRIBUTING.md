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
`powershell -File scripts/build.ps1`; set `$env:PYTHON` to choose the
interpreter explicitly. Build scripts use locked `npm ci` dependencies. The
skill helper itself needs only Python's standard library.

## Change and verify

Edit the canonical skill in `skills/mlview/`, then run
`python tools/sync-skill.py`. Only portable files are distributed: `tests/`,
`__pycache__`, `*.pyc`, dotfiles such as `.DS_Store`, and editor backups are
never part of the skill identity, ZIPs, plugin copy or installs, and a test
fails if a tracked skill file is not portable. To try a changed skill,
reinstall it into a scratch workspace with
`python tools/install_skill.py <workspace>`. The installer's
`.mlview-install.json` manifest lets it replace unmodified files and remove
retired ones; it refuses to overwrite local edits unless you add `--force`.
Edit the viewer in `webview/src/`, run `npm run build` there, then
`python tools/sync-assets.py` from the root. The extension entrypoint and
authored panel live in `vscode-extension/src/`.

```sh
python -m pytest skills/mlview/tests tools evals scripts claude-plugin/tests -q
python tools/verify.py --all
python scripts/check_docs.py
sh scripts/e2e.sh --skip-npm-install
```

The full check type-checks and tests both TypeScript components, validates
skill distribution and evaluation records, packages both skill layouts and the
VSIX, and inspects the actual VSIX for missing assets or retired runtime code.
Use `--skip-build` only when the current outputs have already been built; it
skips `npm ci`, the viewer build and the syncs, but `npm test` and VSIX
packaging still rebuild the extension bundle. The equivalent Windows flags are
`-SkipNpmInstall` and `-SkipBuild`. CI runs these drivers with Node 20.18.1,
22, 24 and 26 and the Python suite on Python 3.10–3.14, so avoid Node APIs
newer than Node 20. See [scripts/README.md](scripts/README.md) for the gate
boundaries.

## Evaluation and review

Do not execute an analyzed project to make its diagram. The native assistant
reads source; the deterministic helper checks document structure and evidence.
Exact anchors do not establish semantic correctness. Preserve uncertainties,
counter-evidence and explicit scenario choices in model-authored artifacts.

Use [evals/workflow](evals/workflow/README.md) to compare interpretations.
Recorded native outputs and provisional reviews are immutable evidence; do not
edit their hashes or source quotations to make a test pass. A committed
evidence lock, `tools/evidence_lock.json`, pins every byte under the evidence
roots; register a new dated record with
`python tools/evidence_lock.py --add <path>`, which refuses to change an
existing entry. Development source fixtures have a hash-pinned historical path
map for replay after relocation. Human approval and live host exercises must
be reported separately from tests.

`evals/workflow/decisions/` holds the pilot owner's decisions and
`evals/workflow/pilot/<campaign>/` holds frozen campaigns, which are immutable
once committed. Never write a decision, verdict, reviewer name or
`Review: complete` into a decision file on someone's behalf; tests use
synthetic data labeled as such. The
[review guide](evals/workflow/reference-candidates/REVIEW_GUIDE.md) describes
the owner's workflow.

Capture a pilot candidate with
`python tools/workflow_candidate.py --campaign <campaign> --build-vsix`, or a
local development snapshot with `--output`; the
[candidate protocol](evals/workflow/CANDIDATE_PROTOCOL.md) explains both, the
frozen prompts and the separately planned no-skill sessions. The
[performance harness](docs/PERFORMANCE.md) measures synthetic renderer scale;
its jsdom timings are not VS Code paint or model-quality measurements.

## Pull requests

Use a feature branch based on the current target branch. Describe the user
problem, resulting behavior and validation actually performed. Keep credentials,
private sources, raw assistant histories and local test artifacts out of commits.
Include new redistributed dependency licenses in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Report security defects through [SECURITY.md](SECURITY.md).
