# Notebook, configuration, and lifecycle reread

Use this reference for notebooks, layered configuration, scoped absence, or
state that survives across phases.

## Notebooks and raw metadata

Read code-cell source in document order. Also inspect raw `execution_count`,
cell outputs, tags, IDs, and relevant notebook/kernel metadata when they bear
on the question. Keep these categories separate:

- source order is the authored sequence;
- execution counts and saved outputs are recorded history that may be stale,
  partial, duplicated, or from another kernel state;
- actual execution success and in-memory values remain unresolved without a
  trustworthy run record.

Track names and objects that can survive between cells. When a cell recreates
an optimizer, model, iterator, or fitted transform, state which earlier state
is replaced and which could persist. Condition accumulation findings on enough
iterations or repeated executions for the effect to occur.

## Configuration and lifecycle

Resolve values in precedence order across defaults, config files, environment,
CLI arguments, registries/factories, and runtime overrides. Record the selected
scenario and keep incompatible branches separate. Trace each material value to
the consumer it changes; presence in a config does not prove use.

For absence claims, name the search boundary and lifecycle interval: for
example, “no later cell in this notebook source consumes the test split” or
“the selected entrypoint contains no checkpoint write after training.” Search
indirect calls, hooks, callbacks, teardown/finally blocks, and framework-owned
lifecycle methods before asserting absence. Do not broaden a scoped absence to
the repository, runtime, or external orchestration.
