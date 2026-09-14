export const meta = {
  name: 'mlview-sprint5-later',
  description: 'Implement the LATER tier of docs/ROADMAP.md on branch sprint5: process fixes first, then three waves (DATAFLOW-IP, CFG-ONE, diff, VIEW-04, H8, H10, MLV-P11; H5, ANA-10, VIEW-08; PERF-04, MLV-P12), then review; commits pushed over SSH with CI watched',
  phases: [
    { title: 'Process', detail: 'macOS smoke fix, 20th e2e step, contracts erratum', model: 'opus' },
    { title: 'Wave 1', detail: 'DATAFLOW-IP; default flip + CFG-ONE + diff; VIEW-04; H10 + H8 + CFG-ONE hosts + MLV-P11', model: 'opus' },
    { title: 'Integrate 1', detail: 'gates, commit, push, CI', model: 'opus' },
    { title: 'Wave 2', detail: 'H5 structured fixes; ANA-10; VIEW-08 viewer + hosts', model: 'opus' },
    { title: 'Integrate 2', detail: 'gates, commit, push, CI', model: 'opus' },
    { title: 'Wave 3', detail: 'PERF-04 rollup + MLV-P12 pipelines in both ports + fuzzer', model: 'opus' },
    { title: 'Integrate 3', detail: 'gates, commit, push, CI', model: 'opus' },
    { title: 'Review', detail: '4 lenses -> verify -> fix -> integrate', model: 'opus' },
  ],
}

const ROOT = '/Users/minghaoyang/Documents/MLView'
const SCRATCH = '/private/tmp/claude-501/-Users-minghaoyang-Documents-MLView/2ebc6c0c-4dab-49ea-a032-c99b4c9f286e/scratchpad'
const PW = SCRATCH + '/pw'

