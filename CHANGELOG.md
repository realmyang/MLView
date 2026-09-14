# Changelog

Every dated entry below was moved here from `docs/STATUS.md`, which is now a
short current-state page. This file is the history: newest first, each entry
condensed to what changed and the numbers that were measured at the time. The
long-form reasoning for anything normative lives in `docs/CONTRACTS.md`; the
acceptance clause each item was measured against lives in `docs/ROADMAP.md`.

Figures in a dated entry are **historical**. They were true on their date and
are deliberately not rewritten when the tree moves on — `docs/STATUS.md`,
`docs/ACCURACY.md` and `analyzer/tests/accuracy/baseline.json` say what is true
today.

---

## Unreleased — consolidation (2026-09-15)

One wave with no behaviour change except the four small items named under
**C8**. Byte-identity is the acceptance and it was measured, not asserted:
`python tools/perf_equiv.py --expect-same` against a `main` reference tree is
identical on all three corpora, and a per-tree digest harness is identical on
19 more trees (the 15 labelled-corpus programs, both samples, `analyzer/tests/clean`)
and on 5 public repositories, in **both** dataflow modes. Both accuracy tables
are byte-identical to `main`'s, character for character.

**C1 — `docs/CONTRACTS.md` is a versioned spec again.** 5 261 lines of frozen
prototype plus 63 append-only amendments became **MLView Contracts v1.1**, 1 515
lines in 18 sections, every normative clause folded into the section that owns
it (727 normative sentences and rows inventoried; 306 of 317 lettered clause ids
kept their exact label, 11 merged, 1 dropped in drafting and restored). Twenty-four
statements that changed meaning are resolved inline and recorded as §17 E1–E24;
§18 maps every old number (§0–§9, §10 A1–A13, 11.1–11.47) to its v1.1 home, so the
662 `CONTRACTS §N` citations in code and tests still resolve. The old file is kept
verbatim at `docs/archive/CONTRACTS-v1.0-amended.md`
(sha256 `96de6c50bca63ba9e842871d16337b7b3d36bfaeeba9eb8cfd8828875e37e23d`, identical
to `git show b46a27c:docs/CONTRACTS.md`).

**C2 — one tracked analyzer.** `vscode-extension/core/mlview` was a third tracked
copy of `analyzer/src/mlview`; it is now a **build artifact**. `tools/sync-core.py`
is still its only writer, called from `vscode-extension/tools/sync-core.mjs` as the
first command of `npm run compile`, `pretest` and the new `vscode:prepublish`, so
`vsce package` builds it too. `--check` stays strict for tracked copies and reports
an unbuilt generated copy as "not built"; `tools/verify.py --vsix` is unchanged in
strictness. `vscode-extension/test/core-untracked.test.js` asserts all four halves
(untracked, ignored, built, and built by the three npm scripts), and
`vscode-extension/tools/vsix_smoke.py` runs the analyzer **out of the packaged
VSIX** — import resolved inside the unzip, version against `package.json`, `--demo`
byte-identical to the golden, plus a live analysis. `claude-plugin/vendor/mlview`
stays tracked with its sync gate, because a marketplace install copies that
directory verbatim; it goes away when the wheel is on PyPI.

**C3 — every source file under 600 lines.** Split by exact line-range slicing, so
method and function bodies are byte-for-byte the originals and only imports and
docstrings are new. Analyzer: `core/build.py` 837 → 108 (+ `build_roles` /
`build_units` / `build_ops` / `build_edges`), `rules/r_holdout.py` 658 → 387
(+ three `holdout_*` helpers, all five `@rule` entry points left in place so
`RuleSpec.module` never moved), `cli.py` 631 → 463, `ir/scopes.py` 629 → 18,
`ir/resolve.py` 622 → 327, `core/project.py` 607 → 418, `ir/bindings.py` 600 → 27,
`tools/gen_rule_docs.py` 762 → 253. Longest analyzer source file now **591**
(`rules/context.py`, untouched). Viewer: `app.ts` 1 456 → 509 into eight modules
under `src/app/`, `canvasview.ts` 756 → 554 into `src/canvas/{host,wiring,emphasis}.ts`,
`ui/chrome.ts` 634 → 502. Every public and cross-module private name is still
importable from its old module; no rule, host or test import changed. The bundle
got **smaller**: `dist/mlview.js` 324 443 → 323 342 B.

