"""Objective-pairing rules: MLV401 (softmax before CE), MLV402 (sigmoid/BCE)."""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Tuple

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, ClassIR, ValueRef
from ..ir.symbols import dotted_text
from ..ir.provenance import IP_HOP_WEIGHT
from .helpers import arg_ref
# The chain walks live next door; the two `@rule` entry points stay here, so
# `RuleSpec.module` (and every rule page that quotes it) is unchanged.
from .loss_chain import (LOGIT_ROLES, SOFTMAX_ROLES, _attribute_producer,
                         _role_of, final_producer, trace_softmax)
from .registry import rule

__all__ = ["softmax_before_cross_entropy", "sigmoid_bce_mismatch"]

_CE_FQNS = ("torch.nn.CrossEntropyLoss.__call__", "torch.nn.functional.cross_entropy")


@rule(code="MLV401", severity="high", base_prior=0.95, frameworks=["torch"],
      rule_version=1, tags=["correctness", "objective"], cross_file=True,
      title="Softmax applied before CrossEntropyLoss",
      why="CrossEntropyLoss applies log-softmax internally, so a second softmax "
          "flattens the gradients and the model trains far worse than it should.",
      fix_hint="Return raw logits from forward() and apply softmax only where you need "
               "probabilities for reporting.")
def softmax_before_cross_entropy(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    #: `(offending softmax, model class) -> the Issue already raised`. One root
    #: cause is one defect and one edit: a LightningModule applies the same
    #: `forward` in `training_step` **and** in `validation_step`, and a
    #: hand-written loop calls the same criterion in train and in eval, so the
    #: per-loss-call loop reported the identical softmax twice from two lines
    #: with two identical `final_layer` locations. Measured on
    #: `analyzer/tests/accuracy/corpus/lightning_tabular`, where the second copy
    #: is a false positive. Two different models that each softmax before a CE
    #: still get one finding each. This is the same merge `sigmoid_bce_mismatch`
    #: below performs, written the same way.
    reported: dict = {}
    for loss_call in _cross_entropy_calls(ctx):
        name, ref = arg_ref(ctx, loss_call, 0)
        softmax_call, model_cls, source = trace_softmax(ctx, loss_call, ref)
        if softmax_call is None:
            continue
        key = _root_cause(softmax_call, model_cls)
        previous = reported.get(key)
        if previous is not None:
            extra = loss_call.loc.related_dict(
                "call_site", "and the loss at %s:%d is the same pairing"
                % (loss_call.loc.file, loss_call.loc.line))
            if extra not in previous.relatedLocs:
                previous.relatedLocs.append(extra)
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
        # R3/G10: with the forward pass drawn as a card of its own
        # (`core/workspace_ops.invoke_op`), the model -> loss connection is two
        # hops - `SmallCNN` -> `logits` -> `loss` - so the model's class unit no
        # longer has a direct data edge into the loss and `edgeIds` came back
        # empty. The edge that expresses the connection now is `logits -> loss`,
        # whose source is the producer of the very value handed to the loss. The
        # ANCHOR NODES do not move - the class unit is what a reader wants to
        # open - only the edge falls back, and a graph with no forward-pass card
        # keeps the edge it always had.
        if edge is None and ref is not None:
            producer = ctx.builder._producer_node(ref)
            if producer is not None and producer is not model_node:
                edge = ctx.edge_between(producer, loss_node, "data")
        nodes = [loss_node] + ([model_node] if model_node is not None
                               and model_node is not loss_node else [])
        # REV-06: ANA-1 mints an op node for the offending `softmax()` call
        # itself, so anchor on that too - a reader who clicked this finding
        # landed on the whole class card rather than on the line that applies
        # the softmax. Appended last, so `nodeIds[0]` (which
        # `contracts/validate_sample.py` and the rail's "Open" both key on)
        # does not move.
        softmax_node = ctx.node_for_call(softmax_call)
        if softmax_node is not None and softmax_node.id not in {n.id for n in nodes}:
            nodes.append(softmax_node)
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (loss_call.fqn or "cross_entropy"), 1.0),
            ("dataflow_direct", "%s reaches the loss input" % (name or "the model output"), 1.0),
            ("cross_file", "model defined in %s" % softmax_call.loc.file,
             1.0 if softmax_call.loc.file == loss_call.loc.file else 0.9),
        ]
        if source == "conditional":
            evidence.append(("context_confirmed", "softmax sits inside a conditional", 0.6))
        elif source == "helper":
            # One `def` crossed, one IP_HOP_WEIGHT paid (11.36 G6): 0.95 x 0.8
            # is 0.76, so a helper-traced pairing lands at `likely` and a
            # cross-object claim still cannot reach `certain`.
            evidence.append(("cross_file",
                             "%s is what %s hands back, one function away"
                             % (softmax_call.fqn or softmax_call.short_name,
                                name or "the helper"), IP_HOP_WEIGHT))
        # 11.36 G6: the helper hop is a crossing, and a crossing is paid for.
        evidence.extend(ctx.hops(ref))
        related_hops = ctx.hop_related(ref)
        related = [("final_layer", softmax_call.loc,
                    "%s applied here" % (softmax_call.fqn or softmax_call.short_name))]
        if model_cls is not None:
            related.append(("definition", model_cls.loc,
                            "model class %s" % model_cls.name))
        related.extend(related_hops)
        issue = ctx.issue(
            message="The value passed to %s at %s:%d comes from %s at %s:%d, so the "
                    "probabilities are log-softmaxed twice."
                    % (_label(loss_call), loss_call.loc.file, loss_call.loc.line,
                       softmax_call.fqn or softmax_call.short_name,
                       softmax_call.loc.file, softmax_call.loc.line),
            loc=loss_call.loc, node_ids=nodes,
            edge_ids=[edge] if edge is not None else (),
            related=related, evidence=evidence,
            dynamic=loss_call.scope.is_dynamic)
        reported[key] = issue
        issues.append(issue)
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
    # Source order, so the surviving copy of a merged pairing is the first loss
    # site in the file rather than whichever module happened to be walked first.
    out.sort(key=lambda c: (c.loc.file, c.loc.line, c.loc.col))
    return out