const PREAMBLE = `
You are one of several autonomous engineers executing Sprint 5 of MLView: the LATER tier of docs/ROADMAP.md (read section (c) LATER in full for your items, plus (e) and (f), and the "framing to carry forward": every analyzer change must state what it could not analyze; a high-severity false positive is the one failure that costs the product its credibility). MLView statically analyzes Python ML code and renders the workflow as an interactive diagram in three hosts (standalone HTML report, VS Code extension, Claude Code plugin). Contracts: docs/CONTRACTS.md sections 0, 10, 11 bind (amendments now run to 11.34). Status: docs/STATUS.md; gate table: scripts/README.md; accuracy: docs/ACCURACY.md.
LEAD DECISIONS (final): REQUIREMENTS section 5 non-goal 5 is lifted for H5 with its guardrails (rules opt in; edits computed from the AST; never auto-applied; no fix below the likely bucket; the five rules named in the entry); DATAFLOW-IP ships behind '--dataflow local|ip' with local as this release's default, every hop multiplies confidence by an explicit interprocedural evidence weight so cross-object findings are never certain, intersection not union across call sites, hops capped; PERF-03 and CACHE flip to default ON now (the roadmap's condition, accuracy identical both ways, was met in Sprint 4); ANA-10 ships its Python half only (the YAML/Hydra half stays deferred); MLV-P12 may extend the section 11.1 KIND enum with 'pipeline:' because HEALTH-02's fuzzer exists; CFG-ONE precedence is TOML wins for disable/exclude and the VS Code settings are additive filters, stated in the settings descriptions and asserted by a test; H10's LM-tool scope/depth inputs are granted by amendment; pushes go over SSH.
ENVIRONMENT (macOS, this Mac): repo root ${ROOT} (git; branch sprint5 from main 3af6f2c = PR #2 merged; remote origin is HTTPS with a PAT lacking the workflow scope, so ALWAYS push with 'git push git@github.com:realmyang/MLView.git HEAD:sprint5' - the SSH key works). START EVERY SHELL COMMAND WITH: export PATH="${ROOT}/.venv/bin:$PATH" PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 (venv Python 3.13 with the analyzer editable plus mcp, pytest, pytest-xdist, jsonschema, build; the system python3 is 3.9 and must never be used). Node 26 / npm 11 (CI runs Node 20 and 22; no Node-26-only APIs). No PowerShell: use 'sh scripts/build.sh' and 'sh scripts/e2e.sh'. No 'claude' or 'code' CLI (plugin validate test skips itself). Playwright + Chromium: run node scripts from ${PW} or set NODE_PATH=${PW}/node_modules. Scratch: ${SCRATCH}. GitHub CLI: per command, export GH_TOKEN=$(printf 'protocol=https\\nhost=github.com\\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p') (never print it); 'gh run list -R realmyang/MLView --branch sprint5 --limit 5', 'gh run watch <id> -R realmyang/MLView --exit-status', 'gh run view <id> -R realmyang/MLView --log-failed'.
BASELINE at main (green on this Mac): sh scripts/e2e.sh 19 steps; analyzer 1722 passed / 3 skipped; webview 384; vscode-extension 298; claude-plugin 305 / 5 skipped; tools/verify.py --all 10/10; tools/accuracy.py precision 100% on 36 rules, recall 71.8% (unseen 53.2%), zero forbidden findings; --demo byte-identical to contracts/graph.sample.json. Keep every gate green; add to them; never weaken an assertion unless the roadmap item, a sanctioned default flip or a re-baseline sanctions it (say which).
GIT RULES (strict): ONLY agents whose brief says "you run git" may run any git command. Commits: imperative subject, body naming the roadmap ids, trailer 'Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>'. Never force-push, never rewrite history, never touch main. CI cost: private repo; one push per wave plus fix iterations.
CONTRACT AMENDMENTS: never edit docs/CONTRACTS.md directly. Write your amendment as a NEW file docs/contracts/11.<NN>-<slug>.md with the number your brief assigns (normative, additive, dated 2026-09-10, in the style of 11.18-11.34); the integrator appends them in order. Schema changes are optional fields only, mirrored byte-identically to analyzer/src/mlview/schema/graph.schema.json; contracts/graph.sample.json never changes.
QUALITY BAR: working software with tests; paste real output tails; files under ~600 lines (new modules over growing build.py / app.ts / verify.py); no innerHTML; no getTotalLength; library code never prints to stdout; write each new source file completely in one Write call; when a concurrent agent's half-written file breaks your test run, wait a minute and re-run rather than editing their file.
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
    commits: { type: 'array', items: { type: 'string' } },
    ci: { type: 'string' },
    ci_green: { type: 'boolean' },
    fixes_applied: { type: 'array', items: { type: 'string' } },
    remaining_problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['gates', 'all_passed', 'commits', 'ci', 'ci_green', 'fixes_applied', 'remaining_problems'],
}
const INTEGRATE = (title, extra, reports) => `${PREAMBLE}
ROLE: integrator (you run git). ${title}
${extra}
STEPS: 1) Read the reports below. 2) Append every docs/contracts/11.*.md fragment to docs/CONTRACTS.md section 11 in numeric order and delete the fragments; make schema mirrors byte-identical. 3) 'python tools/sync-assets.py' and 'python tools/sync-core.py' (vendor and VSIX core). 4) Run and fix until green (fix at the source, minimal edits, never rewrite a component): 'sh scripts/e2e.sh'; 'python tools/verify.py --all'; 'python tools/accuracy.py'; 'python tools/verify.py --scopes --fuzz 200'; 'npx tsc --noEmit' in webview and vscode-extension. 5) Update scripts/README.md's gate table and docs/STATUS.md; keep 'python scripts/check_docs.py' and scripts/doc_numbers.py green (every step-count and graph-size claim consistent). 6) git status; never add scratch, __pycache__, .mlview, .venv, node_modules, docs/gallery or wheel/vsix files; git add -A; commit with the subject in the title and a body listing the roadmap ids; push with 'git push git@github.com:realmyang/MLView.git HEAD:sprint5'; watch CI; on failure read --log-failed, fix, commit ('CI: ...'), push, watch (at most 5 iterations). Report every gate with real output, the commits, and per-job CI conclusions.
COMPONENT REPORTS:
${JSON.stringify(reports, null, 2)}`

// ------------------------------------------------------------ Process (alone)
phase('Process')
const proc = await agent(`${PREAMBLE}
ROLE: process engineer (you run git; you run ALONE, nobody else is editing). ITEMS:
1) The 'smoke (macos)' CI job FAILED on the main merge run 34419964015 (job id 102693018965) - the first time it ran since Sprint 3, while every gate passes on this Mac. Fetch its log (gh api repos/realmyang/MLView/actions/jobs/102693018965/logs), find the cause, fix it at the source (a runner-only difference such as a missing tool, path, locale or Node version, or a genuine macOS-runner defect), and make the job green on sprint5 by temporarily allowing it to run on push to sprint5 for your verification pushes, then restoring the 'push to main || pull_request' guard in your last commit.
2) Promote the owed 20th e2e step: wire webview/test/export_svg.mjs (gate row 12d) into scripts/e2e.sh and e2e.ps1 and update every step-count claim (README, docs/STATUS.md, scripts/README.md, ci.yml comments) so scripts/doc_numbers.py stays green.
3) Contracts erratum: write docs/contracts/11.35-erratum-11-19-edge-count.md correcting section 11.19's '54 nodes and 52 edges' to 51 edges with the reason (ROADMAP REV-06), then append it to docs/CONTRACTS.md yourself (you are alone) and delete the fragment.
4) Note in scripts/README.md that pushes go over SSH until the PAT gains the workflow scope.
Commit as 'Sprint 5 process: green macOS smoke job, SVG export e2e step, contracts erratum' (plus CI fix commits), push over SSH, watch CI until every job including smoke (macos) is green. Report the root cause of the macOS failure explicitly.`,
  { label: 'process', phase: 'Process', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Process: ci_green=${proc && proc.ci_green}`)

