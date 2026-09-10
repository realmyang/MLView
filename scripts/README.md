# scripts/

Two drivers, each in a PowerShell and a POSIX-sh flavour, plus one Python gate
they both call. The two flavours do the same thing; pick whichever shell you are
in. Both are Windows-safe: no `shell: true`, no
symlinks, no `chmod`, and the PowerShell versions are Windows PowerShell 5.1
compatible (no `&&`, no `||`, no ternaries — every step checks `$LASTEXITCODE`).
The `.sh` flavour also runs on Linux and macOS, which is what the `e2e (ubuntu,
sh)` CI job exercises.

| Script | What it does |
|---|---|
| `build.ps1` / `build.sh` | Build everything, in the only order that works. |
| `e2e.ps1` / `e2e.sh` | Build, run every suite, analyze the samples, write the scoped demo reports, render them, run the parity, scope, accuracy and doc gates, print a PASS/FAIL table. |
| `check_docs.py` | The doc gate, checks 1-8 and 12: dead paths, dead Markdown links, "known gap" bullets that still describe a failure somebody already fixed, gap bullets that cite nothing checkable or cite a symbol that has been renamed away, a frozen design record that has started reporting build state, a POSIX shell script written with CRLF, two docs that disagree about the size of the demo graph (check 8 now reads a two-line window and accepts `N nodes and M edges`, both of which a wrapped claim used to escape), and a roadmap item that `docs/STATUS.md` reports as shipped while `docs/ROADMAP.md` carries no `**Landed ...**` measurement note for it (check 12, PROC-01). |
| `doc_numbers.py` | The doc gate, checks 9-11 — the numbers a machine can settle: `docs/ACCURACY.md`'s headline against `analyzer/tests/accuracy/baseline.json`, an `upload-artifact` step whose hidden path would silently upload nothing, and an "N steps" claim that is not the number of rows both e2e drivers print. |
| `pythonpick.sh` | Sourced by both `.sh` drivers: finds a Python 3.10+ and exports `PYTHON`. `python` first under Git Bash, `python3` first elsewhere, because on Windows `python3.exe` is usually the Store alias and on Linux/macOS `python` usually does not exist. |
| `vsix_check.py` | The packaged-VSIX gate (HOST-8): the 1 MB ceiling, `extension/core/` against `vscode-extension/core` on disk, `extension/docs/rules` against `docs/rules`, and zero `__pycache__` — then it echoes the file count and the KB, so the measurement lives in the run rather than hand-copied into two docs that drift. Run it after `npm run package`; CI's `packaging` job does. |
| `test_check_docs.py` / `test_doc_numbers.py` / `test_vsix_check.py` | The gates' own test suite — fifty-six cases: forty-nine throwaway trees, one unit test for the symbol parser, and six that read the real repo. Running any one file runs all of them; `pytest scripts` does too. |

---

## The gate table

