# WorkflowDocument conformance corpus

The rules of WorkflowDocument 1.0 are written three times: in the normative
[schema](../workflow.schema.json), in the helper
(`skills/mlview/scripts/artifact.py`) and in the extension's validator
(`vscode-extension/src/workflowDocument.ts`). This corpus records, per case,
what each of the three layers must say, so a rule that changes in one layer
and not the others fails a test.

- `cases/<area>-<nnn>-<slug>.json`: one self-contained case per file.
- [`helper_bridge.py`](helper_bridge.py): the Python side. It materialises a
  case and reports the helper and strict schema results. Both runners use it.
- [`tools/test_workflow_conformance.py`](../../tools/test_workflow_conformance.py):
  the schema and helper layers, the helper half of the round trip, and the
  recorded-artifact suite.
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

These are contract checks, run locally and in CI. They are not semantic
accuracy, human review or live-host validation. The corpus does not cover
the panel's revision acceptance (`revision-lineage`, `authored-lineage` and
`refine-wedge` tests in `vscode-extension/test/`) or the webview projection.

## Case format

Runners materialise every case into a fresh temporary workspace. Byte-exact
fixtures (a BOM, CRLF, Latin-1, binary files, a file over 8 MiB) therefore
never exist as committed files an editor could normalise, and `.mlview/`
paths, which `.gitignore` ignores at any depth, can still be tested.

| Key | Meaning |
|---|---|
| `id` | Equals the file stem: `<area>-<nnn>-<slug>`. `area` is one of `shape`, `path`, `evidence`, `notebook`, `fingerprint`, `freshness`, `encoding`, `revision`, `size`. `nnn` is three digits, unique within the area. The slug is lowercase kebab-case. |
| `findings` | IDs of the review findings the case pins, for example `CONTRACT-9`. |
| `description` | One or two sentences: the behaviour, and the old behaviour when it changed. |
| `files` | Workspace-relative POSIX path → `{"text": s}` (written as UTF-8 with no newline translation), `{"base64": b}`, or `{"generate": {"bytes": n, "fill": c}}` (`c` is one ASCII character). No symlinks and no case-only siblings. Do not list the artifact itself. |
| `artifact` | Where the runners write the artifact (it ends in `.mlview.json`): `raw` verbatim, otherwise `document` as indented JSON. |
| `document` / `raw` | Exactly one. `raw` is the exact JSON text, for spellings a parsed object cannot carry: duplicate members, `1.0` integers, a leading BOM. Keep `raw` valid Unicode: write unpaired surrogates only as `\u` escapes. |
| `expect` | `schema`, `helper` and `extension`, below. |
| `divergence` | `null`, or `{"layers", "findings", "note", "status": "accepted"}` whose note starts with `Accepted class 1:` or `Accepted class 2:` (see below). |

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
  exact sets of error and warning codes. A `raw` that the helper's parser
  rejects gives `codes: ["invalid_json"]`. `fingerprints` is the exact hash
  map, or `null` for "not checked". `stale` is the set of `file` fields on
  `stale_source` errors.
- `expect.extension`: `{ok, stale, issuePaths}`. The artifact is read the way
  the panel reads a candidate revision: `readArtifactFile`, strict UTF-8 that
  keeps a leading BOM, `JSON.parse`, then `validateWorkflow(value, root)`.
  `ok` means a validated value was returned, `stale` is the sorted
  `stale[].rel`, and `issuePaths` is the exact set of issue paths. A `raw`
  that does not parse gives `{ok: false, stale: [], issuePaths: ["$"]}`.

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

A case with a non-empty `expect.extension.stale` asserts each layer's own
expectations only; it is not a divergence. The layers answer different
questions. The helper validates authoring: a missing tracked file is
`path_outside_workspace`, a changed fingerprint is `stale_source`, and a
fingerprint for a file over 8 MiB is ignored with `not_fingerprinted`. The
viewer checks a published revision's freshness and shows it as historical,
with that file stale.

## Round trip

Every case whose helper expectation is ok, with no `verification`, no `raw`
and no divergence, is published with the real CLI, `artifact.py publish
.mlview/llm/run/draft.json --workspace <tmp> --output <artifact>`. The
extension runner validates the published bytes: they must be ok, with no stale
file and `fingerprints` equal to `verification.files`. The Python runner
re-validates the published artifact with the helper.

## Recorded-artifact suite

`tools/test_workflow_conformance.py` checks that every recorded
`evals/workflow/**/*.mlview.json`, the sample
`samples/configured_training.mlview.json` and the bundled skill example
`skills/mlview/references/workflow-example.json` are valid under the strict
schema layer and pass the helper's structural checks (`_basic_shape`,
`_references`). It also checks that the sample validates fully and fresh
against the repository root. `vscode-extension/test/recorded-artifacts.test.js`
runs `validateWorkflowStructure` over the same artifacts and validates the
sample fresh in the extension. `conformance.test.js` validates the bundled
example in a temporary workspace. Recorded artifacts are immutable evidence:
a rule change that breaks one is wrong, and the artifact is never edited to
pass.

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
file up to 8 MiB, so an inspected-only file without a fingerprint in a
verified document comes from a hand edit or an older tool. The helper
validates authoring: the file must exist as a regular file, and it is hashed.
The viewer checks published freshness only for fingerprinted files and does
not touch this one. A missing or non-regular file therefore fails in the
helper and passes in the viewer. A present file passes in both, and only the
helper's fingerprint map contains it.

## Adding or changing a case

1. Pin one behaviour per case. Choose the area and the next free number.
2. Run every layer and record what it does:
   `python contracts/conformance/helper_bridge.py <case>` prints the helper and
   schema results, and the extension runner prints the extension result when it
   disagrees.
3. If the layers disagree outside the two classes above, fix the layer.
4. A contract change updates, together: `contracts/workflow.schema.json`,
   `artifact.py`, `workflowDocument.ts` (and the revision rules in
   `authoredPanel.ts`), `webview/src/workflow.ts` when the projection is
   affected, the contract docs (`docs/WORKFLOW_CONTRACT.md`,
   `skills/mlview/references/WORKFLOW_CONTRACT.md`), and the cases.
