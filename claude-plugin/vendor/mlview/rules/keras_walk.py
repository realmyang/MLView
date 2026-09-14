"""Walking a Keras model from `compile()` back to the layer it outputs.

MLV709's first cut paired an `activation=` literal with a `from_logits=True`
loss anywhere in the same module, guarded only by the activation family. Two
things followed from that, and both were reported at severity high, confidence
0.95 - above the Problems-panel default, so published in every host:

* a `models.py` holding a probs head and a logits head of the same categorical
  problem accused **the correct one**, because nothing tied a layer and a loss
  to the same `keras.Model`; and
* a squeeze-and-excite `Dense(ch, activation="sigmoid")` channel gate - the
  standard SENet / EfficientNet / MobileNetV3 primitive, multiplied back into
  the feature map - was called an *output* activation, because nothing checked
  position in the graph.

This module is the walk that fixes both: `compile()` -> the model its receiver
was built by -> the layer behind that model's `outputs=`. It lives beside
`r_framework.py` rather than in it so neither file has to be read whole to
follow one rule (and so `r_framework.py` stays inside the size bar).

**What this cannot analyze.** A subclassed `keras.Model` with a `call()` method
has no `outputs=` expression at all; a builder more than one hop from the
`compile()` is not followed; a model compiled in a different module from the one
that built it is not reached. In each case the walk returns nothing and the
caller must stay silent - the tier's house rule is that the rule stays quiet
rather than guessing.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Tuple

from .. import knowledge as K
from ..ir.bindings import binding_of
from ..ir.model import CallSite, ModuleIR
from ..ir.symbols import dotted_text
from .helpers import literal_of

__all__ = ["kwarg_literal", "activation_literal", "call_of_node", "producing_call",
           "layer_behind", "model_construction", "output_layers", "from_logits_loss"]


def kwarg_literal(ctx, call: CallSite, key: str) -> Optional[str]:
    """The literal value of one keyword argument, followed through a binding."""
    node = call.kwarg_nodes.get(key)
    if node is None:
        return call.kwargs.get(key)
    return literal_of(ctx, node, call.scope, call.module)


def activation_literal(ctx, call: CallSite) -> Optional[str]:
    """The `activation=` literal of a Keras layer, lower-cased."""
    literal = kwarg_literal(ctx, call, "activation")
    if literal is None:
        return None
    return literal.strip().lower()


def call_of_node(module: ModuleIR, node) -> Optional[CallSite]:
    """The `CallSite` for an inline call expression, when the IR recorded one."""
    if not isinstance(node, ast.Call):
        return None
    return getattr(module, "_calls_by_node", {}).get(id(node))


def producing_call(ctx, module: ModuleIR, node, scope, at: int) -> Optional[CallSite]:
    """The call that produced the value `node` names - inline or through a name."""
    if node is None:
        return None
    inline = call_of_node(module, node)
    if inline is not None:
        return inline
    if not isinstance(node, (ast.Name, ast.Attribute)):
        return None
    ref = ctx.binding_of(dotted_text(node), scope, at=at)
    return ref.producer if ref is not None else None


def layer_behind(call: Optional[CallSite]) -> Optional[CallSite]:
    """`layers.Dense(n, activation=...)(x)` -> the `Dense(...)` construction.

    The functional API is a call *of* a call, so the value bound to `outputs`
    was produced by the `__call__`, and the `activation=` literal lives one hop
    behind it on the layer the `__call__` was made on.
    """
    if call is None:
        return None
    if K.role_of(call.fqn) == "LAYER":
        return call
    if call.method == "__call__" and call.receiver is not None:
        inner = call.receiver.producer
        if inner is not None and K.role_of(inner.fqn) == "LAYER":
            return inner
    return None


def model_construction(compile_call: CallSite, ctx=None) -> Optional[CallSite]:
    """The `keras.Model(...)` / `Sequential(...)` the compiled model came from.

    One hop through a workspace builder is followed - `model = build_model()`
    then `model.compile(...)` is how every Keras project is written - and no
    further.

    vision-10 adds the mirror hop. `docs/ISSUE_RULES.md` section 4 specifies
    MLV709 over "the same **module**", and the walk could only ever pair a head
    and a loss written inside one function body: when the `compile()` receiver
    is a **parameter** (`def compile_model(model): model.compile(...)`, the
    split the Keras guide itself teaches) there is no producer to follow at
    all. The argument at the resolved call sites is that producer, and it is
    taken only when every call site agrees - an ambiguous parameter stays
    unjudged, which is this module's house rule.
    """
    ref = compile_call.receiver
    producer = ref.producer if ref is not None else None
    if producer is None and ctx is not None:
        producer = _parameter_producer(ctx, compile_call)
    if producer is None:
        return None
    if K.role_of(producer.fqn) == "KERAS_MODEL":
        return producer
    func = producer.target_function
    if func is None:
        return None
    for expr in func.returns:
        candidate = call_of_node(func.module, expr)
        if candidate is None and isinstance(expr, (ast.Name, ast.Attribute)):
            inner = binding_of(dotted_text(expr), func.scope)
            candidate = inner.producer if inner is not None else None
        if candidate is not None and K.role_of(candidate.fqn) == "KERAS_MODEL":
            return candidate
    return None


def _parameter_producer(ctx, compile_call: CallSite) -> Optional[CallSite]:
    """The single producer every call site passes for this receiver parameter."""
    func = compile_call.function
    name = compile_call.receiver_name
    if func is None or not name or name not in (func.params or ()):
        return None
    index = list(func.params).index(name)
    found: List[CallSite] = []
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            if call.target_function is not func:
                continue
            node = call.args[index] if index < len(call.args) \
                else call.kwarg_nodes.get(name)
            if node is None:
                return None              # a call site that does not pass it
            inner = call_of_node(call.module, node)
            if inner is None:
                text = dotted_text(node)
                ref = binding_of(text, call.scope) if text else None
                inner = ref.producer if ref is not None else None
            if inner is None:
                return None              # unresolved at one site: judge none
            found.append(inner)
    if not found:
        return None
    first = found[0]
    for other in found[1:]:
        if (other.loc.file, other.loc.line, other.loc.col) != \
                (first.loc.file, first.loc.line, first.loc.col):
            return None                  # the sites disagree
    return first


def output_layers(ctx, model_call: CallSite) -> List[CallSite]:
    """The layer call(s) that produce this model's **output** tensor.

    `keras.Model(inputs, outputs)` names them in its second positional argument
    (or `outputs=`), and `Sequential([...])` in the last element of its list. A
    multi-output model contributes every one of them; anything the walk cannot
    resolve to a `LAYER` call contributes nothing.
    """
    module = model_call.module
    short = (model_call.fqn or "").rsplit(".", 1)[-1]
    nodes: List[ast.expr] = []
    if short == "Sequential":
        seq = model_call.kwarg_nodes.get("layers")
        if seq is None and model_call.args:
            seq = model_call.args[0]
        if isinstance(seq, (ast.List, ast.Tuple)) and seq.elts:
            nodes = [seq.elts[-1]]
    else:
        out = model_call.kwarg_nodes.get("outputs")
        if out is None and len(model_call.args) >= 2:
            out = model_call.args[1]
        if isinstance(out, (ast.List, ast.Tuple)):
            nodes = list(out.elts)
        elif out is not None:
            nodes = [out]
    found: List[CallSite] = []
    for node in nodes:
        layer = layer_behind(producing_call(ctx, module, node, model_call.scope,
                                            model_call.loc.line))
        if layer is not None and all(layer is not seen for seen in found):
            found.append(layer)
    return found


def from_logits_loss(ctx, compile_call: CallSite) -> Optional[Tuple[CallSite, str]]:
    """The `loss=` of a `compile()` when it is a `<Loss>(from_logits=True)`."""
    node = compile_call.kwarg_nodes.get("loss")
    if node is None and compile_call.args:
        node = compile_call.args[0]
    call = producing_call(ctx, compile_call.module, node, compile_call.scope,
                          compile_call.loc.line)
    if call is None or K.role_of(call.fqn) != "LOSS_CLS":
        return None
    if kwarg_literal(ctx, call, "from_logits") != "True":
        return None
    return call, (call.fqn or "").rsplit(".", 1)[-1]
