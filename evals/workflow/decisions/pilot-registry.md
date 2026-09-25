# Reference decisions: pilot-registry

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-registry
> Lines starting with ">" are written by the tool and ignored. Replace each "pending".
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:".

Candidate: pilot-registry.json c21a4cab74cbf85ac6f01dd577499aec5694fa5a4059339e286d929b13f3c3d0
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Candidate invocation with configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py and no optional overrides, resolved through its four pinned base configs.
> Entrypoints: tools/train.py; configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py
> Arguments: configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact registry-config-required
> Claim: The training entrypoint requires a positional config path; it supplies no default config.
> Basis: observed. Essential: yes. Anchors: tools/train.py:13-16
Decision: pending

## Fact registry-scenario-config
> Claim: The selected config inherits the Faster R-CNN R50 FPN model, COCO detection dataset, 1x schedule, and default runtime bases.
> Basis: observed. Essential: yes. Anchors: configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py:1-5
Decision: pending

## Fact registry-config-load
> Claim: The entrypoint loads the selected file through external mmengine Config.fromfile and records the launcher in the resulting config.
> Basis: observed. Essential: yes. Anchors: tools/train.py:67-71
Decision: pending

## Fact registry-no-overrides
> Claim: With the selected no-override invocation, cfg-options merging is not requested.
> Basis: inferred. Essential: no. Anchors: tools/train.py:69-71
Decision: pending

## Fact registry-workdir
> Claim: Without a CLI or config work_dir, the entrypoint derives ./work_dirs/faster-rcnn_r50_fpn_1x_coco from the config filename.
> Basis: inferred. Essential: no. Anchors: tools/train.py:73-80
Decision: pending

## Fact registry-model
> Claim: The resolved model is FasterRCNN with a pretrained ResNet-50 backbone and FPN neck; its RoI box head has 80 classes.
> Basis: observed. Essential: yes. Anchors: configs/_base_/models/faster-rcnn_r50_fpn.py:1-24; configs/_base_/models/faster-rcnn_r50_fpn.py:48-53
Decision: pending

## Fact registry-data-eval
> Claim: The resolved workflow trains on COCO train2017 with shuffled batches of two and evaluates bounding boxes on val2017 with unshuffled batches of one.
> Basis: observed. Essential: yes. Anchors: configs/_base_/datasets/coco_detection.py:37-64; configs/_base_/datasets/coco_detection.py:67-73
Decision: pending

## Fact registry-schedule-runtime
> Claim: The resolved schedule runs 12 epochs with validation every epoch, SGD at learning rate 0.02, and learning-rate milestones at epochs 8 and 11; runtime checkpointing occurs every epoch.
> Basis: observed. Essential: yes. Anchors: configs/_base_/schedules/schedule_1x.py:1-22; configs/_base_/default_runtime.py:3-9
Decision: pending

## Fact registry-runner-choice
> Claim: The entrypoint uses Runner.from_cfg when runner_type is absent and RUNNERS.build when runner_type is present.
> Basis: observed. Essential: yes. Anchors: tools/train.py:107-114
Decision: pending

## Fact registry-default-runner
> Claim: None of the selected config or four bases defines runner_type, so the entrypoint selects Runner.from_cfg.
> Basis: observed. Essential: yes. Anchors: configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py:1-5; tools/train.py:107-114
Decision: pending

## Fact registry-train
> Claim: After runner construction, the entrypoint invokes runner.train().
> Basis: observed. Essential: yes. Anchors: tools/train.py:116-117
Decision: pending

## Fact registry-external
> Claim: Config parsing, base inheritance, runner construction, registry lookup, and training lifecycle semantics are provided by external mmengine call sites and are not established by tools/train.py alone.
> Basis: unresolved. Essential: yes. Anchors: tools/train.py:6-8
Decision: pending

## Unknown registry-u01
> External mmengine Config inheritance, registry construction, Runner construction, and lifecycle behavior were not inspected beyond the pinned configuration and entrypoint call sites.
Decision: pending
Runs must state:

## Unknown registry-u02
> COCO data, pretrained torchvision ResNet-50 weights, and runtime environment availability remain external.
Decision: pending
Runs must state:

## Unknown registry-u03
> No target imports, config execution, or training were performed.
Decision: pending
Runs must state:

## Non-defect registry-n01
> Config-driven behavior and the alternative registered-runner branch are intentional entrypoint design, not evidence of hidden training logic.
Decision: pending

## Non-defect registry-n02
> Omitted AMP, auto-scale-LR, resume, and cfg-options reflect the selected scenario.
Decision: pending

> Omitted fact: add "## Added fact registry-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown registry-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect registry-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
