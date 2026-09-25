# What the pilot owner needs to review

The pilot needs a human-checked answer key before any held-out model output is
inspected. The [packet](README.md) proposes **93 facts with 106 source anchors,
25 unknowns and 20 non-defects across eight tasks**. These are proposed
references, not approved answers. Passing code tests or approving development
work does not approve them.

You can review the references yourself or nominate reviewers familiar with the
relevant frameworks. You do not need to run training, operate the assistants,
edit JSON, type hashes, copy quotes or count facts. You write your decisions
into one plain-text file per task, a checker says exactly what is still
missing, and a freeze command derives the frozen reference from your words.
Human semantic decisions remain attributable to the person who actually
checked the source.

## First: review one task at a time

1. Open `evals/workflow/decisions/pilot-nanogpt.md`, which has ten proposed
   facts. Every item says `pending`, and its proposal is shown right above it
   on lines starting with `>`. The tool writes those lines and the parser
   ignores them, so editing them changes no decision: `accept` always takes
   the proposal from the candidate ledger. If a proposal line under an item is
   missing or differs from the ledger, for example because someone edited it,
   the check prints a note that quotes the ledger's text, so read that note
   before you accept. After the freeze, a frozen file is compared byte for
   byte, `>` lines and line endings included, so leave it exactly as
   committed; the note then only says which proposal the freeze took.
2. Read the exact pinned source: in VS Code (`.public-corpus/nanoGPT/train.py`),
   or in an optional local sheet that shows every cited line in context.
   `python tools/workflow_eval.py context pilot-nanogpt` writes it to
   `.mlview/review-context/pilot-nanogpt.md`, which is gitignored.
3. Replace each `pending`. Keys and choice words are case-insensitive.

| Item | Write | What to check |
|---|---|---|
| Scenario | `Decision: accept`, or `Decision: replace` with `Description:`, `Entrypoints:`, `Arguments:` and `Reason:` | Are the entrypoints, arguments, defaults and excluded cases appropriate? A proposal with a `<...>` placeholder cannot be accepted: Flax still needs a concrete workdir. The notebook draft covers cells 0–220. |
| Fact | `Decision: accept`, `qualify` or `reject`. `qualify` also needs `Wording:` (your corrected claim) and `Reason:`; `reject` needs `Reason:` | Read the cited lines **and their context**, including conditions or configuration overrides. `accept` takes the claim, basis and essential flag exactly as proposed. |
| Basis, essential flag or anchors | Only to change a proposal: a `Basis:`, `Essential:` or `Anchors:` line, plus `Reason:`. `Anchors:` replaces the proposed list, so repeat every proposed anchor you keep; the check notes each proposed anchor that is dropped | Is the fact observed directly in source, an inference needing assumptions, or unresolved? Source code alone does not prove an actual runtime outcome. Would omitting the fact materially weaken an answer to the task? The essential facts you keep, plus the facts you add, define the task's recall denominator. |
| Unknown | `Decision:` as for facts, then `Runs must state: yes` or `no` unless rejected | Is the listed limitation accurate? `yes` means every run must state this uncertainty. |
| Non-defect | `Decision:` as for facts | Is intentional behavior being mistaken for a defect? Run reviewers judge false accusations against the non-defects you keep. |
| Anything missing | A new section `## Added fact nanogpt-h01`, `## Added unknown nanogpt-hu01` or `## Defect nanogpt-d01` | The file lists the lines each one needs. A defect needs evidence, counter-evidence and a severity. |

Anchors are `path:LINE` or `path:LINE-END`. Notebook anchors are
`path#cellN:LINE-END`, with a zero-based cell and one-based lines inside that
cell. Separate several anchors, entrypoints or arguments with `;`, and write
`none` for an empty list. A line indented by two or more spaces continues the
previous value, also after a blank line; an unindented line is an error, so
indent a wrapped `Reason:` or `Wording:` instead of turning it into a note.
Put your own notes on `>` lines; before the freeze you may add, edit or
remove `>` lines. A line starting with `#` is not a comment: it is always
reported as an error, and where the lines after it go depends on its form:

- A mistyped heading with an item kind and a word with a digit (`### Fact
  nanogpt-f02`, `# Fact nanogpt-f02`, but also `# Fact v2`) starts an item of
  that name, so the lines after it, up to the next heading, belong to it.
  For a real item they are read; for a name that is not an item of the task
  (`v2`) the check says it is not an item, and a `Decision:` after it no
  longer belongs to the item above it, which then reports its decision
  missing.
- A line that looks like a heading of an unknown section, meaning `## Notes`,
  two or more `#` (`### Fact checked`), or one `#` followed by a section kind
  alone (`# Facts`) or by one word that could be an ID of that kind (`# Facts
  nanogpt-f02`), skips the lines after it until the next `## ` heading, and
  the error says they were not read.
