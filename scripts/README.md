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
| `check_docs.py` | The doc gate, checks 1-8, 12 and 21 (9-11 and 19-20 live in `doc_numbers.py`, 13-15 and 23 in `doc_figures.py`, 16-18 in `doc_surfaces.py`, 22 in `doc_claims.py`): dead paths, dead Markdown links, "known gap" bullets that still describe a failure somebody already fixed, gap bullets that cite nothing checkable or cite a symbol that has been renamed away, a frozen design record that has started reporting build state, a POSIX shell script written with CRLF, two docs that disagree about the size of the demo graph (check 8 now reads a two-line window and accepts `N nodes and M edges`, both of which a wrapped claim used to escape), and a roadmap item that `docs/STATUS.md` reports as shipped while `docs/ROADMAP.md` carries no `**Landed ...**` measurement note for it (check 12, PROC-01), and a known gap that names its own retirement condition when the condition is already met — `README.md` waited for a `--group-by` flag that had been in `analyzer/src/mlview/cli.py` for two sprints, and check 4 could not see it because the bullet cites a real path (check 21, HOSTS-UX-R2-07). |
| `doc_numbers.py` | The doc gate, checks 9-11 and 19-20 — the claims a machine can settle: `docs/ACCURACY.md`'s headline against `analyzer/tests/accuracy/baseline.json`, an `upload-artifact` step whose hidden path would silently upload nothing — check 10 resolves `${{ env.NAME }}` against the workflow's own `env:` block, because PUB-01 wrote the same defect a second time with the dot-directory spelled through a variable and the check saw a path with no dot in it — and an "N steps" claim that is not the number of rows both e2e drivers print. Check 19 parses the command lines a workflow generates with the invoked tool's own `build_parser()` — `public-corpus.yml` built `public_corpus.py fetch --repo <names>`, argparse exited 2 on it, and every dispatch that used the documented input died at the job's first step (PUB2-10). Check 20 refuses a closed list of rule codes for the interprocedural hop weight unless a constant in `analyzer/src/mlview/rules/` holds one: `docs/ACCURACY.md` named two rules where the measurement found three, and the mechanism charges whichever rule read the widened value (VIS2-17). |
| `doc_figures.py` | The doc gate, checks 13-15 and 23 — the figures the three *living* docs (`README.md`, `docs/STATUS.md`, `scripts/README.md`) keep requoting: `docs/STATUS.md`'s Components table against the newest `**Gates` paragraph of the same file and its `core/mlview` count against what `tools/sync-core.py` copies (REV5-05), any `N selectors` / `N error cases` / `N promoted counterexamples` claim against `contracts/scope.cases.json` — spelled-out numbers included, which is what "the ten-selector battery" was (REV5-08), and two documents naming two different runs as "the last full green push" (REV5-07). A dated record is exempt: check 8's `at the time` escape applies, and the bundled-core count is read out of table rows only. Check 23 is the one place the doc gate reads `docs/CONTRACTS.md`, which is otherwise in `check_docs.SKIP`: §7's four `mlview diff` node counts, its four edge counts and its headline against `analyzer/tests/core/test_diff.py`, read as text. §7 had three mutually inconsistent figure sets for one command and named those tests as its only pins while disagreeing with them (REV-04); the check is anchored on the `## 7.` heading so §17's errata keep quoting the superseded figures they exist to record. |
| `doc_surfaces.py` | The doc gate, checks 16-18 — the *lists* a document shares with the tree, where the other ten checks compare a number: every selector `SCOPE_KINDS` accepts against the four lists a person reads (`mlview analyze --help`, `README.md`, both `claude-plugin/commands/*.md`) — `pipeline:` and `symbol:` parsed everywhere and were advertised on none of them (HOSTS-UX-DOCS-PIPELINE); the directory `tools/public_corpus.py` fills against `.gitignore`, which had no entry for it while the module docstring called it git-ignored (PUB-17); and the test files a package's `test` script runs against the ones on disk — `webview`'s named its thirty one by one, so three new regression files never ran and `npm test` still printed a green suite (HOSTS-UX-WEBVIEW-RUNNER). |
| `doc_claims.py` | The doc gate, check 22 — the one claim with no machine-readable copy anywhere: a **green** verdict and the **CI matrix** inside one paragraph of a living doc, unless that paragraph also says whether the matrix ran. `README.md` opened "What is verified, and what is not" with *"green on the build machine and on the CI matrix"* and `docs/STATUS.md` said "on every push, across the CI matrix", while every job of every push on the branch came back unstarted for a billing block — the standing rule *state what you could not check* failing on the two pages a newcomer reads first (DOCS-CI-OVERCLAIM, CONTRACTS §17 E28). A doc may describe the matrix, name it, or report one identified run that really was green; saying the matrix has not run is the escape. Paragraphs, not lines: the original claim was wrapped across two. |
| `pythonpick.sh` | Sourced by both `.sh` drivers: finds a Python 3.10+ and exports `PYTHON`. `python` first under Git Bash, `python3` first elsewhere, because on Windows `python3.exe` is usually the Store alias and on Linux/macOS `python` usually does not exist. |
| `vsix_check.py` | The packaged-VSIX gate (HOST-8): the 1 MB ceiling, `extension/core/` against `vscode-extension/core` on disk, `extension/docs/rules` against `docs/rules`, and zero `__pycache__` — then it echoes the file count and the KB, so the measurement lives in the run rather than hand-copied into two docs that drift. Run it after `npm run package`; CI's `packaging` job does. |
| `vscode-extension/tools/vsix_smoke.py` | `vsix_check.py`'s twin since C2, and the reason an untracked bundled core is safe: `vsix_check.py` proves the package *contains* an analyzer, this one proves the analyzer it contains *runs*. It unzips the VSIX, puts `extension/core` on PYTHONPATH the way `coreClient.ts` does, and from a cwd outside this repository imports `mlview` (asserting the module resolved **inside the unzip**, not from an installed copy), checks its version against `vscode-extension/package.json`, emits `--demo` and compares it byte for byte with `contracts/graph.sample.json`, and analyzes a real file so the schema, the rule pack and the knowledge tables are exercised rather than replayed. CI's `packaging` job runs it after `vsix_check.py`. |
| `vscode-extension/tools/sync-core.mjs` | The builder for the one analyzer copy that is **not** in git (C2). `vscode-extension/core/mlview` is gitignored and written at build time; `npm run compile`, `npm run pretest` and `vsce package`'s `vscode:prepublish` all run this first. It finds a Python 3.10+ the way `pythonpick.sh` does (`MLVIEW_PYTHON` overrides) and hands off to `tools/sync-core.py` — one copier, one set of skip rules, one gate. |
| `test_check_docs.py` / `test_doc_numbers.py` / `test_doc_figures.py` / `test_doc_surfaces.py` / `test_doc_claims.py` / `test_vsix_check.py` | The gates' own test suite — 132 cases: a hundred and five throwaway trees, four unit tests (the symbol parser, the one spelling of `all` that counts as an advertisement, the workflow-step block scoper, and check 22's paragraph joiner), and twenty-three that read the real repo. Running any one file runs all of them; `pytest scripts` does too. |

---

## The gate table

