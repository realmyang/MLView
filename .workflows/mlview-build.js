export const meta = {
  name: 'mlview-build',
  description: 'Build the MLView prototype: golden sample, 5 parallel component builders, integrator, then review/verify/fix loop',
  phases: [
    { title: 'Contracts', detail: 'hand-author + validate contracts/graph.sample.json', model: 'opus' },
    { title: 'Build', detail: 'core -> (rules, plugin) || viewer || extension', model: 'opus' },
    { title: 'Integrate', detail: 'build everything, run every gate, fix integration bugs', model: 'opus' },
    { title: 'Review', detail: '4 lenses find issues on the real code', model: 'opus' },
    { title: 'Verify', detail: '3 independent verifiers per finding', model: 'opus' },
    { title: 'Fix', detail: 'one fixer per component, then re-run gates', model: 'opus' },
  ],
}

const ROOT = 'c:/Users/realm/Desktop/MLView'
const SCRATCH = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/841f2125-7fe4-4d10-ba34-a40b1ee16a5e/scratchpad'

const PREAMBLE = `
You are one of several autonomous engineers building MLView: a prototype plugin that statically analyzes Python ML code (PyTorch, scikit-learn) and renders the ML workflow as an interactive diagram with severity-marked issues, for Claude Code and for GitHub Copilot / VS Code.
Repo root: ${ROOT} (Windows 11; NOT a git repo; use forward slashes). Use the Bash tool (Git Bash) for commands; PowerShell is available for .ps1 scripts ('powershell -ExecutionPolicy Bypass -File ...'). Scratch space for temporary files: ${SCRATCH}.
Environment: Python 3.13 ('python'; miniconda; pip works; installed: mcp 2.1.1, pytest 9, jsonschema, numpy, pydantic; torch / sklearn are NOT installed and must NEVER be required, analysis is purely static). ALWAYS run python with PYTHONUTF8=1 (e.g. 'PYTHONUTF8=1 python ...') because the console is cp1252. Node 20.9 + npm 10 (registry reachable; no global tsc so use npx; the npm cache already holds dagre, @dagrejs/dagre 3.1.1, elkjs, esbuild 0.28.2, typescript 5.9.3, jsdom 30, @types/vscode, @types/node, @vscode/vsce). VS Code 1.136 with the Claude Code extension; GitHub Copilot is NOT installed; Claude Code CLI 2.1.186 ('claude').
MANDATORY READING before writing code: docs/CONTRACTS.md (all of it, but especially section 0 conventions and section 10 "Prototype amendments", which OVERRIDE everything above them), contracts/graph.schema.json, contracts/graph.sample.json (if present), then the docs named in your brief. Follow the contracts exactly. If you believe a contract must change, do NOT change it: implement the closest compliant thing and list the request in contract_change_requests.
OWNERSHIP: create/modify files ONLY inside the directories listed in your brief. Other agents are writing elsewhere concurrently. Do not create git repositories. Do not modify docs/ or contracts/ unless your brief says so.
QUALITY BAR: working software, not scaffolding. No TODO stubs on the critical path. Run your build and tests before finishing and report REAL results (paste the tail of the output). Keep source files under ~600 lines and split modules sensibly. Everything must work offline. Windows-safe (paths, CRLF tolerance, no symlinks, no chmod, no shell:true). Library code never prints to stdout.
FINAL ANSWER: return ONLY the structured report. Do not stop early: if something is broken, fix it.
`

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    component: { type: 'string' },
    files_created: { type: 'array', items: { type: 'string' } },
    how_to_build_and_run: { type: 'string' },
    public_api_summary: { type: 'string', description: 'what other components need to know: module paths, function signatures, CLI behaviours, file locations' },
    tests_run: { type: 'string' },
    test_results: { type: 'string', description: 'verbatim tail of the test/build output' },
    all_tests_passing: { type: 'boolean' },
    known_gaps: { type: 'array', items: { type: 'string' } },
    contract_change_requests: { type: 'array', items: { type: 'string' } },
    notes_for_integrator: { type: 'string' },
  },
  required: ['component', 'files_created', 'how_to_build_and_run', 'public_api_summary', 'tests_run', 'test_results', 'all_tests_passing', 'known_gaps', 'contract_change_requests', 'notes_for_integrator'],
}

// ---------------------------------------------------------------- Phase 1: contracts
phase('Contracts')
const sample = await agent(`${PREAMBLE}
TASK: hand-author contracts/graph.sample.json, the golden MLGraph document, and validate it.
OWNERSHIP: contracts/graph.sample.json and contracts/validate_sample.py ONLY.
Requirements:
- Must validate against contracts/graph.schema.json (jsonschema.Draft202012Validator). Run it and report.
- Must satisfy every invariant in docs/CONTRACTS.md section 1.1 and the ordering rules in section 0 (stages by order; nodes by (stage order, file, line, col); edges by (source, kind, target); issues by (severity desc, file, line, code)).
- Models the sample project of section 7.1 (samples/vision_pipeline: config.py, data.py, model.py, train.py, sklearn_baseline.py) with workspace.root "C:/Users/realm/Desktop/MLView/samples/vision_pipeline" and absFile values under it. Use the abridged example in section 2 as the style reference. Ids are 'n:'/'e:'/'i:' + 12 lowercase hex chars (any hex, they need not be real hashes), all unique.
- Contents: all 8 stages (deliver present:false, nodeCount 0, maxSeverity null); EXACTLY 12 nodes spanning at least 6 stages and all three levels, including at least 2 'unit' nodes that have children (e.g. the train() function unit containing a batch-loop unit containing ops; a model class unit with ops) and ONE ghost node (label "zero_grad()", sublabel "missing", parent = the batch-loop unit, ghost true, issueIds non-empty); node kinds should include dataloader, model, loss, optimizer, train_loop, eval_loop, scaler or transform, split, entrypoint or function. EXACTLY 14 edges covering all four kinds (data, call, control with subkind "back", config), each loc at the call site. EXACTLY 6 issues: 2 high / 2 medium / 2 low: MLV201 high (nodeIds[0] = the ghost node; relatedLocs optimizer_site + backward_site), MLV401 high (edgeIds non-empty pointing at the model->loss data edge; nodeIds[0] = the loss node), MLV101 medium-or-high per ISSUE_RULES (use high only if you then rebalance to keep 2/2/2 — simplest: make MLV101 one of the two highs and MLV401 attach... no: keep exactly MLV201 + MLV401 as the highs, MLV101 is listed in ISSUE_RULES as high so instead use MLV110 and MLV302 as the two mediums and MLV601 + MLV602 as the two lows, and put MLV101's shape into a later fixture; i.e. issues = MLV201 high, MLV401 high, MLV110 medium, MLV302 medium, MLV601 low, MLV602 low), each with realistic title/message/why/fixHint/evidence/tags/frameworks/docs ("docs/rules/<CODE>.md"), confidence + matching confidenceBucket (certain >=0.9, likely >=0.7, possible >=0.5, speculative <0.5), suppressed false.
- Consistency: stats {nodes:12, edges:14, issues:{low:2,medium:2,high:2}, suppressed:0, durationMs:412, truncated:false}; each stage's nodeCount / issueCounts / maxSeverity consistent with nodes and issues; node.issueIds consistent with issue.nodeIds; edge.issueIds consistent with issue.edgeIds; every parent refers to a node with a lower level; every edge source/target exists; generator = {name:"mlview", version:"0.1.0", rendererSha: 64 zeros, generatedAt:"2026-09-06T12:00:00Z"}; workspace {entrypoints:["train.py"], filesAnalyzed:5, filesFailed:0, notebooksSkipped:0, frameworks:["torch","sklearn","torchvision"]}; diagnostics: [].
- Snippets are plausible Python for those files; loc.symbol must be a substring of loc.snippet; endLine >= line.
- Write contracts/validate_sample.py (stdlib + jsonschema) that validates the schema AND all of the consistency/ordering invariants above for any MLGraph file given on argv (default contracts/graph.sample.json) and exits 0/1 with a clear message; run it on the sample. The core agent will reuse it in tests.
Return the report with the validator output in test_results.`,
  { label: 'contracts:sample', phase: 'Contracts', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })
