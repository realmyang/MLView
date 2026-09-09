"""Framework rules (ANA-7): Keras, Lightning and HuggingFace `Trainer`.

MLV705 `fit()` with no `compile()` - MLV706 a manual gradient update inside a
Lightning `training_step` - MLV707 a `training_step` that returns no loss -
MLV708 a HuggingFace `Trainer` configured without evaluation - MLV709 a Keras
output activation contradicting a `from_logits=True` loss - MLV711 a
batch-cadence LR scheduler returned from `configure_optimizers` without
`{"interval": "step"}`.

**Why this tier exists.** The `negation_absent` gate (iron law 4) correctly
silences the torch loop rules on a framework project, and nothing replaced
them: the measured consequence was that a Keras project and a HuggingFace
project each published **zero** VS Code diagnostics, because their only finding
was MLV601 x `WRAPPER_FACTOR` 0.4 = 0.36, under the 0.6 panel default. None of
the rules here is an absence rule in the iron-law-3 sense and none opts into
the wrapper gate: the wrapper is the *subject* of the finding, not an excuse
for it.

**What these rules cannot analyze.** Every one of them is written against
literals and one level of workspace resolution, and each says so on its own
page: MLV705 is a workspace-wide claim and stays silent the moment any
`compile()` exists anywhere; MLV709 walks `compile()` back to the model its
receiver was built by and forward to the layer that model outputs (the walk
lives in `rules/keras_walk.py`), so a loss built in a shared `losses.py`, a
subclassed `keras.Model` with no functional `outputs=`, a builder more than one
hop from the `compile()` and a model compiled in another module are all
unjudged - and no layer is judged that is not the model's output; MLV706
and MLV707 need the class's base chain to resolve to a `LightningModule`, so a
module subclassing a project-local base that MLView could not follow is not
judged either. In each case the rule stays quiet rather than guessing.
"""

from __future__ import annotations

import ast
from typing import Dict, Iterable, List, Optional, Tuple

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, ClassIR, ModuleIR
from ..ir.symbols import dotted_text
from .keras_walk import (activation_literal as _activation_literal,
                         from_logits_loss as _from_logits_loss,
                         kwarg_literal as _kwarg_literal,
                         model_construction as _model_construction,
                         output_layers as _output_layers)
from .registry import rule

__all__ = ["keras_fit_without_compile", "lightning_manual_optimization",
           "lightning_training_step_without_loss", "hf_trainer_without_evaluation",
           "keras_activation_contradicts_from_logits",
           "lightning_step_scheduler_without_interval"]

# --------------------------------------------------------------------- shared
#: `Dense(activation=...)` literal -> the loss family it contradicts when that
#: loss was constructed with `from_logits=True`.
_ACTIVATION_LOSSES: Dict[str, Tuple[str, ...]] = {
    "softmax": ("CategoricalCrossentropy", "SparseCategoricalCrossentropy",
                "CategoricalFocalCrossentropy"),
    "sigmoid": ("BinaryCrossentropy", "BinaryFocalCrossentropy"),
}

#: Schedulers Lightning must be told to step per batch. `LRScheduler.step()` is
#: called once per **epoch** unless the returned config says otherwise, so a
#: OneCycle schedule silently runs its whole cycle in the first few epochs.
_BATCH_CADENCE = ("OneCycleLR", "CyclicLR", "get_linear_schedule_with_warmup",
                  "get_cosine_schedule_with_warmup",
                  "get_polynomial_decay_schedule_with_warmup",
                  "get_constant_schedule_with_warmup")


def _classes(ctx) -> List[Tuple[ModuleIR, ClassIR]]:
    """Every workspace class, in a stable order."""
    out: List[Tuple[ModuleIR, ClassIR]] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for name in sorted(module.classes):
            out.append((module, module.classes[name]))
    return out


def _hook_owners(ctx) -> List[Tuple[ModuleIR, ClassIR]]:
    """Classes whose methods are Lightning hooks (`LightningModule` bases)."""
    return [(m, c) for m, c in _classes(ctx) if c.is_hook_owner]


def _returns_of(func_node: ast.AST) -> List[ast.Return]:
    """Every `return` written in this function, not in a nested one."""
    out: List[ast.Return] = []
    stack: List[ast.AST] = list(getattr(func_node, "body", ()) or ())
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Lambda)):
            continue
        if isinstance(node, ast.Return):
            out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    out.sort(key=lambda n: (n.lineno, n.col_offset))
    return out


