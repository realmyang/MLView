# VALIDATION — validating MLView by hand, and publishing it

This is the runbook for a person on **a different machine from the one MLView
was built on**. Part 1 gets the code running there. Part 2 is a 30-minute
session per host, with what to look at and what "working" means for each check.
Part 3 is how to record what you saw. Part 4 is publishing, step by step, with
the exact commands and the accounts each one needs.

Every command appears in both a POSIX (`sh`, macOS / Linux) and a Windows
PowerShell form, because half the gaps this document exists to close are
platform gaps.

**Read this first — what has never been tried on this project.** MLView was
built and gated entirely on one machine with no VS Code Extension Development
Host run under automation, no GitHub Copilot installed, and nothing published
anywhere. Specifically:

- The extension has **never been run inside a real VS Code webview**. Every
  extension test drives `vscode-extension/test/mock-vscode.js`.
- `@mlview` in Copilot Chat and `#mlviewAnalyze` / `#mlviewIssues` /
  `#mlviewDiagram` in agent mode have **never met a live Copilot session**. They
  are contributed correctly and type-check, and that is all anyone can honestly
  claim.
- **CI ran late, and only at the end.** GitHub Actions billing was blocked at
  the account level for the whole of the consolidation and the recall campaign,
  so every job came back unstarted and all of that work was checked on the build
  machine — Python 3.13 alone — and nowhere else. The matrix has run since the
  repository went public: thirteen green jobs on the `public` → `main` pull
  request (run 34986234828 and run 34986239243), which is where Python 3.10,
  3.11 and 3.12, Windows and macOS are exercised. Nothing has run on `main`.
- Nothing has been published: **no PyPI release, no Marketplace extension, no
  Open VSX extension, no hosted plugin marketplace, no GitHub release**. Every
  command in Part 4 is written from the tools' own documentation and has not
  been executed against a real account from this repository. Expect to hit at
  least one name collision (`mlview` may already be taken on PyPI and on the VS
  Code Marketplace) and treat the first run of each as exploratory.
- `claude plugin validate` is not available on a hosted CI runner, so the plugin
  manifest gates are desk-verified only.

Everything in Part 2 exists to convert those unknowns into recorded
observations. A check that fails is a result, not a mistake — write it down.

---

## Part 1 · Prerequisites and getting the code

### What you need

| Thing | Version | Why |
|---|---|---|
| Python | **3.11+** (3.10 works, but cannot read `.mlview.toml` — no `tomllib`) | the analyzer |
| Node.js | **20+** (22 and 26 are both used in this project) | the viewer bundle, the extension, their suites |
| git | any recent | the clone, and `--changed-since` attribution |
| VS Code | **1.100.0+** | the extension host |
| GitHub Copilot | any | `@mlview` and agent mode — *optional*, and the point of the exercise if you have it |
| Claude Code CLI | any recent | `/mlview`, the MCP tools, the hooks |
| `mcp` (Python) | **v2**, verified against `mcp==2.1.1` | Session C only. `python -m pip install mcp`. The plugin vendors MLView but **not** the MCP SDK, so without it `claude-plugin/server/mlview_mcp.py` cannot import and none of the five `mlview_*` tools appear. |
| `MLVIEW_PYTHON` | an env var, not a package | Session C only. `claude-plugin/.mcp.json` runs `${MLVIEW_PYTHON:-python}`, and on macOS and most Linux there is **no bare `python`** on `PATH`; macOS's `/usr/bin/python3` is Xcode's 3.9, which the server refuses. Export an absolute path to a 3.10+ interpreter — ideally the venv's — in the shell you launch Claude Code from. |

No ML framework is needed. MLView never imports the code it reads, so a machine
with neither torch nor scikit-learn installed is a **better** test, not a worse
one.

### Clone and build

```sh
# macOS / Linux
git clone https://github.com/realmyang/MLView
cd MLView

python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e analyzer

sh scripts/build.sh                                # BUILD OK — 6 steps
sh scripts/e2e.sh                                  # E2E OK — 20 steps, 0 failed
```

```powershell
# Windows, PowerShell 5.1 or newer
git clone https://github.com/realmyang/MLView
cd MLView

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # Activate.ps1 is an
                                                            # unsigned local script and the
                                                            # client default is Restricted
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
python -m pip install -e analyzer

powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
```

