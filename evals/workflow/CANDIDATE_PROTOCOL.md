# Candidate identity and paired evaluation

This extends the [pilot protocol](README.md) with reproducible candidate
identification, frozen prompts and a separately planned no-skill comparison.
It does not approve references, freeze model settings, or start native-host
sessions.

## Capture the pilot candidate

Capture one pilot candidate per campaign, after the freeze is committed and
from a clean tree:

```sh
git status --porcelain
(cd webview && npm ci) && (cd vscode-extension && npm ci)
export MLVIEW_PILOT_DIR=~/mlview-pilot
python tools/workflow_candidate.py --campaign pilot-01 --build-vsix
```

`git status --porcelain` must print nothing, including untracked files that
are not ignored. The capture stops at the first failure:

1. It refuses unless the tree is clean, the task manifest's `pilotFreeze`
   names the campaign, the campaign's freeze files are tracked and
   `check-frozen` passes. It needs the full Git history (it refuses a shallow
   or partial clone) and refuses a campaign whose `candidate.json` was ever
   committed, in any branch merged into HEAD, even if it was deleted since: a
   campaign has one candidate, which is final once committed.
2. It builds the VSIX itself, as `$MLVIEW_PILOT_DIR/mlview-<version>.vsix`,
   and refuses if that file exists. Packaging recompiles the extension, so the
   bundle comes from the clean tree; a pre-built VSIX is never accepted.
3. It checks that the tree is still clean, which proves that packaging
   rewrote the extension's notices copy byte-identically.
4. It runs the VSIX payload check, and requires the VSIX's `extension/media/*`
   to equal the committed `vscode-extension/media/*` and its version to equal
   `vscode-extension/package.json`.
5. It requires the skill payload to equal `git ls-files skills/mlview` without
   `tests/`.
