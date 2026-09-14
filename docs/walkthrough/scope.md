# Narrow the diagram to one unit

A 300-node research repository is not a picture you can read. Put the cursor inside the class
or function you care about and press **`Alt+Shift+M`** (`MLView: Scope Diagram to Symbol`).

The diagram redraws as just that unit and its immediate boundary — what flows in, what flows
out — and the title bar says how much of the graph you are looking at.

**The rail never lets a scope read as a clean bill of health.** It says, in words:

> 3 of 15 findings shown · 12 outside this scope · **Show all**

That line is the point of the feature. A scoped view is a filtered view, and its counts describe
the scope, not the project; a scoped diagram that showed "3 findings" with nothing else said
would be a lie by omission.

`MLView: Clear Diagram Scope` puts the whole graph back.

The same selector grammar is available everywhere MLView is: `stage:train`, `unit:train.train`,
`file:data.py`, `concern:evaluation`, `node:<id>`. Copilot agent mode and the Claude Code MCP
tools both take it, so "what does the evaluation stage do here?" is one question in either
assistant, answered from the same projection this keyboard shortcut produces.
