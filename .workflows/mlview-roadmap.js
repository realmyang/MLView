export const meta = {
  name: 'mlview-roadmap',
  description: 'Audit the shipped MLView implementation and propose prioritized new features and optimizations, written as docs/ROADMAP.md plus an artifact page',
  phases: [
    { title: 'Audit', detail: '5 auditors, each measuring one area of the real code', model: 'opus' },
    { title: 'Judge', detail: '2 judges rank every proposal by value / effort / risk', model: 'opus' },
    { title: 'Synthesize', detail: 'docs/ROADMAP.md + roadmap.html artifact source', model: 'opus' },
  ],
}

const ROOT = 'c:/Users/realm/Desktop/MLView'
const SCRATCH = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/3910569e-a804-468c-94be-b7eed7e1819e/scratchpad'
const PW = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/841f2125-7fe4-4d10-ba34-a40b1ee16a5e/scratchpad'

const CONTEXT = `
MLView is a working prototype (every gate green) that statically analyzes Python ML code (PyTorch + scikit-learn rules; Keras/HF/Lightning recognised at node level) and renders the workflow as an interactive diagram with severity-marked issues, in three hosts: a standalone HTML report, a VS Code extension (webview panel, Problems-panel diagnostics, CodeLens, Copilot chat participant + 3 language-model tools, compile-verified only because Copilot is not installed here), and a Claude Code plugin (5 MCP tools, /mlview + /mlview-issues commands, 2 skills). Features shipped so far: 20 issue rules with confidence buckets, ghost nodes, hover flow animation (dot charge outlet->inlet, lineage streams), scoped views (unit:/stage:/file:/concern:/node: with depth, same projection in Python and TypeScript with a parity gate), safe deep links. Repo root: ${ROOT} (Windows; not git; forward slashes). Read README.md, docs/STATUS.md (known gaps + history), docs/REQUIREMENTS.md (P1/P2 items designed but not built, section 5 non-goals, 6.2 cut list), docs/ISSUE_RULES.md section 4 (later-tier rule sketches), docs/FEATURES_FLOW_AND_SCOPE.md section 10 (cut list), docs/CONTRACTS.md (sections 10 and 11 amendments), scripts/README.md (gate table), and the code you audit. Environment: Python 3.13 (ALWAYS PYTHONUTF8=1; torch/sklearn NOT installed and never required), Node 20.9, 'python -m mlview' installed editable, a working Playwright + Chromium at ${PW}/node_modules (driver examples: ${PW}/shoot.mjs, ${SCRATCH}/shots_integrator.mjs). Scratch dir for anything you generate: ${SCRATCH}/audit. Do NOT modify any repo file. Do NOT run scripts/e2e.ps1 or build.ps1 (they rewrite artifacts); running tests, the CLI, node test scripts and Playwright is fine.
GOAL OF THIS ROUND: the user asked "Review and propose new features to add / optimization over the existing features/implementation". Your proposals must be grounded in what you measured or observed in the real system (cite file:line, commands and numbers), not generic advice. Rate each proposal's user value (1-5), effort (S = a few hours for one agent, M = one agent-day, L = multi-agent build), risk, and dependencies, and say what evidence motivates it.
`

const PROPOSALS_SCHEMA = {
  type: 'object',
  properties: {
    area: { type: 'string' },
    assessment: { type: 'string', description: 'markdown: strengths and weaknesses of this area as shipped, with evidence (measurements, file:line, screenshots you took)' },
    measurements: { type: 'array', items: { type: 'object', properties: { what: { type: 'string' }, how: { type: 'string' }, result: { type: 'string' } }, required: ['what', 'how', 'result'] } },
    proposals: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          title: { type: 'string' },
          kind: { enum: ['new-feature', 'optimization', 'quality', 'developer-experience'] },
          problem: { type: 'string', description: 'the observed gap, with evidence' },
          proposal: { type: 'string', description: 'what to build/change, concretely (contracts, files, algorithm, UX)' },
          user_value: { type: 'integer', minimum: 1, maximum: 5 },
          effort: { enum: ['S', 'M', 'L'] },
          risk: { type: 'string' },
          dependencies: { type: 'array', items: { type: 'string' } },
          acceptance: { type: 'string' },
        },
        required: ['id', 'title', 'kind', 'problem', 'proposal', 'user_value', 'effort', 'risk', 'dependencies', 'acceptance'],
      },
    },
  },
  required: ['area', 'assessment', 'measurements', 'proposals'],
}

