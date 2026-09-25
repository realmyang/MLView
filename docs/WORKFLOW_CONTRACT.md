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
`source`; the raw notebook bytes are fingerprinted. Notebook execution order is
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

The `verification` record also carries an RFC 3339 `publishedAt` timestamp.
Fingerprints cover configuration and documentation that influenced the
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
