# Candidate identity and paired evaluation

This extends the [pilot protocol](README.md) with reproducible candidate
identification and a separately planned no-skill comparison. It does not
approve references, freeze model settings, or start native-host sessions.

## Capture exact distributed bytes

Build and validate the current tree first. Then create a new snapshot:

```sh
python tools/workflow_candidate.py --output .mlview/candidate.json
python tools/workflow_candidate.py --check .mlview/candidate.json
```

Add `--vsix vscode-extension/mlview-0.1.0.vsix` when retaining a packaged VSIX.
The file must already exist. Snapshots cannot overwrite an existing record.
The skill identity covers **every distributed file**, including licenses and
optional references, using sorted skill-relative UTF-8 path, NUL, file bytes,
NUL. Each file also has its own SHA-256. Viewer JS/CSS, extension JS, schema and
task manifest have separate identities. Record host/extension versions and
model/reasoning settings separately from these bytes.

`--check` detects payload or component drift; success says nothing about human
approval. The source commit and dirty-tree flag describe capture time. A later
commit can preserve these exact bytes, so byte checks do not require the old
Git metadata to remain identical. Keep the source revision associated with
the selected snapshot before any scored runs. Old four-file bundle hashes in
historical records never identify the expanded current skill.

## Pair the first stage with no-skill responses

```sh
python tools/workflow_eval.py baseline-plan > .mlview/pilot-baselines.json
```

This prepares **24 additional pending sessions**: eight held-out tasks × three
hosts, first repetition only. They are separate from the existing 72 skill
runs. It neither generates model output nor changes the original matrix.
Prompts remain scenario-expansion drafts until approved references and run
settings are frozen. Finalize expanded prompts in the frozen task manifest
before creating the execution matrix; do not silently edit a run's pinned
prompt afterward. For baseline sessions, omit MLView invocation and artifact
publication instructions while keeping task/scenario, model/settings, source
pin and analysis budget matched. Isolate references and other outputs from
each fresh session. Decide whether further baseline repetitions are warranted
before seeing their results.

Compare semantic claims, essential-fact recall, task usefulness and elapsed
time. Artifact publication and diagram-navigation measures apply only to the
skill condition. Capture failures, cancellations and timeouts rather than
replacing them with successful retries. End-to-end completion uses all
assigned sessions as its denominator; semantic metrics on published artifacts
must be labeled separately. Omissions affect recall, not claim precision.

Before scoring, the human reviewer freezes claim boundaries, essential facts,
and how conditional claims count. Count a conditional claim as supported only
when the reviewer confirms both its conditions and conclusion, and report
qualified claims separately. Report task/host numerators and denominators;
repeated sessions on eight tasks are not independent task samples.

## Privacy and human decisions

Raw native captures stay in ignored local storage. Freeze what sanitized fields
may be published before collecting sessions. Retain capture hashes, whether
they were independently verified, source attribution, failed attempts and
deviations. Hashes alone do not prove that a capture is complete or reviewed.

The [reference packet](reference-candidates/README.md) has concrete draft
scenarios and source anchors. A named human must supply source-based decisions
and the frozen reference revision before the scored pilot. Model-generated
reviews, deterministic checks and this document cannot supply those decisions.

The existing 24-run Stage 1 and 48-run Stage 2 stop/go targets remain unchanged.
Stage 2 starts only after Stage 1 is adjudicated under the frozen policy.