// ------------------------------------------------------------ Wave 1
phase('Wave 1')
const W1_IP = `${PREAMBLE}
ROLE: analyzer engineer, DATAFLOW-IP (you do NOT run git). OWNERSHIP: analyzer/src/mlview/ir/** (bindings, returns, resolve, build_ir, scopes), analyzer/src/mlview/rules/context.py, rules/helpers.py, rules/confidence.py, rules/r_leakage.py (and other rules only to consume provenance), analyzer/tests/core/test_dataflow_ip.py (new), analyzer/tests/fixtures/dataflow/** (new), analyzer/tests/clean/** (additions), analyzer/tests/accuracy/** (labels; baseline ratchet upward only, for the ip mode recorded separately), cli.py ONLY for the '--dataflow local|ip' flag (re-read cli.py immediately before editing; another agent adds 'mlview init' and 'mlview diff' subcommands there), api.py ONLY for the additive option, docs/contracts/11.36-dataflow-ip.md, docs/ACCURACY.md (a section for ip mode).
ITEM DATAFLOW-IP per the roadmap entry: a fixed-point interprocedural summary pass after propagate_parameters with three summaries - CONSTRUCTOR (ctor argument tags at every construction site -> parameter -> self.<attr> assigned from it in __init__, union stored into the class scope's bindings), RETURN (extend ir/returns.py from one level to the fixed point), METHOD-ARG (the one-hop argument-to-parameter summary applied to bound-method call sites now that ANA-2 resolves them); provenance on the ValueRef so an issue can say where a tag arrived from (an evidence entry naming the hop chain); hops capped (default 3); every hop multiplies confidence by an explicit interprocedural evidence weight (cross-object findings land at likely or possible, never certain); intersection, not union, when a helper is called from two sites with different tag sets; behind '--dataflow ip' (default local: byte-identical to today). Negative fixtures: a helper that legitimately receives already-split training rows; a helper called from two sites with different tags; a parameter merely named X. Acceptance: the Lightning DataModule leak and the research-repo MinMaxScaler-before-chronological-cut leak both fire in ip mode with related locs at the ctor and split sites; the ctor-param -> self.features probe fires while the 'parameter merely named X' probe does not; analyzer/tests/clean and samples/vision_pipeline_clean stay at 0 high and <= 2 medium in ip mode; tools/accuracy.py in ip mode reports zero forbidden findings (add an '--dataflow ip' mode to tools/accuracy.py if it lacks one, in a separate section of docs/ACCURACY.md). Write the amendment. Run the analyzer suite in both modes and paste tails.`

const W1_CFG = `${PREAMBLE}
ROLE: analyzer engineer, configuration + diff + default flip (you do NOT run git). OWNERSHIP: analyzer/src/mlview/core/config.py (new), rules/suppress.py, cli.py (ONLY: the 'init' and 'diff' subcommands and the --relevance default; re-read immediately before each edit; another agent adds a --dataflow flag), core/pipeline.py (ONLY the relevance/cache default), emit/diff_out.py (new), core/diff.py (new), analyzer/tests/core/test_config.py, test_diff.py, test_relevance_default.py (new), analyzer/tests/fixtures/config/** (new), samples/** (expected_issues regeneration ONLY if the default flip legitimately moves it - it should not), docs/contracts/11.37-cfg-one.md, docs/contracts/11.38-diff-overlay.md, docs/contracts/11.39-relevance-default.md.
ITEMS: (a) PERF-03/CACHE default flip: '--relevance ml' and the sidecar cache become the defaults; byte-identity on samples/vision_pipeline, the clean twin, analyzer/tests/clean and the accuracy corpus must hold (tools/perf_equiv.py --expect-same on those; the set-aside diagnostic may appear only for repos that actually contain non-ML files - add a fixture with one); re-baseline only what the diagnostic legitimately changes and list it; MLVIEW_NO_CACHE=1 and '--relevance all' still restore the old paths. (b) CFG-ONE analyzer half: extend .mlview.toml with [rules].severity (config_warning: severities are fixed; a valid override becomes a warning, not an error), [rules].min_confidence, [rules].enable, [paths].include, [analysis] (relevance, dataflow, max_nodes, include_notebooks) and [baseline] (path); read the same tables from [tool.mlview] in pyproject.toml when no .mlview.toml exists; 'mlview init' writes a commented .mlview.toml listing every registered rule with its severity, generated from the registry; a stated precedence with a test: TOML wins for disable/exclude, CLI flags win over TOML for analysis options, and the file that was applied is named in workspace.configPath. (c) VIEW-08 analyzer half: 'mlview diff <base.json> <head.json> [--json FILE]' emitting a separate overlay document (write its schema in 11.38: per-node and per-edge status added/removed/changed/unchanged keyed by the stable ids, per-issue new/fixed/persisting, a summary block) and a '--format summary' rendering; acceptance: over the sample pair (vision_pipeline vs vision_pipeline_clean) it reports the added nodes and the 15 fixed findings with the exact counts. Write the three amendments. Run the analyzer suite; paste tails.`

