export const meta = {
  name: 'mlview-features-design',
  description: 'Refine two MLView features (edge flow animation on hover; scoped/partial visualization) into a design, contract amendments and a build work-list',
  phases: [
    { title: 'Propose', detail: '4 proposers grounded in the real code', model: 'opus' },
    { title: 'Judge', detail: '2 judges score every proposal', model: 'opus' },
    { title: 'Synthesize', detail: 'design doc + CONTRACTS section 11 + schema additions + work-list', model: 'opus' },
  ],
}

const ROOT = 'c:/Users/realm/Desktop/MLView'
const CONTEXT = `
MLView is a working prototype (all gates green) that statically analyzes Python ML code and renders the workflow as an interactive diagram with severity-marked issues, in three hosts: a standalone HTML report, a VS Code webview panel (with Copilot chat participant + LM tools), and a Claude Code plugin (MCP tools + slash commands). Repo root: ${ROOT} (Windows; not a git repo; forward slashes). Read docs/CONTRACTS.md (section 10 amendments override the rest), docs/UX_DESIGN.md, docs/REQUIREMENTS.md, contracts/graph.schema.json, and the code you need. Run things if it helps (PYTHONUTF8=1 python -m mlview ..., npm test in webview, node webview/test/render_report.mjs). Do NOT modify any repo file; scratch files go under C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/3910569e-a804-468c-94be-b7eed7e1819e/scratchpad.

Key code (line counts): webview/src/render/edges.ts (127; builds each edge as an SVG <g class="mlv-edge mlv-edge--<kind>"> with .mlv-edge__hit, .mlv-edge__path, arrow marker, .mlv-edge-label), render/trace.ts (68; lineage lighting via .is-lit on nodes/edges), canvasview.ts (573; hover/select/focus, applyTrace, reduced-motion check at line 46), layout/routing.ts (534; orthogonal routes), styles/edge.css and canvas.css (dimming under .is-tracing/.is-focusing), app.ts (696; controller), ui/rail.ts (issues/inspector/outline), ui/chrome.ts (toolbar, stage chips, filters), filters.ts, search.ts, types.ts, protocol.ts, bridges.ts; analyzer/src/mlview/core/{build.py,graph.py,pipeline.py,views.py}, cli.py (analyze options incl. --include/--exclude/--max-nodes), api.py (frozen AnalyzeOptions/analyze/analyze_to_dict/render_*/digest), emit/{json_out,html_out,mermaid_out,text_out}.py; vscode-extension/src/{extension,commands,panel,protocol,chat,lmTools,digest,locationIndex,revealInDiagram}.ts and package.json contributions; claude-plugin/server/mlview_mcp.py (mlview_graph already accepts scope="stages"|"stage:<id>"|"node:<id>" + depth), claude-plugin/commands/*.md, skills/*. Sample project: samples/vision_pipeline (45 nodes, 45 edges, 15 issues) and its clean twin.

THE TWO FEATURE REQUESTS (verbatim from the user):
1. "Make the flow of the diagram more visible: for example, when hovering the cursor over a connection, highlight the connection and shows the flow from outlet to inlet like a electron moving through a cable from one end to the other."
2. "Enable visualisation for only part of a codebase/repo. For example, visualisation over a custom defined class for train test split, or perhaps model optimization, or perhaps evaluation on inference result."
3. "For both two, think and refine what should be added/implemented before actual implementation."

LEAD CONSTRAINTS: keep the existing contracts backward compatible (schema additions must be OPTIONAL fields so every existing document still validates; hosts check the schema major only); the analysis must stay whole-workspace so cross-file resolution and workspace-wide rules keep working (a scope is a PROJECTION of the full graph, never a subset of files fed to the parser); the same projection semantics must hold in the Python core (CLI / MCP / HTML report) and in the TypeScript viewer (interactive, no round trip; the standalone report has no host), proven by a parity test; motion must respect prefers-reduced-motion; every existing test must stay green; the whole thing must be buildable by ~4 parallel agents in one session with review rounds.
`