[![CI](https://github.com/realmyang/MLView/actions/workflows/ci.yml/badge.svg)](https://github.com/realmyang/MLView/actions/workflows/ci.yml)

Every gate below runs in CI on every push — ubuntu across Python 3.10-3.13 and
Node 20/22, plus one Windows end-to-end job, one packaging job and one macOS
smoke job (the macOS one **only on push to `main` and on pull requests** — macOS
minutes are billed 10x and this Mac now runs the whole table locally before every
push, so paying tenfold for a signal a laptop already produced bought nothing;
the pre-merge coverage is unchanged) (see
`.github/workflows/ci.yml`, and the "Continuous integration" section of the root
README for the job table). There are three exceptions. Rows 10 and 11: `claude
plugin validate` is not available on a hosted runner, so that test skips itself
there and those two rows are still verified from a desk (Windows 11, Python 3.13
/ miniconda, Node 20.9, VS Code 1.136, Claude Code CLI 2.1.186). And rows 24 / 24a,
which as printed need a second checkout of the pre-change tree to diff against,
so they are run by hand around a change rather than on every push — `tools/perf_equiv.py`
does support `--record FILE` / `--compare FILE` against a committed digest file,
and since wave 3 it also states the expectation in the **exit code**
(`--expect-same` for an optimisation, `--expect-diff` for a re-baseline), which
is what would turn it into an automatic row. Row 12d used to be the fourth:
it needs the `.mlview/graph.json` an e2e run produces, so it was run *beside*
`scripts/e2e` rather than inside it. It is now the table's **20th step**
(PROC-12) — the assertions it makes about the export renderer are also made by
row 3a on the frozen `contracts/graph.sample.json` inside `npm test`, and what
12d adds is the same check over a *real* 54-node document the analyzer emitted a
moment earlier, on both drivers and in both e2e CI jobs.

`scripts/e2e` runs all of them in one pass; the middle column is how to run just
that one.

| # | Gate | Command | Result |
|---|---|---|---|
| 1 | Build | `powershell -ExecutionPolicy Bypass -File scripts/build.ps1` | `BUILD OK` — 6/6 steps (step 6 is PACKAGING's wheel; it says so and carries on when `build` is not installed) |
| 2 | Analyzer + rules | `python -m pytest analyzer/tests -q` | 1855 passed, 4 skipped on 3.11+ (the skips are the 3.10/3.11 `tomllib` split, in both directions: three that need a TOML parser and one that needs its *absence*) |
| 2a | Framework recognition (FW-RECOG) | `python -m pytest analyzer/tests/core/test_framework_recognition.py -q` | 29 passed — the seven-call `tf.data` chain is 7 connected nodes, `take`/`skip` are **not** split-kind, `datasets.Dataset.train_test_split` is split-kind and arms MLV602, every Lightning hook lands in the lane the framework runs it in, and a Keras file never picks up a torch framework |
| 2b | Unresolved callees (ANA-5a) | `python -m pytest analyzer/tests/core/test_unresolved_callee.py -q` | 13 passed — 5 `unknown` ops on the odd-syntax fixture, one `unresolved_callee` diagnostic naming the lambda / `match` case / `default_factory` constructs, the scope-wide dynamic flag **not** widened, and the demo's 15 confidences pinned |
| 2c | Notebook ingest (NB) | `python -m pytest analyzer/tests/core/test_notebooks.py -q` | 26 passed — the untouched default path (a `.ipynb` is still counted and skipped, asserted as a string equality), the four-cell leak notebook exiting **0** through the CLI with MLV101 at cell 2 and MLV201 at cell 3, every magic shape (line magic, `!` shell escape, `?` help query, `%%bash` blanked whole, `%time model.fit(X, y)` keeping the call), the `%` that is an operator and not a magic, the order-verdict table, the failure accounting and both config paths |
| 2d | Notebook locations re-slice (NB / R2.1) | `python -m pytest analyzer/tests/core/test_locations.py::test_notebook_locations_resolve -q` | 3 passed — every `Loc` in a generated module re-opens and slices the text that was actually analyzed, over `leak.ipynb`, `leak_out_of_order.ipynb` and `odd_cells.ipynb` |
| 2e | Interprocedural dataflow (DATAFLOW-IP) | `python -m pytest analyzer/tests/core/test_dataflow_ip.py -q` | 42 passed — the ctor / return / method-arg / projection summaries in **both** modes, `local` silent where `ip` fires, the intersection over call sites (never the union), the `0.8 ** hops` de-rating asserted **numerically** (0.95 → 0.760 → 0.608 → 0.486), the `truncated` diagnostic a chain past the 3-hop cap must produce, and the "parameter merely named `X`" probe silent in both modes |
| 2f | One configuration surface (CFG-ONE) | `python -m pytest analyzer/tests/core/test_config.py -q` | 23 passed, 1 skipped on 3.11+ / 7 passed, 17 skipped on 3.10 — a configuration file needs `tomllib`, stdlib only from 3.11, and the skip is never silence: the 3.10-only sibling asserts that `core/config.py` says `tomllib is unavailable`, names the file it ignored, still finishes the analysis and still reports the rule it could not disable. Otherwise: `--config` / `.mlview.toml` / `[tool.mlview]` first-match-wins with the winner named in `workspace.configPath`, TOML winning `disable` and `exclude` while a flag may only add, CLI winning every `[analysis]` option, every malformed input reduced to one `config_warning` and never fatal, and the one case the precedence cannot see (a flag typed at exactly its default) pinned rather than papered over |
| 2g | Diff overlay (VIEW-08) | `python -m pytest analyzer/tests/core/test_diff.py -q` | 20 passed — a second document kind (`mlview-diff`), per-node / per-edge / per-issue status on the §0 stable ids, a 20-blank-line insertion producing **zero** changed nodes (`loc` is outside the key, `moved: true` is recorded instead), and the `notes[]` block naming every reason a `removed` might not mean "deleted" |
| 2h | Relevance + cache as the default (PERF-03 / CACHE) | `python -m pytest analyzer/tests/core/test_relevance_default.py -q` | 18 passed — `DEFAULT_RELEVANCE == "ml"` through `AnalyzeOptions` and all four subcommands, the set-aside diagnostic naming the count and the widening flag on the first fixture in the tree the filter actually narrows, and the two diagnostics that legitimately change shape under the default (§11.39 C1, C2) recorded rather than left to be found |
| 3 | Viewer tests | `npm test` in `webview` | 419 pass, 0 fail |
| 3a | Diagram export, viewer half (VIEW-07) | `node --test test/export.test.mjs` in `webview` | 22 pass — one `<g data-node-id>` per planned card and one `<path data-edge-id>` per planned route, in plan order and with `d` byte-identical to the routed edge; the SVG references nothing outside itself; 87 palette tokens equal `styles/tokens.css`; the `@media print` block hides the chrome and releases the world transform; `exportFile` and `requestExport` round-trip |
| 3b | Notebook locations and the order caveat, viewer half (NB) | `node --test test/notebook.test.mjs` in `webview` | 26 pass — a cell-mapped location reads `> cell 3 : 4` on the card, the rail row, the inspector, the tooltip, the search meta and the SVG export; end-ellipsis clips the PATH and never the cell; `openLocation` still posts the flat line and the nine frozen keys; **nothing invents a cell** (a half-written or non-numeric mapping falls back to the flat line); the mapping is lifted off `Node.attrs` where 11.29 N6 puts it; and a `notebook_analyzed` **carrying `codes`** raises the out-of-order banner while one without them draws only the chip (11.29 N10) |
| 3c | Cross-lane bundling (VIEW-04) | `node --test test/bundles.test.mjs` in `webview` | 15 pass — every routed edge still owns its own `points` and `d` (a bundle is a **second** drawing), determinism by JSON equality over two layouts of three corpora, a one-member pair never bundled, members leaving the trunk in target order, trunks **nesting rather than braiding** (containment asserted, the interleaved residue counted), every trunk inside the reserved channel, the channel widened by lane **pairs** and never by more edges, and — the one that matters — **a bundle never hides a finding** |
| 4 | Viewer typecheck | `npm run check` in `webview` | `tsc --noEmit`, clean |
| 5 | Extension typecheck | `npm run check` in `vscode-extension` | `tsc --noEmit`, clean |
| 6 | Extension bundle | `npm run compile` in `vscode-extension` | `out/extension.js` 183.5 kb / `out/test-entry.cjs` 129.5 kb; `compile` also runs `sync-rule-docs` (36 pages) and `sync-walkthrough` (5 pages) |
| 7 | Extension tests | `npm test` in `vscode-extension` | 336 pass, 0 fail |
| 7a | Diagram export, host half (VIEW-07) | `node --test test/export.test.js` in `vscode-extension` | 17 pass — the base64 / 32 MiB / basename guard, the PNG-signature and SVG-opening-tag format check *before* the save dialog, the deferred `requestExport`, and the toast's Open / Copy Path actions |
| 7b | Notebooks, host half (NB) | `node --test test/notebooks.test.js` in `vscode-extension` | 24 pass — with `mlview.includeNotebooks` off `buildAnalyzeArgs` emits the argv it emitted before notebooks existed (asserted as a prefix equality), with it on a finding is republished on the cell's `vscode-notebook-cell:` URI with a cell-relative range, and it degrades one honest step at a time: cell URI → the `.ipynb` → the generated module |
| 7c | Multi-root and configuration, host half (H10 / CFG-ONE) | `node --test test/multiroot.test.js test/config.test.js` in `vscode-extension` | 19 pass — one `FolderState` per open folder with the single-folder window asserted **unchanged**, the Problems panel publishing the **union** (publishing one folder alone used to wipe the other's squiggles), a CodeLens answered with its own file's folder graph, the LM tools resolving the **active** folder rather than `workspaceFolders[0]`, and the settings asserted to be **additive** filters over a `.mlview.toml` that wins `disable` and `exclude` (§11.37 C1's own clause: "the VS Code half asserts it with its own test") |
| 8 | Plugin / MCP tests | `python -m pytest claude-plugin/tests -q -n auto` | 356 passed, 7 skipped in ~23 s (~60 s without `-n auto`) |
| 8a | Notebooks over MCP (NB) | `python -m pytest claude-plugin/tests/test_notebooks.py -q` | 8 passed — `includeNotebooks` on `mlview_analyze` and `mlview_issues`, and in `load_graph`'s **cache key** rather than as a filter applied after: the same sources with and without notebooks are two different documents |
| 8b | Notebooks **under attribution** (NB × CI-ADOPT, HOST-5) | `python -m pytest claude-plugin/tests/test_notebook_attribution.py -q` | 11 passed — `includeNotebooks` survives `changedSince`/`baseline` instead of being dropped on that branch (it reaches `AnalyzeOptions` through `load_attributed`), a baselined run really lists the notebook's MLV101, and where attribution *cannot* carry a notebook finding — its location names the generated `.mlview/notebooks/*.py`, which git does not track, so `--changed-only` drops it — the `note` says so with the count and the notebook's name |
| 8c | The pre-commit hooks are installable (CI-ADOPT d, HOST-2) | `python -m pytest claude-plugin/tests/test_pre_commit_hooks.py -q` | 8 passed, 2 skipped — a `language: python` hook makes pre-commit run `pip install .` in the **clone root**, so the root `pyproject.toml` must exist, declare the `mlview` console script each `entry` names, package `analyzer/src` (never a second copy) and keep its version `dynamic` so gate 9's "one version string" still holds. The two skips are the layers that need tooling this venv lacks: with setuptools present the root metadata is really built into a wheel (`--no-isolation`, no network) and the console script and `schema/*.json` are asserted inside it; with pre-commit installed (`MLVIEW_PRE_COMMIT=<path>`, or on PATH) `pre-commit try-repo` installs a throwaway clone of the **working tree** into a scratch consumer repo and runs the hook — measured here: `Passed`, MLV601/MLV602 reported, exit 0 |
| 8d | Claude Code hooks (H8) | `python -m pytest claude-plugin/tests/test_hooks.py -q` | 32 passed — the `PostToolUse` / `Stop` manifest shape, an immediate exit 0 on a non-Python path or one outside `CLAUDE_PROJECT_DIR`, speech **only when the issue-id set grew** (≤ 5 rows at confidence ≥ 0.6 under a 3 s budget), `MLVIEW_HOOK` = on|stop|both|off, always exit 0 so a hook can never block a session, and the assertion that caught a real defect: the hook must write **neither** `.mlview` **nor** a cache into the user's project |
| 9 | Parity gates | `python tools/verify.py --all` | all 10 gates passed |
| 9a | Scope parity (Python == TypeScript) | `python tools/verify.py --scopes` | 10 projections + 6 error cases, python == typescript (24 assertions) |
| 9b | Scope fixtures current | `python analyzer/tools/gen_scope_fixtures.py --check` | 10 projecting + 6 error cases over the golden, plus the promoted `fuzzCases` on their own graphs |
| 9c | Scope fuzz — promoted counterexamples | `python tools/verify.py --scopes --fuzz 200` | 3 promoted counterexamples replay, python == typescript — each is a minimized document the fuzzer once found the two ports disagreeing on (HEALTH-02) |
| 9d | Scope fuzz — generated graphs | (same command) | 200 cases over 40 generated graphs (5-500 nodes), python == typescript, ~2 s; the seed is printed so `MLVIEW_FUZZ_SEED=<n>` replays it. `.github/workflows/nightly.yml` runs 2000 cases (~16 s) once a day |
| 10 | Plugin manifest | `claude plugin validate ./claude-plugin --strict` | Validation passed |
| 11 | Marketplace manifest | `claude plugin validate ./.claude-plugin/marketplace.json --strict` | Validation passed |
| 12 | Report renders | `node test/render_report.mjs` in `webview` | 20/20 assertions |
| 12b | Clean report renders | `node test/render_report.mjs ../.mlview/report_clean.html --min-ghosts=0` | 20/20 assertions |
| 12c | Scoped report renders | `node test/render_report.mjs ../.mlview/evaluation.html --scope=concern:evaluation` | 23/23 assertions — no empty band, badge-free boundary stubs, the breadcrumb still names the project total |
| 12d | Diagram exports to SVG (also the 20th row of `scripts/e2e`, which produces the `.mlview/graph.json` it reads) | `node test/export_svg.mjs ../.mlview/graph.json` in `webview` | `SVG EXPORT CHECK OK` — 54 of 54 cards, 51 of 51 routed edges, every document edge reached the picture, the only `http` is the `xmlns`, no `url(` / `foreignObject` / `xlink` / `<image` / `<script` / `@font-face` / `@import` / `var(--`, every drawn lane's stage colour present as a literal, well-formed XML, 237 real `<text>` nodes and 180 `<rect>`s |
| 13 | Panel + media bundle | `node --test test/panelhtml.test.js` in `vscode-extension` | 4 pass |
| 13b | Cross-host scope handshake | `node test/crosshost.mjs ../.mlview/graph.json` in `webview` | 28/28 assertions — the real viewer bundle answers the real extension's `setScope`, and `parseUiToHost` / `scopeChrome` accept what it posts |
| 14 | Rule docs current | `python analyzer/tools/gen_rule_docs.py --check` | `docs/rules is current (37 pages)` — 36 rule pages plus the index; 7 of the sixteen ANA-7/8/9 pages carry the optional **What it cannot analyze** section (11.26 A14) |
| 15 | Sample issues current | `python analyzer/tools/gen_expected_issues.py --check` | 15 issues — 5/6/4 |
| 16 | Golden parity | `python -m mlview analyze --demo --json -` vs `contracts/graph.sample.json` | byte-identical, 46 078 bytes |
| 17 | Emitted docs valid | `python contracts/validate_sample.py .mlview/graph.json` | schema 1.0 + 10 invariant groups, 54 nodes / 51 edges / 15 issues |
| 18 | Docs match the tree | `python scripts/check_docs.py` | 19 files (16 docs + 3 shell scripts), no dead paths, every known gap anchored, no build state in a plan doc, LF in every shell script, one graph size, the accuracy headline equal to the baseline, no silent artifact upload, one e2e step count, every shipped roadmap item recorded as landed |
| 19 | End to end | `powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1` | `E2E OK` — 20 steps, 0 failed |
| 20 | Scoped demo artifacts | `python -m mlview analyze samples/vision_pipeline --scope concern:evaluation --depth 1 --html .mlview/evaluation.html` | 17 of 54 nodes (7 core / 7 boundary / 3 context), `data-mlview-scope` and `data-mlview-depth` set on the root |
| 21 | Scope catalogue | `python -m mlview analyze samples/vision_pipeline --list-scopes` | 10 scopable units, biggest first |
| 22 | Bytecode residue never poisons the vendor gate | `python -m pytest claude-plugin/tests/test_vendor_bytecode.py -q` | 3 passed — pytest over a throwaway vendored tree writes no `__pycache__` with the flag set and does write one without it, and `sync-core --check` prunes planted residue and stays green |
| 23 | Accuracy corpus (also a row in `scripts/e2e`) | `python tools/accuracy.py` | `accuracy gate: PASS` — 15 labelled programs, 78 labels, precision **100.0% on every one of the 36 rules**, overall recall 71.8% / 64.1% visible, unseen recall 53.2% raw / 40.4% visible, graph fidelity 90.6%; zero `forbidden` findings, nothing below `analyzer/tests/accuracy/baseline.json` |
| 23c | Accuracy under `--dataflow ip` (DATAFLOW-IP) | `python tools/accuracy.py --dataflow ip` | `accuracy gate: PASS` against a **separate** ratchet, `analyzer/tests/accuracy/baseline.ip.json`, so the two modes cannot mask each other: precision **100.0%**, overall recall **78.2%** / 70.5% visible, unseen **63.8%** / 51.1% visible, graph fidelity 90.6%, zero `forbidden` findings, +5 labels over `local`. The `local` row above is unchanged and unmoved — `baseline_moves()` returns `([], [])` |
| 23a | The same three gates, asserted | `python -m pytest analyzer/tests/accuracy -q` | 37 passed — corpus lint plus the matcher's own semantics |
| 23b | The three rule tiers (ANA-7 / ANA-8 / ANA-9) | `python -m pytest analyzer/tests/rules/test_tier_rules.py -q` | 56 passed — the sixteen new codes, their bad/good fixture pairs, the `GradScaler(enabled=…)` three-way (literal `False` suppresses, non-literal de-rates to 0.6, absent fires), and every ANA-7 finding at or above the 0.60 Problems-panel default |
| 24 | Analyzer byte-equivalence | `python tools/perf_equiv.py --baseline DIR --diff --bench` | both shipped samples byte-identical to `main`; `analyzer/tests/clean` gains exactly one `ValueTag` (PERF-02's fifth IR round), 200-file corpus 2.25x faster |
| 24a | …with the verdict in the exit code | `python tools/perf_equiv.py --compare FILE --expect-same` | `perf_equiv: OK - every corpus is byte-identical`, **exit 0** — PERF-03's `--relevance all` path and the whole of CACHE claim exactly this, and so does the Sprint-5 **default flip**: against a tree identical but for `DEFAULT_RELEVANCE = "all"`, `vision_pipeline`, `vision_pipeline_clean` and `tests_clean` are all `identical` and the run exits 0, which is the evidence §11.39 rests on. `--expect-diff` on the same pair exits **1** (`FAILED - --expect-diff, but every corpus is byte-identical`), which is what a re-baseline that never took effect looks like; either flag with no baseline exits 1 rather than passing silently. **NB claims exactly this for its default path**: against the pre-wave-4 analyzer, `vision_pipeline`, `vision_pipeline_clean` and `tests_clean` are all `identical` and the run exits 0 — `--include-notebooks` is the only thing that changes a document |
| 24b | Relevance prefilter (PERF-03) | `python -m pytest analyzer/tests/core/test_relevance.py -q` | 24 passed — seeds derived from the knowledge tables, k-hop BFS in both directions **after** ANA-3 re-export resolution (`train.py → pkg → pkg/net.py` is one hop), the refusal (no seed ⇒ nothing set aside), and one `config_warning` naming the count and both widening flags |
| 24c | Per-file fact cache (CACHE) | `python -m pytest analyzer/tests/core/test_cache.py -q` | 31 passed — a warm run is **byte-identical** to `--no-cache`, an edited file is `cached: partial` and still byte-identical, a forged or foreign-identity sidecar is ignored rather than obeyed, and nothing is opened or written at all under `--relevance all` (which was the shipped default when this row was written and is now the opt-**out**: since Sprint 5 the default is `--relevance ml`, so the cache is on and a plain `analyze .` writes `<root>/.mlview/cache/`). The 31st stands a Windows in for this platform and asserts the MAC secret reads back **byte-identical** to what was written — without `os.O_BINARY` the ~12% of 32-byte keys containing an `0x0A` are CR-mangled on write and the cache is permanently, silently disabled |
| 24d | Perf budget | `python -m pytest analyzer/tests/core/test_perf_budget.py -q` | 6 passed (adds ~20 s: it builds a 500-file corpus and runs six analyses) — the narrowing ratio, the set-aside diagnostic, the edited-file delta and the sample's byte-identity. The delta row asserts the cache in **hits**, not in seconds: 0/501 cold, 500/1 after one file is edited, 501/0 warm, the warm document byte-identical to the cold one, and wall clock only against an absolute ceiling. A cold-over-warm *ratio* measured 1.45x–2.50x across five runs on this Mac and 1.15x then 1.38x on `macos-latest`; the 1.15x is what reddened `smoke (macos)` on run 34419964015 against a 1.25 bar. The ratio is `1 + saved/common` and its inputs are unsteady — two runs of the **identical** configuration in one macOS job took 1.19 s and 0.76 s — while reading all 501 files, the term first blamed, costs 0.01 s there and 0.12–0.23 s here. Both perf rows print the cold, warm and bytes-only figures they measured; `-rP` shows them for a run that passed (CI-MACOS-01) |
| 26 | Wheel installs and runs | `python tools/wheel_check.py` (also a row in `scripts/e2e`) | `wheel-check: OK mlview-0.1.0-py3-none-any.whl -> mlview 0.1.0, 4 node(s), 2 issue(s) in a clean venv` — built with `python -m build --wheel analyzer`, installed into a throwaway venv, run through the **console script**, then one real analysis so a wheel missing `schema/*.json` cannot pass |
| 27 | VSIX packages and stays small | `npm run package` in `vscode-extension`, then `python scripts/vsix_check.py` | `vsix-check: OK mlview-0.1.0.vsix: 140 files, 661.61 KB (64.6% of the 1 MB ceiling), 88 under extension/core/, 37 rule page(s), 0 bytecode entr(y/ies)` — re-measured after Sprint 5 wave 1, which added six core modules and five walkthrough pages — packaged with no `--allow-missing-repository`. **The checker is the gate, not this row** (HOST-8): the file count and the KB moved twice in Sprint 4 while two hand-copied prose figures did not, so `scripts/vsix_check.py` re-derives all of them — the ceiling, `extension/core/` against `vscode-extension/core` on disk, `extension/docs/rules` against `docs/rules`, and zero `__pycache__` — and echoes what it measured. CI runs it in the `packaging` job, and `scripts/test_vsix_check.py` negative-tests each rule against a synthetic package |
| 29 | Walkthrough pages current (MLV-P11) | `node vscode-extension/tools/sync-walkthrough.mjs --check` | `sync-walkthrough: 5 page(s) up to date` — `media.markdown` resolves relative to the **extension** root, so a page that lives only in `docs/walkthrough/` renders as an empty panel once packaged. Wired into `npm run compile` and `pretest`, the same way `sync-rule-docs.mjs` is |
| 30 | Sample gallery renders (MLV-P11) | `python analyzer/tools/gen_gallery.py --quiet` | 90 self-contained reports + an index from 6 clean programs and 36 rules (84 fixtures), ~30 MB in ~1.4 s, into **gitignored** `docs/gallery/` — a build target would write 30 MB on every build, so this one is run by hand. Not a pass/fail row on its own: what it asserts is on the index, which states that every page is a **single-file** analysis (so MLV301/302/401/501 structurally cannot fire) and flags a `_bad.py` that fired nothing or a `_good.py` that fired its own rule. On this build **neither flag appears** |
| 28 | The icon is what its script renders | `python vscode-extension/tools/make_icon.py --check` | `make_icon: OK ... matches (890 bytes, 128x128)` |
| 25 | CI matrix | `.github/workflows/ci.yml` | On the Sprint 5 process push to `sprint5` (run 34422156964): **all 13 jobs green, `smoke (macos)` among them** — Python 3.10-3.13 (69-109 s each), Node 20/22 (125-137 s), `vscode-extension` 33 s, `claude-plugin` 56 s, `e2e (ubuntu, sh)` 311 s, `e2e (windows, powershell)` 382 s, `packaging (wheel + vsix)` 44 s, the accuracy corpus 13 s and `smoke (macos)` 150 s (of which ~23 s was that push's temporary perf-probe step; without it the job still rounds to 3 min). **6m25s wall and ~68 billable minutes** — 24 for the eleven ubuntu jobs, 7 x 2 = 14 for the one Windows job and 3 x 10 = **30** for the one macOS job, under GitHub's rule that **each job is rounded up to a whole minute on its own** before its runner weight is applied; a branch push with macOS skipped is the other ~38. This is the first run in which the macOS share was **measured** rather than estimated, and it is 30, not the ~20 previously assumed. `README.md`'s CI section quotes the same arithmetic. Both e2e jobs archive `mlview-reports-*` (CI-ARTIFACTS-01). macOS runs on push to `main` and on pull requests, where it is 13 jobs. The review-fix wave took **one** fix iteration, and it was real: `test/mock-vscode.js` keyed its virtual documents by the spelling the test wrote while the extension, after the review round's containment fix, opens the `path.resolve`d one — equal on POSIX, `D:\repo\...` on Windows, so two suppression cases died on `document.lineAt is not a function` in a test double that no other platform could see. The `packaging` job now runs `python scripts/vsix_check.py` in place of the inline `wc -c` |
| 25a | Nightly scope fuzz | `.github/workflows/nightly.yml` | `python tools/verify.py --scopes --fuzz 2000` on a 04:17 UTC schedule plus `workflow_dispatch`, ubuntu 1x, ~16 s of fuzzing. GitHub only schedules cron from the default branch, so it starts firing once this lands on `main` |

Rows 16–18 are also asserted inside rows 2 and 19; they are listed separately
because each is a one-line command that answers a question a reviewer asks
directly ("is the golden still the golden?", "does what it just wrote validate?").

`tools/verify.py --all` is itself ten rows, in this order: one version row, the
`plugin: rule docs` row, the CLI-vs-MCP graph parity row, `vendor: synced core`,
`vsix: synced core` (PACKAGING's condition for a third copy of the analyzer — it
also fails when `.vscodeignore` would drop `core/` out of the package), the two
scope rows (`scopes: fixtures` and `scopes: python == ts`), and three
renderer-hash rows. `--fuzz N` adds two more scope rows to `--scopes`, and only
when asked for: `--all` never fuzzes, so no existing gate got slower. The scope rows sit **between** the analyzer-parity row and
the renderer rows because a projection divergence is an analyzer fact, not a
bundle fact (CONTRACTS 11.15).

---

## build

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipNpmInstall -SkipPipInstall
```

```sh
sh scripts/build.sh
sh scripts/build.sh --skip-npm-install --skip-pip-install
```

1. `webview` — `npm install` + `npm run build` → `webview/dist/mlview.{js,css}`
2. `tools/sync-assets.py` → copies that bundle into `vscode-extension/media/` and
   `analyzer/src/mlview/emit/assets/`
3. `tools/sync-core.py` → copies `analyzer/src/mlview` into **both**
   `claude-plugin/vendor/mlview` and `vscode-extension/core/mlview` (PACKAGING)
4. `vscode-extension` — `npm install` + `npm run compile` + `npm run check`
5. `analyzer` — `pip install -e analyzer`, then `python -m mlview --version`
6. `analyzer` — `python -m build --wheel analyzer` → `analyzer/dist/*.whl`, the
   artifact `pip install mlview`, the CI-ADOPT action and `installCore()` all
   name. A missing `build` prints one line and the build carries on: a publishing
   tool nobody has installed must never redden a developer's build

**The order is not arbitrary.** `generator.rendererSha` is the SHA-256 of the
`mlview.js` the analyzer ships, computed at runtime, so the viewer must be built
and synced *before* the analyzer emits anything you intend to compare. Until
step 2 runs, `rendererSha` is 64 zeros and `--html` produces a plain-table
fallback with a visible "Viewer bundle not synced" banner.

**Step 3 is the one people forget.** Nothing about the Claude Code path fails
loudly when `claude-plugin/vendor/` is stale — the MCP server simply runs an old
analyzer, and a stale `vscode-extension/core/` ships an old analyzer inside the
VSIX. `tools/verify.py --all` reports each of the two as its own row
(`vendor: synced core`, `vsix: synced core`) for exactly that reason.

## e2e

```powershell
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1 -SkipBuild
```

```sh
sh scripts/e2e.sh
sh scripts/e2e.sh --skip-build
```

1. `scripts/build`
2. `python -m pytest analyzer/tests -q`
3. `npm test` in `webview`
4. `npm test` in `vscode-extension`
5. `python -m pytest claude-plugin/tests -q`
6. `python -m mlview analyze samples/vision_pipeline --json .mlview/graph.json
   --html .mlview/report.html`, and the clean twin to `.mlview/graph_clean.json`
   + `.mlview/report_clean.html`
7. `node webview/test/render_report.mjs` — load the report in jsdom and check it
   actually *draws*
8. the same for the clean twin, with `--min-ghosts=0`
9. the three **scoped demo artifacts** — `.mlview/split.html`
   (`--scope unit:train_test_split`), `.mlview/optimization.html`
   (`--scope concern:optimization`) and `.mlview/evaluation.html`
   (`--scope concern:evaluation --depth 1`), the three demos of
   `docs/FEATURES_FLOW_AND_SCOPE.md` section 8 — the depths are the demos'
   own: the per-kind default for B and C, `--depth 1` for D, whose boundary
   ring is what shows *what feeds* evaluation. The step also measures every
   report the run wrote against amendment A4's contracted **100 KB – 2 MB**
   band and prints the range in the table, because a KB figure written into a doc
   rots the next time the bundle grows (MLV-R1-H06). One thing to expect in
   Demo B: lane placement wins over containment, so `train_test_split` (stage
   `data`) draws in the DATA lane *beside* its `baseline()` frame (stage
   `preprocess`) rather than inside it — the pre-existing rule that a node whose
   parent sits in another stage is promoted to a root of its own lane, which the
   scope projection deliberately leaves untouched
10. the same jsdom render check over `.mlview/evaluation.html`, with
    `--scope=concern:evaluation` — the breadcrumb, the "not in this scope" chip
    row, and only the scope's cards. It reports SKIP, with the reason, when the
    viewer has no `--scope=` flag or when the report inlines a bundle that is not
    the one `webview/dist` holds (a report written before `tools/sync-assets.py`
    ran embeds a pre-scope viewer, which the bundle-hash gate already reports)
11. `node --test vscode-extension/test/panelhtml.test.js` — the panel HTML points
    at the two files `sync-assets.py` wrote, and they are on disk
12. `node webview/test/crosshost.mjs` — the **cross-host scope handshake**: the
    real `webview/dist/mlview.js` answers the real `setScope` message, and the
    real `vscode-extension/out/test-entry.cjs` parses what it answers. Both
    CONTRACTS §11.7 suites otherwise stand on one side of the wire — the viewer
    posts into a recording bridge, the extension reads a hand-written object — so
    nothing else would catch the selector field drifting from `spec` to `scope`.
    SKIPs, with the reason, when the extension's test bundle is not built
13. `python tools/wheel_check.py` — PACKAGING's row: build the wheel, install it
    into a throwaway venv, run `mlview --version --json` through the **console
    script**, then one real analysis, so a wheel missing its package data cannot
    pass. Reports SKIP, with the reason, when there is no wheel to test
14. `python tools/verify.py --scopes` — the Python projection and the TypeScript
    port project the same battery identically
15. `python tools/verify.py --all` — the parity gates
16. `python tools/accuracy.py` — the labelled accuracy corpus (ANA-12's referee):
    zero forbidden findings, nothing below `analyzer/tests/accuracy/baseline.json`
17. `python scripts/test_check_docs.py` — the doc gate's own self-test (it also runs `test_doc_numbers.py` and `test_vsix_check.py`)
18. `python scripts/check_docs.py` — the docs still match the tree
19. the PASS/FAIL table

**Every step runs even when an earlier one failed.** A run that stops at the
first failure hides the other eighteen, and the whole point of the table is to see
the state of the system in one screen. The exit code is 1 if anything failed.

**SKIP is not FAIL.** Both sample workspaces are present now, so they run; the
sample steps report `SKIP` instead of failing on a checkout where `samples/` is
absent, because the samples are the rules agent's deliverable (amendment A12),
not a precondition for the rest of the build.

`MLVIEW_NO_OPEN=1` is set for the whole run, so nothing launches a browser.

### Why steps 7-9 exist

Every other gate proves the report *parses*. Neither proves it *renders*: a
viewer that mounted and drew nothing, or an extension pointing at a bundle the
sync never wrote, would sail through all of them. Step 7 loads
`.mlview/report.html` in jsdom exactly as a browser would — the inlined bundle,
the inlined graph, the real bootstrap — and asserts the node cards, all three
severity marker shapes, every declared ghost slot, the seven lane bands, the
"not detected" chip row, a clean console, and that clicking a card really posts
`openLocation` with `vscode://file/<abs>:<line>:<col+1>`. Step 8 runs the same
check over the clean twin, which draws no markers and declares no ghosts at all.
Step 9 does the same job for the VS Code panel.

```sh
cd webview
node test/render_report.mjs                                   # the dirty sample
node test/render_report.mjs ../.mlview/report_clean.html --min-ghosts=0
```

The clean twin has no findings and therefore no ghost slots, so it wants
`--min-ghosts=0`; every ghost a document *does* declare must still be drawn.

### Why the scope gate exists

Feature 2 is one algorithm written twice — `analyzer/src/mlview/core/project.py`
in Python and `webview/src/scope/project.ts` in TypeScript — because the CLI must
be able to project a document without a browser and the report must be able to
re-scope without an analyzer. Two implementations of one specification drift; the
only question is whether anyone finds out.

So the battery is data, not code: `contracts/scope.cases.json` names ten
selectors plus six error codes, `contracts/scope.expected.json` holds what the
Python `project()` produces for each of them, and both are computed over the
**frozen** `contracts/graph.sample.json` so a rule change can never redden this
gate. `python tools/verify.py --scopes` regenerates the fixtures and byte-diffs
them (writing nothing), then runs `webview/test/scope_parity.test.mjs`, which
pushes the same cases through the TypeScript port and deep-compares the node,
edge and issue id lists **in order**, every `issue.nodeIds` (so the stable
rotation is checked), every node's `viewRole`, all eight stage rows, `stats`, and
the whole `view` object.

```sh
python tools/verify.py --scopes                       # both halves
python analyzer/tools/gen_scope_fixtures.py --check   # just the Python half
cd webview && node --test test/scope_parity.test.mjs  # just the TypeScript half
```

A Python-side change the port did not follow fails here rather than shipping two
different answers to one question.

### Why the doc gate exists

A README's "known gaps" list is the part a reviewer weighs most, and it rots
silently: someone fixes the test, nobody deletes the bullet that says it fails,
and the honesty section is now wrong in the direction that costs the most
credibility. `check_docs.py` fails the run when a current-state doc names a file
that is not on disk, links to a Markdown file that is not there, or claims a
test fails while that test is in the tree and green.

Round 2 found the hole in that: a bullet does not have to name a test to be
stale. The README described the absence-rule framework gate as workspace-wide
long after `ctx.wrappers_for()` made it per-module, and nothing could tell
(MLV-R2-109). So two more checks now apply inside a "Known gaps" section, and
only there: every bullet must cite a repo path or a code symbol in backticks,
and every symbol it cites must still exist somewhere under `analyzer/`,
`webview/`, `vscode-extension/`, `claude-plugin/`, `tools/`, `scripts/`,
`contracts/` or `samples/`. Rename the code a gap describes and the build fails
on the sentence that describes it, which is the only moment anyone will reread
it. Docs never vouch for docs: the symbol index is built from source only.
Frozen design records
(`docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md`, `docs/ISSUE_RULES.md`,
`docs/UX_DESIGN.md`) are link-checked only — they describe what was *planned*,
and editing them to match the build would erase the decision record.
`docs/CONTRACTS.md` is normative and is never touched by the gate.

That exemption cuts both ways, which round 1 found the hard way: the flow and
scope pass rewrote part of `docs/UX_DESIGN.md` in the present tense to describe
the shipped UI, and because a plan doc is link-checked only, none of those
current-state claims was covered by anything (MLV-R1-H08). So a sixth check
now runs over the plan docs and only them: a sentence that reports the state of
the build — “is now built”, “has been shipped”, “already implemented” — fails the
run there. Design prose is untouched (“the DOM is built with `createElementNS`”
describes a mechanism, not a milestone). What shipped belongs in `README.md` or
`docs/STATUS.md`, where checks 1–5 apply to it.

Round 2 of the feature pass added two more checks, for a rot that has nothing to do with prose. That pass rewrote `scripts/e2e.sh` — the documented POSIX twin of `scripts/e2e.ps1` — from LF to CRLF. Git Bash's `igncr` swallows the stray carriage returns, so the Windows gate stayed green while the file was broken on every platform it exists for: the shebang then names a program called `sh<CR>`, `SKIP_BUILD=0<CR>` makes `[ "$SKIP_BUILD" -eq 1 ]` an illegal-number error, and `OUT="$REPO_ROOT/.mlview"<CR>` writes every report into a directory called `.mlview<CR>` (MLV-R2-H02). So **check 7** requires LF in every `*.sh` in the tree, and forbids a checked doc from *mixing* the two conventions — the same pass flipped `docs/STATUS.md` and this file wholesale, which turned two one-line edits into 400-line rewrites and let a stale figure ride through review unread. **Check 8** is that figure: `docs/STATUS.md` said the demo graph had 39 edges while this file said 45 (MLV-R2-H05). One run produces one graph, so every `N nodes / M edges` claim about `samples/vision_pipeline` — or the `.mlview/graph.json` it emits — must agree with every other one in the doc set. Neither check can be satisfied by editing the sentence that trips it, which is the point.

Sprint 3 added three more, in `scripts/doc_numbers.py`, for a rot the first eight cannot see: a number that is
*written correctly* and is *no longer true*. **Check 9** compares `docs/ACCURACY.md`'s headline — precision, the
three recall readings, and graph fidelity — with `analyzer/tests/accuracy/baseline.json`, the ratchet the
accuracy gate actually enforces. The two had already split apart: the ANA-1 re-baseline re-recorded graph
fidelity 0.6619 → 0.8633 and left the document publishing *"92 of 139 hand-labelled ops, 66.2%"*, explained by a
class-method blind spot the same branch had repaired (TB-08). Nothing caught it because `docs/ACCURACY.md` was
in neither glob and so was checked by nothing at all, not even for dead links; it is a current-state doc now.
**Check 10** is the mirror image in CI: `actions/upload-artifact` skips dot-paths unless
`include-hidden-files: true` is set, so both e2e jobs uploaded `.mlview/*.html`, matched nothing, warned rather
than failed, and four consecutive green runs archived zero artifacts while `README.md` said otherwise
(CI-ARTIFACTS-01). **Check 11** counts the rows each e2e driver can print, requires the PowerShell and the
POSIX flavour to print the *same* table, and holds every "N steps" claim on a line naming `e2e` to that count —
because the reason ANA-12's accuracy row was left out of both drivers was that four documents quoted "17 steps"
(ANA12-E2E-05). All three are stdlib-only and read files the gate already opens.

```sh
python scripts/check_docs.py              # the repo
python scripts/check_docs.py --root DIR   # any tree
python scripts/test_check_docs.py         # the gates' own tests, all 56
python scripts/vsix_check.py              # the packaged VSIX, after `npm run package`
```

### Pushing a change that touches `.github/workflows/`

`origin` is the **HTTPS** URL and the stored credential is a repository-scoped
PAT with no `workflow` scope, so GitHub rejects any push whose diff touches
`.github/workflows/**` — including this sprint's `ci.yml` and `nightly.yml`
changes, and including the `packaging` job's `scripts/vsix_check.py` step. Push
those over **SSH** (`git remote set-url origin git@github.com:realmyang/MLView.git`,
or a one-off `git push git@github.com:realmyang/MLView.git HEAD:<branch>`), or
add the `workflow` scope to the PAT. **Until the PAT gains that scope, every
push on this project goes over SSH** — `git push git@github.com:realmyang/MLView.git HEAD:<branch>`
— because whether a given diff touches a workflow file is not something to
discover after writing the commit.

This is written down because it has already cost work once: a **20th e2e step**
— `webview/test/export_svg.mjs`, gate row 12d, wired into both drivers — was
implemented, passed, and then reverted, because promoting it also means editing
the two "19-step" comments in `ci.yml` to keep `doc_numbers.py`'s step-count
rule green, and that push could not be made over HTTPS. **That promotion landed
in Sprint 5** (PROC-12), over SSH: the step is `export diagram (SVG)` in both
drivers and the table is 20 rows.

## Environment

Both scripts export `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` before running
anything. The Windows console is cp1252, and without those a single non-ASCII
identifier or path corrupts the JSON on stdout.

They also export `PYTHONDONTWRITEBYTECODE=1`. The plugin suite imports the
vendored analyzer in-process, and the `__pycache__` trees CPython would leave
under `claude-plugin/vendor/` are bytecode that would ship with the plugin —
which the vendor gate, running right after, used to report as drift (HEALTH-01).

Set `PYTHON=/path/to/python` to choose an interpreter for the `.sh` scripts;
otherwise `pythonpick.sh` finds one. `MLVIEW_PERF_BUDGET_MS` overrides the
viewer's layout budget, which otherwise scales itself against a calibration
workload run in the same process and doubles under `CI`.

Everything runs offline. `npm install` resolves entirely from the local npm
cache, `pip install -e analyzer` has no dependencies, and neither `torch` nor
`scikit-learn` is installed — the analysis is purely static and must never
require them.

## Related tooling

| Tool | Purpose |
|---|---|
| `tools/sync-assets.py [--check]` | The only writer of `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`. |
| `tools/sync-core.py [--check]` | The only writer of `claude-plugin/vendor/` **and `vscode-extension/core/`** — the two vendored analyzers that let the plugin and the VSIX run with no pip install. |
| `tools/wheel_check.py [--no-build]` | PACKAGING's acceptance: build `analyzer/dist/*.whl`, install it into a throwaway venv, run `mlview --version --json` through the console script, then one real analysis. Exits 0 with a message when there is no wheel to test, non-zero when there is a broken one. |
| `tools/action/action.yml` | CI-ADOPT's composite GitHub Action: install MLView, `analyze --changed-since <base> --changed-only --sarif`, and a `sarif` output for `github/codeql-action/upload-sarif`. |
| `analyzer/tools/gen_gallery.py [--quiet]` | MLV-P11's renderer: 90 self-contained reports plus an index, from the 6 clean programs and the 36 rules' 84 bad/good fixtures, into **gitignored** `docs/gallery/`. Run by hand — a build target would write 30 MB on every build. |
| `vscode-extension/tools/sync-walkthrough.mjs [--check]` | The only writer of `vscode-extension/docs/walkthrough/`, on the same pattern as `sync-rule-docs.mjs`: `media.markdown` resolves relative to the extension root, so a walkthrough page that lives only in `docs/walkthrough/` renders as an empty panel once packaged. `npm run compile` and `pretest` run it. |
| `vscode-extension/tools/make_icon.py [--check]` | Renders `media/icon.png` (128x128) from arithmetic, so the marketplace icon is source rather than a binary nobody can regenerate. |
| `tools/verify.py [--parity\|--scopes\|--hashes\|--versions\|--vsix\|--all]` | The parity gates: one analyzer, one projection, one renderer, one version — ten rows, including `plugin: rule docs`, `vendor: synced core`, `vsix: synced core` and the two scope rows. |
| `tools/accuracy.py [--dataflow local\|ip]` | ANA-12's referee: scores the labelled corpus under `analyzer/tests/accuracy/corpus/` for precision, recall, graph fidelity and calibration, and gates on `baseline.json` — or, with `--dataflow ip`, on `baseline.ip.json`, a **separate** floor so the two dataflow modes cannot mask each other. Either ratchet refuses a downward move without `--allow-regression "reason"` and refuses to write at all while a `forbidden` finding fires. `docs/ACCURACY.md` says what the numbers mean; its §6 covers `ip`. |
| `tools/perf_equiv.py [--baseline DIR\|--record FILE\|--compare FILE]` | PERF-01/02's referee: proves an analyzer optimisation moved no byte, over three corpora, each tree in its own subprocess. |
| `tools/gate_scopes.py` | Gate 5's implementation, called by `tools/verify.py --scopes`: the fixture drift check plus the viewer's parity test. |
| `analyzer/tools/gen_scope_fixtures.py [--check]` | Regenerates `contracts/scope.cases.json` and `contracts/scope.expected.json` from the Python `project()`. |
| `analyzer/tools/scope_gen.py` | HEALTH-02's generator: seeded, schema-valid documents (5-500 nodes, hierarchies, ghosts, colliding names, edge-anchored issues), every one validated by `contracts/validate_sample.py` before it is projected. |
| `analyzer/tools/scope_fuzz.py [--cases N] [--seed N] [--promote]` | HEALTH-02's differential fuzzer over the two `project()` ports. `--promote` minimizes a counterexample by delta debugging and appends it to `contracts/scope.cases.json`'s `fuzzCases`. It found the §11.30 divergence on its first 200 cases. |
| `analyzer/tools/gen_rule_docs.py [--check]` | Regenerates `docs/rules/*.md` from the rule registry. |
| `analyzer/tools/gen_expected_issues.py [--check]` | Regenerates `samples/vision_pipeline/expected_issues.json`. |
| `webview/test/render_report.mjs` | Renders a standalone report in jsdom and checks what it drew. |
| `contracts/validate_sample.py <graph.json>` | Schema + all ten invariant groups on any emitted document. |
