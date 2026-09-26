# WorkflowDocument 1.0 quick reference

The document fields are `workflowVersion`, `title`, `producer`, `revision`,
`request`, `phases`, `nodes`, `edges`, `findings`, `evidence`, `coverage`, and
optional `verification`. Every object accepts only the fields listed below; the
bundled example shows them in use.

```text
Fields (omit an optional field instead of writing null; IDs match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$):
- producer: kind "host-llm"; host copilot | codex | claude-code | unknown; model? (<= 200)
- revision: id; parent? (the published revision ID; never reuse the published ID or its parent's ID)
- request: question (<= 4000, the user's request verbatim); scope (<= 2000); entrypoints? (<= 100 paths); configuration? (<= 2000)
- phases[1..100]: id; label (<= 200)
- nodes[1..2000]: id; label (<= 300); phase; parent? (a different node ID); kind? (<= 100); detail? (<= 8000); basis; evidence
- edges[<= 4000]: id; source; target; label (<= 300); kind?; basis; evidence
- findings[<= 1000]: id; title (<= 300); message (<= 8000); severity; nodeIds; edgeIds?; basis; evidence; counterEvidence?; suggestion? (<= 4000)
- evidence[<= 5000]: id; file; line; endLine; quote (<= 16000); cell? (.ipynb only, zero-based)
- coverage: status scoped | partial; summary (<= 4000); inspectedFiles (<= 2000; at most 2000 tracked files in all); limitations (<= 500, each <= 2000)
- verification: written by publish; never copy it into a draft
```

Omit optional fields you do not use; never write `null` for them (a root node
has no `parent` field).

`request.question` is the user's request verbatim; if it exceeds 4000
characters, cut it there and say so in `request.scope`. Put your
interpretation (selected scenario, exclusions) in `request.scope` and
`request.configuration`, never in a paraphrased question.
`request.entrypoints` lists unique selected entrypoint paths, and
`request.configuration` describes the selected config/launch arguments and
material default assumptions. Omit unknown details rather than inventing them;
record unresolved choices in coverage. Separate incompatible scenarios. Start a
limitation with `Excluded by request:` only when the request excluded the work;
otherwise write `Not inspected: <what> (<reason>)`.

`kind` stays optional free text, but prefer these values. Edges: `data`,
`control`, `call`, `config`, `state`, `loop`, `output`. Nodes: `operation`,
`data`, `model`, `state`, `objective`, `optimizer`, `evaluation`, `metric`,
`output`, `config`, `loop`, `branch`, `group`, `entrypoint`, `artifact`.

Path fields (`evidence[].file`, `inspectedFiles`, `entrypoints`, `--output`)
are workspace-relative slash paths without a drive letter; the helper refuses
absolute ones there. Free text is not checked, but must not contain
machine-specific absolute paths (home directory, workspace root, temporary
directories); placeholders quoted from the scenario or project docs, such as
`/path/to/data`, are fine. Evidence uses
one-based inclusive line ranges, and each quote is the exact cited lines of the
UTF-8 source, with CRLF/CR normalised to LF and joined with LF, with no line
break after the last line (unless the range ends on an empty line). A leading
byte-order mark is not part of line 1; a line-1 quote may include or omit it.
Notebook evidence adds a zero-based `cell`; line ranges then address that
cell's source. Cited notebooks must be valid JSON; NaN and Infinity are refused
(`notebook_cell`), and so is nesting deeper than 500 levels. Phase array order
is display order. Parent links must form a forest, while semantic edges may
cycle. IDs are unique within each collection.
All references must resolve. Across revisions, keep IDs for concepts whose
meaning is unchanged. Coverage's `inspectedFiles` records every materially
considered project source, configuration, notebook, script, test, or document,
even when it has no final evidence anchor.

