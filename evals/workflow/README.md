# Evaluating LLM workflow understanding

[tasks.json](tasks.json) fixes eight development tasks and eight pilot tasks.
Pilot repositories are pinned to the existing public-corpus commits. They have
been used for static-analyzer testing; they are reserved from new skill tuning,
not claimed to be absent from model training or all prior project research.
Third-party source stays in the gitignored corpus; only URLs/commits are stored.

The pilot is **8 tasks × 3 native VS Code hosts × 3 fresh sessions = 72 runs**.
Run it in two predefined stages. Stage 1 is one fresh session for every
task/host pair (**8 × 3 × 1 = 24 runs**). Stage 2 contains the remaining two
fresh sessions for every pair (**8 × 3 × 2 = 48 runs**). Staging changes when
work is attempted, not the matrix or denominators: all 72 generated records
remain visible and pending until their native sessions and human reviews exist.
The schema/helper/renderer tests and developer-subagent smoke artifacts do not
count as native-host pilot runs. No pilot results or human-reviewed reference
facts are asserted by this manifest. Its reference status explicitly requires
human review.

The completed 2026-09-16–17 developer campaign is summarized in
[DEVELOPMENT_RUNS.md](DEVELOPMENT_RUNS.md). It records structural validation,
repair history, and authoring lessons without claiming native-host coverage or
human semantic scores.

[Reference candidates](reference-candidates/README.md) now provide source-linked
draft facts and concrete scenario proposals for all eight held-out tasks,
together with a proposed prompt/budget policy. They are AI-authored inputs to
human review, not frozen truth or completed pilot results. The
[readiness record](PILOT_READINESS.md) identifies the remaining gates.

## Before running

1. A reviewer inspects each pinned scenario and freezes essential workflow facts,
   connections, config choices, unresolved cases, real defects and non-defects.
   Give each fact an ID and source anchors. Do this before inspecting outputs.
2. Freeze skill revision, prompts, budgets and reference revision. Use the same
   question/budget for each host. If a task needs an additional config selection,
   settle it in the reference before runs. Do not silently choose one per host.
3. Generate an empty matrix, then record each actual session:

```sh
python tools/workflow_eval.py plan > .mlview/pilot-runs.json
python tools/workflow_eval.py summarize .mlview/pilot-runs.json
```

Create the output directory first. This tool prepares and summarizes records;
it never logs into a host, runs a model, or judges semantics. Keep sessions and
run artifacts outside committed source unless reviewed for redistribution.

Do not start Stage 1 until the human-reviewed references and implementation,
including the skill revision, prompts, budgets, host settings and repair rules,
are frozen. Run the 24 records whose `repeat` is `1`, retain every failure or
block, and complete source-based human adjudication for all 24 before deciding
whether to continue. Stage 1 proceeds to the 48 records whose `repeat` is `2`
or `3` only when its reviewed results meet every predefined target:

- 100% structurally valid published artifacts;
- 100% exact supplied anchors;
- at least 95% supported claims;
- at least 85% essential-fact recall;
- every known unresolved scenario explicitly qualified; and
- zero high-severity false accusations.

If any target misses, stop before Stage 2 and report the numerators,
denominators and failure taxonomy. Do not repair the skill against held-out
outputs and then count repeats as confirmation of the original frozen system.
An implementation or protocol failure that makes Stage 1 invalid requires an
explicit invalidation record and a newly frozen campaign; it is not a pass.
Passing Stage 1 authorizes collection of the repeats but does not establish
pilot success. The same targets apply to the complete 72 human-reviewed runs.

## Record and adjudicate

Record host/extension/model versions (unknown where hidden), skill revision,
commit/config, exact prompt, artifact and SHA-256, elapsed time, repair rounds,
failure/cancellation state, native UI log and observable usage. Complete the
[live UI checklist](../../docs/LLM_WORKFLOW.md) separately from semantic scores.

Count factual assertions in node details, edge meanings, findings, scenario
choices and coverage summaries as claims. Map equivalent wording/grouping to
reference facts; do not score JSON similarity or reward unresolved placeholders
as covered behavior. Maintain a claim ledger with artifact pointers, relevant
source, and supported/unsupported/qualified decisions.

A human review record supplies `reviewer`, `referenceRevision`, `claimLedger`,
and `{supported, total}` counts for `observedClaims`, `inferredClaims`,
`essentialFacts`, and `anchors`, plus `highSeverityFalseAccusations`. For anchors,
count supplied navigable references; unlocated conceptual groups are excluded.
For essential facts, the denominator is the frozen task reference, not the
claims the model chose to make. Keep direct and inferred claims separate.
Record severity agreement, unknown handling, and task usability in the ledger.

The initial pilot targets are 100% valid published structure and exact anchors,
95% supported claims, 85% essential-fact recall, all known unresolved scenarios
qualified, and no high-severity false accusation. They are **targets, not
measurements**. A complete matrix does not itself mean these targets passed.
Report per-host/task results and numerators/denominators; repeated runs on the
same eight tasks are not 72 independent tasks.

No Stage 1 or Stage 2 run has been completed or human-reviewed. None of the
targets above has passed; they remain stop/go criteria rather than measurements.

Compare the same tasks with a native assistant without the skill. The static
product is retired and is not an active evaluation condition. Keep those conditions in separate records; do not mix them
into the 72 skill runs. A second model may help locate disputed claims but
cannot replace source-based human adjudication. Missing or blocked runs stay
visible and never count as passes.

## Source fixture locations

Current development entrypoints are listed in `tasks.json`. Source examples
formerly under the removed analyzer now live in `fixtures/`. Recorded native
outputs keep their original citation paths and hashes; the evaluation-only
`fixtures/historical-paths.json` mapping resolves moved files and verifies their
original bytes. This mapping is not used by the product validator or viewer.
Open historical artifacts against their recorded source revision for live
navigation; the current `samples/configured_training.mlview.json` example uses
paths that remain valid in this checkout.

The eight held-out repository pins are in `repositories.json`. Fetch only the
source needed for an evaluation with `python tools/fetch_workflow_repos.py`
from the repository root, optionally `--repo nanoGPT`. This is an explicit
network operation and never runs analysis or executes fetched code. Existing
dirty or differently pinned checkouts are refused rather than reset.
