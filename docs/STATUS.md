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
counter-evidence, severity filters and focus mode, refinement prompts and
revision watching.
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
the Outline's rows count each finding once, so they agree with the header,
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

Unreleased viewer M3, step 11 (the review walk): `r`, the header's **Review**
button or **Review the claims** in the **⋯** menu goes through the displayed
revision claim by claim, in the diagram's order (each step, its outgoing
connections, then the findings whose first cited step it is; findings that
cite no step come last). Every claim is visited once: 79 in vit-cc, 176 in
yolov5-cc2. It starts on **Not observed** (7 and 16, the header's counts);
**Findings**, **All claims** and, when cited files changed, **Changed files**
are the other filters. `j` / `k` or ↓ / ↑ step, `[` / `]` change quote, Enter opens
again, `u` / Shift+U go through the claims not observed, `n` / `p` through the
findings, and Escape or `r` ends it. About 150 ms after each step the cited
lines open beside the diagram, highlighted, with the keyboard kept on the
diagram; a quote VS Code did not open says why in the walk bar and the
Selection tab, with no notification. The bar sits under the diagram, above the
bottom panel's tabs, and shrinks to "3/16", Previous and Next, the filters and
Exit below 620 px.
The place is remembered per revision in the panel's view state; nothing marks
a claim as checked. The changed-files notice offers **Review affected
claims**. The host gained a `walk` `clear` message and clears the highlight
on a blocked walk open. Checked by local jsdom and mock `vscode` tests (with
synthetic documents of the vit-cc and yolov5-cc2 shape, the real host with
the built viewer, and mutation checks) and briefly in an isolated VS Code
1.139 Extension Development Host on macOS (vit-cc beside its notebook at about
393, 543 and 902 px); not with a screen reader, on Windows or Linux, or as a
usability check ([changelog](../CHANGELOG.md)).

Unreleased viewer M3, step 12 (the host side of the review walk) and Escape:
an `openLocation` request may carry a sequence number, a request id, a walk
flag and `highlight: false`. The host drops an open a later one has
overtaken, answers a request id with done, blocked (with the reason, for
example "train.py changed after revision r3 was published; not opened."),
cancelled or failed, and never opens a changed, missing or otherwise stale
file. A blocked walk open raises no VS Code notification; one from Enter, a
double-click or an Open link still does. A `walk` end message clears the
cited-range highlight and its overview-ruler mark, as closing the panel does.
The check behind a jump is cached per revision and freshness: 60 jumps into a
synthetic 3.8 MB notebook hashed it once instead of 60 times
([performance](PERFORMANCE.md)). An Escape the viewer used no longer also reaches VS Code (where
it hid a notification); with nothing left to close and the focus off the
diagram, Escape goes to VS Code. The M2 report of focus lost on Escape after
Enter opened a notebook was not reproduced in 14 live attempts, so this fixes
the mechanism found, not a confirmed reproduction (the same symptom in the M3
live check came from how that check drove VS Code; see below). No contract
change, no new setting and no geometry change. Checked by local jsdom and mock `vscode`
tests and in an isolated VS Code 1.139 Extension Development Host on macOS
driven over the DevTools protocol; not on Windows or Linux, with a screen
reader or as a usability check ([changelog](../CHANGELOG.md)).

Unreleased viewer M3, step 13 (the phase overview and the phase index):
Shift+0, or **Phase overview** in the ⋯ menu, shows every phase as a block
over the diagram: its number, name, step count and the findings that touch it,
then its step titles in the Outline's order with ◌ for inferred, ? for
unresolved and the F labels of the findings on each step. Arrows between
neighbouring blocks say how many connections go to the next phase, and
brackets on the right count the ones that skip ahead or go back. The header
reads, for vit-cc, "6 phases · 31 steps · 41 connections: 19 inside a phase, 8
to the next phase, 14 skip ahead or go back." A block that does not fit ends
with "… N more steps", and the listed titles and those counts add up to the
document's steps. Arrow keys move between blocks; Enter or a click goes to
that phase at reading size (about 240 ms, instant under reduced motion) and
Escape returns to the diagram as it was. The labelled phase index replaces the
overview map (the minimap): a list in the lower right corner with each phase's
number, name, findings by severity and step count, the phases in view marked,
and a row going to its phase. Below 1000 px wide it is one line such as "4/6
Objective, optimizer & scheduler" that opens the list. It sits inside the
diagram, above the bottom panel, and the card you are on is panned out from
under it. The ⋯ menu's **Phase index** shows or hides it. Shift+0 no longer
folds every group; **Fit the whole diagram** stays in the ⋯ menu. No contract
change, no new setting and no geometry change. Checked by local jsdom tests
(with synthetic documents of the vit-cc and yolov5-cc2 shape) and headless-Chrome
screenshots of a simulated host at 1440x900, 900x800 and 541x798; not in live
VS Code, with a screen reader or as a usability check
([changelog](../CHANGELOG.md)).

Unreleased viewer M3, step 14 (Reveal in Diagram, from the code back to the
diagram): right-click a line in the editor and choose **Reveal in Diagram**
(or run **MLView: Reveal in Diagram** from the Command Palette) to show the
claim that cites it. This is the extension's second command and has no
default keybinding. The item appears on a file an open diagram cites that has
not changed since the revision was published; the `when` clause is
`resourcePath in mlview.citedFiles`, a list the extension keeps of the open
diagrams' cited, unchanged files (see the review fixes below). One claim on the
cursor's line or the selection is shown at once; several are listed (steps,
then connections, then findings, with the F label, severity, phase and where
each is cited); a line no claim cites offers the nearest claims in the file.
The diagram selects the claim, unfolds its group, brings it into view clear
of the phase index, shows it in the Selection tab (opening a hidden side
panel or bottom panel), and takes the keyboard: the one place the viewer
moves the focus by itself. A diagram hidden behind the code comes to the
front and shows the claim once its page has reloaded. With several diagrams
open, the one citing the file is used, or a list asks which. It works in
notebook cell editors. Each panel keeps an index of its validated revision's
evidence, rebuilt on a new revision and dropped with the panel; it reads no
code. The webview gained a `reveal {kind, id}` host frame for steps,
connections and findings. No hover, CodeLens, diagnostics, contract change,
new setting or geometry change. Checked by local mock `vscode` and jsdom tests
(mutation-checked, including 1440x900, 900x800 and 541x798 on the vit-cc and
yolov5-cc2 shapes) and in an isolated VS Code 1.139 Extension Development
Host on macOS driven over the DevTools protocol (vit-cc, with the diagram at
541 and 866 px, a notebook cell, a hidden panel, an unsaved edit); a changed
file was checked by unit tests only. Not with a screen reader, on Windows or
Linux, or as a usability check ([changelog](../CHANGELOG.md)).

