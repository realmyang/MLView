# WorkflowDocument conformance corpus

The rules of WorkflowDocument 1.0 are written three times: in the normative
[schema](../workflow.schema.json), in the helper
(`skills/mlview/scripts/artifact.py`) and in the extension's validator
(`vscode-extension/src/workflowDocument.ts`). This corpus records, per case,
what each of the three layers must say, so a rule that a case pins fails a
test when it changes in one layer and not the others.

- `cases/<area>-<nnn>-<slug>.json`: one self-contained case per file.
- [`documents/`](documents/README.md): eight generated test documents and the
  small workspace they cite, for the checks of whole documents below.
- [`helper_bridge.py`](helper_bridge.py): the bridge. It materialises a
  case and reports the helper and strict schema results. Both runners use it.
- [`tools/test_workflow_conformance.py`](../../tools/test_workflow_conformance.py):
  the schema and helper layers, the helper half of the round trip, and the
  checks of whole documents.
- [`vscode-extension/test/conformance.test.js`](../../vscode-extension/test/conformance.test.js):
  the extension layer, the parity invariant on actual results (through the
  bridge), and the helper-to-extension round trip.

```sh
python -m pytest tools/test_workflow_conformance.py -q
cd vscode-extension && MLVIEW_PYTHON="$(command -v python)" MLVIEW_REQUIRE_PYTHON=1 npm test
python contracts/conformance/helper_bridge.py contracts/conformance/cases/shape-001-node-parent-null.json
```

Both runners are part of `sh scripts/e2e.sh`, which sets `MLVIEW_PYTHON` and
`MLVIEW_REQUIRE_PYTHON=1`. Without Python, the extension runner skips its
parity and round-trip tests, or fails them when `MLVIEW_REQUIRE_PYTHON=1`.

[docs/validation.md](../../docs/validation.md) says what the automated checks
do not show. The corpus does not cover the panel's revision acceptance
(`revision-lineage`, `authored-lineage` and `refine-wedge` tests in
`vscode-extension/test/`) or the webview projection. It records codes, not
messages: the structured error fields, the warning cap, the `basis` summary,
`excerpt` and multi-record `upsert` are covered by the helper's unit tests
(`skills/mlview/tests/`).

## Case format

Runners materialise every case into a fresh temporary workspace. Byte-exact
fixtures (a BOM, CRLF, Latin-1, binary files, a file over 8 MiB) therefore
never exist as committed files an editor could normalise, and `.mlview/`
paths, which `.gitignore` ignores at any depth, can still be tested.

| Key | Meaning |
|---|---|
| `id` | Equals the file stem: `<area>-<nnn>-<slug>`. `area` is one of `shape`, `path`, `evidence`, `notebook`, `fingerprint`, `freshness`, `encoding`, `revision`, `size`. `nnn` is three digits, unique within the area. The slug is lowercase kebab-case. |
| `description` | A short text: what the case asserts. |
| `files` | Workspace-relative POSIX path → `{"text": s}` (written as UTF-8 with no newline translation), `{"base64": b}`, or `{"generate": {"bytes": n, "fill": c}}` (`c` is one ASCII character). No symlinks and no case-only siblings. Do not list the artifact itself. |
| `artifact` | Where the runners write the artifact (it ends in `.mlview.json`): `raw` verbatim, otherwise `document` as indented JSON. |
| `document` / `raw` | Exactly one. `raw` is the exact JSON text, for spellings a parsed object cannot carry: duplicate members, `1.0` integers, a leading BOM. Keep `raw` valid Unicode: write unpaired surrogates only as `\u` escapes. |
| `expect` | `schema`, `helper` and `extension`, below. |
| `divergence` | `null`, or `{"layers", "note", "status": "accepted"}` whose note starts with `Accepted class 1:` or `Accepted class 2:` (see below). |

`{"$sha256": {"text": s}}` and `{"$sha256": {"base64": b}}` placeholders,
anywhere in `document` or `expect.helper.fingerprints`, are replaced by the
lowercase hex SHA-256 of those bytes before any layer runs. Never type a
digest by hand.

Expectations:

- `expect.schema`: `valid`, `invalid` or `skip`, under the strict schema layer
  (Draft 2020-12, full-match `pattern`, RFC 3339 `date-time`; see
  [contracts/README.md](../README.md)). A `raw` that does not parse as JSON is
  `invalid`.
- `expect.helper`: `{ok, codes, warnings, fingerprints, stale}` from
  `artifact.validate(doc, root, warnings=w)`. `codes` and `warnings` are the
  exact sets of error and warning codes; the hygiene warnings
  (`unreferenced_evidence`, `isolated_node`, `self_edge`, `wide_evidence`,
  `evidence_overlap`, `duplicate_inspected`) are computed only for a document
  without errors. A `raw` is parsed the way the CLI parses a draft (strict
  UTF-8, no `NaN` or `Infinity`, at most 64 levels of nesting). A repeated
  member gives `invalid_json` plus the codes of validating the value that
  keeps each member's last occurrence, as the CLI reports them, with no
  warnings; any other `raw` the parser rejects gives
  `codes: ["invalid_json"]`. `fingerprints` is the exact hash map, or `null`
  for "not checked". `stale` is the set of `file` fields on `stale_source`
  errors.
