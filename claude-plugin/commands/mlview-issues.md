---
description: Print only the MLView issue table for a path — headless, for agent loops and PR descriptions
argument-hint: "[path] [low|medium|high] [--scope <SPEC>] [--depth <0-2>]"
allowed-tools: [Bash, Read, Glob]
---

# /mlview-issues — the issue table, nothing else

Claude Code substitutes positional arguments **0-based**, so `$0` is the first
argument and `$1` the second; `$ARGUMENTS` is the whole argument string.

Target path: `$0` — when `$ARGUMENTS` is empty, use `.` (the current directory).
Minimum severity: `$1` — when it is empty, use `low`.

**Two of the tokens in `$ARGUMENTS` are never the path and never the severity:**
a token starting with `--` is a flag, and the token **immediately after
`--scope` or `--depth` is that flag's value** — a flag occupies two positional
slots, so with the path omitted its value lands in `$1`. Read the two arguments
this way instead of trusting the slots blindly:

- discard every flag and every flag value from `$ARGUMENTS`;
- of what is left, a token spelled exactly `low`, `medium` or `high` is the
  minimum severity, and the other one is the path;
- no path token left → `.`; no severity token left, or it is not one of those
  three words → `low`.

With no flags given that is exactly `$0` and `$1`. So `/mlview-issues --scope
stage:train` runs on `.` at severity `low` — **not** on `.` at severity
`stage:train`, which the CLI and `minSeverity` both reject outright.

**Optional flags, read out of `$ARGUMENTS`** (never out of a positional slot,
because a flag and its value occupy two of them):

- `--scope <SPEC>` — list only the findings anchored inside one part of the
  pipeline. One selector, at most once: `unit:<class|function|loop>` ·
  `stage:<id>` · `file:<path.py>` ·
  `concern:<config|data|optimization|evaluation>` · `node:<nodeId>` · `all`.
- `--depth <0-2>` — boundary hops around the scope. It widens the *picture*, not
  the findings: only a node inside the scope itself can retain an issue.

Omit both entirely when the user did not ask for them; an unscoped table is the
default and is a statement about the whole path.

This command is **headless**: no diagram, no browser, no prose beyond the table.
It exists so an agent loop or a PR description can consume the findings directly.

## Run it

**If the `mlview_*` MCP tools are available**, call `mlview_issues` with
`path` set to the target and `minSeverity` set to `$1` (use `"low"` when that is
empty; `minSeverity` accepts only `low`, `medium` or `high`), plus `scope` and
`depth` when the user gave them.

**Otherwise**, through `Bash`:

```bash
python -m mlview analyze "$0" --format summary --min-severity "$1"
```

Both placeholders are substituted before you read this. Substitute `.` for the
path and `low` for the severity when the corresponding argument came out empty,
is still showing as a literal `$0` / `$1`, or was ruled out above as a flag or a
flag's value. `--min-severity ""` is **not** a
valid value — the CLI accepts only `low`, `medium` and `high` — and an empty path
is a usage error rather than "the whole project".

For a machine-readable list instead of the table:

```bash
python -m mlview issues "$0" --json --min-severity "$1"
```

Append ` --scope <SPEC>` (and ` --depth <N>`) to either line only when the user
gave a scope; with none, the two lines above are exactly what runs. A scoped run
looks like this — a real selector, not a placeholder:

```bash
python -m mlview issues "$0" --min-severity "$1" --scope concern:evaluation
```

An unusable selector exits `1` with `code`, the offending term and up to ten
candidates on stderr, and prints nothing on stdout. Report that verbatim rather
than retrying with a guess.

## Output contract

Emit **only** this, and nothing before or after it:

| Code | Severity | Confidence | Location | Title |
|---|---|---|---|---|
| MLV201 | high | certain | train.py:44 | Gradients are never zeroed |

Then one final line: `N high · N medium · N low` (plus `· N suppressed` when
`suppressedCount` is non-zero). When a scope was used, that line ends with
` · scope: <SPEC>` — the counts describe the scope, not the project, and the
payload's own `scope` field and `note` say so.

If there are no issues at or above the threshold, first check `filesAnalyzed`
and `filesFailed` in the payload — "no issues" and "nothing was analyzed" are
different answers and only one of them is good news:

- `filesAnalyzed > 0` and `filesFailed == 0` — emit exactly:
  `No MLView issues at or above <severity>.`
- `filesAnalyzed == 0` — emit exactly:
  `No analyzable Python at <path> — this is not a clean result.`
- `filesFailed > 0` — emit the table (it may be empty) and then exactly:
  `<N> file(s) failed to parse; their issues are missing from this table.`

Under a `--scope`, a clean table means "nothing was found **in this scope**" and
must be said that way; it is never a clean bill of health for the project.

The payload's own `note` field says which case you are in; when it is present,
never emit the clean line.

Do not summarize, do not interpret, do not propose fixes, and do not edit files.
`/mlview` explains; `mlview-triage` proposes fixes; this command only reports.
