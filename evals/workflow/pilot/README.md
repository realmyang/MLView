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
| `stage1-summary.json`, `stage1-summary.md` | `summarize --campaign <campaign> --stage 1 --record` | Format `mlview-pilot-summary/1`: the Stage 1 decision (`go`, `stop` or `invalid`), every target with numerator and denominator, breakdowns, caveats and input hashes. The Markdown is rendered only from the JSON. |
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
history; deleting a committed candidate does not count), or after the owner
has written its `invalidation.md`; the freeze then records the reason given
with `--supersede-reason`. It refuses in a shallow clone, whose history could
hide a deleted candidate.

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
summary is a problem and never switches the re-derivation off. The hash-only
check still requires `freeze.json` to be the one `candidate.json` identifies
and the candidate ledgers to keep their frozen bytes. For every campaign it
also checks the fields the re-derivation copies: `supersedes` must name
another frozen campaign (and every earlier campaign must be superseded) and
`developmentAdjudication` must have its fixed shape. With the full Git
history, `freeze.json` must equal the version first committed, and
`tasksManifest.sha256` and the development adjudication hash must match the
files committed with it (so commit the campaign, the decisions and
`tasks.json` together, as the freeze says). What it cannot trace without
history it prints as `not verified`. A captured campaign that lost its committed
`candidate.json`, or a superseded captured campaign without a usable
`invalidation.md`, fails the check.

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
"<reason>"`, only after a sealed failed, timed-out or blocked attempt) keeps
the earlier attempt as `evidence/<run>.attempt-<n>/`; `summarize` requires the
evidence, the attempts in `preparations.jsonl` and each session's
`Prior attempts` to agree.

A hash identifies bytes; it does not supply human approval.