const PROPOSAL_SCHEMA = {
  type: 'object',
  properties: {
    angle: { type: 'string' },
    summary: { type: 'string' },
    what_exists_today: { type: 'string', description: 'what you verified in the code that the design builds on (file:line references)' },
    design: { type: 'string', description: 'markdown: the refined feature design, concrete enough to implement' },
    requirements: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, priority: { enum: ['P0', 'P1', 'P2'] }, statement: { type: 'string' }, acceptance: { type: 'string' } }, required: ['id', 'priority', 'statement', 'acceptance'] } },
    contract_changes: { type: 'string', description: 'markdown: exact additions to schema / CLI / messages / renderer API / MCP / commands, each marked additive' },
    implementation_plan: { type: 'string', description: 'markdown: files to touch, new modules, algorithms, tests, per component' },
    demo_scenario: { type: 'string', description: 'how it is demonstrated on samples/vision_pipeline, with the exact symbols/stages involved' },
    risks: { type: 'array', items: { type: 'string' } },
    open_questions_decided: { type: 'array', items: { type: 'string' }, description: 'ambiguities you resolved, with the decision' },
  },
  required: ['angle', 'summary', 'what_exists_today', 'design', 'requirements', 'contract_changes', 'implementation_plan', 'demo_scenario', 'risks', 'open_questions_decided'],
}