`scripts/e2e` is the whole acceptance table in one pass: it builds, runs every
suite, analyzes both samples, writes the scoped reports, and runs the parity,
scope, accuracy and doc gates. **If it is not green, stop here and record that**
— everything below assumes a working build, and a broken build on a second
machine is the single most valuable finding this exercise can produce.

Have a real ML project of your own ready as well — anything with a training
loop. The samples are written to be found; your own code is the test.

---

## Part 2 · The sessions

Three sessions, roughly 30 minutes each. Do them in any order. Record every row
in `docs/DEMO_LOG.md` as you go (Part 3) rather than at the end.

### Session A · VS Code, and Copilot if you have it

```sh
cd vscode-extension
npm install
npm run compile
code .                 # then press F5
```

F5 opens an **Extension Development Host** window. Open your own ML project in
it (`File → Open Folder`). Then, in order:

| # | Do this | "Working" means |
|---|---|---|
| A1 | `Ctrl/Cmd+Shift+P` → **MLView: Visualize ML Workflow (Workspace)** | A panel opens with a swimlane diagram of *your* code within a few seconds. Lanes are labelled `config … deliver`. The status bar shows a finding count. |
| A2 | Look at the **Problems** panel | MLView findings appear with `source: MLView`, a rule code, and related locations. Clicking one jumps to the right line **of your file**, not of a generated file. |
| A3 | Click a node card in the diagram | The editor opens that file with the symbol's range selected. |
| A4 | Click an **edge** | It lands on the *call site* that created the dependency — not on either endpoint's definition. This is the check most likely to be subtly wrong. |
| A5 | Hover a connection, then hover a node | The connection lights up and a charge runs along it outlet → inlet; hovering a node streams its whole lineage. With OS "reduce motion" on, you get a static chevron and dots instead — both are correct, note which you saw. |
| A6 | Put the cursor inside a class or function, press **`Alt+M`** | The matching node is revealed and selected in the diagram. |
| A7 | Press **`Alt+Shift+M`** | The diagram scopes to the unit under the cursor; the breadcrumb says `N of M nodes` with **M the whole project's size**. Then **MLView: Clear Diagram Scope**. |
| A8 | Use the scope picker in the diagram toolbar; try `stage:train` and `concern:evaluation`, and `[` / `]` for depth | The picker lists real units from your code, and the count beside a row is **the number the click delivers**. The **Problems panel does not change** while scoped — a scope is a view, not a filter. |
| A9 | Click the lightbulb on an MLView diagnostic | You are offered `Copy ignore comment`, `Add ignore comment on this line`, `Disable rule MLVxxx in .mlview.toml`, and — on some findings — a **fix preview**. Applying a fix opens VS Code's refactor **preview** first. Nothing is ever written without that preview. |
| A10 | **MLView: Export Diagram as SVG**, then **as PNG** | You are asked what to draw (whole diagram / current view / current scope), then a save dialog appears. Open the file: it should look like the panel. Fonts and shadows differ slightly; a missing node or edge is a real defect. |
| A11 | **MLView: Open MLView Configuration**, then edit and save | With no config, it offers to create `.mlview.toml`. A rule disabled there disappears from Problems after a re-analysis. |
| A12 | **MLView: Save Current Graph As Comparison Base**, change some code, **Compare With Saved Base** | The diff overlay is drawn on the open diagram; the output channel carries the `notes[]` in full. |
| A13 | Check the panel's **coverage** chip and banner | If MLView could not read something — one file analyzed, an untraced argument, a notebook skipped — it says so above the diagram rather than reporting a clean count. On a project it read fully there is no chip; note which you got. |
| A14 | *Copilot, if installed:* in Chat, type `@mlview /issues`, then `@mlview /diagram`, then `@mlview /explain MLV101` | An answer that cites **your** files with clickable anchors. A scoped answer must open by saying it is a filtered view. |
| A15 | *Copilot agent mode:* `#mlviewAnalyze what does the evaluation stage do here?` then `#mlviewIssues` and `#mlviewDiagram` | The tool is invoked and its result reaches the model. Record the exact prompt and the answer — nobody has ever seen this work. |
| A16 | `Help → Get Started` → the MLView walkthrough | Five steps, each a single click on a command that exists. |

Also worth recording, because no automated test can: how long A1 took on your
repo, how big the graph was, whether the first screen was readable without
zooming, and anything the diagram claimed that you know to be false.

