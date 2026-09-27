# Pilot run policy

> Guide: REVIEW_GUIDE.md, "Then: agree on the run policy". Check: python tools/workflow_eval.py check run-policy

Reviewer: realmyang
Date: 2026-09-27
Transcribed by: Claude Code (Opus 5.5), from the owner's decisions given in conversation on 2026-09-27

## Host copilot
> Development runs: Copilot Auto, routed to GPT-5.6 Luna (a hidden resolved model stays unknown).
Model: gpt-6-luna, selected explicitly (not Auto)
Reasoning: high
Invocation: the line "Use the mlview skill." before the prompt text

## Host codex
> Development runs: GPT-5.6 Sol, Ultra reasoning; invoked with the $mlview prefix.
Model: gpt-6-luna
Reasoning: high
Invocation: the $mlview prefix before the prompt text

## Host claude-code
> Development runs: Fable 5.1, Extra High reasoning.
Model: Opus 5.5 (claude-opus-5-5)
Reasoning: high
Invocation: /mlview before the prompt text

## Environment
> The skill runs "python3 <skill>/scripts/artifact.py". Each host's terminal must resolve python3 to 3.10+
> (macOS /usr/bin/python3 is 3.9). Say how, without a machine path; it is not put into the prompt.
Helper Python: python3 resolves to Python 3.12 or newer in each host's terminal, login shells included: a 3.12+
  installation comes first on PATH in the shell profile, and the version is checked in each host before its first run.

## Budget
> Proposed: 20 active minutes including critique and repair; at most 2 validator repair rounds;
> 0 infrastructure retries (a retry is allowed only if the prompt was never sent).
Active minutes: 30
Repair rounds: 2
Infrastructure retries: 0
> Owner, 2026-09-27 (quota-aware scheduling; no free-plan quota for Codex or Copilot): Claude Code runs go first. A
> Codex or Copilot run starts only after a quota check shows room for a whole run, so that no run stops mid-way on
> quota (which would count as a failed run). Codex and Copilot runs are spread across quota resets as needed.

## Scoring
> Qualified claims in supported-claim precision: not-supported | supported | excluded (CANDIDATE_PROTOCOL.md, "Pair the first stage with no-skill responses").
> Per-host targets: yes = precision and recall must also meet their targets within each host; no = pooled only.
Qualified claims: supported
Per-host targets: yes

## Conditions
> Baseline sessions: 24 (one no-skill session per task and host, Stage 1 only) | 0.
> Development adjudication before Stage 1: required | not-required.
Baseline sessions: 0
Development adjudication before Stage 1: not-required

## Targets
> structurallyValid 100%, exactAnchors 100%, supportedClaimPrecision >= 95%, essentialFactRecall >= 85%,
> knownUnresolvedQualified 100%, highSeverityFalseAccusations 0 (tasks.json pilotTargets). accept confirms them.
Decision: accept

## Skill prompt
> Placeholders: {task_prompt} {scenario} {artifact_path}. The host's Invocation is sent before this text.
```text
{task_prompt}

Selected scenario:
{scenario}

Inspect source without importing or executing target code. Read only this workspace and the installed skill; do not inspect parent folders, other workspaces or earlier artifacts. Use this assistant as the interpretation backend; do not delegate to subagents. Publish one WorkflowDocument to {artifact_path} using the installed helper, then report its path, revision, unresolved cases and repair rounds. You have 30 active minutes for this task, including critique and repair.
```
Decision: accept

## No-skill prompt
> Must not mention MLView, the skill, WorkflowDocument or publication (CANDIDATE_PROTOCOL.md, "Frozen prompts").
```text
{task_prompt}

Selected scenario:
{scenario}

Inspect source without importing or executing target code. Read only this workspace; do not inspect parent folders or other workspaces. Do not delegate to subagents. Answer in this conversation: describe the workflow, the unresolved cases, and the files you inspected. You have 30 active minutes for this task.
```
Decision: accept

## Privacy
> Raw transcripts, UI logs, run reviews and workspaces never enter the repository; committed summaries contain
> counts, statuses and hashes only. Say what else, if anything, may be published.
Publication: nothing else; committed summaries contain counts, statuses and hashes only.

## Task
Review: complete