MLView's own files are never project evidence: any `*.mlview.json` or
`*.draft.json`, anything under `.mlview/`, and the installed skill under
`.agents/skills/mlview/`, `.claude/skills/mlview/` or `.github/skills/mlview/`
(case-insensitive over A-Z, plus the long s U+017F as `s` and the Kelvin sign
U+212A as `k`). Citing one is an error (`excluded_evidence`); listing
one in `inspectedFiles` is reported as the warning `excluded_inspected` and it
gets no fingerprint.

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

`verification` is written only by publish. `verification.files` maps each
tracked file to the SHA-256 of its raw bytes. Tracked files are the cited
evidence files plus every `inspectedFiles` entry except MLView's own files.
Inspected files may be binary; files over 8 MiB are listed without a
fingerprint (warning `not_fingerprinted`). At most 2000 distinct tracked files
fit in `verification.files`; list fewer files (`limit`) if a draft has more. A
symlink that resolves to an MLView file, or another name (such as a hard link)
for the draft or artifact being checked, is treated like that file. Readers
ignore fingerprints for untracked paths. A file is fresh when its current raw
bytes match its fingerprint. The helper recomputes the fingerprints during
locked, atomic publication; an existing lock is never stolen automatically.

A draft should omit `verification`: when you start one from the published
artifact, delete the block. If a draft carries one anyway, it must be an
object, and a fingerprint that no longer matches a tracked file blocks
publication with `stale_source` naming that file; keys for other paths are
ignored.

Publish writes `--output`, a workspace-relative path ending in `.mlview.json`;
a published artifact is at most 2 MiB. If no artifact exists, the draft omits
`revision.parent`; otherwise the parent equals the published revision ID. A new
revision ID must differ from the published revision's ID and its parent's ID;
MLView keeps no longer history, so never reuse earlier IDs.

Every helper command prints one JSON object with `ok` and `errors`, except a
successful `excerpt` (it prints the evidence record) and command-line usage
errors (a missing argument or an unknown option), which the argument parser
reports as plain text on stderr with exit status 2 and no JSON.

```sh
python3 <skill-directory>/scripts/artifact.py excerpt <file> --lines <start>[-<end>] [--cell <n>] [--id <evidence-id>] --workspace <workspace-folder>
```

`excerpt` is read-only: for a workspace-relative `<file>` it prints one line,
`{"id", "file", ("cell",) "line", "endLine", "quote"}`, exactly as `validate`
accepts it (same path rules, MLView files refused, `--cell` required for
`.ipynb` and refused elsewhere); a bad path or range exits 1 with `errors`.
`upsert --record` holds one record or a JSON array of records for the same
collection, applied in order and validated once: all are written or none;
`upsert` then adds `records` (each `id` and `action`), plus `id` and `action`
for a single record, and `draft` and `collection`.

Each error has `code`, `path`, and `message`. `quote_mismatch` adds `id`,
`file`, `cell`, `line`, `endLine`, `citedLines`, `quoteLines`, `difference`
(`rangeLine`, source `line`, `column`, and each side's text as `quote` and
`cited`, JSON-escaped so tabs, CR and trailing spaces show) and, when the
quoted text occurs exactly once in that file or cell, `foundAt` (`line`,
`endLine`): a hint, never applied for you. `reference` and
`duplicate_reference` paths index the entry and add `value`; `duplicate_id`
adds `value` and `firstIndex`; `range` adds `maxLine`; `stale_source` adds
`file`; `invalid_json` adds `line` and `column` for syntax errors and
`member` for a repeated member, after which a draft is still validated with
the last value, so other errors show in the same run. A successful `validate`,
`publish` or `upsert` adds `warnings` only when there are any; warnings never
block publication. `validate` adds `revision`, `files`, `basis` (counts of
observed, inferred and unresolved nodes, edges and findings) and, with
`--include-document`, `document`; `publish` adds `output` and `revision`. Each
hygiene warning code lists at most 10 entries, then a count. A relative draft
or `--record` path is resolved against `--workspace`, which must be an
existing directory (`workspace_path`). Output never contains absolute paths.

