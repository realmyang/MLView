# MLView — Build status

**Complete and integrated (2026-09-07).** The multi-agent build finished with two review → verify → fix rounds (48 confirmed findings fixed) and a final verification pass; `scripts/e2e.ps1` was re-run by hand afterwards: 13 steps, 0 failed. Every component is built, every gate is
green on this machine, and the demo artifacts are produced. `scripts/README.md`
holds the gate table with the command for each row.

**Two features were added on top of that prototype (2026-09-07, second pass):
flow visibility and scoped views.** Both are additive — `schemaVersion` stays
`"1.0"`, no existing field, message, argument or return shape changed, and an
unscoped run still emits the bytes it emitted before. `docs/CONTRACTS.md` §11
binds; `docs/FEATURES_FLOW_AND_SCOPE.md` is the design. The e2e driver grew
four steps (17 in total) and `tools/verify.py` grew two gate rows (9 in total).

```
powershell -ExecutionPolicy Bypass -File scripts/build.ps1   # BUILD OK
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1     # E2E OK - 17 steps, 0 failed
```

## Components

| Piece | State |
|---|---|
| Design docs | `docs/REQUIREMENTS.md`, `ARCHITECTURE.md`, `ISSUE_RULES.md`, `UX_DESIGN.md`, `CONTRACTS.md` (§10 amendments are the overriding lead decisions) |
| Contracts | `contracts/graph.schema.json`, `contracts/graph.sample.json` (golden), `contracts/validate_sample.py` (schema + 10 invariant groups) |
| Analyzer `analyzer/` | Complete. 20 rules, zero runtime dependencies, `python -m mlview` installed editable. **1152 passed, 3 skipped.** `analyze --demo --json -` is byte-identical to the golden sample. Scoped views live in `analyzer/src/mlview/core/project.py` + `core/selectors.py`. |
| Viewer `webview/` | Complete. `dist/mlview.{js,css}` built. **289 tests pass**, `tsc --noEmit` clean. Flow animation (`src/render/flow.ts`) and the TypeScript half of the projection (`src/scope/project.ts`) ship here. |
| VS Code extension | Complete. **205 tests pass**, `tsc --noEmit` clean, `out/extension.js` bundled. Copilot participant + LM tools are compile- and unit-verified only (Copilot is not installed here). |
| Claude Code plugin | Complete. MCP server on the `mcp` SDK v2, **still exactly five tools**, each result ≤ 4 KB. **273 tests pass**, with `python tools/sync-core.py` having run after the analyzer changes (`test_vendor_bytecode.py` is the row that checks it); `claude plugin validate ./claude-plugin --strict` passes. |
| Samples | `samples/vision_pipeline` (45 nodes, 45 edges, exactly 15 issues: 5 high / 6 medium / 4 low) and `samples/vision_pipeline_clean` (55 nodes, 0 issues). `expected_issues.json` is machine-checked. |
| Rule docs | `docs/rules/` — 20 pages plus an index, generated from the registry. Every `Issue.docs` deep link resolves. |
| Demo artifacts | `.mlview/graph.json`, `report.html`, `graph_clean.json`, `report_clean.html`, plus the three scoped reports `split.html`, `optimization.html`, `evaluation.html` — self-contained, zero external references, each inside amendment A4's contracted **100 KB – 2 MB** band. No KB figure is quoted here on purpose: the viewer bundle moves, the band does not, and `scripts/e2e` now measures every emitted report against it and prints the range it found (MLV-R1-H06). Each scoped report embeds the **whole** graph and merely opens at its scope. |
| Scope fixtures | `contracts/scope.cases.json` (10 selectors + 6 error codes) and `contracts/scope.expected.json`, generated from the Python `project()` over the frozen golden and consumed by the TypeScript port — the parity gate for one algorithm written twice. |

## What the integration pass changed

Four fixes, each at its source:

1. **`webview/src/layout/model.ts`** — the drawn hierarchy and the document's
   lexical hierarchy had diverged. A node whose `parent` sits in a different
   stage is promoted to a root of its own lane, so no box contains it — but
   `isHidden`, `descendantCount` and `subtreeCounts` still walked the lexical
   chain. Collapsing one group in the *preprocess* lane silently erased six
   nodes from the *data* lane, and the auto-collapse heuristic counted nodes it
   would not actually hide, so the demo report drew 19 of its 46 cards. `parentOf`
   is now the drawn parent, `lexicalParentOf` keeps the document's own value, and
   the three helpers walk lane children.
