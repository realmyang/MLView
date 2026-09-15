---
description: Print only the MLView issue table for a path — headless, for agent loops and PR descriptions
argument-hint: "[path] [low|medium|high] [--scope <SPEC>] [--depth <0-2>] [--group-by rule|file|severity] [--changed-since <rev>] [--baseline <file>] [--diff-base <file>]"
allowed-tools: [Bash, Read, Glob]
---

# /mlview-issues — the issue table, nothing else

Claude Code substitutes positional arguments **0-based**, so `$0` is the first
argument and `$1` the second; `$ARGUMENTS` is the whole argument string.

Target path: `$0` — when `$ARGUMENTS` is empty, use `.` (the current directory).
Minimum severity: `$1` — when it is empty, use `low`.

**Two of the tokens in `$ARGUMENTS` are never the path and never the severity:**
a token starting with `--` is a flag, and the token **immediately after
`--scope`, `--depth`, `--group-by`, `--changed-since`, `--baseline` or
`--diff-base` is that flag's value** — a flag occupies two
positional slots, so with the path omitted its value lands in `$1`. Read the two
arguments this way instead of trusting the slots blindly:

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
  `concern:<config|data|optimization|evaluation>` · `node:<nodeId>` ·
  `pipeline:<entrypoint.py>` · `all`. `symbol:` is a spelling of `unit:`, and
  `pipeline:` lists only the findings anchored inside what one entrypoint
  reaches — a finding anchored on a module two entrypoints share is reported as
  outside the view, not as this pipeline's.
- `--depth <0-2>` — boundary hops around the scope. It widens the *picture*, not
  the findings: only a node inside the scope itself can retain an issue.
- `--group-by rule|file|severity` — fold the findings into one row per rule, per
  file or per severity instead of listing them individually. `rule` is the useful
  one on an inherited repo: eleven distinct codes repeated ten times each is a
  111-row table that says the same thing twelve times. Grouping **folds** the
  rows, it never filters them, so the counts still cover every finding that
  passed the severity floor and the scope. Note that `--group-by severity` is not
  the same as no flag at all: the flat table is already ordered worst-first, and
  the grouped one replaces it with three rows.

- `--changed-since <rev>` — CI-ADOPT. Analyze the whole path as usual, then list
  only the findings that touch what changed since `<rev>` (`HEAD`, `origin/main`,
  a SHA). Each row is attributed `new` (its line is inside an added hunk) or
  `touched` (its file changed, or a related location such as the split site is
  inside a hunk); everything else is dropped and counted in the payload's `note`.
  This is the flag for "what did this PR introduce" on a repo that already has
  findings — it is **never** an answer to "is this project clean". If git is
  absent, the directory is not a repo, or the revision does not exist, every
  finding comes back and the `note` says attribution failed; report that line.
- `--baseline <file>` — the ratchet. Findings already recorded in a
  `mlview baseline write` file are marked, excluded from the counts and reported
  as `baselinedCount`, so the table shows only what is new since the baseline was
  frozen. Baseline entries that no longer match any finding are named in the
  `note` rather than silently forgiven; pass that line on, because a stale
  baseline is a permissive one.

- `--diff-base <file>` — VIEW-08. Compare this analysis against an earlier
  `mlview analyze --json` document and report which findings are **new since
  that document**. Unlike `--changed-since`, which asks git what the diff
  touched, this asks the analyzer what the GRAPH did: a finding is `new` when
  its id is absent from the base, `fixed` when it is absent from the head, and
  `persisting` when both have it. Findings still come from the normal run — the
  base only labels them — so the table is the same table with a `change` column,
  and the counts line ends with ` · N new / N fixed / N persisting since
  <file>`. **Report the comparison's own `note` verbatim before the table**: a
  `removed` node (and therefore a `fixed` finding) can also mean the base was
  truncated, projected, analysed at a different root or written by a different
  analyzer version, and a renamed file reads as everything removed plus
  everything added. `--diff-base` is never an answer to "is this project clean".

Omit all six entirely when the user did not ask for them; an unscoped, ungrouped,
unattributed, uncompared table is the default and is a statement about the whole
path.

This command is **headless**: no diagram, no browser, no prose beyond the table.
It exists so an agent loop or a PR description can consume the findings directly.

## Run it

**If the `mlview_*` MCP tools are available**, call `mlview_issues` with
`path` set to the target and `minSeverity` set to `$1` (use `"low"` when that is
empty; `minSeverity` accepts only `low`, `medium` or `high`), plus `scope`,
`depth`, `groupBy`, `changedSince` and `baseline` when the user gave them
(`changedSince` takes the revision, `baseline` the file path). `groupBy` takes the same three
words as `--group-by`; the result then carries `groups` **instead of** `issues`,
each row `{key, count, maxSeverity, worstBucket, sites}` (plus `title` and a
`files` count under `groupBy: "rule"`).

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

