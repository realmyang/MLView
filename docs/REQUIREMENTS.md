> Historical record: the static analyzer was removed on 2026-09-18.
> Commands, paths, and compatibility promises below describe earlier revisions.
> See [current status](STATUS.md) for the supported product.

# MLView — Requirements

**Status:** frozen for the prototype build. Version 1.0, 2026-09-06.
**Companions:** `ARCHITECTURE.md`, `ISSUE_RULES.md`, `UX_DESIGN.md`, `CONTRACTS.md`.
`CONTRACTS.md` is normative for anything an agent codes against. This document is normative for *what must be true when we are done*.

> **Prototype amendments.** `CONTRACTS.md` §10 (lead decisions of 2026-09-06) overrides this document where they differ: the MCP server uses the official `mcp` Python SDK v2 rather than a hand-rolled JSON-RPC server; `tools/sync-version.py`, `scripts/demo.ps1`, `tools/bench.py`, follow-cursor, axe-core and the eight-state node machine are out of the prototype; the clean-reference corpus is five programs; CodeLens is in. R0–R4 remain the target.

---

## 1. Goal

MLView turns a Python machine-learning codebase into **one interactive, issue-annotated workflow diagram**, produced by static analysis only, and serves that identical diagram to two hosts: **Claude Code** and **GitHub Copilot / VS Code**.

The product answers, in the first ninety seconds of reading unfamiliar training code, the four questions an ML reviewer actually asks:

1. Where does data enter, and where is it split?
2. What exactly is being optimized, and by what?
3. Is the evaluation honest?
4. What is wrong, how badly, and where in the file?

Everything below exists to make those four answers correct, visible, and clickable.

---

## 2. Personas

| # | Persona | Context | What MLView must give them |
|---|---|---|---|
| **P1** | **Mara — ML engineer inheriting a repo** | 40 files, no docs, must ship a change this week | A one-screen map of the pipeline plus a ranked list of what is likely broken, every row landing on a line of code |
| **P2** | **Dev — reviewer on a PR** | Reviewing a 300-line diff to `train.py` | Leakage and train-loop defects in the Problems panel *before* they write a comment; a picture to paste into the review |
| **P3** | **Sam — researcher / student** | Learning by reading someone else's PyTorch | A legible diagram that teaches the canonical shape of a pipeline, with "why is this a problem" on every finding |
| **P4** | **The agent — Claude Code or Copilot agent mode** | Asked "is there data leakage here?" | Structured graph and issues as tool output, bounded in size, with `file:line` it can cite and jump to |

P4 is a first-class persona, not an afterthought: the MCP tools and the VS Code language-model tools are held to the same latency and payload budgets as the UI.

---

## 3. Requirements

Priorities: **P0** = the prototype is not done without it. **P1** = the prototype should have it; may be cut at the mid-session checkpoint. **P2** = designed for, explicitly not built today.

"Verified by test `X`" means a named test that must exist and pass.

### R0 — Foundations (the hard constraints, made testable)

| ID | Pri | Requirement | Acceptance |
|---|---|---|---|
| **R0.1** | P0 | **One core.** A single Python package `mlview` produces the graph and the issues. Neither host contains parsing, inference, stage classification, or rule logic. | `tools/verify.py` runs the fixture corpus through the CLI **and** through a scripted MCP `tools/call`, then byte-diffs the two documents after stripping `generator.generatedAt` and `stats.durationMs`. Plus a source scan of `vscode-extension/src` and `webview/src` finds only transport, rendering and type names — no `ast`, no `lineno`, no rule codes in logic. |
| **R0.2** | P0 | **Static only.** Analysis uses `ast.parse` on source text. MLView never imports, executes or `exec`s user code, and never requires torch / sklearn / tf / transformers to be installed. | `tests/test_no_exec.py` snapshots `sys.modules` before and after a full analysis of a torch-importing fixture and asserts no `torch`/`sklearn`/`tensorflow`/`transformers` key appeared; a source scan asserts the core contains no `exec(`, `eval(`, `importlib.import_module`. Analysis of `samples/vision_pipeline` succeeds on this machine, where torch and sklearn are absent. |
| **R0.3** | P0 | **Fully offline.** No network at analysis, render or load time. The standalone HTML report is self-contained; the webview CSP is `default-src 'none'`. | `tests/test_offline.py` asserts the emitted HTML contains zero matches for `http://`, `https://`, `//cdn`, `@import`, and any `<link>`/`<script>` with an external `href`/`src`. The report renders with the network adapter disabled. |
| **R0.4** | P0 | **Deterministic.** Same input bytes → same output bytes. All collections sorted; ids content-addressed; no set/dict iteration-order leaks. | `tests/test_determinism.py` analyses twice in-process and once in a subprocess with a different `PYTHONHASHSEED`, asserting byte-identical JSON after stripping the two volatile fields. |
| **R0.5** | P0 | **Never crash; degrade instead.** Syntax errors, unreadable files, unresolved calls and rule exceptions all become `diagnostics[]` entries. Exit code stays 0. | `tests/test_robustness.py` feeds a syntax error, an empty file, a non-UTF-8 file, a 3000-line generated file, and a rule that raises; asserts exit 0, a `diagnostics[]` entry of the right `kind` for each, and a populated graph for the rest of the workspace. |
| **R0.6** | P0 | **Versioned contract.** Every document carries `schemaVersion`, `generator.version`, `generator.rendererSha`. Both hosts check the schema *major* on load and refuse a mismatch with an actionable message. | Launching the extension against a core stamped `schemaVersion: "2.0"` shows `MLView core schema 2.0 is newer than this extension (expects 1.x)` with a **Show Output** button, and renders nothing broken. |
| **R0.7** | P1 | **Suppressible.** `# mlview: ignore[MLV201]` (same line or the line above), `# mlview: ignore-file`, and `.mlview.toml` with per-rule `off` plus path excludes. | `tests/test_suppression.py`: a fixture with the comment emits the issue with `suppressed: true` in the graph and zero diagnostics in the Problems panel; a second, un-suppressed code on the same line still fires. |

