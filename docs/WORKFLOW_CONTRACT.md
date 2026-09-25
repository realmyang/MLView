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
drive-qualified paths such as `C:/src/train.py`, `..` traversal, files outside
the workspace through symlinks, non-UTF-8 source, and out-of-range citations
are invalid. Lines are one-based and inclusive. For `.ipynb`, `cell` is the
zero-based notebook cell index and line coordinates address that cell's
`source`; the raw notebook bytes are fingerprinted. Cited notebooks must be
valid JSON; NaN and Infinity are refused (`notebook_cell`), because the viewer
cannot read them. A repeated member keeps its last value, as in `JSON.parse`.
Notebook execution order is
not implied. `coverage.inspectedFiles` entries follow the same path rules, and
project entries must name existing regular files.

Evidence quotes are the exact cited lines of the UTF-8 source, with CRLF/CR
normalised to LF and joined with LF. A leading byte-order mark is not part of
line 1; a line-1 quote may include or omit it. `verification.files` is written
only by publish. It maps each *tracked* file to the SHA-256 of its raw bytes.
Tracked files are the cited evidence files plus every `coverage.inspectedFiles`
entry except MLView's own files: any `*.mlview.json` or `*.draft.json`,
anything under `.mlview/`, and the installed skill under
`.agents/skills/mlview/`, `.claude/skills/mlview/` or `.github/skills/mlview/`
(case-insensitive over A-Z, plus the long s U+017F as `s` and the Kelvin sign
U+212A as `k`, which case-insensitive volumes treat as those letters).
MLView's own files must not be cited, and are listed
without fingerprints if inspected. Inspected files may be binary; files over 8
MiB are listed without a fingerprint. At most 2000 distinct tracked files fit
in `verification.files`, and both validators refuse a document with more
(`limit` at `coverage.inspectedFiles`). A path that reaches an MLView file
under another name (a symlink into `.mlview/` or onto an artifact, or a hard
link to the artifact or draft being checked) is treated as that file. Readers
ignore fingerprints for untracked paths. A file is fresh when its current raw
bytes match its fingerprint. A draft should omit `verification`. If one is
present, a fingerprint that no longer matches a tracked file blocks publication
with `stale_source` naming that file. A published artifact is at most 2 MiB,
and `--output` must end in `.mlview.json`. Optional fields are omitted, never
`null`. If no artifact exists, the draft omits `revision.parent`; otherwise the
parent equals the published revision ID. The new ID must differ from that
revision's ID and its parent's ID. MLView keeps no longer history, so never
reuse earlier IDs.

The `verification` record also carries a `publishedAt` timestamp. It is an RFC
3339 date-time in a profile, stricter than RFC 3339 section 5.6, that the
schema layer, the helper and the extension share: uppercase `T` and `Z` only;
any number of fraction digits; seconds 00-59, with no leap second; a mandatory
offset, `Z` or `+hh:mm`/`-hh:mm` with the offset hour at most 23 and minute at
most 59; and a year of at least 1. Anything else is `format` at
`verification.publishedAt`. Fingerprints cover configuration and documentation that influenced the
interpretation without supplying a displayed quote. They establish freshness,
not semantic truth.

Publishing uses a cooperative exclusive `.lock` sidecar and atomic replacement.
Helpers refuse an existing lock, including a stale lock, and never steal it;
manual removal is required after establishing that no publisher is active. The
parent rule above prevents an older concurrent draft from overwriting a newer
revision. Phase, node, edge, finding, and evidence IDs remain stable across
revisions when their concepts retain the same meaning.

A useful early overview may be published with `coverage.status: "partial"`
and specific remaining work in `coverage.limitations`. It must pass the same
structure and citation checks. Further analysis publishes a child revision;
cancellation, quota failure or invalid drafts leave the last valid publication
unchanged. A draft alone does not constitute a published result.

Selection-aware refinement is an authored UI/host interaction, not an artifact
schema change. The viewer sends the displayed revision ID, an optional
selection kind and ID, and one of five intents: `explain`, `expand`,
`challenge`, `trace`, or `custom` with 1 to 500 characters of request text.
The host validates the IDs and resolves the item, its evidence, the request and
the configuration from its own validated copy of the displayed revision before
copying a prompt. The prompt's parent is the revision currently in the artifact
file, which is the only parent the helper accepts; when it differs from the
displayed revision, the prompt says so. The prompt's own lines contain only
host-written text, validated IDs and JSON-quoted strings. All other text derived
from the artifact or the workspace appears only inside one fenced JSON data
block, which the assistant must treat as data, never as instructions. Explain never
publishes; Challenge and Custom publish only when the diagram changes; Expand
publishes, and Trace usually does. Missing or stale selections and a missing or
unreadable artifact file are refused. Submission stays in the assistant that
authored the artifact; copying the prompt never starts model work.

