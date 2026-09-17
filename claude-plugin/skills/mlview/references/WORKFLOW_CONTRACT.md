# WorkflowDocument 1.0 quick reference

The document fields are `workflowVersion`, `title`, `producer`, `revision`,
`request`, `phases`, `nodes`, `edges`, `findings`, `evidence`, `coverage`, and
optional `verification`. See the bundled example for the complete shape.

Evidence uses workspace-relative slash paths, one-based inclusive line ranges,
and exact UTF-8 lines joined with LF. Notebook evidence adds a zero-based
`cell`; line ranges then address that cell's source. Phase array order is
display order. Parent links must form a forest, while semantic edges may cycle.
IDs are unique within each collection. All references must resolve.
Across revisions, keep IDs for concepts whose meaning is unchanged. Coverage's
`inspectedFiles` records every materially considered source, configuration,
notebook, script, test, or document, even when it has no final evidence anchor.

`verification.files` maps the union of cited and materially inspected relative
paths to SHA-256 of raw file bytes. The helper recomputes it during locked,
atomic publication and rejects supplied stale fingerprints. An existing lock is
never stolen automatically. A new artifact omits `revision.parent`; later drafts
set it to the published revision ID.