const W1_VIEWER = `${PREAMBLE}
ROLE: viewer engineer, VIEW-04 (you do NOT run git). OWNERSHIP: webview/** only.
ITEM VIEW-04 per the roadmap entry: group channel-bound (cross-lane) edges by (source lane, target lane) and route each group as one trunk with splayed entry and exit spurs plus a member-count badge, expanding into individual strokes on hover or when the group has one member; barycentre-sort each lane's cross-lane departures by the y of their target so trunks nest rather than braid; widen the channel by the number of distinct lane pairs, not edges. HARD CONSTRAINTS: keep every per-edge points array and the per-edge 'd' intact (the flow charge and the SVG export read them); bundle at the DOM and stroke level only; node positions unchanged; deterministic; layout.test.mjs, the parity/scope tests and export_svg.mjs stay green (update only assertions that count channel strokes, and say so). Measure crossings per edge on the 54-node demo and on a ~300-node synthetic before and after and report both; verify visually with Playwright (view PNGs with Read). Run build/check/test; paste tails.`

const W1_HOSTS = `${PREAMBLE}
ROLE: hosts engineer, wave 1 (you do NOT run git). OWNERSHIP: vscode-extension/** (not media/ or core/), claude-plugin/** (not vendor/), analyzer/tools/gen_gallery.py (new), docs/walkthrough/** (new), .gitignore (docs/gallery/), README.md, docs/STATUS.md, docs/contracts/11.40-lm-tools-scope.md, docs/contracts/11.41-hooks.md.
ITEMS: (a) H10: add scope and depth inputs to the three languageModelTools inputSchemas and pass them through buildAnalyzeArgs (reuse the MCP selector prose verbatim; amendment 11.40 lifts 11.11's cut); multi-root workspaces: a per-folder map replacing the single graph/index assumption, mlview.activeFolder plus a picker in the status-bar tooltip and a quick pick for surfaces that need one graph; tests with a two-folder mocked workspace. (b) H8: claude-plugin/hooks/hooks.json with a PostToolUse matcher on Edit|Write|NotebookEdit running hooks/post_edit.py: exit 0 immediately unless the edited path is Python (or .ipynb when notebooks are enabled) under CLAUDE_PROJECT_DIR; re-analyze through the same load_graph cache the MCP tools use (sharing MLVIEW_DATA_DIR); diff the issue-id set against the previous run; emit additionalContext only when the set grew, at most 5 rows, under a 3 s wall-clock budget after which it exits 0 silently; MLVIEW_HOOK=off disables; plus a Stop-event variant printing one summary per turn; never blocks and never writes to the project; tests drive the script with a fake hook payload; keep the manifest shape valid per the Claude Code hooks docs (fetch them if unsure) and the plugin's manifest test green. (c) CFG-ONE host half: pass --config when a .mlview.toml (or pyproject [tool.mlview]) is found; settings mlview.configPath and mlview.baselinePath; commands 'MLView: Open MLView Configuration' (creates via 'mlview init' when absent) and 'MLView: Create Baseline From Current Findings'; settings descriptions state the precedence; tests. (d) MLV-P11: analyzer/tools/gen_gallery.py rendering every clean program and every bad/good fixture pair to docs/gallery/ on demand (gitignored) with an index; contributes.walkthroughs in package.json with five steps (install, visualize the bundled sample, read a finding in Problems, Alt+M reveal, Alt+Shift+M scope) each invoking an existing command, with five short Markdown files under docs/walkthrough/; manifest test for the walkthrough. Write the two amendments. Run check/compile/test and the plugin suite; paste tails.`