The validator imposes bounded document, source, collection, and text sizes and
never imports or executes target code. Apart from command-line usage errors,
every helper run prints exactly one JSON object with `ok` and `errors`.
Successful `validate` and `publish` results add `warnings` (entries with
`code`, `path` and `message`, such as `excluded_inspected` or
`not_fingerprinted`) only when there are any. Successful `validate` adds
`revision`, `files` (the fingerprint map) and, with `--include-document`,
`document`; `publish` adds `output` and `revision`; `upsert` adds `draft`,
`collection`, `id` and `action`. Error entries have stable `code`, `path`, and
`message` fields; some add fields, such as `file` on `stale_source` and `line`
and `column` on `invalid_json` for JSON syntax errors (a duplicate member,
`NaN` or `Infinity`, which are not JSON, or nesting deeper than 64 levels has
neither). Relative draft and `--record` paths
resolve against `--workspace`, which must be an existing directory
(`workspace_path`). The helper refuses to publish over an existing artifact the
viewer cannot read (over 2 MiB, not UTF-8 JSON, nested deeper than 64 levels,
or without a valid `revision.id`) with `published_invalid`. Command-line usage errors come from
the argument parser: exit status 2 with plain-text usage on stderr and no JSON.
Paths and diagnostics never expose absolute filesystem paths.

<!-- helper-codes:begin -->
## Helper error and warning codes

