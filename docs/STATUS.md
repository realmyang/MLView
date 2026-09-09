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
four steps (17 at the time; 19 today, since ANA-12 added the accuracy corpus
and PACKAGING added the wheel row) and `tools/verify.py` grew two gate rows
(10 today, the tenth being PACKAGING's `vsix: synced core`).

```
powershell -ExecutionPolicy Bypass -File scripts/build.ps1   # BUILD OK
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1     # E2E OK - 19 steps, 0 failed
```

## Components

| Piece | State |
|---|---|
| Design docs | `docs/REQUIREMENTS.md`, `ARCHITECTURE.md`, `ISSUE_RULES.md`, `UX_DESIGN.md`, `CONTRACTS.md` (§10 amendments are the overriding lead decisions) |
| Contracts | `contracts/graph.schema.json`, `contracts/graph.sample.json` (golden), `contracts/validate_sample.py` (schema + 10 invariant groups) |
| Analyzer `analyzer/` | Complete. **36 rules**, zero runtime dependencies, `python -m mlview` installed editable. **1692 passed, 3 skipped.** `analyze --demo --json -` is byte-identical to the golden sample. Scoped views live in `analyzer/src/mlview/core/project.py` + `core/selectors.py`; the opt-in relevance prefilter and fact cache live in `core/relevance.py` + `core/cache.py` behind `--relevance {ml,all}` (default `all`), `--relevance-hops N` and `--no-cache`. |
| Viewer `webview/` | Complete. `dist/mlview.{js,css}` built. **360 tests pass**, `tsc --noEmit` clean. Flow animation (`src/render/flow.ts`) and the TypeScript half of the projection (`src/scope/project.ts`) ship here. |
| VS Code extension | Complete. **274 tests pass**, `tsc --noEmit` clean, `out/extension.js` bundled, `npm run package` produces a 576.92 KB VSIX (126 files) carrying the bundled analyzer — `core/mlview` at 79 files, gated by `vsix: synced core`. Copilot participant + LM tools are compile- and unit-verified only (Copilot is not installed here). |
| Claude Code plugin | Complete. MCP server on the `mcp` SDK v2, **still exactly five tools**, each result ≤ 4 KB. **296 passed, 5 skipped**, with `python tools/sync-core.py` having run after the analyzer changes (`test_vendor_bytecode.py` is the row that checks it); `claude plugin validate ./claude-plugin --strict` passes. |
| Samples | `samples/vision_pipeline` (54 nodes, 51 edges, exactly 15 issues: 5 high / 6 medium / 4 low) and `samples/vision_pipeline_clean` (64 nodes, 0 issues). `expected_issues.json` is machine-checked. |
| Rule docs | `docs/rules/` — 36 pages plus an index, generated from the registry; 7 carry the optional **What it cannot analyze** section. Every `Issue.docs` deep link resolves. |
| Demo artifacts | `.mlview/graph.json`, `report.html`, `graph_clean.json`, `report_clean.html`, plus the three scoped reports `split.html`, `optimization.html`, `evaluation.html` — self-contained, zero external references, each inside amendment A4's contracted **100 KB – 2 MB** band. No KB figure is quoted here on purpose: the viewer bundle moves, the band does not, and `scripts/e2e` now measures every emitted report against it and prints the range it found (MLV-R1-H06). Each scoped report embeds the **whole** graph and merely opens at its scope. |
| Scope fixtures | `contracts/scope.cases.json` (10 selectors + 6 error codes) and `contracts/scope.expected.json`, generated from the Python `project()` over the frozen golden and consumed by the TypeScript port — the parity gate for one algorithm written twice. `scope.cases.json` also carries a growing `fuzzCases` array of counterexamples promoted by `analyzer/tools/scope_fuzz.py`, each minimized to a handful of nodes and carrying its **own** generated graph. |

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
edges** — **51** after REV-01, on 2026-09-08, dropped the one data edge that
pointed backwards through `SmallCNN.forward` — and carries **exactly the same
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
`scripts/e2e.sh` **19 steps, 0 failed**.

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
11.28 A11 lists the four so it can be done deliberately.

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

**Gates after wave 3.** `sh scripts/e2e.sh` **19 steps, 0 failed, 0 skipped**;
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
