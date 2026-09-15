# Contributing to MLView

MLView reads Python ML code and draws it: an interactive pipeline diagram with
findings on it, in three hosts (a standalone HTML report, a VS Code extension, a
Claude Code plugin). It is a static analyzer, so almost every interesting
question here is the same question — *did we just claim something we cannot
back?*

That is worth stating before the setup instructions, because it decides what a
good contribution looks like:

* **Precision before recall.** MLView's one strong claim is that it does not
  lie. Precision is **100% on every rule** across the labelled corpus and the
  gate fails on a single finding no label covers. A patch that finds two more
  defects and one thing that was never wrong is a regression here, not a
  trade-off.
* **Never look clean when you were blind.** If MLView could not read something,
  it says so — in the `diagnostics[]` block, in the coverage banner, in the
  verdict sentence. A clean report after a partial analysis is the failure mode
  this project is built to prevent.
* **It never runs your code.** Not imported, not `exec`ed, not `eval`ed, not
  compiled — enforced by `analyzer/tests/core/test_no_exec.py`, which parses
  the core and fails on the call or the import that would break it. Any design
  that needs a runtime value has to find another way.
* **Every number is a measurement.** Figures in the docs name the command that
  produced them. Where prose and a command disagree, the command wins.

Reporting something is contributing. A **false positive report** is the single
most valuable issue this project takes — there is a template for it, and the
usual outcome is a permanent `forbidden` label in the corpus so the rule can
never fire that way again.

---

## 1 · Getting it running

You need **Python 3.10+** (3.11+ to use a `.mlview.toml`: 3.10 has no
`tomllib`) and, for the viewer and the extension, **Node 20+**. No ML framework
is required — MLView never imports the code it reads, so a machine with neither
torch nor scikit-learn installed is a *better* test of it, not a worse one.

### macOS / Linux

```sh
git clone https://github.com/realmyang/MLView
cd MLView

python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e analyzer

sh scripts/build.sh          # BUILD OK — 6 steps
sh scripts/e2e.sh            # E2E OK — 20 steps, 0 failed
```

### Windows (PowerShell 5.1 or newer)

```powershell
git clone https://github.com/realmyang/MLView
cd MLView

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # Activate.ps1 is an
                                                            # unsigned local script and the
                                                            # client default is Restricted
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
python -m pip install -e analyzer

powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
```

The `.ps1` and `.sh` drivers do the same thing, step for step; pick whichever
shell you are in. The PowerShell ones are Windows PowerShell 5.1 compatible (no
`&&`, no `||`, no ternaries — every step checks `$LASTEXITCODE`), and the POSIX
ones must stay LF-only: `scripts/check_docs.py` check 7 fails the build on a
shell script written with CRLF, because `#!/usr/bin/env sh<CR>` asks the kernel
for a program named `sh<CR>`.

### The JavaScript halves

```sh
cd webview           && npm install && npm test && npm run check
cd ../vscode-extension && npm install && npm run compile && npm test
```

`npm run compile` in `vscode-extension` also regenerates the bundled rule pages
and the walkthrough, and builds `vscode-extension/core/` — a **build artifact**,
git-ignored on purpose, which is why a fresh clone needs `scripts/build.sh`
before the extension suite means anything.

### Two environment variables worth exporting

```sh
export PYTHONUTF8=1              # Windows consoles, and any non-UTF-8 default
export PYTHONDONTWRITEBYTECODE=1 # keeps __pycache__ out of claude-plugin/vendor,
                                 # which the vendor gate checks after the suite
```

CI sets both (`.github/workflows/ci.yml`). On Windows, `PYTHONUTF8=1` is not
optional.

### Optional pieces

* **The Claude Code plugin** needs the official MCP SDK — `python -m pip install
  mcp` (v2; verified against 2.1.1). It is deliberately not vendored. It also
  needs `MLVIEW_PYTHON` set to an absolute path to a 3.10+ interpreter, because
  `claude-plugin/.mcp.json` defaults to a bare `python`, which does not exist on
  most macOS and Linux systems.
* **The public-repository corpus** clones ~1.9 GB of third-party repositories.
  You only need it when you change what a rule fires on (section 6).

`docs/VALIDATION.md` is the longer version of all of this: the runbook for
bringing MLView up on a machine it was never built on, with a 30-minute session
per host and what "working" means for each check.

---

## 2 · The layout

