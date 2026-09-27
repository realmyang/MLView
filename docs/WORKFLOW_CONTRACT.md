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

`request.question` records the user's analysis request verbatim, up to the
4000 characters the schema and both validators allow; a longer request is cut
at that limit and `request.scope` says so. Only the skill invocation and
instructions about running the skill (where to publish, what to report) are
left out, and a machine-specific absolute path in the request is replaced by a
placeholder, which `request.scope` notes. A refinement keeps the published
revision's question unless the user asks a new one, and describes the
refinement in `request.scope`. Interpretation (the selected scenario, what was
left out and why) belongs in `request.scope` and `request.configuration`,
never in a paraphrased question.
`request.entrypoints` names the selected entrypoints; avoid duplicate paths.
`request.configuration` records the selected configuration, relevant launch
arguments and material default/override assumptions. These existing fields are
shown in the authored viewer. Unknown choices stay explicit in coverage, and
incompatible scenarios must not appear as one execution path.
`coverage.limitations` entries say why something is missing: start an entry
with `Excluded by request:` only when the user's request excluded the work,
and write `Not inspected: <what> (<reason>)` for work the author chose not to
do or could not do, such as a time limit or an unavailable file.

`kind` on nodes and edges is optional free text of at most 100 characters.
A shared vocabulary keeps styling and filtering consistent across hosts, so
prefer these values when one fits. Edges: `data`, `control`, `call`,
`config`, `state`, `loop` and `output`. Nodes: `operation`, `data`, `model`,
`state`, `objective`, `optimizer`, `evaluation`, `metric`, `output`,
`config`, `loop`, `branch`, `group`, `entrypoint` and `artifact`. Other
values stay valid.

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
cannot read them, and so is nesting deeper than 500 levels, which not every
Python version can parse. A repeated member keeps its last value, as in
`JSON.parse`. Notebook execution order is not implied. `coverage.inspectedFiles` entries follow the same path rules, and
project entries must name existing regular files.

Only path fields are checked for path syntax: `evidence[].file`,
`coverage.inspectedFiles`, `request.entrypoints`, the keys of
`verification.files` and the helper's `--output` must be workspace-relative,
and both validators refuse absolute or drive-qualified paths there. Free text
(the request, labels, details, findings and limitations) is not checked. It
must still not contain machine-specific absolute paths, such as the home
directory, the workspace root or a temporary directory. Placeholders quoted
from the scenario or from project documentation, such as `/path/to/data`,
are fine, and a quote reproduces its cited lines exactly, whatever paths they
contain.

Evidence quotes are the exact cited lines of the UTF-8 source, with CRLF/CR
normalised to LF and joined with LF. A quote has no line break after its last
line; it ends with one only when the range ends on an empty line (such as the
empty line after a final newline). A leading byte-order mark is not part of
line 1; a line-1 quote may include or omit it. The helper's `excerpt` command
prints the record for a range exactly as `validate` accepts it (below). `verification.files` is written
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
never imports or executes target code. Apart from command-line usage errors
and a successful `excerpt` (which prints the evidence record itself), every
helper run prints exactly one JSON object with `ok` and `errors`. Successful
`validate`, `publish` and `upsert` results add `warnings` (entries with `code`,
`path` and `message`) only when there are any. Successful `validate` adds
`revision`, `files` (the fingerprint map), `basis` and, with
`--include-document`, `document`; `publish` adds `output` and `revision`;
`upsert` adds `draft`, `collection` and `records`, plus `id` and `action` when
`--record` holds a single record. `basis` counts the claims by basis, as
`{"nodes": {"observed": n, "inferred": n, "unresolved": n}, "edges": {...},
"findings": {...}}`; it is a summary for the author's own check and never
affects validity. Error entries have stable `code`, `path`, and `message`
fields; the structured fields some of them add are listed below. Relative
draft and `--record` paths
resolve against `--workspace`, which must be an existing directory
(`workspace_path`). The helper refuses to publish over an existing artifact the
viewer cannot read (over 2 MiB, not UTF-8 JSON, nested deeper than 64 levels,
or without a valid `revision.id`) with `published_invalid`. Command-line usage errors come from
the argument parser: exit status 2 with plain-text usage on stderr and no JSON.
Paths and diagnostics never expose absolute filesystem paths.

