# scripts/

Two drivers, each in a PowerShell and a POSIX-sh flavour, plus one Python gate
they both call. The two flavours do the same thing; pick whichever shell you are
in. Both are Windows-safe: no `shell: true`, no
symlinks, no `chmod`, and the PowerShell versions are Windows PowerShell 5.1
compatible (no `&&`, no `||`, no ternaries — every step checks `$LASTEXITCODE`).

| Script | What it does |
|---|---|
| `build.ps1` / `build.sh` | Build everything, in the only order that works. |
| `e2e.ps1` / `e2e.sh` | Build, run every suite, analyze the samples, write the scoped demo reports, render them, run the parity, scope and doc gates, print a PASS/FAIL table. |
| `check_docs.py` | The doc gate: dead paths, dead Markdown links, "known gap" bullets that still describe a failure somebody already fixed, gap bullets that cite nothing checkable or cite a symbol that has been renamed away, a frozen design record that has started reporting build state, a POSIX shell script written with CRLF, and two docs that disagree about the size of the demo graph. |
| `test_check_docs.py` | The doc gate's own test suite — twenty-six cases: twenty-two throwaway trees, one unit test for the symbol parser, three that read the real repo. |

---

## The gate table

Every gate below is green on this machine (Windows 11, Python 3.13 / miniconda,
Node 20.9, VS Code 1.136, Claude Code CLI 2.1.186). `scripts/e2e` runs all of
them in one pass; the middle column is how to run just that one.

| # | Gate | Command | Result |
|---|---|---|---|
| 1 | Build | `powershell -ExecutionPolicy Bypass -File scripts/build.ps1` | `BUILD OK` — 5/5 steps |
| 2 | Analyzer + rules | `python -m pytest analyzer/tests -q` | 1075 passed, 2 skipped |
| 3 | Viewer tests | `npm test` in `webview` | 246 pass, 0 fail |
| 4 | Viewer typecheck | `npm run check` in `webview` | `tsc --noEmit`, clean |
| 5 | Extension typecheck | `npm run check` in `vscode-extension` | `tsc --noEmit`, clean |
| 6 | Extension bundle | `npm run compile` in `vscode-extension` | `out/extension.js` 111.4 kb |
| 7 | Extension tests | `npm test` in `vscode-extension` | 180 pass, 0 fail |
| 8 | Plugin / MCP tests | `python -m pytest claude-plugin/tests -q` | 231 passed |
| 9 | Parity gates | `python tools/verify.py --all` | all 9 gates passed |
| 9a | Scope parity (Python == TypeScript) | `python tools/verify.py --scopes` | 10 projections + 6 error cases, python == typescript |
| 9b | Scope fixtures current | `python analyzer/tools/gen_scope_fixtures.py --check` | 10 projecting + 6 error cases over the golden |
| 10 | Plugin manifest | `claude plugin validate ./claude-plugin --strict` | Validation passed |
| 11 | Marketplace manifest | `claude plugin validate ./.claude-plugin/marketplace.json --strict` | Validation passed |
| 12 | Report renders | `node test/render_report.mjs` in `webview` | 15/15 assertions |
| 12b | Clean report renders | `node test/render_report.mjs ../.mlview/report_clean.html --min-ghosts=0` | 15/15 assertions |
| 12c | Scoped report renders | `node test/render_report.mjs ../.mlview/evaluation.html --scope=concern:evaluation` | 18/18 assertions — no empty band, badge-free boundary stubs, the breadcrumb still names the project total |
| 13 | Panel + media bundle | `node --test test/panelhtml.test.js` in `vscode-extension` | 4 pass |
| 13b | Cross-host scope handshake | `node test/crosshost.mjs ../.mlview/graph.json` in `webview` | 28/28 assertions — the real viewer bundle answers the real extension's `setScope`, and `parseUiToHost` / `scopeChrome` accept what it posts |
| 14 | Rule docs current | `python analyzer/tools/gen_rule_docs.py --check` | 21 pages current |
| 15 | Sample issues current | `python analyzer/tools/gen_expected_issues.py --check` | 15 issues — 5/6/4 |
| 16 | Golden parity | `python -m mlview analyze --demo --json -` vs `contracts/graph.sample.json` | byte-identical, 46 078 bytes |
| 17 | Emitted docs valid | `python contracts/validate_sample.py .mlview/graph.json` | schema 1.0 + 10 invariant groups, 45 nodes / 45 edges / 15 issues |
| 18 | Docs match the tree | `python scripts/check_docs.py` | 18 files (16 docs + 2 shell scripts), no dead paths, every known gap anchored, no build state in a plan doc, LF in every shell script, one graph size |
| 19 | End to end | `powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1` | `E2E OK` — 17 steps, 0 failed |
| 20 | Scoped demo artifacts | `python -m mlview analyze samples/vision_pipeline --scope concern:evaluation --depth 1 --html .mlview/evaluation.html` | 17 of 45 nodes (7 core / 7 boundary / 3 context), `data-mlview-scope` and `data-mlview-depth` set on the root |
| 21 | Scope catalogue | `python -m mlview analyze samples/vision_pipeline --list-scopes` | 10 scopable units, biggest first |

