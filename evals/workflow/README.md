# Evaluating LLM workflow understanding

[tasks.json](tasks.json) fixes eight development tasks and eight pilot tasks.
Pilot repositories are pinned to the existing public-corpus commits. They have
been used for static-analyzer testing; they are reserved from new skill tuning,
not claimed to be absent from model training or all prior project research.
Third-party source stays in the gitignored corpus; only URLs/commits are stored.

The pilot is **8 tasks × 3 native VS Code hosts × 3 fresh sessions = 72 runs**.
Run it in two predefined stages. Stage 1 is one fresh session for every
task/host pair (**8 × 3 × 1 = 24 runs**, with run IDs such as
`pilot-nanogpt:codex:1`). Stage 2 contains the remaining two fresh sessions for
every pair (**8 × 3 × 2 = 48 runs**). Staging changes when work is attempted,
not the matrix or denominators: every planned run stays in its stage's
denominator, and a planned run without a sealed record counts as pending.
The schema/helper/renderer tests and developer-subagent smoke artifacts do not
count as native-host pilot runs. No pilot results or human-reviewed reference
facts are asserted by this manifest. Its reference status explicitly requires
human review.

The completed 2026-09-16–17 developer campaign is summarized in
[DEVELOPMENT_RUNS.md](DEVELOPMENT_RUNS.md). It records structural validation,
repair history, and authoring lessons without claiming native-host coverage or
human semantic scores.

[Reference candidates](reference-candidates/README.md) provide source-linked
draft facts and concrete scenario proposals for all eight held-out tasks,
together with a proposed prompt/budget policy. They are AI-authored inputs to
human review, not frozen truth or completed pilot results. The
[review guide](reference-candidates/REVIEW_GUIDE.md) explains how the owner
records, checks and freezes decisions, and the
[readiness record](PILOT_READINESS.md) lists the remaining gates in order.

Run every command below from the repository root. The evaluation tools read,
hash, compare, copy and render. They never log into a host, run a model, judge
semantics or write a human decision. Frozen files, run records and summaries
are created exclusively, so recorded evidence is never silently overwritten.

## Before running

1. **Reference review.** A named reviewer inspects each pinned scenario and
   records, in `evals/workflow/decisions/<task>.md`, a decision on every
   proposed fact, unknown and non-defect, plus any omitted fact, unknown or
   real defect, before inspecting outputs. Facts keep their IDs and source
   anchors. `python tools/workflow_eval.py check` prints every remaining
   problem as `file:line`.
2. **Run policy.** The owner fills `evals/workflow/decisions/run-policy.md`:
   host models, reasoning settings and invocations, the helper Python, the
   budget and repair limits, how qualified claims count, per-host targets,
   baselines, the full skill and no-skill prompt texts, and privacy. Use the
   same question and budget for each host. If a task needs an additional
   config selection, settle it in the reference scenario before runs. Do not
   silently choose one per host.
