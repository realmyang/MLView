# The format and its conformance cases

[`workflow.schema.json`](workflow.schema.json) is the normative
machine-readable shape of WorkflowDocument 1.0, the document that your
assistant writes. [docs/format.md](../docs/format.md) states the rules that
the schema cannot express, and the helper's commands. The skill carries a
short reference of its own and an example that is checked against the schema,
under `skills/mlview/references/`.

## Reading the schema

- **Regular expressions use the ECMA-262 dialect.**
  Every `pattern` is anchored (`^...$`) and must match the whole string, so
  `r1\n` is not a valid ID. Python's `re.search` lets `$` match before a final
  newline. Validate with an ECMA-262 engine or with full-match semantics, as
  the conformance runner does.
- **`format: "date-time"` is a requirement.** Draft 2020-12 treats `format`
  as an annotation by default, and Python's jsonschema has no `date-time`
  checker without extra packages, so assert it explicitly.
  [docs/format.md](../docs/format.md#fingerprints-and-freshness) gives the
  profile of `verification.publishedAt`, and the cases `shape-006`,
  `shape-011` and `shape-016` to `shape-018` hold it.
- **Integers must be JSON integers.** JSON Schema counts `1.0` and `1e0` as
  integers, and `JSON.parse` turns them into `1`. The helper rejects them and
  never writes them.
- **Member names are unique.** The helper rejects duplicate members;
  `JSON.parse` silently keeps the last one, and a schema validator sees only
  the parsed value.
- **`NaN` and `Infinity` are not JSON.** `JSON.parse` rejects them, but
  Python's `json` module accepts them by default. The helper refuses them in
  a draft, in a published document and in a cited notebook.
- **Lengths count Unicode code points**, as JSON Schema `maxLength` does. The
  helper and the extension count code points too.
- **The schema cannot express workspace rules.** The helper and the extension
  also check that paths stay inside the workspace, that quotes match the cited
  lines, fingerprints, MLView's own files, drive letters, parent references,
  unpaired surrogates and the limit of 2000 distinct tracked files. A
  schema-valid document can still be invalid.

## Conformance corpus

A change to the format is checked by [`conformance/`](conformance/README.md).
Each self-contained case records the verdict of the strict schema layer, the
helper (`skills/mlview/scripts/artifact.py`) and the extension's validator
(`vscode-extension/src/workflowDocument.ts`).
`tools/test_workflow_conformance.py` runs the schema and helper layers and the
checks of every sample diagram and of the
[test documents](conformance/documents/README.md).
`vscode-extension/test/conformance.test.js` runs the extension layer, checks
the parity invariant against the helper, and loads every document the helper
publishes from the corpus.
[CONTRIBUTING.md](../CONTRIBUTING.md#changing-the-format) lists the places
that a change to the format touches.

Two classes of disagreement between the helper and the extension are
accepted, and the corpus records each case of them.
[Accepted divergences](conformance/README.md#accepted-divergences) describes
both.

The viewer turns a document into a model of its own before it draws.
That model is not a second format.