Rows 16–18 are also asserted inside rows 2 and 19; they are listed separately
because each is a one-line command that answers a question a reviewer asks
directly ("is the golden still the golden?", "does what it just wrote validate?").

`tools/verify.py --all` is itself nine rows, in this order: one version row, the
`plugin: rule docs` row, the CLI-vs-MCP graph parity row, `vendor: synced core`,
the two scope rows (`scopes: fixtures` and `scopes: python == ts`), and three
renderer-hash rows. The scope rows sit **between** the analyzer-parity row and
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
3. `tools/sync-core.py` → copies `analyzer/src/mlview` into
   `claude-plugin/vendor/mlview`
4. `vscode-extension` — `npm install` + `npm run compile` + `npm run check`
5. `analyzer` — `pip install -e analyzer`, then `python -m mlview --version`

**The order is not arbitrary.** `generator.rendererSha` is the SHA-256 of the
`mlview.js` the analyzer ships, computed at runtime, so the viewer must be built
and synced *before* the analyzer emits anything you intend to compare. Until
step 2 runs, `rendererSha` is 64 zeros and `--html` produces a plain-table
fallback with a visible "Viewer bundle not synced" banner.

**Step 3 is the one people forget.** Nothing about the Claude Code path fails
loudly when `claude-plugin/vendor/` is stale — the MCP server simply runs an old
analyzer. `tools/verify.py --all` reports it as its own row for exactly that
reason.

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
13. `python tools/verify.py --scopes` — the Python projection and the TypeScript
    port project the same battery identically
14. `python tools/verify.py --all` — the parity gates
15. `python scripts/test_check_docs.py` — the doc gate's own self-test
16. `python scripts/check_docs.py` — the docs still match the tree
17. the PASS/FAIL table

**Every step runs even when an earlier one failed.** A run that stops at the
first failure hides the other sixteen, and the whole point of the table is to see
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

```sh
python scripts/check_docs.py              # the repo
python scripts/check_docs.py --root DIR   # any tree
python scripts/test_check_docs.py         # the gate's own tests
```

## Environment

Both scripts export `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` before running
anything. The Windows console is cp1252, and without those a single non-ASCII
identifier or path corrupts the JSON on stdout. Set `PYTHON=/path/to/python` to
choose an interpreter for the `.sh` scripts.

Everything runs offline. `npm install` resolves entirely from the local npm
cache, `pip install -e analyzer` has no dependencies, and neither `torch` nor
`scikit-learn` is installed — the analysis is purely static and must never
require them.

## Related tooling

| Tool | Purpose |
|---|---|
| `tools/sync-assets.py [--check]` | The only writer of `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`. |
| `tools/sync-core.py [--check]` | The only writer of `claude-plugin/vendor/`. |
| `tools/verify.py [--parity\|--scopes\|--hashes\|--versions\|--all]` | The parity gates: one analyzer, one projection, one renderer, one version — nine rows, including `plugin: rule docs`, `vendor: synced core` and the two scope rows. |
| `tools/gate_scopes.py` | Gate 5's implementation, called by `tools/verify.py --scopes`: the fixture drift check plus the viewer's parity test. |
| `analyzer/tools/gen_scope_fixtures.py [--check]` | Regenerates `contracts/scope.cases.json` and `contracts/scope.expected.json` from the Python `project()`. |
| `analyzer/tools/gen_rule_docs.py [--check]` | Regenerates `docs/rules/*.md` from the rule registry. |
| `analyzer/tools/gen_expected_issues.py [--check]` | Regenerates `samples/vision_pipeline/expected_issues.json`. |
| `webview/test/render_report.mjs` | Renders a standalone report in jsdom and checks what it drew. |
| `contracts/validate_sample.py <graph.json>` | Schema + all ten invariant groups on any emitted document. |
