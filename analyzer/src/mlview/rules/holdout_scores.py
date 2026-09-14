"""The prediction argument of a metric call: MLV305 / MLV306.

Which argument is the prediction, whether a class decision has already been
taken, and what tags the scored value carries. Split out of
`rules/r_holdout.py`, which keeps the two `@rule` entry points that read these.
"""

from __future__ import annotations

import ast
from typing import Optional

from .. import knowledge as K
from ..ir.model import CallSite
from ..ir.symbols import dotted_text
from .helpers import value_sources
from .holdout_tables import _DECIDED, _by_node


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
    index = _by_node(call.module)
    if isinstance(node, ast.Call):
        producer = index.get(id(node))
        if producer is None:
            return (), None, dotted_text(node)
        return K.tags_of(producer.fqn), producer, dotted_text(node)
    name = dotted_text(node)
    ref = ctx.binding_of(name, call.scope) if name else None
    if ref is None:
        return (), None, name
    return tuple(ref.tags), ref.producer, name
