"""ANA-10: the vocabulary of a Python config, and the shapes it comes in.

`config_values` decides which *names* hold a container and what a read of one
costs; `config_calls` reads what call sites say about them. This module answers
the narrower question underneath both: **given an expression, what container is
it, and what does that container hold?**

Three shapes and nothing else, because each of them is a value written in
Python that a reader can point at:

* a **dict literal** - nested, and every key that is a constant;
* a **dataclass** - its field defaults, nested through
  `field(default_factory=<another workspace dataclass>)`, with literal
  constructor keywords replacing the defaults they override;
* **argparse** - `add_argument(..., default=...)` keyed by `dest`, exactly the
  way argparse itself derives one.

Everything else resolves to nothing, on purpose. `field(default_factory=lambda:
...)` is the construct ANA-5a already calls unresolvable, and this pass must not
contradict it; a key that is not a constant is a key nobody can read statically;
and no branch here opens a file.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .. import knowledge as K
from .model import ModuleIR, ScopeIR
from .scopes import literal_str
from .symbols import dotted_text

__all__ = [
    "CONFIG_NAME_RE", "CONFIG_EVIDENCE_WEIGHT", "MAX_CONFIG_HOPS",
    "MAX_CONFIG_LEAVES", "MAX_CONFIG_DEPTH", "MAX_PATH_DEPTH",
    "MAX_ALTERNATIVES", "Tree", "ConfigRead", "Root", "read_for",
    "config_read_of", "path_name", "const_key", "tree_digest", "tree_of",
    "argparse_tree", "workspace_class", "root_for_expr", "record_tree",
    "default_digest",
]


#: The names a config container may be bound to. This is the regex
#: `ir.bindings` has always used to recognise a config-shaped name; it lives
#: here now and `bindings` imports it, so the two can never drift. It is also
#: the whole blast radius of this pass: a dict literal called `WEIGHTS` is not
#: a config and is not touched.
CONFIG_NAME_RE = re.compile(
    r"(?i)^(cfg|config|args|opts|options|hparams|params|settings)$")

#: The doubt a config read costs, applied **once** for the read itself and once
#: more per interprocedural hop. Stated as one constant so "how much does
#: reading a config value cost" has exactly one answer:
#:
#:     MLV112 base 0.98   0 hops -> 0.784 likely
#:                        1 hop  -> 0.627 possible
#:                        2 hops -> 0.502 possible
#:
#: The number is the same 0.8 `ir.provenance.IP_HOP_WEIGHT` uses, and for the
#: same reason: one step of doubt should cost one bucket, not three.
CONFIG_EVIDENCE_WEIGHT = 0.8

#: How many argument -> parameter hops a config container may travel. Two is
#: `CFG -> train(cfg=CFG) -> optimizer_for(model, cfg)`, which is the shape the
#: ANA-12 Hydra program has; deeper than that and the intersection over call
#: sites stops being something a reader can check by eye.
MAX_CONFIG_HOPS = 2

#: Per-root caps. A generated config with ten thousand keys must cost a bounded
#: amount of memory and produce a bounded number of bindings.
MAX_CONFIG_LEAVES = 256
MAX_CONFIG_DEPTH = 5
#: How many `.` / `[...]` steps a *read* may have. Deeper reads are left alone.
MAX_PATH_DEPTH = 6
#: How many symbols a one-of-N alternatives node may name. Past this the set
#: stops being a statement a reader can check and the node stays `unknown`.
MAX_ALTERNATIVES = 12

#: Extensions that mean "a config file this analyzer will not open".
_YAML_SUFFIXES = (".yaml", ".yml")
#: Call FQNs that mean the same thing.
_YAML_FQNS = ("yaml.safe_load", "yaml.load", "yaml.full_load",
              "omegaconf.OmegaConf.load", "omegaconf.OmegaConf.merge")

_STORE_ACTIONS = {"store_true": "False", "store_false": "True"}
_OPTION_RE = re.compile(r"^-{1,2}([A-Za-z0-9][A-Za-z0-9_-]*)$")

#: A resolved container: `path tuple -> stringified literal`. The empty path is
#: the container's own literal, when it has one.
Tree = Dict[Tuple[str, ...], str]

# ---------------------------------------------------------------------------
# what a read costs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ConfigRead:
    """Why a config-resolved literal is trustworthy only up to a point.

    Attached to the synthesized leaf `ValueRef` as `ref.config_read`, read back
    by `rules.helpers.literal_of`, and rendered into one `context_confirmed`
    evidence row on any finding that used it.
    """

    weight: float
    detail: str
    file: str
    line: int
    hops: int


def read_for(path: Tuple[str, ...], literal: str, origin: str, file: str,
              line: int, hops: int) -> ConfigRead:
    weight = CONFIG_EVIDENCE_WEIGHT
    for _ in range(max(0, hops)):
        weight *= CONFIG_EVIDENCE_WEIGHT
    detail = ("`%s` was read as `%s` from %s at %s:%d; a value resolved out of "
              "a config container is de-rated x%s%s, because a container can be "
              "overridden at run time by something no static reader can see"
              % (".".join(path), literal, origin, file, line,
                 round(CONFIG_EVIDENCE_WEIGHT, 3),
                 "" if hops <= 0 else " once for the read and once per hop (%d)" % hops))
    return ConfigRead(weight=round(weight, 4), detail=detail, file=file,
                      line=line, hops=hops)


def config_read_of(ref) -> Optional[ConfigRead]:
    """The `ConfigRead` behind a value, or None when it is an ordinary one."""
    read = getattr(ref, "config_read", None)
    return read if isinstance(read, ConfigRead) else None

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def const_key(node: Optional[ast.AST]) -> Optional[str]:
    """`["workers"]` / `[0]` -> `workers` / `0`; anything else -> None."""
    if isinstance(node, ast.Index):                     # pragma: no cover - <3.9
        node = node.value                               # type: ignore[attr-defined]
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value and "." not in value:
        return value
    return None


def path_name(expr: Optional[ast.AST]) -> Optional[str]:
    """The dotted name a mixed attribute / subscript chain reads.

    `CFG["workers"]` and `cfg.data["workers"]` both become dotted names rooted
    at the container, so one binding answers both spellings and `literal_of`
    needs no second lookup table. Returns None for a bare name (`dotted_text`
    already answers those), for a non-constant key, and for anything deeper
    than `MAX_PATH_DEPTH`.
    """
    parts: List[str] = []
    node: Optional[ast.AST] = expr
    for _step in range(MAX_PATH_DEPTH + 1):
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Subscript):
            key = const_key(node.slice)
            if key is None:
                return None
            parts.append(key)
            node = node.value
        elif isinstance(node, ast.Name):
            parts.append(node.id)
            parts.reverse()
            return ".".join(parts) if len(parts) > 1 else None
        else:
            return None
    return None

# ---------------------------------------------------------------------------
# trees
# ---------------------------------------------------------------------------
def tree_digest(tree: Tree) -> Tuple[Tuple[Tuple[str, ...], str], ...]:
    """A hashable, order-independent identity for a resolved container."""
    return tuple(sorted(tree.items()))


def merge(into: Tree, prefix: Tuple[str, ...], sub: Tree) -> None:
    for path in sorted(sub):
        if len(into) >= MAX_CONFIG_LEAVES:
            return
        into[prefix + path] = sub[path]


def workspace_class(module: ModuleIR, workspace, node: Optional[ast.AST]):
    """The workspace `ClassIR` a name refers to, or None."""
    if node is None or workspace is None:
        return None
    symbols = getattr(module, "symbols", None)
    fqn = symbols.resolve(node) if symbols is not None else None
    if fqn:
        cls = workspace.classes.get(fqn)
        if cls is None:
            target = (getattr(workspace, "reexports", None) or {}).get(fqn)
            cls = workspace.classes.get(target) if target else None
        if cls is not None:
            return cls
    name = node.id if isinstance(node, ast.Name) else None
    if not name:
        return None
    for qualname in sorted(module.classes):
        cls = module.classes[qualname]
        if cls.name == name and cls.scope.parent is module.module_scope:
            return cls
    return None


def _is_dataclass(cls) -> bool:
    node = getattr(cls, "node", None)
    for dec in getattr(node, "decorator_list", ()) or ():
        target = dec.func if isinstance(dec, ast.Call) else dec
        text = dotted_text(target) or ""
        if text.split(".")[-1] == "dataclass":
            return True
    return False


def _field_default(node: ast.Call) -> Optional[ast.expr]:
    """`field(default=3)` -> the `3`; `field(default_factory=Cls)` -> the `Cls`.

    `field(default_factory=<lambda>)` and `field(default_factory=list)` return
    the lambda / the builtin, which `tree_of` then declines - which is the
    point: ANA-5a already calls a `default_factory` an unresolvable construct
    and this pass must not contradict it.
    """
    found = None
    for key in ("default", "default_factory"):
        for kw in node.keywords:
            if kw.arg == key:
                found = kw.value
    return found


def tree_of(value: Optional[ast.AST], module: ModuleIR, workspace,
             depth: int = 0, seen: Tuple[str, ...] = ()) -> Optional[Tree]:
    """The resolved container (or scalar, at the empty path) an expression names."""
    if value is None or depth > MAX_CONFIG_DEPTH:
        return None
    if isinstance(value, ast.Dict):
        out: Tree = {}
        whole = literal_str(value)
        if whole is not None:
            out[()] = whole
        for key_node, val_node in zip(value.keys, value.values):
            key = const_key(key_node)
            if key is None:
                continue
            sub = tree_of(val_node, module, workspace, depth + 1, seen)
            if sub:
                merge(out, (key,), sub)
        return out or None
    if isinstance(value, ast.Call):
        cls = workspace_class(module, workspace, value.func)
        if cls is not None and _is_dataclass(cls):
            return _dataclass_tree(cls, module, workspace, depth, seen, ctor=value)
        return None
    if isinstance(value, ast.Name):
        cls = workspace_class(module, workspace, value)
        if cls is not None and _is_dataclass(cls):
            return _dataclass_tree(cls, module, workspace, depth, seen)
        return None
    literal = literal_str(value)
    return {(): literal} if literal is not None else None


def _dataclass_tree(cls, module: ModuleIR, workspace, depth: int,
                    seen: Tuple[str, ...], ctor: Optional[ast.Call] = None
                    ) -> Optional[Tree]:
    """A dataclass's field defaults, with literal constructor keywords on top."""
    if cls.qualname in seen or depth > MAX_CONFIG_DEPTH:
        return None
    seen = seen + (cls.qualname,)
    owner = cls.module if cls.module is not None else module
    out: Tree = {}
    for stmt in getattr(cls.node, "body", ()) or ():
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name, value = stmt.target.id, stmt.value
        elif (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
              and isinstance(stmt.targets[0], ast.Name)):
            name, value = stmt.targets[0].id, stmt.value
        else:
            continue
        if name.startswith("_") or value is None:
            continue
        if isinstance(value, ast.Call) \
                and (dotted_text(value.func) or "").split(".")[-1] == "field":
            value = _field_default(value)
        sub = tree_of(value, owner, workspace, depth + 1, seen)
        if sub:
            merge(out, (name,), sub)
    for kw in (ctor.keywords if ctor is not None else ()):
        if not kw.arg:
            continue
        sub = tree_of(kw.value, module, workspace, depth + 1, seen)
        if not sub:
            continue
        # a literal constructor keyword *replaces* the field default, including
        # every nested path under it - `Cfg(data=DataCfg(workers=8))` must not
        # leave the declared `workers` behind next to the one that won.
        for path in [p for p in sorted(out) if p[:1] == (kw.arg,)]:
            del out[path]
        merge(out, (kw.arg,), sub)
    return out or None


