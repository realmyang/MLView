# Current status

MLView ships one workflow: invoke the native `mlview` skill in Copilot, Codex or
Claude Code, then open its `*.mlview.json` artifact in the VS Code extension.
The active model interprets source and authors the diagram. Python helpers
validate structure, workspace paths, hashes and exact citations; they do not
perform semantic analysis.

The old static analyzer and all of its runtime integrations were removed on
2026-09-18 at the maintainer's request. There is no analyzer CLI, Python package,
static rule engine, MCP analysis server, static Copilot tool, pre-commit hook,
or analyzer GitHub action in the current tree.

The native path includes installed skill ZIPs, a Claude skill plugin, a
WorkflowDocument contract, source/notebook navigation, evidence and
counter-evidence, scope filters, refinement prompts and revision watching.
Malformed revisions retain the last valid diagram. No model runs on open,
refresh, filtering or source navigation.

This remains experimental. Recorded native development artifacts and review
ledgers are preserved, including their known shortcomings; human semantic review
and the held-out native-host pilot are still pending. Structural test results do
not establish model accuracy. See [the evaluation protocol](../evals/workflow/README.md)
and [current validation](VALIDATION.md).

Historical live host exercises predate this removal. Windows and remote VS Code
interaction need live validation before compatibility is claimed. Latest CI
results: see [VALIDATION.md](VALIDATION.md) and the repository's
[Actions page](https://github.com/realmyang/MLView/actions).

Unreleased: Campaign 3 fixes the issues a
public shakedown found (see the [changelog](../CHANGELOG.md)). The skill ran
once per host on 12 public repositories outside the held-out pilot, and a
provisional model review, not a human review, ranked 22 issues. The helper
adds a read-only `excerpt` command that prints exact evidence records,
`quote_mismatch` and reference errors that locate the problem, six
non-blocking hygiene warnings, a `basis` summary and multi-record `upsert`;
the skill defines repair rounds, early and partial drafts, basis, findings and
structure rules; the viewer opens the authored header collapsed so the canvas
keeps its height, wraps titles, drops the `?` glyph for authored nodes and
styles the recommended edge kinds; and the extension reports deleted cited
files as missing. Fixes from four model reviews of the integrated branch
make default excerpt IDs unique per path, bound the `foundAt` search, draw
authored self-edges as loops, keep a revealed finding target beside the
narrow-window rail drawer and keep the collapsed header's controls visible on
short panels. A confirmation run of ten shakedown cases with the fixed skill
then bounded the critique (correct what the draft covers, then publish) and
stopped counting refused upserts as repair rounds; that last change has not
run on a live host ([record](demo-logs/2026-09-26-public-shakedown.md)).
There is no schema change and no version bump. Issues 13, 16, 19 and 20 are
deferred on purpose. Local checks and CI: [details](VALIDATION.md); the pilot
has not run, and once quotes come from `excerpt` the pilot's exact-anchor
target shows only that cited ranges exist and are fresh.

Unreleased viewer fixes from the Stage 1 review: phase and group badges and
the Outline's rows count each finding once, so they agree with the toolbar,
and a collapsed group counts the findings of the connections it hides.
Hovering a connection or its severity marker lists its findings, as hovering a
step does, and the connection's Inspector lists them too. Hovering a step
lights and animates only its direct connections, and the cards it dims stay
clickable; focus mode (select, then F) keeps the full upstream and downstream
lineage. These are checked by local jsdom tests only, not in live VS Code
([changelog](../CHANGELOG.md)).

Unreleased viewer M1, step 1 (the verification loop): a click on a step,
connection, finding or Outline row only selects it. Enter, a double-click or
an Inspector Open link opens the cited range beside the diagram, selected and
highlighted, with focus kept in the diagram; Alt+Enter moves focus to the
editor. A notebook citation selects its cell, and highlights the cell's lines
when VS Code has its editor ready. Steps, connections, findings and quotes
that cite a changed or missing file are marked where they are drawn, their
jumps are blocked, and the status bar counts the files. When the workspace
root is a parent of the folder the diagram cites from, and the files there
match the published hashes, the banner says so and offers to add or open that
folder instead of calling the files changed. No contract change and no new
setting. Checked by local tests only (jsdom and the mock `vscode` module), not
in live VS Code ([changelog](../CHANGELOG.md)).

Unreleased viewer M1, step 2 (the Inspector shows the claim): the Inspector
shows a step's full authored detail under its title, phase label and kind; the
basis once, with a one-line note for inferred and unresolved claims; the
findings on the item with their suggestion, labelled "What to change" (an old
analyzer rule had hidden every suggestion); a caption over the quotes saying
a matching quote does not show that the lines support the claim; and one line
linking to the document-wide limitations, now listed only in the header
Details. A card's accessible name carries the first sentence of its claim.
Notebook cells print as the artifact records them, counted from 0, so they
match the model's own labels. Layout and geometry golden unchanged. Checked by
local jsdom tests only, not in live VS Code ([changelog](../CHANGELOG.md)).

Unreleased viewer M1, steps 3 and 4 (cleanup): the code and styles left from
the static analyzer's viewer are removed, since the viewer only shows authored
documents. Nothing you can use changes, apart from a merged connection's
tooltip and screen-reader name, which no longer describe the retired rollup
weight. The webview's TypeScript went from 26,061 to 18,499 lines and its
bundle from 365 KB to 286 KB (stylesheet 82 KB to 62 KB). Layout and geometry
golden unchanged. Checked by local tests only, not in live VS Code
([changelog](../CHANGELOG.md)).

Unreleased viewer M1, screenshot harness: `webview/tools/screenshots/capture.mjs`
saves headless-Chrome screenshots of the viewer with a simulated host (VS Code
theme colours, the panel's own bootstrap, the extension's `init`, `workflow`
and `stale` frames), with `--viewer` for before/after pictures of another
checkout. The capture is opt-in, outside CI and the e2e gates, and needs a
local Chrome; its pipe and Chrome-lookup test (`webview/test/screenshot-pipe.test.mjs`)
does run in `npm test`, CI and both e2e drivers. Its pictures are a rendering
check, not live VS Code validation or usability evidence
([details](../webview/README.md#screenshots-opt-in)).

Unreleased viewer M1, review fixes: a real double-click on a finding or an
Outline step now opens it (the first click rebuilt the rows, so the second
never arrived), and a double-click opens what its first click selected even
when that click opened the rail over the canvas or shifted the rows; the
second click no longer presses whatever lands under it. A notebook jump that
a later jump overtakes no longer clears the later highlight. The cited-range
highlight has a border in High Contrast themes. In the wrong-workspace-root
case every surface says the file is in another folder, matching the notice,
and the notice leads with the files. The stale marks are darker in light
themes (at least 4.2:1). A card's spoken claim no longer stops at "i.e.".
The Inspector's stale note no longer says "the claim was not re-checked".
Checked by local tests only (jsdom and the mock `vscode` module), not in live
VS Code ([changelog](../CHANGELOG.md)).

Unreleased viewer M1, live check fixes: an extension restart inside a window
no longer leaves a dead diagram tab. VS Code restarts its extensions for
**Developer: Restart Extension Host**, an extension install or update that
restarts extensions, **Save Workspace As...** and adding a folder to a
single-folder window (the root hint's **Add folder to workspace** or VS Code's
**Add Folder to Workspace...**), and it never revives a live panel afterwards.
Each window's open diagrams are kept in the extension's global state under the
window's session, and the next extension host puts each one back in its tab's
place, checked against the workspace as it is then. A tab in front of its
group comes back at once; a tab behind others comes back when it is brought to
the front (blank for about half a second), since until then it cannot be told
from a restored tab not yet shown. A diagram put back this way starts with a
fresh view (selection and zoom reset); Reload Window keeps them. The root hint no longer also shows a VS Code
notification, which outlived a restart with dead buttons; the panel's notice
carries both actions. Multi-root windows recheck in place; Reload Window
revives panels through the serializer. Checked by mock `vscode` tests (with a
mutation check) and in an isolated VS Code 1.139 Extension Development Host for
the hint's and VS Code's Add Folder, Save Workspace As, Restart Extension Host,
Reload Window and the multi-root case; an extension install or update was not
tried ([changelog](../CHANGELOG.md)).

Version 0.3.0 adds Campaign 2, "pilot readiness" (see the
[changelog](../CHANGELOG.md)): owner decision files with a `check` command,
the campaign freeze and `check-frozen`, the v2 pilot candidate that builds its
own VSIX, sealed run records, and a `summarize` that verifies every sealed run
against the frozen campaign and computes the Stage 1 stop/go decision. The
owner's reference review has not happened and **no reference is frozen**: every
file in `evals/workflow/decisions/` is a pending template. The pilot has **not
run**: Stage 1 has 24 skill runs pending and 0 passed, and Stage 2 has 48
pending. The fixes for the campaign's six reviews (37, 15, 25, 19, 15 and
36 findings), for the three regressions its final check found and for the
three a follow-up check found are in:
among them, a run is retried only if its prompt was never
sent (`Prompt sent: no` in `session.md`, refused against sealed evidence that
it was sent, including the skill's drafts under `.mlview/`), every earlier
attempt stays in the summary, `check-frozen` and `--record` fail when a
recorded summary or candidate in the history reachable from `HEAD` was
removed, replaced or recorded twice, merges included, Stage 1 runs and
reviews are final once the Stage 1 summary is recorded, a summary's own
`tooling` field never switches a check off (other tools must be versions
committed in the summary's history), deleting a committed campaign does not
clear the way for a new one, and `run-prepare` installs the candidate's skill
from its source commit, so later skill changes on `main` do not block runs.
Campaign commits reach `main` by a merge commit or fast-forward, never a
squash or rebase merge. The history checks catch accidents and make changes
visible; they do not stop someone with push access from rewriting history,
and commit authorship, `Transcribed by:`, branch protection and the pushed
candidate tag are the safeguards
([known limits](../evals/workflow/pilot/README.md#known-limits)). With these
fixes, the local gate passed on one macOS machine, and all 12 CI jobs
(Python 3.10–3.14, Node 20.18.1 to 26, macOS and Windows) passed on the
branch ([details](VALIDATION.md)). Since 0.3.0 (unreleased, checked locally
only), the Stage 2 gate compares a normalized hash of every Stage 1 review
instead of re-deriving its verdicts, so after the Stage 1 record only `>`
notes, line endings, trailing spaces and blank lines may change in a review,
and a later tool version that reads or counts reviews differently no longer
holds Stage 2 unless it changes the decision, which closes the narrow case
(RC2-1) that 0.3.0 left open. A tools change that rejects a recorded Stage 1
review does change it (to `incomplete`), so such a change must wait for the
next campaign. 0.2.0
shipped to `main` on 2026-09-25, when PR #9 was squash-merged as `d99904f`;
the Campaign 2 branch is based on that commit.

Version 0.2.0 adds Campaign 1, "reliability and trust" (see the
[changelog](../CHANGELOG.md)). An open panel follows the artifact file on disk
and shows a revision whose sources changed as a historical diagram instead of
refusing it. Freshness uses the saved file bytes, as the helper does. Refinement
prompts carry artifact text only inside a JSON data block and name one of five
intents; Explain never publishes. The helper no longer fingerprints MLView's own
artifacts, drafts or installed skill. A shared corpus in
`contracts/conformance` checks the schema, helper and extension together. With
the fixes from the campaign's first and second reviews, on commit `106f172`, the
full local gate passed on one macOS machine ([details](VALIDATION.md)).
CI then passed all eight jobs (Python 3.10–3.13; Node 20.18.1 and 22 on Linux, macOS and Windows) at `deab60a`, in the [push](https://github.com/realmyang/MLView/actions/runs/36093596906) and [PR](https://github.com/realmyang/MLView/actions/runs/36093599706) runs, after two test-only fixes for older Python and Windows. A partial
[live check](demo-logs/2026-09-25-campaign1-live-check.md) in a macOS VS Code
Extension Development Host confirmed High Contrast Light, a BOM source open in
an editor, unsaved-edit and changed-on-disk banners, and the Challenge prompt.
HC Dark, the other intents, a symlinked root, Restricted Mode and Windows were
not exercised live, and none of this is semantic validation.

The [trust and usability campaign](TRUST_USABILITY_CAMPAIGN.md) implements the
first campaign from the [improvement research](IMPROVEMENT_RESEARCH_2026-09-18.md):
authored wording, evidence inspection, textual relationships, coalesced
validation, source-reading aids, incremental draft edits, bundle diagnostics
and reproducible performance/candidate checks. See its measured results and
remaining gates. No human semantic review or held-out pilot pass is implied.

The follow-up completed macOS VS Code viewer/keyboard checks and focused browser
and native performance profiling through 2,000 nodes. Source links now retain
the visible diagram, side tabs support keyboard navigation, and both validators
enforce the same evidence requirements. The [profile](PERFORMANCE.md) identified
repeated routing obstacle checks as the bottleneck; Campaign 1 now runs the
cheap geometric test first, with identical routes, and the jsdom benchmark's
2,000-node update fell from about 10 s to about 1.5 s on the same machine. These synthetic viewer exercises do not run or
score a native assistant. The [human review guide](../evals/workflow/reference-candidates/REVIEW_GUIDE.md)
explains the pending owner/reviewer decisions.
