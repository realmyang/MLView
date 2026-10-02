# Using the MLView skill

MLView asks the LLM in your current VS Code assistant to interpret source,
configuration, notebooks, and documentation. It publishes a source-linked
WorkflowDocument that the MLView extension opens. Native model usage and
permission controls apply. There is no separate MLView API key.

## Install

A standalone skill ZIP can be extracted directly into the target workspace;
it contains the `.agents/skills/mlview/` layout (shared Codex/Copilot), or the
`.claude/skills/mlview/` layout (Claude). Build these distributions with
`python3 tools/package_skill.py` and add `--host claude-code` for the latter.
Together with the VSIX, these local build artifacts need no development
checkout in the target project. They have not been published to a marketplace.

Build the viewer and VSIX using the [root instructions](../README.md). Install
the resulting VSIX through **Extensions: Install from VSIX**. For development,
open the `vscode-extension/` directory in another VS Code window and start its
**Run MLView Extension** launch configuration (or **Run MLView Extension (no
build)** after a build). Both open the repository root in the Extension
Development Host: run **MLView: Open Generated Diagram** there and select
`samples/configured_training.mlview.json`. The artifact viewer needs no Python
installation. Publishing through the skill's helper requires Python 3.10+.

Install the portable skill into the project you want to understand:

```sh
python3 tools/install_skill.py /path/to/target-project
```

The copied directory contains the skill, its contract/example, and its helper;
it has no dependency on the MLView checkout afterward. The installer also
writes `.mlview-install.json` there, recording the SHA-256 of every file it
installed; like other dotfiles, this manifest is not part of the skill's
identity. Rerunning the installer upgrades that installation: unmodified files
are replaced, and files that a newer skill no longer ships are removed when
unmodified. A file you edited is refused with `destination has local edits:
<files>. Back them up and rerun with --force to replace them.` After backing
it up, add `--force` to replace it. Files the installer never wrote are never
replaced or deleted. An installation without a manifest, such as one made
before 0.3.0 or extracted from a skill ZIP, needs `--force` for every file that
differs from the new skill. Restart or refresh the
assistant's skill discovery if needed. Codex and current VS Code Copilot can
discover the `.agents/skills/mlview/` layout. Invoke `$mlview` in Codex or choose
`mlview` in Copilot's skill picker. Actual discovery and invocation depend on
the host version. [Current status](STATUS.md) and [validation](VALIDATION.md)
distinguish documented compatibility from live verification; the dated
[host logs](demo-logs/) record earlier live exercises.

For Claude Code, use the [plugin instructions](../claude-plugin/README.md).
Alternatively install just the same skill into the project's Claude directory:

```sh
python3 tools/install_skill.py /path/to/target-project --destination .claude/skills/mlview
```

Choose the installation for your host; do not install both same-name copies in
a workspace shared with Copilot, which can discover both layouts. The portable
workspace installation and Claude plugin both contain the same native skill;
neither starts an MCP server.

Check an installed workspace without changing it:

```sh
python3 tools/install_skill.py /path/to/target-project --doctor
```

This checks Python 3.10+, the documented skill directories, missing, edited and
unexpected bundled files, exact bundle hashes and duplicate installations.
It reports remediation without overwriting local edits. A skill location that
is a symbolic link is reported as present but linked, with advice to remove the
link (not its target) and rerun the installer, because MLView installs only
real directories. It cannot certify native skill discovery or
the extension UI; complete those checks in the chosen assistant. CI is configured
to package and check both standalone skill ZIPs alongside the VSIX.

## Analyze and refine

An effective first request names an entrypoint and config when known:

> Use MLView to explain training with train.py and configs/distill.json.
> Show where data enters, which model is updated, how the losses combine,
> how validation works, and what source inspection cannot establish.

The assistant inspects the source with its native tools, chooses meaningful
steps and connections, checks alternative interpretations, and writes a draft.
It uses the bundled helper to validate exact citations and publish a revision.
The helper does not decide the steps, findings, or diagram meaning. Its
read-only `excerpt` command prints the exact evidence record for a cited
range, and validation adds non-blocking hygiene warnings (such as uncited
evidence or unconnected nodes) for the assistant's own critique. Invalid
drafts receive actionable errors with a bounded repair loop.

