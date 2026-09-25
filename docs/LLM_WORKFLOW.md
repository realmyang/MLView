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
it has no dependency on the MLView checkout afterward. Restart or refresh the
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
It reports remediation without overwriting local edits. It cannot certify native skill discovery or
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
The helper does not decide the steps, findings, or diagram meaning. Invalid
drafts receive actionable errors with a bounded repair loop.

Open the resulting `*.mlview.json` file and run **MLView: Open Generated
Diagram**. With several artifacts in the workspace, select the intended one.
The owning workspace folder supplies the citation root. The artifact cannot
select another folder or supply absolute source paths.

Select a node or edge to inspect its basis and evidence. Supporting and
counter-evidence remain separate. Notebook anchors name a zero-based cell and
one-based lines inside that cell. Reading a notebook does not establish its
execution order. Unresolved steps and conceptual groups can lack navigation
targets; MLView does not invent locations for them.

The Inspector displays every authored source quote and keeps finding support
and counter-evidence distinct. Previous/Next evidence opens adjacent anchors;
source-less items explain why navigation is unavailable. **Challenge this claim**
opens the refinement composer for the current item; you still decide whether to
send the copied request.

Use **Outline → Text relationships** to enumerate connections without relying
on the canvas. All shows relationships in the current scope; Incoming and
Outgoing use the selected node, and Unresolved shows relationships involving
an unresolved edge or endpoint. These are direct connections, not a claim of
complete transitive change impact. Clear the scope to return to the whole
authored workflow.

Refine in the same assistant, for example:

> Refine workflow.mlview.json: expand the two loss terms and show why only
> the student is updated. Preserve stable IDs and supersede the current revision.

Each update uses a new revision ID and names the revision currently in the
artifact file as its parent.

For a focused change, select a node, edge, or finding, click **Refine**, choose
an intent, then click **Copy prompt**. The composer shows the selected item
captured when it opens. Reopen it after changing the selection to target a
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
as a historical diagram. The banner names the changed files; jumps into those
files are blocked, and evidence in unchanged files still opens. Ask the
assistant to publish a fresh revision to update the diagram.

Unsaved editor changes do not make a diagram stale, because freshness uses the
saved files. The banner lists files with unsaved changes, and a jump is
blocked only when the unsaved text no longer contains the cited lines. Save
source changes before asking for a new analysis: the assistant and its helper
read the files on disk.

During edit bursts, the viewer marks freshness as pending immediately and
coalesces validation work. Navigation rechecks the displayed revision before
jumping, and an obsolete validation result cannot replace a newer revision or
clear its warning.

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