log(`Sample document: ${sample && sample.all_tests_passing ? 'valid' : 'PROBLEM'}`)

// ---------------------------------------------------------------- Phase 2: build
phase('Build')

const CORE_BRIEF = `${PREAMBLE}
COMPONENT: the analyzer core: the Python package 'mlview'
RESUME NOTE: a previous run of this exact task was interrupted after it had already written a substantial amount of work into your directory. Before writing anything, inventory what exists (list files, read the package/module layout, run the existing build and tests). Keep what is good, fix or complete what is broken or missing, and do not start from scratch. Your final report must still describe the complete component.
 (zero runtime dependencies, stdlib only; jsonschema only in tests).
OWNERSHIP: analyzer/** EXCEPT these, which belong to the rules agent that runs after you: analyzer/src/mlview/rules/r_*.py beyond your four seed files, analyzer/tests/rules/* beyond the conftest + four seed tests you create, analyzer/tests/fixtures/* beyond your eight seed fixtures, analyzer/tests/clean/**. You also create analyzer/src/mlview/emit/assets/README.md (placeholder; the bundle is synced there later by tools/sync-assets.py).
Read: docs/CONTRACTS.md (sections 0-3, 7, 9, 10), docs/ARCHITECTURE.md, docs/ISSUE_RULES.md (sections 0-3, 5), docs/REQUIREMENTS.md, contracts/validate_sample.py.

DELIVERABLES
1. Packaging: analyzer/pyproject.toml (name "mlview", version "0.1.0", requires-python ">=3.10", no dependencies, [project.scripts] mlview = "mlview.cli:main", setuptools src layout, package-data for schema/*.json and emit/assets/*), analyzer/README.md. Install in dev mode ('PYTHONUTF8=1 python -m pip install -e analyzer') so 'python -m mlview' works from any directory. Verify it does.
2. Modules (suggested layout, adapt as needed but keep api.py/cli.py/version.py at the top level):
   - mlview/__init__.py, __main__.py, version.py (__version__ = "0.1.0"), cli.py (argparse; commands and options EXACTLY per CONTRACTS section 3 minus the dropped 'mcp' subcommand; exit codes 0/1/2/3/4; the stdout invariant), api.py (FROZEN surface: AnalyzeOptions dataclass, analyze, analyze_to_dict, render_html, render_mermaid, render_text, digest).
   - ingest/discover.py: walk paths (files or dirs; multiple), default excludes, --include/--exclude globs (fnmatch on forward-slash relpaths), max_files cap, .ipynb counting, deterministic sorted order; workspace root = the dir itself for one dir, the parent dir for one file, the common path for several.
   - ingest/parse.py: ast.parse; SyntaxError / UnicodeDecodeError -> diagnostics parse_error (filesFailed++); keep source lines for snippets and end positions.
   - ir/model.py: dataclasses ModuleIR, FunctionIR, ClassIR, CallSite {fqn, canonical_fqns (list), node, loc, receiver (ValueRef|None), args, kwargs literal-stringified, scope}, LoopIR {kind epoch|batch|fold|other, iterates (ValueRef|None), body, depth, inside_no_grad, inside_autocast, loc}, ValueRef {name, scope, tags, producer (CallSite|None), loc}, ScopeIR {qualname, dynamic, reasons}.
   - ir/symbols.py: import-alias resolution to canonical FQNs ('import torch.nn as nn' so nn.Linear -> torch.nn.Linear; 'from sklearn.model_selection import train_test_split'; 'import torch.nn.functional as F'; relative and absolute imports of workspace-local modules; star-import marks the scope dynamic; attribute chains). Never match bare attribute names: every rule works on canonical FQNs.
   - ir/bindings.py: flow-insensitive per-scope bindings: Assign / AnnAssign / AugAssign / tuple unpacking (train_test_split 4-way and 2-way, random_split), self.x attributes inside classes, walrus, 'with X() as y', for-targets. ValueTags (CONTRACTS ValueTag enum) derived from the producer FQN through the knowledge tables (e.g. DataLoader -> LOADER; train_test_split outputs -> TRAIN_SPLIT/TEST_SPLIT/FEATURES/TARGET by position; StandardScaler() -> FITTED_TRANSFORMER after fit; criterion(...) -> LOSS; nn.Module subclass instantiation -> MODEL; optim.* -> OPTIMIZER; torch.device -> DEVICE). RECEIVER RESOLUTION: 'obj.m(...)' where obj is bound to a producer with FQN P resolves to canonical_fqns = [P + '.m'] plus the family base method when P is a known family: any torch optimizer -> torch.optim.Optimizer.step / .zero_grad; any nn.Module (framework class or a workspace class whose bases resolve to torch.nn.Module) -> torch.nn.Module.eval/train/to/parameters/forward; a LOSS-tagged value or any torch call result -> torch.Tensor.backward/item/detach/to/cuda; any sklearn estimator/transformer -> sklearn.base.BaseEstimator.fit/predict/transform/fit_transform/score plus its concrete FQN; LR schedulers -> torch.optim.lr_scheduler.LRScheduler.step.
   - ir/scopes.py: loop-kind classification (iterating range(...) whose argument name contains 'epoch' or a literal, or a target named epoch -> epoch; iterating a LOADER-tagged value or a name containing loader/batch/dl -> batch; KFold/StratifiedKFold/.split() -> fold; else other), nesting depth, with-blocks for torch.no_grad()/torch.inference_mode()/torch.autocast/torch.cuda.amp.autocast and their decorator forms, torch.enable_grad negation; dynamic-scope marking for exec/eval/getattr with non-literal attr/star-import/**kwargs forwarding into framework calls.
   - knowledge/*.py: plain python dicts (no yaml): FQN -> {kind, stage, tags, framework, family} for torch, torchvision, sklearn, pandas, numpy, and minimal keras/tf, transformers (hf), lightning; framework detection from imports; wrapper detection (LightningModule/Trainer, transformers.Trainer, accelerate.Accelerator, keras .fit) used by the negation_absent gate.
   - core/stages.py: the 8-stage classifier per CONTRACTS StageId: op stage from the knowledge table; unit stage = weighted vote of its ops, ties broken by priority order config < data < preprocess < model < objective < train < eval < deliver; classes deriving nn.Module -> model; functions containing backward+step -> train; functions containing eval()/no_grad/metrics/predict -> eval; entrypoint units -> config unless dominated. Record stageEvidence (kind + detail + weight).
   - core/ids.py: content-addressed ids EXACTLY per CONTRACTS section 0 (sha1 hex[:12] with the given input strings).
   - core/build.py + core/graph.py: UNITS = every top-level function; every class (its methods become ops inside the class unit, except a method containing an epoch/batch/fold loop, in which case that loop becomes a child unit); the 'if __name__ == "__main__":' block plus other module-level statements as one 'entrypoint' unit with qualname "<module>.__main__"; epoch/batch/fold loops as child units (label like "for images, labels in train_loader", attrs loopKind / iterates / depth / insideNoGrad / insideAutocast). OPS = calls whose canonical FQN is in the knowledge table or resolves to a known method family (dataset/DataLoader/transforms/split/scaler/model instantiation/loss/optimizer/scheduler/backward/step/zero_grad/eval/train/no_grad/save/load/metrics/fit/predict/transform/fit_transform/cross_val_score/argparse/yaml.safe_load/json.load/torch.device/.to(device)); label = callee short name or the bound var, sublabel from literal kwargs (e.g. "bs=128"), attrs = stringified literal kwargs, var = bound name, produces/consumes ports from bindings, fqn, framework, kind, loc = the call expression (symbol = the dotted callee text, snippet = the trimmed primary source line), defLoc for def/class headers. EDGES: data (producer op -> consumer op or unit through a ValueRef; label = var name; loc = the consumer site; tags), call (unit -> workspace-local function/class unit; loc = the call site), control (subkind enter: function unit -> its first loop child; subkind back: the last op inside a loop -> the loop unit, label "next batch"/"next epoch"/"next fold"), config (a config-valued var, i.e. produced by argparse/yaml/json/toml load or a dict literal bound to a name matching cfg|config|args|hparams -> each consuming unit). Parent forest, never cyclic. Node cap: --max-nodes truncates ops first (keep units) and sets stats.truncated + a 'truncated' diagnostic. Then run the rule registry (issues + ghost nodes per amendment A9), fill node.issueIds / edge.issueIds, stage summaries (present, nodeCount, issueCounts, maxSeverity), stats, canonical ordering per section 0.
   - emit/json_out.py (canonical JSON: indent 2, ensure_ascii False, key order as in the schema example, arrays sorted per section 0; '--json -' writes to stdout with a trailing newline), emit/html_out.py (per amendment A4 including the plain-HTML fallback with a visible banner when assets are missing, and HTML escaping everywhere), emit/mermaid_out.py (flowchart LR with one subgraph per present stage; sanitized ids; unit nesting as nested subgraphs; issue severity as a prefix in labels using [i] [!] [!!]; edges styled per kind), emit/text_out.py (the --format summary: header with root/files/frameworks, per-stage counts, then an issue table sorted by severity with severity, code, confidence bucket, file:line, title; this is the ONLY module allowed to print to stdout), mlview/schema/graph.schema.json (byte-identical copy of contracts/graph.schema.json) and mlview/schema/graph.sample.json (byte-identical copy of contracts/graph.sample.json; served by 'analyze --demo' as-is; 'python -m mlview schema' prints the schema). generator.rendererSha per amendment A2.
3. Rule framework in rules/: __init__.py, registry.py (discovers every rules/r_*.py by import; ordered by code; enabled flag; run_all(ctx) with per-rule try/except -> diagnostic rule_error unless strict), context.py (GraphContext EXACTLY per the frozen surface in CONTRACTS section 3: graph, frameworks, modules, calls_of(fqn) matching canonical_fqns, loops(kind), values_tagged(tag), binding_of(name, scope), class_bases(node), node_for(loc), follow_call(call), is_dynamic(scope), issue(...), ghost(kind, parent_node, label)), confidence.py (confidence = clamp(base_prior * product of evidence weights * 0.7 if dynamic scope * 0.4 when an absence rule sees a framework wrapper in the workspace (also emit a framework_suppressed diagnostic naming the framework and codes); buckets certain >=0.9, likely >=0.7, possible >=0.5, speculative <0.5; absence severity cap: high -> medium unless the scope is static AND no wrapper), suppress.py ('# mlview: ignore[CODE]' or '# mlview: ignore' on the primary line or the line above; '# mlview: ignore-file' in the first 5 lines; .mlview.toml via tomllib with [rules] disable = [...] and [paths] exclude = [...]; suppressed:true, still emitted). The @rule decorator: @rule(code, severity, base_prior, frameworks, rule_version=1, tags=(), absence=False, enabled=True, title=..., why=..., fix_hint=...). ctx.issue(title, message, why, fix_hint, loc, node_ids, edge_ids=(), related=(), evidence=(), tags=()) returns the Issue with id per section 0 and docs = "docs/rules/<CODE>.md". Rules never construct Issue directly.
4. Four seed rules with fixtures (analyzer/tests/fixtures/rules/<CODE>_bad.py and <CODE>_good.py, 10-40 lines, imports only, never executed): MLV201 missing zero_grad (absence rule in a batch loop that has backward + step; ghost node; relatedLocs optimizer_site + backward_site; good fixture = gradient accumulation with zero_grad under 'if step % 4 == 0'); MLV101 preprocessing fitted before the split (fit_transform/fit on the full X whose value later feeds train_test_split; relatedLocs fit_site + split_site; good = split first then fit on X_train only); MLV401 softmax/log_softmax as the final op of a model's forward whose output feeds nn.CrossEntropyLoss (cross-file pairing through the MODEL/LOGITS bindings; attach to the model->loss data edge when present (edgeIds) else to the loss node; good = raw logits); MLV601 no seed anywhere in the workspace (torch.manual_seed / torch.cuda.manual_seed_all / numpy.random.seed / random.seed / seed_everything / np.random.default_rng(literal); workspace-wide absence; loc = the entrypoint unit; good = seeded). Bad fixtures start with '# MLVIEW-EXPECT: MLV201 line=18 confidence>=0.6' (one line per expected issue). Put a shared helper in analyzer/tests/rules/conftest.py (parse the header, run the analyzer on the fixture, assert code+line+confidence; assert the good fixture fires nothing for that code) and write test_seed_rules.py using it; the rules agent will extend both.
5. Core tests per amendment A7 in analyzer/tests/core/*.py with a conftest providing a tmp-workspace factory. Run 'PYTHONUTF8=1 python -m pytest analyzer/tests -q' and make it green.
6. Sanity commands to verify and report: 'PYTHONUTF8=1 python -m mlview analyze --demo --json -' prints the golden sample byte-identically; 'PYTHONUTF8=1 python -m mlview analyze analyzer/tests/fixtures/rules/MLV201_bad.py --format summary' shows the MLV201 issue with a ghost node in the JSON; 'PYTHONUTF8=1 python -m mlview analyze analyzer/tests/fixtures --html ${SCRATCH}/core_report.html' produces the fallback report; exit code 4 on an empty dir.
In public_api_summary describe precisely: the GraphContext methods and their semantics, the IR dataclasses, how canonical_fqns work, how ghost nodes are declared, how to add a rule + fixture, and the CLI behaviours the hosts rely on.`

