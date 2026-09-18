# WorkflowDocument 1.0 contract

WorkflowDocument is the authoring format written by the active Copilot, Codex,
or Claude Code model. It is the supported authoring format. The normative
machine-readable shape is [`contracts/workflow.schema.json`](../contracts/workflow.schema.json).

The root contains `workflowVersion: "1.0"`, a title, host-LLM producer identity,
revision and request records, ordered phases, nodes, edges, findings, evidence,
and coverage. Phase array order controls presentation order. Node `parent`
relationships form a forest; semantic edges may contain cycles. Every ID is
unique within its collection, and every phase, node, edge, and evidence
reference must resolve.

`request.entrypoints` names the selected entrypoints; avoid duplicate paths.
`request.configuration` records the selected configuration, relevant launch
arguments and material default/override assumptions. These existing fields are
shown in the authored viewer. Unknown choices stay explicit in coverage, and
incompatible scenarios must not appear as one execution path.

`basis` distinguishes `observed`, `inferred`, and `unresolved` claims. Nodes,
edges, and findings normally cite evidence. Empty evidence is accepted only for
an unresolved item or a conceptual node that has children. This exception does
not create a source location.

Evidence paths are slash-separated, workspace-relative paths. Absolute paths,
`..` traversal, files outside the workspace through symlinks, non-UTF-8 source,
and out-of-range citations are invalid. Lines are one-based and inclusive. A
quote is the exact cited lines joined with LF after UTF-8 decoding and newline
normalization. For `.ipynb`, `cell` is the zero-based notebook cell index and
line coordinates address that cell's `source`; the raw notebook bytes are
fingerprinted. Notebook execution order is not implied.

The optional `verification` record contains SHA-256 hashes of raw file bytes and
an RFC 3339 `publishedAt` timestamp. On publish, the helper checks any draft
fingerprints against current bytes and recomputes the sorted union of cited
evidence files and `coverage.inspectedFiles`. This includes configuration and
documentation that influenced the interpretation without supplying a displayed
quote. Fingerprints establish freshness, not semantic truth. A stale supplied
fingerprint blocks publication.

Publishing uses a cooperative exclusive `.lock` sidecar and atomic replacement.
Helpers refuse an existing lock, including a stale lock, and never steal it;
manual removal is required after establishing that no publisher is active. If
no published artifact exists, the draft
must omit `revision.parent`. If one exists, the draft parent must equal its
revision ID. This prevents an older concurrent draft from overwriting a newer
revision. Every changed revision requires a new revision ID; reusing an ID with
different semantic content is rejected. Phase, node, edge, finding, and evidence
IDs remain stable across revisions when their concepts retain the same meaning.

A useful early overview may be published with `coverage.status: "partial"`
and specific remaining work in `coverage.limitations`. It must pass the same
structure and citation checks. Further analysis publishes a child revision;
cancellation, quota failure or invalid drafts leave the last valid publication
unchanged. A draft alone does not constitute a published result.

Selection-aware refinement is an authored UI/host interaction, not an artifact
schema change. The viewer sends its revision, selection kind/ID and a bounded
intent. The host resolves the item, source evidence, entrypoints and
configuration from its own validated document before copying a prompt. Missing
IDs and obsolete revisions are rejected. Submission stays in the assistant
that authored the artifact; copying the prompt never starts model work.

The validator imposes bounded document, source, collection, and text sizes and
never imports or executes target code. Its machine output is a JSON object with
`ok`, `errors`, and, on successful validation or publication, `document` or
`output`. Error entries have stable `code`, `path`, and `message` fields. Paths
and diagnostics never expose absolute filesystem paths.
