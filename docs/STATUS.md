# MLView — Build status

**Complete and integrated (2026-09-07).** The multi-agent build finished with two review → verify → fix rounds (48 confirmed findings fixed) and a final verification pass; `scripts/e2e.ps1` was re-run by hand afterwards and every one of the thirteen
rows it had then passed. Every component is built, every gate is
green on this machine, and the demo artifacts are produced. `scripts/README.md`
holds the gate table with the command for each row.

**Two features were added on top of that prototype (2026-09-07, second pass):
flow visibility and scoped views.** Both are additive — `schemaVersion` stays
`"1.0"`, no existing field, message, argument or return shape changed, and an
unscoped run still emits the bytes it emitted before. `docs/CONTRACTS.md` §11
binds; `docs/FEATURES_FLOW_AND_SCOPE.md` is the design. The e2e driver grew
four steps (17 at the time; 20 today, since ANA-12 added the accuracy corpus,
PACKAGING added the wheel row and VIEW-07 added the SVG export row) and `tools/verify.py` grew two gate rows
(10 today, the tenth being PACKAGING's `vsix: synced core`).

```
powershell -ExecutionPolicy Bypass -File scripts/build.ps1   # BUILD OK
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1     # E2E OK - 20 steps, 0 failed
```

## Components

| Piece | State |
|---|---|
| Design docs | `docs/REQUIREMENTS.md`, `ARCHITECTURE.md`, `ISSUE_RULES.md`, `UX_DESIGN.md`, `CONTRACTS.md` (§10 amendments are the overriding lead decisions) |
| Contracts | `contracts/graph.schema.json`, `contracts/graph.sample.json` (golden), `contracts/validate_sample.py` (schema + 10 invariant groups) |
| Analyzer `analyzer/` | Complete. **36 rules**, zero runtime dependencies, `python -m mlview` installed editable. **2574 passed, 9 skipped** on 3.12+, plus 24 `xfail` (two skips are the `tomllib` split in both directions, two are the offline-HTML fallback a synced viewer bundle makes unreachable, four want public-corpus clones under `MLVIEW_PUBLIC_CORPUS_DIR`, and one is a rule probe that says in words what it could not resolve). On 3.10 / 3.11 eight more skip: two robustness fixtures are written in 3.12-only syntax — PEP 695 `type X = …` and PEP 701 f-strings — and MLView parses with the host's own `ast`, so a host that cannot read them is not the thing under test. `analyze --demo --json -` is byte-identical to the golden sample. Scoped views live in `analyzer/src/mlview/core/project.py` + `core/selectors.py`; the relevance prefilter and the fact cache live in `core/relevance.py` + `core/cache.py` and are **on by default** from Sprint 5 — `--relevance {ml,all}` (default `ml`), `--relevance-hops N`, `--no-cache`. Interprocedural dataflow ships behind `--dataflow {local,ip}` (default `local`); `core/config.py` is the one reader of `.mlview.toml` / `[tool.mlview]`; `mlview init` and `mlview diff` are the two new subcommands. |
| Viewer `webview/` | Complete. `dist/mlview.{js,css}` built. **585 tests pass** (1 `todo`), `tsc --noEmit` clean. Flow animation (`src/render/flow.ts`) and the TypeScript half of the projection (`src/scope/project.ts`) ship here. |
| VS Code extension | Complete. **404 tests pass**, `tsc --noEmit` clean, `out/extension.js` bundled, `npm run package` produced a **754.24 KB VSIX (148 files)** carrying the bundled analyzer when this row was last measured, with `core/mlview` at **99** files — the number `tools/verify.py --all`'s `vsix: synced core` row prints. **Neither number here is the gate**, and both move whenever a module lands in the analyzer: `python scripts/vsix_check.py` is the gate, it re-derives the ceiling, the bundled-core count, the rule-page count and the absence of bytecode from the tree itself, and CI runs it in the `packaging` job. Copilot participant + LM tools are compile- and unit-verified only (Copilot is not installed here). |
| Claude Code plugin | Complete. MCP server on the `mcp` SDK v2, **still exactly five tools**, each result ≤ 4 KB, plus two `PostToolUse` / `Stop` hooks under `claude-plugin/hooks/`. **460 passed, 7 skipped**, with `python tools/sync-core.py` having run after the analyzer changes (`test_vendor_bytecode.py` is the row that checks it); `claude plugin validate ./claude-plugin --strict` passes. |
| Samples | `samples/vision_pipeline` (54 nodes, 51 edges, exactly 15 issues: 5 high / 6 medium / 4 low) and `samples/vision_pipeline_clean` (64 nodes, 0 issues). `expected_issues.json` is machine-checked. |
| Rule docs | `docs/rules/` — 36 pages plus an index, generated from the registry; 7 carry the optional **What it cannot analyze** section. Every `Issue.docs` deep link resolves. |
| Demo artifacts | `.mlview/graph.json`, `report.html`, `graph_clean.json`, `report_clean.html`, plus the three scoped reports `split.html`, `optimization.html`, `evaluation.html` — self-contained, zero external references, each inside amendment A4's contracted **100 KB – 2 MB** band. No KB figure is quoted here on purpose: the viewer bundle moves, the band does not, and `scripts/e2e` now measures every emitted report against it and prints the range it found (MLV-R1-H06). Each scoped report embeds the **whole** graph and merely opens at its scope. |
| Labelled corpus | `analyzer/tests/accuracy/corpus/` — **158 labelled programs**, 545 `expected` labels, 2327 `forbidden` labels, 1166 hand-drawn graph ops, scored by `tools/accuracy.py` against two ratchets (`baseline.json`, `baseline.ip.json`). Precision **100.0%** with zero forbidden findings is the gated claim; recall is the measured weakness and `docs/ACCURACY.md` is where it is not rounded off. |
| Public corpus | `tools/public_corpus.py` + `analyzer/tests/public_corpus/` — **37 pinned third-party repositories**, 112 targets × 3 modes (`local`, `ip` and `--include-notebooks`) = 260 runs. Nothing is vendored and nothing is labelled: the gate asserts no crash, exit 0 or 4 only, a schema-valid document, the wall-time budget, and **no new high-severity finding** that a human has not adjudicated in `adjudication.json`. It is the only gate that can see a false positive nobody thought to label — it found two at round 1's integration and two more during round 2, both read before they were recorded. |
| Scope fixtures | `contracts/scope.cases.json` (13 selectors + 7 error cases) and `contracts/scope.expected.json`, generated from the Python `project()` over the frozen golden and consumed by the TypeScript port — the parity gate for one algorithm written twice. `scope.cases.json` also carries a growing `fuzzCases` array of counterexamples promoted by `analyzer/tools/scope_fuzz.py`, each minimized to a handful of nodes and carrying its **own** generated graph. |

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
   Demo D and F2-A5/F2-A6 are `concern:evaluation --depth 1` — 17 of 54 nodes,
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

## Sprint 3 — analyzer and viewer, Track A (2026-09-08)

**The re-baseline.** Four roadmap items land as one graph change, because one
golden regeneration has to cover all of them. `docs/CONTRACTS.md` §11.19 is the
amendment and carries the reasoning and the bounds; this is the summary.

`samples/vision_pipeline` grows from 45 nodes and 45 edges to **54 nodes / 52
edges** — both counts in that sentence are the ones measured at the time; the
shipped sample has been `samples/vision_pipeline` at **54 nodes / 51 edges**
since REV-01, on 2026-09-08, dropped the one data edge that pointed backwards
through `SmallCNN.forward` — and carries **exactly the same
fifteen findings**, at the same lines, in
the same 5 / 6 / 4 split — `samples/vision_pipeline/expected_issues.json` is
unchanged and `analyzer/tools/gen_expected_issues.py --check` passes without
regeneration. Both clean corpora stay at **0 issues**
(`samples/vision_pipeline_clean` 55 → 64 nodes, `analyzer/tests/clean` 108 →
127, and 137 once ANA-12's sixth clean file — the `TimeSeriesSplit` walk-forward
script R3.7 asks for — landed on 2026-09-08).
`contracts/graph.sample.json` is hand-authored and was **not** regenerated,
so `--demo`, `contracts/scope.cases.json` and `contracts/scope.expected.json` are
byte-identical and the parity battery is untouched.

1. **ANA-1 — ops written inside a class method were dropped.** `CallSite.class_ir`
   carried two different facts and `analyzer/src/mlview/core/build.py` read the
   wrong one. They are now two fields: `class_ir` (what the call *resolves to*,
   written only by `ir/resolve.py`) and `enclosing_class` (what class the call is
   *written in*, written only by `ir/scopes.py`). No reader may use one for the
   other.
2. **ANA-2 — `self.<attr>(...)` resolved to a symbol nobody declared.**
   `self.loss_fn(...)` became `torch.nn.Module.loss_fn`; it now resolves through
   the binding to the value the attribute actually holds (`ir/resolve.py`).
3. **ANA-3 — a package `__init__` re-export resolved to nothing**, because
   `_relative_base` trimmed the last dotted component of a name that *is* the
   package (`ir/symbols.py`, `ir/build_ir.py`).
4. **VIEW-01 — lane boxes are no longer normalised to the widest lane**, and
   `LANE_MIN_W` drops 420 → 320 with a new `MAX_RANK_W` wrap beside the existing
   `MAX_RANK_H`. On the demo the world goes 2636×2484 → 1576×2630 and `fit()`
   0.322 → 0.532 at a 1240×848 canvas; worst lane emptiness 91% → 32%. The wrap
   itself never fires on the demo (widest lane content 1400 px against a 2000 px
   threshold) — the win is the trimming.

**Measured after.** Precision stays **100%** and every recall reading is
unchanged to four decimals — this was a graph change, not a rule change: unseen
recall **51.1%** raw / **38.3%** visible / **31.2%** high+medium. Graph fidelity
is the one number the re-baseline was allowed to move, and it ratcheted **66.2%
→ 86.3%** (92 → 120 of 139 hand-labelled ops) at the time; Sprint 4's FW-RECOG
has since taken it to **90.6%** (126 of 139), which is what
`analyzer/tests/accuracy/baseline.json` records today. `docs/ACCURACY.md` is the record, and
`scripts/check_docs.py` now holds it to that baseline.

**Also on this branch, outside both host tracks:** PERF-01 and PERF-02 (memoised
knowledge lookup, a role index, and a convergence loop replacing `range(4)` —
byte-identical output on three corpora, proved by `tools/perf_equiv.py`), ANA-12
(the labelled accuracy corpus, `tools/accuracy.py` and `docs/ACCURACY.md`),
BUILD-01 (minified report CSS, −38% on `webview/dist/mlview.css`, under a size
ratchet in `webview/test/bundle.test.mjs`), CI-01 (`.github/workflows/ci.yml`)
and HEALTH-01 / HEALTH-03.

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

## Sprint 4 — hosts, wave 1 (2026-09-09)

Four roadmap items, all additive; `schemaVersion` stays `"1.0"`, the five MCP
tools are still five, and `contracts/graph.sample.json` is untouched.
`docs/CONTRACTS.md` §11.25 and §11.27 are the amendments.

1. **PACKAGING.** `tools/sync-core.py` now vendors `analyzer/src/mlview` into
   `vscode-extension/core/mlview` as well as `claude-plugin/vendor/mlview`, and
   `tools/verify.py --all` grew a **`vsix: synced core`** row (10 rows) that also
   refuses a `.vscodeignore` which would drop `core/` out of the package — the
   condition the lead attached to accepting a third copy of the analyzer.
   `vscode-extension/src/bundledCore.ts` holds the precedence chain: an installed
   core wins when its schema major matches and it is not older, otherwise the
   bundled copy runs with `<extension>/core` on `PYTHONPATH`, and the status-bar
   tooltip names which of the two answered. `installCore()` now offers
   `pip install --upgrade mlview` rather than a checkout path nobody has.
   `package.json` dropped `private` and gained `repository`, `bugs`, `homepage`,
   `icon`, `galleryBanner`, `preview` and `extensionKind: ["workspace"]`, so
   `npm run package` succeeds **without** `--allow-missing-repository`. The icon
   is rendered by `vscode-extension/tools/make_icon.py` (pure stdlib) and its
   `--check` mode gates the committed PNG. `scripts/build.sh` / `build.ps1` gained
   step 6/6, `python -m build --wheel analyzer`, and both e2e drivers gained the
   row `wheel installs and runs` (`tools/wheel_check.py`: a throwaway venv, the
   console script, then one real analysis). `.claude-plugin/marketplace.json`
   keeps the local entry and adds a `github` source.
2. **MLV-P10 (host half).** A `CodeActionProvider` on MLView diagnostics offering
   `Copy ignore comment`, `Add ignore comment on this line` (a `WorkspaceEdit`,
   so it is one undo away) and `Disable rule MLVxxx in .mlview.toml` behind a
   modal confirm, inside the workspace only
   (`vscode-extension/src/codeActions.ts`, `src/suppression.ts`). The viewer's new
   `suppressRule` message runs the same `runSuppression` entry point, so the two
   surfaces cannot drift. The comment MERGES into an existing
   `# mlview: ignore[...]` list rather than stacking a second dead comment.
3. **H3 (host half).** `CoreClient` passes `--progress-json` **only when a panel is
   live**, parses `{"t":"progress"` stderr lines into `postAnalysisProgress`
   (`vscode-extension/src/progress.ts`), leaves every other stderr byte going to
   the output channel, and drops a frame that arrives after `analysisFailed` for
   that `requestId`. The viewer's `done / total` bar has had a receiver since the
   first release and had never been sent a frame.
4. **CI-ADOPT (host half).** `tools/action/action.yml` is a composite GitHub
   Action (install, `analyze --changed-since <base> --changed-only --sarif`, a
   `sarif` output for `github/codeql-action/upload-sarif`);
   `.pre-commit-hooks.yaml` exposes `mlview` and `mlview-changed`, both with
   `pass_filenames: false` because per-file invocation is the fidelity bug
   COVERAGE measured; `mlview_issues` takes `changedSince` and `baseline`
   (`claude-plugin/server/mlview_adopt.py`, which delegates every decision to the
   analyzer's own `mlview.adopt.cli_glue`), and `/mlview-issues` documents both.
   README gained an "Adopt on an existing repo" section.

**CI cost.** `smoke-macos` now runs only on push to `main` and on pull requests:
macOS minutes are billed 10x and were 42% of the bill for two suites ubuntu
already runs, and this Mac runs the whole table locally before every push. A new
`packaging (wheel + vsix)` ubuntu job builds and proves both artifacts.

## Sprint 4 — analyzer, viewer and contracts, wave 1 (2026-09-09)

Six more roadmap items, all additive. `schemaVersion` stays `"1.0"`,
`contracts/graph.sample.json` is untouched, and `analyze --demo --json -` is
still byte-identical to it. `docs/CONTRACTS.md` §11.21, §11.22, §11.30, §11.31
and §11.32 are the amendments.

1. **CI-ADOPT (analyzer half).** §10 A6's `"baseline"` trim is lifted — and only
   that one — because a realistic repository starts at more findings than any
   `--fail-on` gate can survive. The new `mlview.adopt` package reads
   `git diff -M --unified=0` in the analyzed root and stamps each finding of the
   **whole-workspace** analysis with the optional `Issue.change`
   (`new` / `touched` / `existing`); `--changed-only` keeps the findings that
   intersect an added hunk. `mlview baseline write` records `(code, symbol,
   snippetHash)` and `--baseline FILE` sets the optional `Issue.baselined`, which
   is excluded from the counts and from `--fail-on` but still **emitted** and
   still visible under `--show-suppressed`. `--sarif FILE|-` writes SARIF 2.1.0
   validated against the official OASIS schema, with no absolute path in the
   bytes and fingerprints that survive a file moving. Every attribution failure —
   no git, no repo, unknown rev, timeout — degrades to showing everything plus a
   `config_warning`; it is never an error and never an empty list.
2. **MLV-P1 (Pipeline Answer Card).** `emit/answers.py` composes the optional
   root-level `answers` block — where data enters, what is optimised, how it is
   evaluated, and the verdict — deterministically from the finished document.
   Absences are stated as absences, nothing under 0.6 node confidence is
   asserted, a ghost node is never cited as evidence, and the verdict says "so
   this is not a clean bill of health" whenever a coverage diagnostic is present.
   It surfaces as the first block of `--format summary`/`text`, four sentences in
   `api.digest`, and a collapsible card above the canvas in every host
   (`webview/src/ui/answers.ts`).
3. **H3 (analyzer half).** `--progress-json` writes one NDJSON frame per file to
   **stderr**, throttled to one per 50 ms with a guaranteed final frame
   (`analyzer/src/mlview/core/progress.py`). `AnalyzeOptions.progress` is appended
   last and defaults to `None`, so `api.analyze()` still does no I/O of its own.
4. **VIEW-03 (edge labels).** `webview/src/layout/labels.ts` anchors each label to
   the longest axis-aligned run of its own route lying strictly inside one lane
   band, then makes one greedy declutter pass over a fixed cap of 20 candidate
   positions per label. On the flagship report that is **0 label-label overlaps,
   0 labels over a card and 0 within the lane padding of a boundary**, measured in
   Chromium, against 5 / 6 / 3-stacked before.
5. **VIEW-12 (accessibility scaffolding).** A skip link as the document's first
   tab stop, a `<main>` landmark, one `role="toolbar"` with arrow/Home/End roving
   (`webview/src/ui/roving.ts`), one `h1` and a real heading outline, and a
   `:focus-visible` ring on node cards. The canvas is now the **4th** tab stop,
   or the 2nd through the skip link.
6. **MLV-P10 (suppression as an action).** `webview/src/ui/suppress.ts` owns the
   two strings and offers copy / disable from every rail row, from rule group
   headers and from the Inspector; suppressed and baselined findings render in a
   collapsed "N suppressed" section.
7. **HEALTH-02 (differential fuzzer over the two `project()` ports).**
   `analyzer/tools/scope_gen.py` generates seeded, schema-valid documents and
   `analyzer/tools/scope_fuzz.py` compares the Python projection against the
   TypeScript one. **It found a real divergence on its first 200 cases**, in the
   one branch §11.2 step 6 never spelled out: an issue retained through the edge
   rule whose every `nodeIds` entry fell outside `kept`. Python promoted the
   retaining edge's source and linked it both ways; TypeScript left `nodeIds: []`
   and broke invariant 1.1.3. §11.30 makes the Python behaviour normative, the
   port is fixed, three minimized counterexamples are frozen into
   `contracts/scope.cases.json`, and `python tools/verify.py --scopes --fuzz N` is
   the gate. `.github/workflows/nightly.yml` runs 2000 cases a day. The fuzzer was
   proved to bite by building a viewer with one line removed: caught by all eight
   seeds tried, inside 50 cases every time.

**What none of this could analyze.** Change attribution is only as good as
`git diff`: a finding whose own line is unchanged but whose `relatedLoc` sits in
a hunk is `touched`, never dropped, which means an in-place edit of two adjacent
lines can keep two findings rather than one. The baseline key deliberately omits
the file, so a finding that moves file keeps its entry; counted matching bounds
the blast radius. The SARIF declares no `columnKind`, because `Loc.col` is a
UTF-8 byte offset and neither SARIF enumeration is true of it. And the fuzzer
does **not** compare `diagnostics`: §11.1 leaves that prose free, so a divergence
in diagnostic wording or order would still pass.

## Sprint 4 — hosts, wave 2 (2026-09-09)

**VIEW-07, host half — the picture leaves the sandbox.** `docs/CONTRACTS.md`
§11.33 is the amendment; both messages are optional additions to §4 and
`schemaVersion` stays `"1.0"`.

1. **`requestExport` (host → ui) and `exportFile` (ui → host).** The extension
   host cannot draw the diagram — the lane bands, card rectangles, routed edge
   paths and resolved theme colours only exist once the viewer has laid the graph
   out — so an export is a **request** and the picture comes back as a separate
   message. A VS Code webview also has no download of its own (`<a download>` is
   inert in the sandbox), which is why the bytes travel through the protocol and
   the save dialog and the write live in the extension
   (`vscode-extension/src/exportDiagram.ts`, new, 250 lines).
2. **Two commands.** `MLView: Export Diagram as SVG` / `... as PNG` ask the LIVE
   panel (they never open one) and first ask **what** to draw: the whole diagram,
   the current view, or the current scope — the third offered only while the
   viewer has reported one. Both accept the choice as a command argument, so a
   keybinding can skip the pick. `requestExport` is deferred exactly as a reveal
   is: a request reaching a webview with no graph would render nothing.
3. **What the host is willing to write.** The protocol guard rejects a payload
   that is not pure base64, is over 32 MiB, or carries a `suggestedName` with a
   path separator or `..`; the writer then refuses bytes that are not the format
   that was asked for (the PNG signature, an XML/SVG opening tag) **before** the
   save dialog opens, because a `.svg` is executable content in a browser. The
   save dialog defaults to the workspace folder; the toast offers Open and Copy
   Path; a failed write is an error message, not a swallowed exception.
4. **MCP told the truth instead of growing a fake.** `mlview_open_diagram` cannot
   rasterize anything, so it did not gain an `export` argument. Its docstring now
   says SVG/PNG is a viewer feature and every payload carries a constant
   `exportHint` naming `reportPath` and the two surfaces that do produce a
   picture; `skills/mlview-visualize` says the same. Still five tools.

**Gates.** `vscode-extension`: 273 tests (17 new in `test/export.test.js`, plus
the protocol samples), `tsc --noEmit` clean, every `src/` file at or under the
600-line budget. `claude-plugin`: 296 passed / 5 skipped (2 new).

**What this could not analyze.** The viewer half landed in the same commit
(§11.24, below), so the two commands now work end to end — but **no live VS Code
run proves it**: `showSaveDialog` and `workspace.fs.writeFile` are exercised only
against `test/mock-vscode.js`, and every test here plays the viewer's part
through the mocked webview, so what is proven on this side is the host's half of
the contract, not a picture. The two halves were written concurrently and
disagree about one spelling: the viewer emits `name` **and** `suggestedName` and
`base64` **and** `data` on every frame so either validator accepts it, which is
redundancy a lead should collapse to one spelling. The format check is a signature
check, not a validator: a truncated PNG or an SVG whose body is malformed still
reaches disk. Nothing verifies that the exported picture matches what is on
screen — that gate belongs with the renderer, which owns both geometries. And
clipboard copy and the `@media print` stylesheet from the VIEW-07 proposal are
viewer-side and are not part of this change.

## Sprint 4 — analyzer, viewer and contracts, wave 2 (2026-09-09)

**This wave is a framework re-baseline and deliberately *not* a demo
re-baseline.** `samples/vision_pipeline` is byte-identical — 54 nodes, 51 edges,
the same fifteen findings at the same lines in the same 5 / 6 / 4 split and at
the same confidence values — so `contracts/graph.sample.json`,
`samples/vision_pipeline/expected_issues.json`, the scope fixtures and
`vscode-extension/test/fixtures/vision_pipeline.graph.json` are unchanged and
`--demo` byte parity is untouched. There is **no schema change**: both
`analyzer/src/mlview/schema/graph.schema.json` and `contracts/graph.schema.json`
are byte-identical to what they were.

**FW-RECOG — four framework tables and the Lightning hook units**
(`docs/CONTRACTS.md` §11.23). `analyzer/src/mlview/knowledge/tf_tbl.py` teaches
the analyzer the whole `tf.data` chain plus the Keras families that were missing
(`keras.applications`, `Input`, the preprocessing and `Random*` layers, metrics,
callbacks); `knowledge/hf_tbl.py` adds `datasets`, including
`Dataset.train_test_split` with the **split** role;
`knowledge/gbm_tbl.py` adds xgboost / lightgbm / catboost per estimator FQN, so a
boosting node says xgboost rather than sklearn; `knowledge/hooks_tbl.py` and the
new `analyzer/src/mlview/core/hooks.py` put `LightningModule` and
`LightningDataModule` in `MODEL_BASES` and turn every recognised hook into its
own unit node in the lane the framework runs it in, with `trainer.fit` /
`validate` / `test` drawing control edges into exactly the hooks that call runs.
`self.log`, `log_dict` and `save_hyperparameters` are recognised and deliberately
**not** drawn. Supporting resolution fixes: a chained receiver with no name keeps
its data edge (a seven-call `tf.data` chain used to be seven islands), the Keras
functional API resolves, and `ir/locs.call_loc` anchors a **multi-line** method
chain on the method name (single-line calls are byte-identical).

**ANA-5a — never silently drop a call the analyzer cannot resolve**
(§11.23 A1–A8, and 11.18's `unresolved_callee` row flips from *reserved* to
*emitted*). `CallSite.unresolved_callee` is a **per-call** signal — the
scope-wide dynamic flag is never widened — set both syntactically (the callee is
another call's result, a subscript, a lambda, a conditional, an await, a computed
attribute) and through the binding table (a name that is bound to nothing
resolvable: a lambda, a `match`-assigned value, a dataclass `default_factory`).
`ast.Match` case bodies are now walked at all. Each site mints an `unknown` op
carrying the construct, and `analyzer/src/mlview/core/unresolved.py` emits one
diagnostic per (file, scope). **No emitter may now claim a stage is absent
without qualification**: `--format summary` and the mermaid output append
*"(unverified: N calls could not be resolved, so a stage may be present but
undetected)"*, and the MLV-P1 verdict says this is not a clean bill of health.

**VIEW-07, viewer half — the diagram leaves the tool** (§11.24). An export menu
beside Fit offers three regions (current view / whole diagram / current scope)
and five outputs (Save SVG, Save PNG 2x, Copy PNG, Copy SVG, Print). The
mandatory mitigation landed first: **neither renderer decides what is drawn any
more**. `webview/src/render/plan.ts` returns one scene plan — lanes, node
visuals, edge visuals — and `webview/src/render/scene.ts` turns it into DOM while
`webview/src/export/svg.ts` turns the same object into SVG, so the gate can
assert one `<g data-node-id>` per planned box and one `<path data-edge-id>` per
planned route, in plan order, with each path's `d` byte-identical to the routed
edge. The SVG references **nothing outside itself** — no `url(`, no
`foreignObject`, no `<image>`, no `<use>`, no `xlink`, no `@font-face`, no
`<script>`; the only `http` in the file is the `xmlns` a standalone SVG cannot
omit. Colours are read off the mounted root, so a VS Code user exports their own
theme. PNG is drawn **from that SVG** at 2x, never from a second traversal.
`webview/src/styles/export.css` is a tenth and last stylesheet layer whose
`@media print` block hides the chrome, drops the world transform to `none` and
lifts the compact level-of-detail rules.

**Measured.** Precision stays **100%** and every recall reading is unchanged to
four decimals — this was a graph change, not a rule change. Graph fidelity is the
one number the re-baseline was allowed to move and it ratchets **86.3% → 90.6%**
(120 → 126 of 139 hand-labelled ops), re-recorded in
`analyzer/tests/accuracy/baseline.json` with a note naming what earned it:
`keras_tfdata` 66.7% → **100%**, `hf_trainer_finetune` 83.3% → **91.7%**,
`lightning_tabular` **100%**. `analyzer/tests/clean` grows 137 → 142 nodes and
123 → 135 edges and still emits **0 issues**; `samples/vision_pipeline` and
`samples/vision_pipeline_clean` do not move a byte.

**Gates.** Analyzer **1327 passed / 3 skipped** (37 new cases in
`analyzer/tests/core/test_framework_recognition.py` and
`analyzer/tests/core/test_unresolved_callee.py`, over five new fixtures in
`analyzer/tests/fixtures/frameworks` and one in
`analyzer/tests/fixtures/oddsyntax`). Viewer **360 pass** (19 new in
`webview/test/export.test.mjs`), plus the standalone
`webview/test/export_svg.mjs` over a real analyzer document. Extension **273**,
plugin **296 passed / 5 skipped**, `tools/verify.py --all` **10/10**,
`scripts/e2e.sh` **0 failed** (19 rows at that wave; 20 today).

**What this could not analyze.** A Lightning hook reached through a `Trainer`
built in another module gets no control edge. `take` / `skip` holdouts are drawn
and deliberately left unjudged — MLV121 (ANA-9) is what makes a `tf.data` holdout
judgeable. `xgboost.train` / `lightgbm.train` carry role `GBM_TRAIN` rather than
`FIT`, so MLV101 does not see leakage through the functional boosting API. A
`match`-dispatched value is **reported, not resolved**. `unresolved_callee` is
not in `core/coverage.COVERAGE_KINDS`, so it renders in the summary's Notes block
rather than its Coverage block — the constant is mirrored in host-owned files and
extending it needs a host change; the honesty requirement is met by the qualified
*not detected* line instead. Seven of the thirteen labelled ops the corpus still
misses are inline `criterion(...)` / `model(x)` calls on unannotated parameters,
which is DATAFLOW-IP's problem. On the viewer side the SVG is **faithful, not
pixel-identical**: no box-shadow, CSS ellipsis replaced by an average-advance
estimate per face, `color-mix()` washes become `fill-opacity` over an emitted
background rect, and flow animation, hover cards, the selection ring and issue
connectors are states rather than content and are never exported. PNG, clipboard
and print all depend on host capability; their success paths are gated by a
Chromium run, not by `npm test`, and nothing here can gate a real printer.

## Sprint 4 — the three rule tiers, wave 3 (2026-09-09)

**Sixteen new rules, and deliberately not a demo re-baseline.** The registry
grows from **20 to 36** (`python -m mlview rules --list`), and
`samples/vision_pipeline` keeps exactly the same fifteen findings at the same
lines in the same 5 / 6 / 4 split, so `contracts/graph.sample.json`,
`samples/vision_pipeline/expected_issues.json` and `--demo` byte parity are
untouched. `samples/vision_pipeline_clean` and `analyzer/tests/clean` stay at
zero findings, together and one file at a time. No schema field was added
(`docs/CONTRACTS.md` §11.26).

**ANA-7 — the frameworks that published nothing**
(`analyzer/src/mlview/rules/r_framework.py`). MLV705 a Keras `fit()` with no
`compile()` anywhere in the workspace; MLV706 a manual `backward`/`step` inside
a Lightning `training_step` with no `self.automatic_optimization = False`;
MLV707 a `training_step` that never returns a loss; MLV708 a HF `Trainer` with
neither an `eval_dataset` nor an eval strategy in its resolved
`TrainingArguments`; MLV709 a Keras `activation="softmax"|"sigmoid"`
contradicting a same-module `from_logits=True`; MLV711 a batch-cadence
`OneCycleLR`/`CyclicLR` returned from `configure_optimizers` without
`{"interval": "step"}`. None of these declares `absence=True` and none opts
into the wrapper de-rate — the wrapper *is* the subject of the finding — so
every ANA-7 finding clears the 0.60 Problems-panel default.

**ANA-8 — training mechanics** (`rules/r_mechanics.py`). MLV207 scheduler
cadence (epoch-set stepped per batch, batch-set stepped per epoch,
`ReduceLROnPlateau.step()` with no metric), with the `step_size=len(loader)*k`
carve-out; MLV208 the `GradScaler` protocol in four variants; MLV209 a clip
before `backward` or after `step`; MLV502 a CUDA literal at the call site with
no availability probe anywhere; MLV803 whole-model pickling and an unrestricted
`torch.load`. Every ordering predicate compares `stmt_index` only inside one
`block_id` of one confirmed batch loop, which is what keeps
`analyzer/tests/clean/amp_accumulation.py` silent.

**ANA-9 — held-out integrity** (`rules/r_holdout.py`). MLV106 a random split
over two or more independent temporal signals; MLV114 an augmenting `Compose`
reaching an evaluation loader directly; MLV121 a `tf.data` shuffle feeding a
`take`/`skip` holdout without `reshuffle_each_iteration=False`; MLV305 a class
metric fed logits or probabilities, with an exhaustive score-metric carve-out
checked first; MLV306 a ranking metric fed `predict()` output.

**Two deliberate narrowings and one false-positive fix**, all normative in
§11.26. MLV106 requires **two** temporal signals where the catalogue sketch
allowed one at ×0.6, and MLV708 fires on the conjunction rather than any single
clause — ANA-12's tolerance for a forbidden finding is zero. MLV602 no longer
asks `train_test_split(..., shuffle=False)` for a `random_state`: scikit-learn
raises if you pass one, so that arm was a false positive.

**The corpus is the referee, and it ratcheted up.**
`analyzer/tests/accuracy/corpus` grows from 10 labelled programs to 14
(`keras_uncompiled`, `lightning_manual`, `hf_no_eval`, `torch_mechanics`), 77
labels in all; every new rule has at least one satisfied `expected` label and at
least one `forbidden` label, and 17 further `forbidden` labels were added to the
nine existing programs. `tools/accuracy.py` reports **precision 100.0% on every
one of the 36 rules**, overall recall 62.9% → **71.4%** and unseen recall 51.1%
→ **53.2%**, with `analyzer/tests/accuracy/baseline.json` re-recorded upward and
`docs/ACCURACY.md` rewritten from that run (the doc gate holds the two equal).
Graph fidelity is unchanged at 90.6%: the four new programs carry no `graph`
block, because nobody hand-drew their diagrams and claiming otherwise would move
a ratchet on evidence that does not exist.

**What the sixteen rules cannot analyze**, in the artifact a user actually
reads: `analyzer/tools/gen_rule_docs.py` grew an optional
**"What it cannot analyze"** section and 7 of the 16 new pages under
`docs/rules/` use it — MLV705 cannot tell *which* model was compiled, MLV709
pairs a layer with a loss only inside one module, MLV114 cannot say which half
of a `random_split` inherited an augmentation (which is why the demo keeps its
fifteen findings), MLV502 reads only the device literal at the call site, and
MLV208 / MLV209 never compare two blocks. Each is the flow-insensitivity the
roadmap set, stated where it costs the reader nothing to find.

## Sprint 4 — analyzer performance, wave 3 (2026-09-09)

**PERF-03, the relevance prefilter** (`analyzer/src/mlview/core/relevance.py`,
`docs/CONTRACTS.md` §11.28). Between discovery and `build_workspace`, a byte scan for
the framework token set gives the seed modules, an import graph — and *only* an
import graph — is built over every parsed file, and everything within
`--relevance-hops` (default 2) of a seed in either direction survives. The
reachability is computed **after** ANA-3's re-export resolution, so a
`pkg/__init__.py` publishing `from .net import Net` is one hop, not two. On a
500-file mixed synthetic (50 framework modules, 450 ordinary ones)
`build_workspace` drops from **1087 ms to 76 ms** and the whole analysis from
**2228 ms to 693 ms** — 2.6×–3.2×, well under ROADMAP's 1.5 s acceptance —
reporting **the same 51 findings**.
Narrowing emits one `config_warning` naming the set-aside count and both flags
that widen it; when nothing is set aside there is no diagnostic, which is what
makes the two modes byte-identical on the samples, on every rule fixture and on
all three `perf_equiv` corpora.

**The default is `--relevance all`, deliberately.** ROADMAP's condition for
flipping it — `tools/accuracy.py` identical in both modes — is **met**, and the
report is byte-identical over the whole ANA-12 corpus. It stays `all` because on
workspaces too small for the filter to save anything it still moves four
analyzer gates (`filesAnalyzed` on the awkward-syntax corpus, two
`single_file_analysis` counts, and an unresolved-import note that becomes a
set-aside note). That makes the flip a re-baseline rather than an optimisation;
11.28 A11 lists the four so it can be done deliberately. *(Superseded on
2026-09-10: the flip was taken in Sprint 5 wave 1 as the lead directed — `DEFAULT_RELEVANCE` is `"ml"`, the four gates plus three more were re-baselined, and `perf_equiv --expect-same` re-proved the byte-identity. See `docs/CONTRACTS.md` §11.39.)*

**CACHE, and one `file_signature`.** `mlview.core.cache` now owns the single
content-keyed `file_signature` — `claude-plugin/server/mlview_workspace.py` is a
wrapper around it, and the old mtime+size key is gone. What is cached is
deliberately small: the **per-file relevance facts**, keyed on content digest ×
analyzer identity × python minor, in a JSON sidecar under `MLVIEW_CACHE_DIR`
(default `<root>/.mlview/cache`) authenticated with an HMAC over a secret in the
user's home. A warm `--relevance ml` run of the 500-file corpus is **319 ms**,
and **301 ms** after one file is edited (`cached: partial`, 500 hit / 1 miss),
byte-identical to a cold run. `MLVIEW_NO_CACHE=1` and `--no-cache` disable it.

**What was measured and rejected, because the roadmap budgeted for it.**
Reloading a pickled `ast` is *slower* than re-parsing (247 ms against 229 ms
over 501 files) and would have cost 7.0 MB per workspace plus a `pickle` trust
boundary; reloading the pickled module IR is slower still (485 ms against
315 ms, 18.0 MB) *and* depends on the workspace-wide `dotted_names`, so it must
be thrown away whenever a file is created. Both are recomputed every run, and the
cross-module fixed point and the rules always re-run over the whole kept set —
which is why a cached document is byte-identical rather than merely similar.
The roadmap's "~16 s → under 2 s" assumed a pre-PERF-01/02 analyzer; the same
500 files cost **2.2 s** cold on this tree, so the cache's headroom was far
smaller than budgeted and the honest win lay in not parsing the 450 files the
prefilter was going to discard anyway.

`tools/perf_equiv.py` gains `--expect-same` / `--expect-diff` so an integrator
can wire either claim into a gate, and `mixed_corpus()` beside `synth_corpus()`.

**Gates after wave 3.** `sh scripts/e2e.sh` **0 failed, 0 skipped** (19 rows then);
analyzer **1692 passed / 3 skipped**, webview **360**, vscode-extension **274**,
claude-plugin **296 passed / 5 skipped**; `python tools/verify.py --all`
**10 / 10** (including `vendor: synced core` and `vsix: synced core` over 79
files); `python tools/accuracy.py` **PASS**, precision 100.0% on all 36 rules;
`python scripts/check_docs.py` **DOC CHECK OK**; `tsc --noEmit` clean in both
`webview` and `vscode-extension`;
`python tools/perf_equiv.py --compare <recorded>.json --expect-same` **exit 0,
every corpus byte-identical** (and `--expect-diff` on the same pair exits 1, as
it must). The two new suites are `analyzer/tests/core/test_relevance.py` (24),
`analyzer/tests/core/test_cache.py` (30) and
`analyzer/tests/rules/test_tier_rules.py` (50); `test_perf_budget.py` (6) adds
roughly 20 s to the analyzer suite because it builds a 500-file corpus.
Three assertions moved with the wave, all recorded in §11.26: the
`# mlview: ignore[MLV20]` suggestion test now asserts *an* `MLV20x` is offered
rather than naming three, the tight-cap test derives its node budget from the
finding count instead of the literal 50 that 32 new fixtures outgrew, and
`analyzer/tests/fixtures/rules/MLV501_zoo_good.py` gained an
`is_available()` guard because its unconditional `torch.device("cuda")` was a
genuine MLV502.

## Sprint 4 — hosts, wave 4 (2026-09-09)

**NB, host half — a notebook finding lands in the cell.** The analyzer half
(`--include-notebooks`, `ingest/notebook.py`) landed in the same wave; this is
everything between that flag and a squiggle a user can see.

1. **`mlview.includeNotebooks`, default `false`.** The one and only way to reach
   the flag from the extension, and the fourteenth `mlview.*` setting — ROADMAP
   NB is the sanction, and `test/manifest.test.js` records it as such. With it
   off `buildAnalyzeArgs` emits **exactly** the argv it emitted before notebooks
   existed (asserted as a prefix equality, not by eyeball), so the default path
   is byte-identical. `workspaceContains:**/*.ipynb` joined the activation events,
   because a notebooks-only workspace has no `.py` file to activate on and the
   setting would be unreachable there. It is also the **only** `mlview.*` key that
   re-runs the analyzer on change: every other one re-filters a graph the host
   already has, and re-publishing a notebook-free graph would read as "the setting
   does nothing" (`src/watchers.ts`, `REANALYZE_KEYS`).
2. **The squiggle moves to the cell (`src/notebooks.ts`, new).** The analyzer
   converts each notebook to one generated module under `.mlview/notebooks/` and
   every `Loc` names that file — `Loc` is frozen and cannot carry a cell index —
   so publishing a diagnostic as-is puts it in a file the user never wrote. The
   host reads the cell out of the finding's own `context_confirmed` evidence row
   (`<notebook> cell <N>, line <M>`), finds the open `NotebookDocument`, and
   republishes on that cell's `vscode-notebook-cell:` document with a
   cell-relative range. `buildDiagnostics` is therefore keyed by **uri**, not by
   `absFile`, so two findings in two cells of one notebook are two Problems
   entries and either can be cleared independently. It degrades one honest step at
   a time: the cell uri → the `.ipynb` (right file, wrong granularity, which is
   what a closed notebook gets) → the generated module. The cell index counts
   markdown cells, exactly as `NotebookDocument.cellAt` does; an index that has
   gone stale onto a markdown cell is re-read as a code-cell ordinal rather than
   squiggling prose, and a range past the end of its cell is clamped rather than
   refused by VS Code.
3. **Saving a notebook re-analyzes.** `onDidSaveNotebookDocument` is a *different*
   event from `onDidSaveTextDocument` and neither fires for the other, so without
   it a notebook workspace with `analyzeOnSave` on would never re-analyze at all.
   `mlview.includeNotebooks` gates it ahead of `analyzeOnSave`: a run that will not
   read the notebook has nothing to say about the save.
4. **The status bar tells the two apart.** `N notebooks analyzed` vs
   `N notebooks not analyzed`, and **both** when a run read some and could not read
   others — the case a single number hid. `analyzed` is COUNTED from the
   `notebook_analyzed` diagnostics, because there is no workspace field for it and
   each row's `count` is that notebook's *code cells*: summing those would report
   "3 notebooks analyzed" for one file. The LM digest carries the same number and
   the execution-order caveat in words.
5. **MCP.** `mlview_analyze` gained `includeNotebooks`, and so did **`mlview_issues`**
   — a rule list that silently drops every finding inside a notebook is exactly the
   "clean bill of health from a blind run" this feature exists to remove. The flag
   is part of `load_graph`'s **cache key**, not a filter applied after: the same
   sources with and without notebooks are two different documents, and serving one
   for the other would answer the wrong question. `/mlview` documents the flag on
   both the MCP and the CLI path, refuses to call `notebooksSkipped > 0` a clean
   result, and tells the model to cite the **cell** rather than the generated
   module; `skills/mlview-visualize` says the same.
6. **`src/extension.ts` shrank rather than grew.** The five workspace listeners and
   their handlers moved into `src/watchers.ts` (new, 149 lines) as pure
   classifiers plus one `registerWatchers` call: 599 → 583 lines with the notebook
   event added.

**Gates.** `vscode-extension`: **298 passed / 0 failed** (24 new in
`test/notebooks.test.js`), `tsc --noEmit` clean, every `src/` file under the
600-line budget. `claude-plugin`: **305 passed / 5 skipped** (8 new in
`tests/test_notebooks.py`, 1 new in `test_graph_cache.py`).
`python tools/verify.py --all`: **10/10**. Verified end to end against the real
analyzer on a four-cell leaky notebook: `filesAnalyzed 1`, `notebooksSkipped 0`,
one `notebook_analyzed` row, and MLV101 / MLV602 published on cell 3 at cell-lines
2 and 3 with MLV601 on cell 2 — three findings, three correct cells.

**What this could not analyze.**

- **No live VS Code run.** There is no `code` CLI on this machine, so every
  notebook assertion is against `test/mock-vscode.js`'s new `NotebookDocument`
  stubs. The cell uri the mock hands out has the right *shape*
  (`vscode-notebook-cell://<path>#chNNNN`); whether real VS Code accepts a
  diagnostic on the uri of a cell of a notebook that is open but not focused is
  **not** proven here.
- **The cell mapping is parsed out of prose.** `rules/confidence.notebook_evidence`
  writes `"<notebook> cell <N>, line <M>; <order verdict>"` as an evidence detail
  because `Loc` is frozen, and the host regex-matches it. `test/notebooks.test.js`
  pins the format against `analyzer/src/mlview/rules/confidence.py` itself, so a
  rename on either side reddens — but a *machine-readable* per-finding mapping
  (the `cell` / `cellLine` that `Node.attrs` already carries) would remove the
  parse entirely, and the lead should say whether that is worth an amendment.
- **Related locations stay on the generated module.** They carry no evidence of
  their own, so the cell they came from is not recoverable; the generated module
  is a real file that re-opens and slices (R2.1), so the Problems panel shows
  `.mlview/notebooks/x.py:18` for the split site of a notebook leak.
- **The diagram still draws the generated module's PATH.** Node labels and the
  CodeLens anchor on `.mlview/notebooks/*.py`; only the Problems panel was
  re-anchored. The viewer does now read `Node.attrs.cell` / `.cellLine` and
  appends `> cell N : M` to the label (see the integration section below), but the
  path half of that label is still the generated module, not the `.ipynb`.
- **`vscode-extension/README.md` still lists `mlview.showSpeculative` and
  `mlview.followCursor`**, both of which CLEANUP removed from the manifest. Noticed
  while adding the `includeNotebooks` row; not fixed here because it is not this
  item's change and the row is a one-line delete somebody should make deliberately.

## Sprint 4 — analyzer, viewer and integration, wave 4 (2026-09-09)

**NB — `.ipynb` ingest behind `--include-notebooks`, and the caveat that has to
travel with it.** Two audits wrote the same leaky notebook and both got
`0 files analyzed · 1 notebook skipped · 0 issues`, exit 4: a green status bar
over a textbook fit-before-split. Notebooks are the medium in which people fit
before splitting, so the tool was blind exactly where its flagship rule family
matters most. `docs/CONTRACTS.md` **11.29** is the amendment; `REQUIREMENTS.md`
§5 non-goal 3 is lifted **behind the flag only**, and §10 A6's "notebook
fixtures" trim is lifted with it because NB's acceptance is stated over fixtures.

1. **Nothing happens unless the caller asks.** `--include-notebooks` on
   `analyze`, `issues` and `baseline`, or `[paths] notebooks = true`. Without one,
   discovery, the graph, the diagnostics and the exit code are what they were.
   **Measured, not asserted by eyeball**: `tools/perf_equiv.py --baseline <the
   pre-wave-4 analyzer> --expect-same` reports `vision_pipeline`,
   `vision_pipeline_clean` and `tests_clean` all `identical` and exits 0, and
   `analyze --demo --json -` is still byte-identical to `contracts/graph.sample.json`
   at 46 078 bytes. A `[paths] notebooks` that is not a boolean is a
   `config_warning`, never a silent truthiness read.
2. **One notebook becomes one generated module** at
   `<root>/.mlview/notebooks/<the notebook's path>.py`, and every `Loc` names it,
   so R2.1's re-slice guarantee holds unchanged and is gated on notebook fixtures
   directly. Line counts are **1:1 inside every cell**: a line magic, a `!` shell
   escape and a `?` help query become `pass  # mlview: magic` at their own
   indentation — replaced, never deleted, because deleting one would slide every
   later line and the cell map would be wrong from there on. A magic that *wraps*
   a statement keeps the statement (`%time model.fit(X, y)` → `model.fit(X, y)`),
   guarded by an `ast.parse` of the remainder so a shape the rewriter misreads
   costs one notebook rather than being guessed at. A bracket-depth and
   triple-quote scanner keeps the `%` in `(10\n % 3)` from being read as a magic.
3. **The cell map rides beside the `Loc`, because `Loc` is frozen (§2).** Every
   node in a generated module carries `attrs.notebook`, `attrs.cell` (0-based over
   **all** cells, markdown included — the index a host needs for
   `vscode-notebook-cell:`) and `attrs.cellLine`. Values are strings, so there is
   **no schema change at all**: `contracts/graph.schema.json`, its two mirrors and
   `contracts/graph.sample.json` are byte-identical to what they were.
4. **The execution-order caveat is the honest half.** A notebook records only the
   `execution_count` of its *last* run. `orderOk` is "strictly increasing over the
   cells that record a count"; a non-monotonic notebook emits the
   `notebook_analyzed` diagnostic saying so, carrying
   `codes = [MLV101, MLV203, MLV209]`, and de-rates exactly those three by
   `NOTEBOOK_ORDER_FACTOR = 0.75` — applied as the **weight of an existing
   evidence factor**, so it goes through the six-factor product and is visible
   wherever evidence is rendered rather than needing a new mechanism. In-order
   notebooks get weight 1.0, an exact identity, so the same code in a `.py` and in
   an in-order notebook score identically. Measured end to end: MLV101 goes from
   **0.95 (certain) to 0.712 (likely)** while MLV201 is untouched at 0.9.
5. **Every success says what it did.** One `notebook_analyzed` per analyzed
   notebook, always. `notebooksSkipped` never becomes zero merely because the flag
   was on — it is every notebook discovered minus those that really reached the
   rules, and each failure (bad JSON, non-UTF-8, unwritable or unparseable
   generated module) gets its own `parse_error` naming the `.ipynb`, not the
   generated module, because the reader has to find the file the tool choked on.
6. **The viewer says `> cell 3 : 4` instead of a line nobody can count to.**
   `webview/src/notebook.ts` owns the one translation, and `dom.fileLine`
   delegates to it, so the card, the rail row, the inspector, the tooltip, the
   search meta and the SVG export all pick the cell up from one seam. The cell
   survives end-ellipsis: `locParts` splits the label into a shrinkable path and a
   fixed tail, so the path is clipped and the answer is not. A notebook last run
   out of order raises a dismissible warn banner **above** the coverage banner —
   execution order outranks coverage, because it de-rates the findings underneath
   it — and a run that *did* read notebooks now draws a chip instead of vanishing
   into the "N notes" count. **Nothing here ever invents a cell**: a `.ipynb` path
   with no mapping, or with half a mapping, prints the flat line, because a
   fabricated cell index is a broken click-to-code that looks correct.
   `openLocation` still posts the flat line and the nine frozen keys — hosts own
   the `vscode-notebook-cell:` mapping.

**What the integration pass reconciled.** The viewer half was written before the
analyzer half landed, against an inferred contract: optional `Loc.cell` /
`Loc.cellLine` fields and a `notebook_out_of_order` diagnostic kind. 11.29
settled it differently, so against a real `--include-notebooks` run the viewer
would have rendered flat lines and drawn no banner — the honesty half of NB
failing silently, which is the one failure mode this item exists to remove. Two
changes, both at the source:

- **`adoptCellMap`** lifts 11.29 N6's mapping off `Node.attrs` (where it is, as
  strings) onto each node's own `Loc`, once per document in `App.setGraph`, so the
  twelve label call sites stay unchanged and no surface has to know where the
  analyzer keeps its provenance. A half-written or non-numeric mapping is left
  alone and falls back to the flat line.
