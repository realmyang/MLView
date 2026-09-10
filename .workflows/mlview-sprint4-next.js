export const meta = {
  name: 'mlview-sprint4-next',
  description: 'Implement the NEXT tier of docs/ROADMAP.md in four waves on branch sprint4 (CI-ADOPT, MLV-P1, H3, PACKAGING, MLV-P10, HEALTH-02, VIEW-03, VIEW-12; FW-RECOG, ANA-5a, VIEW-07; ANA-7/8/9, PERF-03, CACHE; NB), then review; commits pushed with CI watched',
  phases: [
    { title: 'Wave 1', detail: 'CI-ADOPT, MLV-P1, H3, VIEW-03, VIEW-12, MLV-P10, PACKAGING, HEALTH-02', model: 'opus' },
    { title: 'Integrate 1', detail: 'gates, commit, push, CI', model: 'opus' },
    { title: 'Wave 2', detail: 'FW-RECOG + ANA-5a re-baseline, VIEW-07 export', model: 'opus' },
    { title: 'Integrate 2', detail: 're-baseline generators, gates, commit, push, CI', model: 'opus' },
    { title: 'Wave 3', detail: 'ANA-7/8/9 rule tiers; PERF-03 + CACHE', model: 'opus' },
    { title: 'Integrate 3', detail: 'gates, commit, push, CI', model: 'opus' },
    { title: 'Wave 4', detail: 'NB notebooks (analyzer, hosts, viewer)', model: 'opus' },
    { title: 'Integrate 4', detail: 'gates, commit, push, CI', model: 'opus' },
    { title: 'Review', detail: '4 lenses -> verify -> fix -> integrate', model: 'opus' },
  ],
}

const ROOT = '/Users/minghaoyang/Documents/MLView'
const SCRATCH = '/private/tmp/claude-501/-Users-minghaoyang-Documents-MLView/2ebc6c0c-4dab-49ea-a032-c99b4c9f286e/scratchpad'
const PW = SCRATCH + '/pw'

const PREAMBLE = `
You are one of several autonomous engineers executing Sprint 4 of MLView: the NEXT tier of docs/ROADMAP.md (read section (c) NEXT in full for your items, plus (e) sequencing, (f) decisions, and the "framing to carry forward": every analyzer change must state what it could not analyze). MLView statically analyzes Python ML code and renders the workflow as an interactive diagram in three hosts (standalone HTML report, VS Code extension, Claude Code plugin). Contracts: docs/CONTRACTS.md sections 0, 10, 11 bind (11.18 and 11.19 were added in Sprint 3). Design and status: docs/STATUS.md, docs/FEATURES_FLOW_AND_SCOPE.md, docs/ACCURACY.md, scripts/README.md (the gate table).
LEAD DECISIONS (final): A6's "baseline - do NOT build" is lifted for CI-ADOPT; PACKAGING's third analyzer copy is accepted with a 'vsix: synced core' gate in the same change; NB ships behind --include-notebooks (default path byte-identical); H3 ships; ANA-12's accuracy corpus is the referee for every rule (zero forbidden findings ever; recall only ratchets up); the macOS CI job runs only on main and pull requests from now on. Only the NOW-tier work is on main; VIEW-01 is already done.
ENVIRONMENT (macOS, this Mac): repo root ${ROOT} (git repo; branch sprint4 tracks origin/sprint4; main is protected by convention). START EVERY SHELL COMMAND WITH: export PATH="${ROOT}/.venv/bin:$PATH" PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 - the venv holds Python 3.13 with the analyzer installed editable plus mcp, pytest, pytest-xdist, jsonschema ('python' then means the venv python; the system python3 is 3.9 and must never be used). Node 26 / npm 11 on PATH (CI runs Node 20 and 22, so never rely on Node 26-only APIs). No PowerShell: use 'sh scripts/build.sh' and 'sh scripts/e2e.sh'. No 'claude' CLI (the plugin validate test skips itself) and no 'code' CLI. Playwright + Chromium: run node scripts from ${PW} (its node_modules has playwright) or set NODE_PATH=${PW}/node_modules. Scratch: ${SCRATCH}. GitHub CLI 'gh' is on PATH but not logged in: per command, export GH_TOKEN=$(printf 'protocol=https\\nhost=github.com\\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p') - never print the token; then 'gh run list -R realmyang/MLView --branch sprint4 --limit 5', 'gh run watch <id> -R realmyang/MLView --exit-status', 'gh run view <id> -R realmyang/MLView --log-failed'.
BASELINE (green on this Mac at sprint4 e08a318): sh scripts/e2e.sh 18 steps; analyzer 1218 passed / 3 skipped; webview 300; vscode-extension 203; claude-plugin 286; tools/verify.py --all 9/9; tools/accuracy.py precision 100% / recall 62.9%. Keep every gate green; add to them; never weaken an assertion unless the roadmap item or a re-baseline sanctions it (say which).
GIT RULES (strict): ONLY agents whose brief says "you run git" may run any git command; everyone else never runs git. Commits: imperative subject, body naming the roadmap ids, trailer line 'Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>'. Never force-push, never rewrite history, never touch main. CI cost: the repo is private; keep pushes to one per wave plus fix iterations.
CONTRACT AMENDMENTS: never edit docs/CONTRACTS.md directly (concurrent agents would clobber it). Write your amendment as a NEW file docs/contracts/11.<NN>-<slug>.md using the number your brief assigns, in the same style as sections 11.18/11.19 (normative, additive, dated 2026-09-09); the integrator appends them to docs/CONTRACTS.md in order. Schema changes must be optional fields only, mirrored byte-identically to analyzer/src/mlview/schema/graph.schema.json, and contracts/graph.sample.json never changes; --demo byte parity is a gate.
QUALITY BAR: working software with tests; run the suites you touch and paste real output tails; keep files under ~600 lines (new modules over growing app.ts / build.py); no innerHTML; no getTotalLength; library code never prints to stdout (progress frames go to stderr); write each new source file completely in one Write call so a concurrent agent's test run never imports a half-written module.
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
STEPS: 1) Read the reports below (notes_for_integrator, known_gaps). 2) Append every new docs/contracts/11.*.md file to docs/CONTRACTS.md section 11 in numeric order (then delete the fragment files), and make sure schema mirrors are byte-identical. 3) 'python tools/sync-assets.py' and 'python tools/sync-core.py' (and the new VSIX core sync once PACKAGING exists). 4) Run and fix until green (fix at the source with minimal edits; never rewrite a component): 'sh scripts/e2e.sh' (which runs every suite, the demo artifacts, the parity and accuracy gates and the doc gate); plus 'python tools/verify.py --all' and 'python tools/accuracy.py' explicitly; plus 'npx tsc --noEmit' in webview and vscode-extension. 5) Update scripts/README.md's gate table and docs/STATUS.md for what this wave changed (counts, new gates, new flags); keep 'python scripts/check_docs.py' green. 6) git status; never add scratch, __pycache__, .mlview, .venv, node_modules or dist-of-wheel files (check .gitignore covers new build outputs such as analyzer/dist and vscode-extension/*.vsix); git add -A; commit with the subject in the title and a body listing the roadmap ids; git push origin sprint4; watch CI with gh; on a failing job read --log-failed, fix, commit ('CI: ...'), push, watch again (at most 5 iterations). Report every gate with real output, the commits, and the per-job CI conclusion.
COMPONENT REPORTS:
${JSON.stringify(reports, null, 2)}`