Open the resulting `*.mlview.json` file and run **MLView: Open Generated
Diagram**. With several artifacts in the workspace, select the intended one.
The owning workspace folder supplies the citation root. The artifact cannot
select another folder or supply absolute source paths.

Click a node, edge or finding to select it and inspect its basis and evidence;
a click never opens source. Enter, a double-click (on a step, connection,
finding or Outline step; a double-click on a group collapses it) or a quote's
**Open** link in the Selection tab opens the cited range beside the diagram, selects and highlights the whole
range, and keeps focus in the diagram so the keyboard keeps working. The
source opens in an editor group you already have, never the diagram's own:
the group already showing that file, else the one the last jump used, else
the one you last worked in, else the group nearest the diagram; only a diagram
alone in the window opens a new group beside it. Text files and notebooks go
to the same group. Alt+Enter
(or Alt+click on an Open link) also moves focus to the editor. A notebook
citation selects its cell; the cell's lines are highlighted when VS Code has
that cell's editor ready. Supporting and
counter-evidence remain separate. Notebook anchors name a zero-based cell and
one-based lines inside that cell. The viewer prints the cell number as
recorded: `cell 7, line 3` is the cell the helper's `--cell 7` names (the
eighth, counting markdown cells), so it matches the model's own labels.
Reading a notebook does not establish its
execution order. Unresolved steps and conceptual groups can lack navigation
targets; MLView does not invent locations for them.

The rail's tabs are **About**, **Findings (n)**, **Selection** and
**Outline**. A new revision opens on About; after that the viewer keeps the
tab you chose for that revision. About holds only authored text: the question
(**Asked**), the coverage summary (**What the model traced**, split into
paragraphs at its own "Data:", "Model:"… heads when it has at least three),
the coverage status in plain words with the limitations listed once, the
scope and entrypoints, the run configuration (with `key=value` tokens in
monospace), every cited file with its freshness, and the provenance, with
"Model-authored; MLView checks citations, not the interpretation." The
revision chip, **Coverage** in the status bar and the **⋯** menu open it.

Selecting an item on the diagram, from a search result or from a link shows
it in the Selection tab; a row chosen in the Findings list or the Outline (or
`n`/`p` for findings) keeps that list in place. For a step it
shows, in order: the phase number and name, kind and parent group; the title;
a one-line basis note only for an inferred or unresolved claim; the full
authored detail; the findings on the step with their suggestion under **What
to change**; every authored quote, numbered, with its line numbers, a
freshness word and **Open**; "Comes from …" and "Feeds …" sentences; then
**Challenge this claim** and **Refine…**, and one line saying how many
document-wide limitations apply, linking to them in About. A connection shows
its kind in words, label, ends, basis, findings and quotes; a finding shows
its severity, F-number and real id, title, description, **What to change**,
the steps it cites (selecting a finding frames all of them, with the ends of
its connections when they fit) and its supporting and counter-evidence. A
group shows the findings inside it, its steps and the connections that cross
its edge. A caption over the quotes says that a
matching quote shows the lines are unchanged since publishing, not that they
support the claim. Previous/Next evidence opens adjacent anchors; source-less
items explain why navigation is unavailable. **Challenge this claim** opens
the refinement composer for the current item; you still decide whether to
send the copied request.

When a docked rail would leave the diagram under 900 px wide (below about
1260 px), the rail is a bottom sheet under the diagram instead: a 32 px tab
strip until a selection opens it to about half the height, with the selected
card kept in view above it. Drag its handle to resize it; the chevron or
Escape collapses it, and Escape gives the focus back to the diagram. From
620 px wide the Selection tab has two columns (the claim on the left, the
quotes and actions on the right). On the diagram, `t` moves the focus to the
panel's current tab (opening the panel), and the tab strip's arrow keys choose
About, Findings, Selection or Outline; `b` shows or hides the side panel, or
opens or collapses the bottom one. When the diagram resizes or the panel
changes shape and the selected card was in view but no longer is, the diagram
pans just far enough to show it again, without zooming; a card you had moved
out of view stays where it is. A panel hidden behind another tab and shown
again keeps its tab, its selection and an open bottom panel. With VS Code's
screen-reader optimisation on, a selection is announced by its claim and
nothing animates.

