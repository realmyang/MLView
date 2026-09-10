"""ANA-10 (Python half) - resolving configuration into literal values.

Measured before this pass existed: `num_workers=4` fires MLV112, a module-level
`WORKERS = 4` fires, and `CFG["workers"]` / `cfg.data.workers` are **silent** -
so every literal-dependent rule (MLV110's `shuffle=`, MLV112's `num_workers=`,
MLV602's `random_state=`, MLV208's `GradScaler(enabled=)`) degrades the moment a
project keeps its hyperparameters where projects actually keep them.

This module is the orchestration: which **names** in a module hold a config
container (`ir.config_shapes` says what a container is, `ir.config_calls` says
what call sites do with one), and what reading a value out of one costs.

* a module-level **dict literal** bound to a `CONFIG_NAME_RE` name (`CFG = {...}`);
* a **dataclass** instance's field defaults;
* **argparse** `add_argument(..., default=...)`;
* an **attribute or subscript chain** rooted at any of the above -
  `cfg.data.workers` and `CFG["data"]["workers"]` are the same path, because
  that is exactly what a `DictConfig` / `SimpleNamespace` / dataclass makes
  them, and a reader who writes one means the other;
* and the same container after it has travelled - through an import, through a
  parameter default, through an argument.

The resolved leaves are stored as ordinary `ValueRef`s carrying a `literal`, so
`rules.helpers.literal_of` picks them up **with no rule changes**. Each leaf
also carries a `config_read` describing where the value came from and what it
costs in confidence.

**Three things this deliberately does not do**, because a wrong read is worse
than no read:

1. **It never opens a file.** The YAML / Hydra half of ANA-10 is deferred; when
   a workspace references a YAML config, `yaml_notes` records it and the graph
   builder publishes a `config_unresolved` diagnostic naming it. *"Never
   imports, never execs"* stays load-bearing, and now *"never reads a config
   file"* is stated rather than discovered.
2. **It never mints a `certain` finding.** Every value that arrives through
   this pass carries `CONFIG_EVIDENCE_WEIGHT` once, compounded per
   interprocedural hop, exactly the way `ir.provenance.IP_HOP_WEIGHT` works -
   because a config container can be overridden at run time by a mechanism no
   static reader can see (a Hydra override, an `argv`, a `cfg.update(...)`).
3. **It intersects, never unions.** A parameter takes a config value only when
   *every* call site of its function agrees on the same container; one
   disagreeing site (or one argument the pass cannot follow) and the parameter
   stays unresolved.

Nothing here imports from `ir.bindings` - `bindings` imports *this* module (and
takes `CONFIG_NAME_RE` from it, so the two spellings cannot drift) and calls
`resolve_module` at the end of every binding round, so the dependency runs one
way.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional, Tuple

from .config_calls import kwarg_reads, scan_calls, undo_kwargs
from .config_shapes import (CONFIG_EVIDENCE_WEIGHT, CONFIG_NAME_RE,
                            MAX_ALTERNATIVES, MAX_CONFIG_HOPS,
                            MAX_CONFIG_LEAVES, MAX_PATH_DEPTH, ConfigRead,
                            Root, argparse_tree, config_read_of,
                            default_digest, path_name, read_for, tree_of,
                            workspace_class)
from .model import ModuleIR, ValueRef

__all__ = [
    "CONFIG_NAME_RE", "CONFIG_EVIDENCE_WEIGHT", "MAX_CONFIG_HOPS",
    "MAX_CONFIG_LEAVES", "MAX_PATH_DEPTH", "MAX_ALTERNATIVES",
    "ConfigRead", "resolve_module", "path_name", "config_read_of",
    "resolved_call_fqn", "alternatives_for", "selected_symbol",
    "alias_origin", "resolve_origin", "yaml_notes", "config_roots",
    "kwarg_reads",
]

def config_roots(module: ModuleIR) -> Dict[str, Any]:
    """This module's module-scope config roots, by name (read by other modules)."""
    return getattr(module, "config_roots", None) or {}