6. It creates `evals/workflow/pilot/pilot-01/candidate.json` and never
   overwrites one. Commit it, and bring that commit to main with a merge commit
   or a fast-forward, never a squash or rebase merge, which would leave
   `source.commit` outside main's history. Keep `source.commit` reachable: keep
   its branch or push a tag at it
   ([merging a campaign](pilot/README.md#merging-a-campaign)).

The candidate (`"version": 2`, `"kind": "pilot-candidate"`) records the
source commit and tree, the full skill identity, the VSIX bytes and inner
entries, and these components: the schema, `tasks.json`, `repositories.json`,
the built viewer JS/CSS, `vscode-extension/package.json` and the campaign's
`freeze.json`, which in turn pins the frozen references, run policy and
prompts. It stores only the VSIX file name, never a machine path, and the
VSIX itself stays with the private run evidence. `pilotApproved` is always
`false`. `candidateSha256`, the SHA-256 of `candidate.json`, is the campaign
identity: every run record and every summary binds it. Rebuild equivalence of
the extension bundle is not claimed.

```sh
python tools/workflow_candidate.py --check evals/workflow/pilot/pilot-01/candidate.json --vsix "$MLVIEW_PILOT_DIR/mlview-<version>.vsix"
```

`--check` verifies the structure, that the source commit is an ancestor of
HEAD, and every component as stored at that commit. It reports drift at HEAD
as information and compares the VSIX bytes when `--vsix` is given. A source
commit that is missing or not an ancestor after a squash or rebase merge, or
after its branch was deleted, fails here and in `run-prepare` and `summarize`.
Success says nothing about human approval.

For local development, this still creates a `development-snapshot`, in which
a dirty tree is allowed and a VSIX is optional (`--vsix PATH`):

```sh
python tools/workflow_candidate.py --output .mlview/candidate.json
```

`summarize` refuses this kind, so it can never identify a pilot campaign.
Snapshots cannot overwrite an existing record.

## Skill identity

The skill identity covers **every distributed file**, including licenses and
optional references, using sorted skill-relative UTF-8 path, NUL, file bytes,
NUL. Tests, caches, dotfiles and editor backup files are never distributed.
Each file also has its own SHA-256 in the identity's `files` list, and **that
list is part of the identity**: the scalar digest has no length framing, so
two different payloads could share it. Tools compare the whole identity;
quote the scalar SHA-256 only together with its file list. Old four-file
bundle hashes in historical records never identify the expanded current skill.
Record host/extension versions and model/reasoning settings in each run's
`session.md`, separately from these bytes.

## Frozen prompts

The task manifest's `prompt` is condition-neutral: the same task text serves
both conditions. The owner approves the full skill and no-skill prompt
templates in `evals/workflow/decisions/run-policy.md`, with the placeholders
`{task_prompt}`, `{scenario}` and `{artifact_path}`, and `freeze` renders 16
files: `prompts/skill/<task>.txt` and `prompts/baseline/<task>.txt` in
`evals/workflow/pilot/<campaign>/`. They contain only MLView-authored task
text, the owner's scenario and the owner's template text. `{scenario}` renders
as `Description:`, `Entrypoints:` and `Arguments:` lines, and
`{artifact_path}` is `pilot.mlview.json`, which is safe because every run has
its own workspace. The freeze refuses a no-skill template that mentions
MLView, the skill, WorkflowDocument, publishing or publication, and any prompt
that contains an absolute machine path (`/Users/`, `/home/`, `/private/` or a
drive letter) or a reference claim of 30 or more characters. Other absolute
paths, such as an upstream scenario argument like `/tmp/mrpc/`, are allowed.

The host's invocation (Codex's `$mlview` prefix, Copilot's skill picker or
the Claude Code invocation) is frozen per host in the run policy and sent
before the prompt text in skill runs; it is not part of the hashed prompt. A
baseline sends the no-skill prompt as a plain message, without the
invocation, and is held only to the policy's model and reasoning. `run-prepare`
copies the exact frozen bytes to the run's `PROMPT.txt`, and the sealed record
stores that file, its SHA-256 and the frozen path. `summarize` requires the
`PROMPT.txt` hash to equal the freeze entry and the bytes at the candidate
commit. When a transcript is present it also reports whether the prompt
appears in it (`promptInTranscript: yes`, `no` or `unverified`); `no` is only a
warning, because UI copies reformat text. Never edit a frozen prompt: a
changed prompt needs a new campaign.

## Pair the first stage with no-skill responses

When the run policy sets `Baseline sessions: 24`,
`python tools/workflow_eval.py plan --campaign pilot-01 --stage 1` lists **24
additional baseline runs**, `<task>:<host>:baseline:1`: eight held-out tasks ×
three hosts, first repetition only. They are separate from the 72 skill runs
and never part of the stop/go gate. Baselines use the frozen no-skill prompt
with the same task and scenario, model settings, source pin and analysis
budget. Their workspaces have no skill installed, the operator confirms that
no MLView plugin or skill is available to the host, and `session.md` records
`MLView available to host: no`. An MLView file in a baseline workspace makes
the baseline invalid. Isolate references and other outputs from each fresh
session. Decide whether further baseline repetitions are warranted
before seeing their results.

Compare semantic claims, essential-fact recall, task usefulness and elapsed
time. Artifact publication and diagram-navigation measures apply only to the
skill condition. Capture failures, cancellations and timeouts rather than
replacing them with successful retries. End-to-end completion uses all
assigned sessions as its denominator; semantic metrics on published artifacts
must be labeled separately. Omissions affect recall, not claim precision.

Before scoring, the reference freezes claim boundaries and essential facts,
and the run policy fixes how qualified claims count in precision:
`not-supported`, `supported` or `excluded`. Count a conditional claim as
supported only when the reviewer confirms both its conditions and conclusion,
and report qualified claims separately. Report task/host numerators and
denominators; repeated sessions on eight tasks are not independent task
samples.

## Privacy and human decisions

Raw native captures (transcripts, UI logs, run reviews and workspaces) stay
under `MLVIEW_PILOT_DIR`, outside the repository. The run policy's privacy
section decides, before sessions start, what else may be published; committed
summaries contain counts, statuses and hashes only. Retain capture hashes,
whether they were independently verified, source attribution, failed attempts
and deviations. Hashes alone do not prove that a capture is complete or
reviewed.

The [reference packet](reference-candidates/README.md) has concrete draft
scenarios and source anchors. A named human must supply source-based decisions
before the freeze derives the frozen reference revision for the scored pilot.
Model-generated reviews, deterministic checks and this document cannot supply
those decisions.

The existing 24-run Stage 1 and 48-run Stage 2 stop/go targets remain unchanged.
Stage 2 starts only after Stage 1 is adjudicated under the frozen policy.
