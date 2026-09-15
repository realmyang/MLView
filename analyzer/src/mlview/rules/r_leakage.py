"""Leakage rules: MLV101 (fit before split), MLV102 (fit on held-out),
MLV103 (preprocessing outside cross-validation)."""

from __future__ import annotations

from typing import Iterable, List, Optional

from ..core.coverage import untraced_reason
from ..core.graph import Diagnostic, Issue
from ..ir.model import CallSite
from ..ir.symbols import dotted_text
from ..knowledge import STATELESS_TRANSFORMERS
from .helpers import arg_ref, reaches, traced_arg
# The dataflow walks - including the three interprocedural ones R5 added - live
# next door. The three `@rule` entry points stay here, so `RuleSpec.module` (and
# every rule page that quotes it) is unchanged.
from .leakage_paths import (callee_fit_transform, fold_projection,
                            note_refused_split, split_after_return,
                            split_consuming)
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
        # REV5-01: the claim is confined to one scope, in **both** modes.
        # `_split_consuming` matches by dotted **name**, so without this a
        # `train_test_split` in any function of the module matched a
        # `fit_transform` in any other function purely because a local happened
        # to share a name - measured on `hydra_research`, where `features` is a
        # local in two different functions, and on a two-function file where
        # the emitted prose contradicted itself ("fitted at line 15, before the
        # split at line 8"). That is a high-severity `certain` false positive on
        # correct code in the shipped default mode: the one failure the product
        # cannot afford. The guard was written for the interprocedural case
        # only, to keep `--dataflow local` byte-identical by construction; the
        # defect it guards against was never interprocedural.
        #
        # A genuine cross-scope claim has to come back through DATAFLOW-IP's
        # provenance chain, where `hops()` de-rates it below `certain` and names
        # the hops it travelled.
        split = split_consuming(ctx, fit, splits, targets)
        returned_ref = None
        if split is None:
            # R5: the fit and the split are in different functions, and the
            # value crossed between them through a `return`. This is the whole
            # shape of a feature-engineering module - `build_matrix()` scales
            # the series, `walk_forward()` folds it - and it is exactly the
            # cross-object claim REV5-01 says must come back through
            # provenance rather than through a name match. It does: the split's
            # argument has to be bound by the very call to this function, at a
            # returned position the fitted value feeds.
            split, returned_ref = split_after_return(ctx, fit, splits, name, ref)
        if split is None:
            # IP-02: a value whose tag arrived interprocedurally, whose only
            # candidate split is in another scope, is not a clean result - it is
            # a refusal. `local` disclosed that gap through `ctx.untraced`
            # (the tag was absent there); `ip` resolved the tag and then dropped
            # the finding in silence, which is strictly less honest than the
            # mode it widens. Say so, exactly as 11.36 N5 makes the hop cap say
            # so.
            note_refused_split(ctx, fit, name, ref, splits)
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
        if returned_ref is not None:
            evidence.extend(ctx.hops(returned_ref))
            related.extend(ctx.hop_related(returned_ref))
            message = ("%s is fitted on %s at %s:%d, and the value it produces is "
                       "returned into %s:%d, where %s splits it - so the transformer "
                       "sees the held-out rows."
                       % (_label(fit), name, fit.loc.file, fit.loc.line,
                          split.loc.file, split.loc.line, split.short_name))
        else:
            message = ("%s is fitted on %s at %s:%d, before %s splits it at line %d, so "
                       "the transformer sees the held-out rows."
                       % (_label(fit), name, fit.loc.file, fit.loc.line,
                          split.short_name, split.loc.line))
        issues.append(ctx.issue(
            message=message,
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
        fold = None
        if ref is not None and ref.tags and not ref.has(*_HELD_OUT) \
                and not ref.has("TRAIN_SPLIT"):
            # R5: `fold_scaler.fit_transform(features[test_idx])`. The rows are
            # a *fold*, not a named split, so no tag ever says TEST_SPLIT - the
            # fact lives in the index: position 1 of the tuple a scikit-learn
            # splitter yields is the held-out half, by the splitter protocol.
            fold = fold_projection(ctx, fit)
            if fold is not None:
                name, ref = fold[0], fold[1]
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
        split = _split_producing(ref) if fold is None else fold[2]
        which = "TEST_SPLIT" if ref.has("TEST_SPLIT") else "VAL_SPLIT"
        by_dataflow = split is not None
        if fold is not None:
            detail = ("%s indexes the fold at position 1 of the tuple %s yields at "
                      "line %d, which is the held-out half"
                      % (name, _label(split), split.loc.line))
        elif by_dataflow:
            detail = "%s carries %s from the split at line %d" % (name, which,
                                                                  split.loc.line)
        else:
            detail = "%s carries %s by naming convention alone" % (name, which)
        evidence = [
            ("fqn_resolved", "%s resolved through the import table" % (fit.fqn or "fit"),
             1.0),
            ("dataflow_direct" if by_dataflow else "name_regex", detail,
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


#: Position 1 of the `(train, test)` tuple every scikit-learn cross-validator
#: yields. The protocol is fixed, so the position is a fact about the library
#: rather than a guess about the author's naming.
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
        hop_ref = None
        if fit is None:
            # R5: the fit is one `def` away. `features, target = build_matrix(p)`
            # then `cross_val_score(est, features, target)` is the commonest
            # spelling of this defect in a research repo, and the local pass
            # cannot see it because the two halves are in different functions.
            fit, hop_ref = callee_fit_transform(ctx, cv_call, data_name)
        if fit is None:
            continue
        if _already_reported(ctx, fit, cv_call):
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
        related = [("fit_site", fit.loc, "fitted once, outside the folds"),
                   ("call_site", cv_call.loc, "cross-validation runs here")]
        # 11.36 G6: a claim that crossed the object boundary pays one
        # IP_HOP_WEIGHT per hop and names the chain, so it can never be
        # `certain`; a claim established inside one scope pays nothing and
        # reads exactly as it did before this path existed.
        evidence.extend(ctx.hops(hop_ref))
        related.extend(ctx.hop_related(hop_ref))
        issues.append(ctx.issue(
            message="%s at %s:%d cross-validates a bare estimator over %s, which %s "
                    "already fitted on the whole set at line %d - the folds share its "
                    "statistics."
                    % (cv_call.short_name, cv_call.loc.file, cv_call.loc.line, data_name,
                       _label(fit), fit.loc.line),
            loc=cv_call.loc, node_ids=[node],
            related=related,
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


def _already_reported(ctx, fit: CallSite, cv_call: CallSite) -> bool:
    """MLV101 fired on the same transformer *in front of the same reader*.

    Never stack two findings on one statement - but MLV101 is anchored on the
    fit site and MLV103 on the cross-validation call, and since the fit may now
    be a `def` and a file away (`_callee_fit_transform`), "the same statement"
    has to mean the same file. A reader of `train.py` who is told nothing
    because `features.py` already carries an MLV101 has been told nothing about
    the folds, which is the only thing MLV103 exists to say.
    """
    for issue in ctx.issues:
        if issue.code == "MLV101" and issue.loc.file == fit.loc.file \
                and issue.loc.line == fit.loc.line \
                and issue.loc.file == cv_call.loc.file:
            return True
    return False
