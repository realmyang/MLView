"""Objective-pairing rules: MLV401 (softmax before CE), MLV402 (sigmoid/BCE)."""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Tuple

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, ClassIR, ValueRef
from ..ir.symbols import dotted_text
from .helpers import arg_ref
from .registry import rule

__all__ = ["softmax_before_cross_entropy", "sigmoid_bce_mismatch"]

_CE_FQNS = ("torch.nn.CrossEntropyLoss.__call__", "torch.nn.functional.cross_entropy")
_SOFTMAX_ROLES = ("SOFTMAX", "LOG_SOFTMAX")


@rule(code="MLV401", severity="high", base_prior=0.95, frameworks=["torch"],
      rule_version=1, tags=["correctness", "objective"],
      title="Softmax applied before CrossEntropyLoss",
      why="CrossEntropyLoss applies log-softmax internally, so a second softmax "
          "flattens the gradients and the model trains far worse than it should.",
      fix_hint="Return raw logits from forward() and apply softmax only where you need "
               "probabilities for reporting.")
def softmax_before_cross_entropy(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for loss_call in _cross_entropy_calls(ctx):
        name, ref = arg_ref(ctx, loss_call, 0)
        softmax_call, model_cls, source = _trace(ctx, loss_call, ref)
        if softmax_call is None:
            continue
        loss_node = ctx.node_for_call(loss_call) or ctx.unit_for_call(loss_call)
        if loss_node is None:
            continue
        model_node = None
        if model_cls is not None:
            model_node = ctx.builder.scope_unit.get(model_cls.scope.qualname)
        elif ref is not None:
            model_node = ctx.builder._producer_node(ref)
        edge = ctx.edge_between(model_node, loss_node, "data")
        nodes = [loss_node] + ([model_node] if model_node is not None
                               and model_node is not loss_node else [])
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (loss_call.fqn or "cross_entropy"), 1.0),
            ("dataflow_direct", "%s reaches the loss input" % (name or "the model output"), 1.0),
            ("cross_file", "model defined in %s" % softmax_call.loc.file,
             1.0 if softmax_call.loc.file == loss_call.loc.file else 0.9),
        ]
        if source == "conditional":
            evidence.append(("context_confirmed", "softmax sits inside a conditional", 0.6))
        related = [("final_layer", softmax_call.loc,
                    "%s applied here" % (softmax_call.fqn or softmax_call.short_name))]
        if model_cls is not None:
            related.append(("definition", model_cls.loc,
                            "model class %s" % model_cls.name))
        issues.append(ctx.issue(
            message="The value passed to %s at %s:%d comes from %s at %s:%d, so the "
                    "probabilities are log-softmaxed twice."
                    % (_label(loss_call), loss_call.loc.file, loss_call.loc.line,
                       softmax_call.fqn or softmax_call.short_name,
                       softmax_call.loc.file, softmax_call.loc.line),
            loc=loss_call.loc, node_ids=nodes,
            edge_ids=[edge] if edge is not None else (),
            related=related, evidence=evidence,
            dynamic=loss_call.scope.is_dynamic))
    return issues


def _label(call: CallSite) -> str:
    if call.receiver_name:
        return "%s()" % call.receiver_name
    return "%s()" % call.short_name


def _cross_entropy_calls(ctx) -> List[CallSite]:
    out = list(ctx.calls_of(*_CE_FQNS))
    for call in ctx.calls_with_role("LOSS_CLS", "LOSS_FN"):
        fqn = call.fqn or ""
        if fqn.endswith("CrossEntropyLoss.__call__") and call not in out:
            out.append(call)
    return out


