"""What a scored value *is*: LOGITS, PROBS or PREDS (R4).

Four rules ask the same question about the same kind of value and used to ask
it four different ways:

* **MLV305** - is the thing handed to `accuracy_score` a class prediction, or
  is it still a raw score?
* **MLV306** - is the thing handed to `roc_auc_score` a score, or has a class
  decision already been taken?
* **MLV401** - does the value fed to `CrossEntropyLoss` come from a softmax?
* **MLV402** - does the value fed to a BCE loss come from a sigmoid?

The knowledge tables already answer that for a *direct* call: `F.softmax` is
`PROBS`, `torch.argmax` is `PREDS`, `nn.Module.__call__` is `LOGITS`,
`predict_proba` is `PROBS` and `predict` is `PREDS`. What no rule could do was
follow the answer through the two hops a real program puts in the way:

    def probabilities(model, x):          # a workspace helper
        return F.softmax(model(x), dim=-1)

    probs = probabilities(model, x)
    accuracy_score(y, probs.detach().cpu().numpy())   # <- still PROBS

The first hop is the **return** of an in-workspace function; the second is the
`.detach().cpu().numpy()` tail that every torch program writes before it hands
a tensor to sklearn. Neither changes what the value is, and dropping the tag at
either one is what made MLV305 silent on the shape it exists to catch.

Two functions, one question each:

    value_tags(ctx, node, scope, module)   what this expression holds
    returned_call_with_role(ctx, call, roles)
                                           the op a workspace callee returns

Both are read-only over the IR: they resolve nothing, bind nothing and mint no
tags of their own. `value_tags` never *invents* a score tag - every tag it
returns was put there by a knowledge-table entry or by `ir.returns`, and the
only thing this module adds is the willingness to keep looking.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .. import knowledge as K
from ..ir.model import CallSite, ValueRef
from ..ir.provenance import DEFAULT_MAX_HOPS, Hop, extend
from ..ir.symbols import dotted_text

__all__ = ["SCORE_TAGS", "Scored", "value_tags", "returned_call_with_role",
           "PROB_ROLES", "LOGIT_ROLES", "DECIDING_ROLES"]

#: The three things a model output can be, in the order a program produces
#: them. Every consumer here reasons about exactly this vocabulary.
SCORE_TAGS = ("LOGITS", "PROBS", "PREDS")

#: Roles whose output is squashed into a probability, and roles whose output is
#: not. `LOG_SOFTMAX` is deliberately a logit: log-probabilities are unbounded
#: below and `CrossEntropyLoss` is the *correct* partner for them.
PROB_ROLES = frozenset({"SOFTMAX", "SIGMOID"})
LOGIT_ROLES = frozenset({"LOG_SOFTMAX"})
#: Roles that take the class decision, after which nothing is a score any more.
DECIDING_ROLES = frozenset({"ARGMAX"})

#: Roles the knowledge tables already carry through their receiver.
_PASSTHROUGH_ROLES = frozenset({"ITEM", "DETACH", "TO_NUMPY", "TO_DEVICE"})

#: Methods that change a tensor's container, device or dtype and not what it
#: holds. Read only when the FQN did not resolve - an unresolved `.numpy()` on
#: an untyped receiver is exactly the tail this module exists to walk, and a
#: name check is the only thing left at that point. Nothing that reduces,
#: selects or compares is on this list: `argmax`, `topk`, `round` and friends
#: take the class decision and are `DECIDING_ROLES`.
_PASSTHROUGH_METHODS = frozenset({
    "detach", "cpu", "cuda", "numpy", "tolist", "clone", "contiguous",
    "float", "double", "half", "bfloat16", "to", "astype", "copy",
    "squeeze", "unsqueeze", "flatten", "ravel", "reshape", "view",
})

#: How many hops `value_tags` will walk before it gives up. Three is the same
#: cap `ir.provenance` uses, for the same reason.
_MAX_DEPTH = 3


@dataclass(frozen=True)
class Scored:
    """What an expression holds, and how the rule came to know it."""

    tags: Tuple[str, ...] = ()
    #: The call that decided the tags - a softmax, an argmax, a `predict()`.
    producer: Optional[CallSite] = None
    #: How to spell the value in prose.
    name: Optional[str] = None
    #: The reference whose `provenance` the finding must pay for (11.36 G6).
    #: `None`, or a ref with an empty chain, costs the finding nothing.
    ref: Optional[ValueRef] = None
    #: True when the answer came from a *callee*, so the caller can say so.
    through_callee: bool = False

    def has(self, *tags: str) -> bool:
        return any(t in self.tags for t in tags)


def value_tags(ctx, node: Optional[ast.expr], scope, module,
               depth: int = 0) -> Scored:
    """What the expression `node` holds, following helpers and tensor tails.

    Returns whatever the *shortest* answer is: a knowledge-table entry on the
    expression itself wins, then the binding's own tags, then the receiver of a
    pass-through method, then the return of a workspace callee. The walk stops
    at `_MAX_DEPTH`, and an expression it cannot type comes back with empty
    tags - never with a guess.
    """
    if node is None or depth > _MAX_DEPTH:
        return Scored()
    if isinstance(node, ast.Call):
        return _call_tags(ctx, node, scope, module, depth)
    name = dotted_text(node)
    if not name:
        return Scored()
    ref = ctx.binding_of(name, scope)
    if ref is None:
        return Scored(name=name)
    if _scoring(ref.tags):
        return Scored(tuple(ref.tags), ref.producer, name, ref)
    producer = ref.producer
    if producer is None:
        return Scored(tuple(ref.tags), None, name, ref)
    found = _through_call(ctx, producer, depth + 1)
    if not found.tags:
        return Scored(tuple(ref.tags), producer, name, ref)
    return Scored(found.tags, found.producer, name,
                  _carry(ctx, ref, found, scope), found.through_callee)


def _call_tags(ctx, node: ast.Call, scope, module, depth: int) -> Scored:
    """The tags of an expression written as a call, in place."""
    index = getattr(module, "_calls_by_node", None) or {}
    call = index.get(id(node))
    text = dotted_text(node)
    if call is None:
        return Scored(name=text)
    direct = K.tags_of(call.fqn)
    if _scoring(direct):
        return Scored(tuple(direct), call, text)
    found = _through_call(ctx, call, depth + 1)
    if found.tags:
        return Scored(found.tags, found.producer, text, found.ref,
                      found.through_callee)
    return Scored(tuple(direct), call, text)


def _through_call(ctx, call: CallSite, depth: int) -> Scored:
    """What a call hands back when its own FQN does not say.

    Two shapes, in order: a tensor tail (`.detach()`, `.cpu()`, `.numpy()`)
    whose receiver holds the answer, and a call into a workspace function whose
    `return` does.
    """
    if depth > _MAX_DEPTH:
        return Scored()
    direct = K.tags_of(call.fqn)
    if _scoring(direct):
        return Scored(tuple(direct), call)
    role = K.role_of(call.fqn or "")
    if role in _PASSTHROUGH_ROLES or (
            role is None and (call.method or "") in _PASSTHROUGH_METHODS):
        receiver = call.receiver
        if receiver is not None and _scoring(receiver.tags):
            return Scored(tuple(receiver.tags), receiver.producer,
                          receiver.name, receiver)
        if receiver is not None and receiver.producer is not None:
            return _through_call(ctx, receiver.producer, depth + 1)
        inline = _inline_receiver(call)
        if inline is not None:
            return _through_call(ctx, inline, depth + 1)
        return Scored()
    collected = _collected_tags(ctx, call, depth)
    if collected.tags:
        return collected
    func = getattr(call, "target_function", None)
    if func is None:
        return Scored()
    for expr in reversed(func.returns):
        found = value_tags(ctx, expr, func.scope, func.module, depth)
        if found.tags:
            return Scored(found.tags, found.producer, found.name, found.ref,
                          through_callee=True)
    return Scored()


def returned_call_with_role(ctx, call: Optional[CallSite],
                            roles: Sequence[str], depth: int = 0
                            ) -> Optional[CallSite]:
    """The call with one of `roles` that a workspace function `return`s.

    `return F.softmax(self.head(x), dim=-1)` inside a helper is the same defect
    as writing the softmax at the loss site; MLV401 and MLV402 both need to see
    through exactly one `def` to say so. Nested one level further, because
    `def probabilities(m, x): return _head(m, x)` is how the second refactor of
    the same helper is written.
    """
    if call is None or depth > _MAX_DEPTH:
        return None
    func = getattr(call, "target_function", None)
    if func is None:
        return None
    index = getattr(func.module, "_calls_by_node", None) or {}
    for expr in reversed(func.returns):
        inner = None
        if isinstance(expr, ast.Call):
            inner = index.get(id(expr))
        else:
            name = dotted_text(expr)
            ref = ctx.binding_of(name, func.scope) if name else None
            inner = ref.producer if ref is not None else None
        if inner is None:
            continue
        if _role(inner) in roles:
            return inner
        deeper = returned_call_with_role(ctx, inner, roles, depth + 1)
        if deeper is not None:
            return deeper
    return None


#: The one-argument collectors that turn a per-batch list back into an array.
#: `np.concatenate(predictions)` is how a batched evaluation is actually
#: written, and the tag used to die in the list.
_COLLECTORS = frozenset({"concatenate", "concat", "stack", "cat", "vstack",
                         "hstack", "asarray", "array"})


def _collected_tags(ctx, call: CallSite, depth: int) -> Scored:
    """`np.concatenate(predictions)` after `predictions.append(scores)` (REC-07).

    A batched evaluation loop collects one array per batch and joins them once
    at the end; nothing about that changes what the values *are*, and MLV305 /
    MLV401 / MLV402 went silent on the dominant real-world spelling of their
    own defect because the tag stopped at the list.

    The same literal-only discipline `ir.containers` uses: the list must be an
    empty `[]` bound in this scope, and only `append` calls on it in that scope
    are read - no aliasing, no mutation modelling beyond the appends in sight.
    And the same **intersection** discipline 3.11 N6 uses: every append has to
    agree, so a list that also receives an argmaxed value yields nothing rather
    than a union that would make a correct program look wrong. Crossing no
    object, it costs no hop of its own; an append whose own answer came out of
    a callee still carries that callee's hop, because `value_tags` minted it.
    """
    if (call.method or call.short_name or "") not in _COLLECTORS:
        return Scored()
    node = call.args[0] if call.args else None
    name = dotted_text(node) if node is not None else None
    if not name:
        return Scored()
    ref = ctx.binding_of(name, call.scope)
    if ref is None or ref.literal != "[]":
        return Scored()
    found: List[Scored] = []
    for other in call.module.calls:
        if (other.method or "") != "append" or other.scope is not call.scope:
            continue
        if other.receiver_name != name or not other.args:
            continue
        answer = value_tags(ctx, other.args[0], other.scope, other.module, depth)
        if not answer.tags:
            return Scored()          # one append MLView could not read: no answer
        found.append(answer)
    if not found:
        return Scored()
    tags = set(found[0].tags)
    for answer in found[1:]:
        tags &= set(answer.tags)
    if not tags:
        return Scored()
    first = found[0]
    return Scored(tuple(t for t in first.tags if t in tags), first.producer,
                  name, first.ref, first.through_callee)


def _inline_receiver(call: CallSite) -> Optional[CallSite]:
    """The call a method was written *on*, when it has no named receiver.

    `hard_labels(model, x).numpy()` binds nothing between the two calls, so
    there is no `ValueRef` to carry the tag and `call.receiver` is `None`. The
    receiver is right there in the AST.
    """
    node = getattr(call, "node", None)
    func = getattr(node, "func", None)
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Call):
        return None
    index = getattr(call.module, "_calls_by_node", None) or {}
    return index.get(id(func.value))


def _role(call: CallSite) -> Optional[str]:
    entry, _fqn = K.best_entry(call.canonical_fqns
                               or ((call.fqn,) if call.fqn else ()))
    return entry["role"] if entry else None


def _scoring(tags) -> bool:
    return any(t in SCORE_TAGS for t in (tags or ()))


def _carry(ctx, ref: ValueRef, found: Scored, scope) -> ValueRef:
    """`ref` with the hop the answer travelled, so the finding pays for it.

    A tag read off a binding costs nothing - `ir.returns` has been filling
    those in since long before DATAFLOW-IP existed. A tag this module went and
    *fetched* out of a callee is a cross-object claim, and 11.36 G6 says a rule
    making one may not skip the de-rating.
    """
    if not found.through_callee:
        return ref
    hop = Hop(kind="return", detail="the value %s returns" % (ref.name or "it"),
              loc=ref.loc or (found.producer.loc if found.producer else None))
    if hop.loc is None:
        return ref
    chain = extend(getattr(ref, "provenance", ()) or (), hop,
                   getattr(ctx.workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
    if chain is None:
        return ref
    carried = ValueRef(name=ref.name, scope=ref.scope, tags=tuple(found.tags),
                       producer=found.producer or ref.producer, loc=ref.loc,
                       sources=ref.sources, class_ir=ref.class_ir,
                       is_config=ref.is_config, via_fqns=ref.via_fqns,
                       provenance=chain)
    ctx.note_hops(carried, scope)
    return carried
