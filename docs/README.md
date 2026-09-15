# docs/

Every document in the repository, one line each, grouped by the question it
answers. Nothing here is a summary of the documents it lists — the point is to
tell you which one to open.

Three of them carry different weights, and it is worth knowing which is which
before you cite one:

* **Normative** — `docs/CONTRACTS.md`. It binds. Where it and any other
  document disagree, it wins.
* **Current-state** — `docs/STATUS.md`, `README.md`, `docs/ACCURACY.md`,
  `scripts/README.md` and the per-directory READMEs. These describe the tree as
  it is, and `scripts/check_docs.py` holds them to it: every path they name
  must exist, every gap bullet must cite something checkable, and a green
  verdict written in the same breath as the CI matrix has to say whether that
  matrix ran and name the run when it did (here: runs 34986234828 and
  34986239243, thirteen green jobs on the `public` → `main` pull request).
* **Frozen plan records** — the design documents in the third table below. They
  say what was *decided*, not what was built. The gate link-checks them and
  nothing else, and fails on a sentence inside one that reports what the build
  currently does, because rewriting a plan to match the code erases the only
  record of the decision.

## Start here

| Document | What it is for |
|---|---|
| [`README.md`](../README.md) | What MLView is, ninety seconds to a diagram, install per host, the CLI, what is verified and what is not |
| [`STATUS.md`](STATUS.md) | The current-state page: what is in the tree today, what has actually been run, and every standing gap |
| [`CHANGELOG.md`](../CHANGELOG.md) | The dated history, newest first, each entry at the figures measured at the time |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Dev setup on all three platforms, which gates to run for which change, the contract and corpus mechanisms, commit and PR conventions |
| [`CONTRIBUTING-RULES.md`](CONTRIBUTING-RULES.md) | The narrower walkthrough: adding a rule, and adding a program to the labelled corpus |
| [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) | Contributor Covenant 2.1, and how to report a concern |
| [`SECURITY.md`](../SECURITY.md) | What MLView does with your code — static only, no execution, no network — and how to report a vulnerability |
| [`LICENSE`](../LICENSE) | MIT |
| [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) | The third-party software redistributed inside an MLView artifact, with each licence copied verbatim |

## What binds, what is measured, what is run

| Document | What it is for |
|---|---|
| [`CONTRACTS.md`](CONTRACTS.md) | **Normative, v1.1.** The schema, the CLI, the MCP tools, the webview↔host protocol, the id and ordering rules, §17 errata and the §18 amendment index |
| [`ACCURACY.md`](ACCURACY.md) | The labelled corpus: what a label is, precision, recall and graph fidelity in both dataflow modes, and the gaps named per rule |
| [`VALIDATION.md`](VALIDATION.md) | The runbook for validating MLView by hand on a machine it was not built on, and the step-by-step publishing procedure |
| [`DEMO_LOG.md`](DEMO_LOG.md) | The template you copy and fill in *while* you validate; completed logs live in `docs/demo-logs/` |
| [`ROADMAP.md`](ROADMAP.md) | The ranked backlog from four audits, with the acceptance clause and the landing measurement for each shipped item |
| [`RESEARCH_COVERAGE_ACCURACY.md`](RESEARCH_COVERAGE_ACCURACY.md) | The 2026-09-15 research review: where the recall goes (107 misses in seven causes), three defects in shipped rules, 37 candidate rules in three tiers with their false-positive exposure measured on the public corpus, and a three-sprint sequence. Advisory, like `ROADMAP.md` |
| [`research/sources.md`](research/sources.md) | The numbered bibliography that review cites, each entry marked with how far it was verified |
| [`../scripts/README.md`](../scripts/README.md) | The gate table: every row, the single command that runs just that row, what green proves, and the two CI tiers with their cost |

## Rules

| Document | What it is for |
|---|---|
| [`rules/README.md`](rules/README.md) | The index of all 36 rules — code, severity, title, frameworks, prior — generated from the registry |
| [`rules/MLV101.md`](rules/MLV101.md) … | One page per rule, generated from the rule declaration and its two fixtures: what it looks for, the trap its `_good` fixture encodes, the fix, and on several rules a **What it cannot analyze** section. Every `Issue.docs` field deep-links here, offline |
| [`ISSUE_RULES.md`](ISSUE_RULES.md) | The frozen catalog the rule set was designed from — the reasoning behind the codes and the fixed severities (a plan record) |

## The design records (frozen)

These were written before the build and are kept as written. They are normative
for *what was decided*; `docs/CONTRACTS.md` is normative for what anything codes
against.

| Document | What it is for |
|---|---|
| [`REQUIREMENTS.md`](REQUIREMENTS.md) | What must be true when the prototype is done — R0–R4, per persona |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The shape of the system, the reasoning behind it, and the build workflow |
| [`UX_DESIGN.md`](UX_DESIGN.md) | The design system and interaction specification: the viewer, buildable from |
| [`FEATURES_FLOW_AND_SCOPE.md`](FEATURES_FLOW_AND_SCOPE.md) | The flow animation and the scoped views, designed in full before either was written |
| [`archive/README.md`](archive/README.md) | Why the archive exists and what is not allowed to change in it |
| [`archive/CONTRACTS-v1.0-amended.md`](archive/CONTRACTS-v1.0-amended.md) | Contracts v1.0 plus its 75 amendments, verbatim — the record of *why* v1.1 reads as it does |
| [`../project.md`](../project.md) | The four-line kickoff brief the project was started from, kept verbatim because the frozen plan records answer to it. It predates the 36 rules and the third host; nothing in it describes the tree |

## Per-directory READMEs

Each component documents itself next to its own code.

| Document | What it is for |
|---|---|
| [`../analyzer/README.md`](../analyzer/README.md) | The Python core: what it analyzes, how to run it, what it will not do |
| [`../webview/README.md`](../webview/README.md) | The renderer bundle, built once and consumed unchanged by both hosts |
| [`../vscode-extension/README.md`](../vscode-extension/README.md) | The VS Code host: commands, settings, the Copilot surface |
| [`../claude-plugin/README.md`](../claude-plugin/README.md) | The Claude Code host: slash commands, the five MCP tools, the hooks |
| [`../contracts/README.md`](../contracts/README.md) | The frozen schema, the golden document and the scope fixtures — read-only once written |
| [`../samples/README.md`](../samples/README.md) | The two shipped sample projects, written to be read and never run |

## Generated directories

None of these is hand-edited.

| Path | What it is |
|---|---|
| `docs/rules/` | Tracked in git, but written by `python analyzer/tools/gen_rule_docs.py`. Edit the rule declaration, its fixtures or `analyzer/tools/gen_rule_notes.py` and regenerate; `--check` fails when the tree disagrees, and that is a gate |
| `docs/walkthrough/` | Tracked. The five VS Code Get-Started pages, copied into the extension by `node vscode-extension/tools/sync-walkthrough.mjs`, whose `--check` is also a gate |
| `docs/gallery/` | **Not** in git. Self-contained example reports built by `python analyzer/tools/gen_gallery.py` from the clean programs and every rule fixture, ~30 MB |
| `docs/demo-logs/` | Empty in git apart from its `.gitkeep`. Where a filled-in copy of `DEMO_LOG.md` goes, one per validation session |
