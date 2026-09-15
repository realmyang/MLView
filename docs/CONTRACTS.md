# MLView Contracts v1.1

**Status:** normative. This document binds every component of MLView, and an agent must be able to implement its component from it alone.

**What this is.** v1.0 was a frozen prototype spec plus 63 append-only amendments (§10's thirteen prototype decisions and §11's fifty entries, 11.1–11.47 including 11.13.1, 11.13.2 and 11.17.1). v1.1 is the same contract, folded: every normative clause of v1.0 and of every amendment is carried here, in its home section, with the narrative history removed. The full v1.0 text is archived verbatim at [`docs/archive/CONTRACTS-v1.0-amended.md`](archive/CONTRACTS-v1.0-amended.md) and is the record of *why*; this file is the record of *what*. **§18 maps every old amendment number to the v1.1 section that now carries it**, so a `CONTRACTS.md §11.25` citation anywhere in the tree still resolves.

**Precedence.** A later, more specific clause wins over an earlier general one and says so. Where two v1.0 amendments contradicted each other the later one won, and the losing statement is recorded in §17. Where prose disagrees with a measurement, the command named beside the figure is the authority — **a figure in prose is a record of a measurement, never the authority for one**.

**How to change it.** A change to a contract you do not own is **reported, not made**. During a consolidation wave, contributors write `docs/contracts/<slug>.md` fragments — dated, normative, additive — which the contracts writer folds into the section that owns the clause. Schema changes are **optional fields only**, mirrored byte-identically between `contracts/graph.schema.json` and `analyzer/src/mlview/schema/graph.schema.json`; `contracts/graph.sample.json` never changes; and `mlview analyze --demo --json -` staying byte-identical to that golden is a gate.

**Ownership.** §1–§7 and §14 — analyzer. §8–§10 — viewer. §11 and §13 — plugin/hosts. §12 — VS Code extension. §15–§18 — contracts. `contracts/` is read-only for everyone once written.

---

## 1. Conventions

These are the classic bug sources in a tool of this shape. They are frozen and asserted by tests.

| Convention | Value |
|---|---|
| **Line numbers** | **1-based**, inclusive. Matches `ast.lineno` and every editor. |
| **Column numbers** | **0-based**. Matches `ast.col_offset` and `vscode.Position.character`. The line/column asymmetry is deliberate and documented on every `Loc`. |
| **Boundary conversion** | Convert **exactly once, at the host boundary**: `new vscode.Position(loc.line - 1, loc.col)`. `vscode-extension/src/location.ts` is the only module allowed to do it (`toEditorLine` / `toGraphLine`), asserted by `test/invariants.test.js`. The standalone HTML builds `vscode://file/{absFile}:{line}:{col + 1}`. Nothing else converts. |
| **Paths** | `file` is **workspace-relative with forward slashes** (`models/net.py`). `absFile` is the absolute path, also forward-slashed. Golden tests compare only `file`. |
| **Edge locations** | An edge's `loc` is the **call site** — the statement that created the dependency — not either endpoint's definition. |
| **Ids** | **Content-addressed, never line-derived**, so ids survive edits above a node: `nodeId = "n:" + sha1("<file>\|<qualname>\|<kind>")[:12]`, `edgeId = "e:" + sha1("<source>\|<kind>\|<target>\|<label>")[:12]`, `issueId = "i:" + sha1("<code>\|<file>\|<qualname>\|<symbol>")[:12]`. Asserted by `test_id_stability.py` against a 20-blank-line insertion. |
| **Ordering** | `stages` by `order`; `nodes` by `(stage order, file, line, col)`; `edges` by `(source, kind, target)`; `issues` by `(severity desc, file, line, code)`; every other array by its natural key. Required for byte-determinism. |
| **Volatile fields** | `generator.generatedAt` and `stats.durationMs` are the **only** fields excluded from equality comparisons. Nothing else may be non-deterministic. |
| **Column encoding** | `Loc.col` is CPython's `ast.col_offset`, a **UTF-8 byte** offset. It equals a UTF-16 code-unit offset only on an ASCII line. Reading a location off by a few columns costs a highlight; **applying an edit** at the wrong offset corrupts a file, which is why §5.4 D1 refuses a fix on a non-ASCII line and why the SARIF emitter declares no `columnKind` (§3.8). |
| **Determinism** | Two runs over the same bytes produce the same document, in-process twice and once in a subprocess with a different `PYTHONHASHSEED`. Every set is materialised in document order; no set-iteration order may leak. |
| **No execution** | The analyzed program is never imported, executed, `exec`ed, `eval`ed or compiled. Configuration is read with `tomllib` and nothing else; no YAML or Hydra file is ever opened (§3.7, §5.5). `tests/core/test_no_exec.py` enforces it; `adopt/gitdiff.py` is the single allowed `subprocess` importer and every call there is a list literal beginning `"git"` with no `shell=`. |

---

## 2. The graph document

### 2.1 Schema and root shape

`contracts/graph.schema.json`, mirrored **byte-identically** at `analyzer/src/mlview/schema/graph.schema.json` (asserted by `test_schema.py`) and carried to the vendored copies by `tools/sync-core.py`. Emitted by `python -m mlview schema`. Draft 2020-12, `$id: https://mlview.dev/schema/mlgraph-1.0.json`, `additionalProperties: false` throughout. `schemaVersion` is `"1.0"` and stays `"1.0"`; hosts check the **MAJOR** component and refuse a mismatch.

| Root key | Req. | Meaning |
|---|---|---|
| `schemaVersion` | yes | `const "1.0"` |
| `generator` | yes | `{name: "mlview", version, rendererSha, generatedAt}`. `rendererSha` is the SHA-256 of the viewer bundle this core ships (64 zeros when the asset is absent), so a drifted viewer is detectable from the data alone; `generatedAt` is VOLATILE |
| `workspace` | yes | `{root, entrypoints, filesAnalyzed, filesFailed, notebooksSkipped, frameworks, configPath?}`. `entrypoints` is workspace-relative, ranked most-likely-first, **capped at 10**; `configPath` names the one configuration file applied (§3.7); `notebooksSkipped` is every notebook discovered minus those that really reached the rules (§3.10 N11); `filesFailed` stays the Python-file counter |
| `stages` | yes | **exactly 8**, sorted by `order`, including absent ones |
| `nodes`, `edges`, `issues`, `diagnostics` | yes | arrays, ordered per §1 |
| `stats` | yes | `{nodes, edges, issues, suppressed?, durationMs, truncated}` |
| `pipelines` | no | §6.7 — emitted **only** at two or more non-empty pipelines |
| `view` | no | §6 — emitted **only** by a real projection, and always the **last** key |
| `answers` | no | the four-sentence Pipeline Answer Card (§2.5) |

### 2.2 Frozen enumerations

| `$def` | Values |
|---|---|
| `Severity` | `low`, `medium`, `high` |
| `ConfidenceBucket` | `certain`, `likely`, `possible`, `speculative` |
| `Confidence` | number in `0..1` |
| `RuleCode` / `NodeId` / `EdgeId` / `IssueId` | `^MLV[0-9]{3}$` / `^n:[0-9a-f]{12}$` / `^e:…$` / `^i:…$` |
| `StageId` | `config`, `data`, `preprocess`, `model`, `objective`, `train`, `eval`, `deliver` — rendered top-to-bottom in this order. **Eight, and never nine**: a framework lifecycle hook (`on_train_epoch_end`) is staged by the phase word in its own name and carries the role `LIGHTNING_HOOK_CONTROL`; *control* is expressed by the `control` edge the `Trainer` draws into it. |
| `Framework` | `torch`, `sklearn`, `pandas`, `numpy`, `keras`, `tf`, `hf`, `lightning`, `imblearn`, `torchvision`, `torchmetrics`, `albumentations`, `xgboost`, `lightgbm`, `other` |
| `NodeKind` | `entrypoint`, `config`, `dataset`, `dataloader`, `split`, `transform`, `augment`, `model`, `layer`, `loss`, `optimizer`, `scheduler`, `scaler`, `train_loop`, `eval_loop`, `metric`, `checkpoint`, `tracker`, `predict`, `function`, `class`, `artifact`, `external`, `unknown` |
| `NodeLevel` | `stage`, `unit`, `op` — stage lane > unit (class/function/loop) > op (call/artifact) |
| `EdgeKind` | `data`, `call`, `control`, `config`. **Containment is expressed by `Node.parent`, not by an edge.** |
| `EdgeSubkind` | `enter`, `back`, `branch` — only meaningful for `kind: control` |
| `ValueTag` | `RAW_DATA`, `FEATURES`, `TARGET`, `TRAIN_SPLIT`, `VAL_SPLIT`, `TEST_SPLIT`, `FITTED_TRANSFORMER`, `MODEL`, `LOADER`, `BATCH`, `LOGITS`, `PROBS`, `PREDS`, `LOSS`, `OPTIMIZER`, `DEVICE` |
| `RelatedRole` | `split_site`, `fit_site`, `backward_site`, `optimizer_site`, `step_site`, `eval_loop`, `final_layer`, `definition`, `call_site`, `construction` |
| `Evidence.kind` | `fqn_resolved`, `dataflow_direct`, `scope_static`, `context_confirmed`, `cross_file`, `negation_absent`, `name_regex`, `class_base`, `knowledge_table` — **nine, frozen**. An interprocedural or config-resolution factor is a `cross_file`, which is what it is. |
| `ViewRole` | `core`, `boundary`, `context` (§6.4) |
| `Diagnostic.kind` | the thirteen of §2.6, **all emitted** |
| `Fix.safety` | `mechanical`, `needs-review` (§5.4) |
| `Issue.change` | `new`, `touched`, `existing` (§3.8) |

**Forward compatibility.** An unknown `kind` / `stage` / `edge.kind` / `Diagnostic.kind` / `Issue.change` / `Fix.safety` value must still render: the renderer falls back to the `unknown` visual (or, for `safety`, to the cautious reading) rather than throwing. `Issue.change` and `Fix.safety` are typed `string` in `webview/src/types.ts`, never narrowed.

### 2.3 Locations, ports and evidence

`Loc` = `{file, absFile, line, col, endLine, endCol, symbol?, snippet?}`, all six required. `symbol` is the dotted source text of the target and **must occur inside `[line..endLine]`** — the re-slice guarantee, gated by `tests/core/test_locations.py` and holding over generated notebook modules too. `snippet` is the primary source line, trimmed, `maxLength 200`, so the standalone report can show code without file access. `RelatedLoc` adds a required `role` and an optional `message`, and drives the on-canvas connector **and** `DiagnosticRelatedInformation`. `Port` = `{name, tags[]}`; `Evidence` = `{kind, detail, weight in 0..1}`; `IssueCounts` = `{low, medium, high}`, all required and `>= 0`.

**A multi-line method chain is anchored on the method name.** `ir/locs.call_loc` anchors on `func.attr` **only when `func.end_lineno != node.lineno`**, so every single-line call keeps the `Loc` it had and a parenthesised `tf.data` chain no longer stacks seven nodes on one line.

### 2.4 Node, Edge, Issue, Stage, Stats

**`Node`** — required: `id, kind, level, stage, label, qualname, loc, parent, attrs, produces, consumes, ghost, dynamic, confidence, confidenceBucket, issueIds, collapsedByDefault, stageEvidence`; optional: `sublabel, fqn, framework, var, defLoc, viewRole, rolledUp`.

| Field | Rule |
|---|---|
| `qualname` | a stable dotted name within the file, and an id input, so it must be deterministic |
| `parent` | containment; forms a forest, never cyclic, always a node at a **lower** `level` |
| `attrs` | a `string -> string` map: **stringified literal keyword arguments, never evaluated**, **plus** the notebook provenance keys `notebook` / `cell` / `cellLine` (§3.10 N6), **plus** the resolved-configuration keys `resolvedValue` / `resolvedFrom` / `alternatives` / `unresolved` (§5.5, §10.7). **Provenance wins over a literal keyword of the same name.** |
| `ghost` | `true` marks a REQUIRED-BUT-ABSENT step, drawn as a dashed placeholder in its correct slot. Declared by rules through `ctx.ghost(kind, parent_node, label)`; the builder appends them after rules run, with `qualname = <parent.qualname>.__ghost_<slug>`, `loc` = the parent's, `sublabel: "missing"`, `issueIds` non-empty. |
| `dynamic` | `true` when the enclosing scope contains `exec` / `eval` / `getattr`-on-target / star-import / `**kwargs` forwarding; confidence in that scope is multiplied by **0.7**. A node minted for an *unresolved callee* carries `dynamic = call.scope.is_dynamic`, **not** `True`. |
| `stageEvidence` | backs the inspector's "why is this node in this stage?" popover |
| `rolledUp` | optional, integer ≥ 1 — §3.13 B1 |

**`Edge`** — required `id, kind, source, target, loc, tags, confidence, issueIds`; optional `subkind, label, weight`. `label` is the variable name for data edges, `next batch` / `next epoch` for control back-edges. `weight` (optional, ≥ 2) — §3.13 B2.

**`Issue`** — required `id, code, ruleVersion, severity, confidence, confidenceBucket, title, message, why, fixHint, loc, relatedLocs, nodeIds, edgeIds, stage, frameworks, tags, evidence, suppressed, docs`; optional `baselined, change, fix`. `message` cites concrete evidence — variable names and line numbers — never a restatement of the title; `why` is the consequence, in ML terms, in one sentence; `fixHint` is one actionable sentence naming the actual API, `minLength 1`. **`nodeIds[0]` is the PRIMARY node** — that is where the badge is drawn; others get a 1px severity ring only. `suppressed: true` (an ignore comment or the configuration matched) is **still emitted** so the UI can offer "show suppressed", and is never published as a diagnostic. `docs` is the relative path to the offline rule page.

**`Stage`** — all seven keys required; `present: false` stages are named in the "not detected" chip row, never drawn as empty bands. **`Stats`** — `durationMs` is VOLATILE; `truncated` means "this document is not the whole graph" (§3.13) and the **words** are the diagnostic's job; `stats.issues` counts every unsuppressed finding and is the document's project-level truth — a baselined finding is netted out of the *rendered* counts, never out of `stats`.

### 2.5 The four optional blocks

**`view`** — present **only** on a PROJECTION (§6). Required inside: `scope, label, depth, counts{core,boundary,context}, of{nodes,edges,issues}, hidden{nodes,edges,inboundEdges,outboundEdges}, resolvedTo[]`; optional `ambiguous`, `empty`. **An unscoped `analyze` MUST NOT emit the key** — that is what keeps `--demo` byte-identical to the golden.

**`answers`** — `{dataEntry, objective, evaluation, verdict}`, each `{sentence, nodeIds[], locs[{file,line}], confidence}`, composed by `emit/answers.compose(doc)`, a pure `dict -> dict` over an already-sorted `nodes[]`: **no model, no network, no clock**, so all three hosts print the same bytes for the same graph.

| # | Rule |
|---|---|
| **P2** | **An absence is stated as an absence.** A workspace with no eval stage is told so in words; printing nothing is not an option. |
| **P3** | Nothing under `MIN_CONFIDENCE` (**0.6**) is asserted as fact. A candidate below the floor is dropped from the citation and **counted**: *"N further candidate(s) were below the 0.6 confidence floor and are not asserted."* |
| **P4** | **A ghost node is never cited**: a ghost marks something expected and not found, so citing one as a located fact inverts its meaning. Ghosts are read in one place — the eval guard — where the absence itself is the answer. |
| **P5** | `confidence` is the **weakest** node the sentence rests on, and `0.0` exactly when nothing is cited. The `verdict`'s is the weakest **finding** it names. |
| **P6** | The guard clause is stated **only where a guard was found**, present or missing. A sklearn-only pipeline has no eval mode to guard, and inventing its absence would be a finding MLView did not make. |
| **P7** | The `verdict` names the top three findings by **severity × confidence** and appends the coverage caveat whenever any coverage diagnostic is present: *"…so this is not a clean bill of health."* **A clean verdict on a blind run is the one sentence this card must never print.** |
| **P8** | A projection carries the whole-project answers verbatim (§6.4 step 10). |
| **R7** | With any coverage diagnostic present the `objective` and `evaluation` absence sentences carry *"and N call(s) could not be read"*, and the `no backward() call` clause — which the analyzer cannot know — is dropped. With nothing unread the flat sentence is unchanged, byte for byte. |

**`pipelines`** — §6.7 D. **Issue-level optional fields** — `change` (§3.8 A2), `baselined` (§3.8 B3), `fix` (§5.4); each emitted **only when set**, so a run of a rule that did not opt in is byte-identical to what it produced before the field existed.

### 2.6 Diagnostics — thirteen kinds, all emitted

| kind | Meaning |
|---|---|
| `parse_error` | A file could not be parsed. For a notebook it names the `.ipynb`, never the generated module. |
| `dynamic_scope` | A scope carries a dynamic construct; also a re-export chain past `_MAX_REEXPORT_HOPS` (**3**), naming the symbol and the cap. |
| `rule_error` | A rule raised (`MLV000`) and was recorded rather than crashing the run. |
| `truncated` | The node budget bound (§3.13); the IR convergence loop stopped on `MAX_ROUNDS = 8`; an interprocedural chain exceeded the hop cap (§3.11 N5); an ANA-10 cap was reached (§5.5); or a scope was taken over an already-capped graph (§6.6). |
| `notebook_skipped` | A `.ipynb` was discovered and not analyzed. |
| `framework_suppressed` | Which rules were not applied, in `codes`. |
| `config_warning` | Every configuration mistake, every scope-resolution note, every degradation of change attribution, every unmatched baseline entry, the prefilter's set-aside note, and a typo'd rule code with up to three near misses. **No configuration mistake may stop an analysis.** |
| `untagged_dataflow` | A rule reached a value it never traced — **no `ValueTag` at all** — and stayed silent. A coverage gap, not a finding. |
| `single_file_analysis` | One file of a larger package was analyzed, so the cross-file rules could not see the siblings they need. |
| `unresolved_callee` | A call the analyzer could not resolve. **The call is never dropped**: it mints an `unknown` op carrying the construct. |
| `config_unresolved` | A YAML/Hydra configuration the workspace names and this run did not open (§5.5 A7). |
| `notebook_analyzed` | A notebook **was** analyzed, carrying the execution-order caveat (§3.10 N10). |
| `framework_filter` | `--framework <x>` narrowed the **rule set**, so rules the detected frameworks would have run did not (C8 below). |

| # | Rule |
|---|---|
| **C1** | `untagged_dataflow` is emitted **once per `(file, scope)`**, never per site: `codes` lists every rule that gave up there, `count` the untraced values, `line` the earliest, and the message names up to three with their lines and says *why* the tag is missing. A rule looping over sites must not emit a diagnostic per iteration. |
| **C2** | A rule declares a coverage gap through `GraphContext.untraced(call, name, reason)` and **never** by appending a `Diagnostic` itself. No rule's gate changes: the branch fires only where the value carries **no tags at all**. |
| **C3** | `single_file_analysis` fires only when all three hold: exactly one module analyzed, sibling Python modules exist under the same package root, and the analyzed module **imports at least one of them**. |
| **C4** | Its `codes` come from `RuleSpec.cross_file`, a declared boolean — never a hand-maintained list. Today **MLV301, MLV302, MLV401, MLV501**, asserted as an equality against what a single-file run actually loses. |
| **C5** | `count` is the number of sibling modules **not** analyzed; the message names up to four and how many the analyzed module imports. |
| **C6** | The summary emitter gives coverage diagnostics **their own block**, `Coverage (N)`, above `Notes (N)` and outside the ten-note clip. |
| **C7** | `RuleSpec.cross_file` is appended **last** and defaults to `False`; `rules.cross_file_codes()` is the only supported way to read the set. |
| **A7** | `unresolved_callee` is emitted **once per `(file, scope)`**, naming up to three sites and then the **distinct constructs** not already named; `count` = sites, `line` = earliest. |
| **R11** | A `backward()` and an optimizer `step()` in a loop no classifier confirmed raise an `untagged_dataflow` note naming the loop, the backward line and the three codes that did not judge it. **A full-batch training loop is not judged, and is never silent.** |
| **C9** | **A host renders every coverage kind the core emits.** The set each host reads MUST equal `core.coverage.COVERAGE_KINDS` as a **set** — render order is each host's own. The three copies are `core.coverage.COVERAGE_KINDS` (the authority), `claude-plugin/server/mlview_notes.py::COVERAGE_KINDS` and `vscode-extension/src/coverage.ts::COVERAGE_DIAGNOSTIC_KINDS`, gated by `claude-plugin/tests/test_payload_truth.py::test_this_host_reads_every_coverage_kind_the_core_emits` and `vscode-extension/test/coverage.test.js::this host reads every coverage kind the core emits` (both compare against the analyzer's own declaration, not a transcription). `api.digest` drops `graph["diagnostics"]` wholesale, so a kind a host does not list is a caveat the model or the viewer **never sees**: `framework_filter` shipped in the core alone, and because `framework` is a model-settable argument of `mlview_analyze`, a model that passed `framework="sklearn"` at a torch project read `0 high / 0 medium` where `auto` reports `1 high / 1 medium`, with no sentence anywhere in the payload saying why. `framework_filter`'s `count` is **suppressed rule codes, not blind sites**: a host carries the per-kind `message`, never a bare tally, and never adds that count to a blind-spot total. |
| **C8** | **`--framework <x>` says so in the document.** The flag narrows the **rule set** — `rules.registry._applies` drops every rule that does not declare the named framework, including rules the *detected* frameworks would have run — so it is the same silent narrowing `single_file_analysis` exists to make loud. `framework_filter` is a **coverage** kind (`core.coverage.COVERAGE_KINDS` is `("untagged_dataflow", "single_file_analysis", "framework_filter")`, which is why the summary gives it the coverage block; **no host imports that tuple** — each keeps its own closed copy, and C9 is what keeps them equal); it is emitted **once per run**, after every rule has run, by `rules.registry.run_all` and **never once per skipped rule**; `codes` is every rule code that **would have run under `--framework auto` on this workspace** and did not, sorted, `count` is `len(codes)`, and the message names at most six and counts the rest so the block stays inside the 4 KB payload budget. It is **silent when the flag cost nothing** — `auto` or unset, or a filter that dropped no rule the detected frameworks would have run — because a caveat on every run is a caveat nobody reads. **The findings themselves are unchanged** by its presence: same ids, confidences, severities and messages. `core.coverage.framework_filter_diagnostic(framework, skipped)` is a pure function of its two arguments and returns `None` rather than an empty caveat. A consumer that does not know the kind still passes it through untouched inside `diagnostics`, but a **host** that does not read it is a contract breach and not a graceful degradation (C9). |

### 2.7 Invariants the renderer relies on

1. All ids are globally unique and stable across runs when the source is unchanged.
2. `parent` forms a forest; no cycles; a parent always sits at a **lower** `level`.
3. `issue.nodeIds[0]` always exists in `nodes[]` and is the primary.
4. `stage` is always present; unclassifiable nodes get `kind: "unknown"` and their best-guess stage.
5. `stages[]` is always all eight, sorted by `order`, including `present: false` entries.
6. **Forward compatibility** — §2.2.
7. Every `edge.source` and `edge.target` exists in `nodes[]`.
8. `ghost: true` nodes have `issueIds.length >= 1`. After any rollup a surviving ghost with no live issue is removed, then edges and `nodeIds` are re-filtered (`drop_orphan_ghosts`).
9. **A document carrying `view` is a PROJECTION.** Its `nodes`, `edges` and `issues` are **subsequences** of the unprojected arrays in the same relative order; every kept node carries `viewRole`; `counts.core + counts.boundary + counts.context == stats.nodes`; `stage.present` and every field of `workspace` and `generator` still describe the FULL analysis; invariants 1–8 hold.
10. `rolledUp`, where present, is an integer ≥ 1; `weight`, where present, an integer ≥ 2.
11. **No edge is a self-loop** (`source != target`), on any document.
12. A document carrying any `rolledUp` or any `weight` has **no two edges sharing `(source, kind, target)`**. Deliberately *not* unconditional: two `data` edges differing only in `label` are ordinary and legal in a full-fidelity document.
13. When `stats.truncated` is **false**, no node carries `rolledUp` and no edge carries `weight`.

`contracts/validate_sample.py` checks the schema **and ten invariant groups**; 10–13 fold into its existing `edges` and `stats` groups rather than adding an eleventh, so the "schema + ten invariant groups" claim elsewhere in the tree stays true. The fifth rollup invariant — `stats.truncated` true ⇒ at least one `Diagnostic{kind: "truncated"}` — is an **emitter** obligation, asserted in `test_rollup.py`, not in the validator.

**Projection carve-outs.** `validate_sample.py`'s "a present stage has nodes or issues" branch is guarded with `and doc.get("view") is None`; `test_graph_invariants.py` asserts the `present`/`nodeCount` equality only when `"view" not in doc`, and for a projection asserts instead that `present` equals the unprojected `present` and `nodeCount` equals the kept nodes of that stage.

### 2.8 The golden document

`contracts/graph.sample.json` is **hand-authored** — 12 nodes / 14 edges / 6 issues — published before any analyzer existed so the viewer and both host adapters were buildable from minute one. It is **never regenerated by anything, ever**. `mlview analyze --demo` emits exactly these bytes and does not run the pipeline. It carries no `answers`, no `fix`, no `pipelines` and no `view`.

## 3. The CLI

`contracts/cli.md` is this section. **Both hosts call exactly this. Nothing else parses Python.**

### 3.1 Commands

```
python -m mlview analyze  <path>... [options]        python -m mlview baseline write [<path>...] [--out FILE]
python -m mlview issues   <path>... [options]        python -m mlview diff BASE.json HEAD.json [--json FILE|-] [--format summary|json]
python -m mlview render   [--graph FILE | <path>]    python -m mlview init [<path>] [--out FILE|-] [--force]
python -m mlview explain  (<node-id>|<rule-code>) [--graph FILE] [--json]
python -m mlview rules    [--list | --json | --explain MLV201]
python -m mlview schema                              python -m mlview --version [--json]
```

### 3.2 `analyze` options

| Flag | Default | Meaning |
|---|---|---|
| `--json <FILE\|->` | — | Write the graph JSON. `-` means stdout, and then **stdout carries only JSON**. |
| `--html <FILE>` | — | Write a self-contained HTML report (viewer JS + CSS + graph inlined). |
| `--open` | off | Open the HTML afterwards (`os.startfile` on Windows, `webbrowser.open` elsewhere). |
| `--format summary\|json\|mermaid\|text` | `summary` | stdout format when `--json -` is not used. |
| `--include <GLOB>` | — | Repeatable. Restrict discovery. |
| `--exclude <GLOB>` | `**/.venv/**`, `**/site-packages/**`, `**/node_modules/**`, `**/build/**`, `**/.git/**` | Repeatable; **adds to** the defaults. |
| `--min-severity low\|medium\|high` · `--min-confidence <float>` | `low` · `0.0` | Filter emitted issues. |
| `--show-suppressed` | off | Include suppressed and baselined issues in the summary (they are always in the JSON). |
| `--max-files <N>` | `500` | Discovery cap. |
| `--max-nodes <N>` | `400` | Node budget; sets `stats.truncated`. §3.13. |
| `--framework auto\|torch\|sklearn\|keras\|hf\|lightning` | `auto` | Restrict framework extractors. |
| `--config <FILE>` | discovery per §3.7 | The configuration file. |
| `--fail-on none\|low\|medium\|high` | `none` | Exit 2 when an issue at or above the threshold exists among the **retained** findings. |
| `--strict` | off | Re-raise rule exceptions instead of recording `MLV000`. |
| `--demo` | off | Emit the golden `contracts/graph.sample.json`. |
| `--no-color` | off | Plain stderr output. |
| `--group-by rule\|file\|severity\|none` | `none` | A rendering choice, **never a filter**: `--json` is byte-identical with and without it, and the `N issue(s)` header keeps counting occurrences, not groups. `--format text` is deliberately **not** grouped. |
| `--relevance ml\|all` · `--relevance-hops <N>` · `--no-cache` | `ml` · `2` · off | §3.9. |
| `--dataflow local\|ip` | `ir.build_ir.DEFAULT_DATAFLOW` (**`ip`** in this build; the constant is the authority and this table follows it) | §3.11, R1.1. |
| `--include-notebooks` | off | §3.10. |
| `--changed-since <REV>` · `--changed-paths <FILE>` · `--changed-only` | off | §3.8 A. |
| `--baseline <FILE>` · `--sarif <FILE\|->` | — | §3.8 B, C. |
| `--progress-json` | off | §3.12. |
| `--scope <SPEC>` | none (`all`) | §6. Not repeatable. Applies to `--json`, `--html` and every `--format`. |
| `--depth <N>` | per-kind (§6.1) | Boundary hops, `0..2`. Taken as text, not `type=int`, so a bad value comes back as the contractual `bad_depth` code rather than argparse's usage error. |
| `--list-scopes` | off | Print the scopable-unit catalogue (`spec`, `label`, `file:line`, `nodeCount`, `issueCounts`, `SUBTREE`) to **stdout** as the requested payload — text, or JSON with `--format json` — then exit 0. Mutually exclusive with `--json`, `--html` and `--scope`. |

### 3.3 The other commands

`issues` takes `--json`, `--text`, `--min-severity`, `--min-confidence`, `--code MLV201,MLV301`, `--limit N`, `--max-files`, `--max-nodes`, `--include`, `--exclude`, `--config`, `--show-suppressed`, `--fail-on`, `--strict`, `--no-color`, and the same relevance, dataflow, notebook, group-by, adoption and scope groups as `analyze`. **`--text` renders** (`emit/text_out.render_findings`) — the same message / why / fix block `analyze --format text` prints. `render` takes `--graph FILE`, `--out FILE`, `--format html|mermaid|text`, `--open`, `--max-files`, `--max-nodes`, `--config`, `--no-color`, the relevance flags and the scope flags; `render --graph FILE --scope <SPEC>` projects an **already-written** document, so a scope can be taken without re-analysing. `baseline write` (§3.8 B7) has `write` as its only action, positional so a later `check` / `prune` needs no new command. `diff` is §7; `init` is §3.7 D; `explain`, `rules`, `schema` and `--version` are unchanged.

### 3.4 Exit codes

| Code | Meaning |
|---|---|
| `0` | Analysis produced a graph — including when `diagnostics[]` is non-empty, and including a valid selector with an **empty** result (a zero-node document carrying `view.empty: true`, plus one note on stderr naming the selector and the whole-graph size) |
| `1` | Usage or I/O error — an invalid selector or bad depth (stdout **untouched**; stderr carries the `code`, the offending term and ≤10 sorted candidates); `--scope` with `--demo` (`bad_selector`: the golden is a fixed artefact); `--sarif -` together with a `--json` that also claims stdout; a `diff` input that is missing, is not JSON, is not an MLView graph, or is itself an overlay; `init` over an existing file without `--force` |
| `2` | `--fail-on` threshold exceeded. The threshold line **also names the active scope**, so a narrowed CI gate is visible in the log. |
| `3` | Internal error (a JSON error object is written to stdout) |
| `4` | Nothing analyzable found (no `.py` files after filtering) |

**No new exit code has ever been added, and none may be.**

### 3.5 The stdout and UTF-8 invariants

**stdout carries only the requested payload.** Every log line, warning, progress frame and written-artifact path goes to **stderr**. Enforced by `test_stdout_purity.py`, which greps the core for bare `print(` outside `emit/text_out.py`: a single stray print corrupts a JSON parse or a JSON-RPC frame. **Every spawn of the CLI, from either host, passes `-X utf8` in argv and `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` in the environment, with `shell: false` and an absolute interpreter path** — without them cp1252 mangles the JSON on a non-ASCII identifier or path.

### 3.6 The text surfaces

`--format summary` prints, in order: the header lines, **`Answers`** (§2.5; absent when the document carries no `answers`, which is why `--demo` is textually unchanged), `Stages`, the issue table, **`Fixes (N)`**, **`Coverage (N)`**, then `Notes (N)`.

| # | Rule |
|---|---|
| **B3/R12** | A baselined finding is **marked, never deleted**. The heading is `Issues (<net> · N baselined · M suppressed)`, dropping the zero terms, and the row carries `(baselined)` — **one command's output may never state two numbers**. |
| **F2** | A row carrying a structured fix is marked `(fix)`, where `(suppressed)` and `(baselined)` are marked. |
| **F4** | The `Fixes` block **states its denominator**: *"no edit was computed for 1 other finding(s) of MLV602 — see `docs/rules/<CODE>.md` for when one is withheld"*. |
| **F5** | A document with no fixes renders **byte-identically** to what it rendered before the field existed. |
| **A8** | **No emitter may claim a stage is absent without qualification when a call was unresolved.** `emit/text_out` and `emit/mermaid_out` append *"(unverified: N call(s) could not be resolved, so a stage may be present but undetected)"* to the `not detected:` line. |
| **R6** | `mlview issues` renders the diagnostics `analyze` renders: the `Coverage` and `Notes` blocks in the text body, `diagnostics` in the `--json` payload. Under `--changed-only` the header names the set-aside count (`· N not shown`) and the empty body reads *"none shown — N finding(s) do not touch the change; see Notes below"*. **It may never print a bare `none found` while something was withheld.** |
| **Scope line** | A scoped run adds exactly **one line** per non-HTML format and nothing else: `summary`/`text` gain `scope: <spec> · depth <n> · <inScope> of <total> nodes`; `mermaid` gains a leading `%% scope: …` comment. `--json` emits the projected document verbatim; `--html` embeds the **full** graph (§9.3). **An unscoped run's output is byte-identical to what it has always been.** |
| **Size band** | `emit/html_out.write_html` enforces the 100 KB – 2 MB report band at runtime: an out-of-band report is still written, with a warning on **stderr** naming `--max-nodes` as the lever. The bundle-absent fallback report is exempt. |

### 3.7 Configuration — one surface, one stated precedence

