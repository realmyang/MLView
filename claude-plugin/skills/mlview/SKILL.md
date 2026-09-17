---
name: mlview
description: Analyze an ML or deep-learning workflow with the active host model and publish a source-linked interactive MLView artifact.
---

# MLView

Use the active assistant model as the interpretation backend. Inspect the
workspace's source, configuration, notebooks, launch scripts, tests, and useful
documentation with native read and search tools. Do not begin by calling the
legacy static analyzer, import the target project, execute analyzed code, or
claim that reading a test or notebook means it ran.

The artifact helper requires Python 3.10 or newer. Check the selected
interpreter before validation; if it is older, use an available newer Python or
report the requirement without publishing an unverified artifact.

State the selected scenario before tracing it. Use the user's entrypoint/config
when supplied; for a single clear default, state that assumption and proceed.
When materially different choices remain, ask one focused question or keep
the alternatives explicitly separate. Record unique `request.entrypoints` and
use `request.configuration` to name the selected config, relevant launch
arguments, and default/override assumptions. Do not merge mutually exclusive
runs into one apparent execution path. Trace data, construction, calls, control, optimization,
evaluation, and outputs across files. Represent absent runtime facts as
alternatives or unresolved details. Keep a compact evidence record while
working and use exact source lines.

Trace state ownership as well as calls: which data fits preprocessing or learned
state, which parameters each optimizer owns, and where gradients or other loop
state are reset, accumulated, and updated. Distinguish computing gradients
through a component from stepping its parameters. Follow the actual expressions
used for metrics, logs, returned values, and saved outputs; nearby accumulators
or names alone do not establish what is reported. A held-out split does not
establish evaluation: follow whether and how that split is consumed.

Author a WorkflowDocument 1.0 draft using `references/workflow-example.json` as
a shape example and `references/WORKFLOW_CONTRACT.md` as the contract. Use
semantic steps people recognize. Preserve branches, loops, shared components,
and repeated phases. Mark every node, edge, and finding as `observed`,
`inferred`, or `unresolved`. Search for counter-evidence before strong findings.
Use findings only for an actionable concern, contradiction, or unresolved risk.
Expected or correct behavior belongs in node detail or the explanation, not in
a low-severity finding. An empty `findings` array is valid; never invent a
finding to make the diagram look complete. An empty citation list is valid only
for unresolved claims or conceptual groups
supported by children. State inspected files and limitations honestly.
Use `observed` for behavior directly established by the inspected source;
qualify conclusions that depend on framework semantics or unavailable runtime
state as `inferred` or `unresolved`. For notebooks, distinguish source order
from recorded execution counts; counts do not prove a successful clean-kernel
run. Cite cell source exactly and disclose metadata used beyond those citations.
`coverage.inspectedFiles` lists every source, config, notebook, launch script,
test, and document materially considered, including files that supplied context
but no final evidence citation. It is not a synonym for the evidence file list.

Before publishing, critique the draft once: check alternative interpretations,
unsupported connections, claimed absences, and scenario mixing. Check whether
the diagram answers the relevant workflow questions: where data originates,
what parameters or fitted state change, which objectives drive those changes,
where evaluation occurs, what outputs are produced, and what remains unknown.
For a missing step, distinguish absence in the inspected scenario from work
not yet traced; do not add a node or finding merely to fill a checklist. Check
preprocessing fit boundaries and state carried across repeated phases when
they affect the request. Report material critique corrections, or that none
were needed, separately from validator repairs. Then run, from the workspace root:

```sh
python3 <skill-directory>/scripts/artifact.py validate .mlview/llm/<run-id>/draft.json --workspace .
python3 <skill-directory>/scripts/artifact.py publish .mlview/llm/<run-id>/draft.json --workspace . --output workflow.mlview.json
```

`<skill-directory>` is the directory containing this file; resolve it using the
host's skill location. Repair actionable validation errors, with at most two
repair rounds. If repair cannot produce a valid document, leave the last
published revision untouched and report the problem. For a follow-up revision,
set `revision.parent` to the currently published revision ID. Preserve draft
`verification.files` when provided: publish rejects it if cited source changed.

Report the published relative path, revision ID, selected scenario, coverage,
and important limitations. Then tell the user to run **MLView: Open Generated
Diagram** in VS Code and select `workflow.mlview.json` if the panel did not open
automatically. Never include absolute paths in the artifact.

For a broad request, a useful overview may be published before deeper analysis:
critique and validate it first, set `coverage.status` to `partial`, and state
the specific work still uninspected in `coverage.limitations`. Continue with a
child revision when the user requests more detail or the active task allows it.
Do not use a partial label to excuse unsupported claims. If a budget/host limit
interrupts work, preserve the last published revision and identify remaining
work when able. If no publication exists, report that plainly on resumption;
do not describe a draft as a usable diagram or claim to keep running after Stop.

For refinement requests, read the published artifact and retain phase, node,
edge, finding, and evidence IDs for concepts that still mean the same thing.
Assign new IDs only to new concepts, remove IDs only when their concepts leave
the requested scenario, and set the new revision's `parent` to the published
revision ID. Expanding detail may add children and evidence without renaming the
stable parent. Reinspect source when the request changes analysis scope; a
display-only projection does not establish new coverage.
When a copied prompt names a selected node, edge, or finding, resolve its ID in
the stated revision and apply the requested change to that concept. Read its
supporting and counter-evidence, and expand to related source only as needed.
If the published revision has changed, reconcile the selection with the current
document before drafting; never overwrite a newer revision using a stale parent.
