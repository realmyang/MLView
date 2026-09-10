# Visualize a pipeline

**Run `MLView: Visualize ML Workflow (Workspace)`.**

The diagram is one picture of the whole pipeline, laid out as eight stage lanes in the order
data actually moves through them:

`config → data → preprocess → model → objective → train → eval → deliver`

Each lane holds the *units* the analyzer recovered — classes, functions, training loops — and
inside them the *ops*: the individual calls that do the work. Edges are typed: a solid edge is
a value flowing, a dashed one a call, a dotted one configuration.

Three things worth knowing on the first screen:

- **A lane that is empty is a statement.** "not detected: preprocess" means the analyzer found
  no preprocessing, which is a finding about your code, not a gap in the picture.
- **A ghosted node is a guess.** Anything the analyzer could not resolve statically is drawn
  faded and says so on hover, rather than being dropped silently.
- **The counts describe what was analyzed.** If notebooks were skipped, or a file failed to
  parse, the tooltip and the coverage chip say so — a clean bill of health and "I could not
  look" never render the same.

`MLView: Visualize ML Workflow (Current File)` is the same picture narrowed to one file. By
default it still *analyzes* the surrounding package, because analysing a file alone cannot fire
the cross-file rules and would quietly lose findings.
