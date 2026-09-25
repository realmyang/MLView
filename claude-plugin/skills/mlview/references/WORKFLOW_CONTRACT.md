# WorkflowDocument 1.0 quick reference

The document fields are `workflowVersion`, `title`, `producer`, `revision`,
`request`, `phases`, `nodes`, `edges`, `findings`, `evidence`, `coverage`, and
optional `verification`. Every object accepts only the fields listed below; the
bundled example shows them in use.

```text
Fields (omit an optional field instead of writing null; IDs match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$):
- producer: kind "host-llm"; host copilot | codex | claude-code | unknown; model? (<= 200)
- revision: id; parent? (the published revision ID; never reuse the published ID or its parent's ID)
- request: question (<= 4000); scope (<= 2000); entrypoints? (<= 100 paths); configuration? (<= 2000)
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

`request.entrypoints` lists unique selected entrypoint paths, and
`request.configuration` describes the selected config/launch arguments and
material default assumptions. Omit unknown details rather than inventing them;
record unresolved choices in coverage. Separate incompatible scenarios.

Paths are workspace-relative slash paths without a drive letter. Evidence uses
one-based inclusive line ranges, and each quote is the exact cited lines of the
UTF-8 source, with CRLF/CR normalised to LF and joined with LF. A leading
byte-order mark is not part of line 1; a line-1 quote may include or omit it.
Notebook evidence adds a zero-based `cell`; line ranges then address that
cell's source. Phase array order is display order. Parent links must form a
forest, while semantic edges may cycle. IDs are unique within each collection.
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

Every helper command prints one JSON object with `ok` and `errors`, except
command-line usage errors (a missing argument or an unknown option), which the
argument parser reports as plain text on stderr with exit status 2 and no JSON.
Each error has `code`, `path`, and `message`; `stale_source` adds `file`, and
`invalid_json` adds `line` and `column` for JSON syntax errors only (not for a
duplicate member, `NaN` or `Infinity`, which are not JSON, or nesting deeper
than 64 levels). A successful `validate` or
`publish` adds `warnings` only when there are any; warnings never block
publication. `validate` adds `revision`, `files`, and, with
`--include-document`, `document`; `publish` adds `output` and `revision`;
`upsert` adds `draft`, `collection`, `id`, and `action`. A relative draft or
`--record` path is resolved against `--workspace`, which must be an existing
directory (`workspace_path`). Output never contains absolute paths.

An early useful overview can be a published `coverage.status: "partial"`
revision with specific remaining work in `coverage.limitations`. It must meet
the same citation and structure checks as a fuller result. Refinement publishes
a new child revision; cancellation or failed validation retains the last valid
publication. Draft existence alone does not imply successful publication.