def _assigns_literal(node: ast.AST, attribute: str, literal) -> bool:
    """`self.<attribute> = <literal>` anywhere under `node`."""
    for child in ast.walk(node):
        if not isinstance(child, (ast.Assign, ast.AnnAssign)):
            continue
        targets = child.targets if isinstance(child, ast.Assign) else [child.target]
        for target in targets:
            if not isinstance(target, ast.Attribute) or target.attr != attribute:
                continue
            value = child.value
            if isinstance(value, ast.Constant) and value.value is literal:
                return True
    return False


def _calls_in(module: ModuleIR, node: ast.AST) -> List[CallSite]:
    """Every recorded call whose AST node lives under `node`."""
    wanted = {id(child) for child in ast.walk(node) if isinstance(child, ast.Call)}
    return [c for c in module.calls if id(c.node) in wanted]


def _short(call: CallSite) -> str:
    if call.receiver_name:
        return "%s.%s()" % (call.receiver_name, call.method or call.short_name)
    return "%s()" % call.short_name


def _anchor(ctx, call: CallSite):
    return ctx.node_for_call(call) or ctx.unit_for_call(call)





def _has_kwarg(call: CallSite, key: str) -> bool:
    node = call.kwarg_nodes.get(key)
    if node is None:
        return False
    return not (isinstance(node, ast.Constant) and node.value is None)


# ---------------------------------------------------------------------------
# MLV705
# ---------------------------------------------------------------------------
@rule(code="MLV705", severity="high", base_prior=0.95, frameworks=["keras", "tf"],
      rule_version=1, tags=["correctness", "framework"],
      title="Keras model is fitted without being compiled",
      why="An uncompiled model has no optimizer, no loss and no metrics, so the very "
          "first training call raises instead of training and the run dies at the "
          "moment somebody walks away from it.",
      fix_hint="Call model.compile(optimizer=..., loss=..., metrics=[...]) before "
               "model.fit(...), or load an already-compiled model with "
               "keras.models.load_model().")
def keras_fit_without_compile(ctx) -> Iterable[Issue]:
    """Deliberately a **workspace-wide** claim, exactly as MLV601 is.

    A `compile()` is routinely written in a builder module and the `fit()` in an
    entrypoint, and MLView cannot follow a model value across that boundary
    yet. Firing per binding would therefore accuse every two-file Keras project.
    So this fires only when the workspace contains **no** `compile()` at all -
    which is the shape that actually crashes - and stays silent otherwise.
    """
    fits = ctx.calls_with_role("KERAS_FIT")
    if not fits:
        return []
    if ctx.calls_with_role("KERAS_COMPILE"):
        return []
    if ctx.calls_with_role("KERAS_LOAD"):
        return []                       # a loaded model arrives already compiled
    fit = fits[0]
    node = _anchor(ctx, fit)
    evidence = [
        ("fqn_resolved", "%s resolved through the receiver family"
         % (fit.fqn or "keras.Model.fit"), 1.0),
        ("negation_absent",
         "no keras.Model.compile() anywhere in the %d analyzed module(s)"
         % len(ctx.modules), 1.0),
        ("knowledge_table",
         "Model.fit and Model.compile are both knowledge-table methods of the "
         "keras_model family", 1.0),
    ]
    if not fit.scope.is_dynamic:
        evidence.append(("scope_static",
                         "no dynamic constructs in %s" % fit.scope.qualname, 1.0))
    return [ctx.issue(
        message="%s at %s:%d trains a model that is never compiled - no compile() "
                "call exists anywhere in this workspace, so there is no optimizer "
                "and no loss to train with."
                % (_short(fit), fit.loc.file, fit.loc.line),
        loc=fit.loc, node_ids=[node] if node is not None else (),
        related=[("call_site", fit.loc, "fit() happens here")],
        evidence=evidence, stage="train", dynamic=fit.scope.is_dynamic)]


# ---------------------------------------------------------------------------
# MLV706
# ---------------------------------------------------------------------------
@rule(code="MLV706", severity="medium", base_prior=0.90, frameworks=["lightning"],
      rule_version=1, tags=["correctness", "framework", "train-loop"],
      title="Manual backward / step inside a Lightning training_step",
      why="Lightning already calls backward and steps the optimizer for you, so the "
          "gradients are applied twice per batch and the effective learning rate is "
          "silently doubled - or the run raises outright on the second backward.",
      fix_hint="Set self.automatic_optimization = False in __init__ and use "
               "self.manual_backward(loss) with self.optimizers(), or delete the "
               "manual backward()/step() and let Lightning drive.")
