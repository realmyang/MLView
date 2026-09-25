# Reference decisions: pilot-sklearn

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-sklearn
> Lines starting with ">" are written by the tool and ignored. Replace each "pending". Indent a wrapped line by two spaces to continue the value above it.
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:". Anchors: replaces the proposed list; repeat each proposed anchor you keep.

Candidate: pilot-sklearn.json 42c00471070b91c8d5c4208d64e6fce942742d921e7e6a384aa733ed3083f676
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Inspect the example as written: compare non-nested parameter selection with nested outer-fold evaluation across repeated Iris trials.
> Entrypoints: examples/model_selection/plot_nested_cross_validation_iris.py
> Arguments: none
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact sklearn-f01
> Claim: The example's stated purpose is to compare non-nested and nested cross-validation on Iris.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:6-11
Decision: pending

## Fact sklearn-f02
> Claim: The source explains that inner GridSearchCV selects hyperparameters while outer cross_val_score estimates generalization over held-out folds.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:19-26
Decision: pending

## Fact sklearn-f03
> Claim: The comparison repeats for 30 trials.
> Basis: observed. Essential: no. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:57-58
Decision: pending

## Fact sklearn-f04
> Claim: Features and labels come from sklearn's Iris dataset loader.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:60-63
Decision: pending

## Fact sklearn-f05
> Claim: Grid search considers C values 1, 10, and 100 and gamma values 0.01 and 0.1.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:65-66
Decision: pending

## Fact sklearn-f06
> Claim: The estimator is an SVC with an RBF kernel.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:68-69
Decision: pending

## Fact sklearn-f07
> Claim: Each trial constructs separate shuffled four-fold inner and outer KFold objects, both seeded by the trial index.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:75-81
Decision: pending

## Fact sklearn-f08
> Claim: The non-nested score is GridSearchCV.best_score_ after fitting the search over the full Iris inputs with outer_cv as its CV splitter.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:83-86
Decision: pending

## Fact sklearn-f09
> Claim: The nested score wraps the inner GridSearchCV in cross_val_score using outer_cv, then averages the outer scores.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:88-91
Decision: pending

## Fact sklearn-f10
> Claim: The reported comparison is non-nested score minus nested score, summarized by mean and standard deviation.
> Basis: observed. Essential: yes. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:93-99
Decision: pending

## Fact sklearn-f11
> Claim: The visualization shows both score sequences and a bar chart of their per-trial difference.
> Basis: observed. Essential: no. Anchors: examples/model_selection/plot_nested_cross_validation_iris.py:101-105
Decision: pending

## Unknown sklearn-u01
> No target code was executed, so numerical score differences and plot contents are not candidate facts.
Decision: pending
Runs must state:

## Unknown sklearn-u02
> The implementation details of GridSearchCV, KFold, cross_val_score, and SVC are outside this inspected example.
Decision: pending
Runs must state:

## Unknown sklearn-u03
> A human reviewer must decide whether to label non-nested selection bias as a demonstrated methodological pitfall rather than a defect in this educational example.
Decision: pending
Runs must state:

## Non-defect sklearn-n01
> The non-nested reuse of CV for selection and scoring is intentional because the example demonstrates its optimistic bias.
Decision: pending

## Non-defect sklearn-n02
> Using the same trial index to seed separate inner and outer splitter objects is explicit example behavior and is not, by itself, evidence of leakage.
Decision: pending

## Non-defect sklearn-n03
> The script compares evaluation strategies; it does not produce a final deployed estimator.
Decision: pending

> Omitted fact: add "## Added fact sklearn-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown sklearn-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect sklearn-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
