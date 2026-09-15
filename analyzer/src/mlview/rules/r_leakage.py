"""Leakage rules: MLV101 (fit before split), MLV102 (fit on held-out),
MLV103 (preprocessing outside cross-validation)."""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional

from .. import knowledge as K
from ..core.coverage import untraced_reason
from ..core.graph import Issue
from ..ir.model import CallSite
from ..ir.symbols import dotted_text
from ..knowledge import STATELESS_TRANSFORMERS
from .helpers import arg_ref, reaches, traced_arg
from .leakage_paths import (_callee_fit_transform, _fold_projection,
                            _note_refused_split, _semi_supervised,
                            _split_after_return, _split_consuming,
                            _split_producing)
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
        # ROB-10 / PUB-02. `sklearn.base.BaseEstimator.fit` carries the role
        # FIT, so EVERY estimator fit was an MLV101 candidate - and the second
        # half of the rule accepts a cross-validator's `.split()` as "the
        # train/test split", so `final.fit(X, y)` after a `KFold` loop, and
        # `GridSearchCV(...).fit(X, y)` (which refits inside every fold), were
        # reported high / 0.95 on correct code. That shape is 13 of the 13
        # high-severity findings MLView produces on scikit-learn's own source.
        # ISSUE_RULES section 3 scopes this rule to the five preprocessing
        # namespaces; the implementation kept the roles and dropped the
        # namespaces. A transformer is what this rule is about.
        if not _is_transformer_fit(ctx, fit):
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
        split = _split_consuming(ctx, fit, splits, targets)
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
            split, returned_ref = _split_after_return(ctx, fit, splits, name, ref)
        if split is None:
            # IP-02: a value whose tag arrived interprocedurally, whose only
            # candidate split is in another scope, is not a clean result - it is
            # a refusal. `local` disclosed that gap through `ctx.untraced`
            # (the tag was absent there); `ip` resolved the tag and then dropped
            # the finding in silence, which is strictly less honest than the
            # mode it widens. Say so, exactly as 11.36 N5 makes the hop cap say
            # so.
            _note_refused_split(ctx, fit, name, ref, splits)
            continue
        node = ctx.node_for_call(fit) or ctx.unit_for_call(fit)
        if node is None:
            continue
        split_node = ctx.node_for_call(split)
        # PUB-04. FP-note (c) de-rates a fit on the target alone - the
        # `LabelEncoder().fit(y)` case - to medium x0.6, and the guard was
        # keyed on a dataflow TARGET tag that a pandas column subscript never
        # acquires, so the commonest spelling of the very pattern the note
        # exists for kept full `high`. The literal column key is reinforcing
        # evidence in the iron-law-2 sense: it cannot create a finding, it only
        # de-rates one that already exists.
        target_only = (ref.has("TARGET") and not ref.has("FEATURES")) \
            or _target_column(fit)
        evidence = [
            ("fqn_resolved", "%s resolved through the import table" % (fit.fqn or "fit"), 1.0),
            ("dataflow_direct",
             ("the value %s produces is returned into %s:%d, where %s reads it"
              % (name, split.loc.file, split.loc.line, split.short_name))
             if returned_ref is not None else
             ("%s flows into %s at line %d"
              % (name, split.short_name, split.loc.line)), 1.0),
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
        #
        # ONE ref, never both: R5's `_split_after_return` builds its chain by
        # `extend`ing the fit's own, so `returned_ref` already contains every
        # hop `ref` has plus the `return`. Charging both would pay for the
        # first hop twice - 0.8 x 0.64 rather than 0.64 - and print its
        # construction site twice in `relatedLocs`.
        hop_ref = returned_ref if returned_ref is not None else ref
        evidence.extend(ctx.hops(hop_ref))
        related = [
            ("fit_site", fit.loc, "fitted on the full dataset here"),
            ("split_site", split.loc, "split happens later, at line %d" % split.loc.line),
        ]
        related.extend(ctx.hop_related(hop_ref))
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
            severity="medium" if target_only else None,
            dynamic=fit.scope.is_dynamic))
    return issues


#: PUB-04. A column key that names the target, for the FP-note (c) de-rate.
_TARGET_KEY_RE = re.compile(r"(?i)^(label|labels|target|targets|y|class|classes|"
                            r"outcome|category)$")


def _target_column(fit: CallSite) -> bool:
    """`le.fit(df["label"])` - a fit on a single target column, by its key."""
    if not fit.args:
        return False
    node = fit.args[0]
    if not isinstance(node, ast.Subscript):
        return False
    key = node.slice
    return bool(isinstance(key, ast.Constant) and isinstance(key.value, str)
                and _TARGET_KEY_RE.match(key.value))


#: The stages a knowledge row must sit in for its `.fit()` to be a
#: *preprocessing* fit. ISSUE_RULES section 3 names the five sklearn namespaces;
#: every one of them lands in the `preprocess` stage, and nothing else does.
_TRANSFORMER_STAGES = ("preprocess",)


def _is_transformer_fit(ctx, fit: CallSite) -> bool:
    """Is this `.fit()` fitting a *transformer*, rather than a model? (ROB-10)

    `fit_transform` is a transformer method by definition and keeps its role.
    A bare `.fit()` has to be attributed: the receiver's constructor decides,
    and a receiver that resolves to nothing is not evidence of a transformer -
    the honest answer there is silence, which is what `ctx.untraced` below
    already records for the argument side.
    """
    for fqn in fit.canonical_fqns or ():
        if K.role_of(fqn) == "FIT_TRANSFORM":
            return True
    ref = fit.receiver
    producer = ref.producer if ref is not None else None
    candidates: List[str] = []
    if producer is not None:
        candidates.extend(producer.canonical_fqns or ())
        if producer.fqn:
            candidates.append(producer.fqn)
    if ref is not None:
        candidates.extend(getattr(ref, "via_fqns", ()) or ())
    entry, _which = K.best_entry(candidates)
    if entry is None:
        return False
    if entry["role"] in ("CV_SEARCH", "PIPELINE", "ESTIMATOR", "MODEL_FACTORY"):
        return False
    return entry["stage"] in _TRANSFORMER_STAGES


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
        # PUB-14, the MLV102 half of ROB-10 / PUB-02. `sklearn.base.
        # BaseEstimator.fit` carries the role FIT, so an *estimator* refitted on
        # the other half of a split was an MLV102 candidate. On the
        # PythonDataScienceHandbook's `05.03-Hyperparameters-and-Model-
        # Validation.ipynb`, cell 16 is hand-rolled two-fold cross-validation -
        #
        #     y2_model = model.fit(X1, y1).predict(X2)
        #     y1_model = model.fit(X2, y2).predict(X1)
        #
        # - and MLView reported the second line high / `certain` 0.97, calling a
        # `KNeighborsClassifier` "the transformer" and saying "the held-out
        # score is not an estimate of unseen-data performance at all" about a
        # model whose score is computed on the half it was never fitted on. Both
        # statements are false, on one of the most-read notebooks in the corpus.
        # This rule's title, `why` and `fix_hint` are all about a transformer,
        # every `expected` MLV102 label in the labelled corpus is a
        # `fit_transform` on a transformer, and MLV101 has answered exactly this
        # question since ROB-10 - so it is answered here with the same function
        # rather than a second mechanism.
        if not _is_transformer_fit(ctx, fit):
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
            fold = _fold_projection(ctx, fit)
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
            fit, hop_ref = _callee_fit_transform(ctx, cv_call, data_name)
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
            loc=cv_call.loc, node_ids=[node], related=related,
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