// ------------------------------------------------------------ Wave 1
phase('Wave 1')
const W1_ANALYZER = `${PREAMBLE}
ROLE: analyzer engineer, wave 1 (additive features; you do NOT run git). OWNERSHIP: analyzer/**, contracts/graph.schema.json + its mirror (optional fields only), docs/contracts/11.20-ci-adopt.md, docs/contracts/11.21-answers.md, docs/contracts/11.22-progress.md, docs/rules/** if a doc page needs a note.
ITEMS (read each NEXT entry in full):
- CI-ADOPT (analyzer half): (a) change attribution: '--changed-since <rev>' and '--changed-paths <file>' on analyze and issues; analyze the WHOLE workspace, then classify each issue as new (primary loc inside an added hunk) / touched (changed file outside hunks, or a relatedLoc inside a hunk) / existing, emitted as an OPTIONAL Issue.change enum field; '--changed-only' drops existing from output and from --fail-on accounting; use 'git diff -M --unified=0 <rev>' parsed into per-file added-line ranges; every failure path (no git, not a repo, unknown rev) degrades to unattributed output plus a config_warning diagnostic, never an error and never an empty list. (b) baseline: 'mlview baseline write [--out .mlview/baseline.json]' and '--baseline FILE' on analyze/issues, matching on (code, symbol, snippetHash) where snippetHash = sha1 of the whitespace-normalised primary snippet; a baselined issue is marked (optional Issue.baselined boolean; still emitted; excluded from summary counts and --fail-on) and unmatched baseline entries are reported as a config_warning diagnostic ('N baseline entries no longer match'). (c) '--sarif FILE': SARIF 2.1.0 with rules[] from the registry (id, shortDescription, fullDescription, helpUri = the rule doc path under a %SRCROOT% uriBaseId), results with partialFingerprints {mlviewIssueId: Issue.id}, level from severity, locations with uriBaseId "%SRCROOT%" and relative uris only; validate it in a test against the official SARIF 2.1.0 JSON schema (vendor the schema into analyzer/tests/fixtures/sarif-schema-2.1.0.json - it is public; if you cannot fetch it offline, write a strict structural test instead and say so). Acceptance per the roadmap: on a git-init'd copy of the sample with 7 added lines, '--changed-since HEAD --changed-only' returns 0 findings and exit 0 while the plain run returns 15; a planted MLV203 inside the hunk returns exactly that one; a non-git dir returns all 15 + diagnostic + exit 0; SARIF has 15 distinct fingerprints and no absolute path; fingerprints survive 20 inserted blank lines; baseline write then issues reports 0 unsuppressed and N baselined; a new MLV201 exits 2 with exactly that finding.
- MLV-P1 Pipeline Answer Card: analyzer/src/mlview/emit/answers.py composing an OPTIONAL root-level 'answers' object deterministically from the graph: dataEntry, objective, evaluation, verdict, each {sentence, nodeIds[], locs[], confidence}; absences stated as absences; never assert a fact from a node under 0.6 confidence ('could not determine'); a block at the top of --format summary and text; an 'answers' key in api.digest (digest stays <= 4096 B, drop the two lowest-value fields if needed and say which); acceptance: the four sentences on the sample cite data.py:26, data.py:31, train.py:23 and train.py:44 (verify the actual lines and adjust if the re-baseline moved them - state the real lines); the clean twin's evaluation answer says the eval path is guarded; a workspace with no eval stage names the absence.
- H3: '--progress-json' writing NDJSON frames {"t":"progress","done":N,"total":M,"file":"rel/path.py"} to STDERR, throttled to one per 50 ms with a guaranteed final frame; stdout purity untouched; a test.
Write the three amendment files. Run the analyzer suite and 'python -m mlview analyze --demo --json - | cmp - contracts/graph.sample.json'; paste tails.`

