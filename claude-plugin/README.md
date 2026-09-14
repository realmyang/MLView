# MLView — the Claude Code plugin

Turns a Python ML codebase into an issue-annotated workflow diagram, from inside
Claude Code. Static analysis only: nothing is imported, nothing is executed, and
**torch and scikit-learn do not need to be installed**.

```
claude-plugin/
  .claude-plugin/plugin.json   the manifest (this path is the only one scanned)
  .mcp.json                    the stdio MCP server registration
  commands/                    /mlview · /mlview-issues
  skills/                      mlview-visualize · mlview-triage
  server/mlview_mcp.py         the MCP server: bootstrap + the five tools
  server/mlview_workspace.py   path resolution, write containment, analysis cache
  server/mlview_payloads.py    the pure payload builders
  server/mlview_views.py       filtered graph views and their rendered shapes
  server/mlview_budget.py      the 4 KB budget (measured on the SDK's encoding)
  vendor/mlview/               a synced copy of the analyzer core
  docs/rules/MLVxxx.md         the rule pages mlview_explain serves (synced)
  tests/                       stdio handshake · payload budget · manifests
```

## Prerequisites

- **Python 3.10 or newer** on `PATH` as `python`. That is all the CLI fallback
  needs. On macOS and Linux the interpreter is usually `python3`, and `.mcp.json`
  spells `python` — see [Troubleshooting](#troubleshooting-on-windows-and-posix)
  below for the one-field edit.
- **`pip install mcp`** (v2; verified against `mcp==2.1.1`) for the MCP tools.
  Without it the five `mlview_*` tools are unavailable — the server fails to
  start — but `/mlview` and `/mlview-issues` still work, because both command
  bodies fall back to running the CLI through `Bash`. The demo never depends on
  MCP registration succeeding.
- **No `pip install` of MLView itself.** `.mcp.json` puts
  `${CLAUDE_PLUGIN_ROOT}/vendor` on `PYTHONPATH`, and `vendor/mlview` is a synced
  copy of the analyzer. The same command also copies `docs/rules/MLV*.md` into
  `claude-plugin/docs/rules/`, which is where `mlview_explain(code=…)` finds a
  rule page once the plugin is installed. Refresh both after changing the
  analyzer or a rule doc:

  ```bash
  python tools/sync-core.py          # from the repo root
  python tools/sync-core.py --check  # verify, exit 1 on drift
  python tools/verify.py --docs      # the same check as a gate row
  ```

  The server prepends **exactly one** core to `sys.path`: `vendor/` when it holds
  an `mlview` package, and `<repo>/analyzer/src` only as a dev fallback when it
  does not. Prepending both would put an editable checkout ahead of the vendored
  copy and make the vendor gates vacuous.

## Install

Validate first, always:

```bash
claude plugin validate ./claude-plugin --strict
```

Then pick one:

**1. Session-only, zero install** (what the demo uses)

```bash
claude --plugin-dir C:/absolute/path/to/MLView/claude-plugin
```

**2. Through the repo-root local marketplace**

```
/plugin marketplace add ./
/plugin install mlview@mlview-local
```

`.claude-plugin/marketplace.json` at the repo root declares the marketplace
`mlview-local` with one entry pointing at `./claude-plugin`.

**3. The MCP server only, without the commands and skills**

```bash
claude mcp add mlview -- python C:/absolute/path/to/MLView/claude-plugin/server/mlview_mcp.py
```

Set `PYTHONPATH` to the plugin's `vendor/` directory yourself in this mode, or
`pip install -e analyzer` first.

## What you get

### Commands

| Command | What it does |
|---|---|
| `/mlview [path] [--scope <SPEC>] [--depth <0-2>]` | Analyze, summarize the pipeline shape and findings, and open the HTML report. Prefers the MCP tools; falls back to `python -m mlview analyze … --open`. With no `--scope` the fallback command line is exactly what it was before scoping existed. |
| `/mlview-issues [path] [severity] [--scope <SPEC>] [--depth <0-2>]` | Headless: the issue table and nothing else, for agent loops and PR descriptions. |

Positional arguments are **0-based** (`$0` is the path, `$1` the severity); the
two flags are read out of `$ARGUMENTS`, because a flag and its value occupy two
positional slots between them.

### Skills

| Skill | Triggers on | Behaviour |
|---|---|---|
| `mlview-visualize` | "visualize / diagram / map / review the structure of this ML code" | Calls `mlview_analyze` **before** reading files, so the review starts from recovered structure rather than a linear read. Its **"When to scope"** section decides when to narrow: a question about one concern gets a scoped call, *"review this project"* gets none. |
| `mlview-triage` | "what's wrong with this training code", "is there leakage" | Reads the cited source, judges each finding, proposes a fix. **Never edits a file.** |

### MCP tools

All five return a plain dict of **at most 4096 bytes**; the complete document
always stays on disk behind `graphPath`.

| Tool | Input | Returns |
|---|---|---|
| `mlview_analyze` | `path?`, `framework?`, `maxNodes?`, `includeHtml?`, `scope?`, `depth?` | The digest: files, frameworks, stage lanes, node/edge/issue counts, up to 10 top issues, `graphPath`, `reportPath?`; with a scope, also `scope{spec,kind,target,depth,nodesInScope,nodesTotal}` |
| `mlview_issues` | `path?`, `minSeverity?`, `minConfidence?`, `code?[]`, `limit?`, `scope?`, `depth?`, `groupBy?`, `changedSince?`, `baseline?` | `countBySeverity`, `suppressedCount`, and the issue rows with `file`, `line`, `fixHint` and related sites. A scope keeps only the findings **anchored inside** it. `changedSince` (a git revision) analyses the whole project and then lists only what the change touched, each row carrying `change: new\|touched`; `baseline` marks what a `mlview baseline write` file already records and returns `baselinedCount`. Both degrade to *"every finding, and here is why"* — never to an empty list |
| `mlview_graph` | `path?`, `format?`, `scope?`, `depth?`, `base?` | `{format, scope, content}` — **mermaid by default**. Two catalogue values, `"stages"` (the lane summary) and `"units"` (the scopable-unit menu), plus the whole selector grammar below — and `scope: "diff"` with `base`, which compares this analysis against an earlier document instead of drawing one |
| `mlview_explain` | `nodeId?` **or** `code?`, `path?`, `graphPath?` | A node with its edges, issues, stage evidence and ≤ 60 lines of real source; or a rule code's documentation |
| `mlview_open_diagram` | `path?`, `graphPath?`, `out?`, `scope?`, `depth?` | `{reportPath, reportUrl, opened}` — writes the self-contained HTML and launches it. `out` must stay inside the project directory or `MLVIEW_DATA_DIR` |

**Still exactly five tools.** Scoping is an argument, not a sixth tool,
discovery is the `"units"` value of an argument that already existed, and
VIEW-08's comparison is a `"diff"` value of the same one — a diff is another
projection of the same graph, which is why it did not earn a tool of its own.

#### The `scope` grammar

| Value | Selects |
|---|---|
| *(omitted)* or `"all"` | the whole graph — the bytes are what they were before this feature existed |
| `"stages"` | one row per stage lane. **The only project-wide lane statement** |
| `"units"` | the catalogue: one row per **container** unit — class, function or loop — as `{nodeId, label, qualname, file, line, nodeCount, maxSeverity}`, sorted `(-nodeCount, file, line, qualname)` and shed to fit 4 KB. Call it to discover a name instead of guessing one. It is a **menu, not the set of legal targets**: `op`-level call sites (`unit:train_test_split`) resolve but are never listed, and when rows are shed the payload's `note` says how many of how many are showing and points at `--list-scopes`, which has no budget |
| `"stage:<id>"` | one lane: `config`, `data`, `preprocess`, `model`, `objective`, `train`, `eval`, `deliver` |
| `"unit:<name>"` | one class, function or loop — a qualname (`train.train`), a bare name (`SmallCNN`), or a node id. Resolves to *every* match and says when it was ambiguous |
| `"file:<path.py>"` | everything found in one file (workspace-relative, forward slashes, or a bare basename) |
| `"concern:<name>"` | `config` · `data` · `optimization` · `evaluation` — four presets that partition the eight stages. Aliases: `setup`, `preprocessing`, `dataset`, `training`, `inference` |
| `"node:<nodeId>"` | one node and its neighbourhood |
| `"symbol:<name>"` | an alias for `unit:<name>` |
| `"diff"` | **VIEW-08 — not a diagram.** Compares this analysis against the `base` document and returns `{summary{headline, nodes, edges, issues}, content, note, basePath}`, where `content` is the `mlview diff` summary and `issues` is `{new, fixed, persisting}`. `format` and `depth` are ignored. Requires `base`; a `base` that is not an MLView graph — a diff overlay included — is an **error naming the file**, never an empty comparison, because *"0 changes"* is the most dangerous wrong answer this projection can give |

The comparison itself is the **analyzer's** (`mlview.core.diff`, CONTRACTS
§11.38) — this server computes none of it, so the report, the editor and the
plugin cannot disagree about what changed. Its caveats ride the payload's
protected `note` key and are therefore never shed by the 4 KB budget: a `removed`
node can also mean not-analyzed, truncated, projected away, a different workspace
root or a different analyzer version, and a **renamed** file is reported as every
node removed plus every node added, because the §0 stable id embeds the path. Read
the `note` before quoting the counts; `/mlview-issues --diff-base <file>` is the
slash-command spelling of the same thing.