- **The banner reads 11.29 N10's shape.** There is one `notebook_analyzed` per
  analyzed notebook and the verdict is carried by its `codes`, not by a kind of
  its own, so the predicate is "the kind, or an analyzed notebook that named the
  rules it cost confidence in". An in-order notebook draws the chip and no banner.

Both are pinned by four new cases in `webview/test/notebook.test.mjs`, and
verified against **real analyzer output** rather than a synthesised document: a
four-cell `execution_count [1, 3, 2, 4]` notebook analysed with
`--include-notebooks` and its standalone report loaded in jsdom gives 15 node
location rows, 13 carrying a cell, the banner drawn naming MLV101 / MLV203 /
MLV209, and the `4 notebooks analyzed` chip. That closes the viewer's "no
end-to-end notebook exercise" gap.

**Gates.** analyzer 1722 passed / 3 skipped (26 of them NB, plus 3 notebook
`test_locations` cases); webview 384 pass (24 NB); vscode-extension 298 pass
(24 NB); claude-plugin 305 passed / 5 skipped (8 NB); `tools/verify.py --all`
**10/10**; `tools/accuracy.py` precision **100.0%**, recall 71.4% (NB adds no
rule, so the ratchet did not move); `sh scripts/e2e.sh` **0 failed** (19 rows then);
`tsc --noEmit` clean in both TypeScript packages. The bundle ratchet was
re-measured and **neither cap moved** (JS 269 389 B under 268 KiB, CSS 60 429 B
under 61 KiB).

