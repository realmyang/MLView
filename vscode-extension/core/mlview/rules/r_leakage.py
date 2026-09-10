"""Leakage rules: MLV101 (fit before split), MLV102 (fit on held-out),
MLV103 (preprocessing outside cross-validation)."""

from __future__ import annotations

from typing import Iterable, List, Optional

from ..core.coverage import untraced_reason
from ..core.graph import Issue
from ..ir.model import CallSite
from ..ir.symbols import dotted_text
from ..knowledge import STATELESS_TRANSFORMERS
from .helpers import arg_ref, reaches, traced_arg
from .registry import rule

__all__ = ["fit_before_split", "fit_on_held_out", "preprocessing_outside_cv"]


@rule(code="MLV101", severity="high", base_prior=0.95, frameworks=["sklearn", "pandas"],
      rule_version=1, tags=["leakage", "preprocess"],
      title="Preprocessing fitted before the train/test split",
      why="Statistics from the test rows leak into training, so the reported test "
          "performance is optimistic and does not survive deployment.",
      fix_hint="Split first, then fit_transform on the training rows and transform the "
               "rest - or put the transformer and estimator in a sklearn Pipeline.")
def fit_before_split(ctx) -> Iterable[Issue]:
    splits = ctx.calls_with_role("SPLIT")
    if not splits:
        return []
    issues: List[Issue] = []
    for fit in ctx.calls_with_role("FIT", "FIT_TRANSFORM"):
        if _stateless(fit):
            continue
        name, ref = traced_arg(ctx, fit, 0)
        if ref is None or not ref.tags:
            # COVERAGE: no tag at all means the analyzer never traced this
            # value - a bare function parameter is the measured case. Staying
            # silent is right; looking clean is not.
            ctx.untraced(fit, name, _untraced_reason(fit, name, ref))
            continue
        if not ref.has("FEATURES", "RAW_DATA"):
            continue
        if ref.has("TRAIN_SPLIT"):
            continue
        targets = {name, fit.var}
        # DATAFLOW-IP: a cross-object claim is confined to one scope. Two
        # uncertainties multiply, and `_split_consuming` matches by **name**:
        # combining an interprocedural hop with a name that means something
        # else in a foreign scope is how a high-severity false positive gets
        # made - measured on `hydra_research`, where `features` is a local in
        # two different functions and the earlier split appeared to consume the
        # later fit. A local finding is unaffected, so `--dataflow local` is
        # byte-identical by construction rather than by measurement.
        split = _split_consuming(ctx, fit, splits, targets,
                                 same_scope=bool(ref.provenance))
        if split is None:
            continue
        node = ctx.node_for_call(fit) or ctx.unit_for_call(fit)
        if node is None:
            continue
        split_node = ctx.node_for_call(split)
        target_only = ref.has("TARGET") and not ref.has("FEATURES")
        evidence = [
            ("fqn_resolved", "%s resolved through the import table" % (fit.fqn or "fit"), 1.0),
            ("dataflow_direct",
             "%s flows into %s at line %d" % (name, split.short_name, split.loc.line), 1.0),
        ]
        # A dynamic scope is de-rated once, by the engine (x0.7).
        if not fit.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % fit.scope.qualname, 1.0))
        if target_only:
            evidence.append(("name_regex", "the fitted value carries only TARGET", 0.6))
        # DATAFLOW-IP: one `cross_file` factor per hop the tag took to get here,
        # so a cross-object finding is de-rated arithmetically and can never
        # reach `certain`; and one RelatedLoc per hop, so the reader can open
        # the construction site the tag entered through.
        evidence.extend(ctx.hops(ref))
        related = [
            ("fit_site", fit.loc, "fitted on the full dataset here"),
            ("split_site", split.loc, "split happens later, at line %d" % split.loc.line),
        ]
        related.extend(ctx.hop_related(ref))
        # Only a **cross-object** finding gets it. A finding whose value
        # dataflow established locally reads identically in both modes, which
        # is what makes `ip` a widening of `local` rather than a second dialect.
        ctor = _transformer_ctor(ctx, fit) if ref.provenance else None
        if ctor is not None:
            related.append(("construction", ctor.loc,
                            "the transformer is constructed here"))
        nodes = [node] + ([split_node] if split_node is not None and split_node is not node
                          else [])
        issues.append(ctx.issue(
            message="%s is fitted on %s at %s:%d, before %s splits it at line %d, so the "
                    "transformer sees the held-out rows."
                    % (_label(fit), name, fit.loc.file, fit.loc.line,
                       split.short_name, split.loc.line),
            loc=fit.loc, node_ids=nodes, related=related, evidence=evidence,
            dynamic=fit.scope.is_dynamic))
    return issues


#: TB-10: the wording lives in `core/coverage` now, because the post-rule sweep
#: explains the same blind spots and the two must not diverge.
_untraced_reason = untraced_reason


def _label(call: CallSite) -> str:
    if call.receiver_name:
        return "%s.%s()" % (call.receiver_name, call.method or call.short_name)
    return "%s()" % call.short_name