### R1 — Visualize the complete logic/workflow *(spec requirement 1)*

| ID | Pri | Requirement | Acceptance |
|---|---|---|---|
| **R1.1** | P0 | The analyzer recovers a **stage-labelled workflow graph** from a Python workspace: nodes, typed edges, and a `stage` on every node. | `python -m mlview analyze samples/vision_pipeline --json -` exits 0 in under 5 s, validates against `contracts/graph.schema.json`, and yields ≥ 25 nodes, ≥ 25 edges, `workspace.filesFailed == 0`. |
| **R1.2** | P0 | **Eight canonical stages** — `config, data, preprocess, model, objective, train, eval, deliver` — render as ordered swimlane bands. Stages that are *absent* are declared, not silently dropped. | For the sample, ≥ 6 of 8 stages are `present: true`; absent stages appear in a "not detected" chip row under the toolbar. `stages[]` is always length 8 and always sorted by `order`. |
| **R1.3** | P0 | **Typed edges**: `data` (a named value produced here, consumed there), `call` (call site → definition), `control` (loop/branch containment and loop back-edges), `config` (a literal bound to a hyperparameter slot). | `tests/test_dataflow.py` asserts exact `(producer, consumer, label, kind)` tuples for six fixtures. In the UI the four kinds are distinguishable in a greyscale screenshot — stroke pattern differs, not only colour. |
| **R1.4** | P0 | **Three-level hierarchy** — `stage` › `unit` (class / function / loop) › `op` (significant call or artifact) — with collapse/expand. The default view fits one screen. | The sample renders collapsed as ≤ 25 boxes at 1440×900 with no scrolling; expanding the `train` stage reveals its unit and op children with edges re-routed, in ≤ 400 ms. |
| **R1.5** | P0 | The **training loop is drawn as a loop**: epoch and batch nesting as concentric containers with labelled back-edges (`next batch`, `next epoch`). | The sample shows two nested loop containers and two back-edges; `tests/layout.test.ts` asserts each back-edge path is routed outside its loop container's bounding box. |
| **R1.6** | P1 | **Ghost nodes.** An absent-but-required step (`optimizer.zero_grad()`, `model.eval()`) renders as a dashed placeholder in its correct slot, carrying the issue marker — showing the hole rather than narrating it. | With `MLV201` firing, the batch loop shows a dashed node labelled `zero_grad()  ·  missing` with the severity marker; clicking it reveals the loop header; `ghost: true` appears on that node in the JSON. |
| **R1.7** | P0 | **Honest about what it cannot resolve.** Unresolved call targets become dashed `unknown` nodes, never dropped. Any scope containing `exec`, `eval`, `getattr` on a call target, a star-import, or `**kwargs` forwarding is marked `dynamic: true`, which de-rates confidence in that scope and raises a "partial understanding" banner. | `fixtures/dynamic/registry.py` (`getattr(models, cfg.name)()`) yields ≥ 1 `unknown` node, a `diagnostics[]` entry of kind `dynamic_scope`, and the banner in the rendered HTML. |
| **R1.8** | P1 | **Cross-file resolution within the workspace.** A `Dataset` subclass in `data/dataset.py` used in `train.py` is one node, with `call` edges spanning files. | `fixtures/multifile/` (4 files) yields a single connected graph where the `model` node's `loc.file` is `models/net.py` while the train loop is in `train.py`, joined by a `call` edge. |
| **R1.9** | P1 | **Framework tiers.** PyTorch: full node + rule coverage. scikit-learn: full split / pipeline / estimator coverage. Keras-TF, HuggingFace, Lightning: recognised at node level (correct `kind`, `stage`, `framework`) with **no dedicated rules**, but with their suppression gates active. | One fixture per framework produces correctly-kinded nodes and zero crashes; the Lightning and HF fixtures produce **zero** PyTorch train-loop findings. |
| **R1.10** | P1 | **Notebooks are declared, not silently skipped.** `.ipynb` files are detected, counted and reported as *not analysed*. | A workspace with 3 notebooks yields `workspace.notebooksSkipped == 3` plus a `notebook_skipped` diagnostic; the status bar shows `3 notebooks not analyzed`. |
| **R1.11** | P1 | **Bounded graphs.** `--max-nodes` (default 400) truncates with `stats.truncated: true` and a visible banner naming what was dropped. | A synthetic 900-node workspace analyses in < 10 s, emits ≤ 400 nodes, sets `truncated`, and renders a dismissible banner. |
| **R1.12** | P0 | **Scoped views.** The diagram can show **one part** of the workspace - a unit, a stage, a file, or one of four concern presets (`config`, `data`, `optimization`, `evaluation`) - as a **projection of the whole-workspace graph**, never a narrower parse. Selector grammar `kind:target` plus a `depth` of 0-2; every kept node carries `viewRole: core \| boundary \| context`; the one-hop boundary ring shows where flow enters and leaves. Available on the CLI (`--scope`), in both hosts and in the standalone report, applied client-side with no re-analysis, and identically in Python and TypeScript. | `analyze samples/vision_pipeline --scope concern:evaluation --depth 1` keeps `workspace.filesAnalyzed` identical to the unscoped run and yields 7 core / 7 boundary / 3 context nodes, 19 edges and exactly `{MLV103, MLV301, MLV302}`; `--scope unit:sklearn_baseline.baseline` yields 13 nodes and `{MLV101, MLV103, MLV602}`; a valid selector matching nothing exits **0** with `view.empty: true`, an invalid one exits **1** with an error code, the offending term and =<10 sorted candidates on stderr and a clean stdout. `stage.present`, `workspace.*` and `view.of` stay project-level truth, no swimlane band is drawn for a stage with no kept nodes, and the VS Code Problems panel is byte-identical while scoped. The Python and TypeScript projections agree on node/edge/issue ids **in order**, on every `viewRole` and on the whole `view` object for all 10 cases of `contracts/scope.cases.json` - gated by `tools/verify.py --scopes` inside `scripts/e2e.ps1`. Full spec: `docs/FEATURES_FLOW_AND_SCOPE.md` section 3, contracts: `CONTRACTS.md` section 11. |

