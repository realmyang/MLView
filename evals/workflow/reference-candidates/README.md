# Pilot reference review packet

**Draft, 2026-09-17 — human review pending.** Eight Sol development-agent
ledgers contain 93 candidate facts and 106 source anchors. They were prepared
from pinned source without importing or executing target code, inspecting
held-out model outputs, or tuning the skill. They are review inputs, not
human-authored ground truth or native-host pilot artifacts.

Start with [what the pilot owner needs to review](REVIEW_GUIDE.md) for a concrete
checklist, a ten-fact starting task and a plain-text decision template.

## Candidates

| Ledger | Proposed scenario | Facts | Anchors |
|---|---|---:|---:|
| [nanoGPT](pilot-nanogpt.json) | Source defaults; no config-file or CLI overrides | 10 | 11 |
| [Transformers](pilot-transformers.json) | Pinned README's MRPC/BERT training and evaluation command | 11 | 12 |
| [scikit-learn](pilot-sklearn.json) | Iris nested/non-nested cross-validation example as written | 11 | 11 |
| [Flax](pilot-flax.json) | MNIST via `main.py` and `configs/default.py` | 12 | 13 |
| [Diffusers](pilot-diffusers.json) | Pinned README's Stable Diffusion v1-4 Naruto fine-tuning command | 13 | 17 |
| [MMDetection](pilot-registry.json) | Faster R-CNN R50/FPN COCO config and four inherited bases; no optional overrides | 12 | 16 |
| [CleanRL](pilot-rl.json) | PPO defaults, including termination/truncation handling | 12 | 13 |
| [Housing notebook](pilot-notebook.json) | Main narrative, zero-based cells 0–220; exercise solutions excluded | 12 | 13 |

Each JSON supplies the commit, scenario arguments, stable fact IDs, proposed
basis/essential status, source excerpts, unknowns and candidate non-defects.
File anchors use one-based line numbers. Notebook anchors add a zero-based cell
index and count lines within that cell's source.

All eight checkout HEADs match [the task manifest](../tasks.json). Independently,
every cited file's bytes match its pinned Git blob, and the artifact helper's
path/notebook/exact-excerpt checks passed for all 106 anchors. This establishes
source integrity, not claim correctness or completeness. The ignored check
record is `.mlview/reference-candidate-validation.json`.

These ledgers contain attributed excerpts of third-party source. The pinned
repository and license for each ledger are listed in
[`THIRD_PARTY_NOTICES.md`](../../../THIRD_PARTY_NOTICES.md), and exact pinned
license texts and source notices are stored in [`licenses/`](licenses/README.md).
Preserve that directory when copying or publishing the review packet; the ledgers are not
part of MLView's binary or standalone-skill distributions.

MMDetection's five selected config files were initially missing from its local
partial checkout. They were retrieved from the exact pinned GitHub revision;
all five blob hashes match that revision's tree. External MMEngine behavior,
pretrained weights, datasets and the Diffusers scheduler's prediction mode
remain qualified where local source cannot establish them.

## Review before freezing

The [evaluation protocol](../README.md) requires source-based human reference
review before inspecting pilot outputs. A reviewer should:

1. Approve or replace each scenario and its arguments. Set a concrete Flax
   workdir such as `./workdirs/mlview-mnist`; this is an analysis scenario,
   not permission to execute training.
2. Check each claim against its anchors, correct its basis, and accept,
   qualify or reject it. Add omitted essential behavior and relationships;
   these 93 candidates are not a pre-approved recall denominator.
3. Review unknowns/non-defects and identify real defects with counter-evidence
   and severity. Exact quotes alone do not establish defects.
4. Record the human reviewer's name, decision and immutable reference revision.
   Freeze essential-fact IDs and their denominator before seeing outputs.
   Keep disputes visible; another model's opinion is not human acceptance.

The candidate files and `tasks.json` intentionally retain pending review
statuses. Development-task semantic adjudication is separate and also remains
outstanding.

## Proposed common run policy

