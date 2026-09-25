# Reference decisions: pilot-notebook

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-notebook
> Lines starting with ">" are written by the tool and ignored. Replace each "pending".
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:".

Candidate: pilot-notebook.json 89009872b31f86de28a8db6faf2c7edcb9c9807be3d9f913b17dfe7036613e0a
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Inspect the California housing main narrative through persistence, using notebook source order and excluding the exercise solutions beginning at cell 221; do not execute cells.
> Entrypoints: 02_end_to_end_machine_learning_project.ipynb
> Arguments: source-order-only; cells-0-through-220; no-cell-execution
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact notebook-load-data
> Claim: The narrative loads the California housing CSV, downloading and extracting an archive only when the local tarball is absent.
> Basis: observed. Essential: no. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell11:6-16
Decision: pending

## Fact notebook-stratification-feature
> Claim: Median income is discretized into five income categories for stratification.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell37:1-3
Decision: pending

## Fact notebook-heldout-split
> Claim: The selected concise split creates an 80/20 train/test boundary stratified by income category with random_state 42.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell42:1-2
Decision: pending

## Fact notebook-training-boundary
> Claim: Model-development features and labels are derived from strat_train_set; the held-out strat_test_set is not used in this preparation step.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell66:1-2
Decision: pending

## Fact notebook-preprocessing
> Claim: The final preprocessing definition builds ratio, log, geographic cluster-similarity, categorical, and remaining-numeric branches, each with its stated imputing, transforming, or scaling steps.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell159:7-29
Decision: pending

## Fact notebook-pipeline-fit-boundary
> Claim: A linear regression is placed after preprocessing in one pipeline and fitted using only the training features and training labels.
> Basis: observed. Essential: no. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell164:1-4
Decision: pending

## Fact notebook-cross-validation
> Claim: The random-forest candidate includes preprocessing inside its pipeline and is evaluated with 10-fold cross-validation on the training features and labels.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell179:1-6
Decision: pending

## Fact notebook-randomized-search
> Claim: The main tuning choice performs a seeded 10-draw, three-fold randomized search over geographic cluster count and random-forest max features, fitting only housing and housing_labels.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell199:4-11
Decision: pending

## Fact notebook-final-model
> Claim: The final model is the randomized search's best estimator and includes preprocessing.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell207:1-3
Decision: pending

## Fact notebook-final-test-once
> Claim: The held-out test set is separated into X_test and y_test, passed to the selected final model, and used to compute final RMSE after tuning.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell210:1-7
Decision: pending

## Fact notebook-confidence-interval
> Claim: A 95% bootstrap confidence interval is computed from squared held-out prediction errors using RMSE as the statistic.
> Basis: observed. Essential: no. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell212:3-10
Decision: pending

## Fact notebook-persistence-and-scope
> Claim: The selected final model is persisted before the notebook's Exercise solutions heading; cells beginning with that heading are outside the proposed scenario.
> Basis: observed. Essential: yes. Anchors: 02_end_to_end_machine_learning_project.ipynb#cell216:1-3; 02_end_to_end_machine_learning_project.ipynb#cell221:1
Decision: pending

## Unknown notebook-u01
> Stored execution counts and outputs do not prove a clean, in-order kernel execution or current runtime state.
Decision: pending
Runs must state:

## Unknown notebook-u02
> External dataset contents and availability were not inspected, downloaded, or executed.
Decision: pending
Runs must state:

## Unknown notebook-u03
> The behavior of scikit-learn and SciPy internals beyond the notebook source is not established by this source-only draft.
Decision: pending
Runs must state:

## Unknown notebook-u04
> A human reviewer must approve cells 0 through 220 as the frozen main narrative and confirm that all exercise cells are excluded.
Decision: pending
Runs must state:

## Non-defect notebook-n01
> Earlier random, hash-based, StratifiedShuffleSplit, grid-search, and model examples are pedagogical alternatives in source order; their presence alone does not mean the final held-out test boundary is crossed.
Decision: pending

## Non-defect notebook-n02
> Fitting preprocessing within estimator pipelines and cross-validation/search objects keeps those transformations inside the corresponding training fit calls in the visible notebook workflow; this draft does not allege leakage.
Decision: pending

## Non-defect notebook-n03
> Stored notebook outputs and execution counts are evidence of notebook metadata, not proof that the proposed main narrative was executed cleanly in source order.
Decision: pending

> Omitted fact: add "## Added fact notebook-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown notebook-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect notebook-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