const VIEWER_BRIEF = `${PREAMBLE}
COMPONENT: the diagram renderer bundle (webview/)
RESUME NOTE: a previous run of this exact task was interrupted after it had already written a substantial amount of work into your directory. Before writing anything, inventory what exists (list files, read the package/module layout, run the existing build and tests). Keep what is good, fix or complete what is broken or missing, and do not start from scratch. Your final report must still describe the complete component.
, consumed unchanged by the VS Code webview and by the standalone HTML report.
OWNERSHIP: webview/** only.
Read: docs/UX_DESIGN.md (design system: tokens, palette, marker shapes, node cards, rail/inspector, states, keyboard, a11y), docs/CONTRACTS.md sections 1, 1.1, 4, 8 and 10 (A3, A5, A6, A7, A11), docs/REQUIREMENTS.md, contracts/graph.sample.json (your primary test input; also generate a 150-node synthetic graph in your tests).
STACK: TypeScript 5.9.3 + esbuild 0.28.2 (exact pins), @dagrejs/dagre 3.1.1 as the only runtime dependency (bundled), jsdom for tests, 'node --test' runner. package.json scripts: build (esbuild -> dist/mlview.js as IIFE with global name MLView, plus dist/mlview.css concatenated from src/styles), check (tsc --noEmit), test. Make sure dist/ exists and is current after 'npm run build'. Version "0.1.0".
FEATURES (all required):
- Layout: the 8 stage bands as horizontal swimlanes stacked top-to-bottom in stage order (present stages only; absent ones listed as chips in a "not detected" row), each band laid out independently with dagre rankdir LR (edge weights data 4 / call 2 / control 2 / config 1); groups (units with children) laid out children-first and placed as sized meta-nodes with a header strip; control back-edges are excluded from dagre and drawn as loops outside the group box; cross-lane edges routed as orthogonal elbows through the gutters between lanes; fully deterministic. Never use dagre compound/setParent.
- Rendering: HTML node cards absolutely positioned over an SVG edge layer; the DOM is built ONLY with document.createElement / createElementNS / textContent (never innerHTML/outerHTML/insertAdjacentHTML); node card = kind icon (inline SVG symbol per kind), label, sublabel, stage color accent bar, severity badge; edge styles per kind (data solid, call dashed, control dotted, config thin) with arrowheads via SVG marker; edge label on hover; ghost nodes dashed with "missing".
- Severity markers EXACTLY per the project spec: low = a subtle circled "i" symbol (muted), medium = a yellow warning triangle containing "!", high = a red exclamation badge (octagon or circle). Three DIFFERENT shapes so severity is never color-only. Markers on nodes (top-right badge; a count when > 1), on edges (at the edge midpoint), and aggregated upward on collapsed groups and lane headers (counts per severity).
- Interaction: pan (drag background) and zoom (wheel, +/- buttons, fit, zoom-to-selection); click a node or edge -> select it and post openLocation with its loc (also on Enter); double-click a group header -> collapse/expand with the viewport anchored; hover -> lineage highlight (upstream/downstream edges + nodes; the rest dimmed) and a tooltip card; focus mode (key F) on the selection; a search box (case-insensitive substring over label / qualname / issue title / rule code, results list, Enter jumps); filters: severity toggles, stage chips, show-suppressed; keyboard: arrows move selection among siblings, Tab cycles issues, Escape clears, + - 0 zoom, F focus, / focuses search; a minimap bottom-right.
- Side rail (right; collapsible; resizable) with tabs: Issues (grouped by severity, each row: marker, code, title, file:line, confidence bucket chip; click -> select + reveal the primary node; an open button -> openLocation), Inspector (selected node: label, kind, stage, framework, fqn, attrs table, ports, stage evidence "why", its issues with message / why / fixHint and related locations as clickable links that post openLocation), Outline (stages -> units -> ops tree).
- Top bar: title, workspace root, stat chips (nodes, edges, issues per severity), refresh (posts requestRefresh; hidden when capabilities.canReanalyze is false), export (posts exportHtml; hidden when canExport is false).
- States: loading skeleton before the first graph; empty state (no nodes: friendly message listing diagnostics); error banner (analysisFailed with action buttons that post 'action'); stale banner ("files changed, refresh"); partial-understanding banner when any node.dynamic or a dynamic_scope diagnostic; truncated banner; notebook_skipped and framework_suppressed chips.
- Theming: src/styles/tokens.css with --mlv-* tokens defined as var(--vscode-*, literal) for light, overridden under [data-theme="dark"] and [data-theme="hc"]; prefers-reduced-motion respected; color-blind-safe severity encoding (shape + color); visible focus rings; ARIA (role application on the canvas, tree for outline, listbox for issues, an aria-live region for announcements).
- HostBridge per CONTRACTS section 8 and amendment A3 (window.MLView = { version, mount, bridges: { vscode(), standalone(opts) } }); ViewState = { viewport, selection, collapsed, filters, railTab }; saveState debounced on change; restore on mount via bridge.loadState(). Handle EVERY HostToUi message type of section 4 (unknown types logged and ignored); post ready on mount. Forward-compatible: unknown node kind / stage / edge kind renders with the 'unknown' visual instead of throwing.
- Performance: a 150-node / 300-edge graph lays out in < 300 ms in node (tested); selection / hover use class toggles, not re-renders.
- dev/index.html loads dist/mlview.css + dist/mlview.js and an inline copy of contracts/graph.sample.json in a <script type="application/json"> (no fetch, so file:// works), then mounts with the standalone bridge; dev/states.html shows every node kind in each state (default, hover, selected, dimmed, ghost, stale) plus the three markers. Add a tiny script (dev/refresh-sample.mjs) that regenerates the inline copy from contracts/graph.sample.json.
TESTS per amendment A7 in webview/test/*.test.mjs (run against the built dist/ through jsdom where DOM is needed): layout (deterministic; no sibling bbox overlap; every node inside its lane's y-range; perf), bundle hygiene (no innerHTML / eval( / import( / http:// / https:// in dist/mlview.js), parity (sample via both bridges in jsdom -> identical sets of data-node-id / data-edge-id / data-issue-id), markers (three distinct SVG path 'd' strings), contrast (parse the literal fallbacks in tokens.css and assert WCAG contrast >= 4.5:1 for each declared text fg/bg pair in light and dark). Also test/render_sample.mjs: renders the sample in jsdom and prints a plain-text summary (lanes, node positions, marker counts) for the integrator. Run 'npm install', 'npm run build', 'npm run check', 'npm test' and make them green.`

