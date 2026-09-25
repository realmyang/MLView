# Reference decisions: pilot-transformers

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-transformers
> Lines starting with ">" are written by the tool and ignored. Replace each "pending".
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:".

Candidate: pilot-transformers.json ca15e10f8c7b066bf5d0b813131536ce326d17e9bfa2920d96851cbfe796025c
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Use the pinned README's MRPC GLUE example with BERT and both training and evaluation enabled.
> Entrypoints: examples/pytorch/text-classification/run_glue.py; examples/pytorch/text-classification/README.md
> Arguments: --model_name_or_path google-bert/bert-base-cased; --task_name mrpc; --do_train; --do_eval; --max_seq_length 128; --per_device_train_batch_size 32; --learning_rate 2e-5; --num_train_epochs 3; --output_dir /tmp/mrpc/
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact transformers-f01
> Claim: The selected scenario is the README's MRPC command using google-bert/bert-base-cased with training and evaluation enabled.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/README.md:31-39
Decision: pending

## Fact transformers-f02
> Claim: The scenario fixes learning rate 2e-5, three epochs, and /tmp/mrpc/ as output directory.
> Basis: observed. Essential: no. Anchors: examples/pytorch/text-classification/README.md:40-42
Decision: pending

## Fact transformers-f03
> Claim: For a named GLUE task, the script loads that task from nyu-mll/glue.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:282-289
Decision: pending

## Fact transformers-f04
> Claim: The script derives label count from the GLUE training split and marks only STS-B as regression.
> Basis: observed. Essential: no. Anchors: examples/pytorch/text-classification/run_glue.py:339-346
Decision: pending

## Fact transformers-f05
> Claim: Configuration, tokenizer, and sequence-classification model are loaded from the selected pretrained model unless separate config or tokenizer names override it.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:363-381
Decision: pending

## Fact transformers-f06
> Claim: The task selects its sentence columns from task_to_keys and tokenization truncates to the lesser of requested and tokenizer maximum length.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:391-393; examples/pytorch/text-classification/run_glue.py:444-451
Decision: pending

## Fact transformers-f07
> Claim: Training uses the train split and evaluation uses validation for MRPC.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:473-485
Decision: pending

## Fact transformers-f08
> Claim: For GLUE, metrics come from evaluate.load('glue', task_name); classification predictions use argmax and multi-valued metrics also receive a combined mean score.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:505-525
Decision: pending

## Fact transformers-f09
> Claim: Trainer receives the model, training arguments, selected train/eval datasets, metric function, tokenizer processing class, and collator.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:536-545
Decision: pending

## Fact transformers-f10
> Claim: The training branch calls Trainer.train, then saves the model, training metrics, and trainer state.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:547-563
Decision: pending

## Fact transformers-f11
> Claim: The evaluation branch calls Trainer.evaluate on the selected validation dataset and saves evaluation metrics.
> Basis: observed. Essential: yes. Anchors: examples/pytorch/text-classification/run_glue.py:581-595
Decision: pending

## Unknown transformers-u01
> Dataset and pretrained-model contents are external to the pinned checkout and were not downloaded or inspected.
Decision: pending
Runs must state:

## Unknown transformers-u02
> Trainer's optimizer, scheduling, checkpoint cadence, and distributed behavior live outside this entrypoint and require separately anchored library inspection if treated as reference facts.
Decision: pending
Runs must state:

## Unknown transformers-u03
> The README output path is platform-specific and the pilot must decide whether to preserve it literally or substitute a recorded workspace-safe path.
Decision: pending
Runs must state:

## Non-defect transformers-n01
> Using the validation split for --do_eval is the intended GLUE evaluation path in this example.
Decision: pending

## Non-defect transformers-n02
> The MRPC scenario does not enter the MNLI matched/mismatched special case.
Decision: pending

## Non-defect transformers-n03
> Creating a local model card when push_to_hub is false is intended output behavior.
Decision: pending

> Omitted fact: add "## Added fact transformers-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown transformers-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect transformers-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
