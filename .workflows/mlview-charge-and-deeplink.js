export const meta = {
  name: 'mlview-charge-and-deeplink',
  description: 'Viewer fixes: dot-with-halo flow charge on hover, and safe vscode:// deep links that never replace the page; then gates, screenshots, sandboxed-iframe repro, review',
  phases: [
    { title: 'Implement', detail: 'one viewer engineer: charge + deep-link safety + tests + contract addenda', model: 'opus' },
    { title: 'Integrate', detail: 'sync bundle, every gate, screenshots, sandboxed-iframe repro', model: 'opus' },
    { title: 'Review', detail: '2 lenses', model: 'opus' },
    { title: 'Verify', detail: '3 verifiers per finding', model: 'opus' },
    { title: 'Fix', detail: 'fix + re-integrate', model: 'opus' },
  ],
}

const ROOT = 'c:/Users/realm/Desktop/MLView'
const SCRATCH = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/3910569e-a804-468c-94be-b7eed7e1819e/scratchpad'
const PW = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/841f2125-7fe4-4d10-ba34-a40b1ee16a5e/scratchpad'

const PREAMBLE = `
MLView is a working prototype (all gates green) that statically analyzes Python ML code and renders the workflow as an interactive diagram in three hosts: a standalone HTML report, a VS Code webview, and a Claude Code plugin. The viewer bundle lives in webview/ (TypeScript, esbuild, tests with node --test + jsdom); its contract is docs/CONTRACTS.md (sections 0, 4, 8, 10, 11 — 11.13 is the flow DOM contract) and its design is docs/FEATURES_FLOW_AND_SCOPE.md section 2 (flow) and docs/UX_DESIGN.md.
Repo root: ${ROOT} (Windows 11; NOT a git repo; forward slashes). Bash tool (Git Bash); PowerShell for .ps1. Scratch: ${SCRATCH}. Python 3.13 with PYTHONUTF8=1 always. Node 20.9 (npx for tsc). A working Playwright + Chromium install exists at ${PW}/node_modules (see ${PW}/shoot.mjs and ${SCRATCH}/shots_integrator.mjs for driver examples); use it from that directory.
BASELINE GATES THAT MUST STAY GREEN: webview 'npm run build && npm run check && npm test' (208 tests); analyzer 'PYTHONUTF8=1 python -m pytest analyzer/tests -q' (1075); extension 'npm run check && npm run compile && npm test' (180); plugin 'PYTHONUTF8=1 python -m pytest claude-plugin/tests -q' (231); 'PYTHONUTF8=1 python tools/verify.py --all' (9 gates; the renderer-hash rows require 'PYTHONUTF8=1 python tools/sync-assets.py' after any bundle change); 'powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1' (17 steps); 'PYTHONUTF8=1 python scripts/check_docs.py'. Rules: no innerHTML, no getTotalLength (jsdom lacks it), no SVG filter primitives on animated elements (repaint cost; see the header comment of webview/src/styles/flow.css), respect prefers-reduced-motion, keep files under ~600 lines, Windows-safe, offline.
THE USER'S TWO REQUESTS (verbatim): (1) "When a single connection is highlighted by cursor hovering, for the moving charge along the cable, make it more clear by changing the charge representation from a line to a dot with some hue around it." (2) "The go-to button in Issues seems to be not working properly in the example live diagram. When I click on one of them, it's empty with a message: This content is blocked. Contact the site owner to fix the issue." — the live diagram is the standalone report embedded in a sandboxed iframe on claude.ai; webview/src/bridges.ts openInEditor (around line 141-165) performs a same-frame anchor click to vscode://file/..., which the sandbox blocks by replacing the frame with the browser's blocked-content page. The same path serves the Issues rail go-to button, the Inspector 'Open file:line' button, related-location links, and node/edge clicks.
FINAL ANSWER: return ONLY the structured report.
`

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    component: { type: 'string' },
    files_created: { type: 'array', items: { type: 'string' } },
    files_modified: { type: 'array', items: { type: 'string' } },
    what_changed: { type: 'string' },
    tests_run: { type: 'string' },
    test_results: { type: 'string' },
    all_tests_passing: { type: 'boolean' },
    known_gaps: { type: 'array', items: { type: 'string' } },
    notes_for_integrator: { type: 'string' },
  },
  required: ['component', 'files_created', 'files_modified', 'what_changed', 'tests_run', 'test_results', 'all_tests_passing', 'known_gaps', 'notes_for_integrator'],
}

