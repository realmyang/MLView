export const meta = {
  name: 'mlview-sprint3-now',
  description: 'Implement the NOW tier of docs/ROADMAP.md: CI + process, byte-identical track B, accuracy corpus, the ANA-1 re-baseline with VIEW-01, then review; commits on branch sprint3 pushed to GitHub with CI watched',
  phases: [
    { title: 'Process', detail: 'CI-01 + HEALTH-03 + HEALTH-01 regression, branch sprint3, CI green', model: 'opus' },
    { title: 'Track B', detail: 'PERF, COVERAGE, viewer S items, hosts cleanup, ANA-12 in parallel', model: 'opus' },
    { title: 'Integrate B', detail: 'gates, commit, push, CI', model: 'opus' },
    { title: 'Track A', detail: 'ANA-1 + ANA-2 + ANA-3 with VIEW-01', model: 'opus' },
    { title: 'Integrate A', detail: 're-baseline generators, gates, commit, push, CI', model: 'opus' },
    { title: 'Review', detail: '3 lenses -> verify -> fix -> integrate', model: 'opus' },
  ],
}

const ROOT = 'c:/Users/realm/Desktop/MLView'
const SCRATCH = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/3910569e-a804-468c-94be-b7eed7e1819e/scratchpad'
const PW = 'C:/Users/realm/AppData/Local/Temp/claude/c--Users-realm-Desktop-MLView/841f2125-7fe4-4d10-ba34-a40b1ee16a5e/scratchpad'

const PREAMBLE = `
You are one of several autonomous engineers executing Sprint 3 of MLView (see docs/ROADMAP.md: section (c) NOW tier, section (e) Sprint 3 sequencing and gates, section (f) decisions). MLView statically analyzes Python ML code and renders the workflow as an interactive diagram in three hosts (standalone HTML report, VS Code extension, Claude Code plugin). Everything is green today: analyzer 1075 tests, viewer 230, extension 180, plugin 231, e2e 17 steps, tools/verify.py 9/9. Contracts: docs/CONTRACTS.md (sections 0, 10, 11 bind; you may append a dated amendment ONLY where your brief says so). Repo root: ${ROOT} (Windows 11; git repo, branch main = the baseline, remote origin = https://github.com/realmyang/MLView.git, private). Use the Bash tool (Git Bash); PowerShell for .ps1. Scratch: ${SCRATCH}. Python 3.13 (ALWAYS PYTHONUTF8=1 and PYTHONDONTWRITEBYTECODE=1 in your shell; torch/sklearn never required). Node 20.9 (npx). Playwright + Chromium available at ${PW}/node_modules.
LEAD DECISIONS (final): batch all five new Diagnostic.kind values in one amendment (untagged_dataflow, single_file_analysis, unresolved_callee, config_unresolved, notebook_analyzed); ANA-12 tolerance = zero 'forbidden' findings ever, recall may only ratchet up; VIEW-01 ships with the ANA-1 re-baseline; the A6 baseline amendment, PACKAGING, notebooks and Issue.fix are NOT in this sprint; HEALTH-02 is not in this sprint. HEALTH-01's first half is already done on main (sync-core --check prunes bytecode residue; conftest sets dont_write_bytecode) — the drivers' env exports and the regression test remain.
GIT RULES (strict): ONLY agents whose brief says 'you run git' may run any git command. Everyone else never runs git (no add/commit/stash/checkout). Work happens on branch sprint3 (created by the Process agent from main). Commit messages: imperative subject, a body naming the roadmap ids, and the trailer line 'Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>'. Never force-push, never rewrite history, never touch main.
GITHUB CLI: gh is at "/c/Program Files/GitHub CLI/gh.exe" and is NOT logged in; authenticate per command via the environment: export GH_TOKEN=$(printf 'protocol=https\\nhost=github.com\\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p') — never print or log the token. Then: "$GH" run list -R realmyang/MLView --branch sprint3 --limit 5 ; "$GH" run watch <id> -R realmyang/MLView --exit-status ; "$GH" run view <id> -R realmyang/MLView --log-failed. CI COST: the repo is private (metered minutes; Windows 2x, macOS 10x): keep one push's CI under ~40 billable minutes: ubuntu jobs may fan out (Python 3.10/3.11/3.12/3.13, Node 20/22), Windows ONE job (Python 3.13 + Node 20), macOS ONE job (Python 3.13 + Node 20); use concurrency cancel-in-progress and pip/npm caching.
QUALITY BAR: working software with tests; run the gates you touch and paste real output tails; keep files under ~600 lines (split new code into new modules); no innerHTML; no getTotalLength; library code never prints to stdout; every existing test stays meaningful (an assertion may change only where the roadmap item or the re-baseline sanctions it, and you say which).
FINAL ANSWER: return ONLY the structured report.
`

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    component: { type: 'string' },
    roadmap_ids_done: { type: 'array', items: { type: 'string' } },
    files_created: { type: 'array', items: { type: 'string' } },
    files_modified: { type: 'array', items: { type: 'string' } },
    what_changed: { type: 'string' },
    tests_run: { type: 'string' },
    test_results: { type: 'string' },
    all_tests_passing: { type: 'boolean' },
    known_gaps: { type: 'array', items: { type: 'string' } },
    notes_for_integrator: { type: 'string' },
  },
  required: ['component', 'roadmap_ids_done', 'files_created', 'files_modified', 'what_changed', 'tests_run', 'test_results', 'all_tests_passing', 'known_gaps', 'notes_for_integrator'],
}
const GATES_SCHEMA = {
  type: 'object',
  properties: {
    gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, passed: { type: 'boolean' }, output_tail: { type: 'string' } }, required: ['name', 'passed', 'output_tail'] } },
    all_passed: { type: 'boolean' },
    commits: { type: 'array', items: { type: 'string' }, description: 'sha + subject of every commit you made' },
    ci: { type: 'string', description: 'the CI run ids/urls you watched and their final conclusion per job' },
    ci_green: { type: 'boolean' },
    fixes_applied: { type: 'array', items: { type: 'string' } },
    remaining_problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['gates', 'all_passed', 'commits', 'ci', 'ci_green', 'fixes_applied', 'remaining_problems'],
}

