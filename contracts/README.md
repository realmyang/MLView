# Artifact contract

[`workflow.schema.json`](workflow.schema.json) defines WorkflowDocument 1.0,
the artifact authored by the active native assistant. Read the semantic and
validation requirements in [WORKFLOW_CONTRACT.md](../docs/WORKFLOW_CONTRACT.md).
The skill carries a concise quick reference and a schema-checked example under
`skills/mlview/references/`.

The old MLGraph schema, static CLI contract and Python/TypeScript scope parity
fixtures have been removed with the static analyzer. Reused internal viewer
graph types are a rendering detail, not a second authoring contract.