Unreleased viewer M3, review fixes: independent reviewers found five
behaviour problems, three record problems and eight accessibility or wording
problems, all fixed. **Reveal in Diagram** was missing from the editor's
context menu on the first right-click after Enter in the diagram, because its
context key was worked out from the active editor and was still off when the
menu was read (measured live); the `when` clause now reads a list of the open
diagrams' cited, unchanged files, and unsaved edits that moved the quotes are
explained by the command instead of hiding the item. **Review affected claims**
(and `u` after a walk on another filter) starts at the first claim instead of
after the old place. When a fixed file takes the walk's claim out of
**Changed files**, the walk shows and announces the next one (not opened by
itself) instead of naming a claim that was not on screen. A quote whose file
is stale never reads "Enter shows". Escape with a legend open over the phase
overview closes the legend first. **Review** and the **⋯** menu's item put
the keyboard on the diagram, so `j` steps at once. The walk bar has Previous
and Next buttons at every width and says when Alt+Enter moved the focus to the
editor; a late answer for a claim the walk has left is ignored; the narrow
bar's full place is screen-reader text; the filter reads **All claims**; a
blocked open is announced without "not opened" twice. The phase overview
keeps a short key below 620 px and says what a bracket's number counts; its
screen-reader text says each F label once; the phase index grows to 360 px to
show longer names, and its rows no longer repeat their name as a tooltip; the
header's Review toggle keeps one name. Checked by local jsdom and mock `vscode`
tests (each new test fails on the code before the fix) and, for the context
menu, the Previous and Next buttons, the menu's Review and the Alt+Enter
wording, in an isolated VS Code 1.139 Extension Development Host on macOS
driven over the DevTools protocol (vit-cc, the diagram at about 541 and
786 px); a changed file and the phase overview changes were not tried live.
Not with a screen reader, on Windows or Linux, or as a usability check
([changelog](../CHANGELOG.md)).