- Any other `#` line is reported under its section, and your decisions around
  it are kept. That covers prose (`# checked twice on the train`), one `#`
  before an item kind and a word without a digit (`# Fact checked`, `# Defects
  none`; every item ID has a digit), and one `#` before a section that takes
  no ID and one word (`# Scenario checked`, `# Task done`).

Section headings are `## <Kind> <id>`, with exactly two `#` and a space; put
your notes on `>` lines instead of any of these forms.

For example, `nanogpt-f02` proposes that the no-override scenario initializes
from scratch. Its anchor is `train.py:41`, where `init_from` is assigned
`'scratch'`. Review the surrounding configuration and initialization branches
before deciding whether the wording, `observed` basis and `Essential: yes` are
justified. This example deliberately does not supply the verdict; it only shows
how a qualification with an extra anchor is written:

```markdown
## Fact nanogpt-f02
> Claim: ...
> Basis: observed. Essential: yes. Anchors: train.py:41
Decision: qualify
Wording: <the claim as the source supports it>
Anchors: train.py:41; train.py:<other lines you relied on>
Reason: <what you checked and why the wording and anchors changed>
```

4. Check the file:

```sh
python tools/workflow_eval.py check pilot-nanogpt
```

Each problem is one line, `file:line: LEVEL section: message`, where LEVEL is
`ERROR`, `TODO` or `NOTE`; click it in VS Code's terminal to open that line.
Only errors make the exit status 1. When every item is decided, fill
`Reviewer:` and `Date:` (YYYY-MM-DD) and write `Review: complete` under
`## Task`. The check then ends with `ready to freeze`. It checks anchor line
ranges only when the pinned corpus is present; otherwise it says
`anchors not checked: corpus absent (freeze requires it)`. Never change the
`Candidate:` line, which binds the file to the immutable ledger bytes. If you
delete a section by mistake,
`python tools/workflow_eval.py template --show pilot-nanogpt` prints the
pristine file. Then review the other seven tasks;
`python tools/workflow_eval.py check` with no target checks every file in
`evals/workflow/decisions/`.

## A second reviewer

A second reviewer is useful for high-severity judgments and disputed claims.
`python tools/workflow_eval.py template pilot-nanogpt --second` creates
`pilot-nanogpt.second.md` and never overwrites an existing file. The second
reviewer decides any subset of items (`pending` means not reviewed) and writes
`Review: complete` when their decisions are final. Their own additions use a
separate ID space (`nanogpt-s-h01`, `nanogpt-s-hu01`, `nanogpt-s-d01`), so the
two reviewers' additions never share an ID. The check of your file then lists
every item where the two of you differ in decision, basis, essential flag,
runs-must-state or severity (wording is not compared), and every item the
second reviewer added. Each stays a TODO until you add
`<item id>: <how it was resolved>` under `## Disagreements`. To adopt an
addition, add it to your file under your own ID and write
`<their id>: adopted as <your id> -- <why>`: the check requires your ID to be
an added item of the same kind, and the frozen reference records the link
(`adoptedAs`), so summaries count the adopted item inside the denominators.
A resolution that starts with `adopted` is always read as an adoption. Two
more rules catch a mistyped adoption:

- A resolution that names your own added item of the same kind (a trailing
  `.` does not matter), whatever its first word, is an error until it reads
  `<their id>: adopted as <your id> -- <why>`, or until you remove your ID
  from the line because the item is not adopted. `nanogpt-s-d02: not adopted
  -- duplicates nanogpt-d01` is still an error when `nanogpt-d01` is your own
  added defect; write `nanogpt-s-d02: not adopted -- duplicates my defect`
  instead.
- A resolution whose first word looks like `adopted` (`adopt as`, `adpoted`,
  `Adoption`) is an error until it uses the adoption form or starts with
  another word, such as `not adopted -- <why>`.