### R2 — The diagram is interactive; clicking leads to the code *(spec requirement 2)*

| ID | Pri | Requirement | Acceptance |
|---|---|---|---|
| **R2.1** | P0 | **Every node, edge and issue carries a precise location** — `{file, absFile, line, col, endLine, endCol, symbol?, snippet?}` — line 1-based and col 0-based, exactly as `ast` reports. | `tests/test_locations.py` re-opens every emitted `loc` across all fixtures, slices `[line..endLine]`, and asserts `symbol` (or `snippet`) occurs in the slice. 100 % must pass. |
| **R2.2** | P0 | **Click a node → reveal the code.** VS Code: `showTextDocument` with the range selected and revealed. | Clicking the `train_loop` node opens `samples/vision_pipeline/train.py` with the cursor on the `for images, labels in train_loader:` line and the loop header selected, in < 300 ms. |
| **R2.3** | P0 | **Click an edge → reveal the *call site***, not either endpoint's definition. | Clicking the `model → loss` edge lands on the `criterion(outputs, labels)` call — not on `class Net:` and not on `nn.CrossEntropyLoss()`. |
| **R2.4** | P0 | **Click an issue row → reveal**, and expose its `relatedLocs` as secondary jumps with named roles. | The `MLV101` row offers **Go to fit site (line 41)** and **Go to split site (line 44)**; both land exactly. |
| **R2.5** | P1 | **Reverse direction.** `MLView: Reveal in Diagram` (`Alt+M`) selects the node whose range most *narrowly* contains the cursor, expanding collapsed ancestors and centring it. | Cursor inside `ResNetBlock.forward` selects that node, not its enclosing class; the group expands; the viewport centres with one pulse. If no node contains the line, the nearest node in the same file is selected and a toast says so. |
| **R2.6** | P0 | **The standalone report is clickable too.** Every location is a `vscode://file/<abs>:<line>:<col+1>` deep link with a "copy `path:line`" toast fallback. | From `.mlview/report.html` in a browser, clicking a node raises the installed VS Code focused on the same range; with the handler blocked, a toast appears and the clipboard holds `train.py:44`. |
| **R2.7** | P1 | **Hover lineage trace.** Hovering a node raises its `data` ancestors and descendants to full opacity and dims the rest. | Hovering `train_loader` leaves the dataset → transform → loader → loop chain lit, everything else at 22 % opacity with `pointer-events: none`. |
| **R2.8** | P1 | **Search** (`/` or `Ctrl+K`) over node label, qualified name, FQN, file path, variable name and rule code, fuzzy-ranked; Enter focuses, Ctrl+Enter opens the code. | Typing `resnet` ranks `ResNetBlock` above `resnet_utils`; `MLV201` matches the issue; `train.py:74` jumps to that line's node. |
| **R2.9** | P1 | **Viewport, selection, collapse state and filters survive** tab switches, window reload and re-analysis. Persistence uses the webview `getState`/`setState` API plus a `WebviewPanelSerializer` — **not** `retainContextWhenHidden`. | Switch tabs and back: zoom, pan and selection preserved. Reload the window: the panel returns with its state. Edit a file and re-analyse: selection survives, because node ids are content-addressed and did not change. |
| **R2.10** | P2 | **Follow cursor**: a debounced soft highlight tracks the editor cursor in the diagram without changing selection. | — designed in `UX_DESIGN.md`, not built today |
| **R2.11** | P0 | **Flow animation.** Hovering, focusing or selecting a connection highlights it and runs a charge along its own routed path **from the outlet (source) to the inlet (target)** at constant speed, with an outlet dot at `points[0]`, an inlet dot at the last point, and a ring on each endpoint card. Hovering a node streams the same charge along its whole lineage, staggered 90 ms per hop so the current radiates. The charge takes the severity colour on an edge that carries a finding, otherwise the source node's stage hue. Direction is never derived and never reversed - every router already emits `points` source-to-target. | Hovering `.mlv-edge__hit` for 400 ms gives the `<g>` `.is-flowing--pulse`, one `.mlv-edge__flow` whose `d` **equals** `.mlv-edge__path`'s `d`, and two `.mlv-edge__port` circles at the first and last coordinate pair; `pointerleave` clears all of it. Hovering a node gives every flow-eligible `.is-lit` edge `.is-flowing` with `--mlv-flow-delay` non-decreasing by hop; `config` edges never stream. Duration comes from `RoutedEdge.points` - a source scan finds **zero** `getTotalLength` in `webview/src`. Above 120 lit edges nothing animates and the lineage still lights. Under `prefers-reduced-motion` the canvas is `data-motion="reduced"`, **no** `.mlv-edge__flow` exists, and a `midAngle` chevron plus a hollow outlet and filled inlet carry the direction instead. Full spec: `docs/FEATURES_FLOW_AND_SCOPE.md` section 2, contracts: `CONTRACTS.md` section 11.13. |