const VSCODE_BRIEF = `${PREAMBLE}
COMPONENT: the VS Code / GitHub Copilot host adapter (vscode-extension/): transport and rendering only, never analysis.
OWNERSHIP: vscode-extension/** only. vscode-extension/media/ must contain only README.md (the bundle is synced there later by tools/sync-assets.py).
Read: docs/CONTRACTS.md sections 3 (CLI), 4 (messages, webview creation), 6 (chat participant, LM tools, feature detection, manifest, diagnostics mapping), 10 (A2, A5, A7, A10, A13), docs/ARCHITECTURE.md, docs/REQUIREMENTS.md, contracts/graph.sample.json.
STACK: TypeScript 5.9.3, esbuild 0.28.2, @types/vscode 1.100.0, @types/node 20.x, engines.vscode ^1.100.0; version "0.1.0"; npm scripts compile (esbuild src/extension.ts -> out/extension.js, cjs, platform node, external vscode, sourcemap), check (tsc --noEmit), test (node --test test/*.test.js), package (vsce package, documented only).
DELIVERABLES in src/:
- extension.ts: activate registers unconditionally: commands (mlview.visualize, mlview.visualizeWorkspace, mlview.refresh, mlview.showIssues, mlview.revealInDiagram [Alt+M + editor/context], mlview.exportHtml, mlview.selectInterpreter, mlview.showOutput, mlview.showRuleDoc), the panel + WebviewPanelSerializer, diagnostics, CodeLens, a status bar item with issue counts, the "MLView" OutputChannel; then feature-detected chat participant + LM tools exactly per section 6 (typeof guards inside try/catch; log 'chat API unavailable - participant not registered' when absent).
- pythonEnv.ts: interpreter chain: setting mlview.pythonPath -> ms-python.python extension API (getActiveEnvironmentPath + resolveEnvironment inside try/catch) -> setting python.defaultInterpreterPath -> PATH probe (python, py -3, python3); each validated >= 3.10 and handshaken with '-X utf8 -m mlview --version --json'; memoized; recomputed on interpreter change; remediation quick-picks: Install MLView core (runs pip install -e <repo>/analyzer when found, else shows instructions), Select interpreter, Show output; schema-major mismatch message.
- coreClient.ts: child_process.execFile with shell:false and the absolute interpreter; argv ['-X','utf8','-m','mlview','analyze', ...paths, '--json','-','--max-files',N,'--max-nodes',N, excludes...]; env PYTHONUTF8=1 PYTHONIOENCODING=utf-8; maxBuffer 32 MB; stderr streamed to the output channel; cancellation kills the child; single-flight per scope; 400 ms debounce on save when mlview.analyzeOnSave; JSON parse + schemaVersion major check; exit-code handling per section 3 (4 = nothing analyzable -> empty state, 2 never used here, 3 = internal error shown).
- panel.ts: createWebviewPanel EXACTLY per section 4 (nonce CSP, localResourceRoots media/, no retainContextWhenHidden), HTML per amendment A5 with the missing-bundle fallback of A13; getState/setState via the webview + a WebviewPanelSerializer; guard every postMessage against disposal; handle every UiToHost type (openLocation with the workspace-containment guard and the single Range conversion of section 4, selectNode, requestRefresh, exportHtml (showSaveDialog then run 'analyze --html <file>'), copy (clipboard), saveState, action (ids: retry, selectInterpreter, showOutput, installCore), askAssistant (ignored), log); post init (theme from vscode.window.activeColorTheme.kind mapped to light/dark/hc), graph, theme on onDidChangeActiveColorTheme, stale on file change, analysisStarted/analysisFailed, revealNode / revealIssue.
- diagnostics.ts: DiagnosticCollection per the section 6 table (mlview.diagnosticSeverity), source 'MLView', code { value, target: a LOCAL rule doc Uri: <extension>/docs/rules/<CODE>.md if present else <repo>/docs/rules/<CODE>.md }, relatedInformation from relatedLocs, publish only confidence >= mlview.minConfidence and suppressed === false, per-file set with explicit clearing, clear() on workspace-folder change.
- codelens.ts ("MLView: show in diagram" above unit nodes' defLoc or loc; toggled by mlview.codeLens), revealInDiagram.ts + locationIndex.ts (cursor -> narrowest containing node by (file, line range), nearest-node fallback; sends revealNode), chat.ts (participant id 'mlview.chat' with /diagram, /issues, /explain and a free-form default; NEVER calls a language model: it answers from the local digest, streaming stream.markdown per finding followed by stream.anchor(new vscode.Location(uri, range), 'file:line'), and offers stream.button for mlview.showIssues / mlview.visualizeWorkspace; sets isSticky handled by the manifest), lmTools.ts (the three tools of section 6 with prepareInvocation + invoke, showDiagram with confirmationMessages; pure exported functions runAnalyzeTool / runListIssuesTool / runShowDiagramTool over a CoreLike interface so they are testable without VS Code), protocol.ts (typed unions of section 4 plus isUiToHost guards with unknown-type tolerance), digest.ts (<= 4 KB JSON digest: stats, lanes, top issues, truncation flag; shared by chat + tools), settings.ts, log.ts.
- package.json with ALL contributions from section 6: commands (with titles/icons/category "MLView"), keybindings, menus (editor/context, editor/title, view/title if you add a view), configuration (all settings listed in section 6 with defaults), chatParticipants (id mlview.chat, name mlview, isSticky, commands), languageModelTools (three tools, each with BOTH canBeReferencedInPrompt: true AND toolReferenceName), activationEvents ['onLanguage:python', 'workspaceContains:**/*.py', 'onWebviewPanel:mlview.diagram'], capabilities.untrustedWorkspaces { supported: 'limited' }, engines.vscode ^1.100.0; .vscodeignore; tsconfig.json (strict); esbuild.mjs; vscode-extension/.vscode/launch.json (Extension Development Host: --extensionDevelopmentPath=\${workspaceFolder} opening \${workspaceFolder}/../samples/vision_pipeline); README.md for the extension (F5 dev host, requirements, settings, commands; state plainly that the Copilot participant and LM tools are compile-verified only on this machine while the Problems-panel diagnostics are the exercised Copilot surface).
TESTS per amendment A7 in test/*.test.js with node --test and a mocked 'vscode' module (test/mock-vscode.js resolved via a Module._resolveFilename hook or by bundling the pure modules for tests with esbuild --external:vscode and aliasing): protocol round-trip + unknown-type tolerance; loc -> Range conversion; workspace-containment guard refusing an out-of-workspace path; digest <= 4 KB on a 500-node synthetic graph; CSP/HTML builder (nonce present, default-src 'none', no absolute URLs, both media Uris referenced); interpreter-resolution order with stubbed probes; diagnostic severity mapping + relatedInformation; runAnalyzeTool smoke with a stubbed core returning contracts/graph.sample.json. Also test/manifest.test.js asserting the package.json contribution shapes above. Run 'npm install', 'npm run check', 'npm run compile', 'npm test' and make them green.`