### Session B · The standalone report (10 minutes, no editor)

```sh
python -m mlview analyze <your project> --html report.html --open
python -m mlview analyze <your project> --format summary
python -m mlview issues  <your project> --min-severity high
python -m mlview explain MLV101
```

```powershell
# Windows: identical, with $env:PYTHONUTF8 = "1" already set
python -m mlview analyze <your project> --html report.html --open
```

| # | Check | "Working" means |
|---|---|---|
| B1 | The report opens offline | One HTML file, no network requests (check DevTools → Network: it should be empty), same diagram as the panel. |
| B2 | Click a node, then the "Go to `file:line`" affordance | A local (`file://`) report — which is what the command above produces — hands the `vscode://file/...` URL to the OS in a transient window it then closes after ~700 ms, so **VS Code should jump to the line** and the toast reads `Copied <file>:<line>`. If nothing handles the protocol, or the browser blocks the popup, the report says so at once instead of failing silently: it puts `file:line` on the clipboard and leaves an **Open in VS Code** anchor in the toast. A report opened over `http(s)`, or embedded in the VS Code panel, never launches at all — it only copies, and its toast says so ("open the report locally to jump into VS Code"). Either outcome is a pass; *silence* is the fail. **Then press `?` and an arrow key**: the keyboard must still work after that click. A deep link that steals the keyboard from the page is a confirmed past defect (§17 E30), and it makes every later check in this session read as broken. |
| B3 | The **Answer Card** above the canvas | Four honest sentences: where data enters, what is optimized, how it is evaluated, and a verdict. If MLView could not read something, the verdict says so rather than giving a clean bill of health. |
| B4 | The issue rail | Ranked by severity; each row jumps to its node. Suppressed and baselined findings are in a collapsed section, not silently dropped. On a project with no findings, a clean state that follows a *blind* run must repeat the caveat rather than say "nothing to flag". |
| B5 | Theme switch, the legend, the shortcut sheet | The report is legible in light and dark. The legend opens from the toolbar button and `?` opens the shortcut sheet; **`Escape` closes whichever is open** and leaves the rest of the view alone. |
| B6 | `--format summary` in a terminal | The text version of the same answer, and stdout carries **only** the payload — `python -m mlview analyze . --format json > g.json` must produce valid JSON with no log lines in it. |
| B7 | Run it twice and look for a new directory in your repo | MLView's parse cache is on by default and must **not** appear inside the project you analyzed. `git status` in your own repo should be unchanged. Record the path it did use if you can find it (`MLVIEW_CACHE_DIR` overrides it; `MLVIEW_NO_CACHE=1` turns it off). |

### Session C · Claude Code

```sh
python -m pip install mcp            # the SDK the server imports; not vendored
export MLVIEW_PYTHON="$(command -v python || command -v python3)"   # a 3.10+
                        # interpreter, by absolute path: `.mcp.json` defaults
                        # to a bare `python`, which usually does not exist

claude plugin validate ./claude-plugin --strict
claude --plugin-dir /absolute/path/to/MLView/claude-plugin
```

```powershell
# Windows, PowerShell
python -m pip install mcp
$env:MLVIEW_PYTHON = (Get-Command python).Source

claude plugin validate ./claude-plugin --strict
claude --plugin-dir C:\absolute\path\to\MLView\claude-plugin
```

