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

Clarify the concrete scenario when configuration or entrypoint choice changes
the workflow. Trace data, construction, calls, control, optimization,
evaluation, and outputs across files. Represent absent runtime facts as
alternatives or unresolved details. Keep a compact evidence record while
working and use exact source lines.

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
`coverage.inspectedFiles` lists every source, config, notebook, launch script,
test, and document materially considered, including files that supplied context
but no final evidence citation. It is not a synonym for the evidence file list.

Before publishing, critique the draft once: check alternative interpretations,
unsupported connections, claimed absences, scenario mixing, and whether it
answers the request. Then run, from the workspace root:

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

For refinement requests, read the published artifact and retain phase, node,
edge, finding, and evidence IDs for concepts that still mean the same thing.
Assign new IDs only to new concepts, remove IDs only when their concepts leave
the requested scenario, and set the new revision's `parent` to the published
revision ID. Expanding detail may add children and evidence without renaming the
stable parent. Reinspect source when the request changes analysis scope; a
display-only projection does not establish new coverage.
