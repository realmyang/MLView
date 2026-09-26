# Frozen pilot campaigns

Each subdirectory `evals/workflow/pilot/<campaign>/`, for example `pilot-01`,
holds one frozen held-out pilot campaign. **A campaign directory is immutable
once committed.** Tools write its files, create each one exclusively and never
overwrite it; the one file a person writes is the owner's `invalidation.md`.
Changing a reference, the run policy or a prompt after the freeze means a new
campaign, not an edit. No campaign has been frozen yet.

The inputs are the owner's decision files in `evals/workflow/decisions/`; the
[review guide](../reference-candidates/REVIEW_GUIDE.md) explains how they are
written and checked, and the [evaluation protocol](../README.md) explains the
runs and the stop/go computation.

## Files and formats

| File | Written by | Contents |
|---|---|---|
| `reference/<task>.json`, one per held-out task | `freeze --write` | Format `mlview-frozen-reference/1`: the owner's scenario; kept facts with their origin, decision, changes and anchor locators; rejected items; `essentialFactIds`; kept unknowns with `runsMustState`; non-defects; defects; disputes between reviewers; the reviewers; and the SHA-256 and Git blob of every cited source file. No third-party source text. |
| `reference-set.json` | `freeze --write` | Format `mlview-reference-set/1`: every reference with its SHA-256 and its essential and must-state counts. The campaign's `referenceRevision` is `sha256:` followed by the SHA-256 of this file's bytes. |
| `policy.json` | `freeze --write` | Format `mlview-run-policy/1`: per-host model, reasoning and invocation; helper Python; budget; scoring; conditions; the six targets; privacy; and the hashes of the two prompt templates. |
| `prompts/skill/<task>.txt`, `prompts/baseline/<task>.txt` | `freeze --write` | The 16 rendered prompts: UTF-8, LF, exactly one trailing newline. Each is what a host receives after its invocation. |
| `freeze.json` | `freeze --write` | Format `mlview-freeze/1`: `frozenAt`, `referenceRevision`, any superseded campaign, the SHA-256 of every file above, of the decision files and of the candidate ledgers, the held-out projection of `tasks.json`, the repositories manifest hash and sparse lists, the development adjudication (or `null`) and the hashes of the freezing tools. |
| `candidate.json` | `python tools/workflow_candidate.py --campaign <campaign> --build-vsix` | Candidate snapshot version 2, kind `pilot-candidate`, with `pilotApproved: false`. Its SHA-256 is the campaign identity that every run record and summary binds ([candidate protocol](../CANDIDATE_PROTOCOL.md)). |
| `stage1-summary.json`, `stage1-summary.md` | `summarize --campaign <campaign> --stage 1 --record` | Format `mlview-pilot-summary/1`: the Stage 1 decision (`go`, `stop` or `invalid`), every target with numerator and denominator, breakdowns, caveats and input hashes. Every earlier attempt of a skill run or a baseline is listed with its status, failure and, when the prompt counts as sent, why (`runs[].attempts`, `failures.earlierAttempts`, `baselines.runs[]`, `baselines.earlierAttempts`), and each baseline keeps its failure and invalid reasons. The Markdown is rendered only from the JSON. |
| `stage2-summary.json`, `stage2-summary.md` | `summarize --campaign <campaign> --stage all --record` | The complete 72-run summary in the same format (`targets-met`, `targets-missed` or `invalid`). |
| `invalidation.md` | the owner only | `# Invalidation: <campaign>` with `Reviewer:`, `Date:`, `Scope: stage1` or `campaign`, and `Reason:`. Tools never create it. |

All JSON is canonical: two-space indentation, sorted keys, UTF-8 and one
trailing newline, with relative POSIX paths and no machine paths. The only
timestamp a freeze writes is `frozenAt`. A summary always says it was computed
against predefined targets and is not an approval.

The freeze also updates `evals/workflow/tasks.json`: each held-out task's
`referenceStatus` becomes `frozen`, and a top-level `pilotFreeze` names the
campaign, its `freeze.json` and its `referenceRevision`. Commit
`evals/workflow/decisions`, the campaign directory and `tasks.json` together.
A later campaign may supersede this one only while this one was never
captured (no `candidate.json` or stage summary now or anywhere in the Git
history, merged branches included; deleting a committed candidate does not
count), or after the owner has written its `invalidation.md`; the freeze then
records the reason given with `--supersede-reason`. Deleting a committed
campaign does not clear the way for a new one: restoring the pre-freeze
`tasks.json`, or a `tasks.json` that names an older campaign, does not make a
new campaign possible, because the
freeze refuses while the history holds a committed campaign that is missing
or that the campaign `tasks.json` names does not reach through the
`freeze.json` `supersedes` chain. Both refuse in a shallow or partial clone,
whose history could hide a deleted candidate.

## Merging a campaign