Unreleased viewer M3, live-check fixes in the viewer: a live check of the
milestone in an isolated VS Code 1.139 Extension Development Host (vit-cc)
found five viewer problems, now fixed. The Selection tab starts each new
claim at its top (it kept the scroll of the claim before, so beside the code
neither the title nor the walk's quote showed), and the review walk then
brings the quote's file line and what the editor shows into view, keeping the
title when both fit. After a changed file is restored, the walk no longer says
its quote was not opened. A keyboard move or a walk step hides the hover card
until the pointer moves, so a card passing under a resting pointer no longer
covers the diagram. The phase overview's header, with **Back**, the counts
and the key, stays at the top while the overview scrolls. From a connection
the arrow keys select its end that lies that way (they went to the diagram's
first card); from a finding they move as from its first cited step. The
narrow walk bar is two rows at 320 px instead of four. No contract change, no
new setting or keybinding and no geometry change. Checked by local jsdom tests
(each fails on the code before the fixes) and headless-Chrome runs of a
simulated host; not yet in VS Code after the fixes, with a screen reader, on
Windows or Linux, or as a usability check ([changelog](../CHANGELOG.md)).

Unreleased viewer M3, the live check's notebook focus loss and the walk's
selection: in the live check, the first key after Enter or a walk step opened
a notebook that was not open took the keyboard from the diagram to the
workbench (the symptom the M2 report describes). It was seen only in a window
that had never been active since it started (launched while the screen was
locked, as in that check, which ran with the display asleep) with keys sent
over the DevTools protocol: there it happened for 4 of 5 Escapes and stopped a
walk over all 79 claims at claim 50; in a window started while VS Code was the
active application it did not happen in 19 Escapes, 2 more with another
application in front, or a walk over all 79 claims. A Chromium trace shows
the notebook's output webview process moving the focus to the workbench frame
right after DevTools gives the page focus for a key; no MLView call takes
part, so MLView is unchanged for it and adds no focus recovery. Not checked by
a person at the machine, nor after switching to another application and back.
The walk still opens sources in a preview tab. One host fix: when the walk
ends, moves to a claim it opens nothing for, or does not open a quote, the
cited lines it selected are no longer left selected, if the editor still shows
them and you did not change the selection. No contract change, no new setting
or keybinding and no geometry change. Checked by mock `vscode` tests
(mutation-checked) and in an isolated VS Code 1.139 Extension Development Host
on macOS driven over the DevTools protocol, with every webview frame emulating
a focused page for the focus checks; not with a screen reader, on Windows or
Linux, or as a usability check ([changelog](../CHANGELOG.md)).

Unreleased viewer M2, live-check fixes: a live check of the branch found
seven problems, now fixed. When the panel resizes or the rail changes shape
and a selection that was in view no longer is, the diagram pans the least
distance that shows it again, at the same zoom; a selection the reader moved
away stays put. A jump opens the source in an existing editor group other than
the panel's own (the group showing the file, the previous jump's, the last one
used, then the nearest), so beside a notebook it no longer opens a third group;
only a diagram alone in the window opens one beside it. Phase tones 2 and 3
moved off the warning amber and the error red (no tone within 30 degrees of
hue of either). The ⋯ menu's **Overview map** is disabled and unchecked, with
the reason, whenever the map is not drawn. The viewer no longer answers
Ctrl/Cmd+B, Ctrl/Cmd+K or Ctrl+1 to Ctrl+4, which VS Code also acted on: `b`
shows or hides the panel, `t` goes to the panel's tabs, Ctrl+F (Cmd+F on
macOS) and `/` focus search, and keys are labelled for the platform. A
finding's id on a step's pane is a line under its title. A hidden panel shown
again keeps its selection and an open bottom sheet (`sheetOpen` in the saved
view). No contract change, no new setting and no geometry change. Checked by
local jsdom and mock `vscode` tests, each written to fail before its fix, and
in an isolated VS Code 1.139 Extension Development Host on macOS driven over
the DevTools protocol; not on Windows or Linux, with a screen reader or as a
usability check ([changelog](../CHANGELOG.md)).

Unreleased viewer M2, review fixes: Tab reaches the header at every width
(its tab stop skips controls the stylesheet hides) and the header row always
fits with **Refine…** in view, folding the revision chip, then "not observed"
(into the ⋯ menu), then the title as it measures an overflow. Header counts
name their unit on screen ("findings", "7 claims not observed"); an off
severity toggle is struck through rather than faded; **Refine…** draws the
button foreground and keeps its High Contrast border; beside the code a
stale-files warning in the status bar stays whole. A canvas click, a search hit
for a step, a Selection-pane link or a host reveal shows the claim in Selection
again (as in M1); only a selection from the Findings list or the Outline on
screen keeps that list. A group's pane lists its findings, steps and the
connections across its edge; observed findings carry no basis mark; a lane
says "· 5 findings touch this phase" after its numbers; cards with a detail
show two lines of it instead of the file:line row; a hover dims nothing; lane
headings are numbered, at the title size, on a plate. Announcements say steps
and connections and lead with the F label. A first view between 62% and about
85% zoom still opens whole at small text (deferred). Dead scope, phase-chip
and export-region code is removed and the benchmark tools run again. No
contract change, no new setting and no geometry change. Checked by local jsdom
tests and headless-Chrome probes of a simulated host only, not in live VS
Code, with a screen reader or as a usability check
([changelog](../CHANGELOG.md)).