### R3 — Potential issues are marked on the diagram *(spec requirement 3)*

| ID | Pri | Requirement | Acceptance |
|---|---|---|---|
| **R3.1** | P0 | **Three severity markers, shape-coded exactly as the spec describes.** Low = a small filled **circle** with `i`. Medium = a filled **amber warning triangle** with `!`. High = a filled **red octagon** with `!` — the red exclamation mark. Severity is never carried by colour alone. | The three glyphs stay distinguishable in a greyscale render and a deuteranopia simulation; `tests/glyphs.test.ts` asserts the three SVG `path` `d` attributes differ structurally; every badge is `role="img"` with an `aria-label` naming the severity in words. |
| **R3.2** | P0 | **Markers aggregate upward.** A collapsed stage or group shows the highest severity present plus the total descendant count. | Collapsing `models/resnet.py` (41 children; 2 high + 1 low) shows one card with the red octagon and count `3`; the group header breaks the mix down where space allows. |
| **R3.3** | P1 | **Edges carry markers** when the finding is about a connection (leakage, wrong pairing). | The `softmax → CrossEntropyLoss` edge carries a red marker at its midpoint on a background-coloured disc. |
| **R3.4** | P0 | **Issue rail**: filterable, searchable, grouped by severity then stage; each row shows marker, rule code, title, node, `file:line`, message and fix hint. Selecting a row focuses and pulses the node. | Row count equals the number of unsuppressed issues passing the active filters; clicking a row centres the node in ≤ 260 ms and opens the inspector on that issue. |
| **R3.5** | P0 | **20 prototype rules**, spanning all three severities and covering both PyTorch and scikit-learn (see `ISSUE_RULES.md`). | `python -m mlview rules --list` prints ≥ 20 prototype codes. `tests/test_registry_complete.py` fails if any registered rule lacks a positive fixture, a negative fixture, a non-empty `fixHint`, a `severity`, a `ruleVersion`, or a docs entry — and if any fixture maps to no registered code. |
| **R3.6** | P0 | **Every issue carries a confidence** in [0,1] from six evidence factors, plus a bucket (`certain / likely / possible / speculative`). The **bucket** is what the UI shows; the number lives in the JSON and the "why" popover. Only `confidence ≥ 0.6` reaches the Problems panel; lower-confidence findings stay on the canvas behind a toggle. | 100 % of issues have non-null `confidence` and `confidenceBucket`. On the sample, the Problems-panel count equals the count of issues with `confidence ≥ 0.6` and `suppressed: false`. Toggling `mlview.showSpeculative` adds the rest to the canvas only. |
| **R3.7** | P0 | **Zero high-severity false positives** on a curated clean-reference corpus, and **zero issues at all** on the union of every rule's negative fixture. | `tests/test_precision.py`: `tests/clean/*.py` — ≥ 6 idiomatic correct programs (vanilla PyTorch; AMP + gradient accumulation; a Lightning module; a HuggingFace `Trainer` script; sklearn `Pipeline` + `GridSearchCV`; a `TimeSeriesSplit` script) — yields **0 high** and **≤ 2 medium**. `tests/test_no_cross_fire.py`: the union of all `*_good.py` fixtures yields **0** issues. |
| **R3.8** | P0 | **Framework suppression gate (`negation_absent`).** Absence-of-evidence rules are suppressed or heavily de-rated whenever a framework that supplies the behaviour is detected (Lightning, HF `Trainer`, `accelerate`, `ignite`, `fastai`, `Fabric`, DDP/FSDP/DeepSpeed). The suppression is *visible*: a chip reads "training loop handled by Lightning — 7 rules not applicable". | The Lightning and HF fixtures produce zero `MLV2xx`/`MLV3xx` findings and one `framework_suppressed` diagnostic naming the framework and the suppressed codes. |
| **R3.9** | P0 | **Issues appear in the editor's Problems panel** via a `DiagnosticCollection` named `mlview`, with `source: "MLView"`, a `code` object linking to the bundled offline rule doc, and `relatedInformation` built from `relatedLocs`. **This is the primary GitHub Copilot integration**: Copilot Chat's `#problems` context, inline fix and agent mode all read the Problems panel, with zero Copilot API surface required. | The sample produces the expected diagnostic count with the expected `code.value` strings; the `MLV101` entry's related information points at the split site; clearing the analysis empties the collection; a deleted file's diagnostics are cleared. |
| **R3.10** | P1 | **Multi-location issues are drawn as a picture**: on selection, a dotted numbered connector links the primary node to each `relatedLoc` node. | Selecting `MLV101` draws a numbered dotted connector from `fit_transform` to `train_test_split` across the `preprocess` band. |
| **R3.11** | P0 | **Severity filters** as toolbar chips with live counts, plus stage / framework / file filters, applied consistently to badges, canvas and rail. | Toggling the medium chip hides amber badges and amber rows; a node whose issues are all filtered out keeps its position and loses its badges. |
| **R3.12** | P1 | Rules are **individually disableable** (`.mlview.toml`, `mlview.disabledRules`), but **severities are fixed** — a red octagon means the same thing in every screenshot. | Setting `[rules] MLV601 = "off"` removes those findings from both hosts. A severity override in config becomes a warning-level `diagnostics[]` entry, not an error. |
| **R3.13** | P2 | `--baseline <file>` records current findings so only *new* issues surface. | — designed, not built today |