const wave1 = await parallel([
  () => agent(W1_IP, { label: 'w1:dataflow-ip', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W1_CFG, { label: 'w1:config-diff', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W1_VIEWER, { label: 'w1:viewer', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W1_HOSTS, { label: 'w1:hosts', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
])
const r1 = { dataflow: wave1[0], config: wave1[1], viewer: wave1[2], hosts: wave1[3] }
log(`Wave 1: ${Object.entries(r1).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)
phase('Integrate 1')
const g1 = await agent(INTEGRATE("Integrate wave 1 and commit it as 'Sprint 5 wave 1: interprocedural dataflow behind a flag, relevance and cache by default, one configuration surface, analysis diff, cross-lane bundling, LM-tool scope, hooks, multi-root, gallery and walkthrough (DATAFLOW-IP, PERF-03/CACHE default, CFG-ONE, VIEW-08 analyzer half, VIEW-04, H10, H8, MLV-P11)'.", "Run the accuracy tool in both dataflow modes; confirm the default flip kept the corpora byte-identical (perf_equiv --expect-same) and --demo parity.", r1),
  { label: 'integrate:1', phase: 'Integrate 1', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate 1: gates=${g1 && g1.all_passed} ci=${g1 && g1.ci_green}`)

// ------------------------------------------------------------ Wave 2
phase('Wave 2')
const W2_H5 = `${PREAMBLE}
ROLE: analyzer engineer, H5 structured fixes (you do NOT run git). OWNERSHIP: analyzer/src/mlview/rules/fixes.py (new), rules/r_*.py (ONLY to attach opt-in fix builders), rules/context.py (ctx.fix builder), contracts/graph.schema.json + mirror (optional Issue.fix), analyzer/tests/rules/test_fixes.py (new), analyzer/tests/fixtures/fixes/** (new), emit/text_out.py (a 'fix available' marker), docs/contracts/11.42-structured-fixes.md, docs/rules/** (regenerate). An ANA-10 agent is concurrently editing ir/**, core/build.py, knowledge/** and rules/helpers.py - never touch those.
ITEM H5 per the roadmap entry and the lead decision: an additive optional Issue.fix {title, safety: mechanical|needs-review, edits:[{file, line, col, endLine, endCol, newText}]} that rules opt into; edits computed from the AST (indentation-correct inside with/for blocks), never string splicing; isPreferred only for mechanical; no fix at all below the likely bucket; start with MLV201, MLV301, MLV302, MLV602, MLV111 (use the ghost-node insertion locs and the role-tagged relatedLocs). Acceptance: for each opted-in rule a test applies the edit to the bad fixture, re-parses (ast.parse valid) and re-analyses, asserting the rule stops firing and no new finding appears; the clean twin yields 0 issues and 0 fixes; the demo's fixes are listed in the summary. Write the amendment. Run the analyzer suite; paste tails.`

const W2_ANA10 = `${PREAMBLE}
ROLE: analyzer engineer, ANA-10 Python half (you do NOT run git). OWNERSHIP: analyzer/src/mlview/ir/bindings.py, ir/config_values.py (new), core/build.py, core/hooks.py, knowledge/**, rules/helpers.py (literal_of), analyzer/tests/core/test_config_values.py (new), analyzer/tests/fixtures/config_values/** (new), docs/contracts/11.43-config-resolution.md. An H5 agent is concurrently editing rules/fixes.py, rules/r_*.py, rules/context.py and the schema - never touch those; a config agent already added core/config.py (the .mlview.toml surface) - do not touch it.
ITEM ANA-10 (Python half only): resolve module-level dict literals, dataclass field defaults, argparse add_argument(default=) and attribute chains rooted at a CONFIG_NAME_RE binding into literal values stored on the ValueRef so literal_of() picks them up with no rule changes (MLV110 shuffle=, MLV112 num_workers=, MLV602 random_state=, MLV208 GradScaler(enabled=) all start seeing CFG["workers"] / cfg.data.workers); emit config nodes with config-kind edges to their consumers so the diagram answers 'where does batch_size come from'; resolve getattr(<workspace module>, <config string>) against the module's exported symbols into a one-of-N alternatives node instead of unknown boxes; de-rate config-sourced literals by an explicit evidence weight so a wrong read can never mint a certain finding; never open YAML (the deferred half; say so in a diagnostic when a YAML/Hydra config file is referenced). Acceptance: the probe ladder from the roadmap (num_workers literal, module constant, CFG["workers"], cfg.data.workers) all fire MLV112 with the last two at most likely; the Hydra research corpus program gains config-kind edges and loses its two unknown registry boxes; analyzer/tests/clean stays at 0; the demo's 15 findings keep their exact confidences. Write the amendment. Run the analyzer suite and tools/accuracy.py; paste tails.`

const W2_VIEWER = `${PREAMBLE}
ROLE: viewer engineer, wave 2 (you do NOT run git). OWNERSHIP: webview/** only.
ITEMS: (a) VIEW-08 viewer half: accept the diff overlay document defined in docs/CONTRACTS.md 11.38 (integrated last wave) as an optional sibling via a new HostToUi 'diffOverlay' message and, in the standalone report, a second <script type="application/json" id="mlview-diff"> block; render added nodes with a ledge, removed nodes as ghost outlines in place, changed nodes with a chip, per-issue new/fixed/persisting chips, a banner '+N nodes · -N nodes · N new findings · N fixed', and a 'changed only' chip that reuses the scope projection (a diff is another projection: core = changed nodes, boundary = one hop); dev page demonstrates it with the sample pair. (b) H5 rendering: a 'Fix available' marker on rail rows and the Inspector showing Issue.fix's title, safety and the edit as a snippet; in VS Code post a new UiToHost 'applyFix' {issueId} message (the host applies it with preview); standalone copies the snippet. (c) ANA-10 rendering: config nodes' resolved value in the card sublabel and the one-of-N alternatives node visual. Tests for all three; run build/check/test; verify visually with Playwright; paste tails.`

const W2_HOSTS = `${PREAMBLE}
ROLE: hosts engineer, wave 2 (you do NOT run git). OWNERSHIP: vscode-extension/** (not media/ or core/), claude-plugin/** (not vendor/), README.md, docs/STATUS.md.
ITEMS: (a) H5 host half: a CodeActionProvider offering each Issue.fix as a WorkspaceEdit code action (isPreferred only for mechanical), applied with VS Code's preview (never auto-applied), handling the webview's 'applyFix' message the same way; refuse edits outside the workspace; tests. (b) VIEW-08 host half: commands 'MLView: Save Current Graph As Comparison Base' and 'MLView: Compare With Saved Base' (runs 'mlview diff base.json current.json --json' and posts diffOverlay), plus 'MLView: Compare With Clean Sample' for the demo; the MCP server exposes the diff through mlview_graph {scope:'diff', base:<graphPath>} without adding a sixth tool, documented in the docstring; /mlview-issues documents '--diff-base'. (c) CFG-ONE: verify the wave-1 settings descriptions state the precedence and add the test if missing. Run check/compile/test and the plugin suite; paste tails.`

const wave2 = await parallel([
  () => agent(W2_H5, { label: 'w2:fixes', phase: 'Wave 2', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W2_ANA10, { label: 'w2:config-values', phase: 'Wave 2', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W2_VIEWER, { label: 'w2:viewer', phase: 'Wave 2', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W2_HOSTS, { label: 'w2:hosts', phase: 'Wave 2', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
])
const r2 = { fixes: wave2[0], configValues: wave2[1], viewer: wave2[2], hosts: wave2[3] }
log(`Wave 2: ${Object.entries(r2).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)
phase('Integrate 2')
const g2 = await agent(INTEGRATE("Integrate wave 2 and commit it as 'Sprint 5 wave 2: structured fixes, in-Python config resolution, analysis comparison in the viewer and hosts (H5, ANA-10, VIEW-08)'.", 'Run the fix apply-and-re-analyse tests, the accuracy tool in both dataflow modes, and --demo parity; regenerate fixtures only where ANA-10 legitimately moved a graph (say what moved).', r2),
  { label: 'integrate:2', phase: 'Integrate 2', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate 2: gates=${g2 && g2.all_passed} ci=${g2 && g2.ci_green}`)

// ------------------------------------------------------------ Wave 3
phase('Wave 3')
const W3_PROJ = `${PREAMBLE}
ROLE: analyzer engineer, projections (you do NOT run git). OWNERSHIP: analyzer/src/mlview/core/graph.py, core/rollup.py (new), core/pipelines.py (new), core/project.py, core/selectors.py, api.py (SCOPE_KINDS), contracts/graph.schema.json + mirror (optional Node.rolledUp, Edge.weight, root pipelines[]), contracts/validate_sample.py (invariants for rolled-up documents), analyzer/tools/gen_scope_fixtures.py (new cases), contracts/scope.cases.json + scope.expected.json (regenerate), analyzer/tests/core/test_rollup.py, test_pipelines.py (new), docs/contracts/11.44-rollup.md, docs/contracts/11.45-pipelines.md. Write the two amendments FIRST (within your first stretch) because the viewer agent ports them concurrently.
ITEMS: (a) PERF-04: replace deletion in the --max-nodes cap with hierarchical rollup - fold each unit's op children into the unit node with a rolledUp count and the union of their issueIds; if still over budget fold units into a per-file summary node; only then fall back to dropping; re-point edges at the surviving ancestor and dedupe parallels into one carrying a weight; ghost invariant and parent forest preserved; stats.truncated and the diagnostic say 'rolled up'; it cannot change any uncapped document. Acceptance on a 525-file synthetic: isolated nodes under 5%, edge retention over 40% of the uncapped set after merging parallels, every issue resolves to a node, validate_sample.py passes at caps 45, 100, 400 and 2000. (b) MLV-P12: compute weakly-connected components over data and call edges seeded from workspace.entrypoints, emit an optional root pipelines[] block (entrypoint, label, nodeIds count, issue counts), add 'pipeline:<entrypoint>' to the 11.1 KIND grammar and to project.py (nodes reachable from several entrypoints become viewRole context), SCOPE_KINDS, --list-scopes and the error candidates; regenerate the parity fixture with pipeline cases. Run the analyzer suite and 'python tools/verify.py --scopes' (the TS half may be red until the viewer agent finishes; say so). Paste tails.`

const W3_VIEWER = `${PREAMBLE}
ROLE: viewer engineer, wave 3 (you do NOT run git). OWNERSHIP: webview/** only.
ITEMS: port docs/contracts/11.44-rollup.md and 11.45-pipelines.md (poll docs/contracts/ until both exist; the analyzer agent writes them first): (a) render rolled-up nodes with a count badge reusing the collapsed-group visual, weighted edges with a thicker stroke and a weight badge, and the 'rolled up' banner; (b) mirror the 'pipeline:' selector in src/scope/selector.ts and src/scope/project.ts line-for-line with the Python (context role for shared nodes), add pipelines to the scope picker with live counts, and open the report on a chooser when pipelines.length >= 2 (persisted in ViewState). Keep test/scope_parity.test.mjs green against the regenerated fixture. Run build/check/test; verify visually with Playwright; paste tails.`

const W3_HEALTH = `${PREAMBLE}
ROLE: contracts engineer, wave 3 (you do NOT run git). OWNERSHIP: analyzer/tools/scope_fuzz.py, tools/gate_scopes.py (if present), webview/test/scope_fuzz.test.mjs, claude-plugin/server/** (ONLY the mlview_graph docstring and SCOPE grammar text for 'pipeline:'), claude-plugin/tests/test_scope_grammar.py (additions), vscode-extension/src/lmTools.ts + chat.ts (ONLY the selector prose for 'pipeline:'), docs/STATUS.md (a note).
ITEMS: extend the differential fuzzer to generate capped (rolled-up) documents with rolledUp counts and weighted edges, pipelines[] blocks, and 'pipeline:' selectors (poll docs/contracts/11.44 and 11.45 for the shapes); run '--fuzz 200' and promote counterexamples; prove the fuzzer catches a one-line divergence in the pipeline projection (scratch copy only); update the MCP and LM-tool selector prose so all hosts describe one grammar. Paste results.`

const wave3 = await parallel([
  () => agent(W3_PROJ, { label: 'w3:projections', phase: 'Wave 3', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W3_VIEWER, { label: 'w3:viewer', phase: 'Wave 3', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W3_HEALTH, { label: 'w3:health', phase: 'Wave 3', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
])
const r3 = { projections: wave3[0], viewer: wave3[1], health: wave3[2] }
log(`Wave 3: ${Object.entries(r3).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)
phase('Integrate 3')
const g3 = await agent(INTEGRATE("Integrate wave 3 and commit it as 'Sprint 5 wave 3: hierarchical rollup for --max-nodes and multi-pipeline workspaces in both projections (PERF-04, MLV-P12)'.", "Run 'python tools/verify.py --scopes --fuzz 200' and the capped-document validation at four caps; confirm uncapped documents are byte-identical (perf_equiv --expect-same) and --demo parity.", r3),
  { label: 'integrate:3', phase: 'Integrate 3', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate 3: gates=${g3 && g3.all_passed} ci=${g3 && g3.ci_green}`)

// ------------------------------------------------------------ Review
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
  `LENS: precision above all. Exercise DATAFLOW-IP (both modes), ANA-10, H5 and the default relevance flip on new programs you write: a Lightning DataModule that fits a scaler before random_split (must fire in ip mode), a helper that receives already-split rows (must not), a helper called from two sites, a config-driven trainer (dict / dataclass / argparse / cfg.x.y), a correct AMP loop, and a Keras program; apply every offered fix and re-analyse; judge false positives (zero tolerance for high/certain), missed findings, confidence honesty (no certain across a hop), config de-rating, and the accuracy corpus labels' truthfulness including the ip-mode section.`,
  `LENS: viewer, projections and export. With Playwright (from ${PW}) on regenerated reports and a ~500-node capped synthetic: VIEW-04 trunks (crossings before/after, hover expansion, flow charge still per edge, SVG export unchanged in edge count), VIEW-08 overlay on the sample pair (ledges, ghosts, banner counts, 'changed only' as a projection), PERF-04 rollup rendering and connectivity at caps 45/100/400, MLV-P12 chooser and 'pipeline:' scoping, fix markers; keyboard and a11y regressions; console errors.`,
  `LENS: hosts. H5 code actions with the mocked vscode (preview, isPreferred rules, containment), H8 hook script driven with fake payloads (budget, silence when nothing grew, MLVIEW_HOOK=off, manifest validity against the Claude Code hooks docs), H10 multi-root map and LM-tool scope inputs, CFG-ONE precedence (TOML vs settings; 'mlview init' output; pyproject [tool.mlview]), the walkthrough manifest, the gallery build target, MCP diff scope and hook cache sharing; plugin suite and extension suite.`,
  `LENS: process, regressions and docs. Diff sprint5 against main (read-only git): every changed or deleted assertion judged against the roadmap; --demo parity; perf_equiv expectations after the default flip; verify.py rows; e2e step-count consistency (20 steps now); CI health and cost with gh (per-job durations, the macOS job green on main and the branch); docs/CONTRACTS.md integration of all amendment fragments (none left in docs/contracts/); docs/STATUS.md, docs/ROADMAP.md 'Landed' notes for every LATER item that shipped; README quick starts followed literally; .gitignore hygiene (git ls-files: no gallery, wheel, vsix, cache).`,
]
const reviews = (await parallel(LENSES.map((lens, i) => () =>
  agent(`${PREAMBLE}
ROLE: reviewer. You do NOT modify repo files and do NOT run git write commands. Find real defects with reproducible evidence; critical = wrong results / crash / roadmap acceptance not met / a high-certain false positive; major = clearly wrong or visibly poor; minor = polish. Give overall_assessment.
${lens}
Integration status: ${JSON.stringify([g1, g2, g3].map(g => g && { all_passed: g.all_passed, ci_green: g.ci_green, remaining: g.remaining_problems }))}`,
    { label: `review:${i + 1}`, phase: 'Review', schema: FINDINGS_SCHEMA, model: 'opus', effort: 'high' })))).filter(Boolean)
const raw = reviews.flatMap(r => r.findings)
log(`Review: ${raw.length} raw findings`)
let confirmed = []
let gR = null
if (raw.length) {
  const order = { critical: 0, major: 1, minor: 2 }
  const toVerify = raw.filter(f => f.severity !== 'minor').sort((a, b) => order[a.severity] - order[b.severity]).slice(0, 24)
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
    const DIRS = { analyzer: 'analyzer/**, samples/**, contracts/scope.*.json, contracts/validate_sample.py, tools/accuracy.py, tools/perf_equiv.py, docs/rules/**, docs/ACCURACY.md', webview: 'webview/**', 'vscode-extension': 'vscode-extension/** (not media/ or core/)', 'claude-plugin': 'claude-plugin/** (not vendor/), tools/action/**', 'process-docs': '.github/**, scripts/**, tools/verify.py, tools/sync-core.py, README.md, docs/STATUS.md, docs/ROADMAP.md, docs/CONTRACTS.md (integration of amendments only), scripts/README.md' }
    await parallel(Object.keys({ ...by, ...minorsBy }).map(c => () =>
      agent(`${PREAMBLE}
ROLE: fixer for '${c}' (you do NOT run git). Fix every CONFIRMED finding at its root cause and the OPTIONAL minors when cheap. OWNERSHIP: ${DIRS[c] || c}. Run that component's tests and paste the tail; add a regression test per confirmed finding.
CONFIRMED: ${JSON.stringify(by[c] || [], null, 2)}
OPTIONAL MINORS: ${JSON.stringify(minorsBy[c] || [], null, 2)}`,
        { label: `fix:${c}`, phase: 'Review', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })))
    gR = await agent(INTEGRATE("Integrate the review fixes and commit them as 'Review fixes for Sprint 5 (see body)'.", "Re-run everything including both dataflow modes of the accuracy tool, the fuzzer, and the capped-document validation; regenerate fixtures only if a fix legitimately moved a graph (say so). Finally add a dated 'Landed 2026-09-10' measurement note under each LATER-tier entry in docs/ROADMAP.md that shipped, in the style of the earlier notes.", { fixes_for: confirmed.map(f => f.title) }),
      { label: 'integrate:review', phase: 'Review', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
    log(`Integrate review: gates=${gR && gR.all_passed} ci=${gR && gR.ci_green}`)
  }
}

return {
  process: proc && { ci_green: proc.ci_green, commits: proc.commits, remaining: proc.remaining_problems },
  waves: [r1, r2, r3].map(r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v ? { passing: v.all_tests_passing, ids: v.roadmap_ids_done, gaps: v.known_gaps.slice(0, 6) } : null]))),
  integrations: [g1, g2, g3, gR].map(g => g && { all_passed: g.all_passed, ci_green: g.ci_green, commits: g.commits, remaining: g.remaining_problems }),
  review: { confirmed: confirmed.map(f => ({ id: f.id, component: f.component, severity: f.severity, title: f.title })), assessments: reviews.map(r => r.overall_assessment) },
}