def _transformer_ctor(ctx, fit: CallSite) -> Optional[CallSite]:
    """Where the transformer being fitted was constructed, when that is known.

    `self.scaler = StandardScaler()` in `__init__` and `self.scaler.fit_transform(...)`
    in `setup()` are the two halves of the Lightning leak, and a finding that
    names only the second half asks the reader to go and find the first. The
    producer of the receiver's binding *is* the first half.
    """
    ref = fit.receiver
    producer = ref.producer if ref is not None else None
    if producer is None or producer is fit:
        return None
    if producer.loc.file == fit.loc.file and producer.loc.line == fit.loc.line:
        return None
    return producer


def _stateless(call: CallSite) -> bool:
    ref = call.receiver
    producer = ref.producer if ref is not None else None
    fqn = producer.fqn if producer is not None else call.fqn
    return bool(fqn and fqn in STATELESS_TRANSFORMERS)


def _split_consuming(ctx, fit: CallSite, splits, targets,
                     same_scope: bool = False) -> Optional[CallSite]:
    """The later split whose input derives from the fit's input or output.

    `same_scope` (DATAFLOW-IP) additionally requires the split to be written in
    the fit's own scope. It is set only for a value whose tags arrived through
    an interprocedural hop; see `fit_before_split` for why.
    """
    for split in splits:
        if split.module is not fit.module:
            continue
        if same_scope and split.scope is not fit.scope:
            continue
        if split.loc.line < fit.loc.line and split.scope is fit.scope:
            continue
        for arg in list(split.args) + [split.kwarg_nodes[k] for k in sorted(split.kwarg_nodes)]:
            name = dotted_text(arg)
            if not name:
                continue
            if reaches(ctx, name, split.scope, targets):
                return split
    return None


# ---------------------------------------------------------------------------
# MLV102
# ---------------------------------------------------------------------------
_HELD_OUT = ("VAL_SPLIT", "TEST_SPLIT")


@rule(code="MLV102", severity="high", base_prior=0.97, frameworks=["sklearn"],
      rule_version=1, tags=["leakage", "preprocess"],
      title="Transformer fitted on validation or test data",
      why="The transformer learns statistics from rows it is supposed to be judged on, "
          "so the held-out score is not an estimate of unseen-data performance at all.",
      fix_hint="Call transform() - not fit() or fit_transform() - on validation and test "
               "data, reusing the transformer already fitted on the training split.")
def fit_on_held_out(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for fit in ctx.calls_with_role("FIT", "FIT_TRANSFORM"):
        if _stateless(fit):
            continue
        if _semi_supervised(fit.module):
            continue
        name, ref = traced_arg(ctx, fit, 0)
        if ref is None or not ref.tags:
            ctx.untraced(fit, name, _untraced_reason(fit, name, ref))
            continue
        if not ref.has(*_HELD_OUT):
            continue
        if ref.has("TRAIN_SPLIT"):
            continue
        node = ctx.node_for_call(fit) or ctx.unit_for_call(fit)
        if node is None:
            continue
        split = _split_producing(ref)
        which = "TEST_SPLIT" if ref.has("TEST_SPLIT") else "VAL_SPLIT"
        by_dataflow = split is not None
        evidence = [
            ("fqn_resolved", "%s resolved through the import table" % (fit.fqn or "fit"),
             1.0),
            ("dataflow_direct" if by_dataflow else "name_regex",
             "%s carries %s %s" % (name, which,
                                   "from the split at line %d" % split.loc.line
                                   if by_dataflow else "by naming convention alone"),
             1.0 if by_dataflow else 0.8),
        ]
        if not fit.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % fit.scope.qualname, 1.0))
        evidence.extend(ctx.hops(ref))
        related = [("fit_site", fit.loc, "fitted on held-out rows here")]
        if split is not None:
            related.append(("split_site", split.loc, "the split happens here"))
        related.extend(ctx.hop_related(ref))
        issues.append(ctx.issue(
            message="%s is fitted on %s at %s:%d, and %s carries %s - the held-out rows "
                    "are used to learn the transform."
                    % (_label(fit), name, fit.loc.file, fit.loc.line, name, which),
            loc=fit.loc, node_ids=[node], related=related, evidence=evidence,
            dynamic=fit.scope.is_dynamic))
    return issues


def _semi_supervised(module) -> bool:
    """Transductive learning legitimately fits on unlabeled test features."""
    for fqn in module.symbols.aliases.values():
        if fqn.startswith("sklearn.semi_supervised"):
            return True
    return False


def _split_producing(ref) -> Optional[CallSite]:
    producer = ref.producer
    if producer is None:
        return None
    from .. import knowledge as K
    return producer if K.role_of(producer.fqn) in ("SPLIT", "SPLITTER") else None


# ---------------------------------------------------------------------------
# MLV103
# ---------------------------------------------------------------------------
_PIPELINE_FQNS = ("sklearn.pipeline.Pipeline", "sklearn.pipeline.make_pipeline",
                  "imblearn.pipeline.Pipeline", "imblearn.pipeline.make_pipeline")


