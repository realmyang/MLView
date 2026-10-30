# Development

This page is for people who change MLView: how to build it, debug it, run its
checks and rebuild the files that a command writes. The
[README](../README.md) names the top-level folders, and
[architecture.md](architecture.md) maps the code inside them.
[releasing.md](releasing.md) has the steps of a release.

## Prerequisites

- Python 3.10 or newer. `scripts/check.py` stops on an older one.
- Node 20.18.1 or newer with npm, as `engines.node` in
  `vscode-extension/package.json` declares.
- The test dependencies, in a virtual environment of Python:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` pins `pytest` and `jsonschema`. The helper imports
modules of the standard library only.

## Build

```sh
sh scripts/build.sh
```

The script installs the locked npm dependencies of `webview/` and
`vscode-extension/` with `npm ci`, builds the viewer, copies it into the
extension, copies the skill into the plugin, compiles the extension,
type-checks both TypeScript projects and runs `tools/verify.py --all` and the
link check. With `--skip-npm-install` it does not run `npm ci`. On Windows the
driver is `scripts/build.ps1`.

`sh scripts/build.sh` writes no `.vsix` file. For the package, run
`npm run package` in `vscode-extension/` afterwards. It writes
`mlview-<version>.vsix` into that folder.

The parts by hand:

| Part | Run in | Command | Writes |
|---|---|---|---|
| The viewer | `webview/` | `npm run build` | `dist/mlview.js` and `dist/mlview.css` |
| The viewer's copy | the root | `python tools/sync-assets.py` | `vscode-extension/media/mlview.js` and `mlview.css` |
| The extension | `vscode-extension/` | `npm run compile` | `out/extension.js` with a source map, and `out/test-entry.cjs` for the tests |
| The VSIX | `vscode-extension/` | `npm run package` | A `.vsix` file, and the minified `out/extension.js` that the file holds |
| A skill ZIP | the root | `python tools/package_skill.py --host shared`, or `--host claude-code` | `mlview-skill-shared.zip` or `mlview-skill-claude-code.zip` under `.mlview/dist/` |

`npm run compile` and `npm run package` write different bundles to the same
path, `out/extension.js`: the unminified build and the packaged one.
`node esbuild.mjs --production` writes the packaged one without making a
VSIX. `scripts/vsix_check.py` does not compare a VSIX with the unminified
build: it reports that as a problem.

## Debugging

`vscode-extension/.vscode/launch.json` holds two launch configurations of the
type `extensionHost`, **Run MLView Extension** and **Run MLView Extension (no
build)**. VS Code is expected to offer them when `vscode-extension/` is the
folder it has open. Both pass the repository root as the folder to open. The
first names the default build task as its `preLaunchTask`, and `tasks.json`
defines that task as `npm: compile`.

That task compiles the extension and does not build the viewer. The page loads
the committed copy of the viewer in `vscode-extension/media/`. After a change
in `webview/src/`, run `npm run build` in `webview/` and
`python tools/sync-assets.py` from the root before you start the
configuration.

The extension writes its log to an output channel named MLView. The viewer
runs in a webview. VS Code is expected to offer the command **Developer: Open
Webview Developer Tools** for it; the command's name depends on the version of
VS Code.

## Run one suite

| Suite | Command | Notes |
|---|---|---|
| Python: the helper, the tools and the scripts | `python -m pytest skills/mlview/tests tools scripts -q` | Needs the test dependencies |
| The viewer | `npm test` in `webview/` | Most tests load the built `dist/mlview.js` into jsdom. The command does not build: run `npm run build` first after a change. One test file also needs the compiled extension: run `npm run compile` in `vscode-extension/` first |
| The extension | `npm test` in `vscode-extension/` | Builds first. The tests run outside VS Code, with `test/mock-vscode.js` in place of the `vscode` module |
| The conformance cases | `python -m pytest tools/test_workflow_conformance.py -q` for the schema and the helper; the extension suite for the extension | The extension's part runs the helper. It looks for Python in `MLVIEW_PYTHON`, and with `MLVIEW_REQUIRE_PYTHON=1` a missing Python is a failure, not a skip |
| The plugin | `python -m pytest tools/test_claude_plugin.py -q` | The tests that run the `claude` command-line tool skip without it; `MLVIEW_REQUIRE_CLAUDE_CLI=1` turns the skip into a failure |
| Types | `npm run check` in `webview/` or in `vscode-extension/` | Runs `tsc --noEmit` |

For one test file, give it to `node --test`: `node --test test/walk.test.mjs`
in `webview/`, or `node --test test/revision-lineage.test.js` in
`vscode-extension/` after `npm run compile`.

## The full check

```sh
sh scripts/e2e.sh
```

On Windows run `pwsh -File scripts/e2e.ps1`. Both drivers call
`scripts/check.py`, which prints a label for each step and, at the end,
`E2E OK: <n> exercised gates`. A step that did not run is not counted.

| Command | What it checks |
|---|---|
| `sh scripts/build.sh` | The steps of [Build](#build): the dependencies install, both builds succeed, both TypeScript projects type-check, and the two checks of the next rows pass |
| `python tools/verify.py --all` | The five places that hold the version agree. The schema is a valid JSON Schema, and the skill's example satisfies it. `claude-plugin/` holds exactly the files of a list. The extension's manifest contributes exactly the listed commands and the one custom editor, has a `menus` entry, and has no other kind of contribution. The plugin's copy of the skill and the extension's copy of the viewer equal their sources |
| `python scripts/check_docs.py` | Each relative link in a tracked Markdown file leads to a file or a folder under the name the link gives, and a link to a heading names a heading that the file has. The links that it reads are Markdown links and pictures, reference definitions and the `href`, `src` and `srcset` attributes of HTML. An address in an issue form that leads into this repository names a path that exists. `scripts/*.sh` have LF line endings |
| `sh scripts/e2e.sh` | The build's steps, the Python suite, the viewer suite and the extension suite. Then it packages both skill ZIPs and the VSIX into a temporary folder and runs the next row's check on that VSIX |
| `python scripts/vsix_check.py [file.vsix]` | The VSIX holds exactly the entries of a list and is at most 1 MiB. Its manifest contributes no command and no custom editor outside the list, and nothing besides commands, custom editors and menus. Its extension bundle is the minified build. `extension.vsixmanifest` offers the changelog as an asset. Its notices, changelog, page, manifest, icon and bundles equal the working tree's |
| `python scripts/vsix_check.py --payload-only [file.vsix]` | The same without the comparison with the working tree, for a VSIX that was built elsewhere. It prints a `SKIP:` line for each comparison that it leaves out |

`--skip-npm-install` leaves out the two `npm ci` steps. `--skip-build`, for
`e2e.sh` only, also leaves out the viewer build, both copies and the compile,
and prints a `SKIP:` line. The outputs can still change after it: `npm test`
in `vscode-extension/` and the packaging step rebuild the extension bundle,
and packaging rewrites its copies of the notices and the changelog. The
PowerShell drivers spell the flags `-SkipNpmInstall` and `-SkipBuild`.

The full check calls no model and opens no VS Code.

## Generated copies

Each of these files is a committed copy or output of a source in the tree.
Edit the source, run the command and commit what it wrote. CI runs
`git diff --exit-code` over the first five rows after its build.

| Copy | Source | Rebuild | Check |
|---|---|---|---|
| `webview/dist/mlview.js` and `mlview.css` | `webview/src/` | `npm run build` in `webview/` | The step of CI named above |
| `vscode-extension/media/mlview.js` and `mlview.css` | `webview/dist/` | `python tools/sync-assets.py` | `python tools/sync-assets.py --check` |
| `claude-plugin/skills/mlview/` | `skills/mlview/` without `tests/` | `python tools/sync-skill.py` | `python tools/sync-skill.py --check` |
| `vscode-extension/THIRD_PARTY_NOTICES.md` | `THIRD_PARTY_NOTICES.md` | `node vscode-extension/tools/sync-notices.mjs`, which `npm run compile` also runs | `node vscode-extension/tools/sync-notices.mjs --check` |
| `vscode-extension/CHANGELOG.md` | `CHANGELOG.md` | The same command | The same check |
| `contracts/conformance/documents/workspace/` | `contracts/conformance/documents/generate.py` | `python contracts/conformance/documents/generate.py` | `python contracts/conformance/documents/generate.py --check` |
| `vscode-extension/media/icon.png` | `vscode-extension/tools/make_icon.py` | `python vscode-extension/tools/make_icon.py` | `python vscode-extension/tools/make_icon.py --check` |
| `LICENSE` in `skills/mlview/`, `claude-plugin/`, `claude-plugin/skills/mlview/` and `vscode-extension/` | `LICENSE` | Copy the file; `sync-skill.py` carries the skill's copy into the plugin | `tools/test_package_skill.py` and `tools/test_claude_plugin.py` compare the skill's and the plugin's copies with the root file; `scripts/vsix_check.py` compares the packaged one |

`.gitattributes` turns off line-ending conversion, so the bytes that a
command writes are the bytes that git stores on every platform.

The key table in `docs/user-guide.md` is a generated copy too:
`node webview/tools/keys-table.mjs` prints it from `KEYMAP` in
`webview/src/ui/keymap.ts`, the printed table goes between the guide's two
`keys` markers, and `--check` compares the two, as
`webview/test/keys-table.test.mjs` does in `npm test`.

## Screenshots of the viewer

`node webview/tools/screenshots/capture.mjs` opens documents in the built
viewer in headless Chrome and saves one PNG per state and an `index.json`.
It needs a local Chrome or Chromium; set `CHROME` to the executable when it is
not in the usual place. `--help` lists the inputs, the states, the themes and
the sizes. Pictures go to `.mlview/screenshots/`, which git ignores, unless
`--out` names another folder. Do not commit screenshots of third-party code.

The tool's page stands in for the extension, so a picture shows how the viewer
draws a document and not how VS Code shows it. The capture is not part of
`npm test` or of the full check. `webview/test/screenshot-pipe.test.mjs`
tests the tool's pipe to Chrome and its search for Chrome, and that test is
part of `npm test`.

## Layout numbers

`node webview/tools/layout-metrics.mjs` mounts documents in the built viewer
in jsdom and prints geometric measures of the layout, such as crossings of
connections and routes that pass through a step. `--help` lists the options.
`webview/tools/layout-metrics.baseline.json` holds a recorded summary:
`--baseline` lists the numbers that differ from it, and `--write-baseline`
records it again. No test compares the tool's numbers with the baseline.
`webview/test/layout-metrics.test.mjs` checks several measures on scenes small
enough to work out by hand: crossings, routes through a step, overlaps,
uncertain connections, crossed labels and the walk replay. The walk replay is
the tool's own model of the review walk, and it does not follow the viewer on
a connection whose two steps do not fit the view together: the replay moves
to the rectangle around both steps, where the viewer shows the start of the
connection or, for a dashed or dotted line, may zoom out to show both.
`webview/test/geometry-golden.test.mjs` pins the routed geometry of one
fixture, expanded and with every group collapsed.

## Benchmark

```sh
node --expose-gc webview/tools/benchmark-workflow.mjs
```

Run it after `npm run build` in `webview/`. It mounts synthetic documents of
several sizes in jsdom and prints JSON: timings for mount, select, SVG export,
revision update and dispose, and memory snapshots. Sizes given as arguments
replace the default sizes, and `MLVIEW_BENCH_ROUNDS` repeats each size. The
run fails when a step of a document is not drawn.

The timings are JavaScript and DOM time in jsdom. They do not include style,
layout or paint in a browser, or anything that VS Code does.
`webview/tools/benchmark.html` runs the same documents in a browser when the
repository is served over HTTP from its root, for example with Python's
`http.server` module.