`depth` is `0`, `1` or `2` boundary hops, its own argument and never packed into
the selector. Omit it for the per-kind default — 1 for `unit`/`node` (a point,
so its interface is the answer), 0 for `stage`/`file`/`concern` (already a
region). A value outside the range is clamped and reported in the payload's
`note` ("depth=3 is above the maximum 2; 2 was used"), never applied silently —
and never rejected either. **This is the one place the tool boundary answers
differently from the CLI**, which exits `1` with the CONTRACTS 11.1 `bad_depth`
error: a model that guesses `depth: 3` recovers better from a disclosed clamp
than from a usage error. The divergence is deliberate, pinned by
`tests/test_scope_discovery.py`, and filed as a contract change request against
11.1 / 11.10 rather than left as an accident.

An unusable selector is an **error naming every accepted value**, never a silent
fall back to the whole graph — including a stage id outside the eight, a concern
outside the four, and a node id this graph does not contain.

**A scoped result says it is scoped.** It carries `scope` and a `note` stating
that its counts describe the scope rather than the project, and the digest's
`nodesInScope` / `nodesTotal` make the project's real size impossible to lose.
**The analysis cache is never keyed on the scope**: `load_graph` still caches on
`(path, framework, maxNodes, signature)`, the projection is applied to the cached
document, and `graphPath` keeps pointing at the **full** one — so widening back
costs no re-analysis. The projection itself is `mlview.core.project`, the same
code the CLI and the report's TypeScript port are gated against
(`python tools/verify.py --scopes`).