[![CI](https://github.com/realmyang/MLView/actions/workflows/ci.yml/badge.svg)](https://github.com/realmyang/MLView/actions/workflows/ci.yml)

Every gate below runs in CI, in **two tiers** (C6). A **push** runs the analyzer
on Python 3.10 and 3.13, the viewer on Node 20, the extension suite, the plugin
suite, the accuracy corpus and the Linux end-to-end table — seven jobs, **7m49s**
of wall. A **pull request, and a push to `main`,** adds Python 3.11 and 3.12,
Node 22, the Windows end-to-end table, the macOS smoke job and packaging — six
more jobs, and the pull request answers in **12m03s**. Nothing reaches `main`
unchecked on any supported interpreter, either e2e driver or any of the three
platforms; the tiers move **when** the expensive half runs, not whether. A push
that touches only `**.md` and `docs/` runs nothing at all, and a pull request
deliberately has no such exemption, so a docs-only branch is still checked before
it merges. The two tiers never overlap: the cheap jobs keep the same-repository
double-billing guard and the expensive ones run exactly on the events that guard
excludes (see `.github/workflows/ci.yml`, whose header carries the arithmetic,
and the "Continuous integration" section of the root README for the job table).
**Row 25 is the measurement, and as of 2026-09-15 it is a reading rather than an
estimate.** Run 34975663652 took the seven cheap jobs and run 34975667772 the six
full ones, on the same commit of `public`; all thirteen came back green, and it
is the first time every job in `.github/workflows/ci.yml` has executed on any
branch of this project — the account's Actions billing was blocked for the two
days the consolidation and the recall campaign were written. There are three
exceptions. Rows 10 and 11: `claude
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
| 2 | Analyzer + rules | `python -m pytest analyzer/tests -q` | 2654 passed, 9 skipped and 24 xfailed on 3.12+ (two skips are the 3.10/3.11 `tomllib` split in both directions, two are the offline-HTML fallback a synced viewer bundle makes unreachable, four want public-corpus clones under `MLVIEW_PUBLIC_CORPUS_DIR` — set it and they run — and one is a rule probe that says in words what it could not resolve). On 3.10 / 3.11 eight more skip: `analyzer/tests/fixtures/robustness/syntax/{pep695,fstrings}` are written in 3.12-only syntax and MLView parses with the host's own `ast`, so those hosts cannot read them at all — asserting `filesFailed == 0` there would be a claim about a file the host cannot open. Both read green on a 3.13 laptop and red on the matrix |
| 2a | Framework recognition (FW-RECOG) | `python -m pytest analyzer/tests/core/test_framework_recognition.py -q` | 29 passed — the seven-call `tf.data` chain is 7 connected nodes, `take`/`skip` are **not** split-kind, `datasets.Dataset.train_test_split` is split-kind and arms MLV602, every Lightning hook lands in the lane the framework runs it in, and a Keras file never picks up a torch framework |
| 2b | Unresolved callees (ANA-5a) | `python -m pytest analyzer/tests/core/test_unresolved_callee.py -q` | 13 passed — 5 `unknown` ops on the odd-syntax fixture, one `unresolved_callee` diagnostic naming the lambda / `match` case / `default_factory` constructs, the scope-wide dynamic flag **not** widened, and the demo's 15 confidences pinned |
| 2c | Notebook ingest (NB) | `python -m pytest analyzer/tests/core/test_notebooks.py -q` | 26 passed — the untouched default path (a `.ipynb` is still counted and skipped, asserted as a string equality), the four-cell leak notebook exiting **0** through the CLI with MLV101 at cell 2 and MLV201 at cell 3, every magic shape (line magic, `!` shell escape, `?` help query, `%%bash` blanked whole, `%time model.fit(X, y)` keeping the call), the `%` that is an operator and not a magic, the order-verdict table, the failure accounting and both config paths |
| 2d | Notebook locations re-slice (NB / R2.1) | `python -m pytest analyzer/tests/core/test_locations.py::test_notebook_locations_resolve -q` | 3 passed — every `Loc` in a generated module re-opens and slices the text that was actually analyzed, over `leak.ipynb`, `leak_out_of_order.ipynb` and `odd_cells.ipynb` |
| 2e | Interprocedural dataflow (DATAFLOW-IP) | `python -m pytest analyzer/tests/core/test_dataflow_ip.py -q` | 51 passed — the ctor / return / method-arg / projection summaries in **both** modes, `local` silent where `ip` fires, the intersection over call sites (never the union), the `0.8 ** hops` de-rating asserted **numerically** (0.95 → 0.760 → 0.608 → 0.486), the `truncated` diagnostic a chain past the 3-hop cap must produce, and the "parameter merely named `X`" probe silent in both modes |
| 2f | One configuration surface (CFG-ONE) | `python -m pytest analyzer/tests/core/test_config.py -q` | 23 passed, 1 skipped on 3.11+ / 5 passed, 19 skipped on 3.10 — a configuration file needs `tomllib`, stdlib only from 3.11, and the skip is never silence: the 3.10-only sibling asserts that `core/config.py` says `tomllib is unavailable`, names the file it ignored, still finishes the analysis and still reports the rule it could not disable. Otherwise: `--config` / `.mlview.toml` / `[tool.mlview]` first-match-wins with the winner named in `workspace.configPath`, TOML winning `disable` and `exclude` while a flag may only add, CLI winning every `[analysis]` option, every malformed input reduced to one `config_warning` and never fatal, and the one case the precedence cannot see (a flag typed at exactly its default) pinned rather than papered over |
| 2g | Diff overlay (VIEW-08) | `python -m pytest analyzer/tests/core/test_diff.py -q` | 20 passed — a second document kind (`mlview-diff`), per-node / per-edge / per-issue status on the §0 stable ids, a 20-blank-line insertion producing **zero** changed nodes (`loc` is outside the key, `moved: true` is recorded instead), and the `notes[]` block naming every reason a `removed` might not mean "deleted" |
| 2h | Relevance + cache as the default (PERF-03 / CACHE) | `python -m pytest analyzer/tests/core/test_relevance_default.py -q` | 18 passed — `DEFAULT_RELEVANCE == "ml"` through `AnalyzeOptions` and all four subcommands, the set-aside diagnostic naming the count and the widening flag on the first fixture in the tree the filter actually narrows, and the two diagnostics that legitimately change shape under the default (§11.39 C1, C2) recorded rather than left to be found |
| 2i | Structured fixes (H5) | `python -m pytest analyzer/tests/rules/test_fixes.py -q` | 49 passed — the acceptance is the five parametrized `test_fix_makes_the_rule_stop_firing` cases, which apply every edit to the bad fixture, `ast.parse` the result, **re-analyse it as a workspace** and assert the rule stops firing *and* that the code set gains nothing new. Also: the opt-in (a test fails if any rule outside `FIX_CODES` has `fix=` in its source), the `likely` floor asserted from both sides by MLV602 alone (the unseeded fixture is `certain` and gets an edit; the globally-seeded one lands `possible` and gets none), `apply_edits`'s UTF-8 byte arithmetic refusing overlaps, and the four refusals — each a fixture that still **fires the finding** and keeps its prose hint |
| 2j | Config resolution (ANA-10) | `python -m pytest analyzer/tests/core/test_config_values.py -q` | 30 passed — the four shapes and nothing else, the probe ladder (`num_workers=4` certain 0.98 → `CFG["workers"]` **likely 0.784** → one hop possible 0.627), **intersection not union** across call sites, the 2-hop cap, one config node per container with `config` edges into every consumer across files, the `getattr` selection drawn in both branches without inventing an FQN, the `config_unresolved` diagnostic for the deferred YAML/Hydra half, and the assertion that nothing in `ir/config_*.py` opens, imports, `exec`s or compiles anything — checked against the AST, not the text |
| 2k | Hierarchical rollup (PERF-04) | `python -m pytest analyzer/tests/core/test_rollup.py -q` | 59 passed — the guarantee that pays for the whole item is **`edges_lost == 0` and zero floating cards at every budget**, asserted on a 525-file synthetic (25 experiments over a shared `common/`, uncapped 1972 nodes / 2273 edges / 126 findings) at caps 2000 / 400 / 100 / 45. Measured against the deletion it replaces: at cap 100 the old cap drew **25 edges (1.1%) and 50 floating cards** and silenced 26 of 126 findings; the rollup draws **155 edges (6.8%), 0 floating cards and all 126 findings**. Also: an uncapped document is untouched (the function returns before mutating anything), a ghost is never folded (§11.46 A5), a parallel merge keeps the label only when the members agreed, and the `truncated` diagnostic counts what it absorbed, merged and lost |
| 2l | Multi-pipeline workspaces (MLV-P12) | `python -m pytest analyzer/tests/core/test_pipelines.py -q` | 23 passed — the one clause the item lives or dies on, that the closure **includes but does not expand through** another entrypoint's own nodes (without it ten scripts sharing a `utils.py` are one pipeline), the owner rule that keeps a script's own seeds its own, `test_the_three_numbers_a_user_sees_are_one_number` (`exclusiveCount` == `|core(E)|` == `view.counts.core` at depth 0 == the `--list-scopes` SUBTREE column), a shared node forced to `viewRole: context` and never `boundary`, and the block emitted **only** at two or more non-empty pipelines so a single-entrypoint workspace is byte-identical to before |
| 2n | Sprint-5 review findings (regression) | `python -m pytest analyzer/tests/core/test_review_fixes.py -q` | 28 passed on 3.11+ (26 passed, 2 skipped on 3.10, where the two `--config` cases have no TOML parser to exercise) — one test per confirmed finding, each written to fail on the code as it was rather than on an incidental detail of the fix: MLV101 never matching a split in another function (in **both** dataflow modes) while still firing inside one, no finding whose prose says a fit happened *before* a split written on an earlier line, `--dataflow ip` disclosing the cross-scope match it refuses instead of dropping it in silence, MLV121 and MLV110 refusing to assert an absence they cannot see, a `CFG["workers"] = 0` invalidating the literal ANA-10 materialised two lines above it, `args = get_args()` resolving as an argparse root, ANA-10's caps publishing a `truncated` diagnostic, one `np.asarray()` no longer dropping the data tag, and an explicit `--config` naming a `[tool.mlview]`-less `pyproject.toml` warning instead of applying nothing in silence |
| 2o | The gallery index measures its own blind spot | `python -m pytest analyzer/tests/core/test_gallery.py -q` | 4 passed — `blindspot_caveat` reads the rendered pages: it may not name a cross-file rule as silent when that rule fired on one of them, and the `single_file_analysis` count is the number of pages that carry one. Row 30 is what it protects |
| 2m | The fuzzer generates both new shapes (HEALTH-02) | `python -m pytest analyzer/tests/core/test_fuzz_shapes.py -q` | 18 passed — a generated document held to §11.46 C1-C5 and §11.47 D, its `pipelines[]` block byte-identical to `pipelines_block`'s own output (so no generated document is one the analyzer could not emit), a minimized document **re-derived** rather than left stale, and an unsupported shape *reported* (`NOT GENERATED: the schema declares no root pipelines[]`) rather than skipped quietly |
| 3 | Viewer tests | `npm test` in `webview` | 585 pass, 0 fail, 1 todo — hardening round 2 closed five of round 1's six: the drag-pan guard now names every canvas overlay (`HOSTS-UX-LEGENDPAN`) and the Findings panel's clean state names its blind spots (`HOSTS-UX-CLEANSTATE`). The one left is the legend's missing Escape rung, which needs a contract amendment rather than a line, and its `todo` string says so. The runner is `webview/tools/run-tests.mjs`, which **discovers** `test/*.test.mjs` (CONTRACTS 11.54 C1): the enumeration it replaced had gone three files stale, so three regression suites written in hardening round 1 ran green when invoked by hand and were invisible to `npm test` and to CI |
| 3a | Diagram export, viewer half (VIEW-07) | `node --test test/export.test.mjs` in `webview` | 22 pass — one `<g data-node-id>` per planned card and one `<path data-edge-id>` per planned route, in plan order and with `d` byte-identical to the routed edge; the SVG references nothing outside itself; 87 palette tokens equal `styles/tokens.css`; the `@media print` block hides the chrome and releases the world transform; `exportFile` and `requestExport` round-trip |
| 3b | Notebook locations and the order caveat, viewer half (NB) | `node --test test/notebook.test.mjs` in `webview` | 26 pass — a cell-mapped location reads `> cell 3 : 4` on the card, the rail row, the inspector, the tooltip, the search meta and the SVG export; end-ellipsis clips the PATH and never the cell; `openLocation` still posts the flat line and the nine frozen keys; **nothing invents a cell** (a half-written or non-numeric mapping falls back to the flat line); the mapping is lifted off `Node.attrs` where 11.29 N6 puts it; and a `notebook_analyzed` **carrying `codes`** raises the out-of-order banner while one without them draws only the chip (11.29 N10) |
| 3c | Cross-lane bundling (VIEW-04) | `node --test test/bundles.test.mjs` in `webview` | 17 pass — every routed edge still owns its own `points` and `d` (a bundle is a **second** drawing), determinism by JSON equality over two layouts of three corpora, a one-member pair never bundled, members leaving the trunk in target order, trunks **nesting rather than braiding** (containment asserted, the interleaved residue counted), every trunk inside the reserved channel, the channel widened by lane **pairs** and never by more edges, and — the one that matters — **a bundle never hides a finding** |
| 3d | Diff overlay, viewer half (VIEW-08) | `node --test test/diff.test.mjs` in `webview` | 33 pass — the overlay read from all three routes and **anything that is not a v1 `mlview-diff` degrading to no overlay**, the headline drawn verbatim from the document (recomputed with a note when its own arrays disagree), "changed only" **reusing the scope projection** (core = every non-`unchanged` node, boundary one hop, stubs badge-free, `nodeIds[0]` rotated onto a core node), composition with a real scope, and a resurrected removed node saying on the card, in the Inspector and in the banner that it has no findings, ports, nesting or severity |
| 3e | Structured fixes, viewer half (H5) | `node --test test/fixes.test.mjs` in `webview` | 10 pass — the "Fix available" marker is a `span` and never a focusable child of a `role="option"`, every edit renders as a verbatim `<pre>` labelled insert/replace/delete, **only the exact word `mechanical`** reads as mechanical (a word a newer analyzer invents gets "Review fix…"), and `runFixAction` posts `applyFix` in VS Code but copies in the standalone report — announcing which of the two happened |
| 3f | Resolved config, viewer half (ANA-10) | `node --test test/configres.test.mjs` in `webview` | 13 pass — `Node.attrs` takes precedence over the sublabel parse (the precedence itself is asserted, so the parse can be retired without a viewer change), a `getattr` registry draws **one** node with `data-config-alt="N"` and names all N candidates in the Inspector, and "could not resolve" is drawn as `not resolved` rather than as an absence |
| 3g | Rollup rendering, viewer half (PERF-04) | `node --test test/rollup.test.mjs` in `webview` | 17 pass — `src/rollup/rolled.ts` is the only module that knows the names `Node.rolledUp` and `Edge.weight` and it **refuses** a value that is not a positive integer; a rolled-up card borrows the collapsed-group visual and **none** of its affordance (`aria-label` reads "7 nodes folded into this card, which cannot be opened"); a weighted cable carries a `x n` pill whose `<title>` says it counts connections, not call sites; the banner draws the analyzer's own `truncated` sentence verbatim; and `stats.truncated` **alone** no longer produces the rollup wording — a document written by an older analyzer keeps the sentence that is true of it |
| 3h | Pipelines, viewer half (MLV-P12) | `node --test test/pipelines.test.mjs` in `webview` | 33 pass — the relation ported line for line, `pipelineDrift` **reporting** a disagreement with the emitted `pipelines[]` block instead of trusting it, the chooser opening once at two or more pipelines with Tab trapped so `aria-modal="true"` is not a lie, and the five caveats it states about its own list (not a partition, N nodes in no pipeline, `config` edges cut, entrypoints capped at ten, and — when `stats.truncated` — that the counts describe the summarised graph) |
| 4 | Viewer typecheck | `npm run check` in `webview` | `tsc --noEmit`, clean |
| 5 | Extension typecheck | `npm run check` in `vscode-extension` | `tsc --noEmit`, clean |
| 6 | Extension bundle | `npm run compile` in `vscode-extension` | `out/extension.js` 207.6 kb / `out/test-entry.cjs` 169.3 kb; `compile` also runs `sync-rule-docs` (36 pages) and `sync-walkthrough` (5 pages) |
| 7 | Extension tests | `npm test` in `vscode-extension` | 404 pass, 0 fail |
| 7a | Diagram export, host half (VIEW-07) | `node --test test/export.test.js` in `vscode-extension` | 17 pass — the base64 / 32 MiB / basename guard, the PNG-signature and SVG-opening-tag format check *before* the save dialog, the deferred `requestExport`, and the toast's Open / Copy Path actions |
| 7b | Notebooks, host half (NB) | `node --test test/notebooks.test.js` in `vscode-extension` | 24 pass — with `mlview.includeNotebooks` off `buildAnalyzeArgs` emits the argv it emitted before notebooks existed (asserted as a prefix equality), with it on a finding is republished on the cell's `vscode-notebook-cell:` URI with a cell-relative range, and it degrades one honest step at a time: cell URI → the `.ipynb` → the generated module |
| 7c | Multi-root and configuration, host half (H10 / CFG-ONE) | `node --test test/multiroot.test.js test/config.test.js` in `vscode-extension` | 22 pass — one `FolderState` per open folder with the single-folder window asserted **unchanged**, the Problems panel publishing the **union** (publishing one folder alone used to wipe the other's squiggles), a CodeLens answered with its own file's folder graph, the LM tools resolving the **active** folder rather than `workspaceFolders[0]`, and the settings asserted to be **additive** filters over a `.mlview.toml` that wins `disable` and `exclude` (§11.37 C1's own clause: "the VS Code half asserts it with its own test") |
| 7d | Fixes and comparison, host half (H5 / VIEW-08) | `node --test test/fixes.test.js test/compare.test.js` in `vscode-extension` | 37 pass — `providedCodeActionKinds` is `[QuickFix]` **only** (never `source.fixAll`, the kind `editor.codeActionsOnSave` runs unattended), `isPreferred` derived from `safety` and nothing else, every `WorkspaceEdit` entry carrying `needsConfirmation` so the apply routes through the refactor preview, the `certain`/`likely` floor re-checked host-side, one bad edit sinking the whole fix (half a fix is a broken file), the two **stale-document** refusals 11.42 I.3 delegated here (an unsaved buffer, an edit past the end of the file), and the viewer's `applyFix` message carrying the **issue id and nothing else** so a webview can never dictate a range or a replacement string. Comparison: the base written verbatim with no second analysis, the head staged in `globalStorageUri` and never in the user's repo, and `postGraph` clearing an outstanding overlay so a stale "0 new findings" is never drawn over a fresh graph |
| 8 | Plugin / MCP tests | `python -m pytest claude-plugin/tests -q -n auto` | 460 passed, 7 skipped in ~12 s with `-n auto` on this Mac (~34 s with `-n 4`, ~65 s without it) |
| 8a | Notebooks over MCP (NB) | `python -m pytest claude-plugin/tests/test_notebooks.py -q` | 8 passed — `includeNotebooks` on `mlview_analyze` and `mlview_issues`, and in `load_graph`'s **cache key** rather than as a filter applied after: the same sources with and without notebooks are two different documents |
| 8b | Notebooks **under attribution** (NB × CI-ADOPT, HOST-5) | `python -m pytest claude-plugin/tests/test_notebook_attribution.py -q` | 11 passed — `includeNotebooks` survives `changedSince`/`baseline` instead of being dropped on that branch (it reaches `AnalyzeOptions` through `load_attributed`), a baselined run really lists the notebook's MLV101, and where attribution *cannot* carry a notebook finding — its location names the generated `.mlview/notebooks/*.py`, which git does not track, so `--changed-only` drops it — the `note` says so with the count and the notebook's name |
| 8c | The pre-commit hooks are installable (CI-ADOPT d, HOST-2) | `python -m pytest claude-plugin/tests/test_pre_commit_hooks.py -q` | 8 passed, 2 skipped — a `language: python` hook makes pre-commit run `pip install .` in the **clone root**, so the root `pyproject.toml` must exist, declare the `mlview` console script each `entry` names, package `analyzer/src` (never a second copy) and keep its version `dynamic` so gate 9's "one version string" still holds. The two skips are the layers that need tooling this venv lacks: with setuptools present the root metadata is really built into a wheel (`--no-isolation`, no network) and the console script and `schema/*.json` are asserted inside it; with pre-commit installed (`MLVIEW_PRE_COMMIT=<path>`, or on PATH) `pre-commit try-repo` installs a throwaway clone of the **working tree** into a scratch consumer repo and runs the hook — measured here: `Passed`, MLV601/MLV602 reported, exit 0 |
| 8d | Claude Code hooks (H8) | `python -m pytest claude-plugin/tests/test_hooks.py -q` | 34 passed — the `PostToolUse` / `Stop` manifest shape, an immediate exit 0 on a non-Python path or one outside `CLAUDE_PROJECT_DIR`, speech **only when the issue-id set grew** (≤ 5 rows at confidence ≥ 0.6 under a 3 s budget), `MLVIEW_HOOK` = on|stop|both|off, always exit 0 so a hook can never block a session, and the assertion that caught a real defect: the hook must write **neither** `.mlview` **nor** a cache into the user's project |
| 8e | The `diff` scope over MCP (VIEW-08) | `python -m pytest claude-plugin/tests/test_diff_scope.py -q` | 10 passed — `mlview_graph(scope="diff", base=…)` rather than a sixth tool, a base that is not a graph (missing, unreadable, not JSON, or itself an overlay) erroring **by name** instead of returning an empty comparison, and the caveats riding the protected `note` key so the 4 KB budget sheds rows and never the "a rename is everything removed plus everything added" sentence |
| 9 | Parity gates | `python tools/verify.py --all` | all 10 gates passed |
| 9a | Scope parity (Python == TypeScript) | `python tools/verify.py --scopes` | 13 projections + 7 error cases, python == typescript (28 assertions) |
| 9b | Scope fixtures current | `python analyzer/tools/gen_scope_fixtures.py --check` | 13 projecting + 7 error cases over the golden, plus the **5** promoted `fuzzCases` on their own graphs |
| 9c | Scope fuzz — promoted counterexamples | `python tools/verify.py --scopes --fuzz 200` | **5** promoted counterexamples replay, python == typescript — each is a minimized document the fuzzer once found the two ports disagreeing on (HEALTH-02). The two newest are the first that carry a `pipelines[]` block: `fuzz_22_g0001_c04` (`pipeline:mod2.py`, 2 nodes) pins §11.47 C — a shared node is `context`, never `core` — and `fuzz_33_g0000_c01` (`stage:objective`, 2 nodes) pins §11.47 D's "carried through verbatim" |
| 9d | Scope fuzz — generated graphs | (same command) | 200 cases over 40 generated graphs (1-500 nodes), python == typescript, ~2 s; the seed is printed so `MLVIEW_FUZZ_SEED=<n>` replays it. Since wave 3 the generator also produces the two Sprint-5 shapes — a measured run: **12 rolled up (PERF-04) + 21 with pipelines (MLV-P12, 45 blocks)** — and the compared fields are the shared digest **plus `rolledUp`, `weight` and `pipelines`**. `.github/workflows/nightly.yml` runs 2000 cases (~16 s) once a day |
| 9e | Scope fuzz — the pipelines relation | (same command) | `PASS scopes: pipelines relation` — §11.47 A is one algorithm written twice and 11.47 D carries the block through a projection *verbatim*, so a port that computes the relation differently never shows up in a projection comparison. This row compares `mlview.core.pipelines.pipelines_block` against `webview/src/scope/pipelines.ts` `rows()` on every generated document (entrypoint, nodeCount, exclusiveCount, sharedCount, issueCounts). It caught a real divergence within an hour of existing — 17 of 40 graphs, Python `exclusiveCount 4` against TypeScript `0` on one 16-node document, both numbers on screen at once because the report embeds the block and the chooser recomputes its own row |
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
| 17 | Emitted docs valid | `python contracts/validate_sample.py .mlview/graph.json` | schema 1.0 + 10 invariant groups, 59 nodes / 51 edges / 15 issues |
| 17b | Emitted docs valid **at four caps** (PERF-04) | `python -m mlview analyze samples/vision_pipeline --format json --max-nodes N` → `python contracts/validate_sample.py -` for N in 400 / 40 / 20 / 8 | `schema 1.0 + 10 invariant groups passed` four times — 59/51, 38/35, 12/13 and 7/3 nodes/edges, and **15 issues (5 high / 6 medium / 4 low) in all four**: a cap folds the diagram, it does not silence a finding. The validator gained four assertions folded into its existing `edges` and `stats` groups (no self-loop; no parallel `(source,kind,target)` in a document that claims a rollup; `rolledUp` >= 1 and `weight` >= 2; **neither field on an untruncated document**), so the "ten invariant groups" claim five documents make stays true |
| 18 | Docs match the tree | `python scripts/check_docs.py` | 19 files (16 docs + 3 shell scripts), no dead paths, every known gap anchored, no build state in a plan doc, LF in every shell script, one graph size, the accuracy headline equal to the baseline, no silent artifact upload, one e2e step count, every shipped roadmap item recorded as landed, the Components table agreeing with its own gate paragraph, the scope battery quoted at its real size, one last-green-push run id, every selector the parser accepts advertised on every list a reader sees, every generated directory git-ignored, every test file its package's `test` script runs, every CI command line one its own tool's parser accepts, no closed list of hop-paying rules the code does not hold, and no known gap waiting for something that has already landed. The three-shell-script count is the repo's own: `tools/public_corpus.py fetch` clones every repository in `analyzer/tests/public_corpus/repos.json` into the tree, each bringing `*.sh` files of its own, and check 7 skips that directory — read from `tools/public_corpus.DEFAULT_CORPUS_DIR`, not from a figure here, so no count in this row can go stale |
| 19 | End to end | `powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1` | `E2E OK` — 20 steps, 0 failed |
| 20 | Scoped demo artifacts | `python -m mlview analyze samples/vision_pipeline --scope concern:evaluation --depth 1 --html .mlview/evaluation.html` | 17 of 54 nodes (7 core / 7 boundary / 3 context), `data-mlview-scope` and `data-mlview-depth` set on the root |
| 21 | Scope catalogue | `python -m mlview analyze samples/vision_pipeline --list-scopes` | `3 pipeline(s) + 10 scopable unit(s)` — the `pipeline:` rows lead, biggest first, and the footer says what a `pipeline:` SUBTREE column counts (only the nodes no other entrypoint reaches) |
| 22 | Bytecode residue never poisons the vendor gate | `python -m pytest claude-plugin/tests/test_vendor_bytecode.py -q` | 3 passed — pytest over a throwaway vendored tree writes no `__pycache__` with the flag set and does write one without it, and `sync-core --check` prunes planted residue and stays green |
| 23 | Accuracy corpus (also a row in `scripts/e2e`) | `python tools/accuracy.py` | `accuracy gate: PASS` — **158 labelled programs, 546 labels**, precision **100.0% on every one of the 36 rules**; the shipped default is `ip` (row 23c) and the row below is `--dataflow local`: overall recall **78.2%** / 70.7% visible / 71.2% high+medium, unseen recall **76.9%** raw / 68.9% visible / 69.3% high+medium, graph fidelity **91.9%** (1072 of 1166); **zero `forbidden` and zero `unlabelled` findings**, nothing below `analyzer/tests/accuracy/baseline.json`. Re-recorded in hardening round 2 with `--allow-regression`, and the reason is in the baseline's own `note`: the corpus grew 92 → 158 programs and 312 → 545 labels, and unlike round 1 every aggregate rose anyway — 72.4% → 77.8% raw and 69.4% → 76.5% unseen — while thirteen per-rule ratios read lower against a larger denominator. Round 1's re-record is the row below this one in `docs/ACCURACY.md` §7; §8 is this one |
| 23c | Accuracy under `--dataflow ip` (DATAFLOW-IP) | `python tools/accuracy.py --dataflow ip` | `accuracy gate: PASS` against a **separate** ratchet, `analyzer/tests/accuracy/baseline.ip.json`, so the two modes cannot mask each other: precision **100.0%**, overall recall **80.4%** / 72.5% visible / 74.3% high+medium, unseen **79.2%** / 70.9% visible, graph fidelity **91.9%**, zero `forbidden` findings, **+12 labels over `local`**. Since the recall campaign this is what an *unflagged* run measures too — `ip` is the default and `--dataflow local` is the opt-out. Round 2 made the mode a real widening: `findings(local) ⊆ findings(ip)` and `|edges(local)| ≤ |edges(ip)|` over every corpus program, gated by `analyzer/tests/core/test_dataflow_ip.py::test_ip_never_reports_less_than_local` (CONTRACTS 11.59 B). It was false on 20 programs before that — 79 edges and, on a mean-teacher program, a high `MLV301` — and the mlflow MLV110 this row used to record as the one narrowing is `state: "fixed"` |
| 23a | The same three gates, asserted | `python -m pytest analyzer/tests/accuracy -q` | 37 passed — corpus lint plus the matcher's own semantics |
| 23b | The three rule tiers (ANA-7 / ANA-8 / ANA-9) | `python -m pytest analyzer/tests/rules/test_tier_rules.py -q` | 56 passed — the sixteen new codes, their bad/good fixture pairs, the `GradScaler(enabled=…)` three-way (literal `False` suppresses, non-literal de-rates to 0.6, absent fires), and every ANA-7 finding at or above the 0.60 Problems-panel default |
| 23d | Public repositories, unlabelled (PUB) | `python tools/public_corpus.py fetch` then `run --out report.json` then `check --report report.json` | `public corpus gate: OK` — **37 pinned third-party repositories**, 112 targets x 3 modes (`local`, `ip` and `--include-notebooks`) = **260 runs, 260 clean**, about a minute of wall at `--jobs 8` with every single run inside the 60 s per-run budget on this laptop (the gate asserts the budget; the wall figure moves with the machine and is not one). **On a hosted runner the budget is 120 s**, which is what `.github/workflows/public-corpus.yml` passes: the first CI run this gate ever had (run 34974208055, the dispatch that followed the repository going public) was clean on 259 of its 260 runs and failed the gate on one — `pytorch-image-models .` in `ip` mode at **62.5 s**, with `local` on the same target at 50.1 s and the next slowest run in the whole corpus at 21.2 s. timm is the largest repository in the manifest and `ip` became the default in the recall campaign, so that pair is the most expensive analysis there is, measured for the first time on a 4-vCPU runner rather than on the machine the 60 was calibrated on; 60 stays the tool's default because that one describes a development machine. The ceiling still does its job — what it exists to catch is a run that has gone quadratic or stopped making progress, which is an order of magnitude and not 4 %. [Run 34975673419](https://github.com/realmyang/MLView/actions/runs/34975673419) is the reading that followed: **260 runs, 260 clean, green**, 232 s of wall at `--jobs 4`. **49 high / 276 medium / 381 low** on the tree that shipped the recall campaign and its review (50 / 276 / 376 in hardening round 2 — one high finding became a `state: "fixed"` adjudication). The five things it asserts are each a credibility claim, not a taste: no traceback, exit 0 or 4 only, every emitted document schema-valid under `contracts/validate_sample.py`, inside the wall-time budget, and **no high-severity finding whose key is not in `analyzer/tests/public_corpus/adjudication.json`** — so a high finding no human has read fails the build. Nothing is vendored; `fetch` clones ~1.8 GB into `$MLVIEW_PUBLIC_CORPUS_DIR` (default `.public-corpus/`, git-ignored). This is the only gate in the tree that can see a false positive nobody thought to label, and it earned that at its first integration: it refused the round-1 build on two NEW high / `certain` claims about correct code (PUB-14 on the Python Data Science Handbook's two-fold cross-validation cell, PUB-15 on a scikit-learn release-highlights script), neither of them reachable from 312 labels. Eleven adjudicated false positives are now `state: "fixed"`, so a return is blocking, and none is left `open` — `check --strict`, which fails on a known-open false positive, passes on this tree too. The 22 entries that stay `open` are adjudicated **true** positives, each with the source read and quoted. `analyzer/tests/public_corpus/test_public_corpus.py` skips when the clones are absent |
| 18b | A gate claimed green on a CI matrix that never ran (doc check 22) | `python -m pytest scripts/test_doc_claims.py -q` | 10 passed — the `README.md` and `docs/STATUS.md` over-claims caught word for word (the STATUS one wrapped across two lines, which is why the check reads paragraphs), the honest fix passing, a paragraph that names one run by id passing, **a green claim about the matrix itself passing once the run is named and failing the moment the id is removed**, a purely descriptive account of the matrix passing, the real repo clean, the gate asserted to be **wired into** `check_docs.run` rather than merely present, and `docs/CONTRACTS.md` asserted to name no `scripts/*.py` that is missing from the tree. The two emphasised cases are new, and they are the check catching up with its own rule (CI-PUBLIC-02): it always said a document may "report that one identified run was green", but the only escape it implemented was a NEGATION — "has not run", "is blocked". That was invisible while no run had ever started; the moment run 34975667772 took all thirteen jobs, a check that accepts *the matrix has not run* and refuses *the matrix is green, here is which run* forbids the true sentence and permits only the false one. A run id is what makes the claim checkable, and check 15 already holds every document citing one to the same id — REV-01: this gate and its suite were written once, cited twice by name in the contract, and then not carried onto the branch that shipped |
| 18c | The contract's diff figures equal the test that pins them (doc check 23) | `python -m pytest scripts/test_doc_figures.py -q` | 23 passed — five of them check 23: §7's `summary.nodes`, `summary.edges` and headline against `analyzer/tests/core/test_diff.py`, the REV-04 defect caught in all three places at once, §17's errata left alone, and the check proven to abstain rather than guess if the pin is ever restructured |
| 18a | The tree advertises what it accepts (doc checks 16-18) | `python -m pytest scripts/test_doc_surfaces.py -q` | 19 passed — three checks added in hardening round 1 (CONTRACTS 11.54), each a list in the tree that was shorter than the thing it described and that no figure-comparing check could see. **16**: every selector `core/selectors.SCOPE_KINDS` accepts is advertised in the `--scope` help, in `README.md` §1b and in both `claude-plugin/commands/*.md` — `pipeline:` had worked and been documented nowhere since 11.47. **17**: every directory a tool writes into is in `.gitignore`, read from the tool's own constant so renaming the directory moves the check. **18**: a package's `test` script either discovers its test files or names every one of them, and every path it names exists. Four of the 19 cases run against the real repository, so reverting any of the three fixes brings the failure back |
| 24 | Analyzer byte-equivalence | `python tools/perf_equiv.py --baseline DIR --diff --bench` | both shipped samples byte-identical to `main`; `analyzer/tests/clean` gains exactly one `ValueTag` (PERF-02's fifth IR round), 200-file corpus 2.25x faster |
| 24a | …with the verdict in the exit code | `python tools/perf_equiv.py --compare FILE --expect-same` | `perf_equiv: OK - every corpus is byte-identical`, **exit 0** — PERF-03's `--relevance all` path and the whole of CACHE claim exactly this, and so does the Sprint-5 **default flip**: against a tree identical but for `DEFAULT_RELEVANCE = "all"`, `vision_pipeline`, `vision_pipeline_clean` and `tests_clean` are all `identical` and the run exits 0, which is the evidence §11.39 rests on. `--expect-diff` on the same pair exits **1** (`FAILED - --expect-diff, but every corpus is byte-identical`), which is what a re-baseline that never took effect looks like; either flag with no baseline exits 1 rather than passing silently. **NB claims exactly this for its default path**: against the pre-wave-4 analyzer, `vision_pipeline`, `vision_pipeline_clean` and `tests_clean` are all `identical` and the run exits 0 — `--include-notebooks` is the only thing that changes a document |
| 24b | Relevance prefilter (PERF-03) | `python -m pytest analyzer/tests/core/test_relevance.py -q` | 24 passed — seeds derived from the knowledge tables, k-hop BFS in both directions **after** ANA-3 re-export resolution (`train.py → pkg → pkg/net.py` is one hop), the refusal (no seed ⇒ nothing set aside), and one `config_warning` naming the count and both widening flags |
| 24c | Per-file fact cache (CACHE) | `python -m pytest analyzer/tests/core/test_cache.py -q` | 31 passed — a warm run is **byte-identical** to `--no-cache`, an edited file is `cached: partial` and still byte-identical, a forged or foreign-identity sidecar is ignored rather than obeyed, and nothing is opened or written at all under `--relevance all` (which was the shipped default when this row was written and is now the opt-**out**: since Sprint 5 the default is `--relevance ml`, so the cache is on and a plain `analyze .` writes `<root>/.mlview/cache/`). The 31st stands a Windows in for this platform and asserts the MAC secret reads back **byte-identical** to what was written — without `os.O_BINARY` the ~12% of 32-byte keys containing an `0x0A` are CR-mangled on write and the cache is permanently, silently disabled |
| 24d | Perf budget | `python -m pytest analyzer/tests/core/test_perf_budget.py -q` | 6 passed (adds ~20 s: it builds a 500-file corpus and runs six analyses) — the narrowing ratio, the set-aside diagnostic, the edited-file delta and the sample's byte-identity. The delta row asserts the cache in **hits**, not in seconds: 0/501 cold, 500/1 after one file is edited, 501/0 warm, the warm document byte-identical to the cold one, and wall clock only against an absolute ceiling. A cold-over-warm *ratio* measured 1.45x–2.50x across five runs on this Mac and 1.15x then 1.38x on `macos-latest`; the 1.15x is what reddened `smoke (macos)` on run 34419964015 against a 1.25 bar. The ratio is `1 + saved/common` and its inputs are unsteady — two runs of the **identical** configuration in one macOS job took 1.19 s and 0.76 s — while reading all 501 files, the term first blamed, costs 0.01 s there and 0.12–0.23 s here. Both perf rows print the cold, warm and bytes-only figures they measured; `-rP` shows them for a run that passed (CI-MACOS-01) |
| 24e | PERF-04 changes no uncapped document | `python tools/perf_equiv.py --baseline DIR --expect-same` | `perf_equiv: OK - every corpus is byte-identical`, **exit 0** — `vision_pipeline`, `vision_pipeline_clean` and `tests_clean` all `identical` against a baseline that still holds the pre-PERF-04 deletion cap, which is the evidence §11.46 A rests on ("it returns immediately, mutating nothing, when the document is within budget"). The baseline is `analyzer/src` at the wave-2 commit **with MLV-P12 back-ported into it**, so the optional root `pipelines[]` block §11.47 D adds to a multi-entrypoint document is factored out of the comparison rather than swept into it: without that, all three corpora read `DIFFERENT` for a reason that has nothing to do with the cap |
| 26 | Wheel installs and runs | `python tools/wheel_check.py` (also a row in `scripts/e2e`) | `wheel-check: OK mlview-0.1.0-py3-none-any.whl -> mlview 0.1.0, 4 node(s), 2 issue(s) in a clean venv` — built with `python -m build --wheel analyzer`, installed into a throwaway venv, run through the **console script**, then one real analysis so a wheel missing `schema/*.json` cannot pass |
| 27 | VSIX packages and stays small | `npm run package` in `vscode-extension`, then `python scripts/vsix_check.py` | `vsix-check: OK mlview-0.1.0.vsix: <N> files, <KB> (<pct>% of the 1 MB ceiling), <C> under extension/core/, 37 rule page(s), 0 bytecode entr(y/ies)` — **the four bracketed figures are whatever the run prints; only the 1 MB ceiling and the zero are asserted**, and they are deliberately not transcribed here because every wave that adds an analyzer module moves them (the Consolidate rebuild's C3 splits moved the core count from 110 to 130 and the package from 82.1% to 87.1% of the ceiling in one commit, while this row still said 110). `docs/STATUS.md`'s Components table carries the current bundled-core count and doc check 13 holds *that* one to `tools/sync-core.py`; run the command to see the rest. The run is taken from a `vscode-extension/core/` that has been **deleted** first, which is the point: `npm run package` now *builds* the bundled core before packaging it (`vsce package` runs `vscode:prepublish` → `npm run compile` → `node tools/sync-core.mjs`, C2), and the run says so, copying the whole analyzer back into `vscode-extension/core/mlview` before vsce sees the directory. Packaged with no `--allow-missing-repository`, and with no license warning: `vscode-extension/LICENSE` is the same MIT text as the repository root's (C7), so vsce finds one and the package carries `extension/LICENSE.txt`. **The checker is the gate, not this row** (HOST-8): the file count and the KB move on every wave that adds an analyzer module while hand-copied prose figures do not, so `scripts/vsix_check.py` re-derives all of them — the ceiling, `extension/core/` against `vscode-extension/core` on disk, `extension/docs/rules` against `docs/rules`, and zero `__pycache__` — and echoes what it measured. Only the 1 MB ceiling is asserted; the three counts are an echo and are expected to have moved by the time you read this. CI runs it in the `packaging` job, and `scripts/test_vsix_check.py` negative-tests each rule against a synthetic package |
| 27a | The packaged VSIX RUNS its bundled analyzer (C2) | `python vscode-extension/tools/vsix_smoke.py` | `vsix-smoke: OK mlview-0.1.0.vsix: bundled core imports from the package, mlview 0.1.0 (schema 1.0), --demo byte-identical to contracts/graph.sample.json (46078 bytes), a live analysis drew 3 nodes / 2 finding(s)` — the row that makes an untracked `vscode-extension/core/` safe. Row 27 proves the package *contains* an analyzer; this one unzips the package, puts `extension/core` on PYTHONPATH the way `vscode-extension/src/coreClient.ts` does, and from a working directory **outside this repository** imports `mlview` and asserts the module resolved inside the unzip (an installed copy on the same machine would otherwise answer and the run would prove nothing about what shipped), checks its version against `vscode-extension/package.json`, emits `--demo` and compares it byte for byte with the frozen golden, and analyzes a real source file so the schema, the rule pack and the knowledge tables are exercised rather than replayed. It also fails on bytecode left behind in the unzip. CI's `packaging` job runs it immediately after row 27 |
| 27b | The bundled core is a BUILD artifact, not a tracked one (C2) | `npm test` in `vscode-extension` (`test/core-untracked.test.js`), and `python tools/verify.py --vsix` | **410 pass, 0 fail** — six assertions on the chain that makes `vscode-extension/core/` appear and keeps it out of the index: it is on disk when the suite runs (because `pretest` builds it), `git ls-files` lists **nothing** under it, `.gitignore` carries `vscode-extension/core/` and `git check-ignore --no-index` agrees, `vscode-extension/tools/sync-core.mjs` delegates to `tools/sync-core.py` rather than being a second copier, `compile` / `pretest` / `vscode:prepublish` all run the builder **before** esbuild, and `.vscodeignore` still negates `!core/**` so the built copy reaches the package. The Python half is the `vsix: synced core` row of `tools/verify.py --all`, which since C2 is **strict** about the directory existing (a missing build artifact is a VSIX with no analyzer), while the bare `tools/sync-core.py --check` — the one the `claude-plugin` CI job runs on a tree nobody has built — reports it as "not built" rather than as drift |
| 29 | Walkthrough pages current (MLV-P11) | `node vscode-extension/tools/sync-walkthrough.mjs --check` | `sync-walkthrough: 5 page(s) up to date` — `media.markdown` resolves relative to the **extension** root, so a page that lives only in `docs/walkthrough/` renders as an empty panel once packaged. Wired into `npm run compile` and `pretest`, the same way `sync-rule-docs.mjs` is |
| 30 | Sample gallery renders (MLV-P11) | `python analyzer/tools/gen_gallery.py --quiet` | 90 self-contained reports + an index from 6 clean programs and 36 rules (84 fixtures), ~30 MB in ~1.4 s, into **gitignored** `docs/gallery/` — a build target would write 30 MB on every build, so this one is run by hand. Not a pass/fail row on its own: what it asserts is on the index, which states that every page is a **single-file** analysis and then measures its own blind spot **off the run** rather than asserting it from a constant — **0 of 90** pages carry a `single_file_analysis` diagnostic (that diagnostic speaks only when an analyzed module *imports* a sibling the run left out, which no self-contained fixture does) and all four cross-file rules, **MLV301, MLV302, MLV401 and MLV501, did fire** on at least one single-file page. The old sentence claimed the opposite of both halves (GALLERY-FALSE-BLINDSPOT): telling a reader the tool was blind where it was not is the same failure as telling them it looked where it did not. It still flags a `_bad.py` that fired nothing or a `_good.py` that fired its own rule; on this build **neither flag appears** |
| 28 | The icon is what its script renders | `python vscode-extension/tools/make_icon.py --check` | `make_icon: OK ... matches (890 bytes, 128x128)` |
| 25 | CI matrix, two tiers (C6) | `.github/workflows/ci.yml` | **A branch push runs 7 jobs; a pull request, or a push to `main`, runs 13.** Measured at last, on the `public` → `main` pull request of 2026-09-15, and every one of the thirteen came back green. The cheap tier is [run 34975663652](https://github.com/realmyang/MLView/actions/runs/34975663652) — 7 jobs, **7m49s** wall: `e2e (ubuntu, sh)` 465 s, analyzer py3.10 458 s, analyzer py3.13 353 s, webview Node 20 77 s, `claude-plugin` 46 s, the accuracy corpus 38 s and `vscode-extension` 27 s. The full tier is [run 34975667772](https://github.com/realmyang/MLView/actions/runs/34975667772) — the 6 jobs the cheap tier's guard excludes, **12m03s** wall: `e2e (windows, powershell)` 718 s, analyzer py3.12 571 s, `smoke (macos)` 541 s, analyzer py3.11 497 s, webview Node 22 77 s and `packaging (wheel + vsix)` 35 s. Both ran on the same commit, which is what makes the two halves one matrix and not two samples, and the next two commits confirmed it: [34977935404](https://github.com/realmyang/MLView/actions/runs/34977935404) / [34977944326](https://github.com/realmyang/MLView/actions/runs/34977944326) (11m15s and 12m39s), then [34979532914](https://github.com/realmyang/MLView/actions/runs/34979532914) / [34979536605](https://github.com/realmyang/MLView/actions/runs/34979536605) (11m14s and 11m34s) — thirteen green each time. **Read the three together before treating any single duration as a constant.** The same job on the same code moves a long way between runs: `e2e (ubuntu, sh)` 465 → 671 → 669 s, analyzer py3.10 458 → 593 → 590 s, analyzer py3.12 571 → 547 → 414 s, `e2e (windows, powershell)` 718 → 754 → 688 s, `smoke (macos)` 541 → 480 → 473 s. The three weighted totals came to **173, 163 and 158 minutes** for the identical thirteen jobs, so a `timeout-minutes` or a cost figure taken from one reading is taken from whichever runner answered that morning; expect the next to differ again, which is why three are written down rather than one. This is the **first time every job in `.github/workflows/ci.yml` has executed on any branch of this project**: GitHub Actions was blocked at the ACCOUNT level for the two days the consolidation and the recall campaign were written, so all of that work had been checked on one macOS laptop and nowhere else until this pull request. **The weighting arithmetic is now history rather than a bill**: the repository is public, and GitHub charges nothing for a standard runner. Were it private again, these same thirteen jobs would weigh **173 minutes** — 49 ubuntu, 24 windows and **100 macOS** — because each job is rounded up to a whole minute *on its own* before its runner weight is applied (ubuntu 1x, windows 2x, macos 10x). The figure worth reading twice is that macOS one: `smoke (macos)` at 541 s is ten whole minutes at 10x, so it weighs **more than the other twelve jobs put together** (73). This row used to estimate it at ~30 from a Sprint-5 run whose analyzer suite was about half the size, and the tiers were designed around that estimate; the reading vindicates where the job sits rather than the number — it runs where a merge is at stake and nowhere else. It took **one fix iteration**, and the four failures were one mistake made four times, in the one place a single-platform run cannot reach: `os.path.abspath` puts the current DRIVE on a drive-less path on Windows, so three assertions in `analyzer/tests/core/test_cache.py` and one in `analyzer/tests/public_corpus/test_public_corpus.py` compared a real answer (`D:/tmp/…`) against the POSIX literal the test had put in the environment a line earlier. `e2e (windows, powershell)` was the only red job, its analyzer-suite step the only red step of that job's twenty, and nothing in the product was wrong — the same shape as the Windows path failures every previous integration in this row's history hit. A push that touches only `**.md` and `docs/**` runs **nothing**; a pull request has no such exemption, so a docs-only branch is still checked before it merges. What is *not* an estimate is the split: the cheap tier keeps the same-repository double-billing guard and every full-tier job runs only on the events that guard excludes, so on a same-repo pull request the push event pays for one tier and the `pull_request` event for the other — each job exactly once, never twice. One caveat these two runs exposed: a branch created at a commit **already on the remote** pushes no new commits, so GitHub creates no push run, and the cheap tier is then skipped on the pull request with nothing having run it — the first real commit to the branch restores both halves (the `public` branch's opening pull-request run, 34974162339, shows the seven cheap jobs skipped for exactly this reason). Both e2e jobs archive `mlview-reports-*` (CI-ARTIFACTS-01). The readings below are the history this arithmetic is built on.**The hardening round-2 integration push to `hardening` (run 34815166539)** is the previous reading, and the one the estimates this row used to carry were extrapolated from: **all 12 branch jobs green** — `e2e (windows, powershell)` 935 s, `e2e (ubuntu, sh)` 724 s, Python 3.10-3.13 275-533 s each, Node 20/22 165-195 s, `claude-plugin` 50 s, `packaging (wheel + vsix)` 39 s, `vscode-extension` 38 s and the accuracy corpus 23 s; **15m39s wall and ~87 billable minutes** (55 for the eleven ubuntu jobs, 16 × 2 = 32 for the one Windows job). It took **no fix iterations**: the round-2 integration pushed four times and every run was green on everything it was allowed to finish — the first two were superseded and cancelled mid-flight by the next push, the third (run 34814075515, 15m06s / ~86 minutes) completed all twelve, and this one is the fourth. The round added about a fifth to both figures over round 1 below, and the cause is its own work: 2405 -> 2574 analyzer tests and 92 -> 158 labelled programs. `smoke (macos)` is skipped on a branch push by design. The hardening round-1 integration push (run 34793319849) is the previous reading: **all 12 branch jobs green** — `e2e (windows, powershell)` 787 s, `e2e (ubuntu, sh)` 617 s, Python 3.10-3.13 219-355 s each, Node 20/22 171-176 s, `claude-plugin` 64 s, `packaging (wheel + vsix)` 46 s, `vscode-extension` 37 s and the accuracy corpus 19 s; **13m10s wall and ~71 billable minutes** (43 for the eleven ubuntu jobs, 14 x 2 = 28 for the one Windows job, each job rounded up to a whole minute on its own before its runner weight). Both figures roughly doubled over the Sprint-5 reading below, and the cause is the round's own work: the analyzer suite went 2087 -> 2405 tests and the labelled corpus 15 -> 92 programs. It took **three fix iterations**, and the row says so because every one was a real defect a single-platform run cannot see: (1) two robustness fixtures written in 3.12-only syntax (PEP 695, PEP 701) asserted `filesFailed == 0` on 3.10 / 3.11 hosts that cannot parse them at all, and a plugin test shelled out to `python -m mlview` in the one job that deliberately does not install the analyzer; (2) a test that edits a file "preserving its size" rewrote it through a text-mode handle, so Windows newline translation grew it 402 -> 418 bytes and the failure read as an analyzer defect; (3) four assertions in two new `vscode-extension` suites compared two spellings of one path — section 0's forward slashes against `Uri.file(...).fsPath`, and a drive-less `\work\api` against the resolved `D:\work\api`. `smoke (macos)` is skipped on a branch push by design. The Sprint 5 review-fix integration push to `sprint5` (run 34454599867) is the previous reading: **all 12 branch jobs green** — `e2e (ubuntu, sh)` 6m29s, `e2e (windows, powershell)` 7m53s, Python 3.10-3.13 90-146 s each, Node 20/22 150-169 s, `vscode-extension` 37 s, `claude-plugin` 48 s, `packaging (wheel + vsix)` 44 s and the accuracy corpus 15 s; **7m57s wall and ~44 billable minutes** (28 for the eleven ubuntu jobs, 8 x 2 = 16 for the one Windows job, each job rounded up to a whole minute on its own before its runner weight). It took **two fix iterations** to get there and the row says so: the first push was red on four jobs and the second on one, all five failures being things only the matrix can see (a gitignored cache sidecar vendored into the core, two 3.10 tests asserting the behaviour a fix had just corrected, a thread race, and two Windows path-portability bugs). `smoke (macos)` is skipped on a branch push by design. The wave-2 push (run 34435948295) is the previous reading and the one the two-iteration story below belongs to: **all 12 branch jobs green** — Python 3.10-3.13 (100-130 s each), Node 20/22 (164-173 s), `vscode-extension` 37 s, `claude-plugin` 77 s, `e2e (ubuntu, sh)` 355 s, `e2e (windows, powershell)` 473 s, `packaging (wheel + vsix)` 40 s and the accuracy corpus 14 s. `smoke (macos)` is **skipped** on a branch push by design — it runs on push to `main` and on pull requests, where the matrix is 13 jobs. **7m57s wall and ~42 billable minutes** — 26 for the eleven ubuntu jobs and 8 x 2 = 16 for the one Windows job, under GitHub's rule that **each job is rounded up to a whole minute on its own** before its runner weight is applied; the ~30 macOS minutes the Sprint-5 process push measured are what a `main` push or a PR adds on top. Both e2e jobs archive `mlview-reports-*` (CI-ARTIFACTS-01). **The wave took two fix iterations and both were real defects this Mac could not have seen.** (1) `e2e (windows, powershell)` alone, on one assertion: `compare.test.js` asserted `baseLabel` with `path.join`, the HOST separator, while `compare.ts` builds it with `.replace(/\\/g, '/')` — which is what §0 requires of a workspace-relative path and what the sibling assertion on the forward-slash `COMPARISON_BASE_RELATIVE` already asserted. The source was right and the test was wrong. (2) `analyzer (py3.12)` alone, on `test_two_ip_runs_are_byte_identical`: its `_stable()` popped `generatedAt` at the **top level** of the document, where §0 does not put it, so the timestamp stayed in the compared string and the assertion was a coin flip on whether two runs landed in the same second — it lost by one character, `03:57:01Z` against `03:57:02Z`. Eight sibling helpers in the same suite already spelled it `generator.generatedAt`; that one did not. Neither is reachable from a single-platform, single-second run, which is the argument for the matrix |
| 25a | Nightly scope fuzz | `.github/workflows/nightly.yml` | `python tools/verify.py --scopes --fuzz 2000` on a 04:17 UTC schedule plus `workflow_dispatch`, ubuntu 1x, ~16 s of fuzzing. GitHub only schedules cron from the default branch, so it starts firing once this lands on `main` |

Rows 16–18 are also asserted inside rows 2 and 19; they are listed separately
because each is a one-line command that answers a question a reviewer asks
directly ("is the golden still the golden?", "does what it just wrote validate?").

`tools/verify.py --all` is itself ten rows, in this order: one version row, the
`plugin: rule docs` row, the CLI-vs-MCP graph parity row, `vendor: synced core`,
`vsix: synced core` (PACKAGING's condition for a third copy of the analyzer — it
also fails when `.vscodeignore` would drop `core/` out of the package), the two
scope rows (`scopes: fixtures` and `scopes: python == ts`), and three
renderer-hash rows. `--fuzz N` adds three more scope rows to `--scopes`
(`scopes: promoted`, `scopes: fuzz` and `scopes: pipelines relation`), and only
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
17. `python scripts/test_check_docs.py` — the doc gate's own self-test (it also runs `test_doc_numbers.py`, `test_doc_figures.py`, `test_doc_surfaces.py`, `test_doc_claims.py` and `test_vsix_check.py`)
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

So the battery is data, not code: `contracts/scope.cases.json` names 13
selectors plus 7 error cases over the **frozen** `contracts/graph.sample.json`,
so a rule change can never redden this gate, and — since HEALTH-02's fuzzer
began promoting what it finds — 5 counterexamples that carry their own generated
graph instead. `contracts/scope.expected.json` holds what the Python `project()`
produces for each of them. `python tools/verify.py --scopes` regenerates the
fixtures and byte-diffs them (writing nothing), then runs `webview/test/scope_parity.test.mjs`, which
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

Sprint 5 added three more, in `scripts/doc_figures.py`, after a review round found the same rot in all three
gate documents at once. **Check 13**: `docs/STATUS.md`'s Components table — the document's headline — was
refreshed in wave 1 and left behind by waves 2 and 3, so all four of its test counts were contradicted 1900
lines lower by the same file's own gate paragraph, and its `core/mlview` file count said 88 where
`tools/verify.py --all` printed 96 (REV5-05). Both halves are now settled by the tree: the table against the
**last** `**Gates` paragraph of the same document, and the file count against what `tools/sync-core.py`
actually copies. **Check 14**: `README.md` called `contracts/scope.cases.json` "the ten-selector battery" for
three sprints while the file grew to 13 projecting cases, 7 error cases and 5 promoted counterexamples, and
this file said "ten selectors plus six error codes" (REV5-08). Any `N selectors` / `N projections` /
`N error cases` / `N promoted counterexamples` claim in a block naming the file is now read out of the JSON,
spelled-out numbers included. **Check 15**: "the last full green push" is a singular, and `README.md` named
run 34422156964 for it at the time while row 25 of this file named the later, greener run 34441571480 in the
same commit (REV5-07); every run id quoted beside that phrase must now be one id. Only the three living documents are
checked — a `docs/CONTRACTS.md` amendment or a `**Landed` note is a dated record, and check 8's `at the time`
escape applies here too.

The hardening round added three more, in `scripts/doc_surfaces.py`, for the one
shape none of the fifteen could see: not a number that has gone stale, but a
**list that is shorter than the build**. **Check 16**: CONTRACTS 11.47 added
`pipeline:<entrypoint>` and named the six machine surfaces that had to learn it —
`SCOPE_KINDS`, the `bad_selector` candidates, `mlview.api`,
`webview/src/scope/selector.ts`, the MCP docstring and `--list-scopes`. The four
surfaces a *person* reads were not on that list and did not change, so the only
way a CLI user could discover the selector was to type a wrong one and read the
refusal, and a model reading `/mlview`'s body would never pass the one selector
that answers "show me just the training entrypoint" (HOSTS-UX-DOCS-PIPELINE).
`symbol:` had been in the same position for longer. The parser's own tuple is the
authority, so adding a kind fails every advertised list until it names the kind.
**Check 17**: `tools/public_corpus.py`'s docstring called its clone directory
git-ignored while `.gitignore` had no entry for it, so `fetch` put ~1.8 GB of
real repositories into `git status` (PUB-17) — and, once they were there, the
doc gate started reading their shell scripts, which is why check 7 now skips the
directory the tool itself names. **Check 18**: `webview/package.json`'s `test`
script named its thirty files one by one, so three regression files written in
this round were invisible to `npm test` and to the `webview` CI job, which
reported "534 pass, todo 0" with all three on disk and failing
(HOSTS-UX-WEBVIEW-RUNNER). Both JS packages now discover their tests —
`webview/tools/run-tests.mjs` beside the one
`vscode-extension/tools/run-tests.mjs` already had; a package that goes back to
enumerating them must enumerate all of them.

Round 2 added three more, for three claims that were false the day they were
written rather than claims that went stale. **Check 19** parses the command lines
a workflow generates with the parser of the tool it invokes.
`.github/workflows/public-corpus.yml` built
`python tools/public_corpus.py fetch --repo <names>` out of its
`workflow_dispatch` `repos` input while `--repo` lived on the top-level parser
alone: argparse answered `unrecognized arguments` and exited 2, so every dispatch
that used the documented input died at the job's first step, and the second step
passed no selector at all, so even a fixed fetch would have planned all
thirty-seven repositories and failed the gate on thirty-six missing directories
(PUB2-10). Nothing in the tree could see it, because a workflow is text nobody
runs until the schedule does. The check holds no table of flags: the workflow
names the script, the script answers with `build_parser()`, and the conditional
fragments (`${{ ... || '' }}`, `${VAR:+...}`) are expanded into every literal
line they can produce first. **Check 20** refuses a closed list of rule codes for
the interprocedural hop weight unless a constant in `analyzer/src/mlview/rules/`
holds one: `docs/ACCURACY.md` §6 said *only MLV101 and MLV102* pay it long after
IP-01 made `RuleContext` charge whichever rule read the widened value, and the
measurement on the labelled corpus is MLV101, MLV401 and MLV803 — one rule named
that does not pay, two that do, missed (VIS2-17). **Check 21** catches a "known
gap" that names its own retirement condition when the condition is met:
`README.md` said the `/mlview-issues` `Bash` fallback would group "once the
matching `--group-by` flag lands on `analyzer/src/mlview/cli.py`" while
`mlview issues --group-by rule` had been printing the grouped table for two
sprints (HOSTS-UX-R2-07). Check 4 could not see it — the bullet cites a real
path, which is all check 4 asks for — but the bullet named the flag and the file
in one clause, so the gate had everything it needed.

```sh
python scripts/check_docs.py              # the repo
python scripts/check_docs.py --root DIR   # any tree
python scripts/test_check_docs.py         # the gates' own tests, all 132
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
| `tools/sync-core.py [--check]` | The only writer of `claude-plugin/vendor/` **and `vscode-extension/core/`** — the two vendored analyzers that let the plugin and the VSIX run with no pip install. Since C2 the two differ in kind: the plugin's copy is **tracked** (`claude plugin install` copies the plugin directory verbatim off a git ref, so what git holds is what the user runs), the extension's is a **gitignored build artifact** written by `vscode-extension/tools/sync-core.mjs` on every compile, pretest and package. `--check` is therefore strict about the first and reports the second as "not built" when nobody has built it; `tools/verify.py --vsix`, which runs after a build, is the row that insists it exists. |
| `tools/wheel_check.py [--no-build]` | PACKAGING's acceptance: build `analyzer/dist/*.whl`, install it into a throwaway venv, run `mlview --version --json` through the console script, then one real analysis. Exits 0 with a message when there is no wheel to test, non-zero when there is a broken one. |
| `tools/action/action.yml` | CI-ADOPT's composite GitHub Action: install MLView, `analyze --changed-since <base> --changed-only --sarif`, and a `sarif` output for `github/codeql-action/upload-sarif`. |
| `analyzer/tools/gen_gallery.py [--quiet]` | MLV-P11's renderer: 90 self-contained reports plus an index, from the 6 clean programs and the 36 rules' 84 bad/good fixtures, into **gitignored** `docs/gallery/`. Run by hand — a build target would write 30 MB on every build. |
| `vscode-extension/tools/sync-walkthrough.mjs [--check]` | The only writer of `vscode-extension/docs/walkthrough/`, on the same pattern as `sync-rule-docs.mjs`: `media.markdown` resolves relative to the extension root, so a walkthrough page that lives only in `docs/walkthrough/` renders as an empty panel once packaged. `npm run compile` and `pretest` run it. |
| `vscode-extension/tools/make_icon.py [--check]` | Renders `media/icon.png` (128x128) from arithmetic, so the marketplace icon is source rather than a binary nobody can regenerate. |
| `tools/verify.py [--parity\|--scopes\|--hashes\|--versions\|--vsix\|--all]` | The parity gates: one analyzer, one projection, one renderer, one version — ten rows, including `plugin: rule docs`, `vendor: synced core`, `vsix: synced core` and the two scope rows. |
| `tools/public_corpus.py [fetch\|run\|check]` | PUB-01's unlabelled referee: 37 pinned third-party repositories, each analysed in three columns — `local`, `ip`, and `notebooks` (a `local` run with `--include-notebooks`). **Every column spells `--dataflow` out on the command line** (C6 fix): the column used to pass the flag only for `ip` and leave `local` to the CLI default, so the day `ip` became that default (R1) the two columns would have been the same run under two names, with the report's own `argv` field unable to show it. |
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
