"""ANA-10: what a call site says about configuration.

Three readings, all of them about **calls** rather than about assignments,
which is why they live apart from `config_values`:

* **parameter sites** - which container each call site hands to a `cfg`-shaped
  parameter of its callee, recorded per site so `config_values` can intersect
  them. Intersection, never union: one site that passed something this pass
  could not follow records `None` and refuses the whole parameter.
* **`getattr` selections** - `getattr(torch.optim, cfg["optimizer"])`. With the
  attribute resolved to a literal the symbol is named exactly and the call a
  line later resolves through it; without it, a `getattr` on a **workspace**
  module is still bounded to the symbols that module really defines.
* **the YAML note** - the on-disk half of ANA-10 is deferred, so every YAML or
  Hydra config the workspace references is recorded here and reported as a
  `config_unresolved` diagnostic. Nothing in this module opens a file.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, Optional

from .. import knowledge as K
from .config_shapes import (CONFIG_NAME_RE, MAX_ALTERNATIVES, MAX_CONFIG_HOPS,
                            config_read_of, default_digest, path_name,
                            record_tree, root_for_expr)
from .model import ModuleIR, ScopeIR
from .symbols import dotted_text

__all__ = ["scan_calls", "undo_kwargs", "kwarg_reads"]

#: Extensions that mean "a config file this analyzer will not open".
_YAML_SUFFIXES = (".yaml", ".yml")
#: Call FQNs that mean the same thing.
_YAML_FQNS = ("yaml.safe_load", "yaml.load", "yaml.full_load",
              "omegaconf.OmegaConf.load", "omegaconf.OmegaConf.merge")

# ---------------------------------------------------------------------------
# calls: parameter sites, getattr, factory calls, YAML notes
# ---------------------------------------------------------------------------
def scan_calls(module: ModuleIR, workspace, roots) -> None:
    for call in module.calls:
        _record_param_sites(call, module, workspace, roots)
        _resolve_getattr(call, module, workspace)
        _note_yaml(call, module)
        _apply_kwargs(call, module)
    for call in module.calls:
        _resolve_factory(call, module)
    _note_yaml_paths(module)
    _note_hydra(module)


def _site_key(call) -> str:
    return "%s:%d:%d" % (call.loc.file, call.loc.line, call.loc.col)


def _record_param_sites(call, module: ModuleIR, workspace, roots) -> None:
    """What this call site says each `cfg`-shaped parameter of its callee is."""
    func = call.target_function
    if func is None:
        return
    params = [p for p in func.params if p != "self"]
    passed: Dict[str, Any] = {}
    for index, arg in enumerate(call.args):
        if index < len(params):
            passed[params[index]] = arg
    for key in sorted(call.kwarg_nodes):
        if key in params:
            passed[key] = call.kwarg_nodes[key]
    for param in params:
        if not CONFIG_NAME_RE.match(param):
            continue
        digest = None
        if param in passed:
            root = root_for_expr(passed[param], call.scope, roots)
            if root is not None and root.hops < MAX_CONFIG_HOPS:
                digest = record_tree(workspace, root)
            elif root is not None:
                # REV5-04: the cap that actually stops most chains, and it
                # stopped them in silence - so a container that travelled too
                # far read exactly like a container ANA-10 never looked at.
                _note_hop_cap(module, call, root, param, func)
        else:
            digest = default_digest(func.module, workspace, func, param, roots)
        workspace.config_param_sites.setdefault(
            (func.qualname, param), {})[_site_key(call)] = digest


def _note_hop_cap(module: ModuleIR, call, root, param: str, func) -> None:
    """Say that a config container was not followed any further (REV5-04)."""
    message = ("the config container `%s` (%s) reaches `%s` of %s at %s:%d after "
               "%d hop(s), which is MLView's cap, so no value was resolved out "
               "of it here. This is a gap in coverage, not an empty container."
               % (root.name, root.origin or "a config container", param,
                  getattr(func, "qualname", "the callee"), call.loc.file,
                  call.loc.line, root.hops))
    row = (call.loc.line, message)
    if row not in module.config_yaml_notes:
        module.config_yaml_notes.append(row)


def _module_prefix(call, module: ModuleIR) -> Optional[str]:
    node = call.args[0] if call.args else None
    if node is None:
        return None
    symbols = getattr(module, "symbols", None)
    resolved = symbols.resolve(node) if symbols is not None else None
    return resolved or dotted_text(node)


def _resolve_getattr(call, module: ModuleIR, workspace) -> None:
    """`getattr(<module>, <config string>)` - the symbol, or the alternatives.

    Two answers, never a guess in between. With the attribute resolved to a
    literal the symbol is named exactly, and the `getattr` stops being an
    operation at all - it is a name lookup, and the node belongs to whatever
    the looked-up symbol is later called as. Without it, a **workspace** module
    still bounds the answer to the symbols that module actually exports, which
    is a one-of-N statement and strictly more than `unknown`.

    Iron law 1 holds in both branches: the exact answer must be a symbol the
    knowledge tables or the workspace really have, and the alternatives are the
    module's real definitions - neither branch invents an FQN.
    """
    if call.short_name != "getattr" or len(call.args) < 2 or not call.var:
        return
    prefix = _module_prefix(call, module)
    if not prefix:
        return
    target = workspace.by_dotted.get(prefix)
    attr = _literal_here(call.args[1], call.scope)
    if attr and attr.isidentifier():
        fqn = "%s.%s" % (prefix, attr)
        known = fqn in workspace.classes or fqn in workspace.functions
        if known or (target is None and K.lookup(fqn) is not None):
            module.config_symbols[(call.scope.qualname, call.var)] = fqn
            module.config_name_lookups[id(call)] = fqn
            ref = call.scope.bindings.get(call.var)
            if ref is not None and not ref.via_fqns:
                ref.via_fqns = (fqn,)
        return
    if target is None:
        return
    names = sorted({cls.name for cls in target.classes.values()
                    if cls.scope.parent is target.module_scope}
                   | {func.name for func in target.functions.values()
                      if not func.is_method and func.parent_function is None
                      and func.scope.parent is target.module_scope})
    if 2 <= len(names) <= MAX_ALTERNATIVES:
        module.config_alternatives[id(call)] = (prefix, tuple(names))


def _literal_here(expr, scope: ScopeIR) -> Optional[str]:
    """The literal an expression reads, using only bindings already in scope."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    name = dotted_text(expr) or path_name(expr)
    if not name:
        return None
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        ref = cur.bindings.get(name)
        if ref is not None:
            return ref.literal
        cur = cur.parent
    return None


