# Artifact contract

[`workflow.schema.json`](workflow.schema.json) is the normative
machine-readable shape of WorkflowDocument 1.0, the artifact the active native
assistant authors. [WORKFLOW_CONTRACT.md](../docs/WORKFLOW_CONTRACT.md) states
the semantic and workspace rules. The skill carries a concise quick reference
and a schema-checked example under `skills/mlview/references/`.

## Reading the schema

- **Regular expressions use the ECMA-262 dialect** that JSON Schema specifies.
  Every `pattern` is anchored (`^...$`) and must match the whole string, so
  `r1\n` is not a valid ID. Python's `re.search` lets `$` match before a final
  newline. Validate with an ECMA-262 engine or with full-match semantics, as
  the conformance runner does.
- **`format: "date-time"` is a requirement.** `verification.publishedAt` is an
  RFC 3339 date-time with an offset (`Z` or `+hh:mm`/`-hh:mm`). Draft 2020-12
  treats `format` as an annotation by default, and Python's jsonschema has no
  `date-time` checker without extra packages, so assert it explicitly. The
  schema layer, the helper and the extension share one profile, stricter than
  RFC 3339 section 5.6: uppercase `T` and `Z` only; any number of fraction
  digits; seconds 00-59, with no leap second; a mandatory offset whose hour is
  at most 23 and minute at most 59; and a year of at least 1. The conformance
  corpus pins it (`shape-006`, `shape-011`, `shape-016` to `shape-018`).
- **Integers must be JSON integers.** JSON Schema counts `1.0` and `1e0` as
  integers, and `JSON.parse` turns them into `1`. The helper rejects them and
  never writes them.
- **Member names are unique.** The helper rejects duplicate members;
  `JSON.parse` and most schema validators silently keep the last one.
- **`NaN` and `Infinity` are not JSON.** `JSON.parse` rejects them, but
  Python's `json` module accepts them by default; the helper rejects them in
  drafts, in an existing artifact and in cited notebooks. Cited notebooks must
  be valid JSON; NaN and Infinity are refused (`notebook_cell`).
- **Lengths count Unicode code points**, as JSON Schema `maxLength` does. The
  helper and the extension count code points too.
- **The schema cannot express workspace rules.** The helper and the extension
  also check that paths stay inside the workspace, that quotes match the cited
  lines, fingerprints, MLView's own files, drive letters, parent references,
  unpaired surrogates and the limit of 2000 distinct tracked files. A
  schema-valid document can still be invalid.

## Conformance corpus

Contract changes are checked by [`conformance/`](conformance/README.md). Each
self-contained case records the verdict of the strict schema layer, the helper
(`skills/mlview/scripts/artifact.py`) and the extension's validator
(`vscode-extension/src/workflowDocument.ts`).
`tools/test_workflow_conformance.py` runs the schema and helper layers and the
recorded-artifact suite. `vscode-extension/test/conformance.test.js` runs the
extension layer, checks the parity invariant against the helper, and loads
every artifact the helper publishes from the corpus. A contract change updates
the schema, both validators, the contract docs and the corpus together.

The layers disagree only in two accepted classes, which the corpus records
case by case:

1. JSON spellings that `JSON.parse` cannot see (duplicate members, integers
   written as `1.0` or `1e0`). The helper rejects them and never publishes
   them. The viewer sees only the parsed value.
2. An inspected-only file without a fingerprint inside a verified (published)
   document. The helper validates authoring and requires the file to exist.
   The viewer checks published freshness and does not touch the file.

The old MLGraph schema, static CLI contract and analyzer parity fixtures were
removed with the static analyzer. The viewer's internal graph types are a
rendering detail, not a second authoring contract.
