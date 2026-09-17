# Implemented semantic-quality candidate

This document records the MLView semantic-quality candidate prepared in this
change on top of base commit `766d9cc`. The base commit passed all 13 remote CI
jobs in push run `35282332067` and pull-
request run `35282336685`; those runs predate and do not validate this candidate.
The evidence set contains twelve native development artifacts and their model-
provisional review ledgers, plus three matched no-skill baseline comparisons.
No claim or usability rating has been human adjudicated, and this document does
not report an accuracy score, host ranking, improvement, or pilot result. The
original ledgers are review inputs, not a complete or approved fact set for the
candidate, and the changes do not guarantee improvement.

The evidence set is the [native artifact matrix](../evals/workflow/development/native-artifacts/README.md),
the [provisional review ledgers](../evals/workflow/development/native-reviews/),
and the [development protocol](../evals/workflow/development/README.md). The
candidate skill bundle has SHA-256
`837358d2689890ec663dfebac57092c369db02d6e75a9229953776b1b5f2e29b`.
That exact bundle is frozen for six fresh native follow-ups: the GAN and
notebook tasks in Copilot, Codex, and Claude Code. Their current outcomes are:

| Host and task | Outcome |
|---|---|
| Codex GAN | Completed in 5m44s as `rev-dev-gan-20260918-01`; first validation passed with zero repairs. |
| Codex notebook | Completed in 5m23s as `rev-leak-out-of-order-20260918`; first validation passed with zero repairs. |
| Claude Code GAN | Completed as `dev-gan-r1`; first validation passed with zero repairs. Five pre-validation critique corrections tightened claim and citation boundaries. |
| Claude Code notebook | Completed as `rev-dev-notebook-20260918-1`; first validation passed with zero repairs. Five pre-validation critique corrections tightened iteration, recorded-order and inference boundaries. |
| Copilot GAN | Failed: the initial validation and both allowed repair rounds produced invalid JSON. A third repair began but was stopped to enforce the two-repair limit; the deviating draft is preserved and unpublished. |
| Copilot notebook | Validator-clean revision `rev-leak-out-of-order-1` published after two repairs as `workflow.mlview.json`; final native UI observation remains pending after desktop attachment failed. |

These are development checks only. Four have confirmed final UI evidence, one
failed within its repair budget, and one has a published artifact with final UI
evidence pending.

The [preserved follow-ups](../evals/workflow/development/quality-followups/README.md)
include five byte-identical valid artifacts, the failed draft, provenance and a
source-linked provisional comparison. The results are mixed: the Codex outputs
address the targeted logging and notebook gaps, while Copilot's notebook still
falsely says execution counts are absent despite recorded counts `1,3,2,4`.
Claude's notebook overstates the certainty of optimistic evaluation bias, and
some Claude GAN labels still mix source observations with framework-dependent
claims. These are review findings, not human-adjudicated scores.

Before another candidate batch, investigate why notebook metadata was missed
and why malformed JSON repairs failed. A focused improvement would make raw
notebook metadata inspection explicit and return actionable JSON parser
locations. Preserve this batch as the comparison point and freeze any changed
bundle separately. Neither a new prompt nor a repaired draft should replace a
failed result in this batch.

Local checks of the current candidate passed 51 focused tests plus four
subtests and all 10 `tools/verify.py --all` gates. The shared distribution ZIP has
SHA-256 `7a3ab6a9fe01e72237c5496c83e0c298cecb21c1802738799829e5078601a7d8`;
the Claude distribution ZIP has SHA-256
`0c62b2fe8c8ff0902e85ef3414bd62769c5367de60b73c23ffc8be314cfd2e7c`.
The Claude GAN diagram opened with its recorded 38 nodes, 67 edges and two
findings; its 4416×4416 whole-diagram PNG was saved and visually inspected.
Packet content, escaping and capture hashes were checked, but browser visual QA
of the local HTML packet was blocked by file-URL policy and is not claimed.

## Implemented scope and priorities

The candidate strengthens the skill's final self-critique. The most
recurring provisional failure is not an incorrect high-level flow; it is a
failure to distinguish source-observed facts from framework behavior, runtime
preconditions, and unavailable implementations. GAN gradient effects were
several times labeled observed even though they depend on autograd semantics or
unseen network definitions. The grouped-CV case showed the same boundary when
imported feature engineering and target-encoder implementations were absent.
The self-critique requires a last pass over every behavioral claim and
finding: either cite inspected implementation, mark it inferred and name the
assumption, or leave it unresolved.

It also requires an explicit omission scan before publication. The provisional
reviews repeatedly identified material negative facts that a compact artifact
missed: an unused holdout, preprocessing fitted before a split, a missing
`zero_grad`, no evaluation or persistence, dead running-loss accumulators, and
an output directory that source never creates. The scan asks separately
about data preparation, fit/update ownership, loss and gradient handling,
evaluation consumption, outputs, and runtime prerequisites. Absence should
become a finding only when source establishes it and it matters to the request;
otherwise it belongs in coverage or an unresolved node.

