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

Cite cell source exactly (the excerpt command's `--cell`), and disclose in node
detail or coverage any metadata used beyond those citations. Track names and
objects that can survive between cells. When a cell recreates an optimizer,
model, iterator, or fitted transform, state which earlier state is replaced and
which could persist. Condition accumulation findings on enough iterations or
repeated executions for the effect to occur.

Notebooks over 8 MiB (usually embedded outputs) cannot be cited: ask the user
to clear outputs, or list the notebook as inspected and mark dependent claims
inferred or unresolved.

## Configuration and lifecycle

Resolve values in precedence order across defaults, config files, environment,
CLI arguments, registries/factories, and runtime overrides. Record the selected
scenario and keep incompatible branches separate. Trace each material value to
the consumer it changes; presence in a config does not prove use. Record flags
the user supplied as the user's choice, and cite a README or other document
only for what it actually contains.

For absence claims, name the search boundary and lifecycle interval: for
example, “no later cell in this notebook source consumes the test split” or
“the selected entrypoint contains no checkpoint write after training.” Search
indirect calls, hooks, callbacks, teardown/finally blocks, and framework-owned
lifecycle methods before asserting absence. Do not broaden a scoped absence to
the repository, runtime, or external orchestration. In `coverage.limitations`,
write `Excluded by request:` only for what the user put out of scope; your own
choice not to inspect something is `Not inspected:` with the reason.
