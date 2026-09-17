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
open the extension directory in another VS Code window and use its **Run MLView
Extension** launch configuration. The artifact viewer needs no Python analyzer
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
the host version; [validation status](LLM_IMPLEMENTATION.md) distinguishes
documented compatibility from live verification.

For Claude Code, use the [plugin instructions](../claude-plugin/README.md).
Alternatively install just the same skill into the project's Claude directory:

```sh
python3 tools/install_skill.py /path/to/target-project --destination .claude/skills/mlview
```

Choose the installation for your host; do not install both same-name copies in
a workspace shared with Copilot, which can discover both layouts. The portable
workspace installation needs no MCP server. The plugin's legacy MCP services
are separate from LLM artifact authoring.

Check an installed workspace without changing it:

```sh
python3 tools/install_skill.py /path/to/target-project --doctor
```

This checks Python 3.10+, the documented skill directories, missing bundled
files and duplicate installations. It cannot certify native skill discovery or
the extension UI; complete those checks in the chosen assistant. CI is configured
to package and check both standalone skill ZIPs alongside the VSIX and legacy
wheel.

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

Refine in the same assistant, for example:

> Refine workflow.mlview.json: expand the two loss terms and show why only
> the student is updated. Preserve stable IDs and supersede the current revision.

Each update uses a new revision ID and names the previous ID as its parent.

For a focused change, select a node, edge, or finding, click **Refine**, choose
Explain, Expand, Challenge, Trace, or a custom request, then click **Copy prompt**.
The composer shows the selected item captured when it opens. Reopen it after
changing the selection to target a different item. With no selection it targets
the whole diagram. Paste the prompt into the same assistant conversation.
The prompt includes the selected stable ID, evidence IDs, entrypoints,
configuration and parent revision. The host rejects stale or missing selections.
Entrypoints and configuration are also visible above the diagram.

The panel watches the selected artifact. Invalid or superseded updates preserve
the last valid diagram. Model work occurs only when you ask the assistant;
filtering, source navigation, and reopening the artifact are local operations.

## Freshness and recovery

The helper fingerprints cited files and declared inspected files, including
configuration. The viewer checks those hashes and exact excerpts. Save source
changes before asking for a new analysis. Stale evidence blocks misleading
source jumps; the existing diagram may still explain the older revision.
Freshness covers recorded dependencies, not every file the model could have
read through opaque host tools.

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
- Edit a cited source or config; verify stale display and blocked stale jumps.
- Try malformed JSON and an obsolete revision; retain the last valid diagram.
- Verify that ordinary saves and view filters do not run a model or static analysis.

Use [the evaluation protocol](../evals/workflow/README.md) for semantic review.
Unit tests do not satisfy this live-host checklist. Windows and remote workspace
support need their own validation before a compatibility claim.