### R4 — The UI/UX is beautiful, clear, intuitive, user-friendly *(spec requirement 4)*

| ID | Pri | Requirement | Acceptance |
|---|---|---|---|
| **R4.1** | P0 | **One design-token layer.** Every colour, radius, spacing, duration and geometry value is a `--mlv-*` custom property whose value is `var(--vscode-*, <literal fallback>)`. One stylesheet serves the webview and the standalone report untouched. | A CSS lint rule fails the build on any raw hex, `rgb(`, or hard-coded px for a tokenised property outside `tokens.css`. |
| **R4.2** | P0 | **Theme parity.** The webview follows VS Code light / dark / high-contrast within one frame; the standalone report follows `prefers-color-scheme` and offers an Auto/Light/Dark switch. | Switching Light+ → Dark+ → Dark High Contrast re-themes with no reload and no hard-coded colour leaking through. The report in a dark-preference browser renders dark. |
| **R4.3** | P1 | **Level of detail by zoom**, implemented as one `data-lod` attribute plus CSS. Node *boxes* are always laid out at full-detail dimensions, so changing LOD never triggers relayout and zooming never reflows the picture. | A 300-node fixture sustains ≥ 50 fps through a continuous 3-second zoom; a DevTools profile shows zero node re-renders caused by zoom. |
| **R4.4** | P1 | **Eight defined node states** — default, hover, selected, focus-visible, dimmed, filtered-out, stale, has-issues — each with defined tokens, plus a `states.html` reference page rendering every node kind in every state. | `states.html` exists and renders; `tests/states.test.ts` snapshots the class list per state. |
| **R4.5** | P0 | **Designed empty / loading / partial-error / hard-error / stale states**, not blank canvases. | (a) No ML found → empty state with a "what MLView looks for" list and the top unresolved imports. (b) Analysis > 400 ms → skeleton graph, determinate progress bar, Cancel; nothing shown before 400 ms. (c) Partial parse errors → graph still renders plus a dismissible banner listing the files. (d) Analyzer failed → stderr tail, **Copy details**, **Retry**, **Select Interpreter**. (e) Files changed → `Files changed · Re-analyze` bar and dashed borders on stale nodes. |
| **R4.6** | P0 | **Keyboard complete.** Tab into the canvas; arrows traverse along edges; Enter opens code; Space collapses; `F` focuses; `Esc` unwinds; `0` fits; `1/2/3` toggle severities; `n`/`p` walk issues; `?` shows the sheet. | With the mouse untouched, every node in the sample is reachable and its code openable. Every focusable element shows a 2 px focus ring with 2 px offset. |
| **R4.7** | P1 | **Screen-reader complete.** The canvas is an application region with `aria-activedescendant`; every node is a labelled focusable element; an `aria-live` region announces selection, collapse and analysis completion; an Outline tab mirrors the graph as a nested list. | `axe-core` reports zero serious/critical violations on the app, the palette, the rail and each designed state. A node label reads e.g. *"Optimizer Adam, objective stage, train.py line 34, 1 high issue: gradients never zeroed."* |
| **R4.8** | P0 | **Contrast is a build gate.** Every declared foreground/background token pair meets 4.5:1 for text and 3:1 for graphics, in light, dark and high contrast. | `tests/contrast.test.ts` walks the token pairs and fails below threshold. This is the mechanical defence against amber-on-light. |
| **R4.9** | P1 | **Motion is purposeful and bounded.** Nothing animates without a user action; all transitions ≤ 260 ms; `prefers-reduced-motion: reduce` disables transitions, pulses and marching ants; layout transitions disable above 200 nodes. | Verified against the motion table in `UX_DESIGN.md` plus a reduced-motion smoke check. |
| **R4.10** | P2 | Legend, a "why is this node in this stage?" popover backed by `stageEvidence[]`, and SVG export. | — |

