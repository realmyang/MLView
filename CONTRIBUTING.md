# Contributing to MLView

MLView is a skill for an assistant, a document format and a VS Code viewer.
The [user guide](docs/user-guide.md) describes the product,
[docs/architecture.md](docs/architecture.md) maps the code, and
[docs/development.md](docs/development.md) has the commands in full.

## Set up

Use Python 3.10 or newer and Node 20.18.1 or newer. In a clone:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
sh scripts/build.sh
```

The build installs the locked npm dependencies with `npm ci`. The helper
needs only Python's standard library. On Windows the drivers are
`scripts/build.ps1` and `scripts/e2e.ps1`, and they use the Python that
`$env:PYTHON` names when it is set.

## Change and check

- **The skill.** Edit it in `skills/mlview/`, then run
  `python tools/sync-skill.py`, which rewrites the plugin's copy. To try a
  changed skill, install it into a scratch project with
  `python tools/install_skill.py <project>`. The installer replaces the files
  it installed before, deletes files the skill does not ship any more, and
  stops at a file with local edits unless you add `--force`.
- **The viewer.** Edit it in `webview/src/`, run `npm run build` in
  `webview/` and then `python tools/sync-assets.py` from the root. Commit the
  built files with the source.
- **The extension.** Its source is `vscode-extension/src/`.
- **The plugin folder.** `python tools/verify.py --all` and tests compare
  `claude-plugin/` with an exact list of files. A stray local file there, for
  example a `.DS_Store`, fails them although `git status` shows nothing.
  Delete the file.

[docs/development.md](docs/development.md#generated-copies) has the table of
generated copies.

Before you open a pull request, run:

```sh
python -m pytest skills/mlview/tests tools scripts -q
python tools/verify.py --all
python scripts/check_docs.py
sh scripts/e2e.sh --skip-npm-install
```

The last command builds the viewer and the extension, type-checks and tests
them, runs the Python tests, packages both skill ZIPs and the VSIX, and
compares the VSIX with an exact list of entries and with the minified bundle.
CI runs the same check on Node 20.18.1 and on newer versions, so use no
JavaScript API that is newer than Node 20.

## Changing the format

A change to the format touches five places. Change them in one pull request:

1. `contracts/workflow.schema.json`, the schema.
2. `skills/mlview/scripts/artifact.py`, the helper.
3. `vscode-extension/src/workflowDocument.ts`, the extension's validator, and
   the revision rules in `revisionLineage.ts` when they are affected.
4. `webview/src/workflow.ts`, when the change affects what the viewer draws.
5. The two descriptions for readers: `docs/format.md` and
   `skills/mlview/references/WORKFLOW_CONTRACT.md`.

Add or update a case under `contracts/conformance/cases/` for every rule that
changes. [contracts/conformance/README.md](contracts/conformance/README.md)
describes a case.

## Diagrams and samples

Do not run a project to make its diagram. The assistant reads the source, and
the helper checks the document's structure and its quotes. A matching quote
does not show that a claim is right, so a diagram that you commit keeps its
uncertain parts, its counter-evidence and the scenario it describes.

Do not edit a file under a sample's folder. Each sample's diagram records a
hash of each file it cites, and `tools/test_samples.py` compares them.

## Pull requests

- Work on a branch, and give the pull request a short title that names the
  change.
- Describe the problem for a user and what changes. List the commands you ran
  and their results, as the pull-request template asks.
- A comment in the code says what the code does and why. It does not tell the
  history of the change.
- Keep credentials, private source, assistant session logs and local test
  output out of commits.
- When you add a dependency that is redistributed, add its licence to
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Report a security problem as [SECURITY.md](SECURITY.md) says, not in a pull
  request.

[docs/releasing.md](docs/releasing.md) has the steps of a release.
