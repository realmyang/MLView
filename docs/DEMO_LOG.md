# DEMO LOG — template

Copy this file, fill it in **while you validate**, and keep it with the run:

```sh
cp docs/DEMO_LOG.md docs/demo-logs/<date>-<machine>.md
mkdir -p docs/demo-logs/screenshots
```

The checks below are the ones in `docs/VALIDATION.md` Part 2. One row each:
`pass`, `fail`, `skip` (with why) or `n/a`. A **fail** row must say what you
did, what happened and what you expected — in the Note column or in a numbered
paragraph under "Failures in full" at the bottom. Screenshots live in
`screenshots/` beside this file and are named by check id
(`screenshots/A10-png-export.png`); a screenshot nothing references is not
evidence.

---

## Environment

| | |
|---|---|
| Date | |
| Who | |
| OS and version | |
| Python (`python -V`) | |
| Node (`node -v`) | |
| VS Code version | |
| GitHub Copilot | installed / not installed — version |
| Claude Code CLI version | |
| MLView commit (`git rev-parse --short HEAD`) | |
| Repo analyzed | name, rough size (files / LOC), framework |

## Build

| Step | Result | Note |
|---|---|---|
| `pip install -e analyzer` | | |
| `scripts/build.sh` / `build.ps1` | | BUILD OK, 6/6 steps? |
| `scripts/e2e.sh` / `e2e.ps1` | | 20 steps — how many passed / failed / skipped |
| Wall time for the e2e run | | |

---

## Session A · VS Code (and Copilot)

| # | Check | Result | Note |
|---|---|---|---|
| A1 | Visualize ML Workflow (Workspace) on my own project | | seconds to first paint, node count |
| A2 | Problems panel: findings, codes, related locations | | count, and were any obviously wrong |
| A3 | Click a node → correct file and range | | |
| A4 | Click an **edge** → the call site, not an endpoint | | |
| A5 | Hover a connection / a node → flow animation | | animated or reduced-motion static? |
| A6 | `Alt+M` reveals the symbol under the cursor | | |
| A7 | `Alt+Shift+M` scopes; breadcrumb says `N of M` with M the project size | | |
| A8 | Scope picker; `stage:`/`concern:`; `[` `]` depth; Problems panel unchanged | | |
| A9 | Lightbulb: ignore comment, disable rule, fix preview | | which rules offered a fix |
| A10 | Export Diagram as SVG, then as PNG | | does the file match the panel |
| A11 | Open MLView Configuration; disable a rule; re-analyze | | |
| A12 | Save Comparison Base → change code → Compare With Saved Base | | |
| A13 | Copilot Chat: `@mlview /issues`, `/diagram`, `/explain MLV101` | | paste the answer |
| A14 | Copilot agent mode: `#mlviewAnalyze`, `#mlviewIssues`, `#mlviewDiagram` | | paste the prompt and the answer |
| A15 | `Help → Get Started` walkthrough, all five steps | | |

**Judgement calls** (no right answer — say what you saw):

- Was the first screen readable without zooming or collapsing anything?
- Did the diagram claim anything you know to be false about your code?
- Did anything take long enough to be annoying? How long?

## Session B · The standalone report

| # | Check | Result | Note |
|---|---|---|---|
| B1 | Report opens offline, zero network requests | | |
| B2 | Copy path / `vscode://file/...` link points at the right place | | |
| B3 | Answer Card: four sentences, honest verdict | | paste it |
| B4 | Issue rail ranked; suppressed findings collapsed, not dropped | | |
| B5 | Light and dark theme; legend and `?` shortcut sheet open; **Escape closes whichever is open** | | |
| B6 | `--format summary`; stdout carries only the payload | | `analyze . --format json > g.json` parses? |

## Session C · Claude Code

| # | Check | Result | Note |
|---|---|---|---|
| C1 | `/mlview <project>` | | |
| C2 | `/mlview-issues <project> high` | | |
| C3 | `/mlview-issues <project> --group-by rule` | | |
| C4 | `/mlview <project> --scope concern:evaluation --depth 1` | | did it say it was scoped |
| C5 | `mlview_open_diagram` returns a report path, claims no image export | | |
| C6 | `PostToolUse` hook speaks after a **second** edit that adds a finding | | what it said |
| C7 | Windows without Git Bash: hook silent, session unaffected | | n/a elsewhere |
| C8 | `/plugin marketplace add` → install → five tools present | | |

---

## Failures in full

> One numbered paragraph per failed check: **what I did**, **what happened**,
> **what I expected**, and the screenshot file name if there is one. Copy each
> of these into its own GitHub issue titled with the check id.

1.

## Anything else

> Surprises, rough edges, things that were better than expected, and anything
> the checks above did not ask about. This section is usually the most useful
> part of the log.
