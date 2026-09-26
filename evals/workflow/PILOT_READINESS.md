# Held-out pilot readiness

**2026-09-25: Campaign 2 adds the tooling to record, check and freeze the
reference review and to prepare, seal, review and summarize pilot runs. No
reference has been frozen and no pilot run has occurred.** Stage 1 has **24
pending and zero passed** runs, Stage 2 has **48 pending and zero passed**,
and none of the stop/go targets has a measured result. The
[remaining gates](#remaining-gates) below name the command for each step.

**2026-09-18: reference drafts and an implemented candidate are ready; scored
runs await human review and reference approval.**

The [trust and usability campaign](../../docs/TRUST_USABILITY_CAMPAIGN.md) changes
the skill and viewer again. Use the [candidate protocol](CANDIDATE_PROTOCOL.md)
to capture every current distributed file. The four-file hashes and candidate
commit below identify historical follow-ups, not the current candidate. No
new held-out session or human reference decision has been supplied by this
campaign; the 24/48 pilot counts below remain pending.

The [review packet](reference-candidates/README.md) provides concrete scenario
proposals, 93 candidate facts, 106 exact source anchors and a proposed common
prompt/budget policy. All eight ledgers are explicitly AI-authored drafts with
human review pending. No target code was imported or executed, and no
held-out native-host output was generated or inspected to prepare them.

The semantic-quality candidate was published as `12747c4`. All 13 remote CI
jobs passed in push run `35287750580` and pull-request run `35287753581` at that
commit. The later [public-readiness review](../../docs/PUBLIC_READINESS_REVIEW.md)
changes the helper and distribution; its local checks and any later remote CI
must be tracked separately. The frozen four-file candidate bundle has SHA-256
`837358d2689890ec663dfebac57092c369db02d6e75a9229953776b1b5f2e29b`.
CI success and fresh development follow-ups do not approve reference facts or
count as held-out runs. The public draft ledgers are review inputs, not a
complete candidate fact set or evidence that the candidate improved quality.

Of the six fresh native development follow-ups, five have final native response
evidence and Copilot GAN failed within its two-repair budget. Copilot notebook's
response was recovered during cleanup after publishing a validator-clean
artifact with two repairs; its fresh diagram was not inspected. These outcomes
remain development evidence and do not change
the 24/48 held-out counts below.

## Pinned source availability

All eight repositories are present under the ignored `.public-corpus`
directory. Checkout HEADs match [tasks.json](tasks.json), entrypoints exist,
and cited file bytes independently match their pinned Git blobs.

| Task | Pinned commit |
|---|---|
| `pilot-nanogpt` | `3adf61e154c3fe3fca428ad6bc3818b27a3b8291` |
| `pilot-transformers` | `a2c15b30764b7c6cb0632ac6aed6eac227edc674` |
| `pilot-sklearn` | `dd3ca57300e14d45b7a34fccd0165d143c7a364c` |
| `pilot-flax` | `01854da11286b4109c59d7fd9205f3822fe807d6` |
| `pilot-diffusers` | `c419dac0152186060246c93a095bc1bfaea342b3` |
| `pilot-registry` | `cfd5d3a985b0249de009b67d04f37263e11cdf3d` |
| `pilot-rl` | `fe8d8a03c41a7ef5b523e2e354bd01c363e786bb` |
| `pilot-notebook` | `e707c2d659abafb9b1f9fd927907619a128db8d7` |

MMDetection's selected config and four inherited bases were initially absent
from the local partial checkout. Narrow retrieval from the pinned revision
closed that source gap; all five blob hashes match the Git tree. The selected
configuration is a proposal, not a default supplied by `tools/train.py`.
External framework/runtime/data behavior remains qualified in the drafts.
Campaign 2 adds those five exact files to the mmdetection sparse list in
[repositories.json](repositories.json), so a fresh fetch materializes them. An
existing checkout needs `--update-sparse` once (gate 3 below); it needs no
network when the files are already present. Pilot workspaces contain only the
sparse paths, so upstream root instruction files such as the `AGENTS.md` or
`CLAUDE.md` of transformers, scikit-learn and diffusers are absent from them.

## Remaining gates

Run every command from the repository root. None of them runs a model or
writes a human decision; the owner's decisions are written only by the owner,
or transcribed at the owner's dictation with `Transcribed by:` filled.

1. **Reference review** (owner or nominated reviewers). A named human
   reviewer decides each scenario, fact, basis, essential flag, unknown and
   non-defect, and adds omitted facts, unknowns and real defects, in
   `evals/workflow/decisions/<task>.md` before inspecting outputs
   ([review guide](reference-candidates/REVIEW_GUIDE.md)). Each file is done
   when its check ends with `ready to freeze`:

   ```sh
   python tools/workflow_eval.py context pilot-nanogpt
   python tools/workflow_eval.py check pilot-nanogpt
   ```

2. **Run policy** (owner). `evals/workflow/decisions/run-policy.md` fixes the
   native model, reasoning and invocation per host, the helper Python, the
   budget and repair rules, qualified-claim counting, per-host targets,
   baselines, the full prompt texts and privacy. These choices have not
   silently been treated as approved. Optionally the owner also completes
   `evals/workflow/decisions/development-adjudication.md`; the policy decides
   whether that is required before Stage 1.

   ```sh
   python tools/workflow_eval.py check run-policy --show-prompts
   python tools/workflow_eval.py check development-adjudication
   ```

3. **Corpus update and verification** (owner or agent, once, before the
   freeze). The freeze, `run-prepare` and `summarize` refuse a checkout whose
   HEAD, clean state, sparse patterns or file bytes do not verify. The
   existing mmdetection checkout must first take the corrected sparse list:

   ```sh
   python tools/fetch_workflow_repos.py --update-sparse
   python tools/fetch_workflow_repos.py --verify
   ```

   The untracked `.mlview-pinned-sha` files left by the retired analyzer are
   tolerated, with a note, only while their bytes equal the pin.

4. **Freeze** (owner, or the agent at the owner's request). The dry run lists
   every unmet precondition; `--write` creates the campaign directory
   ([contents](pilot/README.md)) and marks the held-out tasks `frozen`. Commit
   `evals/workflow/decisions`, `evals/workflow/pilot/pilot-01` and
   `evals/workflow/tasks.json` together, and merge that commit into main with
   a merge commit or a fast-forward, never a squash or rebase merge
   ([merging a campaign](pilot/README.md#merging-a-campaign)).

   ```sh
   python tools/workflow_eval.py freeze --campaign pilot-01
   python tools/workflow_eval.py freeze --campaign pilot-01 --write
   python tools/workflow_eval.py check-frozen
   ```

5. **Candidate capture** (agent). From a clean tree, capture a new pilot
   candidate. It builds the VSIX, pins the distributed bytes and the frozen
   campaign, and records `pilotApproved: false`
   ([candidate protocol](CANDIDATE_PROTOCOL.md)). The historical snapshots
   above cannot identify changed skill bytes. Commit `candidate.json`, merge
   it into main with a merge commit or a fast-forward, never a squash or
   rebase merge, and push a tag at its `source.commit`. Later skill changes on
   main do no harm: `run-prepare` installs the candidate's skill from that
   commit.

   ```sh
   export MLVIEW_PILOT_DIR=~/mlview-pilot
   python tools/workflow_candidate.py --campaign pilot-01 --build-vsix
   python tools/workflow_candidate.py --check evals/workflow/pilot/pilot-01/candidate.json
   ```

6. **Helper Python** (operator, before every session). The skill runs
   `python3 <skill>/scripts/artifact.py`, and the helper refuses Python older
   than 3.10; macOS `/usr/bin/python3` is 3.9. The run policy's
   `Helper Python` says how each host's terminal resolves `python3` to 3.10+,
   without a machine path, which never enters a prompt. The `run-prepare`
   checklist asks the operator to check `python3 --version` in the host
   terminal, `session.md` records it, and `summarize` makes a run with a helper
   Python older than 3.10 invalid.

7. **Stage 1 runs** (operator). The 24 `repeat: 1` records cover all eight
   tasks in all three hosts, plus the 24 no-skill baselines if the policy plans
   them. For each run, prepare the workspace, run one fresh native session
   following the printed checklist, fill `session.md`, then seal the evidence.
   Retain failed, timed-out and blocked attempts.

   ```sh
   python tools/workflow_eval.py plan --campaign pilot-01 --stage 1
   python tools/workflow_eval.py run-prepare pilot-nanogpt:codex:1 --campaign pilot-01
   python tools/workflow_eval.py run-finish pilot-nanogpt:codex:1 --campaign pilot-01
   ```

8. **Stage 1 review** (the named reviewer). Complete a human review for every
   completed run before making the stop/go decision:

   ```sh
   python tools/workflow_eval.py review-template pilot-nanogpt:codex:1 --campaign pilot-01
   python tools/workflow_eval.py check "$MLVIEW_PILOT_DIR/evidence/pilot-nanogpt.codex.1/review.md"
   ```

9. **Stage 1 decision.** `summarize` computes `incomplete`, `stop`, `go` or
   `invalid` against the six predefined targets: 100% valid structure, 100%
   exact anchors, at least 95% supported claims, at least 85% essential-fact
   recall, every must-state unknown stated, and zero high-severity false
   accusations. A target miss stops the campaign; it must not be hidden by
   proceeding to repeats. Retry or amend Stage 1 runs before recording:
   `--record` writes the summary for `go`, `stop` or `invalid` (it refuses
   while a failure the run policy lets you retry is still open), and from
   then on Stage 1 runs can no longer be retried or amended, and no Stage 1
   review may change except for `>` notes, line endings, trailing spaces and
   blank lines (the summary records each review's normalized hash, and the
   Stage 2 gate compares it); keep a copy of the evidence directory. Commit
   both summary files at once, right away, before any other commit, pull,
   merge or rebase, and merge that commit without squashing or rebasing it.

   ```sh
   python tools/workflow_eval.py summarize --campaign pilot-01 --stage 1
   python tools/workflow_eval.py summarize --campaign pilot-01 --stage 1 --record
   ```

10. **Stage 2, only after a committed `go`.** `run-prepare` refuses the 48
    `repeat: 2` and `repeat: 3` records until then. Prepare, run, seal and
    review them the same way, then report complete 72-run per-host/task
    numerators and denominators with
    `python tools/workflow_eval.py summarize --campaign pilot-01 --stage all --record`,
    and commit that summary the same way.
    Stage 1 success is permission to collect more evidence, not a completed
    or passed pilot.

Historical (2026-09-18, superseded by Campaign 2): the local
`.mlview/pilot-runs.json` was generated only because it did not already exist.
Its summarizer confirmed **72 pending, zero completed, zero human-reviewed,
`pilotComplete: false`**, and its prompts were drafts awaiting expansion and
freezing. Campaign 2 no longer uses that matrix: `plan` prints the planned
runs, the frozen prompts live in the campaign directory, and sealed run
records live under `MLVIEW_PILOT_DIR`.

For the current native development follow-ups, Claude Code uses Fable 5.1 with
Extra High reasoning and Codex uses Sol with Ultra reasoning. Copilot Auto was
already selected and both current sessions routed to GPT-5.6 Luna; Upgrade
appeared only as an unavailable choice and was never selected, and no account
change occurred. These are development
settings to preserve, not approved held-out settings until the pilot owner
freezes them in the run policy with the references.

Citation integrity and native UI mechanics can be checked independently of
human semantic review. [The host retry log](../../docs/demo-logs/2026-09-17-host-retry.md)
records successful basic round trips in Copilot and Claude, completing the
earlier Codex coverage. These configured-training compatibility exercises do
not count toward the held-out matrix or establish semantic accuracy.
