# scripts/

Two drivers, each in a PowerShell and a POSIX-sh flavour, plus one Python gate
they both call. The two flavours do the same thing; pick whichever shell you are
in. Both are Windows-safe: no `shell: true`, no
symlinks, no `chmod`, and the PowerShell versions are Windows PowerShell 5.1
compatible (no `&&`, no `||`, no ternaries — every step checks `$LASTEXITCODE`).
The `.sh` flavour also runs on Linux and macOS, which is what the `e2e (ubuntu,
sh)` CI job exercises.

| Script | What it does |
|---|---|
| `build.ps1` / `build.sh` | Build everything, in the only order that works. |
| `e2e.ps1` / `e2e.sh` | Build, run every suite, analyze the samples, write the scoped demo reports, render them, run the parity, scope, accuracy and doc gates, print a PASS/FAIL table. |
| `check_docs.py` | The doc gate, checks 1-8: dead paths, dead Markdown links, "known gap" bullets that still describe a failure somebody already fixed, gap bullets that cite nothing checkable or cite a symbol that has been renamed away, a frozen design record that has started reporting build state, a POSIX shell script written with CRLF, and two docs that disagree about the size of the demo graph. |
| `doc_numbers.py` | The doc gate, checks 9-11 — the numbers a machine can settle: `docs/ACCURACY.md`'s headline against `analyzer/tests/accuracy/baseline.json`, an `upload-artifact` step whose hidden path would silently upload nothing, and an "N steps" claim that is not the number of rows both e2e drivers print. |
| `pythonpick.sh` | Sourced by both `.sh` drivers: finds a Python 3.10+ and exports `PYTHON`. `python` first under Git Bash, `python3` first elsewhere, because on Windows `python3.exe` is usually the Store alias and on Linux/macOS `python` usually does not exist. |
| `test_check_docs.py` / `test_doc_numbers.py` | The doc gate's own test suite — thirty-nine cases: thirty-four throwaway trees, one unit test for the symbol parser, four that read the real repo. Running either file runs all of them; `pytest scripts` does too. |

---

## The gate table

