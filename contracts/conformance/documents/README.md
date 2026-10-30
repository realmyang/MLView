# Test documents

Eight WorkflowDocuments and the small workspace they cite. The validator tests
read them as whole documents, next to the single-rule cases in
[`../cases`](../cases).

They are test fixtures, written by [`generate.py`](generate.py). They are not
sample diagrams: they describe no real program and no model wrote them. Their
titles, questions and limitations say so. For a diagram that an assistant
wrote from an example project, see [`samples/`](../../../samples/README.md).

## The documents

| Document | Steps | Connections | Phases | Findings | What else it covers |
|---|---:|---:|---:|---:|---|
| `d01-minimal` | 4 | 3 | 3 | 0 | one source file; every claim observed |
| `d02-notebook` | 7 | 6 | 4 | 3 | six notebook cells cited with `cell`; a finding with counter-evidence and `edgeIds` |
| `d03-two-files` | 10 | 9 | 3 | 1 | two source files; one group of three steps |
| `d04-loop` | 12 | 15 | 5 | 2 | a connection of kind `loop` that goes back; inferred claims |
| `d05-groups` | 16 | 21 | 4 | 4 | four groups, two of them inside another; an unresolved finding |
| `d06-refinement` | 20 | 23 | 5 | 2 | `revision.parent`; coverage `partial`; unresolved connections without evidence |
| `d07-multi-file` | 28 | 41 | 6 | 2 | four cited files; three groups; a loop |
| `d08-dense` | 38 | 72 | 9 | 2 | five cited files; four groups; a loop; observed, inferred and unresolved claims |

A group counts as a step. Every document names `host` `unknown` and no model as
its producer.

## The workspace

`workspace/` is laid out like a user's workspace. Each document sits at its
root and cites paths relative to it.

- `pipeline/data.py`, `features.py`, `model.py`, `train.py`, `evaluate.py` and
  `export.py`: modules of three-line functions. A step cites one function.
- `notebooks/explore.ipynb`: six code cells.
- `pipeline/config.json`: every document lists it as inspected and no evidence
  cites it, so each document holds a fingerprint for a file without a quote.

No document cites `pipeline/export.py`. It stands for a workspace file that a
document does not track.

## Changing them

Do not edit a file under `workspace/` by hand. Change `generate.py` and run
it from the repository root:

```sh
python contracts/conformance/documents/generate.py
python contracts/conformance/documents/generate.py --check
```

The script publishes every document with the helper
(`skills/mlview/scripts/artifact.py publish`), so the helper checks each path,
hash and quote and writes `verification.files`. The script then sets
`verification.publishedAt` to `2000-01-01T00:00:00Z`, so that a second run
gives the same bytes. `--check` writes nothing. It exits 1 unless `workspace/`
equals a fresh run.

## Tests that read them

- `tools/test_conformance_documents.py` runs `generate.py --check` and pins
  the list of files and the size of each document. It also requires that
  every other `*.mlview.json` file that git tracks is a sample diagram
  `samples/<name>.mlview.json` beside its folder `samples/<name>/`, and that
  each of the three suites below names all eight.
- `skills/mlview/tests/test_documents.py`,
  `tools/test_workflow_conformance.py` and
  `vscode-extension/test/documents.test.js` list the eight documents
  by name. Each checks their structure and validates them in full against
  `workspace/`: paths, hashes and quotes.
- `webview/tools/layout-metrics.mjs --dev` measures how the viewer lays them
  out.