const RULES_BRIEF = (coreReport) => `${PREAMBLE}
COMPONENT: the sixteen remaining rules, their fixtures, the precision corpus, the generated rule docs, and the sample projects.
OWNERSHIP: analyzer/src/mlview/rules/**, analyzer/tests/rules/**, analyzer/tests/fixtures/**, analyzer/tests/clean/**, analyzer/tools/**, docs/rules/**, samples/**. You MAY also edit the analyzer core (ir/, core/, knowledge/, emit/) when a rule needs IR support, because the core agent has FINISHED, but every existing test in analyzer/tests/core must stay green and the frozen api.py / CLI must not change.
Read: docs/ISSUE_RULES.md section 3 (each rule's detection logic, false-positive traps, fix hint), docs/CONTRACTS.md section 3 (rule API), section 7 (fixtures + the sample plan), section 10 (A7, A8, A9, A12).
THE CORE AGENT'S REPORT (how the IR, GraphContext, registry, fixtures and tests work):
${JSON.stringify(coreReport, null, 2)}

DELIVERABLES
1. Rules MLV102, MLV103, MLV110, MLV111, MLV112, MLV202, MLV203, MLV204, MLV205, MLV301, MLV302, MLV402, MLV501, MLV602, MLV701, MLV702, grouped by family (r_leakage.py, r_data.py, r_trainloop.py, r_eval.py, r_loss.py, r_device.py, r_repro.py, r_model.py), each via @rule + ctx.issue exactly like the seeds; ghost nodes for MLV202 (optimizer.step()) and MLV301 (model.eval()); relatedLocs with the roles from the schema; evidence entries that justify the confidence; absence=True where ISSUE_RULES says so.
2. Fixtures analyzer/tests/fixtures/rules/<CODE>_bad.py / <CODE>_good.py for every rule (self-describing MLVIEW-EXPECT headers; the good fixture encodes the NEAREST false-positive trap named in ISSUE_RULES), per-rule tests through the shared conftest helper, test_no_cross_fire.py (the union of ALL good fixtures analyzed as one workspace yields zero issues), the precision corpus analyzer/tests/clean/{vanilla_torch,amp_accumulation,lightning_module,hf_trainer,sklearn_pipeline}.py written as idiomatic correct programs + test_precision.py (0 high, <= 2 medium across all of them, analyzed together and separately), test_registry_complete.py (every registered code has both fixtures, a non-empty fix hint, a severity, a rule_version and a docs/rules page; every fixture maps to a registered code), test_suppression.py (inline ignore, ignore-file, .mlview.toml), test_confidence.py (each factor in isolation, bucket boundaries, the absence cap), test_samples.py (see 4).
3. analyzer/tools/gen_rule_docs.py: writes docs/rules/<CODE>.md for every registered rule from its metadata (title, severity, frameworks, why it matters, how it is detected, false positives avoided, fix hint, a bad/good example taken from the fixtures) plus docs/rules/README.md index; run it and commit the output.
4. samples/vision_pipeline/ (config.py, data.py, model.py, train.py, sklearn_baseline.py; realistic, ~230 lines total; imports only torch / torchvision / sklearn / numpy; never executed) with EXACTLY the 15 planted issues of CONTRACTS section 7.1 (5 high / 6 medium / 4 low across 14 codes, MLV602 twice) and nothing else; samples/vision_pipeline_clean/ (same five files and structure, every defect fixed, 0 issues, >= 20 nodes); samples/vision_pipeline/expected_issues.json = sorted list of {code, severity, file, line}; samples/README.md describing every planted defect and the demo story; test_samples.py asserts the analyzer output equals expected_issues.json exactly (codes/severities/files/lines) and the clean twin yields 0/0/0 with >= 20 nodes and >= 6 present stages, and that both graphs validate against the schema (reuse contracts/validate_sample.py).
If a rule cannot be made reliable within reason, register it enabled=False with the reason in its doc page and list it in known_gaps; at least 14 of the 20 must be enabled and green, and every code planted in the sample must be enabled. Run 'PYTHONUTF8=1 python -m pytest analyzer/tests -q' (the whole analyzer suite) and make it green; also run 'PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline --format summary' and paste it in test_results.`

