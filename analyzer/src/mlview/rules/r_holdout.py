"""Held-out-integrity rules (ANA-9): is the number you are reading honest?

MLV106 a random split over apparently temporal data - MLV114 random augmentation
in the evaluation transform - MLV121 a tf.data `shuffle` feeding a `take` /
`skip` holdout - MLV305 a class metric computed on raw logits or probabilities -
MLV306 a ranking metric fed hard labels.

This is the class no general-purpose linter touches: none of these is a syntax
error, every one of them produces a number that looks fine and is wrong.
MLV121 is the extreme case - `shuffle(1024)` before `take()` / `skip()`
reshuffles on every epoch, so the training and validation halves swap rows every
pass and the holdout stops existing.

**What these rules cannot analyze.**

* **MLV305** needs the prediction value to carry `LOGITS` or `PROBS`. A
  prediction produced by a helper function looks unproduced to a
  flow-insensitive IR, so the finding is **de-rated** (evidence weight 0.6)
  rather than dropped, and the score-metric carve-out
  (`roc_auc_score`, `average_precision_score`, `log_loss` and the rest of
  `_SCORE_METRICS`) is exhaustive and checked twice: those metrics legitimately
  take scores and this rule never fires on one.
* **MLV106** requires **two independent** temporal signals in the same module.
  The catalog sketch allowed a single signal at x0.6; ANA-12 forbids spending
  precision on a guess, so one signal is silence here.
* **MLV114** requires the augmenting `Compose` to reach an evaluation loader
  **directly** - transform to dataset to loader. An augmented dataset that is
  later `random_split` into a training and a validation half is not judged: the
  analyzer cannot tell which half inherits what, and saying so is better than
  guessing (this is exactly the shape `samples/vision_pipeline` writes).
* **MLV121** follows the tf.data receiver chain through at most eight links,
  and only through names it can bind. A dataset rebuilt inside a helper is not
  judged, and a **holdout must be visible before the rule describes one**: the
  same shuffled receiver has to reach both a `take` and a `skip`, or the subset
  has to be bound to an evaluation name. A lone `take` is a peek - `for images,
  labels in train_ds.take(1)` is the commonest line in TensorFlow code - and
  calling it a leaking train/val split was a statement about code that does not
  exist. A holdout whose two halves come off *different* `shuffle` calls is
  judged only by the name test.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite
from ..ir.symbols import dotted_text
from .helpers import (KWARG_ABSENT, KWARG_RESOLVED, UNRESOLVED_KWARG_WEIGHT,
                      kwarg_literal, literal_of, note_unresolved_kwarg)
from .registry import rule

from .holdout_scores import (_decided, _prediction_arg, _scored_value,
                             scored_value)
from .holdout_splits import (_HOLDOUT_PAIR, _augmenting_pipelines, _eval_loaders,
                             _holdout_of, _subset_name, _temporal_signals,
                             _upstream)
from .holdout_tables import (_CLASS_METRICS, _RANKING_METRICS, _SCORE_METRICS,
                             _anchor, _element_calls, _short, _static)

__all__ = ["random_split_on_temporal_data", "augmentation_in_eval_transform",
           "tfdata_shuffle_before_holdout", "metric_on_raw_scores",
           "ranking_metric_on_hard_labels"]


# ---------------------------------------------------------------------------
# MLV106
# ---------------------------------------------------------------------------
@rule(code="MLV106", severity="medium", base_prior=0.70, frameworks=["sklearn", "pandas"],
      rule_version=1, tags=["leakage", "data"],
      title="Random split used on apparently temporal data",
      why="A shuffled split puts tomorrow's rows in the training half and yesterday's "
          "in the test half, so the model is scored on interpolating a series it has "
          "already seen the future of and the reported error is optimistic.",
      fix_hint="Use TimeSeriesSplit(n_splits=...) or a chronological cut "
               "(train = df[df.date < cutoff]) instead of a shuffled split.")
def random_split_on_temporal_data(ctx) -> Iterable[Issue]:
    """Phrased as a question, and it takes **two** independent signals to ask
    it: one is a coincidence in any dataset that happens to carry a date."""
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        signals = _temporal_signals(ctx, module)
        if len(signals) < 2:
            continue
        for call in module.calls:
            if K.role_of(call.fqn) != "SPLIT":
                continue
            shuffle = literal_of(ctx, call.kwarg_nodes.get("shuffle"), call.scope, module)
            if shuffle == "False":
                continue
            node = _anchor(ctx, call)
            weight = 1.0 if len(signals) > 2 else 0.8
            evidence = [
                ("fqn_resolved", "%s resolved to %s"
                 % (call.short_name, call.fqn or "a split"), 1.0),
                ("context_confirmed",
                 "%d independent temporal signals in %s: %s"
                 % (len(signals), relpath, "; ".join(signals[:3])), weight),
                ("negation_absent",
                 "the split does not pass shuffle=False", 1.0),
            ] + _static(call.scope)
            issues.append(ctx.issue(
                message="%s at %s:%d shuffles rows that look like a time series (%s). "
                        "Is a random split what you meant here?"
                        % (_short(call), call.loc.file, call.loc.line,
                           "; ".join(signals[:2])),
                loc=call.loc, node_ids=[node] if node is not None else (),
                related=[("split_site", call.loc, "the shuffled split happens here")],
                evidence=evidence, stage="data", dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV114
# ---------------------------------------------------------------------------
@rule(code="MLV114", severity="medium", base_prior=0.90,
      frameworks=["torchvision", "torch"],
      rule_version=1, tags=["evaluation", "data"],
      title="Random augmentation in the evaluation transform pipeline",
      why="Every evaluation pass sees differently cropped and flipped images, so the "
          "validation curve moves for reasons that have nothing to do with the model "
          "and the score is systematically worse than the model deserves.",
      fix_hint="Give the evaluation dataset its own Compose with only the "
               "deterministic steps (Resize / CenterCrop / ToTensor / Normalize).")
def augmentation_in_eval_transform(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        pipelines = _augmenting_pipelines(ctx, module)
        if not pipelines:
            continue
        loaders = _eval_loaders(ctx, module)
        if not loaders:
            continue
        for loader in loaders:
            dataset_node = loader.args[0] if loader.args \
                else loader.kwarg_nodes.get("dataset")
            name = dotted_text(dataset_node) if dataset_node is not None else None
            ref = ctx.binding_of(name, loader.scope) if name else None
            producer = ref.producer if ref is not None else None
            if producer is None or K.role_of(producer.fqn) != "DATASET":
                continue
            hit = None
            for key in ("transform", "transforms", "target_transform"):
                node = producer.kwarg_nodes.get(key)
                text = dotted_text(node) if node is not None else None
                if text and text.split(".")[-1] in pipelines:
                    hit = (key, pipelines[text.split(".")[-1]], text)
                    break
            if hit is None:
                continue
            key, compose, text = hit
            augments = [e for e in _element_calls(module, compose)
                        if K.role_of(e.fqn) == "AUGMENT"]
            anchor = _anchor(ctx, compose)
            evidence = [
                ("fqn_resolved", "%s resolved to %s"
                 % (text, compose.fqn or "a transform pipeline"), 1.0),
                ("dataflow_direct",
                 "%s -> %s(%s=) at line %d -> %s at line %d"
                 % (text, producer.short_name, key, producer.loc.line,
                    loader.var or "an evaluation loader", loader.loc.line), 1.0),
                ("knowledge_table",
                 "the pipeline contains %s, whose role is AUGMENT"
                 % ", ".join(sorted({a.short_name for a in augments})), 1.0),
            ] + _static(compose.scope)
            issues.append(ctx.issue(
                message="%s at %s:%d applies random augmentation (%s) and reaches the "
                        "evaluation loader %s at line %d through %s."
                        % (text, compose.loc.file, compose.loc.line,
                           ", ".join(sorted({a.short_name for a in augments})),
                           loader.var or "a DataLoader", loader.loc.line,
                           producer.short_name),
                loc=compose.loc, node_ids=[anchor] if anchor is not None else (),
                related=[("construction", producer.loc,
                          "the evaluation dataset is built here"),
                         ("eval_loop", loader.loc, "and served by this loader")],
                evidence=evidence, stage="preprocess",
                dynamic=compose.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV121
# ---------------------------------------------------------------------------
@rule(code="MLV121", severity="high", base_prior=0.95, frameworks=["tf", "keras"],
      rule_version=1, tags=["leakage", "data"],
      title="tf.data shuffle feeds a take/skip holdout",
      why="tf.data reshuffles the buffer on every epoch by default, so take() and "
          "skip() carve out a different training and validation half each pass: every "
          "validation row has been trained on by epoch two and the holdout has stopped "
          "existing.",
      fix_hint="Pass reshuffle_each_iteration=False to shuffle(), or split with "
               "take()/skip() first and shuffle only the training half afterwards.")
def tfdata_shuffle_before_holdout(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    reached: Dict[int, List[CallSite]] = {}
    order: List[CallSite] = []
    for holdout in ctx.calls_with_role("TFDATA_SUBSET"):
        for shuffle in _upstream(holdout.module, holdout):
            if K.role_of(shuffle.fqn) != "TFDATA_SHUFFLE":
                continue
            if id(shuffle) not in reached:
                reached[id(shuffle)] = []
                order.append(shuffle)
            reached[id(shuffle)].append(holdout)
            break
    for shuffle in order:
        # ANA-01: three states, three answers. `reshuffle_each_iteration=False`
        # is not a leak; an unwritten keyword really does default to True; and a
        # keyword whose value the analyzer cannot read is neither of those. It
        # used to take the *absent* branch, so a `reshuffle_each_iteration=
        # get_flag()` published, at severity high and confidence certain, an
        # evidence entry reading "shuffle() does not pass
        # reshuffle_each_iteration=False" about the very line it points at.
        state, literal = kwarg_literal(ctx, shuffle, "reshuffle_each_iteration")
        if state == KWARG_RESOLVED and literal == "False":
            continue
        found = _holdout_of(shuffle.module, reached[id(shuffle)])
        if found is None:
            continue
        holdout, why = found
        node = _anchor(ctx, shuffle)
        if state == KWARG_ABSENT:
            reshuffle = ("negation_absent",
                         "shuffle() does not pass reshuffle_each_iteration=False", 1.0)
            claim = ("and reshuffle_each_iteration defaults to True, so the two "
                     "halves are re-drawn every epoch")
        elif state == KWARG_RESOLVED:
            reshuffle = ("context_confirmed",
                         "shuffle() passes reshuffle_each_iteration=%s" % literal, 1.0)
            claim = ("and reshuffle_each_iteration=%s, so the two halves are "
                     "re-drawn every epoch" % literal)
        else:
            reshuffle = ("context_confirmed",
                         "reshuffle_each_iteration is passed at line %d but its "
                         "value could not be resolved statically, so whether the "
                         "halves are re-drawn is unknown" % shuffle.loc.line,
                         UNRESOLVED_KWARG_WEIGHT)
            claim = ("and reshuffle_each_iteration is passed an expression MLView "
                     "could not resolve - if it is not False the two halves are "
                     "re-drawn every epoch")
            note_unresolved_kwarg(
                ctx, shuffle, "reshuffle_each_iteration",
                "the take()/skip() holdout is only re-drawn every epoch when it is not False")
        evidence = [
            ("fqn_resolved", "%s resolved to %s"
             % (_short(shuffle), shuffle.fqn or "Dataset.shuffle"), 1.0),
            ("dataflow_direct",
             "the shuffled dataset reaches %s at line %d through the tf.data "
             "receiver chain, and %s" % (_short(holdout), holdout.loc.line, why), 1.0),
            reshuffle,
        ] + _static(shuffle.scope)
        related = [("split_site", holdout.loc, "the holdout is carved out here"),
                   ("call_site", shuffle.loc, "the shuffle happens here")]
        for other in reached[id(shuffle)]:
            if other is not holdout and _subset_name(other) in _HOLDOUT_PAIR:
                related.append(("split_site", other.loc,
                                "and the other half is taken here"))
                break
        issues.append(ctx.issue(
            message="%s at %s:%d shuffles before %s at line %d carves out the "
                    "holdout, %s."
                    % (_short(shuffle), shuffle.loc.file, shuffle.loc.line,
                       _short(holdout), holdout.loc.line, claim),
            loc=shuffle.loc, node_ids=[node] if node is not None else (),
            related=related,
            evidence=evidence, stage="data", dynamic=shuffle.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV305
# ---------------------------------------------------------------------------
@rule(code="MLV305", severity="medium", base_prior=0.85,
      frameworks=["sklearn", "torch"],
      rule_version=1, tags=["evaluation", "correctness"],
      title="Class metric computed on raw scores instead of predicted classes",
      why="accuracy_score compares floats to integer labels, so the reported accuracy "
          "is roughly the chance rate no matter how good the model is - and it is a "
          "number, not an error, so nobody notices.",
      fix_hint="Take the class first: preds = logits.argmax(axis=1) (or a 0.5 "
               "threshold for a binary head), then pass preds to the metric.")
def metric_on_raw_scores(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for call in module.calls:
            fqn = call.fqn or ""
            if fqn in _SCORE_METRICS or fqn not in _CLASS_METRICS:
                continue                # the carve-out, checked before anything else
            node = _prediction_arg(call)
            if node is None:
                continue
            tags, producer, name, scored_ref = scored_value(ctx, call, node)
            decided = _decided(ctx, node, call)
            if not ({"LOGITS", "PROBS"} & set(tags)):
                # A value that is visibly argmaxed / rounded / thresholded is
                # *checked*, not untraced: noting it would make every correct
                # program carry a coverage diagnostic (11.18 acceptance).
                if name and not tags and not decided:
                    ctx.untraced(call, name,
                                 "the prediction argument carries no LOGITS / PROBS "
                                 "tag, so MLV305 could not tell scores from classes")
                continue
            if decided:
                continue
            anchor = _anchor(ctx, call)
            weight = 1.0 if producer is not None else 0.6
            detail = ("%s is produced by %s" % (name, producer.fqn or producer.short_name)
                      if producer is not None
                      else "%s carries %s but its producer is outside this scope, so "
                           "the finding is de-rated" % (name, "/".join(sorted(tags))))
            evidence = [
                ("fqn_resolved", "%s resolved to %s" % (call.short_name, fqn), 1.0),
                ("dataflow_direct", detail, weight),
                ("negation_absent",
                 "no argmax / round / threshold / topk between the model output and "
                 "the metric", 1.0),
                ("knowledge_table",
                 "%s takes class predictions; the score metrics (%s) are carved out "
                 "and never judged" % (call.short_name, "roc_auc_score, "
                                       "average_precision_score, log_loss"), 1.0),
            ] + _static(call.scope)
            # 11.36 G6: only a value this rule had to fetch out of a callee
            # carries a chain, and only that finding pays for it.
            evidence.extend(ctx.hops(scored_ref))
            related = [("call_site", call.loc, "the metric is computed here")]
            if producer is not None:
                related.append(("construction", producer.loc,
                                "%s is produced here" % name))
            related.extend(ctx.hop_related(scored_ref))
            issues.append(ctx.issue(
                message="%s at %s:%d scores %s, which carries %s rather than class "
                        "predictions, so it compares continuous values with integer "
                        "labels."
                        % (call.short_name, call.loc.file, call.loc.line, name,
                           "/".join(sorted({t for t in tags if t in ("LOGITS", "PROBS")}))),
                loc=call.loc, node_ids=[anchor] if anchor is not None else (),
                related=related, evidence=evidence, stage="eval",
                dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV306
# ---------------------------------------------------------------------------
@rule(code="MLV306", severity="low", base_prior=0.90, frameworks=["sklearn"],
      rule_version=1, tags=["evaluation", "correctness"],
      title="Ranking metric fed hard labels",
      why="ROC AUC over 0/1 predictions collapses to a two-point curve, so the number "
          "you report is balanced accuracy wearing an AUC label and it hides exactly "
          "the threshold behaviour AUC exists to show.",
      fix_hint="Pass scores: roc_auc_score(y_true, clf.predict_proba(X)[:, 1]) or "
               "clf.decision_function(X).")
def ranking_metric_on_hard_labels(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for call in module.calls:
            if (call.fqn or "") not in _RANKING_METRICS:
                continue
            node = _prediction_arg(call)
            if node is None:
                continue
            tags, producer, name, scored_ref = scored_value(ctx, call, node)
            if producer is None or "PREDS" not in tags:
                continue
            role = K.role_of(producer.fqn)
            if role not in ("PREDICT", "ARGMAX"):
                continue
            anchor = _anchor(ctx, call)
            source = "predict()" if role == "PREDICT" else (
                producer.fqn or producer.short_name)
            evidence = [
                ("fqn_resolved", "%s resolved to %s" % (call.short_name, call.fqn), 1.0),
                ("dataflow_direct",
                 "%s comes from %s, whose knowledge-table tag is PREDS"
                 % (name, producer.fqn or "predict()"), 1.0),
                ("knowledge_table",
                 "predict_proba carries PROBS and decision_function carries LOGITS; "
                 "neither was used here", 1.0),
            ] + _static(call.scope)
            evidence.extend(ctx.hops(scored_ref))
            related = [("call_site", call.loc, "the ranking metric is computed here"),
                       ("construction", producer.loc,
                        "%s is produced by %s here" % (name, source))]
            related.extend(ctx.hop_related(scored_ref))
            issues.append(ctx.issue(
                message="%s at %s:%d ranks %s, which comes from %s and holds "
                        "hard class labels rather than scores."
                        % (call.short_name, call.loc.file, call.loc.line, name, source),
                loc=call.loc, node_ids=[anchor] if anchor is not None else (),
                related=related,
                evidence=evidence, stage="eval", dynamic=call.scope.is_dynamic))
    return issues
