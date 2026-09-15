# DEMO LOG — template

Copy this file, fill it in **while you validate**, and keep it with the run:

```sh
mkdir -p docs/demo-logs/screenshots
cp docs/DEMO_LOG.md "docs/demo-logs/$(date +%F)-<your-machine>.md"
```

```powershell
# Windows, PowerShell
New-Item -ItemType Directory -Force docs/demo-logs/screenshots | Out-Null
Copy-Item docs/DEMO_LOG.md "docs/demo-logs/$(Get-Date -Format yyyy-MM-dd)-<your-machine>.md"
```

The `mkdir` comes first: a fresh clone carries `docs/demo-logs/.gitkeep` and
nothing else, and `screenshots/` is not there at all.

The checks below are the ones in [`docs/VALIDATION.md`](VALIDATION.md) Part 2.
One row each: `pass`, `fail`, `skip` (with why) or `n/a`. A **fail** row must say
what you did, what happened and what you expected — in the Note column or in a
numbered paragraph under "Failures in full" at the bottom. Screenshots live in
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
| `mcp` SDK version (`pip show mcp`) | |
| MLView commit (`git rev-parse --short HEAD`) | |
| Repo analyzed | name, rough size (files / LOC), framework |

## Build

| Step | Result | Note |
|---|---|---|
| `pip install -e analyzer` | | |
| `scripts/build.sh` / `build.ps1` | | BUILD OK, 6/6 steps? |
| `scripts/e2e.sh` / `e2e.ps1` | | 20 steps — how many passed / failed / skipped |
| Wall time for the e2e run | | |
| `python tools/verify.py --all` | | 10 of 10? |
| `python tools/accuracy.py` | | PASS, and the precision / recall it printed |

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
| A8 | Scope picker; `stage:`/`concern:`; `[` `]` depth; row count == what the click draws; Problems panel unchanged | | |
| A9 | Lightbulb: ignore comment, disable rule, fix preview | | which rules offered a fix |
| A10 | Export Diagram as SVG, then as PNG | | does the file match the panel |
| A11 | Open MLView Configuration; disable a rule; re-analyze | | |
| A12 | Save Comparison Base → change code → Compare With Saved Base | | |
| A13 | Coverage chip / banner is present iff the run was blind | | paste what it said, or "no chip" |
| A14 | Copilot Chat: `@mlview /issues`, `/diagram`, `/explain MLV101` | | paste the answer |
| A15 | Copilot agent mode: `#mlviewAnalyze`, `#mlviewIssues`, `#mlviewDiagram` | | paste the prompt and the answer |
| A16 | `Help → Get Started` walkthrough, all five steps | | |

**Judgement calls** (no right answer — say what you saw):

- Was the first screen readable without zooming or collapsing anything?
- Did the diagram claim anything you know to be false about your code?
- Did anything take long enough to be annoying? How long?

## Session B · The standalone report

| # | Check | Result | Note |
|---|---|---|---|
| B1 | Report opens offline, zero network requests | | |
| B2 | "Go to `file:line`" on a **local** report: VS Code jumps, **or** the toast says the launch was refused and offers *Open in VS Code* — **and the keyboard still works after that click** | | which of the two; press `?` and an arrow key afterwards |
| B3 | Answer Card: four sentences, honest verdict | | paste it |
| B4 | Issue rail ranked; suppressed findings collapsed, not dropped; a clean state after a blind run repeats the caveat | | |
| B5 | Light and dark theme; legend and `?` shortcut sheet open; **Escape closes whichever is open** | | |
| B6 | `--format summary`; stdout carries only the payload | | `analyze . --format json > g.json` parses? |
| B7 | No new directory inside the analyzed repo after two runs | | `git status` in your repo; where did the cache go? |

## Session C · Claude Code

| # | Check | Result | Note |
|---|---|---|---|
| C0 | The five `mlview_*` tools are listed at session start | | if not, read the server's stderr — C1+ all fail for that one reason |
| C1 | `/mlview <project>` | | |
| C2 | `/mlview-issues <project> high` | | |
| C3 | `/mlview-issues <project> --group-by rule` | | |
| C4 | `/mlview <project> --scope concern:evaluation --depth 1` | | did it say it was scoped |
| C5 | `framework: "torch"` on a non-torch project names the suppressed rules, from the `coverage` row of kind **`framework_filter`** | | paste the sentence; the `framework_suppressed` tally entry is the same cost stated twice, never a second one |
| C6 | `mlview_open_diagram` returns a report path, claims no image export | | |
| C7 | `PostToolUse` hook speaks after a **second** edit that adds a finding | | what it said |
| C8 | No stray `.mlview/` in the analyzed repo after the session | | `git status` in your repo |
| C9 | Windows without Git Bash: a **visible** hook error notice, not silence | | paste the text; n/a elsewhere |
| C10 | `/plugin marketplace add` → install → five tools present | | which entry (`mlview` or `mlview-github`) |

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