def _trace(ctx, loss_call: CallSite, ref: Optional[ValueRef]):
    """Find the softmax that produced the loss input, if any.

    Three shapes reach the same answer: an inline `F.softmax(...)` argument, a
    named binding whose producer chain ends in one, and - the shape a bare
    `net = nn.Sequential(..., nn.Softmax(dim=1))` takes - a forward call whose
    receiver was built by a Sequential ending in a softmax.
    """
    producer: Optional[CallSite] = None
    if loss_call.args and isinstance(loss_call.args[0], ast.Call):
        producer = _call_site_for(ctx, loss_call.module, loss_call.args[0])
    current = ref
    for _hop in range(6):
        if producer is None:
            if current is None:
                break
            producer = current.producer
            if producer is None:
                break
        if _is_softmax(producer):
            return producer, None, "direct"
        tail = _sequential_tail_softmax(ctx, producer)
        if tail is not None:
            return tail, None, "direct"
        model_ref = producer.receiver
        cls = model_ref.class_ir if model_ref is not None else producer.class_ir
        if cls is not None and cls.is_nn_module:
            found, source = _forward_softmax(ctx, cls)
            if found is not None:
                return found, cls, source
            break
        if model_ref is None:
            break
        current = model_ref
        producer = None
    return None, None, ""


def _call_site_for(ctx, module, node: ast.Call) -> Optional[CallSite]:
    for call in module.calls:
        if call.node is node:
            return call
    return None


def _is_softmax(call: CallSite) -> bool:
    for fqn in call.canonical_fqns or ():
        if K.role_of(fqn) in _SOFTMAX_ROLES:
            return True
    return False


def _forward_softmax(ctx, cls: ClassIR) -> Tuple[Optional[CallSite], str]:
    """Does `forward` end in a softmax / log_softmax?"""
    forward = cls.methods.get("forward")
    if forward is None:
        return None, ""
    for expr in forward.returns:
        call = None
        if isinstance(expr, ast.Call):
            call = _call_site_for(ctx, cls.module, expr)
        else:
            name = dotted_text(expr)
            ref = ctx.binding_of(name, forward.scope) if name else None
            if ref is not None:
                call = ref.producer
        if call is None:
            continue
        if _is_softmax(call):
            inside_if = _inside_conditional(forward.node, expr)
            return call, "conditional" if inside_if else "direct"
        module_call = _module_softmax(ctx, cls, call)
        if module_call is not None:
            return module_call, "direct"
    return None, ""


def _module_softmax(ctx, cls: ClassIR, call: CallSite) -> Optional[CallSite]:
    """`return self.head(x)` where `self.head` ends in nn.Softmax."""
    return _sequential_tail_softmax(ctx, call)


def _sequential_tail_softmax(ctx, call: CallSite) -> Optional[CallSite]:
    """The softmax behind `<binding>(x)` when the binding is a Sequential.

    Covers both `self.head = nn.Sequential(..., nn.Softmax(dim=1))` inside an
    nn.Module subclass and the bare `net = nn.Sequential(..., nn.Softmax(dim=1))`
    binding - ISSUE_RULES MLV401 names the second one explicitly ("or whose
    final nn.Sequential element is one of those") and it is the shortest way to
    write a small classifier.
    """
    producer = _attribute_producer(ctx, call)
    if producer is None:
        return None
    if K.role_of(producer.fqn) in _SOFTMAX_ROLES:
        return producer
    last = _sequential_last(producer)
    if last is None:
        return None
    inner = _call_site_for(ctx, producer.module, last)
    return inner if inner is not None and _is_softmax(inner) else None


def _sequential_last(producer: CallSite) -> Optional[ast.Call]:
    """The final positional element of an `nn.Sequential(...)` construction."""
    if not (producer.fqn or "").endswith("nn.Sequential") or not producer.args:
        return None
    last = producer.args[-1]
    return last if isinstance(last, ast.Call) else None


def _inside_conditional(func_node: ast.AST, expr: ast.expr) -> bool:
    for node in ast.walk(func_node):
        if isinstance(node, ast.If):
            for child in ast.walk(node):
                if child is expr:
                    return True
    return False


# ---------------------------------------------------------------------------
# MLV402
# ---------------------------------------------------------------------------
_LOGIT_LOSSES = ("torch.nn.BCEWithLogitsLoss.__call__",
                 "torch.nn.functional.binary_cross_entropy_with_logits")
