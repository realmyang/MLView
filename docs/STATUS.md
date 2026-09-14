# MLView — current state

What is in the tree today, what is verified, and how to run all of it on
Windows, macOS and Linux. The dated history — every sprint at the figures it
measured — is [`CHANGELOG.md`](../CHANGELOG.md); the normative spec is
[`docs/CONTRACTS.md`](CONTRACTS.md); the gate-by-gate table with the command for
each row is [`scripts/README.md`](../scripts/README.md).

MLView reads a Python ML/DL codebase **statically** — `ast` only, never an
import, never an `exec`, no network — and emits one document: a stage-labelled
workflow graph with findings attached to the nodes and edges that carry them.
Three hosts render that same document through the same viewer bundle: a
self-contained HTML report, a VS Code webview, and the Claude Code plugin.

---

## Components

| Piece | State |
|---|---|
| Analyzer `analyzer/` | **36 rules**, zero runtime dependencies, installed editable as `python -m mlview`. **2109 passed / 4 skipped** (the skips are the `tomllib` split, in both directions). `analyze --demo --json -` is byte-identical to `contracts/graph.sample.json`. |
| Viewer `webview/` | One renderer, built to `webview/dist/mlview.js` + `mlview.css`. **536 tests**, `tsc --noEmit` clean. Scope projection (`webview/src/scope/project.ts`), flow animation, SVG/PNG export and the diff overlay all live here. |
| VS Code extension | **381 tests**, `tsc --noEmit` clean, `out/extension.js` bundled, 19 commands and 16 settings. Ships the analyzer inside the VSIX — `core/mlview` at **113** files, the number `python tools/verify.py --all`'s `vsix: synced core` row prints — so no `pip install` is required. **That figure is not the gate**: it moves with every analyzer module, and `python scripts/vsix_check.py` re-derives it, the 1 MB ceiling and the rule-page count from the tree. Copilot participant and LM tools are compile- and unit-verified only. |
| Claude Code plugin | MCP server on the `mcp` SDK v2, **exactly five tools**, each result ≤ 4 KB, plus `PostToolUse` / `Stop` hooks under `claude-plugin/hooks/`. **373 passed / 7 skipped**. |
| Contracts | `contracts/graph.schema.json`, `contracts/graph.sample.json` (the frozen golden), `contracts/validate_sample.py` (schema + 10 invariant groups), `contracts/scope.cases.json` (13 projecting cases + 7 error cases + 5 promoted counterexamples). |
| Samples | `samples/vision_pipeline` — 54 nodes, 51 edges, exactly 15 issues (5 high / 6 medium / 4 low) — and `samples/vision_pipeline_clean`, 0 issues. `expected_issues.json` is machine-checked. |
| Rule docs | `docs/rules/` — 36 pages plus an index, generated from the registry. Every `Issue.docs` deep link resolves. |
| Accuracy corpus | `analyzer/tests/accuracy/corpus/` with `analyzer/tests/accuracy/baseline.json` as the ratchet; `docs/ACCURACY.md` is the record. |

**Gates**, on this Mac (macOS 26.6, Python 3.13, Node 26): analyzer **2109
passed / 4 skipped**; webview **536 tests**; vscode-extension **381 tests**;
claude-plugin **373 passed / 7 skipped**; `python -m pytest scripts -q` **74
passed**; `npx tsc --noEmit` clean in both TypeScript packages;
`python tools/accuracy.py` **PASS**; `python scripts/check_docs.py` **DOC CHECK
OK**; `sh scripts/e2e.sh` **20 steps, 0 failed, 0 skipped**;
`python tools/verify.py --all` **10 of 10**; `python tools/verify.py --scopes
--fuzz 200` **5 of 5**; `python contracts/validate_sample.py` green at four node
budgets. Re-run the table before a release: `scripts/e2e` prints every row with
its command, and `scripts/README.md` says what each green row proves.

## Accuracy headline

`python tools/accuracy.py` scores the labelled corpus and gates on it: recall
and graph fidelity may only ratchet up, and a `forbidden` finding fails the run
outright whatever the baseline says.