Output semantics are now literal. Two GAN artifacts described running sums
as the printed values even though the source prints current-batch losses. A
final output audit traces each reported, saved, returned, or displayed
value to the exact expression at its sink, and should call out computed values
that are never consumed when that changes the reader's interpretation.

Notebook-specific guidance now requires analysis to state
source order and recorded execution order independently, avoid assuming a
second loop iteration when input cardinality is unknown, and inventory which
created splits or metrics are actually used. This is the largest provisional
coverage gap in the matrix: one compact notebook artifact omitted the
fit-before-split risk, unused test partition, missing gradient clearing, absent
evaluation, and unresolved input contract together.

The candidate also preserves the strengths already visible across the matrix. Configured
training artifacts consistently separated teacher and student state, both loss
terms, validation, output, and unknown external files. Grouped-CV artifacts
usually separated fold fitting, validation application, final refit, and
holdout evaluation. The changes add qualification and omission checks
without forcing every workflow into a larger diagram or turning normal design
choices into defect findings.

## Candidate quality questions and acceptance

The follow-up comparison should use the same source snapshots and task requests
as the initial development matrix. Reviewers compare meaning rather than JSON
shape or node count.

| Question | Candidate acceptance for a provisional before/after comparison |
|---|---|
| Does the artifact separate observed source from library or runtime behavior? | Initial overstatements identified in the GAN, notebook, and grouped-CV ledgers are qualified or unresolved in the follow-up artifact, without weakening directly observed claims. |
| Does it find material omissions named by the review? | GAN follow-ups address the printed-current-loss behavior, unused accumulators, and output-directory precondition. Notebook follow-ups address fit-before-split scaling, unused holdout, absent gradient clearing, absent evaluation/output, and the external data contract. |
| Are outputs described from their actual sink expressions? | The follow-up never says running sums are printed when the print expression uses current losses, and distinguishes selected writes from successful runtime creation. |
| Are fit and update owners explicit? | Optimizer membership, fitted preprocessing scope, validation-only application, and final refit ownership remain answerable without relying on an unstated framework assumption. |
| Are evaluation boundaries and unused partitions visible? | Inner validation, independent holdout, and any created-but-unused test partition are represented or explicitly noted. |
| Is uncertainty usable? | Missing imports, external files, unknown row counts, notebook runtime state, and conditional device behavior are attached to the affected claim, node, edge, finding, or coverage statement. |
| Did the change preserve concise successful behavior? | The configured-training explanation stays navigable and does not acquire speculative findings merely to satisfy a checklist. |

Meeting these candidate criteria after human adjudication would show that the revised guidance addressed
the named development failures. It would not establish general semantic
accuracy, cross-model parity, or readiness for the held-out pilot.

## Review packet and human gate

Generate the local review packet from the checked-in provisional material with:

```sh
python tools/workflow_eval.py review-packet \
  --reviews evals/workflow/development/native-reviews \
  --baselines evals/workflow/development/native-reviews/baselines.json \
  --baseline-captures .mlview/quality-20260918/baseline-captures.json \
  --output .mlview/quality-20260918/review.html
```

The optional capture mapping adds the ignored local native responses after
verifying their exact SHA-256 values. Omit `--baseline-captures` for a
reproducible public packet without raw captures; the capture packet escapes raw
text and marks it private. The command validates artifact identity and exact
source excerpts and renders places for human decisions. It does not adjudicate
the claims. A reviewer must
decide every material claim and all six usability questions, record rationale,
and review the three baseline comparisons before this candidate sprint can be
called an improvement.

The current evidence comprises twelve original skill reviews and three matched
baseline comparisons, all model-provisional and all awaiting human decisions.
The six fresh follow-ups test whether the implemented guidance changes the
targeted failure modes; they do not replace review of the original evidence or
authorize an improvement claim.

Only after that human review should the held-out pilot be staged. The first
stage is the protocol's 24 first runs: eight pinned held-out tasks across three
hosts. The 48 repeat runs remain blocked until the first stage is complete and
human-adjudicated against advancement criteria fixed before looking at held-out
results. Development follow-ups, valid JSON, exact citations, and successful
rendering do not count as held-out runs or semantic passes.

## Support evidence boundary

| Environment | Current evidence | Claim boundary |
|---|---|---|
| macOS local VS Code | Native Codex, Copilot, and Claude Code development invocations have published valid artifacts; the viewer has been opened, navigated, and refined in live development exercises. | Supported as development evidence on the recorded local setup. Semantic review is still pending, and the exercises do not establish broad model quality. |
| Windows local | Automated code paths and historical implementation work exist, but the current LLM workflow has no equivalent recorded native validation on Windows. | Pending native validation before a Windows compatibility claim. |
| Remote workspace | The workflow and extension design cover workspace-relative artifacts, but no recorded native remote-workspace exercise completes the live checklist. | Pending remote validation before a remote-workspace support claim. |

This boundary follows the [workflow guide](LLM_WORKFLOW.md): unit and integration
tests do not replace native assistant discovery, publication, navigation,
refinement, freshness, and recovery checks on each claimed platform.