The pilot tools bind evidence to Git history: `candidate.json` names its
`source.commit`, which must stay an ancestor of `HEAD`, and `check-frozen`
reads `tasksManifest.sha256` against the `tasks.json` committed with
`freeze.json`. So commits that carry a campaign freeze (`freeze.json` with its
`tasks.json`), a `candidate.json` or a stage summary reach main by a merge
commit or a fast-forward, never a squash or rebase merge, which rewrites
those commits (a squash can also combine the freeze with later `tasks.json`
edits, which check-frozen then reports on main). Freezing and capturing
directly on main also works. Keep the commit that `candidate.json` names
reachable: keep its branch, or push a tag at it, for example
`git tag pilot-01-candidate <source.commit>` and `git push origin
pilot-01-candidate`. A pull request's CI tests the merge ref, which keeps the
branch history, so it cannot catch a squash merge before it happens.

If a campaign branch was squash- or rebase-merged anyway, main no longer holds
the commits the campaign names, and `run-prepare`, `summarize` and
`python tools/workflow_candidate.py --check` say that `source.commit` is not
an ancestor of `HEAD` (`check-frozen` does not check the candidate's
ancestry). Nothing is lost while the original branch or the candidate tag
still exists: merge it into main with a merge commit, for example
`git merge --no-ff pilot-01-candidate` (or the original branch), then confirm
with `python tools/workflow_candidate.py --check
evals/workflow/pilot/pilot-01/candidate.json` (or `run-prepare`) and run
`python tools/workflow_eval.py check-frozen`. The merge brings back the
original commits, and the changes the squash already brought in usually merge
cleanly; resolve any conflict in favour of main's current files. If
check-frozen reports the tasks manifest, ask the owner. Run the pilot tools
from main (or a branch that contains `candidate.json`), never from the
candidate's source commit, which precedes `candidate.json`.

Commit both files of a recorded summary at once, right after `summarize
--record`, before any other commit, pull, merge or rebase. A recorded summary
is final and is never recorded again. It names the tools that computed it,
which `summarize --record` requires to be the ones committed at `HEAD`; the
Stage 2 gate and `check-frozen` accept those tools as long as they are
versions committed in the history of the commit that records the summary, so
a pull or tool commit in between does no harm. A rebase that rewrites an
unpushed commit holding those tools can break that link, and the gate then
refuses the summary; before pushing, drop the summary commit, delete the two
files and record again. `summarize --record` refuses while a failure the run
policy lets the operator retry is still open; retry it first. Once the Stage
1 summary is recorded (once `stage1-summary.json` exists in the working tree
or the history), Stage 1 runs (skill runs and baselines) can no longer be
retried or amended, and every Stage 1 `review.md` must keep saying what it
said: a changed record, or a changed verdict that changes what the summary
reports, stops the recorded go from unlocking Stage 2 and leaves the
all-stage summary `incomplete` until it is restored. Review files live
outside Git, so keep a copy of the evidence directory. When the tools have
changed since the summary was recorded, a re-saved review is compared by what
the running tools read from it, so even a re-save can hold Stage 2; the
message then gives the sha256 the summary recorded for each named
`review.md`, and restoring those exact bytes from the copy clears it.

## Checks

