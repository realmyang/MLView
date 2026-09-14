"""ANA-10's graph-side half: config aliases, alternatives, and the YAML note.

`ir/config_values.py` decides *what a config value is*; this module decides
*what the diagram says about it*. It is a separate file for the same reason
`core/hooks.py` is: `core/build.py` is the largest module in the analyzer and
every feature that grows it makes the next one harder to review.

Three jobs, and each of them is a statement about what the analyzer could and
could not see:

* **aliases** - a container that travelled into a function is bound to a name in
  every scope it reached, and minting one node per name draws the same dict
  three times. Every alias maps onto the single node its container already has,
  so `config` edges run from `CFG` into each consuming unit **across files**.
* **selections** - `getattr(<module>, <a string>)` used to draw an `unknown`
  box that said nothing at all. It draws a `config` node now, and the node says
  which symbol was selected when the string resolved to a literal, or which
  symbols it could have been when it did not - *"one of MLP, WideMLP"* is a
  claim a reader can check, and `unknown` never was. The node's kind stays
  `config` in both cases: a `getattr` line **selects a name**, it does not
  construct anything, and borrowing the `class` / `model` kind for it would
  claim the object exists a line before it does.
* **the YAML note** - the on-disk half of ANA-10 is deferred, so a workspace
  that keeps its hyperparameters in `conf/config.yaml` gets a
  `config_unresolved` diagnostic naming the file rather than an empty Config
  lane that looks like a project with no configuration.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from ..ir import config_values as CV
from ..ir.model import CallSite, ModuleIR, ValueRef
from .graph import Diagnostic, Evidence, Node

__all__ = ["MAX_CONFIG_NOTES", "map_aliases", "selection_op",
           "config_diagnostics"]

#: How many "I did not open this config file" notes one module may publish. The
#: point is to be told once per file, not once per call site.
MAX_CONFIG_NOTES = 3


def map_aliases(builder, aliases: Sequence[Tuple[Tuple[str, str, str], ValueRef]]
                ) -> None:
    """Point every config alias at the one node its container already has.

    The origin arrives as a `(relpath, scope, name)` key rather than a
    `ValueRef`, because the binding passes rebuild every `ValueRef` on every IR
    round and only a name survives them.
    """
    for key, ref in aliases:
        origin = CV.resolve_origin(builder.ws, key)
        node = builder._producer_node(origin) if origin is not None else None
        if node is not None:
            builder.config_literal_node[id(ref)] = node


def selection_op(builder, call: CallSite, module: ModuleIR,
                 fqn: Optional[str] = None, alternatives=None) -> Node:
    """One `config` node for a `getattr` that selects a symbol by name.

    Two shapes, one node. **Resolved**: the config string was a literal, the
    symbol is named exactly, and the construction a line later resolves through
    it - so the registry that produced two `unknown` boxes produces a named
    selection and a real `optimizer`. **Unresolved**: the string is not a
    literal, but a `getattr` on a *workspace* module is still bounded to the
    symbols that module defines, so the node names them and takes `1/N` as its
    confidence: it is certainly here, and which symbol it is is a one-in-N guess
    this pass refuses to make.
    """
    if fqn is not None:
        sublabel = "selects %s" % fqn
        confidence = 0.9
        evidence = Evidence(
            "fqn_resolved",
            "the attribute resolved to a config literal, so this getattr "
            "selects %s exactly" % fqn, 1.0)
    else:
        prefix, names = alternatives
        sublabel = "one of %d in %s · %s" % (len(names), prefix, ", ".join(names))
        confidence = round(1.0 / max(1, len(names)), 2)
        evidence = Evidence(
            "name_regex",
            "getattr on the workspace module %s selects one of its %d "
            "definitions (%s); which one is decided by a value this run could "
            "not resolve" % (prefix, len(names), ", ".join(names)), 0.5)
    if call.scope.is_dynamic:
        confidence = round(confidence * 0.7, 4)
    parent = builder._owning_unit(call)
    node = builder._make_node(
        module.relpath,
        "%s.%s" % (call.scope.qualname, call.var or call.short_name), "config",
        level="op", stage="config", label=call.var or "%s()" % call.short_name,
        sublabel=sublabel, fqn=fqn, var=call.var, loc=call.loc,
        parent=parent.id if parent else None,
        dynamic=call.scope.is_dynamic, confidence=confidence,
        stageEvidence=[evidence])
    builder.node_for_call[id(call)] = node
    builder.call_for_node[node.id] = call
    if parent is not None:
        builder._children.setdefault(parent.id, []).append(node)
        votes = builder._op_votes.setdefault(parent.id, {})
        votes["config"] = votes.get("config", 0.0) + 0.5
    return node


def config_diagnostics(builder) -> None:
    """Name every config file this run deliberately did not open."""
    for module in builder._modules():
        notes = CV.yaml_notes(module)
        if not notes:
            continue
        distinct = len({message for _line, message in notes})
        said: List[str] = []
        for line, message in sorted(notes):
            if message in said:
                continue
            if len(said) >= MAX_CONFIG_NOTES:
                builder.diagnostics.append(Diagnostic(
                    kind="config_unresolved", file=module.relpath, line=line,
                    message=("MLView did not open the remaining config files %s "
                             "references; the YAML / Hydra half of config "
                             "resolution is deferred, so any value that comes "
                             "from them is unresolved rather than guessed."
                             % module.relpath),
                    count=distinct - len(said)))
                break
            said.append(message)
            builder.diagnostics.append(Diagnostic(
                kind="config_unresolved", file=module.relpath, line=line,
                message=message))