---

## 4. Non-functional requirements

### Offline & privacy
- No network calls, no telemetry, no API keys, no model inference in the analyzer or the renderer. Enforced by CSP (`default-src 'none'`), by the offline HTML grep test, and by the core having **zero runtime dependencies**.
- The only thing that ever leaves the machine is whatever the *host's* LLM chooses to send when a user asks it a question. MLView's analysis is 100 % local. Stated in the README and in the chat participant's first response.

### Performance budgets (measured, asserted)

| Metric | Budget | Asserted by |
|---|---|---|
| Analyse a 2 000-line / 40-file workspace, cold | < 5 s | `tools/bench.py` |
| Analyse a single file (on-save path) | < 400 ms, debounced 400 ms, previous run cancelled | extension unit test |
| Graph JSON parse (5 MB) | < 200 ms | renderer test |
| Layout, 300 nodes / 600 edges | < 300 ms | `layout.test.ts` |
| First paint after `graph/load` | < 800 ms | manual trace |
| Pan / zoom | ≥ 50 fps sustained | manual trace, 300-node fixture |
| Selection → visual response | < 100 ms | — |
| Collapse/expand including animation | < 400 ms | — |
| Standalone HTML | < 2 MB total | `tests/test_offline.py` |
| Model-facing tool result (MCP / LM tool) | ≤ 4 KB, full detail behind `graphPath` | `tests/test_digest_budget.py` on a 500-node synthetic graph |

### Accessibility
WCAG 2.1 AA as the floor: 4.5:1 text / 3:1 graphics contrast (test-gated); shape + colour + text for every severity; full keyboard operation; visible focus that is never removed; 24×24 minimum hit targets; nothing conveyed by hover alone (everything in a tooltip is also in the inspector); `prefers-reduced-motion` respected; a linear Outline view as the screen-reader-complete path.

### Theming
All colour flows through `--mlv-*` tokens with `--vscode-*` primaries and literal fallbacks. Severity colours prefer `--vscode-editorError-foreground`, `--vscode-editorWarning-foreground`, `--vscode-editorInfo-foreground` (falling back to `--vscode-charts-red/yellow/blue`, then literals) so markers match the user's theme automatically. High-contrast themes drop fills to strokes and keep the glyph letter, so all three severities stay distinguishable.

### Portability & robustness
- Windows 11 is the primary development target and the demo machine. Every child process is spawned with `shell: false`, an **absolute** interpreter path, and `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` / `-X utf8`. The same variables are set in the plugin's `.mcp.json`. Without them, cp1252 mangles stdio JSON-RPC and JSON on stdout.
- Paths in the JSON are workspace-relative with forward slashes (`file`) plus an absolute sibling (`absFile`). Golden tests compare only the relative form.
- Interpreter discovery is a documented four-step chain with an actionable failure (`ARCHITECTURE.md` §7).
- **stdout purity**: the CLI writes only the requested payload to stdout; every log, warning and progress line goes to stderr. A lint test greps the core for bare `print(` outside the text emitter.

### Security
- The webview never uses `innerHTML`; SVG and node DOM are built with `createElementNS` / `textContent`. The HTML emitter escapes every interpolated string. Analysed source is untrusted input — file paths, identifiers and snippets from an arbitrary repo end up in the report.
- The extension's `openLocation` handler **rejects any path outside the workspace folder** before calling `showTextDocument`.
- Webview CSP is nonce-based with `default-src 'none'`; `localResourceRoots` is restricted to the extension's `media/` directory.
- No credentials, no environment capture, no writes outside the workspace's `.mlview/` directory and the OS temp directory.

### Determinism & reproducibility
Sorted collections, content-addressed ids, rounded floats, volatile fields (`generatedAt`, `durationMs`) excluded from every comparison. Layout is deterministic (dagre `network-simplex` over a stable insertion order), because snapshot tests and screenshots depend on it.

---

## 5. Non-goals (explicit, for this version)