| Directory | What is in it |
|---|---|
| `analyzer/` | The Python core: ingest, IR, rules, emitters, CLI. Installable as `mlview`, zero runtime dependencies. |
| `webview/` | The viewer: layout, rendering, interaction. TypeScript, bundled and inlined into the standalone report and the extension panel. |
| `vscode-extension/` | The VS Code host: panel, Problems integration, code actions, export, Copilot participant. |
| `claude-plugin/` | The Claude Code host: slash commands, the MCP server, hooks, and a vendored copy of the analyzer. |
| `contracts/` | The frozen schema, the golden document and the scope fixtures. **Read-only once written.** |
| `scripts/` | The two drivers (`build`, `e2e`) and the documentation gate. |
| `tools/` | The cross-cutting gates: parity, accuracy, the public corpus, the wheel check. |
| `samples/` | Two shipped programs — a defective pipeline and its correct twin. |
| `docs/` | Everything written down. `docs/README.md` is the index. |

Three copies of the analyzer exist on purpose: `analyzer/src/mlview` is the
source, `claude-plugin/vendor/` and `vscode-extension/core/` are **synced
artifacts**. Never edit a copy — `python tools/verify.py --all` fails when one
drifts, and `sh scripts/build.sh` is what puts them back in step.

---

## 3 · The gates, and which ones your change needs

The full gate-by-gate table — every row, the one command that runs just that
row, and what a green row proves — is [`scripts/README.md`](scripts/README.md).
`scripts/e2e` runs them in one pass and prints a PASS/FAIL table.

**Run the whole table before you open a pull request.** While you are working,
this is the subset that matters:

| If you changed… | Run |
|---|---|
| The analyzer or a rule | `python -m pytest analyzer/tests -q`, then **both** accuracy modes (section 5), `python tools/verify.py --all`, `python scripts/check_docs.py` |
| What a rule fires on | …and the public corpus, `--strict` (section 6) |
| The viewer (`webview/`) | `npm test` and `npm run check` in `webview`, then `sh scripts/build.sh` and `python tools/verify.py --all` — the three checked-in copies of the bundle and the renderer hashes are gates |
| The VS Code extension | `npm run check`, `npm run compile`, `npm test` in `vscode-extension`; `python tools/verify.py --vsix` if you touched packaging or `.vscodeignore` |
| The plugin or the MCP server | `python -m pytest claude-plugin/tests -q`, then `python tools/verify.py --all` for the vendored-core row |
| The schema or a contract | `python contracts/validate_sample.py .mlview/graph.json` and the golden-parity row — `python -m mlview analyze --demo --json -` must stay byte-identical to `contracts/graph.sample.json` |
| Only documentation | `python scripts/check_docs.py` **and** `python -m pytest scripts -q` (the gate has its own tests) |
| Anything crossing two components | `sh scripts/e2e.sh` — that is what it is for |

Three notes that save an hour each:

* **`python scripts/check_docs.py` runs on every change, including a code-only
  one.** Twenty-three checks, all offline: dead paths, dead links, a "known
  gap" bullet describing a failure somebody already fixed, a gap bullet citing
  a symbol that has been renamed away, a build-state sentence inside a frozen
  plan document, a CRLF shell script, two documents disagreeing about the size
  of the demo graph, a CI command line the tool it invokes would reject, and a
  gate claimed green on a matrix that never ran. It catches renames long before
  a reader does.
* **A "known gap" bullet must cite something the gate can check** — a repo path
  or a code symbol, in backticks. A rule code is not enough: `MLV301` says
  nothing about the tree. A claim nobody can retire is a claim that will rot.
* **Files stay under 600 lines**, tests excepted. The threshold the last
  consolidation actually split source on was 750, so a handful of files sit
  between the two budgets as stated exemptions. The command that settles it:
  `git ls-files '*.py' '*.ts' '*.js' '*.mjs' | grep -v -e '^vscode-extension/core/' -e '^claude-plugin/vendor/' -e '/test' | xargs wc -l | sort -rn | head`.

### Style

There is no autoformatter and no lint step, deliberately: a reformat-the-world
commit buries the change it carries. `.editorconfig` records the conventions
already in the tree — LF, UTF-8, 4-space Python, 2-space TypeScript / JSON /
YAML, no trailing whitespace outside Markdown. Match the file you are editing.
Module docstrings in this repository explain *why* a thing exists and what
incident it prevents; they are the most useful prose in the tree, and a new
module is expected to carry one.

---

## 4 · Contracts v1.1

