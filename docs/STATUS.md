# MLView — current state

[![CI](https://github.com/realmyang/MLView/actions/workflows/ci.yml/badge.svg)](https://github.com/realmyang/MLView/actions/workflows/ci.yml)
[![status: preview](https://img.shields.io/badge/status-preview-orange.svg)](STATUS.md)

The badge reports the newest run on `main`. The overview a first-time reader wants —
the screenshots, the ninety-second quick start per host, the rule families and the
measured accuracy — is the root [`README.md`](../README.md); this page is the detail
behind it.

What is in the tree today, what is verified, and how to run all of it on
Windows, macOS and Linux. The dated history — every sprint and hardening round
at the figures it measured — is [`CHANGELOG.md`](../CHANGELOG.md); the normative
spec is [`docs/CONTRACTS.md`](CONTRACTS.md); the gate-by-gate table with the
command for each row is [`scripts/README.md`](../scripts/README.md).

MLView reads a Python ML/DL codebase **statically** — `ast` only, never an
import, never an `exec`, no network — and emits one document: a stage-labelled
workflow graph with findings attached to the nodes and edges that carry them.
Three hosts render that same document through the same viewer bundle: a
self-contained HTML report, a VS Code webview, and the Claude Code plugin.

---

## Components

| Piece | State |
|---|---|
| Analyzer `analyzer/` | **36 rules**, zero runtime dependencies, installed editable as `python -m mlview`. **2654 passed / 9 skipped** plus 24 `xfail`. On 3.10 / 3.11 eight more skip: two robustness fixtures are PEP 695 / PEP 701 source, and MLView parses with the host's own `ast`, so a host that cannot read them is not the thing under test. `analyze --demo --json -` is byte-identical to `contracts/graph.sample.json` at 46 078 bytes. |
| Viewer `webview/` | One renderer, built to `webview/dist/mlview.js` + `mlview.css`. **599 tests** (598 pass, 1 todo), `tsc --noEmit` clean. Scope projection (`webview/src/scope/project.ts`), flow animation, SVG/PNG export and the diff overlay all live here. |
| VS Code extension | **410 tests**, `tsc --noEmit` clean, `out/extension.js` bundled, 19 commands and 16 settings. Ships the analyzer inside the VSIX, so no `pip install` is required — `core/mlview` at **130** files, the number `python tools/verify.py --all`'s `vsix: synced core` row prints. The bundled copy under `vscode-extension/core/` is a **build artifact** written by `vscode-extension/tools/sync-core.mjs` at compile and package time, not a tracked directory, and **that figure is not the gate**: it moves with every analyzer module, and `python scripts/vsix_check.py` re-derives it, the 1 MB ceiling and the rule-page count from the tree. Copilot participant and LM tools are compile- and unit-verified only. |
| Claude Code plugin | MCP server on the `mcp` SDK v2, **exactly five tools**, each result ≤ 4 KB, plus `PostToolUse` / `Stop` hooks under `claude-plugin/hooks/`. **476 passed / 7 skipped**. `claude-plugin/vendor/mlview` is **tracked** on purpose: a marketplace install copies the plugin directory verbatim off a git ref with no build step. |
| Contracts | `contracts/graph.schema.json`, `contracts/graph.sample.json` (the frozen golden), `contracts/validate_sample.py` (schema + 10 invariant groups), `contracts/scope.cases.json` (13 projecting cases + 7 error cases + 5 promoted counterexamples). |
| Samples | `samples/vision_pipeline` — 59 nodes, 51 edges, exactly 15 issues (5 high / 6 medium / 4 low) — and `samples/vision_pipeline_clean`, 70 nodes and 0 issues. `expected_issues.json` is machine-checked. |
| Rule docs | `docs/rules/` — 36 pages plus an index, generated from the registry. Every `Issue.docs` deep link resolves. |
| Labelled corpus | `analyzer/tests/accuracy/corpus/` — **158 labelled programs**, **546** scored `expected` labels, 2327 `forbidden` labels, 1166 hand-drawn graph ops, scored by `tools/accuracy.py` against two ratchets (`baseline.json`, `baseline.ip.json`). `docs/ACCURACY.md` is the record. |
| Public corpus | `tools/public_corpus.py` + `analyzer/tests/public_corpus/` — **37 pinned third-party repositories**, 112 targets × 3 modes (`local`, `ip`, `--include-notebooks`) = **260 runs**. Nothing is vendored and nothing is labelled: the gate asserts no crash, exit 0 or 4 only, a schema-valid document, the wall-time budget, and **no new high-severity finding** a human has not adjudicated in `adjudication.json`. It is the only gate that can see a false positive nobody thought to label, and it has caught four. |

**Gates**, on this Mac (macOS 26.6, Python 3.13, Node 26): analyzer **2654
passed / 9 skipped**; webview **599 tests**; vscode-extension **410 tests**;
claude-plugin **476 passed / 7 skipped**; `python -m pytest scripts -q` **132
passed**; `npx tsc --noEmit` clean in both TypeScript packages;
`python tools/accuracy.py` **PASS** in both dataflow modes;
`python scripts/check_docs.py` **DOC CHECK OK**; `sh scripts/e2e.sh` **20
steps**; `python tools/verify.py --all` **10 of 10**; `python tools/verify.py
--scopes --fuzz 200` **5 of 5** (13 projections + 7 error cases, 5 promoted
counterexamples, and 200 fuzz cases over 40 generated graphs — the graph sizes,
the rolled-up count and the pipeline count move with the seed, which the run
prints and `MLVIEW_FUZZ_SEED` replays); `python contracts/validate_sample.py`
green at four node budgets; `python tools/public_corpus.py run` then
`check --strict` **gate OK** over the 37 pinned repositories. Re-run the table
before a release: `scripts/e2e` prints every row with its command, and
`scripts/README.md` says what each green row proves.

**Every gate in that paragraph was run locally, on this macOS machine, at the
consolidation-and-recall integration on 2026-09-15, and run again in full after
the campaign review's fixes the same day — and nowhere else.** GitHub
Actions is blocked at the **account** level (*"The job was not started because
recent account payments have failed or your spending limit needs to be
increased"*), so no CI job has started on this line of work and **no claim of a
green CI run is made anywhere in this repository**. Python 3.10 / 3.11 / 3.12,
Windows and macOS-on-a-runner are therefore unverified; see *What is verified,
and what is not* below.

## Accuracy headline

`python tools/accuracy.py` scores the labelled corpus and gates on it: recall
and graph fidelity may only ratchet up, and a `forbidden` finding fails the run
outright whatever the baseline says.

| Reading | `--dataflow ip` | `--dataflow local` |
|---|---|---|
| Precision | **100.0%** — zero false positives, zero forbidden, zero unlabelled | **100.0%**, the same three zeroes |
| Recall, whole corpus (546 labels) | **80.4%** raw · 72.5% visible · 74.3% high+medium | **78.2%** · 70.7% · 71.2% |
| Recall, unseen only (515 labels) | **79.2%** raw · 70.9% visible · 72.5% high+medium | **76.9%** · 68.9% · 69.3% |

Recall is the measured weakness and `docs/ACCURACY.md` is where it is not
rounded off: what a label is, which programs are *tuned*, and the gap per rule.
The corpus is 158 programs and 515 of its 546 labels are **unseen** — written
by somebody who was not developing the rule they exercise — which is why the
unseen column is only a point and a half below the whole-corpus one.

On the public corpus the claim is different in kind, because nothing there is
labelled: `tools/public_corpus.py check --strict` asserts no crash, no schema
error, every exit code 0 or 4, every run inside its wall-time budget, and **no
new high-severity finding** that a human has not written down in
`analyzer/tests/public_corpus/adjudication.json`. That last one is the gate that
has actually caught things: four false positives no label in the tree could
have found.

## Running it

The same four steps on every platform; use a virtual environment, never the
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
`tomllib`) and **Node 20+**; set `PYTHONUTF8=1` on Windows. Both drivers run the
same table and print the same rows, and `scripts/pythonpick.sh` finds the POSIX
driver a 3.10+ interpreter.

Individual suites and gates:

```sh
python -m pytest analyzer/tests -q        # analyzer core + rules
python -m pytest claude-plugin/tests -q   # MCP handshake, budgets, manifests
python -m pytest scripts -q               # the doc and packaging gates
cd webview && npm test                    # layout, bundle hygiene, parity, contrast
cd vscode-extension && npm test           # protocol, ranges, CSP, digests, mapping
python tools/verify.py --all              # the parity gates
python tools/accuracy.py                  # the labelled corpus, the default mode (`ip`)
python tools/accuracy.py --dataflow local # the same, forcing the narrower mode
python tools/accuracy.py --dataflow ip     # the same, naming the default explicitly
python tools/public_corpus.py fetch --corpus-dir .public-corpus
python tools/public_corpus.py run   --corpus-dir .public-corpus --out pc.json
python tools/public_corpus.py check --corpus-dir .public-corpus --report pc.json --strict
```

---

## What is verified, and what is not

**Exercised end to end on this machine, and now by CI as well.**
`.github/workflows/ci.yml` runs a cheap tier on a push and adds the rest on a
pull request and on a push to `main`. Actions billing was blocked at the account
level for the whole of the consolidation and the recall campaign, so every job
came back unstarted and all of that work was checked here alone. The block went
with the repository going public: the matrix has run on the `public` → `main`
pull request and all thirteen jobs are green — run 34983316368 for the seven
cheap-tier jobs and run 34983321423 for the other six. So **Python 3.10, 3.11
and 3.12, Windows and macOS are exercised there rather than here** — this machine
has 3.13 alone, and `CHANGELOG.md` records what was measured when.

What *is* exercised here: the analyzer and its rules; the CLI, including
`--demo` byte parity and every documented exit code; a real stdio MCP handshake
with `PYTHONPATH` pointing only at `claude-plugin/vendor`, which also proves the
no-`pip install` path; the self-contained and scoped HTML reports; all four
parity gates; and the 260 runs over 37 pinned third-party repositories.

**Compile-verified only**: the VS Code Extension Development Host (F5) has never
been driven under automation and Copilot is not installed here, so `@mlview` and
the three language-model tools are type-checked and unit-tested against a mocked
`vscode` and have never met a live Copilot session. The exercised Copilot
surface is the `DiagnosticCollection` — what a Copilot agent reads today is the
Problems panel, and that path is tested. [`docs/VALIDATION.md`](VALIDATION.md)
is the runbook for closing both gaps by hand on a second machine, and
[`docs/DEMO_LOG.md`](DEMO_LOG.md) is the template the validator fills in.

## Known gaps

None blocks the demo. Roughly in the order they matter:

- **No live host run.** The extension has never run inside a real VS Code
  webview and the chat surfaces have never met a live Copilot session; both are
  covered by unit tests against `vscode-extension/test/mock-vscode.js` plus a
  real subprocess test against a fake CLI.
- **Loop nesting is flattened.** Invariant §1.1.2 plus a three-value `NodeLevel`
  cannot express function → epoch loop → batch loop → op, so an inner loop is a
  sibling of its epoch loop. The depth survives in `LoopIR.depth` /
  `LoopIR.parent_loop` (`analyzer/src/mlview/ir/model.py`); it cannot be drawn.
- **Cross-file call following is one level.** `analyzer/src/mlview/ir/resolve.py`
  fills `target_function` for a call into a workspace module and stops, so a rule
  cannot chase a helper that a helper calls. `from config import N` resolves;
  `import config` then `config.N` does not.
- **The framework gate reaches one import hop.** `ctx.wrappers_for()`
  (`analyzer/src/mlview/rules/context.py`) de-rates an absence finding only when a
  Lightning / HF Trainer / accelerate / ignite / fastai / DDP / FSDP wrapper sits in
  the finding's own module or one it imports — `_detect_wrappers()` in
  `analyzer/src/mlview/ir/build_ir.py` walks exactly one hop. It caps severity at
  `medium` and scales confidence by 0.4; it never drops a finding.
- **`MLV201`'s `negation_absent` evidence line reads the workspace-wide set.**
  `analyzer/src/mlview/rules/r_trainloop.py` composes that sentence from
  `ctx.wrappers`, not from the per-module set the gate uses, so an ungated
  hand-written loop can carry "framework wrapper detected: Lightning" beside a
  `certain` finding. Severity and confidence are right; the sentence is not.
- **The interprocedural hop cap is a guess.** `DEFAULT_MAX_HOPS`
  (`analyzer/src/mlview/ir/provenance.py`) is deep enough for caller → ctor →
  attribute → sibling method and shallow enough that two hops stay above
  `speculative`; nothing measured that choice. A chain past it is not propagated
  and **is** reported as a `truncated` diagnostic.
- **`local` is not a subset of `ip`.** One mlflow example in the public corpus
  reports a finding under `--dataflow local` that `--dataflow ip` does not, with
  `diagnostics == []` in both modes, so the recall inequality holds in aggregate
  and not per finding. It is `state: "open"` in
  `analyzer/tests/public_corpus/adjudication.json`.
- **A fold is lossy about *which* thing.** After
  `analyzer/src/mlview/core/rollup.py` folds a file or directory the diagram shows
  one card carrying `rolledUp` and nothing says what was inside it; the summary's
  `kind` and `stage` are a majority vote with no record of how close it was. Every
  finding keeps a real `loc`, so this is legibility, not correctness.
- **A `pipeline:` view draws the other entrypoints, greyed.**
  `analyzer/src/mlview/core/pipelines.py` pulls in up to one file per neighbour as
  context, `workspace.entrypoints` is a heuristic capped at 10, and nodes in no
  pipeline are counted, never named.
- **A structured fix lands at coordinates nobody can prove are current.**
  `vscode-extension/src/fixes.ts` refuses an unsaved buffer and a file shorter than
  the analysis saw — but a file edited, saved and left the same length passes both.
- **The multi-root diagram shows one folder at a time.** `folderTooltipLine` in
  `vscode-extension/src/folders.ts` names the folder the count describes and how
  many it does not; the Problems panel is the only surface showing the union.
- **The per-finding notebook cell mapping is a string, not a field.**
  `analyzer/src/mlview/rules/confidence.py` writes it as one evidence detail
  because `Loc` is frozen, and `vscode-extension/src/notebooks.ts` regex-matches
  that sentence to place a squiggle. A test pins the format on both sides.
- **The Claude Code hooks do nothing on Windows without Git Bash.** The command
  in `claude-plugin/hooks/hooks.json` is shell form, which is PowerShell there,
  and `${MLVIEW_PYTHON:-python}` does not expand. Nothing runs — but the exit is
  non-zero, and a non-zero `PostToolUse` exit raises a visible *hook error*
  notice on every edit, so the degradation is **noise, not silence**. A
  `"shell": "bash"` field on both entries is the fix; it is not applied yet.
- **`--list-scopes` lists units only.** `analyzer/src/mlview/emit/scope_out.py`
  prints the scopable-unit catalogue; the four concerns and the eight stage ids
  are discovered from this document, the MCP tool description, or the candidates
  an unusable selector prints.

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
