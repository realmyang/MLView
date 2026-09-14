# Read a finding in Problems

Every finding MLView makes is a real VS Code diagnostic. **Run `MLView: Show ML Issues`**, or
just open the Problems panel (`Ctrl+Shift+M` / `Cmd+Shift+M`) and filter on `MLView`.

A finding carries more than a message:

| Part | What it is |
|---|---|
| `MLVnnn` | The rule code — a link to an **offline** page shipped with the extension |
| Severity | `high` is a correctness bug; `medium` is a hygiene problem; `low` is a smell |
| Fix hint | The concrete API-level change, not "consider reviewing this" |
| Related locations | The other end of the finding — the split site a leak crossed, for instance |

Two dials decide what reaches the panel: `mlview.minSeverity` and `mlview.minConfidence`
(default `0.6`). Lower-confidence findings still exist on the canvas; they are held back from
Problems so the panel stays worth reading.

Disagree with a rule? The lightbulb on a finding offers `# mlview: ignore[MLVnnn]` on the line,
in the file, or in `.mlview.toml` for the whole project — and
**`MLView: Open MLView Configuration`** opens that file, creating it if there is none. The file
wins for what is disabled; `mlview.disabledRules` can only hide *more*.

Adopting MLView on a repository that already has findings? **`MLView: Create Baseline From
Current Findings`** records today's list so only new findings count from here.