const W1_VIEWER = `${PREAMBLE}
ROLE: viewer engineer, wave 1 (you do NOT run git). OWNERSHIP: webview/** only.
ITEMS (read each NEXT entry in full):
- VIEW-03: lane-seam-aware edge label placement: anchor each label to the longest axis-aligned run of the route lying strictly inside one lane band (fall back to the outlet-adjacent segment); one deterministic greedy declutter pass (document order, fixed iteration cap, grid bucketing) that pushes a colliding label along its own segment or flips it across the stroke, hiding it after the cap; paint-order stroke halo; never within LANE_PAD of a lane boundary; nudge severity markers off label boxes; measure the relayout cost. Add a test that reports label-label overlaps, labels over cards and labels within LANE_PAD on the demo graph and asserts 0 / 0 / 0, and 0 label-label overlaps on a 300-node synthetic at zoom >= 0.62.
- VIEW-12 accessibility scaffolding: skip link as the first tab stop; <main> around the canvas; role=toolbar with arrow-key roving on the chrome (search input keeps its own stop); one real h1 with the workspace name; rail severity headings h4 under an h3 panel heading; minimap aria-hidden with its toggle labelled and before the canvas in DOM order; :focus-visible ring on node cards; tests: canvas reachable in <= 3 presses via the skip link and <= 4 without; exactly one h1 and a monotonic heading outline; the existing chip-filter tests still pass.
- MLV-P10 (viewer half): 'Copy ignore comment' and 'Disable this rule' actions on every rail row and in the Inspector, and on RAIL-GROUP group headers (copy uses the existing copy-toast fallback in bridges.ts; disable posts a new UiToHost message 'suppressRule' {code, scope:'workspace'} that the standalone bridge answers with a copy-toast of the .mlview.toml snippet); suppressed findings rendered as a collapsed 'N suppressed' section.
- MLV-P1 card: a collapsible card pinned above the canvas that renders the document's optional 'answers' block (four sentences, each with clickable file:line links posting openLocation); hidden when the block is absent; state persisted in ViewState.answersOpen.
- CI-ADOPT rendering: when Issue.change is present show a small chip (new / touched / existing) on rail rows and a filter 'only changed'; when Issue.baselined is true render the row in the suppressed section with a 'baselined' chip.
Add types for the optional fields (answers, Issue.change, Issue.baselined) in types.ts and protocol.ts (suppressRule). Run 'npm run build && npm run check && npm test' in webview (300 + new tests green); verify VIEW-03 and the card visually with Playwright on a report you generate in scratch (view PNGs with Read); paste tails.`

const W1_HOSTS = `${PREAMBLE}
ROLE: hosts engineer, wave 1 (you do NOT run git). OWNERSHIP: vscode-extension/** (not media/), claude-plugin/** (not vendor/), tools/** (sync-core.py, verify.py, new tools/action/**), .pre-commit-hooks.yaml, .claude-plugin/marketplace.json, .github/workflows/ci.yml (ONLY the macOS job condition and any new packaging step), README.md, docs/STATUS.md, docs/contracts/11.25-packaging.md, docs/contracts/11.27-suppression-actions.md.
ITEMS (read each NEXT entry in full):
- PACKAGING: bundle the analyzer into the extension: extend tools/sync-core.py to also copy analyzer/src/mlview -> vscode-extension/core/mlview (same skip rules), add a 'vsix: synced core' row to tools/verify.py --all, and .vscodeignore must include core/; pythonEnv.ts precedence chain: an installed core wins when present and its schema major matches and its version is >= the bundled one, else the bundled core (run with PYTHONPATH pointing at <extension>/core), and the status bar tooltip names which is in use; rewrite installCore() to offer 'pip install mlview' (the wheel name) instead of a checkout path; package.json: drop private, add repository/bugs/homepage, a 128x128 icon (generate media/icon.png with a small pure-Python PNG writer script under vscode-extension/tools, a simple two-tone mark; commit the PNG), galleryBanner, preview true, extensionKind ["workspace"], and make 'npm run package' work without --allow-missing-repository; wheel: add 'build' to the venv (pip install build) and a scripts/build.sh step that runs 'python -m build --wheel analyzer' into analyzer/dist (gitignored) and an e2e step that installs the wheel into a throwaway venv and runs 'mlview --version --json'; hosted marketplace: .claude-plugin/marketplace.json source pointing at the GitHub repo (github source form per the Claude Code plugin docs; keep the local './claude-plugin' entry too). Acceptance: 'npm run package' succeeds and the VSIX stays under 1 MB; verify.py 10/10.
- MLV-P10 (host half): a VS Code CodeActionProvider on MLView diagnostics offering 'Copy ignore comment', 'Add ignore comment on this line' (edits the document with a WorkspaceEdit) and 'Disable rule MLVxxx in .mlview.toml' behind a confirm dialog and inside the workspace only; handle the webview's 'suppressRule' message the same way; tests with the mocked vscode module.
- H3 (host half): CoreClient passes --progress-json only when a panel is live, parses stderr lines starting with '{"t":"progress"' into postAnalysisProgress (ignoring frames after analysisFailed by requestId), leaves other stderr in the log; tests.
- CI-ADOPT (host half): tools/action/action.yml composite action (checkout expected by the caller; installs the wheel or 'pip install -e analyzer' when run inside this repo; runs 'mlview analyze . --changed-since <base> --changed-only --sarif mlview.sarif --fail-on high' with inputs for base ref, fail-on and extra args; uploads SARIF via the github/codeql-action/upload-sarif step documented in README); .pre-commit-hooks.yaml with pass_filenames false; MCP mlview_issues gains optional changedSince and baseline parameters and the /mlview-issues command grammar documents '--changed-since <rev>' and '--baseline <file>'; README 'Adopt on an existing repo' section.
- CI cost lever: make the smoke-macos job run only on push to main and on pull_request (this Mac now covers macOS locally); note it in scripts/README.md.
Write the two amendment files. Run 'npm run check && npm run compile && npm test && npm run package' in vscode-extension and the plugin suite; paste tails.`