def argparse_tree(module: ModuleIR) -> Optional[Tree]:
    """Every `add_argument(default=...)` in the module, keyed by `dest`.

    Deliberately module-wide rather than per-parser: a module with **two**
    `ArgumentParser()` constructions is refused outright rather than guessed
    at, because the two namespaces would be indistinguishable here.
    """
    parsers = 0
    adds: List[Any] = []
    for call in module.calls:
        role = K.role_of(call.fqn)
        if role == "ARGPARSE":
            parsers += 1
        elif role == "CONFIG_ARG":
            adds.append(call)
    if parsers > 1 or not adds:
        return None
    out: Tree = {}
    for call in adds:
        dest = const_key(call.kwarg_nodes.get("dest"))
        if dest is None:
            for arg in call.args:
                text = const_key(arg)
                if text is None:
                    continue
                match = _OPTION_RE.match(text)
                if match:
                    dest = match.group(1).replace("-", "_")
                    break
                if not text.startswith("-"):
                    dest = text.replace("-", "_")
                    break
        if not dest:
            continue
        node = call.kwarg_nodes.get("default")
        literal = literal_str(node) if node is not None else None
        if literal is None:
            literal = _STORE_ACTIONS.get(call.kwargs.get("action") or "")
        if literal is not None:
            out[(dest,)] = literal
    return out or None