2. **`vscode-extension/test/manifest.test.js`** — asserted `media/` contains only
   the A13 placeholder, which `tools/sync-assets.py` falsifies by design on every
   successful build. It now asserts the pre-sync state *or* the exact post-sync
   set, so it is meaningful in both.
3. **`scripts/e2e.{ps1,sh}`** — the clean twin now also emits
   `.mlview/graph_clean.json`, and two gates were added (below).
4. **New gates.** `webview/test/render_report.mjs` loads the standalone report in
   jsdom and asserts it actually draws; `vscode-extension/test/panelhtml.test.js`
   asserts the panel's HTML points at the two files the sync wrote and that they
   are on disk. Every other gate proved the report *parsed*; neither proved it
   *rendered*.

## What the round-1 doc pass changed (2026-09-07)

1. **`README.md` "Known gaps"** described a `vscode-extension/test/manifest.test.js`
   failure that the integration pass had already repaired (MLV-R1-006), and a
   missing samples/rule-docs corpus that has since landed. Both bullets are gone;
   the three gaps that are real and were only recorded here -- inert
   `mlview.showSpeculative`, unsent `analysisProgress`, the absence-rule
   framework gate -- were carried into the README too. (That third bullet was
   itself wrong about the gate's scope; round 2 rewrote it, see below.)
2. **The absence-rule gate is described accurately.** It caps severity at
   `medium` and applies the confidence penalty; it does not drop the findings.
   Both this file and the README said "switches them off".
3. **New doc gate, `scripts/check_docs.py`,** wired into both `scripts/e2e`
   drivers with its own suite (`scripts/test_check_docs.py`, 7 cases then, 26 now). It fails
   the run on a dead path, a dead relative Markdown link, or a "known gap" bullet
   claiming a test fails when that test is in the tree. The frozen design records
   are link-checked only; `docs/CONTRACTS.md` is not touched.

## What the round-2 doc pass changed (2026-09-07)

1. **MLV-R2-109.** Both this file and `README.md` still described the absence-rule
   framework gate as workspace-wide -- "one Lightning module *anywhere* caps every
   absence finding at `medium`". That stopped being true when the gate moved to
   `ctx.wrappers_for()` in `analyzer/src/mlview/rules/context.py`, which reads the
   wrappers of the finding's own module plus the workspace modules it imports;
   `analyzer/tests/core/test_robustness.py` has pinned the per-module behaviour
   since round 1. Both bullets now describe the gate that ships, including the one
   edge that is genuinely still open (the import walk is one hop).
2. **The doc gate got two more checks.** The round-1 gate only caught claims
   shaped like "test X fails", which is why a purely behavioural sentence survived
   a whole round. `scripts/check_docs.py` now also requires every "Known gaps"
   bullet to cite a repo path or a code symbol in backticks, and fails when a
   cited symbol is nowhere in the source -- so renaming the code that a gap bullet
   describes breaks the build instead of quietly orphaning the prose.

## What the feature pass added (2026-09-07)

### Feature 1 — flow visibility

Hovering a connection highlights it and runs a charge along it **from outlet to
inlet**, the way current runs through a cable. Hovering a node streams its whole
lineage, staggered 90 ms per hop, so a value's path through the pipeline is
something you watch rather than something you infer.

- Direction is never decided: every router already emits `points` source →
  target, so animating along the edge's own `d` is always outlet → inlet.
- Colour follows meaning: the source node's stage hue on a clean edge, the
  severity hue on one carrying an issue — so `SmallCNN --logits--> criterion`,
  the edge MLV401 attaches to, runs red.
- `prefers-reduced-motion`, and any trace above `FLOW_MAX_EDGES = 120` lit edges,
  flips `.mlv-canvas` to `data-flow="static"`: nothing is built, and the
  connection reads instead as a direction chevron plus an outlet and inlet dot.
- Nothing animates without a user action; no schema, protocol or host change was
  needed (CONTRACTS 11.13).

### Feature 2 — scoped views

One selector string projects the whole-workspace document down to one part of a
codebase, in every surface: `unit:<class|function|loop>`, `stage:<id>`,
`file:<path>`, `concern:<config|data|optimization|evaluation>`, `node:<id>`,
`all`, with `depth` 0–2 boundary hops as its own parameter.

| Surface | How |
|---|---|
| CLI | `--scope SPEC` / `--depth N` on `analyze`, `issues` and `render`, plus `--list-scopes` for the catalogue |
| Report | `--html` embeds the **full** graph and sets `data-mlview-scope` / `data-mlview-depth` on `#mlview-root`; the viewer projects |
| VS Code | `MLView: Scope Diagram to Symbol` (`Alt+Shift+M`) and `MLView: Clear Diagram Scope`; the panel title and description follow |
| MCP | `scope` / `depth` on `mlview_analyze`, `mlview_issues` and `mlview_open_diagram`; `mlview_graph` accepts the whole grammar plus the `"units"` catalogue — **still five tools** |
| Commands | `/mlview` and `/mlview-issues` take `[--scope <SPEC>] [--depth <0-2>]`; the unscoped Bash fallback is unchanged |

Three properties are asserted rather than asserted-of:

1. **A scope is a view, not a filter.** `stage.present`, `workspace`,
   `generator` and `diagnostics` still describe the FULL analysis in a projected
   document; `view.of` carries the project totals so no surface can claim the
   project is smaller than it is. The VS Code Problems panel is byte-identical
   while scoped.
2. **One algorithm, two languages.** `analyzer/src/mlview/core/project.py` and
   `webview/src/scope/project.ts` are gated against each other by
   `python tools/verify.py --scopes` over a frozen 16-case battery.
3. **The plugin's analysis cache is never keyed on the scope.** `load_graph`
   still caches on `(path, framework, maxNodes, signature)`, the projection is
   applied to the cached dict, and `graphPath` keeps pointing at the full
   document — so widening back is free.

Try it:

```
python -m mlview analyze samples/vision_pipeline --list-scopes
python -m mlview analyze samples/vision_pipeline --scope unit:train_test_split --html .mlview/split.html --open
python -m mlview analyze samples/vision_pipeline --scope concern:optimization --format summary
python -m mlview analyze samples/vision_pipeline --scope concern:evaluation --depth 1 --format mermaid
python tools/verify.py --scopes
```

### What the feature integration pass fixed (2026-09-07)

Three defects, all found by driving the built reports rather than by reading
code — two in real Chromium (`.mlview/*.html` at 1600x1000), one by running the
analyzer suite against a freshly synced viewer bundle:

1. **Three components that hide themselves never actually hid.** An author
   `display` outranks the UA stylesheet's `[hidden] { display: none }`, so the
   scope picker sat permanently open over the theme switcher, an unscoped
   toolbar drew an empty breadcrumb pill, and `0 suppressed` was painted while
   the code believed it had hidden it (that last one predates the feature pass).
   `.mlv-chip[hidden]` (`webview/src/styles/base.css`) and
   `.mlv-breadcrumb[hidden], .mlv-scopepicker[hidden]`
   (`webview/src/styles/scope.css`) fix it; `webview/test/bundle.test.mjs`
   asserts the rule exists for every class that declares a `display` and is
   toggled through the `hidden` property.
2. **`test_the_html_report_embeds_the_full_graph_and_the_two_attributes`
   asserted the string `data-mlview-scope` was absent from an unscoped report.**
   The synced viewer bundle names both attributes because it READS them off the
   root, so the absence is now asserted on the root element itself — stricter,
   since it checks `data-mlview-depth` too.
3. **`.mlview/evaluation.html` was written at the per-kind default depth 0.**
   Demo D and F2-A5/F2-A6 are `concern:evaluation --depth 1` — 17 of 45 nodes,
   7 core / 7 boundary / 3 context — which is the ring that shows *what feeds*
   evaluation. Both e2e drivers now pass the demos' own depths.

### What the review round fixed (2026-09-08)

1. **`scripts/e2e.sh` had been rewritten from LF to CRLF** (MLV-R2-H02 /
   R2-REG-01). It is the only non-Windows entry point to the acceptance run
   — `README.md`, `scripts/README.md` and CONTRACTS all document
   `sh scripts/e2e.sh` as the POSIX twin of `scripts/e2e.ps1` — and Git
   Bash's `igncr` hid the damage on this machine while under dash the
   shebang named a program `sh<CR>`, `SKIP_BUILD` compared as an illegal
   number and every artifact would have landed in a directory called
   `.mlview<CR>`. The file is LF again and `sh -n scripts/e2e.sh` parses
   under dash. `docs/STATUS.md` and `scripts/README.md` were flipped the
   same way and are LF again too, so the next edit to either reads as an
   edit instead of a whole-file rewrite.
2. **This file's Components row said the demo graph had 39 edges.** It has
   45 — `python -m mlview analyze samples/vision_pipeline --format summary`,
   `tools/verify.py --all` and `scripts/README.md` all said so already
   (MLV-R2-H05). Row fixed.
3. **The doc gate grew the two checks that would have caught both.**
   `scripts/check_docs.py` check 7 fails the run on any `*.sh` in the tree
   that carries a carriage return, and on a checked doc that mixes CRLF
   with LF; check 8 fails it when two docs quote different sizes for the
   demo graph. Nine new cases in `scripts/test_check_docs.py` (26 total),
   one of which asserts against the shipped `scripts/*.sh` directly rather
   than against a fixture.

## Sprint 3 — hosts, Track B (2026-09-08)

Three roadmap items, all additive; `schemaVersion` stays `"1.0"` and no message,
tool count or return shape changed.

1. **COVERAGE (host half).** `mlview.currentFileAnalysisScope`
   (`file` | `package` | `workspace`, default `package`) makes
   `MLView: Visualize (Current File)` analyse the package directory around the
   file and then narrow the diagram to the file through the existing §11.7
   `setScope` path (`vscode-extension/src/currentFile.ts`). Analysing a file alone
   cannot fire MLV301, MLV302, MLV401 or MLV501 — each needs a sibling module — so
   the old path lost four of seven findings on `train.py` silently. The analyzer's
   `single_file_analysis` / `untagged_dataflow` diagnostics are surfaced in the
   status-bar tooltip, the panel tab description and the chat / language-model
   digests (`vscode-extension/src/coverage.ts`), and both slash commands and the
   `mlview_analyze` docstring repeat the caveat for a single-file path.
2. **RAIL-GROUP (host half).** `mlview_issues` takes `groupBy: rule|file|severity`
   and answers with `groups` instead of `issues` — one row per key with an
   occurrence count, the worst severity and confidence in the group and up to
   three citable `file:line` sites (`claude-plugin/server/mlview_groups.py`).
   `/mlview-issues --group-by` carries the same three words through the argument
   grammar. Grouping folds the rows and never filters them, and the payload's
   `note` says exactly that.
3. **CLEANUP (host bits).** `mlview.showSpeculative` and `mlview.followCursor`
   were deleted — both shipped in the Settings UI reading "Not implemented in this
   prototype", and A6 cut `followCursor` outright.
   `capabilities.canAskAssistant` is now true exactly when `vscode.chat` exists,
   and `askAssistant` opens chat seeded with the viewer's own prompt
   (`vscode-extension/src/panel.ts`). `claude-plugin/server/mlview_mcp.py` refuses
   an interpreter older than 3.10 with a message naming `.mcp.json`, the
   `command` field and `python3`, because JSON cannot carry that comment itself;
   `claude-plugin/README.md` carries the long form.

Files split to stay inside the ~600-line budget while doing it:
`vscode-extension/src/panelHtml.ts`, `src/toolAnalyze.ts`, `src/failure.ts` out of
`extension.ts` / `panel.ts`, and `claude-plugin/server/mlview_notes.py` out of
`mlview_payloads.py`. Every one is a move plus a re-export; no behaviour moved
with them.

## Known gaps

None block the demo. In rough order of how likely they are to matter:

- **No live host run.** The extension has never been driven inside a real VS Code
  webview (F5), and the Copilot chat participant and LM tools have never met a
  live Copilot session — Copilot is not installed on this machine. Both are
  covered by unit tests with a mocked `vscode`
  (`vscode-extension/test/panelhtml.test.js` and the rest of that directory) and
  a real subprocess test against a fake CLI.
- **The framework gate reaches one import hop.** `ctx.wrappers_for()` in
  `analyzer/src/mlview/rules/context.py` de-rates an absence finding
  (`MLV301` / `MLV302` / `MLV501`, ...) only when a Lightning / HF Trainer /
  accelerate / ignite / fastai / DDP / FSDP wrapper sits in the finding's own
  module or in a workspace module that one imports -- `_detect_wrappers()` in
  `analyzer/src/mlview/ir/build_ir.py` walks exactly one hop -- so a wrapper two
  imports away does not gate anything. When it does fire it caps severity at
  `medium` and multiplies confidence by 0.4; it never drops a finding.
- **`MLV201`'s `negation_absent` evidence line still reads the workspace-wide
  set.** `analyzer/src/mlview/rules/r_trainloop.py` composes that sentence from
  `ctx.wrappers`, not from the per-module set the gate uses, so an ungated
  hand-written loop can carry "framework wrapper detected: Lightning" beside a
  `certain` finding. Cosmetic -- severity and confidence are correct -- but it
  reads as a contradiction.
- **Loop nesting is flattened.** Invariant §1.1.2 (a parent must have a strictly
  lower `NodeLevel`) plus a three-value `NodeLevel` cannot express
  function → epoch loop → batch loop → op, so an inner batch loop is a sibling of
  its epoch loop rather than a child. The true depth is kept in the loop unit's
  `depth` attr.
- **Cross-file resolution is one level and import-table-only.**
  `from config import N` resolves; `import config` then `config.N` does not.
  `analyzer/src/mlview/ir/resolve.py` sets `target_function` for the first hop
  and stops.
- **The scoped jsdom render step needs a synced bundle.** `scripts/e2e.sh` reports
  SKIP for `render scoped report (jsdom)` while
  `analyzer/src/mlview/emit/assets/mlview.js` differs from `webview/dist/mlview.js`
  — a report written before `tools/sync-assets.py` ran inlines a viewer with no
  scope UI. The two bundle-hash rows of `tools/verify.py` report the same single
  cause; the integrator's sync clears all three.
- **`--list-scopes` lists units only.** `analyzer/src/mlview/emit/scope_out.py`
  prints the scopable-unit catalogue; the four concerns and the eight stage ids
  are discovered from this document, from the MCP tool docstring, or from the
  candidate list an unusable selector prints.
- **`analysisProgress` is never posted** — the CLI emits no progress frames, so
  the viewer shows an indeterminate load rather than "Parsing 42 of 128 files".
- **The host's coverage caveat is text, not a banner.** `single_file_analysis` and
  `untagged_dataflow` reach the status-bar tooltip, the panel tab description and
  the model digests through `vscode-extension/src/coverage.ts`. The in-canvas
  banner and chip are the viewer's own, drawn from `graph.diagnostics` in
  `webview/src/ui/chrome.ts` — the host passes those through untouched and adds
  nothing to the canvas.
- **`groupBy` folds inside the MCP server**, in
  `claude-plugin/server/mlview_groups.py`. `/mlview-issues --group-by` therefore
  groups through the MCP tool; the command body tells the model to fold the table
  itself on the `Bash` fallback until the matching CLI flag lands on
  `analyzer/src/mlview/cli.py`.
- **`CONTRACTS.md` §7.5 fixture directories** (`multifile/`, `dynamic/`,
  `malformed/`, `frameworks/`) do not exist as directories; that ground is covered
  inline by `analyzer/tests/core/test_robustness.py` and
  `analyzer/tests/rules/test_rule_robustness.py`.

## Contract change requests

Every agent filed some; they are recorded in each component's report and none
were acted on — the contracts in `docs/CONTRACTS.md` and
`contracts/graph.schema.json` are unchanged. The three worth a lead decision
before the next iteration:

1. **§1.1.2** (`parent` must have a lower `NodeLevel`) is unsatisfiable together
   with the three-value `NodeLevel` and real ML nesting. Either add a `group`
   level or relax it to "never cyclic, parent level ≤ child level".
2. **§0 ordering leaves ties undefined.** A ghost node shares its parent loop's
   `(stage, file, line, col)` exactly, so two nodes can have identical sort keys.
   Byte-determinism wants a stated tie-break (parent before child, then id).
3. **Serialization is unspecified**, yet A7 requires `--demo` to equal
   `contracts/graph.sample.json` byte for byte. The golden is UTF-8 without BOM,
   LF, `json.dump(..., indent=2, ensure_ascii=False)` plus a trailing newline.
   Freeze exactly that.

## Review and roadmap (2026-09-08)

Five auditors measured the shipped system (analysis accuracy on four unseen
projects, viewer layout on a 360-node graph, host workflow fit, analyzer and
viewer timings on 50/200/500-file synthetic repos, a practitioner walkthrough),
two judges ranked 59 proposals, and the result is `docs/ROADMAP.md` (42 ranked,
11 declined). Headline: 0 false positives on unseen code but roughly 26 % recall,
because `core/build.py` drops every op written inside a class method; the first
screen opens a real repo at 20 % zoom; and the tool cannot yet say "I could not
check this". The one item already applied from the NOW tier is HEALTH-01:
`tools/sync-core.py --check` prunes `__pycache__` residue under
`claude-plugin/vendor` instead of failing on it (source drift still fails), and
`claude-plugin/tests/conftest.py` sets `sys.dont_write_bytecode`, so
`tools/verify.py --all` stays 9/9 after any test run.