[`docs/CONTRACTS.md`](docs/CONTRACTS.md) is **normative**. It binds every
component, and the standard it is written to is that an agent can implement its
component from that document alone. The JSON schema, the CLI surface, the
webview↔host message protocol, the MCP tool shapes and the ordering and id
rules that make every document byte-deterministic all live there.

**Ownership.** §1–§7 and §14 belong to the analyzer, §8–§10 to the viewer, §11
and §13 to the plugin and the hosts, §12 to the VS Code extension, §15–§19 to
the contracts owner. `contracts/` is read-only for everyone once written.

**How it changes — this is the part people get wrong.**

* **A change to a contract you do not own is reported, not made.** You write a
  dated, normative, additive fragment at `docs/contracts/<slug>.md`; the
  contracts owner folds it into the section that owns the clause. That is how
  v1.1 was assembled: v1.0 plus 75 append-only amendments, folded into one
  document with the narrative history moved out.
* **A statement that turns out to be wrong becomes an erratum, not an edit.**
  §17 is the record of every statement that did not survive — 43 of them — with
  the resolution folded into the body. A later, more specific clause wins over
  an earlier general one, and says so. Quietly rewriting a superseded sentence
  destroys the only record of *why* the current one reads as it does.
* **§18 maps every old amendment number to the v1.1 section that carries it**,
  so a `CONTRACTS.md §11.25` citation anywhere in the tree still resolves. Cite
  freely; do not renumber.
* **Schema changes are optional fields only**, mirrored byte-identically
  between `contracts/graph.schema.json` and
  `analyzer/src/mlview/schema/graph.schema.json`.
  `contracts/graph.sample.json` never changes, and `mlview analyze --demo
  --json -` staying byte-identical to it is a gate.
* `docs/CONTRACTS.md` is exempt from the documentation gate, because it carries
  the dated measurements of every amendment folded into it and a gate that
  forced those to be rewritten would make §17 impossible. The price of that
  exemption is that **every figure in it names the command that settles it**.
  Keep paying it.

---

## 5 · Accuracy: the corpus and the two ratchets

`analyzer/tests/accuracy/corpus/` holds the labelled corpus — **158 programs**
as of 2026-09-15, most shipping as a defective / correct pair so that a
zero-false-positive claim has something to be zero about. Each program is a
directory with its sources and a `labels.json` beside them.

```sh
python tools/accuracy.py                      # the default (ip) mode: report + gate
python tools/accuracy.py --dataflow local     # the opt-out mode, its own ratchet
python tools/accuracy.py --verbose            # every missed label and missing op
python tools/accuracy.py --program hydra_research --no-gate
python -m pytest analyzer/tests/accuracy -q   # the same three gates, asserted
```

### What a label is

Three verdicts, not two, so *"the tool may or may not say this"* is expressible
and the corpus does not become a ceiling of its own:

```json
{"code": "MLV101", "file": "datamodule.py", "line": 27,
 "symbol": "self.scaler.fit_transform", "severity": "high",
 "verdict": "expected",
 "defect": "the scaler is fitted on the whole frame inside setup()",
 "why":    "every validation row has already contributed its mean and variance"}
```

* **`expected`** — a defect planted on purpose. Firing on it is a true
  positive; missing it moves recall.
* **`acceptable`** — MLView may reasonably go either way. Scored neither as a
  hit nor as a false positive.
* **`forbidden`** — firing here is *wrong*, and the label **must** say why; the
  loader refuses a corpus where one does not. Any hit is a hard failure,
  regardless of the baseline.

An unsuppressed finding that satisfies no label at all counts as a **false
positive**. That is deliberate: the corpus is labelled exhaustively, and
`acceptable` is how a legitimate-but-unplanted observation gets expressed. A
new rule that starts firing here needs a label, not an exemption.

Each program also carries a small `graph` block — the ops a person sketching
that pipeline on a whiteboard would draw, each a `file` + `line`. An op counts
as recovered only when a node is anchored on **that exact line**.

### Tuned versus unseen

A few programs are marked `"tuned": true` — seven of the 158 today: the rules
were developed against them, so their numbers are a ceiling rather than a
measurement. Every headline is
quoted twice — over the whole corpus and over the **unseen** programs alone —
and a rule labelled only in tuned programs is marked as such in the report, by
a test that exists to stop that from going unnoticed.

### The two modes, the two ratchets

`--dataflow ip` (interprocedural) is the shipped default and is gated against
`analyzer/tests/accuracy/baseline.ip.json`. `--dataflow local` is the narrower
opt-out and is gated against `analyzer/tests/accuracy/baseline.json`. They are
two different analyses and one ratchet cannot gate both, so **both must be
green**; `ip` must never report *less* than `local`.

