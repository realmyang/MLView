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
                            default_digest, derating_rationale, path_name,
                            read_for, tree_of, workspace_class)
from .model import ModuleIR, ValueRef
from .returns import slot_of

__all__ = [
    "CONFIG_NAME_RE", "CONFIG_EVIDENCE_WEIGHT", "MAX_CONFIG_HOPS",
    "MAX_CONFIG_LEAVES", "MAX_PATH_DEPTH", "MAX_ALTERNATIVES",
    "ConfigRead", "resolve_module", "path_name", "config_read_of",
    "resolved_call_fqn", "alternatives_for", "selected_symbol",
    "alias_origin", "resolve_origin", "yaml_notes", "config_roots",
    "kwarg_reads", "derating_rationale",
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
    # ANA-02: a `CFG["workers"] = 0` two lines below the literal is a real
    # assignment and 11.45 A2 says a real assignment always wins. Applied to
    # the ROOT's tree rather than to the materialised leaves, so an importing
    # module inherits the corrected container instead of the stale one.
    _apply_stores(module, roots)
    _imported_roots(module, workspace, roots)
    _parameter_roots(module, workspace, roots)
    _materialize(module, roots)
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
        argparse_from = _argparse_module(call, module) if call is not None else None
        if argparse_from is not None:
            tree = argparse_tree(argparse_from)
            origin = "the argparse defaults in %s" % argparse_from.relpath
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


def _argparse_module(call, module: ModuleIR) -> Optional[ModuleIR]:
    """The module whose `add_argument(default=...)` calls define this namespace.

    ANA-04: the test used to be `call.short_name == "parse_args"`, so the single
    commonest way real code is written -

        def get_args():
            p = argparse.ArgumentParser()
            p.add_argument("--shuffle", type=bool, default=True)
            return p.parse_args()

        args = get_args()

    - was not a config root at all: nothing resolved, nothing was de-rated, and
    nothing said the container had gone unread. Combined with ANA-03 that
    turned a recall gap into a false positive on correct code. `argparse_tree`
    was always module-wide (and refuses a module with two parsers outright), so
    the only thing missing was following the wrapper one level - which the
    return inference already does.
    """
    if call.short_name == "parse_args":
        return module
    target = call.target_function
    if target is None:
        return None
    slot = slot_of(call)
    fqns = slot.fqns if slot is not None else ()
    if not any(f.rsplit(".", 1)[-1] == "parse_args" for f in fqns):
        return None
    return getattr(target, "module", None)


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
                # REV5-04: DATAFLOW-IP turns its own hop cap into a `truncated`
                # diagnostic because "I stopped following this" is a fact the
                # reader needs; ANA-10's cap said nothing at all, so a container
                # that travelled three hops read exactly like a container this
                # pass never looked at. Same discipline, same vocabulary.
                module.config_yaml_notes.append((func.loc.line, (
                    "the config container reaching `%s` in %s (from %s) is more "
                    "than %d hop(s) away, so MLView stopped following it and "
                    "resolved no value out of it."
                    % (param, func.qualname, origin or "a config container",
                       MAX_CONFIG_HOPS))))
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
# ANA-02: a container that is written to after it is built
# ---------------------------------------------------------------------------
#: Methods that rewrite a container in place. `pop` and `clear` remove keys and
#: `update` can add or replace any of them, so none of the three can be
#: modelled leaf by leaf: the honest answer is to refuse the whole container.
_MUTATING_METHODS = ("update", "setdefault", "pop", "popitem", "clear",
                     "__setitem__")


def _apply_stores(module: ModuleIR, roots) -> None:
    """Fold every later write to a config path back into its root's tree.

    11.45 A2 - *"A real assignment to the same dotted name always wins; the
    leaf is never written over one"* - held only for the attribute spelling,
    where the store creates an ordinary binding that `_materialize` then
    declines to overwrite. A **subscript** store creates no binding, which is
    to say it held for every spelling except the one a dict is written in - so
    `CFG = {"workers": 4}` followed by `CFG["workers"] = 0` was read as 4 and
    MLV112 published a finding about a value the program never has.

    Two outcomes, both of them the assignment winning:

    * the store is **unconditional in the container's own suite** - the same
      indentation as the statement that built it, outside any loop or `match` -
      and its right-hand side is a literal, so the leaf takes the new value;
    * anything else - a store under an `if`, inside a loop, in a `match` arm, a
      right-hand side that is not a literal, or an `update()` / `pop()` /
      `clear()` where no leaf-by-leaf story is true at all - so the path and
      everything under it is **removed** from the tree and the rules see an
      unresolved value, which is what they saw before ANA-10 existed.

    The second branch is the important one: adopting a value that is only
    written on one path would let a rule state a number the program may never
    have, which is worse than resolving nothing. The column test is what tells
    the two apart, and it costs nothing.

    Either way it is recorded on `module.config_yaml_notes`, so the refusal
    reaches the document as a `config_unresolved` diagnostic instead of being
    silently indistinguishable from a value nothing ever wrote.
    """
    if not roots:
        return
    by_scope: Dict[str, Dict[str, Root]] = {}
    for (qualname, name), root in roots.items():
        by_scope.setdefault(qualname, {})[name] = root
    for record in module.assignments:
        scoped = by_scope.get(record.scope.qualname)
        if not scoped:
            continue
        for target in record.targets:
            if not isinstance(target, (ast.Subscript, ast.Attribute)):
                continue
            path = path_name(target)
            if not path:
                continue
            head, _dot, _rest = path.partition(".")
            root = scoped.get(head)
            if root is None:
                continue
            literal = (_literal_str(record.value)
                       if _unconditional(record, root) else None)
            _rewrite_leaf(module, root, path, literal, record.loc.line)
    for call in module.calls:
        name = (call.receiver_name or "").split(".")[0]
        scoped = by_scope.get(call.scope.qualname if call.scope is not None else "")
        root = scoped.get(name) if scoped else None
        if root is None or (call.method or call.short_name) not in _MUTATING_METHODS:
            continue
        _rewrite_leaf(module, root, root.name, None, call.loc.line,
                      "%s.%s()" % (name, call.method or call.short_name))


def _unconditional(record, root: Root) -> bool:
    """Does this store run on every path that reached the container?

    Column equality with the container's own assignment is the whole test: a
    statement written under an `if`, a `try` or a `with` is indented further
    than the statement that built the container, and a loop or a `match` arm is
    recorded explicitly. It over-refuses (a store in a sibling `if` chain that
    covers every case reads as conditional) in the only safe direction.
    """
    if record.kind not in ("assign", "ann", "walrus"):
        return False
    if record.loop is not None or getattr(record, "in_match", False):
        return False
    origin = getattr(root.ref, "loc", None) if root.ref is not None else None
    if origin is None:
        return False
    return record.loc.file == origin.file and record.loc.col == origin.col


def _literal_str(node) -> Optional[str]:
    """`ir.scopes.literal_str`, imported lazily: `scopes` is upstream of this."""
    from .scopes import literal_str
    return literal_str(node)


def _note_cap(module: ModuleIR, root: Root, why: str) -> None:
    """Record one cap that stopped a container being resolved (REV5-04)."""
    message = ("MLView resolved only part of the config container `%s` (%s): %s. "
               "Any value it holds beyond that is unresolved rather than guessed."
               % (root.name, root.origin or "a config container", why))
    line = root.line or 1
    if (line, message) not in module.config_yaml_notes:
        module.config_yaml_notes.append((line, message))


def _rewrite_leaf(module: ModuleIR, root: Root, path: str,
                  literal: Optional[str], line: int,
                  how: Optional[str] = None) -> None:
    """Replace or delete `path` (and its subtree) in `root.tree`."""
    parts = tuple(path.split("."))
    if parts[0] != root.name:
        return
    key = parts[1:]
    if literal is not None:
        if root.tree.get(key) == literal:
            return
        root.tree[key] = literal
        return
    doomed = [p for p in root.tree if p == key or p[:len(key)] == key] if key \
        else list(root.tree)
    if not doomed:
        return
    for p in doomed:
        del root.tree[p]
    module.config_yaml_notes.append((line, (
        "`%s` is rewritten at %s:%d by %s, so MLView refused the %d value(s) it "
        "had resolved out of it rather than reading a stale one."
        % (path, module.relpath, line, how or "a store it cannot evaluate",
           len(doomed)))))


# ---------------------------------------------------------------------------
# materialisation
# ---------------------------------------------------------------------------
def _materialize(module: ModuleIR, roots) -> None:
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
        # REV5-04: the width cap is applied upstream, in `config_shapes.merge`,
        # which stops filling the tree and returns - so by the time the leaves
        # are stored the only trace left is a tree that is exactly the cap wide.
        # That is the condition, and it is the one worth reporting: part of this
        # container was never resolved, and nothing said so.
        if len(root.tree) >= MAX_CONFIG_LEAVES:
            _note_cap(module, root, "it is at or beyond the %d-leaf cap MLView "
                                    "resolves per container, so an unknown "
                                    "number of its values were never read"
                      % MAX_CONFIG_LEAVES)
        if any(len(path) >= MAX_PATH_DEPTH for path in root.tree):
            _note_cap(module, root, "it nests at least %d levels deep, which is "
                                    "the deepest path MLView spells" % MAX_PATH_DEPTH)
        for path in sorted(root.tree):
            if not path:
                continue
            if made >= MAX_CONFIG_LEAVES:
                # REV5-04: the cap used to `break` in silence, which reads
                # downstream exactly like a container ANA-10 never looked at.
                _note_cap(module, root, "it is wider than the %d-leaf cap "
                                        "MLView resolves per container"
                          % MAX_CONFIG_LEAVES)
                break
            # `made` counts leaves CONSIDERED, not leaves created. Counting
            # creations made the cap round-dependent: after the first IR round
            # every leaf already exists, so nothing was created, `made` stayed
            # 0, and the note above was reachable only on round one - the
            # silence REV5-04 is about, one level deeper.
            made += 1
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