The review walk goes through the displayed revision claim by claim. Press `r`
on the diagram, **Review** in the header or **Review the claims** in the **⋯**
menu. It follows the diagram's order: phase by phase, each step, then its
outgoing connections, then the findings whose first cited step it is;
findings that cite no step (only connections, or the workflow as a whole) come
last, in document order. It starts on **Not observed**, the claims marked
inferred or unresolved, with the same count as the header's **N not
observed**; **Findings**, **All** and, while VS Code reports changed or
missing cited files, **Changed files** are the other filters, each with its
count. `j` / `k` or ↓ / ↑ go to the next or previous claim, `[` / `]` to the
claim's other quotes, Enter opens the current quote again (Alt+Enter moves the
focus to the editor), `n` / `p` go to the next or previous finding, `u` /
Shift+U to the next or previous claim not observed (`u` also starts the walk
there), and Escape or `r` ends the walk. ← and → still move to the nearest
card. Each step selects the claim, brings it into view and shows it in the
Selection tab; about 150 ms after you stop, its cited lines open in the editor
beside the diagram with the range highlighted, and the keyboard stays on the
diagram. A claim with no quotes opens nothing and clears the previous
highlight. A quote whose file changed, went missing or has unsaved edits is
not opened: the walk bar and the quote in the Selection tab say why, and no
notification appears. A screen reader hears, for example, "Claim 3 of 16, not
observed: Step Load batches, inferred." The walk bar sits under the diagram,
above the bottom panel's tabs (with the side panel, along the bottom of the
diagram), and shows the place and filter, the filters, the keys, **Exit** and
what the editor beside shows; below 620 px wide it is "3/16", the filters and
**Exit**. The walk remembers its place for each revision in the panel's view
state, so `r` resumes there; a new revision starts fresh. It marks nothing as
checked and writes nothing to any file. When cited files change, the notice
offers **Review affected claims**, which walks the claims citing them.

The phase overview shows the whole workflow at once. Press Shift+0 on the
diagram, or choose **Phase overview** in the **⋯** menu. Each phase is a block
with its number, name, step count (and how many steps are inferred or
unresolved) and the findings that touch it. Under that come its step titles in
the Outline's order, a group before its steps, with ◌ for inferred, ? for
unresolved and the F labels of the findings on each step. An arrow between
two neighbouring blocks says how many connections go from one phase to the
next. A connection that skips a phase or goes back is a bracket on the right
with its count, dashed when it goes back. The header gives the counts as a
sum, for example "6 phases · 31 steps · 41 connections: 19 inside a phase, 8
to the next phase, 14 skip ahead or go back." A block with more titles than
fit ends with "… N more steps", so every step is either listed or counted.
Beside your code, a document with many phases scrolls a little rather than
dropping the titles. ↑ / ↓ (or ← / →), Home and End move between blocks.
Enter or a click goes to that phase at reading size; the move takes about a
quarter of a second, or happens at once with Reduce Motion or a screen reader.
The next arrow key then starts at the phase's first step. Escape, Shift+0 or
**Back** returns to the diagram exactly as it was, with the keyboard where it
was. Any other key the diagram uses closes the overview first. A screen
reader reads each block as a button named by its phase, counts and
connections, with its titles as the description.

The phase index sits in the lower right corner of the diagram. It lists every
phase with its number, name, findings by severity (a finding on two phases
counts in each, as on the lane headings) and step count, and it marks the
phases in view. Clicking a row goes to that phase. In a panel under 1000 px
wide, or on a diagram under 350 px tall, it is one line naming the phase most
in view, such as "4/6 Objective, optimizer & scheduler"; clicking it opens the
list above it. When wide, its chevron folds it to that line. It stays inside
the diagram, above the bottom panel, and never hides the card you are on:
arrows, search, the Outline, a finding, the review walk and VS Code's reveal
all pan the card out from under it. **Phase index** in the **⋯** menu shows or
hides it, and the panel remembers the choice.