1. **Executing or importing user code** — including "just to get the model summary". Ever.
2. **Cloud anything** — no hosted service, no API keys, no telemetry, no LLM-assisted analysis. The hosts' LLMs consume MLView's output; they never produce it.
3. **Notebook (`.ipynb`) analysis.** Detected, counted and reported as *not analysed*. Out-of-order-execution leakage is a real and important class that this version does not address; it is called out in the README rather than discovered by a user.

   > **Lifted behind a flag, 2026-09-09 (NB, `docs/CONTRACTS.md` 11.29).** Notebook analysis now exists: `--include-notebooks`, or `[paths] notebooks = true` in `.mlview.toml`, converts each notebook's code cells into a generated module under `<root>/.mlview/notebooks/`, maps every `Loc` back to `(cell, cellLine)`, and de-rates MLV101 / MLV203 / MLV209 on a notebook whose recorded `execution_count` is not monotonic — because out-of-order execution is undecidable from the file, and saying so is the point. **Without the flag this non-goal still holds exactly as written**: a notebook is counted, skipped and declared, byte for byte as before.
4. **Type or shape inference.** No tensor dimension tracking. Several rules would be sharper with it; deliberately deferred.
5. **Auto-fix / code actions that edit code.** Fix hints are text. The diagnostic `code` field is shaped so quick fixes can be added later.
6. **Deep interprocedural analysis.** One level of function summaries within a module, plus workspace-level definition lookup. No whole-program dataflow.
7. **Config-driven pipeline resolution** (Hydra, registries, `getattr` factories). Not resolved — rendered honestly as `unknown` nodes in a `dynamic` scope with a partial-understanding banner.
8. **Framework-specific rules beyond PyTorch and scikit-learn.** Keras-TF, HuggingFace and Lightning get node recognition and suppression gates only.
9. **Distributed-training rules** (DDP/FSDP/DeepSpeed samplers, rank-0 checkpointing, gradient sync). Detected only in order to *suppress* inapplicable single-process rules, with a visible chip.
10. **Multi-root workspaces, remote/WSL/container path mapping, watch mode, incremental re-analysis.**
11. **Marketplace publishing** (`.vsix` to the VS Code Marketplace, a wheel to PyPI, a plugin marketplace entry). Packaging is *possible* — `@vscode/vsce` declares `engines.node >= 20` and this machine has 20.9 — but the demo path is the F5 Extension Development Host.
12. **PNG export, minimap-driven editing, layout editing, user-authored rules, rule-severity customisation, SARIF / CI action.**
13. **Verified live GitHub Copilot behaviour.** Copilot is not installed on this machine. The chat participant and language-model tools are compile-verified, feature-detected and directly invocable; the Problems-panel path is the Copilot integration that is actually exercised. The README says so plainly.

---

## 6. Prototype scope / definition of done

### 6.1 In scope

**Analyzer** — discovery with excludes; `ast` parse with `diagnostics` on failure; import-alias resolution to canonical FQNs; flow-insensitive binding tracking with tuple unpacking and `self.x`; scope / loop / `no_grad` tagging; SSA-lite value tagging (`ValueTag`) for the leakage and loss families; 8-stage classification with recorded `stageEvidence`; three-level hierarchy; the six-factor confidence model including the `negation_absent` framework gate; **20 prototype rules**; suppression comments; the frozen CLI; canonical JSON plus self-contained HTML, mermaid and text emitters.

**Renderer** — one esbuild IIFE bundle serving both hosts; 8 swimlane bands with per-lane dagre; HTML node cards over an SVG edge layer; four edge styles; the three severity markers with aggregation; ghost nodes; multi-location connectors; hover lineage; collapse/expand; LOD; search; issue rail; inspector; filters; the five designed states; token-driven light/dark/HC theming; keyboard traversal and ARIA.

**Claude Code** — plugin directory (`.claude-plugin/plugin.json`, `commands/`, `skills/`, `.mcp.json`, vendored core); the zero-dependency stdio JSON-RPC MCP server with 5 tools; `/mlview` and `/mlview-issues`; the self-contained HTML report opening in the browser with `vscode://` deep links.

**VS Code** — `mlview.visualize` / `visualizeWorkspace` / `refresh` / `showIssues` / `revealInDiagram` / `exportHtml` / `selectInterpreter` / `showOutput`; the webview panel with nonce CSP, `setState` persistence and a serializer; the `DiagnosticCollection`; the four-step interpreter chain; the Output channel and status bar; the `@mlview` chat participant and three language-model tools, feature-detected and compile-verified.

**Glue** — `tools/sync-assets.py`, `sync-core.py`, `sync-version.py` (each with `--check`); `tools/verify.py`; `scripts/build.ps1`, `e2e.ps1`, `demo.ps1`; the sample project and its clean twin; per-rule fixtures; the clean-reference corpus.