The whole file is parsed in one place, `core/config.py`; `rules/suppress.py` re-exports `RuleConfig`, `load_config`, `known_codes` and `unknown_code_warning` from there and keeps only the ignore-comment index, so `mlview.rules.load_config` — the import path every caller uses — is unchanged. `MlviewConfig` is the class, `RuleConfig` an alias whose first five fields are the historical surface in the historical order.

| # | Rule |
|---|---|
| **A1** | **One file, chosen in one order, never merged:** `--config FILE`, else `<root>/.mlview.toml`, else the `[tool.mlview]` tables of `<root>/pyproject.toml`. The first that exists wins **outright**; the others are not read. |
| **A2** | `<root>` is `ingest.discover`'s own root, reached through `core.config.probe_root` → `discover._common_root`. **A second implementation of "where is the root" is forbidden.** |
| **A3** | Under `pyproject.toml` the tables are `[tool.mlview.{rules,paths,analysis,baseline}]` and are otherwise identical. A `pyproject.toml` with **no** `[tool.mlview]` table is not a configuration file: `configPath` is absent and nothing is applied; passing such a file to `--config` explicitly is a `config_warning`, not an error. |
| **A4** | The file that was applied is named in `workspace.configPath`. No new field. |
| **A5** | The file is resolved **before** discovery, so `[paths] include` / `exclude` narrow the first walk and `[analysis]` is in force for the whole run. |

| table | key | type | effect |
|---|---|---|---|
| `[rules]` | `disable` / `enable` / `min_confidence` | codes / codes / `0..1` | suppressed (still emitted with `suppressed: true`) / an **allow-list** (B3) / findings below it are filtered out |
| `[rules.severity]` | `<code>` | `low\|medium\|high` | **reported and ignored** (B4) |
| `[paths]` | `exclude` / `include` / `notebooks` | globs / globs / bool | added to `--exclude` / added to `--include` / the checked-in half of `--include-notebooks` |
| `[analysis]` | `relevance`, `relevance_hops`, `dataflow`, `max_nodes`, `include_notebooks` | as the matching flag | |
| `[baseline]` | `path` | file path | as `--baseline`, resolved against the config file's directory |

| # | Rule |
|---|---|
| **B1** | Every table and key is optional. A file naming none of them behaves **exactly** as no file at all, except that `configPath` names it. |
| **B2** | The legacy inline spellings `MLV601 = "off"` and `MLV601 = "high"` under `[rules]` still behave as they did. **Nothing that worked stops working.** |
| **B3** | **`enable` is an allow-list, not an un-disable.** Empty or absent means every registered rule; non-empty suppresses every rule outside it, expressed as `disabled \|= known_codes() - enable` so one mechanism still does all the suppressing and a rule turned off this way is still **emitted** with `suppressed: true`. A code in both lists stays **off** and the contradiction is a `config_warning`. It cannot resurrect a rule the build ships with `enabled=False`. |
| **B4** | **Severities are fixed.** A `[rules.severity]` entry is recorded, reported as a `config_warning` and **never applied**: refusing the whole file over it would throw away the `disable` list beside it. An invalid severity *value* is a different warning naming the three allowed words. |
| **B5** | `[baseline] path` is applied in the CLI, not in the pipeline — a baseline is applied to the **finished graph**, never to the analysis. `--baseline` on the command line always wins. |
| **C1** | **`disable` and `exclude` belong to the file.** A host — the VS Code settings, the plugin, a flag — may **add** to them and may never take one away. |
| **C2** | **A flag beats the file for every `[analysis]` option** and for `[rules] min_confidence`, because a flag is something a human typed just now. `[paths] include` is the exception in the other direction: **additive**, exactly as `exclude` is, since a filter a file and a flag both narrow must end up narrower. |
| **C3** | `AnalyzeOptions` carries values, not provenance: an option still equal to its dataclass default reads as "the caller did not ask". A caller who **types** a flag at exactly its shipped default is therefore indistinguishable from one who typed nothing, and **the file wins that one case** — pinned by `test_the_one_case_the_precedence_cannot_see`. |
| **C4** | **No configuration mistake may stop an analysis.** An unreadable file, an unparseable file, a wrong type, an out-of-range number, an unknown key, an unknown table and an unknown rule code are each **one `config_warning`**, naming the file and, where there is a near miss, the key or code probably meant. |
| **D1** | `mlview init [PATH] [--out FILE\|-] [--force]` writes `<root>/.mlview.toml`. The payload is the **file**, so stdout stays empty and the path goes to stderr; `--out -` asks for it on stdout and writes nothing. |
| **D2** | **Every key in the generated file is commented out.** Running `init` cannot change what a later `analyze` reports — asserted by re-analysing the same workspace before and after and comparing finding ids. |
| **D3** | The file ends with **every registered rule, with the severity it ships at**, generated from the registry, so a rule added in a commit is in the next file `init` writes. |
| **D4** | An existing file is **never** silently overwritten: `init` exits 1 naming `--force`. |

**Stated limit.** An unknown key under `[rules]` is reported as an *unknown rule code*, not an unknown key, because the legacy `MLV601 = "off"` spelling makes every key in that table code-shaped; the near-miss suggestion is the mitigation.

### 3.8 CI adoption — attribution, the baseline ratchet, SARIF

**A0 — the analysis is never narrowed.** Every flag here runs after a **whole-workspace** analysis and edits the finished document. Narrowing the analysis to the changed files is a fidelity loss that would be invisible: the output would simply be smaller.

| # | Change attribution |
|---|---|
| **A1** | The diff is `git -c core.quotepath=false diff -M --unified=0 --no-color <rev> --`, run in the analyzed root. **`-M` is normative** — without rename detection a moved file reads as entirely new; `--unified=0` is what makes line attribution possible at all. |
| **A2** | `Issue.change` is a closed three-value enum. **`new`** — the primary `loc` is inside an added hunk. **`touched`** — a `relatedLoc` is inside an added hunk, **or** the primary `loc` is in a changed file outside every hunk. **`existing`** — neither. Emitted **only** when attribution succeeded; its absence means *unattributed*, never *old*. |
| **A3** | **`--changed-only` keeps exactly the findings that intersect an added hunk** — `new`, plus the `touched` whose evidence is inside one — and drops `existing` together with the `touched` that merely share a file. `change` stays a three-value **display** classification; `--changed-only` is the **gate** filter. A finding whose `relatedLoc` lands in a hunk is `touched` and is **never** dropped. |
| **A4** | `--changed-paths FILE` accepts **either** a unified diff **or** a newline-separated path list. A path list has no hunks, so nothing can be `new`; the run says so through a `config_warning` and `--changed-only` then keeps every finding in a changed file. |
| **A5** | **Every failure degrades to "unattributed, showing everything" with a `config_warning`** — never to an error and never to an empty list: no git on PATH, not a repository, an unknown revision, a git that does not answer within 20 s, an unreadable `--changed-paths`. Nothing is dropped, `--changed-only` is inert and says so, and the exit code is whatever the findings justify. **A gate that passes because git was missing is worse than no gate.** |
| **A6** | Paths are mapped through `git rev-parse --show-toplevel` into workspace-relative form, and a changed file outside the analyzed root is discarded. |
| **A7** | `--changed-only` may remove the only finding a ghost carried, so the ghost sweep and `finalize()` re-run afterwards: invariant 2.7/8 and every ordering rule hold on the emitted document. |
| **R5** | **A notebook finding is attributed to its source `.ipynb`.** `adopt.notebook_source()` is the exact inverse of `ingest.notebook.shadow_relpath`; a finding in a generated module is attributed to the notebook at **file** granularity, so a notebook with any added line counts as changed throughout and its findings are `new`. A `config_warning` names the count and says granularity was traded for a location git can see. |

| # | The baseline ratchet |
|---|---|
| **B1** | The match key is **`(code, symbol, snippetHash)`**, `snippetHash = sha1(" ".join(snippet.split()))[:12]`. Not the line, because a baseline that dies on an edit above the finding is a baseline nobody keeps; not the file, because a renamed module carries the same finding. |
| **B2** | **Matching is counted, not keyed alone.** A key recorded *n* times forgives the first *n* findings carrying it, in document order; the *n+1*th is reported. Without the count a copied training loop would arrive pre-forgiven. |
| **B3** | A matched finding is **marked, never deleted**: `Issue.baselined: true`, the issue stays in `issues[]`, `--show-suppressed` lists it, it is excluded from the **rendered** counts and from `--fail-on`, and `stats.issues` is unchanged. |
| **B4** | **Unmatched entries are reported, always**: `N baseline entries no longer match: …` as a `config_warning` naming up to three. A baseline that has silently stopped matching is a gate that has silently stopped gating. |
| **B5** | The document is `{"version": 1, "tool": "mlview", "entries": [...]}`, sorted, with **no timestamp and no analyzer version**: it is committed and reviewed. `file`, `line` and `title` are written for that reviewer and are **never** matched on. |
| **B6** | A baseline that cannot be read, is not JSON, or declares another format version is a `config_warning` and every finding is reported. Never an exit code. |
| **B7** | `mlview baseline write` writes the file and nothing to **stdout**; the path goes to stderr. Default `--out` is `<root>/.mlview/baseline.json`. |

| # | SARIF 2.1.0 |
|---|---|
| **C1** | `--sarif FILE` writes SARIF 2.1.0; `--sarif -` writes it to stdout, and combining that with a `--json` that also claims stdout is a **usage error** (exit 1, stdout untouched). On `issues` the SARIF honours `--code` but not `--limit` and not the suppressed/baselined hiding. |
| **C2** | **No absolute path is ever emitted.** Every `artifactLocation.uri` is the workspace-relative `Loc.file` with `uriBaseId: "%SRCROOT%"`, and `originalUriBaseIds["%SRCROOT%"]` carries a `description` and **no `uri`**. |
| **C3** | `partialFingerprints.mlviewIssueId` is `Issue.id` — content-addressed, never line-derived — re-asserted end to end across 20 inserted blank lines. |
| **C4** | `tool.driver.rules[]` is the **whole registry**, not the rules that fired, so `ruleIndex` is stable between runs. |
| **C5** | Severity maps `high → error`, `medium → warning`, `low → note`; `rank` is `confidence × 100`. A **suppressed or baselined** finding ships as a result carrying `suppressions[{kind: "external"}]`, not as a missing one. `change` maps to `baselineState` (`new → new`, otherwise `unchanged`). |
| **C6** | The document deliberately declares **no `columnKind`** (§1). Columns are `col + 1`, SARIF being 1-based. |
| **C7** | `runs[0].properties.diagnostics` carries every `Diagnostic` kind and message: what the analyzer could **not** see travels with the findings. |
| **R8** | `reportingDescriptor.helpUri` is **absolute** — `https://github.com/realmyang/MLView/blob/v<__version__>/docs/rules/<CODE>.md`, pinned to the running version. The in-repo path stays as `properties.docsPath` with `properties.docsPathBaseId`; `artifactLocation.uri` is unchanged. |
| **C8** | **`Issue.fix` reaches SARIF as `result.fixes[]`** — the one surface that needs no host work, since GitHub code scanning renders it as the alert's suggested change. A result carries `fixes` **only when its issue carries `fix`**, never `fixes: []`, so every SARIF document produced before this clause is unchanged. One `fixes[]` entry with one `artifactChanges[]` entry (every edit of one fix names one file, §5.4 A6), whose `artifactLocation` is the workspace-relative `file` under `uriBaseId: "%SRCROOT%"` — C2 is not weakened. One `replacements[]` entry per `TextEdit`, in the order the fix lists them: `deletedRegion` is `{startLine, startColumn, endLine, endColumn}` with **1-based columns** (`col + 1`), the same conversion `locations[]` makes, and an **insertion is a zero-width `deletedRegion`**, which is §5.4 A3's own spelling of one. `fixes[0].description.text` is `Fix.title`; the safety grade travels as `result.properties.fixSafety`, verbatim, and there is **no `isPreferred`** — SARIF has no such member on a fix, and inventing one would be the second spelling of one decision §5.4 A5 refuses. A malformed edit withholds the **whole** fix (`sarif_out.fixes_for` is pure and returns `[]`), and the document still validates against the vendored **official** OASIS SARIF 2.1.0 schema with `fixes[]` present — that schema, not this repository, is the judge of the shape. |

### 3.9 The relevance prefilter and the fact cache

Both ship **on**: `core.pipeline.DEFAULT_RELEVANCE` is `"ml"`, `AnalyzeOptions.relevance` defaults to `"ml"`, the flag defaults to `ml` on `analyze`, `issues`, `render` and `baseline`, and because `all` never consults the sidecar the first default turns the cache on as well.

| # | Rule |
|---|---|
| **A2** | **`all` is the identity.** It derives no facts, consults no cache and makes exactly the single `parse_all` pass the analyzer has always made. |
| **A3** | A module is a **seed** when its source contains, as a whole word, any token in `core.relevance.framework_tokens()`. That set is **derived** from the knowledge tables minus `GENERIC_ROOTS = {argparse, json, os, pickle, random, toml, tomllib, yaml}`. `GENERIC_ROOTS` is the **only** hand-maintained half: a framework added to `knowledge/` becomes a seed token in the same commit. |
| **A4** | The kept set is every seed, everything within `--relevance-hops` of one **in either direction** over the module import graph, and every `__init__.py` on a kept module's package path. |
| **A5** | The import graph is resolved through `ir.symbols._relative_base` / `_sibling_module` — the analyzer's own — and re-export chains are followed for up to `_MAX_REEXPORT_HOPS` hops. **A second implementation of module naming is forbidden.** |
| **A6** | **The refusal.** If nothing is a seed, nothing is set aside and no diagnostic is emitted. |
| **A7** | A path the caller named as a **file** is always a seed. |
| **A8** | Narrowing emits exactly one `config_warning` naming the set-aside **count**, the hop count, up to four files by relpath and **both** `--relevance all` and `--relevance-hops`. When nothing was set aside there is **no** diagnostic. |
| **A9** | **Every discovered file is still read and still parsed on a cold run**, so a `parse_error` in a set-aside file is reported in both modes and `filesFailed` is unchanged. Only `filesAnalyzed` moves, and A8's diagnostic accounts for the difference. |
| **A10** | **What it cannot see.** The seed scan is a byte match and cannot tell `import torch` from the word `torch` in a docstring; it errs towards keeping. The hop walk cannot see a module reached only through `importlib`, a plugin registry or a dotted name held in a string. A **workspace-wide absence rule** (MLV601) means "absent from the kept set" under `ml`: same finding, anchored inside the kept set. |
| **B1** | `mlview.core.cache.file_signature` is the **only** implementation; the plugin's copy is a wrapper. The key is **content**, not `st_mtime_ns` and `st_size`. The walk prunes exactly `ingest.discover.ALWAYS_PRUNE` and stops at 2000 files. |
| **B2** | The cache key is `(content digest, analyzer identity, python major.minor)`, with the workspace root folded into the sidecar's name. An unreadable package yields `unknown-<pid>`, which no stored file can match, so the cache is **off** rather than trusted. **No analysis option is in the key**: none of them changes what a file imports. |
| **B3** | **Only the per-file relevance facts are cached** — "is this a seed" and "what does this import", both pure functions of one file's bytes. Caching a pickled `ast` or a pickled module IR was measured and **rejected**. |
| **B4** | **The cross-module fixed point and every rule always re-run over the whole kept set.** Nothing derived from more than one file is ever cached, which is why a warm run is **byte-identical** to a cold one. |
| **B5** | **The sidecar never lands inside the analyzed folder.** `core.cache.cache_dir_for(root)` returns `MLVIEW_CACHE_DIR` when it is set and non-empty, else `<user cache root>/<root key>`, and **it never returns a path inside `root`**. `core.cache.user_cache_root()` is `$XDG_CACHE_HOME/mlview` when `XDG_CACHE_HOME` is set — on *every* platform, because a user who set it has said where caches go — else `%LOCALAPPDATA%/mlview/cache` on Windows, `~/Library/Caches/mlview` on macOS, `~/.cache/mlview` everywhere else. `core.cache.root_key(root)` is 16 hex characters of BLAKE2b over the **normalised absolute** root, naming the per-workspace directory *and* the sidecar inside it (`<user cache root>/<key>/facts-<key>.json`), so two workspaces share a parent directory and can never share a sidecar. The file is written **atomically** (`os.replace`). `.mlview` stays in `ALWAYS_PRUNE`, so a cache written there by an older build can never become input to the analysis it is caching. |
| **B5.1** | **The analyzed folder is not written to at all on a default run** — pinned by `test_a_default_run_writes_nothing_into_the_analyzed_folder`, which walks the tree before and after a full analysis and compares the file lists. `MLVIEW_NO_CACHE=1` / `--no-cache` are unchanged, and so are `MLVIEW_CACHE_KEY_FILE` and the MAC secret at `~/.mlview/cache.key`: the secret always lived in the user's home, and the payload now agrees with the key. The cache decides **where facts are read from, never what they are**, so byte-identity is unaffected. The test suite roots the default somewhere disposable by setting `XDG_CACHE_HOME` for the session in `analyzer/tests/conftest.py` — deliberately **not** `MLVIEW_CACHE_DIR`, so `cache_dir_for` still walks the default branch in every test that never thinks about the cache. |
| **B6** | **Trust.** The payload is JSON and never executable, authenticated with an HMAC over a 32-byte secret in the **user's home** (`~/.mlview/cache.key`, mode 0600, `O_EXCL`) and never in the analyzed project. A sidecar whose MAC, magic, format, analyzer identity or python tag does not match is **ignored**, never obeyed and never fatal. |
| **B7** | `MLVIEW_NO_CACHE=1` and `--no-cache` disable it. `AnalyzeOptions.cache: bool \| None = None` means "ask the environment". `--relevance all` never consults it. |
| **B8** | **`cached: full \| partial \| none \| off` is reported, and never in the document.** It rides on `AnalysisResult.cache`, on `logging.getLogger("mlview.cache")` at INFO, and on `api.digest(..., cached=None)`. `MLVIEW_CACHE_LOG=1` is the operator's switch for the stderr line. |
| **B9** | `coreClient.ts` takes an optional third constructor argument, `cacheDir`, and sets `MLVIEW_CACHE_DIR` only when given. A host is expected to pass its own storage directory: `analyzeOnSave` fires on every Ctrl+S, and a tool that writes into the user's repository that often is a tool people switch off. |
| **C** | `tools/perf_equiv.py` takes `--expect-same` (what an **optimisation** claims: exit 0 only if every corpus is byte-identical) and `--expect-diff` (what a **re-baseline** claims: exit 0 only if at least one corpus moved). Either without `--baseline` / `--compare` is a usage error, not a silent success. |

**Stated costs of the shipped defaults.** (1) A package directory whose own `__init__.py` is empty now carries a `single_file_analysis` note as well as the prefilter's own. (2) `ML-02` ("an import resolved to nothing") can only fire when a workspace module of that dotted name exists; if that module is set aside the note goes with it — but never both go quiet, because the prefilter's diagnostic names the file and the flag that brings it back. (3) MLV601's anchor moves inside the kept set. (4) **Not a cost any more:** the cache no longer writes into the analysed repository at all (B5). `MLVIEW_CACHE_DIR` keeps its meaning and its precedence, so a host that names its own directory still gets it — that is now belt and braces rather than the only thing standing between a user and a written-to checkout. `render` still writes its report under `<root>/.mlview/` when asked to, and the plugin's `MLVIEW_DATA_DIR` still defaults to `<project>/.mlview`; both are host-owned, and neither happens unless the user asked for a report or installed the plugin.

### 3.10 Notebooks

**Nothing happens unless the caller asks:** `--include-notebooks`, or `[paths] notebooks = true`. Either turns it on; neither turns the other off. Without one, discovery, parsing, the graph, the diagnostics and the exit code are exactly what they were. One notebook becomes one generated Python module at `<root>/.mlview/notebooks/<the notebook's own path>.py`.

| # | Rule |
|---|---|
| **N1** | **Code cells only, in document order.** Each contributes its lines, preceded by a `# %% cell N (execution_count K)` marker and followed by one blank line, under a three-line header naming the source notebook. `source` may be a list or a string; nbformat 3's `worksheets` / `input` / `prompt_number` are accepted. |
| **N2** | **Line counts are 1:1 inside a cell.** A line magic, a shell escape and a help query become `pass  # mlview: magic` at their own indentation — **replaced, never deleted**. A cell whose first line is a cell magic with no Python body has **every** line blanked at column 0. `PYTHON_CELL_MAGICS` lists the cell magics whose body *is* Python. |
| **N3** | **A magic that wraps a statement keeps the statement.** `%time model.fit(X, y)` becomes `model.fit(X, y)`; only the **column** moves. The remainder must `ast.parse` first, so `%timeit -n 100 f()` falls back to N2. |
| **N4** | **A `%` at statement position only.** The rewriter tracks bracket depth and open triple-quoted strings. |
| **N5** | **The generated module is on disk, and every `Loc` names it.** `Loc` cannot carry a cell index, and a location naming the `.ipynb` would name a line of JSON. `.mlview/` is git-ignored, is in `ALWAYS_PRUNE`, and `.mlview` is not a legal Python identifier, so the generated module can never shadow a real one or be re-discovered as source. |
| **N6** | **The cell map rides beside the `Loc`**, on `Node.attrs`: `notebook`, `cell` (0-based among **all** cells, markdown included) and `cellLine` (1-based within the cell). Provenance wins a name collision. A line belonging to no cell gets `notebook` and **no** cell — an invented mapping is worse than an absent one. |
| **N7** | **Every finding carries the same mapping as one evidence factor**, `kind: "context_confirmed"`, naming the notebook, the cell, the line within it and the order verdict in words. Exactly one per finding, appended last. |
| **N8** | `orderOk` is *strictly increasing over the cells that record a count*. A cell with no count is skipped rather than treated as a break; a notebook where no cell records one is in order by default, and the diagnostic says why. |
| **N9** | **A non-monotonic notebook is de-rated, not silenced.** `NOTEBOOK_ORDER_FACTOR = 0.75`, applied as the weight of N7's factor, for `ORDER_SENSITIVE_CODES = MLV101, MLV203, MLV209` and nothing else. An in-order notebook's factor is **1.0**, an exact identity, so the same code in a `.py` and in an in-order notebook score identically. |
| **N10** | `notebook_analyzed` is emitted **per analyzed notebook**: `file` = the `.ipynb`, `count` = the code-cell count, the message names the generated module, the cell counts, how many lines were replaced and the order verdict; `codes` = `ORDER_SENSITIVE_CODES` **when and only when** the order is not monotonic. |
| **N11** | **`notebooksSkipped` never becomes zero because the flag was on.** A notebook whose JSON is invalid, whose generated module does not parse, whose bytes are not UTF-8, or which cannot be written is counted **and** gets its own `parse_error` naming the `.ipynb`. |

**Stated limits.** It does not reconstruct an execution order; publishes no `vscode-notebook-cell:` URIs (host work, §12); puts no cell on `relatedLocs` or on edges; does not enter the parse cache or the prefilter; emits no progress frames; and a module-level entrypoint node may anchor on a replaced magic line, because that line really is the module's first statement in the text that was analyzed.

### 3.11 Dataflow modes — `--dataflow local|ip`

| # | Rule |
|---|---|
| **N1** | `local` is the analysis that shipped before the option existed, and the guarantee is by **construction**, not measurement: every new code path is reached only from `workspace.dataflow == "ip"` or from a non-empty `ValueRef.provenance`, which is empty in `local` for every value there is. |
| **N2** | `ir/summaries.py` runs after `propagate_parameters` and before `resolve_calls`, inside every IR round, to its own fixed point. **CONSTRUCTOR**: argument facts at **every** construction site map onto `__init__`'s parameters and from there onto any `self.<attr>` assigned from such a parameter by a bare `ast.Name`. **RETURN**: `infer_returns` gains `max_depth`, raised to the hop cap in `ip`. **METHOD-ARG**: the argument-to-parameter summary applied to bound-method call sites. **PROJECTION** (`rules.helpers.traced_arg`): a `Subscript` argument is followed to its base and the base's **data tags only** are read, as one recorded hop. |
| **N3** | **Intersection, never union.** A parameter keeps only the tags **every** call site agrees on, and a site whose argument resolves to nothing contributes the **empty set** on purpose. Two owners are never overruled: an **annotation**, and a **real store inside the function body**. |
| **N4** | `ValueRef.provenance: Tuple[Hop, ...] = ()`; `ir/provenance.py` owns `Hop(kind, detail, loc)`, `DEFAULT_MAX_HOPS = 3` and `IP_HOP_WEIGHT = 0.8`. **Every hop is one factor in the ordinary confidence product**, contributed as a single `cross_file` `Evidence` of weight `IP_HOP_WEIGHT ** hops`, so *"never `certain`"* is arithmetic: MLV101 at prior 0.95 reads 0.950 / 0.760 / 0.608 / 0.486 at 0–3 hops. A cross-object finding carries **one `RelatedLoc` per hop** plus the construction site of the transformer being fitted. A finding established **locally** reads identically in both modes. |
| **N5** | A chain past the cap, and a tag reaching a helper from several call sites whose chains have different shapes, are **not propagated**, are recorded on `workspace.ip_notes` and are emitted as `truncated` diagnostics naming the function, the cap and the parameter. |
| **N6** | **A cross-object claim is confined to one scope.** When a fitted value's tags arrived through a hop, `r_leakage._split_consuming`'s name match additionally requires the split to be written in the fit's own scope. A finding with no hops is unaffected. |
| **N7** | `tools/accuracy.py --dataflow {local,ip}` gates `ip` against **`analyzer/tests/accuracy/baseline.ip.json`**, a second file with the same shape and the same two tolerances — **zero `forbidden` findings ever, recall may only ratchet up**. The two ratchets are independent; the report and both baselines carry a `dataflow` field. |
| **G6** | **No finding carrying an interprocedural `cross_file` factor reaches `certain`, and every one names its hop chain** — asserted over the whole document, so a rule that starts making cross-object claims without calling `ctx.hops(ref)` / `ctx.hop_related(ref)` is caught by the gate rather than by a user. |
| **G8** | Two `ip` runs of one workspace are byte-identical, and `AnalyzeOptions(paths=…)` with no `dataflow` equals `dataflow=DEFAULT_DATAFLOW` byte for byte. |
| **R1.1** | **`ip` is the default.** `ir.build_ir.DEFAULT_DATAFLOW` is `"ip"` and is the **single authority** for the product default: `core.pipeline.AnalyzeOptions.dataflow`, the `--dataflow` flag on `analyze` and `issues`, and `tools/accuracy.py`'s own default all read it and **none of them spells a mode again**. §3.2's table entry follows the constant. `tools/accuracy_corpus.run_corpus()` takes `dataflow=None` meaning *the product default*, resolved by reading `mlview.api.DEFAULT_DATAFLOW`, and every report it produces records the mode it scored in `report["dataflow"]`, whichever entry point produced it. A gate that wants the **non-default** ratchet names its mode at the call site, beside the baseline it asserts against: `analyzer/tests/accuracy/test_accuracy.py` scores `local` against `baseline.json`, `analyzer/tests/core/test_dataflow_ip.py` scores `ip` against `baseline.ip.json`. A rendered accuracy report names its mode **unconditionally** (`[--dataflow ip]` / `[--dataflow local]`) and its `accuracy gate:` line names the baseline file it read — naming the mode only when it was not the default made the shipped default the one report that could not be identified. |
| **R1.2** | **`local` is the opt-out, not a deprecation.** It stays supported, shipped and gated: `analyzer/tests/accuracy/baseline.json` still ratchets it, `tests/core/test_dataflow_ip.py` still asserts both tolerances, and `AnalyzeOptions(paths=…, dataflow="local")` is byte for byte the analysis that shipped before the flag existed. A host that needs the narrower analysis passes it **explicitly**; omitting the field now means `ip`, and a host that relied on the old implicit `local` was relying on a default this section named reviewable from the day the flag shipped. |
| **R1.3** | **The flip is a widening, and the four things that make it one are gates, not claims.** (1) Precision on the labelled corpus is identical in the two modes — 100%, zero `forbidden`, zero unlabelled. (2) Recall in `ip` is **≥** recall in `local`, **per rule and overall, on the labelled corpus** — that inequality is the gate, and `tools/accuracy.py` scores each mode against its own baseline. An **individual** finding may be withdrawn in `ip`, and that is not a regression: framework recognition can resolve a wrapper `local` could not see (so a de-rating or the `negation_absent` multiplier applies) and `IP_HOP_WEIGHT` is a factor in the confidence product, so a finding `local` published just above the threshold can land just below it. Measured 2026-09-15 over the public corpus in both modes, the exception set is four findings (`mlflow` MNIST autolog MLV110; `pytorch-examples` minGPT-ddp MLV501; `pytorch-tutorials` `torch_compile_tutorial` MLV301 and MLV302), and in three of the four `ip` is the better answer. **The per-finding subset is not a gate, is asserted nowhere, and must not be written as one** (§17 E29). (3) Every interprocedural hop multiplies the confidence product by `IP_HOP_WEIGHT` and contributes one `cross_file` evidence naming the chain in words, so **no cross-object finding reaches `certain`** — G6, unchanged and now load-bearing by default. (4) `samples/vision_pipeline` is byte-identical under both modes bar `stats.durationMs`, so `contracts/graph.sample.json` is regenerable in either mode and the `--demo` byte-parity gate is untouched. |
| **R1.4** | `tools/perf_equiv.py --expect-same` against a **pre-R1** reference tree **must fail**, and that failure is the correct result: the two modes differ on `analyzer/tests/clean` in tags and edges — never in findings, of which that corpus holds zero in both. An equivalence claim against a pre-R1 baseline names `--dataflow local` on **both** sides, or it is comparing two analyses rather than two trees. |
| **R1.5** | Three detection paths are **`ip`-only by construction** (§14.2 R13–R15), so `local` recall for MLV101 / MLV102 / MLV103 is unchanged **by design**: `local` must stay the narrower analysis. |

**Stated limits.** The RETURN summary carries reach, not doubt: a tag arriving purely through a return chain is **not** de-rated and **not** named in a hop chain. CONSTRUCTOR reads one shape, `self.<attr> = <parameter>` in `__init__` only. PROJECTION reads a subscript and nothing else, data tags only. Intersection is over the call sites MLView **resolved**, so it cannot invent a tag but can keep one a fourth, unseen site would have removed. N6 buys precision with reach. The hop cap is three and three is a guess; what is measured is that exceeding it is reported. **The "not de-rated" limit is about `ir.summaries`' RETURN summary and about it alone** — a value `rules/valuetype.py` fetched out of a callee *is* de-rated and *is* named, because that read is a rule's cross-object claim (§5.3 A13). MLV101, MLV102, MLV103, MLV111, MLV305, MLV306, MLV401 and MLV402 consume provenance today.

### 3.12 `--progress-json`

NDJSON to **stderr**, one frame per analyzed file: `{"t":"progress","done":3,"total":45,"file":"src/train.py"}`.

| # | Rule |
|---|---|
| **H1** | **stdout is never touched.** The frame is exactly that object — no spaces, key order `t, done, total, file`, one trailing newline, `file` workspace-relative with forward slashes. |
| **H2** | **The library never opens the sink.** `AnalyzeOptions.progress` is an optional `(done, total, relpath)` callable; `core/progress.ProgressWriter` is what the CLI passes. `api.analyze()` performs no I/O of its own. |
| **H3** | Throttled to one frame per **50 ms** (`INTERVAL_MS`), with a **guaranteed final frame** at `done == total` that the throttle never suppresses. |
| **H4** | **A frame can never break an analysis.** A sink that raises is dropped for the rest of the run, silently. A progress bar is not worth an exit code. |
| **H5** | `done` counts files whose **parse has completed**; `total` is the discovered file count after `--max-files`. Frames are emitted only for Python files that reach the parser. |

A host parses stderr lines prefixed `{"t":"progress"`, forwards them as `analysisProgress`, leaves every other stderr line going to the log, and ignores frames arriving after `analysisFailed` for that `requestId`. Passing the flag only when a panel is live keeps the headless and export paths byte-identical.

### 3.13 The node budget — `--max-nodes` is a hierarchical rollup

A **graph** cap on the finished document, applied after the rules and **before** projection (§6.6). `core/rollup.apply_node_budget(graph, max_nodes)` is the only implementation and returns immediately, **mutating nothing**, when `max_nodes <= 0` or the document is already within budget: an uncapped document is byte-for-byte what it was before this mechanism existed. Above budget the phases run in order, stopping the moment the document fits; each runs only when the one before it has folded everything it can.