Reveal in Diagram goes from the code back to the diagram. Right-click a line
in the editor and choose **Reveal in Diagram**, or run **MLView: Reveal in
Diagram** from the Command Palette. There is no default keybinding. The item
is offered only while an open diagram cites the file and the file still
matches it: VS Code has not reported it changed or missing since the revision
was published, and the editor's text, unsaved edits included, still has a
quote at its cited lines. The cursor's line, or the selected lines, decide
the claim. When one claim cites them it is shown at once; when several do, a
list names each one's kind, title, F label, severity, phase and cited lines,
steps first, then connections, then findings; on a line no claim cites, the
list offers the nearest claims in the file. The diagram selects the claim,
unfolds its group, brings it into view and shows it in the Selection tab
(opening a hidden side panel or a collapsed bottom panel), and the keyboard
moves to the diagram. It is the one time the viewer moves the focus by
itself, because you asked for the diagram; nothing is opened in the editor. A
diagram hidden behind the code comes to the front. With several diagrams
open, the one that cites the file is used, or a list asks which. It works in
notebook cell editors. Run where it does not apply (from a keybinding of your
own, or after the file changed), it says why, for example that the file
changed after the revision was published and the assistant should publish a
fresh one. The claims come from the displayed revision's
evidence records; MLView reads no code to find them.

On the diagram, observed claims carry no basis mark. An inferred step or
connection has a dashed border or line and an `inferred` tag; an unresolved
one has a dotted border or line and a `? unresolved` tag. Line style shows
this certainty, not the connection's kind, which the hover card and the
Selection tab name. The header's **N not observed** toggle fades the observed
claims so the others stand out. Each phase is coloured by its place in the
document, in tones that keep clear of the warning and error colours. Finding
badges read F1, F2… in document order; a new revision can renumber them, so
the Selection tab shows the real id with the number (a finding listed on a
step shows it on a line under its title), and
Refine and Challenge prompts use the real id. A lane heading carries the
phase's number and name, its step count, its findings by severity and their
total ("5 findings touch this phase"): a finding that cites two phases counts
in both. A card shows two lines of its authored detail; its file and line are
in the hover card and the Selection tab. Hovering a card rings its direct
neighbours and lights its connections without fading anything; focus mode
(select, then F) fades the rest. A hover or focus-mode flow runs twice and then stops; Shift+A plays it
again, and VS Code's Reduce Motion setting turns the animation off.

The diagram opens readable: the whole document if it fits at 62% zoom or
more, otherwise the first phase at 90% (or all of the first phase, when it
fits at 75% or more). Reopening the same revision keeps where you were. Press
`0` to return to that first view from any zoom; **Fit the whole diagram** in
the header's **⋯** menu shows everything. Shift+0 opens the phase overview;
it no longer folds every group (each group keeps its own chevron). Zoomed out below 62%, cards show only their titles, at about
11 px on screen down to about 35% zoom; the full title is in the hover card.

The header is one row: the title, the assistant and revision, search, the
severity toggles (each with its count), **N not observed**, **Review**, a
**⋯** menu and **Refine…**. In a panel under 620 px wide, such as beside your
code, search, the revision and **Review** move into the **⋯** menu; a row still too full folds **N not
observed** into it as well, so **Refine…** stays in view. The menu also holds the
phase overview, the legend, the flow animation, the phase index, the side or
bottom panel, **Fit the whole diagram**, zoom to the selection, the SVG and PNG
exports and the shortcut sheet, and always **Review the claims**. The phase
index item is disabled, with the reason, for a diagram with fewer than two
phases. Ctrl+F (Cmd+F on macOS), or `/` on the diagram, focuses
search; the viewer's other keys are single keys, so VS Code's own Ctrl and Cmd
shortcuts keep working, and the shortcut sheet prints them for your platform.
Escape closes one thing at a time in the viewer (a menu or panel, the phase
index's list, the phase overview, the review walk, the bottom sheet, focus mode, the selection, then the focus on the
diagram) without VS
Code also acting on it; after that it goes to VS Code, for example to hide a
notification. Each search result shows its
title and, under it, where it is cited. The status bar counts steps and
connections, shows the coverage status with its limitations, and says
whether the cited files are unchanged (muted text) or changed or missing (a
warning). The whole document is always drawn; to narrow what you look at,
collapse groups or use focus mode (select, then F).

Use **Outline → Text relationships** to enumerate connections without relying
on the canvas. All shows every relationship; Incoming and Outgoing use the
selected node, and Unresolved shows relationships involving an unresolved edge
or endpoint. These are direct connections, not a claim of complete transitive
change impact.

Refine in the same assistant, for example:

> Refine workflow.mlview.json: expand the two loss terms and show why only
> the student is updated. Preserve stable IDs and supersede the current revision.

Each update uses a new revision ID and names the revision currently in the
artifact file as its parent.

For a focused change, select a node, edge, or finding, click **Refine…**,
choose an intent, then click **Copy prompt**. The composer names the item it
captured when it opened by its label (for example "Step: Compute loss"); the
prompt carries its stable id. Reopen it after changing the selection to target a
different item. With no selection it targets the whole diagram. Paste the
prompt into the same assistant conversation; copying it never starts model
work.

| Intent | What the assistant does | New revision? |
|---|---|---|
| Explain | Explains the item or diagram in the conversation, citing its evidence | Never; if the diagram is wrong, it says so and offers a corrected revision |
| Expand | Adds the sub-steps, data and state flow the item summarizes, with evidence | Yes |
| Challenge | Re-checks the claim against the source, then keeps, qualifies or removes it | Only if something changes |
| Trace | Follows data, control and state flow into and out of the item across files | Usually; otherwise it explains why nothing more can be traced |
| Custom | Does what your typed request (1 to 500 characters) asks, answering questions in the conversation | Only if the diagram changes |

The prompt names the intent, the selected stable ID and the revision to build
on: the revision currently in the artifact file, which the helper requires and
which can differ from the displayed one (see below). Text taken from the
artifact and the workspace, such as the question, scope, configuration, labels,
evidence IDs, the viewer's rejection reasons and changed file names, appears
only inside one JSON data block that the assistant is told to treat as data,
never as instructions. Evidence quotes are not copied; the assistant re-reads
the cited files. In VS Code Restricted Mode the prompt
also states that the workspace is not trusted. The host refuses to copy a
prompt for a stale or missing selection, and while the artifact file is
missing or cannot be read, because the helper would refuse to publish over it.
Entrypoints and configuration are also visible above the diagram.

SVG and PNG exports are saved through VS Code's save dialog. The VS Code
notification confirms the saved file; the panel announces an export only after
the save completes, and reports a cancelled or failed save as such.

Model work occurs only when you ask the assistant; filtering, source
navigation, and reopening the artifact are local operations.

## Revisions in the open panel

The panel watches the selected artifact file and shows the newest valid
revision in it:

- A new valid revision replaces the displayed one, even when some of its
  sources changed after publication. It then appears as a historical diagram
  (see below): staleness never hides a newer revision.
- An invalid, malformed or unreadable file keeps the last valid diagram
  visible, and the banner names the problem, such as the fields the viewer
  rejected or the JSON parse error. When the file is repaired, or the assistant
  publishes a child revision, the panel moves on without being reopened.
- If the file goes back to a revision the panel has already seen superseded,
  for example after `git restore` or copying a backup, the panel keeps the
  newer diagram and says so. A revision whose content changed without a new
  revision ID is kept at its earlier content in the same way. Run **MLView:
  Open Generated Diagram** again to show the file as it is: re-running the
  command always shows the file's current revision.
- If the file holds a revision the panel cannot prove is older, such as an
  older root revision or a reused revision ID with different content, the
  panel shows it with a note that it does not directly follow the revision
  last read from the file. The same note appears when two revisions were
  published faster than the panel read them.
- If the artifact file is deleted, the last diagram stays visible and the
  panel starts again with the next revision that appears.

A copied Refine prompt always continues from the revision in the file. When
that differs from the displayed revision, the copy notification says so, and
the prompt asks the assistant to read the file first; for a restored older
revision it also asks the assistant to check with you before continuing.

Earlier builds behaved differently: they rejected a newer revision whose
sources had changed, treated unsaved editor changes as stale sources, kept an
obsolete diagram even after **Open Generated Diagram** was re-run, published a
new revision for every Refine intent including Explain, and announced an
export before the file was saved.

## Freshness and recovery

The helper fingerprints the raw bytes of cited files and of the project files
listed as inspected, including configuration; files over 8 MiB are listed
without a fingerprint. MLView's own files (artifacts, drafts, anything under
`.mlview/` and the installed skill) are never fingerprinted and cannot be
cited, so reinstalling the skill does not make a diagram stale. A project
directory named `.mlview/` at the workspace root is treated as MLView's own
in the same way. The viewer compares the saved files on disk with the
fingerprints and checks the exact excerpts. Freshness covers recorded
dependencies, not every file the model could have read through opaque host
tools.