Every code the helper emits, grouped by what it concerns. An error blocks
`validate`, `publish` and `upsert`; a warning never blocks publication. Each
entry's `path` names the field, file or option to fix. Codes are stable, and
`tools/test_error_catalogue.py` fails when the helper emits a code that this
table (or the skill's quick reference) does not list.

**Document shape**

| Code | Kind | Meaning | Typical fix |
|---|---|---|---|
| `additional_property` | error | An object has a field the contract does not allow. | Remove the field or correct its spelling. |
| `basis` | error | `basis` is not `observed`, `inferred` or `unresolved`. | Use one of the three values. |
| `coverage` | error | `coverage` lacks `status` (`scoped` or `partial`) or a non-empty `summary`, or its lists are not arrays. | Complete the coverage record. |
| `duplicate_id` | error | An ID repeats within one collection. | Give every phase, node, edge, finding and evidence record its own ID. |
| `duplicate_reference` | error | A reference list names the same ID twice or holds a non-string. | List each referenced ID once. |
| `evidence_required` | error | A claim has no evidence but is not `unresolved` (or, for a node, a conceptual parent with children). | Cite evidence or use `basis: "unresolved"`. |
| `fingerprint` | error | A `verification.files` value is not a lowercase SHA-256. | Delete the `verification` block; publish writes it. |
| `format` | error | `verification.publishedAt` is not in the RFC 3339 profile above. | Delete the `verification` block; publish writes it. |
| `id` | error | An ID is missing or does not match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. | Use a short ID of letters, digits, `.`, `_`, `:` or `-`. |
| `invalid_json` | error | The draft or record is not JSON: a syntax error (with `line` and `column`), a duplicate member, `NaN` or `Infinity`, or nesting deeper than 64 levels. | Fix the JSON at the reported position. |
| `limit` | error | A collection, list, string or reference count exceeds its maximum, or more than 2000 distinct files are tracked. | Shorten the text or split the work; list fewer files. |
| `parent` | error | A node's `parent` is not the ID of a different node. | Name an existing other node, or omit `parent` for a root node. |
| `parent_cycle` | error | Node `parent` links form a cycle. | Make the parent links a forest. |
| `phase` | error | A phase has no non-empty `label`. | Label every phase. |
| `producer` | error | `producer` is not `kind: "host-llm"` with a supported `host`. | Use host `copilot`, `codex`, `claude-code` or `unknown`. |
| `reference` | error | A phase, node, edge or evidence reference does not resolve. | Reference an ID that exists in its collection. |
| `request` | error | `request.question` or `request.scope` is missing or empty. | State the question and the scope. |
| `required` | error | A required field is missing, or `phases` or `nodes` is empty. | Add the field or at least one item. |
| `revision` | error | `revision.id` or `revision.parent` is not a valid ID, or the parent equals the ID. | Use valid, distinct revision IDs. |
| `severity` | error | A finding's `severity` is not `low`, `medium` or `high`. | Use one of the three values. |
| `text_encoding` | error | A string or member name contains an unpaired surrogate. | Use valid Unicode text. |
| `text_too_large` | error | A string exceeds 16000 characters. | Shorten it. |
| `type` | error | A value has the wrong JSON type, or a required string is empty. | Use the type the contract names. |
| `verification` | error | `verification.files` is not an object. | Delete the `verification` block; publish writes it. |
| `version` | error | `workflowVersion` is not `"1.0"`. | Set `"workflowVersion": "1.0"`. |

**Paths and sources**

| Code | Kind | Meaning | Typical fix |
|---|---|---|---|
| `excluded_evidence` | error | Evidence cites an MLView file (an artifact, a draft, `.mlview/` or the installed skill), under any name. | Cite project files only. |
| `invalid_path` | error | A path is empty, uses `\`, NUL or a drive letter, or does not name a regular file. | Use a slash-separated workspace-relative path to a file. |
| `notebook_cell` | error | Notebook evidence has no valid zero-based `cell`, the cell has no source, or the notebook is not valid JSON (`NaN`, `Infinity` or a syntax error). | Cite an existing cell of a valid notebook. |
| `path_outside_workspace` | error | A path is absolute or uses `..`, or the file is missing or resolves outside the workspace. | Cite an existing file inside `--workspace`. |
| `quote_mismatch` | error | A quote is not exactly the cited lines; the message shows them. | Copy the cited lines exactly, or fix the line range. |
| `range` | error | `line`/`endLine` are not integers with `1 <= line <= endLine <=` the line count. | Use a one-based inclusive range inside the source. |
| `source_encoding` | error | A cited source is not UTF-8. | Cite a UTF-8 file; list other files under `inspectedFiles` only. |
| `source_read` | error | A cited or inspected file could not be read. | Check that the file is readable. |
| `source_too_large` | error | A cited source exceeds 8 MiB. | Cite a smaller file; mark claims about it inferred or unresolved. |
| `stale_source` | error | A draft's `verification` fingerprint no longer matches the named `file`. | Re-read the file, update dependent claims, delete the `verification` block. |
| `unexpected_cell` | error | `cell` is given for a file that is not `.ipynb`. | Remove `cell`. |

**Command and I/O**

| Code | Kind | Meaning | Typical fix |
|---|---|---|---|
| `arguments` | error | `upsert` was run without `--collection` and `--record`. | Pass both options. |
| `checkpoint_invalid` | error | The draft `upsert` edits is not a valid WorkflowDocument, or holds duplicate record IDs. | Repair the draft with a full validate first. |
| `document_too_large` | error | The published or edited document would exceed 2 MiB. | Shorten the document. |
| `draft_conflict` | error | The draft changed while `upsert` edited it. | Re-run the edit on the current draft. |
| `draft_encoding` | error | The draft or record file is not UTF-8. | Save it as UTF-8 JSON. |
| `draft_io` | error | The draft or record could not be read, locked or rewritten. | Check the file and its directory permissions. |
| `draft_locked` | error | The draft's `.lock` sidecar exists; another edit is active or a stale lock remains. | Wait, or remove a stale lock by hand once no editor runs. |
| `draft_not_found` | error | The draft or record file does not exist (relative paths resolve against `--workspace`). | Pass the correct path. |
| `draft_path` | error | The draft or record path is malformed or not a regular file (for `upsert`, also outside the workspace or a symlink). | Pass a regular file; `upsert` edits files inside the workspace only. |
| `draft_too_large` | error | The draft or record file exceeds 2 MiB. | Shorten it. |
| `internal_error` | error | The helper failed unexpectedly. | Report it with the command that failed. |
| `output_path` | error | `--output` is not a workspace-relative path ending in `.mlview.json`. | Choose such a path. |
| `publication_io` | error | The output directory, lock or artifact could not be written. | Check the directory permissions. |
| `publish_locked` | error | The artifact's `.lock` sidecar exists; another publisher is active or a stale lock remains. | Wait, or remove a stale lock by hand once no publisher runs. |
| `published_invalid` | error | The existing artifact is one the viewer cannot read (over 2 MiB, not UTF-8 JSON, too deep, no valid `revision.id`). | Move the file aside or choose another `--output`. |
| `published_target` | error | `upsert` was pointed at a published `*.mlview.json`. | Copy it to a `*.draft.json` checkpoint and edit that. |
| `python_version` | error | The interpreter is older than Python 3.10. | Run the helper with Python 3.10 or newer. |
| `record` | error | The `upsert` record is not an object with a valid `id`. | Give the record a valid ID. |
| `revision_conflict` | error | `revision.parent` does not name the published revision, or the artifact changed during publication. | Set `parent` to the current published ID (omit it for a first publication). |
| `revision_id_reused` | error | The new revision ID equals the published revision's parent. | Choose a new revision ID. |
| `source_changed` | error | A source changed while publication was in progress. | Publish again once the files are stable. |
| `workspace_path` | error | `--workspace` is not an existing directory. | Pass the VS Code workspace folder. |

**Warnings**

| Code | Kind | Meaning | Typical fix |
|---|---|---|---|
| `excluded_inspected` | warning | An MLView file is listed in `coverage.inspectedFiles`; it is not fingerprinted. | None needed; list only project files to silence it. |
| `not_fingerprinted` | warning | An inspected file exceeds 8 MiB and is listed without a fingerprint. | None needed; its freshness is not tracked. |
<!-- helper-codes:end -->