| # | Phase |
|---|---|
| **A1** | **Fold operations into their parent.** A group is one node `U` plus its `op`-level children that are **not ghosts**, folded ascending by `(issues anchored on the group, -len(group), stage order, file, line, col, id)`. `U` keeps its ghost children. |
| **A2** | **Fold a whole file into one summary node**, ascending by `(issues anchored on the file, -surviving nodes in the file, file)`. A file is folded only when it has **two or more** surviving non-ghost nodes. |
| **A3** | **The file summary node** is a real node in every respect: `id = "n:" + sha1("<file>\|<file>\|file-rollup")[:12]` — a `kind` slot no `NodeKind` can occupy, so the id is stable across budgets and cannot collide; `level: "stage"`; `kind` and `stage` the **most common** among the folded nodes, ties by ascending name / `StageId` order; `label` the basename; `sublabel` `"<n> nodes rolled up"`; `qualname` the workspace-relative path, so `unit:src/model.py` resolves to it; `loc` at `line 1, col 0`, no `symbol`, no `snippet`; `parent: null`; `confidence` the **maximum** of the folded nodes; `dynamic` true if any was; `ghost: false` always; `collapsedByDefault: true`; `attrs: {"rollup": "file"}`; `issueIds` the sorted union. |
| **A3b** | **Fold a directory**, one group per round, ascending by `(issues anchored on the group, -group size, directory path)`; a group of one is never folded. Rounds are recomputed, so a directory summary folds into its **parent** next round and the phase climbs to the workspace root. Same shape as A3, with `sha1("<dir>\|<dir>\|dir-rollup")` and a `loc` that is its **first member's own location** — a directory is not a place an editor can open. |
| **A4** | **Drop**, only if 1, 2 and 2b ran to completion and the document is still over budget. Order: ghosts and each issue's **first** anchor, then every other anchor, then ancestors, then units, then ops. A dropped node's issue re-anchors to its nearest surviving ancestor; an issue that loses every anchor is dropped, and the diagnostic **counts it**. |
| **A5** | **Ghosts are never folded, in any phase.** A ghost draws a call the code should have made and does not; folding it into its parent would delete the most legible finding MLView draws. A ghost may still be *dropped* in phase 3. |
| **B1** | `Node.rolledUp` — how many nodes were folded into this one, counted **transitively**. Absent means zero. Not a subtree size and not a child count: "how many cards this card stands for". |
| **B2** | `Edge.weight` — after re-pointing, parallel edges merge on `(source, kind, target)`. The merged edge carries `weight` **only when ≥ 2**; `label` = the members' common label when they all agree and **no label at all** when they disagree; `confidence` = the **maximum**; `loc` and `tags` = the first member's in document order; `issueIds` = the sorted union; `id` **recomputed from the merged edge's own final endpoints and label**. |
| **B3** | An edge whose two endpoints fold into the *same* survivor is **absorbed, not dropped**: removed from `edges[]` and counted in the diagnostic. **Self-loops are never emitted.** |
| **B4** | Every `issue.nodeIds` and `issue.edgeIds` entry is mapped through the fold, de-duplicated, order preserved, and the reverse links rebuilt. **A fold never drops an issue.** Only phase 3 can. |

**The diagnostic says "rolled up."** `stats.truncated` stays a boolean meaning "this document is not the whole graph"; the words are the diagnostic's job. The `Diagnostic{kind: "truncated"}` message **must** contain the word `budget` and the exact phrase `"<n> node(s) kept"`; **must** contain the words `rolled up` whenever any node was folded, naming separately how many nodes were rolled up, how many units absorbed their operations, how many files were summarised, how many edges were merged, how many absorbed and how many nodes **dropped**; and **must** state the number of issues lost when phase 3 lost any, and say nothing about issues when it lost none. `Diagnostic.count` stays the number of nodes not in the emitted document (folded + dropped).

**Acceptance (normative), on the 525-file synthetic** (uncapped **2297 nodes / 2297 edges** / 126 findings; 1972 / 2273 / 126 before §5.3 A7–A11 recovered the workspace objects — §17 E26): **`edges_lost == 0` and zero floating cards at every budget**, and `drawn + merged + absorbed == the uncapped edge count`, exactly. A *floating card* is a card with no edge, no parent and no children; **raw degree-0 is not the metric**, because a ghost has no edges by construction — the test asserts both that floating is empty **and** that every edgeless survivor is a ghost. Every finding resolves to a node at every budget and the finding **set** is identical to the uncapped one. `contracts/validate_sample.py` returns zero errors at 45, 100, 400 and 2000. **Edge retention** is a recorded floor, not a fixed percentage at a fixed budget: **> 30% at `--max-nodes 400`** (measured 33.7%) and **> 40% at `--max-nodes 500`** (measured 40.7%) — §17 E26 states why the figure at 400 moved and what did not.

**Stated limits.** The drop phase is still reachable and still loses findings when it runs (it did not run at any budget on the synthetic, so "a cap never silences a finding" is a claim about that corpus and those budgets, not a theorem). A fold is lossy about *which* thing, and `rolledUp` is the whole disclosure. A merged edge loses the labels it disagreed on. Fold order is a heuristic, not a measurement. A ghost that phase 3 drops takes its "missing" visual with it. `stage` and `kind` on a summary are a majority vote, and nothing says the vote was close.

## 4. The in-process API

`contracts/core_api.md` is this section. The MCP server and the VS Code helper import this rather than shelling out to themselves, so argument handling cannot diverge; `tools/verify.py` proves the two outputs match anyway.

```python
# mlview/api.py — FROZEN
from mlview.api import analyze, analyze_to_dict, AnalyzeOptions, MLGraph

@dataclass(frozen=True)
class AnalyzeOptions:
    paths: tuple[str, ...]
    include: tuple[str, ...] = ();  exclude: tuple[str, ...] = ()
    max_files: int = 500;           max_nodes: int = 400
    framework: str = "auto";        min_severity: str = "low"
    min_confidence: float = 0.0;    config_path: str | None = None
    strict: bool = False
    # every field below is APPENDED LAST and DEFAULTED, so positional construction,
    # frozen=True and hashability are unchanged
    scope: str | None = None;       depth: int | None = None
    progress: Callable[[int, int, str], None] | None = None
    relevance: str = "ml";          relevance_hops: int = 2;   cache: bool | None = None
    include_notebooks: bool = False
    dataflow: str = DEFAULT_DATAFLOW    # §3.11 R1.1 — `"ip"` in this build

def analyze(options) -> MLGraph: ...            # ALWAYS the FULL workspace graph
def analyze_full(options) -> AnalysisResult: ...
def analyze_to_dict(options) -> dict: ...       # schema-valid, canonically ordered; projects when options.scope is set
def render_html(graph, out_path, scope=None, depth=None) -> str: ...   # returns the absolute path written
def render_mermaid(graph) -> str: ...  def render_text(graph) -> str: ...
def render_summary(graph, show_suppressed=False, group_by="none") -> str: ...
def digest(graph, limit_bytes=4096, cached=None) -> dict: ...
def schema_path() / sample_path() / schema_text() / demo_bytes() / demo_dict(): ...
# scope (§6), additive
CONCERNS, CONCERN_ALIASES, SCOPE_KINDS, Scope, ScopeError, ScopeResolution
parse_scope(spec, depth=None) -> Scope          # raises ScopeError
resolve_scope(graph, scope) -> ScopeResolution  # anchors + core, no projection
project(graph, scope) -> dict                   # pure dict -> dict
scope_catalog(graph, limit=40) -> list[dict]    # backs --list-scopes and scope="units"
# dataflow (§3.11), additive
DATAFLOW_MODES, DEFAULT_DATAFLOW
```

**The rules that make this surface frozen.** Every new parameter is **appended last and defaulted**, so the frozen two- or three-argument call returns exactly what it always returned; `render_text`'s one-argument and `render_summary`'s two-argument signatures are pinned by `tests/core/test_api.py::test_render_signatures`. **`analyze()` returns the full graph even when `options.scope` is set** — a scope is a document-level projection, never a smaller analysis, and its docstring says so. `render_html` with a scope embeds the **full** graph and sets the two root-element attributes (§9.3), so it projects nothing; the viewer does.

**`digest`** is the ≤ **4096-byte** model-facing summary; full detail lives behind `graphPath`. It carries `schemaVersion, root, filesAnalyzed, filesFailed, notebooksSkipped, frameworks, stats, lanes, topIssues, truncated`, plus optional `cached`, `answers` (the four **sentences** only) and `scope` (`{spec, kind, target, depth, nodesInScope, nodesTotal}`, copied from `graph["view"]`). **The budget is a hard cap and outranks every field:** the shedding ladder empties `topIssues`, then `lanes`, then the answers in the stated order **`dataEntry`, `objective`, `evaluation`, `verdict`** — the first two are what an agent can most cheaply re-derive from `lanes` and `topIssues` — setting `truncatedDigest` each time. At the contractual 4096 B none of the four is dropped on any corpus measured.

## 5. The rule API

### 5.1 Registration and context

```python
@rule(code="MLV201", severity="high", base_prior=0.90, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"], absence=True)
def missing_zero_grad(ctx: GraphContext) -> Iterable[Issue]: ...

# GraphContext surface — FROZEN
ctx.graph / ctx.frameworks / ctx.modules
ctx.calls_of(fqn) -> list[CallSite]          ctx.loops(kind=None) -> list[LoopIR]   # epoch|batch|fold|None
ctx.values_tagged(tag) -> list[ValueRef]     ctx.binding_of(name, scope) -> ValueRef | None
ctx.class_bases(node) -> list[str]           ctx.node_for(loc) -> Node | None
ctx.follow_call(call) -> FunctionIR | None   ctx.is_dynamic(scope) -> bool
ctx.issue(..., fix=None) -> Issue            # the ONLY way to publish a finding
ctx.ghost(kind, parent_node, label) -> Node  # declares a ghost slot for an absence rule
ctx.untraced(call, name, reason) -> None     # the ONLY way to declare a coverage gap
ctx.fix(module, title, edits, safety=...) -> Fix | None
ctx.hops(ref) / ctx.hop_related(ref)         # interprocedural provenance (§3.11)
ctx.calls_with_role(...)                     # additive
```

Rules never construct `Issue` directly — `ctx.issue(...)` computes confidence from the declared evidence and applies the cap. `absence=True` activates the severity cap and the `negation_absent` gate. `RuleSpec.cross_file` is appended last and defaults to `False` (§2.6 C7).

### 5.2 Confidence, and the iron laws

* **Iron law 1 — a candidate comes from a binding, never from a name. No FQN is ever invented.** When the callee is `<recv>.<attr>` and `binding_of("<recv>.<attr>", scope)` yields a `ValueRef` with a producer FQN, a `via_fqns` or a workspace `class_ir`, that value becomes the receiver and the method becomes `__call__`. A binding with nothing behind it is refused; a name with no binding resolves exactly as before. A class that *declares* a method may not have a framework base symbol invented for it: `torch.nn.Module.forward` survives, `torch.nn.Module.encode` does not.
* **Iron law 4 — `WRAPPER_FACTOR` 0.4** de-rates an **absence** rule when Lightning / HF `Trainer` / `accelerate` / Keras `Model.fit` owns the loop. It does **not** apply to a rule whose subject *is* the framework (§14.2 A1), and a framework hook body is **not** an eval region (§14.2 F15).
* `DYNAMIC_FACTOR` **0.7** (a dynamic scope) · `NOTEBOOK_ORDER_FACTOR` **0.75** (§3.10 N9) · `IP_HOP_WEIGHT` **0.8** per hop (§3.11 N4) · `CONFIG_EVIDENCE_WEIGHT` **0.8** (§5.5 A4).
* **The scope-wide dynamic flag is never widened to cover one unresolved callee.** `CallSite.unresolved_callee` is a per-call optional string naming the construct; `ScopeIR.mark_dynamic` is untouched, because widening it would silently drop unrelated findings a confidence bucket.

### 5.3 Resolution facts that are normative

| # | Rule |
|---|---|
| **A1** | `CallSite.class_ir` means *the workspace class this call **resolves to*** and is written **only** by `ir/resolve.py`. `CallSite.enclosing_class` means *the class whose body this call is **written in*** and is written **only** by `ir/scopes.py`. **No reader may use one for the other.** |
| **A2** | A call whose callee is a call resolves **through the value** (`layers.Dense(64)(x)`); a callee that still resolves to nothing keeps its unresolved-callee flag. An annotation naming a known third-party class carries its family. |
| **A3** | `WorkspaceIR.reexports` maps a package alias to its definition, following at most **3** hops (`_MAX_REEXPORT_HOPS`), cycle-safe, workspace-internal only. A chain that outruns the cap is a `dynamic_scope` diagnostic naming the symbol and the cap. |
| **A3′** | `ast.Match` case bodies are walked under a `#match<line>.<case>` block id, and `AssignRecord.in_match` records that only one arm runs. |
| **A4** | `ValueRef.opaque` names the construct behind a binding — a lambda, a value assigned in a match case, a conditional expression, a subscript, a dataclass `default_factory`. It is read **only** by the diagnostic; **no rule may gate on it**. |
| **A6** | An `unknown` op minted for an unresolved callee carries `confidence: 0.35` and `kind: "unknown"`. |
| **A7** | **A call that resolves to a workspace class mints an `op` at the construction site**, instead of folding onto the class's own unit node, **when the class says something the diagram can use**. The kind and lane are read from the class's shape, in this order: a model base (`torch.nn.Module` or a `LightningModule` root) whose `forward` returns a LOSS-tagged value → `loss` / `objective`; a model base constructed inside another model class's body → `layer` / `model`; a model base → `model` / `model`; a `torch.utils.data.*` subclass or a `LightningDataModule` → `dataset` / `data`; an sklearn transformer subclass (`TransformerMixin` / `preprocessing` / `decomposition` / `impute` / `feature_selection` / `feature_extraction`) → `transform` / `preprocess`; anything else under `sklearn.` → `model` / `model`; **anything else keeps the pre-existing fold, unchanged**. **"A loss class because its `forward` returns a loss" is structural, never nominal**: `FocalLoss` is a criterion because its `ReturnSummary` carries `LOSS`, a class called `FocalLoss` that returns logits is a model, and a class called `Objective` that returns `F.cross_entropy(…)` is a loss. |
| **A8** | **A `__call__` on a workspace object mints an `op`** — `logits = model(images)` → `predict`, `loss = criterion(out, y)` → `loss` — **only when the call is not written inside a model class's own body**. Role `FORWARD` stays transparent everywhere else, which is what keeps `self.conv(x)` inside a `forward` drawn as the layer it calls rather than as a box of its own. The receiver must **already be believed** a model or a criterion — a MODEL / LOSS tag, a resolved workspace class, or a `module` / `keras_model` / `lightning_module` receiver family — **never a name**. |
| **A9** | **A call to a workspace function whose `ReturnSummary` names an object mints that object at the call site.** The returned symbol must carry one of the curated *object* roles (`MODEL_CLS`, `MODEL_FACTORY`, `ESTIMATOR`, `PIPELINE`, `CV_SEARCH`, `CONTAINER`, `LAYER`, `LOSS_CLS`, `OPTIMIZER`, `SCHEDULER`, `GRAD_SCALER`, `LOADER`, `DATASET`, `DATASET_HF`, `SAMPLER`, `GENERATOR`, `COLLATOR`, `TRANSFORMER`, `STATELESS_TRANSFORMER`, `TRANSFORM_PIPE`, `AUGMENT`, `SPLITTER`, `HF_MODEL`, `HF_TOKENIZER`, `HF_TRAINER`, `HF_PIPELINE`, `KERAS_MODEL`, `LIGHTNING_MODULE`, `LIGHTNING_TRAINER`, `LIGHTNING_DM`, `TS_MODEL`, `ACCELERATOR`, `FABRIC`, `WRAP_MODEL`), or name a workspace class (A7), or — failing both — the return must carry exactly one of MODEL, LOADER, OPTIMIZER or LOSS. **A factory that returns a number or a matrix draws nothing**: `accuracy = score(preds, y)` and `X = load(path)` name no object, and a card for them would draw a second time what the callee already drew. |
| **A9′** | **"Used here" is the complement of two AST shapes.** A7–A10 mint a card only when the value stays in this scope: **not** when the call is a bare expression statement (`log_everything()` throws the value away) and **not** when it is the whole `return` / `yield` value (the value leaves, and the caller is where it gets a name and a box). Everything else counts — a binding, an argument, a tuple element, the receiver of a chained method — because the ways a value can be used are open-ended and the ways it can be discarded are two. |
| **A10** | **`ir.returns.ReturnSlot.opaque`**, appended last and defaulted, is the noun phrase for the construct that defeated the analyzer when a return could not be typed **at all**. It is set only when `fqns`, `tags` and `class_ir` are all empty, it merges **last** (a branch that named a symbol always wins), and `ir.converge._slot_key` fingerprints it so the IR fixed point sees it move. A call to such a function whose value is used (A9′) mints an `unknown` card reading `unresolved factory · <phrase>` at confidence 0.35 (A6), with the stage inherited. This is **A6's rule one level out** — *an unresolved callee is a per-call fact* becomes *an unresolvable **return** is a per-call-site fact* — and the alternative is the silently smaller graph ANA-5a exists to stop. |
| **A11** | **Five ways an object reaches the line that uses it.** Each is one level deep, literal-only, and invents nothing. (a) `self.<attr>` across sibling methods. (b) A **dict / tuple / list literal**: `ValueRef.container` (appended last, defaulted) remembers the literal AST node, `ir/containers.py` reads it, and `scaler = ctx["scaler"]` / `opt_a, opt_b = optimizers` recover the element's producer, class and tags — only a **constant** key, only a literal the same module builds, and a later mutation of the container is **not** modelled. (c) A **dataclass or holder field**: constructing a workspace class with a bound name also binds `<name>.<field>` in the **caller's** scope, for every field the constructor really names — `__init__`'s parameters, or the annotated class-body fields where there is no `__init__`; a field whose value is not itself something binds nothing. (d) An **attribute of a workspace object**: `binding_of` falls back, once and last, to the class scope the base name resolves to, so `bundle.model` is what `Bundle` stores in `self.model`; only a workspace class, and `self.` is never re-entered. (e) A **rebinding wrapper**: `WRAP_PREPARE` (`accelerate.Accelerator.prepare`, `Fabric.setup`) is **position *i* out is argument *i* in**, which is what both projects document; the scalar form (`model = accelerator.prepare(model)`, `torch.compile(net)`, `DistributedDataParallel(net)`) carries argument 0's workspace class along with the MODEL tag the row already had. |
| **A12** | **A card minted by A7–A10 never invents an `fqn` and never votes on a lane.** A workspace class is not a canonical third-party symbol (§1), so **no construction, invocation or factory card carries an `fqn` at all** — a factory's returned symbol goes in the sublabel. None of these nodes contributes to `GraphBuilder._op_votes`, so **no unit changes stage because of this pass** and every unit's `stage` and `stageEvidence` are byte-identical for every unit whose ops did not otherwise change. The two cards whose lane is a property of *where they run* rather than of what they are — the forward pass and the loss computation — are registered in `GraphBuilder.inherit_stage` and re-staged from their parent **after** `_assign_stages` has decided the parent's lane. Their `id` does not depend on `stage` (§1), so id stability is untouched. |
| **A12′** | **The construction site answers before the class definition.** `core.build_edges._through` tries a value's **producer** before its `class_ir`: `model = SmallCNN()` has a card of its own and that card is the instance the chain flows from, while the class node is where the instance was *declared*. The fallback to the class is unchanged, so a graph with no construction card is exactly what it was. |
| **A12′** | **Carriage travels exactly one hop in each of two directions, and never more.** *Out of a `return`*: a function returning a dict / list / tuple **literal** carries that literal on its `ReturnSlot` together with **the scope and module its element expressions must be read in** — `{"model": model}` names `model` in the *callee's* scope, and reading it in the caller's would resolve a different object or none; two `return`s with two different literals carry nothing. *Into a parameter*: a parameter inherits a container when **every resolved call site passes the same literal** — §3.11 N6's intersection discipline, so an unseen site cannot invent one and two sites with two different dicts carry nothing. Beyond those two hops there is still no aliasing analysis and no modelling of a container mutated after construction. A subscript the analyzer **did** follow into a literal is no longer marked `opaque` (ANA-5a): a resolved object must not report itself as a gap. `CallSite.unresolved_callee` has two halves — the **syntactic** half (`callee_construct`: "a subscript", "a lambda", "the result of another call") is a pure function of the AST and is preserved, including the one place receiver resolution deliberately clears it (the Keras functional API); the **inferred** half (a binding that exists with nothing behind it) is **recomputed on every IR round** rather than written once, because a sticky gap meant a name the first round could not follow reported itself as unresolved for the life of the run even after a later round resolved it. |
| **A13** | **`rules/valuetype.py` is the single place a rule asks what a scored value is** — `value_tags(ctx, node, scope, module)` for what an expression holds, `returned_call_with_role(ctx, call, roles)` for the op a workspace callee's `return` yields. **It mints no tag**: every tag it returns was written by a knowledge-table entry or by `ir.returns`, and it adds only the willingness to keep looking, through (a) the receiver of a container / device / dtype method that does not change what the value holds and (b) one workspace callee's `return`. The walk is capped at **three** hops, and an expression it cannot type comes back **empty rather than guessed**. A value it had to fetch **out of a callee** carries a `return` `Hop`, and the finding that consumed it pays `IP_HOP_WEIGHT` **once** and names the crossing in its evidence — in `local` as well as in `ip`, because §3.11 G6 is a rule about cross-object *claims*, not about a flag. **One bounded collector hop** is part of the same answer: a name bound to an empty `[]` in a scope, `append`-ed to in that scope and passed to `np.concatenate` / `np.stack` / `np.vstack` / `np.hstack` / `torch.cat` / `torch.stack` / `np.array` / `np.asarray` / `pd.concat` carries the **intersection** of the appended elements' tags — never their union, so a list that also receives an argmaxed value carries nothing. Only appends in that scope are read, and an append the analyzer cannot type abandons the answer entirely. The hop crosses no object and therefore costs no `IP_HOP_WEIGHT` of its own; an appended element whose own answer came out of a callee still carries that callee's hop. |
| **R3** | **`binding_of` never resolves a name to the store the call being resolved is about to write.** It takes `exclude: Optional[CallSite]`, and receiver resolution passes the call itself with `at=call.loc.line`, so `ds = ds.map(...)` and `df = df.dropna()` resolve. Python evaluates the right-hand side before it rebinds the name; skipping the call's own store is what the language does. A scope whose only store for a name is the call's own resolves to a value written by `propagate_parameters` when there is one, and to nothing otherwise. |
| **R4** | **"Recognised but not drawn" applies to edges as well as nodes.** `core.build.NOT_DRAWN_ROLES` keeps `LIGHTNING_LOG`, `LIGHTNING_HPARAMS`, `LIGHTNING_CTL`, `MODEL_SUMMARY` and `TFDATA_CARD` from falling through `_resolve_transparent` onto their receiver's class node. Ops written *inside* such a call keep their own dataflow. |

### 5.4 Structured fixes — the opt-in `Issue.fix`

The non-goal barring quick fixes that edit ML logic is lifted **for this feature with its guardrails**, and four of the five live in `rules/fixes.py` with the fifth in `GraphContext.issue`, so a rule cannot opt out of any of them.

| # | Rule |
|---|---|
| **A1–A3** | `Issue.fix` is one **optional** property. `Fix = {title: string(minLength 1), safety: "mechanical"\|"needs-review", edits: TextEdit[]}`, `minItems 1`, `maxItems 4`. `TextEdit = {file, absFile, line, col, endLine, endCol, newText}`, all required, §1's conventions verbatim. A **zero-width** range is an insertion. |
| **A2′** | The cap of four is a **producer** bound; a consumer may be more permissive (the VS Code reader refuses above **16**), which is the correct direction for the asymmetry: the producer's cap can tighten without a host release. |
| **A4** | `absFile` is carried deliberately: every other location-bearing object carries both spellings, and a host rebuilding an absolute path from a relative one is a multi-root bug. |
| **A5** | **There is no `isPreferred` field.** It is derivable — `isPreferred == (safety == "mechanical")` — and two spellings of one decision is how they come to disagree. |
| **A6** | All edits of one fix name **one file** — the file of the issue's own `loc` — and never overlap. Applying them all is one atomic change or none. |
| **A7** | `Issue.fix` is emitted **only when set**, so every run of every rule that did not opt in is byte-identical to what it produced before the field existed. |
| **B1** | **Rules opt in** by passing `fix=` to `ctx.issue`. `rules.fixes.FIX_CODES` is the list — **MLV111, MLV201, MLV301, MLV302, MLV602** — and a test fails if any other rule's source contains `fix=`. |
| **B2** | **Edits are computed from the AST.** Every position comes from an `ast` node's `lineno` / `col_offset` / `end_lineno` / `end_col_offset`; indentation for an inserted statement is the **target statement's own `col_offset`**. **No fix anywhere searches the source for a substring.** |
| **B3** | **No fix at all below the `likely` bucket.** `GraphContext.issue` attaches the candidate only when the computed `confidenceBucket` is `certain` or `likely`, reading the same clamped number the user is shown. The rule is not consulted. |
| **B4** | **`mechanical` is a promise**: one keyword argument at one call site, no statement inserted, no control flow touched. Only **MLV111** and **MLV602** qualify; everything that inserts a statement into a training loop is **`needs-review`**. |
| **B5** | **Never auto-applied, and never applied by the analyzer at all.** Nothing in `mlview` writes an edit to a file. `rules.fixes.apply_edits` is pure and exists so the analyzer can prove an edit re-parses before publishing it. Every text surface that renders a fix says *"nothing here is applied automatically"*. |
| **C1–C2** | A rule builds an edit **only** through `ctx.fix(module, title, edits, safety=...)`; `rules/fixes.py` is the only module that constructs a `TextEdit`. `ctx.fix` returns `None` — never a partial fix — when a builder gave up, the title is empty, `safety` is not one of the two values, there are no edits or more than four, an edit names another file, or applying the edits changes nothing. |
| **C3** | **The last gate is a parse.** `build_fix` applies the candidate to a copy of the module source *in memory* and runs `ast.parse`; a candidate that does not parse is discarded and the finding ships with its prose hint alone. |
| **C4** | A rule's gate, its evidence and its confidence are **unchanged** by any of this. It publishes no finding that was not already published. |

**The four refusals** — each still fires the finding and keeps its prose `fixHint`: **D1** a non-ASCII physical line anywhere an edit touches; **D2** a receiver that is not a plain dotted name; **D3** a missing import in the edited module; **D4** a block that would have to be re-indented (which is why MLV302 gets the decorator or nothing, and why MLV201 is withheld where the loop body starts on the `for` line).

| Code | Safety | Edit | Offered when |
|---|---|---|---|
| **MLV111** | `mechanical` | the `shuffle=` literal `True` → `False` | the keyword is a literal at the call site |
| **MLV201** | `needs-review` | `<optimizer>.zero_grad(set_to_none=True)` as the **first statement of the batch-loop body**, at that statement's indentation | the optimizer is a dotted name, the `.step()` that proves the finding is inside this loop's own body, and the optimizer is constructed above the insertion point |
| **MLV301** | `needs-review` | `<model>.eval()` immediately **above the loop**, or as the first statement of the evaluation function after any docstring | the model is a dotted name bound above the region; the edit cannot also restore `model.train()` |
| **MLV302** | `needs-review` | `@torch.no_grad()` directly above the `def` | the region is inside a function with no `backward()` / `optimizer.step()` / `zero_grad()` anywhere, and the module binds `torch` |
| **MLV602** | `mechanical` | `random_state=42` / `seed=42` / `generator=torch.Generator().manual_seed(42)` **after the last existing argument** | the call forwards no `**kwargs` |

`docs/rules/<CODE>.md` gains a **Structured fix** section generated from `rules.fixes.FIX_DOCS`, stating for each of the five both when the edit is offered **and when it is withheld**.

**Stated limits.** It cannot tell a missing `zero_grad()` from gradient accumulation — nothing can, statically. The `with torch.no_grad():` wrap is never built. A fix is computed against the file as it was analyzed and the document carries **no content hash**, so every host surface built on this field must re-analyze or verify before applying (§12.4 A9). No fix crosses a file, and none adds an import.

### 5.5 Configuration resolution

`ir/config_shapes.py` recognises exactly four shapes: a **dict literal** (nested, every constant key); a **dataclass** (field defaults, nested through `default_factory` naming another workspace dataclass, with literal constructor keywords replacing the defaults they name); **argparse** (`add_argument(..., default=...)` keyed by `dest` — explicit `dest=` first, else the option string with `--` stripped and `-` → `_` — plus `store_true → False` / `store_false → True`); and an **attribute or subscript chain rooted at one of the above**, so `cfg.data.workers` and `CFG["data"]["workers"]` are one path. **Not** resolved: a computed key, a comprehension, a `dict()` call, a `default_factory` lambda, a module with **two** `ArgumentParser()` constructions, a key containing `.`, a chain deeper than `MAX_PATH_DEPTH`.

The container's **name** must match `CONFIG_NAME_RE` — `cfg`, `config`, `args`, `opts`, `options`, `hparams`, `params`, `settings`, case-insensitively. **That regex is the whole blast radius of this pass.** Caps: `MAX_CONFIG_LEAVES = 256`, `MAX_CONFIG_DEPTH = 5`, `MAX_PATH_DEPTH = 6`, `MAX_ALTERNATIVES = 12`, `MAX_CONFIG_HOPS = 2`.

| # | Rule |
|---|---|
| **A2** | Two sinks, both things rules already read. **`ValueRef.literal`**: every scalar leaf is an ordinary `ValueRef` under its dotted path, written into `scope.bindings` and deliberately **not** into `binding_history` — a real assignment to the same dotted name always wins. **`CallSite.kwargs`**: filled from the container for keys the call site did **not** write, scalars only, never over 40 characters; a keyword written at the call site always wins; every key written is recorded and taken back at the start of the next IR round. |
| **A3** | A container travels three ways and no others: an **import** (no hop), a **declared default** `def train(cfg=CFG)` (one hop, read only in the module the default is written in), and an **argument** onto a `CONFIG_NAME_RE`-shaped parameter (one hop). Capped at `MAX_CONFIG_HOPS`. |
| **A4** | **Intersection, never union.** A parameter takes a container only when **every** recorded call site agrees on the same one; a site that passed something unfollowable records `None`, which refuses the parameter for everybody. The price is `CONFIG_EVIDENCE_WEIGHT = 0.8`, charged **once for the read** and once more per hop, as one ordinary factor. **A config-resolved value can never mint a `certain` finding**: the highest registered prior is 0.98 and `0.98 × 0.8 = 0.784 < 0.9`. It is applied by `rules.helpers.apply_config_derating(ctx)` **once per issue**, joined to the finding by the **source range they share**; several reads out of one container pay the **weakest** once and the detail names them all. |
| **A5** | `core/config_nodes.py` owns aliases, selections and `config_unresolved`. Every alias maps onto the **one** node its container already has, carried as a `(relpath, scope, name)` key, which is what turns *"where does `batch_size` come from"* into `config` edges from `CFG` into each consuming unit, including across files. |
| **A6** | `getattr(<module>, <literal>)` draws a **`config`** node in both branches. **Resolved**: the symbol is named exactly, the node carries that FQN and the `ValueRef` carries it as `via_fqns` — and the symbol **must exist** in `workspace.classes` / `workspace.functions` or in the knowledge tables; **no FQN is invented**. **Unresolved**: a `getattr` on a *workspace* module is bounded to the symbols that module defines, the node names them, and its confidence is **1/N**. The kind is `config` in both branches: a `getattr` line **selects a name**; it constructs nothing. |
| **A7** | `config_unresolved` is published for every YAML or Hydra config the workspace **names** and this run did not open: any string constant ending `.yaml` / `.yml`, a call to `yaml.safe_load` / `yaml.load` / `yaml.full_load` / `OmegaConf.load` / `OmegaConf.merge`, or a `@hydra.*` decorator. At most three per module, then one counted row. **Nothing in `ir/config_shapes.py`, `ir/config_values.py` or `ir/config_calls.py` opens, imports, execs or compiles anything** — asserted against the AST, not the text. |
| **A8** | **No schema change**, and the shipped demo's fifteen findings are unchanged — asserted causally: not one of them carries a config factor. |

**Stated limits.** It does not open YAML or compose Hydra. A container and a parameter must both be `CONFIG_NAME_RE`-named. The two-hop cap publishes a `truncated` note. The keyword de-rating is anchored on the **call**, not on the argument — safe direction, stated rather than hidden. `cls()` after an unresolved `getattr` is still an `unknown` op. `literal_of` still returns a string, so a rule cannot ask *whether* a value came from a container.

## 6. Scope — the selector grammar and the projection

Two implementations, one algorithm: `analyzer/src/mlview/core/project.py` and `webview/src/scope/project.ts`. They move in the same change and are held together by the parity and fuzz gates of §16.2. The Python module is `core/project.py` — **not** `core/scope.py`, which would collide with `ir/scopes.py` where "scope" already means lexical scope — and it imports nothing from `build.py` or `pipeline.py`.

### 6.1 The grammar (normative)

```
SPEC   := "all" | KIND ":" TARGET
KIND   := "unit" | "stage" | "file" | "concern" | "node" | "symbol" | "pipeline"
DEPTH  := integer 0..2            -- a separate parameter, never packed into SPEC
```