| # | Do this | "Working" means |
|---|---|---|
| C0 | Start the session and ask what MLView tools are available | The five `mlview_*` tools are listed. If they are not, the server failed to start: read its stderr, which names the fix in one line (a missing `mcp`, or an interpreter older than 3.10). Do **not** record C1-C8 as failures until C0 passes — they all fail for that one reason. |
| C1 | `/mlview <your project>` | The model analyzes, summarizes, and offers to open the diagram. The answer cites real files and line numbers from your repo. |
| C2 | `/mlview-issues <your project> high` | A ranked list of high-severity findings, each citable. |
| C3 | `/mlview-issues <your project> --group-by rule` | One row per rule with an occurrence count and up to three sites, not a flat repeated list. |
| C4 | `/mlview <your project> --scope concern:evaluation --depth 1` | A scoped answer that **says it is scoped** and still reports the project's real size. |
| C5 | Ask the model to analyze with `framework: "torch"` on a project that is not torch-only | The answer must say that the filter dropped rules, naming the codes from the `coverage` row of kind **`framework_filter`** — that row carries the `codes[]`, and it is the only coverage row a `--framework` run adds. The payload's `diagnostics` tally *also* carries a bare `{kind: "framework_suppressed", count: N}` of the **same** count: the analyzer's `framework_filter` and the host's own suppression note are two statements of one cost (§11.4 C3), the host stands its own note down whenever the core emitted `framework_filter`, and the two counts must never be added together. Then the model must offer to re-run with `"auto"`. A shorter finding list presented as a cleaner project is a fail. |
| C6 | Ask the model to open the diagram | `mlview_open_diagram` writes an HTML report and returns its path; the model must not claim it can export an image. |
| C7 | Let Claude **edit a training file** in a way that introduces a defect (delete an `optimizer.zero_grad()`, or fit a scaler before a split) | The `PostToolUse` hook speaks up **only because the finding set grew**, at most 5 rows. The first edit in a session is silent by design — there is nothing to diff against yet. Run a second edit to see it. |
| C8 | Then check your own repo for a stray `.mlview/` | A `--plugin-dir` session names no storage directory of its own, so this is the route that used to seed a cache inside the analyzed project. `git status` in your repo should be unchanged. |
| C9 | On Windows without Git Bash | The command in `claude-plugin/hooks/hooks.json` is shell form, and Claude Code falls back to PowerShell when Git Bash is absent. PowerShell reads `${MLVIEW_PYTHON:-python}` as a variable *named* `MLVIEW_PYTHON:-python`, which is unset, so the hook runs nothing and exits non-zero — and a non-zero `PostToolUse` exit surfaces a **`<hook name> hook error` notice carrying the first line of stderr**, on every Edit and Write. **Expect a visible error notice, not silence**; record the exact text. (Silence would mean something else again. The fix is a `"shell": "bash"` field on both hook entries, or exec form; neither is applied yet.) |
| C10 | Marketplace install path: `/plugin marketplace add <this repo or a local path>` then install `mlview` from it | The plugin installs and the five tools appear. See Part 4.3 for hosting the marketplace file. |

---

## Part 3 · Recording what you saw

Copy `docs/DEMO_LOG.md`, fill in one row per check, and keep it with the run:

```sh
mkdir -p docs/demo-logs/screenshots
cp docs/DEMO_LOG.md "docs/demo-logs/$(date +%F)-<your-machine>.md"
```

```powershell
# Windows, PowerShell
New-Item -ItemType Directory -Force docs/demo-logs/screenshots | Out-Null
Copy-Item docs/DEMO_LOG.md "docs/demo-logs/$(Get-Date -Format yyyy-MM-dd)-<your-machine>.md"
```

**The `mkdir` comes first on purpose.** A fresh clone carries
`docs/demo-logs/.gitkeep` and nothing else, and `screenshots/` is not there at
all; copying into a directory that does not exist fails and takes the rest of
the block with it.

One row per check — **pass / fail / note** — plus the environment block at the
top (OS, Python, Node, VS Code, Copilot, Claude Code versions) and the repo it
was run against. Screenshots go in `docs/demo-logs/screenshots/` — one shared
directory, not one per log — and are referenced by file name from the row that
needed them; a screenshot with no row is not evidence of anything.

Rules for the log, so the result is usable by somebody who was not there:

- **A fail needs three things**: what you did, what happened, and what you
  expected. "Export PNG is broken" is not reportable; "A10: Export as PNG saved
  a 0-byte file; SVG from the same panel was correct" is.
- **A pass that surprised you is worth a note.** "A4 landed on the call site —
  correct, but the file opened in a new column each time" is exactly the kind of
  thing no unit test will ever report.
- **Do not fix anything while validating.** Record it and move on; a session
  that turns into a debugging session stops being a measurement.

**Handing findings back.** Open one GitHub issue per failed check, titled with
the check id (`A10: Export as PNG writes a 0-byte file`), with the log row, the
environment block and the screenshot attached. Then open one pull request that
adds your filled-in log under `docs/demo-logs/` — the log lands in the repo even
if none of the issues are fixed, which is the point: it is the first record of
this software being run anywhere but its build machine. If something is
security-relevant (a path escape, an injection through a file name), do not open
a public issue; contact the maintainer directly.

