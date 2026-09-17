# Development semantic review workspace

The later [native artifact snapshots](native-artifacts/README.md) preserve five
fresh host-authored outputs. Their [run log](../../../docs/demo-logs/2026-09-17-development-native.md)
records publication results and the desktop-control interruption; they are
separate from the four provisional smoke reviews below.

This directory turns the four existing development smoke artifacts into review
candidates. The reviews are model-authored triage, not human adjudication or
accuracy scores. Every claim and usability answer remains explicitly pending a
human decision. Original artifacts stay unchanged at these current ignored
paths:

- `.mlview/development-smoke/configured-training.mlview.json`
- `.mlview/development-smoke/dev-sklearn.mlview.json`
- `.mlview/development-smoke/dev-gan.mlview.json`
- `.mlview/development-smoke/notebook.mlview.json`

After a content audit found no secrets, credentials, absolute machine paths,
private directories, or transcript content, byte-identical snapshots were
checked into [`artifacts/`](artifacts/). Reviews bind to those snapshots by
path, SHA-256, revision, task, and request so clean checkouts can validate them.
The ignored originals retain the same SHA-256 values and are not rewritten or
required by tests.

The claim verdicts mean: `supported` is directly backed by inspected source;
`qualified` needs a boundary or depends on library/runtime behavior;
`unsupported` overstates its cited evidence; and `omitted` is useful source
behavior absent from the artifact. These are candidates for human review. They
must never be aggregated as human precision, recall, approval, or pass/fail.

The usability rubric asks whether a reader can answer six questions from the
rendered workflow: where data originates; what parameters or fitted state
change; what losses are computed; where evaluation boundaries lie; what outputs
are produced; and what remains uncertain. Reviewers judge the answer's clarity
and correctness, not JSON field or source-text similarity.

Run `python tools/workflow_eval.py development-plan` to emit 12 pending skill
runs (four tasks across Copilot, Codex, and Claude Code) plus three matched
`dev-config` baseline runs without MLView. They remain pending until a native
host session supplies an artifact and UI log. The held-out `plan` command still
emits the unchanged 72-run matrix. After development review, the held-out pilot
may be staged as 24 first runs followed by 48 repeats; this is a protocol only,
and no held-out run is launched or credited here.

Each native record keeps the generated `id`, `task`, `host`, `condition`, and
`prompt` unchanged. A non-pending record supplies workspace-relative paths and
SHA-256 values for `responseLog` and `liveUiLog`, plus `workspace`,
`hostVersion`, and `model`. `failed` and `blocked` records also require a
`failureReason` and cannot carry a provisional review. A `completed` skill run
additionally requires `skillRevision`, `artifact`, and `artifactSha256`; the
artifact must be a WorkflowDocument 1.0 revision. A completed baseline has no
MLView artifact. Optional `provisionalReview` is a workspace-relative file;
`humanReview` remains null in every development record. Paths must remain
inside the workspace after symlink resolution. A structurally valid record
does not prove that a native UI action succeeded: the recorder must assign the
real status and preserve the corresponding logs.

Summarize evidence-backed statuses without semantic scores with:

```sh
python tools/workflow_eval.py summarize-development .mlview/development-runs.json
```

Validate provenance with:

```sh
python tools/workflow_eval.py validate-development evals/workflow/development/*.json
```

This checks pending status, review shape, evidence IDs, and exact source quotes.
It does not execute targets, import ML frameworks, or decide whether a claim is
semantically correct.

## Failure taxonomy

Use one or more of these labels during human review: `fabricated-behavior`,
`wrong-data-lineage`, `wrong-fit-or-update-owner`, `wrong-loss-or-gradient`,
`wrong-evaluation-boundary`, `wrong-output`, `unqualified-inference`,
`false-defect`, `missed-essential-behavior`, `misleading-emphasis`, and
`unusable-uncertainty`. Anchor failures remain structural validation failures
and are tracked separately from semantic failures.
