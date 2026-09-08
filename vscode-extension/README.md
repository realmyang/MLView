# MLView — VS Code extension

Turns the Python ML code in a workspace into **one interactive, issue-annotated workflow
diagram**, plus a Problems-panel list of what is likely broken, from **static analysis only**.
No code is imported or executed, nothing touches the network, and neither PyTorch nor
scikit-learn needs to be installed.

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

```powershell
cd vscode-extension
npm install
npm run compile          # esbuild -> out/extension.js (cjs, node, external:vscode)
```

Then press **F5** in VS Code with `vscode-extension/` open. The bundled launch configuration
starts an Extension Development Host with `--extensionDevelopmentPath=${workspaceFolder}` and
opens `${workspaceFolder}/../samples/vision_pipeline`.

From a terminal instead:

```powershell
code --extensionDevelopmentPath=<abs>\vscode-extension <abs>\samples\vision_pipeline
```

Other scripts: `npm run check` (`tsc --noEmit`), `npm test` (`node --test`, which rebuilds the
bundles first), `npm run watch`, `npm run sync:rule-docs` (copies `../docs/rules/MLV*.md` into
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

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `mlview.pythonPath` | `""` | Interpreter override; first in the resolution chain |
| `mlview.analyzeOnSave` | `true` | Re-analyze 400 ms after a Python file is saved |
| `mlview.exclude` | `[]` | Extra discovery excludes, added to the analyzer defaults |
| `mlview.maxFiles` | `500` | Discovery cap |
| `mlview.maxNodes` | `400` | Graph cap; exceeding it sets `stats.truncated` |
| `mlview.minSeverity` | `low` | Lowest severity shown in Problems and in the digests |
| `mlview.minConfidence` | `0.6` | Lowest confidence published as a diagnostic |
| `mlview.showSpeculative` | `false` | Reserved; not implemented in this prototype (the frozen `setFilter` message has no confidence channel) |
| `mlview.diagnosticsEnabled` | `true` | Publish to the Problems panel at all |
| `mlview.diagnosticSeverity` | `warning` | `warning`: high → Warning. `error`: high → Error |
| `mlview.disabledRules` | `[]` | Rule codes to hide, e.g. `["MLV601"]` — in the Problems panel, the quick pick, the chat/LM digests **and** on the diagram (the host posts the surviving codes as a `setFilter` keep-list) |
| `mlview.codeLens` | `true` | The "show in diagram" CodeLens |
| `mlview.followCursor` | `false` | Reserved; not implemented in this prototype |
| `mlview.trace` | `off` | `off` / `messages` / `verbose` output-channel verbosity |

Analysis is disabled in **Restricted Mode** (`capabilities.untrustedWorkspaces: "limited"`),
because it spawns an interpreter. Trust the folder to enable it.

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
tools/               sync-rule-docs.mjs (build-time only; excluded from the .vsix)
media/               the synced viewer bundle (written only by tools/sync-assets.py)
docs/rules/          offline rule pages, copied from <repo>/docs/rules by `npm run compile`
```

`docs/rules/` is what makes a diagnostic's `code.target` a **local** file in an installed
extension: `<extensionPath>/docs/rules/MLV201.md`. The `<repo>/docs/rules` fallback in
`diagnostics.ts` only ever resolves in a dev checkout, so the pages are synced into the
extension at build time and shipped in the `.vsix`.
