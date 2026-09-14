"""Model-definition rules: MLV701 (`super().__init__()`), MLV702 (plain container).

Both are purely syntactic and both are silent killers: PyTorch raises a
confusing `AttributeError` for the first and simply *ignores* the submodules
for the second, so training appears to work while most of the network never
learns.
"""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional

from ..core.graph import Issue
from ..ir.model import ClassIR, FunctionIR, ModuleIR
from ..ir.symbols import dotted_text
from .registry import rule

__all__ = ["missing_super_init", "unregistered_submodules"]

#: Bases whose subclasses must chain to `super().__init__()`.
#:
#: vision-13: `LightningDataModule` was missing, although the rule already
#: declared `lightning` in its frameworks list. `LightningDataModule.__init__`
#: installs the hook bookkeeping Lightning needs - skipping it makes
#: `save_hyperparameters()` raise and the trainer's dataloader wiring
#: misbehave, which is the same always-a-bug, purely syntactic defect that
#: earned this rule its high severity and 0.97 prior.
_MODULE_BASES = (
    "torch.nn.Module",
    "pytorch_lightning.LightningModule",
    "lightning.LightningModule",
    "lightning.pytorch.LightningModule",
    "pytorch_lightning.LightningDataModule",
    "lightning.LightningDataModule",
    "lightning.pytorch.LightningDataModule",
)

#: Containers that *do* register their contents.
_REGISTERING = ("torch.nn.ModuleList", "torch.nn.ModuleDict", "torch.nn.Sequential",
                "torch.nn.ParameterList", "torch.nn.ParameterDict")


def _module_classes(ctx) -> List[ClassIR]:
    out: List[ClassIR] = []
    for relpath in sorted(ctx.modules):
        for qualname in sorted(ctx.modules[relpath].classes):
            cls = ctx.modules[relpath].classes[qualname]
            if any(b in _MODULE_BASES for b in cls.resolved_bases):
                out.append(cls)
    return out


def _first_base(cls: ClassIR) -> str:
    for base in cls.resolved_bases:
        if base in _MODULE_BASES:
            return base
    return "torch.nn.Module"


def _is_module_call(call) -> bool:
    for fqn in call.canonical_fqns or ():
        if fqn.startswith("torch.nn.") and not fqn.startswith("torch.nn.functional."):
            return True
    return bool(call.class_ir is not None and call.class_ir.is_nn_module)


def _stmt_loc(module: ModuleIR, stmt: ast.stmt):
    from ..core.views import parsed_view
    from ..ir.locs import loc_of
    return loc_of(parsed_view(module), stmt)


# ---------------------------------------------------------------------------
# MLV701
# ---------------------------------------------------------------------------
@rule(code="MLV701", severity="high", base_prior=0.97, frameworks=["torch", "lightning"],
      rule_version=1, tags=["correctness", "model"],
      title="nn.Module.__init__ never calls super().__init__()",
      why="Without the base initialiser the module has no parameter registry, so "
          "assigning a layer raises AttributeError or drops it from .parameters() and "
          "the optimizer never updates those weights.",
      fix_hint="Add super().__init__() as the first statement of __init__, before any "
               "self.<layer> = nn.Module(...) assignment.")
def missing_super_init(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for cls in _module_classes(ctx):
        init = cls.methods.get("__init__")
        if init is None:
            continue
        if _calls_super_init(init, cls):
            continue
        if _is_abstract(cls):
            continue
        node = ctx.builder.scope_unit.get(cls.scope.qualname)
        if node is None:
            continue
        base = (cls.bases[0] if cls.bases else "nn.Module").split(".")[-1]
        layers = _layer_assignments(init)
        evidence = [
            ("class_base", "%s resolves to %s" % (cls.name, _first_base(cls)), 1.0),
            ("negation_absent",
             "no super().__init__() and no %s.__init__(self, ...) in the body" % base, 1.0),
        ]
        if not cls.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % cls.scope.qualname, 1.0))
        if layers:
            evidence.append(("dataflow_direct",
                             "%d submodule assignment(s) would be unregistered: %s"
                             % (len(layers), ", ".join(layers[:3])), 1.0))
        issues.append(ctx.issue(
            message="%s.__init__ (line %d) never calls super().__init__(), so the "
                    "parameter and module registries inherited from %s are never built."
                    % (cls.name, init.loc.line, _first_base(cls)),
            loc=init.loc, node_ids=[node],
            related=[("definition", cls.loc, "class %s(%s)" % (cls.name, base))],
            evidence=evidence, dynamic=cls.scope.is_dynamic))
    return issues