**What the tool surface deliberately will not do.** The caller is a language model
that has been reading untrusted third-party source, so two inputs are constrained
rather than trusted:

- `mlview_open_diagram`'s `out` is resolved and then checked against the project
  directory and `MLVIEW_DATA_DIR`. A `../` traversal or an unrelated absolute path
  is refused with an error naming the permitted roots — the file it writes is
  one self-contained HTML report with the whole viewer bundle inlined (amendment
  A4's contracted 100 KB – 2 MB band; `scripts/e2e` measures it) and, without
  `MLVIEW_NO_OPEN=1`, is handed to `os.startfile`.
- `mlview_explain(code=…)` reads its rule page only from the plugin's own
  `docs/rules/` (then the repo's, for a checkout). The directory *under analysis*
  is never searched: a repository that could plant `docs/rules/MLV201.md` would
  otherwise define what MLView's rules mean about it, and `mlview-triage` tells
  the model to weigh that page against its own judgement of the finding.

**"0 issues" is never reported bare.** `mlview_issues` and `mlview_analyze` both
carry `filesAnalyzed`, `filesFailed` and a `diagnostics` tally, plus a `note` when
nothing was analyzable or a file failed to parse — so an empty directory and a
directory of syntax errors cannot be mistaken for clean code.

**How the tools work.** The server imports `mlview.api` in-process rather than
shelling out to itself, so MCP and CLI argument handling cannot diverge;
`tools/verify.py --parity` proves the two documents are byte-identical anyway.
Each analysis is cached per `(resolved path, signature of every .py file's mtime
and size)` and written to `<project>/.mlview/graph.json`, so repeated tool calls
in one conversation re-analyze nothing. The `.sig` sidecar that lets a *later*
process reuse that file also records `analyzer_identity()` — the core's version,
its renderer hash and a digest of every `.py` in the imported `mlview` package —
because a file outlives the build that wrote it, and a graph from an older
analyzer is not a cheaper answer, it is a wrong one. `tools/verify.py --parity`
runs the server twice over one data directory, doctoring the cache in between, to
keep that true. Every log line goes to **stderr** —
stdout carries protocol frames only.

### Hooks (H8)

`hooks/hooks.json` registers two hooks. They exist because the rest of the plugin is
**pull-based**: when Claude edits a training file during a session nothing tells it the
edit introduced MLV203, and the user finds out on the next manual `/mlview-issues`.

| Event | Script | What it does |
|---|---|---|
| `PostToolUse` on `Edit\|Write\|NotebookEdit` | `hooks/post_edit.py` | Re-analyzes and adds one bounded `additionalContext` **only when the edit added a finding** |
| `Stop` | `hooks/stop_summary.py` | The same diff, once per turn, for teams that prefer one summary to one line per edit |

**The discipline is the feature.** A hook that speaks on every edit gets turned off within
a day, so:

- it exits 0 **immediately** unless the edited path is a `.py` under `CLAUDE_PROJECT_DIR`
  (or an `.ipynb` when `MLVIEW_INCLUDE_NOTEBOOKS=1`, or `[paths] notebooks = true` is set
  in the project's configuration);
- it re-analyzes through the **same `load_graph` cache the MCP tools read**, sharing
  `MLVIEW_DATA_DIR` for the graph document *and* `<MLVIEW_DATA_DIR>/cache` for the
  per-file parse cache (both halves call `mlview_workspace.cache_dir()`), so the hook
  *warms* the cache those tools then read for free;
- it diffs the issue-id set against the previous run and speaks **only when the set grew**,
  at most **5 rows**, worst severity first;
- it gives up after a **3-second** wall clock and exits 0 in silence;
- it **never blocks** (a hook blocks by exiting 2; these never do) and **never writes into
  the project** — with nothing naming `MLVIEW_DATA_DIR` it redirects both the document and
  the parse cache to a temporary directory rather than creating `<project>/.mlview`;
- the **first** run on a project is silent by construction: there is nothing to diff
  against, and its whole value is the warm cache.

`MLVIEW_HOOK` decides which of the two speaks: unset or `on` is the PostToolUse hook alone,
`stop` is the turn summary alone, `both` is both, and **`off` disables them entirely**. An
unrecognized value is the default rather than an error.

Two things it cannot do, stated rather than discovered: an issue id is content-addressed,
so an unchanged finding whose line moved comes back with a new id — those are counted
("*3 existing finding(s) moved line and are not repeated here*") instead of printed as
new; and the command is the shell form `${MLVIEW_PYTHON:-python} "${CLAUDE_PLUGIN_ROOT}/…"`,
which on Windows *without* Git Bash is PowerShell and will not expand, so the hook does
nothing there. It fails silently and never blocks, which is the intended degradation —
set `MLVIEW_PYTHON` and use a bash-capable shell to get it back.

### Environment

| Variable | Meaning |
|---|---|
| `MLVIEW_PROJECT_DIR` | The project root. Relative `path` arguments resolve against it. Defaults to the process working directory. |
| `MLVIEW_DATA_DIR` | Where `graph.json` and `report.html` are written. Defaults to `<project>/.mlview`. |
| `MLVIEW_NO_OPEN=1` | `mlview_open_diagram` writes the report but does not launch a browser (`opened: false`). Used by the tests and by `scripts/e2e`. |
| `MLVIEW_HOOK` | H8: which hook speaks — unset/`on` (PostToolUse), `stop`, `both`, or `off`. |
| `MLVIEW_INCLUDE_NOTEBOOKS=1` | H8: treat an `.ipynb` edit as worth re-analyzing for. |
| `MLVIEW_CACHE_DIR` | The per-file parse cache (CONTRACTS 11.28), which ships **on** (11.39). The server *and* the hooks default it to `<MLVIEW_DATA_DIR>/cache` — one shared directory, and nothing written into the project. `.mcp.json` names it explicitly as `${CLAUDE_PLUGIN_DATA}/cache`. |
| `MLVIEW_LOG_LEVEL` | `DEBUG` for verbose stderr logging. |

## Tests

```bash
PYTHONUTF8=1 python -m pytest claude-plugin/tests -q
```

- `test_scope_grammar.py` — the section 11.1 selector grammar at this boundary:
  the `"units"` catalogue's row shape, sort order and 4 KB budget (in-process on a
  500-node graph, and over the wire in the indented encoding the model reads); a
  scoped digest's `scope` block; an unusable selector naming every accepted value
  as a visible `ToolError`; and **CLI-vs-MCP parity on three selectors** — the CLI
  running `analyzer/src`, the server running `vendor/`, both asked to project
  `stage:train`, `unit:train.train` and `concern:evaluation` and required to agree
  on the node, edge and issue counts. It also pins the cache obligation: three
  scoped calls write **one** graph document, and that document carries no `view`.
- `test_mcp.py` — spawns the server as a real subprocess with `PYTHONPATH`
  pointing **only** at `vendor/`, so it also proves the vendored core is complete
  (the server prepends one core, vendor first, so nothing else can shadow it).
  Asserts exactly the five tool names, usable input schemas, and ≤ 4 KB results
  **for the `content` text as well as `structuredContent`** — the SDK renders the
  text block with `indent=2`, which is ~27% larger than the compact encoding.
- `test_server_bootstrap.py` — the vendored core really is the one imported, and
  a project-supplied `docs/rules/` page never reaches `mlview_explain`.
- `test_out_containment.py` — `../` traversal, an absolute path and a UNC path are
  all refused by `mlview_open_diagram`.
- `test_digest_budget.py` — a 500-node / 800-edge / 300-issue synthetic graph
  through every payload builder.
- `test_plugin_manifest.py` — manifest shapes, plus `claude plugin validate
  ./claude-plugin --strict` when the CLI is on `PATH`.

## Troubleshooting on Windows and POSIX

**The `mlview_*` tools do not appear.** Run `/mcp` in Claude Code. If `mlview`
is not listed, start the server by hand and read the stderr:

```bash
set PYTHONPATH=C:\path\to\MLView\claude-plugin\vendor
python C:\path\to\MLView\claude-plugin\server\mlview_mcp.py
```

It should print `MLView MCP server 0.1.0 starting (core from vendor, …)` and then
block waiting for frames. `ModuleNotFoundError: mcp` means `pip install mcp`;
`ModuleNotFoundError: mlview` means `python tools/sync-core.py`.

**`python` is not on PATH, or it is a Python 2.** `.mcp.json` spells the command
`${MLVIEW_PYTHON:-python}`, and JSON has no comments, so the note that belongs
beside that field lives here:

> `python` is the only *default* that works out of the box on Windows. On most
> macOS and Linux boxes the 3.x interpreter is called **`python3`** and the bare
> `python` is missing or is a Python 2. **Set `MLVIEW_PYTHON` in the environment
> you launch Claude Code from** — `export MLVIEW_PYTHON=python3`, or the absolute
> path of the interpreter you want (`/usr/bin/python3.12`, `C:/Python313/python.exe`,
> a virtualenv's `bin/python`) — and the plugin picks it up with no file edited,
> which is what you want for a plugin installed read-only. Editing `.mcp.json` and
> changing `"command"` to `"python3"` works just as well when you own the checkout.
> Nothing else in the file changes either way; the `args` and `env` are already
> interpreter-independent.

`server/mlview_mcp.py` checks this for you before it imports anything: an
interpreter older than 3.10 exits 1 with

```
mlview-mcp: this server needs Python 3.10 or newer; /usr/bin/python is 2.7.
mlview-mcp: set MLVIEW_PYTHON to a Python 3.10+ interpreter (e.g.
MLVIEW_PYTHON=python3, or an absolute path) and restart Claude Code; .mcp.json
reads "command": "${MLVIEW_PYTHON:-python}". Editing that field to "python3"
works too.
```

rather than a SyntaxError from somewhere inside `vendor/mlview`. On a machine
where only `py` exists, set `MLVIEW_PYTHON` to an absolute interpreter path.

**Mangled output or a `UnicodeEncodeError`.** The Windows console is cp1252.
`.mcp.json` already sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`; keep them,
and pass `-X utf8` when you spawn the CLI yourself.

**A backslash in a path.** Every path MLView emits is forward-slashed, including
`absFile`. Paths you pass in may use either separator.

**The HTML report says "Viewer bundle not synced".** The viewer has not been
built into the analyzer yet:

```bash
cd webview && npm run build
cd .. && python tools/sync-assets.py
```

**`claude plugin validate` fails after an edit.** `plugin.json` must stay inside
`claude-plugin/.claude-plugin/`, and must **not** declare `commands`, `skills`,
`agents`, `hooks` or `mcpServers` — the conventional directories are the
defaults, and `commands`/`agents` *replace* the default scan when set, silently
dropping everything.
