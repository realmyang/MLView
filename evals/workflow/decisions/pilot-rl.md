# Reference decisions: pilot-rl

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-rl
> Lines starting with ">" are written by the tool and ignored. Replace each "pending". Indent a wrapped line by two spaces to continue the value above it.
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:". Anchors: replaces the proposed list; repeat each proposed anchor you keep.

Candidate: pilot-rl.json 725cea6cd067cbc10f2c38fa2386adc1896c48f95cdf830d11314125668b932c
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Inspect cleanrl/ppo.py using its declared defaults, without executing or importing the target.
> Entrypoints: cleanrl/ppo.py
> Arguments: none
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact rl-default-scenario
> Claim: The declared defaults select CartPole-v1, 500,000 total timesteps, four environments, and 128 rollout steps.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:37-46
Decision: pending

## Fact rl-batch-derived
> Claim: Batch size is num_envs times num_steps; minibatch size divides that batch by four default minibatches, and iteration count divides total timesteps by batch size.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:130-133
Decision: pending

## Fact rl-agent-outputs
> Claim: The agent samples from a categorical actor and returns the action, its log probability, entropy, and critic value.
> Basis: observed. Essential: no. Anchors: cleanrl/ppo.py:121-126
Decision: pending

## Fact rl-rollout-storage
> Claim: Rollout storage keeps observations, actions, log probabilities, rewards, done flags, and values for every rollout step and environment.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:170-176
Decision: pending

## Fact rl-interaction-cycle
> Claim: Each rollout step stores the current observation and prior done flag, samples an action without gradients, steps the vector environment, and stores the reward.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:192-208
Decision: pending

## Fact rl-termination-truncation-mask
> Claim: The code combines termination and truncation with logical OR into one done flag; it does not preserve separate flags in rollout storage.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:204-208
Decision: pending

## Fact rl-gae-mask-semantics
> Claim: GAE uses one minus the combined done flag as nextnonterminal, so both a termination and a truncation make the recurrence and bootstrap multiplier zero at that boundary.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:217-231
Decision: pending

## Fact rl-flatten-and-shuffle
> Claim: After advantage estimation, rollout tensors are flattened and their indices are shuffled for each update epoch before minibatch selection.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:233-248
Decision: pending

## Fact rl-clipped-policy-loss
> Claim: The policy objective uses the larger loss between the unclipped probability-ratio term and a ratio clipped to one plus or minus clip_coef.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:250-267
Decision: pending

## Fact rl-value-and-total-loss
> Claim: By default, value loss is clipped relative to stored values; the total loss combines policy loss, a negative entropy bonus, and value loss weighted by vf_coef.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:269-285
Decision: pending

## Fact rl-gradient-update
> Claim: Each minibatch clears gradients, backpropagates the combined loss, clips gradients across all agent parameters, and steps Adam.
> Basis: observed. Essential: yes. Anchors: cleanrl/ppo.py:287-290
Decision: pending

## Fact rl-logging
> Claim: Episode return and length come from final_info, while learning rate, losses, KL estimates, clip fraction, explained variance, and throughput are written to TensorBoard.
> Basis: observed. Essential: no. Anchors: cleanrl/ppo.py:210-215; cleanrl/ppo.py:299-309
Decision: pending

## Unknown rl-u01
> Whether a human reviewer classifies masking truncations like terminations as a defect for this CartPole scenario.
Decision: pending
Runs must state:

## Unknown rl-u02
> The exact runtime autoreset and final-observation behavior supplied by the installed Gymnasium version was not inspected or executed.
Decision: pending
Runs must state:

## Unknown rl-u03
> CLI overrides, runtime device selection, generated trajectories, metrics, and output files are unknown because the target was not run.
Decision: pending
Runs must state:

## Non-defect rl-n01
> Policy and value clipping, advantage normalization, entropy regularization, gradient clipping, and learning-rate annealing are explicit configurable PPO choices; this draft does not label them defects.
Decision: pending

## Non-defect rl-n02
> This draft records the combined termination/truncation mask as observed behavior and leaves defect adjudication to human review.
Decision: pending

> Omitted fact: add "## Added fact rl-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown rl-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect rl-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