The three gates, in the order they are checked:

1. **Zero `forbidden` findings, ever.** Not a baseline, not a ratchet, no
   tolerance. No flag suppresses it: `--no-gate` covers the ratchet comparison
   only and still exits `2`, and `--update-baseline` refuses to write while one
   is firing.
2. **Recall may only ratchet up** — overall, unseen-only, and per rule, in all
   three readings (raw, visible, high+medium).
3. **Graph fidelity may only ratchet up.**

Precision is not on that list because it is not a ratchet: it is **100% and
stays 100%**, on every rule, in both modes.

The baseline is a floor, never a pin — a rule that starts finding something it
used to miss passes. When a change legitimately earns a new number, re-record
it with `python tools/accuracy.py --update-baseline` and say **in the commit
body which change earned it**. That command enforces gate 2 rather than
bypassing it: it refuses to run from a `--program` subset, refuses to write
while a `forbidden` finding fires, prints the before/after of every gated
number that moved in either direction, and exits `3` if any moved down.
Recording a downward move takes an explicit `--allow-regression "<reason>"`,
and that reason is written into the new baseline's own `note` field — so the
file says why it went backwards rather than leaving the evidence in a commit
message nobody reads next to it.

Adding a program to the corpus is described in
[`docs/CONTRIBUTING-RULES.md`](docs/CONTRIBUTING-RULES.md); the numbers the
corpus produces today, per rule, with the gaps named rather than averaged away,
are in [`docs/ACCURACY.md`](docs/ACCURACY.md).

---

## 6 · The public-repository corpus, and adjudication

The labelled corpus measures MLView against programs written *for* it. The
public corpus measures it against code nobody wrote for it: **37 real,
popular Python ML repositories**, pinned to exact commits in
`analyzer/tests/public_corpus/repos.json`. Nothing is vendored.

```sh
python tools/public_corpus.py fetch                        # ~1.9 GB, network, once
python tools/public_corpus.py run   --out report.json
python tools/public_corpus.py check --report report.json --strict
```

`check` asserts five things, each a credibility claim rather than a taste: no
traceback in any run; exit 0 or 4 only (4 is "nothing analyzable found"); every
emitted document passes the same validator the golden sample uses; every run
inside its wall-time budget; and **no new high-severity finding, and no
adjudicated false positive**.

That last one is the interesting mechanism. `analyzer/tests/public_corpus/adjudication.json`
records a verdict for every high-severity finding this corpus has ever
produced, keyed by `repo|CODE|repo-relative file|symbol`:

* A high finding whose key is **not** in that file fails the gate. It has not
  been read by a human yet — so read the code, decide, and write down which it
  is and why.
* A finding adjudicated `false-positive` carries a `state`. `open` means the
  analyzer still produces it (listed, and fatal only under `--strict`);
  `fixed` means it must never come back, and the gate fails if it does.
* Under `--strict`, an adjudicated false positive that has **gone away** also
  fails — the record is stale and wants its `state` updated.

So one file is the review record, the campaign's open list and the regression
ratchet at once. It is the only gate that can see a false positive nobody
thought to label, and it has earned its keep several times over. A weekly
workflow (`.github/workflows/public-corpus.yml`) runs it on a schedule and on
demand; it never runs on a push or a pull request.

---

## 7 · Commits and pull requests

**Branches.** Work on a branch and open a pull request into `main`. Never
force-push a shared branch.