def _resolve_factory(call, module: ModuleIR) -> None:
    """`factory(...)` where `factory` came out of a resolved `getattr`."""
    func = getattr(call.node, "func", None)
    if not isinstance(func, ast.Name):
        return
    cur: Optional[ScopeIR] = call.scope
    while cur is not None:
        fqn = module.config_symbols.get((cur.qualname, func.id))
        if fqn:
            module.config_call_fqn[id(call)] = fqn
            return
        cur = cur.parent


def _yaml_note(what: str) -> str:
    return ("MLView did not open %s: the YAML / Hydra half of config resolution "
            "is deferred, so any value that comes from it is unresolved rather "
            "than guessed. Python-side config - dict literals, dataclass field "
            "defaults and argparse defaults - is resolved." % what)


def _note_yaml(call, module: ModuleIR) -> None:
    """Record - never open - a YAML loader the workspace calls."""
    if (call.fqn or "") not in _YAML_FQNS:
        return
    module.config_yaml_notes.append(
        (call.loc.line, _yaml_note("the file `%s` reads" % call.fqn)))


def _note_yaml_paths(module: ModuleIR) -> None:
    """Every YAML path the module *names*, wherever it names it.

    A path is as likely to be a parameter default (`def load(path=
    "conf/config.yaml")`) or a module constant as a call argument, and the
    reader needs to be told the same thing in all three cases. This walks the
    module's string constants rather than its call arguments for exactly that
    reason - and reads nothing off disk, which is the whole point.
    """
    seen = set()
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if not text.lower().endswith(_YAML_SUFFIXES) or text in seen:
            continue
        seen.add(text)
        module.config_yaml_notes.append(
            (getattr(node, "lineno", 1) or 1, _yaml_note("`%s`" % text)))