const IMPLEMENT_BRIEF = `${PREAMBLE}
ROLE: viewer engineer. OWNERSHIP: webview/** plus APPEND-ONLY additions to docs/CONTRACTS.md (a new '### 11.13.1 Charge representation (2026-09-08)' right after 11.13's content and a new '### 11.17 Standalone deep-link safety (2026-09-08)' at the end of section 11), a short amendment paragraph in docs/FEATURES_FLOW_AND_SCOPE.md section 2 (charge shape + deep-link behaviour), and the matching lines in docs/UX_DESIGN.md if it describes the charge or the standalone click. Do not touch analyzer/, vscode-extension/, claude-plugin/, contracts/.

PART 1 — THE CHARGE IS A DOT WITH A HALO (direct hover and latched selection, i.e. the 'is-flowing--pulse' mode in webview/src/render/flow.ts).
- Replace the moving dash segment with a travelling dot: a <g class="mlv-edge__charge"> containing three concentric circles built with createElementNS: .mlv-edge__charge-halo (r 9, fill var(--mlv-flow-color), fill-opacity ~0.18), .mlv-edge__charge-glow (r 5.5, fill var(--mlv-flow-color), fill-opacity ~0.42) and .mlv-edge__charge-core (r 2.6, fill var(--mlv-surface), stroke var(--mlv-flow-color), stroke-width 1.6). NO SVG filters (feGaussianBlur is banned by flow.css's header for repaint cost); a soft edge comes from the stacked opacities, or from ONE radialGradient paint server defined once per edge layer if you prefer it, never per edge.
- Motion: SMIL <animateMotion dur="<pulseDurationMs(route.length)>ms" repeatCount="indefinite" calcMode="linear" rotate="auto"> with <mpath href="#<id>"/> referencing the edge's visible .mlv-edge__path. Give every .mlv-edge__path a unique id 'mlv-p-<mountSerial>-<edgeId hex>' (a per-mount serial so dev/states.html, which mounts several apps on one page, never collides); set both 'href' and 'xlink:href' on mpath for compatibility. For routes longer than ~360 px add a second charge with begin="-<dur/2>ms" so the cable never looks empty. The cable itself keeps its existing hover highlight; the old full-length .mlv-edge__flow element is no longer built in pulse mode (or is kept only as a static faint underlay if you find that reads better — decide and say why).
- Colour rules stay: stage hue for .mlv-edge[data-stage]:not(.has-issue), severity colour for .mlv-edge.has-issue (the softmax-before-CrossEntropyLoss edge must run RED). Tokens in styles/tokens.css and styles/flow.css; keep contrast.test.mjs green.
- The multi-edge lineage stream ('is-flowing') stays as it is (dash stream, hop-staggered) — the user's request is about the single hovered connection. If, and only if, switching streams to dots is cheap and stays under the perf assertion (150 nodes / 300 edges), you may do it; otherwise leave it and note it.
- Reduced motion: no charge is ever built under data-motion="reduced"; the static chevron substitute is unchanged. Also guard: if the SVG has no route length (0), build nothing.
- stripEdge must remove .mlv-edge__charge groups and there must be no leaked charge after unhover, selection change, scope change (11.14 C1) or destroy().
- Tests (webview/test/flow.test.mjs and a new charge.test.mjs): the hovered edge gets exactly one (or two, for long routes) .mlv-edge__charge groups with the three circles; the animateMotion's dur equals pulseDurationMs(route.length) and its mpath href equals '#' + the path's id; the path id is unique across two mounts on one document; unhover strips everything; reduced motion builds no charge; no getTotalLength; bundle hygiene unchanged; dist/mlview.css still has the prefers-reduced-motion block.

PART 2 — DEEP LINKS NEVER REPLACE THE PAGE (webview/src/bridges.ts, StandaloneBridge).
- Rewrite openInEditor so that the document is NEVER navigated: no anchor.click() on a same-frame link, no location.href assignment.
- Determine the context once per call: embedded = (window.self !== window.top) (wrap in try/catch; a cross-origin access error counts as embedded); local = location.protocol === 'file:'.
- If embedded OR not local: do not attempt the vscode:// launch. Copy 'file:line' to the clipboard (the existing copyText with its verified-promise semantics) and show the toast 'Copied file:line — open the report locally to jump into VS Code'; in the toast also render an anchor (createElement, textContent) 'Open in VS Code' with href = the vscode://file/... deep link, target="_blank", rel="noopener noreferrer", so a browser that allows the protocol can still launch it (a sandbox without allow-popups blocks it silently instead of replacing the frame).
- If top-level AND local: launch through a hidden iframe (createElement('iframe'), hidden, aria-hidden, src = the vscode:// deep link, appended to document.body and removed after ~1500 ms) — this triggers the OS protocol handler without ever navigating the report — and keep the existing blur-based detection: if no blur within 400 ms, copy 'file:line' and toast as today.
- Export the pure decision helper (e.g. deepLinkPlan({embedded, local, absFile, file, line, col}) -> {mode:'copy'|'launch', url, copyText, toast}) so it is unit-testable without a DOM.
- Tests (webview/test/bridges.test.mjs or the existing bridge tests): jsdom with window.top stubbed to a different object -> no iframe or anchor navigation, clipboard called with 'file:line', toast present with the 'Open in VS Code' anchor whose href is the deep link and target _blank; top-level + file: -> a hidden iframe with the vscode:// src is appended and later removed, document.location unchanged; top-level + http: -> copy-only; parity.test.mjs (both bridges yield identical id sets) still green.
Also update dev/index.html so it demonstrates both (it is opened over file: locally) and make sure webview/test/render_report.mjs still passes.

Run 'npm run build', 'npm run check', 'npm test' in webview (all 208 + your new tests green) and paste the tail. In what_changed describe the DOM shape of the charge and the exact deep-link decision table.`

