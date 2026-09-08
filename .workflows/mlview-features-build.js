export const meta = {
  name: 'mlview-features-build',
  description: 'Implement MLView flow animation + scoped views: 4 builders, integrator, then review/verify/fix rounds',
  phases: [
    { title: 'Build', detail: 'analyzer -> plugin, in parallel with viewer and extension', model: 'opus' },
    { title: 'Integrate', detail: 'sync assets, run every gate, demo artifacts', model: 'opus' },
    { title: 'Review', detail: '4 lenses on the real code', model: 'opus' },
    { title: 'Verify', detail: '3 verifiers per finding', model: 'opus' },
    { title: 'Fix', detail: 'one fixer per component, then re-integrate', model: 'opus' },
  ],
}

const ROOT = 'c:/Users/realm/Desktop/MLView'
const SCRATCH = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/3910569e-a804-468c-94be-b7eed7e1819e/scratchpad'

const PREAMBLE = `
You are one of several autonomous engineers adding two features to MLView, a WORKING prototype (all gates green) that statically analyzes Python ML code and renders the workflow as an interactive diagram with severity-marked issues in three hosts: a standalone HTML report, a VS Code webview panel, and a Claude Code plugin (MCP tools + slash commands).
THE TWO FEATURES (user's words): (1) "Make the flow of the diagram more visible: when hovering the cursor over a connection, highlight the connection and show the flow from outlet to inlet like an electron moving through a cable from one end to the other." (2) "Enable visualisation for only part of a codebase/repo: for example a custom defined class for train/test split, or model optimization, or evaluation on inference result."
THE DESIGN IS DECIDED. Implement it exactly: docs/FEATURES_FLOW_AND_SCOPE.md (the design, acceptance criteria F1-A*/F2-A*, demo scripts) and docs/CONTRACTS.md section 11 (the normative, additive contracts: selector grammar 11.1, projection algorithm 11.2, schema 11.3 (already applied), invariants 11.4, CLI 11.5, api 11.6, messages 11.7, renderer API 11.8, ViewState 11.9, MCP 11.10, VS Code 11.11, plugin commands 11.12, flow DOM contract 11.13, flow x scope 11.14, new gates 11.15, files that change together 11.16). Sections 0 and 10 of CONTRACTS.md still apply. Read those first, fully, then the code you touch. If a contract is impossible as written, implement the closest compliant thing and record it in contract_change_requests; never edit docs/CONTRACTS.md, contracts/graph.schema.json, contracts/graph.sample.json or docs/FEATURES_FLOW_AND_SCOPE.md.
Repo root: ${ROOT} (Windows 11; NOT a git repo; forward slashes; a pristine snapshot of the pre-feature tree is in .workflows/backup/pre-features/ for diffing). Use the Bash tool (Git Bash); PowerShell for .ps1 ('powershell -ExecutionPolicy Bypass -File ...'). Scratch: ${SCRATCH}. Python 3.13 ('python'; ALWAYS PYTHONUTF8=1; mcp 2.1.1, pytest, jsonschema installed; torch/sklearn NOT installed and never required). Node 20.9 / npm 10 (no global tsc: npx). The analyzer is installed editable ('python -m mlview'). Claude Code CLI 2.1.186 ('claude'). GitHub Copilot is not installed.
BASELINE GATES THAT MUST STAY GREEN (do not lower them; add to them): analyzer 849 passed / 2 skipped ('PYTHONUTF8=1 python -m pytest analyzer/tests -q'); webview 106 pass ('npm test' + 'npm run check' in webview); vscode-extension 149-151 pass ('npm run check', 'npm run compile', 'npm test'); claude-plugin 175 pass ('PYTHONUTF8=1 python -m pytest claude-plugin/tests -q'); 'PYTHONUTF8=1 python tools/verify.py --all'; 'claude plugin validate ./claude-plugin --strict'; 'python -m mlview analyze --demo --json -' byte-identical to contracts/graph.sample.json; 'PYTHONUTF8=1 python scripts/check_docs.py'; scripts/e2e.ps1 13 steps green. Windows-safe, offline, no innerHTML, library code never prints to stdout, files under ~600 lines (split new code into new modules rather than growing app.ts / build.py).
OWNERSHIP: create/modify files ONLY inside the directories listed in your brief; other agents work elsewhere concurrently. Keep every existing test meaningful (adjust an assertion only where CONTRACTS 11.4 / 11.15 / your brief says so, and say which).
QUALITY BAR: working software; run your build and tests and paste the real tail of the output; no stubs on the critical path; add regression tests for what you build.
FINAL ANSWER: return ONLY the structured report.
`

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    component: { type: 'string' },
    files_created: { type: 'array', items: { type: 'string' } },
    files_modified: { type: 'array', items: { type: 'string' } },
    how_to_build_and_run: { type: 'string' },
    public_api_summary: { type: 'string' },
    tests_run: { type: 'string' },
    test_results: { type: 'string' },
    all_tests_passing: { type: 'boolean' },
    baseline_counts_now: { type: 'string', description: 'the new pass counts for every suite you ran' },
    known_gaps: { type: 'array', items: { type: 'string' } },
    contract_change_requests: { type: 'array', items: { type: 'string' } },
    notes_for_integrator: { type: 'string' },
  },
  required: ['component', 'files_created', 'files_modified', 'how_to_build_and_run', 'public_api_summary', 'tests_run', 'test_results', 'all_tests_passing', 'baseline_counts_now', 'known_gaps', 'contract_change_requests', 'notes_for_integrator'],
}