const ANGLES = [
  { key: 'flow-ux', prompt: `YOUR ANGLE: Feature 1 only, as a motion/interaction designer and front-end engineer. Design the "flow" experience: on edge hover, highlight the connection and animate the flow from the source endpoint (outlet) to the target endpoint (inlet) like a charge moving along a cable; what the outlet and inlet on the two node cards look like while it runs (port dots, glow, label such as the variable name travelling with the pulse); what happens on NODE hover (flow along all lit lineage edges, upstream ones flowing in, downstream ones flowing out) and on selection (the flow keeps running while selected so it can be studied; Escape stops it); how direction is derived per edge kind (data producer->consumer, call caller->callee, control enter/back with 'next batch' loops, config); the SVG technique (SMIL animateMotion along the existing path via mpath, and/or CSS stroke-dashoffset 'marching charge' with a gradient; pick and justify; consider the VS Code webview and a plain browser; consider 45-edge graphs and 300-edge graphs; only lit edges animate), timing/easing/size/colour tokens (use the existing --mlv-* tokens; severity-coloured pulse on edges that carry an issue), the reduced-motion fallback (static directional gradient + arrow emphasis, no animation), a toolbar toggle to turn flow animation off, keyboard focus on an edge triggering the same, and an optional 'play the pipeline' mode that animates stage by stage in order. Write the implementation plan against the real files (edges.ts, trace.ts, canvasview.ts, edge.css, canvas.css, chrome.ts, keymap.ts) and the tests (jsdom: classes/elements/attributes; reduced-motion via a stubbed matchMedia).` },
  { key: 'scope-core', prompt: `YOUR ANGLE: Feature 2, the analyzer/core side, as the ML-tooling architect. Define the SCOPE model precisely: kinds file:<relpath>, dir:<relpath>, symbol:<qualname or bare class/function name resolved against the workspace>, stage:<id>[,<id>...], node:<id>, concern:<data|optimization|evaluation|...> (presets = stage groups such as data+preprocess, model+objective+train, eval+deliver); plus depth (boundary hops, default 1) and direction (up|down|both: upstream = what feeds the scope, downstream = what consumes it, both = neighbourhood). Specify the PROJECTION algorithm on the full MLGraph (which nodes are in-scope, which become boundary nodes, how parents/children/ghost nodes are handled, which edges are kept, which issues are kept and how counts/stage summaries/stats are recomputed, deterministic ordering, what happens when the scope resolves to nothing, ambiguous symbol names, and truncation). Decide the schema additions (optional fields only, e.g. workspace.scope {kind,target,depth,direction,nodesInScope,nodesTotal,resolvedTo} and node.boundary boolean; keep schemaVersion "1.0" or justify "1.1"), the CLI (--scope, --depth, --direction on analyze/issues/render; exit codes; what summary/mermaid/text emit for a scoped graph), the api.py additions (additive: project(graph, scope) plus a resolve_scope helper; AnalyzeOptions gains optional fields with defaults), the MCP tool changes (mlview_analyze / mlview_issues / mlview_open_diagram gain scope/depth/direction; mlview_graph's existing scope harmonised with the new grammar; a new mlview_scopes tool that lists the scopable symbols so a model can pick one), determinism and the parity test (Python projection vs the TypeScript projection on the sample graph -> identical node/edge/issue id sets for a battery of scopes), and how the demo scenario works on samples/vision_pipeline (name the real classes/functions there: read the files).` },
  { key: 'scope-ux', prompt: `YOUR ANGLE: Feature 2, the user-facing side in all three hosts, as a product designer. How does a user ENTER a scope: from the search box (a result row offers 'Scope to this'), from a node card / inspector ('Scope to this unit', 'Show what feeds this', 'Show what this feeds'), from a stage chip (alt-click or a menu: 'Only this stage'), from a 'Concerns' menu with presets (Data & splitting, Model & optimization, Evaluation & inference, Everything), from the Outline tree, and from the keyboard. What the SCOPED VIEW looks like: a scope breadcrumb chip in the toolbar ('Scoped to SplitStrategy · depth 1 · 8 of 45 nodes' with an X), boundary nodes drawn faded/dashed with an 'outside scope' treatment and a hover affordance to widen ('+1 hop'), lanes re-fitted, the issue rail showing only in-scope issues with a line 'N issues hidden outside scope (show)', the stats chips reflecting the scope, minimap, and how selection/focus/lineage interact with scope; state persistence in ViewState; the empty-scope state. Viewer implementation: a client-side projection over the full graph (the same semantics as the core; you will define the TS module and where it plugs into app.ts / layout / rail / chrome), new HostToUi 'setScope' and UiToHost 'scopeChanged' messages. VS Code: commands 'MLView: Visualize This Symbol' (cursor -> narrowest unit via locationIndex.ts), 'Visualize Current File as Scope', 'Visualize Selection', editor context-menu and CodeLens entries ('MLView: focus on this'), the panel title reflecting the scope, chat participant '/diagram <symbol|stage|concern>' and the LM tools gaining a scope input, diagnostics unaffected. Claude Code: '/mlview <path> [--scope ...]' argument grammar and the skill text telling the model when to scope (e.g. a question about evaluation -> concern:evaluation). The standalone report: scope preserved in the file name and a 'Scoped' banner. Include accessibility and the demo script on samples/vision_pipeline (read the sample files to name real targets).` },
  { key: 'lead-risk', prompt: `YOUR ANGLE: pragmatic tech lead doing the RIGHT-SIZING and risk pass for BOTH features. Read the code paths the features touch and the existing tests (webview/test, analyzer/tests, vscode-extension/test, claude-plugin/tests). Propose the minimal coherent implementation of both features that fits one build session with ~4 parallel agents (viewer, analyzer core, VS Code extension, Claude Code plugin) plus an integrator and review rounds; the exact component split and file ownership so agents do not collide (note: app.ts is 696 lines and build.py 675, near the size guideline; say where new code should live instead); the contract amendments needed in docs/CONTRACTS.md section 11 (schema optional fields, CLI flags, new messages, renderer API, MCP params, extension commands, plugin command args) written so that a coding agent can implement from them alone; the regression risks to the current gates (849 analyzer / 106 viewer / 151 extension / 175 plugin tests, e2e 13 steps, tools/verify.py parity, sync-assets hashes, the golden --demo byte parity that must not change) and the mitigations; what is P0 vs P1 vs cut; the acceptance gates to add (projection parity Python-vs-TS, reduced-motion, scope round-trip through both hosts); and a demo script for each feature on samples/vision_pipeline.` },
]

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    scores: { type: 'array', items: { type: 'object', properties: { angle: { type: 'string' }, total: { type: 'number' }, breakdown: { type: 'string' }, best_ideas: { type: 'array', items: { type: 'string' } }, flaws: { type: 'array', items: { type: 'string' } } }, required: ['angle', 'total', 'breakdown', 'best_ideas', 'flaws'] } },
    cross_cutting_notes: { type: 'string' },
    recommended_scope_cuts: { type: 'array', items: { type: 'string' } },
  },
  required: ['scores', 'cross_cutting_notes', 'recommended_scope_cuts'],
}

const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    files_written: { type: 'array', items: { type: 'string' } },
    executive_summary: { type: 'string' },
    components: { type: 'array', items: { type: 'object', properties: { key: { type: 'string' }, directories: { type: 'string' }, responsibilities: { type: 'string' }, acceptance_tests: { type: 'string' } }, required: ['key', 'directories', 'responsibilities', 'acceptance_tests'] } },
    schema_changes: { type: 'string' },
    validation_output: { type: 'string', description: 'output of validating contracts/graph.sample.json and .mlview/graph.json against the updated schema, and of the existing analyzer schema tests' },
    demo_scripts: { type: 'string' },
    decisions: { type: 'array', items: { type: 'string' } },
  },
  required: ['files_written', 'executive_summary', 'components', 'schema_changes', 'validation_output', 'demo_scripts', 'decisions'],
}