const W1_HEALTH = `${PREAMBLE}
ROLE: contracts engineer, HEALTH-02 (you do NOT run git). OWNERSHIP: analyzer/tools/gen_scope_fixtures.py (extend), analyzer/tools/scope_fuzz.py (new), tools/verify.py (ONLY the --scopes --fuzz N option; the hosts agent is editing verify.py's --all rows concurrently, so make a minimal, clearly delimited edit and re-read the file immediately before writing), contracts/scope.cases.json + contracts/scope.expected.json (promote counterexamples only), webview/test/scope_fuzz.test.mjs (new; the viewer agent owns the rest of webview/), .github/workflows/nightly.yml (new: scheduled --fuzz 2000).
BUILD the differential fuzzer per the HEALTH-02 entry: a seeded generator of schema-valid graphs (node counts 5-500, hierarchy depth, ghost density, issue-anchoring arity, disconnected components, cross-stage parents) that contracts/validate_sample.py accepts; random selectors across all scope kinds and depths 0-2; run the Python project() and the TypeScript projection (through node, loading webview/dist/mlview.js the way scope_parity.test.mjs does, or a small node harness) and deep-compare node/edge/issue id lists in order, issue.nodeIds rotation, viewRole, all eight stage rows, stats and the whole view object; 'python tools/verify.py --scopes --fuzz 200' under 60 s; promote every discovered counterexample into the fixture files; prove the fuzzer catches a one-line divergence (temporarily drop the rotateToCore call in a scratch copy of project.ts, NOT in the repo, and show it is caught within 50 cases). Run it and paste the results.`