const ANALYZER_BRIEF = `${PREAMBLE}
COMPONENT: analyzer core, scoped views (Feature 2, Python side) plus the parity fixture that unblocks everyone else.
OWNERSHIP: analyzer/** and contracts/scope.cases.json, contracts/scope.expected.json, contracts/validate_sample.py (the 11.4 F1 guard only). Do not touch webview/, vscode-extension/, claude-plugin/, docs/.
ORDER OF WORK
1. FIRST, within your first stretch, ship the parity fixture: implement analyzer/src/mlview/core/project.py (pure; no import of build.py/pipeline.py) per CONTRACTS 11.1 and 11.2 (parse_scope splitting on the FIRST colon; symbol: normalized to unit:; concern aliases; the five-tier unit: resolution with the case-insensitive retry; core/boundary/context roles via ancestor closure; edges kept iff both endpoints survive; issue retention = any nodeId in core OR an edgeId on a kept edge whose both endpoints are core; the single stable rotation of nodeIds; ghost pruning; stage recount with present carried through; stats recomputed; view object appended as the LAST key with scope/label/depth/counts/of/hidden/resolvedTo/ambiguous/empty; never re-sort: every output array is a subsequence of the input; --max-nodes applies BEFORE projection and is disclosed). Then analyzer/tools/gen_scope_fixtures.py that writes contracts/scope.cases.json (the 10 battery cases named in FEATURES section 7 / CONTRACTS 11.15 over the FROZEN contracts/graph.sample.json) and contracts/scope.expected.json (the full projected documents), with --check for drift. Write both files as soon as project.py is correct so the viewer agent (waiting for them) can run its parity test.
2. api.py additions per 11.6 (Scope, ScopeError with code/term/candidates, parse_scope, resolve_scope, project, scope_catalog, CONCERNS, CONCERN_ALIASES, SCOPE_KINDS; AnalyzeOptions gains scope and depth appended last with None defaults; analyze() still returns the FULL graph; analyze_to_dict() projects when a scope is set; render_html gains the two defaulted params and sets data-mlview-scope / data-mlview-depth on the root div while embedding the FULL graph; digest gains an optional scope block).
3. cli.py per 11.5: --scope / --depth on analyze, issues, render; --list-scopes on analyze (the catalogue is the requested payload, exit 0); ScopeError -> exit 1 with the code, the term and the sorted <=10 candidates on stderr and a clean stdout; --scope with --demo rejected (exit 1); empty scope -> exit 0 with a valid zero-node document and view.empty true; --fail-on's stderr line names the active scope.
4. Emitters: exactly one 'scope:' line in summary/text output and one '%% scope:' comment in mermaid for a projected document; html_out embeds the full graph plus the data attributes.
5. Mandatory fixes: contracts/validate_sample.py lines ~300-301 guarded so the 'present implies nodes-or-issues' check applies only when doc.get('view') is None (11.4 F1); analyzer/tests/core/test_graph_invariants.py's present==bool(nodeCount or issues) assertion scoped to unprojected documents (11.4 F2). Every projected battery case must pass BOTH jsonschema and validate_sample.py's invariant groups.
6. Tests: analyzer/tests/core/test_project_parse.py, test_project_resolve.py (on samples/vision_pipeline: unit:train resolves to train.train alone; unit:train_test_split falls to tier 4; unit:batch_loop yields two anchors with ambiguous true; unit:Nope -> empty document exit 0), test_project.py (the exact expected sets in the work-list: concern:evaluation@1 = issues {MLV103, MLV301, MLV302} with 7 core / 7 boundary / 3 context; unit:SmallCNN = {MLV401, MLV702} with MLV401.nodeIds[0] the SmallCNN node after rotation; stage:train = {MLV201, MLV205, MLV501, MLV601}; concern:optimization = {MLV201, MLV205, MLV401, MLV501, MLV601, MLV702}; unit:sklearn_baseline.baseline = 13 nodes / 16 edges / {MLV101, MLV103, MLV602} with an empty boundary ring; subsequence property; workspace.filesAnalyzed identical scoped and unscoped) -- if the real numbers differ from these expectations, verify against the ALGORITHM in 11.2 and report the discrepancy rather than bending the algorithm; test_schema.py additions ('view' absent from analyze_to_dict(unscoped); --demo byte parity kept); test_cli.py (the full 11.5 exit table with stdout purity); test_determinism.py (two scoped runs byte-identical in-process and in a subprocess with a different PYTHONHASHSEED).
Run the whole analyzer suite and 'PYTHONUTF8=1 python -m mlview analyze --demo --json - | cmp - contracts/graph.sample.json' and paste results. In public_api_summary document the exact api.py signatures, the CLI flags, the fixture file shapes, and the project() semantics the other agents rely on.`

