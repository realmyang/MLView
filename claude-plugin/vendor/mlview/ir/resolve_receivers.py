"""Receiver -> candidate FQNs: the table walk behind every `obj.m(...)`.

`_canonical_for_receiver` is the whole of iron law 1's machinery: given the
`ValueRef` behind a receiver and the method spelled on it, it proposes an
ordered list of canonical FQNs, most specific first - the producer's own class,
the family the knowledge tables put that producer in, a torch `Module`'s
`__call__`, a data frame's method - and the resolver in `ir/resolve.py` takes
the first one a table knows.

Nothing here writes to a `CallSite`; it only answers "what could this name be?"
so that the pass which does write has one place to ask.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .. import knowledge as K
from .bindings import TENSOR_ROLES
from .model import ModuleIR, ScopeIR, ValueRef


#: Receiver bases for values that are plain data frames / arrays.
_FRAME_BASES = ("pandas.DataFrame", "pandas.Series", "numpy.ndarray")

_FAMILY_BASE = {
    "module": "torch.nn.Module",
    "loss": "torch.nn.Module",
    "optimizer": "torch.optim.Optimizer",
    "scheduler": "torch.optim.lr_scheduler.LRScheduler",
    "grad_scaler": "torch.amp.GradScaler",
    "tensor": "torch.Tensor",
    "estimator": "sklearn.base.BaseEstimator",
    "splitter": "sklearn.model_selection.BaseCrossValidator",
    "keras_model": "keras.Model",
    "hf_trainer": "transformers.Trainer",
    "lightning_trainer": "pytorch_lightning.Trainer",
    "argparse": "argparse.ArgumentParser",
    "loader": "torch.utils.data.DataLoader",
    "dataset": "torch.utils.data.Dataset",
    # FW-RECOG (11.23). Each of these is what carries a *chain*: the value the
    # previous link returned has no name to look up, so the family is the only
    # thing that says `.map` here is `tensorflow.data.Dataset.map`.
    "tf_dataset": "tensorflow.data.Dataset",
    "hf_dataset": "datasets.Dataset",
    "keras_dataset": "tensorflow.data.Dataset",
    "lightning_module": "pytorch_lightning.LightningModule",
    # INFRA-03 / INFRA-04 / TAB-01. Each of these is a wrapper object whose
    # methods *are* the pipeline: `learn.fine_tune(...)`, `engine.save_
    # checkpoint(...)`, `evaluator.run(...)`, `model.fit()` on a SARIMAX.
    # Without the family the method call resolves to nothing and the stage it
    # belongs to is declared absent on correct code.
    "fastai_learner": "fastai.learner.Learner",
    "deepspeed_engine": "deepspeed.DeepSpeedEngine",
    "ignite_evaluator": "ignite.engine.create_supervised_evaluator",
    "statsmodel": "statsmodels.api.SARIMAX",
    "prophet": "prophet.Prophet",
    # GRAPH-R2. A metric **object** is held across a loop and read once at the
    # end; with no base here `acc.update(...)` / `metric.compute()` proposed no
    # candidate at all, which is the whole point of holding one.
    "hf_metric": "evaluate.EvaluationModule",
    "torchmetric": "torchmetrics.Metric",
    "timm_scheduler": "timm.scheduler.CosineLRScheduler",
    "mixup": "timm.data.Mixup",
    # INFRA-R2-05 / PUB2-08. The two shapes whose *methods* are the pipeline
    # and whose constructor nobody writes: a TF2 `GradientTape`, a Keras
    # optimizer's `apply_gradients`, and the native boosting `Booster` that
    # `xgb.train(...)` / `lgb.train(...)` hand back.
    "accelerator": "accelerate.Accelerator",
    "fabric": "lightning.fabric.Fabric",
    "grad_tape": "tensorflow.GradientTape",
    "keras_optimizer": "keras.optimizers.Optimizer",
    "xgb_booster": "xgboost.Booster",
    "lgb_booster": "lightgbm.Booster",
}


def _class_scope(scope: ScopeIR) -> Optional[ScopeIR]:
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        if cur.kind == "class":
            return cur
        cur = cur.parent
    return None


# ---------------------------------------------------------------------------
# receiver resolution
# ---------------------------------------------------------------------------

def _local_lookup(module: ModuleIR, scope: ScopeIR, name: str):
    """A class or function defined in this module, visible from `scope`."""
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        qual = "%s.%s" % (cur.qualname, name)
        if qual in module.classes:
            return module.classes[qual], None
        if qual in module.functions:
            return None, module.functions[qual]
        cur = cur.parent
    return None, None


def _producer_entry(ref: ValueRef):
    if ref.via_fqns:
        entry, fqn = K.best_entry(ref.via_fqns)
        if entry is not None:
            return entry, fqn
    producer = ref.producer
    if producer is None:
        return None, None
    return K.best_entry(producer.canonical_fqns or ((producer.fqn,) if producer.fqn else ()))


def _family_of_ref(ref: ValueRef) -> Optional[str]:
    """Which receiver family this value belongs to (`module`, `tensor`, ...)."""
    entry, _fqn = _producer_entry(ref)
    if entry is not None and entry["role"] in TENSOR_ROLES:
        return "tensor"
    if ref.class_ir is not None:
        # FW-RECOG: a LightningModule answers to its own method surface first.
        # It *is* an nn.Module, so without this `self.log(...)` would resolve
        # through `torch.nn.` and prefix-match to role LAYER - a layer node in
        # the Model lane for a logging call, the same fabrication 11.19 A2 shut
        # down for `self.loss_fn`.
        if ref.class_ir.is_hook_owner:
            return "lightning_module"
        if ref.class_ir.is_nn_module:
            return "module"
        bases = ref.class_ir.resolved_bases
        if any(b.startswith("torch.utils.data.") for b in bases):
            return "dataset"
        if any(b.startswith("sklearn.") for b in bases):
            return "estimator"
    if entry is not None and entry["family"]:
        return entry["family"]
    if ref.has("LOSS", "LOGITS", "PROBS", "PREDS", "BATCH"):
        return "tensor"
    if ref.has("MODEL"):
        return "module"
    if ref.has("OPTIMIZER"):
        return "optimizer"
    if ref.has("LOADER"):
        return "loader"
    if ref.has("DEVICE"):
        return "device"
    if ref.has("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT", "VAL_SPLIT",
               "TEST_SPLIT"):
        return "frame"
    return None


def _is_class_like(entry, producer_fqn: str) -> bool:
    """May `<producer FQN>.<method>` name a real symbol?

    Only when the producer is a *class* (a knowledge row with a receiver
    family) and is not itself a method. `cross_val_score` is a plain function,
    so `sklearn.model_selection.cross_val_score.mean` does not exist - and the
    `sklearn.model_selection.` prefix rule would happily classify it as a
    `split` node in the Data lane (CONTRACTS section 1: `Node.fqn` is a
    "canonical third-party symbol").
    """
    if entry is None or not entry.get("family"):
        return False
    if entry["role"] in TENSOR_ROLES:
        return False
    return producer_fqn not in K.METHODS


#: Frameworks whose objects really are `torch.nn.Module` subclasses.
_TORCH_FRAMEWORKS = ("torch", "torchvision", "lightning", "hf", "torchmetrics")


def _is_torch_module(ref: ValueRef, entry, family: Optional[str], method: str) -> bool:
    """May `torch.nn.Module.<method>` be proposed for this receiver?

    The MODEL tag alone is not enough: an sklearn estimator carries it too, and
    `torch.nn.` prefix-matches *any* attribute, so an ungated candidate invents
    symbols like `torch.nn.Module.predict` - which then mislanes the node into
    the Model lane and adds a phantom `torch` framework to a pure-sklearn file.
    """
    if K.lookup_exact("torch.nn.Module.%s" % method) is not None:
        return True                  # a real nn.Module method, whoever the receiver is
    if ref.class_ir is not None and ref.class_ir.is_model_module:
        return True
    if family in ("module", "loss", "lightning_module") and entry is not None:
        if entry.get("framework") in _TORCH_FRAMEWORKS:
            return True
    return False


def _canonical_for_receiver(ref: ValueRef, method: str) -> Tuple[str, ...]:
    """`obj.m()` -> [<producer FQN>.m, <family base>.m, ...] in specificity order."""
    out: List[str] = []
    family = _family_of_ref(ref)
    entry, producer_fqn = _producer_entry(ref)
    tensor_like = family == "tensor"
    torch_module = _is_torch_module(ref, entry, family, method)

    if not tensor_like:
        if producer_fqn and _is_class_like(entry, producer_fqn):
            out.append("%s.%s" % (producer_fqn, method))
        elif ref.class_ir is not None:
            out.append("%s.%s" % (ref.class_ir.qualname, method))
    if ref.class_ir is not None:
        candidate = "%s.%s" % (ref.class_ir.qualname, method)
        if candidate not in out:
            out.append(candidate)

    # FW-RECOG. When the receiver's own workspace class **declares** this
    # method, a framework base may only be proposed for it if that base really
    # publishes the symbol. `def encode(self, x)` on an nn.Module subclass used
    # to produce `torch.nn.Module.encode`, which prefix-matches `torch.nn.` to
    # role LAYER and drew a layer node for a helper the framework never heard
    # of. `torch.nn.Module.forward` survives because it is an exact row; the
    # invented ones do not. Same iron law 1 as 11.19 A2, one level up.
    declared = (ref.class_ir is not None
                and method in (getattr(ref.class_ir, "methods", None) or {}))

    def add(candidate: str) -> None:
        if not candidate or candidate in out:
            return
        if declared and K.lookup_exact(candidate) is None:
            return
        out.append(candidate)

    if family == "frame":
        # A DataFrame / ndarray has no constructor to hang the method off, so
        # only *known* frame methods are proposed - never a fabricated symbol.
        for base in _FRAME_BASES:
            candidate = "%s.%s" % (base, method)
            if K.lookup_exact(candidate) is not None:
                add(candidate)
    base = _FAMILY_BASE.get(family or "")
    if base and (base != "torch.nn.Module" or torch_module):
        add("%s.%s" % (base, method))
    if family in ("estimator", "splitter"):
        add("sklearn.base.BaseEstimator.%s" % method)
    if ref.has("MODEL") and torch_module:
        add("torch.nn.Module.%s" % method)
    if ref.has("OPTIMIZER"):
        add("torch.optim.Optimizer.%s" % method)
    if tensor_like or ref.has("LOSS", "LOGITS", "PROBS", "PREDS", "BATCH"):
        add("torch.Tensor.%s" % method)

    seen: List[str] = []
    for fqn in out:
        if fqn and fqn not in seen:
            seen.append(fqn)
    return tuple(seen)