phase('Implement')
const impl = await agent(IMPLEMENT_BRIEF, { label: 'implement:viewer', phase: 'Implement', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Implementation: ${impl && impl.all_tests_passing ? 'green' : 'RED'}`)

const GATES_SCHEMA = {
  type: 'object',
  properties: {
    gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, passed: { type: 'boolean' }, output_tail: { type: 'string' } }, required: ['name', 'passed', 'output_tail'] } },
    all_passed: { type: 'boolean' },
    fixes_applied: { type: 'array', items: { type: 'string' } },
    screenshots: { type: 'array', items: { type: 'string' } },
    iframe_repro: { type: 'string', description: 'what happened when the Issues go-to button was clicked inside a sandboxed iframe, before/after' },
    remaining_problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['gates', 'all_passed', 'fixes_applied', 'screenshots', 'iframe_repro', 'remaining_problems'],
}
const INTEGRATE_BRIEF = (extra) => `${PREAMBLE}
ROLE: integrator. The viewer engineer's report: ${JSON.stringify(impl, null, 2)}
${extra}
STEPS: 1) 'PYTHONUTF8=1 python tools/sync-assets.py' then 'PYTHONUTF8=1 python tools/sync-core.py'. 2) Run every baseline gate listed above and fix anything red at its source (you may edit any file except docs/CONTRACTS.md, docs/FEATURES_FLOW_AND_SCOPE.md, contracts/graph.schema.json, contracts/graph.sample.json). 3) Regenerate the demo artifacts: 'PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline --json .mlview/graph.json --html .mlview/report.html' plus the clean twin and the three scoped reports as scripts/e2e.ps1 does (running e2e.ps1 does all of it). 4) Playwright, from ${PW}: (a) open file:///C:/Users/realm/Desktop/MLView/.mlview/report.html at 1600x1000, hover the edge from train_loader to the batch loop (the .mlv-edge__hit of the edge whose data-edge-id matches the data edge labelled train_loader; fall back to hovering any data edge), wait 350 ms, screenshot ${SCRATCH}/shots/charge-hover.png and a 2x clip around the charge to charge-closeup.png; take a second frame 300 ms later to prove the dot moved (compare the charge group's getBoundingClientRect between frames; report the delta); repeat in dark (colorScheme dark) and hover the SmallCNN -> criterion edge to confirm the charge is red; (b) THE USER'S REPRO: write ${SCRATCH}/embed.html containing <iframe sandbox="allow-scripts allow-same-origin" style="width:1500px;height:900px" src="file:///C:/Users/realm/Desktop/MLView/.mlview/report.html"></iframe>, open it, inside the frame click the first Issues go-to button (.mlv-issue__open or the button next to an issue row), wait 700 ms, assert the frame still contains .mlv-root and shows a toast whose text starts with 'Copied' and contains an anchor 'Open in VS Code', and that frame.url() is still the report (not about:blank or a chrome-error page); screenshot to ${SCRATCH}/shots/embed-after-click.png; also do the same at the top level (open the report directly, click the go-to button, assert page.url() unchanged and that a hidden iframe with a vscode:// src was created or a toast appeared); (c) view every PNG with the Read tool and fix anything visibly wrong (charge invisible, off the cable, wrong colour, toast clipped). 5) Update docs/STATUS.md and scripts/README.md if counts changed. Report gates, screenshots and the iframe repro result.`
phase('Integrate')
let gates = await agent(INTEGRATE_BRIEF(''), { label: 'integrate:all', phase: 'Integrate', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integration: ${gates && gates.all_passed ? 'ALL GATES GREEN' : 'failing: ' + (gates ? gates.gates.filter(g => !g.passed).map(g => g.name).join(', ') : 'none')}`)

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, severity: { enum: ['critical', 'major', 'minor'] }, file: { type: 'string' }, title: { type: 'string' }, detail: { type: 'string' }, repro: { type: 'string' }, suggested_fix: { type: 'string' } }, required: ['id', 'severity', 'file', 'title', 'detail', 'repro', 'suggested_fix'] } },
    overall_assessment: { type: 'string' },
  },
  required: ['findings', 'overall_assessment'],
}
const VERDICT_SCHEMA = { type: 'object', properties: { confirmed: { type: 'boolean' }, reasoning: { type: 'string' } }, required: ['confirmed', 'reasoning'] }

phase('Review')
const LENSES = [
  `LENS: the charge, as a motion designer. Using Playwright from ${PW}, hover several edges of every kind (data, call, control enter, control back-edge, config, an edge with an issue) in .mlv-report.html at 1600x1000, capture frames 250 ms apart, view them with Read, and judge: is the dot clearly visible against light AND dark backgrounds, is the halo a soft hue rather than a hard disc, is it centred on the cable and does it follow elbows, does it run outlet to inlet, is the size right relative to the 1.5 px cable and 216 px cards, does a long cable get its second charge, does the red issue edge read as red, does selection latch it and Escape clear it, does hovering a node still stream the lineage without leaking charges, is anything left behind after unhover or a scope change, is reduced motion clean (emulateMedia reducedMotion 'reduce'), and any console errors. Also review webview/src/render/flow.ts and styles/flow.css for correctness (unique path ids across mounts, stripEdge completeness, no filters).`,
  `LENS: deep-link safety and regressions. Read webview/src/bridges.ts and its tests. With Playwright from ${PW}: reproduce the user's scenario in a sandboxed iframe (allow-scripts allow-same-origin; also try WITHOUT allow-same-origin and with 'allow-scripts allow-popups') clicking the Issues go-to button, the Inspector 'Open' button, a related-location link, a node card and an edge; assert the frame never leaves the report and a toast with the 'Open in VS Code' anchor appears; at the top level over file:, assert the page never navigates and the hidden iframe launch is attempted then removed; check clipboard behaviour when navigator.clipboard is unavailable (legacy path) and when writeText rejects; confirm the VS Code webview bridge is untouched (vscode host still posts openLocation to the extension: run the extension tests and diff webview/src/bridges.ts's VsCodeBridge against .workflows/backup/pre-features if unchanged, otherwise justify); check docs/CONTRACTS.md 11.17 and FEATURES section 2 describe exactly what ships; run the full gate list and tools/verify.py --all.`,
]
const reviews = (await parallel(LENSES.map((lens, i) => () =>
  agent(`${PREAMBLE}
ROLE: reviewer. Do NOT modify repo files. Find real defects with reproducible evidence (exact repro; observed vs expected). Severity: critical = the user's request not met or a crash; major = clearly wrong behaviour or visibly poor; minor = polish.
${lens}
Integration report: ${JSON.stringify(gates && { all_passed: gates.all_passed, iframe_repro: gates.iframe_repro, screenshots: gates.screenshots, remaining: gates.remaining_problems })}`,
    { label: `review:${i + 1}`, phase: 'Review', schema: FINDINGS_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
const raw = reviews.flatMap(r => r.findings)
log(`Review: ${raw.length} raw findings`)

let confirmed = []
if (raw.length) {
  phase('Verify')
  const order = { critical: 0, major: 1, minor: 2 }
  const toVerify = raw.filter(f => f.severity !== 'minor').sort((a, b) => order[a.severity] - order[b.severity]).slice(0, 16)
  const minors = raw.filter(f => f.severity === 'minor')
  const verified = await parallel(toVerify.map(f => () =>
    parallel([0, 1, 2].map(i => () =>
      agent(`${PREAMBLE}
ROLE: independent verifier #${i + 1}. Reproduce the claimed defect yourself (run the repro, read the code). Confirm ONLY if it is real at the stated severity and not by design per docs/CONTRACTS.md 11.13.1 / 11.17 or docs/FEATURES_FLOW_AND_SCOPE.md. Do not modify repo files.
CLAIM: ${JSON.stringify(f, null, 2)}`,
        { label: `verify:${f.id}:${i + 1}`, phase: 'Verify', schema: VERDICT_SCHEMA, model: 'opus', effort: 'medium' })))
      .then(vs => ({ ...f, confirmed: vs.filter(Boolean).filter(v => v.confirmed).length >= 2 }))))
  confirmed = verified.filter(Boolean).filter(v => v.confirmed)
  log(`Verify: ${confirmed.length}/${toVerify.length} confirmed, ${minors.length} minors`)
  if (confirmed.length || minors.length) {
    phase('Fix')
    await agent(`${PREAMBLE}
ROLE: fixer. Fix every CONFIRMED finding at its root cause and the OPTIONAL minors when cheap. OWNERSHIP: webview/** and the append-only doc sections named above; if a fix needs another directory, describe it precisely in notes_for_integrator. After fixing run 'npm run build && npm run check && npm test' in webview and 'PYTHONUTF8=1 python tools/sync-assets.py'; add a regression test per confirmed finding.
CONFIRMED: ${JSON.stringify(confirmed, null, 2)}
OPTIONAL MINORS: ${JSON.stringify(minors, null, 2)}`,
      { label: 'fix:viewer', phase: 'Fix', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })
    gates = await agent(INTEGRATE_BRIEF('This is re-integration after the fix round: re-sync assets, re-run EVERY gate, regenerate the demo artifacts, redo the screenshots and the sandboxed-iframe repro.'),
      { label: 'integrate:round1', phase: 'Fix', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
    log(`Re-integration: ${gates && gates.all_passed ? 'ALL GATES GREEN' : 'failing: ' + (gates ? gates.gates.filter(g => !g.passed).map(g => g.name).join(', ') : 'none')}`)
  }
}

return { impl: impl && { passing: impl.all_tests_passing, what_changed: impl.what_changed, gaps: impl.known_gaps }, gates, confirmed: confirmed.map(f => ({ id: f.id, severity: f.severity, title: f.title })), assessments: reviews.map(r => r.overall_assessment) }