const VIEWER_BRIEF = `${PREAMBLE}
COMPONENT: the viewer (webview/), BOTH features -- flow animation (Feature 1, renderer-only) and the scoped view (Feature 2, client-side projection + UI).
OWNERSHIP: webview/** only. The parity fixture contracts/scope.cases.json + contracts/scope.expected.json is being written CONCURRENTLY by the analyzer agent; build everything else first and, when you reach the parity test, poll for those two files (check every few minutes; they should land within the hour). If they have not landed after a long wait, write the parity test so it skips with a clear message when the files are absent, and say so in known_gaps.
FLOW (CONTRACTS 11.13, FEATURES section 2): RoutedEdge.length as the polyline sum over points (NEVER getTotalLength; jsdom lacks it -- a source scan test asserts zero occurrences); lazily build .mlv-edge__flow (same d as .mlv-edge__path, pathLength=100), .mlv-edge__port--out at points[0] and .mlv-edge__port--in at the last point, .mlv-edge__dir chevron rotated by the route's midAngle for the static mode; canvas attributes data-motion=full|reduced (OS preference) and data-flow=motion|static|off (effective mode; static when reduced or when more than FLOW_MAX_EDGES edges are lit); hook startEdgeFlow/stopEdgeFlow into the existing edge hover intent (keeps the 400/120 ms delays and the pointer-sweep invariant); lineage BFS with per-edge hop depth and --mlv-flow-delay = min(hop,6)*90ms so a node hover streams outward/inward in order; data-stage on the edge <g> from the SOURCE node's stage; the two order-independent --mlv-flow-color rules (stage hue for .mlv-edge[data-stage]:not(.has-issue), severity colour for .mlv-edge.has-issue); one stream speed (220 px/s) with the three gaps (34 / 96 / 24 px for data / call+control:enter / control:back); config edges light but never flow; selection latches the flow (Escape stops it); keyboard e / Shift+E cycle the selected node's incident edges (focus on the hit path, pulse, announce "Connection: A to B, label"); toolbar flow toggle persisted as ViewState.flow; reduced motion handled TWICE (the flow element is never built when data-motion=reduced AND an explicit display:none !important block in a prefers-reduced-motion media query names .mlv-edge__flow) with the static substitute (2.5 px accent cable, chevron at the midpoint pointing at the inlet, hollow outlet / filled inlet, both rings); tokens per FEATURES 2.7 in styles/tokens.css (keep the contrast test green). New modules: src/render/flow.ts, src/motion.ts, src/styles/flow.css.
SCOPE (CONTRACTS 11.2 / 11.8 / 11.9 / 11.14, FEATURES section 3): port core/project.py's algorithm to src/scope/project.ts LINE-FOR-LINE from the normative text in 11.2 (filter-only, never re-sort, one stable rotation, view object identical in shape); src/scope/selector.ts (parse/format the 11.1 grammar, same error codes) and src/scope/catalog.ts (the scopable units list with counts); split App.setGraph into setGraph(full) + applyProjection() so chrome/rail/outline/minimap/layout all scope with no further edits; MLViewApp.setScope(spec, depth?) / getScope(); mount() reads data-mlview-scope / data-mlview-depth off the root element (the 3-arg mount signature and the A4 bootstrap stay frozen); handle the setScope host message and post scopeChanged {spec, depth, label, nodes, of} (field named spec, never scope); the breadcrumb chip in the toolbar ('Scoped to X - depth N - A of B nodes' with a clear button; new src/ui/breadcrumb.ts); the scope picker (new src/ui/scopepicker.ts): the four concern presets with live counts, the units catalogue with search, depth 0/1/2, entered from the toolbar button, from a search result row ('Scope to this'), and from the inspector ('Scope to this unit'); boundary cards dashed with the --mlv-fg-boundary token and NO severity badge; context nodes as empty frames; the rail's 'A of B findings shown - C outside this scope - Show all' line; the FOURTH empty state (scope resolved to nothing) and the scope-empty canvas state; FIX layout/model.ts:87 so a lane is drawn only when it has drawn roots while a view is present, and surface excluded-but-present stages as a 'not in this scope' chip row; keys s (open picker) / Shift+S (clear) / [ and ] (depth); the ONE Escape cascade: sheet -> focus mode -> scope -> selection -> blur; ViewState gains scope/depth/flow and round-trips through both bridges.
COMPOSITION (11.14): clear every flow element and --mlv-flow-* property on re-projection; a lineage stream requires BOTH endpoints viewRole core (boundary-touching edges only light); a direct hover/selection pulses any drawn edge; e/Shift+E iterate only routes in the current projection.
TESTS (add to webview/test; keep the existing 106 green): flow.test.mjs (pulse element identity and port coordinates; pulseDurationMs values per FEATURES 2.7; per-hop delays; config edges lit but never flowing; latched selection survives with no pointer; a 150-node/300-edge synthetic hub hover yields data-flow=static with zero .is-flowing and >120 .is-lit; the reduced-motion case with a FULL matchMedia stub installed before mount asserting data-motion=reduced, zero .mlv-edge__flow, one .mlv-edge__dir with a rotate transform; the positive case with matches false); bundle.test.mjs additions (dist/mlview.css has a prefers-reduced-motion block naming mlv-edge__flow; zero getTotalLength in src); scope.test.mjs (no empty lane band under concern:evaluation; breadcrumb text; rail hidden-count line; fourth empty state; ViewState round-trip); scope_parity.test.mjs (all cases of contracts/scope.cases.json deep-compared to contracts/scope.expected.json: node/edge/issue id lists in order, issue.nodeIds order, every viewRole, all eight stage rows, stats, the whole view object); a composition test (scope -> relayout -> hover an edge inside (flow renders); hover a node whose lineage crosses the boundary; clear scope leaves no flow element or --mlv-flow-* property). Re-run layout.test.mjs's 150-node perf assertion with a scope applied. Update dev/index.html so it also demonstrates a scope (a query-string or a select) and test/render_report.mjs to accept --scope for the integrator. Run npm run build, npm run check, npm test; paste the tail.`

