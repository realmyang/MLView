# Build and validation scripts

Python 3.10+ and Node 20.18.1+ are required for development. The skill helper is
standard-library-only; tests require `pip install -r requirements-dev.txt`,
which pins the exact `pytest` and `jsonschema` versions CI uses.

| Command | What it proves |
|---|---|
| `sh scripts/build.sh` | Locked npm dependencies, viewer build, synchronized copies, extension compile, type checks and current docs |
| `sh scripts/e2e.sh` | Build plus Python and TypeScript suites, skill ZIP packaging and actual VSIX payload checks |
| `pwsh -File scripts/e2e.ps1` (or `powershell -File`), `scripts/build.ps1` | The same gates on Windows |
| `python tools/verify.py --all` | Matching skill/viewer copies and a schema-valid example, matching component versions, no retired analyzer surfaces |
| `python scripts/check_docs.py` | Active documentation links and local shell line endings |
| `python scripts/vsix_check.py [file.vsix]` | Required assets, native commands, current bundles, size ceiling and no Python analyzer payload; a missing working-tree bundle is reported as a problem (build first) |
| `python scripts/vsix_check.py --payload-only [file.vsix]` | The payload checks without comparing bundles to the working tree; prints `SKIP: bundle freshness not compared (--payload-only)` for each skipped comparison |
| `python tools/workflow_candidate.py --campaign pilot-01 --build-vsix` | Pilot candidate (version 2) from a clean tree: builds the VSIX into `$MLVIEW_PILOT_DIR`, pins distributed bytes and the frozen campaign, writes `evals/workflow/pilot/pilot-01/candidate.json`; no human approval |
| `python tools/workflow_candidate.py --check <candidate.json> [--vsix <file.vsix>]` | Verifies a candidate against its source commit and reports drift at HEAD |
| `python tools/workflow_candidate.py --output .mlview/candidate.json` | Local development snapshot (dirty tree allowed, VSIX optional); never identifies a pilot campaign |
| `python tools/fetch_workflow_repos.py [--repo NAME]` | Network fetch of the pinned sparse checkouts in `.public-corpus`; refuses dirty or differently pinned checkouts rather than resetting them |
| `python tools/fetch_workflow_repos.py --verify [--json]` | Read-only check of every checkout: pinned HEAD, clean state, sparse patterns and blob-exact files |
| `python tools/fetch_workflow_repos.py --update-sparse` | Applies changed sparse patterns to clean checkouts at their pins, refusing to drop a covered file; may fetch newly included blobs |
| `node --expose-gc webview/tools/benchmark-workflow.mjs` | Synthetic scale timings and representation/disposal checks; not browser paint |

Both shell drivers delegate to `scripts/check.py` after picking an
interpreter that reports Python 3.10+: `PYTHON` when set, otherwise
`python3` then `python` (`python`, `python3`, `py` in Windows shells). The
PowerShell drivers `scripts/build.ps1` and `scripts/e2e.ps1` honor
`$env:PYTHON`, which must pass that check, and otherwise try `python`,
`py -3` and `python3`, skipping the Microsoft Store alias under
`\WindowsApps\`. CI runs the native drivers: `sh scripts/e2e.sh` on Linux and
macOS and `pwsh -File scripts/e2e.ps1` on Windows, with the same 17 gates. It
runs the Python suite on Python 3.10–3.14 and the drivers with Node 20.18.1,
22, 24 and 26.

`--skip-npm-install` reuses existing node_modules: the two `npm ci` steps do
not run, are not printed as skipped and are simply absent from the gate count (15 exercised gates instead of 17 for a
full e2e run). `--skip-build` (e2e only) skips `npm ci`, the viewer build, both
syncs and the extension compile, and prints `SKIP:`. It does not freeze the
outputs: `npm test`'s pretest still rebuilds the extension bundle (and checks
the notices copy), and VSIX packaging recompiles the extension, rewriting its
bundle and `THIRD_PARTY_NOTICES.md`. Steps that did not run are never counted
as successful gates. The PowerShell flags are `-SkipNpmInstall` and
`-SkipBuild`.

The strict Claude plugin validation test skips when the `claude` CLI is not
installed; set `MLVIEW_REQUIRE_CLAUDE_CLI=1` to make a missing CLI a failure
instead.

Tests create temporary skill archives and a temporary VSIX and remove them on
completion. To retain packages for installation, run `npm run package` inside
`vscode-extension/`, and `python tools/package_skill.py --host shared` or
`--host claude-code` from the root. Skill archives go under `.mlview/dist/`.

These checks establish structural and distribution correctness. They do not
call an LLM, judge interpretation quality, or prove native assistant discovery
and live VS Code interaction. Use the [live checklist](../docs/LLM_WORKFLOW.md)
and [evaluation protocol](../evals/workflow/README.md) for that evidence.