const AREAS = [
  { key: 'analysis', prompt: `AREA: analysis depth and accuracy (analyzer/). Measure, do not guess: run the analyzer on samples/vision_pipeline, the clean twin, the precision corpus, and on at least FOUR new realistic projects you write in scratch: (a) a HuggingFace Trainer fine-tune with a custom collator and a datasets pipeline, (b) a PyTorch Lightning project with LightningDataModule and callbacks, (c) a Keras/TensorFlow classifier with tf.data, (d) a multi-file research repo with Hydra-style config (cfg.model.name), a registry via getattr, a custom Dataset subclass in a subpackage, a time-series split, and mixed precision + gradient accumulation. Tabulate: nodes/edges/stages recovered vs what a human would draw; unknown/dynamic nodes; false positives/negatives against docs/ISSUE_RULES.md sections 3 and 4; which of the later-tier rules in section 4 (MLV8xx/9xx, notebooks, distributed) would have fired usefully; cross-file resolution limits (the known one-hop import walk; 'import config; config.X' unresolved); confidence calibration. Also test robustness on odd syntax (async, decorators, match, dataclasses, nested functions, lambdas, comprehensions) and report crashes or silent drops. Propose: new rule families, framework tiers (Keras/HF/Lightning rules), deeper dataflow (inter-procedural, attribute constants, config resolution), notebook support (.ipynb cell analysis with execution-order caveats), and accuracy tooling (a labelled corpus + precision/recall report in CI).` },
  { key: 'viewer', prompt: `AREA: the diagram viewer (webview/), UX and visual quality. Use Playwright (from ${PW}) on .mlview/report.html, the three scoped reports, and a LARGE graph: generate one by analyzing a synthetic 40-file / 300+ node project you write in scratch (or by concatenating the samples several times under different module names) and rendering it with 'python -m mlview analyze <dir> --html'. Take screenshots at 1600x1000 and 1280x800, light and dark, with the rail open and closed; view them with Read and critique as a product designer: layout quality (edge crossings, label overlaps such as the X_scaled/X_test/X_train labels near lane borders, long vertical gutters, minimap occlusion, lane heights, empty space), readability at first paint, collapse defaults on big graphs, LOD behaviour when zoomed out, information density in the rail, discoverability of features (scope picker, flow toggle, keyboard), and time-to-first-paint / layout time for the large graph (measure in the browser with performance.now around mount). Propose: layout improvements (crossing minimisation across lanes, label placement, edge bundling, orthogonal routing tweaks), a diff/compare view (dirty vs clean or before/after a commit), play-the-pipeline walkthrough, SVG/PNG export, sticky notes/annotations, a legend, better search (fuzzy, file:line), a 'what changed since last analysis' banner with node-level diff, minimap improvements, touch/trackpad gestures, and any accessibility gaps you find by running the keyboard-only path.` },
  { key: 'hosts', prompt: `AREA: host integration and workflow fit (vscode-extension/, claude-plugin/). Read the extension and plugin code; run their tests; drive the MCP server with the SDK client; try the slash commands' argument grammar. Evaluate against how ML engineers actually work: PR review (diff-aware analysis: only issues introduced by the change; SARIF output for GitHub code scanning; a GitHub Action / pre-commit hook), continuous feedback (watch mode / incremental re-analysis on save with caching; analysisProgress frames which the viewer already handles but the CLI never emits), fixes (VS Code code actions / quick fixes for mechanical rules such as adding zero_grad, model.eval(), seeds; Claude Code triage skill producing patches with user confirmation), notebooks in VS Code, Copilot agent-mode tools (scope input on the LM tools, cut earlier), the chat participant's usefulness without a model, multi-root workspaces, remote/WSL path mapping, settings surface (baseline file, disabled rules, severity gating), status bar, CodeLens value, the plugin's hooks (a PostToolUse hook that re-analyzes after Claude edits a file), marketplace packaging (PyPI wheel for the analyzer, VSIX publishing, plugin marketplace), and telemetry-free usage. Propose concrete, contract-compatible features with the exact command/tool/setting names.` },
  { key: 'performance', prompt: `AREA: performance, scalability and engineering health. MEASURE: (1) analyzer wall time and peak memory on samples/vision_pipeline and on synthetic repos you generate of 50, 200 and 500 files (use realistic file sizes, 100-400 lines, mixed torch/sklearn), with 'python -X importtime' for startup and cProfile for the hot spots (ingest, symbols, bindings, rules, emit); (2) the JSON and HTML sizes vs node count and the --max-nodes behaviour; (3) viewer: layout time and time-to-interactive for 45, 150 and 400-node graphs in headless Chromium (performance.now around MLView.mount, and the layout.test perf assertion), bundle size (dist/mlview.js 143 KB+ and css), memory; (4) MCP tool latency for repeated calls (cache hits vs misses); (5) test-suite runtimes per component and the e2e total; (6) code health: files over the 600-line guideline (app.ts 959, canvasview.ts 662, build.py 675, chrome.css 606, and others), duplicated logic, dead code, TODOs, the two-language projection maintenance cost, test flakiness risks (timing-based tests), Windows-only assumptions in scripts, missing CI. Propose optimizations with expected gains (e.g. parallel file parsing, AST caching keyed by file hash, incremental re-analysis, lazy rule evaluation, worker-thread layout in the viewer, virtualised rail lists, bundle splitting or minification settings), refactors that reduce risk, a CI pipeline design (GitHub Actions matrix: Windows/Linux/macOS, Python 3.10-3.13, Node 20/22), and packaging.` },
  { key: 'practitioner', prompt: `AREA: the ML practitioner's daily use. Put yourself in the shoes of the four personas in docs/REQUIREMENTS.md section 2 and walk the actual product: run the CLI, open the report in Chromium via Playwright, use the scope picker, read the issue messages and fix hints, try the rule docs, try the clean-vs-dirty comparison, try Claude Code's /mlview on a fresh small project you write (you may run 'claude --plugin-dir <abs>/claude-plugin -p "..." --model sonnet' ONCE if it works headlessly; if it needs interaction, skip and say so). Judge: does it answer the four reviewer questions of REQUIREMENTS section 1 within 90 seconds; are messages actionable; is confidence understandable; what is missing for adoption on a real team (baseline/ratchet for legacy code, suppression UX in the UI, team config, rule severity policy, custom user rules in a simple DSL/YAML, experiment-tracking integration such as MLflow/W&B detection, data-card/model-card export, an 'explain this pipeline' narrative generated by the host LLM from the graph, onboarding/tutorial, sample gallery, VS Code walkthrough). Also collect the small papercuts you hit. Propose features ranked by what would make you keep the tool installed.` },
]

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    ranking: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' }, tier: { enum: ['now', 'next', 'later', 'drop'] }, score: { type: 'number' }, why: { type: 'string' } }, required: ['id', 'title', 'tier', 'score', 'why'] } },
    merged_or_conflicting: { type: 'string', description: 'proposals that overlap or conflict across areas and how to resolve' },
    quick_wins: { type: 'array', items: { type: 'string' } },
    strategic_bets: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['ranking', 'merged_or_conflicting', 'quick_wins', 'strategic_bets', 'notes'],
}