const VSCODE_BRIEF = `${PREAMBLE}
COMPONENT: the VS Code extension (Feature 2 host commands + protocol additions). Feature 1 needs no host change.
OWNERSHIP: vscode-extension/** only. src/diagnostics.ts, src/chat.ts and src/lmTools.ts MUST have no diff (a scope never changes the Problems panel, the status-bar count or the issue quick pick).
Implement CONTRACTS 11.7 and 11.11: findEnclosingUnit(index, file, line) in src/locationIndex.ts (run the existing findNodeAtLine, then climb parent to the narrowest ancestor with level unit or stage; carry parent and qualname into IndexedNodeInfo); new src/scopeCommands.ts (~90 lines, mirroring revealInDiagram.ts) with mlview.scopeToSymbol ('MLView: Scope Diagram to Symbol', icon $(list-tree), keybinding alt+shift+m when editorTextFocus && editorLangId == python, editor/context group mlview@3) and mlview.clearScope ('MLView: Clear Diagram Scope', icon $(clear-all)), both ending in panel.postSetScope(spec) and opening/creating the panel first when needed; when no enclosing unit exists show the existing 'no node here' toast and never guess; panel.ts gains postSetScope and an onScopeChanged handler that sets the panel title to 'MLView - <label>' (use the em dash the codebase already uses) or the default, and the description to '<nodes> of <of> nodes'; protocol.ts accepts setScope (host->ui) and scopeChanged (ui->host) with the selector field named spec; package.json contributions (commands, keybinding, menu entries, category MLView; NO new settings); README.md of the extension documents the two commands.
TESTS (keep the 149-151 green): test/scope.test.js (findEnclosingUnit on samples/vision_pipeline/train.py:44 returns the validate() unit while the raw findNodeAtLine returns its batch loop -- run the real analyzer to get the graph, or use a committed graph fixture; mlview.scopeToSymbol against a stubbed panel posts {type:'setScope', spec:'unit:train.validate'}; mlview.clearScope posts spec null; the title/description formatter); test/protocol.test.js additions (setScope/scopeChanged round-trip; unknown type still dropped); test/manifest.test.js (both new commands carry category MLView); test/diagnostics.test.js NEW CASE (setting a scope and re-rendering leaves the publisher output byte-identical) plus a test asserting src/diagnostics.ts is byte-identical to .workflows/backup/pre-features/vscode-extension/src/diagnostics.ts. Run npm run check, npm run compile, npm test; paste the tail.`