- `expect.extension`: `{ok, stale, issuePaths}`. The artifact is read the way
  the panel reads a candidate revision: `readArtifactFile`, strict UTF-8 that
  keeps a leading BOM, `JSON.parse`, the same 64-level nesting bound, then
  `validateWorkflow(value, root)`. `ok` means a validated value was returned,
  `stale` is the sorted `stale[].rel`, and `issuePaths` is the exact set of
  issue paths. A `raw` that does not parse, or is nested more deeply, gives
  `{ok: false, stale: [], issuePaths: ["$"]}`.

No expectation may be `"unverified"` and no divergence may be `"open"`. Both
runners fail on either. Case files are ASCII JSON (indent 2, non-ASCII as `\u`
escapes) of at most 100 KB.

## Parity invariant

The extension runner checks these on actual results, for every case whose
`divergence` is `null`. The Python runner checks P1 and P3 on the committed
expectations.

- **P1.** If the extension reports no stale file, the helper and the extension
  agree on `ok`.
- **P2.** If both are ok and nothing is stale, the extension's `fingerprints`
  equal the helper's hash map.
- **P3.** If both are ok, the schema layer says `valid` (unless `skip`). The
  schema cannot express workspace rules, so a schema-valid document can still
  be invalid; the implication runs one way only.

P1 and P2 do not apply to a case with a non-empty `expect.extension.stale`;
it is not a divergence. The layers answer different questions. The helper
validates authoring: a missing tracked file is `path_outside_workspace`, a
changed fingerprint is `stale_source`, and a fingerprint for an
inspected-only file over 8 MiB is ignored with `not_fingerprinted`. The
extension checks a published revision's freshness, and the diagram is shown
as historical, with that file stale.

## Round trip

Every case whose helper expectation is ok, with no `verification`, no `raw`
and no divergence, is published with the real CLI, `artifact.py publish
.mlview/llm/run/draft.json --workspace <tmp> --output <artifact>`. The
extension runner validates the published bytes: they must be ok, with no stale
file and `fingerprints` equal to `verification.files`. The Python runner
re-validates the published artifact with the helper.

## Whole documents

Three suites check whole documents next to the single-rule cases: every
sample diagram `samples/<name>.mlview.json` and the eight test documents in
[`documents/`](documents/README.md). Each suite reads every sample diagram it
finds and requires at least one. It lists the test documents by name, so a
missing test document fails, and it requires `documents/workspace/` to hold
exactly the eight. `tools/test_conformance_documents.py` requires that every
other `*.mlview.json` file that git tracks is a sample diagram beside its
folder `samples/<name>/`. `tools/test_samples.py` requires that git tracks
exactly the sample diagrams that its table lists, so a new sample diagram
fails until it is listed.

- `tools/test_workflow_conformance.py` checks that every sample diagram, the
  eight test documents and the bundled skill example
  `skills/mlview/references/workflow-example.json` are valid under the strict
  schema layer and pass the helper's structural checks (`_basic_shape`,
  `_references`). It also validates each test document in full against
  `documents/workspace/`: paths, hashes and quotes.
- `skills/mlview/tests/test_documents.py` runs the helper's structural checks
  over every sample diagram and the eight test documents and validates each
  test document in full.
- `vscode-extension/test/documents.test.js` runs
  `validateWorkflowStructure` over every sample diagram and the eight test
  documents and validates each sample diagram and each test document in full
  in the extension.

`tools/test_samples.py` validates each sample diagram in full against the
repository root: paths, hashes and quotes. It compares the diagram's producer
and the codes of the helper's warnings with its table, and it requires that
every file the diagram cites, lists as inspected, names as an entrypoint or
fingerprints lies under `samples/<name>/`.

`conformance.test.js` validates the bundled example in a temporary workspace.

The test documents are generated fixtures of 4 to 38 steps and 3 to 72
connections. They are not sample diagrams. `documents/generate.py` writes
them, and `generate.py --check` fails when the committed files differ from a
fresh run; [`documents/README.md`](documents/README.md) says how to change
them.

## Accepted divergences

Only these two classes may be recorded as `accepted`. Any other disagreement
is a bug in one layer.

### Class 1: JSON spellings `JSON.parse` cannot see

Duplicate member names, and integers written as `1.0` or `1e0`. `JSON.parse`
keeps the last duplicate and turns `1.0` into `1`, so the extension sees a
valid value; JSON Schema also counts `1.0` as an integer. The helper rejects
both (`invalid_json`, `range`), so it never publishes them. Integers must be
JSON integers.

### Class 2: an unfingerprinted inspected-only file in a verified document

A published document's `verification.files` covers every tracked inspected
file up to 8 MiB. A verified document can still list an inspected-only file
of up to 8 MiB without a fingerprint: for example after a hand edit, or
because the file was over 8 MiB when the document was published. The helper
validates authoring: the file must exist as a regular file, and it is hashed.
The extension checks published freshness only for fingerprinted files and
does not touch this one. A missing or non-regular file therefore fails in the
helper and passes in the extension. A present file passes in both, and only
the helper's fingerprint map contains it.

## Adding or changing a case

1. Pin one behaviour per case. Choose the area and the next free number.
2. Run every layer and record what it does:
   `python contracts/conformance/helper_bridge.py <case>` prints the helper and
   schema results, and the extension runner prints the extension result when it
   disagrees.
3. If the layers disagree outside the two classes above, fix the layer.
4. A change to the format updates, together: `contracts/workflow.schema.json`,
   `artifact.py`, `workflowDocument.ts` (and the revision rules in
   `revisionLineage.ts`), `webview/src/workflow.ts` when the change affects
   what the viewer draws, the two descriptions for readers (`docs/format.md`,
   `skills/mlview/references/WORKFLOW_CONTRACT.md`), and the cases.