3. **Corpus.** Every pinned checkout must pass
   `python tools/fetch_workflow_repos.py --verify`
   (see [source locations](#source-fixture-locations)).
4. **Freeze.** `python tools/workflow_eval.py freeze --campaign pilot-01` is a
   dry run; add `--write` to create `evals/workflow/pilot/pilot-01/`
   ([contents](pilot/README.md)): eight frozen references, their
   `referenceRevision`, the run policy and 16 rendered prompts. The task
   manifest's `prompt` stays condition-neutral; the frozen prompt files are
   what hosts receive. `python tools/workflow_eval.py check-frozen` re-derives
   the frozen files from the decisions and requires byte equality.
5. **Candidate.** From a clean tree, capture the pilot candidate, which builds
   the VSIX itself and pins the frozen campaign
   ([candidate protocol](CANDIDATE_PROTOCOL.md)), then commit its
   `candidate.json`. Its SHA-256 is the campaign identity that every run
   record and summary binds. Merge the freeze, candidate and summary commits
   into main with a merge commit or a fast-forward, never a squash or rebase
   merge, and keep the candidate's `source.commit` reachable
   ([merging a campaign](pilot/README.md#merging-a-campaign)).

```sh
export MLVIEW_PILOT_DIR=~/mlview-pilot
python tools/workflow_candidate.py --campaign pilot-01 --build-vsix
```

`MLVIEW_PILOT_DIR` holds the VSIX, run workspaces and run evidence and has no
default; the run commands also accept `--pilot-dir`. It must be outside the
MLView checkout and outside any Git work tree, and no ancestor directory may
contain `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `AGENTS.override.md` or
`.github/copilot-instructions.md`, because hosts load such files from parent
folders. User-level host configuration cannot be excluded; record it in the
run's `session.md`.

## Run and record

```sh
python tools/workflow_eval.py plan --campaign pilot-01 --stage 1
python tools/workflow_eval.py run-prepare pilot-nanogpt:codex:1 --campaign pilot-01
python tools/workflow_eval.py run-finish pilot-nanogpt:codex:1 --campaign pilot-01
```

`plan` prints the planned run IDs and conditions from the frozen manifest;
`--stage` takes `1`, `2` or `all`, and `--output PATH` also writes the plan to
a new file (never overwritten). `run-prepare` refuses unless the frozen chain,
the pinned checkout and the installed skill identity verify. It then creates a
fresh workspace (`$MLVIEW_PILOT_DIR/workspaces/pilot-nanogpt.codex.1`, not a
Git repository) containing only the manifest's pinned paths, installs the
candidate's skill for skill runs (read from the candidate's source commit, so
a later skill change on main is never installed and never blocks a run; a
note says when the checkout's skill differs), copies the frozen prompt to the
evidence directory's `PROMPT.txt`, appends the attempt to `$MLVIEW_PILOT_DIR/preparations.jsonl`
and prints the operator checklist. Every attempt is prepared once: deleting
an evidence directory never allows preparing the run again.

The operator opens that workspace in a new VS Code window and runs one fresh
native session with the policy's settings and invocation (a baseline sends
the prompt as a plain message, without the skill invocation), then fills
`session.md` in `$MLVIEW_PILOT_DIR/evidence/pilot-nanogpt.codex.1/`: status
(`completed`, `failed`, `timed-out` or `blocked`) and failure kind, whether the
prompt was sent (`Prompt sent: yes` or `no`), start and end times, active and
approval-wait minutes, repair rounds, host and extension versions, model and
reasoning settings (unknown where hidden), invocation, helper Python, exposed
usage, transcript, native UI log, prior attempts and deviations. A failure detail and a deviation's `invalidates:` flag follow
` -- ` (two hyphens) or ` — `; a single `-` is not a separator. Write no
machine paths in `session.md`. Complete the
[live UI checklist](../../docs/LLM_WORKFLOW.md) in the UI log, separately
from semantic scores.

`run-finish` copies the published `pilot.mlview.json`, compares the workspace
with the pinned bytes recomputed from the corpus (not with
`workspace-before.json`), records any changed project file and the skill
doctor report, writes `finish-state.json`, hashes every evidence file into a
sealed `record.json`, and removes the workspace. A file a host writes for its
own settings (Claude Code's `.claude/settings.local.json`) is copied and
reported as a warning, not as a changed project file; in a baseline every
added file counts, including MLView files. A sealed record changes only
through `run-finish ... --amend "<reason>"`, which keeps the previous seal; a
deleted `record.json` is never sealed again with other session facts.
Retain every failure, timeout and block, and never replace an attempt with a
retry the policy does not allow. A retry is allowed only if the prompt was
never sent: after a sealed `failed` or `blocked` attempt whose session says
`Prompt sent: no` (the tool refuses that answer for a timeout, a
`no-publication` or `repair-budget` failure, repair rounds above zero, a
transcript that contains the prompt, a published `pilot.mlview.json` or a
draft the skill wrote in the workspace (a `*.draft.json` or `*.mlview.json`
file, or anything under `.mlview/`, such as the `.mlview/llm/<run-id>/draft.json`
that SKILL.md prescribes), and an amendment never drops or
replaces a sealed transcript), `run-prepare RUN --campaign C --retry
"<reason>"` keeps the earlier evidence as `evidence/<run>.attempt-<n>/`,
prepares a fresh `workspaces/<run>.attempt-<n+1>/` and writes
`Prior attempts: <n>` into the new `session.md`. It refuses an attempt that
timed out, failed after the prompt, says `Prompt sent: yes` or leaves it
empty, completed at any point of its amendment chain, or has sealed evidence
that the prompt reached the host (a captured artifact, repair rounds, a
sealed transcript with the prompt, or a draft in the workspace); it verifies
the sealed record first, and it refuses a retry beyond the policy's
infrastructure retries (with the proposed policy, none) and a retry of a
Stage 1 run once the Stage 1 summary is recorded. Changed project
files and host settings files are not taken as proof, because a host may
write files when it starts. A retry made around these rules makes the run
invalid, and every earlier attempt stays in the summary (its status, failure
and why it counts as sent, including "it completed" for an attempt that
completed before an amendment, in the run entry and the failures list, or in
the baseline section for a baseline, and its hashes in the inputs). Transcripts, UI logs, run
reviews and workspaces stay out of the repository; committed summaries contain
counts, statuses and hashes only.

## Stage 1 stop/go

Do not start Stage 1 until the human-reviewed references, run policy and
candidate, including the skill revision, prompts, budgets, host settings and
repair rules, are frozen and committed. Run the 24 `repeat: 1` records, retain
every failure or block, and complete source-based human adjudication for all
24 before deciding whether to continue. Stage 1 proceeds to the 48 records
whose `repeat` is `2` or `3` only when its reviewed results meet every
predefined target (`pilotTargets` in the task manifest):

| # | Key | Target | Denominator |
|---|---|---|---|
| T1 | `structurallyValid` | 100% structurally valid published artifacts | all planned runs; failed, timed-out, blocked, invalid and pending runs count as not valid |
| T2 | `exactAnchors` | 100% exact supplied anchors | evidence records of completed, non-invalid runs, checked by the frozen helper |
| T3 | `supportedClaimPrecision` | at least 95% supported claims | observed and inferred claims of reviewed runs; qualified claims count as the run policy says |
| T4 | `essentialFactRecall` | at least 85% essential-fact recall | all planned runs, each against its task's frozen essential facts |
| T5 | `knownUnresolvedQualified` | every must-state unknown explicitly stated | all planned runs, each against its task's frozen must-state unknowns |
| T6 | `highSeverityFalseAccusations` | zero high-severity false accusations | reviewed runs; a `high` finding judged `unsupported` |

T1, T4 and T5 count every planned run (intention to treat), so a missing or
failed run never counts as a pass. Recall and unknown values over reviewed
runs only are reported beside them as secondary. If the run policy asks for
per-host targets, T3 and T4 must also be met within each host.

```sh
python tools/workflow_eval.py review-template pilot-nanogpt:codex:1 --campaign pilot-01
python tools/workflow_eval.py summarize --campaign pilot-01 --stage 1
```

`summarize` verifies before it counts. It reads every frozen input and the
artifact helper at the candidate's source commit, validates each artifact with
that frozen helper against the pinned corpus, and re-hashes every sealed file.
An integrity failure, such as a missing or changed evidence file, a wrong
prompt, candidate or reference hash, or an unplanned or duplicate run, exits 1
with no decision. A protocol violation makes the run `invalid`, which counts
as a failure: settings that differ from the policy, over budget, too many
repairs, a helper Python older than 3.10, a changed project file (or a
`workspace-before.json` that differs from the pinned files), a wrong producer
host, skill identity drift, a baseline with MLView available or an MLView
file in a baseline workspace, a retry after a completed attempt or after an
attempt that sent the prompt, or a deviation marked as invalidating. A baseline is held to the policy's model and
reasoning, not to the skill invocation. `--json` prints the machine-readable
summary. The decision is always labeled "computed against the predefined
targets; not an approval":

- `incomplete`: a planned run is pending, a completed run is unreviewed, a
  review still has problems (each run is named with its first problem, for
  example `remove review.md` after an amendment to `failed` or `timed-out`),
  or the corpus was absent. Early-stop indicators list targets that can no
  longer be met, but no decision is issued before all 24 runs are adjudicated;
  a failure the run policy still lets the operator retry is marked "may still
  be retried" and counted as open.
- `stop`: complete, and at least one target is missed; the reasons give each
  numerator and denominator.
- `go`: complete, and all six targets are met. This permits collecting the 48
  repeats; it is not a pilot pass.
- `invalid`: the owner wrote `evals/workflow/pilot/<campaign>/invalidation.md`.
  Tools never create it.

`--record` also creates `stage1-summary.json` and `stage1-summary.md` in the
campaign directory, only for `go`, `stop` or `invalid`. For `go` or `stop` it
also waits until every planned baseline is sealed and reviewed (baselines
never change the decision; a completed baseline without a finished review
shows as `unreviewed`, with no paired difference, and neither does a pending
one; a baseline that did not complete needs its `review.md` removed) and
until no failure the run policy still lets the operator retry is open (the
summary lists each with its `run-prepare ... --retry` command; retry it
first). The same retry rule applies to `--stage all --record`. Commit both
files at once, right away, before any other commit, pull, merge or rebase. A
recorded summary is final: `--record` refuses a summary file that was ever
committed, in any branch merged into `HEAD`, even after it was deleted. So is
the Stage 1 evidence behind it: once `stage1-summary.json` exists in the
working tree or the history, `run-prepare --retry` and `run-finish --amend`
refuse every Stage 1 run, skill run or baseline (retry or amend before
`--record`; undo any edit made for a refused amendment, because `session.md`
must keep its sealed bytes), and every Stage 1 `review.md`, skill run or
baseline, must keep its content. Beside each review's SHA-256 the summary
records a normalized hash (`inputs.runs[].reviewNormalized`, review
normalization v1), and the Stage 2 gate compares it for every review the
summary lists, whichever tools recorded the summary. Normalization v1 decodes
the file as UTF-8, strips a leading BOM, treats CRLF, CR and LF alike, strips
trailing whitespace from every line, drops blank lines and `>` notes (lines
whose first non-blank character is `>`, which the review grammar ignores),
keeps leading indentation (a continuation line depends on it), and takes the
SHA-256 of the remaining lines, each ended by LF. So after the record only
`>` notes (added, edited or removed), line endings, trailing spaces and blank
lines may change. Any other change, such as a verdict, a reason, the
reviewer, the date, a severity, a false accusation added or removed, a
changed indentation or a deleted review, stops the recorded go from unlocking
Stage 2 and leaves the all-stage summary `incomplete` until that `review.md`
is restored exactly as it was, apart from those changes. Review files live
outside Git, so keep a copy of the evidence directory. `run-prepare`
refuses repeat runs until a committed Stage 1 summary says `go`, and it and
`summarize --stage all` re-compute Stage 1 from the sealed evidence and the
reviews: a summary that is not a recorded Stage 1 summary of this candidate,
whose decision differs from the re-computation, whose other fields or
Markdown differ from what `summarize --record` writes, that differs from the
version first committed, or that was committed with more than one content
(for example through a merge), does not unlock Stage 2, and those Stage 2
runs count as invalid. When the Stage 1 evidence here differs from the
summary's sealed inputs (a record, amendment or earlier attempt changed, or
missing from this pilot directory) or a review it lists has lost its
normalized hash, the message names each run and file and what to restore,
`run-prepare` refuses Stage 2, and `summarize --stage all` is `incomplete`
with a note instead of marking the Stage 2 runs invalid; so it is when the
re-computation is incomplete only because the corpus is absent or unverified
here. The
summary's `tooling` field is part of the file being checked, so it never
switches a check off on its own word: when it names the running tools, every
field and the Markdown rendering are compared; when it names other tools,
each of them must be a version of that file committed in the history of the
commit that records the summary (`summarize --record` refuses tools that
differ from `HEAD` in this checkout; those tool versions stay in the history
of the summary's commit after a pull, merge or tool commit in between, but a
rebase that rewrites an unpushed commit holding them can break the link:
before pushing, drop the summary commit, delete the two files and record
again), `skills/mlview/scripts/artifact.py` must be the candidate's frozen
helper, and the decision, the sealed inputs, the normalized review hashes and
the disclosure of retries and failures (each skill run's status, failure and
earlier attempts, and each baseline's failure and earlier attempts; a
baseline's computed status and review state belong to the tools) are still
compared (a note says the other fields and the Markdown were not compared).
What the tools read or count from a review (whether it is complete, its
verdict counts, the baselines' false accusations total, a skill run's
reviewer) is never compared across tool versions, so a later tool version
that judges or counts a review differently does not hold Stage 2 over an
unchanged or re-saved review (unless the re-computed decision is no longer
`go`). A review the recording tools did not read (a
baseline they judged invalid) is not listed in the summary and is not
compared; an earlier attempt is never reviewed, and its raw review hash, if
any, stays evidence only. A Stage 1 summary recorded before normalized review
hashes existed has none: it does not unlock Stage 2, and the message says to
record Stage 1 again with the current tools. No pilot has run, so no such
summary exists; the tools refuse one rather than fall back to comparing
re-derived verdicts. With
per-host targets, a stop reason names
each host that misses a target, and the early-stop indicators include each
host's bound.

If any target misses, stop before Stage 2 and report the numerators,
denominators and failure taxonomy. Do not repair the skill against held-out
outputs and then count repeats as confirmation of the original frozen system.
An implementation or protocol failure that makes Stage 1 invalid requires the
owner's invalidation record and a newly frozen campaign; it is not a pass.
Passing Stage 1 authorizes collection of the repeats but does not establish
pilot success. The same six targets apply to the complete 72 human-reviewed
runs: `summarize --campaign pilot-01 --stage all` reports `targets-met`,
`targets-missed`, `incomplete` or `invalid`.

## Review and adjudicate

Each completed run gets one human review file, `review.md` in its evidence
directory. `review-template` writes one line per artifact node, edge,
finding, coverage summary and configuration, so no element can be skipped.
The reviewer gives each a verdict, `supported`, `qualified`, `unsupported` or
`no-claim`, with a reason after ` -- ` (or ` — `) for anything other than
supported or no-claim, and adds `<pointer>#2`, `#3`, ... lines (no leading
zeros) when one element makes several claims. The claim type
comes from the artifact's basis, not from the reviewer. Count factual
assertions in node details, edge meanings, findings, scenario choices and
coverage summaries as claims. Map equivalent wording/grouping to reference
facts; do not score JSON similarity or reward unresolved placeholders as
covered behavior. Unresolved-basis elements and `no-claim` lines are listed
but never counted in precision.

For each frozen essential fact the reviewer writes `covered`, `partial`,
`missing` or `contradicted` with the artifact pointers, and for each
must-state unknown `stated` or `not-stated`. For essential facts, the
denominator is the frozen task reference, not the claims the model chose to
make. Reviewers no longer count anchors: exactness is computed by the frozen
helper from the artifact's evidence records. Severity agreement and task
usability (six questions and overall usefulness) are recorded and reported,
not gated. Baseline reviews cite transcript line ranges (`response:12-14`)
instead of artifact elements. `python tools/workflow_eval.py check <path>`
validates a `session.md` or `review.md` like the owner's decision files (a
`review.md` of a run whose record is no longer `completed` is told to go).
Stage 1 reviews are final once the Stage 1 summary is recorded: afterwards
change nothing but `>` notes, line endings, trailing spaces and blank lines,
and keep a copy of the evidence directory (see "Stage 1 stop/go").

A second model may help locate disputed claims but cannot replace
source-based human adjudication. Each run has a single human reviewer, and
summaries say so. Missing or blocked runs stay visible and never count as
passes. Report per-host/task results and numerators/denominators; repeated
runs on the same eight tasks are not 72 independent tasks.

No Stage 1 or Stage 2 run has been completed or human-reviewed. None of the
targets above has passed; they remain stop/go criteria rather than
measurements. A complete matrix does not itself mean these targets passed.

Development-task adjudication is separate: the owner records verdicts on the
provisional native development reviews in
`evals/workflow/decisions/development-adjudication.md`.

## Compare without the skill

Compare the same Stage 1 tasks with a native assistant without the skill when
the run policy plans 24 baseline sessions; `plan` then lists them as
`<task>:<host>:baseline:1`. Baselines use the frozen no-skill prompt, the same
pinned source, model settings and budget, have no skill installed, and are
never part of the stop/go gate. The static product is retired and is not an
active evaluation condition. Keep those conditions in separate records; do not
mix them into the 72 skill runs.

## Source fixture locations

Current development entrypoints are listed in `tasks.json`. Source examples
formerly under the removed analyzer now live in `fixtures/`. Recorded native
outputs keep their original citation paths and hashes; the evaluation-only
`fixtures/historical-paths.json` mapping resolves moved files and verifies their
original bytes. This mapping is not used by the product validator or viewer.
Open historical artifacts against their recorded source revision for live
navigation; the current `samples/configured_training.mlview.json` example uses
paths that remain valid in this checkout.

The eight held-out repository pins and sparse paths are in `repositories.json`.
Fetch only the source needed for an evaluation with
`python tools/fetch_workflow_repos.py` from the repository root, optionally
`--repo nanoGPT`. This is an explicit network operation and never runs analysis
or executes fetched code. Existing dirty or differently pinned checkouts are
refused rather than reset. `--verify` (optionally with `--json`) reads every
checkout without changing it and checks its HEAD, clean state, sparse patterns
and blob-exact files. `--update-sparse` applies a changed sparse list to a
clean checkout at its pin, refusing if that would drop a covered file; it may
fetch newly included blobs, and says so.