def _calls_super_init(init: FunctionIR, cls: ClassIR) -> bool:
    """`super().__init__()` or `Base.__init__(self, ...)` anywhere in the body."""
    base_names = {b.split(".")[-1] for b in cls.bases}
    base_names.update(b.split(".")[-1] for b in cls.resolved_bases)
    for child in ast.walk(init.node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not isinstance(func, ast.Attribute) or func.attr != "__init__":
            continue
        inner = func.value
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                and inner.func.id == "super":
            return True
        text = dotted_text(inner) or ""
        if text and text.split(".")[-1] in base_names:
            return True
    return False


def _is_abstract(cls: ClassIR) -> bool:
    """An abstract intermediate base is never instantiated, so it cannot fail."""
    for method in cls.methods.values():
        for dec in method.decorators:
            if dec.split(".")[-1] in ("abstractmethod", "abstractproperty"):
                return True
    for base in cls.bases:
        if base.split(".")[-1] in ("ABC", "ABCMeta", "Protocol"):
            return True
    return False


def _layer_assignments(init: FunctionIR) -> List[str]:
    """`self.fc = nn.Linear(...)` names inside `__init__`."""
    out: List[str] = []
    by_node = getattr(init.module, "_calls_by_node", {})
    for stmt in ast.walk(init.node):
        if not isinstance(stmt, ast.Assign) or not isinstance(stmt.value, ast.Call):
            continue
        call = by_node.get(id(stmt.value))
        if call is None or not _is_module_call(call):
            continue
        for target in stmt.targets:
            name = dotted_text(target)
            if name and name.startswith("self.") and name not in out:
                out.append(name)
    return out


# ---------------------------------------------------------------------------
# MLV702
# ---------------------------------------------------------------------------
@rule(code="MLV702", severity="high", base_prior=0.95, frameworks=["torch"],
      rule_version=1, tags=["correctness", "model"],
      title="Submodules held in a plain list are never registered",
      why="A plain list is invisible to nn.Module, so those layers never appear in "
          "parameters(), the optimizer never updates them and .to(device) leaves them "
          "behind - the network trains with most of itself frozen.",
      fix_hint="Wrap the container in nn.ModuleList([...]) or nn.ModuleDict({...}) so "
               "the submodules are registered as children.")
def unregistered_submodules(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for cls in _module_classes(ctx):
        init = cls.methods.get("__init__")
        if init is None:
            continue
        module = cls.module
        by_node = getattr(module, "_calls_by_node", {})
        for stmt in _assign_statements(init.node):
            container = _container_kind(stmt.value)
            if container is None:
                continue
            name = _self_target(stmt)
            if name is None:
                continue
            elements = _submodule_elements(stmt.value, by_node)
            if not elements:
                continue
            if _later_wrapped(init, by_node, name):
                continue
            node = ctx.builder.scope_unit.get(cls.scope.qualname)
            if node is None:
                continue
            first = elements[0]
            evidence = [
                ("class_base", "%s resolves to torch.nn.Module" % cls.name, 1.0),
                ("fqn_resolved", "%s resolves to %s"
                 % (first.short_name, first.fqn or "an nn.Module subclass"), 1.0),
                ("negation_absent",
                 "the %s is not wrapped in nn.ModuleList / nn.ModuleDict / nn.Sequential"
                 % container, 1.0),
            ]
            if not cls.scope.is_dynamic:
                evidence.append(("scope_static",
                                 "no dynamic constructs in %s" % cls.scope.qualname, 1.0))
            loc = _stmt_loc(module, stmt)
            issues.append(ctx.issue(
                message=_container_message(name, container, elements, first, cls),
                loc=loc or first.loc, node_ids=[node],
                related=[("construction", first.loc,
                          "%s built here" % (first.fqn or first.short_name)),
                         ("definition", cls.loc, "class %s" % cls.name)],
                evidence=evidence, dynamic=cls.scope.is_dynamic))
    return issues


def _container_message(name: str, container: str, elements, first, cls) -> str:
    """A comprehension holds one *expression*, not one submodule - say so.

    `self.blocks = [ConvBlock(w, w) for _ in range(depth)]` builds `depth`
    blocks; counting the element expressions and reporting "1 submodule(s)"
    reads as an obviously wrong count and undercuts the finding.
    """
    if container.endswith("comprehension"):
        return ("%s is a plain %s of %s (line %d), so none of the submodules it "
                "builds is registered on %s."
                % (name, container, first.fqn or first.short_name,
                   first.loc.line, cls.name))
    return ("%s is a plain %s holding %d submodule(s) (%s at line %d), so none of "
            "them is registered on %s."
            % (name, container, len(elements), first.fqn or first.short_name,
               first.loc.line, cls.name))


def _assign_statements(func_node: ast.AST) -> List[ast.stmt]:
    return [n for n in ast.walk(func_node)
            if isinstance(n, (ast.Assign, ast.AnnAssign))
            and getattr(n, "value", None) is not None]


def _self_target(stmt) -> Optional[str]:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    for target in targets:
        name = dotted_text(target)
        if name and name.startswith("self."):
            return name
    return None


def _container_kind(value: ast.expr) -> Optional[str]:
    if isinstance(value, ast.List):
        return "list"
    if isinstance(value, ast.Tuple):
        return "tuple"
    if isinstance(value, ast.Dict):
        return "dict"
    if isinstance(value, ast.ListComp):
        return "list comprehension"
    if isinstance(value, ast.DictComp):
        return "dict comprehension"
    return None


def _element_exprs(value: ast.expr) -> List[ast.expr]:
    if isinstance(value, (ast.List, ast.Tuple)):
        return list(value.elts)
    if isinstance(value, ast.Dict):
        return [v for v in value.values if v is not None]
    if isinstance(value, ast.ListComp):
        return [value.elt]
    if isinstance(value, ast.DictComp):
        return [value.value]
    return []


def _submodule_elements(value: ast.expr, by_node) -> List:
    """The element call sites that build an nn.Module - the whole check."""
    out = []
    for expr in _element_exprs(value):
        if not isinstance(expr, ast.Call):
            continue
        call = by_node.get(id(expr))
        if call is not None and _is_module_call(call):
            out.append(call)
    return out


def _later_wrapped(init: FunctionIR, by_node, name: str) -> bool:
    """`self.blocks = [...]` followed by `nn.Sequential(*self.blocks)` is fine."""
    short = name.split(".")[-1]
    for child in ast.walk(init.node):
        if not isinstance(child, ast.Call):
            continue
        call = by_node.get(id(child))
        if call is None:
            continue
        if not any(f in _REGISTERING for f in call.canonical_fqns or ()):
            continue
        for arg in list(child.args) + [kw.value for kw in child.keywords]:
            target = arg.value if isinstance(arg, ast.Starred) else arg
            text = dotted_text(target) or ""
            if text == name or text.split(".")[-1] == short:
                return True
    return False
