# Development workflow runs

**Campaign:** 2026-09-16–17. These eight runs exercise the canonical skill and
artifact helper against the development tasks in [`tasks.json`](tasks.json).
They were authored by Sol developer subagents through workspace tools. They are
not native Copilot, Codex IDE, or Claude Code pilot sessions, do not count
toward the 72-run host pilot, and have no human semantic adjudication or score.

The raw drafts and artifacts remain under gitignored `.mlview/development-smoke/`
and are not committed. After the campaign, the root agent independently ran the
helper against all eight final artifacts and current source fingerprints; all
eight revalidated. That establishes current structural and citation validity,
not semantic correctness.

| Task | Final revision | Nodes | Edges | Findings | Validator repairs | Post-validation critique |
|---|---|---:|---:|---:|---:|---|
| `dev-config` | `dev-smoke-configured-training-r1` | 17 | 19 | 2 | 0 | The initial developer artifact remained r1; subsequent review exposed misuse of a finding for correct behavior, described below. |
| `dev-notebook` | `dev-smoke-notebook-r1` | 11 | 10 | 2 | 1 | The repair changed one notebook citation `endLine` from 11 to 10 after `quote_mismatch`; no semantic rewrite. |
| `dev-hosted-training` | `dev-dev-hosted-training-r2` | 14 | 13 | 3 | 0 | r2 corrected a duplicated request entrypoint found during critique. |
| `dev-keras-jax` | `dev-dev-keras-jax-r2` | 15 | 15 | 3 | 0 | r2 corrected a duplicated request entrypoint found during critique. |
| `dev-gan` | `dev-gan-r1` | 12 | 12 | 0 | 0 | No post-validation artifact change. |
| `dev-multi-entry` | `dev-multi-entry-r1` | 10 | 11 | 0 | 0 | Critique retained the training-to-inference checkpoint link as inferred; no revision was needed. |
| `dev-pytorch` | `dev-pytorch-sol-2` | 10 | 8 | 5 | 0 | r2 added the exact `DEVICE = "cuda"` anchor to strengthen an existing finding. |
| `dev-sklearn` | `dev-sklearn-sol-1` | 8 | 8 | 0 | 0 | No post-validation artifact change. |

“Validator repairs” counts rounds prompted by helper errors. A new revision made
after a successful validation is listed separately as critique work. The helper
correctly caught the notebook range error, but it cannot determine whether a
schema-valid claim deserves to be a finding or whether a request lists the
right entrypoints. Those checks required semantic critique.

## Interpretation limits and lessons

The finding counts above describe unadjudicated model output. They must not be
reported as verified bugs, precision measurements, or passed accuracy targets.
The paired PyTorch sample, grouped-CV sample, alternating GAN, and multi-entry
scenario were useful checks for counter-evidence, clean guards, optimizer
ownership, and inferred checkpoint handoff. The hosted-framework and Keras/JAX
artifacts also showed that calls observed in local code must remain separate
from update behavior inferred from external framework APIs.

The first `dev-config` developer artifact illustrates the semantic limit most
clearly. It emitted a low-severity finding titled “Only the student is
optimized,” even though freezing the teacher and optimizing only the student is
the intended distillation behavior. That false use of the findings channel
prompted a skill correction: expected or correct behavior belongs in node
detail, and an empty findings array is valid. It is not counted here as a
verified defect. A later native Codex development exercise of the same scenario
produced a new 12-node artifact with zero findings; that separate run and its
limitations are recorded in
[`docs/demo-logs/2026-09-16-llm-workflow.md`](../../docs/demo-logs/2026-09-16-llm-workflow.md).
Neither output has been human scored.

Other recurring limitations were external dataset and checkpoint contents,
runtime tensor values, notebook kernel history, and trainer/framework internals
outside inspected source. Runs recorded those boundaries as coverage limits or
inference rather than treating uninspected behavior as observed.

The detailed developer notes, exact publish timestamps, and local timing remain
in the gitignored campaign directory. This checked-in summary intentionally
retains only the reproducible task identity, final artifact shape, repair
history, and lessons needed to design the native-host pilot and human review.

## Human adjudication of development reviews

The twelve native development artifacts recorded later (four tasks in each of
Codex, Claude Code and Copilot) have provisional, model-authored review
ledgers in [`development/native-reviews/`](development/native-reviews/README.md),
with three baseline notes. Those ledgers are immutable and are never edited to
record a human decision. The owner's verdicts go in
`evals/workflow/decisions/development-adjudication.md`: one line per claim and
usability answer, in sections whose tool-written `Ledger:` line binds them to
the ledger's bytes. Check it with
`python tools/workflow_eval.py check development-adjudication`. Until a named
reviewer completes that file, every development review remains provisional and
no development result has a human score. The run policy decides whether the
adjudication must be complete before the held-out Stage 1 starts.