Naming an added item of another kind (an added fact in a defect's resolution)
is fine, since only the same kind can be adopted.
If the addition duplicates a
candidate item that is already in your reference, it is not an adoption:
write `<their id>: same as <candidate id> -- <why>`, without the word
`adopted`. Keys are case-insensitive, so one item has one resolution line.
Your file holds the final decision, and the frozen reference keeps both
positions and the resolution. The second reviewer's file has no place for
your own additions, so your added facts and defects are second-reviewed only
through theirs: they add the same item under their own ID (the note names
an unused one, such as `nanogpt-s-d01`, and mentions a second-review defect
that has no resolution yet as a possible match) and you resolve it as adopted.
Until then, the check keeps a note on each of your high-severity defects;
after the freeze, the note on a frozen file only says the defect was not
second-reviewed in that campaign, because a second opinion then needs a new
campaign. The second reviewer must be a different person (the check refuses
the same name), and only a person can be a second reviewer; another model's
opinion is not human acceptance.

## Then: agree on the run policy

Fill `evals/workflow/decisions/run-policy.md`. The
[proposed policy](README.md#proposed-common-run-policy) appears only on `>`
lines; no value has a default. You decide:

- the model, reasoning setting and invocation for Copilot, Codex and Claude Code;
- how each host's terminal finds a Python 3.10+ `python3` for the skill's
  helper (macOS `/usr/bin/python3` is 3.9), described without a machine path;
- the budget: active minutes, validator repair rounds and infrastructure
  retries (the proposal is 20 minutes, two repairs and no retries);
- whether qualified claims count as `not-supported` or `supported` in
  precision, or are `excluded`, and whether precision and recall must also
  meet their targets within each host;
- whether to run the 24 matched no-skill sessions, and whether the development
  adjudication below must be complete before Stage 1;
- the six predefined stop/go targets (`Decision: accept` confirms them);
- the full skill and no-skill prompt texts, shown as fenced blocks; and
- what else, if anything, may be published.

`python tools/workflow_eval.py check run-policy --show-prompts` checks the file
and prints all 16 prompts (eight tasks, with and without the skill) exactly as
the hosts will receive them after each host's invocation. The no-skill prompt
may not mention MLView, the skill, WorkflowDocument, publishing or
publication.

Optionally, `evals/workflow/decisions/development-adjudication.md` records your
verdicts on the 12 provisional native development reviews and the three
baseline notes; a reason follows ` -- ` (two hyphens) or ` — `, and a single
`-` is not a separator. Check it with
`python tools/workflow_eval.py check development-adjudication`, which ends
with `complete` when every verdict is final. The ledgers themselves are never
edited.

## Freeze

When every file is ready, ask for the freeze or run it yourself:

```sh
python tools/workflow_eval.py freeze --campaign pilot-01
python tools/workflow_eval.py freeze --campaign pilot-01 --write
```

The first command is a dry run: it prints each task's counts and every unmet
precondition with its next action. `--write` creates
`evals/workflow/pilot/pilot-01/` ([contents](../pilot/README.md)) and marks the
eight held-out tasks `frozen` in `tasks.json`. The freeze needs every pinned
checkout verified (`python tools/fetch_workflow_repos.py --verify`). A checkout
fetched before a manifest change to its sparse patterns (such as mmdetection's
config files) is repaired once with
`python tools/fetch_workflow_repos.py --update-sparse --repo <name>`, which
refuses to drop any materialised file; the freeze names that command when it
applies. It refuses
anything pending, re-verifies every kept quote against the pinned source, copies
no source text into the repository, and adds no judgment or approval. Commit
`evals/workflow/decisions`, `evals/workflow/pilot/pilot-01` and
`evals/workflow/tasks.json` together before you edit any of them again
(until that commit, Git does not hold the frozen bytes), and merge them into
main with a merge commit or a fast-forward, never a squash or rebase merge
([why](../pilot/README.md#merging-a-campaign)). After the freeze, changing the
reference means a new campaign. `check <task>` says `frozen in pilot-01` for
an unchanged file, including a primary file whose second review was added,
edited or removed after the freeze: the disagreements this causes are listed
as notes for a new campaign, and removing the late file (or restoring the
frozen second review) keeps pilot-01. That includes a second review that no
longer parses, for example because it was re-saved as UTF-16 or in a Windows
ANSI encoding: `check` names its restore, not a change to your file. A
frozen file that was deleted is named with its restore too, both by `check
<task>` and by `check` without a target, never with a new template in its
place. An edited file is reported as
`changed after the freeze of pilot-01`, with the command that restores the
frozen bytes when no decision was meant to change (a `>` note or a
line-ending conversion also counts as a change). That command names where Git
holds exactly those bytes: `git checkout -- <file>` when the index has them,
or `git checkout <commit> -- <file>` for a committed change or removal. When
Git does not hold them (the freeze is not committed yet), no git command is
offered, because restoring the committed file would bring back the pending
template: undo the edit in your editor instead. `check-frozen` names each
changed, removed or added decision file.

## After runs: review the outputs separately

The named reviewer then judges each run against the frozen reference in that
run's `review.md`, which
`python tools/workflow_eval.py review-template <run id> --campaign pilot-01`
creates and `check` validates like the other files. This produces the
supported-claim, qualification, essential-fact, unknown and false-accusation
counts. Do not change the reference facts or denominator after seeing a model
miss something. Approving the reference packet does not pre-approve any output.

## Effort and limits

- The eight references take about 170 decision lines, the optional
  development adjudication about 190, and each run review about 40–60 (about
  1,200 for the 24 Stage 1 skill runs, plus any baselines). There are no bulk
  verdicts, because a bulk accept would manufacture an approval.
- The tool checks what a file says, not who wrote it: it cannot authenticate a
  person. Attribution rests on the `Reviewer:` line, commit authorship and
  `Transcribed by:`. When an assistant types decisions you dictate, it fills
  `Transcribed by:`; only you write `Review: complete`, after reading the whole
  file. Agents never write decisions on their own initiative.
- A hash identifies bytes; it does not supply human approval.

See the [evaluation protocol](../README.md) and
[candidate protocol](../CANDIDATE_PROTOCOL.md) for the complete rules.