def _reset(module: ModuleIR) -> None:
    undo_kwargs(module)
    module.config_roots = {}
    module.config_call_fqn = {}          # id(CallSite) -> resolved FQN
    module.config_name_lookups = {}      # id(CallSite) -> selected FQN
    module.config_alternatives = {}      # id(CallSite) -> (name, ...)
    module.config_alias_root = {}        # id(alias ValueRef) -> origin key
    module.config_yaml_notes = []        # (line, message)
    module.config_symbols = {}           # (scope qualname, name) -> FQN


def resolve_module(module: ModuleIR, workspace) -> None:
    """Resolve this module's config containers into leaf bindings.

    Called at the end of every `bind_module`, so it runs once per module per IR
    round and its output is part of the state `ir.converge` fingerprints - a
    round that only moved a config value still counts as movement, and the
    argument -> parameter propagation reaches its fixed point the same way
    `propagate_parameters` does, one hop per round.
    """
    _reset(module)
    if workspace is None or module.module_scope is None:
        return
    _init_workspace(workspace)
    roots: Dict[Tuple[str, str], Root] = {}
    _local_roots(module, workspace, roots)
    _imported_roots(module, workspace, roots)
    _parameter_roots(module, workspace, roots)
    _materialize(roots)
    scan_calls(module, workspace, roots)


def _init_workspace(workspace) -> None:
    if getattr(workspace, "config_param_sites", None) is None:
        workspace.config_param_sites = {}
    if getattr(workspace, "config_trees", None) is None:
        workspace.config_trees = {}
    if getattr(workspace, "config_tree_sources", None) is None:
        workspace.config_tree_sources = {}


def _local_roots(module: ModuleIR, workspace, roots) -> None:
    """`CFG = {...}` / `cfg = TrainConfig()` / `args = parser.parse_args()`."""
    for record in module.assignments:
        if record.kind not in ("assign", "ann", "walrus"):
            continue
        targets = record.targets
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        name = targets[0].id
        if not CONFIG_NAME_RE.match(name):
            continue
        scope = record.scope
        ref = scope.bindings.get(name)
        if ref is None or ref.loc != record.loc:
            continue                     # a later statement rebound the name
        call = record.call
        tree = origin = None
        if call is not None and call.short_name == "parse_args":
            tree = argparse_tree(module)
            origin = "the argparse defaults in %s" % module.relpath
        elif call is not None:
            cls = workspace_class(module, workspace, call.node.func)
            tree = tree_of(call.node, module, workspace)
            origin = ("the dataclass defaults of `%s`" % cls.name) if cls is not None \
                else "a config constructor"
        elif record.value is not None:
            tree = tree_of(record.value, module, workspace)
            origin = "the dict literal `%s`" % name
        if not tree:
            continue
        ref.is_config = True
        root = Root(name=name, scope=scope, ref=ref, tree=tree, origin=origin,
                     file=record.loc.file, line=record.loc.line, hops=0,
                     source=(module.relpath, scope.qualname, name))
        roots[(scope.qualname, name)] = root
        if scope is module.module_scope:
            module.config_roots[name] = root


def _imported_roots(module: ModuleIR, workspace, roots) -> None:
    """`from conf import CFG` - the root the defining module already resolved."""
    symbols = getattr(module, "symbols", None)
    scope = module.module_scope
    if symbols is None or scope is None:
        return
    for local in sorted(symbols.aliases):
        if not CONFIG_NAME_RE.match(local) or (scope.qualname, local) in roots:
            continue
        head, _dot, attr = symbols.aliases[local].rpartition(".")
        other = workspace.by_dotted.get(head)
        if other is None or other is module:
            continue
        root = config_roots(other).get(attr)
        ref = scope.bindings.get(local)
        if root is None or ref is None:
            continue
        ref.is_config = True
        roots[(scope.qualname, local)] = Root(
            name=local, scope=scope, ref=ref, tree=root.tree,
            origin=root.origin, file=root.file, line=root.line,
            hops=root.hops, source=root.source)
        module.config_alias_root[id(ref)] = root.source