_PROB_LOSSES = ("torch.nn.BCELoss.__call__",
                "torch.nn.functional.binary_cross_entropy")
#: Roles whose output is definitely *not* squashed into [0, 1].
_LOGIT_ROLES = ("LAYER", "NORM", "NORM_TRAIN_SENSITIVE", "CONTAINER", "DROPOUT")


@rule(code="MLV402", severity="high", base_prior=0.95, frameworks=["torch"],
      rule_version=1, tags=["correctness", "objective"],
      title="Sigmoid and BCE loss are paired inconsistently",
      why="BCEWithLogitsLoss applies the sigmoid itself, so a second one saturates the "
          "gradient; BCELoss without one is fed unbounded logits and returns NaN as soon "
          "as a value leaves [0, 1].",
      fix_hint="Feed raw logits to BCEWithLogitsLoss and drop the trailing nn.Sigmoid(), "
               "or feed sigmoid outputs to BCELoss - never the mismatched pairing.")
def sigmoid_bce_mismatch(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for loss_call, variant in _bce_calls(ctx):
        name, ref = arg_ref(ctx, loss_call, 0)
        final, cls, resolved = _final_producer(ctx, loss_call, ref)
        if not resolved or final is None:
            continue
        is_sigmoid = _role_of(final) == "SIGMOID"
        if variant == "double_sigmoid" and not is_sigmoid:
            continue
        if variant == "missing_sigmoid" and is_sigmoid:
            continue
        loss_node = ctx.node_for_call(loss_call) or ctx.unit_for_call(loss_call)
        if loss_node is None:
            continue
        model_node = None
        if cls is not None:
            model_node = ctx.builder.scope_unit.get(cls.scope.qualname)
        elif ref is not None:
            model_node = ctx.builder._producer_node(ref)
        edge = ctx.edge_between(model_node, loss_node, "data")
        nodes = [loss_node] + ([model_node] if model_node is not None
                               and model_node is not loss_node else [])
        final_name = final.fqn or final.short_name
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (loss_call.fqn or "the loss"), 1.0),
            ("dataflow_direct", "%s reaches the loss input" % (name or "the model output"),
             1.0),
            ("context_confirmed",
             "the producing chain ends in %s at %s:%d"
             % (final_name, final.loc.file, final.loc.line), 1.0),
        ]
        if cls is not None:
            evidence.append(("class_base",
                             "%s is an nn.Module whose forward() was resolved" % cls.name,
                             1.0))
        related = [("final_layer", final.loc, "%s is the last operation" % final_name)]
        if cls is not None:
            related.append(("definition", cls.loc, "model class %s" % cls.name))
        if variant == "double_sigmoid":
            message = ("%s at %s:%d is a logits loss, but its input comes from %s at "
                       "%s:%d - the sigmoid is applied twice."
                       % (_label(loss_call), loss_call.loc.file, loss_call.loc.line,
                          final_name, final.loc.file, final.loc.line))
        else:
            message = ("%s at %s:%d expects probabilities, but its input comes from %s at "
                       "%s:%d, which returns unbounded logits."
                       % (_label(loss_call), loss_call.loc.file, loss_call.loc.line,
                          final_name, final.loc.file, final.loc.line))
        issues.append(ctx.issue(
            message=message, loc=loss_call.loc, node_ids=nodes,
            edge_ids=[edge] if edge is not None else (),
            related=related, evidence=evidence,
            tags=("correctness", "objective", variant),
            dynamic=loss_call.scope.is_dynamic))
    return issues


