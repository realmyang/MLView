# MLView

[![CI](https://github.com/realmyang/MLView/actions/workflows/ci.yml/badge.svg)](https://github.com/realmyang/MLView/actions/workflows/ci.yml)

**Turn a Python machine-learning codebase into one interactive, issue-annotated
workflow diagram — and serve that identical diagram to three hosts: a
self-contained HTML report, VS Code / GitHub Copilot, and Claude Code.**

Everything is static. MLView parses source with `ast`; it never imports,
executes or `exec`s the code it reads, and **torch and scikit-learn do not need
to be installed** — the machine this was built on has neither. Everything works
offline: no network at analysis, render or load time.

It answers, in the first ninety seconds of reading unfamiliar training code, the
four questions an ML reviewer actually asks: where does data enter and where is
it split, what is being optimized and by what, is the evaluation honest, and
what is wrong — how badly and on which line.

---

## What you get

- **A stage-labelled graph.** Eight canonical stages —
  `config → data → preprocess → model → objective → train → eval → deliver` —
  as swimlane bands, a three-level hierarchy (stage › unit › op), four typed
  edge kinds (`data`, `call`, `control`, `config`), and the training loop drawn
  *as a loop*. A stage that is **absent** is declared, not dropped.
- **Findings on the diagram, not in a list beside it.** 36 rules (`MLV1xx`
  leakage, `MLV2xx` train loop, `MLV3xx` evaluation, `MLV4xx` loss, `MLV5xx`
  device, `MLV6xx` reproducibility, `MLV7xx` framework, `MLV8xx` model) attach a
  severity marker to the exact node or edge. A required-but-missing step — no
  `optimizer.zero_grad()`, no `model.eval()` — is drawn as a dashed **ghost
  node** in the slot where it belongs. Every finding carries a rule code, a
  confidence bucket, a message citing real variable names, and a one-line fix.
- **Click-to-code everywhere.** Every node, edge and issue carries
  `{file, absFile, line, col, endLine, endCol, symbol, snippet}`. Clicking an
  **edge** lands on the call site that created the dependency, not on either
  endpoint.
- **Flow you watch rather than infer.** Hover a connection and a charge runs
  along it outlet → inlet; hover a node and its lineage streams, 90 ms per hop.
  Under `prefers-reduced-motion`, or above 120 lit edges, the same information
  is a static chevron plus outlet and inlet dots.
- **One selector narrows every surface.** `unit:SmallCNN`, `stage:train`,
  `file:data.py`, `concern:evaluation`, `pipeline:train.py`, `node:<id>`, with
  `depth` 0–2 boundary hops. It is a **view, not a filter**: the Problems panel
  and the project totals still describe the whole analysis.
- **An honest report.** When MLView could not read something it says so —
  unresolved calls, a single-file analysis, an untagged training loop — and no
  emitter is allowed to claim a stage is absent without that qualification.

---

## Ninety seconds

```sh
git clone https://github.com/realmyang/MLView && cd MLView
python3 -m venv .venv && . .venv/bin/activate      # Windows: py -3 -m venv .venv
python -m pip install -e analyzer
sh scripts/build.sh                                 # Windows: scripts/build.ps1

python -m mlview analyze samples/vision_pipeline --format summary
python -m mlview analyze samples/vision_pipeline --html report.html --open
```

`samples/vision_pipeline` is a small PyTorch + scikit-learn project written to
be read, never run: 59 nodes, 51 edges and exactly 15 findings (5 high, 6
medium, 4 low). `samples/vision_pipeline_clean` is its corrected twin and
reports none. The report is one self-contained HTML file with zero external
references.

Requirements: **Python 3.10+** (3.11+ to read a `.mlview.toml`, which needs
`tomllib`) and **Node 20+** to build the viewer.

---

## Install it in your host

### Command line

```sh
python -m pip install -e analyzer      # or: pip install mlview, once published
python -m mlview analyze . --json .mlview/graph.json --html .mlview/report.html
```

### VS Code / GitHub Copilot

```sh
cd vscode-extension && npm install && npm run compile
code vscode-extension                  # then press F5
```

F5 launches an Extension Development Host; `npm run package` builds a VSIX you
can install instead. **No `pip install` is required** — the VSIX bundles the
analyzer (`tools/sync-core.py` vendors it at build time), and an `mlview` already
installed in your interpreter wins only when its schema major matches and it is
not older.

Then: `MLView: Visualize ML Workflow (Workspace)`, findings in the **Problems**
panel, `Alt+M` to reveal the symbol under the cursor in the diagram,
`Alt+Shift+M` to scope the diagram to it, `@mlview` in Copilot Chat and
`#mlviewAnalyze` in agent mode. Full command, setting and troubleshooting
reference: [`vscode-extension/README.md`](vscode-extension/README.md).

### Claude Code

```sh
claude plugin validate ./claude-plugin --strict
claude --plugin-dir /absolute/path/to/MLView/claude-plugin
```

Then, in the session:

```
/mlview samples/vision_pipeline                       # analyze, summarize, open the diagram
/mlview-issues samples/vision_pipeline high
/mlview samples/vision_pipeline --scope concern:evaluation --depth 1
```

Five MCP tools (`mlview_analyze`, `mlview_issues`, `mlview_graph`,
`mlview_open_diagram`, `mlview_explain`), each answer ≤ 4 KB, and a
`PostToolUse` hook that speaks only when your edit *added* a finding. The plugin
needs no `pip install`: `.mcp.json` puts `claude-plugin/vendor` on `PYTHONPATH`.
Full reference: [`claude-plugin/README.md`](claude-plugin/README.md).

---

## The CLI

```sh
python -m mlview analyze <path> [--json FILE|-] [--html FILE] [--open] [--format summary|text|json|mermaid]
python -m mlview issues  <path> [--min-severity low|medium|high] [--fail-on ...]
python -m mlview explain MLV201                  # the rule page, offline
python -m mlview rules --list                    # all 36 codes
python -m mlview init                            # a commented .mlview.toml
python -m mlview diff BASE.json HEAD.json        # what a change added, removed, fixed
python -m mlview analyze --demo --json -         # the golden sample document
```

| Flag | What it does |
|---|---|
| `--scope SPEC` / `--depth N` | Narrow every surface to one part of the pipeline; `--list-scopes` prints the catalogue of scopable units |
| `--config FILE` | Configuration: this file, else `<root>/.mlview.toml`, else `[tool.mlview]` in `pyproject.toml`. **First match wins outright**, never merged, and the winner is named in the document's `configPath` |
| `--dataflow {local,ip}` | Follow values across the object boundary. **`ip` is the default**; `local` is the narrower opt-out. Every hop multiplies confidence by an explicit weight, so a cross-object finding is never reported as `certain` |
| `--relevance {ml,all}` / `--relevance-hops N` | The prefilter that keeps only the modules within N import hops of ML code. `--no-cache` turns off the per-file fact cache |
| `--max-nodes N` | A node budget that **folds** rather than deletes: ops into their unit, then files, then directories, each fold carrying a `rolledUp` count |
| `--include-notebooks` | Analyze `.ipynb` too. Each notebook becomes one generated module under `.mlview/notebooks/`; a non-monotonic `execution_count` de-rates the rules that depend on cell order and says so |
| `--changed-since REV` / `--changed-only` / `--baseline FILE` / `--sarif FILE` | Adoption on a repo that already has findings — see below |

Exit codes: `0` ok · `1` usage or I/O · `2` `--fail-on` threshold exceeded ·
`3` internal error · `4` nothing analyzable. stdout carries **only** the
requested payload; every log line goes to stderr.

**In the report or the panel:** hover a connection to watch the value travel
along it; `e` / `Shift+E` walk the selected node's connections; `s` scopes to
the selection, `[` / `]` change the depth, `Shift+S` or `Esc` leaves.

### Adopt on a repo that already has findings

A realistic 50-file project starts at ~111 findings, so `--fail-on high` exits
`2` forever. MLView still analyses the **whole** project — narrowing the
analysis to the changed files is exactly the fidelity loss that makes one file
report 3 findings where its directory reports 7 — and then attributes:

```sh
python -m mlview issues . --changed-since origin/main --changed-only   # what THIS change introduced
python -m mlview baseline write --out .mlview/baseline.json            # freeze today
python -m mlview analyze . --baseline .mlview/baseline.json --fail-on high
python -m mlview analyze . --sarif mlview.sarif                        # for code scanning
```

Every failure path degrades to *"unattributed, showing everything"* with a
diagnostic — never to an error and never to an empty list, because a gate that
goes green because git was absent is the one failure a CI gate must not have.
`tools/action/action.yml` is a composite GitHub Action (check out with
`fetch-depth: 0`) and `.pre-commit-hooks.yaml` exposes `mlview` and
`mlview-changed`.

---

## How it is put together

```
analyzer/          the Python package `mlview` — the ONE analyzer
webview/           the ONE renderer; dist/mlview.{js,css} is the bundle
vscode-extension/  panel · diagnostics · reveal · chat · LM tools
claude-plugin/     plugin.json · .mcp.json · commands · skills · MCP server · hooks
contracts/         FROZEN: graph.schema.json · graph.sample.json · scope fixtures
samples/           vision_pipeline (dirty) + vision_pipeline_clean (twin)
tools/ scripts/    sync, parity, accuracy and packaging gates; the two drivers
docs/              the spec, the status page, the rule pages, the runbooks
```

**Three frozen seams**, and nothing crosses them informally: the process seam
(`python -m mlview analyze <path> --json -` — both hosts call exactly this, and
nothing else parses Python), the in-process seam (`mlview.api`, which the MCP
server imports rather than shelling out to itself), and the render seam
(`window.MLView.mount(el, graph, bridge)`, whose only host-specific code is a
seven-method `HostBridge`). `python tools/verify.py --all` byte-diffs the two
analyzer paths, hashes the viewer bundle across all three copies of it, and
checks that one version string is spelled the same in five places.

## Tests

```sh
python -m pytest analyzer/tests -q        # analyzer core + rules
python -m pytest claude-plugin/tests -q   # MCP handshake, budgets, manifests
cd webview && npm test                    # layout, bundle hygiene, parity, contrast
cd vscode-extension && npm test           # protocol, ranges, CSP, digests, mapping
```

Everything at once, as one PASS/FAIL table — build, every suite, the samples,
the scoped reports, the parity, scope, accuracy and doc gates:

```sh
sh scripts/e2e.sh                                              # 20 steps
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1       # the same 20
```

`.github/workflows/ci.yml` runs that table in two tiers, because the repository
is private and minutes are metered. **Every push** runs the analyzer on Python
3.10 and 3.13, the viewer on Node 20, both host suites, the accuracy corpus and
the Linux e2e table — seven jobs, ~19 billable minutes. **Every pull request and
every push to `main`** adds Python 3.11 and 3.12, Node 22, the Windows e2e table,
a macOS smoke job and packaging, so nothing reaches `main` that has not been
checked on every supported interpreter, both e2e drivers and all three platforms.
A push that touches only Markdown and `docs/` runs nothing at all.
[`scripts/README.md`](scripts/README.md) is the gate-by-gate table with the
command for each row and what a green row proves, and row 25 of it breaks the
last full green push (run 34454599867) down job by job.

## What is verified, and what is not

Every gate above is green on the build machine. **The CI matrix has not run.**
GitHub has refused to start a job on this branch since its Actions billing was
blocked, so nothing in this tree has been executed on Python 3.10, 3.11 or 3.12,
on Windows or on macOS — the build machine has only 3.13 — and the full-tier jobs
(`analyzer-extra`, `webview-extra`, `e2e-windows`, `smoke-macos`, `packaging`)
have never run at all. `CHANGELOG.md` records it push by push, and
`scripts/README.md` row 25 names the last run that did execute. What the matrix
would not cover either: the VS Code Extension Development Host has never been driven
under automation, and GitHub Copilot is not installed on the build machine, so
`@mlview` and the three language-model tools are type-checked and unit-tested
against a mocked `vscode` and have never met a live Copilot session. The
exercised Copilot surface is the Problems panel.
[`docs/VALIDATION.md`](docs/VALIDATION.md) is the runbook for closing that by
hand on a second machine.

### Known gaps

The full list, each bullet naming the code it is about, is in
[`docs/STATUS.md`](docs/STATUS.md). The four worth knowing before you trust an
answer:

- **The framework gate reaches one import hop.** `ctx.wrappers_for()` in
  `analyzer/src/mlview/rules/context.py` de-rates an absence finding
  (`MLV301`, `MLV302`, `MLV501`, ...) only when a Lightning / HF Trainer /
  accelerate / ignite / fastai / DDP / FSDP wrapper sits in the finding's own
  module or in a workspace module it imports, so a wrapper two hops away gates
  nothing. When it fires it caps severity at `medium` and multiplies confidence
  by 0.4; it never deletes a finding.
- **Cross-file call following is one level.** `analyzer/src/mlview/ir/resolve.py`
  fills `target_function` for a call into a workspace module and stops, so a rule
  cannot chase a helper that a helper calls.
- **Loop nesting is flattened.** A batch loop inside an epoch loop is parented to
  the enclosing function unit; the true depth survives in `LoopIR.depth` in
  `analyzer/src/mlview/ir/model.py` but cannot be drawn.
- **Recall is the weakness, and it is measured rather than claimed.** On unseen
  labelled programs roughly two in five planted defects still produce nothing;
  `analyzer/tests/accuracy/baseline.json` is the ratchet and `docs/ACCURACY.md`
  names the gap per rule.

## Where the docs are

| Document | What it is for |
|---|---|
| [`docs/STATUS.md`](docs/STATUS.md) | What is in the tree today, what is verified, what the known gaps are |
| [`CHANGELOG.md`](CHANGELOG.md) | The dated history, newest first, with the figures measured at the time |
| [`docs/CONTRACTS.md`](docs/CONTRACTS.md) | **Normative.** The schema, the CLI, the MCP tools, the message protocol |
| [`docs/ACCURACY.md`](docs/ACCURACY.md) | The labelled corpus: precision, recall, graph fidelity, and what is still missed |
| [`docs/VALIDATION.md`](docs/VALIDATION.md) | The runbook for validating MLView by hand on another machine, and for publishing it |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | The ranked backlog, and the measurement note each shipped item landed with |
| [`docs/rules/`](docs/rules/README.md) | One offline page per rule: what it looks for, its traps, and what it cannot analyze |

`docs/REQUIREMENTS.md`, `docs/ARCHITECTURE.md`, `docs/ISSUE_RULES.md` and
`docs/UX_DESIGN.md` are **plan records**: they say what was decided, not what was
built, and the doc gate link-checks them and nothing else so that editing one to
match the code cannot quietly erase a decision.

License: [MIT](LICENSE) — Copyright (c) 2026 realmyang.