const PLUGIN_BRIEF = (coreReport) => `${PREAMBLE}
COMPONENT: the Claude Code host adapter plus the repository glue (sync tools, verification, build/e2e scripts, top-level README).
OWNERSHIP: claude-plugin/**, tools/**, scripts/**, .claude-plugin/marketplace.json (repo root), README.md (repo root), .mlview/ (output dir; add .mlview/.gitignore-style README). Do NOT touch samples/ (the rules agent is writing it concurrently), analyzer/, webview/, vscode-extension/.
Read: docs/CONTRACTS.md sections 3 (CLI + in-process API), 5 (MCP tools, commands, skills, plugin.json, install), 9, 10 (A1, A2, A7), docs/ARCHITECTURE.md, docs/REQUIREMENTS.md. The analyzer is installed in dev mode ('python -m mlview' works; 'from mlview.api import analyze_to_dict, AnalyzeOptions, render_html, render_mermaid, render_text, digest').
THE CORE AGENT'S REPORT:
${JSON.stringify(coreReport, null, 2)}

DELIVERABLES
1. claude-plugin/.claude-plugin/plugin.json exactly per section 5 (no component-path fields); claude-plugin/.mcp.json exactly per section 5; claude-plugin/commands/mlview.md and mlview-issues.md (YAML frontmatter: description, argument-hint, allowed-tools; body: prefer the mlview_* MCP tools when available, otherwise run the CLI through Bash exactly as section 5 shows, with $ARGUMENTS / $1 handling and a default of the current directory); claude-plugin/skills/mlview-visualize/SKILL.md and claude-plugin/skills/mlview-triage/SKILL.md (frontmatter name + description; bodies per section 5; triage never auto-edits); claude-plugin/README.md (validate, --plugin-dir, marketplace install, prerequisites Python >= 3.10 + 'pip install mcp' (v2) with the note that the CLI fallback works without mcp, how the tools work, troubleshooting on Windows).
2. claude-plugin/server/mlview_mcp.py: the MCP SDK v2 server per amendment A1 exposing exactly the five tools of section 5 with the stated input and output shapes: mlview_analyze, mlview_issues, mlview_graph (mermaid by default; 'stages' scope = only stage subgraph summaries; 'stage:<id>' = that lane; 'node:<id>' = the node with its neighbours to depth), mlview_explain (node record + in/out edges + issues + stageEvidence + a <= 60-line source segment read from absFile; or the rule doc for a code, read from docs/rules/<CODE>.md), mlview_open_diagram (render_html into MLVIEW_DATA_DIR or <project>/.mlview/report.html, open with os.startfile on Windows / webbrowser.open elsewhere, opened=false and no launch when MLVIEW_NO_OPEN=1). Default path = MLVIEW_PROJECT_DIR or cwd; resolve relative paths against it; refuse paths that do not exist with a clear isError-style message (raise ValueError so the SDK reports isError). Cache the graph per (resolved path, file-signature of mtimes+sizes) in <project>/.mlview/graph.json and return graphPath. Every result dict <= 4096 bytes when json.dumps'd (truncate lists first, set truncated:true, keep graphPath); docstrings are the tool descriptions Claude sees, so make them precise about when to call each tool. All logging to stderr. sys.path bootstrap per A1 (vendor first, then the repo's analyzer/src as the dev fallback).
3. tools/sync-assets.py (+ --check), tools/sync-core.py (copy analyzer/src/mlview -> claude-plugin/vendor/mlview, skipping __pycache__; idempotent), tools/verify.py with --parity (CLI graph vs MCP tools/call mlview_analyze graph read back from graphPath, byte-equal after stripping generatedAt and durationMs; drive the server as a subprocess through the mcp SDK client: 'from mcp.client.stdio import stdio_client, StdioServerParameters' and 'from mcp.client.session import ClientSession' or whatever the installed 2.1.1 exposes - inspect it), --hashes (sha256 equality across webview/dist, vscode-extension/media, analyzer/src/mlview/emit/assets, and generator.rendererSha in a freshly emitted document), --versions (per A2), --all; exits 1 on any failure with a table.
4. scripts/build.ps1 and scripts/build.sh (npm install + build in webview; sync-assets; sync-core; npm install + compile + check in vscode-extension; pip install -e analyzer), scripts/e2e.ps1 and scripts/e2e.sh (build -> pytest analyzer/tests -> npm test in webview -> npm test in vscode-extension -> pytest claude-plugin/tests -> analyze samples/vision_pipeline to .mlview/graph.json + .mlview/report.html and the clean twin to .mlview/report_clean.html -> tools/verify.py --all -> a PASS/FAIL table; non-zero exit on any failure). PowerShell 5.1-compatible (no && or ||; check $LASTEXITCODE after each step; set PYTHONUTF8=1 in the env). scripts/README.md.
5. claude-plugin/tests/test_mcp.py (real subprocess stdio handshake through the mcp SDK client: list tools -> assert exactly the five names with valid inputSchema objects -> call mlview_analyze on samples/vision_pipeline if it exists else analyzer/tests/fixtures -> assert not isError, structuredContent present, JSON <= 4 KB, graphPath exists; then mlview_issues and mlview_graph(format mermaid) succeed), test_digest_budget.py (a 500-node / 800-edge / 300-issue synthetic in-memory graph -> every tool's digest builder output <= 4096 bytes), test_plugin_manifest.py (plugin.json + .mcp.json shape; runs 'claude plugin validate ./claude-plugin --strict' when 'claude' is on PATH, falling back to no --strict if the flag is unknown, and asserts exit 0; skip with a message if the CLI is absent).
6. .claude-plugin/marketplace.json at the repo root with name "mlview-local", an owner, and one plugin entry {name "mlview", source "./claude-plugin", description}; check the expected shape with 'claude plugin --help' / 'claude plugin marketplace --help' and adapt.
7. README.md at the repo root: what MLView is and the 4 spec requirements it meets, quick start for both hosts (Claude Code: validate + --plugin-dir + /mlview; VS Code / Copilot: scripts/build then F5 in vscode-extension, commands, Problems panel, @mlview and #mlviewAnalyze), architecture in one diagram (mermaid) + directory map, how to run tests and e2e, honest status (Copilot compile-verified only on this machine; DiagnosticCollection is the exercised Copilot surface), known gaps.
Run 'PYTHONUTF8=1 python -m pytest claude-plugin/tests -q' -> green; run 'claude plugin validate ./claude-plugin --strict' and paste the output; run tools/sync-core.py and confirm the server starts with PYTHONPATH pointing only at vendor/.`