const wave1 = await parallel([
  () => agent(W1_ANALYZER, { label: 'w1:analyzer', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W1_VIEWER, { label: 'w1:viewer', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W1_HOSTS, { label: 'w1:hosts', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W1_HEALTH, { label: 'w1:health', phase: 'Wave 1', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
])
const r1 = { analyzer: wave1[0], viewer: wave1[1], hosts: wave1[2], health: wave1[3] }
log(`Wave 1: ${Object.entries(r1).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)
phase('Integrate 1')
const g1 = await agent(INTEGRATE("Integrate wave 1 and commit it as 'Sprint 4 wave 1: change attribution, baseline, SARIF, answer card, progress frames, label declutter, a11y, suppression actions, packaging, scope fuzzer (CI-ADOPT, MLV-P1, H3, VIEW-03, VIEW-12, MLV-P10, PACKAGING, HEALTH-02)'.", "Also run 'python tools/verify.py --scopes --fuzz 200' and the wheel install step; confirm --demo byte parity.", r1),
  { label: 'integrate:1', phase: 'Integrate 1', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate 1: gates=${g1 && g1.all_passed} ci=${g1 && g1.ci_green}`)

// ------------------------------------------------------------ Wave 2
phase('Wave 2')
const W2_ANALYZER = `${PREAMBLE}
ROLE: analyzer engineer, wave 2 = the framework re-baseline (you do NOT run git). OWNERSHIP: analyzer/**, docs/contracts/11.23-framework-recognition.md, vscode-extension/test/fixtures/vision_pipeline.graph.json (regenerate only if the demo moved), samples/** (expected_issues regeneration only if it moved).
ITEMS (read each NEXT entry in full):
- FW-RECOG: knowledge entries for tf.data (from_tensor_slices, from_generator, list_files, map, shuffle, repeat, cache, batch, prefetch, take, skip, image_dataset_from_directory), datasets (Dataset.map, Dataset.train_test_split with the SPLIT role, load_from_disk, the HF collators), the missing Keras families (keras.applications, Input, Rescaling, GlobalAveragePooling2D, callbacks) and GBM (Classifier/Regressor, fit, predict, predict_proba, DMatrix); Lightning: LightningModule (pytorch_lightning and lightning) in the nn.Module-equivalent base set so the class gets kind model, a hook table (training_step -> train, validation_step/test_step/predict_step -> eval, configure_optimizers -> objective with its return tagged OPTIMIZER, *_dataloader -> data, on_*_epoch_* -> control) using the same mechanism as forward, and trainer.fit(model, ...) as a control edge into the hooks. Ship call-table and hook halves together. Do NOT give take/skip the SPLIT role (ANA-9's ordering check comes later). One positive fixture per family asserting kind + stage. Acceptance: the tf.data probe yields >= 7 connected nodes; the HF probe yields a split-kind node and MLV602 fires on it; analyzer/tests/clean/lightning_module.py yields >= 20 nodes with LitClassifier kind model, an objective node at F.cross_entropy and a populated eval lane while still 0 issues; hf_trainer keeps 0 findings; analyzer/tests/clean stays at 0 issues.
- ANA-5a: a per-call CallSite.unresolved_callee signal (never widen the scope-wide dynamic flag; the demo's 15 findings keep their exact confidence values) set whenever the callee expression is not a Name or Attribute chain (call of a call, subscript, lambda-bound name, match-returned value, dataclass default_factory); mint an 'unknown' op node for it and emit the 'unresolved_callee' diagnostic (the kind exists since 11.18) naming the construct; the summary must not claim a stage is absent without qualification when unresolved calls exist in it. Acceptance per the roadmap on an odd-syntax fixture you write.
Then: run the accuracy tool (recall may only go up; update the baseline only upward), gen_expected_issues.py --check (the sample's 15 issues must be unchanged), gen_scope_fixtures.py --check (unchanged golden), the analyzer suite, perf_equiv (which will legitimately differ on the clean corpus - say so). Write the amendment file. Paste tails and before/after node counts for the clean corpus programs.`

const W2_VIEWER = `${PREAMBLE}
ROLE: viewer engineer, VIEW-07 export (you do NOT run git). OWNERSHIP: webview/**, docs/contracts/11.24-export.md.
ITEM: VIEW-07: an export menu beside the fit button with four outputs: a standalone SVG emitting real rect/text elements from the same LayoutFrame geometry the DOM renderer uses plus the routed edge paths verbatim, with theme tokens resolved to literal colours, a generic font stack, no foreignObject and no external references; a 2x PNG drawn from that SVG on an offscreen canvas; clipboard copy (PNG or SVG text) via the async clipboard API with the existing copy-toast fallback; and an @media print stylesheet that hides toolbar/rail/minimap, releases the canvas transform and sets the world to natural size so Ctrl+P paginates the whole diagram. Offer current view / whole diagram / current scope. In the VS Code webview route the bytes through a new UiToHost message 'exportFile' {kind:'svg'|'png', name, base64} (the hosts side will handle the save dialog; the standalone bridge triggers a download via an object URL and falls back to copy). MANDATORY: drive SVG and DOM from one source and add a gate test asserting one <g> per drawn node and one path per routed edge in the SVG, and that the demo SVG contains all 54 cards, 52 edges, the stage colours, and no 'http' or 'url(' externals; the print stylesheet has a test asserting the hidden chrome. Write the amendment file. Run build/check/test; render an exported SVG through Playwright (open the SVG file in Chromium and screenshot it; view with Read) and paste tails.`

const W2_HOSTS = `${PREAMBLE}
ROLE: hosts engineer, wave 2 (you do NOT run git). OWNERSHIP: vscode-extension/src/**, vscode-extension/test/**, vscode-extension/package.json, claude-plugin/**, docs/STATUS.md, README.md.
ITEMS: (a) handle the viewer's 'exportFile' message (VIEW-07): decode base64, showSaveDialog defaulting to the workspace, write with vscode.workspace.fs, toast; commands mlview.exportSvg / mlview.exportPng that ask the panel to export (a new HostToUi 'requestExport' {kind, scope:'view'|'all'|'scope'} message - define it in protocol.ts and tell the integrator the viewer must accept it; if the viewer already handles it, use its name); (b) MCP: mlview_open_diagram gains optional export ('svg'|'png') returning the file path, implemented by rendering the report and driving the standalone bundle in a headless way is NOT available, so instead implement export in Python: emit/svg_out.py that produces the same SVG structure from the graph and the layout numbers is out of scope - therefore expose only what exists: document in the tool docstring that SVG export is a viewer feature and add a 'reportPath' hint; do not fake it; (c) docs for VIEW-07 in README/STATUS. Run the extension check/compile/test and plugin suite; paste tails.`

const wave2 = await parallel([
  () => agent(W2_ANALYZER, { label: 'w2:analyzer', phase: 'Wave 2', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W2_VIEWER, { label: 'w2:viewer', phase: 'Wave 2', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W2_HOSTS, { label: 'w2:hosts', phase: 'Wave 2', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
])
const r2 = { analyzer: wave2[0], viewer: wave2[1], hosts: wave2[2] }
log(`Wave 2: ${Object.entries(r2).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)
phase('Integrate 2')
const g2 = await agent(INTEGRATE("Integrate wave 2 and commit it as 'Sprint 4 wave 2: framework recognition, unresolved-callee honesty, diagram export (FW-RECOG, ANA-5a, VIEW-07)'.", "This wave is a re-baseline: run every generator with --check, regenerate what legitimately moved (the sample's 15 issues must be unchanged; the golden and scope fixtures must not change), update the graph-size figures scripts/check_docs.py's one-graph-size rule reaches, and ratchet the accuracy baseline only upward. Make sure the viewer accepts the 'requestExport' message the hosts agent defined (or reconcile the names).", r2),
  { label: 'integrate:2', phase: 'Integrate 2', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate 2: gates=${g2 && g2.all_passed} ci=${g2 && g2.ci_green}`)

// ------------------------------------------------------------ Wave 3
phase('Wave 3')
const W3_RULES = `${PREAMBLE}
ROLE: rules engineer, wave 3 (you do NOT run git). OWNERSHIP: analyzer/src/mlview/rules/**, analyzer/src/mlview/knowledge/** (additions only), analyzer/tests/rules/**, analyzer/tests/fixtures/**, analyzer/tests/clean/** (additions only), analyzer/tests/accuracy/** (labels + baseline ratchet upward), docs/rules/** (generated), docs/ISSUE_RULES.md (append the two new codes MLV709 and MLV711 to section 3/4 tables), docs/contracts/11.26-rule-tiers.md. A perf engineer is concurrently editing core/pipeline.py, ingest/**, core/cache.py, core/relevance.py, cli.py and tools/perf_equiv.py - never touch those; if a transient test failure names one of those files, re-run after a minute.
ITEMS: ANA-7 (MLV705-708 per docs/ISSUE_RULES.md section 4 plus the two new codes: MLV709 Keras Dense(activation="softmax") contradicting CategoricalCrossentropy(from_logits=True), MLV711 a Lightning batch-cadence scheduler (OneCycleLR, CyclicLR) returned from configure_optimizers without {"interval": "step"}); ANA-8 (MLV207-209, MLV502, MLV803: ordering predicates over one confirmed loop body; a non-literal GradScaler(enabled=cfg.x) de-rates, never suppresses; negatives derived from analyzer/tests/clean/amp_accumulation.py); ANA-9 (MLV305/306, MLV106, MLV114, MLV121: MLV305 ships at medium with an exhaustive score-metric carve-out and an unresolved-producer de-rate; MLV121 is the tf.data shuffle-before-take/skip holdout failure). Every rule: two fixtures (bad with MLVIEW-EXPECT header, good = the nearest false-positive trap), a generated docs/rules page (run analyzer/tools/gen_rule_docs.py), registry completeness green, test_no_cross_fire green, the precision corpus (analyzer/tests/clean) at 0 findings alone and together, lightning_module.py and hf_trainer.py at 0 findings; then extend the accuracy corpus labels so each new rule has at least one expected and one forbidden entry, run tools/accuracy.py and record the per-rule precision (must be 100%; recall may only ratchet up). Write the amendment file. Paste the accuracy table and the suite tail.`

const W3_PERF = `${PREAMBLE}
ROLE: perf engineer, wave 3 (you do NOT run git). OWNERSHIP: analyzer/src/mlview/core/pipeline.py, core/relevance.py (new), core/cache.py (new), ingest/**, cli.py (only the new flags), api.py (only additive options), analyzer/tests/core/test_relevance.py, test_cache.py, test_perf_budget.py, tools/perf_equiv.py, docs/contracts/11.28-relevance-and-cache.md, docs/STATUS.md (a short note), vscode-extension/src/coreClient.ts (ONLY to pass the cache env/flag), claude-plugin/server/** (ONLY to use the shared file_signature). A rules engineer is concurrently editing rules/**, knowledge/**, tests/rules, tests/fixtures, tests/clean, tests/accuracy - never touch those; if a transient failure names one of those files, re-run after a minute.
ITEMS: PERF-03 relevance prefilter: between discover and build_workspace, byte-scan for the framework token set to get the seed set; ast.parse everything but build only the module import graph; keep a module if it is a seed or within k hops (default 2, '--relevance-hops N') in either direction, computed AFTER re-export resolution (ANA-3); run the IR fixed point and rules over the kept set; emit a config_warning-style diagnostic naming the set-aside count and the flag that includes them; ship behind '--relevance {ml,all}' with 'all' byte-identical and ml as the default ONLY if tools/accuracy.py is identical both ways (measure and decide; say what you chose); acceptance: a mixed 500-file synthetic (50 ML files) drops under 1.5 s reporting the same issues as --relevance all; the demo and every fixtures/rules case identical in both modes; --demo parity. CACHE: promote file_signature into mlview.core (one implementation; the plugin's mlview_workspace uses it), keyed on content hash + sys.version_info[:2] + analyzer identity; cache per-file derived facts as a sidecar under the data dir (MLVIEW_CACHE_DIR, default <project>/.mlview/cache); delta re-analysis recomputes only changed modules' facts then re-runs the cross-module fixed point and the rules; report cached: full|partial|none in a diagnostic-free way (a field in stats is not allowed - schema frozen - so use stderr logging plus the digest); MLVIEW_NO_CACHE=1 disables; acceptance: editing one file in a 500-file repo re-analyses under 2 s and the document is byte-identical to a cold run (a test mutating a random file); determinism and CLI-vs-MCP parity gates stay green with the cache enabled. Update perf_equiv to take '--expect-same' / '--expect-diff' so the integrator can wire it. Write the amendment file. Paste timings and suite tails.`

const wave3 = await parallel([
  () => agent(W3_RULES, { label: 'w3:rules', phase: 'Wave 3', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W3_PERF, { label: 'w3:perf', phase: 'Wave 3', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
])
const r3 = { rules: wave3[0], perf: wave3[1] }
log(`Wave 3: ${Object.entries(r3).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)
phase('Integrate 3')
const g3 = await agent(INTEGRATE("Integrate wave 3 and commit it as 'Sprint 4 wave 3: framework, training-mechanics and held-out rule tiers; relevance prefilter; per-file cache (ANA-7, ANA-8, ANA-9, PERF-03, CACHE)'.", "Run the accuracy tool and check every new rule shows 100% precision; run perf_equiv with the expectation flag; run the cache byte-identity test twice; sync vendor and the VSIX core.", r3),
  { label: 'integrate:3', phase: 'Integrate 3', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate 3: gates=${g3 && g3.all_passed} ci=${g3 && g3.ci_green}`)

// ------------------------------------------------------------ Wave 4
phase('Wave 4')
const W4_ANALYZER = `${PREAMBLE}
ROLE: analyzer engineer, wave 4 = NB notebooks (you do NOT run git). OWNERSHIP: analyzer/**, docs/contracts/11.29-notebooks.md, docs/REQUIREMENTS.md (ONLY a dated note under section 5 non-goal 3 saying notebook analysis now exists behind a flag).
ITEM NB per the roadmap entry: an .ipynb ingest path behind '--include-notebooks' and '[paths] notebooks = true' in .mlview.toml (byte-identical behaviour without it): read the JSON, take code cells, replace IPython magics and shell escapes with 'pass  # mlview: magic' preserving line counts 1:1, handle source as string or list, concatenate in document order with a per-cell offset table so every Loc maps to (cell, cellLine) as well as the flat line (carry cell and cellLine in Loc-adjacent attrs: node.attrs.cell / issue evidence detail, since Loc itself is frozen; document the mapping); materialise a shadow .py under the data dir so test_locations.py can slice it; a non-monotonic execution_count emits the 'notebook_analyzed' diagnostic variant saying the notebook was last run out of order and de-rates order-sensitive rules (MLV101, MLV203, MLV209); notebooks that fail to parse still count in notebooksSkipped. Acceptance: the 4-cell leak notebook exits 0, filesAnalyzed 1, fires MLV101 and MLV201 with correct cell indices; test_locations passes for notebook fixtures; execution_count [1,3,2,4] emits the out-of-order diagnostic and its MLV101 confidence is strictly lower than the same code in a .py. Write the amendment file. Run the suite; paste tails.`
const W4_HOSTS = `${PREAMBLE}
ROLE: hosts engineer, wave 4 (you do NOT run git). OWNERSHIP: vscode-extension/src/**, vscode-extension/test/**, vscode-extension/package.json, claude-plugin/** (not vendor/), README.md, docs/STATUS.md.
ITEM NB host half: setting mlview.includeNotebooks (default false) passing --include-notebooks; publish notebook findings on vscode-notebook-cell URIs so squiggles land in the real cell (derive the cell URI from the notebook document's cells by index; fall back to the .ipynb file URI); re-analyze on onDidSaveNotebookDocument; the status-bar tooltip reads 'N notebooks analyzed' vs 'not analyzed'; MCP mlview_analyze gains includeNotebooks and the /mlview command documents it; tests with the mocked vscode module (add NotebookDocument stubs). Run check/compile/test and the plugin suite; paste tails.`
const W4_VIEWER = `${PREAMBLE}
ROLE: viewer engineer, wave 4 (you do NOT run git). OWNERSHIP: webview/** only.
ITEM NB viewer half: when a node or issue carries a cell mapping (the analyzer agent documents the attrs it uses in docs/contracts/11.29-notebooks.md; read it, and if it is not there yet poll for it), show locations as 'name.ipynb > cell 3 : 4' in cards, rail rows, inspector and tooltips, keep openLocation posting the flat line (hosts map it), and render the out-of-order diagnostic as a banner. Tests. Run build/check/test; paste tails.`
const wave4 = await parallel([
  () => agent(W4_ANALYZER, { label: 'w4:analyzer', phase: 'Wave 4', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' }),
  () => agent(W4_HOSTS, { label: 'w4:hosts', phase: 'Wave 4', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
  () => agent(W4_VIEWER, { label: 'w4:viewer', phase: 'Wave 4', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' }),
])
const r4 = { analyzer: wave4[0], hosts: wave4[1], viewer: wave4[2] }
log(`Wave 4: ${Object.entries(r4).map(([k, v]) => `${k}=${v ? (v.all_tests_passing ? 'green' : 'RED') : 'MISSING'}`).join(', ')}`)
phase('Integrate 4')
const g4 = await agent(INTEGRATE("Integrate wave 4 and commit it as 'Sprint 4 wave 4: notebook analysis behind --include-notebooks with a cell line map and an execution-order caveat (NB)'.", 'Confirm the default path is byte-identical (demo parity, perf_equiv --expect-same on the three corpora with notebooks excluded).', r4),
  { label: 'integrate:4', phase: 'Integrate 4', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`Integrate 4: gates=${g4 && g4.all_passed} ci=${g4 && g4.ci_green}`)

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
  `LENS: analysis precision and honesty. Exercise FW-RECOG, ANA-5a, the new rule tiers and NB on new programs you write (a tf.data Keras classifier with a shuffle-before-take holdout, an HF datasets fine-tune, a Lightning module with a OneCycleLR scheduler, a research script with lambda/match/default_factory indirection, a leaky notebook and a correct notebook); judge false positives (the tolerance is zero), missed findings, node fidelity, the unresolved-callee honesty, cell mapping correctness (open the notebook and check cell indices), the relevance prefilter's equivalence (--relevance ml vs all on your programs), the cache's byte identity after edits, and the accuracy corpus labels' truthfulness.`,
  `LENS: viewer and export quality. With Playwright (from ${PW}) on the regenerated reports: VIEW-03 label placement (count overlaps yourself, view screenshots), VIEW-12 keyboard path (tab counts, headings), MLV-P10 actions and the suppressed section, the MLV-P1 card and its links, change/baselined chips, VIEW-07 exports (open the SVG and PNG, compare to the DOM render; print stylesheet via emulateMedia print), NB location display; a11y and console errors.`,
  `LENS: hosts and adoption. PACKAGING: build the VSIX, inspect its contents (unzip) for core/ and size; simulate a fresh-machine install path by running the bundled core via PYTHONPATH with the system python3.13 (no venv) and 'mlview --version --json' from the wheel in a throwaway venv; the precedence chain logic via the mocked tests. CI-ADOPT: run the composite action's command sequence locally on a git-init'd scratch copy (changed-since attribution, --changed-only, --sarif, validate SARIF against the 2.1.0 schema, baseline write/ratchet); pre-commit hook config validity (pre-commit try-repo if installable via pip in scratch). MLV-P10 code actions and the .mlview.toml write guard. H3 frames parsing. MCP: the new parameters (changedSince, baseline, includeNotebooks) with the SDK client; results still <= 4 KB; plugin validate skip note. The nightly fuzz workflow file validity.`,
  `LENS: process, regressions and docs. Diff sprint4 against main (read-only git); list every changed or deleted assertion and judge whether the roadmap sanctions it; check --demo parity, perf_equiv expectations, verify.py 10/10, e2e step count consistency across docs, the gate table, README quick starts followed literally on this Mac, docs/CONTRACTS.md section 11 integration of all amendment files (no fragments left in docs/contracts/), docs/STATUS.md and docs/ROADMAP.md 'landed' notes, CI run health and cost (gh with GH_TOKEN: per-job durations, the macOS gating), .gitignore hygiene (no wheel/vsix/cache files committed: git ls-files).`,
]
const reviews = (await parallel(LENSES.map((lens, i) => () =>
  agent(`${PREAMBLE}
ROLE: reviewer. You do NOT modify repo files and do NOT run git write commands. Find real defects with reproducible evidence; critical = wrong results / crash / roadmap acceptance not met; major = clearly wrong or visibly poor; minor = polish. Give overall_assessment.
${lens}
Integration status: ${JSON.stringify([g1, g2, g3, g4].map(g => g && { all_passed: g.all_passed, ci_green: g.ci_green, remaining: g.remaining_problems }))}`,
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
    const DIRS = { analyzer: 'analyzer/**, samples/**, tools/accuracy.py, tools/perf_equiv.py, docs/rules/**', webview: 'webview/**', 'vscode-extension': 'vscode-extension/** (not media/ or core/, which are synced)', 'claude-plugin': 'claude-plugin/** (not vendor/), tools/action/**, .pre-commit-hooks.yaml', 'process-docs': '.github/**, scripts/**, tools/verify.py, tools/sync-core.py, README.md, docs/STATUS.md, docs/ROADMAP.md, docs/CONTRACTS.md (integration of amendments only), scripts/README.md' }
    await parallel(Object.keys({ ...by, ...minorsBy }).map(c => () =>
      agent(`${PREAMBLE}
ROLE: fixer for '${c}' (you do NOT run git). Fix every CONFIRMED finding at its root cause and the OPTIONAL minors when cheap. OWNERSHIP: ${DIRS[c] || c}. Run that component's tests and paste the tail; add a regression test per confirmed finding.
CONFIRMED: ${JSON.stringify(by[c] || [], null, 2)}
OPTIONAL MINORS: ${JSON.stringify(minorsBy[c] || [], null, 2)}`,
        { label: `fix:${c}`, phase: 'Review', schema: REPORT_SCHEMA, model: 'opus', effort: 'high' })))
    gR = await agent(INTEGRATE("Integrate the review fixes and commit them as 'Review fixes for Sprint 4 (see body)'.", 'Re-run everything including the accuracy tool, the fuzzer, and the wheel/VSIX steps; regenerate fixtures only if a fix legitimately moved the graph (say so). Finally add a dated "Landed 2026-09-09" measurement note under each NEXT-tier entry in docs/ROADMAP.md that shipped, in the style of the VIEW-01 note.', { fixes_for: confirmed.map(f => f.title) }),
      { label: 'integrate:review', phase: 'Review', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
    log(`Integrate review: gates=${gR && gR.all_passed} ci=${gR && gR.ci_green}`)
  }
}

return {
  waves: [r1, r2, r3, r4].map(r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v ? { passing: v.all_tests_passing, ids: v.roadmap_ids_done, gaps: v.known_gaps.slice(0, 6) } : null]))),
  integrations: [g1, g2, g3, g4, gR].map(g => g && { all_passed: g.all_passed, ci_green: g.ci_green, commits: g.commits, remaining: g.remaining_problems }),
  review: { confirmed: confirmed.map(f => ({ id: f.id, component: f.component, severity: f.severity, title: f.title })), assessments: reviews.map(r => r.overall_assessment) },
}
