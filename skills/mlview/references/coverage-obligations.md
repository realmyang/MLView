# Coverage obligations and critique checklist

Use this as a scratch checklist tailored to the user's request. Do not copy it
into the artifact or add placeholder nodes. Mark an item **answered** (including
justified absence within inspected source), **not applicable**, **not inspected**,
or **unresolved with a stated boundary** before publication. Put material
uninspected work in coverage limitations and choose partial/scoped coverage as
appropriate; do not imply that an uninspected area is absent.

## Coverage obligations

- Selected scenario: entrypoint, configuration precedence, launch assumptions,
  and mutually exclusive alternatives.
- Data and state: origins, splits, transforms, fitted state, initialization,
  and state carried across loops, cells, phases, or restarts.
- Construction and calls: resolved factories/registries, relevant wrappers,
  branches, loops, callbacks, and framework-owned lifecycle seams.
- Objectives and updates: exact loss expressions, optimizer-owned parameter
  sets, gradient paths, reset/accumulation behavior, and update ordering.
- Evaluation: the data actually consumed, mode/context changes, metric inputs,
  aggregation, selection criteria, and leakage boundaries.
- Outputs: exact log/return/save expressions, payloads, conditions, consumers,
  and values that are accumulated but never observed.
- Uncertainty and absence: external inputs, runtime-dependent behavior, search
  boundary for negative claims, counter-evidence, and files still uninspected.

Every material answer should map to source evidence or be visibly qualified as
inferred/unresolved. `coverage.inspectedFiles` must include context that changed
the interpretation even when it supplied no displayed quotation. Each
`coverage.limitations` entry starts with `Excluded by request:` (only for what
the user put out of scope) or `Not inspected:` with the reason.

## Critique checklist

Run it once on the validated draft. Fix what fails, validate again, and then
re-read each material correction in the validated draft before reporting it: a
failed edit can leave the old text in place.

Workflow questions:

- Does the diagram show where data originates, what parameters or fitted state
  change, which objectives drive those changes, where evaluation occurs, what
  outputs are produced, and what remains unknown?
- For a missing step, is it absent in the inspected scenario or not yet traced?
  Do not add a node or finding merely to fill this checklist.
- Are preprocessing fit boundaries and state carried across repeated phases
  shown when they affect the request?

Claims against the source:

- Check alternative interpretations, unsupported connections, claimed
  absences, and mixing of mutually exclusive scenarios.
- Do the cited lines execute the stated behavior under the scenario's flags?
  Prefer the executing line to a nearby caller, definition, or comment.
- Does each cited range show every value its claim states? A single line
  rarely supports a claim about several fields.
- Are flags the user supplied recorded as the user's choice? Cite a document
  only for what it actually contains.
- For a negative or "never" claim that depends on schedule arithmetic or an
  assumed data size, check each lifecycle interval separately (for example the
  first iterations, the steady state, and the last iteration) and mark derived
  counts `inferred`.
- Check long literal data (label lists, maps, templates) by reading it as data:
  count entries, look for duplicates, and check alignment with its consumer. A
  scratch script under `.mlview/` may parse the literal's text with a standard
  JSON or literal parser; never import or execute the target file.

Structure:

- Every repeated phase is a loop: a `loop` node with children and a `loop`
  edge from the last step of the repeated work back to its first step,
  carrying state across iterations.
- Every shared component (a model, data loader, or preprocessing object) has
  an edge to each step that uses it.
- Every branch or loop outcome (such as continue, retry, skip, or stop) is an
  edge.
- Components whose parameters change by different mechanisms (optimizer step,
  averaging or copying, frozen) are separate nodes or state nodes, each with
  its own update edge. One-time construction is separate from the repeated
  work that uses it.
- Node and edge kinds come from the recommended lists in SKILL.md where they
  fit.

Basis:

- List the claims that rest on framework or library semantics, runtime values,
  or data. Each one is cited to code that establishes it or sits in its own
  `inferred` or `unresolved` node or edge.
- Each node's and edge's basis is its weakest load-bearing claim. Do not
  demote directly observed content: split the dependent part out instead.
- The helper's `basis` summary agrees with that list, and any statement about
  basis in coverage text matches the actual labels.

Findings:

- Each finding names a concrete consequence in the selected scenario and what
  the user would change; otherwise it belongs in node detail, a limitation, or
  an unresolved node. A finding does not restate a limitation.
- Severity follows the rubric in SKILL.md: `high`, silently wrong results in
  the selected scenario; `medium`, a plausible conditional risk with a stated
  trigger, or a certain failure that shows itself when it happens (an
  exception or crash); `low`, reproducibility or observability.
- An unresolved-risk finding names the node or edge whose outcome could flip.
- `counterEvidence` holds only source that weakens, bounds, or conditions the
  finding; a medium or high finding carries it or states the search boundary.

Helper output (warnings never block publication and never count as repair
rounds, but on the finished draft each can signal an omission; while the draft
is still growing they are expected):

- `unreferenced_evidence`: attach the record to the claim it supports, or
  remove it.
- `isolated_node`: connect it to the step it affects or nest it under a
  group; a node that only records an absence or an external unknown belongs
  in `coverage.limitations` instead.
- `self_edge`: point the edge at the real target; for an iteration, draw the
  `loop` edge from the last step of the repeated work back to its first step
  (a one-step repetition may keep a self-edge of kind `loop`, drawn as a small
  loop on its card).
- `wide_evidence`: split the range into records for each claim.
- `evidence_overlap`: counterEvidence repeats a supporting record; remove it.
- `duplicate_inspected`: list each inspected file once.