// ------------------------------------------------------------ Phase 1: process
phase('Process')
const process_ = await agent(`${PREAMBLE}
ROLE: process engineer (you run git). Roadmap items: CI-01, HEALTH-03 (read its entry wherever it sits in docs/ROADMAP.md and fold it in as your first commits), and the HEALTH-01 remainder (export PYTHONDONTWRITEBYTECODE=1 beside PYTHONUTF8=1 in scripts/build.ps1, build.sh, e2e.ps1, e2e.sh; add the regression test that runs pytest over a throwaway vendored tree and then asserts tools/sync-core.py --check is green; add claude-plugin/vendor/**/__pycache__ to .gitignore if not covered).
STEPS: 1) git checkout -b sprint3 (from main). 2) Make scripts/build.sh and scripts/e2e.sh work on Linux and macOS as well as Git Bash: detect python3 vs python, no Windows-only paths, LF endings (scripts/check_docs.py asserts LF), and a Windows-only test guard: mark the Windows-only tests in claude-plugin/tests/test_out_containment.py with pytest skipif on non-Windows (state which ones and why); give webview/test/layout.test.mjs's timing assertion a CI-safe budget (e.g. an env override MLVIEW_PERF_BUDGET_MS or a 2x budget when process.env.CI is set) without weakening it locally. 3) Write .github/workflows/ci.yml: jobs analyzer (ubuntu matrix Python 3.10-3.13: pip install -e analyzer, pytest analyzer/tests -q, python contracts/validate_sample.py, --demo byte parity), plugin (ubuntu Python 3.13: pip install mcp pytest jsonschema, pytest claude-plugin/tests -q), webview (ubuntu Node 20 and 22: npm ci, build, check, test, then a drift check that dist/ matches the committed copies via tools/sync-assets.py --check), extension (ubuntu Node 20: npm ci, check, compile, test), e2e-linux (ubuntu Python 3.13 + Node 20: sh scripts/e2e.sh), e2e-windows (windows-latest Python 3.13 + Node 20: powershell scripts/e2e.ps1), smoke-macos (macos-latest: analyzer tests + webview tests only); env PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 CI=true at workflow level; concurrency group per ref with cancel-in-progress; actions/checkout, setup-python with pip cache, setup-node with npm cache; triggers push (main, sprint3, any branch) and pull_request; a 20-minute timeout per job. Note 'claude plugin validate' is unavailable in CI and its test already skips. 4) Commit (subject 'Add GitHub Actions CI matrix and cross-platform drivers (CI-01, HEALTH-03, HEALTH-01)'), push -u origin sprint3, watch the run with gh (GH_TOKEN as instructed), read failed logs, fix, commit, push, repeat until every job is green (at most 6 iterations; if a job cannot be made green, disable it with a clear comment and say so). 5) Add the CI badge and a 'Continuous integration' section to README.md and the gate rows to scripts/README.md. Report the final run URL and per-job conclusions.`,
  { label: 'process:ci', phase: 'Process', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Process: CI green=${process_ && process_.ci_green}`)

// ------------------------------------------------------------ Phase 2: track B
phase('Track B')
const ANALYZER_B = `${PREAMBLE}
ROLE: analyzer engineer, Track B (byte-identical or additive; you do NOT run git). OWNERSHIP: analyzer/**, tools/perf_equiv.py (new), contracts/graph.schema.json + its mirror analyzer/src/mlview/schema/graph.schema.json (ONLY the Diagnostic.kind enum extension), docs/CONTRACTS.md (append '### 11.18 Diagnostic kinds and coverage diagnostics (2026-09-08)' recording the five new enum values and the two emitted now).
ITEMS (read each in docs/ROADMAP.md section (c) NOW and implement to its acceptance):
- PERF-01 + PERF-02: lru_cache knowledge.lookup (and the startswith-heavy prefix matching), a role index beside the cached _index(), id-key the two O(n^2) scans, replace build_ir.py's literal range(4) fixed-point loop with a convergence loop. OUTPUT MUST BE BYTE-IDENTICAL: write tools/perf_equiv.py that analyzes samples/vision_pipeline, samples/vision_pipeline_clean and analyzer/tests/clean, strips generator.generatedAt and stats.durationMs, and compares sha256 before/after (run it against the main-branch analyzer via a scratch copy of analyzer/src from 'git show main:...' or a copy you take BEFORE editing); add analyzer/tests/core/test_perf_budget.py (a 200-file synthetic generated in a tmp dir analyses under a ceiling that is generous on CI, e.g. 20 s, with the measured local number recorded in the test docstring). Report before/after timings at 4 / 50 / 200 files.
- COVERAGE (analyzer half): extend the Diagnostic.kind enum with the five values (one schema edit, mirrored byte-identically; contracts/validate_sample.py and any enum copies in the viewer types are the viewer agent's concern for TS, but keep contracts/graph.sample.json untouched); emit 'untagged_dataflow' when a leakage-family rule bails because a value has no ValueTag (e.g. a function parameter), naming the variable and site; emit 'single_file_analysis' when the analyzed path is a single file inside a larger package (sibling modules exist and are imported), naming how many sibling modules were not analyzed; tests for both on fixtures; the summary/text emitter prints them.
- RAIL-GROUP (CLI half): --group-by rule|file|none on 'analyze --format summary' and on 'issues' (default none so every snapshot holds), grouping with occurrence counts.
- BUILD-01 (analyzer half): enforce amendment A4's 100 KB - 2 MB band inside emit/html_out.write_html at runtime (a clear error/diagnostic when a report falls outside; the demo fallback path exempt when the bundle is absent), with a test.
- CLEANUP (analyzer bits): wire the dead --text flag on 'issues', fix suppress.py's mixed-separator path handling, warn (config_warning diagnostic) on typo'd rule codes in .mlview.toml / ignore comments, fix the 'rules --list' column alignment. Read the CLEANUP entry for the exact list and do the analyzer-owned ones.
Run 'PYTHONUTF8=1 python -m pytest analyzer/tests -q', tools/perf_equiv.py, 'python -m mlview analyze --demo --json - | cmp - contracts/graph.sample.json', validate_sample on .mlview/graph.json regenerated by you into scratch (not .mlview). Paste tails.`

const VIEWER_B = `${PREAMBLE}
ROLE: viewer engineer, Track B (render-only; you do NOT run git). OWNERSHIP: webview/** only (tools/sync-assets.py is run by the integrator, not you).
ITEMS (read each in docs/ROADMAP.md section (c) NOW; implement to acceptance):
- MLV-P6: render issue.evidence[] in the rail row detail and the Inspector (kind, detail, weight as a compact list), show the confidence chip on EVERY issue row (not only possible/speculative), and inline the rule-doc sidecar (the report already embeds nothing for docs: add a compact per-code 'why / detection / fix' section read from a JSON sidecar the analyzer will expose later — for now build it from issue.why/fixHint/message and the code, and leave a clearly named hook for a docs map) so the standalone report can answer 'why should I believe this'.
- RAIL-GROUP (rail half): a 'Group by: none | rule | file' control in the Issues rail; grouped mode shows one row per rule with an occurrence count and expands to the instances; default none; persisted in ViewState.
- VIEW-06: normalize wheel deltaMode (pixel/line/page), branch on ctrlKey (pinch-zoom on trackpads) vs plain wheel (pan), use deltaX for horizontal pan, add two-pointer pinch zoom via pointer events; keep the pixel-mode path bit-identical so existing tests pass untouched; tests for each mode with synthetic WheelEvent/PointerEvent.
- VIEW-09ab: the search box parses a pasted 'train.py:29' (file:line, also 'train.py' alone) into a node jump (narrowest node containing that line, nearest fallback), and reports search-result truncation ('showing 40 of N') instead of silently cutting.
- VIEW-10: a legend (generated from markers.ts / edge kinds / node states, opened from a toolbar button and the '?' sheet), an Overview mode (Shift+0: collapse all groups + fit), and a labelled flow toggle (text label + tooltip, not an icon-only button).
- BUILD-01 (viewer half): minify the report CSS in build.mjs with one esbuild.transform call (dist/mlview.css), and add a bundle-size ratchet to test/bundle.test.mjs (JS <= 210 KB, CSS <= 55 KB; record the current numbers).
- COVERAGE (viewer half): accept the five new Diagnostic.kind values in types.ts and render 'untagged_dataflow' / 'single_file_analysis' as banners/chips with their messages (unknown kinds still render generically).
- CLEANUP (viewer bits): whatever the CLEANUP entry assigns to the viewer.
Run 'npm run build && npm run check && npm test' in webview (230 + new tests green); render .mlview/report.html-equivalent from a scratch analyze via test/render_report.mjs; paste tails.`

const HOSTS_B = `${PREAMBLE}
ROLE: hosts engineer, Track B (you do NOT run git). OWNERSHIP: vscode-extension/** (not media/), claude-plugin/** (not vendor/), README.md, docs/STATUS.md, docs/UX_DESIGN.md.
ITEMS (read each in docs/ROADMAP.md section (c) NOW):
- COVERAGE (host half): add setting mlview.currentFileAnalysisScope with values file | package | workspace, default 'package' (analyze the containing package directory when 'Visualize (Current File)' runs, then scope the diagram to that file via the existing setScope path), and surface the analyzer's 'single_file_analysis' / 'untagged_dataflow' diagnostics in the panel banner and the status bar tooltip; the plugin's mlview_analyze docstring and the /mlview command note the same behaviour for single-file paths.
- CLEANUP (host bits): delete the two settings whose descriptions say 'Not implemented' (and their reads), set capabilities.canAskAssistant per the CLEANUP entry, document python3 in claude-plugin/.mcp.json (a comment-equivalent in README since JSON has no comments, plus a startup check in server/mlview_mcp.py that prints an actionable stderr message when 'python' resolves to a Python < 3.10), and any other host-owned lines of the CLEANUP entry.
- RAIL-GROUP (host half): pass --group-by through mlview_issues (MCP) and the /mlview-issues command argument grammar.
- Docs: README 'Known gaps' and docs/STATUS.md updated for what this track changes (keep scripts/check_docs.py green).
Run 'npm run check && npm run compile && npm test' in vscode-extension and 'PYTHONUTF8=1 python -m pytest claude-plugin/tests -q'; paste tails.`

const ACCURACY = `${PREAMBLE}
ROLE: accuracy engineer, ANA-12 (additive; you do NOT run git). OWNERSHIP: analyzer/tests/accuracy/** (new), tools/accuracy.py (new), docs/ACCURACY.md (new), and ONE new job in .github/workflows/ci.yml named 'accuracy' (append only; ubuntu, Python 3.13).
BUILD the labelled accuracy corpus per the ANA-12 entry: at least 8 realistic labelled programs (re-create the four the auditors used: HF Trainer fine-tune, Lightning module + DataModule, Keras/tf.data classifier, Hydra-style research repo with registry/getattr, time-series split, AMP + accumulation; plus the two shipped samples), each with a sidecar labels JSON: expected findings (code, file, line-or-symbol, severity) and 'forbidden' findings (codes that must NOT fire on that file). tools/accuracy.py runs the analyzer over the corpus and prints per-rule precision/recall, a graph-fidelity score (nodes/edges recovered vs a small hand-labelled expectation per program), and a confidence-calibration table (bucket vs observed precision); exits non-zero on ANY forbidden finding or when recall drops below the committed baseline in analyzer/tests/accuracy/baseline.json (recall may only ratchet up: the tool has --update-baseline). Wire it as pytest analyzer/tests/accuracy/test_accuracy.py too. Record today's baseline honestly (the auditors measured ~26% recall). Run it and paste the table.`

const trackB = await parallel([
  () => agent(ANALYZER_B, { label: 'trackB:analyzer', phase: 'Track B', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(VIEWER_B, { label: 'trackB:viewer', phase: 'Track B', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(HOSTS_B, { label: 'trackB:hosts', phase: 'Track B', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
  () => agent(ACCURACY, { label: 'trackB:accuracy', phase: 'Track B', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
])
const reportsB = { analyzer: trackB[0], viewer: trackB[1], hosts: trackB[2], accuracy: trackB[3] }
log(`Track B: ${Object.entries(reportsB).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)

const INTEGRATE = (title, extra, reports) => `${PREAMBLE}
ROLE: integrator (you run git). ${title}
${extra}
STEPS: 1) Read the reports below (notes_for_integrator, known_gaps). 2) 'PYTHONUTF8=1 python tools/sync-assets.py' and 'PYTHONUTF8=1 python tools/sync-core.py'. 3) Run and fix until green (fix at the source, minimal edits, never rewrite a component): analyzer suite; webview build/check/test; extension check/compile/test; plugin suite; 'PYTHONUTF8=1 python tools/verify.py --all'; tools/accuracy.py if present; 'PYTHONUTF8=1 python scripts/check_docs.py'; 'powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1'; 'sh scripts/e2e.sh'. 4) Regenerate demo artifacts via e2e; validate .mlview/graph.json with contracts/validate_sample.py; render the report in jsdom (webview/test/render_report.mjs). 5) Update scripts/README.md gate table and docs/STATUS.md counts. 6) git status; review the diff for stray files (scratch, __pycache__, .mlview) and never add them; git add -A; commit with the subject given in the title and a body listing the roadmap ids; git push origin sprint3; watch CI with gh (GH_TOKEN as instructed); if a job fails, read --log-failed, fix, commit ('CI: ...'), push, watch again (at most 5 iterations). Report every gate with real output, commits, and the CI conclusion per job.
COMPONENT REPORTS:
${JSON.stringify(reports, null, 2)}`

phase('Integrate B')
let gatesB = await agent(INTEGRATE("Integrate Track B and commit it as 'Track B: byte-identical perf, coverage diagnostics, viewer and host quick wins, accuracy corpus (PERF-01, PERF-02, COVERAGE, MLV-P6, RAIL-GROUP, VIEW-06, VIEW-09ab, VIEW-10, BUILD-01, CLEANUP, ANA-12)'.", 'Also confirm tools/perf_equiv.py reports byte-identical output vs main and that --demo byte parity holds.', reportsB),
  { label: 'integrate:B', phase: 'Integrate B', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate B: gates=${gatesB && gatesB.all_passed} ci=${gatesB && gatesB.ci_green}`)

// ------------------------------------------------------------ Phase 4: track A (re-baseline)
phase('Track A')
const ANALYZER_A = `${PREAMBLE}
ROLE: analyzer engineer, Track A = THE RE-BASELINE (you do NOT run git). OWNERSHIP: analyzer/**, samples/** (expected_issues.json regeneration via analyzer/tools/gen_expected_issues.py), vscode-extension/test/fixtures/vision_pipeline.graph.json (regenerate), and docs/CONTRACTS.md (append '### 11.19 Class-method ops and resolution fixes (2026-09-08)' recording the graph-shape change).
ITEMS (docs/ROADMAP.md NOW: ANA-1, ANA-2, ANA-3 — read them in full, including the measured expectations):
- ANA-1: split the CallSite.class_ir overload so ops written inside class methods become op nodes under the class unit (or under a method-level loop unit where one exists) instead of being dropped by core/build.py's early return; keep ids content-addressed and deterministic; expected: samples/vision_pipeline 45 -> ~63 nodes with the SAME 15 issues (5/6/4), the clean twin still 0 issues, analyzer/tests/clean still 0 high.
- ANA-2: resolve self.<attr>(...) through binding_of instead of fabricating torch.nn.Module.<attr>; expected: recovers MLV401 on the self.loss_fn pattern with zero regressions (add the fixture).
- ANA-3: skip the parts[:-1] trim in _relative_base for package __init__.py; expected: +edges on the multi-package fixture, two dynamic_scope diagnostics and three orphan nodes gone (add the fixture).
THEN re-baseline: run analyzer/tools/gen_expected_issues.py (the 15 issues must be unchanged; if a line moved, explain), regenerate vscode-extension/test/fixtures/vision_pipeline.graph.json from the new analyzer, update every analyzer test that asserts node/edge counts for the sample (list each), run tools/accuracy.py and record the new recall in its baseline only if it went UP (it must not go down), and make sure contracts/graph.sample.json and --demo stay byte-identical (the golden is hand-authored and must not change). Do NOT touch the scope fixtures (they are computed over the frozen golden). Run the analyzer suite, the accuracy tool and perf_equiv (which will now legitimately differ — say so). Paste tails and the before/after node/edge/issue counts for the five corpora.`

const VIEWER_A = `${PREAMBLE}
ROLE: viewer engineer, VIEW-01 (you do NOT run git). OWNERSHIP: webview/** only.
ITEM: VIEW-01 (docs/ROADMAP.md NEXT tier, pulled into this sprint because it must land with ANA-1): stop normalising every lane box to the widest lane's width (layout.ts sets lane.w = maxContentW); introduce MAX_RANK_W (a cap on a lane's rank width) so lanes wrap into multiple rank rows instead of one very wide row; make fit() land the demo at ~0.55-0.6 and a 360-node graph well above the 0.15 floor; keep every existing layout test green (deterministic, no overlap, lanes contain their nodes, back-edges outside containers, perf); add tests for the new width behaviour and a fit() regression (fit must NOT be a no-op on the shipped samples). Verify visually with Playwright at 1600x1000 and 1280x800 on a 45-node and a ~300-node graph (generate the big one by analyzing a synthetic project in scratch with 'python -m mlview analyze <dir> --html'); view the PNGs with Read and iterate until the first paint is legible. Run npm run build/check/test; paste tails and the measured fit zoom before/after.`

const trackA = await parallel([
  () => agent(ANALYZER_A, { label: 'trackA:analyzer', phase: 'Track A', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(VIEWER_A, { label: 'trackA:viewer', phase: 'Track A', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
])
const reportsA = { analyzer: trackA[0], viewer: trackA[1] }
log(`Track A: ${Object.entries(reportsA).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)

phase('Integrate A')
let gatesA = await agent(INTEGRATE("Integrate the re-baseline and commit it as 'Re-baseline: class-method ops, self-attribute resolution, package relative imports, lane width cap (ANA-1, ANA-2, ANA-3, VIEW-01)'.",
  "This is the ONE golden-family regeneration of the sprint: run every generator with --check first to see what moved (analyzer/tools/gen_expected_issues.py, gen_scope_fixtures.py, gen_rule_docs.py), regenerate what the re-baseline legitimately changes (expected_issues must keep the same 15 issues; the scope fixtures over the frozen golden must NOT change; the plugin tests asserting node counts for stage: scopes move to the new counts; vscode-extension/test/fixtures; webview/test/render_report.mjs assertions), then update the '45 nodes' figure everywhere scripts/check_docs.py's one-graph-size rule reaches (README, docs/STATUS.md, docs/ROADMAP.md measurement notes, scripts/README.md). Re-run tools/accuracy.py and update the recall baseline only upward. Take Playwright screenshots of the new first paint (light) to ${SCRATCH}/shots/sprint3-firstpaint.png and view it.", reportsA),
  { label: 'integrate:A', phase: 'Integrate A', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate A: gates=${gatesA && gatesA.all_passed} ci=${gatesA && gatesA.ci_green}`)

// ------------------------------------------------------------ Phase 6: review
const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, component: { enum: ['analyzer', 'webview', 'vscode-extension', 'claude-plugin', 'process-docs'] }, severity: { enum: ['critical', 'major', 'minor'] }, file: { type: 'string' }, title: { type: 'string' }, detail: { type: 'string' }, repro: { type: 'string' }, suggested_fix: { type: 'string' } }, required: ['id', 'component', 'severity', 'file', 'title', 'detail', 'repro', 'suggested_fix'] } },
    overall_assessment: { type: 'string' },
  },
  required: ['findings', 'overall_assessment'],
}
const VERDICT_SCHEMA = { type: 'object', properties: { confirmed: { type: 'boolean' }, reasoning: { type: 'string' } }, required: ['confirmed', 'reasoning'] }
phase('Review')
const LENSES = [
  `LENS: Track B correctness and regressions. Diff sprint3 against main (git diff main...sprint3 --stat and per file; you may read git history but not modify). Verify PERF byte-identity claims via tools/perf_equiv.py against a scratch copy of main's analyzer; exercise the coverage diagnostics on fixtures you write (parameter-fed features; a single file inside a package); the CLI --group-by; the rail grouping, evidence rendering and confidence chips in jsdom and with Playwright screenshots; wheel/trackpad/pinch handling with synthetic events; the search file:line jump and truncation notice; the legend and Overview mode; bundle size ratchet numbers; the accuracy tool's honesty (labels vs what the analyzer reports; forbidden findings enforced; baseline semantics).`,
  `LENS: the re-baseline fidelity and precision (ANA-1/2/3 + VIEW-01). Compare the sample graph before (git show main:vscode-extension/test/fixtures/vision_pipeline.graph.json) and after: every new node must be a real op in a class method with a correct loc (open the file and check line/col/symbol); the 15 issues unchanged; the clean twin and analyzer/tests/clean still 0 high; run the analyzer on two new class-heavy projects you write (a Lightning module with training_step/validation_step/configure_optimizers, and a plain nn.Module trainer class with fit()/evaluate() methods) and judge fidelity and any new false positives; check scope projections still validate and parity holds; check VIEW-01 with Playwright on 45 and 300 nodes (fit zoom, no overlaps, lanes readable) and the first-paint screenshot.`,
  `LENS: process, CI and documentation truthfulness. Read .github/workflows/ci.yml and the drivers; with GH_TOKEN, list the sprint3 runs and confirm every job of the latest run is green (gh run view <id> --json jobs); check the matrix cost is sane (job count, runner types, caching, concurrency); confirm the Windows-only skips and the perf budget override are justified; run sh scripts/e2e.sh under Git Bash; verify README.md, docs/STATUS.md, scripts/README.md, docs/ACCURACY.md, docs/CONTRACTS.md 11.18/11.19 describe what exists (follow the quick starts literally); check .gitignore keeps generated files out and that no scratch/pycache/.mlview files were committed (git ls-files); check commit messages carry the trailer.`,
]
const reviews = (await parallel(LENSES.map((lens, i) => () =>
  agent(`${PREAMBLE}
ROLE: reviewer. You do NOT modify repo files and do NOT run git write commands (read-only git is fine). Find real defects with reproducible evidence; severity critical = wrong results / crash / roadmap acceptance not met; major = clearly wrong or visibly poor; minor = polish. Give overall_assessment.
${lens}
Integration status: ${JSON.stringify({ B: gatesB && { all_passed: gatesB.all_passed, ci_green: gatesB.ci_green, remaining: gatesB.remaining_problems }, A: gatesA && { all_passed: gatesA.all_passed, ci_green: gatesA.ci_green, remaining: gatesA.remaining_problems } })}`,
    { label: `review:${i + 1}`, phase: 'Review', schema: FINDINGS_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
const raw = reviews.flatMap(r => r.findings)
log(`Review: ${raw.length} raw findings`)
let confirmed = []
let gatesR = null
if (raw.length) {
  const order = { critical: 0, major: 1, minor: 2 }
  const toVerify = raw.filter(f => f.severity !== 'minor').sort((a, b) => order[a.severity] - order[b.severity]).slice(0, 20)
  const minors = raw.filter(f => f.severity === 'minor')
  const verified = await parallel(toVerify.map(f => () =>
    parallel([0, 1, 2].map(i => () =>
      agent(`${PREAMBLE}
ROLE: independent verifier #${i + 1}. Reproduce the claim yourself (run the repro; read the code; read-only git is fine). Confirm ONLY if real at the stated severity and not sanctioned by docs/ROADMAP.md or docs/CONTRACTS.md. Do not modify repo files.
CLAIM: ${JSON.stringify(f, null, 2)}`,
        { label: `verify:${f.id}:${i + 1}`, phase: 'Review', schema: VERDICT_SCHEMA, model: 'opus', effort: 'medium' })))
      .then(vs => ({ ...f, confirmed: vs.filter(Boolean).filter(v => v.confirmed).length >= 2 }))))
  confirmed = verified.filter(Boolean).filter(v => v.confirmed)
  log(`Verify: ${confirmed.length}/${toVerify.length} confirmed; ${minors.length} minors`)
  if (confirmed.length || minors.length) {
    const by = {}, minorsBy = {}
    for (const f of confirmed) (by[f.component] = by[f.component] || []).push(f)
    for (const f of minors) (minorsBy[f.component] = minorsBy[f.component] || []).push(f)
    const DIRS = { analyzer: 'analyzer/**, samples/**, tools/accuracy.py, tools/perf_equiv.py', webview: 'webview/**', 'vscode-extension': 'vscode-extension/** (not media/)', 'claude-plugin': 'claude-plugin/** (not vendor/)', 'process-docs': '.github/**, scripts/**, README.md, docs/STATUS.md, docs/ACCURACY.md, scripts/README.md' }
    await parallel(Object.keys({ ...by, ...minorsBy }).map(c => () =>
      agent(`${PREAMBLE}
ROLE: fixer for '${c}' (you do NOT run git). Fix every CONFIRMED finding at its root cause and the OPTIONAL minors when cheap. OWNERSHIP: ${DIRS[c] || c}. Run that component's tests and paste the tail; add a regression test per confirmed finding.
CONFIRMED: ${JSON.stringify(by[c] || [], null, 2)}
OPTIONAL MINORS: ${JSON.stringify(minorsBy[c] || [], null, 2)}`,
        { label: `fix:${c}`, phase: 'Review', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })))
    gatesR = await agent(INTEGRATE("Integrate the review fixes and commit them as 'Review fixes for Sprint 3 (see body)'.", 'Re-run everything, including the accuracy tool and both e2e drivers; regenerate fixtures only if a fix legitimately moved the graph (say so).', { fixes_for: confirmed.map(f => f.title) }),
      { label: 'integrate:review', phase: 'Review', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
    log(`Integrate review: gates=${gatesR && gatesR.all_passed} ci=${gatesR && gatesR.ci_green}`)
  }
}

return {
  process: process_ && { ci_green: process_.ci_green, ci: process_.ci, commits: process_.commits, remaining: process_.remaining_problems },
  trackB: Object.fromEntries(Object.entries(reportsB).map(([k, v]) => [k, v ? { passing: v.all_tests_passing, ids: v.roadmap_ids_done, gaps: v.known_gaps } : null])),
  integrateB: gatesB && { all_passed: gatesB.all_passed, ci_green: gatesB.ci_green, commits: gatesB.commits, remaining: gatesB.remaining_problems },
  trackA: Object.fromEntries(Object.entries(reportsA).map(([k, v]) => [k, v ? { passing: v.all_tests_passing, ids: v.roadmap_ids_done, gaps: v.known_gaps, what: v.what_changed.slice(0, 1500) } : null])),
  integrateA: gatesA && { all_passed: gatesA.all_passed, ci_green: gatesA.ci_green, commits: gatesA.commits, remaining: gatesA.remaining_problems },
  review: { confirmed: confirmed.map(f => ({ id: f.id, component: f.component, severity: f.severity, title: f.title })), assessments: reviews.map(r => r.overall_assessment), integrate: gatesR && { all_passed: gatesR.all_passed, ci_green: gatesR.ci_green, commits: gatesR.commits } },
}