Unreleased viewer M2, steps 5 and 9 (About, the Selection pane and the bottom
sheet): the rail's tabs are About · Findings (n) · Selection · Outline. A new
revision opens on About, which holds only authored text: the question, the
model's coverage summary (split at its own run-in heads when it has three),
coverage with the limitations listed once, scope, run configuration, the
cited files with their freshness, and provenance with "Model-authored; MLView
checks citations, not the interpretation." Afterwards the reader's tab is
kept per revision. Selection (the old Inspector) reads claim first: phase,
kind and parent group, title, a basis note only for an exception, the full
detail, the findings on the step with What to change, numbered quotes with
line numbers, a freshness word and Open, "Comes from" and "Feeds" sentences,
Challenge and Refine…, and one link to the limitations. Selecting a finding
frames every step it cites. Where a docked rail would leave the canvas under
900 px (below 1260 px with the default rail), the rail is a bottom sheet under
the canvas: a 32 px tab strip, about half the height when a selection opens
it, with the selected card kept in view above it; a drag handle, a chevron and
Escape collapse it, and it has two columns from 620 px. The shortcut sheet and
the Refine… popover keep Tab inside and give the focus back; with VS Code's
screen-reader class a selection is announced by its claim and nothing moves.
No contract change, no new setting and no geometry change. Checked by local
jsdom tests and headless-Chrome screenshots of a simulated host at 1440, 900
and 541 px only, not in live VS Code, with a screen reader or as a usability
check ([changelog](../CHANGELOG.md)).

Unreleased viewer M2, step 10 (one header row): the brand row, the toolbar,
the phase chip row and the authored header are now one row of about 36 px:
the title (cut with an ellipsis, whole on hover), a host · revision chip whose
dot turns amber only when a cited file is stale, search, the severity toggles
(each counted once; a severity with no findings has none), **N not observed**,
a ⋯ menu (legend, flow, overview map, side rail, Fit the whole diagram, zoom
to the selection, Export SVG/PNG, Copy SVG, shortcuts) and **Refine…**, which
names its target by label. Below 620 px wide only the title, the severity
toggles, **N not observed**, ⋯ and **Refine…** stay in the row. The chip and
the status bar's coverage item open the request and coverage (the About tab
since steps 5 and 9).
The scope picker and the phase chip row are gone, with their keys (`s`,
Shift+S, `[`, `]`); a view saved by an older viewer still loads, its scope and
phase filter ignored. Copy PNG, Print and the export region choice went with
the old export menu. The status bar (about 22 px) reads "N steps · M
connections", "Coverage: scoped · K limitations", the source freshness (muted
unless a cited file changed or went missing) and the zoom. Ctrl/Cmd+F focuses
search. In the screenshot harness the chrome around the canvas went from 203,
201-244 and 299-348 px to 58 px at 1440, 900 and 541 px wide. No contract
change, no new setting and no geometry change. Checked by local jsdom tests
and headless-Chrome screenshots of a simulated host only, not in live VS Code
([changelog](../CHANGELOG.md)).

Unreleased viewer M2, steps 7 and 8 (a calm canvas): cards lost the
`basis=observed` chip row and connection labels the " · observed" suffix (the
one deliberate geometry change of M2; cards are 26 px shorter). Only inferred
and unresolved claims are marked, with a dashed or dotted border or line and
a small tag that keeps its size as you zoom; line style now means certainty,
not connection kind, and the kind is written in the hover card and the
Inspector. Each phase is coloured by its place in the document. Connections
and card borders reach at least 3:1 against the canvas in Dark Modern, Light
Modern and Dark High Contrast (computed from theme colours, not measured on
screen). A header toggle fades the observed claims. Finding badges read
`F1`, `F2`… in document order, with the real id kept in the hover card, the
Inspector and Refine prompts. Every count names its unit, and phase counts say
"findings touch this phase" (a finding in two phases counts in both). Flow
animations stop after two passes (Shift+A replays them) and follow VS Code's
Reduce Motion setting. No contract change and no new setting. Checked by local
jsdom tests and headless-Chrome screenshots of a simulated host only, not in
live VS Code, with a screen reader or as a usability check
([changelog](../CHANGELOG.md)).

Unreleased viewer M2, step 6 (a readable first view): the diagram opens whole
when it fits at 62% or more, otherwise on its first phase at 90% (or the whole
first phase when that fits at 75% or more); a view saved for the same revision
still wins. On the public shakedown artifacts the first paint went from
17-59% (2.1-7.1 px titles) to 84-90% (11.0-11.7 px titles) at 541, 900 and
1440 px, measured with the screenshot harness. Key `0` returns to that view;
the Fit button is now **Fit the whole diagram** (in the header's ⋯ menu since
step 10). Zoomed out below
62%, cards show only their title at about 11 px, capped to fit the card,
which keeps titles at 10 px or more down to about 35% without laying the
diagram out again. No contract change, no new setting and no geometry change.
Local jsdom tests and headless-Chrome screenshots only, not live VS Code.

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
