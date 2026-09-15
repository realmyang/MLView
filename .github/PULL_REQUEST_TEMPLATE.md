<!--
Delete the rows that do not apply, but do not tick a row you did not run.
"Not run, and here is why" is a perfectly good line in a pull request; a tick
that turns out to be a guess is the one thing that costs this project its
reason to exist. `CONTRIBUTING.md` explains every gate below and which subset
a change of your kind needs.
-->

## What this changes

<!-- One paragraph. What is different afterwards, and why. If it fixes an
issue, `Fixes #123`. -->

## How to see it

<!-- The command or the click that shows the new behaviour, and what it prints
or draws. A before/after pair for anything visual. -->

## Gates

Paste the tail of each run you ticked — the `PASS` / `OK` line is enough.

- [ ] `python -m pytest analyzer/tests -q` — analyzer and rules
- [ ] `cd webview && npm test && npm run check` — viewer
- [ ] `cd vscode-extension && npm run check && npm run compile && npm test` — extension
- [ ] `python -m pytest claude-plugin/tests -q` — plugin and MCP
- [ ] `python -m pytest scripts -q` — the doc and packaging gates themselves
- [ ] `python tools/verify.py --all` — 10 parity gates (versions, vendored core, VSIX core, scope Python == TypeScript, renderer hashes)
- [ ] `python scripts/check_docs.py` — **every change, including a docs-only one**
- [ ] `sh scripts/e2e.sh` / `powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1` — 20 steps, the whole table in one pass

### If this touches the analyzer or any rule

- [ ] `python tools/accuracy.py` — the default (`ip`) mode, against `analyzer/tests/accuracy/baseline.ip.json`
- [ ] `python tools/accuracy.py --dataflow local` — the opt-out mode, against `analyzer/tests/accuracy/baseline.json`
- [ ] **Both** are green. Precision is **100% on every rule** and stays there; zero `forbidden`, zero unlabelled findings. Recall and graph fidelity may only ratchet **up**.
- [ ] If a baseline moved: re-recorded with `python tools/accuracy.py --update-baseline`, and the body below says which change earned it. A downward move needs `--allow-regression "<reason>"`, and the reason is now in the baseline's `note`.
- [ ] `python tools/public_corpus.py run --out report.json` then `check --report report.json --strict` — run this whenever a rule changes **what it fires on**. A new high-severity finding on the 37 pinned repositories fails the gate until a human has read the code and recorded a verdict in `analyzer/tests/public_corpus/adjudication.json`.
- [ ] New or changed rule: two fixtures (`<CODE>_bad.py` with its `# MLVIEW-EXPECT:` lines, `<CODE>_good.py` with `# MLVIEW-EXPECT-NONE:`), and `python analyzer/tools/gen_rule_docs.py` re-run so `docs/rules/` is current. See `docs/CONTRIBUTING-RULES.md`.

### If this touches a contract

- [ ] Nothing in `docs/CONTRACTS.md` was edited in place to match new behaviour. **A change to a contract you do not own is reported, not made**: a normative change goes in as a dated, additive fragment under `docs/contracts/<slug>.md` for the contracts owner to fold, and a statement that turned out to be wrong is recorded as a `§17` erratum rather than quietly rewritten.
- [ ] Schema change (if any) is **optional fields only**, mirrored byte-identically between `contracts/graph.schema.json` and `analyzer/src/mlview/schema/graph.schema.json`.
- [ ] `contracts/graph.sample.json` is untouched and `python -m mlview analyze --demo --json -` is still byte-identical to it. If a legitimate change moved the golden, say so here in full — it is the one figure the whole tree is pinned to.

### Claims

- [ ] Every number written in this PR, in a commit body or in a doc is one I measured on this branch, with the command beside it.
- [ ] Anything I could not check is named here rather than left out — a platform, a host, an interpreter, a gate that needs something this machine does not have. **A gate claimed green on CI names the run that was green** (`gh run list --branch <branch>`); "green on my machine" is the honest phrasing for everything CI did not run.
- [ ] Nothing under `docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md`, `docs/ISSUE_RULES.md` or `docs/UX_DESIGN.md` was edited to describe what the build now does — those are frozen plan records, and `scripts/check_docs.py` check 6 fails on a build-state sentence inside one.

## What I could not check

<!-- Platforms, hosts, interpreters, or a gate that needs something you do not
have (a live Copilot session, `claude plugin validate`, 1.9 GB of clones).
Write it down; it is a result. -->