const PLUGIN_BRIEF = (analyzerReport) => `${PREAMBLE}
COMPONENT: the Claude Code plugin (MCP + commands + skill), the gate wiring, and the docs.
OWNERSHIP: claude-plugin/**, tools/**, scripts/**, docs/UX_DESIGN.md, docs/STATUS.md, README.md. Never edit docs/CONTRACTS.md, docs/FEATURES_FLOW_AND_SCOPE.md, docs/REQUIREMENTS.md, contracts/.
THE ANALYZER AGENT HAS FINISHED; its report (api signatures, fixture shapes, project() semantics):
${JSON.stringify(analyzerReport, null, 2)}
Implement CONTRACTS 11.10 and 11.12: STILL EXACTLY FIVE MCP TOOLS. mlview_graph's scope accepts the full 11.1 grammar on top of today's forms and gains the catalogue value 'units' (rows {nodeId, label, qualname, file, line, nodeCount, maxSeverity} sorted (-nodeCount, file, line, qualname), shed to fit the 4 KB budget); mlview_analyze, mlview_issues and mlview_open_diagram gain optional scope and depth; extend mlview_graph's docstring in the same edit so it names every accepted value; the existing view helpers in claude-plugin/server become thin delegating wrappers over mlview.core.project (wrapped, not deleted); the analysis cache is NEVER keyed on scope and graphPath keeps pointing at the FULL document; every scoped result keeps the filtered-view note and adds 'scope'. commands/mlview.md frontmatter argument-hint '[path] [--scope <SPEC>] [--depth <0-2>]' with the scope fragment omitted entirely when absent so the unscoped Bash fallback is unchanged; mlview-issues.md likewise; skills/mlview-visualize/SKILL.md gains a 'When to scope' section (questions about evaluation -> concern:evaluation, about a class -> unit:<name>, 'review this project' -> NO scope). tools/verify.py gains --scopes (run analyzer/tools/gen_scope_fixtures.py --check, then the viewer parity test 'node --test test/scope_parity.test.mjs' in webview) wired into --all; scripts/e2e.ps1 and e2e.sh gain the step between the CLI-vs-MCP parity gate and the bundle-hash gate, plus scoped demo artifacts (.mlview/split.html for unit:train_test_split, .mlview/optimization.html for concern:optimization, .mlview/evaluation.html for concern:evaluation) and a jsdom render check of one of them with 'node test/render_report.mjs --scope ...' if the viewer added that flag (else skip with a message). Run tools/sync-core.py so vendor/ carries the new core. Docs: docs/UX_DESIGN.md sections on the toolbar/breadcrumb/keyboard updated (the Breadcrumb is now built), docs/STATUS.md and README.md gain the two features (how to hover for flow, how to scope from the CLI, MCP, VS Code and the report; the demo commands), scripts/README.md gate table rows added; keep 'PYTHONUTF8=1 python scripts/check_docs.py' green.
TESTS (keep the 175 green): claude-plugin/tests/test_scope_grammar.py (mlview_graph {scope:'units'} <= 4096 bytes with the documented row shape; a scoped mlview_analyze digest carries the scope block; the error text names every accepted form; CLI-vs-MCP parity on three selectors). EXACTLY the existing tests that assert an exact node set for scope:'stage:<id>' may move to the one-node superset the ancestor closure adds (verify on samples/vision_pipeline: stage:train 9 -> 10 nodes); node:<id> at depth 1 must stay byte-identical to today. Run the plugin suite, 'claude plugin validate ./claude-plugin --strict', tools/verify.py --all, check_docs.py; paste the tails.`