The selector is **one string with exactly one `kind` and one `target`**, split on the **first** `:` only (a node id contains a colon: `node:n:55662bceebd0`). No comma-unions, no `@depth` suffix, no `~direction`, no `+pin`. **Parsing:** trim; lowercase the `kind`; replace `\` with `/` inside a `file:` or `pipeline:` target; `symbol` **normalizes to `unit`**; a `concern` alias normalizes to its canonical name **before validation**. The normalized string is what `view.scope` reports, so two spellings of one scope produce byte-identical documents. An empty or missing spec means `all` and performs no projection.

| kind | target | seed set | default depth | descendant closure? |
|---|---|---|---|---|
| `unit` | qualname, FQN, bare name, or a node id | tiered resolution (§6.4 step 1) | **1** | **yes** |
| `stage` | one of the eight `StageId`s | `node.stage == target` | **0** | no |
| `file` | workspace-relative path (forward slashes) or a bare basename | `loc.file == target`, else `basename(loc.file) == target` when the target has no `/` | **0** | no |
| `concern` | one of four presets, or an alias | `node.stage` ∈ the preset's stages | **0** | no |
| `node` | a node id (`n:…`) — legacy pinpoint selector | that node alone | **1** | **no** |
| `pipeline` | a workspace entrypoint path, or its bare basename | `seeds(E)` (§6.7) | **0** | no (the relation already carries containment) |

**Concern presets — FROZEN. The four partition all eight stages.** `config` = {`config`}, alias `setup`. `data` = {`data`, `preprocess`}, aliases `preprocessing`, `dataset`. `optimization` = {`model`, `objective`, `train`}, alias `training`. `evaluation` = {`eval`, `deliver`}, aliases `inference`, `eval`.

### 6.2 Error codes

Only the **code**, the offending **term**, and a **sorted, ≤10-entry candidate list** are contractual. Message prose is free and may differ between Python and TypeScript.

| code | raised when |
|---|---|
| `bad_selector` | no `:`, or an unknown `kind` |
| `unknown_stage` / `unknown_concern` / `unknown_node` | not one of the eight `StageId`s (candidates: the eight) / not a preset or alias (candidates: the four canonical names) / not a node id in this graph |
| `unknown_file` | matched no `loc.file` by either rule (candidates: distinct `loc.file` values) |
| `unknown_pipeline` | matched no entry of `workspace.entrypoints`; an **empty** target falls through to the resolver and raises this with `term: ""` and the same candidate list |
| `unknown_unit` | **not raised.** A `unit:` target that resolves to nothing is an *empty scope*, not an error |
| `bad_depth` | `depth` outside `0..2`, or not an integer |

### 6.3 Where the grammar is repeated

`SCOPE_KINDS`, the `bad_selector` candidate list, `SCOPE_SPELLINGS`, `mlview.api.SCOPE_KINDS`, `webview/src/scope/selector.ts`, the MCP `mlview_graph` selector prose, the three VS Code language-model tool descriptions and `analyze --list-scopes` all enumerate the same set and move together. **`stages` and `units` are MCP-only catalogue payloads** and must not appear in the CLI's or a host's advertised selector list — `mlview analyze --scope stages` is a `bad_selector` refusal.

### 6.4 Resolution and projection (normative)

Input: a finalized, schema-valid document `D` and a parsed `Scope(kind, target, depth)`. Output: a finalized, schema-valid document `D'` carrying `view`. **Pure**: no filesystem, no IR, no clock, no randomness, no set-iteration-order leak.

1. **Resolve anchors**, in **document order**. `stage` / `file` / `concern` / `node` / `pipeline` per §6.1 and §6.7. `unit`: strip a trailing `()`; if the target starts with `n:` and names a node, that node alone; otherwise the **first non-empty tier** of, in order — (1) `qualname == t` · (2) `fqn == t` · (3) `lastSegment(qualname) == t` **and** `level ∈ {stage, unit}` · (4) `lastSegment(qualname) == t` · (5) `label == t` or `label == t + "()"` — then tiers 1–5 again ASCII-case-insensitively, emitting a `config_warning` naming the canonical spelling on a hit. **Every node in the winning tier is an anchor.** More than one ⇒ `view.ambiguous: true` plus a `config_warning` naming the disambiguating qualnames. **Never a silent "best" pick.**
2. **`core`** = the anchors, plus — for `kind == "unit"` only — their transitive **descendant** closure over `parent` (cycle-guarded). For `kind == "pipeline"`, §6.7 C replaces this step.
3. **`boundary`** = BFS over `edges[]` in **both** directions, `depth` rings from `core`, minus `core`. **Containment is not a hop.**
4. **`context`** = for every node in `core ∪ boundary`, the transitive `parent` chain, minus anything already kept.
5. **`kept`** = `core ∪ boundary ∪ context`. **Edges** kept iff `source ∈ kept ∧ target ∈ kept`.
6. **Issues.** Retain issue `I` iff `∃ n ∈ I.nodeIds : n ∈ core` **or** `∃ e ∈ I.edgeIds` that is a kept edge with **both** endpoints in `core`. Then, for each retained `I`: `I.nodeIds ← [n for n in I.nodeIds if n ∈ kept]` (order preserved); if `I.nodeIds[0] ∉ core`, **stably rotate** the first core element to index 0 (`nodeIds[k:] + nodeIds[:k]`); `I.edgeIds ← [e for e in I.edgeIds if e is a kept edge]`. Suppressed issues follow the same rule and keep `suppressed: true`. **The edge-retained case is normative:** **F1** — an issue retained through the edge rule whose `nodeIds` all fell outside `kept` **promotes** the first live retaining edge's `source` (a `core` node by construction, so a legal `nodeIds[0]` needing no rotation) and that becomes the issue's whole `nodeIds`; **F2** — the promotion is the one place a projection *adds* an id, so the **reverse link travels with it**: the promoted node's `issueIds` gains the issue id, appended after the filtered ones, and only if the issue survived step 7; **F3** — if there is no live retaining core edge after all, the issue is **dropped**. A retained issue always ends with at least one node.
7. **Ghost pruning.** Drop every kept node with `ghost: true` whose `issueIds` contain no retained issue; then re-filter `edges` and every `I.nodeIds`, and drop any issue whose `nodeIds` became empty. Repeat once; it converges.
8. **Nodes.** For each kept node, in document order: copy it, set `viewRole` to `core` / `boundary` / `context`, and filter `issueIds` to retained issues.
9. **Aggregates.** `stages[]` stays **all eight rows in `order`**. Per row: `nodeCount` = kept nodes of that stage in **all three roles**; `issueCounts` and `maxSeverity` recomputed over retained **non-suppressed** issues; **`present` copied verbatim from `D`**. `stats.nodes` / `stats.edges` = kept counts; `stats.issues` = retained non-suppressed counts; `stats.suppressed` = retained suppressed count; `stats.truncated` and `stats.durationMs` carried through. An anchor set of size 0 is legal: all eight rows at `nodeCount: 0`, empty `nodes`/`edges`/`issues`, `view.empty: true`, `view.resolvedTo: []`, and a `config_warning` naming the whole-graph node count.
10. **Carried verbatim:** `schemaVersion`, `generator`, **every** field of `workspace`, `answers`, `pipelines`, every unknown root key, and `diagnostics` (scope diagnostics appended, then the array re-sorted by its existing key). **A projection never restates project-level truth.**
11. **`view`** is appended as the **last key** of the document.

`counts.core + counts.boundary + counts.context == stats.nodes`. `hidden.inboundEdges` / `outboundEdges` count edges of `D` with **exactly one** endpoint kept. **`view.of` is always taken from the unprojected document**, so no surface can claim the project is smaller than it is.

### 6.5 The ordering invariant (normative)

Steps 1–10 only *remove* elements from arrays that are already canonically sorted, and only *filter* the `nodeIds` / `edgeIds` / `issueIds` lists. **No output array is ever re-sorted.** `nodes`, `edges` and `issues` in `D'` are **subsequences** of `D`'s, in the same relative order. The only non-filter operations in the whole algorithm are the stable rotation in step 6 and F1's promotion. **A port that sorts anything is wrong, even when its output happens to match.**

### 6.6 The cap runs before the projection

`--max-nodes` (§3.13) runs **before** projection and is not re-applied: moving it after would make Python (project→cap) and TypeScript (already-capped→project) disagree whenever the cap binds. When `stats.truncated` is true and a scope was given, append a `Diagnostic{kind: "truncated"}` saying the graph was capped before scoping; `view.of.nodes` always reports the pre-projection count.

### 6.7 Pipelines

`core/pipelines.py` is the only implementation and is **pure**: it reads `workspace.entrypoints`, `nodes[].id`, `nodes[].parent`, `nodes[].loc.file`, `edges[].kind`, `edges[].source`, `edges[].target` and nothing else. **Both ports compute it; neither trusts the emitted block.**

| # | Rule |
|---|---|
| **A1** | `seeds(E)` = the nodes whose `loc.file == E`, in document order. |
| **A2** | Adjacency is undirected and is the union of exactly two things: every edge whose `kind` is **`data`** or **`call`**, in both directions; and the **containment relation** `parent` ⇄ child, in both directions. `config` and `control` edges are deliberately **excluded** — a shared `config.py` is precisely the module that would merge ten independent training scripts into one component. |
| **A3** | `reach(E)` is the closure of `seeds(E)` under A2, which **includes but does not expand through** a node belonging to a *different* entrypoint's file. **That clause is load-bearing**: without it ten scripts sharing one `utils.py` would all have the same reach. |
| **A3.1** | A node in `reach(E)` that some other entrypoint also reaches is **shared** for `E` — **unless it is one of `E`'s own seeds**, which are never taken away from the entrypoint they live in. A node in no reach at all is **unreached**. |
| **A4** | Every set is materialised in **document order**, never in set-iteration order. |
| **B** | The `pipeline:` target is matched against `workspace.entrypoints`, first match winning: exact path; then bare basename when the target contains no `/`; then the same two ASCII-case-folded, emitting the same `config_warning` a case-folded `file:` does. `view.scope` / `view.label` report the **selector as normalized by §6.1**, not the canonical entrypoint; the canonical spelling is named in the warning. An entrypoint that resolves but whose `seeds(E)` is empty is an **empty scope**, not an error. |
| **C** | For `kind == "pipeline"` only, step 2 is replaced: **`core`** = the nodes of `reach(E)` that are **not shared**; **forced context** = the nodes of `reach(E)` that **are** shared. Steps 3–7 are unchanged except that `boundary ← boundary − forced context`; step 8 gives every forced-context node **`context`**. Consequence: **a finding anchored only on a shared node is not retained by a `pipeline:` scope**, and the rail reports it as "outside this view". |
| **C1** | A `pipeline:` projection appends one `config_warning` naming how many nodes it drew, how many are shared with another entrypoint, and how many nodes of the whole graph belong to **no** pipeline. |
| **D** | `pipelines[]` is an **optional root array**, emitted after `stats` and before `answers`, and **only when the document has two or more non-empty pipelines**. Rows are in `workspace.entrypoints` order: `{entrypoint, label, nodeCount, exclusiveCount, sharedCount, issueCounts}`, all six required, `additionalProperties: false`. `nodeCount = \|reach(E)\|`; `exclusiveCount + sharedCount == nodeCount`. **`exclusiveCount` is `\|core(E)\|` — the A3.1 sense of shared, with the owner exception, not the global one**, which ties together the three numbers a user can see: `pipelines[].exclusiveCount == view.counts.core` of `pipeline:<E>` at depth 0 == the `SUBTREE` column of that entrypoint's `--list-scopes` row. `issueCounts` counts **non-suppressed** issues with at least one `nodeId` in `reach(E)`; an issue spanning two pipelines is counted in **both** — the block is a menu, not a partition, and the numbers are deliberately not required to sum to `stats.issues`. A projection carries the block verbatim. |

`--list-scopes` gains one `pipeline:` row per pipeline **above** the unit rows, whenever the workspace has two or more pipelines.

**Stated limits.** Containment is in the relation, so a utility class touched by two scripts pulls its whole subtree into both pipelines' `reach`; `sharedCount` is the only signal. A neighbouring entrypoint's own nodes are drawn as context. `config` and `control` edges are cut on purpose, so a pipeline that genuinely depends on a config node does not show it as `core`. `workspace.entrypoints` is capped at ten and is itself a heuristic, with no statement when an eleventh is missing. Unreached nodes are counted, never named; there is no `pipeline:none` selector. On a rolled-up document the counts describe the **summarised** graph, and `stats.truncated` is the only thing that says so.

## 7. The diff overlay document

`core/diff.py` computes it, `emit/diff_out.py` renders it, `mlview diff` is the entry point. **The diff is defined in the analyzer, so all three hosts get one answer from one implementation.** A node id is `sha1(file|qualname|kind)` and is never line-derived, so a diff is a **join on ids**; nothing invents a parallel identity.

| # | Rule |
|---|---|
| **A1** | `mlview diff BASE.json HEAD.json [--json FILE\|-] [--format summary\|json]`. Both inputs are documents `mlview analyze --json` already writes. **Nothing is analysed:** `diff` reads two files and writes one. |
| **A2** | Exit **0** on success; **1** for a missing file, a file that is not JSON, a document that is not an MLView graph, or a document that is itself a diff overlay. Every failure names the file, goes to stderr and leaves stdout untouched. |
| **A3** | `--format summary` (default) prints D's rendering; `--format json` prints the overlay. `--json FILE` also writes the overlay and names it on stderr; `--json -` makes the overlay the stdout payload. |

**It is a separate document and never a graph.** `schemaVersion` stays `1.0`, the schema and the golden are untouched, and **a consumer checks `kind` before anything else**.

```jsonc
{ "kind": "mlview-diff",            // REQUIRED, and the discriminator
  "diffVersion": "1.0", "schemaVersion": "1.0",
  "generator": { "name": "mlview", "version": "0.1.0" },
  "generatedAt": "...",             // present ONLY when the caller passes one
  "base": { "root", "generatedAt", "analyzerVersion", "schemaVersion",
            "filesAnalyzed", "nodes", "edges", "issues", "truncated", "view" },
  "head": { /* the same keys */ },
  "summary": { "nodes": {"added","removed","changed","unchanged"},
               "edges": {"added","removed","changed","unchanged"},
               "issues": {"new","fixed","persisting"},
               "headline": "+26 nodes · −16 nodes · 0 new findings · 15 fixed" },
  "nodes":  [ { "id", "status": "added|removed|changed|unchanged", "label", "kind", "level",
                "stage", "loc": {"file","line"}, "changed": [...], "moved": true } ],
  "edges":  [ { "id", "status", "source", "target", "kind", "label", "changed", "moved" } ],
  "issues": [ { "id", "status": "new|fixed|persisting", "code", "severity", "title",
                "confidenceBucket", "nodeIds", "loc", "suppressed", "changed": [...] } ],
  "notes":  [ { "kind", "side": "base|head", "count", "message" } ] }
```

| # | Rule |
|---|---|
| **B1** | Every array is keyed on the **stable id** and sorted by it. `nodes` and `edges` carry every id in either document, so `added + changed + unchanged` equals the head's count and `removed + changed + unchanged` equals the base's. **A diff that loses an id is a diff that lies about a deletion.** |
| **B2** | **A move is not a change.** The node comparison key is `label, sublabel, kind, level, stage, parent, dynamic, ghost, collapsedByDefault, confidenceBucket, issueCodes` and **excludes `loc`**. A node whose line moved and whose meaning did not is `unchanged`, with `moved: true` beside it. |
| **B3** | `issueCodes` — the sorted set of rule **codes** anchored on the entry — is the one derived field in the key. Codes rather than issue ids: an issue id embeds the symbol it was raised on, so a renamed variable would otherwise look like a changed node. |
| **B4** | `source`, `kind`, `target` and `label` are *inside* the edge id, so a change to any of them is an add **plus** a remove, which is the truthful reading. The edge comparison key is therefore only `confidence, tags, issueCodes`. |
| **B5** | **A float is not a fact.** Confidences are compared rounded to three places. |
| **B6** | Issue statuses are `new` (head only), `fixed` (base only) and `persisting` (both). A persisting issue may carry `changed` naming any of `severity, confidenceBucket, suppressed, message, nodeIds`. |
| **B7** | The overlay is **deterministic**: the same two documents produce the same bytes, and `generatedAt` is present only when a caller supplies one, which is what lets a test pin them. |

**`notes[]` — what a diff cannot see.** `removed` is a claim about two documents, not about the code. Five honest reasons for an id to be missing, each emitting a note, **never elided by any renderer**: `not-analyzed` (either side set files aside or capped — carries `side` and `count`), `truncated` (either side's `stats.truncated`), `projection` (either side carries `view`: a projection holds a subset of its own analysis), `different-roots` (ids are built from the workspace-relative path, so only files present under both roots at the same relative path can match), and `different-analyzers` / `different-schemas` (a `changed` or `new` status may reflect a rule change rather than a code change). A pair with nothing to declare says so in one line: *"both analyses read their whole workspace, so a removed node is a removed node."*

**`--format summary` order, deliberately:** the two documents named (a diff of the wrong pair is the easiest mistake to make and the hardest to notice), the headline, the three count lines, **findings before structure** (new, then fixed, then still-present), then added / removed / changed nodes, then the notes. Every list **but the notes** is capped at **10 rows**, and every elision names the number it did not print.

**Stated limits.** A file **renamed** is every node removed plus every node added; no rename detection is attempted or implied. A node whose `qualname` changed is likewise an add plus a remove. Confidence movement below 0.001 is invisible by construction (B5). The overlay says nothing about *why* something changed — it reports that the head document does not contain an id, and `notes[]` is the complete list of reasons it knows that might not mean what a reader will assume.

## 8. The webview ↔ host message protocol

`contracts/messages.md` is this section. Every message carries `v: 1`. **Unknown message types are logged and ignored on both sides** — a version skew must degrade, not crash. The authorities are `webview/src/types.ts` and `vscode-extension/src/protocol.ts`, whose `HOST_TO_UI_TYPES` and `UI_TO_HOST_TYPES` lists are exactly the two blocks below.

### 8.1 Host → webview (15)

```ts
type HostToUi =
  | { v: 1; type: 'init';            schemaVersion: string; theme: 'light'|'dark'|'hc'; host: 'vscode'|'standalone';
                                     capabilities: { canOpenSource: boolean; canReanalyze: boolean;
                                                     canExport: boolean; canAskAssistant: boolean } }
  | { v: 1; type: 'graph';           requestId: string; graph: MLGraph;
                                     preserve?: { viewport?: Viewport; selection?: Sel|null; collapsed?: string[] } }
  | { v: 1; type: 'analysisStarted'; requestId: string; scope: 'workspace'|'file'; path?: string }
  | { v: 1; type: 'analysisProgress';requestId: string; done: number; total: number; file?: string }
  | { v: 1; type: 'analysisFailed';  requestId: string; message: string; detail?: string;
                                     actions?: { id: string; label: string }[] }
  | { v: 1; type: 'theme';           kind: 'light'|'dark'|'hc' }
  | { v: 1; type: 'revealNode';      nodeId: string; center?: boolean; approximate?: boolean }
  | { v: 1; type: 'revealIssue';     issueId: string }
  | { v: 1; type: 'cursorHint';      file: string; line: number }
  | { v: 1; type: 'setFilter';       severities?: ('low'|'medium'|'high')[]; codes?: string[]; query?: string }
  | { v: 1; type: 'stale';           changedFiles: string[] }
  | { v: 1; type: 'restoreState';    state: ViewState }
  | { v: 1; type: 'setScope';        spec: string | null; depth?: number }
  | { v: 1; type: 'requestExport';   kind: 'svg'|'png'; scope?: 'view'|'all'|'scope' }
  | { v: 1; type: 'diffOverlay';     overlay: unknown | null; baseLabel?: string };
```

### 8.2 Webview → host (14)

```ts
type UiToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'openLocation';  file: string; absFile: string; line: number; col: number;
                                   endLine: number; endCol: number; preview?: boolean }
  | { v: 1; type: 'selectNode';    nodeId: string | null }
  | { v: 1; type: 'requestRefresh';scope: 'workspace'|'file'; path?: string }
  | { v: 1; type: 'exportHtml' }
  | { v: 1; type: 'copy';          text: string }
  | { v: 1; type: 'saveState';     state: ViewState }
  | { v: 1; type: 'action';        id: string }                        // error-banner buttons
  | { v: 1; type: 'askAssistant';  nodeId: string; prompt: string }
  | { v: 1; type: 'log';           level: 'debug'|'info'|'warn'|'error'; message: string }
  | { v: 1; type: 'scopeChanged';  spec: string | null; label: string; nodes: number; of: number }
  | { v: 1; type: 'suppressRule';  code: string; scope: 'workspace';
                                   action: 'copy'|'insert'|'disable'; absFile?: string; line?: number }
  | { v: 1; type: 'exportFile';    kind: 'svg'|'png';
                                   name: string;          base64: string;   // spelling A
                                   suggestedName: string; data: string;     // spelling B, byte-identical
                                   scope: 'view'|'all'|'scope' }
  | { v: 1; type: 'applyFix';      issueId: string };
```

### 8.3 What each message carries

**`openLocation` — the host's obligations.** Node paths originate from parsing arbitrary source, so **a webview must never be able to talk the extension into opening `~/.ssh/id_rsa`**: `path.resolve(workspaceRoot, msg.file)`, refuse and log when `vscode.workspace.getWorkspaceFolder(uri)` is undefined, then `openTextDocument` + `showTextDocument(doc, {viewColumn: One, selection: new Range(msg.line - 1, msg.col, msg.endLine - 1, msg.endCol), preview: !!msg.preview})` — **the one and only boundary conversion (§1)** — followed by `revealRange(sel, InCenterIfOutsideViewport)`. `StandaloneBridge` answers the same message per §10.4 and **never navigates its own document**.

**`setScope` / `scopeChanged`.** The selector field is named **`spec`**, never `scope`: `analysisStarted` and `requestRefresh` already carry a field literally named `scope` with values `'workspace' | 'file'`, and reusing the word would be a live collision. `spec: null` clears the scope. `scopeChanged` is posted on **every** scope change including a clear (then `spec: null`, `label: "Everything"`, `nodes === of`); the host uses it for the panel title and description, and **it must never trigger a re-analysis**.

**`suppressRule`.** `isUiToHost` accepts it only when `code` matches `^MLV[0-9]{3}$` and `action` is one of the three words — **rejected by the guard, not by the handler**. The viewer carries both `scope` and `action` and always sends them, and only ever sends `action: 'disable'`: "copy ignore comment" goes through the generic `copy` message and `insert` belongs to the editor's own lightbulb, which has a cursor to insert at. **It is a request, never an edit**: the viewer writes no file, ever. **The two suppression strings have exactly one definition**, `webview/src/ui/suppress.ts` — `ignoreComment(code)` is `# mlview: ignore[<code>]` and `disableSnippet(code)` is `[rules]\n<code> = "off"` — read from there by the rail, the Inspector, the group headers and the standalone bridge, so **no surface can teach a user a syntax the analyzer does not accept**.

**`requestExport` / `exportFile`.** `requestExport` is the host's two commands asking for a picture they cannot draw; the viewer sets the menu's checked region from `scope`, renders, and answers with exactly **one** `exportFile`, or with a toast when nothing is drawn. `exportFile` does **not** require a preceding `requestExport` — the viewer's own menu is the primary trigger and the host treats both identically; what protects the user is validation and the save dialog (§12.5), not provenance. `all` is the host's word for the renderer's `diagram`, and the mapping lives in one place (`hostRegionWord` / `regionFromHostWord`).

> **Interop note (§17 E2).** The viewer half and the host half were specified with different field names, and the host validator **rejects a frame without `data`**. The frame therefore carries **both spellings on every message**, with `name === suggestedName` and `base64 === data` **always**, so either validator accepts it and either reader decodes the same bytes. This is deliberate, gated redundancy (`test/export.test.mjs` asserts the equality and the base64 shape) and is the one thing here a reviewer should collapse: pick one spelling, drop the other from `types.ts`, `export/actions.ts` and `bridges.ts`, and delete this note.

The payload carries the file itself — UTF-8 SVG markup, or PNG bytes — because the channel is a structured clone a `Blob` does not reliably survive, and base64 makes the frame one plain string for every reader. It is **pure base64**: no whitespace, no `data:` prefix, length a multiple of four. The filename is a **suggestion** (`mlview-<workspace>-<scope>-<region>.svg`, slugged to `[a-z0-9._-]`, no separator and no `..`); a host may rename it and **must** sanitise it before touching a filesystem.

**`applyFix`.** **The id and nothing else.** No range, no replacement string, no path: the host resolves the id against **its own** copy of the graph and reads the edits from there — a webview that could name a range and a string would be a webview deciding what gets written to disk. `isUiToHost` rejects a missing or empty `issueId`; extra keys are ignored by the guard and by the handler. An id not in the current analysis is **reported to the user**, never guessed at.

**`diffOverlay`.** The overlay travels **verbatim** and is an optional **sibling** of the graph, never merged into it; `overlay: null` clears a comparison. It is **deferred until a graph has been delivered**, like `revealNode`, `setScope` and `requestExport` — an overlay arriving before the document it decorates has nothing to decorate. The host types it only as far as it reads it (`kind`, `diffVersion`, `summary.headline`, `notes[]`); everything else passes through, because the viewer owns the rendering and the host owns the transport.

## 9. The renderer API and `ViewState`

`contracts/renderer_api.md` is this section. The viewer bundle exposes exactly **one** global.

### 9.1 The global

```ts
window.MLView = {
  version: string,
  mount(root: HTMLElement, graph: MLGraph, bridge: HostBridge): MLViewApp,
  bridges: {
    vscode(): HostBridge,                                                  // wraps acquireVsCodeApi() ONCE
    standalone(opts?: { theme?: 'auto'|'light'|'dark'|'hc' }): HostBridge  // 'auto' = prefers-color-scheme
  },
  __internal: { scope: { parseScope, resolveScope, project }, flow: FLOW, /* … */ }
}
interface HostBridge {
  host: 'vscode' | 'standalone';  theme: 'light' | 'dark' | 'hc';
  capabilities: { canOpenSource: boolean; canReanalyze: boolean; canExport: boolean; canAskAssistant: boolean };
  post(msg: UiToHost): void;
  onMessage(cb: (msg: HostToUi) => void): () => void;   // returns an unsubscribe fn
  saveState(s: ViewState): void;  loadState(): ViewState | null;
}
interface MLViewApp {
  update(graph: MLGraph, preserve?: Partial<ViewState>): void;
  focusNode(id: string, opts?: { center?: boolean; pulse?: boolean }): void;
  focusIssue(id: string): void;
  setFilters(f: Partial<Filters>): void;   setTheme(kind: 'light'|'dark'|'hc'): void;
  setScope(spec: string | null, opts?: { depth?: number }): void;
  getScope(): { spec: string|null; label: string; depth: number; nodes: number; of: number };
  getState(): ViewState;  destroy(): void;
}
```

**`mount` keeps its exact three-argument signature.** `setScope` re-projects and relayouts locally: **it never posts `requestRefresh` and never touches the analyzer**, and an unresolvable spec is a no-op plus a toast — it never throws out of `mount` or `setScope`. The renderer sets `data-theme="light|dark|hc"` on the root element it mounts into, and every design token is `var(--vscode-*, <literal>)`, so the same CSS works in a webview and in a plain browser.

### 9.2 `ViewState`

```ts
export interface ViewState {
  viewport: Viewport; selection: Sel | null; collapsed: string[];
  filters: Filters;                 // Filters gains an optional `changedOnly?: boolean`
  railTab: RailTab;
  minimapCollapsed?: boolean;
  scope?: { spec: string; depth: number };
  flow?: boolean;                   // absent = on
  railGroupBy?: 'none' | 'rule' | 'file';
  legendOpen?: boolean;             // absent = closed
  answersOpen?: boolean;            // absent = open
  diffOnly?: boolean;               // absent = off
  pipelineChosen?: boolean;         // absent = not asked yet
}
```

**Every field after `railTab` is optional and absent at its default, and is sanitized on restore** — `sanitizeScope` beside `sanitizeFilters`, `sanitizeGroupBy` folding an unknown value to `'none'`, booleans through a `typeof === 'boolean'` guard. `applyState` tolerates missing keys, so an older saved state restores to the defaults, and **a host predating any of them round-trips it untouched** because the host stores `ViewState` opaquely. `pipelineChosen` records only **that** the chooser was answered, never which pipeline was chosen — that is a scope, and `scope` already persists it. On a new `graph` message the saved scope is **re-resolved** against the new document and, if it now matches nothing, dropped with a toast (*"Scope no longer matches — cleared"*). Restoring `diffOnly` with no overlay loaded is a **no-op**, never an empty diagram.

### 9.3 Bridges, the report bootstrap, the panel and the build

`VsCodeBridge` wraps `acquireVsCodeApi()` (called **once**), mapping `post` → `postMessage` and `saveState` / `loadState` → `setState` / `getState`. `StandaloneBridge` handles `openLocation` per §10.4, no-ops `requestRefresh` and `askAssistant`, and hides their buttons via `capabilities`; `askAssistant` is posted by the bridge and ignored by both hosts (`capabilities.canAskAssistant = false`).

**The standalone report** (`emit/html_out.py`) is one self-contained file: `<style>` with the inlined `assets/mlview.css`, `<div id="mlview-root">`, `<script id="mlview-graph" type="application/json">` holding the graph JSON with every `</` escaped as `<\/` (and `<!--` as `<\!--`), `<script>` with the inlined `assets/mlview.js`, then a **three-line bootstrap** unchanged by every amendment since:

```
MLView.mount(document.getElementById('mlview-root'),
             JSON.parse(document.getElementById('mlview-graph').textContent),
             MLView.bridges.standalone({theme:'auto'}))
```

**An initial scope arrives as two optional attributes on the root element**, which `mount()` reads from `root` itself: `data-mlview-scope="concern:evaluation"` and `data-mlview-depth="1"`; absent attributes mean no scope. **`--html` with `--scope` embeds the FULL graph and sets the two attributes** — `render_html` projects nothing; the viewer does. That is what makes the standalone report and the webview run the identical code path, and it is where the parity guarantee comes from for free. If the assets are missing (pre-sync) the report still renders a plain-HTML fallback (a table of stages / nodes / issues) with a visible "viewer bundle not synced" banner.

**The VS Code panel** is created frozen: `createWebviewPanel('mlview.diagram', 'MLView', ViewColumn.Beside, {enableScripts: true, localResourceRoots: [<extensionUri>/media]})`, with **`retainContextWhenHidden` deliberately NOT set** — state lives in `getState`/`setState` plus a `WebviewPanelSerializer` registered for `'mlview.diagram'`. The HTML carries a CSP built from a fresh `randomBytes(24)` nonce: `default-src 'none'; img-src ${cspSource} data:; style-src ${cspSource} 'unsafe-inline'; font-src ${cspSource}; script-src 'nonce-${nonce}'`. **`'unsafe-inline'` is granted for styles only** (nodes carry positional styles); scripts are nonce-locked, and `default-src 'none'` is the CSP-level enforcement of the offline requirement. An inline nonce'd bootstrap creates the bridge with `MLView.bridges.vscode()`, posts `ready`, and mounts on the first `graph` message; subsequent `graph` messages call `app.update`.

**Build:** `npx esbuild src/main.ts --bundle --format=iife --global-name=MLView --platform=browser --target=es2020 --minify --outfile=dist/mlview.js`. **Non-negotiable build rules, all lint- or test-enforced:** no `innerHTML` anywhere; no external font, image, script or stylesheet; no dynamic `import()`; no `eval`; no `getTotalLength()` (§10.1); no filter primitives in the flow layer (§10.2).

**Layout.** Exactly the eight `StageId`s, in `order`, as horizontal swimlane bands stacked top-to-bottom, each laid out with `@dagrejs/dagre@3.1.1` (`rankdir: LR`) **independently**; `present: false` stages are not drawn as bands but listed in a "not detected" chip row. **dagre compound / `setParent` is never used**; groups are laid out children-first and placed as sized meta-nodes. While `graph.view` is present a lane is admitted **only** when it has drawn roots, and the excluded-but-present stages are rendered in a separate **"not in this scope"** chip row beside the "not detected" one. Level of detail is one zoom-threshold class toggle (`data-lod="full|compact"`); the node state machine is `default, hover, selected, dimmed, ghost, stale`.

## 10. Viewer contracts (DOM, and what the picture may claim)

Everything here is **renderer-local**: no schema change, no protocol change, no host change, unless a clause says otherwise.

### 10.1 Flow — the DOM contract

Feature 1 consumes only `edges[].kind`, `subkind`, `source`, `target`, `label` and `issueIds`. **Two observable attributes on `.mlv-canvas`**, each with one job, so every branch is assertable in a runner that executes no CSS animation: `data-motion` is `full` | `reduced` from `matchMedia('(prefers-reduced-motion: reduce)')`, re-read on its `change` event; `data-flow` is `off` when the user toggled it off, `static` when `data-motion="reduced"` **or** the current trace exceeds `FLOW_MAX_EDGES`, and `motion` otherwise.

| Class | Element | Position | Built when |
|---|---|---|---|
| `mlv-edge__flow` | `<path pathLength="100">`, `d` **equal to** `.mlv-edge__path`'s `d` | the route | `data-flow="motion"` |
| `mlv-edge__port--out` / `--in` | `<circle r="3.5">` | `route.points[0]` / `points[last]` | `motion` or `static` |
| `mlv-edge__dir` | `<path>` rotated by `route.midAngle` | `route.mid` | `data-flow="static"` |

**State classes:** `.is-flowing--pulse` (one charge, single edge) and `.is-flowing` (stream, lineage) on the edge `<g>`; `.is-flow-source` / `.is-flow-target` on the endpoint cards; `--mlv-flow-delay` inline per streaming edge; `--mlv-flow-dur` and `--mlv-flow-len` inline per pulsing edge. **Constants** (exported through `__internal.flow`, so tests do not hard-code timings): `FLOW_MAX_EDGES = 120`; pulse speed `320 px/s` clamped to `[PULSE_MIN_MS 380, PULSE_MAX_MS 2200]`; stream speed `220 px/s`; head `12 px`; gaps `34 / 96 / 24 px` for data / call+control:enter / control:back giving periods `210 / 490 / 165 ms`; hop delay `90 ms` capped at 6 hops; `CHARGE_HALO_R = 9`, `CHARGE_GLOW_R = 5.5`, `CHARGE_CORE_R = 2.6`, `CHARGE_TWIN_PX = 360`.

| # | Mandatory rule |
|---|---|
| **1** | **Length is the polyline length summed from `RoutedEdge.points`. `getTotalLength()` MUST NOT be called** — jsdom does not implement it, so measuring the DOM would make the tested path different from the shipped path. A source scan of `webview/src` asserts zero occurrences. |
| **2** | **Direction is never derived.** Every router emits `points` source→target, so animating along `d` is always outlet→inlet. No per-edge direction decision may be reintroduced. |
| **3** | **Reduced motion is handled twice**: the element is never built when `data-motion="reduced"`, **and** `@media (prefers-reduced-motion: reduce) { .mlv-edge__flow { display: none !important } }` exists in the stylesheet. The blanket duration clamp *freezes* an animation rather than removing it, which would park a 12 px stub at every outlet. |
| **4** | **Charge colour is order-independent:** `.mlv-edge[data-stage]:not(.has-issue) { --mlv-flow-color: var(--mlv-stage) }` and `.mlv-edge.has-issue { --mlv-flow-color: var(--mlv-sev) }`. `data-stage` on the edge `<g>` comes from the **source** node's stage. |
| **5** | **No `will-change`, no `filter: drop-shadow`, no halo filter, and nothing may animate without a user action.** |
| **6** | `config`-kind edges never join a lineage stream; they pulse only on direct hover or selection. |
| **7** | Nothing in the flow layer carries a `data-*-id`, so the parity gate is unaffected by construction. |

**The `Escape` dismiss cascade**, in this exact order, written **once** by one owner (`webview/src/ui/appkeys.ts`): **scope picker → shortcut sheet → legend → focus mode → scope → selection → blur.** Whichever rung fires also stops the flow it owned; clearing a selection blurs the focused edge first, because focus alone is a flow trigger. **The legend rung sits above focus mode and below the sheet**: the legend is the shallower thing on screen, so dismissing it must never also leave focus mode, clear the scope or drop the selection, while the sheet, modal over everything, still goes first. **Escape closes the legend exactly as its `[x]` does** — the same close path, so `ViewState.legendOpen` is persisted false (i.e. absent, §9.2) and the toolbar's `Legend` button returns to `aria-pressed="false"`; there is no second way to close a legend. **Escape never OPENS the legend and never toggles it**: the rung is a close, and `l` remains the only key that opens it. **A closed legend is not a rung**: with it closed, Escape behaves exactly as it did before the rung existed. The `Escape` `KEYMAP` row is the only place the cascade is described to a user (it is what the `?` sheet renders), so it names the legend: *"Close the picker, sheet or legend, exit focus mode, clear the scope, clear the selection, leave the canvas."* The export menu and the pipeline chooser are **not** rungs — each handles Escape inside its own panel — because this order describes what Escape does *on the canvas*, where `handleCanvasKey` runs. **`KEYMAP` rows** this contract adds: `e` / `Shift+E` (cycle the selection's connections — and because `handleCanvasKey` folds case for `f`/`F` and `p`/`P`, the pair **must** branch on `ev.shiftKey` explicitly), `s` / `Shift+S` (scope to selection / clear), `[` / `]` (step depth), `l` (legend). None collides with the `Shift+F` and `Ctrl+Shift+E` reserved elsewhere.

