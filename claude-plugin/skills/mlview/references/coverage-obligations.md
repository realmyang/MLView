# Coverage obligations

Use this as a scratch checklist tailored to the user's request. Do not copy it
into the artifact or add placeholder nodes. Mark an item **answered** (including
justified absence within inspected source), **not applicable**, **not inspected**,
or **unresolved with a stated boundary** before publication. Put material
uninspected work in coverage limitations and choose partial/scoped coverage as
appropriate; do not imply that an uninspected area is absent.

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
the interpretation even when it supplied no displayed quotation.
