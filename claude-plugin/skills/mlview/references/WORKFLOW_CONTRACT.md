# WorkflowDocument 1.0 quick reference

The document fields are `workflowVersion`, `title`, `producer`, `revision`,
`request`, `phases`, `nodes`, `edges`, `findings`, `evidence`, `coverage`, and
optional `verification`. See the bundled example for the complete shape.

`request.entrypoints` lists unique selected entrypoint paths, and
`request.configuration` describes the selected config/launch arguments and
material default assumptions. Omit unknown details rather than inventing them;
record unresolved choices in coverage. Separate incompatible scenarios.

Evidence uses workspace-relative slash paths, one-based inclusive line ranges,
and exact UTF-8 lines joined with LF. Notebook evidence adds a zero-based
`cell`; line ranges then address that cell's source. Phase array order is
display order. Parent links must form a forest, while semantic edges may cycle.
IDs are unique within each collection. All references must resolve.
Across revisions, keep IDs for concepts whose meaning is unchanged. Coverage's
`inspectedFiles` records every materially considered source, configuration,
notebook, script, test, or document, even when it has no final evidence anchor.

A finding has this minimal shape:

```json
{
  "id": "finding-id",
  "title": "Concise concern",
  "message": "What may be wrong or unresolved and why it matters.",
  "severity": "medium",
  "nodeIds": ["affected-node-id"],
  "basis": "inferred",
  "evidence": ["evidence-id"]
}
```

`severity` is exactly `low`, `medium`, or `high`. `nodeIds` is required and may
be empty for a workflow-level finding. Optional fields are `edgeIds`,
`counterEvidence`, and `suggestion`. Findings with no evidence must use an
`unresolved` basis.

`verification.files` maps the union of cited and materially inspected relative
paths to SHA-256 of raw file bytes. The helper recomputes it during locked,
atomic publication and rejects supplied stale fingerprints. An existing lock is
never stolen automatically. A new artifact omits `revision.parent`; later drafts
set it to the published revision ID.

An early useful overview can be a published `coverage.status: "partial"`
revision with specific remaining work in `coverage.limitations`. It must meet
the same citation and structure checks as a fuller result. Refinement publishes
a new child revision; cancellation or failed validation retains the last valid
publication. Draft existence alone does not imply successful publication.
