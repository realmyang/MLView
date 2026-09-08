---
description: Analyze the ML pipeline in a path and open the interactive MLView diagram
argument-hint: "[path] [--scope <SPEC>] [--depth <0-2>]"
allowed-tools: [Bash, Read, Glob]
---

# /mlview — map and audit an ML pipeline

Target path: `$0` — the **first** argument. Claude Code substitutes positional
arguments **0-based** (`$0` is the first, `$1` the second); `$ARGUMENTS` is the
whole argument string. When `$ARGUMENTS` is empty, the target is `.` (the
current directory). When `$0` starts with `--` it is a flag, not a path — the
target is `.` in that case too.

**Optional flags, read out of `$ARGUMENTS`** (never out of a positional slot,
because a flag and its value occupy two of them):

- `--scope <SPEC>` — narrow the diagram to one part of the pipeline. One
  selector, at most once. `unit:<class|function|loop>` ·
  `stage:<config|data|preprocess|model|objective|train|eval|deliver>` ·
  `file:<path.py>` · `concern:<config|data|optimization|evaluation>` ·
  `node:<nodeId>` · `all`. `symbol:` is a spelling of `unit:`.
- `--depth <0-2>` — boundary hops around the scope. Omit it for the per-kind
  default (1 for `unit`/`node`, 0 for `stage`/`file`/`concern`).

Both are optional and order-free. Anything else in `$ARGUMENTS` is passed
through unchanged. If no `--scope` was given, **do not invent one** — omit the
argument entirely and analyze the whole project.

MLView reads Python source statically. It never imports or runs the user's code,
and it does not need torch or scikit-learn to be installed.

**A single file is not a project.** If the target is one `.py` file, say so in the
answer: MLV301, MLV302, MLV401 and MLV501 each need a sibling module and cannot
fire on a lone file — measured, `train.py` alone yields 3 findings where its own
directory yields 7. The payload carries a `single_file_analysis` diagnostic naming
the rules that could not run, and `untagged_dataflow` when a key argument could not
be traced so the leakage rules could not check it. Repeat those caveats; a shorter
list from a narrower run is not a cleaner project. The better move is to analyze
the **directory** and pass `--scope file:<name>.py`, which recovers the cross-file
rules and still answers about that one file.

## Step 1 — analyze

**If the `mlview_*` MCP tools are available**, prefer them; they are in-process,
cheaper, and return a bounded digest:

1. `mlview_analyze` with `path` set to the target (omit it for the whole
   project), plus `scope` and `depth` when the user gave them.
2. `mlview_open_diagram` with the same `path`, `scope` and `depth`, to write and
   open the report. The report always embeds the **whole** graph and merely
   *opens at* the scope, so the user can widen it in the toolbar.

If the user named a part of the pipeline in words rather than a selector —
"the train/test split", "the evaluation path", "SmallCNN" — call
`mlview_graph` with `scope: "units"` first. That is the catalogue of the
**container** units (`nodeId`, `label`, `qualname`, `file`, `line`, `nodeCount`,
`maxSeverity`), biggest unit first, and it costs no extra analysis. It is a menu
rather than the full set of legal targets: a call site such as
`unit:train_test_split` is an `op` and never appears in it, and rows are dropped
when the payload's `note` says the menu is INCOMPLETE. When the row you want is
missing, name the unit anyway — an unresolvable `unit:` target comes back as an
empty result with a note, not an error.

**Otherwise** (the MCP server did not register — this fallback is why the demo
never depends on that), run the CLI through `Bash`:

```bash
python -m mlview analyze "$0" --json .mlview/graph.json --html .mlview/report.html --open --format summary
```

Append ` --scope <SPEC>` and ` --depth <N>` to that line **only** when the user
gave them; with no scope the command is exactly the line above, unchanged. A
scoped run looks like this (a real selector, not a placeholder):

```bash
python -m mlview analyze "$0" --scope concern:evaluation --depth 1 --html .mlview/report.html --format summary
```

To discover the scopable units from the CLI instead:

```bash
python -m mlview analyze "$0" --list-scopes
```

The `$0` above is already substituted with the first argument by the time you
read this. If it came out empty (`analyze ""`), or if a literal `$0` is still
showing, no path was given — run the command with `.` instead. Never pass an
empty path: it is a usage error, not "the whole project".

Exit codes: `0` fine, `1` usage or I/O (including an unusable `--scope`, whose
stderr names the code, the offending term and up to ten candidates), `2`
`--fail-on` threshold, `3` internal error, `4` nothing analyzable (no `.py`
files after filtering — say so plainly rather than retrying).

## Step 2 — report back

Tell the user, in this order and no longer than a short paragraph plus a table:

1. **Shape** — how many files were analyzed, which frameworks were detected, and
   which stages exist (`config → data → preprocess → model → objective → train →
   eval → deliver`). Name the stages that were *not* detected; an absent
   `eval` lane is itself a finding. Take that list from `mlview_analyze`'s
   `lanes` or from `mlview_graph` with `scope: "stages"` — **every other scope is
   a filtered view**. `stage:train`, `unit:SmallCNN`, `file:data.py`,
   `concern:evaluation` and `node:<id>` all return counts that describe the
   *scope*, and each says so in its `note`; none of them is a statement about
   which stages the project has. `scope: "units"` is a catalogue, not a lane
   summary. When you used a scope, say which one, in the same sentence as the
   counts.
   If `filesAnalyzed` is 0, or `filesFailed` is above 0, say that first: an empty
   finding list from a path with no parsable Python is not a clean result. The
   same goes for a `single_file_analysis` or `untagged_dataflow` entry in
   `diagnostics`: name the rules that could not run before you report the count.
2. **Findings** — the issues, worst first, each as `MLVxxx · severity · file:line ·
   title`. Quote the rule's own message; it already cites the variable names and
   line numbers. Under a scope these are the findings **anchored inside** it;
   `graphPath` still holds the full document, so offer to widen.
3. **Where to look** — the report path (`.mlview/report.html`) and the graph
   document (`.mlview/graph.json`). Mention that hovering a connection in the
   report animates the value travelling from its outlet to its inlet, and that
   the toolbar's scope picker narrows the picture without re-analyzing.

## Step 3 — offer, do not act

Offer to explain any single finding (`mlview_explain` with its `code`, or
`python -m mlview explain MLV201`) or to walk one node (`mlview_explain` with its
`nodeId`). **Do not edit any file.** Fixing is a separate, explicit request.

If a finding looks wrong, say so — the confidence bucket (`certain`, `likely`,
`possible`, `speculative`) is on every issue, and a `dynamic: true` scope means
the analyzer knew it was guessing.
