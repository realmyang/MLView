# Install the MLView skill

Use the LLM in your existing Copilot, Codex, or Claude Code assistant to interpret
source and configuration. Install the portable MLView skill into this workspace
using the installer in the MLView checkout. Codex/Copilot discover the
.agents/skills/mlview directory; Claude can use its plugin or .claude/skills.
The copied skill includes its own helper and needs Python 3.10+ to publish.

MLView uses your host's model, permissions, and source-processing policy. It
requires no separate API key. The viewer itself does not run an analyzer or a
model. Legacy static commands still use MLView: Select Python Interpreter.
