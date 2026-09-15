"""MLV305 / MLV306: which argument is the prediction, and was it decided?

`_prediction_arg` picks the argument a metric scores, `_decided` asks whether a
hard class decision has already been taken on it (`argmax`, `round`, `> 0.5`,
`astype(int)`), and `_scored_value` reads the tags and the producer behind it.
The two rules in `rules/r_holdout.py` are the two directions of one question:
a class metric handed raw scores, and a ranking metric handed hard labels.
"""

from __future__ import annotations

import ast
from typing import Optional

from .. import knowledge as K
from ..ir.model import CallSite
from ..ir.symbols import dotted_text
from .helpers import value_sources
from .holdout_tables import _DECIDED, _by_node
from .valuetype import value_tags


# ---------------------------------------------------------------------------
# MLV305 / MLV306 - the prediction argument
# ---------------------------------------------------------------------------
def _prediction_arg(call: CallSite) -> Optional[ast.expr]:
    """sklearn's convention is `(y_true, y_pred)`; the kwarg spelling counts too."""
    for key in ("y_pred", "y_score", "preds", "output"):
        node = call.kwarg_nodes.get(key)
        if node is not None:
            return node
    if len(call.args) >= 2:
        return call.args[1]
    return None


def _decided(ctx, node: ast.expr, call: CallSite) -> bool:
    """Has this expression already been turned into class predictions?"""
    for child in ast.walk(node):
        if isinstance(child, (ast.Compare, ast.Subscript)):
            return True
        text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute,
                                                        ast.Call)) else None
        if text and text.rsplit(".", 1)[-1] in _DECIDED:
            return True
    name = dotted_text(node)
    if not name:
        return False
    for source in value_sources(ctx, name, call.scope):
        if source.rsplit(".", 1)[-1] in _DECIDED:
            return True
        ref = ctx.binding_of(source, call.scope)
        producer = ref.producer if ref is not None else None
        if producer is None:
            continue
        if K.role_of(producer.fqn) == "ARGMAX":
            return True
        for arg in producer.args:
            for child in ast.walk(arg):
                text = dotted_text(child) if isinstance(child, ast.Call) else None
                if text and text.rsplit(".", 1)[-1] in _DECIDED:
                    return True
        if (producer.method or producer.short_name) in _DECIDED:
            return True
    return False


def _scored_value(ctx, call: CallSite, node: ast.expr):
    """`(tags, producer, name)` for the prediction argument of a metric call."""
    tags, producer, name, _ref = scored_value(ctx, call, node)
    return tags, producer, name


def scored_value(ctx, call: CallSite, node: ast.expr):
    """`(tags, producer, name, ref)` - `_scored_value` plus what it cost (R4).

    The direct read comes first and is unchanged, so a metric whose argument
    the knowledge tables already type reads exactly as it did. Only when that
    answers nothing does `rules.valuetype` go looking through the helper and
    the `.detach().cpu().numpy()` tail - and if it finds the answer inside a
    callee, the `ref` it hands back carries the hop the finding must pay for.
    """
    index = _by_node(call.module)
    if isinstance(node, ast.Call):
        producer = index.get(id(node))
        if producer is None:
            return (), None, dotted_text(node), None
        direct = K.tags_of(producer.fqn)
        if direct:
            return direct, producer, dotted_text(node), None
        found = value_tags(ctx, node, call.scope, call.module)
        if found.tags:
            return found.tags, found.producer or producer, dotted_text(node), found.ref
        return direct, producer, dotted_text(node), None
    name = dotted_text(node)
    ref = ctx.binding_of(name, call.scope) if name else None
    if ref is None:
        return (), None, name, None
    if ref.tags:
        return tuple(ref.tags), ref.producer, name, ref
    found = value_tags(ctx, node, call.scope, call.module)
    if found.tags:
        return found.tags, found.producer, name, found.ref
    return tuple(ref.tags), ref.producer, name, ref