**C4 — docs flattened.** `docs/STATUS.md` 2 528 → 199 lines (a current-state page),
its dated history moved into this file; `README.md` 661 → 283 lines, a newcomer's
path rather than a build report. Two new documents: `docs/VALIDATION.md`, the
runbook a person follows on a second machine to exercise the surfaces no automated
test reaches and then publish the artifacts, and `docs/DEMO_LOG.md`, the template
that run fills in.

**C5 — `.workflows/` removed from git** (9 orchestration scripts full of absolute
machine paths) and gitignored.

**C6 — CI under budget.** `.github/workflows/ci.yml` is two non-overlapping tiers.
A **push** runs 7 jobs (analyzer 3.10 + 3.13, webview Node 20, extension, plugin,
accuracy, Linux e2e) for **~19 billable minutes**, against ~44 for the same push
before. A **pull request or a push to `main`** adds analyzer 3.11 + 3.12, Node 22,
Windows e2e, macOS smoke and packaging — 13 jobs, ~75 minutes, unchanged. Each job
runs exactly once per event because the full tier fires only where the cheap tier's
double-billing guard excludes it. `paths-ignore: ['**.md', 'docs/**']` on the push
trigger only.

**C7 — `LICENSE`** (MIT, Copyright (c) 2026 realmyang) at the repository root,
byte-identical to `vscode-extension/LICENSE`, matching `plugin.json` and
`package.json`. `analyzer/LICENSE` is the same file again, because
`analyzer/pyproject.toml` declared `license = { text = "MIT" }` with no licence
text beside it: the wheel `pip install mlview` delivers now carries
`mlview-0.1.0.dist-info/licenses/LICENSE`, where before it carried none.

**C8 — the four small items, the only behaviour changes in this entry.**

- **The fact cache leaves the analyzed folder.** `cache_dir_for(root)` now returns
  `MLVIEW_CACHE_DIR` when set, else a user-level directory keyed by a hash of the
  workspace path — `$XDG_CACHE_HOME/mlview`, else `%LOCALAPPDATA%\mlview` on
  Windows, `~/Library/Caches/mlview` on macOS, `~/.cache/mlview` elsewhere — and
  **never** a path inside `root`. Measured: 277 `.mlview/cache` directories had been
  written into this working tree; **0** after, and still 0 after five bare analyses
  and a full `pytest`. The cache decides where facts are read from, never what they
  are, so byte-identity is untouched.
- **`--framework <x>` says what it dropped.** A `framework_filter` coverage
  diagnostic (the thirteenth `Diagnostic.kind`, mirrored byte-identically into both
  schema copies) names the rules the filter dropped that `auto` would have run.
  Silent for `auto` and silent when the filter cost nothing. On
  `samples/vision_pipeline`, `--framework keras` takes 15 findings to 1 and now says
  so, naming 28 dropped codes.
- **`Issue.fix` reaches SARIF.** `emit/sarif_out.fixes_for` maps a structured fix to
  `result.fixes[]` (one `artifactChanges` entry, one `replacement` per edit, a
  zero-width `deletedRegion` for an insertion, the safety grade as
  `properties.fixSafety`). A result with no fix carries no `fixes` key, so every
  SARIF document produced before this is unchanged; the document still validates
  against the official OASIS SARIF 2.1.0 schema.
- **Escape closes the legend.** One rung added to the dismiss cascade, written once
  in `webview/src/ui/appkeys.ts`: scope picker → sheet → **legend** → focus mode →
  scope → selection → blur. The `?` sheet's Escape row, the only description a user
  ever sees, names it.