## Helper commands and diagnostics

```sh
python3 <skill>/scripts/artifact.py validate <draft> --workspace <ws> [--include-document]
python3 <skill>/scripts/artifact.py publish <draft> --workspace <ws> [--output <path>.mlview.json]
python3 <skill>/scripts/artifact.py upsert <draft> --workspace <ws> --collection <phases|nodes|edges|findings|evidence> --record <file>
python3 <skill>/scripts/artifact.py excerpt <file> --lines <start>[-<end>] [--cell <n>] [--id <evidence-id>] --workspace <ws>
```

**excerpt** is read-only. It reads `<file>`, a workspace-relative path
written as in `evidence[].file`, with the rules `validate` applies to
evidence: the same workspace confinement and symlink resolution, the same
refusal of MLView's own files (`excluded_evidence`), the 8 MiB and UTF-8
limits, zero-based notebook cells (`--cell` is required for `.ipynb` and
refused elsewhere), and the same line splitting and joining. It prints one
line of JSON, the evidence record `{"id", "file", ("cell",) "line",
"endLine", "quote"}`, which `validate` accepts as printed: the record-level
checks run before it is printed. Without `--id` the ID is derived from the
path and range, with the first 8 hex digits of the path's SHA-256 so that
paths that read alike stay apart, for example `ev-src-train.py-a454ee59-10-24`;
the same path and range always give the same ID. A bad option, path or range
exits 1 with the usual `{"ok": false, "errors": [...]}`: `arguments` or
`range` at `--lines`, `id` at `--id`, path and source codes at `file` (with
`limit` for a path over 500 characters and `text_encoding` for a path that is
not valid Unicode), notebook codes at `--cell`, `limit`
when the quote would exceed 16000 characters, and `text_encoding` at
`--lines` when the cited notebook text holds an unpaired surrogate. It never
writes a file.

**upsert** takes a `--record` file that holds one record object, or a JSON
array of records for the same `--collection`. An array lists each ID once
(a repeat is refused with `record`, because it would replace a record the
same batch added), is applied in order (a record whose ID is already in the
draft replaces it) and is validated once as a whole, so a record may cite
another in the same array; if the result is invalid, nothing is written.
`records` lists each applied ID with `inserted` or `replaced`, in order. The
existing draft must still validate first.

**Error details.** Some errors add structured fields:

- `quote_mismatch`: `id` (the evidence ID), `file`, `cell` (notebooks only),
  `line` and `endLine` (the cited range), `citedLines` and `quoteLines` (line
  counts), and `difference` with `rangeLine` (the first differing line,
  one-based within the quote), `line` (the same line in the source's
  coordinates), `column` (one-based, counting Unicode code points), and
  `quote` and `cited`: at most 80 characters of each side's line, starting at
  `startColumn`, or `null` when that side has no such line. When the quoted
  text occurs exactly once in the same file or cell, `foundAt` gives its
  `line` and `endLine`. That is a diagnostic only; the helper never rewrites
  a range, and the search for it is bounded, so a quote of many repeated
  lines may get no `foundAt`. `differingLines` counts the quote lines that
  differ from the cited line at the same position (a line only one side has
  counts). The message states the same facts with both sides JSON-quoted, so
  tabs, carriage returns, trailing spaces and a byte-order mark are visible,
  names the common causes (a line break after the last line, a range that
  ends on an empty line the quote leaves out, a carriage return, a
  whitespace-only difference, or part of a line) and, without `foundAt`, says
  when more lines than the first differ.
- `reference`: `value` names an unresolved string. In a reference list the
  path indexes the entry (for example `nodes[3].evidence[1]`) and `index`
  gives its position; `phase`, `source` and `target` keep the field's path.
  `duplicate_reference`: the path indexes the repeat, with `index`,
  `firstIndex` and `value`. `duplicate_id`: `value` and `firstIndex`, the
  earlier record in the same collection.