phase('Build')
log('Build: analyzer -> plugin, in parallel with viewer and extension (all Opus)')
const built = await parallel([
  () => agent(ANALYZER_BRIEF, { label: 'build:analyzer', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' })
    .then(async analyzer => {
      log(`analyzer done (passing: ${analyzer && analyzer.all_tests_passing})`)
      const plugin = await agent(PLUGIN_BRIEF(analyzer), { label: 'build:plugin-docs', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })
      return { analyzer, plugin }
    }),
  () => agent(VIEWER_BRIEF, { label: 'build:viewer', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(VSCODE_BRIEF, { label: 'build:vscode', phase: 'Build', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
])
const reports = { analyzer: built[0] && built[0].analyzer, plugin: built[0] && built[0].plugin, viewer: built[1], vscode: built[2] }
log(`Build reports: ${Object.entries(reports).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)

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
ROLE: integrator. The four components are built (reports below). Make the whole system work end to end and leave every gate green. You may modify ANY file except the frozen ones (docs/CONTRACTS.md, docs/FEATURES_FLOW_AND_SCOPE.md, contracts/graph.schema.json, contracts/graph.sample.json); fix at the source with minimal edits; never rewrite a component.
${extra}
STEPS: 1) Read the reports' notes_for_integrator and contract_change_requests. 2) 'PYTHONUTF8=1 python tools/sync-assets.py' (the viewer bundle changed) and 'PYTHONUTF8=1 python tools/sync-core.py'. 3) Run and fix until green: analyzer suite; webview npm test + check; extension check/compile/test; plugin suite; 'PYTHONUTF8=1 python tools/verify.py --all' (now including --scopes); 'claude plugin validate ./claude-plugin --strict'; 'PYTHONUTF8=1 python scripts/check_docs.py'; 'powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1'. 4) Golden parity: 'python -m mlview analyze --demo --json -' byte-identical to contracts/graph.sample.json. 5) Demo artifacts: regenerate .mlview/report.html (unscoped) and the three scoped reports (.mlview/split.html unit:train_test_split, .mlview/optimization.html concern:optimization, .mlview/evaluation.html concern:evaluation); confirm each is self-contained and renders in jsdom (webview/test/render_report.mjs) with the expected core/boundary/context counts from the analyzer tests and the breadcrumb text; confirm hovering an edge in jsdom creates .mlv-edge__flow + both ports (data-flow=motion) and that with a reduced-motion matchMedia stub it creates .mlv-edge__dir instead. 6) Visual check: in ${SCRATCH}/../../841f2125-7fe4-4d10-ba34-a40b1ee16a5e/scratchpad there is a working playwright + chromium install (node_modules/playwright; see shoot.mjs there); write a script that opens .mlview/report.html at 1600x1000, hovers the train_loader -> batch loop edge (find an .mlv-edge__hit inside the data->train route, or hover the train_loader card), waits 600 ms, screenshots to ${SCRATCH}/shots/flow-hover.png; then opens .mlview/split.html and .mlview/evaluation.html and screenshots each; view the PNGs with the Read tool and fix anything visibly wrong (overlaps, missing ports, empty bands, unreadable breadcrumb). 7) Update scripts/README.md's gate table with the new rows and docs/STATUS.md counts. Report every gate with real output, every fix, and the screenshot paths.
COMPONENT REPORTS:
${JSON.stringify(reports, null, 2)}`
phase('Integrate')
let gates = await agent(INTEGRATE_BRIEF(''), { label: 'integrate:all', phase: 'Integrate', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integration: ${gates && gates.all_passed ? 'ALL GATES GREEN' : 'failing: ' + (gates ? gates.gates.filter(g => !g.passed).map(g => g.name).join(', ') : 'no report')}`)

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, component: { enum: ['analyzer', 'webview', 'vscode-extension', 'claude-plugin', 'docs-scripts'] }, severity: { enum: ['critical', 'major', 'minor'] }, file: { type: 'string' }, line: { type: 'integer' }, title: { type: 'string' }, detail: { type: 'string' }, repro: { type: 'string' }, suggested_fix: { type: 'string' } }, required: ['id', 'component', 'severity', 'file', 'title', 'detail', 'repro', 'suggested_fix'] } },
    overall_assessment: { type: 'string' },
  },
  required: ['findings', 'overall_assessment'],
}
const VERDICT_SCHEMA = { type: 'object', properties: { confirmed: { type: 'boolean' }, reasoning: { type: 'string' }, corrected_severity: { enum: ['critical', 'major', 'minor'] } }, required: ['confirmed', 'reasoning'] }
const LENSES = [
  { key: 'flow-ux', prompt: `LENS: Feature 1, flow animation, as a motion designer + front-end reviewer. Read webview/src/render/flow.ts, motion.ts, styles/flow.css, edges.ts, trace.ts, canvasview.ts and the tests. Judge against FEATURES section 2 and CONTRACTS 11.13/11.14: is the flow visibly from outlet to inlet on every edge kind (direction correct on back-edges and cross-lane elbows), do the port dots sit on the card faces, does node hover stream in hop order, do issue edges run severity-coloured, does selection latch and Escape stop, does e/Shift+E cycle edges with announcements, does the toggle persist, is reduced motion a true substitute (nothing frozen mid-path), is the FLOW_MAX_EDGES fallback sane, any leaked flow elements after scope changes, performance on 300 edges, and is it beautiful. Use the playwright install in the older scratchpad (see the integrator's script in ${SCRATCH}) to hover edges and nodes in .mlview/report.html, take screenshots (light and dark, plus a mid-animation frame and the reduced-motion variant via emulateMedia reducedMotion 'reduce'), view them with Read, and critique concretely.` },
  { key: 'scope-semantics', prompt: `LENS: Feature 2 semantics, as the ML-tooling architect. Exercise the CLI on samples/vision_pipeline with every selector kind (unit: by qualname / bare name / node id, stage:, file:, concern:, node:, symbol: alias, bad selectors, ambiguous names, empty scopes, depth 0/1/2, --list-scopes), on the clean twin, and on two new realistic scripts you write in scratch (a project with a custom SplitStrategy class used from two places; a project with a separate evaluate.py that consumes saved predictions). Check the projection against CONTRACTS 11.2 literally (roles, ancestor closure, edge rule, issue retention + rotation, ghost pruning, stage recount with present carried through, view counts and hidden edge counts, subsequence property, stats, --max-nodes disclosure), the exit table 11.5, stdout purity, determinism, the Python-vs-TypeScript parity fixture (regenerate it and compare; try a case NOT in the battery by running both implementations yourself), the MCP tools (units catalogue, scoped analyze/issues/open_diagram, error text, cache not keyed on scope), and whether the user's three examples (custom split class, model optimization, evaluation on inference results) produce a useful, honest view.` },
  { key: 'hosts', prompt: `LENS: hosts and documentation. VS Code: read scopeCommands.ts, locationIndex.ts changes, panel.ts, protocol.ts, package.json; run check/compile/test; simulate activation with the mocked vscode module and drive mlview.scopeToSymbol from a cursor inside samples/vision_pipeline/train.py's validate loop; confirm diagnostics.ts/chat.ts/lmTools.ts are byte-identical to the pre-feature snapshot (.workflows/backup/pre-features); confirm the panel title/description update on scopeChanged and the webview bootstrap still mounts unscoped. Claude Code: 'claude plugin validate' strict; drive the MCP server with the SDK client for scoped calls and the units catalogue; check the slash command argument grammar and the skill's 'When to scope' guidance; verify README.md / docs/STATUS.md / scripts/README.md / claude-plugin/README.md / vscode-extension/README.md / docs/UX_DESIGN.md describe what exists (follow the quick starts literally); run scripts/e2e.ps1 under Windows PowerShell 5.1 and scripts/e2e.sh under Git Bash.` },
  { key: 'regressions', prompt: `LENS: regressions and contract compliance. Diff the tree against .workflows/backup/pre-features (ignore node_modules, dist, out, vendor, __pycache__, .mlview) and review every changed file for unintended behaviour changes to the PRE-EXISTING features: unscoped analysis output byte-identical to before for samples/vision_pipeline and the clean twin (generate both from the backup's analyzer copy via PYTHONPATH and compare after stripping generatedAt/durationMs and rendererSha); --demo golden parity; the unscoped report renders identically in jsdom (node/edge/issue id sets); existing keyboard shortcuts unchanged; existing tests not weakened (list every assertion that was changed or deleted and judge whether CONTRACTS 11.4/11.15 sanctioned it); schema additions optional-only; tools/verify.py --all; sync hashes; file sizes under the guideline; no innerHTML/getTotalLength/external URLs; CRLF/UTF-8 safety; no stray files in the repo root; the artifact-era leftovers under .mlview (g.json, graph-*.json) not referenced by anything.` },
]

let round = 0
const allConfirmed = []
while (round < 2) {
  round++
  phase('Review')
  const reviews = (await parallel(LENSES.map(l => () =>
    agent(`${PREAMBLE}
ROLE: reviewer (round ${round}). You do NOT modify any repo file (scratch files are fine). Find real defects and real quality problems with reproducible evidence; every finding needs the exact repro and observed vs expected. Severity: critical = wrong results / crash / a requested behaviour missing; major = clearly wrong behaviour or a visibly poor experience; minor = polish. Also give overall_assessment: how well do the two features deliver what the user asked for.
${l.prompt}
Integration status: ${JSON.stringify(gates && { all_passed: gates.all_passed, remaining: gates.remaining_problems, demo_artifacts: gates.demo_artifacts })}
Previously confirmed-and-fixed findings (do not re-report unless still broken): ${JSON.stringify(allConfirmed.map(f => f.title))}`,
      { label: `review:${l.key}`, phase: 'Review', schema: FINDINGS_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
  const raw = reviews.flatMap(r => r.findings)
  log(`Round ${round}: ${raw.length} raw findings`)
  if (!raw.length) break

  phase('Verify')
  const order = { critical: 0, major: 1, minor: 2 }
  const toVerify = raw.filter(f => f.severity !== 'minor').sort((a, b) => order[a.severity] - order[b.severity]).slice(0, 24)
  const minors = raw.filter(f => f.severity === 'minor')
  const verified = await parallel(toVerify.map(f => () =>
    parallel([0, 1, 2].map(i => () =>
      agent(`${PREAMBLE}
ROLE: independent verifier #${i + 1}. Another reviewer claims the defect below. Reproduce it yourself (run the repro; read the code). Confirm ONLY if you can demonstrate it is real and matters at the stated severity; if you cannot reproduce it, or it is by design per docs/CONTRACTS.md section 11 or docs/FEATURES_FLOW_AND_SCOPE.md, or it is stylistic, mark confirmed=false. You may lower the severity. Do not modify repo files.
CLAIM: ${JSON.stringify(f, null, 2)}`,
        { label: `verify:${f.id}:${i + 1}`, phase: 'Verify', schema: VERDICT_SCHEMA, model: 'opus', effort: 'medium' })))
      .then(vs => { const votes = vs.filter(Boolean); return { ...f, confirmed: votes.filter(v => v.confirmed).length >= 2 } })))
  const confirmed = verified.filter(Boolean).filter(v => v.confirmed)
  log(`Round ${round}: ${confirmed.length}/${toVerify.length} confirmed`)
  allConfirmed.push(...confirmed)
  if (!confirmed.length && !minors.length) break

  phase('Fix')
  const byComponent = {}, minorsBy = {}
  for (const f of confirmed) (byComponent[f.component] = byComponent[f.component] || []).push(f)
  for (const f of minors) (minorsBy[f.component] = minorsBy[f.component] || []).push(f)
  const components = Array.from(new Set([...Object.keys(byComponent), ...Object.keys(minorsBy)]))
  const DIRS = {
    analyzer: 'analyzer/**, contracts/scope.cases.json, contracts/scope.expected.json, contracts/validate_sample.py, samples/**',
    webview: 'webview/**',
    'vscode-extension': 'vscode-extension/** (not media/, which is synced)',
    'claude-plugin': 'claude-plugin/**, tools/**',
    'docs-scripts': 'README.md, scripts/**, docs/STATUS.md, docs/UX_DESIGN.md, */README.md',
  }
  const TESTS = {
    analyzer: "'PYTHONUTF8=1 python -m pytest analyzer/tests -q' and 'PYTHONUTF8=1 python analyzer/tools/gen_scope_fixtures.py' (regenerate the fixture if the projection changed, and say so)",
    webview: "'npm run build && npm run check && npm test' in webview",
    'vscode-extension': "'npm run check && npm run compile && npm test' in vscode-extension",
    'claude-plugin': "'PYTHONUTF8=1 python -m pytest claude-plugin/tests -q', 'PYTHONUTF8=1 python tools/verify.py --all', 'claude plugin validate ./claude-plugin --strict'",
    'docs-scripts': "'PYTHONUTF8=1 python scripts/check_docs.py' and 'powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1'",
  }
  await parallel(components.map(c => () =>
    agent(`${PREAMBLE}
ROLE: fixer for component '${c}' (round ${round}). Fix every CONFIRMED finding at its root cause; fix the OPTIONAL minors when cheap and safe. OWNERSHIP for this task: ${DIRS[c] || c}; other fixers work concurrently elsewhere; if a fix needs a change outside your ownership, describe it precisely in notes_for_integrator. Keep the contracts intact. After fixing run ${TESTS[c] || 'the relevant tests'} and make them green; add a regression test per confirmed finding where practical.
CONFIRMED FINDINGS:
${JSON.stringify(byComponent[c] || [], null, 2)}
OPTIONAL MINOR FINDINGS:
${JSON.stringify(minorsBy[c] || [], null, 2)}`,
      { label: `fix:${c}`, phase: 'Fix', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })))
  gates = await agent(INTEGRATE_BRIEF(`This is re-integration after fix round ${round}: fixers may have changed the viewer bundle (re-run sync-assets), the analyzer (re-run sync-core and regenerate the scope fixture if the projection changed), the extension and the plugin. Re-run EVERYTHING in steps 2-6 and fix regressions.`),
    { label: `integrate:round${round}`, phase: 'Fix', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
  log(`Round ${round} re-integration: ${gates && gates.all_passed ? 'ALL GATES GREEN' : 'failing: ' + (gates ? gates.gates.filter(g => !g.passed).map(g => g.name).join(', ') : 'no report')}`)
  if (!confirmed.length) break
}

return {
  build: Object.fromEntries(Object.entries(reports).map(([k, v]) => [k, v ? { all_tests_passing: v.all_tests_passing, counts: v.baseline_counts_now, known_gaps: v.known_gaps, contract_change_requests: v.contract_change_requests } : null])),
  gates,
  confirmed_findings: allConfirmed.map(f => ({ id: f.id, component: f.component, severity: f.severity, title: f.title })),
  rounds: round,
}