def _parameter_roots(module: ModuleIR, workspace, roots) -> None:
    """A `cfg`-shaped parameter, when every call site agrees what it is.

    Intersection, never union: the parameter takes a container only when every
    recorded call site of the function passed the same one. A site that passed
    something this pass could not follow records `None`, which is enough to
    refuse the whole parameter - so an unanalysable second caller silences the
    first rather than being outvoted by it.
    """
    sites = workspace.config_param_sites
    trees = workspace.config_trees
    for qualname in sorted(module.functions):
        func = module.functions[qualname]
        for param in [p for p in func.params if p != "self"]:
            if not CONFIG_NAME_RE.match(param) or param in func.scope.bindings:
                continue                 # a real assignment always wins
            recorded = sites.get((func.qualname, param))
            if recorded:
                values = {recorded[key] for key in sorted(recorded)}
                digest = values.pop() if len(values) == 1 else None
            else:
                digest = default_digest(module, workspace, func, param, roots)
            entry = trees.get(digest) if digest is not None else None
            if entry is None:
                continue
            tree, origin, file, line, hops = entry
            if hops + 1 > MAX_CONFIG_HOPS:
                continue
            ref = ValueRef(name=param, scope=func.scope, loc=func.loc,
                           is_config=True)
            func.scope.bindings[param] = ref
            source = workspace.config_tree_sources.get(digest)
            roots[(func.scope.qualname, param)] = Root(
                name=param, scope=func.scope, ref=ref, tree=tree, origin=origin,
                file=file, line=line, hops=hops + 1, source=source)
            if source is not None:
                module.config_alias_root[id(ref)] = source

# ---------------------------------------------------------------------------
# materialisation
# ---------------------------------------------------------------------------
def _materialize(roots) -> None:
    """Store every leaf as an ordinary literal-carrying `ValueRef`.

    The binding is written straight into `scope.bindings` and **not** into
    `binding_history`: it is not a statement, it has no position in the source
    order, and REV-01's ordered lookup must keep answering questions about real
    stores only.
    """
    for key in sorted(roots):
        root = roots[key]
        scope = root.scope
        made = 0
        for path in sorted(root.tree):
            if not path:
                continue
            if made >= MAX_CONFIG_LEAVES:
                break
            name = "%s.%s" % (root.name, ".".join(path))
            if name in scope.bindings:
                continue
            literal = root.tree[path]
            ref = ValueRef(name=name, scope=scope, literal=literal,
                           loc=root.ref.loc if root.ref is not None else None,
                           sources=(root.name,))
            ref.config_read = read_for((root.name,) + path, literal,
                                        root.origin, root.file, root.line,
                                        root.hops)
            scope.bindings[name] = ref
            made += 1

# ---------------------------------------------------------------------------
# what the graph builder asks
# ---------------------------------------------------------------------------
def resolved_call_fqn(module: ModuleIR, call) -> Optional[str]:
    """The FQN a `getattr`-selected factory call constructs, or None."""
    return (getattr(module, "config_call_fqn", None) or {}).get(id(call))


def selected_symbol(module: ModuleIR, call) -> Optional[str]:
    """The FQN a `getattr` this pass resolved selects, or None."""
    return (getattr(module, "config_name_lookups", None) or {}).get(id(call))


def alternatives_for(module: ModuleIR, call):
    """`(module dotted name, symbol names)` a `getattr` could have selected."""
    return (getattr(module, "config_alternatives", None) or {}).get(id(call))


def alias_origin(module: ModuleIR, ref):
    """`(relpath, scope qualname, name)` for the container an alias stands for."""
    return (getattr(module, "config_alias_root", None) or {}).get(id(ref))


def resolve_origin(workspace, key) -> Optional[ValueRef]:
    """The live `ValueRef` an `alias_origin` key names, in this round's IR."""
    if not key or workspace is None:
        return None
    relpath, qualname, name = key
    module = workspace.modules.get(relpath)
    if module is None:
        return None
    for scope in module.scopes:
        if scope.qualname == qualname:
            return scope.bindings.get(name)
    return None


def yaml_notes(module: ModuleIR) -> List[Tuple[int, str]]:
    """`(line, message)` for every YAML / Hydra config this run did not open."""
    return list(getattr(module, "config_yaml_notes", None) or [])
