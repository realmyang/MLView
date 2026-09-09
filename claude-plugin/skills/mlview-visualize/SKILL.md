---
name: mlview-visualize
description: Recover and visualize the structure of Python machine-learning code — the training pipeline, its stages, and where the data flows. Use when asked to visualize, diagram, map, chart, walk through, or review the structure of ML/PyTorch/scikit-learn code, when asked "how does this training script work" or "where is the data split", or before answering any question about how training and evaluation are wired together. Static analysis only; nothing is imported or executed.
---

# Visualizing an ML pipeline with MLView

## The rule that makes this worth using

**Recover the structure before you read the files.** Call `mlview_analyze`
first. A linear read of `train.py` tells you what happens on line 44; the graph
tells you that the batch loop consumes a loader built from an unsplit dataframe,
which is the thing the user actually needs to know. Reading first and analyzing
second wastes both the context window and the answer.

## The loop

1. **`mlview_analyze`** — `path` defaults to the whole project. You get the
   stage lanes, the frameworks, the counts, the top issues, and `graphPath`.
   - **Read `filesAnalyzed` and `filesFailed` before you read anything else.**
     They are what separates "clean" from "nothing was looked at":
     - `filesAnalyzed: 0` **and** `filesFailed: 0` — there is no Python at that
       path. Say so; do not go hunting with `Glob`, and do not call it clean.
     - `filesFailed > 0` — those files could not be parsed (syntax error, or not
       UTF-8) and **their defects are missing from every count**. Name them as a
       gap in the answer; the `diagnostics` rows say which kind.
     - Both zero and nodes present — this is a real result you can reason about.
   - A `note` field, when present, states exactly this in one sentence. Repeat it
     to the user; never emit a clean bill of health over the top of it.
   - `notebooksSkipped > 0`? Notebooks are not analyzed in this version. Mention it.
2. **`mlview_issues`** — the ranked findings with `file:line` and a fix hint.
   Do this *before* reading source, so your reads are aimed at the defects.
3. **`mlview_graph`** — a diagram to reason about and to show.
   - `scope: "stages"` for the one-screen shape of the pipeline. **This is the
     only scope whose lane list is a statement about the project.**
   - `scope: "units"` for the catalogue of the **container** units — one row per
     class, function and loop as `{nodeId, label, qualname, file, line,
     nodeCount, maxSeverity}`, biggest first. Call it *before* guessing a name.
     It is a menu, **not the complete set of legal targets**: a call site such as
     `train_test_split`, `fit` or `predict` is an `op`, so it never appears here
     even though `unit:train_test_split` resolves. And when the payload's `note`
     says the menu is INCOMPLETE, rows were dropped to fit 4 KB — the whole list
     is `python -m mlview analyze <path> --list-scopes`.
   - `scope: "stage:train"`, `"unit:SmallCNN"`, `"file:data.py"`,
     `"concern:evaluation"`, `"node:<id>"` for one part. A scoped diagram is a
     *filtered* view: its counts describe the scope, and its `note` says so.
   - `depth: 0|1|2` widens the boundary ring. Omit it for the per-kind default
     (1 for `unit`/`node`, 0 for `stage`/`file`/`concern`).
   - Mermaid is the default and is what you should paste into an answer.
4. **`mlview_explain`** — one node in full (record, edges, stage evidence, and up
   to 60 lines of real source), or one rule code's documentation. Reach for this
   instead of `Read` when the question is about a specific node. The rule page
   comes from the plugin's own `docs/rules/`, never from the repository under
   analysis, so an analyzed project cannot rewrite what a rule means.