log('Build: core -> (rules, plugin) in parallel with viewer and extension')
const buildResults = await parallel([
  () => agent(CORE_BRIEF, { label: 'build:core', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' })
    .then(async core => {
      log(`core done (tests passing: ${core && core.all_tests_passing})`)
      const [rules, plugin] = await parallel([
        () => agent(RULES_BRIEF(core), { label: 'build:rules', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
        () => agent(PLUGIN_BRIEF(core), { label: 'build:plugin', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
      ])
      return { core, rules, plugin }
    }),
  () => agent(VIEWER_BRIEF, { label: 'build:viewer', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(VSCODE_BRIEF, { label: 'build:vscode', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
])
const reports = {
  sample,
  core: buildResults[0] && buildResults[0].core,
  rules: buildResults[0] && buildResults[0].rules,
  plugin: buildResults[0] && buildResults[0].plugin,
  viewer: buildResults[1],
  vscode: buildResults[2],
}
log(`Build reports: ${Object.entries(reports).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)

// ---------------------------------------------------------------- Phase 3: integrate
phase('Integrate')
const GATES_SCHEMA = {
  type: 'object',
  properties: {
    gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, passed: { type: 'boolean' }, output_tail: { type: 'string' } }, required: ['name', 'passed', 'output_tail'] } },
    all_passed: { type: 'boolean' },
    fixes_applied: { type: 'array', items: { type: 'string' } },
    demo_artifacts: { type: 'array', items: { type: 'string' } },
    remaining_problems: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['gates', 'all_passed', 'fixes_applied', 'demo_artifacts', 'remaining_problems', 'notes'],
}
const INTEGRATE_BRIEF = (extra) => `${PREAMBLE}
ROLE: integrator. Every component has been built by other agents (reports below). Make the whole system work end to end on this machine and leave every gate green. You may modify ANY file in the repo, but fix bugs at their source with minimal, targeted edits; never rewrite a component; never change docs/CONTRACTS.md or contracts/graph.schema.json.
${extra}
STEPS
1. Read docs/CONTRACTS.md section 10, then skim each component's report below (public_api_summary, known_gaps, notes_for_integrator, contract_change_requests). Where two components disagree on an interface, make them agree with the contract.
2. Run the build: 'powershell -ExecutionPolicy Bypass -File scripts/build.ps1' (fall back to scripts/build.sh or the individual steps if the script itself is broken; fix the script). Ensure tools/sync-assets.py copied the bundle into vscode-extension/media and analyzer/src/mlview/emit/assets and that tools/sync-core.py populated claude-plugin/vendor.
3. Run every gate and fix until green: 'PYTHONUTF8=1 python -m pytest analyzer/tests -q'; 'npm test' + 'npm run check' in webview; 'npm run check' + 'npm run compile' + 'npm test' in vscode-extension; 'PYTHONUTF8=1 python -m pytest claude-plugin/tests -q'; 'PYTHONUTF8=1 python tools/verify.py --all'; 'claude plugin validate ./claude-plugin --strict'; then 'powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1' end to end.
4. Produce the demo artifacts: 'PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline --json .mlview/graph.json --html .mlview/report.html --format summary' and the clean twin to .mlview/graph_clean.json / .mlview/report_clean.html. Confirm the HTML is self-contained (bundle present, size 100 KB - 2 MB, contains 'MLView.mount', zero http(s):// references) and that the summary lists exactly the 15 planted issues (5/6/4).
5. Render .mlview/report.html in jsdom (adapt webview/test/render_sample.mjs) and confirm: >= 20 node cards, all three marker shapes present, >= 1 ghost node, 7 lanes drawn + 1 'not detected' chip, no thrown errors in the console. Also confirm that clicking a node card in jsdom dispatches an openLocation message on the standalone bridge (stub window.location / navigation).
6. Confirm 'PYTHONUTF8=1 python -m mlview analyze --demo --json -' equals contracts/graph.sample.json byte for byte, and that the VS Code extension's webview HTML builder references media/mlview.js + media/mlview.css (which now exist).
7. Write scripts/README.md (or update it) with the gate table. Report every gate with its real output tail, every fix you applied (file + what), and anything still failing with your best diagnosis.
COMPONENT REPORTS:
${JSON.stringify(reports, null, 2)}`
let gates = await agent(INTEGRATE_BRIEF(''), { label: 'integrate:all', phase: 'Integrate', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integration: ${gates && gates.all_passed ? 'ALL GATES GREEN' : 'gates failing: ' + (gates ? gates.gates.filter(g => !g.passed).map(g => g.name).join(', ') : 'no report')}`)

// ---------------------------------------------------------------- Phase 4-6: review -> verify -> fix loop
const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          component: { enum: ['analyzer', 'webview', 'vscode-extension', 'claude-plugin', 'docs-scripts'] },
          severity: { enum: ['critical', 'major', 'minor'] },
          file: { type: 'string' },
          line: { type: 'integer' },
          title: { type: 'string' },
          detail: { type: 'string' },
          repro: { type: 'string', description: 'exact command or steps that demonstrate it, with the observed vs expected output' },
          suggested_fix: { type: 'string' },
        },
        required: ['id', 'component', 'severity', 'file', 'title', 'detail', 'repro', 'suggested_fix'],
      },
    },
    overall_assessment: { type: 'string' },
  },
  required: ['findings', 'overall_assessment'],
}
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    confirmed: { type: 'boolean' },
    reasoning: { type: 'string' },
    corrected_severity: { enum: ['critical', 'major', 'minor'] },
  },
  required: ['confirmed', 'reasoning'],
}
const LENSES = [
  { key: 'ml-accuracy', prompt: `LENS: ML analysis accuracy. Exercise the analyzer for real: run it on samples/vision_pipeline (compare against samples/vision_pipeline/expected_issues.json AND against what a senior ML engineer would flag), the clean twin, every fixture in analyzer/tests/fixtures, the precision corpus, AND on three NEW realistic scripts you write in the scratch dir (a vanilla PyTorch image classifier with validation + checkpointing; a scikit-learn pipeline with GridSearchCV and cross_val_score; a HuggingFace Trainer fine-tune). Judge: are the stages, units, ops, edges (data/call/control/config) and hierarchy faithful and readable? Are node/edge locs correct click targets (open the file and check the line/col/symbol/snippet)? False positives / false negatives against docs/ISSUE_RULES.md section 3 detection logic and traps? Ghost nodes correct? Ids stable across a whitespace edit? Determinism? Mermaid/text outputs sensible? Any crash on odd code (decorators, async, lambdas, nested functions, classes with properties, dataclasses, match statements, type hints, walrus, f-strings)?` },
  { key: 'renderer-ux', prompt: `LENS: renderer correctness, UX and visual polish. Read webview/src thoroughly, run its tests, render both contracts/graph.sample.json and the real .mlview/report.html (or .mlview/graph.json through dev/index.html) in jsdom. Check spec compliance: marker shapes exactly as the project spec (subtle symbol for low, yellow warning triangle for medium, red exclamation for high), click -> openLocation payload correctness for nodes AND edges, lineage/dimming, collapse/expand, filters, search, keyboard, ARIA, theming tokens with fallbacks for light/dark/hc, every HostToUi message handled, no innerHTML, states/banners, layout sanity (no overlaps, lane order, edges routed, back-edges, cross-lane elbows), minimap, rail/inspector content. Then judge visual quality like a product designer against docs/UX_DESIGN.md: hierarchy, spacing, typography, color usage, information density, empty/error states. STRONGLY RECOMMENDED: in the scratch dir run 'npm init -y && npm i playwright && npx playwright install chromium' (network is available), then write a script that opens file://.../.mlview/report.html at 1600x1000, waits for '.mlv-node' (or whatever the node card class is), and screenshots light and dark (emulate prefers-color-scheme), a zoomed-in crop, and the rail; view every PNG with the Read tool and critique concretely (what looks wrong, overlapping, cramped, misaligned, ugly, unreadable). Report screenshot paths in your findings.` },
  { key: 'vscode-extension', prompt: `LENS: VS Code extension correctness against the VS Code API (@types/vscode 1.100) and the contracts. Read vscode-extension/src fully; run npm run check / compile / test. Verify: activation and error paths, CSP/nonce and the webview HTML (media Uris via asWebviewUri, bootstrap mounting with MLView.bridges.vscode(), ready/graph handshake, update on re-analysis), every UiToHost message handled, the workspace-containment guard, the single Range conversion (line-1, col), diagnostics mapping + relatedInformation + code.target, chat participant + LM tools declarations (both canBeReferencedInPrompt and toolReferenceName; ids match; handler signatures), feature detection guards, interpreter chain and Windows spawn details (-X utf8, PYTHONUTF8, shell:false, absolute path, maxBuffer, kill), serializer, CodeLens, status bar, settings wiring, disposal. Simulate activation with the mocked vscode module where feasible (write a scratch script that requires out/extension.js with a mock 'vscode' and calls activate) and report any exception. Also check package.json for contribution mistakes that would make VS Code reject the manifest.` },
  { key: 'plugin-docs', prompt: `LENS: Claude Code plugin, MCP server, scripts and documentation truthfulness. Run 'claude plugin validate ./claude-plugin --strict'; drive the MCP server end to end with the mcp SDK client (all five tools; error paths: nonexistent path, a directory with no .py files, a huge synthetic graph for truncation, a path with a non-ASCII character); verify each tool result <= 4 KB, structuredContent present, graphPath valid, mermaid output parseable-looking, explain returns a source segment; check commands/skills frontmatter and body against the Claude Code plugin docs (fetch https://docs.anthropic.com/en/docs/claude-code/plugins and plugins-reference if needed), .mcp.json variable usage and env, the marketplace.json shape, vendor/ sync, scripts/build.ps1 + e2e.ps1 actually run under Windows PowerShell 5.1 (run them), tools/verify.py gates, and whether README.md / claude-plugin/README.md / vscode-extension/README.md / scripts/README.md describe what actually exists and works (flag every false or missing statement). Also check the top-level README's quick start by following it literally.` },
]

let round = 0
let allConfirmed = []
while (round < 2) {
  round++
  phase('Review')
  log(`Review round ${round}: 4 lenses`)
  const reviewResults = (await parallel(LENSES.map(l => () =>
    agent(`${PREAMBLE}
ROLE: reviewer (round ${round}). You do NOT modify any repo file (scratch files in ${SCRATCH} are fine). Find real defects and real quality problems in the built system, with reproducible evidence. Prefer fewer, verified findings over speculation; every finding must include the exact repro and the observed vs expected result. Rate severity: critical = wrong results / crash / spec requirement not met; major = clearly wrong behaviour or a visibly poor experience; minor = polish. Also list 'overall_assessment': what works well and how close the prototype is to the four spec requirements.
${l.prompt}
Integration status from the integrator: ${JSON.stringify(gates && { all_passed: gates.all_passed, remaining: gates.remaining_problems, demo_artifacts: gates.demo_artifacts })}
Previously confirmed-and-fixed findings (do not re-report unless still broken): ${JSON.stringify(allConfirmed.map(f => f.title))}`,
      { label: `review:${l.key}`, phase: 'Review', schema: FINDINGS_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
  const raw = reviewResults.flatMap(r => r.findings)
  log(`Round ${round}: ${raw.length} raw findings`)
  if (!raw.length) break

  phase('Verify')
  const order = { critical: 0, major: 1, minor: 2 }
  const toVerify = raw.filter(f => f.severity !== 'minor').sort((a, b) => order[a.severity] - order[b.severity]).slice(0, 24)
  const minors = raw.filter(f => f.severity === 'minor')
  log(`Verifying ${toVerify.length} critical/major findings (${minors.length} minors pass straight to fixers as optional)`)
  const verified = await parallel(toVerify.map(f => () =>
    parallel([0, 1, 2].map(i => () =>
      agent(`${PREAMBLE}
ROLE: independent verifier #${i + 1}. Another reviewer claims the defect below in the built MLView system. Reproduce it yourself (run the repro; read the code). Confirm ONLY if you can demonstrate it is real and matters at the stated severity; if you cannot reproduce it, or it is by design per docs/CONTRACTS.md (section 10 amendments included), or it is merely stylistic, mark confirmed=false. You may lower the severity via corrected_severity. Do not modify repo files.
CLAIM: ${JSON.stringify(f, null, 2)}`,
        { label: `verify:${f.id}:${i + 1}`, phase: 'Verify', schema: VERDICT_SCHEMA, model: 'opus', effort: 'medium' })))
      .then(vs => {
        const votes = vs.filter(Boolean)
        const yes = votes.filter(v => v.confirmed).length
        return { ...f, confirmed: yes >= 2, votes: votes.map(v => ({ confirmed: v.confirmed, reasoning: v.reasoning.slice(0, 400) })) }
      })))
  const confirmed = verified.filter(Boolean).filter(v => v.confirmed)
  log(`Round ${round}: ${confirmed.length}/${toVerify.length} findings confirmed`)
  allConfirmed.push(...confirmed)
  if (!confirmed.length && !minors.length) break

  phase('Fix')
  const byComponent = {}
  for (const f of confirmed) (byComponent[f.component] = byComponent[f.component] || []).push(f)
  const minorsBy = {}
  for (const f of minors) (minorsBy[f.component] = minorsBy[f.component] || []).push(f)
  const components = Array.from(new Set([...Object.keys(byComponent), ...Object.keys(minorsBy)]))
  const DIRS = {
    analyzer: 'analyzer/**, samples/**, docs/rules/**',
    webview: 'webview/**',
    'vscode-extension': 'vscode-extension/** (but NOT media/ - that is synced from webview/dist)',
    'claude-plugin': 'claude-plugin/**, tools/**, .claude-plugin/**',
    'docs-scripts': 'README.md, scripts/**, docs/** (never docs/CONTRACTS.md), */README.md',
  }
  const TESTS = {
    analyzer: "'PYTHONUTF8=1 python -m pytest analyzer/tests -q'",
    webview: "'npm run build && npm run check && npm test' in webview, then 'PYTHONUTF8=1 python tools/sync-assets.py' so both hosts get the new bundle",
    'vscode-extension': "'npm run check && npm run compile && npm test' in vscode-extension",
    'claude-plugin': "'PYTHONUTF8=1 python -m pytest claude-plugin/tests -q' and 'PYTHONUTF8=1 python tools/verify.py --all' and 'claude plugin validate ./claude-plugin --strict'",
    'docs-scripts': "'powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1'",
  }
  await parallel(components.map(c => () =>
    agent(`${PREAMBLE}
ROLE: fixer for component '${c}' (round ${round}). Fix every CONFIRMED finding below at its root cause; also fix the OPTIONAL minor findings when cheap and safe. OWNERSHIP for this task: ${DIRS[c] || c}. Do not touch other directories (other fixers are working there concurrently); if a fix truly requires a change elsewhere, describe it precisely in notes_for_integrator instead. Keep the contracts intact. After fixing, run ${TESTS[c] || 'the relevant tests'} and make them green; add a regression test for each confirmed finding where practical.
CONFIRMED FINDINGS:
${JSON.stringify(byComponent[c] || [], null, 2)}
OPTIONAL MINOR FINDINGS:
${JSON.stringify(minorsBy[c] || [], null, 2)}`,
      { label: `fix:${c}`, phase: 'Fix', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })))

  gates = await agent(INTEGRATE_BRIEF(`This is re-integration after fix round ${round}. The fixers may have changed the viewer bundle (re-run tools/sync-assets.py), the analyzer (re-run tools/sync-core.py), the extension and the plugin. Re-run EVERYTHING in steps 2-6 and fix any regression.`),
    { label: `integrate:round${round}`, phase: 'Fix', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
  log(`Round ${round} re-integration: ${gates && gates.all_passed ? 'ALL GATES GREEN' : 'still failing: ' + (gates ? gates.gates.filter(g => !g.passed).map(g => g.name).join(', ') : 'no report')}`)
  if (!confirmed.length) break
}

return {
  build: Object.fromEntries(Object.entries(reports).map(([k, v]) => [k, v ? { all_tests_passing: v.all_tests_passing, known_gaps: v.known_gaps, contract_change_requests: v.contract_change_requests, files: v.files_created.length } : null])),
  gates,
  confirmed_findings: allConfirmed.map(f => ({ id: f.id, component: f.component, severity: f.severity, title: f.title, file: f.file })),
  rounds: round,
}
