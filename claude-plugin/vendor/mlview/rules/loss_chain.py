"""The chain walks MLV401 and MLV402 share: what produced the loss input?

Split out of `rules/r_loss.py`, which keeps the two `@rule` entry points -
`RuleSpec.module` is part of every rule page and must not move. What lives here
is the *walking*: given the value handed to a criterion, which operation
produced it, and does that operation squash the value into a probability.

Two walks, one question. `_trace` answers it for a softmax before a
cross-entropy (MLV401); `_final_producer` / `_walk_final` answer it for the
sigmoid / BCE pairing (MLV402), which additionally has to say *what* the final
op is rather than only whether it is a softmax. Both step through a model
class's `forward`, through an `nn.Sequential` tail stored on an attribute, and -
R4 - through one workspace helper's `return`, which is the one hop that costs a
finding an `IP_HOP_WEIGHT`.

Nothing here emits an `Issue` or writes to the IR; it only answers "what is
behind this value?", so the two rules that do emit have one place to ask.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Tuple

from .. import knowledge as K
from ..ir.model import CallSite, ClassIR, ValueRef
from ..ir.symbols import dotted_text
from .valuetype import returned_call_with_role

__all__ = ["SOFTMAX_ROLES", "LOGIT_ROLES", "trace_softmax", "final_producer",
           "_role_of", "_attribute_producer"]

#: The two roles MLV401 treats as "a softmax has already been applied".
#: `LOG_SOFTMAX` is one of them here and a *logit* in `rules/valuetype`, and
#: both are right: log-probabilities are unbounded below, so they are the
#: correct partner for `NLLLoss` and the wrong one for `CrossEntropyLoss`.
_SOFTMAX_ROLES = ("SOFTMAX", "LOG_SOFTMAX")
SOFTMAX_ROLES = _SOFTMAX_ROLES

#: Roles whose output is definitely *not* squashed into [0, 1].
_LOGIT_ROLES = ("LAYER", "NORM", "NORM_TRAIN_SENSITIVE", "CONTAINER", "DROPOUT")
LOGIT_ROLES = _LOGIT_ROLES


def trace_softmax(ctx, loss_call: CallSite, ref: Optional[ValueRef]):
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
        # FW-RECOG: `is_model_module`, not `is_nn_module`. A
        # `pl.LightningModule` subclasses `nn.Module`, so `self(features)` in a
        # `training_step` is a model forward in every sense this rule cares
        # about - and `is_nn_module` answers False for it, which is what made
        # the whole Lightning half of MLV401 unreachable.
        if cls is not None and cls.is_model_module:
            found, source = _forward_softmax(ctx, cls)
            if found is not None:
                return found, cls, source
            break
        # R4: `scores = probabilities(model, x)` then `F.cross_entropy(scores, y)`.
        # The helper's `return` is the softmax, and until now the chain stopped
        # at a workspace call it could not name. **After** the model-class
        # branch, never before it: a model's `forward` is a workspace function
        # too, and pre-empting the class path would cost the finding its model
        # class, its model -> loss edge and its `definition` location - the
        # three things that make MLV401 navigable - and charge it a helper hop
        # for a call it never crossed.
        helper = returned_call_with_role(ctx, producer, tuple(_SOFTMAX_ROLES))
        if helper is not None:
            return helper, None, "helper"
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


def _role_of(call: Optional[CallSite]) -> Optional[str]:
    if call is None:
        return None
    entry, _fqn = K.best_entry(call.canonical_fqns or ((call.fqn,) if call.fqn else ()))
    return entry["role"] if entry else None


#: NLP2-17. Shape-only tensor methods cannot change whether a value is a logit
#: or a probability, so the walk steps through them to reach the activation that
#: produced it. `CrossEncoder.forward` ending in
#: `self.squash(self.head(pooled)).squeeze(-1)` hid an `nn.Sigmoid` from
#: MLV402's chain walk, on a textbook double sigmoid.
_SHAPE_ONLY = ("squeeze", "unsqueeze", "view", "reshape", "flatten", "permute",
               "transpose", "contiguous", "expand", "expand_as", "ravel", "t")


def _through_shape_ops(ctx, call: Optional[CallSite], depth: int = 0
                       ) -> Optional[CallSite]:
    """Step past `.squeeze(-1)` / `.view(...)` to the call that produced it."""
    while call is not None and depth < 4:
        if (call.method or "") not in _SHAPE_ONLY:
            return call
        depth += 1
        inner = call.receiver.producer if call.receiver is not None else None
        if inner is None:
            node = getattr(call.node, "func", None)
            base = getattr(node, "value", None)
            inner = (_call_site_for(ctx, call.module, base)
                     if isinstance(base, ast.Call) else None)
        call = inner
    return call


def _loss_input_calls(ctx, loss_call: CallSite) -> List[CallSite]:
    """Every call the loss's first argument could have come from.

    NLP2-17: the argument may be an `ast.BinOp` - a pairwise ranking loss is
    `criterion(positive_scores - negative_scores, target)` - and reading only
    `args[0]` when it is a bare `Call` missed both operands.
    """
    if not loss_call.args:
        return []
    out: List[CallSite] = []
    stack = [loss_call.args[0]]
    seen = 0
    while stack and seen < 8:
        node = stack.pop()
        seen += 1
        if isinstance(node, ast.Call):
            found = _call_site_for(ctx, loss_call.module, node)
            if found is not None:
                out.append(found)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            stack.extend([node.left, node.right])
        elif isinstance(node, ast.UnaryOp):
            stack.append(node.operand)
        else:
            name = dotted_text(node)
            ref = ctx.binding_of(name, loss_call.scope,
                                 at=loss_call.loc.line) if name else None
            if ref is not None and ref.producer is not None:
                out.append(ref.producer)
    return out


def final_producer(ctx, loss_call: CallSite, ref: Optional[ValueRef]):
    """`(call, model class, resolved, through a helper)` for the last op that
    produced the loss input."""
    candidates = _loss_input_calls(ctx, loss_call)
    for start in candidates:
        found, cls, ok, via = _walk_final(ctx, _through_shape_ops(ctx, start), 0)
        if ok:
            return found, cls, ok, via
    start = candidates[0] if candidates else None
    current = ref
    seen = 0
    while start is None and current is not None and seen < 4:
        seen += 1
        start = current.producer
        if start is None:
            current = None
    return _walk_final(ctx, _through_shape_ops(ctx, start), 0)


def _walk_final(ctx, call: Optional[CallSite], depth: int):
    """`(final op, model class, resolved, through a helper)`."""
    if call is None or depth > 3:
        return None, None, False, False
    role = _role_of(call)
    if role in ("SIGMOID", "SOFTMAX", "LOG_SOFTMAX"):
        return call, None, True, False
    cls = _forward_class(call)
    if cls is not None:
        inner = _forward_final_call(ctx, cls)
        if inner is None:
            return None, cls, False, False
        found, _cls, ok, via = _walk_final(ctx, _through_shape_ops(ctx, inner),
                                           depth + 1)
        if found is not None and ok:
            return found, cls, True, via
        return inner, cls, _role_of(inner) in _LOGIT_ROLES, False
    # R4: the same helper hop MLV401 walks, and in the same place - after the
    # model class, which is a workspace function too. A binary head written as
    # `def scores(m, x): return torch.sigmoid(m(x))` pairs just as wrongly with
    # `BCEWithLogitsLoss` as an inline sigmoid does.
    helper = returned_call_with_role(ctx, call, ("SIGMOID", "SOFTMAX",
                                                 "LOG_SOFTMAX") + tuple(_LOGIT_ROLES))
    if helper is not None:
        return helper, None, True, True
    if role in _LOGIT_ROLES:
        return call, None, True, False
    return call, None, False, False


def _forward_class(call: CallSite) -> Optional[ClassIR]:
    """The model class whose `forward` this call is.

    FW-RECOG: `is_model_module`, for the reason `_trace` gives - a
    `LightningModule`'s `self(x)` is a model forward, and MLV402's sigmoid/BCE
    pairing is written inside `training_step` at least as often as it is
    written in a hand-rolled loop.
    """
    if _role_of(call) != "FORWARD":
        return None
    ref = call.receiver
    cls = ref.class_ir if ref is not None else None
    if cls is None:
        cls = call.class_ir
    return cls if cls is not None and cls.is_model_module else None


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