5. **`mlview_open_diagram`** — only when the user wants to *look* at it. It
   launches a browser, so do not call it speculatively.
   - **A picture file is the viewer's job, not this server's.** Asked for an SVG,
     a PNG, or "an image for the PR": give the user `reportPath` and tell them the
     report's own export menu produces it — or, in VS Code, `MLView: Export Diagram
     as SVG` / `... as PNG`. The payload's `exportHint` is that sentence. This
     server writes HTML and nothing else; never name a file it did not write.

## When to scope

A question about one concern gets a scoped call; a question about the project
does not.

| The user asks | The call |
|---|---|
| "is my evaluation right?", "how is inference scored?" | `scope: "concern:evaluation"` |
| "where does the split happen?" | `scope: "unit:train_test_split"` — an `op` call site, so it is **not** in the `"units"` menu; name it anyway |
| "walk me through SmallCNN" | `scope: "unit:SmallCNN"` |
| "what happens during training?" | `scope: "concern:optimization"` or `"stage:train"` |
| "what is in data.py?" | `scope: "file:data.py"` |
| **"review this project", "what is wrong with this code?"** | **no scope** |

**"review this project" → no scope.** Narrowing first is how you miss the finding
that lives in the lane you did not look at.

The four **concerns** partition the eight stages, so one of them always covers a
"which part" question: `config` = config · `data` = data + preprocess ·
`optimization` = model + objective + train · `evaluation` = eval + deliver.
Aliases work too (`setup`, `preprocessing`, `dataset`, `training`, `inference`).

When the user names a part in words rather than a selector, call
`mlview_graph {scope: "units"}` first and pick the row — and do not fall back to
reading files to find a name.

**The catalogue lists container units only** (`level` `stage`/`unit`, plus
anything with children), and it is shed to fit 4 KB. Two kinds of legal target
are therefore missing from it: a call site (`unit:train_test_split`,
`unit:fit`), which is an `op`, and any row that was dropped when the `note` says
the menu is INCOMPLETE. So when the row you want is not there, use the word the
user used — `unit:` accepts a bare name, and an unresolvable one is an **empty
result with a note, never an error**, which is a cheap, honest probe. Only the
selector *kinds* and the stage / concern vocabularies are closed; unit names are
not. If it is mistyped you get an error naming every accepted value. Either way,
retry with a real name rather than dropping the scope silently.

A scoped result's counts describe the **scope**. Only an unscoped run, or
`scope: "stages"`, is a statement about the project — **say which one you used**,
in the same sentence as the numbers. `graphPath` always points at the full
document, so widening back is free and costs no re-analysis.

The same two arguments work on `mlview_analyze` (the digest then carries a
`scope` block with `nodesInScope` / `nodesTotal`), on `mlview_issues` (only the
findings anchored inside the scope), and on `mlview_open_diagram` (the report
still embeds the whole graph and merely *opens at* the scope, so the reader can
widen it in the toolbar).

## Fallback when the MCP tools are absent

Everything above is available from the CLI, and the answer is identical — the
MCP server and the CLI call the same in-process API:

```bash
python -m mlview analyze <path> --json .mlview/graph.json --format summary
python -m mlview analyze <path> --format mermaid
python -m mlview analyze <path> --list-scopes
python -m mlview analyze <path> --scope concern:evaluation --format summary
python -m mlview issues  <path> --json --min-severity medium
python -m mlview explain MLV201
```

## How to read what comes back

- **Eight canonical stages**, always in this order: `config`, `data`,
  `preprocess`, `model`, `objective`, `train`, `eval`, `deliver`. A stage that is
  *not present* is information, not noise — a pipeline with no `eval` lane has no
  honest evaluation.
- **Three levels**: `stage` lane › `unit` (a class, function or loop) › `op` (a
  significant call or artifact). Answer at the level the question was asked at.
- **Ghost nodes** (`ghost: true`, sublabel `missing`) are steps that *should*
  exist and do not — a missing `optimizer.zero_grad()` is drawn as a hole in the
  loop, not narrated in prose. Say where the hole is.
- **Confidence** is on every node and issue (`certain`, `likely`, `possible`,
  `speculative`), and `dynamic: true` marks a scope the analyzer could not fully
  resolve (`exec`, `getattr` on a call target, star-imports, `**kwargs`
  forwarding). Report `speculative` findings as questions, not as facts.
- **Flow.** In the HTML report and the VS Code panel, hovering a connection
  highlights it and runs a charge from the outlet to the inlet, so the direction
  of a value is something the user sees rather than something you assert. Point
  at it when you hand over the report; the animation respects
  `prefers-reduced-motion` and degrades to a static direction chevron.

## Answering

Lead with the shape in two or three sentences — where data enters, where it is
split, what is optimized, whether evaluation is honest. Then the mermaid diagram.
Then the findings, worst first, each with `file:line`. Cite locations from the
graph rather than from memory; they are exact and the user can click them.

Do not edit files from this skill. If the user wants fixes, that is
`mlview-triage`.