**Consolidation gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0 failed,
0 skipped**; analyzer **2 109 passed / 4 skipped** (2 087 at `main`; +22 from the
C8 items); webview **536 tests**; vscode-extension **381 tests**; claude-plugin
**373 passed / 7 skipped**; `pytest scripts` **74 passed**; `npx tsc --noEmit`
clean in both TypeScript packages; `tools/verify.py --all` **10 of 10**;
`tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py` **PASS** —
precision **100.0%**, recall **73.1%**, unseen **55.3%**, zero forbidden findings —
and `--dataflow ip` **PASS** at **79.5%** / unseen **66.0%**, both tables identical
to `main`'s; `scripts/check_docs.py` **DOC CHECK OK**; `python -m mlview analyze
--demo --json -` byte-identical to `contracts/graph.sample.json` at 46 078 bytes.

---

## Sprint 5 — the LATER tier of the roadmap (2026-09-10)

Interprocedural dataflow, structured fixes, one configuration surface, analysis
comparison, node-budget rollup, pipelines, cross-lane bundling, and the process
work around them. `docs/CONTRACTS.md` §11.35–§11.47 are the amendments.
`schemaVersion` stayed `"1.0"`, `contracts/graph.sample.json` never moved, and
`python -m mlview analyze --demo --json -` stayed byte-identical to it at
46 078 bytes through every wave.

**Analyzer and viewer**

- **DATAFLOW-IP** (§11.36) — `analyzer/src/mlview/ir/summaries.py` adds a
  fixed-point interprocedural pass (constructor, return, method-argument
  intersection and subscript projection summaries) behind `--dataflow {local,ip}`
  with `local` the shipped default. `local` is byte-identical *by construction*:
  every new path is reached only from `workspace.dataflow == "ip"` or from a
  non-empty `ValueRef.provenance`. Confidence is arithmetic, not a promise —
  `rules/confidence.py` weights one `cross_file` evidence `0.8 ** hops`, so
  MLV101's 0.95 prior reads 0.760 at one hop and 0.486 at three. Measured:
  recall 71.8% → **78.2%** overall and 53.2% → **63.8%** unseen, precision 100%
  in both modes, zero forbidden findings.
- **PERF-03 / CACHE become the default** (§11.39) — `DEFAULT_RELEVANCE` is
  `"ml"`, which turns the fact cache on with it. `tools/perf_equiv.py
  --expect-same` re-proved byte-identity on all three corpora. On a 501-file
  mixed corpus: 2 920 ms (`--relevance all`) → 1 237 ms cold → **547 ms warm**,
  same 148 findings. The honest cost: a default run now writes
  `<root>/.mlview/cache/`.
- **CFG-ONE** (§11.37, §11.45) — `core/config.py` is the only parser:
  `--config FILE`, else `<root>/.mlview.toml`, else `[tool.mlview]` in
  `pyproject.toml`; first match wins outright and is named in
  `workspace.configPath`. TOML wins for `disable`/`exclude`, flags win for
  `[analysis]` and `min_confidence`, every mistake is one `config_warning`.
  `mlview init` writes a commented file listing all 36 rules from the registry.
- **ANA-10** — in-Python config resolution: module-level dict literals,
  dataclass field defaults, `argparse` defaults and the chains rooted at them
  resolve to literals. Measured A/B: overall recall **71.8% → 73.1%**, unseen
  **53.2% → 55.3%**, graph fidelity 126 → **127 of 139**; in `ip`,
  78.2% → **79.5%** and unseen 63.8% → **66.0%**.
- **H5, structured fixes** (§11.42) — `analyzer/src/mlview/rules/fixes.py` is the
  only module that constructs a `TextEdit`; 31 of 36 rules are byte-identical.
  Rules opt in, every position comes from an `ast` node, nothing below the
  `likely` bucket is offered an edit, and nothing in the analyzer writes to a
  file. Finding-neutral by construction: `tools/accuracy.py` identical to the
  character with and without the field.
- **VIEW-08, `mlview diff`** (§11.38) — a separate `mlview-diff` overlay keyed on
  the §0 stable ids: per-node/edge `added|removed|changed|unchanged`, per-issue
  `new|fixed|persisting`, and a `notes[]` block naming every reason a `removed`
  might not mean "deleted". A move is not a change. Over the sample pair:
  **+26 / −16 nodes, 11 changed, 27 unchanged, 0 new findings, 15 fixed**.
- **PERF-04, rollup** (§11.46) — `core/rollup.py` makes `--max-nodes` a zoom
  level instead of a guillotine: a unit absorbs its ops, a file folds, then a
  directory, and only then the old deletion order. `samples/vision_pipeline` at
  `--max-nodes` 400 / 40 / 20 / 8 gives **54/51, 38/40, 12/18 and 7/4**
  nodes/edges with **15 issues (5 high / 6 medium / 4 low) in all four**.
- **MLV-P12, pipelines** (§11.47) — the root `pipelines[]` block plus a
  `pipeline:<entrypoint>` selector. A single-entrypoint workspace is
  byte-identical to before.
- **VIEW-04, cross-lane bundling** — `layout/channel.ts` plans one trunk per lane
  pair and nests rather than braids; `layout/bundles.ts` draws the common run
  once with a member count. Crossings per edge **3.82 → 1.96** on the 54-node
  demo and **44.55 → 30.47** on a 300-node synthetic. A bundled cable's severity
  marker is never faded.
- **HEALTH-02 grows** — `analyzer/tools/scope_gen_projections.py` generates
  rolled-up and multi-pipeline documents. It found two real divergences within an
  hour, including `exclusiveCount` disagreeing on 17 of 40 graphs; §11.47 D is
  the normative reading, and two counterexamples were promoted into
  `contracts/scope.cases.json` (three → five).

**Hosts**

- H10 multi-root: one graph per open folder (`vscode-extension/src/folders.ts`),
  the Problems panel publishing the union, `MLView: Select Active Folder`.
- The three language-model tools take the whole selector grammar, described in
  the MCP docstring's own words and asserted against it.
- H5's fix preview, VIEW-08's three comparison commands
  (`vscode-extension/src/compare.ts`), and `mlview_graph {scope: "diff"}` — a
  sixth *value*, not a sixth tool. Still exactly five MCP tools.
- H8: `PostToolUse` / `Stop` hooks under `claude-plugin/hooks/` that speak only
  when the issue set grew, at most 5 rows, under a 3-second budget.

**Process**

- CI-MACOS-01: `smoke (macos)` was red on a wall-clock *ratio* assertion that
  read 1.15x–2.50x across runs of the same commit. The delta test now asserts
  what the cache controls, as counts — `("none", 0, 501)`, `("partial", 500, 1)`,
  `("full", 501, 0)` — with wall clock held to a ceiling.
- PROC-12: `webview/test/export_svg.mjs` became the e2e table's 20th step;
  `scripts/doc_numbers.py` check 11 holds every "N steps" claim to what the two
  drivers print.
- §11.35 is an erratum, not an edit: §11.19's "54 nodes and 52 edges" predates
  REV-06 dropping the one backwards data edge. §11 is append-only.
- Review round: three new doc-gate checks in `scripts/doc_figures.py` — the
  `docs/STATUS.md` Components table against that file's own newest `**Gates`
  paragraph, any scope-battery size claim against `contracts/scope.cases.json`,
  and two documents naming different runs as "the last full green push".

**Review fixes (19 findings).** Five were high-severity false positives — MLV101
matching a split by *name* across two functions, MLV121 taking the *absent*
branch for a `reshuffle_each_iteration` it could not read, and three more — each
fixed at its source with no assertion weakened. Three defects were reachable only
from CI: a stray `.mlview` sidecar copied into both vendored cores (now skipped
by `tools/sync-core.py`), two `analyzer (py3.10)` tests asserting behaviour the
CFG-ONE fix removed, and a plugin test that was a race rather than a test.

**Sprint 5 final gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0 failed,
0 skipped**; analyzer **2087 passed / 4 skipped** (1722 / 3 at the sprint
baseline); webview **534**; vscode-extension **377**; claude-plugin **373 passed
/ 7 skipped**; `pytest scripts` **74 passed**; `tools/verify.py --all` **10 of
10**; `tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py`
**PASS** — precision **100.0%** on 36 rules, recall **73.1%**, unseen **55.3%**,
graph fidelity **91.4%** (127 of 139), zero forbidden findings — and
`--dataflow ip` **PASS** at **79.5%** / unseen **66.0%**;
`contracts/validate_sample.py` green at four budgets;
`analyzer/tools/gen_gallery.py` renders **90 reports plus an index**;
`scripts/check_docs.py` **DOC CHECK OK**. CI run 34454599867: **all 12 branch
jobs green**, 7m57s wall, ~44 billable minutes.

---

## Sprint 4 — the NEXT tier of the roadmap (2026-09-09)

Adoption, the answer card, framework recognition, three rule tiers, export,
packaging and notebooks. `docs/CONTRACTS.md` §11.21–§11.34 are the amendments.

- **Sixteen new rules** (ANA-7 / ANA-8 / ANA-9, §11.26) take the registry from
  **20 to 36**: framework misconfiguration (MLV705–MLV711), training mechanics
  (MLV207, MLV208, MLV209, MLV502, MLV803) and held-out integrity (MLV106,
  MLV114, MLV121, MLV305, MLV306). The labelled corpus grew 10 → 14 programs and
  77 labels; precision stayed **100% on all 36 rules**, overall recall
  62.9% → **71.4%**, unseen 51.1% → **53.2%**. `samples/vision_pipeline` kept
  exactly its fifteen findings, so no golden was regenerated.
- **FW-RECOG** (§11.23) — four framework knowledge tables (`knowledge/tf_tbl.py`,
  `hf_tbl.py`, `gbm_tbl.py`, `hooks_tbl.py`) and Lightning hook units in
  `core/hooks.py`. Graph fidelity **86.3% → 90.6%** (120 → 126 of 139).
- **ANA-5a** (§11.23) — a call the analyzer cannot resolve is never silently
  dropped: `CallSite.unresolved_callee` mints an `unknown` op and one diagnostic
  per scope, and no emitter may claim a stage is absent without the qualification
  *"(unverified: N calls could not be resolved…)"*.
- **CI-ADOPT** — the `mlview.adopt` package stamps each finding `new` /
  `touched` / `existing` from `git diff`, `mlview baseline write` plus
  `--baseline FILE`, `--sarif FILE` (SARIF 2.1.0 against the OASIS schema),
  `tools/action/action.yml` and `.pre-commit-hooks.yaml`. Every attribution
  failure degrades to "showing everything" with a diagnostic.
- **MLV-P1** — the deterministic Pipeline Answer Card (`emit/answers.py`), first
  block of `--format summary`, four sentences in `api.digest`, a card in every
  host.
- **VIEW-07** (§11.24, §11.33) — SVG/PNG export. The mitigation landed first:
  `webview/src/render/plan.ts` returns one scene plan that both
  `render/scene.ts` and `export/svg.ts` consume, so the gate can assert one
  `<path data-edge-id>` per routed edge with byte-identical `d`. The SVG
  references nothing outside itself.
- **NB** (§11.29) — `.ipynb` ingest behind `--include-notebooks`. One notebook
  becomes one generated module under `.mlview/notebooks/`, 1:1 line counts inside
  every cell, the cell map on `Node.attrs`, and a non-monotonic `execution_count`
  de-rates MLV101 / MLV203 / MLV209 by 0.75 and says so. The VS Code host
  re-anchors squiggles onto `vscode-notebook-cell:` URIs.
- **PACKAGING** — `tools/sync-core.py` vendors the analyzer into the VSIX as well
  as the plugin, `tools/verify.py` grew a tenth row, `scripts/vsix_check.py`
  re-derives the ceiling and the bundled-core count from the tree, and
  `tools/wheel_check.py` builds the wheel and runs it from a throwaway venv.
- **PERF-03 + CACHE** (§11.28) — the relevance prefilter and the content-keyed
  fact cache, both opt-in at this point. On a 500-file synthetic
  `build_workspace` dropped **1 087 ms → 76 ms** and the whole analysis
  **2 228 ms → 693 ms**, reporting the same 51 findings; a warm run 319 ms.
  Pickling the AST or the IR was measured and **rejected** — both slower than
  recomputing.
- **HEALTH-02** — the differential fuzzer over the two `project()` ports found a
  real divergence on its first 200 cases; §11.30 made the Python behaviour
  normative and three counterexamples were frozen into the battery.
- **Process** — PROC-01 put a `**Landed` measurement note on every shipped
  roadmap item and `scripts/check_docs.py` check 12 keeps it that way; HOST-8
  moved the VSIX figures out of two documents and into `scripts/vsix_check.py`;
  PROC-10 replaced an estimated CI bill with a measured one and stated the
  rounding rule; PROC-12 wrote down that pushes go over SSH because the stored
  PAT has no `workflow` scope.
- **Review fixes (23 findings).** Two rules were judging the wrong thing (MLV709
  paired a loss with any same-file activation; MLV121 fired on
  `train_ds.take(1)`), and a whole binding style was unanalyzed —
  `ds = ds.map(...)` resolved its right-hand side against the store the same
  statement was about to write, so three semantically identical `tf.data`
  pipelines measured 7/5, 7/5 and **2 nodes / 0 edges with `diagnostics: []`**.
  All three now measure 7/5, gated per style.

**Sprint 4 final gates.** `sh scripts/e2e.sh` **19 steps, 0 failed**; analyzer
**1748 passed / 3 skipped**; webview **404**; vscode-extension **308**;
claude-plugin **324 passed / 7 skipped**; `tools/verify.py --all` **10/10**;
`tools/accuracy.py` precision **100.0%**, recall **71.8%**, unseen 53.2%, graph
fidelity **90.6%**, zero forbidden findings; VSIX **128 files, 604.57 KB**.
CI run 34320075813: 12 jobs green, 6m30s wall, ~38 billable minutes.

---

## Sprint 3 — the NOW tier of the roadmap (2026-09-08)

**The re-baseline (§11.19).** Four items landed as one graph change, because one
golden regeneration has to cover all of them.

- **ANA-1** — ops written inside a class method were dropped: `CallSite.class_ir`
  carried two different facts and `core/build.py` read the wrong one. They are
  now `class_ir` (what the call resolves to) and `enclosing_class` (what class it
  is written in).
- **ANA-2** — `self.<attr>(...)` resolved to a symbol nobody declared; it now
  resolves through the binding.
- **ANA-3** — a package `__init__` re-export resolved to nothing.
- **VIEW-01** — lane boxes are no longer normalised to the widest lane. On the
  demo the world went 2636×2484 → 1576×2630 and `fit()` **0.322 → 0.532**; worst
  lane emptiness **91% → 32%**.

`samples/vision_pipeline` grew from 45 nodes / 45 edges to 54 nodes (52 edges at
the time; 51 since REV-01 dropped one backwards data edge) carrying **exactly the
same fifteen findings** at the same lines, so `expected_issues.json` was
unchanged. Precision stayed **100%** and every recall reading was unchanged to
four decimals; graph fidelity ratcheted **66.2% → 86.3%** (92 → 120 of 139).

Also in Sprint 3: PERF-01/PERF-02 (memoised knowledge lookup, a role index and a
convergence loop, byte-identical on three corpora), **ANA-12** — the labelled
accuracy corpus, `tools/accuracy.py` and `docs/ACCURACY.md` — BUILD-01 (−38% on
the report CSS), CI-01 (`.github/workflows/ci.yml`), COVERAGE (the
`single_file_analysis` / `untagged_dataflow` diagnostics and
`mlview.currentFileAnalysisScope`), RAIL-GROUP (`mlview_issues` `groupBy`) and
CLEANUP (`mlview.showSpeculative` and `mlview.followCursor` deleted).

**The pre-sprint audit, for the record.** Five auditors measured the shipped
prototype on 2026-09-08: **0 false positives on unseen code but roughly 26%
recall**, because class-method ops were dropped; the first screen opened a real
repo at 20% zoom; and the tool could not say "I could not check this". Those
three headlines are what Sprint 3 moved, and `docs/ROADMAP.md` (42 ranked items,
11 declined) is what came out of it.

---

## Feature pass and review rounds (2026-09-07)

**Two features on top of the first prototype**, both additive —
`schemaVersion` stayed `"1.0"` and an unscoped run emitted the bytes it emitted
before (§11.13 and the `docs/FEATURES_FLOW_AND_SCOPE.md` design).

- **Flow visibility.** Hovering a connection runs a charge along it from outlet
  to inlet; hovering a node streams its lineage, staggered 90 ms per hop.
  Direction is never decided — every router emits `points` source → target.
  `prefers-reduced-motion`, or more than `FLOW_MAX_EDGES = 120` lit edges, flips
  the canvas to a static chevron plus outlet and inlet dots.
- **Scoped views.** One selector string — `unit:` / `stage:` / `file:` /
  `concern:` / `node:` / `all`, with `depth` 0–2 — projects the whole-workspace
  document in every surface: `--scope` on the CLI, `data-mlview-scope` on the
  report, `Alt+Shift+M` in VS Code, `scope`/`depth` on the MCP tools. A scope is
  a **view, not a filter**: `stage.present`, `workspace` and `diagnostics` still
  describe the full analysis and the VS Code Problems panel is byte-identical
  while scoped. One algorithm, two languages
  (`analyzer/src/mlview/core/project.py` and `webview/src/scope/project.ts`),
  gated against each other by `contracts/scope.cases.json`.

**Integration and review fixes.** Three components that hid themselves never
actually hid (an author `display` outranks `[hidden]`); the drawn hierarchy and
the lexical hierarchy had diverged in `webview/src/layout/model.ts`, so
collapsing one group erased six nodes from another lane and the demo drew 19 of
its 46 cards; `scripts/e2e.sh` had been rewritten LF → CRLF, which is unrunnable
under dash (MLV-R2-H02); and two documents disagreed about the size of the demo
graph (MLV-R2-H05). The doc gate `scripts/check_docs.py` was created in this
pass and grew to eight checks by the end of it, each one the regression gate for
a specific incident.

---

## First build (2026-09-07)

The multi-agent build of the prototype: analyzer, viewer, VS Code extension and
Claude Code plugin, finished with two review → verify → fix rounds (48 confirmed
findings fixed) and a final verification pass. Twenty rules, the frozen
`contracts/graph.schema.json` and `contracts/graph.sample.json`, the
self-contained HTML report, the five MCP tools, and `scripts/build` +
`scripts/e2e` as the two drivers.