Append ` --scope <SPEC>` and ` --depth <N>` to either line only when the user
gave them; with none, the two lines above are exactly what runs. The two
adoption flags are spelled the same way on the CLI, and `--changed-since`
carries `--changed-only` with it:

```bash
python -m mlview issues "$0" --min-severity "$1" --changed-since origin/main --changed-only
python -m mlview issues "$0" --min-severity "$1" --baseline .mlview/baseline.json
```

`--diff-base` is served by the MCP tool `mlview_graph` with `scope: "diff"` and
`base` set to the file — **not** by `mlview_issues`, and it does not add a sixth
tool. Call `mlview_issues` for the table as usual, then `mlview_graph` for the
comparison, and read `summary.issues` = `{new, fixed, persisting}` off it. On the
`Bash` fallback, the base is whatever `analyze --json` wrote **before** the
change and the head is written now — `diff` reads two files and analyzes nothing:

```bash
python -m mlview analyze "$0" --json .mlview/base.json
python -m mlview analyze "$0" --json .mlview/head.json
python -m mlview diff .mlview/base.json .mlview/head.json
```

The first line is the one you run before the change (keep its output); the second
and third are what you run after it. If any of them exits `1`, report the message
it printed on stderr and drop the comparison rather than guessing at the counts —
exit `1` from `diff` means a missing file, a file that is not JSON, or a document
that is not an MLView graph, and none of those is "nothing changed". A scoped run
looks like this — a real selector, not a placeholder:

```bash
python -m mlview issues "$0" --min-severity "$1" --scope concern:evaluation
```

An unusable selector exits `1` with `code`, the offending term and up to ten
candidates on stderr, and prints nothing on stdout. Report that verbatim rather
than retrying with a guess.

`--group-by` is served by the MCP tool's `groupBy` argument. On the `Bash`
fallback, append ` --group-by <MODE>` to the line and use its output when the CLI
accepts the flag; if it exits `1` with an unrecognised-argument usage error,
drop the flag, re-run without it, and fold the rows into the grouped table
yourself — the counts are the same either way. Never report a usage error as a
finding.

## Output contract

Emit **only** this, and nothing before or after it:

| Code | Severity | Confidence | Location | Title |
|---|---|---|---|---|
| MLV201 | high | certain | train.py:44 | Gradients are never zeroed |

Then one final line: `N high · N medium · N low` (plus `· N suppressed` when
`suppressedCount` is non-zero, and `· N baselined` when `baselinedCount` is).
Under `--changed-since` that line ends with ` · changed since <rev>`, and a row's
`change` value (`new` / `touched`) is worth quoting when it is present: "1 new,
2 touched" is the sentence a PR description needs. When a scope was used, that line ends with
` · scope: <SPEC>` — the counts describe the scope, not the project, and the
payload's own `scope` field and `note` say so.

Under `--group-by`, emit this table instead — one row per group, worst first, and
nothing else:

| Code | Severity | Count | Files | Title |
|---|---|---|---|---|
| MLV702 | high | 10 | 10 | Random seed is never set |

(`Code` is the group's `key`, so it reads `Files` / `Severity` under
`--group-by file` / `severity`; drop the `Files` column when the payload's rows
carry no `files`.) Keep the same final counts line and append ` · grouped by
<MODE>`. A group count is a count of findings, never of groups: say "10
occurrences", never "10 issues found" when there are twelve groups.

**A single file is not a project.** When the target path is one `.py` file, four
rules (MLV301, MLV302, MLV401, MLV501) cannot fire at all, because each needs a
sibling module — measured: 3 findings for `train.py` where its directory yields 7.
The payload then carries a `coverage` row of kind `single_file_analysis`, one of
kind `untagged_dataflow` when a key argument could not be traced so the leakage
rules could not check it, and one of kind `framework_filter` when a framework
filter narrowed the rule set (`framework_suppressed` instead when the document
was cached by an older build — the same cost, stated by this host rather than by
the analyzer, and never both). When any of them appears, add one line after the table
naming the rules from that row's `codes` — quote them, do not guess — and never
present the result as a clean file; its `count` is blind spots or suppressed rule
codes, not rules that ran and found nothing. Prefer running on the containing directory and passing
` --scope file:<name>.py`: that recovers those rules and still answers about the
one file.

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
must be said that way; it is never a clean bill of health for the project. The
same applies twice over under `--changed-since`: an empty table means "this
change introduced nothing", never "this project is clean" — the payload's `note`
names how many findings were withheld, and that number belongs in the answer.

The payload's own `note` field says which case you are in; when it is present,
never emit the clean line.

Do not summarize, do not interpret, do not propose fixes, and do not edit files.
`/mlview` explains; `mlview-triage` proposes fixes; this command only reports.