def lightning_manual_optimization(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for module, cls in _hook_owners(ctx):
        step = cls.methods.get("training_step")
        if step is None:
            continue
        if _assigns_literal(cls.node, "automatic_optimization", False):
            continue
        manual = [c for c in _calls_in(module, step.node)
                  if K.role_of(c.fqn) in ("BACKWARD", "OPT_STEP")]
        if not manual:
            continue
        first = min(manual, key=lambda c: (c.loc.line, c.loc.col))
        node = _anchor(ctx, first)
        evidence = [
            ("class_base", "%s resolves to a LightningModule (%s)"
             % (cls.name, ", ".join(cls.resolved_bases) or "no base resolved"), 1.0),
            ("fqn_resolved", "%s resolved to %s"
             % (_short(first), first.fqn or "a gradient call"), 1.0),
            ("negation_absent",
             "self.automatic_optimization = False is not set anywhere in %s"
             % cls.name, 1.0),
        ]
        if not step.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % step.qualname, 1.0))
        issues.append(ctx.issue(
            message="%s.training_step calls %s at %s:%d while automatic optimization "
                    "is still on, so Lightning applies the gradients a second time."
                    % (cls.name, _short(first), first.loc.file, first.loc.line),
            loc=first.loc, node_ids=[node] if node is not None else (),
            related=[("definition", step.loc, "training_step is defined here"),
                     ("backward_site", first.loc, "the manual update happens here")],
            evidence=evidence, stage="train", dynamic=step.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV707
# ---------------------------------------------------------------------------
def _dict_has_loss(node: ast.expr) -> Optional[bool]:
    """`True` / `False` for a dict literal, `None` when it is not one."""
    if not isinstance(node, ast.Dict):
        return None
    for key in node.keys:
        if isinstance(key, ast.Constant) and key.value == "loss":
            return True
        if key is None:                 # `{**other}` - unknowable, so not judged
            return None
    return False


@rule(code="MLV707", severity="medium", base_prior=0.90, frameworks=["lightning"],
      rule_version=1, tags=["correctness", "framework", "train-loop"],
      title="LightningModule.training_step does not return a loss",
      why="Lightning back-propagates whatever training_step hands back, so returning "
          "nothing means the batch is skipped: the loss curve is flat and the weights "
          "never move, with no error anywhere to explain it.",
      fix_hint="Return the loss tensor from training_step (or a dict with a 'loss' "
               "key), which is what Lightning calls backward() on.")
def lightning_training_step_without_loss(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for _module, cls in _hook_owners(ctx):
        step = cls.methods.get("training_step")
        if step is None:
            continue
        returns = _returns_of(step.node)
        values = [r.value for r in returns]
        if any(v is not None and _dict_has_loss(v) is not False
               and not (isinstance(v, ast.Constant) and v.value is None)
               for v in values):
            continue                    # at least one return may carry a loss
        if any(isinstance(r, ast.Yield) for r in ast.walk(step.node)):
            continue
        variant = ("no return statement" if not returns
                   else "every return yields None or a dict with no 'loss' key")
        node = _anchor(ctx, step.calls[0]) if step.calls else None
        evidence = [
            ("class_base", "%s resolves to a LightningModule (%s)"
             % (cls.name, ", ".join(cls.resolved_bases) or "no base resolved"), 1.0),
            ("context_confirmed",
             "training_step at line %d: %s" % (step.loc.line, variant), 1.0),
            ("negation_absent",
             "no return expression in training_step carries a loss", 1.0),
        ]
        if not step.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % step.qualname, 1.0))
        issues.append(ctx.issue(
            message="%s.training_step at %s:%d returns no loss (%s), so Lightning has "
                    "nothing to back-propagate and the batch is skipped."
                    % (cls.name, step.loc.file, step.loc.line, variant),
            loc=step.loc, node_ids=[node] if node is not None else (),
            related=[("definition", step.loc, "training_step is defined here")],
            evidence=evidence, stage="train", dynamic=step.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV708
# ---------------------------------------------------------------------------
_EVAL_STRATEGY_KEYS = ("eval_strategy", "evaluation_strategy")


def _args_have_eval_strategy(ctx, call: CallSite) -> Optional[bool]:
    """Does the `TrainingArguments` this Trainer was given ask for evaluation?

    `None` when the arguments could not be resolved at all - which is a reason
    to stay quiet, never a reason to fire.
    """
    node = call.kwarg_nodes.get("args")
    if node is None:
        return None
    name = dotted_text(node)
    producer = None
    if isinstance(node, ast.Call):
        producer = next((c for c in call.module.calls if c.node is node), None)
    elif name:
        ref = ctx.binding_of(name, call.scope)
        producer = ref.producer if ref is not None else None
    if producer is None or K.role_of(producer.fqn) != "HF_ARGS":
        return None
    for key in _EVAL_STRATEGY_KEYS:
        literal = _kwarg_literal(ctx, producer, key)
        if literal is not None and literal not in ("no", "None"):
            return True
    return False


@rule(code="MLV708", severity="medium", base_prior=0.85, frameworks=["hf"],
      rule_version=1, tags=["evaluation", "framework"],
      title="HuggingFace Trainer is configured without evaluation",
      why="With no eval_dataset and no evaluation strategy the run reports only the "
          "training loss, so overfitting is invisible and the checkpoint you keep is "
          "the last one rather than the best one.",
      fix_hint="Pass eval_dataset= to the Trainer and set eval_strategy=\"epoch\" on "
               "TrainingArguments, with compute_metrics= for anything but the loss.")
def hf_trainer_without_evaluation(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for call in ctx.calls_with_role("HF_TRAINER"):
        if _has_kwarg(call, "eval_dataset"):
            continue
        strategy = _args_have_eval_strategy(ctx, call)
        if strategy is not False:
            continue                    # asked for, or unresolvable: not judged
        node = _anchor(ctx, call)
        missing = ["eval_dataset"]
        if not _has_kwarg(call, "compute_metrics"):
            missing.append("compute_metrics")
        missing.append("eval_strategy")
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (call.fqn or "transformers.Trainer"), 1.0),
            ("negation_absent", "the Trainer sets none of: %s" % ", ".join(missing), 1.0),
            ("knowledge_table",
             "TrainingArguments resolved and declares no eval_strategy / "
             "evaluation_strategy", 1.0),
        ]
        if not call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % call.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="The Trainer at %s:%d has no eval_dataset and its TrainingArguments "
                    "set no evaluation strategy, so nothing is ever scored on held-out "
                    "data (missing: %s)."
                    % (call.loc.file, call.loc.line, ", ".join(missing)),
            loc=call.loc, node_ids=[node] if node is not None else (),
            related=[("construction", call.loc, "the Trainer is built here")],
            evidence=evidence, stage="eval", dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV709
# ---------------------------------------------------------------------------
@rule(code="MLV709", severity="high", base_prior=0.95, frameworks=["keras", "tf"],
      rule_version=1, tags=["correctness", "framework", "loss"],
      title="Keras output activation contradicts from_logits=True",
      why="The loss squashes the output a second time, so the gradients through an "
          "already-saturated activation are tiny and the model converges to a "
          "confident-looking constant instead of learning.",
      fix_hint="Remove activation= from the output Dense layer (return logits) or "
               "build the loss with from_logits=False - never both.")
def keras_activation_contradicts_from_logits(ctx) -> Iterable[Issue]:
    """Both operands are literals, so this is the cheapest high-confidence
    finding in the tier - and the pairing is scoped to **one model**, not to a
    module. Pairing by activation family alone accused a `models.py` holding a
    probs head and a logits head of the same categorical problem, and it
    accused an internal sigmoid gate of being an output activation; both are
    ordinary shapes, and both were reported at severity high, confidence 0.95.
    The walk is now `compile()` -> its receiver's `keras.Model(inputs, outputs)`
    -> the layer behind `outputs`, so the layer and the loss provably belong to
    the same model. Anything that walk cannot resolve is not judged.
    """
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for compile_call in module.calls:
            if K.role_of(compile_call.fqn) != "KERAS_COMPILE":
                continue
            pair = _from_logits_loss(ctx, compile_call)
            if pair is None:
                continue
            loss_call, loss_name = pair
            model_call = _model_construction(compile_call)
            if model_call is None:
                continue
            for call in _output_layers(ctx, model_call):
                activation = _activation_literal(ctx, call)
                wanted = _ACTIVATION_LOSSES.get(activation or "")
                if not wanted or loss_name not in wanted:
                    continue
                node = _anchor(ctx, call)
                evidence = [
                    ("fqn_resolved", "%s resolved to %s"
                     % (call.short_name, call.fqn or "a Keras layer"), 1.0),
                    ("dataflow_direct",
                     "%s at line %d is the outputs= of %s at line %d, and %s at line "
                     "%d is the loss= the same model is compiled with"
                     % (call.short_name, call.loc.line, model_call.short_name,
                        model_call.loc.line, loss_name, loss_call.loc.line), 1.0),
                    ("knowledge_table",
                     "%s is a knowledge-table Keras loss; from_logits=True declares that "
                     "its input is unnormalised" % loss_name, 1.0),
                ]
                if not call.scope.is_dynamic:
                    evidence.append(("scope_static",
                                     "no dynamic constructs in %s" % call.scope.qualname,
                                     1.0))
                issues.append(ctx.issue(
                    message="%s at %s:%d applies activation=\"%s\" to this model's "
                            "output, but %s at line %d was built with from_logits=True "
                            "and applies it again."
                            % (call.short_name, call.loc.file, call.loc.line, activation,
                               loss_name, loss_call.loc.line),
                    loc=call.loc, node_ids=[node] if node is not None else (),
                    related=[("final_layer", call.loc,
                              "the output activation is applied here"),
                             ("construction", loss_call.loc,
                              "%s(from_logits=True) is built here" % loss_name),
                             ("definition", model_call.loc,
                              "the layer and the loss meet on this model")],
                    evidence=evidence, stage="objective",
                    dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV711
# ---------------------------------------------------------------------------
def _interval_is_step(node: ast.AST) -> bool:
    """A `{"interval": "step"}` entry anywhere under `node`."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key, value in zip(child.keys, child.values):
            if not (isinstance(key, ast.Constant) and key.value == "interval"):
                continue
            if isinstance(value, ast.Constant) and value.value == "step":
                return True
    return False


def _batch_cadence_name(call: CallSite) -> Optional[str]:
    short = (call.fqn or call.short_name or "").rsplit(".", 1)[-1]
    return short if short in _BATCH_CADENCE else None


@rule(code="MLV711", severity="medium", base_prior=0.90, frameworks=["lightning"],
      rule_version=1, tags=["correctness", "framework", "train-loop"],
      title="Batch-cadence scheduler returned without interval=\"step\"",
      why="Lightning steps a returned scheduler once per epoch unless it is told "
          "otherwise, so a one-cycle schedule completes its whole cycle in the first "
          "few epochs and the remaining epochs train at the floor learning rate.",
      fix_hint="Return {\"optimizer\": opt, \"lr_scheduler\": {\"scheduler\": sched, "
               "\"interval\": \"step\"}} from configure_optimizers().")
def lightning_step_scheduler_without_interval(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for module, cls in _hook_owners(ctx):
        hook = cls.methods.get("configure_optimizers")
        if hook is None:
            continue
        if _interval_is_step(hook.node):
            continue
        schedulers = [(c, _batch_cadence_name(c)) for c in _calls_in(module, hook.node)]
        schedulers = [(c, n) for c, n in schedulers if n]
        if not schedulers:
            continue
        call, name = schedulers[0]
        node = _anchor(ctx, call)
        evidence = [
            ("class_base", "%s resolves to a LightningModule (%s)"
             % (cls.name, ", ".join(cls.resolved_bases) or "no base resolved"), 1.0),
            ("fqn_resolved", "%s resolved to %s" % (name, call.fqn or name), 1.0),
            ("negation_absent",
             "no {\"interval\": \"step\"} literal appears in configure_optimizers", 1.0),
        ]
        if not hook.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % hook.qualname, 1.0))
        issues.append(ctx.issue(
            message="%s.configure_optimizers returns %s (built at %s:%d) with no "
                    "{\"interval\": \"step\"}, so Lightning steps a per-batch schedule "
                    "once per epoch."
                    % (cls.name, name, call.loc.file, call.loc.line),
            loc=call.loc, node_ids=[node] if node is not None else (),
            related=[("construction", call.loc, "%s is built here" % name),
                     ("definition", hook.loc, "configure_optimizers is defined here")],
            evidence=evidence, stage="train", dynamic=hook.scope.is_dynamic))
    return issues