---

## Part 4 · Publishing

Do these in order. Each has its own account and its own token, and **none of
this has been done before from this repository** — budget time for first-run
surprises.

### 4.0 Before anything is published

```sh
# 1. One version string, in five places. The gate that checks it:
python tools/verify.py --versions

# 2. The whole table, green, on this machine:
sh scripts/e2e.sh                           # 20 steps
python tools/verify.py --all                # 10 rows
python tools/verify.py --scopes --fuzz 200  # the differential fuzz
python scripts/check_docs.py                # DOC CHECK OK
python tools/accuracy.py                    # the labelled corpus, default mode
python tools/accuracy.py --dataflow local   # forcing the narrower mode
python tools/accuracy.py --dataflow ip      # forcing the wider mode

# 3. The pinned third-party corpus: no crash, no schema error, and no new
#    high-severity finding a human has not adjudicated.
python tools/public_corpus.py fetch --corpus-dir .public-corpus
python tools/public_corpus.py run   --corpus-dir .public-corpus --out pc.json
python tools/public_corpus.py check --corpus-dir .public-corpus --report pc.json --strict

# 4. The packaged artifacts build and run:
python tools/wheel_check.py                 # builds the wheel, installs it in a
                                            # throwaway venv, analyzes with it
                                            # NOTE the sdist 4.1 also uploads is
                                            # NOT gated: nothing in the repo or in CI
                                            # builds or smoke-tests one, and
                                            # `wheel_check.py` takes only `--no-build`.
                                            # `pip install mlview` falls back to the
                                            # sdist on any platform without a matching
                                            # wheel, and a version can never be
                                            # re-uploaded — so if 4.1 is a real upload,
                                            # install the built tarball by hand first.
cd vscode-extension && npm run package && cd ..
python scripts/vsix_check.py                # ceiling, bundled core, rule pages, no bytecode
```

```powershell
# Windows, PowerShell — the same rows
python tools/verify.py --versions
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
python tools/verify.py --all
python tools/verify.py --scopes --fuzz 200
python scripts/check_docs.py
python tools/accuracy.py
python tools/public_corpus.py run --corpus-dir .public-corpus --out pc.json
python tools/public_corpus.py check --corpus-dir .public-corpus --report pc.json --strict
python tools/wheel_check.py
cd vscode-extension; npm run package; cd ..
python scripts/vsix_check.py
```

To bump the version, change it in **all five**: `analyzer/src/mlview/version.py`
(`__version__`, the source of truth), `analyzer/pyproject.toml`,
`vscode-extension/package.json`, `claude-plugin/.claude-plugin/plugin.json` and
`webview/package.json`. The root `pyproject.toml` reads it dynamically and needs
no edit. `tools/verify.py --versions` fails if any of them disagree. Add the
release to `CHANGELOG.md` in the same commit, and tag it: `git tag v0.1.0 && git
push origin v0.1.0`.

### 4.1 PyPI — the `mlview` wheel