- `range`: `maxLine`, the largest valid `endLine` for the cited source.
- `stale_source`: `file`.
- `invalid_json`: `line` and `column` for JSON syntax errors (a duplicate
  member, `NaN` or `Infinity`, which are not JSON, or nesting deeper than 64
  levels has neither), and `member`, the location of a repeated member (for
  example `nodes[3].label`).

Errors do not hide one another where the helper can go on. `unexpected_cell`
still checks the quote against the file's own lines. A repeated JSON member
in a `validate` or `publish` draft is reported (at most 20 individually, then
a count), and the draft is still validated with each member's last value, as
`JSON.parse` reads it, so every other problem appears in the same run; the
draft still fails. `upsert` refuses a draft or record with a repeated member
without validating further.

**Warnings.** Besides `excluded_inspected` and `not_fingerprinted`, a
document without errors is checked for six hygiene problems, reported in this
order: `unreferenced_evidence` (an evidence record that no node, edge or
finding cites, counting `counterEvidence`), `isolated_node` (in a diagram of
two or more nodes, a node with no edge, parent or child), `self_edge` (an
edge whose source and target are the same node, unless its `kind` is `loop`,
ignoring case and surrounding spaces; the viewer draws a self-edge as a small
loop on its card), `wide_evidence` (an evidence record
spanning more than 60 lines), `evidence_overlap` (a finding that lists the
same evidence ID in `evidence` and `counterEvidence`) and
`duplicate_inspected` (a repeated `coverage.inspectedFiles` entry). Each of
these codes lists at most 10 entries in document order, then one entry at the
collection's path (for example `evidence`) that counts the rest. Warnings are
deterministic, appear only in successful results, and never change validity,
the exit status or publication.

<!-- helper-codes:begin -->
## Helper error and warning codes