This is a concrete proposal for the pilot owner to freeze with the human
references. It has not started any runs or changed their budgets.

- **Prompt:** invoke MLView, give the exact manifest prompt, then append a
  `Selected scenario` block with the approved description, entrypoints,
  arguments and notebook bounds. Finish with: “Inspect source without importing
  or executing target code. Use this assistant as the interpretation backend;
  do not delegate to subagents or use the legacy static analyzer. Publish one
  WorkflowDocument using the installed helper, then report its path, revision,
  unresolved cases and repair rounds.” Save the fully expanded prompt before
  runs. Do not include reference facts or another host's artifact in context.
- **Isolation:** one fresh native VS Code assistant session per run, with the
  same pinned source and installed skill bytes. Keep reference ledgers, prior
  outputs and other hosts' conversations outside that workspace. Assign output
  paths by run ID. Use all 8 tasks × 3 hosts × 3 repetitions.
- **Analysis budget:** 20 minutes of active elapsed analysis per run, including
  critique and repair. Record wall time and approval-wait time separately.
  Preserve cancellation/limit events and partial outputs; do not silently
  restart a failed attempt or replace it with a successful repetition.
- **Repairs:** at most two validator repair rounds, matching the skill. Record
  citation/schema repairs separately from patch failures, approval waits and
  semantic self-critique. Do not hand-edit scored artifacts to make them pass.
- **Models and usage:** fix exposed model/reasoning settings per host and record
  host/extension versions. Use Copilot Auto only if explicitly chosen for that
  condition; a hidden resolved model stays unknown. Record exposed usage;
  do not estimate tokens or claim equal token budgets across opaque hosts.
  This compares configured native-host workflows, not isolated models.
- **Outcome:** independently validate artifacts and check native UI, then obtain
  the protocol's human claim ledger. Preserve failed/missing runs and explicit
  deviations. Keep baseline conditions separate from the 72 skill runs.

The local matrix `.mlview/pilot-runs.json` contains **72 pending records, zero
completed runs and zero human reviews**. Its stored prompts are manifest drafts;
replace them with frozen expanded prompts before execution. Planning or
summarizing the matrix is not a model run.

## Candidate implementation snapshot

The following hashes preserve the original 2026-09-17 drafting snapshot. They
describe the then-uncommitted tree and must not be mistaken for the semantic-
quality candidate selected for follow-up evaluation.

| Material | SHA-256 |
|---|---|
| Four-file canonical skill bundle | `b973aa623b3b68cd22b001446c268e097178569815f457b7e770da75d4c42b5c` |
| Current task manifest | `cc878da33f90906a09289eb61966fbfd407ac6a648071c43b6eba7447ab59ed1` |
| Locally installed VSIX | `69dbcd1dfc67413df33346b368696c5c6af7c79134afa6d5f000fa17f7ffea95` |

The bundle hash concatenates sorted skill-relative UTF-8 paths, NUL, file bytes,
NUL for `SKILL.md`, `scripts/artifact.py`, `references/WORKFLOW_CONTRACT.md` and
`references/workflow-example.json`. Tests/caches are excluded. Record reference
and expanded-prompt hashes after review, not from these drafts.

The current semantic-quality candidate is an uncommitted change based on
`766d9cc`. That base commit passed all 13 remote CI jobs in push run
`35282332067` and pull-request run `35282336685`; those runs predate and do not
validate the candidate. Its frozen four-file skill bundle SHA-256 is
`837358d2689890ec663dfebac57092c369db02d6e75a9229953776b1b5f2e29b`.
Six fresh GAN/notebook native follow-ups used those bytes. Four completed with
final UI evidence, Copilot GAN failed within its two-repair budget, and Copilot
notebook published a validator-clean artifact but still awaited final UI
observation. They remain development evidence and cannot approve these
reference candidates or establish that the candidate improved quality. The 24
held-out first runs and 48 repeat runs remain pending human review and freezing
of the scenarios, facts, denominators, unresolved cases, prompts, and run
policy. Human fields must remain pending until a named reviewer supplies those
decisions.