@rule(code="MLV103", severity="medium", base_prior=0.85, frameworks=["sklearn"],
      rule_version=1, tags=["leakage", "preprocess"],
      title="Preprocessing happens outside cross-validation",
      why="Every fold is scored on rows whose scaling was computed from the whole set, "
          "so the cross-validation estimate is optimistic and model selection is biased.",
      fix_hint="Wrap the transformer and the estimator in sklearn.pipeline.Pipeline and "
               "pass the pipeline to the CV call, so preprocessing is refit per fold.")
def preprocessing_outside_cv(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for cv_call, estimator_expr, data_expr in _cv_sites(ctx):
        if _is_pipeline(ctx, cv_call, estimator_expr):
            continue
        data_name = dotted_text(data_expr) if data_expr is not None else None
        if not data_name:
            continue
        fit = _feeding_fit_transform(ctx, cv_call, data_name)
        if fit is None:
            continue
        if _already_reported(ctx, fit):
            continue                     # MLV101 owns this root cause
        node = ctx.node_for_call(cv_call) or ctx.unit_for_call(cv_call)
        if node is None:
            continue
        estimator_text = dotted_text(estimator_expr) or "the estimator"
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (cv_call.fqn or cv_call.short_name), 1.0),
            ("dataflow_direct",
             "%s was produced by %s at line %d and is passed straight to %s"
             % (data_name, _label(fit), fit.loc.line, cv_call.short_name), 1.0),
            ("negation_absent",
             "%s is a bare estimator, not a Pipeline / make_pipeline" % estimator_text,
             1.0),
        ]
        if not cv_call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % cv_call.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="%s at %s:%d cross-validates a bare estimator over %s, which %s "
                    "already fitted on the whole set at line %d - the folds share its "
                    "statistics."
                    % (cv_call.short_name, cv_call.loc.file, cv_call.loc.line, data_name,
                       _label(fit), fit.loc.line),
            loc=cv_call.loc, node_ids=[node],
            related=[("fit_site", fit.loc, "fitted once, outside the folds"),
                     ("call_site", cv_call.loc, "cross-validation runs here")],
            evidence=evidence, dynamic=cv_call.scope.is_dynamic))
    return issues


def _cv_sites(ctx):
    """`(cv call, estimator expression, X expression)` for every CV entrypoint."""
    from .. import knowledge as K
    out = []
    for call in ctx.calls_with_role("CV"):
        estimator = call.args[0] if call.args else call.kwarg_nodes.get("estimator")
        data = call.args[1] if len(call.args) > 1 else call.kwarg_nodes.get("X")
        out.append((call, estimator, data))
    for call in ctx.calls_with_role("FIT"):
        receiver = call.receiver
        producer = receiver.producer if receiver is not None else None
        if producer is None or K.role_of(producer.fqn) != "CV_SEARCH":
            continue
        estimator = producer.args[0] if producer.args \
            else producer.kwarg_nodes.get("estimator")
        data = call.args[0] if call.args else call.kwarg_nodes.get("X")
        out.append((call, estimator, data))
    out.sort(key=lambda t: (t[0].loc.file, t[0].loc.line, t[0].loc.col))
    return out


def _is_pipeline(ctx, cv_call: CallSite, expr) -> bool:
    if expr is None:
        return True                      # cannot tell: stay quiet
    module = cv_call.module
    by_node = getattr(module, "_calls_by_node", {})
    import ast as _ast
    if isinstance(expr, _ast.Call):
        inner = by_node.get(id(expr))
        return bool(inner is not None and _pipeline_fqn(inner))
    name = dotted_text(expr)
    ref = ctx.binding_of(name, cv_call.scope) if name else None
    if ref is None:
        return True                      # unresolved estimator: stay quiet
    return bool(ref.producer is not None and _pipeline_fqn(ref.producer))


def _pipeline_fqn(call: CallSite) -> bool:
    return any(f in _PIPELINE_FQNS for f in call.canonical_fqns or ())


def _feeding_fit_transform(ctx, cv_call: CallSite, data_name: str) -> Optional[CallSite]:
    """A `fit_transform` earlier in the same function that produced the CV's X."""
    from .. import knowledge as K
    best = None
    for fit in ctx.calls_with_role("FIT_TRANSFORM"):
        if fit.module is not cv_call.module or fit.function is not cv_call.function:
            continue
        if fit.loc.line >= cv_call.loc.line:
            continue
        if _stateless(fit):
            continue
        targets = {fit.var}
        name, _ref = arg_ref(ctx, fit, 0)
        if name:
            targets.add(name)
        if reaches(ctx, data_name, cv_call.scope, targets):
            if best is None or fit.loc.line > best.loc.line:
                best = fit
    return best


def _already_reported(ctx, fit: CallSite) -> bool:
    """MLV101 fired on the same transformer: never stack two findings."""
    for issue in ctx.issues:
        if issue.code == "MLV101" and issue.loc.file == fit.loc.file \
                and issue.loc.line == fit.loc.line:
            return True
    return False