**One shipped bug fell out of CI while landing this.** `e2e (windows, powershell)`
went red on a *different* `analyzer/tests/core/test_cache.py` case on each run,
always with `cache MAC mismatch`, on a tree whose analyzer source had not changed
since the previous green Windows run. The cause is in `core/cache._secret`, not in
NB: the 32-byte MAC secret was created with `os.open(..., O_WRONLY | O_CREAT |
O_EXCL)`, and **on Windows that is TEXT mode** — every `0x0A` byte is written as
`0x0D 0x0A`. The creating run then MACs with the 32 bytes it holds in memory while
every later run MACs with the longer bytes it reads back, so the sidecar is
rejected for ever and CACHE is silently off. It bites the ~12 % of keys that
contain a `0x0A` (1 − (255/256)³²), which is why it read as an intermittent CI
flake rather than as the permanent, per-user cache outage it actually is. Fixed by
naming the flag (`core/cache.O_BINARY`, `os.O_BINARY` where the platform has it and
0 elsewhere) and passing it. The regression test stands a Windows in for whatever
platform it runs on — it emulates the text-mode translation and asserts the secret
reads back byte-identical — so removing the flag reddens on Linux and macOS too
rather than waiting for a Windows runner to be unlucky.

## Sprint 4 — process and docs, review round (2026-09-09)

**The roadmap now records every item that shipped, and a gate keeps it that way
(PROC-01).** Waves 2, 3 and 4 landed FW-RECOG, ANA-5a, VIEW-07, ANA-7 / ANA-8 /
ANA-9, PERF-03, CACHE and NB, and `docs/ROADMAP.md` carried a `**Landed ...**`
measurement note for wave 1 only. That is not bookkeeping: the roadmap is where
the **acceptance clause** is written, and the framing this sprint was told to
carry forward — *every analyzer change must state what it could not analyze* —
is discharged in those notes and was discharged nowhere in the roadmap for the
seven analyzer-heavy items that followed. Seven notes were written from the
measured figures in the sections above, each naming the acceptance clauses that
were **not** met literally: PERF-03 and CACHE ship opt-in with the default path
byte-identical and CACHE's `~16 s cold` baseline no longer exists; VIEW-07's
*"all 45 cards, 45 edges"* predates the ANA-1/2/3 re-baseline; NB's leak fixture
fires MLV101 / MLV602 / MLV601 rather than the MLV101 / MLV201 the clause names,
and the cell map rides on `Node.attrs` because `Loc` is frozen; ANA-9's MLV121
closes the `tf.data` `take` / `skip` holdout that FW-RECOG had left deliberately
unjudged one wave earlier. H3's note, which had been written *below* the
`### LATER` divider where it read as an item of its own, moved back into H3's
section.

`scripts/check_docs.py` gained **check 12** for it: when a `docs/STATUS.md`
paragraph opens by naming a roadmap item, that item's roadmap section must carry
a `**Landed` note, and a landed note must sit inside some item's section. Run
against the pre-fix tree it reports exactly the eight problems above; against
this one it is silent. Check 8 was widened in the same pass (PROC-09): it reads a
**two-line window**, so `54 nodes / 52\nedges` — which sat in this file for a
whole sprint — is no longer invisible, and it accepts `N nodes and M edges`,
the shape `docs/CONTRACTS.md` §11.19 used. A figure escapes only when its own
window says, in words, that it is *at the time*.

**The VSIX figures are measured by a gate instead of retyped into two docs
(HOST-8).** `scripts/README.md` row 27 and this file's component table both said
`126 files, 576.92 KB`, and this file said `core/mlview` at **79** files while
`tools/verify.py --all` printed **80** for the same directory on the same commit.
The package measured in this round is **127 files, 593.08 KB**, 80 under
`extension/core/`, 37 rule pages, no `__pycache__`, 57.9% of the 1 MB ceiling —
and it will move again on the next analyzer module, which is the point. Both
prose copies were corrected, and `scripts/vsix_check.py` now re-derives all of them — the ceiling,
`extension/core/` against `vscode-extension/core` on disk, `extension/docs/rules`
against `docs/rules`, and zero bytecode — and echoes what it measured, the way
`webview/test/bundle.test.mjs` does for the renderer bundle. CI's `packaging` job
runs it in place of the inline `wc -c`.

**One CI cost figure, with the rounding rule stated (PROC-10).** `README.md` said
a full green run was `~48 billable minutes` and that gating macOS took a branch
push to `~28`; the gate table said `~41`. The measured run (34311137829, the tip
of `sprint4`) is neither: **6m39s wall and ~37 billable minutes** — 23 for the
**eleven** ubuntu jobs (`README.md` said ten) and 14 for the one Windows job at
2x, with `smoke (macos)` skipped; `main` and pull requests add ~20 for the 10x
macOS job, so ~57. Both docs now quote that arithmetic *and* the rule it assumes
— each job rounded up to a whole minute on its own, then weighted — so the next
re-measure is reproducible.

**The constraint that cost work is now written down (PROC-12).** `origin` is the
HTTPS URL and the stored credential is a repo-scoped PAT with no `workflow`
scope, so a push whose diff touches `.github/workflows/**` is rejected. A 20th
e2e step (gate row 12d, `webview/test/export_svg.mjs` wired into both drivers)
was implemented, passed and then reverted for exactly this reason, because
promoting it also means editing `ci.yml`'s two "19-step" comments. `scripts/README.md`
now records the SSH workaround and the owed promotion beside the CI section.

**Gates.** `python -m pytest scripts -q` **56 passed** (39 before: 9 new doc-gate
cases and 8 for the VSIX checker); `python scripts/test_check_docs.py` runs all
three files from one entry point and prints `check_docs self-test OK`;
`python scripts/check_docs.py` **DOC CHECK OK** (19 files);
`python tools/verify.py --all` **10/10**; `python scripts/vsix_check.py`
**OK**. No analyzer, viewer or host source was touched, and the only workflow
change is the `packaging` job's last step.

**What this could not analyze.** `docs/CONTRACTS.md` §11.19 still says *"54 nodes
and 52 edges"* in frozen normative prose. It is in `check_docs.py`'s SKIP set and
was true when written, and the correct repair is a contracts-owned **erratum**,
not an edit to a frozen amendment — this round had no amendment number assigned
and deliberately did not take one. The component table above also still carries
per-suite test counts from earlier waves (the extension row says 274 where wave 4
measured 298); those belong to whoever lands the next wave, and re-running four
suites to refresh them would have raced the agents holding them. And check 12
reads only STATUS paragraphs that *open* with an item id: a wave that reports an
item some other way still ships unrecorded.

## Sprint 4 — review fixes, integrated (2026-09-09)

Twenty-three defects from the Sprint-4 review, fixed at their source and landed
in one commit. `docs/CONTRACTS.md` **§11.34** is the amendment for the twelve
analyzer-side ones (R1–R12); the viewer, host and process fixes needed no new
contract clause and are recorded here.

**Two rules were judging the wrong thing, and the lead decision on ANA-12 is
that a forbidden finding is never tolerated.** MLV709 paired *a module's*
`from_logits=True` with *any* softmax/sigmoid layer in the same file, so a
`models.py` holding a probs head and a logits head accused correct code at
high/certain, and a squeeze-and-excite `Dense(ch, activation="sigmoid")`
channel gate — an internal gate, not an output — was read as an output
activation. `analyzer/src/mlview/rules/keras_walk.py` (new, 169 lines) walks
`compile()` → the `keras.Model(inputs, outputs)` / `Sequential([...])` its
receiver resolves to → the layer behind that model's `outputs=`; the layer and
the loss must now meet **on the same model** and the layer must be that model's
**output**. Where the walk resolves to nothing the rule is silent rather than
pairing by family. MLV121 fired on `for images, labels in train_ds.take(1)` —
the commonest peek-at-one-batch line in TensorFlow — with a message asserting a
holdout that the program does not have. A holdout is now **the pair** (one
shuffled receiver reaching both a `take()` and a `skip()`) or a subset finally
bound to an evaluation name; `shard` is never on its own evidence.

**A whole binding style was silently unanalyzed.** `ir.bindings.binding_of`
gained `exclude: Optional[CallSite]` and `ir/resolve.py` passes the call being
resolved, so `ds = ds.map(...)` — the style the official `tf.data` guide writes
— no longer resolves its right-hand side against the store that same statement
is about to write. Measured on three semantically identical six-call pipelines:
fluent **7 nodes / 5 edges**, distinct names **7 / 5**, and `ds = ds.<op>(...)`
**2 nodes / 0 edges with `diagnostics: []`** — a clean bill of health from a
blind tool, which is the failure this sprint exists to forbid. All three now
measure 7 / 5, gated per style. The same seam silenced MLV101 on
`df = df.dropna()`. Separately, F9's *"recognised but not drawn"* now applies to
**edges** as well as nodes (`core.build.NOT_DRAWN_ROLES`): `self.log(...)` was
drawing a `data` edge from the loss into the LightningModule while
`self.log_dict(...)` drew none.

**Four surfaces claimed more than they knew.** A notebook finding is now
attributed to its source `.ipynb` (`adopt.notebook_source()`, the exact inverse
of `ingest.notebook.shadow_relpath`) at **file** granularity, with a
`config_warning` saying the granularity was traded for a location git can see —
before this, every notebook finding classified `existing` and a pull request
whose entire content was a fit-before-split notebook passed both shipped CI
surfaces at exit 0. `mlview issues` renders the `Coverage` and `Notes` blocks
`analyze` renders and may no longer print a bare `none found` while findings
were withheld. `emit/answers.py` drops the `no backward() call` clause and adds
*"and N call(s) could not be read"* whenever a `_COVERAGE_KINDS` diagnostic is
present — it had been telling a reader there was no `backward()` in a file whose
training loop calls `loss.backward()`. SARIF `helpUri` is now the absolute
`https://github.com/realmyang/MLView/blob/v<version>/docs/rules/<CODE>.md`;
`reportingDescriptor.helpUri` has no `uriBaseId` companion in 2.1.0, so the
relative path 404'd in every repository that is not this one.

**The accuracy referee stopped flattering itself (ANA-12 is the referee for
every rule).** `score_graph` returned `1.0` for a program with no `graph` block,
so the four programs that carry no hand-drawn diagram printed four perfect
scores; they now read `not labelled` and contribute nothing, exactly as they
always did to the aggregate. `perRule` gained `unseenExpected`,
`unseenRecovered` and `unseenRecall` and the table an `unseen recall` column
with the `*` footnote — sixteen rules read `recall 100.0%` off a single label in
a program written alongside them, and nothing said so. A full-batch training
loop (`for epoch in range(20):` over tensors already in memory) is judged by no
MLV201/202/203 classifier and now raises an `untagged_dataflow` note naming the
loop, the `backward()` line and the three codes that did not judge it; zero such
notes on `analyzer/tests/clean` and both `vision_pipeline` samples, measured.
Under `--show-suppressed`, `analyze --format summary` now heads its table
`Issues (<net> · N baselined · M suppressed)` and marks baselined rows, instead
of netting them out of the header and listing them unmarked.

**The viewer drew a layout it had not reserved.**
`webview/src/layout/cardmetrics.ts` (new, 102 lines, pure — no DOM) derives a
card's height from what the card will **draw**, from the same predicates the
renderer uses: 70.1 px
for a three-row card (`NODE_H` 72, unchanged), 54.4 px with no `file : line` row
(`NODE_H_GHOST` 60, unchanged), 96.1 px with the attribute chip row
(`+ NODE_CHIP_ROW_H` 26). On the shipped demo exactly one card carries chips, so
24 px of extra ink collided with nothing and every gate stayed green; on a
notebook report **every** node carries `attrs.cell`, so all 26 cards drew 96 px
against a plan of 72 — two card pairs overlapped and 6 of 26 edge labels were
placed on top of a card. `render/nodes.ts` now pins `height` rather than
`min-height` and clips the text column, so past this point the plan is
authoritative and the ink gives way, as it already did in the SVG export. The
label declutter gained a frame-bounds test (5 demo labels had been placed left
of x = 0 and truncated in the SVG, the PNG and in print). The VIEW-07 export
menu is operable from the keyboard: every key on the trigger now stops
propagation (the roving `role="toolbar"` was eating ArrowDown and moving focus
to "Toggle side rail"), Escape closes it from anywhere in the capture phase, and
opening focuses the first item for **every** gesture — its items are
`tabIndex = -1`, as `role="menu"` requires, so Enter or a click had left the
panel unreachable. The standalone theme switch now updates `App.theme`, so an
exported SVG stops claiming `data-mlview-theme="light"` and the high-contrast
export path is reachable at all. The toolbar and status-bar severity counters
net baselined findings out, the way the rail, the answer card and the CLI
already did. The notebook chip prints the notebook's name and **its cell count**
— `core/pipeline.py` emits one diagnostic per notebook whose `count` is that
notebook's code cells, so two notebooks read "4 notebooks analyzed" twice. The
baseline and changed-paths diagnostics wrap instead of being silently truncated
as one-line nowrap chips wider than the window.

**Hosts.** `suppressRule(insert)` applies the containment guard on the path the
webview names, not only where it can never fail; `addDisabledRule` keeps a
trailing comment on the `disable` line, which §11.27 S4 promises and the
implementation deleted. MCP `mlview_issues` carries `includeNotebooks` through
`changedSince` / `baseline` (it reaches `AnalyzeOptions` via `load_attributed`)
instead of dropping it on that branch. The pre-commit hooks are installable at
all for the first time: a `language: python` hook makes pre-commit run
`pip install .` in the **clone root**, and the only packaging metadata lived in
`analyzer/pyproject.toml`, so both hooks died with *"Directory '.' is not
installable"*, tag or no tag. A root `pyproject.toml` packages `analyzer/src` in
place — no second copy of the analyzer — with its version `dynamic` off
`mlview.version.__version__` so gate 9's "one version string" still holds.

