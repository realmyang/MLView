# Jump from the editor to the diagram

Put the cursor anywhere inside a training script and press **`Alt+M`**
(`MLView: Reveal in Diagram`).

The diagram opens beside the editor, pans to the node that line belongs to, selects it and
announces the selection to a screen reader. It is a round trip, not a one-way link: clicking a
node in the diagram opens the file at the line it came from, and every finding in the rail does
the same.

If the cursor is on a line the analyzer produced no node for, MLView says so rather than
guessing at a nearby one. A quiet wrong answer is worse than a refusal.

Above every analyzed unit there is also a **`MLView: show in diagram`** CodeLens, which is the
same jump for people who would rather click than remember a chord. Turn it off with
`mlview.codeLens` if the extra line bothers you.

> In a workspace with several folders open, the CodeLens and the reveal both follow the file
> you are actually in — not whichever folder happens to be first. The status-bar tooltip names
> the folder the counts describe, and offers to switch.
