# MLView for Claude Code

This plugin gives Claude Code the `mlview` skill. The skill instructs Claude
Code to read an ML project (source, configuration, notebooks, launch scripts,
tests and documentation), to write a diagram of its workflow whose claims
cite source lines, and to check and publish the diagram with the skill's
helper. The diagram is a `*.mlview.json` file. With the MLView
extension installed, a click on the file in VS Code's Explorer opens it.

The plugin holds the skill and nothing else: no hooks, no commands and no
servers. It needs no model API key and no Python package. The helper needs
Python 3.10 or newer, and it does not import or run the project.

This page says what Claude Code is expected to do with a plugin. That depends
on the version of Claude Code.

## Install

From a clone of this repository, add its marketplace in Claude Code and
install the plugin:

```text
/plugin marketplace add ./
/plugin install mlview@mlview-local
```

To use the plugin for one session without installing it, start Claude Code
with the plugin's folder:

```bash
claude --plugin-dir /absolute/path/to/MLView/claude-plugin
```

Without a clone, add the marketplace from GitHub:

```text
/plugin marketplace add realmyang/MLView
/plugin install mlview-github@mlview-local
```

The marketplace is named `mlview-local` whether it is added from a clone or
from GitHub, so add it from one of them only. The `mlview-github` entry names
no branch, tag or commit. Claude Code is expected to fetch `claude-plugin/`
from the default branch of the repository for it. An install from a clone
gives the plugin of that clone.

## Use

Ask Claude Code to map, review or explain an ML workflow. Claude Code is
expected to load the `mlview` skill. The skill has it publish the diagram as
`workflow.mlview.json` in the workspace folder, and report the file's path,
the revision, the scenario that it chose, the coverage and the important
limitations.

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
```

`skills/mlview/` is generated from the canonical repository skill at
`skills/mlview/`. Run `python tools/sync-skill.py` after changing the canonical
skill and `python tools/sync-skill.py --check` to detect drift. The plugin and
skill licenses are byte-identical copies of the repository MIT license.

## Validate

With the Claude Code command-line tool installed, check the plugin's files
from the root of the repository:

```bash
claude plugin validate ./claude-plugin --strict
```