**Gates, all re-run on this Mac at the integrated tree.** `sh scripts/e2e.sh`
**19 steps, 0 failed, 0 skipped**; analyzer **1748 passed / 3 skipped** (1722
before); webview **404 tests** (384); vscode-extension **308 tests** (298);
claude-plugin **324 passed / 7 skipped** (305 / 5); `npx tsc --noEmit` clean in
both TypeScript packages; `python tools/verify.py --all` **10/10**;
`python tools/accuracy.py` **PASS** — precision **100.0%**, overall recall
**71.8%** / 64.1% visible / 63.2% high+medium over 15 programs and 78 labels,
unseen recall 53.2% / 40.4% / 34.4%, graph fidelity **90.6%** (126 of 139),
**zero forbidden findings**;
`python analyzer/tools/scope_fuzz.py --cases 400 --seed 4` **PASS**, python ==
typescript over 80 generated graphs;
`python tools/wheel_check.py` **OK**; `npm run package` + `python scripts/vsix_check.py` **OK — 128 files, 604.57 KB, 59.0% of the 1 MB ceiling, 81 under
`extension/core/`, 37 rule pages, 0 bytecode**; `python scripts/check_docs.py`
**DOC CHECK OK** (19 files). One corpus program was added — `keras_se_gate`,
carrying the MLV709 and MLV121 false-positive shapes as `forbidden` labels and a
rebinding-style holdout as `expected` — and it is marked `tuned`, because the
two guards were developed against its shapes: its zero-forbidden result is a
regression guard, not an unseen measurement. `analyzer/tests/accuracy/baseline.json` moved overall recall 0.7143 → 0.7179 and visible 0.6364 → 0.6410;
unseen and graph fidelity did not move and precision stayed 1.0. No fixture was
regenerated: `analyze --demo --json -` is still byte-identical to
`contracts/graph.sample.json` at 46 078 bytes and `.mlview/graph.json` is still
54 nodes / 51 edges / 15 issues, because none of these fixes touches a shape the
demo contains.

**CI (run 34320075813, `sprint4`).** **12 jobs green, `smoke (macos)` skipped**
— Python 3.10-3.13, Node 20/22, `vscode-extension`, `claude-plugin`,
`e2e (ubuntu, sh)`, `e2e (windows, powershell)`, `packaging (wheel + vsix)` and
the accuracy corpus; **6m30s wall, ~38 billable minutes**. **One** fix iteration,
and it was real: `vscode-extension/test/mock-vscode.js` keyed its virtual
documents by the spelling the test wrote, while the extension — after this
round's containment fix — opens the `path.resolve`d path. Those two strings are
equal on POSIX and `D:\repo\...` on Windows, so two suppression cases died on
`document.lineAt is not a function` in a **test double** that no other platform
could see. `docKey()` now resolves on both sides, which is what a real
`Uri.file()` round trip does. The push itself had to go over **SSH**: the stored
credential is a repo-scoped PAT with no `workflow` scope and this diff moves the
`packaging` job onto `scripts/vsix_check.py`, exactly the constraint PROC-12
wrote down last round.

**What this could not analyze.** MLV709 is silent on a subclassed `keras.Model`
with a `call()` method, on a model compiled in a different module from the one
that built it, and on an `outputs=` expression that is neither an inline call
nor a name bound to one. MLV121 is silent on a holdout whose `take` and `skip`
come off different `shuffle` calls unless the subset carries an evaluation name.
The `binding_of` fix covers the **self**-rebinding case only — a name rebound in
a branch, or through a container, is still resolved flow-insensitively. A
notebook finding is attributed to the whole notebook and never to the cell, and
its SARIF `artifactLocation.uri` still names the generated module, so a GitHub
code-scanning alert on a notebook finding cannot anchor to a line of the
checked-out commit. `cardmetrics.ts` reserves a constant, so a host whose UI
font is materially larger than ours draws taller rows than its table; the card
clips rather than overlaps, which is the honest failure but still a failure.
The export menu's keyboard path is unit-covered and was exercised in Chromium on
the emitted report, never inside a real VS Code webview — there is no `code` CLI
on this machine. And ANA-12's unseen half is still small: R10 marks which rules
have no unseen label, it does not close the gap, and closing it needs labelled
programs nobody on this project wrote.

## Sprint 5 — process (2026-09-10)

No analyzer, viewer or host behaviour changed in this wave. One CI job that had
been red since it last ran, one gate row promoted out of the "run it by hand"
list, and one wrong number in frozen prose.

**CI-MACOS-01. `smoke (macos)` was red, and the assertion was the defect.** The
job runs only on push to `main` and on pull requests, so run 34419964015 — the
Sprint-4 merge — was the first time it had executed since Sprint 3, and it
failed while all thirteen other jobs and the whole local table were green. The
failure was one test:
`test_perf_budget.py::test_editing_one_file_re_analyses_fast_and_byte_identically`,
`AssertionError: the warm run was only 1.15x faster than the cold one (0.98s ->
0.85s)` against a `DELTA_SPEEDUP = 1.25` bar. **Nothing on that runner was
broken**: the cache was consulted, hit 501 of 501, and the warm document was
byte-identical to the cold one — the assertion immediately above the failing one
proved it on the runner itself. What failed was a **wall-clock ratio**, and the
ratio is dominated by the term the cache does not touch. The cache elides exactly
one thing — the parse of the 450 modules the relevance prefilter was going to
discard anyway; reading all 501 files, the IR fixed point and every rule over the
51 kept modules are paid in full by the warm run too, and that common term is two
to four times the elided one. The ratio is therefore `1 + saved/common`: it drifts
towards 1.0 with every rule the analyzer gains, and it moves with whatever else
the host is doing. Measured on this Mac while fixing it: **1.45x, 1.46x, 1.56x,
1.58x and 2.50x on five runs of the same commit**, against a 1.25 bar. Measured on
`macos-latest` after the fix: **1.38x**, where the failing run had read 1.15x. And
measured inside that one macOS job, the reason the bar could not stand: two runs of
the **identical** configuration — `relevance="ml"`, cache off — took **1.19 s and
0.76 s**, 57% apart, in the same process. A bar at 1.25 against a quantity that
reads 1.15x–1.38x on a host whose own inputs swing by half is a coin toss, and it
was going to redden on somebody's machine whatever the cache did.
The delta test now asserts what the cache actually controls, as **counts**:
`("none", 0, 501)` cold, `("partial", 500, 1)` after one file is edited — which
is CACHE's acceptance sentence, *"only that module's facts are recomputed"*,
asserted for the first time rather than implied — and `("full", 501, 0)` warm,
with `--no-cache` consulting nothing at all. Byte-identity is unchanged. Wall
clock is held to `DELTA_CEILING_S = 8.0`, the item's own *"under 2 s"* acceptance
with the room for a shared runner that `CEILING_S` above it already carries. Both
perf tests now print the cold, warm and bytes-only figures they measured, so the
next person to read a CI log sees the numbers instead of inferring them.

**PROC-12. The 20th e2e step.** `webview/test/export_svg.mjs` — gate row 12d,
VIEW-07's exporter over a **real** 54-node document rather than the frozen
`contracts/graph.sample.json` that `npm test` uses — is now `export diagram
(SVG)` in both drivers, between the clean-report render and the scoped demo
artifacts, where the `.mlview/graph.json` it reads has just been written. It
SKIPs itself, with the reason in the table, when that document, the script or
`webview/dist/mlview.js` is missing. It had been implemented and reverted once
before because promoting it means editing `ci.yml`, and `origin`'s PAT cannot
push a workflow file; this time the push went over SSH. Every "19 steps" claim in
`README.md`, `scripts/README.md`, `ci.yml` and this file moved to 20 —
`doc_numbers.py` check 11 holds all of them to one number and is what caught the
last three. Historical wave records above now state their row count as *"19 rows
then"* rather than as an `N steps` total, because what those paragraphs record is
what that wave measured, not how big the table is today.

**§11.35. An erratum, not an edit.** `docs/CONTRACTS.md` §11.19 opens with
*"54 nodes and 52 edges"*; the shipped sample has been 54 / 51 since REV-06
removed the one backwards `data` edge through `SmallCNN.forward`, later the same
day §11.19 was written. §11 is append-only, so the repair is a new numbered entry
correcting the figure and naming the reason, not a two-character edit to a frozen
amendment. It also writes down why nothing caught it: `check_docs.py` holds every
document to one graph size, `docs/CONTRACTS.md` is deliberately exempt from that
rule so a frozen amendment may keep a figure that has since moved, and the price
of the exemption is that a wrong figure is equally invisible. The exemption
stays.

**Pushes go over SSH.** `scripts/README.md` now says so as a standing rule rather
than as a workaround for one file: whether a diff touches `.github/workflows/**`
is not something to discover after writing the commit. It reverts to a choice
when the PAT gains the `workflow` scope.

**Gates, all on this Mac.** `sh scripts/e2e.sh` **20 steps, 0 failed, 0 skipped**
— the 20th being `export diagram (SVG)`, which reports 54 of 54 cards, 51 of 51
routed edges, every document edge in the picture, 237 `<text>` nodes, 180
`<rect>`s and nothing to fetch. analyzer **1748 passed / 3 skipped**, webview
**404**, vscode-extension **308**, claude-plugin **324 passed / 7 skipped**,
`python tools/verify.py --all` **10/10**, `--scopes` **2/2**, `python
scripts/check_docs.py` **DOC CHECK OK (19 files)**, `python -m pytest scripts -q`
**56 passed**, the accuracy corpus **PASS** with the ratchet unmoved (no rule
changed).

**CI (run 34422156964, `sprint5`).** **All 13 jobs green, `smoke (macos)` among
them** — the first branch push on which that job has ever run, its guard widened
to this branch for one verification push and restored in the commit after it.
Python 3.10-3.13 69-109 s, Node 20/22 125-137 s, `vscode-extension` 33 s,
`claude-plugin` 56 s, `e2e (ubuntu, sh)` 311 s, `e2e (windows, powershell)`
382 s, `packaging` 44 s, accuracy 13 s, `smoke (macos)` 150 s. **6m25s wall and
~68 billable minutes** — 24 ubuntu, 7 x 2 = 14 Windows, 3 x 10 = **30** macOS.
That last figure had been *estimated* at ~20 since Sprint 4 and is now measured
at 30: the job is slower than the ~93 s it was when the estimate was made, and
the 10x multiplier turns one extra rounded minute into ten. **Zero fix
iterations** — the fix was green on the runner the first time it ran there.

**What this could not analyze.** *Why* a given run of that workload lands where
it does is not established, only that it is unsteady: the same configuration
measured 1.19 s and 0.76 s inside one macOS job. The first hypothesis — that the
runner's per-file reads cost more — is **wrong, and was tested rather than
believed**: the perf tests now print the bytes-only figure, and reading all 501
files costs **0.01 s** on that runner against 0.12–0.23 s on this Mac, the
opposite of the guess and in any case a term too small to matter on either. GC
pressure from the 501 ASTs a cold run holds is the next candidate and is not
measured here. None of it affects the fix, which is that a ratio was never the
right unit for this assertion. `NARROWING_SPEEDUP = 1.25` in the same file is the
same shape of bar for PERF-03 and is **left alone** — it passed on that runner
and measured 2.87x there and 2.46x here — but it is the same kind of proxy, and
the exact `filesAnalyzed` counts beside it are what actually catch a prefilter
that stopped filtering. Nor does this wave say anything about the **other** twelve
jobs: they were green before it and are green after it.

## Sprint 5 — hosts, wave 1 (2026-09-10)

Four LATER items, all in the two host adapters. Three of them are the same defect
seen from different sides: **the extension answered a question about one thing
while describing another** — a scope-less language-model tool answered "what does
the evaluation stage do?" with the whole workspace; `workspaceFolderFor` answered
a question about the second open folder with the first folder's code; and the
extension answered with `mlview.disabledRules` while a checked-in `.mlview.toml`
sat unread beside it. `docs/CONTRACTS.md` §11.40 and §11.41 are the
amendments.