const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    files_written: { type: 'array', items: { type: 'string' } },
    headline_assessment: { type: 'string' },
    now: { type: 'array', items: { type: 'string' } },
    next: { type: 'array', items: { type: 'string' } },
    later: { type: 'array', items: { type: 'string' } },
    key_measurements: { type: 'array', items: { type: 'string' } },
  },
  required: ['files_written', 'headline_assessment', 'now', 'next', 'later', 'key_measurements'],
}

phase('Audit')
const audits = (await parallel(AREAS.map(a => () =>
  agent(`${CONTEXT}\n${a.prompt}\n\nReturn 6-12 proposals for your area, each grounded in evidence, plus your measurements table. Do not write repo files.`,
    { label: `audit:${a.key}`, phase: 'Audit', schema: PROPOSALS_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
log(`Audits: ${audits.length}/5, proposals: ${audits.reduce((n, a) => n + a.proposals.length, 0)}`)

phase('Judge')
const LENSES = [
  'Judge as the PRODUCT OWNER of MLView: rank by value to the four personas and by demo/adoption impact; be ruthless about generic advice without evidence; prefer proposals that compound (e.g. incremental analysis enables watch mode enables PR review).',
  'Judge as the TECH LEAD who will build these with autonomous agents: rank by effort/risk realism, contract compatibility (docs/CONTRACTS.md sections 10-11), the existing green gates, and whether each proposal has a crisp acceptance test; flag proposals that would destabilise the two-language projection or the frozen schema.',
]
const judges = (await parallel(LENSES.map((lens, i) => () =>
  agent(`${CONTEXT}\n${lens}\n\nScore every proposal 1-10 and assign a tier: now (next sprint), next, later, drop. Merge duplicates across areas; note conflicts. List the top quick wins (S effort, value >= 4) and the strategic bets (L effort, value 5).\n\nAUDITS:\n${JSON.stringify(audits, null, 2)}`,
    { label: `judge:${i + 1}`, phase: 'Judge', schema: JUDGE_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
log(`Judges: ${judges.length}/2`)

phase('Synthesize')
const synth = await agent(`${CONTEXT}
YOUR JOB: write the final review + roadmap from the audits and the judges' rankings. You are the only writer in this phase; you may create exactly two files.

1. ${ROOT}/docs/ROADMAP.md — structure: (a) Executive summary (10 lines: what MLView is good at today, its three biggest weaknesses with evidence, the recommended next sprint). (b) Current-state assessment by area (analysis, viewer, hosts, performance/engineering, practitioner fit), each with a strengths/weaknesses table and the measurements the auditors took (real numbers, commands). (c) Prioritised proposals in three tiers — NOW (quick wins + the one strategic bet to start), NEXT, LATER — each proposal with: id, title, kind, the problem with evidence, the proposal (concrete: contracts touched, files/modules, algorithm/UX), user value, effort S/M/L, risk, dependencies, acceptance criteria. Merge duplicates; drop what both judges dropped (list them in a short 'Considered and not recommended' section with one-line reasons). (d) Optimizations section with expected gains and how to measure them. (e) A suggested 'Sprint 3' plan: 4-6 items that fit one multi-agent build session, with the gates to add. (f) Risks and open questions for the user to decide. Keep it crisp: tables for rankings, one paragraph per proposal, ~1200-2000 lines max is fine but every line must carry information.

2. ${SCRATCH}/roadmap.html — an artifact page presenting the SAME content for review on the web. Rules (they are enforced by the artifact host): NO <!doctype>, <html>, <head> or <body> tags — start the file with <title>MLView Roadmap</title> then a <style> block then the content; no external scripts, stylesheets, fonts or images (inline everything; system font stack only); no innerHTML in any script (prefer no script at all; a small vanilla script for tier filtering and collapsible sections is fine, built with createElement/textContent). Design brief (a utilitarian, well-composed engineering document, not a marketing page): tokens on bare :root for the full light palette, a @media (prefers-color-scheme: dark) block guarded as :root:not([data-theme="light"]) redefining only the tokens, and a :root[data-theme="dark"] block redefining them again; body sets background and color from the tokens; a slightly cool grey neutral (not pure grey), one accent (deep teal #0E7C85 light / #2DC5D0 dark, matching MLView's data-stage hue), semantic colours for tiers (now / next / later) and for effort chips; type: system UI stack, a 1.25 modular scale, headings with text-wrap: balance, running text at ~68ch, tabular-nums for numbers, uppercase eyebrow labels with letter-spacing for tiers; layout: a sticky left mini-TOC on wide screens (>= 1100px) collapsing to a top list on narrow ones, tables in overflow-x:auto containers, proposal cards as a single consistent object (title row with id + tier chip + effort chip + value dots; then problem / proposal / acceptance as labelled paragraphs), a measurements table per area, a compact 'Sprint 3' checklist; visible focus rings; prefers-reduced-motion respected; nothing hidden behind scroll-triggered animation. Write real content only (from the audits), no placeholders.

Return the structured summary.

JUDGES:
${JSON.stringify(judges, null, 2)}

AUDITS:
${JSON.stringify(audits, null, 2)}`,
  { label: 'synthesize:roadmap', phase: 'Synthesize', schema: SYNTH_SCHEMA, model: 'opus', effort: 'xhigh' })

return { audits: audits.map(a => ({ area: a.area, proposals: a.proposals.length, measurements: a.measurements.length })), judges: judges.length, synth }