**Commits.** An imperative subject line that says what the commit does
("Absolutize the public-corpus directory so a relative `--corpus-dir` still
reaches the analyzer children"), then a body in prose. The body is where this
project keeps its reasoning: what was wrong, what the fix is, which gate would
have caught it and now does, and any number you moved with the command that
measured it. Group a wide change by component (`Analyzer`, `Viewer and hosts`,
`Docs and process`) rather than listing files. If a tool co-wrote the change,
record it in a `Co-Authored-By:` trailer.

**Staging.** Add the paths you changed, by name. `git add -A` in this
repository is how a generated bundle, a 30 MB gallery or someone else's
half-finished file ends up in a commit.

**Pull requests.** `.github/PULL_REQUEST_TEMPLATE.md` is the gate checklist;
fill it in honestly. A row that says "not run, because I have no Windows
machine" is a good line in a pull request. A tick that turns out to have been a
guess is the one thing that costs this project its reason to exist. The last
section of the template asks what you could not check — **a check you could not
run is a result, so write it down.**

---

## 8 · CI: the two tiers, and what they cost

`.github/workflows/ci.yml` runs the gate table in two tiers, and the header of
that file carries the arithmetic.

* **Cheap tier — every push, and every pull request from a fork.** The analyzer
  on Python 3.10 and 3.13 (the two ends of `requires-python`), the viewer on
  Node 20, the extension suite, the plugin suite, the accuracy corpus and the
  Linux end-to-end table: seven jobs, **7m49s of wall and 27 weighted minutes**
  when the matrix was first measured end to end (run 34975663652).
* **Full tier — pull requests, and pushes to `main`, on top of the cheap
  tier.** Python 3.11 and 3.12, Node 22, the Windows end-to-end table, the
  macOS smoke job and packaging: six more jobs, **12m03s of wall and 146 more
  weighted minutes**, of which **100 are the single macOS job** — more than the
  other twelve jobs put together (10× weighting, each job rounded up to a whole
  minute on its own before its weight is applied). The tiers were designed
  around an estimate of ~30 for that job; the measurement is what row 25 of
  `scripts/README.md` now carries, and it vindicates where the job sits rather
  than the number. Weighting is history while the repository is public — GitHub
  charges nothing for a standard runner — so read these as relative cost.

The split is exact rather than approximate: the cheap tier carries a
same-repository double-billing guard (a branch push and a same-repo pull
request are two events for one commit) and the full tier runs on exactly the
events that guard excludes, so each job is paid for once. A push that touches
only `**.md` and `docs/` runs nothing at all; a pull request deliberately has
no such exemption, so a docs-only branch is still checked before it merges.
**The tiers move when the expensive half is paid for, not whether** — nothing
reaches `main` unchecked on any supported interpreter, either e2e driver or any
of the three platforms.

Two separate budgets sit outside both tiers: `.github/workflows/nightly.yml`
(the scope fuzzer, 2000 cases on a schedule) and
`.github/workflows/public-corpus.yml` (weekly, plus manual).

**What has actually run.** Read this before you trust a green tick anywhere in
this repository: GitHub Actions was billing-blocked at the account level for the
whole of the consolidation and recall work, so all of it was checked on one
machine — Python 3.13, macOS — and nowhere else. That ended when the repository
went public. The matrix has run on the `public` → `main` pull request and all
thirteen jobs came back green: run 34986234828 took the seven cheap-tier jobs
and run 34986239243 the six the cheap tier excludes. The first time every job in
`.github/workflows/ci.yml` executed on any branch of this project was run
34975663652 with its pull-request half, one Windows fix earlier; the matrix has
been green on every commit of the branch since. `main` itself has had no run
since the block was lifted, so the badge at the top of the README stays red
until this merges. The rule the documents
live under is unchanged: a claim that something is green on CI has to name the
run that was green, which is what `scripts/check_docs.py` check 22 enforces.

---

## 9 · Where the documentation is

[`docs/README.md`](docs/README.md) indexes every document in one line each. The
five you are most likely to want:

| Document | What it is for |
|---|---|
| [`docs/STATUS.md`](docs/STATUS.md) | What is in the tree today, what is verified, and the known gaps |
| [`docs/CONTRACTS.md`](docs/CONTRACTS.md) | **Normative.** Schema, CLI, MCP tools, message protocol |
| [`docs/ACCURACY.md`](docs/ACCURACY.md) | The labelled corpus: precision, recall, fidelity, and what is still missed |
| [`scripts/README.md`](scripts/README.md) | The gate table: every row, its command, and what green proves |
| [`docs/CONTRIBUTING-RULES.md`](docs/CONTRIBUTING-RULES.md) | How to add a rule and a corpus program, end to end |

`docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md`, `docs/ISSUE_RULES.md`,
`docs/UX_DESIGN.md` and `docs/FEATURES_FLOW_AND_SCOPE.md` are **frozen plan
records**: they say what was decided, not what was built. The documentation
gate link-checks them and nothing else, precisely so that editing one to match
the code cannot quietly erase a decision — and it fails on a sentence inside
one that reports what the build currently does.

## 10 · Code of Conduct, licence, security

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1). Contributions are licensed under the repository's
[MIT licence](LICENSE). Please do not open a public issue for a security
problem — [SECURITY.md](SECURITY.md) has the private route, and also documents
exactly what MLView does and never does with the code you point it at.