**Several folders open, one graph each.** The controller held ONE `graph`, ONE
`index` and ONE `lastScope`, and `workspaceFolderFor` fell back to
`workspaceFolders?.[0]`, so in a window with two folders open the second was never
analyzed and nothing said so. `vscode-extension/src/folders.ts` replaces that with
a map keyed by folder; a single-folder window is the one-entry case and is
asserted unchanged. The Problems panel now publishes the **union** of every
analyzed folder (publishing one alone silently wiped the other's squiggles), a
CodeLens is answered with the graph of the folder its own file lives in, and the
diagram, the status bar and the chat / LM answers follow an **active** folder that
`MLView: Select Active Folder` and a link in the status-bar tooltip move. With two
or more folders the tooltip says which one the count describes and how many it does
not: *"Folder: ws0 — 1 other folder in this workspace is not shown here."* With one
folder it is the plain string it has always been. Eight cases in
`vscode-extension/test/multiroot.test.js` drive the real `out/extension.js` against
a two-folder mocked workspace.

**The language-model tools take the whole selector grammar.** `scope` and `depth`
join the three `inputSchema`s and reach the analyzer through the
`buildAnalyzeArgs({scopeSpec, depth})` that already existed and was reachable only
from `exportHtml`. The descriptions are the `mlview_graph` docstring's own words:
a test reads `claude-plugin/server/mlview_mcp.py`, extracts the seven shared
selector entries and asserts the manifest contains each verbatim, so Copilot agent
mode and the MCP tools cannot describe two different products again. `stages` and
`units` stay MCP-only in both directions — they are catalogue payloads, and
`--scope stages` is a `bad_selector` refusal at the CLI. A scoped answer opens by
saying it is a filtered view whose counts describe the scope; a scoped result is
never adopted as the folder's graph, and `scopeKey` gained a third argument so a
scoped tool call and the diagram's own run are two single-flight keys.

**One configuration surface, the host half.** Every analyzer spawn now passes
`--config` when the folder has a `.mlview.toml`, or a `pyproject.toml` carrying a
`[tool.mlview]` table — resolved inside `CoreClient`, so the diagram, the export,
the baseline run and the two assistants cannot disagree about which file applied.
`mlview.configPath` and `mlview.baselinePath` join the contributed settings,
making sixteen. The precedence is stated in both descriptions and in
`vscode-extension/README.md` and asserted by `test/config.test.js`: **the file
wins** for `[rules].disable` and `[paths].exclude`, and the two `mlview.*` settings
are additive filters that can hide more and can never re-enable a rule the file
disabled. A baseline is never discovered — only `mlview.baselinePath`, and only
when the file exists — because a file dropped into `.mlview/` must not quietly
empty somebody's Problems panel. `MLView: Open MLView Configuration` creates the
file with `mlview init` rather than writing a stub, and
`MLView: Create Baseline From Current Findings` runs `mlview baseline write` over
the current scope; both go through the one `spawn` seam that holds the trust gate.

**Two hooks for the Claude Code plugin.** `claude-plugin/hooks/hooks.json`
registers a `PostToolUse` matcher on `Edit|Write|NotebookEdit` and a `Stop`
variant. The plugin was entirely pull-based: when Claude edited a training file
nothing told it the edit introduced a finding. The hook exits 0 immediately unless
the path is Python under `CLAUDE_PROJECT_DIR`, re-analyzes through the same
`load_graph` cache the MCP tools read — so it *warms* what they then read for free
— diffs the issue-id set and **speaks only when the set grew**, at most 5 rows
above confidence 0.6, under a hard 3-second budget after which it exits 0 in
silence. It never blocks (exit 2 is what blocks; nothing here can produce it) and
never writes into the project: with nothing naming `MLVIEW_DATA_DIR` both the
document and the per-file parse cache are redirected out of the repository, which
was measured creating `<project>/.mlview` on the first run before
`MLVIEW_CACHE_DIR` was defaulted too. `MLVIEW_HOOK` chooses which speaks — unset
is the edit hook, `stop` is the turn summary, `both`, `off`. Thirty-two cases in
`claude-plugin/tests/test_hooks.py`, eight of them driving the real scripts with a
fake payload on stdin against a temp project holding a measured pair (0 findings →
1 high MLV101).

**Where the diff is honest about itself.** An issue id is content-addressed, so an
unchanged finding whose line moved comes back with a new id. Printing those would
be a false alarm on every edit, so a row has to be new by id **and** by
`(code, file)`; the remainder is counted — *"3 existing finding(s) moved line and
are not repeated here"* — and the cost is stated: a genuine second occurrence of
the same rule in the same file is counted rather than printed. When the run
skipped a notebook, failed to parse a file or truncated at the node cap, one line
says so, because a hook that reports "no new findings" about a run that never read
three notebooks has given a clean bill of health for code it did not see.

**A gallery nobody has to commit, and a walkthrough.**
`analyzer/tools/gen_gallery.py` renders every clean program and every rule fixture
into `docs/gallery/` on demand: **90 reports plus an index, 30 MB, 1.4 s** for 6
clean programs and 36 rules (84 fixture files), which is why the directory is in
`.gitignore`. Zero new content — each page is an existing fixture through the
pipeline a user's own code goes through. The index states that every page is a
single-file analysis, so MLV301/302/401/501 structurally cannot fire, and it flags
a `_bad.py` that reported nothing or a `_good.py` that reported its own rule; on
this build **neither flag appears**. `contributes.walkthroughs` gains five steps —
install, visualize, read a finding in Problems, `Alt+M`, `Alt+Shift+M` — each
invoking one already-contributed command, with the pages in `docs/walkthrough/`
copied into the extension by `vscode-extension/tools/sync-walkthrough.mjs` (the twin of
`sync-rule-docs.mjs`, and for the same reason: `media.markdown` resolves relative
to the extension root, so a page that lives only in the repo renders as an empty
panel once packaged).

**Measured on this branch.** `npm run check` clean; `npm test` **336 tests, 336
pass** (was 298 before this wave; +8 multi-root, +11 configuration, +6
language-model scope, +2 walkthrough manifest, the rest from concurrent waves);
`pytest claude-plugin/tests -q` **356 passed, 7 skipped** (was 305 / 5; +32 hooks).
`src/extension.ts` went past the repo's ~600-line budget and was split: the
analysis engine into `src/analysisRunner.ts` and the argv builder, exit-code table
and stderr tail out of `src/coreClient.ts` into `src/analyzeArgs.ts`, which
re-exports them so no importer moved.

## Sprint 5 — analyzer, viewer and contracts, wave 1 (2026-09-10)

Five LATER items in the analyzer and the viewer, integrated together because
three of them touch `core/pipeline.py` and `cli.py`. Amendments §11.36–§11.39 in
`docs/CONTRACTS.md` bind them; no schema field changed, `contracts/graph.sample.json`
is untouched, and `python -m mlview analyze --demo --json -` is still byte-identical
to it.

**DATAFLOW-IP, and the price of a hop.** Recall stopped at the **object
boundary**, which is where real ML code lives: MLV101 fired for an in-scope
producer and was silent for `ctor param → self.features → read in a sibling
method`, the Lightning `DataModule` shape. `ir/summaries.py` adds a fixed-point
interprocedural pass — a CONSTRUCTOR summary (ctor argument → `__init__`
parameter → `self.<attr>`), a RETURN summary (`infer_returns` at the hop depth
rather than at one level), a METHOD-ARG summary that **intersects** over every
resolved call site instead of taking the first, and a subscript PROJECTION —
behind `--dataflow {local,ip}` with `local` the shipped default. `local` is
byte-identical **by construction**, not by measurement: every new path is
reached only from `workspace.dataflow == "ip"` or from a non-empty
`ValueRef.provenance`, which is empty in `local` for every value there is.
"Never certain" is arithmetic rather than a promise: `rules/confidence.py`
emits one `cross_file` evidence weighted `0.8 ** hops`, so MLV101's 0.95 prior
becomes 0.760 (`likely`) at one hop, 0.608 (`possible`) at two and 0.486
(`speculative`) at three, and the hop chain is named in words on the finding.
Measured on the ANA-12 corpus: recall 71.8% → **78.2%** overall and 53.2% →
**63.8%** unseen, **precision 100% in both modes**, zero forbidden findings.
The first `ip` run produced a high-severity false positive — `_split_consuming`
matching a split by *name* across two functions that each have a local called
`features` — and the fix (a cross-object claim is confined to one scope,
because two uncertainties multiply) is why the mode ships at all.

**PERF-03 and the relevance prefilter are the default.** `DEFAULT_RELEVANCE` is
now `"ml"`, so `--relevance` on `analyze`, `issues`, `render` and `baseline`
defaults to the narrowed set. The roadmap's condition — the corpus green both
ways — was met in Sprint 4 and re-proved here: `tools/perf_equiv.py --baseline
<pre-flip tree> --expect-same` reports `vision_pipeline`, `vision_pipeline_clean`
and `analyzer/tests/clean` **all byte-identical**, and `tools/accuracy.py` prints
the same table before and after. On a 501-file mixed corpus the win is 2920 ms
(`--relevance all`) → 1237 ms cold → **547 ms warm**, same 148 findings. Four
gates named by §11.28 A11 were re-baselined and three more followed; none was
weakened — each now names `relevance="all"` where it always meant the wide run,
and a new sibling asserts what the *default* path reports instead.

**CACHE ships on with it.** §11.28 B7 keeps `--relevance all` from ever
consulting the sidecar, so flipping the first default turns the second on. The
honest cost is stated rather than hidden: a plain `python -m mlview analyze .`
now writes `<root>/.mlview/cache/` into the user's repository. `.mlview` is in
`ingest.discover.ALWAYS_PRUNE` and in `.gitignore`, and `MLVIEW_CACHE_DIR`
redirects it, but it is a new write on the default path.

**CFG-ONE resolves one configuration surface.** `core/config.py` is now the only
parser: `--config FILE`, else `<root>/.mlview.toml`, else `[tool.mlview]` in
`<root>/pyproject.toml` — first match wins outright, never merged, and the winner
is named in `workspace.configPath`. TOML wins for `disable` and `exclude` (a flag
may only add); CLI flags win for every `[analysis]` option and for
`min_confidence`; `include` is additive both ways; and every mistake —
unreadable, unparseable, wrong type, out of range, unknown key, unknown rule —
is one `config_warning` and never fatal. `mlview init` writes a fully-commented
`.mlview.toml` whose tail lists all 36 rules with their shipped severity,
generated from the registry rather than typed.

**VIEW-08 answers "what did my PR change?" as a document.** `mlview diff
BASE.json HEAD.json` emits a separate `mlview-diff` overlay — per-node and
per-edge `added|removed|changed|unchanged` keyed on the §0 stable ids, per-issue
`new|fixed|persisting`, and a `notes[]` block naming every reason a `removed`
status might *not* mean "deleted". A move is deliberately not a change: `loc` is
outside the comparison key, so inserting twenty blank lines produces zero changed
nodes. Over the sample pair: **+26 nodes · −16 nodes · 11 changed · 27 unchanged,
0 new findings · 15 fixed**. It does no rename detection — a renamed file is
every node removed plus every node added, because the id embeds the path.

**VIEW-04 bundles the cross-lane channel.** All cross-lane edges funnelled through
one 56 px channel staggered at `n * 7` with no bound, so the seventh member of a
lane pair was drawn *through* the first column of lane boxes. `layout/channel.ts`
now plans one trunk per lane pair, orders members by the y of their target,
gives the longest hop the outermost slot so trunks **nest rather than braid**, and
bounds every splay inside the corridor; the channel is reserved by lane **pairs**
rather than by edge count, capped at 112 px. `layout/bundles.ts` +
`render/bundles.ts` draw the common run once with a member-count badge, and a
member is transparent rather than absent — it keeps its hit stroke, its `<mpath>`
id and its `d`, so flow, tracing and the SVG export are untouched. Crossings per
edge as drawn: **3.82 → 1.96** on the 54-node demo and **44.55 → 30.47** on a
300-node synthetic. A decluttering device that hid a finding would be the one
unaffordable failure, so a bundled cable's severity marker is explicitly **not**
faded and the trunk carries the worst severity of its members.

**Measured on this branch (this Mac).** `sh scripts/e2e.sh` **20 steps, 0 failed,
0 skipped**; analyzer **1855 passed / 4 skipped**; webview **419**;
vscode-extension **336**; claude-plugin **356 passed / 7 skipped**;
`tools/verify.py --all` **10 of 10**; `tools/verify.py --scopes --fuzz 200` 4 of 4
(200 cases over 40 generated graphs, python == typescript);
`tools/accuracy.py` **precision 100.0% on 36 rules, recall 71.8% / unseen 53.2%**,
and `--dataflow ip` **78.2% / 63.8%**, both `accuracy gate: PASS`, zero forbidden
findings; `tsc --noEmit` clean in both TypeScript packages.

## Sprint 5 — hosts, wave 2 (2026-09-10)

Two LATER items and one correction, all in the two host adapters. Both items are
halves of work the analyzer shipped in the same sprint: H5's `Issue.fix` had no
button and VIEW-08's `mlview diff` had no surface. `docs/CONTRACTS.md` §11.43 is
the amendment; it amends §4, §6, §9, 11.40 C2 and 11.42 I.3, and adds no schema
field — `contracts/graph.sample.json` is untouched and an unscoped `analyze` still
emits the bytes it always emitted.

**A fix you preview, never one that is applied for you (H5, host half).**
`vscode-extension/src/fixes.ts` turns an opted-in `Issue.fix` into a `QuickFix`
code action. The module is the guardrails: `providedCodeActionKinds` is
`[QuickFix]` and never `source.fixAll` — that is the kind
`editor.codeActionsOnSave` runs unattended; `isPreferred` is derived from
`safety` and from nothing else, so `Ctrl+.`+Enter cannot land on a
`needs-review` judgement call; every `WorkspaceEdit` entry carries
`needsConfirmation` and the apply passes `isRefactoring`, so VS Code routes the
change through the refactor **preview**; and the `certain`/`likely` floor is
re-checked here even though the analyzer already enforced it, because this is the
module that does the damage if the producer is wrong. `readFix` validates the
whole shape defensively — it arrives from a child process — and one bad edit sinks
the whole fix, because half a fix is a broken file. Containment is
`codeActions.writableFile`, the guard `suppressRule` already used.

11.42 I.3 asked the host amendment to say what it does about **stale
coordinates**. The document carries no content hash, so the host cannot prove the
source is unchanged; it proves the two ways it is certainly wrong, before the
preview rather than after the write — the buffer has unsaved changes (the analysis
read the file on disk), or the edit's end line is past the end of the buffer. Both
are refusals naming the file. A file edited, saved and left the same length still
passes, and §11.43 I.1 says so rather than implying more.

The viewer reaches the same code path with `applyFix`, the fourteenth `UiToHost`
message, which carries the **issue id and nothing else**: the edits are read from
the host's own copy of the graph, so a webview can never dictate a range or a
replacement string.

**Comparing two analyses in the editor (VIEW-08, host half).** Three commands in
`vscode-extension/src/compare.ts`: `Save Current Graph As Comparison Base` writes
the analysis you are looking at to `.mlview/comparison-base.json` **verbatim**,
with no second analysis — a diff whose two sides came from two different runs is
the mistake §11.38 D orders the summary to make visible; `Compare With Saved Base`
re-analyzes, runs `mlview diff base head --json -` through the same `CoreClient`
seam every analysis uses, and posts `diffOverlay`, the fifteenth `HostToUi`
message; `Compare With Clean Sample` does the same with `samples/vision_pipeline_clean`
as the base. The overlay is an optional **sibling** of the graph and is typed only
as far as the host reads it, so the viewer owns the rendering and the host owns
the transport.

Two honesty rules travel with it. Every entry of the overlay's `notes[]` goes to
the output channel verbatim and the toast says how many there are — *"−16 nodes"*
is a claim about two documents, not about the code, and §11.38 C is the list of
innocent reasons an id can be missing. And a comparison **dies with the document
it described**: `postGraph` clears any outstanding overlay, because a stale
*"0 new findings"* drawn over a freshly analyzed diagram is a confident wrong
answer.

**The plugin: a `diff` scope, not a sixth tool.** `mlview_graph {scope: "diff",
base: "<earlier analyze --json document>"}` returns `{content, summary{headline,
nodes, edges, issues}, note, basePath}` — a diff is another projection of the same
graph, which is the argument §11.1 already makes for `stage:` and `unit:`.
`claude-plugin/server/mlview_diff.py` is the boundary; the comparison is
`mlview.core.diff`'s. A `base` that is not an MLView graph — a diff overlay
included — is an **error naming the file**, never an empty comparison, because
*"0 changes"* is the most dangerous wrong answer this projection can give. Its
caveats ride the payload's protected `note` key, so the 4 KB budget sheds rows and
never the sentence that a rename reads as everything removed plus everything
added. `/mlview-issues` documents `--diff-base <file>`, and its `Bash` fallback is
three runnable lines because `tests/test_command_arguments.py` executes every
documented fallback.

**CFG-ONE, the clause asserted on the wrong pair.** 11.40 C2 says *"`mlview.disabledRules`
and `mlview.exclude` are additive filters on top … Both settings' `markdownDescription`
say this in those words"*. The wave-1 test asserted it on `mlview.configPath` and
`mlview.baselinePath` instead, so the two rows a user actually reads while typing a
rule code said nothing about precedence at all. Both now carry the claim — additive,
the file wins, *"cannot re-enable a rule the file disabled"* / *"cannot re-include a
path the file excluded"* — each naming the table it loses to, and `test/config.test.js`
asserts it in both directions. No setting was added; the contributed set is still 16.

**Measured on this branch.** `npm run check` clean; `npm test` **371 tests, 371
pass** (was 336 after wave 1; +19 `fixes.test.js`, +15 `compare.test.js`, +1
`config.test.js`). `pytest claude-plugin/tests -q` **365 passed, 7 skipped, 1
failed** at the time this half was measured — the failure was
`test_sync_core_check_is_green_after_this_suite_imported_the_vendored_core`, red
because the concurrent analyzer wave had added `ir/config_shapes.py` and
`ir/config_values.py` that `tools/sync-core.py` had not yet vendored; nothing in
this half touches `claude-plugin/vendor`, and one `tools/sync-core.py` at the end
of the wave closed it (**366 passed / 7 skipped** integrated). `src/panel.ts` and `src/extension.ts`
reached the ~600-line budget and were split with no behaviour change:
`src/panelOpen.ts` takes `openLocation` and `rangeFromLoc`, `src/visualizeCommands.ts`
takes the three "show me the diagram" commands.

## Sprint 5 — analyzer, viewer and integration, wave 2 (2026-09-10)

Three LATER items in one wave, and they share a property that is the reason the
three amendments were written together: **each of them ships a field that may
not be there.** `Issue.fix` exists only on the five rules that opted in, the
`mlview-diff` overlay is a separate document a host may never send, and ANA-10's
resolved value is a literal a container may never yield. A reader that renders
any of them badly when they are absent breaks every document that predates them,
so the first rule in each half is what happens when the field is missing.
`docs/CONTRACTS.md` §11.42 (analyzer fixes), §11.43 (hosts), §11.44 (renderer)
and §11.45 (config resolution) are the amendments; **no schema field became
required, `contracts/graph.sample.json` is untouched, and `analyze --demo` is
byte-identical to it at 46 078 bytes.**

**H5 — a fix computed from the AST, offered, and never applied.** The lead
lifted `REQUIREMENTS.md` §5 non-goal 5 with its five guardrails, and every one of
them is enforced in code rather than by convention.
`analyzer/src/mlview/rules/fixes.py` is the only module in MLView that
constructs a `TextEdit`; 31 of the 36 rules are byte-identical, and a test fails
if any rule outside `FIX_CODES` passes `fix=`. Every position comes from an `ast`
node — indentation for an inserted statement is the target statement's own
`col_offset`, so `MLV201_nested_loop_bad.py` indents to column 20 and
`MLV301_with_block_bad.py` inserts *inside* a `with torch.no_grad():` block —
and there is no substring search anywhere in the module. `GraphContext.issue`
attaches a fix only when the bucket the user is shown is `certain` or `likely`,
asserted from both sides by one rule: the new unseeded MLV602 fixture is
`certain` and gets an edit, while `fixtures/rules/MLV602_bad.py` seeds globally,
lands `possible`, and gets none. `mechanical` means one keyword at one call site
(MLV111, MLV602); anything that inserts a statement into a training loop is
`needs-review` (MLV201, MLV301, MLV302), because gradient accumulation is a
deliberately missing `zero_grad()`. Nothing in the analyzer writes to a file.

The acceptance is structural rather than pinned by examples: `build_fix` applies
every candidate to a copy of the module source *in memory* and runs `ast.parse`
over the result, discarding a candidate that does not parse — and
`analyzer/tests/rules/test_fixes.py`'s five parametrized
`test_fix_makes_the_rule_stop_firing` cases apply the edits, re-analyse the
fixture as a workspace, and assert the rule stops firing **and** that the code
set gains nothing new. 44 tests. The demo publishes five fixes (MLV201
`train.py:30`, MLV301 `train.py:44`, MLV302 `train.py:41`, MLV111 `data.py:35`,
MLV602 `sklearn_baseline.py:27`) and the clean twin still yields 0 issues and
0 fixes.

**ANA-10 — configuration resolved in Python, and the deferred half said out
loud.** `analyzer/src/mlview/ir/config_shapes.py`, `ir/config_values.py` and
`ir/config_calls.py` resolve four shapes and nothing else, at the end of
`bind_module`: module-level dict literals, `dataclass` field defaults (nested
through `field(default_factory=…)`), `argparse add_argument(default=)` keyed by
`dest`, and the attribute/subscript chains rooted at any of them.
`cfg.data.workers` and `CFG["workers"]` are **one dotted path**, because that is
what a `DictConfig`, a `SimpleNamespace` and a dataclass all make them. No rule
changed: each scalar leaf becomes an ordinary `ValueRef` carrying `literal`, so
`rules/helpers.literal_of` picks it up, and `CallSite.kwargs` is filled from the
container for keys the call site did not write, with the call site always
winning. `core/config_nodes.py` maps every alias of a container onto the one node
it already has, so `config`-kind edges now run from `CFG` into each consuming
unit across files, and a `getattr` registry draws a selection node in both
branches — `selects torch.optim.AdamW` when the string resolved, `one of 2 in
factories · Alpha, Beta` at confidence 1/N when it did not — inventing an FQN in
neither.

The de-rating the roadmap demanded is one visible evidence factor, not a hidden
constant: `CONFIG_EVIDENCE_WEIGHT = 0.8`, once for the read and once more per
hop, so the highest registered prior lands at 0.98 × 0.8 = **0.784** and a config
read can never mint a `certain` finding. Travel is import (free), declared
default and argument→parameter (one hop each), capped at two, and **intersection,
never union**: a parameter takes a container only when every recorded call site
agrees. The probe ladder reads `num_workers=4` certain 0.98, `WORKERS` certain
0.98, `CFG["workers"]` **likely 0.784**, `cfg.data.workers` **likely 0.784**, one
hop possible 0.627. The false statement the roadmap named is gone:
`DataLoader(ds, shuffle=CFG["shuffle"])` with `CFG["shuffle"] = True` no longer
reports *"shuffle=unset (defaults to False)"*.

**VIEW-08 — the diff a reader can see, in the viewer and in both hosts.**
`webview/src/diff/overlay.ts` accepts a §11.38 overlay from three routes (the
`diffOverlay` message, `window.MLViewDiff`, and a
`<script type="application/json" id="mlview-diff">` block read at mount) and
anything that is not a v1 `mlview-diff` degrades to no overlay, so a document
that predates the feature draws byte-for-byte what it always drew. The
acceptance's second clause is met the way it was written:
`webview/src/diff/changed.ts` **reuses the scope projection** — `projectResolved()`
was extracted out of `scope/project.ts`, so "changed only" is core = every
non-`unchanged` node and boundary = one hop, boundary stubs stay badge-free,
`nodeIds[0]` stays rotated onto a core node, and the rail still reports the
findings outside the view. In VS Code, `vscode-extension/src/compare.ts` adds
`Save Current Graph As Comparison Base`, `Compare With Saved Base` and
`Compare With Clean Sample`; the host **computes nothing** — it writes the
analysed document verbatim, stages the head in its own `globalStorageUri` and
shells out to `python -X utf8 -m mlview diff` — and `mlview_graph(scope="diff",
base=…)` gives the plugin the same answer without a sixth tool. One latent bug
was repaired in passing: `App.applyProjection` reused `this.fullIndex` whenever
`scopes.spec === null`, which was correct while a scope was the only way to
narrow a document and drew every node a diff projection had just removed.

**CFG-ONE — one clause, asserted on the wrong pair of settings.** §11.40 C2
requires `mlview.disabledRules` and `mlview.exclude` to state the precedence *in
those words*; the wave-1 test asserted it on `mlview.configPath` and
`mlview.baselinePath`, so the two rows a user reads while typing a rule code said
nothing about precedence at all. Both now carry the claim — additive, the file
wins, *"cannot re-enable a rule the file disabled"* / *"cannot re-include a path
the file excluded"* — each naming the table it loses to, and
`vscode-extension/test/config.test.js` asserts it in both directions. No setting
was added; the contributed set is still 16.

**The accuracy re-baseline, and who earned it.** `analyzer/tests/accuracy/baseline.json`
and its `--dataflow ip` twin were re-recorded once for the whole wave rather than
once per agent, and the move belongs entirely to ANA-10. Measured A/B on this
tree with `ir.bindings._resolve_config` stubbed to a no-op: overall recall
**71.8% → 73.1%**, visible 64.1% → 65.4%, high+medium 63.2% → 64.9%, unseen
**53.2% → 55.3%**, graph fidelity **126 → 127 of 139**; in `ip`, 78.2% → **79.5%**
and unseen 63.8% → **66.0%**. Precision stays **100.0%** and forbidden findings
stay **0** in both modes. The single new finding is a planted defect — MLV201 at
`hydra_research/src/train.py:35`, *"gradients are never zeroed"*, reachable only
because the `getattr` selection makes `optimizer_for(...)` resolve to an
optimizer — and `hydra_research`'s graph fidelity moves 75.0% → 81.2% with it.
H5 is finding-neutral by construction and moved nothing: measured with and
without the field on the same tree, `tools/accuracy.py` is identical to the
character, so §11.42 C4's figures were corrected at integration to say that
rather than to quote a number ANA-10 had since moved. **No fixture was
regenerated.** `analyze --demo --format json` is still byte-identical to
`contracts/graph.sample.json`, and `samples/vision_pipeline` still analyses to
54 nodes / 51 edges / 15 issues — ANA-10 moved graphs in the accuracy corpus
(`hydra_research` 47 nodes / 44 edges / 0 config edges → 49 / 49 / 3) and in
nothing that is checked in as a golden.

**Gates, all re-run on this Mac at the integrated tree.** `sh scripts/e2e.sh`
**20 steps, 0 failed, 0 skipped**; analyzer **1929 passed / 4 skipped** (1722 / 3
at the sprint baseline); webview **473 tests** (384); vscode-extension **371
tests** (298); claude-plugin **366 passed / 7 skipped** (305 / 5);
`npx tsc --noEmit` clean in both TypeScript packages; `python tools/verify.py --all`
**10 of 10**, including `parity: CLI vs MCP — 54 nodes, 51 edges, byte-identical`
and both vendored-core gates after one `tools/sync-assets.py` +
`tools/sync-core.py` at the end of the wave;
`python tools/verify.py --scopes --fuzz 200` **4 of 4** (200 cases over 40
generated graphs, 6–370 nodes, python == typescript);
`python tools/accuracy.py` **PASS** — precision **100.0%** on 36 rules, recall
**73.1%** / 65.4% visible / 64.9% high+medium over 15 programs and 78 labels,
unseen 55.3% / 42.5% / 37.5%, graph fidelity **91.4%** (127 of 139), zero
forbidden findings — and `--dataflow ip` **PASS** at 79.5% / 66.0% unseen against
its own ratchet; `pytest analyzer/tests/core/test_perf_budget.py` **6 passed**
(PREFILTER 501 files 2.81 s → 51 files 1.69 s, 1.66×; CACHE cold 1.56 s → warm
0.63 s, 2.48×); `python scripts/check_docs.py` **DOC CHECK OK** (19 files). **CI (run 34435948295): all 12 branch jobs green**, 7m57s wall — `smoke (macos)` is skipped on a branch push by design. It took two fix iterations and neither defect was reachable from this Mac: `e2e (windows, powershell)` alone caught `compare.test.js` asserting `baseLabel` with `path.join`, the host separator, where §0 requires a workspace-relative path to be forward-slashed (the source was right and the test was wrong); and `analyzer (py3.12)` alone caught `test_two_ip_runs_are_byte_identical`'s `_stable()` popping `generatedAt` at the top level of the document instead of at `generator.generatedAt`, which left the timestamp in the compared string and made the assertion a coin flip on the second boundary — it lost by one character. Eight sibling helpers in the same suite already spelled it correctly.

**Two integration edits outside any agent's ownership, both recorded here.**
`docs/STATUS.md`'s known-gap bullet about the editor's comparison cited nothing a
gate could check and has been rewritten around `compareWithSavedBase` in
`vscode-extension/src/compare.ts`, which is the honest residue of it — the
viewer half it described as missing landed in this same wave. And §11.42 C4's
accuracy figures were corrected as described above. Nothing else in any
component was edited at integration.


## Sprint 5 — contracts, wave 3 (2026-09-10)

**HEALTH-02 grows two shapes: the fuzzer now generates rolled-up and
multi-pipeline documents.** PERF-04 and MLV-P12 are the two items the Sprint-4
fuzzer explicitly could not cover — its own measurement note said "the generator
never produces a document above `--max-nodes`, so PERF-04 will need capped
documents". `analyzer/tools/scope_gen_projections.py` is that generator half:
non-ghost ops folded into their unit and whole files folded into a synthesized
summary node with a transitive `rolledUp` count, edges re-pointed and parallels
merged into a `weight`, edges internal to a fold absorbed, `stats.truncated` with
the `truncated` diagnostic §11.46 D requires; and the root `pipelines[]` block
over the reach of each entrypoint under `data`/`call` edges plus containment,
emitted only for two or more non-empty pipelines. A fifth of every document's
selectors are now `pipeline:` ones — a real entrypoint, its basename, the
case-folded and backslashed spellings, a miss and the empty term — emitted
*whether or not* the grammar has landed, because two ports that disagree about
whether `pipeline:` parses at all is exactly the §11.16 drift the fuzzer is for.

**It found two real divergences on its first runs, and both are closed.** The first was a
`view.scope` disagreement on `pipeline:MAIN.PY` and `pipeline:mod1.py` — six of
200 cases on seed 20260910, in three spellings the fixture battery does not
contain (case-folded, bare basename, backslashed). The two ports have since
converged on echoing the spec as typed, and the amendment appended at
integration says the same thing: §11.47 B pins `view.scope` to the **selector as
normalized by 11.1**, not to the canonical entrypoint, "exactly what `file:` does
today, and for the same reason". So `pipeline:TRAIN.PY` and `pipeline:train.py`
differ by that one string plus the case-fold `config_warning` that names the
canonical spelling, and that is the contracted answer rather than a residue. The
draft the fuzzer was written against said the reverse; a human read the section
before it landed, which is the only way that class of disagreement is ever
found — two ports that agree with each other and not with the prose are
invisible to differential fuzzing by construction.

The second was caught, and fixed inside the wave, by a new gate row —
**`scopes: pipelines relation`**. §11.47 A is a second algorithm written twice,
and a projection carries the `pipelines[]` block through *verbatim* (11.47 D), so
a port that computes the relation differently never shows up in a projection
comparison. The fuzzer therefore compares the relation itself:
`mlview.core.pipelines.pipelines_block` against `webview/src/scope/pipelines.ts`'s
`rows()`, on every generated document. They disagreed on **17 of 40 graphs** at
`--fuzz 200`: Python counted `sharedCount = len(index.context_of(E))`, which does
not count a node `E` itself owns even when another entrypoint reaches it, while
TypeScript counted every node another entrypoint reaches. On one 16-node
document Python said `main.py` was `nodeCount 7, exclusive 4, shared 3` and
TypeScript said `exclusive 0, shared 7` — both on screen at once, since the
report embeds the document's block and the chooser recomputes its own row. The
viewer moved to the Python count, so the row's split now matches what the
`pipeline:` projection actually draws as context — and the amendment that landed
states the rule the ports implement: §11.47 A3.1 says a node another entrypoint
also reaches is shared for `E` **unless it is one of `E`'s own seeds**, "which
are never taken away from the entrypoint they live in", and §11.47 D pins the
three numbers a user sees as one number (`exclusiveCount` == `|core(E)|` ==
`view.counts.core` at depth 0 == the `--list-scopes` SUBTREE column). Both
questions this section raised against the draft are therefore settled in the
appended text, not left open.

**Every shape is schema-probed, never assumed.** `contracts/graph.schema.json` is
`additionalProperties: false` at every level, so the generator reads the schema,
produces only what it declares, and the gate row says what it could not produce:
on a checkout without the two amendments the row reads `NOT GENERATED: the schema
declares no root pipelines[]` rather than passing quietly. The same rule covers a
*required member* the generator cannot compute — it names the member and skips
the shape rather than inventing a value the fuzz run would then assert against.

**Proved to bite.** Three scratch bundles, one line each: one that drops the
`pipelines` block from the projected document, one that stops `core_of` excluding
the shared nodes (`return this.reach(e)` — the heart of §11.47 C), and one that
adds `pipeline` to the port's `SCOPE_KINDS` while the analyzer has not. Five
seeds each, 40 cases each, **caught every time**, always inside the first or
second generated graph. Two of them were **promoted**, which is what
makes the proof permanent: `contracts/scope.cases.json`'s `fuzzCases` grows from
three to five, and the two new ones are the first that carry a `pipelines[]`
block at all. `fuzz_22_g0001_c04` (`pipeline:mod2.py`, **2 nodes**) pins §11.47
C — the shared node is `context`, not `core` — and `fuzz_33_g0000_c01`
(`stage:objective`, **2 nodes**) pins §11.47 D's "carried through verbatim".
Replayed with no Python in the loop they are green against the shipped bundle and
red against the one-line bundles they were found on. Their expectations travel
with them: the promoted rows carry `expectExtras`, because
`gen_scope_fixtures.py` regenerates promoted answers with the **shared** digest,
which does not know about the new fields.

**What it could not do.** The compared digest still excludes `diagnostics`
(§11.1 leaves that prose free), so §11.47 C1's scope diagnostic and §11.46 D's
rollup wording are checked by neither port comparison — only their *presence* is,
and only by `analyzer/tests/core/test_fuzz_shapes.py` on the generated side.
The relation row compares the four members both ports
compute — entrypoint, `nodeCount`, `exclusiveCount`, `sharedCount` and
`issueCounts` — and **not** `label`, because the viewer's chooser row derives its
own name; a divergence in that name would pass. A deviation both ports share, as
the `view.scope` one now is, is invisible to a differential fuzzer by
construction: nothing here reads `docs/CONTRACTS.md`.
`rolledUp`, `weight` and `pipelines` are compared through an `_extras` block this
driver adds itself, because `digest_of` in `gen_scope_fixtures.py` does not carry
them; a **promoted** counterexample replays without that block unless its case row
carries `expectExtras`, since the promoted expectations are regenerated by that
shared digest. The generator produces the contracted *shape*, not the analyzer's
*choices*: it does not reproduce §11.46 A1's fold ordering or phase 3 (drop), and
it never generates a document whose budget is smaller than its file count. Its
`pipelines[]` block is `pipelines_block`'s own output rather than a second
implementation — deliberately, so no generated document is one the analyzer could
not emit, but it does mean a bug **inside** `pipelines_block` would be generated
faithfully into every fuzz document and only caught by the relation row, which
compares it against the port. The one host that still described the
grammar without `pipeline:` — the three `vscode-extension/package.json`
tool-input descriptions, which the model actually reads, unlike the TypeScript
comment beside them — was closed at integration, and a new
`manifest.test.js` case now reads `SCOPE_KINDS` out of the vendored
`core/selectors.py` and asserts every kind in it is named in all three
descriptions, so the next addition to the grammar cannot land in one file and
not the other.


## Sprint 5 — analyzer, viewer and integration, wave 3 (2026-09-10)

Two LATER items, and they answer the same complaint from opposite ends: **a big
repo renders as one unreadable graph.** PERF-04 makes `--max-nodes` a zoom level
instead of a guillotine; MLV-P12 says the workspace was never one graph in the
first place. `docs/CONTRACTS.md` §11.46 (rollup) and §11.47 (pipelines) are the
amendments — appended at integration under those numbers, not the 11.44/11.45
their briefs assigned, because the tree they landed on already carried a §11.44
and a §11.45 from wave 2. **Three optional schema fields, no `required` array
moved, `schemaVersion` still `1.0`, `contracts/graph.sample.json` untouched, and
`analyze --demo --format json` byte-identical to it at 46 078 bytes.**

**PERF-04 — the cap folds, it does not delete.** `core/rollup.py`'s
`apply_node_budget` replaces `pipeline._apply_node_cap` at the same point in the
pipeline, still before projection (11.2.2), and it **returns before mutating
anything** when the document is within budget — so an uncapped document cannot
change, which `tools/perf_equiv.py --expect-same` proves rather than asserts:
`vision_pipeline`, `vision_pipeline_clean` and `tests_clean` all read `identical`
against a baseline still holding the deletion cap, exit 0. Above budget three
phases run in order — a unit absorbs its non-ghost ops, then a whole file folds
into a synthesized `stage`-level summary, then (a **stated deviation** from the
roadmap entry, §11.46 A3b) a whole directory does — and only then the old
deletion order, as a last resort. Edges are re-pointed at the surviving ancestor,
self-loops absorbed rather than dropped, parallels merged into one carrying
`Edge.weight`. The measured result on `samples/vision_pipeline` at four budgets:
**54/51, 38/40, 12/18 and 7/4** nodes/edges at `--max-nodes` 400 / 40 / 20 / 8,
`contracts/validate_sample.py` green on all four, and **15 issues — 5 high / 6
medium / 4 low — in every one of them.** The diagnostic at cap 20 reads *"Graph
cap (--max-nodes budget) 20 reached: 42 node(s) rolled up into their surviving
ancestor (7 unit(s) absorbed their operations, 0 file(s) and 0 director(ies)
summarised), 0 node(s) dropped, 12 node(s) kept. 3 parallel edge(s) merged into
one carrying a weight, 30 absorbed into a rolled-up node, 0 lost an endpoint."*

**The roadmap's two numeric targets were redefined out loud rather than
quietly.** "Isolated nodes under 5%" is asserted as **zero floating cards**
(`test_the_rollup_leaves_no_floating_card`) plus *every edgeless survivor is a
ghost* — because a ghost has no edges by construction and is drawn inside its
parent, so raw degree-0 is 56% of a 45-card document and measures the finding
rather than the cap. "Edge retention over 40%" is asserted at the roadmap's own
budget (`test_edge_retention_at_the_roadmap_budget`, 47.3% at cap 400) and is
**replaced at every other budget by the stronger `report.edges_lost == 0`**,
because a fold *absorbs* an intra-group edge rather than losing it and the ratio
therefore falls as the budget tightens. On the 525-file synthetic the two caps
measured side by side: at `--max-nodes 100` the deletion drew 25 edges (1.1%),
**50 floating cards** and silenced 26 of 126 findings; the rollup draws 155
(6.8%), **zero** floating cards and **all 126 findings**.

**MLV-P12 — a pipeline is another projection, not a new mode.**
`core/pipelines.py` computes the relation from a finished document and nothing
else: seeds are one entrypoint's nodes, adjacency is `data` + `call` edges both
ways plus containment, and `config` and `control` edges are **deliberately cut**
— a shared `config.py` is precisely what would merge ten training scripts into
one component. The clause the item lives on is that the closure **includes but
does not expand through** another entrypoint's own nodes; without it an
undirected closure is the whole connected component whichever seed it starts
from, ten scripts sharing a `utils.py` are one pipeline, and MLV-P12 answers
nothing. `pipeline:<entrypoint>` joins the 11.1 grammar in both ports, in
`--list-scopes` (`3 pipeline(s) + 10 scopable unit(s)` on the demo, the pipeline
rows leading), in the MCP `mlview_graph` docstring and in the VS Code LM tools.
In a `pipeline:` view the exclusive reach is `core` and every shared node is
forced to `viewRole: context` and **never** `boundary`, so a finding anchored
only on a shared node is reported as outside the view — which is right: it is not
this pipeline's. The root `pipelines[]` block is emitted **only at two or more
non-empty pipelines**, so a single-entrypoint workspace — the golden included —
is byte-identical to before.

**The gate that caught the bug is the one worth keeping.** HEALTH-02's fuzzer
grew a fifth row, `scopes: pipelines relation`, because §11.47 A is one algorithm
written twice and §11.47 D carries the block through a projection *verbatim*, so
a port that computes it differently never shows up in a projection comparison.
It disagreed on **17 of 40 graphs** within an hour of existing — Python
`exclusiveCount 4` where TypeScript said `0` on one 16-node document, both
numbers on screen at once because the report embeds the block while the chooser
recomputes its own row. The fix was the normative reading now pinned in §11.47 D
and in `test_the_three_numbers_a_user_sees_are_one_number`: `exclusiveCount` ==
`|core(E)|` == `view.counts.core` at depth 0 == the `--list-scopes` SUBTREE
column. Two counterexamples were promoted, taking the frozen `fuzzCases` from
three to five and giving the battery its first documents that carry a
`pipelines[]` block at all.

**Gates, all re-run on this Mac at the integrated tree.** `sh scripts/e2e.sh`
**20 steps, 0 failed, 0 skipped**; analyzer **2024 passed / 4 skipped** (1929 / 4
at wave 2, 1722 / 3 at the sprint baseline); webview **521 tests** (473);
vscode-extension **372 tests**; claude-plugin **370 passed / 7 skipped** (366 /
7); `scripts` gates **56 passed**; `npx tsc --noEmit` clean in both TypeScript
packages; `python tools/verify.py --all` **10 of 10**, including `parity: CLI vs
MCP — 54 nodes, 51 edges, byte-identical` and both vendored-core gates after
`tools/sync-assets.py` + `tools/sync-core.py`;
`python tools/verify.py --scopes --fuzz 200` **5 of 5** (13 projections + 7 error
cases, 5 promoted counterexamples, 200 fuzz cases over 40 generated graphs of
1–339 nodes with **11 rolled up and 17 carrying pipelines**, and the relation
row); `python tools/accuracy.py` **PASS** — precision **100.0%** on 36 rules,
recall **73.1%** / 65.4% visible / 64.9% high+medium, unseen 55.3% / 42.5% /
37.5%, graph fidelity **91.4%** (127 of 139), zero forbidden findings —
**unchanged from wave 2 in every digit, which is the point: neither item is
allowed to move a finding**; `python contracts/validate_sample.py` green at four
budgets; `python scripts/check_docs.py` **DOC CHECK OK** (19 files). **CI (run
34441571480): all 12 branch jobs green on the first push, no fix iteration** —
8m09s wall, ~46 billable minutes, `e2e (windows, powershell)` 8m07s and
`e2e (ubuntu, sh)` 6m32s; `smoke (macos)` is skipped on a branch push by design.

**Two integration edits outside any agent's ownership, both recorded here.** The
three `vscode-extension/package.json` LM-tool `scope` descriptions still
described the 11.1 grammar without `pipeline:` — the description the model
actually reads, unlike the `src/lmTools.ts` comment beside it — so the sentence
was added to all three, and a new `manifest.test.js` case reads `SCOPE_KINDS` out
of the vendored `core/selectors.py` and asserts every kind in it appears in each
description, so the next addition cannot land in one file and not the other. And
the wave-3 contracts entry above raised two questions against the *draft*
amendments (whether `view.scope` reports the canonical entrypoint, and whether
"shared" has an owner rule); the text that landed settles both — §11.47 B pins
the selector as normalized by 11.1, §11.47 A3.1 states the owner rule — so those
paragraphs were rewritten to say what the contract says rather than to leave an
open question pointing at an unappended file.


## Sprint 5 review round — the doc gate learns to check the figures the docs requote (2026-09-10)

**Four minor findings, all in the process documents, each fixed at the mechanism
rather than at the sentence (REV5-05, REV5-06, REV5-07, REV5-08).** The
Components table at the top of this file was refreshed in wave 1 and left behind
by waves 2 and 3, so all four of its test counts were contradicted 1900 lines
lower by this file's own wave-3 gate paragraph, and its `core/mlview` figure said
**88** where `python tools/verify.py --all` printed **96**. `README.md` had
called `contracts/scope.cases.json` "the ten-selector battery" for three sprints
while the file grew to **13** projecting cases, **7** error cases and **5**
promoted counterexamples — and `scripts/README.md` carried the same "ten
selectors plus six error codes". Both were true at the time they were written,
which is the only way a figure like that survives review. `README.md` and `scripts/README.md` row 25 named
two *different* runs as "the last full green push" in the same commit, and the
paragraph that cited the older one still reasoned about the 20 macOS minutes a
rewrite in the same paragraph had already replaced with 30.

**The prose was corrected against a measurement, not against memory.** The four
Components rows read **2024 passed / 4 skipped**, **521**, **372** and
**370 passed / 7 skipped** at the time — the integration pass below re-ran every
suite over the fixes and moved all four again — and the VSIX row **744.45 KB, 148 files, 96 under
`core/mlview`** — from `npm run package` + `python scripts/vsix_check.py` run on
this tree, not retyped. The wave-3 gate paragraph's `vscode-extension **371
tests**` was a transcription error at that same tree (every other figure in it
reproduces exactly) and reads **372**; nothing else in that dated paragraph was
touched, so `scripts` gates still records the **56** wave 3 measured, against
**74** here — this round added 18 cases. `README.md`'s CI paragraph named run
**34441571480** for "the last full green push" at the time, the same run
`scripts/README.md` row 25 named, and keeps the 13-job run (34422156964) as what
it actually is: the one push on which `smoke (macos)` has ever run. (Both now name
the integration push below; the check is that they name **one** id, not that
the id never moves.)

**Three new doc-gate checks, in `scripts/doc_figures.py` (74 self-test cases,
was 56).** Check **13** holds this file's Components table to the **last**
`**Gates` paragraph of this same file — the two figures live in one document, so
the document may settle them — and its bundled-core count to the files
`tools/sync-core.py` actually copies out of `analyzer/src/mlview`. Check **14**
reads `contracts/scope.cases.json` and holds every `N selectors` /
`N projections` / `N error cases` / `N promoted counterexamples` claim in a block
naming that file to it, spelled-out numbers included, because "the ten-selector
battery" — accurate at the time, and a sentence no digit ever appeared in — is
how this one hid. Check **15** requires every run id quoted beside
"the last full green push" to be one id.

**What these checks cannot see.** They are held to the three *living* documents
(`README.md`, `docs/STATUS.md`, `scripts/README.md`) only: a `docs/CONTRACTS.md`
amendment, a `**Landed` note or a frozen design record is a dated record, and
check 8's `at the time` escape releases a narrating block in the living three as
well — `docs/REQUIREMENTS.md` R1.12 still says "all 10 cases" and is left alone
by design. Check 13 compares the *table* with the *paragraph*: if both are stale
in the same way it is silent, and only re-running the suites finds that (the
real-repo case in `scripts/test_doc_figures.py` at least fails when a future wave
records its figures without naming the four packages, which would switch the
check off without failing anything). Check 14 counts only six nouns, so a bare
`N cases` — the shape `--fuzz 200` sentences use — is never a claim about the
battery. And none of the three can tell a wrong number from a number that was
right when it was written: they can only tell one that a file in this tree
contradicts today.

## Sprint 5 — review fixes, integrated (2026-09-10)

**Nineteen confirmed findings, each fixed at its source; no component was
rewritten and no assertion was weakened.** Eleven were the analyzer's, five the
viewer's, two the hosts', one the generated documentation's. **No agent wrote a
contract amendment this round**, so `docs/CONTRACTS.md` still ends at §11.47 and
there was nothing for the integrator to append; the four copies of
`graph.schema.json` (`analyzer/src/mlview/schema/`, `contracts/`,
`claude-plugin/vendor/mlview/schema/`, `vscode-extension/core/mlview/schema/`)
are byte-identical at `404bc97ba02399b4`, `contracts/graph.sample.json` did not
move, and `python -m mlview analyze --demo --json -` is still byte-identical to
it at **54 nodes and 51 edges**. **No fixture was regenerated**, because no fix
moved a graph: `gen_scope_fixtures.py --check`, `gen_expected_issues.py --check`
and `gen_rule_docs.py --check` are all current, and `tools/sync-assets.py` and
`tools/sync-core.py` reported `0 copied` — every agent had already vendored.

**Five high-severity false positives, which is the one failure the product
cannot afford.** **REV5-01** — `MLV101` matched a `train_test_split` in *any*
function of a module against a `fit_transform` in any other, purely because two
locals shared the name `features`, and published it `high` / `certain` with
prose that contradicted itself ("fitted at line 15, before the split at line
8"). The scope guard `rules/r_leakage.py` had gained in wave 1 was applied only
when the value arrived interprocedurally, so it never fired in the **shipped
default mode**; it now holds in both, and a genuine cross-scope claim has to
come back through DATAFLOW-IP's provenance chain where `hops()` de-rates it
below `certain`. **ANA-01** — a `reshuffle_each_iteration=` the analyzer could
not read took the *absent* branch, so `MLV121` printed, at `high` / `certain`,
an evidence line reading "shuffle() does not pass
reshuffle_each_iteration=False" about the very line it points at. **ANA-03** —
`MLV110` never resolved the `shuffle=` **expression**, only the folded constant,
so it said "shuffle= unset (defaults to False)" above a snippet reading
`shuffle=config.shuffle` — including when ANA-10 already held the literal
`True`. Both now keep three states apart (absent / resolved / present but
unreadable), and the third is de-rated by `UNRESOLVED_KWARG_WEIGHT` and
disclosed through `note_unresolved_kwarg` rather than being read as absence.
**ANA-02** — a `CFG["workers"] = 0` written below the dict literal did not
invalidate the leaf ANA-10 had materialised from it, so `MLV112` was minted from
a value the program never holds; `ir/config_values._apply_stores` now folds every
later unconditional write back into its root's tree. **ANA-04** — the argparse
root required the assignment's own call to *be* `parse_args`, so the ubiquitous
`args = get_args()` wrapper resolved to nothing and `MLV110` fired on correct
code; the root is now the module whose `add_argument(default=…)` calls define
the namespace, one call away.

**Six places where the tool asserted more than it knew, in both directions.**
Telling a reader the tool was blind where it was not is the same failure as
telling them it looked where it did not, and this round had one of each.
**VIEW-R1** — after `--max-nodes` folded a stage's nodes onto a summary card
whose stage is a majority vote, `emit/answers.py` and `--format summary` stated
"No loss function was detected" and "No data entry was detected" about
`samples/vision_pipeline`, a program with a `CrossEntropyLoss` and two loaders
in it: a regression against `main`. `stages[].present` is now recomputed against
a census taken **before** the fold (`Graph.stagesBeforeRollup`), the three
`answers` cards refuse to answer off a rolled-up document and say why, and the
summary marks a folded stage instead of printing `0 nodes` beside `[i]25`.
**REV5-02** — `Diagnostic.count` added `len(summaries)`, counting summaries the
directory tier had itself re-folded, so the viewer's `dropped = count - folded`
drew a banner claiming deletions the analyzer's own sentence two lines below it
denied. The counters are now a **partition of the input document** —
`folded + dropped + kept_originals == total`, §11.46 D — computed off the
finished plan in the new `analyzer/src/mlview/core/rollup_report.py` (81 lines,
split out rather than grown into `core/rollup.py`). **IP-02** — on the
fit-in-method / split-in-caller leak, `--dataflow ip` reported zero issues *and*
zero coverage notes where `local` had at least disclosed the gap; a hop that
resolves a tag and then refuses the cross-scope match now says so, the way
§11.36 N5 already makes the hop cap say so. **REV5-04** — ANA-10's four caps
abandoned a container in silence while its sibling in the same wave published a
`truncated` diagnostic for the identical situation; every cap now records a
`config_unresolved`. **CFG-CONFIG-WARNING-DROPPED** — an explicit `--config`
naming a `pyproject.toml` with no `[tool.mlview]` table applied nothing and said
nothing, because the post-discovery re-read threw away the `config_warning`
§11.37 A3 requires; the warning survives and only the *path* is dropped, so
`workspace.configPath` still names only a file that decided something.
**GALLERY-FALSE-BLINDSPOT** — the gallery index asserted, from a constant, that
`MLV301` / `MLV302` / `MLV401` / `MLV501` "structurally cannot fire here" and
that "the analyzer says so on every page as a `single_file_analysis`
diagnostic". Both halves were false: all four fire on their own single-file
fixtures, and **0 of 90** pages carry that diagnostic, which speaks only when an
analyzed module *imports* a sibling the run left out. The paragraph is now
measured off the run.

**The interprocedural arithmetic, made unavoidable (IP-01).** Only
`rules/r_leakage.py` ever called `ctx.hops()`, so `MLV111`, `MLV114` and
`MLV301` / `MLV302` published cross-object claims at `certain` with evidence
reading `dataflow_direct 1.0` — "the tag was established here" — about a tag
that had arrived from another file, and with no `RelatedLoc` a reader could
open. `rules/context.py` now records every read whose value carries a provenance
chain and spends it in `issue()`, ahead of `compute_confidence`: one
`cross_file` factor per finding (the **longest** chain, not one per read, since
several reads out of one object are not independent chances of being wrong),
plus the hop `RelatedLoc`s. A rule that already paid is left exactly as it was,
and on `--dataflow local` nothing ever carries a chain, so the default mode is
untouched by construction. **IP-03** — a single `np.asarray()` / `np.array()` /
`np.concatenate([...])` dropped the `FEATURES` / `RAW_DATA` tag entirely,
silencing `MLV101` and defeating the constructor summary DATAFLOW-IP was built
for; `FRAME_MAKE` now carries the six data tags through argument 0, and a
**list** argument carries the **intersection** of its members' tags — stacking
the training half onto the test half does not produce training rows.

**H5-01, and the file layout most training scripts use.** `_defined_after`
withheld the `MLV201` / `MLV301` edit whenever the value's producer sat below
the insertion point *anywhere in the file*, so `def train(model, loader,
optimizer)` written above `def main()` resolved its parameter to the
`torch.optim.AdamW(...)` the caller runs — below the loop being edited — and the
lightbulb was empty for the ordinary layout. A parameter is bound before its
body runs at any line, so the guard now applies only within one scope, which is
the only case where "above" and "below" order two statements at run time.

**The viewer.** **VIEW-R3** — a gutter group's trunk was the **intersection** of
its members' x-spans, which goes negative on a wide lane, so `VIEW-04` silently
built no trunk for exactly the biggest groups and fell back to twenty
near-parallel runs — the picture the item exists to remove. `layout/bundles.ts`
now clusters members by overlap and builds each cluster's trunk from the
**union** of its spans, so a connected cluster's trunk is covered at every point
by at least one member, a group may yield more than one trunk (`part`, and `#n`
in the id), and a member that overlaps nothing keeps its own stroke and is
counted as residue. **VIEW-R4** — `role="listitem"` on the chooser's `<button>`
elements *replaces* the implicit button role, so the modal's only real actions
were invisible to the button rotor; the list semantics moved to a wrapper.
**VIEW-R5** — two rows is not enough to earn a modal over the first paint:
`workspace.entrypoints` is a ranked heuristic and on the 54-node demo it offered
a one-node `config.py` as a "training script", covering the one screen VIEW-01
exists to protect. `shouldAskPipeline` owns the floor and the chooser draws only
the rows that clear it. **VIEW-R7** — the chooser opens by itself, so `hide()`
dropped focus onto `<body>`; it now hands focus to the canvas that owns the
roving tab stop.