<!-- helper-codes:begin -->
Helper codes and the usual repair (the entry's `path` names what to fix):

```text
Errors (block validate, publish, upsert and excerpt):
- additional_property: remove a field the object does not allow
- arguments: upsert needs --collection, --record; excerpt --lines
- basis: use observed, inferred or unresolved
- checkpoint_invalid: the draft upsert edits must validate first
- coverage: give coverage a status (scoped|partial) and a summary
- document_too_large: the artifact would exceed 2 MiB; shorten it
- draft_conflict: the draft changed during upsert; edit it again
- draft_encoding: save the draft or record as UTF-8 JSON
- draft_io: the draft or record could not be read or written
- draft_locked: the draft's .lock exists; wait, or ask the user
- draft_not_found: no such draft or record (relative to --workspace)
- draft_path: pass a regular file (upsert: inside the workspace)
- draft_too_large: the draft or record exceeds 2 MiB
- duplicate_id: an ID repeats within its collection
- duplicate_reference: list each referenced ID once
- evidence_required: cite evidence or use basis unresolved
- excluded_evidence: cite project files, never MLView files
- fingerprint: delete the draft's verification block
- format: delete the draft's verification block
- id: IDs match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$
- internal_error: the helper failed; report the command
- invalid_json: fix the JSON (syntax, duplicate member, NaN, nesting)
- invalid_path: use a slash-separated relative path to a regular file
- limit: shorten text or lists; at most 2000 tracked files
- notebook_cell: cite an existing zero-based cell of a valid notebook
- output_path: --output is a workspace-relative *.mlview.json path
- parent: another node's ID; omit parent for root nodes
- parent_cycle: parent links must form a forest
- path_outside_workspace: cite an existing file inside --workspace
- phase: give every phase a label
- producer: kind host-llm; host copilot|codex|claude-code|unknown
- publication_io: the artifact, its folder or lock could not be written
- publish_locked: the artifact's .lock exists; wait, or ask the user
- published_invalid: the existing artifact is unreadable; ask the user
- published_target: upsert a *.draft.json copy, not the artifact
- python_version: run the helper with Python 3.10+
- quote_mismatch: fix the range (see foundAt) or the quote (difference)
- range: line..endLine is a one-based inclusive range in the source
- record: each upsert record needs a valid id
- reference: reference an ID that exists
- request: request.question and request.scope must be non-empty
- required: add the missing field; phases and nodes are non-empty
- revision: revision.id and parent are valid, distinct IDs
- revision_conflict: parent is the published revision ID (omit if none)
- revision_id_reused: choose a new revision ID
- severity: use low, medium or high
- source_changed: sources changed while publishing; publish again
- source_encoding: cite UTF-8 files only
- source_read: the file could not be read
- source_too_large: the cited source exceeds 8 MiB
- stale_source: re-read the file, update claims, delete verification
- text_encoding: remove unpaired surrogates
- text_too_large: shorten strings to 16000 characters
- type: use the JSON type the contract names
- unexpected_cell: cell is only for .ipynb evidence
- verification: delete the draft's verification block
- version: workflowVersion is "1.0"
- workspace_path: --workspace is the existing workspace folder
Warnings (never block publication):
- excluded_inspected: MLView file in inspectedFiles; not fingerprinted
- not_fingerprinted: inspected file over 8 MiB; no fingerprint
- unreferenced_evidence: no claim cites it; cite it or remove it
- isolated_node: no edge, parent or child; connect it
- self_edge: source is target; kind loop if intended
- wide_evidence: over 60 lines; cite a narrower range
- evidence_overlap: same ID in evidence and counterEvidence
- duplicate_inspected: inspectedFiles lists it twice
```
<!-- helper-codes:end -->

An early useful overview can be a published `coverage.status: "partial"`
revision with specific remaining work in `coverage.limitations`. It must meet
the same citation and structure checks as a fuller result. Refinement publishes
a new child revision; cancellation or failed validation retains the last valid
publication. Draft existence alone does not imply successful publication.
