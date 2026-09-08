# `mlview` — the MLView analyzer core

Static analysis of Python ML code (PyTorch, scikit-learn, and a working
minimum of Keras/TF, HuggingFace and Lightning) into an **MLGraph** document:
eight pipeline stages, a node/edge graph of the recovered workflow, and
severity-marked issues with file/line locations.

* **Never imports, executes or `exec`s the analyzed source.** `torch` and
  `sklearn` do not have to be installed — only their *names* are recognised.
* **Zero runtime dependencies**, stdlib only (`jsonschema` and `pytest` are
  test-only).
* **Fully offline.** No network, no telemetry, no cache directory.
* **Windows-safe.** Forward-slashed paths everywhere, CRLF tolerated, no
  symlinks, no `chmod`, no `shell=True`.

The emitted document is the contract between this package and both hosts (the
Claude Code plugin and the VS Code extension): `contracts/graph.schema.json`,
mirrored byte-for-byte at `src/mlview/schema/graph.schema.json`.

---

## Install

```console
$ PYTHONUTF8=1 python -m pip install -e analyzer
```

Editable install, so `python -m mlview` works from any directory and edits to
the source take effect immediately. Python 3.10+.

> Always run with `PYTHONUTF8=1` (and pass `-X utf8` when spawning it) — on a
> cp1252 console a non-ASCII identifier or path otherwise mangles the JSON.

## Use

```console
$ python -m mlview analyze .                      # summary to stdout
$ python -m mlview analyze . --json -             # the graph, and only the graph
$ python -m mlview analyze . --json .mlview/graph.json --html .mlview/report.html --open
$ python -m mlview analyze . --format mermaid     # a compact textual diagram
$ python -m mlview issues . --min-severity medium --code MLV201,MLV301
$ python -m mlview render --graph .mlview/graph.json --out report.html
$ python -m mlview explain MLV201
$ python -m mlview rules --list
$ python -m mlview schema                         # the JSON Schema, verbatim
$ python -m mlview analyze --demo --json -        # the golden sample, byte-identical
```

**stdout carries only the requested payload.** Every log, warning and progress
line goes to stderr — a single stray `print` would corrupt a JSON parse, so
`tests/core/test_stdout_purity.py` greps the package for one.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | A graph was produced (including when `diagnostics[]` is non-empty) |
| `1` | Usage or I/O error |
| `2` | `--fail-on` threshold exceeded |
| `3` | Internal error (a JSON error object goes to stdout) |
| `4` | Nothing analyzable found (no `.py` files after filtering) |

Full flag list: `docs/CONTRACTS.md` §3.

## In-process API

The MCP server and the VS Code helper import this rather than shelling out, so
argument handling cannot diverge:

```python
from mlview.api import AnalyzeOptions, analyze, analyze_to_dict, digest
from mlview.api import render_html, render_mermaid, render_text

doc = analyze_to_dict(AnalyzeOptions(paths=("path/to/project",), max_nodes=400))
render_html(doc, ".mlview/report.html")     # returns the absolute path written
small = digest(doc, limit_bytes=4096)       # the model-facing summary
```

## Layout

```
src/mlview/
  cli.py  api.py  version.py       CLI, the frozen in-process surface, identity
  ingest/   discover.py            walk paths, globs, caps, .ipynb counting
            parse.py               ast.parse; syntax/encoding failures -> diagnostics
  ir/       symbols.py             import aliases -> canonical FQNs
            bindings.py            flow-insensitive bindings + ValueTags
            scopes.py              loop classification, with-blocks, dynamic scopes
            build_ir.py  model.py  the IR dataclasses and their assembly
  knowledge/                       FQN -> {kind, stage, tags, framework, family}
  core/     build.py  graph.py     units, ops, edges, the MLGraph document
            stages.py  ids.py      the 8-stage classifier, content-addressed ids
            pipeline.py            discover -> parse -> IR -> graph -> rules -> emit
  rules/    registry.py            @rule, discovery, run_all
            context.py             GraphContext — the surface every rule sees
            confidence.py          the confidence model + the absence severity cap
            suppress.py            `# mlview: ignore[...]`, .mlview.toml
            r_*.py                 one file per rule family
  emit/     json_out.py  html_out.py  mermaid_out.py  text_out.py
            assets/                the viewer bundle (synced by tools/sync-assets.py)
  schema/   graph.schema.json  graph.sample.json
tests/
  core/                            symbols, bindings, scopes, stages, invariants,
                                   determinism, ids, schema, stdout purity, HTML
  rules/                           rule_harness.py + the per-rule tests
  fixtures/rules/                  <CODE>_bad.py / <CODE>_good.py
```

## Adding a rule

One module, two fixtures. Nothing else is registered by hand — every
`rules/r_*.py` is imported by the registry at start-up.

```python
# src/mlview/rules/r_mystuff.py
from .helpers import calls_in_loop, first_with_role
from .registry import rule


@rule(code="MLV205", severity="medium", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"],
      title="Loss accumulated without .item()",
      why="Keeping the graph alive for every batch leaks memory until the epoch ends.",
      fix_hint="Accumulate loss.item() (or loss.detach()) instead of the tensor.")
def loss_without_item(ctx):
    for loop in ctx.loops("batch"):
        backward = first_with_role(calls_in_loop(ctx, loop), "BACKWARD")
        if backward is None:
            continue
        node = ctx.node_for_loop(loop)
        ctx.issue(message="...cite the variable and the line...",
                  loc=backward.loc, node_ids=[node],
                  evidence=[("fqn_resolved", backward.fqn, 1.0),
                            ("context_confirmed", "inside a batch loop", 1.0)])
```

Rules never construct `Issue`: `ctx.issue(...)` computes the confidence from
the declared evidence, applies the absence-rule severity cap, resolves
suppression and mints the content-addressed id.

Then write the fixtures — 10–40 lines, imports only, never executed:

```python
# tests/fixtures/rules/MLV205_bad.py
# MLVIEW-EXPECT: MLV205 line=18 confidence>=0.6
```
```python
# tests/fixtures/rules/MLV205_good.py
# MLVIEW-EXPECT-NONE: MLV205
```

The good fixture encodes the **nearest false-positive trap**, not merely
correct code. `tests/rules/rule_harness.py` picks both up (import it by that
name, not as `conftest` - two suites put a `conftest.py` on `sys.path`):

```python
from rule_harness import assert_fires, assert_silent

def test_mlv205():
    assert_fires("MLV205_bad")
    assert_silent("MLV205_good", "MLV205")
```

## Test

```console
$ PYTHONUTF8=1 python -m pytest analyzer/tests -q
```

`tests/core/` asserts the frozen conventions: 1-based lines / 0-based columns,
content-addressed ids that survive edits above a node, byte-determinism across
two runs, schema validity via `contracts/validate_sample.py`, `--demo` equal to
the golden sample, stdout purity, and a self-contained offline HTML report.

## Configuration

`.mlview.toml` in the workspace root (or `--config FILE`):

```toml
[rules]
disable = ["MLV601"]

[paths]
exclude = ["experiments/**"]
```

In-source suppression: `# mlview: ignore[MLV201]` on the reported line or the
one above it, or `# mlview: ignore-file` in the first five lines. Suppressed
issues are still emitted, with `suppressed: true`, so a UI can offer *"show
suppressed"* — hosts simply never publish them as diagnostics.
