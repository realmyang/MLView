# Reference decisions: pilot-nanogpt

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-nanogpt
> Lines starting with ">" are written by the tool and ignored. Replace each "pending".
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:".

Candidate: pilot-nanogpt.json 9dded969253eab56a4f8de522a41a2ca3c8c41051d57faa0d0499d6c6c83b163
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Inspect train.py with its source defaults and no config-file or CLI overrides.
> Entrypoints: train.py
> Arguments: none
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact nanogpt-f01
> Claim: The declared defaults target a 124M-parameter GPT-2 configuration on OpenWebText.
> Basis: observed. Essential: yes. Anchors: train.py:33
Decision: pending

## Fact nanogpt-f02
> Claim: The selected no-override scenario initializes from scratch.
> Basis: observed. Essential: yes. Anchors: train.py:41
Decision: pending

## Fact nanogpt-f03
> Claim: The default model has 12 layers, 12 attention heads, and embedding width 768.
> Basis: observed. Essential: yes. Anchors: train.py:52-54
Decision: pending

## Fact nanogpt-f04
> Claim: Training batches are sampled independently from train.bin or val.bin and targets are the same token windows shifted by one position.
> Basis: observed. Essential: yes. Anchors: train.py:119-125
Decision: pending

## Fact nanogpt-f05
> Claim: The default accumulation count is 40 micro-steps and the per-device micro-batch size is 12.
> Basis: observed. Essential: yes. Anchors: train.py:48-49
Decision: pending

## Fact nanogpt-f06
> Claim: In DDP, accumulation steps are divided by world size so the global tokens-per-iteration calculation retains the world-size factor.
> Basis: observed. Essential: no. Anchors: train.py:94-101
Decision: pending

## Fact nanogpt-f07
> Claim: Loss estimation switches to evaluation mode, averages 200 sampled batches for each of the train and validation splits, then restores training mode.
> Basis: observed. Essential: yes. Anchors: train.py:218-228
Decision: pending

## Fact nanogpt-f08
> Claim: The learning-rate policy linearly warms up, then cosine-decays, and floors at min_lr after the decay horizon.
> Basis: observed. Essential: no. Anchors: train.py:231-242
Decision: pending

## Fact nanogpt-f09
> Claim: Each optimizer update accumulates scaled loss over the configured micro-steps, clips gradients when enabled, steps the optimizer/scaler, and clears gradients.
> Basis: observed. Essential: yes. Anchors: train.py:292-314
Decision: pending

## Fact nanogpt-f10
> Claim: At evaluation intervals, the master process saves model and optimizer state, model arguments, iteration, best validation loss, and config to out/ckpt.pt after iteration zero; the default always_save_checkpoint makes every such later interval eligible.
> Basis: observed. Essential: yes. Anchors: train.py:40; train.py:274-286
Decision: pending

## Unknown nanogpt-u01
> The contents and provenance of local data/openwebtext files are not established by train.py.
Decision: pending
Runs must state:

## Unknown nanogpt-u02
> Runtime hardware, DDP environment variables, dtype branch, and whether torch.compile succeeds are unknown without execution.
Decision: pending
Runs must state:

## Unknown nanogpt-u03
> configurator.py can change every declared default when config-file or CLI overrides are allowed; this candidate excludes those overrides.
Decision: pending
Runs must state:

## Non-defect nanogpt-n01
> Dividing each micro-step loss by gradient_accumulation_steps is intentional accumulation scaling.
Decision: pending

## Non-defect nanogpt-n02
> Suppressing DDP gradient synchronization until the final micro-step is an explicit optimization.
Decision: pending

## Non-defect nanogpt-n03
> Not saving a checkpoint at iteration zero is guarded intentionally by iter_num > 0.
Decision: pending

> Omitted fact: add "## Added fact nanogpt-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown nanogpt-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect nanogpt-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