| Reading | Value |
|---|---|
| Precision | **100%** — zero false positives, zero forbidden findings |
| Recall, whole corpus | **73.1%** raw · 65.4% visible · 64.9% high+medium |
| Recall, unseen programs only | **55.3%** raw · 42.5% visible · 37.5% high+medium |
| Graph fidelity | **91.4%** — 127 of 139 hand-labelled ops |
| With `--dataflow ip` | recall **79.5%**, unseen **66.0%**, precision still 100% |

`docs/ACCURACY.md` is the full record — what a label is, which programs are
*tuned* (the rules were written against them, so their numbers are a ceiling),
and the remaining recall gap per rule. Recall is this product's weakness: on
unseen code, roughly two in five planted defects still produce nothing.

## Running it

The same four steps on every platform. Use a virtual environment; never the
system Python.

```sh
# macOS / Linux
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e analyzer
sh scripts/build.sh        # 6 steps: viewer bundle, sync, compile, package, wheel
sh scripts/e2e.sh          # the whole gate table, 20 steps, PASS/FAIL per row
```

```powershell
# Windows (PowerShell 5.1 or newer)
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -e analyzer
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
```

Requirements: **Python 3.10+** (3.11+ to read `.mlview.toml`, which needs
`tomllib`) and **Node 20+**. Set `PYTHONUTF8=1` on Windows. The two drivers run
the same table and print the same rows; `scripts/pythonpick.sh` is how the POSIX
driver finds a 3.10+ interpreter.

Individual suites and gates:

```sh
python -m pytest analyzer/tests -q        # analyzer core + rules
python -m pytest claude-plugin/tests -q   # MCP handshake, budgets, manifests
python -m pytest scripts -q               # the doc and packaging gates
cd webview && npm test                    # layout, bundle hygiene, parity, contrast
cd vscode-extension && npm test           # protocol, ranges, CSP, digests, mapping
python tools/verify.py --all              # the parity gates
python tools/accuracy.py                  # the labelled corpus and its ratchet
```

---

## What is verified, and what is not

**Exercised end to end** on this machine and, on every push, across the CI
matrix — `.github/workflows/ci.yml` runs a fast tier on a push and the full
matrix (ubuntu, Windows and macOS, Python 3.10–3.13, two Node versions) on every
pull request and every push to `main`: the analyzer and its rules; the CLI including `--demo` byte parity and every documented exit code;
a real stdio MCP handshake with `PYTHONPATH` pointing only at
`claude-plugin/vendor`, which also proves the no-`pip install` path; the
self-contained HTML report and the scoped demo reports; and all four parity
gates.

**Compile-verified only**: the VS Code Extension Development Host (F5) has never
been driven under automation, and GitHub Copilot is not installed on the build
machine, so `@mlview` and the three language-model tools are type-checked and
unit-tested against a mocked `vscode` but have never met a live Copilot session.
The exercised Copilot surface is the `DiagnosticCollection` — what a Copilot
agent reads today is the Problems panel, and that path is tested.
`docs/VALIDATION.md` is the runbook for closing that gap by hand on a second
machine.

## Known gaps

None blocks the demo. Roughly in the order they matter:

- **No live host run.** The extension has never been driven inside a real VS
  Code webview and the chat surfaces have never met a live Copilot session; both
  are covered by unit tests against `vscode-extension/test/mock-vscode.js` plus a
  real subprocess test against a fake CLI.
- **Loop nesting is flattened.** Invariant §1.1.2 plus a three-value `NodeLevel`
  cannot express function → epoch loop → batch loop → op, so an inner loop is a
  sibling of its epoch loop. The true depth survives in `LoopIR.depth` and
  `LoopIR.parent_loop` in `analyzer/src/mlview/ir/model.py`; it cannot be drawn.
- **Cross-file call following is one level.** `analyzer/src/mlview/ir/resolve.py`
  fills `target_function` for a call into a workspace module and stops, so a rule
  cannot chase a helper that a helper calls. `from config import N` resolves;
  `import config` then `config.N` does not.