**Accounts:** a [PyPI](https://pypi.org) account and a
[TestPyPI](https://test.pypi.org) account (they are separate), each with 2FA on,
and a **project-scoped API token** from each (`Account settings → API tokens`).
Tokens are used as the password with the username `__token__`.

```sh
python -m pip install --upgrade build twine

# Build from the analyzer package (the distribution that gets published):
rm -rf analyzer/dist
python -m build --wheel --sdist analyzer
twine check analyzer/dist/*

# TestPyPI first. Always.
twine upload --repository testpypi analyzer/dist/*

# Verify the uploaded artifact in a clean venv, with the real index for deps:
python3 -m venv /tmp/mlview-test && . /tmp/mlview-test/bin/activate
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple mlview
mlview --version
mlview analyze <some project> --format summary
deactivate

# Then the real thing:
twine upload analyzer/dist/*
```

```powershell
# Windows, PowerShell
python -m pip install --upgrade build twine
Remove-Item -Recurse -Force analyzer/dist -ErrorAction SilentlyContinue
python -m build --wheel --sdist analyzer
twine check analyzer/dist/*
twine upload --repository testpypi analyzer/dist/*

py -3 -m venv $env:TEMP\mlview-test
& "$env:TEMP\mlview-test\Scripts\Activate.ps1"
pip install --index-url https://test.pypi.org/simple/ `
            --extra-index-url https://pypi.org/simple mlview
mlview --version
deactivate
```

Verification after the real upload:

```sh
python3 -m venv /tmp/mlview-live && . /tmp/mlview-live/bin/activate
pip install mlview
mlview --version                      # matches the tag
mlview analyze <some project> --format summary
python -c "import mlview, pathlib; print(pathlib.Path(mlview.__file__).parent)"
deactivate
```

The last line matters: the wheel must carry `schema/*.json` and `emit/assets/*`
as package data, or it installs perfectly and fails on the first analysis. That
is exactly what `tools/wheel_check.py` gates, and it is worth re-running against
the *published* wheel, not only the local build.

**The sdist is published untested, and that is a stated gap, not an oversight.**
`tools/wheel_check.py` builds and installs the **wheel** — it takes `--no-build`
and nothing else — and neither `scripts/e2e` nor CI's `packaging` job builds a
source distribution at all. The package-data failure above is exactly as
invisible in an sdist as in a wheel, and `pip install mlview` falls back to the
sdist on any platform with no matching wheel. Since a version can never be
re-uploaded, do the equivalent by hand before the real upload: `pip install
analyzer/dist/mlview-*.tar.gz` into a throwaway venv and run the two commands
above against it. Record the result in `docs/DEMO_LOG.md` beside the wheel row.

**If the name is taken.** `mlview` may already exist on PyPI. If so, pick a new
distribution name (`mlview-analyzer`, say), change `name =` in **both**
`pyproject.toml` files, leave the import package `mlview` alone, and update the
install lines in `README.md`, `vscode-extension/README.md` and
`claude-plugin/README.md`. A version can never be re-uploaded to PyPI, so a bad
upload costs you a version number, not a name.

### 4.2 The VS Code Marketplace (and Open VSX)

**Accounts:** a Microsoft/Azure DevOps organization, a **publisher** created at
<https://marketplace.visualstudio.com/manage>, and a **Personal Access Token**
from Azure DevOps (`https://dev.azure.com/<org>/_usersSettings/tokens`) with
*Organization: all accessible organizations* and the scope **Marketplace →
Manage**. The publisher id must equal `publisher` in
`vscode-extension/package.json`, which is currently **`mlview`** — if that id is
unavailable, change the field and re-run `npm run package`.

**Azure DevOps retires global Personal Access Tokens on 1 December 2026.** If you
are publishing after that date these instructions are stale: use Microsoft Entra
ID authentication instead (workload identity federation for automated publishing)
and follow the current VS Code publishing document rather than this paragraph.

```sh
npm install -g @vscode/vsce

cd vscode-extension
npm run compile                       # this is also what writes core/mlview
npm run package                       # writes mlview-<version>.vsix
cd .. && python scripts/vsix_check.py # the packaged artifact, re-measured

cd vscode-extension
vsce login <publisher>                # paste the PAT
vsce publish --packagePath mlview-<version>.vsix
```

`core/mlview` inside the extension is a **build artifact**, not a checked-in
directory: `npm run compile` and `vscode:prepublish` both run
`vscode-extension/tools/sync-core.mjs` to write it, and it is gitignored. A
clone that has never run either step has no `core/` at all — which is correct,
and is why the package step is not optional.

Verify from a **different** machine or a clean profile: `code
--install-extension <publisher>.mlview`, open a Python ML project, run
`MLView: Visualize ML Workflow (Workspace)`, and confirm the bundled analyzer
answers with no `pip install` (the status-bar tooltip names which core
answered).

Open VSX, for VS Codium / Cursor / Windsurf users, is a separate registry with
its own account at <https://open-vsx.org> and its own token:

```sh
npm install -g ovsx
ovsx create-namespace <publisher> -p <open-vsx-token>
ovsx publish vscode-extension/mlview-<version>.vsix -p <open-vsx-token>
```

Marketplace publishing has pre-flight rules that the local package step does not
enforce: a `LICENSE` file, a `README.md` that renders standalone (relative
image and link paths break), an icon of at least 128×128, and a `repository`
field. All are present in this repo; confirm them on the listing page rather
than assuming.

### 4.3 The Claude Code plugin marketplace

A Claude Code marketplace is a **`.claude-plugin/marketplace.json` hosted in a
git repository** — this repo already is one. Nothing is uploaded anywhere; users
add the repository and install from it.

```sh
# From this repo (already committed):
cat .claude-plugin/marketplace.json     # entry "mlview" from ./claude-plugin,
                                        # entry "mlview-github" from git-subdir
                                        # github.com/realmyang/MLView @ claude-plugin
claude plugin validate ./claude-plugin --strict
claude plugin validate ./.claude-plugin/marketplace.json --strict
```

**The hosted entry is `git-subdir`, and it has to be.** The plugin lives in
`claude-plugin/`, not at the repository root, and the `github` source form takes
`repo` / `ref` / `sha` and **no `path`** — it publishes the fetched tree's root.
This repository's root holds a marketplace manifest and no `plugin.json`, so a
`github` entry installs a directory with no plugin in it, and the failure only
shows up after a user installs. `git-subdir` takes `url` + `path`, which is the
one form that can name a subdirectory;
`claude-plugin/tests/test_plugin_manifest.py` asserts that every entry's
resolved directory really contains `.claude-plugin/plugin.json`.

For a user, on any machine:

```
/plugin marketplace add realmyang/MLView
/plugin install mlview@mlview-local
```

then restart the session and confirm the five `mlview_*` tools are listed and
`/mlview` runs. A local checkout can be added by path instead:
`/plugin marketplace add /absolute/path/to/MLView`.

The published plugin directory is copied **verbatim**, which is why
`claude-plugin/vendor/mlview` is tracked in git: a marketplace install has no
build step and no `pip install`, so the analyzer has to be inside the plugin
directory. (This is the opposite of the VS Code extension's `core/`, which is
built from a working tree and therefore gitignored.) Once the wheel is on PyPI,
that vendored copy can be replaced by a dependency — see 4.5.

### 4.4 A GitHub release

Attach both artifacts so that a user can install either without a package
registry at all:

```sh
gh release create v0.1.0 \
  analyzer/dist/mlview-0.1.0-py3-none-any.whl \
  analyzer/dist/mlview-0.1.0.tar.gz \
  vscode-extension/mlview-0.1.0.vsix \
  --title "MLView 0.1.0" \
  --notes-file CHANGELOG.md
```

`--notes-file CHANGELOG.md` posts the whole file; trim it to the release's own
section first, or write the notes inline with `--notes`. Verify the release page
shows all three assets and that `pip install <the .whl URL>` works from a clean
venv.

### 4.5 What to update afterwards

- **README install lines.** `vscode-extension/README.md` still tells the reader to
  `pip install -e <repo>/analyzer`; once the wheel is public it should say
  `pip install mlview` and point at the Marketplace listing. `README.md` already
  carries `pip install mlview` as a parenthetical ("or: pip install mlview, once
  published") — promote it to the primary line and demote the editable install to
  the contributor note. `claude-plugin/README.md` needs **no** change until the
  vendored analyzer goes away: its install story is deliberately the opposite one
  (no `pip install` of MLView at all; `.mcp.json` puts `claude-plugin/vendor` on
  `PYTHONPATH`).
- **Drop the vendored analyzer from the plugin.** `claude-plugin/vendor/mlview`
  exists only because a marketplace install copies the plugin directory verbatim
  with no build step. Once `pip install mlview` works, the plugin can depend on
  it and `tools/sync-core.py` plus its `vendor: synced core` gate row can go
  away. Do this as its own change: it removes a gate, so it needs the plugin
  suite re-run against a pip-installed core with `PYTHONPATH` **not** pointing at
  `vendor/`.
- **Pin the GitHub Action.** `tools/action/action.yml` is a composite action that
  installs the checkout; after a release it should install the published wheel
  instead. No `uses:` line is documented anywhere in this repository today — if
  one is added (`uses: realmyang/MLView/tools/action@v0.1.0` is the line users
  copy), pin it to the tag rather than to `@main` from the start.
- **The scheduled workflows.** `.github/workflows/nightly.yml` and
  `.github/workflows/public-corpus.yml` only start firing once they are on the
  default branch — and neither has ever run, because Actions billing is blocked.
  Confirm both ran the day after the merge, and treat the first public-corpus
  run as a measurement, not a formality.
- **`docs/STATUS.md`** should stop saying the hosts are compile-verified only,
  for whichever of them this validation run actually exercised. That is the
  whole point of Part 3's log: it is the evidence that lets a line in the status
  page change.