### 10.2 The charge (amends 10.1 for the pulse only)

A charge on a hovered or selected connection is a **travelling dot with a halo**, not a moving dash. This applies to the **pulse** — `.is-flowing--pulse`, i.e. direct edge hover, edge focus and the selection latch. The **lineage stream** (`.is-flowing`) keeps the hop-staggered dash train: on a stream the reading is *density per hop*, and a stream may decorate up to `FLOW_MAX_EDGES` cables at once, where one SMIL timeline per edge is a cost the dash pattern does not pay. The group is `mlv-edge__charge` — a `<g>` holding `mlv-edge__charge-halo` (`<circle r="9">` at `--mlv-flow-halo-opacity` 0.18), `mlv-edge__charge-glow` (`r="5.5"` at `--mlv-flow-glow-opacity` 0.42) and `mlv-edge__charge-core` (`r="2.6"`, `fill: var(--mlv-surface)`, `stroke: var(--mlv-flow-color)` at `--mlv-flow-core-width`) plus one `<animateMotion>` — built only for a pulse, under `motion`, with route length > 0.

**Motion.** `<animateMotion dur="<pulseDurationMs(polylineLength(route.points))>ms" repeatCount="indefinite" calcMode="linear" rotate="auto" fill="remove">` containing `<mpath>` referencing the edge's **visible** `.mlv-edge__path`. Both `href` and `xlink:href` are set, the latter **in the XLink namespace** (`setAttributeNS`; a plain `setAttribute("xlink:href", …)` lands in no namespace and SVG 1.1 renderers ignore it). **Path identity:** every `.mlv-edge__path` carries `id="mlv-p-<mount serial>-<edge id, each UTF-16 code unit as four hex digits>"`, the serial allocated once per mounted `CanvasView`, because `<mpath href="#…">` is a **document-wide** reference and `dev/states.html` mounts several apps on one page. The fixed-width hex is injective by construction.

| # | Rule (additive to 10.1's seven, all of which still hold) |
|---|---|
| **1** | **Two dots on a long cable.** A route longer than `CHARGE_TWIN_PX` gets a second charge whose `begin` is **negative** — a phase offset, so the trailing dot is half a period behind from the first frame. |
| **2** | **The halo is stacked opacity, never a filter.** No `feGaussianBlur`, `feDropShadow`, `feColorMatrix`, `filter:` or `will-change:` anywhere in the flow layer; the built bundle is grepped for the primitive names. |
| **3** | **`mlv-edge__flow` survives, demoted.** In a pulse it is a **static, faint, full-length underlay** (`stroke-dasharray: none`, `stroke-opacity: var(--mlv-flow-underlay-opacity)`, no `animation`), so a severity edge still reads red between passes. `@keyframes mlv-flow-pulse` is **deleted**; `mlv-flow-stream` is the only keyframe animating `stroke-dashoffset`, still with no `calc()` on the animated side. |
| **4** | **Colour is unchanged** — 10.1 rule 4 governs the dot exactly as it governed the dash. |
| **5** | **Reduced motion, and the zero-length route.** No charge group is built when `data-motion="reduced"`, and `@media (prefers-reduced-motion: reduce) { .mlv-edge__charge { display: none !important } }` exists as its own rule — **not** belt-and-braces: SMIL is not CSS, so the CSS duration clamp does not touch `<animateMotion>` at all. A route whose polyline length is 0, or whose visible path carries no id, builds **nothing**. |
| **6** | **`stripEdge` removes `.mlv-edge__charge`** with the rest of the set, so unhover, selection change, scope change, the flow toggle and `destroy()` all leave zero charge groups and zero SMIL timelines in the document. |
| **7** | **The charge begins at the GESTURE.** Every `<animateMotion>` a pulse builds carries an ABSOLUTE `begin="<t0>s"`, `t0` = `ownerSVGElement.getCurrentTime()` read **once per pulse** and shared by both dots; the twin's is `t0 - dur/2`. An absent `begin` resolves to `0s` on the SVG document timeline — a clock that started with the page — so the dot would start at an arbitrary phase. Where the renderer exposes no SMIL clock (jsdom, any host without `getCurrentTime`) the pre-amendment form is written instead, through a `typeof` guard, so the fallback is the old behaviour and never a thrown build. |
| **8** | **The charge fades at both ends of its cycle.** `@keyframes mlv-charge-ends` takes `.mlv-edge__charge` from `opacity: 0` to 1 over the first 8% and back over the last 8%, driven by the same `--mlv-flow-dur` the motion carries; `repeatCount="indefinite"` wraps instantaneously, so without it the charge blinks out at the inlet and in at the outlet. The trailing dot carries `mlv-edge__charge--twin` and an `animation-delay` of `calc(var(--mlv-flow-dur) / -2)`. It is `opacity` on an element the compositor already moves — no filter, no `will-change` — and under `prefers-reduced-motion` the charge is still removed outright rather than faded. |
| **9** | **High contrast rings the dot in ink.** In hc (`body.vscode-high-contrast`, `body.vscode-high-contrast-light`, `[data-theme="hc"]`) the halo is `fill: none` with `stroke: var(--mlv-text)` at 1.2 px: geometry rather than colour. The override wins on **specificity**, not source order. |
| **10** | **A mid-session motion flip REBUILDS what was running.** `FlowController.setMotion` only clears, so `FlowBinding`'s `MotionWatcher` callback ends with `stop()`. Without it a flip to `reduce` stripped a selected or keyboard-focused connection of its charge *and* of the ports and chevron that replace it, leaving a connection emphasised, holding DOM focus, with no direction cue at all. The remembered capped-trace node id is dropped with it. |

**Correction to the constants (§17 E15).** `pulseDurationMs` documents the **clamp**, not the intent: the constant-apparent-speed promise holds for a lineage **stream**, whose period is constant per kind, and **not** for a pulse at either clamp. Widening the clamp is a contract amendment, not a renderer-local change.

### 10.3 Flow × scope composition (normative)

| # | Rule |
|---|---|
| **C1** | A scope change **clears every flow element and every `--mlv-flow-*` inline property** before rebuilding the scene, and resets the remembered flowing-edge and endpoint ids. `clearFlow` is idempotent. |
| **C2** | An edge is **flow-eligible in a lineage stream** iff its `kind` is not `config` **and** (the document has no `view` **or** both endpoints carry `viewRole === "core"`). A boundary or context node's other connections are cut, so a charge animating into it would lie about where the value goes. Such edges still take `.is-lit` — they are real and they are drawn — but never `.is-flowing`. |
| **C3** | A **direct** edge hover, focus or selection pulses **any** drawn edge, including one touching a boundary or context node: the user pointed at it, not at a path. |
| **C4** | `e` / `Shift+E` iterate **only** routes present in the current projection, read from the live `routes` array. A cached incident list would select a route no longer in the DOM. |
| **C5** | `FLOW_MAX_EDGES` and scoping are complements: the capped-trace copy names scoping as the way to get the animation back. |

### 10.4 Deep links, and the toast as an interface

**The rule, absolute: the standalone report never navigates its own document, and never creates a browsing context inside it.** No `.click()` on a same-frame anchor, no `location.href` assignment, no `location.assign` / `location.replace`, and no `createElement('iframe')`. `deepLinkPlan({embedded, local, absFile, file, line, col})` is a pure, exported function of two booleans and is the only place the outcome is decided: `embedded` (either `local`) → `copy`; not embedded and not `local` → `copy`; not embedded and `local` → `launch`. `copy` puts `file:line` on the clipboard and toasts *"Copied `<file>:<line>` — open the report locally to jump into VS Code"* with the anchor below; `launch` opens the `vscode://` URL in **one named transient context** — `window.open(url, 'mlview-deeplink')`, closed again after **700 ms** — and the existing blur detection copies `file:line` and toasts if no blur arrives within **900 ms**. **`embedded` is `window.self !== window.top`, read inside `try/catch`, and a throw counts as embedded**, since only a cross-origin embedding can make that comparison raise. `url` is built in both modes and is always `vscode://file/<absFile>:<line>:<col + 1>`.

