# MLView — VS Code extension

Turns the Python ML code in a workspace into **one interactive, issue-annotated workflow
diagram**, plus a Problems-panel list of what is likely broken, from **static analysis only**.
No code is imported or executed, nothing touches the network, and neither PyTorch nor
scikit-learn needs to be installed.

It is part of [MLView](https://github.com/realmyang/MLView): the repository root's
[`README.md`](../README.md) is the overview — screenshots, the ninety-second quick start for all
three hosts, the rule families and the measured accuracy. **Nothing is published yet**: the
extension is not on the VS Code Marketplace or Open VSX, so installing it means cloning the
repository and either pressing F5 (below) or building a VSIX with `npm run package`.

This extension is the **host adapter**. It transports and renders; it never analyses:

| It does | It never does |
|---|---|
| Spawn `python -m mlview analyze … --json -` and parse the graph | Parse Python |
| Host the shared viewer bundle in a webview | Compute severities or duplicate a rule |
| Publish diagnostics, CodeLens, reveal, chat and LM surfaces | Render anything of its own |

---

## Requirements

- **VS Code 1.100.0 or newer** (`engines.vscode: ^1.100.0`).
- **Python 3.10+** with the `mlview` core package importable by that interpreter.
  Install it from this repo with `pip install -e <repo>/analyzer`, or let the extension offer
  **Install MLView core** when it cannot find it.
- The `ms-python.python` extension is *optional*: it is consulted when present, and the
  interpreter chain works without it.

### How the interpreter is chosen

In order, each candidate validated as Python ≥ 3.10 and then handshaken with
`-X utf8 -m mlview --version --json`:

1. the `mlview.pythonPath` setting
2. the Python extension's active environment (`getActiveEnvironmentPath` → `resolveEnvironment`)
3. `python.defaultInterpreterPath`
4. a PATH probe: `python`, `py -3`, `python3`

The result is memoized and recomputed when the interpreter or the settings change. Every step
is written to the **MLView** output channel, so a failure names the exact candidates tried and
why each was rejected. When the core is missing, or its graph schema major version differs from
this extension's, the notification and the in-panel banner offer **Install MLView core**,
**Select Interpreter** and **Show Output**.

Every spawn uses `shell: false`, an absolute interpreter path, `-X utf8` in argv and
`PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` in the environment — without which cp1252 mangles the
JSON on the first non-ASCII identifier or path on Windows.

---

## Running it from source (F5)

```sh
cd vscode-extension
npm install
npm run compile          # esbuild -> out/extension.js (cjs, node, external:vscode)
```

The three lines are the same in PowerShell. `npm install` needs **Node 20 or newer**; the
analyzer it spawns needs **Python 3.10+**, and `pip install -e ../analyzer` from a clone is the
quickest way to have one (the VSIX bundles its own copy instead).

Then press **F5** in VS Code with `vscode-extension/` open. The bundled launch configuration
starts an Extension Development Host with `--extensionDevelopmentPath=${workspaceFolder}` and
opens `${workspaceFolder}/../samples/vision_pipeline`.

From a terminal instead:

```sh
code --extensionDevelopmentPath=<abs>/vscode-extension <abs>/samples/vision_pipeline
```

```powershell
code --extensionDevelopmentPath=<abs>\vscode-extension <abs>\samples\vision_pipeline
```

Other scripts: `npm run check` (`tsc --noEmit`), `npm test` (`node --test`, which rebuilds the
bundles first), `npm run watch` (syncs the bundled core once, then rebuilds the bundles on every
edit), `npm run sync:rule-docs` (copies `../docs/rules/MLV*.md` into
`docs/rules/`; `npm run compile` and `npm run pretest` already run it), and `npm run package`
(`npx --yes @vscode/vsce package --no-dependencies --allow-missing-repository` — `vsce` is not a
devDependency, so this resolves it through npx from the local npm cache). Packaging is verified
to produce `mlview-0.1.0.vsix` (29 files, ~121 KB, including all 20 rule pages) on Node 20.9,
but it is **not** on the acceptance path.

### The viewer bundle

The diagram itself is the shared viewer, copied into `media/` by `tools/sync-assets.py` (run by
`scripts/build.ps1`). Until that has run, `media/` holds only its README and the panel shows a
"viewer bundle not built" message with the command to run — analysis, the Problems panel,
CodeLens and *Reveal in Diagram* keep working regardless.

---

## Commands

| Command | Default binding | What it does |
|---|---|---|
| `MLView: Visualize ML Workflow (Current File)` | editor title bar / context menu | Analyzes the active Python file and opens the diagram beside it |
| `MLView: Visualize ML Workflow (Workspace)` | — | Analyzes the whole workspace |
| `MLView: Re-analyze` | — | Re-runs the last scope and re-probes the interpreter |
| `MLView: Show ML Issues` | status bar click | Quick-pick of every finding; picking one opens the line |
| `MLView: Reveal in Diagram` | **Alt+M**, editor context menu | Selects the node whose range most narrowly contains the cursor |
| `MLView: Scope Diagram to Symbol` | **Alt+Shift+M**, editor context menu | Draws only the unit the cursor is in, plus one hop of context |
| `MLView: Clear Diagram Scope` | — | Puts the whole workspace back on the diagram |
| `MLView: Export HTML Report` | — | Save dialog, then `analyze --html <file>` at the diagram's current scope; offers to open it |
| `MLView: Export Diagram as SVG` | — | Asks the open diagram for a standalone SVG of the whole diagram, the current view or the current scope, then a save dialog |
| `MLView: Export Diagram as PNG` | — | The same, as a raster image |
| `MLView: Select Active Folder` | status-bar tooltip link | **Multi-root only.** Chooses which open folder the diagram, the status bar and the chat / LM answers describe; a single-folder window never sees it |
| `MLView: Open MLView Configuration` | — | Opens the `.mlview.toml` (or the `pyproject.toml` `[tool.mlview]` table) MLView passes to `--config`, creating one with `mlview init` when there is none |
| `MLView: Create Baseline From Current Findings` | — | Runs `mlview baseline write` over the current scope and offers to point `mlview.baselinePath` at the result |
| `MLView: Save Current Graph As Comparison Base` | — | Writes the current analysis to `.mlview/comparison-base.json` verbatim — no re-analysis, so the base is the document you were looking at |
| `MLView: Compare With Saved Base` | — | Re-analyzes, then runs `mlview diff base head --json -` and draws the overlay on the open diagram. The toast carries the headline and the number of caveats; the caveats themselves are in the output channel |
| `MLView: Compare With Clean Sample` | — | The same, with `samples/vision_pipeline_clean` (or a `vision_pipeline_clean` under the root) as the base. A demo affordance: the pair are siblings, not two commits, and the overlay's `different-roots` note says so |
| `MLView: Select Python Interpreter` | — | Python extension picker, or the `mlview.pythonPath` setting |
| `MLView: Show Output` | — | The MLView output channel |
| `MLView: Open Rule Documentation` | — | Opens the offline `MLVnnn.md` rule page |

### Scoping the diagram to part of the codebase

`MLView: Scope Diagram to Symbol` (**Alt+Shift+M**) resolves the cursor to its **enclosing
unit** — the narrowest node containing the line, then up the containment chain to the
class, function or loop that owns it — and posts a `unit:<qualname>` selector to the diagram.
The panel then shows only that unit, its descendants and one hop of neighbours, and the tab
retitles itself `MLView — validate()`. The node count lives inside the panel, on the viewer's
own scope breadcrumb (`Scoped to validate() · depth 1 · 9 of 54 nodes`) — a `WebviewPanel`
exposes a title and no subtitle. `MLView: Clear Diagram Scope` restores the whole workspace,
and does nothing at all when no diagram is open. With the cursor inside no node at all,
nothing is scoped and a toast says so: a scope is never guessed.

### Exporting the picture (VIEW-07)

`MLView: Export Diagram as SVG` and `... as PNG` ask the **open diagram** for the picture:
the extension host cannot draw one, because the geometry — lane bands, card rectangles,
routed edge paths, resolved theme colours — exists only inside the viewer once it has laid
the graph out. So the command posts `requestExport { kind, scope }`, the viewer renders and
answers with `exportFile`, and the extension decodes the bytes, opens a save dialog in the
workspace folder and writes the file with `workspace.fs`. A webview cannot download a file
of its own — an `<a download>` in a VS Code webview is inert — which is why the bytes travel
through the message protocol rather than out of the sandbox.

Each command first asks **what** the picture should contain: the whole diagram, the current
view, or the current scope (offered only while the diagram is scoped). Both commands accept
that choice as an argument, so a keybinding can skip the pick:
`{ "command": "mlview.exportSvg", "args": "all" }`.

The host writes only what it recognises: a payload that is not the format that was requested
is refused before the save dialog opens, and a name the viewer suggests is used as a
**basename only**. Nothing is exported while the diagram is closed — the command says so
rather than opening an empty picture.

`MLView: Export HTML Report` follows the scope: a report exported from a scoped panel opens on
the same projection (`--scope <SPEC>`, plus the depth the viewer last saved). The file still
embeds the **whole** graph, so nothing is lost — the report's own scope bar clears or widens it.

Three things a scope deliberately does **not** do:

- it never re-runs the analyzer — the viewer holds the whole document and re-projects locally;
- it never changes the Problems panel, the status-bar count or the issue quick pick. Those keep
  reporting every finding in the workspace (a view must not quietly hide defects);
- it never touches the severity filter chips. Filters dim, a scope removes and relayouts, and
  clearing one never clears the other.

A status-bar item shows the live issue counts (`$(graph) MLView: 2 high · 3 med · 1 low`) and
clicks through to the issue list. A **MLView: show in diagram** CodeLens sits above every
analyzed unit.

### Structured fixes (H5)

Eleven of the analyzer's rules describe a single-line mechanical repair, and five of them now
compute it. Where one exists, `Issue.fix` carries `{title, safety, edits[]}` and the lightbulb
on that finding offers it. Five rules travel with the offer:

- **rules opt in.** A finding with no `fix` produces no action, so an empty lightbulb means
  "no edit was computed", never "the tool had nothing to say";
- **the edits come from the analyzer's AST**, not from string splicing in the editor;
- **nothing below the `likely` confidence bucket is ever offered an edit**;
- **`isPreferred` only for `mechanical`** — a `needs-review` fix (one that inserts a
  statement) is offered but never promoted, so `Ctrl+.`+Enter cannot land on a judgement call;
- **never auto-applied.** Every edit carries `needsConfirmation` and is applied with
  `isRefactoring`, so VS Code routes it through the refactor **preview**. There is deliberately
  no `source.fixAll` kind, which is the kind `editor.codeActionsOnSave` runs unattended.

An edit naming a file outside every open workspace folder is refused outright, and a fix whose
second edit escapes is refused whole — half a fix is a broken file. The diagram's rail reaches
the same code path through the `applyFix` message, and sends only the **issue id**: the edits
are read from the host's own copy of the graph, never from the webview.

**All three surfaces are one path.** The lightbulb carries a *command*, not a `WorkspaceEdit`:
an attached edit is applied by VS Code itself, which would let the surface you actually click
skip the checks the palette command and the rail go through. So the lightbulb, `MLView: Apply
Fix` and the rail all run the same function, and all three refuse the same two states — a
buffer with **unsaved changes** (the analyzer read the file on disk) and a file **shorter than
the analysis saw**. Save and re-analyze, then apply.

What it cannot do: it cannot prove the analyzer's coordinates still match a buffer you have
edited since the analysis — a saved edit that moved a line is invisible to it, because the
graph carries no content hash. The two refusals above are the cases it can prove; the preview
is the mitigation for the rest, not a proof — read the diff.

### Comparing two analyses (VIEW-08)

`MLView: Save Current Graph As Comparison Base` writes the analysis you are looking at to
`.mlview/comparison-base.json` — the document verbatim, with no second analysis, because a
diff whose two sides came from two different runs is the mistake that is hardest to notice.
`MLView: Compare With Saved Base` re-analyzes, then runs `mlview diff base head --json -` and
posts the overlay to the open diagram. `MLView: Compare With Clean Sample` does the same with
the shipped clean twin as the base.

The comparison is computed **by the analyzer** (`CONTRACTS.md` §11.38), never here: all three
hosts must give one answer. The overlay is a separate document, so the graph on screen does
not move and `schemaVersion` stays `1.0`.

**Read the caveats.** `−16 nodes` is a claim about two documents, not about your code: a
missing id can also mean a truncated run, a projected view, a different workspace root or a
different analyzer version, and a renamed file reads as everything removed plus everything
added. Every one of the overlay's `notes[]` goes to the MLView output channel in full, and the
toast says how many there are. A new analysis clears the overlay, so a comparison can never be
drawn over a graph it never saw.


## Settings

| Setting | Default | Meaning |
|---|---|---|
| `mlview.pythonPath` | `""` | Interpreter override; first in the resolution chain |
| `mlview.analyzeOnSave` | `true` | Re-analyze 400 ms after a Python file is saved |
| `mlview.currentFileAnalysisScope` | `package` | What **MLView: Visualize (Current File)** analyzes before scoping the diagram to the file: `file` (fastest, and reported as incomplete — the cross-file rules cannot fire), `package`, or `workspace` |
| `mlview.exclude` | `[]` | Extra discovery excludes, added to the analyzer defaults |
| `mlview.configPath` | `""` | The `.mlview.toml` (or `pyproject.toml` with `[tool.mlview]`) passed to `--config`. Empty means discover it. **The file wins** for `[rules].disable` and `[paths].exclude`; the two settings below are additive filters on top |
| `mlview.baselinePath` | `""` | A `mlview baseline write` file whose findings stop counting. Never auto-discovered — name it here on purpose |
| `mlview.includeNotebooks` | `false` | Analyze `.ipynb` as well as `.py` (passes `--include-notebooks`). See **Notebooks** below |
| `mlview.maxFiles` | `500` | Discovery cap |
| `mlview.maxNodes` | `400` | Graph cap; exceeding it sets `stats.truncated` |
| `mlview.minSeverity` | `low` | Lowest severity shown in Problems and in the digests |
| `mlview.minConfidence` | `0.6` | Lowest confidence published as a diagnostic |
| `mlview.diagnosticsEnabled` | `true` | Publish to the Problems panel at all |
| `mlview.diagnosticSeverity` | `warning` | `warning`: high → Warning. `error`: high → Error |
| `mlview.disabledRules` | `[]` | Rule codes to hide, e.g. `["MLV601"]` — in the Problems panel, the quick pick, the chat/LM digests **and** on the diagram (the host posts the surviving codes as a `setFilter` keep-list) |
| `mlview.codeLens` | `true` | The "show in diagram" CodeLens |
| `mlview.trace` | `off` | `off` / `messages` / `verbose` output-channel verbosity |

Analysis is disabled in **Restricted Mode** (`capabilities.untrustedWorkspaces: "limited"`),
because it spawns an interpreter. Trust the folder to enable it.

### Notebooks

Off by default. With `mlview.includeNotebooks` off the extension passes exactly the argv it
passed before notebooks existed, and the status bar says how many notebooks it set aside
(`3 notebooks not analyzed`) rather than reporting a clean workspace it never read.

Turn it on and:

- the flag reaches the analyzer, and changing the setting **re-runs** the analysis (it is the
  only `mlview.*` key that does — every other one re-filters a graph the host already has);
- **findings land in the cell.** The analyzer converts each notebook to one generated module
  under `.mlview/notebooks/` and its locations name that file, because `Loc` is frozen and
  cannot carry a cell index. The extension re-anchors every notebook finding onto the
  `vscode-notebook-cell:` document of the cell it came from, so the squiggle appears in the
  cell you are looking at. With the notebook closed there is no cell URI to use, and the
  finding falls back to the `.ipynb` itself;
- saving the notebook re-analyzes (`onDidSaveNotebookDocument`; saving a notebook does **not**
  fire the text-document save event, so this is a second listener, not the same one);
- the status-bar tooltip reads `N notebooks analyzed`, and says both when a run analyzed some
  notebooks and could not read others.

**What this cannot know.** Cell execution order. A notebook records only the `execution_count`
of its last run, so document order is an assumption. When those counts are not monotonic the
analyzer says so in its `notebook_analyzed` note and de-rates the order-sensitive rules
(MLV101, MLV203, MLV209) rather than pretending. Related locations on a notebook finding still
point at the generated module: they carry no cell mapping of their own, and the generated file
is real and opens.

---

## GitHub Copilot integration — what is verified and what is not

**Read this before demoing.** Copilot is **not installed on the build machine**, so the honest
split is:

- **The Problems panel is the exercised Copilot surface.** Findings are published to a
  `DiagnosticCollection` named `mlview` with `source: "MLView"`, a `code` object whose `target`
  is a **local** rule-doc file, and `relatedInformation` built from each finding's related
  locations. Copilot Chat's `#problems` context, inline fix and agent mode all read the Problems
  panel — so this delivers Copilot support with zero Copilot API surface and no Copilot install.
  This path is covered by tests and works today.
- **The `@mlview` chat participant and the three language-model tools are compile-verified
  only.** They are declared in `package.json` (each tool carrying **both**
  `canBeReferencedInPrompt: true` **and** a `toolReferenceName`, without which agent mode never
  calls a tool), they type-check against the real `@types/vscode@1.100.0` surface, and every
  tool body is an exported pure function exercised by `node --test` with a stubbed core. They
  have **not** been run against a live Copilot session on this machine.

Closing that gap is a person's job, not a test's: [`../docs/VALIDATION.md`](../docs/VALIDATION.md)
session A is the 30-minute script for it — what to click, what "working" means for each check,
and where to write down what you saw.

Registration is feature-detected: `vscode.chat?.createChatParticipant` and
`vscode.lm?.registerTool` are `typeof`-guarded inside try/catch, and when they are absent the
output channel logs `chat API unavailable - participant not registered` and activation continues
normally. The diagram, diagnostics, reveal, CodeLens and status bar register unconditionally.

The `@mlview` participant answers **from the local digest and never calls a language model**:
`/diagram` opens the panel, `/issues` streams every finding followed by a clickable
`file:line` anchor, `/explain MLV201` explains one rule or one stage, and the free-form path
summarises the pipeline. Every reply says plainly that nothing left the machine.

---

## Layout

```
src/
  extension.ts       activation, commands, status bar, wiring    panel.ts        webview + CSP + protocol host
  pythonEnv.ts       the four-step interpreter chain             diagnostics.ts  the Problems-panel publisher
  coreClient.ts      the only place that spawns the analyzer     codelens.ts     "show in diagram" lenses
  locationIndex.ts   cursor -> narrowest node, then its unit     revealInDiagram.ts  Alt+M
  scopeCommands.ts   cursor -> `unit:<qualname>` scope selector   (Alt+Shift+M, clear scope)
  chat.ts            the @mlview participant                     lmTools.ts      the three LM tools
  protocol.ts        the typed message unions + guards           digest.ts       the <= 4 KB model payloads
  panelState.ts      the pre-handshake message queue + preserve   graph.ts        the graph types and guards
  location.ts        THE 1-based -> 0-based conversion, and the workspace-containment guards
                                                                 issues.ts, settings.ts, log.ts
test/                node --test suites with a mocked `vscode` module
tools/               sync-core.mjs, sync-rule-docs.mjs (build-time only; excluded from the .vsix)
core/mlview/         BUILD ARTIFACT: the bundled analyzer, written by tools/sync-core.mjs
media/               the synced viewer bundle (written only by tools/sync-assets.py)
docs/rules/          offline rule pages, copied from <repo>/docs/rules by `npm run compile`
```

`core/mlview/` is **not in git**. `compile`, `pretest` and `vscode:prepublish` all run
`tools/sync-core.mjs`, which writes it out of `<repo>/analyzer/src/mlview`, so a fresh clone
has no `core/` until one of those has run — and that is correct, because a VSIX is packaged
from a working tree and a second tracked copy of the analyzer is a second thing to drift.
(The Claude Code plugin's `vendor/mlview` is the opposite case and *is* tracked: a marketplace
install copies the plugin directory verbatim off a git ref, with no build step to write
anything.)

`docs/rules/` is what makes a diagnostic's `code.target` a **local** file in an installed
extension: `<extensionPath>/docs/rules/MLV201.md`. The `<repo>/docs/rules` fallback in
`diagnostics.ts` only ever resolves in a dev checkout, so the pages are synced into the
extension at build time and shipped in the `.vsix`.

---

## More documentation

| Document | What it is for |
|---|---|
| [`../README.md`](../README.md) | What MLView is, and the ninety-second demo |
| [`../docs/STATUS.md`](../docs/STATUS.md) | What is verified today, and the known gaps |
| [`../docs/CONTRACTS.md`](../docs/CONTRACTS.md) | **Normative.** The schema, the CLI, the MCP tools, the message protocol |
| [`../docs/VALIDATION.md`](../docs/VALIDATION.md) | Validating this host by hand on another machine, and publishing it |
| [`../CHANGELOG.md`](../CHANGELOG.md) | The dated history, newest first |
