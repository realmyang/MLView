# MLView

[![CI](https://github.com/realmyang/MLView/actions/workflows/ci.yml/badge.svg)](https://github.com/realmyang/MLView/actions/workflows/ci.yml)

**Turn a Python machine-learning codebase into one interactive, issue-annotated
workflow diagram — and serve that identical diagram to two hosts: Claude Code and
GitHub Copilot / VS Code.**

Everything is static. MLView parses source with `ast`; it never imports, executes
or `exec`s the code it reads, and **torch and scikit-learn do not need to be
installed** — the machine this was built on has neither. Everything works offline:
no network at analysis, render or load time.

MLView answers, in the first ninety seconds of reading unfamiliar training code,
the four questions an ML reviewer actually asks: where does data enter and where
is it split, what is being optimized and by what, is the evaluation honest, and
what is wrong — how badly and on which line.

---

## The four spec requirements, and how they are met

| # | Requirement | How |
|---|---|---|
| **1** | **Visualize the complete logic / workflow** | A stage-labelled graph recovered by static analysis: eight canonical stages (`config → data → preprocess → model → objective → train → eval → deliver`) as swimlane bands, a three-level hierarchy (stage › unit › op), four typed edge kinds (`data`, `call`, `control`, `config`), and the training loop drawn *as a loop* with labelled back-edges. Stages that are absent are **declared, not dropped** — a missing `eval` lane is itself a finding. |
| **2** | **The diagram is interactive; clicking leads to the code** | Every node, edge and issue carries `{file, absFile, line, col, endLine, endCol, symbol, snippet}` — line 1-based, column 0-based, converted exactly once at the host boundary. Clicking a node opens the file with the range selected; clicking an **edge** lands on the *call site* that created the dependency, not on either endpoint's definition; an issue exposes its related locations as named secondary jumps ("go to the split site"). |
| **3** | **Potential issues are marked on the diagram** | Twenty rules (`MLV1xx` leakage, `MLV2xx` train loop, `MLV3xx` evaluation, `MLV4xx` loss, `MLV5xx` device, `MLV6xx` reproducibility, `MLV7xx` model) attach severity-marked badges to the exact node or edge. A **required-but-absent** step — a missing `optimizer.zero_grad()`, a missing `model.eval()` — is drawn as a dashed **ghost node** in its correct slot, so the diagram shows the hole rather than narrating it. Every finding carries a rule code, a confidence bucket, a message citing real variable names, and a one-sentence fix. |
| **1a** | **The flow is visible** | Hover a connection and it lights up while a charge runs along it **from outlet to inlet**, the way current runs through a cable; hover a node and its whole lineage streams, staggered 90 ms per hop. Direction is never guessed — every route is emitted source → target, so animating along the edge's own path *is* the direction. The charge takes the severity colour on an edge that carries a finding, so the wrong tensor is the one you watch move into the loss. Under `prefers-reduced-motion`, or above 120 lit edges, the same information is a static chevron plus an outlet and an inlet dot. |
| **1b** | **You can visualize part of a codebase** | One selector narrows every surface to one part of the pipeline: `unit:SmallCNN`, `unit:train_test_split`, `stage:train`, `file:data.py`, `concern:evaluation`, `node:<id>`, with `depth` 0–2 boundary hops. It is a **view, not a filter**: the Problems panel, `stage.present`, `workspace` and `generator` still describe the whole analysis, and the breadcrumb always says `N of M nodes` with `M` the project's real size. |
| **4** | **The UI/UX is beautiful, clear, intuitive** | One renderer, three severity marker *shapes* (not only colours, so it survives a greyscale screenshot), a collapsed default view that fits one screen, an issue rail ranked by severity, and design tokens written as `var(--vscode-*, <literal>)` so the same CSS is correct in a VS Code webview, in a light browser and in a dark one. |

The honest counterweight to that table is the [status section](#status--what-is-actually-verified) below.

---

## Quick start

Build once. It takes about a minute and needs no network beyond the npm cache.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

```sh
sh scripts/build.sh
```

### Claude Code

```bash
claude plugin validate ./claude-plugin --strict     # always validate first
claude --plugin-dir C:/absolute/path/to/MLView/claude-plugin
```

Then, in the session:

```
/mlview samples/vision_pipeline        # analyze, summarize, open the diagram
/mlview-issues samples/vision_pipeline high

/mlview samples/vision_pipeline --scope concern:evaluation
/mlview samples/vision_pipeline --scope unit:SmallCNN --depth 1
/mlview-issues samples/vision_pipeline low --scope stage:train
```

**Grouping from an agent.** `mlview_issues {groupBy: "rule"}` (and
`/mlview-issues --group-by rule|file|severity`) folds the findings into one row
per rule, file or severity with an occurrence count, the worst severity and
confidence, and up to three citable `file:line` sites. On an inherited repo the
flat list is eleven codes repeated ten times, and the 4 KB payload budget then
sheds rows until the answer is both long and incomplete. Grouping **folds** the
rows, it never filters them, and the payload's `note` says so.

**Scoping from an agent.** `mlview_graph {scope: "units"}` returns the catalogue
of everything that can be scoped to — one row per class, function and loop with
its file, line, node count and worst severity — so the model picks a real name
instead of guessing one. `mlview_analyze`, `mlview_issues` and
`mlview_open_diagram` then take the same `scope` and `depth`. There are **still
exactly five tools**; a scoped result says it is scoped, and `graphPath` keeps
pointing at the full document, so widening back costs nothing.

**Comparing from an agent (VIEW-08).** `mlview_graph {scope: "diff", base:
"<earlier analyze --json document>"}` answers *"did my change add a finding"* —
`summary.issues` is `{new, fixed, persisting}` and `content` is the `mlview diff`
summary. It is the **sixth value of an argument, not a sixth tool**, because a
diff is another projection of the same graph. `/mlview-issues --diff-base <file>`
is the slash-command spelling. A `base` that is not an MLView graph is an error
naming the file, never an empty comparison, and the payload's protected `note`
carries every reason a `removed` might not mean "deleted" — including that a
renamed file reads as everything removed plus everything added.

**Telling you before you ask (H8).** `claude-plugin/hooks/hooks.json` registers a
`PostToolUse` hook on `Edit|Write|NotebookEdit` and a `Stop` hook. The plugin is
otherwise entirely pull-based: when Claude edits a training file during a session
nothing tells it the edit introduced MLV203. The hook re-analyzes through the same
`load_graph` cache the MCP tools read, diffs the issue-id set against the previous
run, and **speaks only when the set grew** — at most 5 rows, worst first, under a
hard 3-second budget after which it exits 0 in silence. It never blocks a tool call
and never writes into your repository. `MLVIEW_HOOK` chooses which one speaks
(unset = the edit hook, `stop` = one summary per turn, `both`, `off`), and the
first run on a project is silent by construction: there is nothing to diff against
yet, and its value is the warm cache.

`/mlview` prefers the five `mlview_*` MCP tools and **falls back to the CLI
through `Bash`** when they are unavailable, so the demo does not depend on MCP
registration succeeding. The plugin needs no `pip install` of MLView itself —
`.mcp.json` puts `claude-plugin/vendor` on `PYTHONPATH`. See
[`claude-plugin/README.md`](claude-plugin/README.md) for the marketplace install,
the tool reference and Windows troubleshooting.

### VS Code / GitHub Copilot

```
scripts/build.ps1          # or scripts/build.sh
code vscode-extension      # open the folder, then press F5
```

F5 launches an Extension Development Host. Open a Python ML project in it, then:

- **Commands** (`Ctrl+Shift+P` → "MLView"): `Visualize ML Workflow (Current File)`
  · `(Workspace)` · `Re-analyze` · `Show ML Issues` · `Reveal in Diagram`
  (`Alt+M`, also on the editor context menu) · `Scope Diagram to Symbol`
  (`Alt+Shift+M`, also on the editor context menu — it scopes the panel to the
  unit the cursor is inside) · `Clear Diagram Scope` · `Export HTML` ·
  `Export Diagram as SVG` / `as PNG` · `Select Active Folder` ·
  `Open MLView Configuration` · `Create Baseline From Current Findings` ·
  `Save Current Graph As Comparison Base` · `Compare With Saved Base` ·
  `Compare With Clean Sample` · `Select Interpreter` · `Show Output` ·
  `Show Rule Doc`.
- **Getting started.** `Help → Get Started` carries a five-step MLView
  walkthrough — install, visualize the sample, read a finding in Problems,
  `Alt+M`, `Alt+Shift+M` — each step a single click on a command that already
  exists. Its pages live in `docs/walkthrough/`.
- **Exporting the picture.** `Export Diagram as SVG` / `as PNG` ask the open
  diagram for the whole diagram, the current view or the current scope, then a
  save dialog writes the file. The host cannot draw the diagram — only the viewer
  holds the geometry — so the command posts a request and the viewer answers with
  the bytes; with no diagram open the command says so rather than exporting an
  empty picture. In a terminal host `mlview_open_diagram` writes the **HTML**
  report and hands back `reportPath` plus an `exportHint`: an image file is the
  viewer's job, and the MCP server never claims otherwise.
- **Problems panel** — findings at or above `mlview.minConfidence` (default 0.6)
  are published as diagnostics with `source: "MLView"`, the rule code linking to
  a **local** offline doc page, and `relatedInformation` for every related site.
  Analysis runs on save by default (`mlview.analyzeOnSave`).
- **One configuration surface (CFG-ONE).** MLView passes `--config` to every
  analyzer run when the folder has a `.mlview.toml` — or a `pyproject.toml` with a
  `[tool.mlview]` table — so a checked-in configuration finally applies **in the
  editor** and not only on the CLI. `mlview.configPath` names one explicitly and
  `mlview.baselinePath` names a baseline whose findings stop counting. The
  precedence is stated in both settings descriptions and asserted by a test: **the
  file wins** for `[rules].disable` and `[paths].exclude`, and `mlview.disabledRules`
  / `mlview.exclude` are **additive filters on top** — they can hide more, and
  neither can re-enable a rule the file disabled. `Open MLView Configuration`
  creates the file with `mlview init` when there is none.
- **Several folders open (H10).** Every open workspace folder gets its own graph
  rather than the first one being analysed and the rest silently ignored. The
  Problems panel shows the union; a CodeLens answers for the folder its file lives
  in; the diagram, the status bar and the chat/LM answers follow the **active**
  folder, which the status-bar tooltip names — *"Folder: api — 1 other folder in
  this workspace is not shown here"* — with a link to switch. A single-folder
  window sees none of this and behaves exactly as before.
- **Current file, whole picture.** `Visualize (Current File)` analyses the
  **package directory** around the file and then scopes the diagram to the file
  (`mlview.currentFileAnalysisScope`, default `package`; `file` and `workspace`
  are the other two). Analysing a file alone cannot fire MLV301, MLV302, MLV401
  or MLV501 — each needs a sibling module — so the old behaviour lost four of
  seven findings on `train.py` and said nothing about it. Set it back to `file`
  and the analyzer's `single_file_analysis` diagnostic says which rules could not
  run.
- **A blind run says so.** `single_file_analysis` and `untagged_dataflow` reach
  the status-bar tooltip, the panel tab (`coverage: incomplete (N blind spots)`)
  and the chat / language-model digests, which tell the model the count is a floor
  rather than a clean bill of health
  (`vscode-extension/src/coverage.ts`).
- **Copilot Chat** — `@mlview` with `/diagram`, `/issues` and `/explain`. Every
  finding streamed into chat is followed by an anchor, so it is a click into the
  source.
- **Copilot agent mode** — `#mlviewAnalyze`, `#mlviewIssues` and `#mlviewDiagram`
  reference the three language-model tools directly in a prompt. All three take
  the same `scope` and `depth` the MCP tools take, described in **the same words**
  (a test reads the MCP docstring and asserts it), so *"what does the evaluation
  stage do here?"* is one question in either assistant. A scoped answer opens by
  saying it is a filtered view whose counts describe the scope and not the project;
  an unrecognized selector comes back as an error naming the accepted values,
  never as a silently substituted default.

- **A fix you can preview, never one that is applied for you (H5).** Where a rule
  computed one, `Issue.fix` carries `{title, safety, edits[]}` and the lightbulb
  offers it. The guardrails are the feature: rules **opt in**, so an empty
  lightbulb means "no edit was computed"; the edits come from the analyzer's
  **AST**; nothing below the `likely` bucket is offered an edit at all;
  `isPreferred` is set for `mechanical` and never for `needs-review`; and every
  edit carries `needsConfirmation` and is applied with `isRefactoring`, so VS Code
  routes it through the refactor **preview**. There is no `source.fixAll` kind —
  that is the one `editor.codeActionsOnSave` runs unattended. An edit naming a file
  outside the workspace is refused, and a fix whose second edit escapes is refused
  whole. The rail reaches the same path with `applyFix`, sending only the issue id.
- **Compare two analyses in the editor (VIEW-08).** `Save Current Graph As
  Comparison Base` writes the analysis you are looking at to
  `.mlview/comparison-base.json` verbatim; `Compare With Saved Base` re-analyses
  and runs `mlview diff base head --json -`, and the overlay is drawn on the open
  diagram as a **sibling** of the graph, so the document on screen does not move.
  `Compare With Clean Sample` does the same against the shipped clean twin. The
  diff is the **analyzer's** (§11.38) — all three hosts get one answer from one
  implementation — and every one of its `notes[]` goes to the output channel in
  full, with the toast saying how many there are: `−16 nodes` is a claim about two
  documents, not about your code. A new analysis clears the overlay.
- **Suppress a false positive without leaving the editor.** The lightbulb on any
  MLView diagnostic offers `Copy ignore comment`, `Add ignore comment on this
  line` (a `WorkspaceEdit`, so it is one undo away) and `Disable rule MLVxxx in
  .mlview.toml` behind a modal confirm that says the rule stops being reported for
  everyone who opens the repo. The diagram's own rail reaches the same three
  through one message, so both surfaces behave identically.
- **No pip install required.** The VSIX ships the analyzer in
  `vscode-extension/core`. An `mlview` installed in the interpreter wins when its
  schema major matches and it is not older than the bundled copy; otherwise the
  bundled one runs, with `<extension>/core` on `PYTHONPATH`. The status-bar
  tooltip names which of the two answered.

Both chat surfaces register behind a feature check and a `try`/`catch`, so a
chat-API change can never break activation of the diagram, the diagnostics or the
reveal.

### Or just the CLI

```bash
python -m pip install -e analyzer
python -m mlview analyze samples/vision_pipeline --json .mlview/graph.json --html .mlview/report.html --open
python -m mlview issues  samples/vision_pipeline --min-severity high
python -m mlview explain MLV201
python -m mlview analyze --demo --json -          # the golden sample document

python -m mlview analyze samples/vision_pipeline --list-scopes
python -m mlview analyze samples/vision_pipeline --scope unit:train_test_split --html .mlview/split.html --open
python -m mlview analyze samples/vision_pipeline --scope concern:optimization --format summary
python -m mlview analyze samples/vision_pipeline --scope concern:evaluation --depth 1 --format mermaid
python -m mlview issues  samples/vision_pipeline --scope stage:train
python -m mlview render  --graph .mlview/graph.json --scope unit:SmallCNN --format mermaid

python -m mlview init                             # a commented .mlview.toml, rules listed from the registry
python -m mlview diff BASE.json HEAD.json         # what this change added, removed, fixed and broke
python -m mlview analyze . --dataflow ip          # follow values across the object boundary (see below)
```

**Configuration.** `--config FILE`, else `<root>/.mlview.toml`, else
`[tool.mlview]` in `<root>/pyproject.toml` — the **first match wins outright** and
is never merged with the others, and the winner is named in the document's
`configPath`. The file wins for `disable` and `exclude` (a flag may only *add* to
them); a flag wins for everything under `[analysis]` and for `min_confidence`;
`include` is additive both ways. Every mistake in the file — unreadable,
unparseable, wrong type, out of range, unknown key, unknown rule — is one
`config_warning` on the document and never a failed run.

**Comparing two analyses.** `mlview diff BASE.json HEAD.json` writes a separate
`mlview-diff` document: which nodes and edges were added, removed or changed,
which findings are new, fixed or persisting, and a `notes[]` block naming every
reason a `removed` might not mean "deleted" — not analyzed, truncated, projected
away, a different root, a different analyzer. Moving code is not a change: `loc`
is outside the comparison key. It does **no rename detection**, so a renamed file
reads as every node removed plus every node added.

**Following a value across the object boundary.** `--dataflow ip` (default
`local`) turns on interprocedural summaries: a constructor argument reaching
`self.<attr>` and read by a sibling method, a return chain deeper than one level,
an argument intersected over *every* resolved call site. It is off by default for
one release. Every hop multiplies the confidence by an explicit weight, so a
cross-object finding is **never** reported as certain — one hop takes MLView's
strongest leakage rule from `certain` to `likely` — and the hop chain is named in
words on the finding. A chain that runs past the hop cap is not propagated and is
**reported** as a `truncated` diagnostic rather than dropped in silence.

`--scope` takes one selector and `--depth` its 0–2 boundary hops; `--list-scopes`
prints the catalogue of scopable units. An unusable selector exits `1` with
nothing on stdout and the code, the offending term and up to ten candidates on
stderr. An `--html` report always embeds the **whole** graph and merely opens
*at* the scope, so the reader can widen it in the toolbar, and an unscoped run is
byte-identical to what it produced before the feature existed.

**In the report or the panel:** hover a connection to watch the value travel
along it; press `e` / `Shift+E` to walk the selected node's connections; press
`s` to scope to the selection, `[` / `]` to change the depth, and `Shift+S` or
`Esc` to leave.

Exit codes: `0` ok · `1` usage or I/O · `2` `--fail-on` threshold exceeded ·
`3` internal error · `4` nothing analyzable. stdout carries **only** the requested
payload; every log line goes to stderr.

### Adopt on an existing repo

A repository that already has findings cannot be gated on: a realistic 50-file
project starts at **111** of them, so `--fail-on high` exits `2` forever and the
only usable setting is "never gate". The adoption flags fix the arithmetic without
lowering the bar — MLView still analyses the **whole** project, because narrowing
the analysis to the changed files is exactly the fidelity loss that makes a single
file report 3 findings where its directory reports 7 — and then attributes.

```bash
# 1. What did THIS change introduce? (the whole project is still analyzed)
python -m mlview issues . --changed-since origin/main --changed-only

# 2. Or freeze today's list and gate on what comes next.
python -m mlview baseline write --out .mlview/baseline.json
python -m mlview analyze . --baseline .mlview/baseline.json --fail-on high

# 3. Either way, hand the result to the review tool the team already reads.
python -m mlview analyze . --sarif mlview.sarif
```

Every failure path degrades to *"unattributed, showing everything"* with a
diagnostic — never to an error and never to an empty list. If git is missing, the
directory is not a repository, or the base revision is not in the clone, you get
every finding and a line saying so, because a gate that goes green because git was
absent is the one failure a CI gate must never have.

**GitHub Actions.** `tools/action/action.yml` is a composite action. Check the
code out with `fetch-depth: 0` — a shallow clone has no base commit to diff
against — and upload the SARIF with the step GitHub documents for it:

```yaml
permissions:
  contents: read
  security-events: write   # required by upload-sarif
steps:
  - uses: actions/checkout@v5
    with: { fetch-depth: 0 }
  - id: mlview
    uses: realmyang/MLView/tools/action@main
    with:
      base: ${{ github.event.pull_request.base.sha }}
      fail-on: high
  - uses: github/codeql-action/upload-sarif@v3
    if: always()
    with:
      sarif_file: ${{ steps.mlview.outputs.sarif }}
```

Inputs: `path`, `base`, `fail-on` (`high` by default, `none` to report without
ever failing), `baseline`, `sarif`, `version`, `args` and `python-version`.
Outputs: `sarif` and `exit-code`. Inside this repository the action installs the
checkout rather than the release, so it always tests the code it ships with.

**pre-commit.** `.pre-commit-hooks.yaml` exposes two hooks, both with
`pass_filenames: false`, because per-file invocation is the same fidelity bug:

```yaml
repos:
  - repo: https://github.com/realmyang/MLView
    rev: v0.1.0
    hooks:
      - id: mlview-changed    # or `mlview` for the whole project
```

**Claude Code.** `/mlview-issues . --changed-since origin/main` and
`/mlview-issues . --baseline .mlview/baseline.json` do the same thing through the
MCP server; `mlview_issues` takes `changedSince` and `baseline` directly.

---

## Architecture

```mermaid
flowchart TB
  subgraph core["ONE analyzer — the mlview Python package"]
    direction LR
    ingest["ingest<br/>discover · ast.parse"] --> ir["IR<br/>symbols · bindings · scopes"]
    ir --> build["graph builder<br/>stages · nodes · edges · ids"]
    build --> rules["rules<br/>20 codes · confidence · suppression"]
    rules --> emit["emit<br/>json · html · mermaid · text"]
  end

  emit -->|"mlview.api (in-process)"| mcp["claude-plugin/server<br/>MCP: 5 stdio tools"]
  emit -->|"python -m mlview --json - (subprocess)"| ext["vscode-extension<br/>coreClient.ts"]

  mcp --> cc["Claude Code<br/>/mlview · skills · MCP tools"]
  mcp --> html["report.html<br/>self-contained, offline"]
  ext --> panel["webview panel"]
  ext --> diag["Problems panel<br/>DiagnosticCollection"]
  ext --> lm["Copilot<br/>@mlview · #mlviewAnalyze"]

  subgraph viewer["ONE renderer — webview/dist/mlview.js"]
    direction LR
    mount["MLView.mount(root, graph, bridge)"]
  end

  panel --> viewer
  html --> viewer
```

**Three frozen seams**, and nothing crosses them informally:

1. **The process seam** — `python -m mlview analyze <path> --json -`. Both hosts
   call exactly this. Nothing else parses Python.
2. **The in-process seam** — `mlview.api`. The MCP server imports it rather than
   shelling out to itself, so argument handling cannot diverge.
   `tools/verify.py --parity` byte-diffs the two documents anyway.
3. **The render seam** — `window.MLView.mount(el, graph, bridge)`. The only
   host-specific code in the viewer is a seven-method `HostBridge`.

### Directory map

```
MLView/
  docs/                     REQUIREMENTS · ARCHITECTURE · ISSUE_RULES · UX_DESIGN · CONTRACTS
    walkthrough/            the five VS Code walkthrough pages (synced into the extension)
    gallery/                GENERATED, gitignored: every fixture and clean program rendered
  contracts/                FROZEN: graph.schema.json · graph.sample.json
  analyzer/                 the Python package `mlview` — the ONE analyzer
    src/mlview/             ingest · ir · core · knowledge · rules · emit · schema
    tests/                  core · rules · fixtures · clean corpus
  webview/                  the ONE renderer; dist/mlview.{js,css} is the bundle
  vscode-extension/         panel · diagnostics · reveal · chat · LM tools · core (the bundled analyzer)
  claude-plugin/            plugin.json · .mcp.json · commands · skills · server · hooks · vendor
  samples/                  vision_pipeline (dirty) + vision_pipeline_clean (twin)
  tools/                    sync-assets.py · sync-core.py · verify.py · wheel_check.py · action/
  analyzer/tools/           gen_rule_docs.py · gen_gallery.py · the scope fixture generators
  scripts/                  build · e2e (PowerShell and sh) · the doc gate
  .claude-plugin/           marketplace.json — the repo doubles as a local marketplace
  .github/workflows/        ci.yml — the CI matrix (see "Continuous integration")
                            nightly.yml — the 2000-case scope fuzz, once a day
  .workflows/               multi-agent orchestration scripts; not part of the product
  .mlview/                  generated output (graph.json, report.html)
```

**One agent owns each directory** and no agent writes into another's.
`tools/sync-assets.py` is the only thing that writes `vscode-extension/media/`
and `analyzer/src/mlview/emit/assets/`; `tools/sync-core.py` is the only thing
that writes `claude-plugin/vendor/` **and `vscode-extension/core/`**, the two
vendored copies of the analyzer that let the plugin and the VSIX work with no pip
install at all. Both are gated: `tools/verify.py --all` fails on either drifting.

---

## Tests

```bash
PYTHONUTF8=1 python -m pytest analyzer/tests -q        # analyzer core + rules
PYTHONUTF8=1 python -m pytest claude-plugin/tests -q   # MCP handshake, budgets, manifests
cd webview && npm test                                 # layout, bundle hygiene, parity, contrast
cd vscode-extension && npm test                        # protocol, ranges, CSP, digest, mapping
```

The whole thing, plus the samples and the parity gates, in one table:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
```

```sh
sh scripts/e2e.sh
```

### Continuous integration

`.github/workflows/ci.yml` runs the gate table on every push and pull request,
so "it works" is a statement about thirteen jobs — twelve on a branch push,
where macOS is skipped — rather than about one machine. Nine job definitions,
three of which fan out over a matrix:

| Job | Runner | What it runs |
|---|---|---|
| `analyzer` | ubuntu x Python 3.10 / 3.11 / 3.12 / 3.13 | the analyzer suite, `contracts/validate_sample.py`, and `--demo` compared byte for byte against `contracts/graph.sample.json` |
| `claude-plugin` | ubuntu, Python 3.13 | the plugin suite under `pytest -n auto`, then `tools/sync-core.py --check` |
| `webview` | ubuntu x Node 20 / 22 | `npm run check`, `build`, `test`, then `tools/sync-assets.py --check` against the bundle just built |
| `vscode-extension` | ubuntu, Node 20 | `npm run check`, `compile`, `test`, and the doc gate with its self-test |
| `e2e (ubuntu, sh)` | ubuntu, Python 3.13 + Node 20 | `sh scripts/e2e.sh` — all 20 steps, uploading the emitted reports |
| `e2e (windows, powershell)` | windows, Python 3.13 + Node 20 | `scripts/e2e.ps1` — the same 20 steps under the other driver |
| `smoke (macos)` | macos, Python 3.13 + Node 20 | the analyzer and viewer suites — **only on push to `main` and on pull requests** |
| `packaging (wheel + vsix)` | ubuntu, Python 3.13 + Node 20 | `tools/wheel_check.py` (build the wheel, `pip install` it into a throwaway venv, analyze with it), `sync-core.py --check`, `make_icon.py --check`, `npm run package`, then `scripts/vsix_check.py` — the 1 MB ceiling, the whole bundled analyzer, every rule page, no `__pycache__`, with the measured figures echoed |
| `accuracy corpus` | ubuntu, Python 3.13 | `tools/accuracy.py` over the ten labelled programs, then `pytest analyzer/tests/accuracy` — zero `forbidden` findings, and recall and graph fidelity may only ratchet up |

`.github/workflows/nightly.yml` is separate and deliberately not on the push
path: `python tools/verify.py --scopes --fuzz 2000` builds the viewer from that
commit's source and fuzzes the two `project()` ports for about 16 s, on a 04:17
UTC schedule plus `workflow_dispatch`. A failing run prints the seed that
reproduces it (`MLVIEW_FUZZ_SEED=<n>`). GitHub only schedules cron from the
default branch, so it starts firing once this lands on `main`.

The matrix is deliberately lopsided: the repository is private, so minutes are
metered and weighted (windows 2x, macos 10x), and the fan-out is therefore
ubuntu-only. **Measured, not estimated** — the last full green push
(run 34422156964, Sprint 5's process wave) took **6m25s of wall time and ~68
billable minutes** across **13 green jobs**: 24 of them the eleven ubuntu jobs,
14 the one Windows job (6m22s, billed as 7 min at 2x) and **30 the one macOS
job** (2m30s, billed as 3 min at 10x). The rounding rule is what
makes that figure reproducible, so it is stated rather than assumed: **each job
is rounded up to a whole minute on its own** and then multiplied by its runner's
weight — summing the seconds first and rounding once gives a smaller number that
GitHub does not charge. That run is the first branch push on which `smoke
(macos)` has ever run — its guard was widened to `sprint5` for exactly one
verification push and restored immediately after — so it is also the first
*measurement* of the macOS job's share rather than an estimate of it. A branch
push with the job skipped is the other **~38**. That single job is therefore over a third of a full run's bill for two
suites ubuntu already runs; because the multiplier and the rounding, not the
job's contents, are what cost the 20, trimming it cannot help. That decision was
taken in Sprint 4: macOS is now covered locally on a development machine that
runs the full e2e table before every push, so the job runs **only on push to
`main` and on pull requests** — the two moments where nobody's laptop is the
referee — and leaves the pre-merge signal intact.
`claude plugin validate` is not available on a hosted runner;
the test that would call it skips itself when the CLI is absent, so gates 10 and
11 of `scripts/README.md` are still Windows-desk gates.

### The three parity gates

`tools/verify.py` is what stops the two hosts from slowly acquiring different
analyzers or different viewers:

```bash
python tools/verify.py --all
```

1. **One analyzer** — the CLI document and the document produced by a real MCP
   `tools/call` (driven as a subprocess over stdio) are byte-identical after
   stripping `generator.generatedAt` and `stats.durationMs`, the only two fields
   the contract allows to vary.
2. **One renderer** — `mlview.js` and `mlview.css` are SHA-256-identical across
   `webview/dist/`, `vscode-extension/media/` and
   `analyzer/src/mlview/emit/assets/`, and a freshly emitted document's
   `generator.rendererSha` equals that hash. A drifted viewer is detectable from
   the data alone.
3. **One version** — the same version string in `mlview.version`,
   `analyzer/pyproject.toml`, `vscode-extension/package.json`,
   `claude-plugin/.claude-plugin/plugin.json` and `webview/package.json`.

Gate 1 runs the CLI against `analyzer/src` and the server against
`claude-plugin/vendor` **on purpose**, so a stale vendored copy shows up as a
behavioural difference rather than only as a file-hash mismatch; the table
carries a `vendor: synced core` row alongside it saying which of the two it was.

---

## Status — what is actually verified

This is a prototype built in one session. The distinction between "works" and
"compiles" is kept honest here.

**Exercised end to end on this machine (Windows 11, Python 3.13, Node 20.9,
VS Code 1.136):**

- The analyzer core and its rules, with the full pytest suite green.
- The Claude Code plugin: a real stdio handshake with the MCP server, spawned as
  a subprocess with `PYTHONPATH` pointing only at `vendor/` — which also proves
  the no-`pip install` path.
- The CLI, including `--demo` emitting `contracts/graph.sample.json`
  byte-identically, and every documented exit code.
- The self-contained HTML report: one file, zero external references — including
  the three scoped demo reports (`.mlview/split.html`, `optimization.html`,
  `evaluation.html`).
- All four parity gates, the scope gate included: the ten-selector battery in
  `contracts/scope.cases.json` projects identically through the Python
  `analyzer/src/mlview/core/project.py` and the TypeScript
  `webview/src/scope/project.ts` (`python tools/verify.py --scopes`).

**Compile-verified only:**

- **GitHub Copilot is not installed on this machine.** The chat participant
  (`@mlview`) and the three language-model tools are contributed correctly, type-
  check clean, and each tool body is extracted into a pure function that is
  smoke-tested with `vscode` mocked — but they have never been invoked by a real
  Copilot agent. **The exercised Copilot surface is the `DiagnosticCollection`**:
  findings in the Problems panel are what a Copilot agent reads today, and that
  path is tested.
- The VS Code extension is verified by `tsc --noEmit` and its unit suite; the F5
  Extension Development Host path has not been run under automation.

**Known gaps:**

- The scoped jsdom render step in `scripts/e2e.sh` reports SKIP until
  `tools/sync-assets.py` has run: a report written before the sync inlines the
  previous viewer bundle, which has no scope UI to assert against. The
  bundle-hash rows of `tools/verify.py` report the same one cause, and a full
  `scripts/build` followed by `scripts/e2e` never hits it.
- `--list-scopes` lists scopable **units** only
  (`analyzer/src/mlview/emit/scope_out.py`). The four concerns and the eight
  stage ids are discovered from this README, from the MCP tool description, or
  from the candidate list an unusable selector prints — not from that command.
- Both sample workspaces and all thirty-six rule pages under `docs/rules/` are on
  disk now, so the degradation paths written for a checkout without them --
  `scripts/e2e` reporting `SKIP` instead of failing, `tools/verify.py` falling
  back to the rule fixtures as its parity corpus, `mlview_explain <code>`
  returning the rule's registry record instead of a doc page -- are never taken
  by a normal run, and nothing tests them.
- Loop nesting is flattened one level: a batch loop inside an epoch loop is
  parented to the enclosing function unit, not to the epoch loop. Frozen
  invariant 1.1.2 (a parent must have a strictly lower level) plus a three-value
  level enum cannot express four levels of real nesting. The true nesting
  survives in the IR -- `LoopIR.depth` and `LoopIR.parent_loop` in
  `analyzer/src/mlview/ir/model.py` -- it just cannot be drawn.
- Cross-file call following is one level and module-local, as the contract
  specifies: `analyzer/src/mlview/ir/resolve.py` fills `target_function` for a
  call into a workspace module, and stops there. A rule cannot chase a helper
  that a helper calls.
- Notebooks are analyzed only when asked (`--include-notebooks`, `[paths] notebooks`,
  or `mlview.includeNotebooks` in VS Code); without it they are counted and declared
  exactly as before, as `notebooksSkipped` plus a `notebook_skipped` diagnostic, and
  no cell is parsed. When asked, each notebook becomes one generated module under
  `.mlview/notebooks/` and every `Loc` names **that** file -- `Loc` is frozen and
  cannot carry a cell index -- with the cell mapping riding beside it in
  `Node.attrs.notebook` / `.cell` / `.cellLine` and in one evidence row per finding.
  The VS Code host re-anchors findings onto `vscode-notebook-cell:` URIs from that
  evidence, so a squiggle lands in the cell; a *related* location still points at the
  generated module, which is a real file that re-opens and slices. Cell execution
  order is not recoverable from an `.ipynb` at all, so a non-monotonic
  `execution_count` de-rates MLV101, MLV203 and MLV209 and says so.
- Bindings are flow-insensitive within a scope (`analyzer/src/mlview/ir/bindings.py`);
  rules that care about ordering compare line numbers explicitly.
- `analysisProgress` is posted only when the diagram panel is open. The extension
  passes `--progress-json` exactly then (`vscode-extension/src/progress.ts`), so a
  headless run — `Show ML Issues`, the chat digests, the language-model tools —
  still shows an indeterminate spinner and emits the bytes it always emitted.
- The host renders the coverage caveat as text only — the status-bar tooltip, the
  panel tab description and the digests (`vscode-extension/src/coverage.ts`). The
  in-canvas banner and chip are the viewer's, drawn from `graph.diagnostics` in
  `webview/src/ui/chrome.ts`, which the host passes through untouched.
- `mlview_issues`'s `groupBy` folds the rows inside the MCP server
  (`claude-plugin/server/mlview_groups.py`), which is where the plugin's grouping
  lives. `/mlview-issues --group-by` therefore groups through the MCP tool; its
  `Bash` fallback line groups only once the matching `--group-by` flag lands on
  `analyzer/src/mlview/cli.py`.
- The framework gate on the absence rules (`MLV301`, `MLV302`, `MLV501`, ...)
  reaches one import hop, no further. `ctx.wrappers_for()` in
  `analyzer/src/mlview/rules/context.py` de-rates a finding only when a
  Lightning / HF Trainer / accelerate / ignite / fastai / DDP / FSDP wrapper is
  in the finding's *own* module or in a workspace module that one imports, so a
  wrapper two hops away is invisible to it and the finding keeps full weight.
  When the gate does fire it caps severity at `medium`, multiplies confidence by
  0.4 and says so in a `framework_suppressed` diagnostic; it never deletes a
  finding.
- `MLV201`'s `negation_absent` evidence line is written off the workspace-wide
  `ctx.wrappers` rather than the per-module set the gate actually uses
  (`analyzer/src/mlview/rules/r_trainloop.py`), so an ungated hand-written loop
  in a workspace that also contains a Lightning module reads "framework wrapper
  detected: Lightning" next to a `certain` finding. The score is right; that one
  evidence sentence contradicts it.

---

## Design documents

Four of the five are **plan records**: they say what was *decided*, not what was built, and `scripts/check_docs.py` link-checks them and nothing else so that editing one to match the code cannot quietly erase a decision (it fails the run on a sentence in one that reports build state). What the software actually does today is this file, `docs/STATUS.md` and `scripts/README.md`, all three of which the doc gate holds to the tree.

| Document | What it settles |
|---|---|
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | What must be true when we are done, as testable acceptance criteria |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The seven analyzer passes, the three seams, directory ownership |
| [`docs/CONTRACTS.md`](docs/CONTRACTS.md) | **Normative.** The schema, the CLI, the MCP tools, the message protocol. Section 10 overrides everything above it. |
| [`docs/ISSUE_RULES.md`](docs/ISSUE_RULES.md) | The thirty-six rules, their evidence and their false-positive traps |
| [`docs/UX_DESIGN.md`](docs/UX_DESIGN.md) | Layout, tokens, markers, states, interaction |

License: MIT.
