# MLView for Claude Code

This plugin gives Claude Code one native `mlview` skill. The active Claude
model inspects ML source, configuration, notebooks, launch scripts, tests, and
documentation; authors a source-linked `WorkflowDocument`; and validates and
publishes it with the bundled local helper. Open the result with **MLView: Open
Generated Diagram** in VS Code.

The plugin does not bundle the retired static analyzer, an MCP server, hooks,
or separate slash-command wrappers. It needs no model API key or Python
package installation. The helper requires Python 3.10 or newer and never
imports or executes the project being analyzed.

## Install

Validate the plugin when the Claude CLI is available:

```bash
claude plugin validate ./claude-plugin --strict
```

For a session from a checkout:

```bash
claude --plugin-dir /absolute/path/to/MLView/claude-plugin
```

Through the repository's local marketplace:

```text
/plugin marketplace add ./
/plugin install mlview@mlview-local
```

Directly from GitHub:

```text
/plugin marketplace add realmyang/MLView
/plugin install mlview-github@mlview-local
```

The repository's marketplace is named `mlview-local` whether it is added from
a checkout or from GitHub; add it from only one of them. The `mlview-github`
entry pins no ref: it installs `claude-plugin/` from the repository's default
branch. That branch gives this native skill only after
[pull request #9](https://github.com/realmyang/MLView/pull/9) merges; until
then it still delivers the retired static-analyzer plugin, so use one of the
checkout-based installs above.

Then ask Claude to visualize, map, review, or explain an ML workflow. Claude
loads the `mlview` skill, writes `workflow.mlview.json` in the workspace, and
reports the selected scenario, coverage, uncertainty, and publication result.

## Distribution contents

```text
claude-plugin/
  .claude-plugin/plugin.json
  LICENSE
  README.md
  skills/mlview/
    LICENSE
    SKILL.md
    references/WORKFLOW_CONTRACT.md
    references/coverage-obligations.md
    references/notebooks-and-configuration.md
    references/training-state.md
    references/workflow-example.json
    scripts/artifact.py
  tests/test_distribution.py
```

`skills/mlview/` is generated from the canonical repository skill at
`skills/mlview/`. Run `python tools/sync-skill.py` after changing the canonical
skill and `python tools/sync-skill.py --check` to detect drift. The plugin and
skill licenses are byte-identical copies of the repository MIT license.