| # | Rule |
|---|---|
| **D1** | Floating toasts live inside **ONE persistent host**, `div.mlv-toasts--floating` with `role="status"`, created **before** the message lands, so the text is a live-region **mutation** rather than a node that appears already containing it. `aria-live` is left off, so the app's announcer stays the only `[aria-live]` element. The host is mounted in `.mlv-root` when one exists, for the theme tokens. |
| **D2** | It holds **exactly one card**. A new message replaces the previous one, so two toasts can never occupy identical rectangles and no buried anchor can keep a stale deep link in the tab order. |
| **D3** | The 3000 ms timer is **held** while the pointer is over the card or focus is inside it (`mouseenter` / `focusin` clear it; `mouseleave` / `focusout` re-arm it). |
| **D4** | When the gesture came from the **keyboard**, the anchor **takes focus**; from a pointer, focus is not moved. The modality is read in the capture phase from `Enter` / `Space` only, and only within 1000 ms. If the toast is dismissed while holding focus, focus returns to the element the gesture started from — **never to `<body>`**, which silently kills the canvas keymap. |
| **D5** | The deep-link path is **encoded**: `encodeURI`, then `#` → `%23` and `?` → `%3F`, which `encodeURI` deliberately leaves alone. `:<line>:<col + 1>` is appended **after** the encoding. |
| **D6** | An empty `absFile` yields `url: ""`, and a toast with no `url` carries **no anchor**: a dead link is not an affordance. |
| **D7** | **One hand-off at a time.** A run of "Go to" clicks never leaves two contexts open: every earlier one is closed before the next is opened, and they share one target name, so a browser reuses a single context rather than stacking six *"Open Visual Studio Code?"* prompts. The 700 ms lifetime is a lifetime, not the protection. |
| **D8** | **A refused launch is visible and is answered at once.** `window.open` returns `null` when a popup blocker or a host refuses; the report then does **not** wait — it copies `file:line` immediately and shows the toast **with the `Open in VS Code` anchor** (the `copy` row's toast), since that anchor is then the only way left from the page to the editor. The hidden iframe could not do this: it failed silently and left the reader with a 400 ms wait that read as a success. |
| **D9** | **The launching context is never the one holding the diagram.** Measured in Chrome 141 on macOS 25.6, on a `file://` report: handing a URL to the OS protocol handler costs the launching browsing context its keyboard, permanently — the same page with `location.href = 'vscode://…'` and no frame at all fails identically, while the same frame at an unregistered scheme does not, so the cost is the hand-off and not the element (§17 E30). The fallback deadline is therefore **900 ms**, 200 ms *after* the close: `execCommand('copy')` fails in an unfocused document and the transient context holds focus until it is closed, so a 400 ms fallback would have reported *"Copy blocked"* where the old path said *"Copied"*. When focus never leaves the page the fallback still copies and toasts, with **no** anchor. |

**The source-scan gate.** With comments stripped, `webview/src/bridges.ts` contains: no `.click()`, no `location.href =`, no `location.assign`, no `location.replace`; no `createElement('iframe')` and no `mlv-deeplink` class; exactly **two** occurrences of `window.open` — the capability guard and the one call, which is literally `window.open(url, LAUNCH_TARGET)`; and `deepLinkPlan`, the one decision function. It lives in `webview/test/bridges.test.mjs`, beside a behaviour test that **clicks a node card and then presses `l`** — the order no keyboard test in the suite used before, which is why 536 green webview tests stood over a report whose keyboard died on its first click.

The copy toast's way out is `<a class="mlv-toast__link" target="_blank" rel="noopener noreferrer">Open in VS Code</a>`, built with `createElement` + `textContent` like everything else. `target="_blank"` is what makes it safe: a host that permits the protocol gets a one-click jump, and a sandbox **without `allow-popups`** merely drops the click into a *new* browsing context, leaving the report where it was. The `launch` fallback toast carries **no** link.

### 10.5 Export — SVG, PNG, clipboard and print

**The one hard rule.** There are **two renderers of one picture**, and they may not be able to disagree. `render/plan.ts` owns the decision — `planScene(index, frame, routes, labels, keep, staleFiles, isFilteredOut)` returns the lanes, the `NodeVisual`s (shallowest first) and the `EdgeVisual`s — and **both** `render/scene.ts` (DOM) and `export/svg.ts` (SVG) walk that one object. **Nothing else may decide what is drawn.**

| # | Rule |
|---|---|
| **E1** | The SVG carries **exactly one `<g data-node-id>` per planned box** and **exactly one `<path data-edge-id>` per planned route**, in plan order, with the same **id sets** — not merely the same counts. |
| **E2** | Each such path's `d` is the `RoutedEdge.d` string **verbatim**. The export may never re-derive geometry. |
| **E3** | Every document edge a route stands for is listed in that path's `data-edge-ids`, so a merged route loses none of them. |
| **E4** | An edge label is drawn **iff** the layout planned one that is neither `hidden` nor hover-only (`placement.always === false`) — exactly the set `styles/edge.css` reveals at `data-lod="full"`. |

**"Standalone" is enumerated.** No `url(...)` — therefore no `<marker>`, no `clip-path`, no gradient and no filter; the arrowheads are inline `<path>`s reproducing the `<marker>` transform (`refX 8.5`, `refY 5`, `markerUnits="userSpaceOnUse"`, 0.9 scale). No `foreignObject`, no `<image>`, no `<use>`, no `xlink:href`, no `<script>`, no `@import`, no `@font-face`. **The only `http` in the file is the `xmlns` declaration**, and the gate asserts that literally. Text is real `<text>` in a generic stack; geometry is real `<rect>` and `<path>`.

**Colours are literals, resolved from the live theme.** `export/palette.ts` reads each `--mlv-*` token off the **mounted root** with `getComputedStyle` and falls back **per token** to the literal fallback chain of `styles/tokens.css`, transcribed once. **A value that still contains `var(` or `color-mix(` is refused rather than emitted.** The transcription is gated: the test parses `dist/mlview.dev.css` and asserts every entry is the last literal in that token's declaration, for light, dark and high contrast, following a one-token alias. `color-mix()` washes become `fill-opacity` over the emitted background rectangle.

**PNG** is drawn **from that SVG** — never from a second traversal — onto an offscreen canvas at **2×**. The source is a `data:` URI, not a `blob:` one, because a webview CSP is written per scheme and a data URI needs no revocation; the no-external-reference rule is what keeps the canvas untainted. Where there is no canvas the result is `null` and the viewer **says so** rather than claiming a file. **Clipboard:** `navigator.clipboard.write([ClipboardItem])` for the PNG, `writeText` for the markup; every failure falls back to posting the existing `copy` message, and **Copy PNG falls back to Copy SVG before it falls back to the toast**.

**The standalone download** lives in `export/download.ts`, a module of its own, because `test/bridges.test.mjs` greps `bridges.ts` for `.click()`, `location.href =` and `window.open` and that grep must stay blunt (§10.4). Four rules: it is reached only from an explicit export gesture; the href is always an object URL of bytes the page just produced; the anchor always carries `download` and the function **refuses to click one that cannot**; and the anchor is created, clicked and removed inside one call.

**Print.** `styles/export.css` is a new, **last** stylesheet layer, so its `!important` overrides win over every layer above it. Its `@media print` block hides the chrome (`.mlv-chromebar`, `.mlv-chiprow`, `.mlv-banners`, `.mlv-status`, `.mlv-rail`, `.mlv-minimap`, `.mlv-zoom`, `.mlv-statehost`, `.mlv-tooltip`, the toasts, the legend, the shortcut sheet, the scope picker, the answers card, the theme switch and the export menu); releases the page-fill chain (`html.mlv-fills-page`, `body`, `.mlv-root`, `.mlv-body`, `.mlv-main`, `.mlv-canvas` → `display: block`, `height: auto`, `overflow: visible`); and drops the canvas transform (`.mlv-world { transform: none; position: static }`) so the world prints at the **natural pixel size the layout already wrote onto it**. `print-color-adjust: exact` keeps the lane washes and stage rails, which are meaning rather than decoration, and the compact-LOD rules are lifted, because level of detail is a zoom decision and print has just thrown the zoom away.

**The three regions** (`export/actions.ts`). `diagram` is the whole world; `view` is the visible canvas converted to world coordinates and clamped to it; `scope` is the **bounding box of the `viewRole === 'core'` nodes**, padded 24 px — the scope's actual subject, not the projection. With no projection there is no core, the offer degrades to `diagram`, and the menu entry is **disabled** with a title saying why. **Elements that do not intersect the region are not emitted at all**, so a "current view" file does not secretly contain the rest of the document. **The menu** is one trigger beside Fit (`Chrome.exportSlot`), `aria-haspopup="menu"` / `aria-expanded`, with the popup mounted on the **app root, not in the toolbar** (the chrome is one roving `role="toolbar"`, and eight more controls under its arrow keys is the flattening that group exists to undo): a `role="menu"` with three `menuitemradio` regions and five `menuitem` outputs, its own arrow keys, Home/End, Escape-closes-and-returns-focus, Tab-closes and outside-click-closes.

**What the export cannot render, stated rather than discovered.** The SVG is faithful, not pixel-identical: CSS `box-shadow` is not reproduced; CSS text ellipsis is replaced by an **average-advance** estimate per face (0.51 em sans, 0.55 em semibold, 0.60 em mono, 0.72 em for the all-caps lane header), so an unusually wide string can ellipsise one character early or late; the `color-mix` washes are `fill-opacity` over the emitted background; a collapsed group's severity **cluster** is drawn where the DOM draws a pill; and the flow animation, the hover card, the selection ring and the issue connectors are **states, not content**, and are never exported. An edge label can still be crossed by a **later** edge's stroke, and the export reproduces that faithfully, because it is the same picture.

### 10.6 Labels, and the scaffolding around the diagram

| # | Rule |
|---|---|
| **V9** | A label is anchored to the **longest axis-aligned run of its own route that lies strictly inside one lane band**, a band being the lane box inset by `LANE_PAD` top and bottom. Horizontal runs are preferred over vertical; when no run survives the clip the **outlet-adjacent segment** is used and the placement is marked `fallback`. |
| **V10** | **No drawn label may sit within `LANE_PAD` of a lane boundary, overlap a node card, or overlap another drawn label.** One greedy declutter pass, in **document order**, with a **fixed** cap of 20 candidate positions (10 per run, over the route's runs longest-first). When the cap is reached the label is **hidden**, and its `<g class="mlv-edge">` carries `data-label-hidden="1"` so the drop is auditable rather than silent. |
| **V11** | Only labels drawn **without hovering** participate in the collision set and can be hidden by it. A call or config label appears one at a time under the pointer; it obeys V9 and V10's band and card rules and is **never dropped**. |
| **V12** | The pass is **pure geometry over (frame, routes)**: no DOM, no text measurement, no randomness, every collection walked in document order. Two runs over the same bytes place every label identically. The label box model is calibrated against Chromium's measured ink, because a model smaller than the ink enforces `LANE_PAD` against a box nobody draws. |
| **V13** | The severity marker is walked **along its own polyline** until its disc clears the label box, instead of being centred on the same point. |
| **V14** | The **skip link is the document's first tab stop** and lands focus on the canvas. It is a real anchor whose click is `preventDefault`ed: the report never navigates its own document, not even to a fragment. |
| **V15** | The canvas is reachable in **≤ 3 presses via the skip link and ≤ 4 without it**. The toolbar row and the stage-filter row are **ONE** `role="toolbar"` with arrow-key roving (one tab stop); the search input keeps its own stop because its arrow keys drive the caret and the results listbox; **nothing else may be added between them and the canvas** — anything new that would take a stop there goes *after* the canvas in DOM order. |
| **V16** | Exactly **one `h1`**, carrying the workspace name, and a monotonic outline below it: `h2` for the `<main>` diagram region and for the rail, `h3` per rail panel, `h4` for the severity sections and the inspected node, `h5` for that node's subsections. **No level is skipped.** |
| **V17** | The canvas sits inside a **`<main>`** landmark; the rail stays a sibling `<aside>`. |
| **V18** | The minimap is **`aria-hidden="true"`** — it duplicates a canvas that is already fully navigable — and sits **before** the canvas inside `<main>`. An `aria-hidden` subtree may not hold a tab stop, so its in-panel chevron is pointer-only (`tabindex="-1"`) and the keyboard's copy is a labelled `Minimap` toggle in the toolbar. The two stay in step in both directions. |
| **V19** | Node cards carry their own `:focus-visible` ring, at the card's radius. |

**The five empty states.** The rail tells apart: nothing analysed, nothing wrong, filtered out, out of scope, and **every finding suppressed**. The fifth exists because *"No issues match these filters"* would be false and *"No issues found"* would be a clean bill of health over N suppressions.

### 10.7 Drawing the optional fields

**Every clause here begins with what happens when the field is missing.**

| # | Rule |
|---|---|
| **V4** | `Issue.change` is typed `string`, never narrowed. `new`, `touched` and `existing` draw a chip; anything else renders unchipped. **Absent means the run was not attributed**, and an unattributed finding is never hidden: the `only changed` filter drops an explicit `existing` and nothing else. |
| **V5** | `Issue.baselined` is treated exactly as `suppressed`: **marked, not deleted**. Both are removed from the severity sections by `FilterModel.keep` and listed in the rail's collapsed `N suppressed` section, each row carrying its own chip. `FilterModel.keepBase` is `keep` without the suppression and baseline tests, so that section still honours the severity chips, the stage chips and a host's `setFilter` codes. |
| **V6** | `MLGraph.answers` is optional and every field inside it is optional. **Absent means absent**: no card is drawn, never an empty one; a block carrying two of the four draws two rows in the fixed order `dataEntry, objective, evaluation, verdict`. A row whose `confidence` is under **0.6** is **marked as low confidence rather than dropped**. |
| **V7** | An `answers` citation is `{file, line}` — an answer cites a place to look, not a range to select. The viewer completes it into the six fields `openLocation` requires, rebuilding `absFile` from `workspace.root` when the emitter did not write one. |
| **A1–A3** | The **diff overlay** reaches the viewer three ways, consulted in this order: the `diffOverlay` message, `window.MLViewDiff`, and a `<script type="application/json" id="mlview-diff">` element beside `#mlview-graph`, read at **mount** so the first paint carries the decoration. The payload is **validated before anything is drawn**: `kind` must be `"mlview-diff"` and `diffVersion`'s major must be `1`. Anything else — a graph document, a truncated block, a future major, a string — degrades to **no overlay**, and the diagram is byte-for-byte the one it would have drawn anyway; an overlay rejected on the wire is answered with one `log` frame at `warn`. `baseLabel` is the **host's** name for what the comparison is against; absent, it falls back to the root's last segment. |
| **A4** | The overlay is lifted onto a **COPY** of the host's document; `diffStatus` and `diffChanged` are renderer-local fields, **never on the wire**. |
| **A5** | **A removed node is drawn by resurrecting it** from the overlay entry and merging it into the document in the analyzer's own `(stage order, file, line, id)` position. It is **`ghost: false`** and carries the ghost **visual**: `ghost` is the schema's word for a step the analyzer expected and did not find, and §6.4 step 7 would prune a projected ghost with no retained finding. `stats` is left exactly as the analyzer wrote it. |
| **A6** | The three statuses are **never colour alone**: `added` gets a ledge bearing the word *added*, drawn as a child of the **card** so it survives the compact LOD; `removed` gets the dashed ghost outline plus a *removed* ledge; `changed` gets a chip that **names** the field when the overlay named one and counts them when it named several; `unchanged` is decorated with nothing. Every one is also in the card's `aria-label`, and a removed node is announced as *"Removed: …"*, never as *"Missing step"*. |
| **A7–A8** | The banner draws `summary.headline` **verbatim** when the overlay's own arrays support it; when they do not, the arrays win and the disagreement is reported as an extra note. **`notes[]` is never elided, never folded behind a disclosure and never capped.** Beside them the banner states the **viewer's own** blind spots, which no analyzer note can carry: removed edges are counted and not drawn, a resurrected ghost carries no findings / ports / nesting, removed nodes a scope or a cap took off screen are counted separately, and **a rename is every node removed plus every node added**. |
| **A9–A11** | **"Changed only" is a PROJECTION, not a filter**: the same `project()` machinery with `core` = every node the overlay says is not `unchanged` and `boundary` = one edge hop, so boundary stubs carry no severity badge, `nodeIds[0]` is rotated onto a core node, and the rail still says how many findings are outside the view — worded *"N outside the changed set"*. It **composes** with a real scope (the outer scope's selector, depth, anchors and project-level `of` counts are restored onto the result; the label becomes `<scope> · changed only`). With no scope under it the projection sets `view.scope: "changed"` and **the breadcrumb is not drawn**, `getScope()` still reports `spec: null`, and **`scopeChanged` is not posted**. |
| **A13** | The rail lists what the change **fixed** — findings that live in the BASE document — in a collapsed section that says so and offers **no "Open" and no suppression action**. Findings present in this document carry `new vs base` / `still there`, worded so they can never be confused with the `new` / `touched` / `existing` chip, which is about git hunks inside ONE analysis. |
| **A14** | `export/svg.ts` draws a removed node with the same dashed outline and `data-diff` on its `<g>`, but carries **no ledge, no chip and no banner**. An exported picture of a diff view is a picture of the narrowed graph, not a picture of the diff. |
| **B1–B3** | The **fix** marker is drawn from `Issue.fix`'s **presence**, never inferred from `fixHint`; a `fix` with an empty `edits[]` is not a fix. `safety` is typed `string` and **only the exact word `"mechanical"`** reads as mechanical — anything else, including a word a newer analyzer invents, reads as *needs review* and gets the cautious verb. The edit is shown **verbatim**, one `<pre>` per edit, labelled with its file, line and whether it inserts, replaces or deletes: no re-indentation, no wrapping, no prettifying, because Python is whitespace-significant. |
| **B4–B6** | The viewer **never edits and never auto-applies**: in VS Code it posts `applyFix` (the id and nothing else) and the panel states, **before** the button, that the host will apply it behind a preview. The **standalone report has no host to ask and sends no `applyFix` at all**: it copies the snippet through the `copy` message, and both the toast and the live-region announcement say *the clipboard*, never that anything was edited. The confidence chip is drawn beside the marker on every row, so the analyzer's `likely` floor is auditable. |
| **C1–C5** | **Resolved configuration has two sources, in this order.** `Node.attrs` takes precedence when populated, accepting several spellings per field (`resolvedValue`/`resolved`/`configValue`/`value`; `resolvedFrom`/`configSource`/`source`/`from`; `alternatives`/`oneOf`/`candidates`; `unresolved`/`configUnresolved`) — **the canonical spellings are the first of each group**. Otherwise the analyzer's **own sublabel** is kept **verbatim**, because that wording is shared with `mlview issues` and the other hosts. A resolved value from `attrs` replaces the sublabel with `name = value`, middle-truncated at 40 characters with the untruncated string on `data-config-sub` and in the hover, and the provenance spoken in the `aria-label`. A `getattr` registry is **one** node, not two `unknown` boxes: `data-config-alt="N"`, a doubled dashed outline, and an Inspector table naming **all N** candidates with their defining module and saying out loud that MLView could not tell which one runs *"rather than guessing"*. **"Could not resolve" is drawn, never omitted** — `not resolved`, with the analyzer's reason when it gave one. The renderer **de-rates nothing and invents nothing**. |
| **Rollup** | `src/rollup/rolled.ts` is the only module that knows the names `Node.rolledUp` and `Edge.weight`, and it **refuses** a value that is not a positive integer. A rolled-up card borrows the collapsed-group visual and **none** of its affordance (`aria-label`: *"7 nodes folded into this card, which cannot be opened"*). A weighted cable carries a `× n` pill whose `<title>` says it counts **connections, not call sites**. The banner draws the analyzer's own `truncated` sentence verbatim, and **`stats.truncated` alone never produces the rollup wording** — a document written by an older analyzer keeps the sentence that is true of it. |
| **Pipelines** | The relation of §6.7 is ported line for line; `pipelineDrift` **reports** a disagreement with the emitted `pipelines[]` block instead of trusting it. The chooser opens once at two or more pipelines, with Tab trapped so `aria-modal="true"` is not a lie, and states five caveats about its own list: it is not a partition, N nodes are in no pipeline, `config` edges are cut, entrypoints are capped at ten, and — when `stats.truncated` — the counts describe the summarised graph. |

## 11. MCP tools (Claude Code)

`contracts/mcp.md` is this section. The server is `claude-plugin/server/mlview_mcp.py`, built on the official `mcp` Python SDK (`from mcp.server.mcpserver import MCPServer`, falling back to `mcp.server.fastmcp.FastMCP` on mcp 1.x). Before importing `mlview` it prepends `<plugin_root>/vendor` to `sys.path` and, as a dev fallback when that has no `mlview` package, `<repo>/analyzer/src`. **`${CLAUDE_PLUGIN_ROOT}/vendor` on `PYTHONPATH` is what makes the plugin work with no pip install at all.** Logging goes to **stderr only**; **stdout carries protocol frames only**. `.mcp.json` sits at the plugin root — the default scan location, so `plugin.json` omits the override field entirely:

```json
{ "mcpServers": { "mlview": {
  "type": "stdio", "command": "${MLVIEW_PYTHON:-python}",
  "args": ["${CLAUDE_PLUGIN_ROOT}/server/mlview_mcp.py"],
  "env": { "PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}/vendor", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "MLVIEW_PROJECT_DIR": "${CLAUDE_PROJECT_DIR}", "MLVIEW_DATA_DIR": "${CLAUDE_PLUGIN_DATA}",
           "MLVIEW_CACHE_DIR": "${CLAUDE_PLUGIN_DATA}/cache" } } } }
```

### 11.1 Exactly five tools

`TOOL_NAMES = ("mlview_analyze", "mlview_issues", "mlview_graph", "mlview_explain", "mlview_open_diagram")` — **five, and the exactly-five assertion is a gate.** Every result is `{content: [{type: "text", text: <json string>}], structuredContent: <object>, isError: false}`, and **every model-facing payload is capped at 4096 bytes** with full detail behind `graphPath`.

| Tool | Parameters | Returns (`structuredContent`) |
|---|---|---|
| `mlview_analyze` | `path?`, `framework="auto"`, `maxNodes=400`, `includeHtml=False`, `scope?`, `depth?`, `includeNotebooks=False` | `{schemaVersion, root, filesAnalyzed, filesFailed, notebooksSkipped, frameworks[], stats{nodes,edges,issues{low,medium,high}}, lanes[{stage,label,nodeCount,maxSeverity}], topIssues[{code,severity,confidenceBucket,title,file,line}] (≤10), answers?, graphPath, reportPath?, truncated, cached?, scope?, note?}` |
| `mlview_issues` | `path?`, `minSeverity="low"`, `minConfidence=0.0`, `code?: string[]`, `limit=20`, `scope?`, `depth?`, `groupBy?`, `changedSince?`, `baseline?`, `includeNotebooks=False` | `{countBySeverity{low,medium,high}, suppressedCount, issues[{id,code,severity,confidenceBucket,title,message,fixHint,file,line,related[{role,file,line}]}], note?}` |
| `mlview_graph` | `path?`, `format="mermaid"`, `scope?`, `depth?`, `base?` | `{format, content, …}` — **mermaid is the default**, so the model gets a compact textual diagram it can reason about in the terminal without ingesting the whole graph |
| `mlview_explain` | `nodeId?`, `code?`, `path?`, `graphPath?` | For a node: the node record + in/out edges + its issues + `stageEvidence` + a ≤60-line source segment. For a rule code: the full offline rule doc. |
| `mlview_open_diagram` | `path?`, `graphPath?`, `out?`, `scope?`, `depth?` | `{reportPath, reportUrl, opened, exportHint}` — writes the self-contained HTML and opens it |

### 11.2 `scope` on the MCP surface

`mlview_graph`'s `scope` accepts the full §6.1 grammar **plus two catalogue values that are MCP-only**: `"stages"` (a non-projecting summary) and **`"units"`**. `scope: "units"` returns one row per scopable unit — every node with children, or `level ∈ {stage, unit}` — as `{nodeId, label, qualname, file, line, nodeCount, maxSeverity}`, rendered as text / json / mermaid, sorted `(-nodeCount, file, line, qualname)`, shed to fit the budget. **This is discovery without a sixth tool.** `depth` is bounded `0..2`. `mlview_graph {scope: "diff", base}` is the comparison projection — a diff is another projection of the same graph, so it is a **value of `scope`, not a sixth tool**.

| # | Rule |
|---|---|
| **E2** | `base` is the earlier `analyze --json` document, resolved through `mlview_workspace.resolve_path`, so it is constrained to the project directory exactly like every other path a tool argument carries. |
| **E3** | **A base that is not a graph is an ERROR naming the file** — missing, unreadable, not JSON, not a graph, or itself an overlay — re-raised through `visible_errors` as a `ToolError` the model can act on. **It is never an empty comparison:** *"0 changes"* is the most dangerous wrong answer this projection can give. |
| **E4** | The result is `{format: "text", scope: "diff", content, summary{headline, nodes, edges, issues{new,fixed,persisting}}, note, basePath, graphPath, truncated}`. `content` is `emit/diff_out.render_summary` — the analyzer's own text, never a second rendering — so a model never parses prose to answer *"did this PR add a finding"*. |
| **E5** | **The caveats outlive the clip.** `note` is a `PROTECTED_KEY` in the 4 KB budget walk: rows may be shed and the caveats may not. It carries every `notes[]` entry, the *"both analyses read their whole workspace"* line when a pair has nothing to declare, and — **always, for every pair** — the standing sentence that a rename is every node removed plus every node added. |

**Other invariants.** Every scoped result keeps the existing filtered-view `note` and adds `"scope": "<normalized spec>"`. `mlview_graph`'s docstring contractually names the accepted values and is extended in the **same edit** as the grammar — a documented contract must not become a lie the model acts on; errors surface through the existing `ValueError` path carrying the §6.2 code, term and candidates. **The analysis cache is never keyed on scope**: `load_graph` caches on `(resolved, framework, maxNodes, signature)`, `project()` is applied to the cached dict, and `graphPath` keeps pointing at the **full** document, so a model can always widen for free. `mlview_views.py` keeps `subgraph`, `stage_scope_ids` and `neighbourhood_ids` as **thin delegating wrappers** over `mlview.core.project` — wrapped, not deleted — so no other caller moves. **MCP gains no export, and says so**: `mlview_open_diagram` writes HTML only (an MCP server has no renderer, and inventing one in Python would be a second geometry to keep in step with the viewer), and its result carries a **constant, always present** `exportHint` naming the report's own export menu and the two VS Code commands, with the docstring saying the same.

## 12. VS Code contributions

`vscode-extension/package.json` is the authority for every list here, and `test/manifest.test.js` asserts the exact sets.

### 12.1 Manifest essentials

`"engines": {"vscode": "^1.100.0", "node": ">=20"}` · `@types/vscode@1.100.0` · `typescript@5.9.3` · `esbuild@0.28.2` · `@types/node 20.x` — exact pins · `activationEvents: ["onLanguage:python", "workspaceContains:**/*.py", "workspaceContains:**/*.ipynb", "onWebviewPanel:mlview.diagram"]` · `capabilities.untrustedWorkspaces: {"supported": "limited"}` (analysis is disabled in restricted mode, since it spawns an interpreter) · `extensionKind: ["workspace"]`, **declared** rather than relied upon, so Remote-SSH, WSL and Dev-Container installs land on the machine that owns the files and the interpreter. `npm run compile` bundles `src/extension.ts` → `out/extension.js` (cjs, node, `--external:vscode`) and runs `sync-rule-docs` and `sync-walkthrough`; `npm run check` is `tsc --noEmit`; `npm test` is `node --test test/*.test.js` with a mocked `vscode` module.

### 12.2 Commands — 19 contributed, all `"category": "MLView"`

`mlview.visualize` · `visualizeWorkspace` · `refresh` · `showIssues` · `revealInDiagram` (`Alt+M`, `editor/context`) · `scopeToSymbol` (`$(list-tree)`, `editor/context` group `mlview@3`, `alt+shift+m` when `editorTextFocus && editorLangId == python`) · `clearScope` (`$(clear-all)`) · `exportHtml` · `exportSvg` · `exportPng` · `activeFolder` · `openConfiguration` · `createBaseline` · `saveComparisonBase` · `compareWithBase` · `compareWithCleanSample` · `selectInterpreter` · `showOutput` · `showRuleDoc`.

**Registered and deliberately NOT contributed**, because each takes an argument and would be broken from the palette: `mlview.copyIgnoreComment`, `mlview.addIgnoreComment`, `mlview.disableRule`, `mlview.applyFix`.

`scopeToSymbol` resolves the cursor to the **enclosing unit**: `findNodeAtLine` (which already picks the narrowest containing node), then climb `parent` to the narrowest ancestor with `level ∈ {unit, stage}`, then post `{type: 'setScope', spec: 'unit:' + qualname}`. When nothing contains the cursor, show the "no node here" toast the reveal path already uses; **do not guess**. `onScopeChanged` sets `panel.title = spec ? 'MLView — ' + label : PANEL_TITLE` and `panel.description = nodes + ' of ' + of + ' nodes'`. `exportSvg` / `exportPng` act on the **live** panel (with no diagram open the command says so), ask which region to draw — whole diagram, current view, and current scope **only while the viewer has reported one** — and take that choice as an optional command argument so a keybinding can skip the pick; asking for `'scope'` with no scope set falls back to `'all'`.

### 12.3 Settings — 16 rows, and this is the whole set

| Setting | Type | Default |
|---|---|---|
| `mlview.pythonPath` | string | `""` |
| `mlview.analyzeOnSave` | boolean | `true` |
| `mlview.exclude` | array | `[]` |
| `mlview.maxFiles` · `mlview.maxNodes` | integer | `500` · `400` |
| `mlview.minSeverity` · `mlview.minConfidence` | `low\|medium\|high` · number | `low` · `0.6` |
| `mlview.currentFileAnalysisScope` | `file\|package\|workspace` | `package` |
| `mlview.includeNotebooks` | boolean | `false` |
| `mlview.diagnosticsEnabled` · `mlview.diagnosticSeverity` | boolean · `warning\|error` | `true` · `warning` |
| `mlview.disabledRules` | array | `[]` |
| `mlview.codeLens` | boolean | `true` |
| `mlview.configPath` · `mlview.baselinePath` | string, `scope: resource` | `""` |
| `mlview.trace` | `off\|messages\|verbose` | `off` |

`currentFileAnalysisScope` decides what **Visualize (Current File)** hands the analyzer before narrowing the diagram back to the file through `setScope`. `package` is the default because analysing a file alone cannot fire MLV301, MLV302, MLV401 or MLV501 — each needs a sibling module; `file` restores the old behaviour and earns a `single_file_analysis` diagnostic for doing so. **Nothing removed here may come back under the same name with different meaning**; a future toggle needs a new name. There is deliberately **no** persisted active-folder setting (§12.6 B2) and **no** `mlview.defaultScope`; the flow preference is renderer-owned via `ViewState.flow`.

**`mlview.disabledRules` and `mlview.exclude` each carry a `markdownDescription`** (not a `description` — one per row, or the Settings UI shows both) stating: this setting is an **ADDITIVE** filter; the table in the configuration file **WINS**; and the thing it therefore cannot do — *"cannot re-enable a rule the file disabled"* / *"cannot re-include a path the file excluded"*. Each names the table it loses to (`[rules].disable`, `[paths].exclude`) and links to `#mlview.configPath#`; `test/config.test.js` asserts the claim on **both** rows, in both directions.

### 12.4 Diagnostics, suppression and the fix lightbulb

**Diagnostics mapping (frozen).** high → `Warning` (`Error` under `diagnosticSeverity: "error"`); medium → `Warning`; low → `Information`. `source: "MLView"` · `code: {value: "MLV201", target: Uri.joinPath(ctx.extensionUri, 'docs', 'rules', 'MLV201.md')}` — a **local** file, so rule docs work offline · `relatedInformation` from `relatedLocs` · only `confidence >= mlview.minConfidence` and `suppressed === false` are published · per-file `set()`, with files dropping to zero issues explicitly cleared. **A scope never changes the Problems panel, the status-bar count, or the issue quick pick**: `DiagnosticsPublisher.publish` output is byte-identical while scoped, asserted by `diagnostics.test.js`.

**Suppression — three actions, one implementation.** The `CodeActionProvider` (`src/codeActions.ts`, `QuickFix` kind, `python` selector) and the `suppressRule` message both call `runSuppression`, so the confirm dialog, the containment check and the "already ignored" message cannot differ by where the user clicked. `copy` → `# mlview: ignore[MLV201]` to the clipboard; `insert` → a `WorkspaceEdit` replacing the diagnostic's own line, **preferred**; `disable` → `[rules] disable` at the workspace root, behind a **modal** confirm.

| # | Rule |
|---|---|
| **S3** | **The comment MERGES, it never stacks.** The analyzer reads the **first** `# mlview: ignore[...]` on a line, so `withIgnoreComment` adds the code to the existing bracket list, refuses to edit a line already covered by a blanket `ignore` / `ignore-file`, and reports "already listed" rather than writing a duplicate. |
| **S4** | **The config write is confirmed, contained and conservative.** The dialog is **modal**, names the file, says the rule stops being reported for everyone who opens the repo and for CI, and points at the narrower gesture. The path is always `<workspace root>/.mlview.toml`, checked with the same containment rule every other write path uses; with no folder open the action refuses and says so. The edit is a **line transform, never a TOML round-trip**: an existing `[rules]` section keeps its comments, key order and CRLF, and an unterminated array is refused rather than half-written. |
| **S5** | `suppressRule.line` is 1-based like every `Loc.line`; `src/location.ts` is still the only module that converts. |
| **A1** | **One entry point.** `applyIssueFix(issueId, deps)` is the only function that applies a fix; the lightbulb, the `mlview.applyFix` command and the viewer's `applyFix` message all reach it. |
| **A2** | **`QuickFix` and nothing else.** `providedCodeActionKinds: [QuickFix]`. It must **never** contribute `source.fixAll` or any `source.*` kind: those are what `editor.codeActionsOnSave` runs unattended. |
| **A3** | **`isPreferred` is derived from `safety` and from nothing else.** `Ctrl+.`+Enter and "fix all in file" must not land on a judgement call. |
| **A4** | **Every entry needs confirmation.** Each `WorkspaceEdit` entry carries `{needsConfirmation: true, label: fix.title, description: "MLView · <safety>"}` and the apply passes `{isRefactoring: true}`, so VS Code routes the change through the refactor **preview**, always, for both safety levels. |
| **A5** | **The host re-checks the floor.** A fix on a finding whose bucket is not `certain` or `likely` is refused with `low-confidence`, even though the producer already refused to attach one. |
| **A6** | **`fix` is read defensively.** `readFix` validates the whole shape — title, `safety` against the closed pair, every edit's absolute path, 1-based `line ≥ 1`, `endLine ≥ line`, a non-inverted range, a bounded `newText`. Anything else yields **no lightbulb**. The host's edit cap is **16** against the producer's 4. |
| **A7** | **All or nothing.** If any edit fails any check the whole fix is refused and not one byte is written. |
| **A8** | **Containment.** Every edit's `absFile` goes through `codeActions.writableFile`; a path outside every open workspace folder is **refused and logged**, never redirected. |
| **A9** | **Staleness.** The document carries no content hash, so the host proves the two ways it is certainly wrong **before** the preview: the target buffer has **unsaved changes**, or the edit's end line is **past the end** of the buffer. Either is a `stale-document` refusal naming the file. |
| **A10** | **Notebooks are excluded.** A `vscode-notebook-cell:` document gets no actions: a finding inside an `.ipynb` names the generated shadow module, and repairing that would edit a file the user never wrote. |

### 12.5 Export, comparison and the one spawn seam

**Export.** `isUiToHost` accepts `exportFile` only when `kind` is one of the two words, `data` is pure base64 (`^[A-Za-z0-9+/]+={0,2}$`, length a multiple of 4, no whitespace, no `data:` prefix) of at most **32 MiB decoded** — checked as a **character count, before anything is allocated** — and `suggestedName`, when present, is 1–128 characters with no path separator and no `..`. The writer then **refuses bytes that are not the format asked for**: the eight-byte PNG signature for `png`, `<?xml` / `<!DOCTYPE svg` / `<svg` for `svg`. That check is normative, not defensive tidying: a `.svg` is executable content in a browser. **A refused payload never opens a save dialog.** The save is the host's and it is a **dialog** — `showSaveDialog` (defaulting to the workspace folder, filtered to the one extension) then `workspace.fs.writeFile`. **No path from the viewer is ever written to**: `suggestedName` names the file the dialog opens on and nothing else, and the bytes written are byte-identical to the decoded payload.

| # | Comparison (`src/compare.ts`) |
|---|---|
| **C2** | The base is **the analyzed document, written verbatim** to `<folder>/.mlview/comparison-base.json`. Saving a base **never** spawns the analyzer: a diff whose two sides came from two different runs is the mistake §7's `notes[]` exists to make visible. |
| **C3** | The comparison is **the analyzer's**: `python -X utf8 -m mlview diff <base> <head> --json -` through `CoreClient.runCli`. A stdout payload whose `kind` is not `mlview-diff` is refused with a message naming that the core may predate `mlview diff`; **`kind` is checked before anything else**. |
| **C4** | The head is staged in the extension's own `globalStorageUri`, **never in the user's repository**. The only file this feature writes into a workspace is the base named in C2, and only when the user asks. |
| **C5** | **`notes[]` is never swallowed.** Every entry goes to the MLView output channel verbatim, and the toast carries the headline plus `· N caveat(s) — see MLView output` with a `Show Output` action. |
| **C6** | **A comparison dies with the document it described.** `MlviewPanel.postGraph` posts `diffOverlay: null` immediately after any graph whenever an overlay is outstanding: a stale *"0 new findings"* over a freshly analysed diagram is a confident wrong answer. |
| **C7** | The clean twin is found **by name, under the root** — `samples/vision_pipeline_clean`, then `vision_pipeline_clean` — and never outside it. When there is none the command **names what it looked for**. |

**One spawn seam.** Everything — the diagram, the export, the baseline run, the comparison, the chat participant, the LM tools, `mlview init` — runs through `CoreClient`, so the trust gate, the interpreter chain, the bundled-core `PYTHONPATH` and the UTF-8 environment are all in one place. **A second `execFile` anywhere in this extension would be a second place for `untrustedWorkspaces: "limited"` to be forgotten.** There is exactly one argv builder, `buildAnalyzeArgs({scopeSpec, depth, …})`.

### 12.6 Chat, language-model tools, multi-root, configuration and the walkthrough

**Chat participant.** `chatParticipants: [{id: "mlview.chat", name: "mlview", fullName: "MLView", isSticky: true, commands: [diagram, issues, explain]}]`, registered as `vscode.chat.createChatParticipant('mlview.chat', handler)` — **the id must match the manifest**. `/issues` streams each finding via `stream.markdown(...)` followed by `stream.anchor(new vscode.Location(uri, range), 'train.py:44')`, so every finding in chat is a click into the source; `/diagram` opens the panel and offers `stream.button({command: 'mlview.showIssues', title: 'Show issues'})`. **The free-form path is the only place a cloud model is touched, and the participant says so in its first response.**

**Three language-model tools** — `mlview_analyzeWorkspace` (`mlviewAnalyze`), `mlview_listIssues` (`mlviewIssues`), `mlview_showDiagram` (`mlviewDiagram`). **Both `canBeReferencedInPrompt: true` and `toolReferenceName` are required** — with either missing the tool exists in `vscode.lm.tools` but agent mode never calls it. Each tool body is extracted into a pure, directly-invocable function so it can be smoke-tested with Copilot absent; `mlview_showDiagram` has a side effect, so its `prepareInvocation` also returns `confirmationMessages`.

| # | Rule |
|---|---|
| **A1** | All three gain `scope` (string) and `depth` (integer, `0..2`), both optional. A call that omits them produces **byte-identical** argv and a byte-identical answer. |
| **A2** | **One grammar, two hosts, word for word.** The `scope` description is the `scope:` block of `mlview_graph`'s docstring **verbatim** (modulo wrapping), and `depth` likewise; `test/lmtool.test.js` reads the Python file and asserts the containment. |
| **A3** | **`stages` and `units` are MCP-only and must NOT appear here** (§6.3). The seven the CLI accepts are exactly the seven advertised, asserted in both directions. |
| **A5** | **A depth a host cannot act on is dropped; a scope it cannot resolve is a refusal.** `depth` outside `{0,1,2}` falls back to the per-kind default; an unrecognised `scope` reaches the CLI and comes back as its `bad_selector` error — **never a silently substituted default**. |
| **A6** | **A scoped answer says so before it says anything else:** *"This is a filtered view of `<spec>` [at depth N]: the counts below describe that scope, not the whole project. Re-run without a scope for the project-wide numbers."* |
| **A7** | **A scoped result is never adopted as the folder's graph**: a projected document is a filtered view, so a scoped call neither reads the cached graph nor writes one. `scopeKey` gains a third argument so a scoped run and the diagram's unscoped run are two single-flight keys. |
| **A8** | `mlview_showDiagram` with a `scope` opens the panel **at** that selector through the same `setScope` message the command posts. Nothing is locked. |
| **B1** | Multi-root: the single-graph assumption is replaced by a **map keyed by workspace folder** (`src/folders.ts`), one `FolderState` per folder holding `graph`, `index`, `lastScope`, `staleFiles`, `appliedFocus`, `lastFailure`. A single-folder window is the **one-entry case** and its behaviour is unchanged — asserted, not assumed. |
| **B2** | **The active folder is session state, not a setting.** `mlview.activeFolder` is a **command**; a folder named by a string means nothing on the next machine. It defaults to `workspaceFolders[0]`. |
| **B3** | Three ways it moves: the command, the **status-bar tooltip's picker**, and opening a Python file — `Visualize (Current File)` makes the file's own folder active. |
| **B4** | With two or more folders open the status-bar tooltip becomes a trusted `MarkdownString` carrying *"Folder: `<name>` — N other folder(s) in this workspace is not shown here."* and one command link. With **one** folder it stays the plain string it has always been. |
| **B5** | **Per-window surfaces publish every analyzed folder; per-file surfaces answer for the file's own folder.** `DiagnosticsPublisher.publish` takes one graph **or many** and clears down to their union. `MlviewCodeLensProvider` takes the `TextDocument` and is answered with that folder's graph; a file outside every analyzed folder gets **nothing**, never the active folder's line numbers. |
| **B6** | The single-flight key is **folder + scope**. A save re-analyses the active folder **plus** every other folder that has a graph and a stale file in it. |
| **B7** | A closed folder has its state **pruned** and its diagnostics dropped, and the folders still open are **re-published rather than cleared**. |
| **B8** | The chat participant and the language-model tools analyse the **active** folder, not `workspaceFolders[0]`. |
| **C1** | Every analyzer spawn passes `--config` when there is a file to name, resolved in `src/mlviewConfig.ts` by: `mlview.configPath` when set and present; else `<folder>/.mlview.toml`; else `<folder>/pyproject.toml` **only when it carries a `[tool.mlview]` table**. Resolution happens inside `CoreClient`. |
| **C4** | **A baseline is never discovered**: `--baseline` is passed only when `mlview.baselinePath` is set **and** the file exists — a file dropped into `.mlview/` must not quietly empty somebody's Problems panel. A `configPath` or `baselinePath` naming a file that is not there is a **warning in the output channel** naming the path, never a silent fallback. |
| **C5** | `Open MLView Configuration` opens the resolved file and, when there is none, asks first and then runs **`mlview init`** rather than writing a stub — a host-authored starter would be a second, drifting description of the rule catalogue. A core too old to have `init` produces a message naming that, not a silent no-op. `Create Baseline From Current Findings` runs `mlview baseline write` and offers to point the setting at what it wrote. |

**There is deliberately no host-side override path**: a second mechanism that could contradict the checked-in file is the risk one configuration surface exists to remove. **Prose-to-scope resolution stays cut** — a model must send a selector from the grammar; MLView does not guess one from "the evaluation bit".

**Feature detection (mandatory).** `registerChat` runs only when `typeof vscode.chat?.createChatParticipant === 'function'`, and `registerLmTools` only when `typeof vscode.lm?.registerTool === 'function'`, each inside `try/catch` that logs a warning. **The diagram, diagnostics, reveal and CodeLens register unconditionally: a chat-API change can never break activation.**

**Notebooks, host half.** With `mlview.includeNotebooks` off, `buildAnalyzeArgs` emits the argv it emitted before notebooks existed, asserted as a prefix equality. With it on, a finding is republished on the cell's `vscode-notebook-cell:` URI with a cell-relative range, degrading one honest step at a time: cell URI → the `.ipynb` → the generated module.

**The walkthrough.** One, `mlview.gettingStarted`, with **five** steps — install, visualize the bundled sample, read a finding in Problems, `Alt+M` reveal, `Alt+Shift+M` scope. **Each step invokes exactly one already-contributed command** and completes on `onCommand:<that command>`; a step pointing at an unregistered command would do nothing when clicked, silently. The five pages live in `docs/walkthrough/` and are copied into `vscode-extension/docs/walkthrough/` by `tools/sync-walkthrough.mjs` (with `--check`), because `media.markdown` resolves relative to the **extension** root.

**Stated limits.** The diagram shows one folder at a time; the Problems panel is the only surface showing the union. A CodeLens on a file in a folder nobody has analyzed draws nothing and says nothing. A depth typed at its per-kind default is indistinguishable from none. The lightbulb offers a fix for a finding the Problems panel may be hiding, because the floor for an **edit** is the producer's `likely`, not `mlview.minConfidence`. A comparison is only as honest as its base: nothing covers a settings change between the two runs.

## 13. The Claude Code plugin

`claude-plugin/.claude-plugin/plugin.json` carries `name`, `displayName`, `version`, `description`, `author`, `license: "MIT"` and `keywords`. **Component-path fields (`commands`, `skills`, `agents`, `hooks`, `mcpServers`) are deliberately omitted** — the conventional directories are the defaults. Note the verified asymmetry: `skills` *adds to* the default scan while `commands` / `agents` *replace* it, so setting them by accident silently drops the defaults. `test_plugin_manifest.py::test_plugin_json_omits_every_component_path_field` enforces the omission.

### 13.1 Commands and skills

`commands/mlview.md` carries frontmatter `description`, `argument-hint: "[path] [--scope <SPEC>] [--depth <0-2>]"` and `allowed-tools: [Bash, Read, Glob]`. Its body prefers `mlview_analyze` + `mlview_open_diagram` when the MCP tools are available and **otherwise** runs the documented `python -m mlview analyze …` line through `Bash` — that fallback is why the demo does not depend on MCP registration succeeding. `commands/mlview-issues.md` is headless, printing only the issue table for agent loops and PR descriptions; it takes the same two scope arguments plus `--diff-base <file>`, and its `Bash` fallback is **three runnable lines** (`analyze --json` twice, then `diff`), because `tests/test_command_arguments.py` **executes every documented fallback** and a placeholder would be a documented command that fails.

**Argument grammar.** `$1` is the path (default: the project dir). `--scope` takes one §6.1 selector; `--depth` takes `0`, `1` or `2`. Both optional, order-free, each at most once; anything else is passed through unchanged. **The `--scope` fragment is omitted entirely when no scope was given**, so the unscoped fallback is unchanged.

`skills/mlview-visualize/SKILL.md` triggers on "visualize / diagram / map / review the structure of ML code" and instructs the model to call `mlview_analyze` then `mlview_issues` **before** reading files; its **"When to scope"** section tells the model to call `mlview_graph {scope:"units"}` when the user names a part of the pipeline, to scope a question about one concern, and — explicitly — **not** to scope a request to review the project. `skills/mlview-triage/SKILL.md` takes the issue list, reads the relevant source and proposes fixes; it explicitly does **not** auto-edit.

**Install paths**, in order of preference: `claude --plugin-dir <abs>/claude-plugin` (session-only, zero install) · the repo-root `.claude-plugin/marketplace.json` plus `/plugin marketplace add ./` and `/plugin install mlview@mlview-local` · `claude mcp add mlview -- python <abs>/server/mlview_mcp.py` (MCP only). Run `claude plugin validate ./claude-plugin --strict` first, always. The marketplace manifest carries the local `./claude-plugin` entry **and** a hosted one; **two entries may never share a name.** A hosted entry names the plugin's **directory, not the repository**: the source forms that fetch a repository — `github` (`repo`/`ref`/`sha`), `url` and `archive` — have **no `path` key**, so the fetched tree's *root* becomes the plugin root, and MLView's repository root holds `.claude-plugin/marketplace.json` and **no** `plugin.json`, `commands/`, `skills/`, `hooks/` or `.mcp.json`. A `github` entry therefore published a directory with no manifest — no `/mlview` commands, no skills, no hooks and none of the five `mlview_*` tools — and, because Claude Code cannot read a remote `plugin.json` before installing, the failure surfaced only **after** the user installed. The hosted entry MUST use `git-subdir`, the only form carrying a subdirectory: `{"source": "git-subdir", "url": "https://github.com/realmyang/MLView.git", "path": "claude-plugin"}`, with `ref` (a release tag) and `sha` added once a release exists. **Gate:** `claude-plugin/tests/test_plugin_manifest.py` asserts that the repository root is not itself a plugin, that the hosted entry is `git-subdir` at `path: "claude-plugin"`, and that **every** entry's resolved plugin directory contains `.claude-plugin/plugin.json` — a source form with no `path` resolves to `.`, the repository root, and fails that assertion.

### 13.2 Hooks — `PostToolUse` and `Stop`

**The discipline is the feature.** A hook that speaks on every edit gets turned off within a day, so every rule below is a rule about staying quiet. This adds no tool, no schema field and no `Diagnostic.kind`.

| # | Rule |
|---|---|
| **A1** | `claude-plugin/hooks/hooks.json`, in the **conventional directory**. `plugin.json` must NOT gain a `hooks` field. |
| **A2** | The file is the shape the hooks documentation specifies: a top-level `"hooks"` key, one entry per event, each carrying a matcher group whose `hooks` array holds `{"type": "command", "command": ..., "timeout": ...}`. |
| **A3** | Two events. **`PostToolUse`** with matcher **`Edit\|Write\|NotebookEdit`** → `hooks/post_edit.py`. **`Stop`** (no matcher; the event *is* the match) → `hooks/stop_summary.py`. |
| **A4** | The command is `${MLVIEW_PYTHON:-python} "${CLAUDE_PLUGIN_ROOT}/hooks/<script>.py"` — the same `${VAR:-default}` idiom `.mcp.json` uses, with the same default `python`, **the one spelling Windows has out of the box**. `timeout` is 10 s: an outer bound on top of the script's own 3 s budget, never the mechanism. |
| **B1** | **Exit 0 immediately** unless the edited path is a `.py`/`.pyi` **under `CLAUDE_PROJECT_DIR`** — or an `.ipynb` when notebooks are on (`MLVIEW_INCLUDE_NOTEBOOKS`, or `[paths] notebooks = true` read **as text**, because the decision precedes importing the core). No analysis, no state file, nothing. |
| **B2** | **Emit only when the issue set GREW.** The previous run's issue ids are kept per project, per event, and diffed. |
| **B3** | **The first run on a project is silent by construction**: there is nothing to diff against. |
| **B4** | At most **5 rows**, worst severity first, at confidence **≥ 0.6** — the same floor the Problems panel publishes at. A hook is not the place to be louder than the quietest surface. |
| **B5** | **A hard 3-second wall clock.** The analysis runs on a daemon worker; when the budget expires the process exits 0 in silence. That cannot corrupt the shared cache: `load_graph` writes `graph.json` first and its `.sig` sidecar afterwards, so a half-written document is one whose sidecar does not match. |
| **B6** | **`MLVIEW_HOOK` selects which of the two speaks** — unset/`on` = PostToolUse only (the default), `stop` = the turn summary only, `both`, **`off` = neither**. Both matchers ship; an unrecognised value is the default, never an error. |
| **B7** | The `Stop` hook keeps its diff in a **separate slot** of the same state file, and returns immediately when `stop_hook_active` is set. |
| **C1** | **It never blocks.** Exit is 0 on every reachable path, including a malformed payload, an unreadable core and an unhandled exception. Exit 2 is what blocks a tool call or a turn, and nothing here can produce it. |
| **C2** | **It never writes into the project.** Two directories, and neither may be `<project>/.mlview`: `MLVIEW_DATA_DIR` and `MLVIEW_CACHE_DIR`. Both are `setdefault`, so a user who named either keeps it; with neither named, both go to a per-project directory under the system temp. Since §3.9 B5 moved the fact cache out of the analyzed folder by default, the second of those is belt and braces rather than the only guard. |
| **C7** | **No branch of the plugin's storage resolution is inside the analyzed project.** `mlview_workspace.cache_dir()` answers, in order: `MLVIEW_CACHE_DIR` when set; `<data dir>/cache` when a host named its storage directory through `MLVIEW_DATA_DIR` **or `CLAUDE_PLUGIN_DATA`** (the second name matters: a `claude --plugin-dir` session — the route `docs/VALIDATION.md` Session C prescribes — exports it without the first, and `hooks/hook_core.hook_data_dir` already accepted both, which is what makes one plugin share one directory, §13.2 C3); otherwise the core's `cache_dir_for(<project>)` (§3.9 B5). Until this clause the host derived its own answer from `data_dir()` and handed it back to the core through `MLVIEW_CACHE_DIR`, so a run with no plugin environment recreated `<project>/.mlview/cache` — the core stopped doing it and this host was still doing it for itself. `data_dir()` keeps its documented default of `<project>/.mlview` for `graph.json` and `report.html`, which are **outputs the user asked for**, but it MUST NOT create a directory as a side effect of merely resolving one: `resolve_out` asks with `create=False`, so answering a containment question about a model-supplied `out` leaves the project untouched. **Gate:** `claude-plugin/tests/test_storage_paths.py`. |
| **C3** | **It re-analyzes through the same `load_graph` the MCP tools use**, sharing `MLVIEW_DATA_DIR`, so the hook **warms** the cache the tools then read for free rather than keeping a second one. |
| **C4** | `sys.dont_write_bytecode = True` before the first `mlview` import, in both entry scripts and in `hook_core`. `claude plugin install` copies `vendor/` verbatim and the sync gate fails on a single `__pycache__` there. |
| **C5** | The only thing either process ever prints on **stdout** is one hook JSON object: `{"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}`. Diagnostics go to stderr and only under `MLVIEW_HOOK_DEBUG`. |
| **C6** | `claude plugin validate --strict` must stay green; where the CLI is absent, `test_hooks.py` asserts the manifest shape directly. |
| **D1** | **An issue id is content-addressed, so an unchanged finding whose line moved comes back with a NEW id.** Rows are therefore the findings whose id is new **and** whose `(code, file)` pair is new; the rest are counted — *"3 existing finding(s) moved line and are not repeated here"* — and never printed as news. |
| **D2** | The cost of D1, stated: **a genuine second occurrence of the same rule in the same file is counted rather than printed.** |
| **D3** | **The summary says what the run could not look at.** When the analysis skipped notebooks, failed to parse a file, or truncated at the node budget, one line names it. |
| **D4** | Every emitted context ends by naming the **project-wide total** and pointing at `mlview_issues` / `/mlview-issues`, so a 5-row extract can never read as the whole list. |

**Stated limits.** (1) **Windows without Git Bash**: a hook command is shell form, which is PowerShell there, and `${MLVIEW_PYTHON:-python}` does not expand — the hook fails to start, which is exit-non-zero, which is non-blocking, so the degradation is "MLView says nothing", never a broken session. (2) It re-analyzes the whole project, not the edited file; on a repository too big for the 3 s budget the hook is silent, correctly but permanently. (3) Findings below confidence 0.6 are never announced. (4) **Nothing correlates the finding with the edit**: the hook says the set grew after an edit, not that *this* edit caused it.

## 14. Fixtures, corpora and the rule catalogue

### 14.1 The sample projects

**`samples/vision_pipeline/`** — five files, ~230 lines of plausible PyTorch + scikit-learn that needs neither library installed to analyse. **Exactly 15 planted issues: 5 high, 6 medium, 4 low**, from 14 distinct rule codes (MLV602 fires twice). `expected_issues.json` is the machine-checked contract and records code / file / line / severity — **deliberately not confidence**, which is pinned where the constraint lives (`test_unresolved_callee.DEMO_FINDINGS`). If the sample is edited, that file is edited in the same commit.

| # | File | Planted defect | Code | Sev |
|---|---|---|---|---|
| 1 | `sklearn_baseline.py` | `StandardScaler().fit_transform(X)` on the full `X` **before** `train_test_split` | MLV101 | high |
| 2 | `train.py` | Batch loop with `loss.backward()` and `optimizer.step()` but no `optimizer.zero_grad()` | MLV201 | high |
| 3 | `train.py` | `validate()` runs the model with no `model.eval()` (Dropout **and** BatchNorm) | MLV301 | high |
| 4 | `model.py` | `forward` returns `F.softmax(x, dim=1)` while `train.py` uses `nn.CrossEntropyLoss` | MLV401 | high |
| 5 | `model.py` | `self.blocks = [ConvBlock(...) for _ in range(4)]` — a plain list, not `nn.ModuleList` | MLV702 | high |
| 6 | `sklearn_baseline.py` | Bare estimator passed to `cross_val_score` after external scaling | MLV103 | medium |
| 7 | `data.py` | `DataLoader(train_ds, ...)` with no `shuffle=True` and no sampler | MLV110 | medium |
| 8 | `data.py` | `DataLoader(..., num_workers=4)` at module scope with no `__main__` guard | MLV112 | medium |
| 9 | `train.py` | `running_loss += loss` — no `.item()`, accumulator outside the loop | MLV205 | medium |
| 10 | `train.py` | `validate()` not wrapped in `torch.no_grad()` | MLV302 | medium |
| 11 | `train.py` | `model.to(device)` but batches are never moved | MLV501 | medium |
| 12 | `data.py` | `DataLoader(test_ds, shuffle=True)` | MLV111 | low |
| 13 | `config.py` | No seed anywhere in the workspace | MLV601 | low |
| 14 | `sklearn_baseline.py` | `train_test_split(...)` with no `random_state` | MLV602 | low |
| 15 | `data.py` | `random_split(ds, [45000, 5000])` with no `generator` | MLV602 | low |

The five cards §5.3 A7–A8 added to it, none of which changed a finding:

| Line | Card |
|---|---|
| `train.py:20` | `model = SmallCNN()` — `model`, Model lane |
| `train.py:30` | `logits = model(images)` — `predict`, Train lane (inherited) |
| `train.py:31` | `loss = criterion(logits, labels)` — `loss`, Train lane (inherited) |
| `train.py:45` | `logits = model(images)` — `predict`, Evaluate lane (inherited) |
| `model.py:34` | `self.blocks = [ConvBlock(w, w) …]` — `layer`, Model lane |

**The demo is 59 nodes and 51 edges** (§17 E1, E25). **The canonical count is whatever `python -m mlview analyze samples/vision_pipeline --format summary` prints**, and `tools/verify.py --all` reports the same pair; a figure in prose is a record of a measurement, never the authority for one. `scripts/check_docs.py` check 8 holds every *living* document to one graph size; `docs/CONTRACTS.md` is in its `SKIP` set so a dated figure in an archived amendment is not forced to be rewritten.

The demo shows, on one screen: **all three marker shapes**; **two ghost nodes** (`zero_grad()` in the batch loop, `model.eval()` at the head of the eval loop); **one multi-location leakage connector** (MLV101, `fit_transform` → `train_test_split`); and **one edge-borne marker** (MLV401, on the `logits → loss` edge that now carries the `model → loss` connection — §14.2 R21). It publishes **five** structured fixes and **withholds the sixth**, and says so in the summary. **`samples/vision_pipeline_clean/`** is the *same five files*, same structure, same node/edge shape, every defect corrected, expected **0** findings (70 nodes / 56 edges in `ip`, 70 / 55 in `local`) — shown side by side, this is what earns belief that the findings mean something. It is owned by the rules agent, not the hosts agent, because the planted issues must track real rule behaviour.

### 14.2 The rule catalogue and the precision corpora

The registry holds **36 rules** and every host reads the **enumeration**, never a count: `mlview rules --list`, `docs/rules/README.md` and `gen_rule_docs.py` all enumerate it. A rule that cannot be made reliable is registered `enabled=False` with the reason on its doc page. **`tests/fixtures/rules/`** holds `<CODE>_bad.py` / `<CODE>_good.py`, 10–40 lines, imports only; bad fixtures are **self-describing** (`# MLVIEW-EXPECT: MLV201 line=18 confidence>=0.6`) and good fixtures encode the **nearest false-positive trap**, not merely correct code. **`tests/clean/`** is the precision gate — `vanilla_torch.py`, `amp_accumulation.py`, `lightning_module.py`, `hf_trainer.py`, `sklearn_pipeline.py`, `timeseries_split.py` — and `test_precision.py` asserts **0 high and ≤ 2 medium**, each file alone **and** all of them together, in **both** dataflow modes. Other fixtures: `multifile/`, `dynamic/`, `malformed/`, `notebooks/`, `frameworks/`, `oddsyntax/`, `dataflow/`, `config_values/`, `config/`, `fixes/`, `pkgreexport/`, `synthetic/`.

| # | Rule-level clauses that are normative |
|---|---|
| **F1** | **Knowledge entries are data, and the tables are the contract.** A row is an `entries.E`, and a *family* on a row is what carries a chain: `ir/resolve._FAMILY_BASE` maps each family to the base FQN its chain resolves against. A family may **alias** another — `keras_dataset` is `tf_dataset`, because `keras.utils.image_dataset_from_directory` really does return a `tf.data.Dataset`. Adding a framework means adding rows and, where a chain is needed, a family; it never means a branch in the resolver (F16). |
| **A1** | **A rule whose subject is the wrapper is not an absence rule.** Iron law 4's `WRAPPER_FACTOR` is correct for MLV201 / MLV202 / MLV301 / MLV601 and **wrong** for MLV705–711, whose finding is *about* the framework. None of those six declares `absence=True` and none passes `wrapper_gated`; every framework-tier finding clears 0.6 on its own fixture. |
| **A2** | **Every ordering predicate is evaluated over one block of one confirmed loop.** The IR is flow-insensitive: MLV208 and MLV209 compare `stmt_index` **only** between calls sharing a `block_id` inside a confirmed `ctx.loops("batch")`. Calls spanning two functions, or two branches of an `if`, are never compared. |
| **A3** | A non-literal `GradScaler(enabled=...)` **de-rates (0.6), it never suppresses**; `enabled=False` suppresses outright; a literal `True` or a bare constructor is full strength. |
| **A4** | MLV305's score-metric carve-out is **exhaustive and checked first**: `_SCORE_METRICS` is frozen, `_CLASS_METRICS` is a separate frozen set **disjoint** from it, and a metric on neither list is **not judged at all**. |
| **A5** | MLV106 requires **≥ 2 independent temporal signals in the same module** (weight 0.8 at exactly two, 1.0 above), and treats an explicit `shuffle=False` as the chronological cut it is. |
| **A6** | MLV114 judges a **direct** transform → dataset → evaluation-loader chain and nothing else. An augmented dataset later `random_split` into halves is **not** judged. |
| **A7/R2** | MLV121 requires **a holdout to exist before it describes one**: the same shuffled receiver reaching **both** a `take()` and a `skip()`, or a subset finally bound to a name matching `_EVAL_NAME_RE`, walked forward through the chain. `shard` is never on its own evidence. At most **8** chain links, and only through bindings that resolve. |
| **A8/R1** | MLV709 **pairs one model, not one module**: `compile()` → the `keras.Model(inputs, outputs)` / `Sequential([...])` its receiver resolves to (through at most one workspace builder) → the layer behind that model's `outputs=`. The layer and the loss must meet on **the same model** and the layer must be the model's **output**. Where the walk resolves to nothing the rule stays silent rather than pairing by activation family alone; the finding gains a third `relatedLoc`, role `definition`. |
| **A9** | MLV705 is a **workspace-wide** claim: it fires only when the workspace contains **no** `keras.Model.compile` at all and no `keras.models.load_model`. One `compile()` anywhere silences it. |
| **A10** | MLV708 fires on the **conjunction**: no `eval_dataset` **and** a resolved `TrainingArguments` that sets neither `eval_strategy` nor `evaluation_strategy` to a non-`"no"` constant. A `Trainer` whose `args=` cannot be resolved is **not judged** — unresolvable is not absent. |
| **A11** | MLV502 reads the device literal **written at the call site**, additionally requires that nothing in the workspace probes `torch.cuda.is_available()` / `device_count`, and reports **one finding per module** anchored at the first site with the others as `call_site` related locations. |
| **A12** | MLV602 no longer asks a non-shuffling split for a `random_state`: `_ALWAYS_RANDOM` splitters whose `shuffle` kwarg is the literal `False` are skipped. `datasets.Dataset.train_test_split` is in `_ALWAYS_RANDOM` under the keyword `seed`. |
| **A14** | A generated rule page may state **`## What it cannot analyze`**, rendered from a `cannot` key; a page with no such key is byte-identical to what it was. |
| **F2** | `take` / `skip` carry the role `TFDATA_SUBSET`, **not `SPLIT`**; that guard may not be relaxed. |
| **F3** | `batch` / `prefetch` carry the LOADER **tag** and not the `LOADER` **role**, because the coverage sweep reads argument 0 of every `LOADER` site. |
| **F4** | `knowledge.MODEL_BASES` is `torch.nn.Module` plus the three `LightningModule` roots, and `ClassIR.is_model_module` is the question the graph asks. **`ClassIR.is_nn_module` keeps its exact torch meaning**, because it also gates whether `torch.nn.Module.<method>` may be proposed. |
| **F5** | A framework hook is a **unit**, and its lane is **declared, not voted on** (`HOOK_STAGES`); the class node is then promoted to `level: "stage"`. |
| **F7** | `Trainer.fit` / `.validate` / `.test` draw a `control` edge (`subkind: "enter"`) into the hooks they actually run, found through the **binding** behind the model / datamodule argument. `fit` does not enter `test_step`. `MAX_CONTROL_EDGES` caps one call at **12** targets. |
| **F8** | `configure_optimizers()` returns an OPTIMIZER **by contract**: the hook's contract *is* its return type. |
| **F9** | **Recognised is not the same as drawn.** `LIGHTNING_LOG`, `LIGHTNING_HPARAMS`, `LIGHTNING_CTL`, `MODEL_SUMMARY`, `TFDATA_CARD` and every `LIGHTNING_HOOK_*` role are absent from `knowledge.OP_ROLES`, so nothing is fabricated for those methods and nothing is drawn for them. `manual_backward` **is** drawn. |
| **F15** | **A framework hook body is not an eval region**: MLV301 / MLV302 do not fire inside `validation_step`. A narrowing of two rules, stated as one. |
| **F16** | **A new framework is a table row.** `knowledge/pandas_tbl.py` and `knowledge/stats_tbl.py` add nine roles — `FRAME_TEMPORAL`, `FRAME_RESHAPE`, `FRAME_WRITE` (pandas beyond the shape-preserving hop), `TS_MODEL`, `TS_FIT`, `HF_METRIC`, `METRIC_UPDATE` (statsmodels / Prophet / HuggingFace `evaluate` / torchmetrics) and `KERAS_EXPORT` (`keras.Model.export`), plus `WRAP_PREPARE` (§5.3 A11 e) in `knowledge/other_tbl.py` — and six receiver families (`statsmodel`, `prophet`, `hf_metric`, `torchmetric`, `accelerator`, `fabric`), each **contributed by the table that defines it** rather than hard-coded in the resolver. **Every one of the nine is in `K.OP_ROLES` and no rule keys on any of them**: the tables add sight, not verdicts. |
| **F17** | **`FRAME_TEMPORAL` is deliberately not spelled `TEMPORAL`.** `rules/holdout_splits._temporal_signals` already recognises `shift(…)` and `rolling(…)` **by method name**; reusing the `TEMPORAL` role would make it print `pandas.to_datetime at line 20` for a `shift` — a true signal reported with a false sentence. |
| **F18** | `FRAME_TEMPORAL` and `FRAME_RESHAPE` carry the receiver's data tags in the same branch as `FRAME_OP` (`ir/bindings_tags.call_output_tags`): a lag column is still the same feature matrix, so the tags `read_csv` seeded travel exactly as far as they did, and both keep the `frame` receiver family so `frame[col].shift(1).rolling(24).mean()` stays **one chain**. The closing aggregations (`mean`, `sum`, `std`, …) stay transparent `FRAME_OP` — the box belongs to the window, not to the `.mean()`. |
| **F19** | **Indexers are stripped.** `ir/resolve._frame_base` strips a known pandas accessor (`loc`, `iloc`, `at`, `iat`, `values`, `T`, `str`, `dt`, `cat`) when a chained receiver looks for the frame behind a subscript, because `dotted_text` answers `frame.loc` — a name nothing binds — and `X = df.loc[:, cols].to_numpy()` stopped the frame's tags dead one line before every leakage rule needed them. |
| **F20** | **The `Framework` enum (§2.2) is frozen and a table may not widen it.** statsmodels and Prophet are not members, so their rows say `other`. |
| **F21** | **`torch.load` is deliberately not typed as a model**: it returns a state dict as often as a model, and typing its result MODEL would be a guess. `from_pretrained`, `keras.models.load_model` and the workspace factories (§5.3 A9) are typed because their rows or their returns say so. |
| **R13** | **MLV101, through a `return` (`ip` only).** When no `SPLIT` is written in the fit's own scope, the rule may follow the fitted value out through the function's `return`: a split in the **caller** whose argument binding's producer **is the very call to the fit's function**, at a returned tuple position the fitted value feeds, is the same leak with a `def` in the middle. **No name is matched across scopes** — §3.11 N6 stands — because the binding's own producer carries the identity. One `return` hop is paid. The returned expression is read in **three equivalent forms** (R15 reads the same three): a **name** (`return matrix`), a **tuple position** (`return matrix, y`) and a **bare call** (`return scaler.fit_transform(frame)`). `ir.symbols.dotted_text` answers for a call with its *callee*, which names no value, so a returned call is resolved through `module._calls_by_node` and stands for the names it is written on — its arguments, its receiver and its bound variable. One level, literal, no deeper; a call the IR never recorded contributes nothing. Until 2026-09-15 only the name form was read, so `return scaler.fit_transform(frame)` missed where `matrix = scaler.fit_transform(frame); return matrix` hit — the same program one refactoring apart, and the missed spelling is the commoner one. |
| **R14** | **MLV102, through a fold index (`ip` only).** The fitted argument may be `X[test_idx]` where `test_idx` is the **second** name unpacked from the header of a `fold` loop over a `SPLIT`-role `splitter.split(…)`. Position 1 of that tuple is the held-out half **by the scikit-learn cross-validator protocol** — a fact about the library, not an inference from the name. One `projection` hop is paid. |
| **R15** | **MLV103, through a callee (`ip` only).** The `fit_transform` may be one `def` away: resolve the CV's `X` to the workspace call that produced it, read the callee's `return` at the tuple position the caller unpacked, and a non-stateless `fit_transform` whose output reaches that position is the fit every fold now shares. One `return` hop is paid. |
| **R16** | **MLV103 defers to MLV101 only in the same file.** *"One root cause never yields two findings"* now reads *"… at the same line **of the same file**"*. With the fit a module away, a reader of the training script who is silenced by an MLV101 in `features.py` has been told nothing about the folds, which is the only thing MLV103 exists to say. |
| **R17** | **MLV111, the split dictionary.** The loader's dataset argument may be `d["test"]` / `d["val"]` — the HuggingFace `DatasetDict` spelling — when the subscript base is a value already traced to data and the key is a literal naming the held-out half. **Both halves are required.** It is **name evidence (0.8)**, never dataflow evidence. |
| **R18** | **MLV205, two corrections.** (a) *"Created outside the loop"* means outside the **accumulating** loop, not outside the outermost loop in sight: an accumulator reset once per epoch and added to once per batch holds a whole epoch of autograd graphs, and the old test exempted precisely that shape. (b) The `LOSS` tag is read through **one** arithmetic step, because `loss = criterion(…) / ACCUM_STEPS` is how gradient accumulation is written and a division does not take a tensor off the graph; a value already off the graph (`.item()`, `.detach()`, `float()`) stops the read. The deliberate `total_loss.backward()` guard matches on the **method name** as well as on the resolved FQN, because an accumulator bound to a `BinOp` carries no `LOSS` tag and so never resolved `torch.Tensor.backward` — and a guard may only ever *silence* this rule, so reading it by name is safe in the direction that matters. (c) MLV205 is silent, **and may only be silenced**, when any of three statements about the program holds — each a statement, not a de-rating. **No graph**: the accumulating loop is inside `torch.no_grad()` / `inference_mode()`, or its function carries that decorator. **The accumulator is the live value**: the accumulated name, or a name assigned directly from an expression mentioning it (one level), is the receiver of a `backward()`, or is what the enclosing function `return`s — and the `return` arm is **refused** when the *collected* tensor is itself back-propagated in that scope, because `losses.append(loss)` after `loss.backward()` is a record of the epoch rather than the objective, and returning it is the defect the rule exists for. **Already detached**: every write to the accumulated operand in that scope goes through `.item()` / `.detach()` / `float()` (its numeric or empty initialiser is not a write), so the value is a Python scalar carrying an inherited `LOSS` tag rather than a live tensor. |
| **R19** | **The four value-typed rules** (§5.3 A13). MLV305 types its prediction argument through a helper `return` and a `.detach().cpu().numpy()` tail; MLV306 accepts an `ARGMAX`-role producer, not only `PREDICT`; MLV401 and MLV402 follow a helper's `return` for the softmax / sigmoid **and** test the model class with **`is_model_module`**, so a `LightningModule` counts (F4 is unchanged — `is_nn_module` keeps its exact torch meaning). For MLV401 / MLV402 the helper path is tried **after** the model class, never before it: a model's `forward` is a workspace function too, and pre-empting the class path costs the finding its model class, its `model → loss` edge and its `definition` related location — the three things that make it navigable — and charges it a hop it never took. Each path ships with its **nearest** negative fixture. |
| **R20** | **MLV401 and MLV402 emit one finding per root cause.** The key is the offending op plus the model class it lives in (plus the variant, for MLV402) and the survivor is the first loss site in source order: **a model applied from both `training_step` and `validation_step` is one defect**, not two. |
| **R21** | **The `model → loss` marker falls back to the producer edge.** With the forward pass drawn as a card of its own (§5.3 A8) the connection is two hops — `SmallCNN → logits → loss` — so `ctx.edge_between(<the model's class unit>, loss_node, "data")` finds nothing. MLV401 / MLV402 then mark the edge `ctx.builder._producer_node(ref)` yields, which is `logits → loss`. **The anchor nodes do not move**: `nodeIds` still names the loss node, the model class and the offending op, in that order. A graph with no forward-pass card keeps exactly the edge it always had, and §14.1's *"one edge-borne marker"* is **met**. |

### 14.3 The accuracy corpus and the referee

`tools/accuracy.py` is the referee; `analyzer/tests/accuracy/baseline.json` and `baseline.ip.json` are the ratchets, with the same two tolerances: **zero `forbidden` findings ever, and recall may only ratchet up**.

| # | Rule |
|---|---|
| **A13** | A program written alongside the rules that find its defects is marked **`tuned: true`** and does not inflate the unseen headline. A program carrying no hand-drawn `graph` block is added for its findings only; claiming a diagram for it would move the graph-fidelity ratchet on evidence nobody drew. |
| **R9** | **Graph fidelity for a program with no `graph` block is `null`, rendered `not labelled`** — never `1.0`. The gated aggregate is untouched: 0/0 contributed nothing before and contributes nothing now. |
| **R10** | **A rule whose every label lives in a tuned program is marked, and its unseen recall is stated.** `perRule` carries `unseenExpected`, `unseenRecovered` and `unseenRecall` (`null` when nothing unseen is labelled), and the per-rule table carries an `unseen recall` column with the same `*` footnote. |
| **Relabels** | A label re-coded to a rule that can actually see the defect records the change in a `relabelled` field. |
| **R23** | **A test region is not an evaluation region.** `_EVAL_NAME_RE` reads `test…` as an evaluation entrypoint, which made an ordinary pytest module an evaluation loop and put a `high` MLV301 on an assertion about a tensor shape. A test region is therefore **removed before MLV301 and MLV302 see it**, exactly as a framework hook is: it is not evaluation, so there is nothing to de-rate. **Both halves must hold.** The *module* is a test suite — its path matches `test_*.py` / `*_test.py`, or a directory component is `tests` / `test` / `testing`, or it imports `pytest` / `unittest` / `nose` / `absl.testing`. The *region* is test-shaped — the function (or an enclosing function) is named `test…`, or the body's conclusions are assertions (`assert`, `torch.testing.assert_*`, `np.testing.assert_*`, `self.assert*`). A guard may only silence, so a shape it misses costs a false negative and never a false positive. |
| **R22** | **A hand-drawn `graph` block records who drew it**, in `graph.drawnBy`. A block added after the programs it sits beside were labelled says so there, and `tools/accuracy.py` anchors a hand-drawn op on `(file, line)` **exactly** — a card on the right file and the wrong line is a miss, on purpose, because a containment test would score an op as recovered merely because the function that should have contained it exists. |

### 14.4 The sample gallery

`analyzer/tools/gen_gallery.py` is the generator; `analyzer/tests/core/test_gallery.py` is its gate.

| # | Rule |
|---|---|
| **G1** | **On demand, and never committed.** The generator renders **every** clean program and **every** bad/good rule fixture, plus an index, into `docs/gallery/`. **Zero new content**: every page is an existing fixture analyzed through exactly the pipeline a user's own code goes through. ~90 pages at ~30 MB, so `docs/gallery/` is in `.gitignore` and nothing from it is committed — a build target that wrote 30 MB on every build would be the wrong trade, so this is run by hand before a release, a demo, or a move in the rule catalogue. |
| **G2** | **The index states what the gallery could not analyze**, which is §1's standing criterion applied to a user-facing artifact. Every page is a **single-file** analysis, so the cross-file rules (MLV301, MLV302, MLV401, MLV501) may structurally be unable to fire, and the index says so rather than letting a short list read as a clean bill of health. The index **measures that blind spot off the run** rather than asserting it from a constant, and states what it measured (§17 E27). A `_bad.py` that reports **0**, and a `_good.py` that reports the rule it is the negative control for, are each **flagged in the index** — the second is a false positive, and one high-severity false positive costs more trust than ten misses. |

## 15. Repository layout, ownership, packaging and the sync gates

### 15.1 Directory ownership

| Directory | Contents |
|---|---|
| `contracts/` | the schema, `graph.sample.json`, `scope.cases.json`, `scope.expected.json`, `validate_sample.py`. **Read-only once written.** |
| `analyzer/src/mlview/` | `{__main__,cli,cli_parser,cli_commands,version,api}.py`, `ingest/`, `ir/`, `core/`, `rules/`, `adopt/`, `emit/`, `knowledge/`, `schema/` |
| `analyzer/tests/` | `core/`, `rules/`, `fixtures/`, `clean/`, `golden/`, `accuracy/` |
| `webview/` | the viewer: layout, render, markers, states, tokens, interactions, a11y, `scope/`, `diff/`, `export/`, `rollup/`, its tests, `dev/index.html`, `dev/states.html` |
| `vscode-extension/` | the extension: commands, panel, diagnostics, interpreter chain, reveal, chat, LM tools, protocol, fixes, compare, folders, its tests. **`vscode-extension/core/mlview` is a build artifact**: gitignored, and `git ls-files vscode-extension/core` MUST be empty (§15.3 P1). |
| `claude-plugin/` | `plugin.json`, `.mcp.json`, `commands/`, `skills/`, `hooks/`, `server/`, `vendor/` |
| `samples/`, `tools/`, `scripts/`, `.claude-plugin/marketplace.json`, `README.md` | samples, sync/verify/bench tooling, build/e2e scripts, the marketplace manifest |
| `docs/` | the design and status documents; `docs/rules/MLVxxx.md` is **generated output, never hand-edited**; `docs/archive/` holds superseded specs |

**Rules of engagement.** No agent writes into another agent's directory. `tools/sync-assets.py` is the only thing that writes `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`; `tools/sync-core.py` is the only thing that writes a vendored analyzer copy. **A contract change is requested, never made unilaterally.** **No source file may exceed ~600 lines**; the splits that keep `panel.ts`, `extension.ts`, `cli.py` and `core/build.py` under it are extractions with **no behaviour change**.

### 15.2 Files that must change together

| Group | Files |
|---|---|
| Schema | `contracts/graph.schema.json` **and** `analyzer/src/mlview/schema/graph.schema.json`, byte-identical |
| `present` consumers | `contracts/validate_sample.py`, `analyzer/tests/core/test_graph_invariants.py`, `webview/src/layout/model.ts` |
| One projection | `analyzer/src/mlview/core/project.py` **and** `webview/src/scope/project.ts` |
| One pipeline relation | `analyzer/src/mlview/core/pipelines.py` **and** its TypeScript port |
| One fuzz digest | `digest_of` in `analyzer/tools/gen_scope_fixtures.py` **and** `digestOf` in `webview/test/scope_fuzz.test.mjs` |
| Grammar and its promise | `claude-plugin/server/mlview_payloads.py` **and** `mlview_mcp.py`'s `mlview_graph` docstring **and** the three LM-tool descriptions in `vscode-extension/package.json` |
| Diagnostic enum | the two schema copies, `webview/src/types.ts`, `webview/src/ui/chrome.ts`, `claude-plugin/server/mlview_notes.py` |
| Manifest surface | `vscode-extension/package.json`, `vscode-extension/README.md`, `vscode-extension/test/manifest.test.js` |
| Walkthrough | `docs/walkthrough/*.md` and `vscode-extension/docs/walkthrough/*.md`, through `tools/sync-walkthrough.mjs` |
| Hooks | `claude-plugin/hooks/hooks.json`, `hook_core.py`, `post_edit.py`, `stop_summary.py`, `claude-plugin/README.md` |
| Graph-shape changes | `vscode-extension/test/fixtures/vision_pipeline.graph.json` (a real analyzer run) in the **same** commit. `contracts/graph.sample.json` is **not** regenerated by anything, ever. |
| Assets | `webview/dist/*` → `vscode-extension/media/`, `analyzer/src/mlview/emit/assets/` — **the integrator alone** runs `tools/sync-assets.py`, once per review round; every viewer change moves `generator.rendererSha` |
| Vendored cores | `tools/sync-core.py` re-vendors into `claude-plugin/vendor/mlview` in the **same** change as any analyzer edit, and into `vscode-extension/core/mlview` **at build time** (§15.3 P1). `tools/verify.py --all` still reads both rows, and a stale built copy still fails. |
| Licence | `LICENSE` at the repository root and `vscode-extension/LICENSE`, byte-identical — MIT, `Copyright (c) 2026 realmyang`, the licence `vscode-extension/package.json` and `claude-plugin/.claude-plugin/plugin.json` already declare. It ships in the VSIX as `extension/LICENSE.txt`. |

### 15.3 Packaging and the precedence chain

| # | Rule |
|---|---|
| **P1** | **One tracked analyzer, plus one tracked vendor copy — and one built one.** `analyzer/src/mlview` is the analyzer. `claude-plugin/vendor/mlview` **stays tracked**, because `claude plugin install` copies the plugin directory verbatim off a git ref, so for that host *what git holds is what the user runs*; it is temporary, and goes when the `mlview` wheel is published and `.mcp.json` can depend on it. `vscode-extension/core/mlview` **need not be tracked**: the VSIX is a build artifact `vsce package` produces from a working tree, the copy only has to exist at package time, and it is therefore **gitignored** with `git ls-files vscode-extension/core` empty. `tools/sync-core.py` is still its only writer and still writes it byte-exactly under the same skip rules (`__pycache__`, `*.pyc`, `*.pyo`, `*.pyd`, `.mlview`, any `tests` directory). |
| **P1.1** | **Every path that tests or packages the extension builds it first.** `vscode-extension/tools/sync-core.mjs` runs `tools/sync-core.py` with the first Python 3.10+ it finds (`MLVIEW_PYTHON` overrides the search; **no interpreter is a hard failure, never a silent skip**) and is the first command of `npm run compile`, of `pretest` and of `vscode:prepublish` — which `vsce package` and `vsce publish` both run, so a hand-built package is covered too. `scripts/build.{sh,ps1}` keep their own step 3, which is what puts the copy on disk for a fresh clone. |
| **P1.2** | **The two gates split along that line.** `tools/verify.py --vsix` is **strict** and unchanged in meaning — the directory must EXIST, be byte-identical to `analyzer/src/mlview`, and not be excluded from the package by `.vscodeignore` (a VSIX that ships without its analyzer is green in every other gate and broken on install) — and it runs after a build. `tools/sync-core.py --check`, which also runs on fresh clones, holds every **tracked** copy to the source unconditionally and reports an **unbuilt** generated copy as "not built" rather than as drift: absence there is a build that has not run, not a divergence. **Neither gate may be satisfied by a copy that was not produced from the current `analyzer/src/mlview`.** |
| **P1.3** | **The package is proved by running it**, because the bundled analyzer is no longer in the index for a reviewer to read. `vscode-extension/tools/vsix_smoke.py` unzips the built VSIX, puts `extension/core` on `PYTHONPATH` exactly as `bundledCore.ts` does, and from a working directory **outside the repository** imports `mlview` — asserting the module resolved *inside the unzipped package*, so an installed copy cannot answer for it — checks its version against `vscode-extension/package.json`, emits `analyze --demo --json -` and compares it **byte for byte** with `contracts/graph.sample.json`, and analyzes a real source file. A VSIX whose `core/` is missing, stale or unrunnable fails there. |
| **P2** | **The precedence chain, stated once** (`vscode-extension/src/bundledCore.ts`, pure): (1) the **installed** core when it is present, `schemaMajor(installed) == schemaMajor(extension)` and `compareVersions(installed, bundled) >= 0`; (2) the **bundled** core; (3) neither — the install prompt. `compareVersions` is numeric per dotted component and sorts any pre-release suffix **below** the same release. |
| **P3** | The bundled core runs through **`PYTHONPATH`, never through a copied interpreter**: `CoreClient` *prepends* the bundled path and sets `PYTHONDONTWRITEBYTECODE=1`. Nothing else about the spawn changes. |
| **P4** | **A schema-major mismatch is not fatal** when a bundled core is present: the extension uses the copy it shipped and reports a **warning**. With no bundled core the old fatal path is unchanged. |
| **P5** | **The host says which core answered.** `pythonEnv.coreDescription()` returns one line, carried in the status-bar tooltip under the issue counts. |
| **P6** | `installCore()` offers the **published wheel** — `python -m pip install --upgrade mlview`, on the interpreter MLView actually resolved — never a checkout path. |
| **P7** | The manifest is publishable: no `private`, with `repository` (+`directory`), `bugs`, `homepage`, `icon` (128×128), `galleryBanner`, `preview: true` and `extensionKind`. `npm run package` succeeds with **no `--allow-missing-repository`**, and the VSIX stays **under 1 MB**. |
| **P8** | **The icon is source, not a binary somebody once drew.** `vscode-extension/tools/make_icon.py` renders `media/icon.png` using only `zlib` and `struct`, and its `--check` mode re-renders into memory and byte-compares. |
| **P9** | **The wheel is built and proved, every run.** `scripts/build.{sh,ps1}` step 6/6 builds it into `analyzer/dist` (gitignored) and **skips with a message** when `build` is absent. `tools/wheel_check.py` is the acceptance: a fresh venv, `pip install`, `mlview --version --json` through the **console script**, then one real analysis on a planted leak — because a wheel missing `schema/*.json` or `emit/assets/*` installs perfectly and fails on first use. |
| **P10** | The plugin's marketplace manifest carries both a local and a hosted source (§13.1). |

### 15.4 The three parity gates

1. **One analyzer** — `tools/verify.py`: the CLI graph vs the MCP `tools/call` graph, **byte-identical**
   after stripping `generatedAt` and `durationMs`.
2. **One renderer** — SHA-256 equal across `webview/dist/`, `vscode-extension/media/`,
   `analyzer/.../emit/assets/`, and equal to `generator.rendererSha` in every emitted document.
3. **One version** — `tools/verify.py --versions`: `mlview.version.__version__`,
   `analyzer/pyproject.toml`, `vscode-extension/package.json`, `claude-plugin/.claude-plugin/plugin.json`
   and `webview/package.json` all carry the same version.

---

## 16. Acceptance gates

### 16.1 Analyzer

`analyzer/tests/core/` — symbols, bindings, scopes, stages, the §2.7 invariants, determinism, locations (`loc.symbol` inside `[line..endLine]`, re-sliced over notebooks too), id stability, schema (both mirrors byte-identical; `python -m mlview schema` equals the contracts copy; `--demo` byte-equals the golden; `view` / `viewRole` / `fix` / `rolledUp` / `weight` / `pipelines` absent from every `required` array), stdout purity, offline HTML (no `http://`, `https://`, `//cdn`, `@import`, external `<link>` / `<script src>`; the size band), robustness (syntax error, empty file, non-UTF-8, no `.py` → exit 4), the exit-code table, `--json -`, and one focused module per feature: `test_coverage`, `test_ir_converge`, `test_cleanup`, `test_class_method_ops`, `test_pkg_reexport`, `test_ci_adopt`, `test_sarif`, `test_answers`, `test_framework_recognition`, `test_unresolved_callee`, `test_relevance`, `test_cache`, `test_perf_budget`, `test_notebooks`, `test_progress`, `test_dataflow_ip`, `test_config`, `test_config_values`, `test_diff`, `test_relevance_default`, `test_rollup`, `test_pipelines`, `test_review_fixes`, `test_gallery`, `test_fuzz_shapes`, `test_no_exec`, `test_project_parse`, `test_project_resolve`, `test_project`.

`analyzer/tests/rules/` — per-rule bad/good fixtures with `# MLVIEW-EXPECT:` headers; `test_no_cross_fire` (the union of all good fixtures → 0 issues, alone and as one workspace); `test_precision` (§14.2, in both dataflow modes); `test_registry_complete`; `test_suppression`; `test_confidence`; `test_samples`; and `test_fixes.py`, whose acceptance is one parametrized case per opted-in rule: **apply every edit to the bad fixture, `ast.parse` the result, re-analyse it as a workspace, and assert the rule stops firing and that the code set gains nothing new**.

### 16.2 The scope parity and fuzz gates

`contracts/scope.cases.json` is computed over the **frozen** `contracts/graph.sample.json`, so the gate cannot churn when a rule changes: **13 projecting cases and 7 error cases**, plus a `fuzzCases` array of **5 promoted counterexamples** carrying their graphs inline. `contracts/scope.expected.json` is generated by `analyzer/tools/gen_scope_fixtures.py`, whose `--check` regenerates and byte-diffs without writing. `webview/test/scope_parity.test.mjs` runs `MLView.__internal.scope.project` on each case and **deep-compares**: the `nodes` id list **in order**, the `edges` id list in order, the `issues` id list in order, every `issue.nodeIds` in order (so the rotation is checked), every node's `viewRole`, all eight stage rows, `stats`, and the **whole** `view` object; error cases assert `(code, term, candidates)` only.

| # | The differential fuzzer (`analyzer/tools/scope_fuzz.py`) |
|---|---|
| **G1** | Documents are generated from a **seed** — node counts 5–500, hierarchy depth, cross-stage parents, ghost density, orphan density, issue arity 1–4, issues anchored on an edge whose nodes sit elsewhere, 1–3 disconnected components, and the rollup and pipeline shapes. The same seed reproduces the same run byte for byte, so a failure is replayable from its printed seed. |
| **G2** | Every generated document is checked by `contracts/validate_sample.py` — schema **and** all ten invariant groups — **before** it is projected. A document that does not validate **fails the run as a generator bug**: the harness must never compare two projections of garbage. |
| **G3** | Selectors are drawn across **every** kind at every legal depth, plus the rejected forms, so `ScopeError` parity is fuzzed on its contractual triple and never on its prose. |
| **G4** | The comparison is the **digest** (§15.2); `diagnostics` is deliberately excluded because step 10's wording is free. |
| **G5** | Every counterexample is **promoted, not merely reported**: `--promote` minimizes it by delta debugging and appends it to `fuzzCases`. **The fixture battery grows; the fuzzer never replaces it.** |
| **G6** | `cases` is untouched by G5, so the parity gate keeps its exact shape. |
| **G7** | The gate is `python tools/verify.py --scopes --fuzz N`, adding two rows (`scopes: promoted`, `scopes: fuzz`): **200 locally**, **2000 nightly**. `--fuzz` is inert unless asked for. |
| **G8** | The fuzzer must be **proved to bite** whenever its comparison changes: build the viewer from a copy of `webview/src` with one line removed and aim `MLVIEW_FUZZ_BUNDLE` at it. **Never edit the repository to test the tester.** |

### 16.3 Viewer, extension and plugin

`webview/test/` — layout (deterministic; no sibling bbox overlap; every node inside its lane; < 300 ms for 150 nodes), bundle hygiene (no `innerHTML`, `eval(`, dynamic `import(`, `getTotalLength`, `http(s)` literals, filter primitives; the JS/CSS size ratchet with a 2 KB tolerance and a written justification per move), parity through both bridges in jsdom, markers, contrast (each declared token pair ≥ 4.5:1 in light and dark), plus `flow`, `charge`, `bridges`, `labels`, `a11y`, `adopt`, `export`, `notebook`, `bundles`, `diff`, `fixes`, `configres`, `rollup`, `pipelines`, `scope_parity` and `scope_fuzz`. **The reduced-motion gate stubs `matchMedia` BEFORE `MLView.mount`**, with a full stub (the theme module calls `addEventListener` on the result), and the **positive** case is asserted separately with `matches: false`, so "no flow because reduced motion" and "no flow because it is broken" cannot be confused. **The composition gate**: apply a scope, relayout, hover an edge inside it and assert the flow renders; hover a node whose lineage crosses the boundary and assert core-to-core edges take `.is-flowing` while boundary-touching edges take `.is-lit` and not `.is-flowing`; clear the scope and assert no flow element or `--mlv-flow-*` property survives. `render_report.mjs` and `export_svg.mjs` re-check the shipped report outside the unit suite.

`vscode-extension/test/` — `tsc --noEmit` clean; protocol round-trip and unknown-type tolerance; `loc → Range`; the workspace-containment guard; digest ≤ 4 KB; the CSP builder; interpreter-resolution order; the diagnostic severity mapping; `manifest` (the exact command and settings sets); `activation`; `scope`; `suppression`; `packaging`; `export`; `notebooks`; `multiroot`; `config`; `fixes`; `compare`; `lmtool` (including the MCP-parity containment); `hygiene` (the ~600-line budget).

**The two line budgets, and where they disagree.** The campaign quality bar is *files under 600 lines*; C3's split threshold — the one the consolidation wave actually applied, and applied to **source**, never to test files — is **750**. Measured 2026-09-15 over tracked `.py` / `.ts` / `.js` / `.mjs` outside the vendored and built copies (`git ls-files … | xargs wc -l | sort -rn`): **no tracked source file exceeds 750**, and eleven sit between the two budgets — `webview/src/bridges.ts` 724 (D8/D9 grew it), `webview/src/types.ts` 718, `tools/verify.py` 709, `claude-plugin/server/mlview_mcp.py` 665, `webview/src/export/svg.ts` 626, `claude-plugin/server/mlview_payloads.py` 623, `webview/src/layout/labels.ts` 618, `webview/src/scope/project.ts` 614, `scripts/check_docs.py` 607, `webview/src/render/flow.ts` 605 and `webview/src/ui/issuelist.ts` 601. That is a **stated exemption**, not an oversight: each is under the threshold the wave split on, and splitting a file to meet a budget it was never measured against buys a module boundary nobody asked for. **Test files are outside both budgets by construction** — `vscode-extension/test/host.test.js` is 1094 lines because it is one table per contract clause, and a test suite cut into fragments is harder to read against the contract it asserts. `vscode-extension/test/hygiene.test.js` keeps the extension's own ~600-line budget over its `src/`, which is a separate and enforced one.

`vscode-extension/test/core-untracked.test.js` (4: `git ls-files` empty for the bundled core, an ignore rule actually naming it, the copy built and current anyway, and the three npm scripts that build it) and `vscode-extension/tools/vsix_smoke.py` are §15.3 P1's own gates; `webview/test/composition.test.mjs` and `orient.test.mjs` carry the legend rung of the Escape cascade (§10.1) — four Escapes take sheet, legend, focus mode and scope in that order with the selection still standing, and closing the legend closes nothing else with it.

`claude-plugin/tests/` — a **real subprocess handshake** over stdio (initialize → initialized → tools/list → tools/call) asserting **exactly the five tool names** and a ≤ 4 KB result; the digest budget on a 500-node synthetic; scope payloads and the extended error text; CLI-vs-MCP parity on three selectors; `test_diff_scope.py`; `test_hooks.py` (the manifest shape, the `MLVIEW_HOOK` matrix, the path filter, data-directory containment, the diff's two edge cases, the coverage line, the budget, and cases that drive the **real scripts** with a fake payload on stdin); `claude plugin validate ./claude-plugin --strict` when the CLI is present.

### 16.4 The end-to-end drivers and the doc gate

`scripts/e2e.ps1` / `e2e.sh` build everything, run every suite, analyze both samples to JSON and HTML, write and render the scoped demo reports, then run — in this order — the **CLI-vs-MCP parity gate**, the **scope gate**, the **bundle-hash gate**, the accuracy gate, the wheel gate and the doc gate, printing a PASS/FAIL table. `tools/verify.py --all` is the parity, sync, hash and version rollup.

**The CI tiers are a cost policy, never a coverage policy.** `ci.yml` runs a cheap tier on every push (analyzer on 3.10 and 3.13, the viewer on one Node, both host suites, the accuracy corpus, the Linux e2e table) and the remainder — the other interpreters, the second Node, the Windows e2e table, the macOS smoke job and `packaging` — on `pull_request` and on pushes to `main`. **Every gate in §15.4 and §16 therefore still runs before anything reaches `main`** — by design, and not yet by measurement (§17 **E28**: no CI job has been allowed to start on this branch) — on every interpreter `requires-python` claims, both e2e drivers and all three platforms. A push whose paths are only `**.md` and `docs/**` runs nothing; **a pull request carries no such exemption**, so a docs-only branch is still checked before it merges. The two tiers **may not overlap**: the cheap jobs keep the same-repository double-billing guard, and every full-tier job runs exactly on the events that guard excludes.

`scripts/check_docs.py` (checks 1–8, 12), `scripts/doc_numbers.py` (9–11), `scripts/doc_figures.py` (13–15) and `scripts/doc_claims.py` (**16** — a green claim and the CI matrix in one breath must say in that same breath whether the matrix ran; §17 E28) are the doc gate. **`docs/CONTRACTS.md` is in `check_docs.SKIP` and is held to none of them**, deliberately: a normative spec carries dated measurements from the amendments folded into it, and a gate that forced them to be rewritten would make §17-style errata impossible. The cost is that a wrong figure here is equally invisible to the gate, which is why **every figure in this document names the command that settles it**. `docs/archive/**` is outside every glob the gate collects and is likewise unchecked — an archive must keep the text the tree was built against.

## 17. Errata and superseded statements

Every entry here was a conflict between two v1.0 amendments or a mistake in one. **The later statement
wins**, and the resolution is already folded into the body above; this table is the record.

| # | Statement, and what replaced it |
|---|---|
| **E1** | **v1.0 §11.19 wrote "54 nodes and 52 edges"; the demo was 54 nodes and 51 edges** (it is 59 / 51 now — E25). v1.0 §11.35 corrected it: a later fix in the same release (`binding_history` plus `binding_of(name, scope, at=…)`) removed exactly one wrong edge — `data self.pool -> self.stem`, an arrow pointing three lines backwards — and added none, so the graph went 52 → 51. Only the edge total moved; no node, finding, anchor, line, severity or confidence in §11.19 changed, and none of its normative clauses was amended. **§14.1 carries 59 / 51** (E25). |
| **E2** | **`exportFile` was specified twice with different field names** — `{kind, name, base64}` by the viewer amendment and `{kind, data, suggestedName?, scope?}` by the host amendment, whose validator **rejects a frame without `data`**. Resolved by writing **both spellings on every frame**, with `name === suggestedName` and `base64 === data` always (§8.2, §8.3). This is the one redundancy in the protocol a reviewer should collapse. |
| **E3** | **`Diagnostic.kind` listed `unresolved_callee`, `config_unresolved` and `notebook_analyzed` as "reserved, not emitted".** All three are emitted now (§2.6), by ANA-5a, ANA-10 and the notebook ingest respectively. A reserved value was part of the enum from the amendment that reserved it, so no consumer needed a change. |
| **E4** | **`--relevance` defaulted to `all`, and the amendment that introduced it said the default would stay `all` until a change moved four named gates deliberately.** That change landed: the default is **`ml`**, the cache is on with it, and the four gates were re-baselined with the honesty property each protected asserted *more* explicitly (§3.9). |
| **E5** | **`--max-nodes` was a deletion** — keep the highest-priority N nodes, drop the rest, keep only edges whose two endpoints both survived. It is now a **hierarchical rollup** (§3.13); deletion survives only as phase 3. |
| **E6** | **The prototype §6 settings listing named two settings that did not exist and omitted one that did**; a later amendment fixed it at thirteen rows, and a later one still added two more. **The manifest is the authority and the set is the 16 rows of §12.3.** |
| **E7** | **"Settings: none added" and "a `scope` input on the three language-model tools is cut for v1"** were both lifted — the first for exactly `mlview.configPath` and `mlview.baselinePath`, which name a *file*; the second for `scope` and `depth` only. **Prose-to-scope resolution stays cut.** |
| **E8** | **The MCP transport was first specified as a hand-rolled JSON-RPC server with a `--sdk` flag and a `python -m mlview mcp` subcommand.** All three were dropped in favour of the official `mcp` Python SDK (§11); `python -m mlview mcp` is not a command. |
| **E9** | **The prototype trimmed "baseline" from scope.** That one trim was lifted (§3.8 B); the other three challengers — fuzzy search, a third LOD tier, and implementing `followCursor` — stay refused. The trims of notebook fixtures and of the synthetic generators were lifted by the notebook and rollup work. |
| **E10** | **MLV709 was scoped to the module** *"because two models in one workspace would otherwise accuse each other"*; the same accusation happened **inside** a module. It is **model-scoped** now (§14.2 A8/R1). |
| **E11** | **MLV121's subject was "a `Dataset.shuffle(...)` reaching one of `take`/`skip`"**, which permitted a lone `take(1)` — the commonest line in TensorFlow code — to be reported at high severity. **A holdout must exist before the rule describes one** (§14.2 A7/R2). |
| **E12** | **§11.2 step 6 did not say what happens to an issue retained through the edge rule whose every `nodeIds` entry fell outside `kept`.** The two ports answered differently and one answer broke invariant 3. **The promotion rule F1–F3 is normative** (§6.4). |
| **E13** | **`Node.attrs` was "stringified literal keyword arguments only".** It additionally carries the notebook provenance keys and the resolved-configuration keys, with provenance winning a name collision (§2.4). |
| **E14** | **`workspace.notebooksSkipped` was ".ipynb files detected but not analyzed in this version".** It is now every notebook discovered minus the ones that really reached the rules (§3.10 N11). |
| **E15** | **The charge amendment claimed the "constant-apparent-speed promise" was unchanged.** It holds for a lineage **stream** and not for a **pulse** at either clamp; `pulseDurationMs` documents the clamp, not the intent (§10.2). |
| **E16** | **The prototype rule catalogue was 20 codes.** The registry is **36** and every host reads the enumeration, never a count (§14.2). |
| **E17** | **`mlview_locate` and `mlview_rule_doc` were sketched as a later tier.** Neither shipped, and the tool count is still **exactly five**; discovery is `mlview_graph {scope: "units"}` and a diff is `{scope: "diff", base}` (§11). |
| **E18** | **The scope battery was "10 projections + 6 error cases" over one 45-node document.** It is **13 projecting + 7 error cases + 5 promoted fuzz cases** over the frozen golden, and `contracts/scope.cases.json` is the authority (§16.2). |
| **E19** | **The IR's resolution round count was a literal `range(4)`.** It is a convergence loop capped at `MAX_ROUNDS = 8`, and stopping on the cap emits a `truncated` diagnostic (§2.6). |
| **E20** | **The prototype forbade `subprocess` outright.** The ban is narrowed, not weakened: `adopt/gitdiff.py` is the single allowed importer, every call there is a list literal beginning `"git"` with no `shell=`, and the promise that survives untouched is that **the analyzed program is never imported, executed or `exec`ed** (§1). |
| **E21** | **The `Escape` cascade was "shortcut sheet → focus mode → scope → selection → blur".** The scope picker was already ahead of it in the shipped owner, and the **legend** rung was added between the sheet and focus mode. **The order is the one in §10.1**, written once by one owner. |
| **E22** | **The fact cache defaulted into the analyzed repository.** v1.0 §11.28 B5 put the sidecar at `<root>/.mlview/cache/` and v1.0 §11.39 C4 accepted that as a sanctioned cost; it is not one — `mlview analyze <somebody else's repo>` is the commonest first use of this tool, and it created a directory inside a checkout the user does not own, silently, on the first run (measured: **277** such directories in this working tree). A default every host had to override was the wrong default. **§3.9 B5 now keeps it out of `root` entirely**, and `MLVIEW_CACHE_DIR` becomes belt and braces. |
| **E23** | **v1.0 §11.25 P1 authorised a tracked third copy of the analyzer.** The gate did its job, but 113 tracked files were a duplicate of 113 others in the same commit — reviewed twice, rebased twice, conflicted twice, and never read, because reading them is what the gate is for. **`vscode-extension/core/mlview` is now a build artifact** (§15.3 P1); `claude-plugin/vendor/mlview` stays tracked, because a marketplace install copies the plugin directory verbatim off a git ref, and it goes when the wheel is on PyPI. |
| **E25** | **§14.1 recorded the demo at 54 nodes.** It is **59**, and the five added cards are listed in §14.1: `§5.3` A7–A8 draw a workspace object at the line it is built or applied, which is five lines of `samples/vision_pipeline` that had no box. **Only the picture moved.** `samples/vision_pipeline/expected_issues.json` is unchanged, all 15 findings keep their code, file, line, severity and confidence, `contracts/graph.sample.json` is untouched and `mlview analyze --demo --json -` is still byte-identical to it at 46 078 bytes. `samples/vision_pipeline_clean` went 64 / 55 / 0 → 70 / 56 / 0 and `analyzer/tests/clean` 142 / 135 / 0 → 157 / 139 / 0, both still **zero findings in both dataflow modes**. One consequence is contract-visible and is stated rather than hidden: **MLV401's `nodeIds[0]` moves** from `train.train.criterion` (the `CrossEntropyLoss()` construction, `train.py:22`) to `train.train.loss` (the `criterion(logits, labels)` computation, `train.py:31`), because `ctx.node_for_call` now finds the call site's own card. `loc`, message, severity, confidence and `relatedLocs` are unchanged, and the new anchor is the line a reader would point at. `contracts/validate_sample.py` keys on `nodeIds[0]` existing, not on which node it is, and passes. |
| **E26** | **PERF-04's "edge retention over 40% at `--max-nodes 400`" no longer holds at that literal budget, and is restated as a floor.** The acceptance measured **47.3%** (1074 of 2273) on a 525-file synthetic that drew **1972 nodes / 2273 edges**. The same 525 files now draw **2297 / 2297** — the 325 extra cards are the workspace objects §5.3 A7–A11 recover — so a 400-node budget is a 5.7× fold where it was a 4.9× one, and retention at 400 is **33.7%**; folding by the *same factor* (budget 466) gives 37.0%, and 40% is first reached at **495** (40.1%), with 500 at 40.7%. 400 also sits on a fold-tier cliff here: the file tier overshoots to 351 cards at 400 and 425 alike. **Everything the acceptance exists to protect is unchanged** — `edges_lost == 0` at every budget, zero floating cards, every finding surviving every budget, and the deletion cap this replaced still retaining only **0.8%** (19 of 2273) at the same budget. §3.13 now records **> 30% at 400** and **> 40% at 500** as measured floors, and `analyzer/tests/core/test_rollup.py::test_edge_retention_at_the_roadmap_budget` asserts exactly those two and states the deviation in its docstring. **A graph that grew because it draws more of the program is not a regression in the cap**; a reader at `--max-nodes 400` on a 500-file repository now sees more absorbed edges and fewer drawn ones, which is a coarser zoom level and not a loss. |
| **E24** | **`--framework <x>` was documented as "restrict framework extractors"** while it actually narrows the **rule set** — on `samples/vision_pipeline`, `--framework keras` takes the finding list from 15 to 1 — and the document said nothing about why. It now emits the `framework_filter` coverage diagnostic (§2.6 C8). |
| **E27** | **v1.0 §11.40 D2 asserted the gallery's blind spot from a constant**: *"every page is a single-file analysis, so MLV301/302/401/501 structurally cannot fire and the index says so"*. Measured off a real run, **both halves were false** — 0 of 90 pages carry a `single_file_analysis` diagnostic (it speaks only when an analyzed module imports a sibling the run left out, which no self-contained fixture does), and all four cross-file rules **did** fire on at least one single-file page. §14.4 G2 therefore requires the index to **measure** what it could not analyze and state what it measured. Telling a reader the tool was blind where it was not is the same failure as telling them it looked where it did not. |
| **E28** | **`README.md` and `docs/STATUS.md` claimed every gate green *on the CI matrix*.** No CI job has started on the consolidation branch: every job of every push came back *"The job was not started because recent account payments have failed or your spending limit needs to be increased"*, so nothing in this tree has run on Python 3.10, 3.11 or 3.12, on Windows or on macOS, and the five full-tier jobs (`analyzer-extra`, `webview-extra`, `e2e-windows`, `smoke-macos`, `packaging`) have never run at all. The C6 split itself is verified — the first branch push created exactly the seven cheap-tier jobs and marked all five full-tier jobs `skipped` — but the **coverage** the matrix would give is not. §16.4's claim that *"every gate in §15.4 and §16 therefore still runs before anything reaches `main`"* is a statement about the workflow's design, not a measurement, and is true only once a job is allowed to start. `scripts/doc_claims.py` check 16 keeps the two documents honest about it. |
| **E29** | **§3.11 R1.3 (2) said *"a rule that fires in `local` and not in `ip` is a regression, not a trade"*.** As a statement about **individual findings** it is false on real code and is gated nowhere: framework recognition and the `IP_HOP_WEIGHT` factor each withdraw findings in `ip` **by design**, and four findings on the public corpus do exactly that (§3.11 R1.3). The gate that exists, and the only one this clause ever meant, is the **recall inequality per rule and overall on the labelled corpus**. Restated in place; `docs/ACCURACY.md` §6 carries the same restatement and the same four-finding table. |
| **E30** | **§10.4 said a `launch` appends a hidden `<iframe>`, removed after ~1500 ms.** It did — and it took the report's keyboard with it. Handing a URL to the OS protocol handler costs the **launching browsing context** its keyboard permanently (measured Chrome 141 / macOS 25.6, headless and headed: after one node-card click, `l`, `?`, `f`, `s`, `[`, `]`, `e`, the arrows and **Escape** — including the legend rung of §10.1's cascade — never reached the document again; nothing recovered it). A `launch` now happens in a **transient context the report can afford to lose** (D7–D9), and `bridges.ts` creates no browsing context inside its own document. A hand validation of the viewer read as broken from its second step until this was found, and 536 green webview tests stood over it because no keyboard test pressed a key **after** a click. |
| **E31** | **`Diagnostic.kind` is a closed enum, and widening it is how a new diagnostic ships** (precedent: 11.18, 11.23 A1, 11.29 N10, and `framework_filter` in the C8 wave). §17 is where this project records exactly that kind of deviation, and it was not recorded. A consumer validating a document against a **pinned older copy** of the schema rejects a document carrying the new kind, where an added optional property would have validated. The mitigations are the schema-mirror gate (all three copies byte-identical) and §2.2's render-the-unknown rule — which binds renderers and **not validators**, and that is the residual risk. |
| **E32** | **The hosted marketplace entry named the repository, which is not a plugin.** `{"source": "github", "repo": "realmyang/MLView"}` publishes the fetched tree's root as the plugin root; MLView's plugin is at `claude-plugin/`, so the entry installed a directory with no `plugin.json` — and Claude Code cannot read a remote manifest before installing, so the failure surfaced only afterwards. §13.1 now requires `git-subdir` with `path: "claude-plugin"`, gated three ways. |
| **E33** | **§2.6 C8's rationale claimed *"a host reading that tuple picks it up with no code change"*.** No host reads `core.coverage.COVERAGE_KINDS`: the plugin and the extension each keep their own closed copy, so `framework_filter` shipped in the core alone and a run the **model itself** narrowed came back as a clean bill of health in both hosts. The rationale is deleted and §2.6 C9 replaces it with a membership gate on each host's copy. |

**One statement is deliberately left unresolved.** Nothing in §11's dated measurements was re-derived
by a tool for this consolidation. Every figure quoted from an amendment is a measurement of the tree
on the day that amendment was written; where the number still matters, the command that settles it is
named beside it (§14.1, §3.13 E, §16). No gate compares this document's prose against the tree, and
none is proposed, for the reason §16.4 gives.

---

## 18. Amendment index

Every section and amendment of v1.0 (archived at
[`docs/archive/CONTRACTS-v1.0-amended.md`](archive/CONTRACTS-v1.0-amended.md)) and the v1.1 section
that now carries its normative content. A `CONTRACTS.md §11.25` citation anywhere in the tree resolves
through this table. **Nothing normative was dropped**; what was dropped is the narrative — the *why*,
the measurements of the day, and the review history — which is what the archive is for.

| v1.0 | Subject | Carried by |
|---|---|---|
| §0 | Universal conventions | **§1** |
| §1 | The graph document — JSON Schema | **§2.1–§2.5** |
| §1.1 | Invariants the renderer relies on | **§2.7** (1–8) |
| §2 | Example document | **§2.8** |
| §3 | CLI contract, stdout and UTF-8 invariants | **§3.1–§3.6** |
| §3 (`core_api.md`) | The in-process API | **§4** |
| §3 (`rule_api.md`) | The rule API | **§5.1** |
| §4 | Webview ↔ host message protocol, `openLocation`, webview creation | **§8**, **§9.3** |
| §5 | MCP tools, slash commands, skills, `plugin.json`, install paths | **§11**, **§13.1** |
| §6 | Chat participant, LM tools, feature detection, manifest, diagnostics mapping | **§12** |
| §7 | Sample projects and fixtures | **§14.1–§14.2** |
| §8 | Renderer API and the build rules | **§9.1**, **§9.3** |
| §9 | Repository layout, ownership, the three parity gates | **§15.1**, **§15.4** |
| §10 A1 | MCP on the official SDK; the vendored core | **§11**, **§15.2** (+ §17 E8) |
| §10 A2 | `rendererSha`, asset sync, the version check | **§9.3**, **§15.4** |
| §10 A3 | The renderer global's final shape | **§9.1** |
| §10 A4 | The standalone HTML report and its size band | **§9.3**, **§3.6** |
| §10 A5 | The VS Code webview bootstrap | **§9.3** |
| §10 A6 | Scope trims | **§17 E9** |
| §10 A7 | Test scope — the gates that actually run | **§16** |
| §10 A8 | Rules ownership and count | **§14.2** (+ §17 E16) |
| §10 A9 | Ghost nodes | **§2.4** |
| §10 A10 | Extension toolchain pins | **§12.1** |
| §10 A11 | Stage bands and dagre | **§9.3** |
| §10 A12 | Sample ownership | **§14.1** |
| §10 A13 | Extension media placeholder / bundle-absent fallback | **§9.3** |
| §11 preamble | Additivity of every amendment | front matter, **§2.1** |
| 11.1 | The scope selector grammar, concern presets, error codes | **§6.1**, **§6.2** |
| 11.2 | Resolution and projection | **§6.4** |
| 11.2.1 | The ordering invariant | **§6.5** |
| 11.2.2 | `--max-nodes` runs before projection | **§6.6** |
| 11.3 | `view`, `viewRole`, `ViewAnchor` schema additions | **§2.2**, **§2.5** |
| 11.4 | Invariant 9 and the three `present` consumers | **§2.7**, **§15.2** |
| 11.5 | `--scope`, `--depth`, `--list-scopes`, the scoped exit table, the emitter line | **§3.2**, **§3.4**, **§3.6** |
| 11.6 | `mlview.api` scope additions | **§4** |
| 11.7 | `setScope` / `scopeChanged` | **§8.1**, **§8.2**, **§8.3** |
| 11.8 | `mount` unchanged; the two root attributes; `setScope` / `getScope`; `__internal.scope` | **§9.1**, **§9.3** |
| 11.9 | `ViewState.scope` and `.flow` | **§9.2** |
| 11.10 | MCP scope, `scope: "units"`, the cache key | **§11.2** |
| 11.11 | `scopeToSymbol` / `clearScope`; "settings: none added"; diagnostics untouched | **§12.2**, **§12.3**, **§12.4** (+ §17 E7) |
| 11.12 | Plugin command argument grammar | **§13.1** |
| 11.13 | The flow DOM contract, constants and the Escape cascade | **§10.1** |
| 11.13.1 | Charge representation | **§10.2** |
| 11.13.2 | Charge legibility; the motion-flip rebuild | **§10.2** (+ §17 E15) |
| 11.14 | Flow × scope composition (C1–C5) | **§10.3** |
| 11.15 | The Python gates, the parity battery, the reduced-motion and composition gates | **§16.1**, **§16.2**, **§16.3** |
| 11.16 | Files that must change together | **§15.2** |
| 11.17 | Standalone deep-link safety and `deepLinkPlan` | **§10.4** |
| 11.17.1 | The copy toast is an interface (D1–D7) | **§10.4** |
| 11.18 | The twelve `Diagnostic.kind`s; coverage diagnostics C1–C7; `--group-by`; `issues --text`; `ctx.untraced`; the runtime size band | **§2.2**, **§2.6**, **§3.2**, **§3.3**, **§3.6**, **§5.1** |
| 11.19 | Class-method ops, receiver resolution, package re-exports | **§5.3** A1/A3, **§14.1** (+ §17 E1) |
| 11.20 | The contributed settings listing; `railGroupBy` / `legendOpen` | **§12.3**, **§9.2** (+ §17 E6) |
| 11.21 | Change attribution, the baseline ratchet, SARIF | **§3.8** |
| 11.22 | The Pipeline Answer Card (P1–P8) | **§2.5**, **§3.6**, **§4** |
| 11.23 | Framework recognition F1–F15; ANA-5a A1–A8 | **§14.2**, **§5.3**, **§2.6**, **§3.6** |
| 11.24 | The SVG/PNG/clipboard/print export, E1–E4, `exportFile` | **§10.5**, **§8.2**, **§8.3** |
| 11.25 | Packaging, the bundled core, the precedence chain, the wheel | **§15.3** |
| 11.26 | The three rule tiers, A1–A14 | **§14.2**, **§14.3** |
| 11.27 | `suppressRule` and the quick fixes, S0–S6 | **§12.4**, **§8.2**, **§8.3** |
| 11.28 | The relevance prefilter and the fact cache, A1–A11 / B1–B10 / C | **§3.9** |
| 11.29 | Notebook ingest, N1–N11 | **§3.10** |
| 11.30 | The edge-retained issue F1–F3; the differential fuzz gate G1–G8 | **§6.4**, **§16.2** |
| 11.31 | `--progress-json`, H1–H5 | **§3.12** |
| 11.32 | Label placement V9–V13; a11y scaffolding V14–V19; answers, attribution and suppression V1–V8 | **§10.6**, **§10.7**, **§9.2**, **§8.2** |
| 11.33 | `requestExport` / `exportFile`, the host half, E1–E6 | **§8.3**, **§12.5**, **§11.1** |
| 11.34 | Sprint-4 review fixes R1–R12 | **§14.2**, **§5.3**, **§3.8**, **§3.6**, **§2.5**, **§2.6**, **§14.3** |
| 11.35 | Erratum: the demo is 54 / 51 | **§17 E1**, **§14.1** |
| 11.36 | `--dataflow local\|ip`, N1–N10, G1–G8 | **§3.11** |
| 11.37 | CFG-ONE: one configuration surface, A1–A5 / B1–B5 / C1–C4 / D1–D4 | **§3.7** |
| 11.38 | The `mlview-diff` overlay document | **§7** |
| 11.39 | The prefilter and cache become the defaults | **§3.9** (+ §17 E4) |
| 11.40 | LM-tool scope and depth; multi-root folders; CFG-ONE host half; the gallery (D1/D2) and the walkthrough (D3/D4) | **§12.6**, **§12.3**, **§12.5**, **§14.4** |
| 11.41 | The plugin's `PostToolUse` and `Stop` hooks, A1–A4 / B1–B7 / C1–C6 / D1–D4 | **§13.2** |
| 11.42 | Structured fixes: the opt-in `Issue.fix`, A1–A8 / B1–B5 / C1–C4 / D1–D4 / E / F1–F5 | **§5.4**, **§2.5**, **§3.6** |
| 11.43 | The fix lightbulb A1–A11; `applyFix` B1–B3; the comparison commands C1–C7; `diffOverlay` D1–D4; `mlview_graph {scope:"diff"}` E1–E6; the two settings descriptions F1–F2 | **§12.4**, **§12.5**, **§8.3**, **§11.2**, **§12.3** |
| 11.44 | The viewer half of VIEW-08 (A1–A14), H5 (B1–B6) and ANA-10 (C1–C5) | **§10.7**, **§8.1**, **§8.3**, **§9.2** |
| 11.45 | ANA-10, the Python half, A1–A10 | **§5.5** |
| 11.46 | PERF-04: the hierarchical rollup, A1–A5 / B1–B5 / C / D / E / F | **§3.13**, **§2.4**, **§2.7** |
| 11.47 | MLV-P12: `pipeline:<entrypoint>` and `pipelines[]`, A1–A4 / B / C / D / E / F | **§6.7**, **§2.5** |

**Fragments folded into v1.1 during the consolidation wave** (each was normative and additive; each was folded into the sections named below and then removed from `docs/contracts/`, because this document — not a fragment — is the record from here on):

| Fragment | Folded into |
|---|---|
| `viewer-legend.md` — Escape closes the legend | **§10.1** (the cascade, its five rules), §17 E21 |
| `analyzer-c8.md` — the cache directory, the `--framework` caveat, SARIF `fixes[]` | **§3.9 B5 / B5.1** and §3.9's stated costs, **§2.2 / §2.6 C8** (the thirteenth `Diagnostic.kind`), **§3.8 C8**, §13.2 C2, §17 E22 / E24 |
| `built-vsix-core.md` — the VSIX's bundled core is built, not committed | **§15.3 P1 / P1.1 / P1.2 / P1.3**, §15.1, §15.2 (the vendored-core and licence rows), **§16.4** (the CI tiers), §16.3, §17 E23 |
| `rule-recall.md` — R1 (`ip` is the default), R4 (LOGITS / PROBS / PREDS value typing), R5 (the named rule shapes) | **§3.11 R1.1–R1.5** and §3.11's stated limits, §3.2, §4, **§5.3 A13**, **§14.2 R13–R21** |
| `graph-fidelity.md` — R3 (calls through workspace-defined objects), R2 (the knowledge tables) | **§5.3 A7–A12′**, **§14.2 F16–F21**, §14.1 (the five added cards), §14.3 R22, §3.13, §17 E25 / E26 |
| `plugin-marketplace-and-coverage-kinds.md` — the hosted marketplace source, coverage-kind parity, the plugin's storage | **§13.1** (the `git-subdir` entry and its gate), **§2.6 C9**, **§13.2 C7**, §17 E32 / E33 |
| `deeplink-launch-context.md` — where a standalone deep link is launched from | **§10.4** (the absolute rule, the `launch` row, **D7–D9** and the source-scan gate), §17 E30 |
| `consolidate-analyzer-corrections.md` — analyzer corrections | **§3.11 R1.1 / R1.3**, **§5.3 A12′ / A13**, **§14.2 R13 / R15 / R18 / R23**, §2.6 C8, §17 E29 / E31 |

Any later fragment the integrator appends lands as a **v1.1 addendum** under the section that owns the clause, never as a new §11.

---

*MLView Contracts v1.1 — 2026-09-15. Supersedes v1.0 + 63 amendments
(`docs/archive/CONTRACTS-v1.0-amended.md`, 5261 lines, kept verbatim).*