**The hosts.** The code-action lightbulb attached a ready `WorkspaceEdit`, which
VS Code's own bulk-edit service applies — making the lightbulb the one surface
that never reached `applyIssueFix`, and therefore the one with no
`verifyAgainstBuffer`, no dirty-buffer refusal and no §11.43 A9 staleness
refusal. It is also the surface a user actually clicks. The action now carries a
**command and no edit**, so all three surfaces are one path as §11.43 A1
requires; the edit is still built, but only to decide whether to offer the
lightbulb at all. `parseFix` also stopped accepting a fractional coordinate: the
value arrives from a child process, and `Math.trunc(3.9)` is a half-understood
coordinate written into somebody's file.

**What these fixes could not close.** IP-01's join is "the finding is anchored
inside the scope the value was read in", one level coarser than
`apply_config_derating`'s source-range test, because a hop's own location is in
the caller's file and can never fall inside the finding's range — which is
exactly why the reader gets the `RelatedLoc`. A scope with no `loc` falls back to
the file test alone, over-approximating towards costing confidence rather than
inventing it. IP-02's disclosure is a `truncated` diagnostic, not a finding: the
cross-object leak it describes is still **neither confirmed nor ruled out**, and
`--dataflow ip` is still off by default. ANA-02 folds only *unconditional* stores
— a write inside an `if` leaves the leaf as it was rather than guessing which
branch ran — and ANA-04 follows one call, so `args = build()(…)` still resolves
to nothing. VIEW-R3's clustering is per gutter group, so two clusters that are
adjacent but not overlapping still draw two trunks. And the gallery paragraph
now reports what happened **on this corpus**: it says nothing about whether a
cross-file rule would fire on the reader's own repository.