# ---------------------------------------------------------------------------
# roots
# ---------------------------------------------------------------------------
class Root(object):
    """One resolved config container, bound to a name in one scope."""

    __slots__ = ("name", "scope", "ref", "tree", "origin", "file", "line",
                 "hops", "source")

    def __init__(self, name, scope, ref, tree, origin, file, line, hops, source):
        self.name = name
        self.scope = scope
        self.ref = ref          # the ValueRef the name is bound to here
        self.tree = tree
        self.origin = origin    # words: "the dict literal `CFG`"
        self.file = file
        self.line = line
        self.hops = hops
        #: A **stable key** for the container's own binding -
        #: `(relpath, scope qualname, name)` - never a `ValueRef`. `bind_module`
        #: clears and rebuilds every `ValueRef` on every round, so an object
        #: stored here in round 2 is a corpse in round 3; the workspace-level
        #: tables outlive a round and must therefore hold names, not objects.
        self.source = source


def default_digest(module: ModuleIR, workspace, func, param, roots):
    """`def train(cfg=CFG)` - the container the declared default names.

    Only for a function defined in *this* module: the default expression is
    written in the callee's own namespace, and reading it against a caller's
    roots would be resolving a name in the wrong file.
    """
    if func.module is not module:
        return None
    args = getattr(getattr(func, "node", None), "args", None)
    if args is None:
        return None
    names = [a.arg for a in list(getattr(args, "posonlyargs", []) or []) + list(args.args)]
    defaults = list(args.defaults)
    pairs = list(zip(names[len(names) - len(defaults):], defaults)) if defaults else []
    pairs += [(a.arg, d) for a, d in zip(args.kwonlyargs, args.kw_defaults)
              if d is not None]
    for name, default in pairs:
        if name != param:
            continue
        root = root_for_expr(default, func.scope, roots)
        if root is not None:
            return record_tree(workspace, root)
        tree = tree_of(default, module, workspace)
        if tree:
            return record_tree(workspace, Root(
                name=param, scope=func.scope, ref=None, tree=tree,
                origin="the declared default of `%s`" % param,
                file=func.loc.file, line=func.loc.line, hops=0, source=None))
    return None


def root_for_expr(expr, scope: ScopeIR, roots) -> Optional[Root]:
    """The root a plain name refers to, walking the scope chain outwards."""
    name = dotted_text(expr)
    if not name or "." in name:
        return None
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        root = roots.get((cur.qualname, name))
        if root is not None:
            return root
        cur = cur.parent
    return None


def record_tree(workspace, root: Root):
    """Publish a container under its digest so a parameter can adopt it."""
    digest = tree_digest(root.tree)
    workspace.config_trees[digest] = (root.tree, root.origin, root.file,
                                      root.line, root.hops)
    if root.source is not None:
        workspace.config_tree_sources[digest] = root.source
    return digest

