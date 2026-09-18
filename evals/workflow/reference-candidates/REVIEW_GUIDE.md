# What the pilot owner needs to review

The pilot needs a human-checked answer key before any held-out model outputs
are inspected. The [packet](README.md) contains **93 draft facts and 106 source
anchors across eight tasks**. These are proposed references, not approved
answers. Passing code tests or approving development work does not approve them.

You can review the references yourself or nominate reviewers familiar with the
relevant frameworks. You do not need to run training, operate all the assistants,
edit JSON by hand, or prepare hashes. The agent can handle that bookkeeping and
the authorized native-host runs. Human semantic decisions remain attributable
to the person who actually checked the source.

## First: review one task at a time

Start with [nanoGPT](pilot-nanogpt.json), which has ten proposed facts. For each
task, review the exact pinned source revision and supply these decisions:

| Decision | What to check |
|---|---|
| Scenario | Are the entrypoints, arguments, defaults and excluded cases appropriate? The notebook draft covers cells 0–220; Flax still needs a concrete workdir. |
| Each fact | Accept, qualify with corrected wording, or reject it. Read the cited lines **and their context**, including conditions or configuration overrides. |
| Basis | Is the fact directly observed in source, an inference needing assumptions, or unresolved? Source code alone does not prove an actual runtime outcome. |
| Essential facts | Would omitting this fact materially weaken an answer to the task? Correct the proposed `essential` flags and add missing essential behavior. This defines the recall denominator. |
| Unknowns and non-defects | Are the listed limitations accurate? Is intentional behavior being mistaken for a defect? Any proposed defect needs evidence, counter-evidence and a severity decision. |

For example, `nanogpt-f02` proposes that the no-override scenario initializes
from scratch. Its anchor is `train.py:41`, where `init_from` is assigned
`'scratch'`. Review the surrounding configuration and initialization branches
before deciding whether the wording, `observed` basis and `essential: true`
are justified. This example deliberately does not supply the verdict.

Plain text is sufficient; use the existing task and fact IDs:

```text
Reviewer: <name>; date: <date>
Task: pilot-nanogpt
Scenario: <accept or replacement, with reason>
nanogpt-f02: <accept / qualify / reject>
Wording and reason: <decision, checked source, conditions or uncertainty>
Basis: <observed / inferred / unresolved>; essential: <yes / no>
Missing facts / unknowns / non-defects: <decisions, or still pending>
Task review: <complete / partial, listing unresolved items>
```

The agent can present source context in small batches and transcribe your
decisions into review records. Unreviewed facts stay pending. Keep disagreements
visible; a second reviewer is useful for high-severity judgments and disputed
claims. All task references must be settled before the planned eight-task
Stage 1 starts.

## Then: agree on the run policy

The [proposed policy](README.md#proposed-common-run-policy) needs an explicit
decision on exposed host/model/reasoning settings, the analysis budget, repair
limits, prompts, privacy and publication rules, and the stop/go criteria. The
current proposal is 20 active minutes and at most two validator repair rounds
per session, with 24 first-stage skill runs plus 24 matched no-skill sessions.
The remaining 48 skill repetitions depend on the first-stage review.

The agent records those decisions, freezes source and reference revisions,
essential-fact counts, expanded prompts and candidate hashes, then prepares the
run matrix. A hash identifies bytes; it does not supply human approval.

## After runs: review the outputs separately

The named reviewer then judges generated claims against the frozen references.
This produces the supported-claim, qualification, omission and false-accusation
counts. Do not change the reference facts or denominator after seeing a model
miss something. Approving the reference packet does not pre-approve any output.

See the [evaluation protocol](../README.md) and
[candidate protocol](../CANDIDATE_PROTOCOL.md) for the complete rules.
