---
name: mlview-triage
description: Triage the machine-learning defects MLView detected — data leakage, broken training loops, dishonest evaluation, reproducibility gaps — by reading the cited source and proposing a concrete fix for each. Use when asked what is wrong with ML/PyTorch/scikit-learn training code, whether there is data leakage, why a model is not learning, or to review an ML change before merging. Proposes fixes; never applies them.
---

# Triaging MLView findings

## The contract with the user

**This skill never edits a file.** It reads, judges, and proposes. Applying a fix
is a separate, explicit request, and even then the user chooses which ones.
An ML defect is often deliberate — gradient accumulation looks exactly like a
missing `zero_grad()` until you read the modulo guard — so an auto-edit here is a
silent regression.

## The loop

1. **`mlview_issues`** — the findings with `file:line`, message, fix hint and
   `related` sites. Start at `minSeverity: "high"`; widen only if the user asks.
   (Fallback without MCP: `python -m mlview issues <path> --json`.)
2. **`mlview_explain` with `code`** — for any rule you are about to report, pull
   its documentation. It carries the known false-positive traps, which is what
   stops you from confidently reporting a non-bug. The page ships **inside the
   plugin** (`claude-plugin/docs/rules/`) and is deliberately never read from the
   repository being analyzed, so the code under review cannot supply its own
   definition of the rule that is flagging it.
3. **Read the actual source.** Every finding is a claim about specific lines.
   Open them. `mlview_explain` with the `nodeId` returns up to 60 lines of the
   real source plus the node's edges, which is usually cheaper than a `Read` and
   always in sync with the graph.
4. **Judge, then rank.** For each finding decide: *confirmed*, *false positive*,
   or *needs the author*. Rank by consequence to the model, not by rule severity.
   A leaked `StandardScaler` invalidates every number in the paper; a missing
   `random_state` costs a rerun.
5. **Propose.** One fix per confirmed finding, as a small diff or a precise
   instruction naming the real API, anchored at `file:line`.

## Verifying a finding before you report it

| Finding | What to confirm in the source before agreeing |
|---|---|
| Leakage (MLV1xx) | The fit really precedes the split *on the same data*, and no `Pipeline` re-fits per fold. |
| Train loop (MLV2xx) | No `zero_grad` under a modulo guard (gradient accumulation), no `set_to_none` variant, no Lightning / HF `Trainer` owning the loop. |
| Evaluation (MLV3xx) | The model genuinely has dropout or batch-norm; `torch.no_grad()` is not applied by a decorator or an outer context. |
| Loss (MLV4xx) | The activation really reaches the criterion — `CrossEntropyLoss` wants logits, `NLLLoss` wants log-probabilities. |
| Device (MLV5xx) | The batches are not moved inside a helper, or by the loader's `collate_fn`. |
| Reproducibility (MLV6xx) | No seed is set in an imported module or a config entry point. |

The analyzer already applies these gates and de-rates confidence when a scope is
`dynamic` or a framework wrapper is present, so a `certain` finding rarely needs
re-litigating — but a `possible` or `speculative` one always does.

## Reporting

For each finding, four short lines:

- **What** — `MLV201 · high · train.py:44` and the rule's own message.
- **Why it matters** — the consequence to the model, in one sentence, in ML terms.
  ("Gradients accumulate across batches, so every update is the sum of all
  previous ones and training diverges silently.")
- **Fix** — the concrete change, naming the API. Show the two or three lines.
- **Confidence** — the bucket, plus your own verdict after reading the source, and
  what would settle it if you are unsure.

Close with what you did *not* find: the checks that came back clean are the part
that earns trust in the ones that did not.

Then stop. Ask whether to apply any of it.