def _root_cause(final: CallSite, cls: Optional[ClassIR]) -> Tuple[str, int, int, str]:
    """What two findings would have to share to be the same defect."""
    return (final.loc.file, final.loc.line, final.loc.col,
            cls.qualname if cls is not None else "")



# ---------------------------------------------------------------------------
# MLV402
# ---------------------------------------------------------------------------
_LOGIT_LOSSES = ("torch.nn.BCEWithLogitsLoss.__call__",
                 "torch.nn.functional.binary_cross_entropy_with_logits")
_PROB_LOSSES = ("torch.nn.BCELoss.__call__",
                "torch.nn.functional.binary_cross_entropy")


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
    #: `(criterion construction, producing layer) -> the Issue already raised`.
    #: One wrong pairing is one defect and one edit; a GAN that evaluates the
    #: same criterion against the same discriminator four times in one loop
    #: body was getting four identical findings (NLP2-17).
    reported: dict = {}
    for loss_call, variant in _bce_calls(ctx):
        name, ref = arg_ref(ctx, loss_call, 0)
        final, cls, resolved, via_helper = final_producer(ctx, loss_call, ref)
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
        # R3/G10: with the forward pass drawn as a card of its own
        # (`core/workspace_ops.invoke_op`), the model -> loss connection is two
        # hops - `SmallCNN` -> `logits` -> `loss` - so the model's class unit no
        # longer has a direct data edge into the loss and `edgeIds` came back
        # empty. The edge that expresses the connection now is `logits -> loss`,
        # whose source is the producer of the very value handed to the loss. The
        # ANCHOR NODES do not move - the class unit is what a reader wants to
        # open - only the edge falls back, and a graph with no forward-pass card
        # keeps the edge it always had.
        if edge is None and ref is not None:
            producer = ctx.builder._producer_node(ref)
            if producer is not None and producer is not model_node:
                edge = ctx.edge_between(producer, loss_node, "data")
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
        if via_helper:
            # See MLV401: one `def` crossed, one IP_HOP_WEIGHT paid (11.36 G6).
            evidence.append(("cross_file",
                             "%s is what %s hands back, one function away"
                             % (final_name, name or "the helper"), IP_HOP_WEIGHT))
        related = [("final_layer", final.loc, "%s is the last operation" % final_name)]
        if cls is not None:
            related.append(("definition", cls.loc, "model class %s" % cls.name))
        # Where the criterion was BUILT is the line the fix is applied to -
        # `nn.BCELoss()` becomes `nn.BCEWithLogitsLoss()` there, not at the
        # call - and on a multi-loss dict it is the only place the reader can
        # see which of them this is about.
        criterion = loss_call.receiver.producer if loss_call.receiver is not None else None
        if criterion is None:
            criterion = _attribute_producer(ctx, loss_call)
        if criterion is not None and criterion is not loss_call:
            related.append(("construction", criterion.loc,
                            "the criterion is built here"))
        key = (id(criterion) if criterion is not None else None, id(final), variant)
        previous = reported.get(key)
        if previous is not None:
            extra = loss_call.loc.related_dict(
                "call_site", "and %s at %s:%d is the same pairing"
                % (_label(loss_call), loss_call.loc.file, loss_call.loc.line))
            if extra not in previous.relatedLocs:
                previous.relatedLocs.append(extra)
            continue
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
        issue = ctx.issue(
            message=message, loc=loss_call.loc, node_ids=nodes,
            edge_ids=[edge] if edge is not None else (),
            related=related, evidence=evidence,
            tags=("correctness", "objective", variant),
            dynamic=loss_call.scope.is_dynamic)
        reported[key] = issue
        issues.append(issue)
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
