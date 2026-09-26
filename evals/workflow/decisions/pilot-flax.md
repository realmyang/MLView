# Reference decisions: pilot-flax

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-flax
> Lines starting with ">" are written by the tool and ignored. Replace each "pending". Indent a wrapped line by two spaces to continue the value above it.
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:". Anchors: replaces the proposed list; repeat each proposed anchor you keep.

Candidate: pilot-flax.json 161f674e64f6b8a6e94a33eb25d8ea47b8736147de2497a82908430cb911cfac
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Run the MNIST example through main.py with examples/mnist/configs/default.py and a reviewer-selected work directory.
> Entrypoints: examples/mnist/main.py; examples/mnist/train.py; examples/mnist/configs/default.py
> Arguments: --config=examples/mnist/configs/default.py; --workdir=<reviewer-selected-directory>
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact flax-config
> Claim: The selected config sets learning rate 0.1, momentum 0.9, batch size 128, and 10 epochs.
> Basis: observed. Essential: yes. Anchors: examples/mnist/configs/default.py:24-27
Decision: pending

## Fact flax-invocation
> Claim: main.py requires config and workdir flags and passes both to train_and_evaluate.
> Basis: observed. Essential: yes. Anchors: examples/mnist/main.py:64-68
Decision: pending

## Fact flax-data-splits
> Claim: The workflow loads the TensorFlow Datasets MNIST train and test splits separately.
> Basis: observed. Essential: yes. Anchors: examples/mnist/train.py:91-94
Decision: pending

## Fact flax-preprocessing
> Claim: Both splits cast images to float32 and divide by 255; only training is shuffled.
> Basis: observed. Essential: yes. Anchors: examples/mnist/train.py:96-111
Decision: pending

## Fact flax-batching
> Claim: Both datasets use fixed-size batches with incomplete batches dropped and prefetch one batch.
> Basis: observed. Essential: no. Anchors: examples/mnist/train.py:112-117
Decision: pending

## Fact flax-loss
> Claim: The loss is mean softmax cross-entropy from integer labels, and logits are returned for metrics.
> Basis: observed. Essential: yes. Anchors: examples/mnist/train.py:63-68
Decision: pending

## Fact flax-update
> Claim: Each jitted training step differentiates loss_fn, updates metrics, and applies gradients to the model through the NNX optimizer.
> Basis: observed. Essential: yes. Anchors: examples/mnist/train.py:71-77
Decision: pending

## Fact flax-param-filter
> Claim: The SGD optimizer is attached to the model with wrt=nnx.Param, limiting optimization to parameter variables.
> Basis: observed. Essential: yes. Anchors: examples/mnist/train.py:140-142
Decision: pending

## Fact flax-evaluation
> Claim: After every epoch, the model switches to eval mode and eval_step accumulates loss and accuracy over the test dataset without an optimizer update.
> Basis: observed. Essential: yes. Anchors: examples/mnist/train.py:163-170
Decision: pending

## Fact flax-metrics
> Claim: The tracked metrics are accuracy and average loss, reset between training and test accumulation.
> Basis: observed. Essential: no. Anchors: examples/mnist/train.py:143-146; examples/mnist/train.py:159-161
Decision: pending

## Fact flax-summaries
> Claim: Per-epoch train/test loss and accuracy are written to TensorBoard and flushed after training.
> Basis: observed. Essential: no. Anchors: examples/mnist/train.py:184-190
Decision: pending

## Fact flax-export
> Claim: After training, the eval-mode model is exported under workdir/mnist_export with a 1x28x28x1 float32 serving signature.
> Basis: observed. Essential: no. Anchors: examples/mnist/train.py:198-206
Decision: pending

## Unknown flax-u01
> Dataset availability and exact downloaded contents are external to the inspected source.
Decision: pending
Runs must state:

## Unknown flax-u02
> The internal semantics of NNX transforms, Optax SGD, TensorBoard writing, and Orbax export are not established beyond these call sites.
Decision: pending
Runs must state:

## Unknown flax-u03
> The reviewer must choose the concrete work directory.
Decision: pending
Runs must state:

## Non-defect flax-n01
> In-place NNX model, optimizer, and metric updates are the explicit API style used by this example; they are not evidence of missing functional state handling.
Decision: pending

## Non-defect flax-n02
> Dropping incomplete train and test batches is explicit configuration, not an inferred defect.
Decision: pending

> Omitted fact: add "## Added fact flax-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown flax-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect flax-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