def _note_hydra(module: ModuleIR) -> None:
    """`@hydra.main(...)` composes a config out of files this run did not read."""
    for qualname in sorted(module.functions):
        func = module.functions[qualname]
        for dec in func.decorators:
            if dec == "hydra.main" or dec.startswith("hydra."):
                module.config_yaml_notes.append((
                    func.loc.line,
                    "MLView did not compose the Hydra config for `%s()`: the "
                    "YAML / Hydra half of config resolution is deferred, so "
                    "`cfg` inside it is unresolved rather than guessed."
                    % func.name))
                break


# ---------------------------------------------------------------------------
# keyword arguments a container supplies
# ---------------------------------------------------------------------------
#: A container literal is not written into `kwargs`: `shuffle={...}` is not a
#: thing a rule can compare, and a 400-character dict in a node's `attrs` is
#: noise. Only scalars travel.
_CONTAINER_PREFIXES = ("{", "[", "(")
_MAX_KWARG_LITERAL = 40


def _apply_kwargs(call, module: ModuleIR) -> None:
    """Give `call.kwargs` the values a config container supplies.

    `CallSite.kwargs` is what a rule reads when it asks *"was `shuffle=True`
    passed here?"*, and it only ever held literals written at the call site. So
    `DataLoader(ds, shuffle=CFG["shuffle"])` on a config that says `True`
    produced MLV110 saying **"shuffle=unset (defaults to False)"** - a false
    statement about the program, at `likely`, on correct code. That is the one
    failure this product cannot afford, and it is fixed here rather than in
    eleven rules.

    Every key written is recorded, so the next round can take it back: a
    parameter that resolves optimistically in round 1 and is refused by the
    intersection in round 2 must not leave a value behind.
    """
    writes = getattr(module, "config_kwarg_writes", None)
    if writes is None:
        writes = module.config_kwarg_writes = []
    for key in sorted(call.kwarg_nodes):
        if key in call.kwargs:
            continue                     # written at the call site; it wins
        found = _config_leaf(call.kwarg_nodes[key], call.scope)
        if found is None:
            continue
        literal, read = found
        if literal.startswith(_CONTAINER_PREFIXES) or len(literal) > _MAX_KWARG_LITERAL:
            continue
        call.kwargs[key] = literal
        writes.append((call, key, read))


def _config_leaf(expr, scope: ScopeIR):
    """`(literal, ConfigRead)` when an expression reads a container leaf."""
    name = dotted_text(expr) or path_name(expr)
    if not name:
        return None
    cur = scope
    while cur is not None:
        ref = cur.bindings.get(name)
        if ref is not None:
            read = config_read_of(ref)
            if read is None or ref.literal is None:
                return None
            return ref.literal, read
        cur = cur.parent
    return None


def undo_kwargs(module: ModuleIR) -> None:
    """Take back every keyword this pass wrote in the previous round."""
    for call, key, _read in getattr(module, "config_kwarg_writes", None) or []:
        call.kwargs.pop(key, None)
    module.config_kwarg_writes = []


def kwarg_reads(module: ModuleIR):
    """`(file, line, ConfigRead)` for every keyword a container supplied."""
    out = []
    for call, _key, read in getattr(module, "config_kwarg_writes", None) or []:
        out.append((call.loc.file, call.loc.line, read))
    return out