Every code the helper emits, grouped by what it concerns. An error blocks
`validate`, `publish`, `upsert` and `excerpt`; a warning never blocks
publication. Each
entry's `path` names the field, file or option to fix. Codes are stable, and
`tools/test_error_catalogue.py` fails when the helper emits a code that this
table (or the skill's quick reference) does not list.

**Document shape**

| Code | Kind | Meaning | Typical fix |
|---|---|---|---|
| `additional_property` | error | An object has a field the contract does not allow. | Remove the field or correct its spelling. |
| `basis` | error | `basis` is not `observed`, `inferred` or `unresolved`. | Use one of the three values. |
| `coverage` | error | `coverage` lacks `status` (`scoped` or `partial`) or a non-empty `summary`, or its lists are not arrays. | Complete the coverage record. |
| `duplicate_id` | error | An ID repeats within one collection; `value` and `firstIndex` name it and its first use. | Give every phase, node, edge, finding and evidence record its own ID. |
| `duplicate_reference` | error | A reference list names the same ID twice (the path indexes the repeat) or holds a non-string. | List each referenced ID once. |
| `evidence_required` | error | A claim has no evidence but is not `unresolved` (or, for a node, a conceptual parent with children). | Cite evidence or use `basis: "unresolved"`. |
| `fingerprint` | error | A `verification.files` value is not a lowercase SHA-256. | Delete the `verification` block; publish writes it. |
| `format` | error | `verification.publishedAt` is not in the RFC 3339 profile above. | Delete the `verification` block; publish writes it. |
| `id` | error | An ID (or `excerpt --id`) is missing or does not match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. | Use a short ID of letters, digits, `.`, `_`, `:` or `-`. |
| `invalid_json` | error | The draft or record is not JSON: a syntax error (with `line` and `column`), a duplicate member (with `member`; the rest of a draft is still validated), `NaN` or `Infinity`, or nesting deeper than 64 levels. | Fix the JSON at the reported position. |
| `limit` | error | A collection, list, string or reference count exceeds its maximum, or more than 2000 distinct files are tracked. | Shorten the text or split the work; list fewer files. |
| `parent` | error | A node's `parent` is not the ID of a different node. | Name an existing other node, or omit `parent` for a root node. |
| `parent_cycle` | error | Node `parent` links form a cycle. | Make the parent links a forest. |
| `phase` | error | A phase has no non-empty `label`. | Label every phase. |
| `producer` | error | `producer` is not `kind: "host-llm"` with a supported `host`. | Use host `copilot`, `codex`, `claude-code` or `unknown`. |
| `reference` | error | A phase, node, edge or evidence reference does not resolve; the path indexes it and `value` names it. | Reference an ID that exists in its collection. |
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
| `path_outside_workspace` | error | A path is absolute or uses `..`, is not normalised (a `./`, empty or trailing segment), or the file is missing or resolves outside the workspace. | Cite an existing file inside `--workspace`, written like `src/train.py`. |
| `quote_mismatch` | error | A quote is not exactly the cited lines; `difference` shows the first differing line and column, and `foundAt` where the quoted text occurs when it occurs exactly once. | Fix the line numbers (see `foundAt`), then rerun `excerpt` for that range and replace the record. |
| `range` | error | `line`/`endLine` (or `excerpt --lines`) are not integers with `1 <= line <= endLine <=` the line count (`maxLine`). | Use a one-based inclusive range inside the source. |
| `source_encoding` | error | A cited source is not UTF-8. | Cite a UTF-8 file; list other files under `inspectedFiles` only. |
| `source_read` | error | A cited or inspected file could not be read. | Check that the file is readable. |
| `source_too_large` | error | A cited source exceeds 8 MiB. | Cite a smaller file; mark claims about it inferred or unresolved. |
| `stale_source` | error | A draft's `verification` fingerprint no longer matches the named `file`. | Re-read the file, update dependent claims, delete the `verification` block. |
| `unexpected_cell` | error | `cell` (or `excerpt --cell`) is given for a file that is not `.ipynb`; the quote is still checked. | Remove `cell`. |

**Command and I/O**

| Code | Kind | Meaning | Typical fix |
|---|---|---|---|
| `arguments` | error | `upsert` was run without `--collection` and `--record`, or `excerpt` without a valid `--lines`. | Pass the options the command needs. |
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
| `record` | error | An `upsert` record is not an object with a valid `id`, the record array is empty, or it repeats an ID. | Give every record a valid ID, once per record file. |
| `revision_conflict` | error | `revision.parent` does not name the published revision, or the artifact changed during publication. | Set `parent` to the current published ID (omit it for a first publication). |
| `revision_id_reused` | error | The new revision ID equals the published revision's parent. | Choose a new revision ID. |
| `source_changed` | error | A source changed while publication was in progress. | Publish again once the files are stable. |
| `workspace_path` | error | `--workspace` is not an existing directory. | Pass the VS Code workspace folder. |

**Warnings**

| Code | Kind | Meaning | Typical fix |
|---|---|---|---|
| `excluded_inspected` | warning | An MLView file is listed in `coverage.inspectedFiles`; it is not fingerprinted. | None needed; list only project files to silence it. |
| `not_fingerprinted` | warning | An inspected file exceeds 8 MiB and is listed without a fingerprint. | None needed; its freshness is not tracked. |
| `unreferenced_evidence` | warning | No node, edge or finding cites this evidence record. | Cite it where it supports a claim, or remove it. |
| `isolated_node` | warning | In a diagram of two or more nodes, this node has no edge, parent or child. | Connect it to the step it affects or nest it under a group node; a node that only records an absence or an external unknown can become a coverage limitation. |
| `self_edge` | warning | An edge connects a node to itself without `kind: "loop"`. | Draw an iteration from the last step of the repeated work back to its first step (kind `loop` also marks a one-step repetition), or connect two nodes. |
| `wide_evidence` | warning | An evidence record spans more than 60 lines. | Cite the narrowest range that contains the claim, or split it. |
| `evidence_overlap` | warning | A finding lists the same evidence ID in `evidence` and `counterEvidence`. | Keep it on the side it supports. |
| `duplicate_inspected` | warning | `coverage.inspectedFiles` lists the same file twice. | List each file once. |
<!-- helper-codes:end -->