`python tools/workflow_eval.py check-frozen` re-derives every file of the
current campaign from the decision files, candidate ledgers, `tasks.json` and
`run-policy.md` and requires byte equality, so a hand-edited frozen file fails
even with updated hashes. It also requires the held-out part of `tasks.json` to
equal the frozen projection; development-task edits stay allowed. Source file
hashes are re-read only when the pinned corpus is present. Superseded
campaigns, and a campaign whose final summary is recorded, get a hash-integrity
check only, so later tool changes cannot fail history. A final summary counts
only when `stage1-summary.{json,md}` (with a `stop` or `invalid` decision) or
`stage2-summary.{json,md}` are summaries `summarize --record` wrote for this
campaign's `candidate.json` and `freeze.json`; any other file named like a
summary is a problem and never switches the re-derivation off. For every
campaign with a `candidate.json`, with or without a summary, `freeze.json` must
be the one `candidate.json` identifies; the hash-only check also requires the
candidate ledgers to keep their frozen bytes. For every campaign it
also checks the fields the re-derivation copies: `supersedes` must name
another frozen campaign (and every earlier campaign must be reached from the
current one through `supersedes`) and `developmentAdjudication` must have its
fixed shape. The history checks read every version a file ever had in the
history reachable from `HEAD`, merges included (a version added, replaced or
removed inside a merge, or on a branch merged later, counts). With the full
Git history, `freeze.json` must equal the version first committed, and
`tasksManifest.sha256` and the development adjudication hash must match the
files committed with it (so commit the campaign, the decisions and
`tasks.json` together, as the freeze says). A campaign whose `freeze.json`,
`candidate.json` or stage summary was ever committed and that is now missing
fails the check, also when `tasks.json` has no `pilotFreeze`. `candidate.json`
and each stage summary are final once committed: each must have exactly one
content in the history and still hold it (a recorded summary is final; a
removal later restored byte for byte changes nothing). The rule is decided
from Git object IDs, so a version whose contents Git cannot read never turns
it into a note, and a version committed as a gitlink or symbolic link is a
problem. Two branches that both
recorded a summary and were merged leave two contents, which cannot be
undone: the owner records `invalidation.md` and a new campaign supersedes this
one, after which the finding is kept as a note. A superseded captured campaign
without a usable `invalidation.md` also fails. When a summary names the
running `tools/workflow_pilot.py` as its renderer, its Markdown must equal the
rendering of its JSON; after a tool change that check is noted as not
verified, so later tool changes cannot fail history, but only when the named
`tools/workflow_pilot.py` is a version committed in the history of the commit
that recorded the summary's content (the summary's own `tooling` field is not
trusted on its word; a hash of tools that were never committed there is a
problem, kept as a note once the owner invalidated the campaign and a new
campaign supersedes it).
The history queries pin Git's `log.follow`, `log.diffMerges` and
`log.showRoot` settings, so a user's Git configuration cannot change what
they list. Without the full history
(a shallow or partial clone, such as a default CI checkout, or no Git) these
history checks cannot run, and check-frozen prints a `not verified` line for
each campaign that names them; the Python CI jobs fetch the full history (the
integration jobs' shallow checkouts only print those notes). A decision file
the current freeze did not include, such as a second review written after it,
is named as added after the freeze; moving it out of
`evals/workflow/decisions/` (it holds a reviewer's decisions, so keep it for a
new campaign) keeps this one. A
changed or missing frozen decision file is named with the command that
restores its frozen bytes from where Git holds them (the index, or the commit
that has them), or with no git command when Git does not hold them yet.

## Private run evidence

Run evidence never enters this directory. It lives outside the repository in
`$MLVIEW_PILOT_DIR/evidence/<run>/`, where `<run>` is the run ID with `:`
replaced by `.`, for example `pilot-nanogpt.codex.1`:

| File | Written by |
|---|---|
| `PROMPT.txt`, `workspace-before.json` and a pending `session.md` | `run-prepare` |
| `session.md` (status, times, settings, deviations), `transcript.txt`, `ui-log.md` | the operator |
| `artifact.mlview.json` (or `partial-artifact.mlview.json`), `workspace-after.json`, `workspace-changes.json` (changed project files, host files and paths where `workspace-before.json` differs from the pinned files), `workspace-changes/`, `doctor.json`, `finish-state.json` | `run-finish` |
| `record.json`, format `mlview-pilot-run/1`, sealed with every evidence hash | `run-finish`; `--amend "<reason>"` keeps the previous seal as `record.previous-<n>.json` |
| `review.md` | `review-template`, then the named reviewer |

`$MLVIEW_PILOT_DIR/preparations.jsonl` gets one line per `run-prepare`
attempt and is never rewritten. A retry (`run-prepare <run> --retry
"<reason>"`) is allowed only if the prompt was never sent, and only as many
times as the run policy's infrastructure retries allow: only after a sealed
`failed` or `blocked` attempt whose `session.md` says `Prompt sent: no`, never
after a timeout, a failure after the prompt or a completed session, and never
when sealed evidence shows the prompt reached the host (a captured artifact,
repair rounds, a sealed transcript that contains `PROMPT.txt`, or a draft the
skill wrote in the workspace: a `*.draft.json` or `*.mlview.json` file, or
anything under `.mlview/`, such as `.mlview/llm/<run-id>/draft.json`). It keeps
the earlier attempt as
`evidence/<run>.attempt-<n>/`; `summarize` verifies each earlier attempt like
a current record, requires the evidence, the attempts in `preparations.jsonl`
and each session's `Prior attempts` to agree, and lists every earlier attempt
in the summary, for skill runs and baselines alike.

A hash identifies bytes; it does not supply human approval.

## Known limits

The history checks exist to catch accidents (a squash merge, a re-recorded
summary, an edited frozen file, a lost commit) and to make tampering visible
in the history; they do not resist someone with push access. A force push, a
rewritten or crafted history, a summary recorded with tools that were
committed only to justify it, a tag moved to another commit, or evidence
files outside Git edited and re-sealed consistently are not caught. Commit
authorship and the `Transcribed by:` line in decision files, branch
protection on main, and the pushed candidate tag are the safeguards; review
who committed what before trusting a result.

With a Stage 1 summary recorded by earlier tools, a changed Stage 1 review
is compared by what the current tools read from it, and the baselines' false
accusations only as one total. So a tool change that judges or counts one
baseline's accusations differently, plus an honest re-save or `>` note of
another baseline review, can hold Stage 2 and name the re-saved review.
Nothing is lost: restore the exact bytes of each named `review.md` (the
message gives the sha256 the summary recorded; keep a copy of every Stage 1
review) and Stage 2 proceeds.