When a saved source file changes after publication, the diagram stays visible
as a historical diagram. The banner names the changed or missing files, and the
diagram marks the steps, connections and findings that cite them; the status
bar counts them. Each stale quote says why its Open link is disabled; evidence
in unchanged files still opens. The marks do not say whether a claim is still
right. Ask the assistant to publish a fresh revision to update the diagram.

If most tracked files are missing from the workspace root but exist, with
their published hashes, under the artifact's folder or a folder between it and
the root, the source did not change: the workspace root is wrong. The banner
says "source.py is not in the workspace root (<root>/). It is in ./<folder>/,
unchanged (it matches its published hash)." and offers **Add folder to
workspace** and **Open folder**. The marks, the status bar, the Selection tab and
a blocked jump say the file is "in another folder" and point to that notice,
not that it changed or went missing. MLView never resolves citations against
another folder on its own; the panel checks again when the workspace folders
change. The two actions are only in the panel's notice, not in a notification.

In a single-folder window, adding the folder makes VS Code turn the window into
an untitled multi-root workspace and restart its extensions. MLView handles
every extension restart inside a window the same way, whatever caused it
(**Developer: Restart Extension Host**, an extension install or update that
restarts extensions, **Save Workspace As...**, the notice's **Add folder to
workspace** or VS Code's **Add Folder to Workspace...**): each open diagram
comes back in its tab's place and is checked against the workspace as it is
then, here against the added folder. A diagram in front of its editor group
comes back at once; one behind other tabs comes back when it is brought to the
front, after a blank half second, because until then it cannot be told from a
tab VS Code restored at startup and has not shown yet. A diagram put back this
way starts with a fresh view (the selection and zoom start over); Reload Window
keeps them.

Unsaved editor changes do not make a diagram stale, because freshness uses the
saved files. The banner lists files with unsaved changes, and a jump is
blocked only when the unsaved text no longer contains the cited lines. Save
source changes before asking for a new analysis: the assistant and its helper
read the files on disk.

During edit bursts, the viewer marks freshness as pending immediately and
coalesces validation work. Navigation checks the cited file before jumping:
when its saved bytes still match the last check the jump goes ahead, and
otherwise the displayed revision is validated again first. An obsolete
validation result cannot replace a newer revision or clear its warning.

If validation fails, read the reported field/error, repair the draft, and try
again. Do not overwrite the prior artifact with a static fallback. Cancellation,
quota errors, or missing host access leave the previously published revision
available. No verification stamp certifies semantic correctness.

For a broad request, the assistant may publish a critiqued, validated partial
overview and state the work still uninspected. It can later publish a fuller
child revision. Stop model work through the native assistant's controls; MLView
does not control that host's run or promise that a cancelled first attempt has
published anything. A copied refinement prompt remains a request until sent.

## Live validation checklist

Record host/extension/model versions, OS, repository commit, selected request,
artifact hashes, elapsed time, repair rounds, and any exposed usage. Leave
unexposed model/usage fields unknown. Complete this independently for Copilot,
Codex, and Claude Code inside VS Code:

- Discover and invoke the installed skill in the native assistant.
- Have the model read source and author a diagram without the static analyzer.
- Open the artifact, inspect node and edge evidence, and navigate to exact lines.
- Right-click a cited line and choose Reveal in Diagram; verify that the claim
  citing it is shown and that an uncited file does not offer the command.
- Exercise a notebook cell and repeated/custom phase names.
- Request a refinement; verify a new revision and stable unaffected node IDs.
- Copy a Refine prompt for each intent; verify that Explain answers without
  publishing.
- Edit a cited source or config; verify stale display and blocked stale jumps.
- Leave an unsaved edit in a cited file; verify the unsaved-changes notice and
  that only jumps whose cited lines moved are blocked.
- Try malformed JSON and an obsolete revision; retain the last valid diagram.
- Verify that ordinary saves and view filters do not run a model or static analysis.

Use [the evaluation protocol](../evals/workflow/README.md) for semantic review.
Unit tests do not satisfy this live-host checklist. Windows and remote workspace
support need their own validation before a compatibility claim.