- **The framework gate reaches one import hop.** `ctx.wrappers_for()` in
  `analyzer/src/mlview/rules/context.py` de-rates an absence finding only when a
  Lightning / HF Trainer / accelerate / ignite / fastai / DDP / FSDP wrapper sits
  in the finding's own module or in a workspace module it imports —
  `_detect_wrappers()` in `analyzer/src/mlview/ir/build_ir.py` walks exactly one
  hop. When it fires it caps severity at `medium` and multiplies confidence by
  0.4; it never drops a finding.
- **`MLV201`'s `negation_absent` evidence line reads the workspace-wide set.**
  `analyzer/src/mlview/rules/r_trainloop.py` composes that sentence from
  `ctx.wrappers` rather than from the per-module set the gate uses, so an ungated
  hand-written loop can carry "framework wrapper detected: Lightning" beside a
  `certain` finding. Severity and confidence are right; the sentence contradicts
  them.
- **The interprocedural hop cap is a guess.** `DEFAULT_MAX_HOPS` in
  `analyzer/src/mlview/ir/provenance.py` is deep enough for caller → ctor →
  attribute → sibling method and shallow enough that two hops stay above
  `speculative`, and nothing measured that choice. A chain past it is not
  propagated and **is** reported as a `truncated` diagnostic.
- **A fold is lossy about *which* thing.** After
  `analyzer/src/mlview/core/rollup.py` folds a file or a directory the diagram
  shows one card carrying `rolledUp` and nothing says what was inside it; the summary's `kind` and `stage` are a majority vote
  and nothing records that the vote was close. Every finding survives with a real
  `loc`, so this is legibility, not correctness.
- **A `pipeline:` view draws the other entrypoints, greyed.**
  `analyzer/src/mlview/core/pipelines.py` pulls in up to one file per neighbour as
  context, `workspace.entrypoints` is a heuristic capped at 10, and nodes in no
  pipeline are counted but never named.
- **A structured fix lands at coordinates nobody can prove are current.**
  `vscode-extension/src/fixes.ts` refuses an unsaved buffer and a file shorter
  than the analysis saw, and VS Code shows the refactor preview — but a file
  edited, saved and left the same length passes both checks.
- **The multi-root diagram shows one folder at a time.** `folderTooltipLine` in
  `vscode-extension/src/folders.ts` names the folder the count describes and how
  many it does not; the Problems panel is the only surface showing the union.
- **The per-finding notebook cell mapping is a string, not a field.**
  `analyzer/src/mlview/rules/confidence.py` writes it as one evidence detail
  because `Loc` is frozen, and `vscode-extension/src/notebooks.ts` regex-matches
  that sentence to place a squiggle. A test pins the format on both sides.
- **The Claude Code hooks do nothing on Windows without Git Bash.** The command
  in `claude-plugin/hooks/hooks.json` is shell form, which is PowerShell there,
  and `${MLVIEW_PYTHON:-python}` does not expand. The hook fails to start, which
  is non-blocking, so the degradation is silence rather than a broken session.
- **`--list-scopes` lists units only.**
  `analyzer/src/mlview/emit/scope_out.py` prints the scopable-unit catalogue; the
  four concerns and the eight stage ids are discovered from this document, from
  the MCP tool description, or from the candidates an unusable selector prints.

## Open contract change requests

Filed by the agents that hit them, recorded here because `docs/CONTRACTS.md` is
normative and none has been acted on:

1. **§1.1.2** (`parent` must have a lower `NodeLevel`) is unsatisfiable together
   with the three-value level enum and real ML nesting — add a `group` level, or
   relax it to "never cyclic, parent level <= child level".
2. **§0 ordering leaves ties undefined.** A ghost node shares its parent loop's
   `(stage, file, line, col)`, so two nodes can sort equal; byte-determinism
   wants a stated tie-break.
3. **Serialization is unspecified**, yet `--demo` must equal
   `contracts/graph.sample.json` byte for byte: UTF-8 without BOM, LF,
   `json.dump(..., indent=2, ensure_ascii=False)`, trailing newline.
4. **The per-finding notebook cell mapping should be two optional `Issue`
   fields, not a sentence** — the same pair `Node.attrs` already carries. It
   would delete the regex parse in `vscode-extension/src/notebooks.ts`.