phase('Propose')
const proposals = (await parallel(ANGLES.map(a => () =>
  agent(`${CONTEXT}\n${a.prompt}\n\nGround every claim in the real code (cite file:line). Return the structured proposal. Do not write repo files.`,
    { label: `propose:${a.key}`, phase: 'Propose', schema: PROPOSAL_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
log(`Proposals: ${proposals.length}/4`)

phase('Judge')
const LENSES = [
  'Judge as the END USER, an ML engineer who asked for these two features: does the design deliver what they asked (visible flow from outlet to inlet on hover; visualising just a class / an optimization concern / an evaluation slice), is it intuitive and beautiful, does it stay consistent with the existing UI?',
  'Judge as the IMPLEMENTING TECH LEAD: is it buildable by four parallel agents in one session without breaking the green gates; are the contracts additive and precise; is the Python/TypeScript projection parity realistic; are the risks and the cuts right?',
]
const judges = (await parallel(LENSES.map((lens, i) => () =>
  agent(`${CONTEXT}\n${lens}\n\nScore each proposal on five criteria (1-10 each): fidelity to the user's request, UX quality, technical soundness against the real code, feasibility in one session, completeness. List the ideas that MUST survive and the flaws to fix. Add cross-cutting notes (conflicts between proposals and how to resolve them) and recommended scope cuts.\n\nPROPOSALS:\n${JSON.stringify(proposals, null, 2)}`,
    { label: `judge:${i + 1}`, phase: 'Judge', schema: JUDGE_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
log(`Judges: ${judges.length}/2`)

phase('Synthesize')
const synth = await agent(`${CONTEXT}
YOUR JOB: synthesize the FINAL design for both features from the proposals and the judge verdicts, then WRITE it into the repo (you are the only writer in this phase). Take the best-scored ideas, fix every flagged flaw, apply the judges' scope cuts unless a P0 depends on them, and DECIDE every ambiguity (state the decision).

WRITE:
1. docs/FEATURES_FLOW_AND_SCOPE.md: the design of both features: goals, UX (with the exact interaction table), the scope model and projection algorithm (precise, step by step, with edge cases), motion spec (technique, timings, tokens, reduced-motion), host integration (VS Code commands/menus/chat/LM tools; Claude Code commands/skills/MCP), acceptance criteria per requirement, demo scripts on samples/vision_pipeline naming real symbols, and explicit non-goals.
2. Append '## 11. Feature amendments: flow animation and scoped views (2026-09-07)' to docs/CONTRACTS.md: the frozen additive contracts a coding agent can implement from alone: schema additions (exact JSON for the new optional fields), CLI flags and exit behaviour, api.py additions, the projection semantics (normative), HostToUi/UiToHost message additions, renderer API additions (MLViewApp.setScope/getScope, mount options), ViewState additions, MCP tool parameter additions and the new tool, VS Code command ids/titles/menus/settings, plugin command argument grammar, and the new acceptance gates (including the Python-vs-TypeScript projection parity test design and the reduced-motion test). Keep section 10 intact.
3. Update contracts/graph.schema.json with the optional fields ONLY (additive; additionalProperties stays false; schemaVersion stays "1.0"), and copy it to analyzer/src/mlview/schema/graph.schema.json so test_schema_current stays green. Then VERIFY: 'PYTHONUTF8=1 python contracts/validate_sample.py' (golden still valid), 'PYTHONUTF8=1 python contracts/validate_sample.py .mlview/graph.json', and 'PYTHONUTF8=1 python -m pytest analyzer/tests/core/test_schema.py -q' (or the equivalent schema tests) must all pass; paste the outputs into validation_output. Do not change contracts/graph.sample.json.
4. Add rows to docs/REQUIREMENTS.md: under R2 a 'R2.11 Flow animation' requirement and under R1 an 'R1.12 Scoped views' requirement (P0), each with acceptance criteria, and note in section 6.1 that both are in scope as of 2026-09-07.
Return the work-list: one component per agent (viewer; analyzer core; vscode-extension; claude-plugin+docs) with directories, responsibilities and acceptance tests, plus the demo scripts.

JUDGE VERDICTS:
${JSON.stringify(judges, null, 2)}

PROPOSALS:
${JSON.stringify(proposals, null, 2)}`,
  { label: 'synthesize:features', phase: 'Synthesize', schema: SYNTH_SCHEMA, model: 'opus', effort: 'xhigh' })

return { proposals: proposals.length, judges: judges.length, synth }