def _bce_calls(ctx) -> List[Tuple[CallSite, str]]:
    """Every BCE loss evaluation, tagged with which half of the check applies."""
    out: List[Tuple[CallSite, str]] = []
    for call in ctx.calls_of(*_PROB_LOSSES):
        out.append((call, "missing_sigmoid"))
    for call in ctx.calls_of(*_LOGIT_LOSSES):
        out.append((call, "double_sigmoid"))
    seen = []
    unique: List[Tuple[CallSite, str]] = []
    for call, variant in out:
        if id(call) in seen:
            continue
        seen.append(id(call))
        unique.append((call, variant))
    unique.sort(key=lambda p: (p[0].loc.file, p[0].loc.line, p[0].loc.col))
    return unique


def _role_of(call: Optional[CallSite]) -> Optional[str]:
    if call is None:
        return None
    entry, _fqn = K.best_entry(call.canonical_fqns or ((call.fqn,) if call.fqn else ()))
    return entry["role"] if entry else None


def _final_producer(ctx, loss_call: CallSite, ref: Optional[ValueRef]):
    """`(call, model class, resolved)` for the last op that produced the loss input."""
    start: Optional[CallSite] = None
    if loss_call.args and isinstance(loss_call.args[0], ast.Call):
        start = _call_site_for(ctx, loss_call.module, loss_call.args[0])
    current = ref
    seen = 0
    while start is None and current is not None and seen < 4:
        seen += 1
        start = current.producer
        if start is None:
            current = None
    return _walk_final(ctx, start, 0)


def _walk_final(ctx, call: Optional[CallSite], depth: int):
    if call is None or depth > 3:
        return None, None, False
    role = _role_of(call)
    if role in ("SIGMOID", "SOFTMAX", "LOG_SOFTMAX"):
        return call, None, True
    cls = _forward_class(call)
    if cls is not None:
        inner = _forward_final_call(ctx, cls)
        if inner is None:
            return None, cls, False
        found, _cls, ok = _walk_final(ctx, inner, depth + 1)
        if found is not None and ok:
            return found, cls, True
        return inner, cls, _role_of(inner) in _LOGIT_ROLES
    if role in _LOGIT_ROLES:
        return call, None, True
    return call, None, False


def _forward_class(call: CallSite) -> Optional[ClassIR]:
    """The nn.Module whose `forward` this call is."""
    if _role_of(call) != "FORWARD":
        return None
    ref = call.receiver
    cls = ref.class_ir if ref is not None else None
    if cls is None:
        cls = call.class_ir
    return cls if cls is not None and cls.is_nn_module else None


def _forward_final_call(ctx, cls: ClassIR) -> Optional[CallSite]:
    """The call that produces whatever `forward` returns."""
    forward = cls.methods.get("forward")
    if forward is None:
        return None
    for expr in reversed(forward.returns):
        call = None
        if isinstance(expr, ast.Call):
            call = _call_site_for(ctx, cls.module, expr)
        else:
            name = dotted_text(expr)
            ref = ctx.binding_of(name, forward.scope) if name else None
            if ref is not None:
                call = ref.producer
        if call is None:
            continue
        inner = _sequential_tail(ctx, cls, call)
        return inner or call
    return None


def _attribute_producer(ctx, call: CallSite) -> Optional[CallSite]:
    """The construction behind `self.head(...)` - `self.head = nn.Sequential(...)`.

    Receiver resolution binds `self.head(x)` to the *class* (`self`), so the
    attribute's own producer has to be looked up by name.
    """
    ref = call.receiver
    if ref is not None and ref.producer is not None:
        return ref.producer
    if call.receiver_name and call.method:
        attr = ctx.binding_of("%s.%s" % (call.receiver_name, call.method), call.scope)
        if attr is not None and attr.producer is not None:
            return attr.producer
    return None


def _sequential_tail(ctx, cls: Optional[ClassIR], call: CallSite) -> Optional[CallSite]:
    """`return self.head(x)` where `self.head = nn.Sequential(..., nn.Sigmoid())`."""
    producer = _attribute_producer(ctx, call)
    if producer is None:
        return None
    last = _sequential_last(producer)
    if last is not None:
        return _call_site_for(ctx, producer.module, last) or producer
    return producer