**What only CI could see, and the three things it caught.** All four of the
following were green on this Mac and red on the runners, which is the whole
reason the matrix exists. **The bundled-core count was 97 here and 96 there.**
The fact cache is ON by default since §11.39 and writes `<root>/.mlview/cache`
into whatever directory was analyzed, so somebody who had once run the analyzer
over `analyzer/src/mlview` left a `facts-<hash>.json` inside the source tree —
gitignored, therefore invisible to CI, and copied into **both** vendored cores by
`tools/sync-core.py`, which skipped `__pycache__` but not `.mlview`. It now skips
`.mlview` for exactly the HEALTH-01 reason, and the stray sidecars were deleted;
`docs/STATUS.md`'s Components row reads **96**, the number
`tools/verify.py --all` prints on both machines. **Two `analyzer (py3.10)` tests
asserted the behaviour the CFG-ONE fix removed.** With no `tomllib`,
`load_config` used to return the ignored file's `path` and `source`, so
`workspace.configPath` named a file that had decided nothing — the reading
§11.37 A3 exists to prevent, and the two tests that asserted it are the ones the
fix should have re-pointed. `test_below_3_11_the_file_is_ignored_out_loud…` now
asserts `path is None` with the warning intact (verified against a real
no-`tomllib` interpreter, not by reading the code), and the four tests that need
a parser to have anything to assert carry the `NEEDS_TOMLLIB` marker the other
seventeen already did. **One plugin test was a race, not a test.**
`test_a_run_that_overshoots_the_budget_says_nothing_at_all` passed `budget=0.0`
and analyzed an empty directory: `join(0.0)` returns at once, but so does the
worker, so on a fast runner the thread had already finished and a real graph came
back. It lost that race on two of thirteen jobs. The overshoot is now **forced** —
`hook_core.analyze` is replaced by a blocking stub — so the abandonment is the
thing under test rather than the scheduler. The VSIX was re-measured while
settling the core count: **754.24 KB, 148 files, 96 under `extension/core/`,
73.7% of the 1 MB ceiling**. A second iteration cleared two Windows-only
failures, both of them a new test meeting a real portability bug: `gen_gallery.py` subtracted the literal `docs/gallery` from every page path to build the index's hrefs and called `os.path.relpath(path, REPO)` on the output directory, so an `--out` anywhere else produced broken links and an `--out` on another **drive** — which is what a Windows temp directory is — raised `ValueError: path is on mount 'D:', start on mount 'C:'`. The index now links by a path computed from the real output paths, and `_relative` falls back to the absolute path rather than raising. And `test_the_server_and_the_hooks_name_one_parse_cache_outside_the_project` compared a forward-slashed `cache_dir()` against an un-normalized `str(tmp_path)`, so it failed for spelling rather than for the sharing it is about.

**Gates, all re-run on this Mac at the integrated tree.** `sh scripts/e2e.sh`
**20 steps, 0 failed, 0 skipped**; analyzer **2087 passed / 4 skipped** (2024 / 4
at wave 3, 1722 / 3 at the sprint baseline); webview **534 tests** (521);
vscode-extension **377 tests** (372); claude-plugin **373 passed / 7 skipped**
(370 / 7); `python -m pytest scripts -q` **74 passed**; `npx tsc --noEmit` clean
in both TypeScript packages; `python tools/verify.py --all` **10 of 10**,
including `parity: CLI vs MCP — 54 nodes, 51 edges, byte-identical`, both
vendored-core gates and all three renderer-hash rows;
`python tools/verify.py --scopes --fuzz 200` **5 of 5** (13 projections + 7 error
cases, 5 promoted counterexamples, 200 fuzz cases over 40 generated graphs of
6–457 nodes with **7 rolled up and 23 carrying pipelines**, seed 25161, 2.8 s);
`python tools/accuracy.py` **PASS** — precision **100.0%** on 36 rules, recall
**73.1%** / 65.4% visible / 64.9% high+medium, unseen 55.3% / 42.5% / 37.5%,
graph fidelity **91.4%** (127 of 139), zero forbidden findings;
`python tools/accuracy.py --dataflow ip` **PASS** against its separate ratchet —
precision **100.0%**, recall **79.5%** / 71.8% visible, unseen **66.0%** / 53.2%,
graph fidelity **91.4%**; **every one of those figures is unchanged from wave 3
in every digit**, which is the point — the review fixes removed false positives
the corpus never labelled and added disclosure the corpus does not score, and
they were not allowed to move a labelled finding.
`python contracts/validate_sample.py` green at four budgets —
`--max-nodes 400 / 40 / 20 / 8` give **54/51, 38/40, 12/18 and 7/4** nodes/edges
and **15 issues (5 high / 6 medium / 4 low) in all four**;
`python analyzer/tools/gen_gallery.py --quiet` renders **90 reports plus an
index**; `python scripts/check_docs.py` **DOC CHECK OK** (19 files).
**CI (run 34454599867): all 12 branch jobs green**, 7m57s wall and ~44 billable
minutes — `e2e (windows, powershell)` 7m53s and `e2e (ubuntu, sh)` 6m29s;
`smoke (macos)` is skipped on a branch push by design. It took **two fix
iterations**, recorded above rather than smoothed over: five failures across the
first two pushes, every one of them something only the matrix could see.

## Hardening round 1 — integrated (2026-09-14)

Not a sprint. The brief was *"test the current implementation extensively and
carefully; besides fixing bugs, focus on coverage over all possible ML/DL code —
test against public repos, construct code that mimics real ML/DL applications"*,
and the product's standing rule decided what counted as a failure: **a
high-severity false positive on correct code is the worst outcome, and silently
misrepresenting code — a stage claimed absent, a call dropped, a crash swallowed
— is the second worst.** Both happened, repeatedly, and both are what this round
went after.

**Coverage.** Six testers worked in parallel over five surfaces, and the two
measurements they built are now gates rather than anecdotes:

| Surface | What was covered | What it left in the tree |
|---|---|---|
| Public repositories | **24 pinned repos** — transformers, pytorch-lightning, scikit-learn, keras-io, diffusers, detectron2, timm, yolov5, nanoGPT / minGPT, CLIP, stable-diffusion, fastai, flax, mlflow, stable-baselines3, pytorch_geometric, vit-pytorch, DeepLearningExamples, tensorflow-models, wandb-examples, PythonDataScienceHandbook, denoising-diffusion-pytorch, pytorch-examples — at exact SHAs, **90 targets × 2 dataflow modes = 180 runs** | `tools/public_corpus.py` (`fetch` / `run` / `check`) and `analyzer/tests/public_corpus/` — the manifest, the adjudication record and the pytest wrapper |
| Written ML/DL code | **77 new labelled programs, 188 source files**: 25 vision, 15 infrastructure, 13 tabular, 12 NLP, 12 advanced (RL / GNN / distillation / meta-learning / audio / multimodal), most as a correct / defective pair | `analyzer/tests/accuracy/corpus/` grows 15 → **92 programs**, 78 → **312** expected labels, 125 → **1229** forbidden labels, 139 → **614** hand-drawn graph ops |
| Robustness | a deep-but-legal AST, a FIFO named `*.py`, a symlink to `/dev/zero`, an unreadable directory, a backslash-continued shell escape in a notebook, `from x import *`, duplicate `Issue.id`s | `analyzer/tests/core/test_hardening_robustness.py`, `test_hardening_perf.py`, `analyzer/tests/fixtures/robustness/` |
| Hosts and UX | 16 real repositories rendered in all three hosts; every MCP argument driven out of range | `webview/test/hardening_*.test.mjs` (4 files), `vscode-extension/test/hardening_*.test.js` (3), `claude-plugin/tests/test_argument_bounds.py` + `test_hardening_tool_arguments.py` |
| The tree itself | which selectors are advertised, which directories a tool writes into, which test files a package's `npm test` actually runs | `scripts/doc_surfaces.py` + `scripts/test_doc_surfaces.py` — doc-gate checks **16, 17 and 18** |

**Findings fixed: 49.** 47 in the analyzer, one in the viewer
(`HOSTS-UX-CHIPWALL`: an unbounded diagnostic chip row collapsed the diagram to
zero pixels on 7 of 16 real repositories) and one in the Claude Code plugin
(`HOSTS-UX-FRAMEWORK`: `mlview_analyze` accepted any `framework` string and
silently returned a stripped analysis — five high findings became zero on
`pytorch`, a spelling no rule declares). The worst class was the largest: **five
forbidden findings** — high-severity claims about correct code that the labelled
corpus explicitly forbids — were firing on `hardening` at `ef4fb71` when the
round opened, and the precision headline read **97.6%**, not 100%. Nine
contract amendments came out of it, **§11.50 – §11.56**.

**Two findings were made by the integration itself**, and they are the reason
the public-corpus gate exists. With every tester's fix in the tree,
`python tools/public_corpus.py check` refused the build on two NEW high findings
— neither reachable from 312 labels:

* **PUB-15** — MLV101 reported a `certain` leak at
  `scikit-learn examples/release_highlights/plot_release_highlights_0_24_0.py:153`,
  where the fit is on iris and the split it cited is twenty-seven lines later on
  covtype. PUB-03's rebinding guard read assignment targets through
  `dotted_text`, which is empty for an `ast.Tuple` — so `X, y = load_iris(...)`,
  the way scikit-learn binds data, was invisible to it. The shipped PUB-03
  fixture could not catch this because its fit is an *estimator* fit, which a
  second, independent guard already silences.
* **PUB-14** — MLV102 reported a `certain` 0.97 leak on cell 16 of the Python
  Data Science Handbook's `05.03-Hyperparameters-and-Model-Validation.ipynb`,
  which is *teaching* two-fold cross-validation. It called a
  `KNeighborsClassifier` "the transformer" and said the held-out score was not an
  estimate of unseen-data performance — about a model scored only on the half it
  was never fitted on. `_is_transformer_fit` has answered exactly this question
  for MLV101 since ROB-10; MLV102 now asks it too.

Both are `state: "fixed"` in `analyzer/tests/public_corpus/adjudication.json`, so
a return is blocking, and both cost **nothing**: every accuracy figure is
identical to four decimal places in both dataflow modes, and the corpus-wide high
count falls from 37 to 34.

**The recall headline went down, and that is the honest reading.** 73.1% → 72.4%
raw, because 77 of the 92 programs are new, unseen and harder than the fifteen
the rules were developed against. The control is in `docs/ACCURACY.md` §3:
scored over the **original fifteen programs alone**, this build reads 73.1% →
**75.6%** and the whole previous gate — every `perRule` row and graph fidelity —
**passes**. Both baselines were re-recorded with `--allow-regression` and the
reason written into each file's own `note`, never by deleting a label. On the
**unseen** half every reading is sharply up: 55.3% → **69.4%** raw, 42.5% →
**63.0%** visible, 37.5% → **60.2%** high+medium, and the unseen set is 86
programs rather than eight. No rule carries a tuned `*` any more: all 36 have at
least one label in a program nobody wrote for them.

**Gates, all re-run on this Mac at the integrated tree.** `sh scripts/e2e.sh`
**20 steps, 0 failed, 0 skipped**; analyzer **2405 passed / 7 skipped** (2087 / 4
at the Sprint-5 close); webview **561 tests** (534); vscode-extension **401
tests** (377); claude-plugin **434 passed / 7 skipped** (373 / 7); `python -m
pytest scripts -q` **99 passed** (74); `npx tsc --noEmit` clean in both
TypeScript packages; `python tools/verify.py --all` **10 of 10**, including
`parity: CLI vs MCP — 54 nodes, 51 edges, byte-identical`, both vendored-core
gates (**99** files) and all three renderer-hash rows;
`python tools/verify.py --scopes --fuzz 200` **5 of 5** (13 projections + 7 error
cases, 5 promoted counterexamples, 200 fuzz cases over 40 generated graphs of
5–259 nodes with **12 rolled up and 21 carrying pipelines**, seed 42532, 2.0 s);
`python tools/accuracy.py` **PASS** — precision **100.0%** on 36 rules over
**92 programs and 312 labels**, recall **72.4%** / 66.7% visible / 64.5%
high+medium, unseen **69.4%** / 63.0% / 60.2%, graph fidelity **85.0%** (522 of
614), zero forbidden and zero unlabelled findings;
`python tools/accuracy.py --dataflow ip` **PASS** against its separate ratchet —
precision **100.0%**, recall **76.3%** / 69.9% visible, unseen **73.7%** / 66.5%,
graph fidelity **85.2%**;
`python tools/public_corpus.py run && … check` **gate OK** — 180 runs, **180
clean**, 43 s wall against a 60 s budget, 34 high / 102 medium / 208 low, no
traceback, no schema error, every exit code 0 or 4.
`python contracts/validate_sample.py` green at four budgets —
`--max-nodes 400 / 40 / 20 / 8` give **54/51, 38/40, 12/18 and 7/4** nodes/edges
and **15 issues (5 high / 6 medium / 4 low) in all four**;
`python analyzer/tools/gen_gallery.py --quiet` renders **102 reports plus an
index**; `python scripts/check_docs.py` **DOC CHECK OK** (19 files, 18 checks).
**CI (run 34793319849): all 12 branch jobs green**, 13m10s wall and ~71 billable
minutes (43 for the eleven ubuntu jobs, 14 x 2 = 28 for the one Windows job) —
`e2e (windows, powershell)` 787 s, `e2e (ubuntu, sh)` 617 s, Python 3.10-3.13
219-355 s, Node 20/22 171-176 s; `smoke (macos)` skipped on a branch push by
design. Both totals roughly doubled over Sprint 5's, and the cause is this
round's own work: 2087 -> 2405 analyzer tests and 15 -> 92 labelled programs.

It took **three fix iterations**, recorded here rather than smoothed over,
because every one was a real defect a single-platform run cannot see and every
one was in a test this round wrote:

1. **`analyzer (py3.10)` and `(py3.11)`, four failures, two fixtures.**
   `robustness/syntax/pep695` is PEP 695 and `.../fstrings` is PEP 701 — both
   3.12-only source. MLView parses with the **host** interpreter's `ast`, so on
   those runners the files cannot be read at all, and
   `test_every_syntax_fixture_analyzes_without_incident` asserted
   `filesFailed == 0` about a file the host cannot open. `syntax_programs()` now
   carries a `MIN_PYTHON` skipif (eight skips there, verified by setting the map
   to `(3, 99)` and counting them). **`claude-plugin`**, same push: a test shelled
   out to `python -m mlview` in the one job that deliberately does **not** install
   the analyzer, read `No module named mlview`, and asserted against that text;
   the child now gets `PYTHONPATH=analyzer/src`, which is what the sibling
   `_cli_scoped` already does.
2. **`e2e (windows, powershell)`**, `assert 418 == 402`.
   `test_an_edit_that_preserves_size_and_mtime_is_still_seen` wrote the fixture as
   bytes and rewrote it through a **text-mode** handle, so Windows turned every
   `\n` into `\r\n` and the file grew a byte a line. The premise of the test was
   destroyed by the file mode and the failure read as an analyzer defect. Both
   handles now pass `newline=""`.
3. **`e2e (windows, powershell)`** again, four subtests in two new
   `vscode-extension` suites, one defect wearing two hats: an assertion comparing
   two spellings of one path. §0 makes every path in the document
   forward-slashed and `Uri.file(...).fsPath` gives the host separator; and
   `path.join(path.sep, 'work', 'api')` is a drive-less `\work\api` that
   everything downstream resolves against the current drive. Both are now
   compared through `path.resolve`.

**What this round did not close**, named rather than averaged away: a model,
criterion and optimizer arriving as parameters still cost a training step its
forward, loss and backward nodes (vision-02's residue, 8 of the 92 missing graph
ops); `--dataflow ip` still reports a strict subset of `local` on one mlflow
example, so `local ⊆ ip` is not yet true (vision-08, `state: "open"` in the
adjudication record); and 42 of the 92 missing ops are still a call through an
object this workspace defines, which has been the largest single recall family
since ANA-1.

## Hardening round 2 — integrated (2026-09-14)

The same brief as round 1, pointed at the build round 1 left behind: *"test the
current implementation extensively and carefully; besides fixing bugs, focus on
coverage over all possible ML/DL code — test against public repos, construct
code that mimics real ML/DL applications."* The credibility rule decided again
what counted as a failure — **a high-severity false positive on correct code is
the worst outcome, and silently misrepresenting code is the second worst** — and
this round's defects were overwhelmingly the second kind: a model rebound by
`accelerator.prepare(...)` or `fabric.setup(...)` that deleted `MLV301` and
`MLV302` and left the verdict reading *"No findings"*; a `tf.GradientTape` loop
drawn in the Evaluate lane under an answer card that said *"Evaluation runs in
…"* at 0.95; `--dataflow ip` returning **less** than `local` on 20 programs with
`diagnostics == []` in both modes.

**Coverage.** Seven testers worked in parallel over the analyzer, the renderer,
the three hosts and the tree itself:

| Surface | What was covered | What it left in the tree |
|---|---|---|
| Public repositories | **24 → 37 pinned repos** — the round-1 set plus torchtune, peft, trl, accelerate, statsmodels, LightGBM, optuna-examples, cleanrl, mmdetection, LLMs-from-scratch, handson-ml3, pytorch-tutorials and more — at exact SHAs, **112 targets × 3 modes (`local`, `ip`, `--include-notebooks`) = 260 runs** | `analyzer/tests/public_corpus/repos.json` and `adjudication.json` grow with them; the notebooks mode is new |
| Written ML/DL code | **66 new labelled programs**: adversarial / RL / GNN / self-supervised (`adv_*`), infrastructure (Airflow, Click, DVC, Fabric, Optuna, PySpark, Ray, SageMaker, a plugin registry, a TF custom loop, a notebooks-only repository), NLP (DistilBERT distillation, DPO, instruction SFT, Keras text, a reranker, RAG indexing) and vision, most as a correct / defective pair | `analyzer/tests/accuracy/corpus/` grows 92 → **158 programs**, 312 → **545** `expected` labels, 1229 → **2327** `forbidden` labels, 614 → **1166** hand-drawn graph ops |
| The renderer | the **built** viewer mounted in jsdom over the 260 public-corpus documents and 158 documents emitted from the labelled corpus — 1257 chips measured past 48 characters on 227 of them, 1255 with no `title` at all | `webview/test/hardening_chrome_budget.test.mjs` (14 assertions) and `hardening_hosts_ux2.test.mjs` (5) |
| Hosts | every accepted `mlview_analyze(framework=…)` value against the rule registry; the VS Code configuration precedence chain | `claude-plugin/tests/test_framework_suppression.py` (**26 cases**) and `vscode-extension/test/hardening_config_precedence.test.js` |
| The analyzer's own declarations | binding shapes (tuple parameters, dict literals, `functools.partial`, factory returns), notebook magics, package walking, report escaping | `analyzer/tests/core/test_round2_analyzer.py` + `test_round2_core.py` (**64 cases**) and three new `analyzer/tests/fixtures/robustness/` trees |
| The tree itself | the command lines CI generates, the exclusive rule lists a document asserts, and a "known gap" that names its own retirement condition | doc-gate checks **19, 20 and 21** — the gate is now twenty-one checks, still offline and stdlib-only |

**Findings fixed: 54.** Forty-four in the analyzer (`docs/ACCURACY.md` §8 is the
record), three in the tree's own documents and CI (**PUB2-10**, **VIS2-17**,
**HOSTS-UX-R2-07**), one in the Claude Code plugin (**INFRA-R2-18**: an
*accepted* `--framework` value silently returned a shorter finding list — a
high-severity `MLV121` disappeared when a Keras workspace was narrowed to
`torch` and nothing in the payload said a rule had been disabled), two in the
renderer (**TAB2-10**, **HOSTS-UX-R2-06**) and four more the integration itself
made. The worst class was again the largest: `hardening` opened this round with
**eight forbidden findings** — high-severity claims about correct code the
labelled corpus explicitly forbids — and precision **97.9%**; it closes at zero
forbidden, zero unlabelled and **100% precision in both dataflow modes**.

**Five contract amendments, §11.57 – §11.61.** They were written as
`docs/contracts/11.50-…` through `11.53-…` plus one that had already noticed the
clash and taken `11.57`; `docs/CONTRACTS.md` already carried §11.50 – §11.56
from round 1, so the integrator renumbered all five into the next free block and
moved the three citations that named them by number — `core/pipeline.py`'s
`scope` comment, `docs/ACCURACY.md` §6 and `baseline.ip.json`'s own `note`.

**Three findings were made by the integration itself.** The round's
`webview/test/hardening_hosts_ux2.test.mjs` arrived **red**: the tests were
written and the fixes were not, which is an honest hand-off and a blocking one.

* **HOSTS-UX-LEGENDPAN** — `app.ts` appends the legend to `shell.canvas`, and
  the drag-pan guard in `ui/shell.ts` named only `.mlv-node, .mlv-group__header,
  .mlv-minimap, .mlv-zoom, .mlv-edge__hit`. A `pointerdown` anywhere on the
  legend therefore started a canvas pan and took pointer capture, so the panel's
  own close button never saw its `click` — it worked from the keyboard and not
  from the mouse. The guard now names every overlay the app paints over the
  canvas, and three of the four round-1 `todo` tests in
  `hardening_canvas_overlays.test.mjs` are ordinary gates again.
* **HOSTS-UX-ANSWERWRAP** — `.mlv-answers__sentence` and `.mlv-answers__cites`
  declared no wrapping and a workspace-relative path is one unbreakable token,
  so on 7 of 90 real reports an answer was painted **over** the answer beside it
  (`…image_classification/training.py:205` and `MLV803 (low) at` composited into
  `…/tMLIVN803G.(low)205at`). `overflow-wrap: anywhere` — the value that lowers
  min-content width, so the grid column and the citation buttons can actually
  shrink — on both.
* **HOSTS-UX-ROWCOUNT** — round 1 made the *pipeline* rows of the scope picker
  promise `drawnCount`, "the number the click delivers". `unitRow()` and
  `groupRow()` were left promising the match set, so on the frozen golden
  `unit:train.train` offered 4 nodes and drew 9. `scope/catalog.viewCountOf`
  now runs the same `project()` the click runs for any selector — and
  `scope/project.ts` pays for it honestly: steps 3-7 are extracted as
  `keptSets()`, so `projectedNodeCount` answers a row without step 8's copy of
  every kept node and edge. Opening a 222-row picker over a 400-node, 2 220-edge
  public repository went 819 ms → 101 ms, with one implementation still behind
  the promise and the click.
* **HOSTS-UX-CLEANSTATE** — round 1's own finding, left open by it and closed
  here because §11.59 A1 is what made it expressible. The Issues rail — the
  panel a reviewer reads first — said *"No issues found · 213 nodes across 8
  stages checked — nothing to flag."* on a nanoGPT report whose two banners and
  whose verdict all said the run had been blind. `cleanState()` now appends the
  same sentence the banner draws, from the same `coverageHeadline`, over the
  wider set `blindSpots()` selects: the three banner kinds plus `parse_error`,
  `notebook_skipped` and a `truncated` whose `scope` is not `nodes` — a rolled-up
  graph is a display cap the reader can see, not a gap in the analysis. A
  document with no coverage diagnostic still gets an unqualified clean result.
  Measured over the 260 pinned public-repository documents: **122 draw the clean
  state, and 118 of them were drawing it over a run that had been blind.**

**The recall headline went UP, on a corpus 1.7× larger.** Round 1 had to report
a fall (73.1% → 72.4%) because 77 of its 92 programs were new; this round's 66
new programs are just as unseen and every aggregate still rose: `local` recall
**72.4% → 77.8%**, visible 66.7% → 70.1%, high+medium 64.5% → 70.7%, unseen
69.4% → **76.5%**; `ip` 76.3% → **79.1%** with unseen 73.7% → 77.8%. Both
baselines were re-recorded with `--allow-regression` and the reason written into
each file's own `note`, never by deleting a label — the thirteen per-rule ratios
that read lower do so against a larger denominator, and `docs/ACCURACY.md` §8
says which. Fourteen labels naming rules that are not built were moved to
`unsupported` with the reason in each row: a label for a rule that cannot fire
can never be satisfied and can never be violated.

**Gates, all re-run on this Mac at the integrated tree.** `sh scripts/e2e.sh`
**20 steps, 0 failed, 0 skipped**; analyzer **2574 passed / 9 skipped** (2405 / 7
at the round-1 close); webview **585 tests** (561); vscode-extension **404
tests** (401); claude-plugin **460 passed / 7 skipped** (434 / 7); `python -m
pytest scripts -q` **119 passed** (99); `npx tsc --noEmit` clean in both
TypeScript packages; `python tools/verify.py --all` **10 of 10**, including
`parity: CLI vs MCP — 54 nodes, 51 edges, byte-identical` and both vendored-core
gates (**99** files); `python tools/verify.py --scopes --fuzz 200` **5 of 5**
(200 fuzz cases over 40 generated graphs of 5–495 nodes, 7 rolled up and 18
carrying pipelines, seed 65134, 2.9 s); `python tools/accuracy.py` **PASS** —
precision **100.0%** on 36 rules over **158 programs and 545 labels**, recall
**77.8%** / 70.1% visible / 70.7% high+medium, unseen **76.5%** / 68.3% / 68.7%,
graph fidelity **84.5%** (985 of 1166), zero forbidden and zero unlabelled
findings; `python tools/accuracy.py --dataflow ip` **PASS** against its separate
ratchet — precision **100.0%**, recall **79.1%** / 71.2% visible, unseen
**77.8%**; `python tools/public_corpus.py fetch && run && check` **gate OK**, and
`check --strict` too — **260 runs, 260 clean**, 36 s of wall at `--jobs 8` with
the slowest single run 17.9 s (timm under `ip`) against the 60 s per-run budget
CI uses, 50 high / 276 medium / 376 low, zero tracebacks, zero schema errors,
every exit code 0 or 4.

**What this round did not close**, named rather than averaged away: Escape
still does not close the legend, because `dismissTopmost` runs the cascade
§11.13 freezes and adding a rung to it is an amendment rather than a line
(`HOSTS-UX-LEGENDESC`, the one `todo` left in the viewer suite); and twenty-two
points of recall are still missing, largest first — MLV208's `GradScaler`
through a parameter dict, MLV305 needing a prediction to carry `LOGITS` or
`PROBS`, and a model built by a registry (`build_from_cfg("model", cfg)`) still
being untyped.

## Known gaps

None block the demo. In rough order of how likely they are to matter:

- **A fold is lossy about *which* thing, and `rolledUp` is the whole
  disclosure.** After `core/rollup.py::_summary_node` folds a file or a
  directory, the diagram shows one card carrying `rolledUp: <n>` and
  `sublabel: "<n> nodes rolled up"`, and **nothing says what was inside it**. The
  summary's `kind` and `stage` are a majority vote over the folded nodes and
  nothing records that the vote was close; a merged edge with `weight: 3` keeps
  its label only when its members agreed and is otherwise unlabelled, so the
  disagreement is erased rather than reported. The findings all survive with
  real `loc`s (`test_every_finding_survives_and_resolves_to_a_node`), which is
  why this is a legibility gap and not a correctness one — but "42 nodes rolled
  up into their surviving ancestor" is the most a reader is told.

- **The deletion phase still exists, and "a cap never silences a finding" is a
  claim about a corpus, not a theorem.** `_choose_survivors` in
  `analyzer/src/mlview/core/rollup.py` is the pre-PERF-04 deletion order kept as
  phase 3, and it runs when the budget is smaller than the number of top-level
  directories — no fold tier is left. It did not run at any budget on the
  525-file synthetic (zero nodes dropped even at `--max-nodes 45`) or on
  `samples/vision_pipeline` down to `--max-nodes 8`, so every measurement here
  has `lost_issues == 0`; a tighter budget on a wider
  tree can still drop a node, and only the `truncated` diagnostic's own counters
  would say so.

- **A `pipeline:` view draws the *other* entrypoints, greyed, and nothing tells
  them apart from a shared helper.** §11.47 A3's closure includes but does not
  expand through a neighbouring entrypoint's own nodes, so
  `core/pipelines.py::PipelineIndex.reach` pulls in up to one whole file per
  neighbour as context. Excluding them instead was tried and is worse: on
  `samples/vision_pipeline`, where the entrypoint heuristic lists `train.py`,
  `config.py` **and** `data.py`, it empties the core. Related, and measurable in
  the same file: `workspace.entrypoints` is itself a heuristic **capped at 10**,
  so a repo with 25 training scripts gets 10 pipelines and nothing says 15 are
  missing; a library with no entrypoint gets `unknown_pipeline` with an empty
  candidate list; and nodes in *no* pipeline are counted in the projection's
  `config_warning` but never named — there is no `pipeline:none` selector.

- **On a rolled-up document the `pipelines[]` counts describe the summarised
  graph.** A file summary counts once however many nodes it stands for, so
  `pipelines[].nodeCount` after a rollup is a count of cards, not of statements.
  `stats.truncated` is the only thing that says so, and the viewer's chooser is
  the only surface that repeats it (`ui/pipelinechooser.ts` adds that caveat when
  `stats.truncated` is set).

- **`--dataflow ip` is analyzer-only.** No host wires the flag in this release —
  not the VS Code settings, not the MCP tools, not the plugin skills — which is
  what the roadmap's "one release behind the flag" asks for, but it means the
  mode is reachable from `python -m mlview` and `mlview.api.build_workspace`
  only. Paying for a hop is no longer a rule's decision: IP-01 records every
  widened value read through `ctx.binding_of` (`note_hops` in
  `analyzer/src/mlview/rules/context.py`) and `issue()` charges the finding one
  `interprocedural_evidence` factor of `0.8 ** hops` with the `cross_file`
  evidence row that explains it, so a rule that starts making cross-object
  claims cannot skip the de-rating even by accident — which is what §11.36 gate
  G6 asks for. This bullet used to say two rules pay and name them; measured in
  `ip` over the labelled corpus on 2026-09-14, three do (MLV101, MLV401,
  MLV803), and `docs/ACCURACY.md` §6 now carries the measurement with the
  command that reproduces it. The RETURN summary is the one piece of that debt
  left: it extends a pass that already shipped with no de-rating, so a tag
  arriving purely through a return chain carries no provenance and is not
  de-rated.
- **The 3-hop interprocedural cap is a guess; what is measured is that
  exceeding it is reported.** `DEFAULT_MAX_HOPS` in
  `analyzer/src/mlview/ir/provenance.py` is deep enough
  for caller → ctor → attribute → sibling method and shallow enough that two
  hops still land above `speculative`, and nothing measured that choice. A chain
  that runs past it is not propagated and **is** emitted as a `truncated`
  diagnostic naming the function, the cap and the parameter (13 rows on a
  490-file workspace, capped at 25 plus a counted remainder).
- **The SVG export is deliberately not bundled.** `webview/src/export/svg.ts`
  still emits one `<path data-edge-id>` per routed edge, so a diagram pasted
  into a PR looks like the pre-VIEW-04 picture: a static file cannot be hovered,
  and drawing both trunks and members would double the ink. `mlview diff` has
  the same shape of limit in the other direction — `core/diff.py` does no rename
  detection, so a renamed file is every node removed plus every node added.
- **The default relevance prefilter writes into the repository, and can make a
  true diagnostic redundant.** A plain `python -m mlview analyze .` now creates
  `<root>/.mlview/cache/` (gitignored, prunable, redirectable with
  `MLVIEW_CACHE_DIR`). And `core/relevance._package_inits` keeps every
  `__init__.py` below the discovery root but not the root's own, so analysing a
  package whose own `__init__.py` is empty is told twice that it is a
  single-file analysis. Both notes are true and both name the file; the reader
  is merely told twice.
- **A structured fix still lands at coordinates nobody can prove are current.**
  `vscode-extension/src/fixes.ts` refuses the two provable failures — an unsaved
  buffer and a file shorter than the analysis saw — and VS Code's refactor preview
  shows the diff before anything is written. Neither is a proof: a file edited,
  **saved** and left the same length passes both checks, and the edit lands at a
  line that has moved. The honest fix is a content hash on the document, which
  11.42 I.3 declined to add; until then the preview is the last line of defence.
- **The lightbulb and the Problems panel can disagree about which findings exist.**
  Code actions are matched against the **graph**, so a finding below
  `mlview.minConfidence` (default 0.6) but at or above the `likely` bucket gets a
  lightbulb with no squiggle beside it. That is deliberate — the floor for an EDIT
  is 11.42 B3's, not a display preference — but a user who filters the Problems
  panel down is not filtering the fixes.
- **The host cannot say what a comparison base was captured from.**
  `compareWithSavedBase` in `vscode-extension/src/compare.ts` re-analyses the head
  and hands both documents to `python -m mlview diff`; nothing records the commit,
  the working-tree state or the settings the base was analysed under, so a base
  captured before a change and one captured after it are indistinguishable. The
  overlay's `different-analyzers` note covers a version change and nothing covers a
  settings change; the base file's mtime is the only clue and the host does not
  read it.
- **The multi-root diagram still shows one folder at a time.** A window with
  several folders open has one panel and one status bar; `folderTooltipLine` in
  `vscode-extension/src/folders.ts` names the folder the count describes and how
  many it does not, and the Problems panel is the only surface that shows the
  union. A CodeLens on a file in a folder nobody has analyzed draws nothing and
  has no affordance to say why.
- **The Claude Code hooks do nothing on Windows without Git Bash.** The command
  in `claude-plugin/hooks/hooks.json` is shell form, which is PowerShell there,
  and `${MLVIEW_PYTHON:-python}` does not expand. The hook fails to start, which
  is non-blocking, so the degradation is "MLView says nothing" rather than a
  broken session; `claude-plugin/README.md` says so rather than leaving it to be
  discovered. The same hook re-analyzes the whole project rather than the edited
  file, so on a repository too large for `BUDGET_SECONDS` it is permanently
  silent until CACHE makes the re-analysis incremental.
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
- **A notebook label names the generated module, not the `.ipynb`.**
  `webview/src/notebook.ts` appends the cell reference to `loc.file`, and 11.29 N5
  makes `loc.file` the generated module, so a card reads
  `.mlview/notebooks/leak.py > cell 3 : 2`. That path is the text that was
  actually analyzed and is what click-to-code copies, so label and link agree;
  showing `attrs.notebook` instead would make them disagree, and which of the two
  names "the location" is a product decision 11.29 does not settle. The hover
  already carries the flat line into the concatenation.
- **The cell map is on nodes and on issue evidence only.** `relatedLocs` and edges
  carry no `attrs` map (11.29 N6), so a related location inside a notebook — the
  split site of a leak, say — prints a flat line into the generated module in
  `webview/src/ui/issuelist.ts` and in the extension's Problems panel. Wrong
  granularity, never a broken link.
- **The per-finding cell mapping is a string, not a field.**
  `analyzer/src/mlview/rules/confidence.py` writes it as one `context_confirmed`
  evidence detail and `vscode-extension/src/notebooks.ts` regex-matches that
  sentence to place a squiggle. `test/notebooks.test.js` pins the format against
  the analyzer source so a rename on either side reddens, but two optional `Issue`
  fields would remove the parse; it is logged below as a contract change request.
- **Notebooks are outside the parse cache and the relevance prefilter.**
  `analyzer/src/mlview/core/cache.py`'s `file_signature` hashes `.py` only, so
  editing a notebook does not invalidate a host's cached graph, and `--relevance ml`
  never sets a notebook aside because notebooks bypass phase 1 entirely. Widening
  the signature would also change the second copy in
  `claude-plugin/server/mlview_workspace.py`.
- **No `--progress-json` frames for notebooks.** 11.31 H5 defines `total` as the
  discovered Python file count and `analyzer/src/mlview/core/pipeline.py` leaves it
  exactly that, rather than quietly redefining it; notebook conversion runs outside
  the counted phase.
- **The ANA-12 accuracy corpus still has no notebook program.**
  `docs/ACCURACY.md` §5 records the shortfall as blocked on NB. NB unblocks it, but
  adding a corpus program moves the recall ratchet in
  `analyzer/tests/accuracy/baseline.json`, which is a deliberate re-baseline and not
  part of NB's acceptance.
- **The standalone report's copy toast says the flat line.** `webview/src/bridges.ts`
  builds the clipboard text and the `vscode://file/...` deep link from the
  `openLocation` frame, which carries no cell by design, so a notebook card shows
  `> cell 3 : 2` while the clipboard says `…:28`. Both name the same place; only one
  of them says which cell.

## Contract change requests

Every agent filed some; they are recorded in each component's report and none
were acted on — the contracts in `docs/CONTRACTS.md` and
`contracts/graph.schema.json` are unchanged. The four worth a lead decision
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
4. **NB (2026-09-09): the per-finding cell mapping should be two optional
   `Issue` fields, not a sentence.** 11.29 N7 carries it as a
   `context_confirmed` evidence detail because `Loc` is frozen and `Issue` has no
   `attrs`; `vscode-extension/src/notebooks.ts` therefore regex-parses English to
   place a squiggle. Optional `Issue.cell` / `Issue.cellLine` — the same pair
   `Node.attrs` already carries, and an additive schema change of the kind §11.6
   sanctions — would delete the parse on both sides. Filed, not acted on: the
   string contract is pinned by a test on both halves and works today.

## Review and roadmap (2026-09-08)

Five auditors measured the shipped system (analysis accuracy on four unseen
projects, viewer layout on a 360-node graph, host workflow fit, analyzer and
viewer timings on 50/200/500-file synthetic repos, a practitioner walkthrough),
two judges ranked 59 proposals, and the result is `docs/ROADMAP.md` (42 ranked,
11 declined).

**The pre-sprint baseline, as the audit found it.** 0 false positives on unseen
code but roughly 26 % recall, because `core/build.py` dropped every op written
inside a class method; the first screen opened a real repo at 20 % zoom; and the
tool could not say "I could not check this". Those three sentences described the
tree on 2026-09-08 *before* Sprint 3 and are kept here as the measurement they
were, not as a description of the build.

**After Sprint 3, measured on this branch.** Eleven NOW-tier items landed —
HEALTH-01, HEALTH-03, CI-01, PERF-01, PERF-02, ANA-12, BUILD-01, COVERAGE,
RAIL-GROUP, CLEANUP and ANA-1/ANA-2/ANA-3 with VIEW-01 — recorded in the two
Sprint-3 sections above. All three audit headlines moved:

| The audit's headline | Where it stands now |
|---|---|
| ~26 % recall, class-method ops dropped | precision **100 %** and unseen recall **51.1 %** raw / **38.3 %** visible / **31.2 %** high+medium over ten labelled programs, with **graph fidelity 90.6 %** (was 66.2 %; ANA-1 took it to 86.3 %, FW-RECOG to 90.6 %). ANA-1 is the fix; `docs/ACCURACY.md` is the record and `analyzer/tests/accuracy/baseline.json` the ratchet. The high+medium reading is the one comparable to the audit's ~26 %. |
| the first screen opens a real repo at 20 % zoom | VIEW-01: `fit()` **0.322 → 0.532** on the demo at a 1240×848 canvas, worst lane emptiness 91 % → 32 %. |
| the tool cannot say "I could not check this" | COVERAGE: `untagged_dataflow` and `single_file_analysis` diagnostics, emitted by the analyzer and surfaced in all three hosts (`docs/CONTRACTS.md` §11.18). |

Recall is still the product's weakness — 51.1 % raw on unseen code means roughly
half of the planted defects produce nothing — and `docs/ACCURACY.md` §5 says what
that measurement does and does not cover.