**Added 2026-09-07 - both in scope.** **R2.11 Flow animation** (`webview/` only: a lazily built `.mlv-edge__flow` overlay, two port dots, per-hop lineage stagger, `data-motion` / `data-flow` on the canvas, and a static chevron substitute under reduced motion) and **R1.12 Scoped views** (one `project()` algorithm in `analyzer/src/mlview/core/project.py` and `webview/src/scope/project.ts`, the optional root-level `view` block and `node.viewRole`, `--scope` / `--depth` on `analyze`/`issues`/`render`, `--list-scopes`, the `setScope` / `scopeChanged` messages, `MLViewApp.setScope`/`getScope`, a scope picker and breadcrumb, two VS Code commands, and `scope` on four MCP tools with `mlview_graph {scope:"units"}` for discovery - still exactly five tools). Both are additive: `schemaVersion` stays `"1.0"`, an unscoped run is byte-identical to today, and `--demo` still equals `contracts/graph.sample.json`. Design: `docs/FEATURES_FLOW_AND_SCOPE.md`. Frozen contracts: `docs/CONTRACTS.md` section 11.

### 6.2 Explicitly out (say no fast)

Everything in §5, plus: `@vscode/test-electron` (replaced by direct handler invocation), a lanes-vs-flow layout toggle, SVG/PNG export, `--baseline`, `--sarif`, watch mode, CodeLens (P2 — designed, cut if time is short), the `mlview_locate` and `mlview_rule_doc` MCP tools, the `MLV8xx` / `MLV9xx` rule families, and any additional framework rules.

### 6.3 Definition of done — the acceptance walkthrough

`scripts/e2e.ps1` must exit 0 having asserted every numbered item below. Each is machine-checked unless marked *(manual)*.

1. **Build.** `scripts/build.ps1` completes: core installed editable, renderer bundled, extension type-checked (`npx tsc --noEmit` clean), assets synced. `tools/sync-assets.py --check` and `sync-version.py --check` exit 0.
2. **One renderer.** SHA-256 of `webview/dist/mlview.js` equals the copies in `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`, and equals `generator.rendererSha` in every emitted graph.
3. **Analyse.** `python -m mlview analyze samples/vision_pipeline --json -` exits 0 in < 5 s; output validates against the schema; issue counts match `samples/vision_pipeline/expected_issues.json` exactly (the planted set: **5 high, 6 medium, 4 low** — see `CONTRACTS.md` §7).
4. **Clean twin.** `python -m mlview analyze samples/vision_pipeline_clean --fail-on low` exits 0 with **0 high, 0 medium, 0 low**. Same shape of graph, no alarms. *This is the trust beat.*
5. **Fail-on.** `analyze samples/vision_pipeline --fail-on high` exits 2.
6. **Precision gates.** `pytest -q` green, including `test_precision.py`, `test_no_cross_fire.py`, `test_registry_complete.py`, `test_locations.py`, `test_no_exec.py`, `test_determinism.py`, and `test_node_id_stability.py` (insert 20 blank lines at the top of a fixture: every node id unchanged, every `loc.line` shifted by exactly 20).
7. **Offline HTML.** `render --html` produces a file between 200 KB and 2 MB with zero external-URL matches, which opens and renders with the network disabled.
8. **Host parity.** `tools/verify.py` byte-diffs the CLI graph against the graph obtained by scripting MCP `initialize` → `notifications/initialized` → `tools/list` → `tools/call mlview_analyze`, after stripping the two volatile fields. `tools/list` returns exactly the 5 expected tool names with valid input schemas.
9. **Plugin validity.** `claude plugin validate ./claude-plugin --strict` exits 0.
10. **Claude Code** *(manual)*. `claude --plugin-dir <abs>/claude-plugin` starts; `/help` lists `/mlview`; `/mcp` shows `mlview` connected with 5 tools; `/mlview samples/vision_pipeline` prints the severity summary and opens the report; asking "is there leakage here?" results in an `mlview_issues` tool call rather than a manual `Bash` invocation.
11. **VS Code** *(manual)*. `code --extensionDevelopmentPath=<abs>/vscode-extension <abs>/samples` activates with no error and no Copilot installed, logging `chat API unavailable — participant not registered`. `MLView: Visualize ML Workflow` opens the panel showing the **identical** diagram; the Problems panel lists the ≥ 0.6-confidence findings with `MLV…` codes and related information; clicking a node lands on the right line; `Alt+M` from inside a function selects that node; switching theme re-themes in place; tab away and back preserves the viewport; reloading the window restores the panel.
12. **Copilot surface** *(manual + compiled)*. `package.json` contributes `chatParticipants` and three `languageModelTools`, each carrying **both** `canBeReferencedInPrompt: true` and a `toolReferenceName`; `node vscode-extension/test/lmtool.smoke.js` invokes the exported tool handler directly and receives a valid ≤ 4 KB digest; `engines.vscode` is `^1.100.0`.
13. **Accessibility.** `contrast.test.ts` and the axe run are green; the three glyph paths differ; keyboard traversal reaches every node *(manual)*.
14. **Demo insurance** *(manual)*. The standalone report is generated and open in a second browser tab **before** the demo starts, so the walkthrough survives an extension-host failure with only click-to-source degrading to clipboard.

**Done means:** items 1–9 and the automated half of 12 pass inside `e2e.ps1`, and items 10, 11, 13, 14 have been performed once by hand and recorded in `docs/DEMO_LOG.md`.
