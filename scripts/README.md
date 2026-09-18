# Build and validation scripts

Python 3.10+ and Node 20.18.1+ are required for development. The skill helper is
standard-library-only; tests require `pip install -r requirements-dev.txt`.

| Command | What it proves |
|---|---|
| `sh scripts/build.sh` | Locked npm dependencies, viewer build, synchronized copies, extension compile, type checks and current docs |
| `sh scripts/e2e.sh` | Build plus Python and TypeScript suites, skill ZIP packaging and actual VSIX payload checks |
| `python tools/verify.py --all` | Matching skill/viewer copies and a schema-valid example, matching component versions, no retired analyzer surfaces |
| `python scripts/check_docs.py` | Active documentation links and local shell line endings |
| `python scripts/vsix_check.py [file.vsix]` | Required assets, native commands, current bundles, size ceiling and no Python analyzer payload |

Both shell drivers delegate to `scripts/check.py`. PowerShell equivalents are
`scripts/build.ps1` and `scripts/e2e.ps1`. `--skip-npm-install` reuses existing
node_modules; `--skip-build` explicitly skips the e2e build. A skipped step is
reported as skipped, never counted as a successful gate.

Tests create temporary skill archives and a temporary VSIX and remove them on
completion. To retain packages for installation, run `npm run package` inside
`vscode-extension/`, and `python tools/package_skill.py --host shared` or
`--host claude-code` from the root. Skill archives go under `.mlview/dist/`.

These checks establish structural and distribution correctness. They do not
call an LLM, judge interpretation quality, or prove native assistant discovery
and live VS Code interaction. Use the [live checklist](../docs/LLM_WORKFLOW.md)
and [evaluation protocol](../evals/workflow/README.md) for that evidence.