[![CI](https://github.com/realmyang/MLView/actions/workflows/ci.yml/badge.svg)](https://github.com/realmyang/MLView/actions/workflows/ci.yml)

Every gate below runs in CI on every push — ubuntu across Python 3.10-3.13 and
Node 20/22, plus one Windows end-to-end job, one packaging job and one macOS
smoke job (the macOS one **only on push to `main` and on pull requests** — macOS
minutes are billed 10x and this Mac now runs the whole table locally before every
push, so paying tenfold for a signal a laptop already produced bought nothing;
the pre-merge coverage is unchanged) (see
`.github/workflows/ci.yml`, and the "Continuous integration" section of the root
README for the job table). There are four exceptions. Rows 10 and 11: `claude
plugin validate` is not available on a hosted runner, so that test skips itself
there and those two rows are still verified from a desk (Windows 11, Python 3.13
/ miniconda, Node 20.9, VS Code 1.136, Claude Code CLI 2.1.186). And row 24,
which as printed needs a second checkout of the pre-change tree to diff against,
so it is run by hand around a change rather than on every push — `tools/perf_equiv.py`
does support `--record FILE` / `--compare FILE` against a committed digest file,
which is what would turn it into an automatic row. And row 12d, which needs the
`.mlview/graph.json` an e2e run produces: the assertions it makes about the
export renderer are also made by row 3a on the frozen `contracts/graph.sample.json`
inside `npm test`, so what row 12d adds is the same check over a *real* 54-node
document, run beside `scripts/e2e` rather than inside it.

`scripts/e2e` runs all of them in one pass; the middle column is how to run just
that one.

| # | Gate | Command | Result |
|---|---|---|---|
| 1 | Build | `powershell -ExecutionPolicy Bypass -File scripts/build.ps1` | `BUILD OK` — 6/6 steps (step 6 is PACKAGING's wheel; it says so and carries on when `build` is not installed) |
| 2 | Analyzer + rules | `python -m pytest analyzer/tests -q` | 1327 passed, 3 skipped (the third needs Python 3.10, where tomllib is absent) |
| 2a | Framework recognition (FW-RECOG) | `python -m pytest analyzer/tests/core/test_framework_recognition.py -q` | 24 passed — the seven-call `tf.data` chain is 7 connected nodes, `take`/`skip` are **not** split-kind, `datasets.Dataset.train_test_split` is split-kind and arms MLV602, every Lightning hook lands in the lane the framework runs it in, and a Keras file never picks up a torch framework |
| 2b | Unresolved callees (ANA-5a) | `python -m pytest analyzer/tests/core/test_unresolved_callee.py -q` | 13 passed — 5 `unknown` ops on the odd-syntax fixture, one `unresolved_callee` diagnostic naming the lambda / `match` case / `default_factory` constructs, the scope-wide dynamic flag **not** widened, and the demo's 15 confidences pinned |
| 3 | Viewer tests | `npm test` in `webview` | 360 pass, 0 fail |
| 3a | Diagram export, viewer half (VIEW-07) | `node --test test/export.test.mjs` in `webview` | 19 pass — one `<g data-node-id>` per planned card and one `<path data-edge-id>` per planned route, in plan order and with `d` byte-identical to the routed edge; the SVG references nothing outside itself; 87 palette tokens equal `styles/tokens.css`; the `@media print` block hides the chrome and releases the world transform; `exportFile` and `requestExport` round-trip |
| 4 | Viewer typecheck | `npm run check` in `webview` | `tsc --noEmit`, clean |
| 5 | Extension typecheck | `npm run check` in `vscode-extension` | `tsc --noEmit`, clean |
| 6 | Extension bundle | `npm run compile` in `vscode-extension` | `out/extension.js` 150.4 kb |
| 7 | Extension tests | `npm test` in `vscode-extension` | 273 pass, 0 fail |
| 7a | Diagram export, host half (VIEW-07) | `node --test test/export.test.js` in `vscode-extension` | 17 pass — the base64 / 32 MiB / basename guard, the PNG-signature and SVG-opening-tag format check *before* the save dialog, the deferred `requestExport`, and the toast's Open / Copy Path actions |
| 8 | Plugin / MCP tests | `python -m pytest claude-plugin/tests -q -n auto` | 296 passed, 5 skipped in ~10 s (~36 s without `-n auto`) |
| 9 | Parity gates | `python tools/verify.py --all` | all 10 gates passed |
| 9a | Scope parity (Python == TypeScript) | `python tools/verify.py --scopes` | 10 projections + 6 error cases, python == typescript (24 assertions) |
| 9b | Scope fixtures current | `python analyzer/tools/gen_scope_fixtures.py --check` | 10 projecting + 6 error cases over the golden, plus the promoted `fuzzCases` on their own graphs |
| 9c | Scope fuzz — promoted counterexamples | `python tools/verify.py --scopes --fuzz 200` | 3 promoted counterexamples replay, python == typescript — each is a minimized document the fuzzer once found the two ports disagreeing on (HEALTH-02) |
| 9d | Scope fuzz — generated graphs | (same command) | 200 cases over 40 generated graphs (5-500 nodes), python == typescript, ~2 s; the seed is printed so `MLVIEW_FUZZ_SEED=<n>` replays it. `.github/workflows/nightly.yml` runs 2000 cases (~16 s) once a day |
| 10 | Plugin manifest | `claude plugin validate ./claude-plugin --strict` | Validation passed |
| 11 | Marketplace manifest | `claude plugin validate ./.claude-plugin/marketplace.json --strict` | Validation passed |
| 12 | Report renders | `node test/render_report.mjs` in `webview` | 20/20 assertions |
| 12b | Clean report renders | `node test/render_report.mjs ../.mlview/report_clean.html --min-ghosts=0` | 20/20 assertions |
| 12c | Scoped report renders | `node test/render_report.mjs ../.mlview/evaluation.html --scope=concern:evaluation` | 23/23 assertions — no empty band, badge-free boundary stubs, the breadcrumb still names the project total |
| 12d | Diagram exports to SVG (by hand, like row 24: it needs `.mlview/graph.json`, which `scripts/e2e` produces) | `node test/export_svg.mjs ../.mlview/graph.json` in `webview` | `SVG EXPORT CHECK OK` — 54 of 54 cards, 51 of 51 routed edges, every document edge reached the picture, the only `http` is the `xmlns`, no `url(` / `foreignObject` / `xlink` / `<image` / `<script` / `@font-face` / `@import` / `var(--`, every drawn lane's stage colour present as a literal, well-formed XML, 237 real `<text>` nodes and 180 `<rect>`s |
| 13 | Panel + media bundle | `node --test test/panelhtml.test.js` in `vscode-extension` | 4 pass |
| 13b | Cross-host scope handshake | `node test/crosshost.mjs ../.mlview/graph.json` in `webview` | 28/28 assertions — the real viewer bundle answers the real extension's `setScope`, and `parseUiToHost` / `scopeChrome` accept what it posts |
| 14 | Rule docs current | `python analyzer/tools/gen_rule_docs.py --check` | 21 pages current |
| 15 | Sample issues current | `python analyzer/tools/gen_expected_issues.py --check` | 15 issues — 5/6/4 |
| 16 | Golden parity | `python -m mlview analyze --demo --json -` vs `contracts/graph.sample.json` | byte-identical, 46 078 bytes |
| 17 | Emitted docs valid | `python contracts/validate_sample.py .mlview/graph.json` | schema 1.0 + 10 invariant groups, 54 nodes / 51 edges / 15 issues |
| 18 | Docs match the tree | `python scripts/check_docs.py` | 19 files (16 docs + 3 shell scripts), no dead paths, every known gap anchored, no build state in a plan doc, LF in every shell script, one graph size, the accuracy headline equal to the baseline, no silent artifact upload, one e2e step count |
| 19 | End to end | `powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1` | `E2E OK` — 19 steps, 0 failed |
| 20 | Scoped demo artifacts | `python -m mlview analyze samples/vision_pipeline --scope concern:evaluation --depth 1 --html .mlview/evaluation.html` | 17 of 54 nodes (7 core / 7 boundary / 3 context), `data-mlview-scope` and `data-mlview-depth` set on the root |
| 21 | Scope catalogue | `python -m mlview analyze samples/vision_pipeline --list-scopes` | 10 scopable units, biggest first |
| 22 | Bytecode residue never poisons the vendor gate | `python -m pytest claude-plugin/tests/test_vendor_bytecode.py -q` | 3 passed — pytest over a throwaway vendored tree writes no `__pycache__` with the flag set and does write one without it, and `sync-core --check` prunes planted residue and stays green |
| 23 | Accuracy corpus (also a row in `scripts/e2e`) | `python tools/accuracy.py` | `accuracy gate: PASS` — 10 labelled programs, precision 100.0%, unseen recall 51.1% raw / 38.3% visible, graph fidelity 90.6%; zero `forbidden` findings, nothing below `analyzer/tests/accuracy/baseline.json` |
| 23a | The same three gates, asserted | `python -m pytest analyzer/tests/accuracy -q` | 35 passed — corpus lint plus the matcher's own semantics |
| 24 | Analyzer byte-equivalence | `python tools/perf_equiv.py --baseline DIR --diff --bench` | both shipped samples byte-identical to `main`; `analyzer/tests/clean` gains exactly one `ValueTag` (PERF-02's fifth IR round), 200-file corpus 2.25x faster |
| 26 | Wheel installs and runs | `python tools/wheel_check.py` (also a row in `scripts/e2e`) | `wheel-check: OK mlview-0.1.0-py3-none-any.whl -> mlview 0.1.0, 4 node(s), 2 issue(s) in a clean venv` — built with `python -m build --wheel analyzer`, installed into a throwaway venv, run through the **console script**, then one real analysis so a wheel missing `schema/*.json` cannot pass |
| 27 | VSIX packages and stays small | `npm run package` in `vscode-extension` | `Packaged: mlview-0.1.0.vsix (105 files, 513.05 KB)` — no `--allow-missing-repository`, `core/mlview` (74 files) included, under the 1 MB ceiling |
| 28 | The icon is what its script renders | `python vscode-extension/tools/make_icon.py --check` | `make_icon: OK ... matches (890 bytes, 128x128)` |
| 25 | CI matrix | `.github/workflows/ci.yml` | On the Sprint 4 wave 2 push to `sprint4` (run 34298585002): **12 jobs green, `smoke (macos)` skipped** — Python 3.10-3.13, Node 20/22, both e2e drivers, `packaging (wheel + vsix)` (50 s) and the accuracy corpus (16 s). **5m51s wall, ~30 billable minutes** (~18 ubuntu at 1x, per-job minute rounding + 12 windows at 2x + **0 macos**), and both e2e jobs archive `mlview-reports-*` (CI-ARTIFACTS-01). macOS runs on push to `main` and on pull requests, where it is 13 jobs |
| 25a | Nightly scope fuzz | `.github/workflows/nightly.yml` | `python tools/verify.py --scopes --fuzz 2000` on a 04:17 UTC schedule plus `workflow_dispatch`, ubuntu 1x, ~16 s of fuzzing. GitHub only schedules cron from the default branch, so it starts firing once this lands on `main` |

Rows 16–18 are also asserted inside rows 2 and 19; they are listed separately
because each is a one-line command that answers a question a reviewer asks
directly ("is the golden still the golden?", "does what it just wrote validate?").

`tools/verify.py --all` is itself ten rows, in this order: one version row, the
`plugin: rule docs` row, the CLI-vs-MCP graph parity row, `vendor: synced core`,
`vsix: synced core` (PACKAGING's condition for a third copy of the analyzer — it
also fails when `.vscodeignore` would drop `core/` out of the package), the two
scope rows (`scopes: fixtures` and `scopes: python == ts`), and three
renderer-hash rows. `--fuzz N` adds two more scope rows to `--scopes`, and only
when asked for: `--all` never fuzzes, so no existing gate got slower. The scope rows sit **between** the analyzer-parity row and
the renderer rows because a projection divergence is an analyzer fact, not a
bundle fact (CONTRACTS 11.15).

---

## build

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipNpmInstall -SkipPipInstall
```

```sh
sh scripts/build.sh
sh scripts/build.sh --skip-npm-install --skip-pip-install
```

1. `webview` — `npm install` + `npm run build` → `webview/dist/mlview.{js,css}`
2. `tools/sync-assets.py` → copies that bundle into `vscode-extension/media/` and
   `analyzer/src/mlview/emit/assets/`
3. `tools/sync-core.py` → copies `analyzer/src/mlview` into **both**
   `claude-plugin/vendor/mlview` and `vscode-extension/core/mlview` (PACKAGING)
4. `vscode-extension` — `npm install` + `npm run compile` + `npm run check`
5. `analyzer` — `pip install -e analyzer`, then `python -m mlview --version`
6. `analyzer` — `python -m build --wheel analyzer` → `analyzer/dist/*.whl`, the
   artifact `pip install mlview`, the CI-ADOPT action and `installCore()` all
   name. A missing `build` prints one line and the build carries on: a publishing
   tool nobody has installed must never redden a developer's build

**The order is not arbitrary.** `generator.rendererSha` is the SHA-256 of the
`mlview.js` the analyzer ships, computed at runtime, so the viewer must be built
and synced *before* the analyzer emits anything you intend to compare. Until
step 2 runs, `rendererSha` is 64 zeros and `--html` produces a plain-table
fallback with a visible "Viewer bundle not synced" banner.

**Step 3 is the one people forget.** Nothing about the Claude Code path fails
loudly when `claude-plugin/vendor/` is stale — the MCP server simply runs an old
analyzer, and a stale `vscode-extension/core/` ships an old analyzer inside the
VSIX. `tools/verify.py --all` reports each of the two as its own row
(`vendor: synced core`, `vsix: synced core`) for exactly that reason.

## e2e

```powershell
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1 -SkipBuild
```

```sh
sh scripts/e2e.sh
sh scripts/e2e.sh --skip-build
```

1. `scripts/build`
2. `python -m pytest analyzer/tests -q`
3. `npm test` in `webview`
4. `npm test` in `vscode-extension`
5. `python -m pytest claude-plugin/tests -q`
6. `python -m mlview analyze samples/vision_pipeline --json .mlview/graph.json
   --html .mlview/report.html`, and the clean twin to `.mlview/graph_clean.json`
   + `.mlview/report_clean.html`
7. `node webview/test/render_report.mjs` — load the report in jsdom and check it
   actually *draws*
8. the same for the clean twin, with `--min-ghosts=0`
9. the three **scoped demo artifacts** — `.mlview/split.html`
   (`--scope unit:train_test_split`), `.mlview/optimization.html`
   (`--scope concern:optimization`) and `.mlview/evaluation.html`
   (`--scope concern:evaluation --depth 1`), the three demos of
   `docs/FEATURES_FLOW_AND_SCOPE.md` section 8 — the depths are the demos'
   own: the per-kind default for B and C, `--depth 1` for D, whose boundary
   ring is what shows *what feeds* evaluation. The step also measures every
   report the run wrote against amendment A4's contracted **100 KB – 2 MB**
   band and prints the range in the table, because a KB figure written into a doc
   rots the next time the bundle grows (MLV-R1-H06). One thing to expect in
   Demo B: lane placement wins over containment, so `train_test_split` (stage
   `data`) draws in the DATA lane *beside* its `baseline()` frame (stage
   `preprocess`) rather than inside it — the pre-existing rule that a node whose
   parent sits in another stage is promoted to a root of its own lane, which the
   scope projection deliberately leaves untouched
10. the same jsdom render check over `.mlview/evaluation.html`, with
    `--scope=concern:evaluation` — the breadcrumb, the "not in this scope" chip
    row, and only the scope's cards. It reports SKIP, with the reason, when the
    viewer has no `--scope=` flag or when the report inlines a bundle that is not
    the one `webview/dist` holds (a report written before `tools/sync-assets.py`
    ran embeds a pre-scope viewer, which the bundle-hash gate already reports)
11. `node --test vscode-extension/test/panelhtml.test.js` — the panel HTML points
    at the two files `sync-assets.py` wrote, and they are on disk
12. `node webview/test/crosshost.mjs` — the **cross-host scope handshake**: the
    real `webview/dist/mlview.js` answers the real `setScope` message, and the
    real `vscode-extension/out/test-entry.cjs` parses what it answers. Both
    CONTRACTS §11.7 suites otherwise stand on one side of the wire — the viewer
    posts into a recording bridge, the extension reads a hand-written object — so
    nothing else would catch the selector field drifting from `spec` to `scope`.
    SKIPs, with the reason, when the extension's test bundle is not built
13. `python tools/wheel_check.py` — PACKAGING's row: build the wheel, install it
    into a throwaway venv, run `mlview --version --json` through the **console
    script**, then one real analysis, so a wheel missing its package data cannot
    pass. Reports SKIP, with the reason, when there is no wheel to test
14. `python tools/verify.py --scopes` — the Python projection and the TypeScript
    port project the same battery identically
15. `python tools/verify.py --all` — the parity gates
16. `python tools/accuracy.py` — the labelled accuracy corpus (ANA-12's referee):
    zero forbidden findings, nothing below `analyzer/tests/accuracy/baseline.json`
17. `python scripts/test_check_docs.py` — the doc gate's own self-test
18. `python scripts/check_docs.py` — the docs still match the tree
19. the PASS/FAIL table

**Every step runs even when an earlier one failed.** A run that stops at the
first failure hides the other eighteen, and the whole point of the table is to see
the state of the system in one screen. The exit code is 1 if anything failed.

**SKIP is not FAIL.** Both sample workspaces are present now, so they run; the
sample steps report `SKIP` instead of failing on a checkout where `samples/` is
absent, because the samples are the rules agent's deliverable (amendment A12),
not a precondition for the rest of the build.

`MLVIEW_NO_OPEN=1` is set for the whole run, so nothing launches a browser.

### Why steps 7-9 exist

Every other gate proves the report *parses*. Neither proves it *renders*: a
viewer that mounted and drew nothing, or an extension pointing at a bundle the
sync never wrote, would sail through all of them. Step 7 loads
`.mlview/report.html` in jsdom exactly as a browser would — the inlined bundle,
the inlined graph, the real bootstrap — and asserts the node cards, all three
severity marker shapes, every declared ghost slot, the seven lane bands, the
"not detected" chip row, a clean console, and that clicking a card really posts
`openLocation` with `vscode://file/<abs>:<line>:<col+1>`. Step 8 runs the same
check over the clean twin, which draws no markers and declares no ghosts at all.
Step 9 does the same job for the VS Code panel.

```sh
cd webview
node test/render_report.mjs                                   # the dirty sample
node test/render_report.mjs ../.mlview/report_clean.html --min-ghosts=0
```

The clean twin has no findings and therefore no ghost slots, so it wants
`--min-ghosts=0`; every ghost a document *does* declare must still be drawn.

### Why the scope gate exists

Feature 2 is one algorithm written twice — `analyzer/src/mlview/core/project.py`
in Python and `webview/src/scope/project.ts` in TypeScript — because the CLI must
be able to project a document without a browser and the report must be able to
re-scope without an analyzer. Two implementations of one specification drift; the
only question is whether anyone finds out.

So the battery is data, not code: `contracts/scope.cases.json` names ten
selectors plus six error codes, `contracts/scope.expected.json` holds what the
Python `project()` produces for each of them, and both are computed over the
**frozen** `contracts/graph.sample.json` so a rule change can never redden this
gate. `python tools/verify.py --scopes` regenerates the fixtures and byte-diffs
them (writing nothing), then runs `webview/test/scope_parity.test.mjs`, which
pushes the same cases through the TypeScript port and deep-compares the node,
edge and issue id lists **in order**, every `issue.nodeIds` (so the stable
rotation is checked), every node's `viewRole`, all eight stage rows, `stats`, and
the whole `view` object.

```sh
python tools/verify.py --scopes                       # both halves
python analyzer/tools/gen_scope_fixtures.py --check   # just the Python half
cd webview && node --test test/scope_parity.test.mjs  # just the TypeScript half
```

A Python-side change the port did not follow fails here rather than shipping two
different answers to one question.

### Why the doc gate exists

A README's "known gaps" list is the part a reviewer weighs most, and it rots
silently: someone fixes the test, nobody deletes the bullet that says it fails,
and the honesty section is now wrong in the direction that costs the most
credibility. `check_docs.py` fails the run when a current-state doc names a file
that is not on disk, links to a Markdown file that is not there, or claims a
test fails while that test is in the tree and green.

Round 2 found the hole in that: a bullet does not have to name a test to be
stale. The README described the absence-rule framework gate as workspace-wide
long after `ctx.wrappers_for()` made it per-module, and nothing could tell
(MLV-R2-109). So two more checks now apply inside a "Known gaps" section, and
only there: every bullet must cite a repo path or a code symbol in backticks,
and every symbol it cites must still exist somewhere under `analyzer/`,
`webview/`, `vscode-extension/`, `claude-plugin/`, `tools/`, `scripts/`,
`contracts/` or `samples/`. Rename the code a gap describes and the build fails
on the sentence that describes it, which is the only moment anyone will reread
it. Docs never vouch for docs: the symbol index is built from source only.
Frozen design records
(`docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md`, `docs/ISSUE_RULES.md`,
`docs/UX_DESIGN.md`) are link-checked only — they describe what was *planned*,
and editing them to match the build would erase the decision record.
`docs/CONTRACTS.md` is normative and is never touched by the gate.

That exemption cuts both ways, which round 1 found the hard way: the flow and
scope pass rewrote part of `docs/UX_DESIGN.md` in the present tense to describe
the shipped UI, and because a plan doc is link-checked only, none of those
current-state claims was covered by anything (MLV-R1-H08). So a sixth check
now runs over the plan docs and only them: a sentence that reports the state of
the build — “is now built”, “has been shipped”, “already implemented” — fails the
run there. Design prose is untouched (“the DOM is built with `createElementNS`”
describes a mechanism, not a milestone). What shipped belongs in `README.md` or
`docs/STATUS.md`, where checks 1–5 apply to it.

Round 2 of the feature pass added two more checks, for a rot that has nothing to do with prose. That pass rewrote `scripts/e2e.sh` — the documented POSIX twin of `scripts/e2e.ps1` — from LF to CRLF. Git Bash's `igncr` swallows the stray carriage returns, so the Windows gate stayed green while the file was broken on every platform it exists for: the shebang then names a program called `sh<CR>`, `SKIP_BUILD=0<CR>` makes `[ "$SKIP_BUILD" -eq 1 ]` an illegal-number error, and `OUT="$REPO_ROOT/.mlview"<CR>` writes every report into a directory called `.mlview<CR>` (MLV-R2-H02). So **check 7** requires LF in every `*.sh` in the tree, and forbids a checked doc from *mixing* the two conventions — the same pass flipped `docs/STATUS.md` and this file wholesale, which turned two one-line edits into 400-line rewrites and let a stale figure ride through review unread. **Check 8** is that figure: `docs/STATUS.md` said the demo graph had 39 edges while this file said 45 (MLV-R2-H05). One run produces one graph, so every `N nodes / M edges` claim about `samples/vision_pipeline` — or the `.mlview/graph.json` it emits — must agree with every other one in the doc set. Neither check can be satisfied by editing the sentence that trips it, which is the point.

Sprint 3 added three more, in `scripts/doc_numbers.py`, for a rot the first eight cannot see: a number that is
*written correctly* and is *no longer true*. **Check 9** compares `docs/ACCURACY.md`'s headline — precision, the
three recall readings, and graph fidelity — with `analyzer/tests/accuracy/baseline.json`, the ratchet the
accuracy gate actually enforces. The two had already split apart: the ANA-1 re-baseline re-recorded graph
fidelity 0.6619 → 0.8633 and left the document publishing *"92 of 139 hand-labelled ops, 66.2%"*, explained by a
class-method blind spot the same branch had repaired (TB-08). Nothing caught it because `docs/ACCURACY.md` was
in neither glob and so was checked by nothing at all, not even for dead links; it is a current-state doc now.
**Check 10** is the mirror image in CI: `actions/upload-artifact` skips dot-paths unless
`include-hidden-files: true` is set, so both e2e jobs uploaded `.mlview/*.html`, matched nothing, warned rather
than failed, and four consecutive green runs archived zero artifacts while `README.md` said otherwise
(CI-ARTIFACTS-01). **Check 11** counts the rows each e2e driver can print, requires the PowerShell and the
POSIX flavour to print the *same* table, and holds every "N steps" claim on a line naming `e2e` to that count —
because the reason ANA-12's accuracy row was left out of both drivers was that four documents quoted "17 steps"
(ANA12-E2E-05). All three are stdlib-only and read files the gate already opens.

```sh
python scripts/check_docs.py              # the repo
python scripts/check_docs.py --root DIR   # any tree
python scripts/test_check_docs.py         # the gate's own tests, all 39
```

## Environment

Both scripts export `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` before running
anything. The Windows console is cp1252, and without those a single non-ASCII
identifier or path corrupts the JSON on stdout.

They also export `PYTHONDONTWRITEBYTECODE=1`. The plugin suite imports the
vendored analyzer in-process, and the `__pycache__` trees CPython would leave
under `claude-plugin/vendor/` are bytecode that would ship with the plugin —
which the vendor gate, running right after, used to report as drift (HEALTH-01).

Set `PYTHON=/path/to/python` to choose an interpreter for the `.sh` scripts;
otherwise `pythonpick.sh` finds one. `MLVIEW_PERF_BUDGET_MS` overrides the
viewer's layout budget, which otherwise scales itself against a calibration
workload run in the same process and doubles under `CI`.

Everything runs offline. `npm install` resolves entirely from the local npm
cache, `pip install -e analyzer` has no dependencies, and neither `torch` nor
`scikit-learn` is installed — the analysis is purely static and must never
require them.

## Related tooling

| Tool | Purpose |
|---|---|
| `tools/sync-assets.py [--check]` | The only writer of `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`. |
| `tools/sync-core.py [--check]` | The only writer of `claude-plugin/vendor/` **and `vscode-extension/core/`** — the two vendored analyzers that let the plugin and the VSIX run with no pip install. |
| `tools/wheel_check.py [--no-build]` | PACKAGING's acceptance: build `analyzer/dist/*.whl`, install it into a throwaway venv, run `mlview --version --json` through the console script, then one real analysis. Exits 0 with a message when there is no wheel to test, non-zero when there is a broken one. |
| `tools/action/action.yml` | CI-ADOPT's composite GitHub Action: install MLView, `analyze --changed-since <base> --changed-only --sarif`, and a `sarif` output for `github/codeql-action/upload-sarif`. |
| `vscode-extension/tools/make_icon.py [--check]` | Renders `media/icon.png` (128x128) from arithmetic, so the marketplace icon is source rather than a binary nobody can regenerate. |
| `tools/verify.py [--parity\|--scopes\|--hashes\|--versions\|--vsix\|--all]` | The parity gates: one analyzer, one projection, one renderer, one version — ten rows, including `plugin: rule docs`, `vendor: synced core`, `vsix: synced core` and the two scope rows. |
| `tools/accuracy.py` / `tools/accuracy_corpus.py` | ANA-12's referee: scores the labelled corpus under `analyzer/tests/accuracy/corpus/` for precision, recall, graph fidelity and calibration, and gates on `baseline.json`. `docs/ACCURACY.md` says what the numbers mean. |
| `tools/perf_equiv.py [--baseline DIR\|--record FILE\|--compare FILE]` | PERF-01/02's referee: proves an analyzer optimisation moved no byte, over three corpora, each tree in its own subprocess. |
| `tools/gate_scopes.py` | Gate 5's implementation, called by `tools/verify.py --scopes`: the fixture drift check plus the viewer's parity test. |
| `analyzer/tools/gen_scope_fixtures.py [--check]` | Regenerates `contracts/scope.cases.json` and `contracts/scope.expected.json` from the Python `project()`. |
| `analyzer/tools/scope_gen.py` | HEALTH-02's generator: seeded, schema-valid documents (5-500 nodes, hierarchies, ghosts, colliding names, edge-anchored issues), every one validated by `contracts/validate_sample.py` before it is projected. |
| `analyzer/tools/scope_fuzz.py [--cases N] [--seed N] [--promote]` | HEALTH-02's differential fuzzer over the two `project()` ports. `--promote` minimizes a counterexample by delta debugging and appends it to `contracts/scope.cases.json`'s `fuzzCases`. It found the §11.30 divergence on its first 200 cases. |
| `analyzer/tools/gen_rule_docs.py [--check]` | Regenerates `docs/rules/*.md` from the rule registry. |
| `analyzer/tools/gen_expected_issues.py [--check]` | Regenerates `samples/vision_pipeline/expected_issues.json`. |
| `webview/test/render_report.mjs` | Renders a standalone report in jsdom and checks what it drew. |
| `contracts/validate_sample.py <graph.json>` | Schema + all ten invariant groups on any emitted document. |
