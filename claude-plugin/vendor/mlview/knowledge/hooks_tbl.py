"""The Lightning hook table and the `LightningModule` method surface (FW-RECOG).

A `LightningModule` never calls its own hooks: `Trainer.fit(model, ...)` calls
them. MLView therefore saw a Lightning file as a class with some unreachable
methods - `training_step`, `validation_step`, `configure_optimizers` and
`F.cross_entropy` produced **zero** nodes and the stage line read *"not
detected: preprocess, objective, eval, deliver"* on a **correct** program. That
is the actively-misleading end of the honesty problem, not the thin end.

Two tables live here.

**`HOOK_STAGES` / `hook_stage()`** map a framework hook *method name* to the
stage its body belongs in. `core/hooks.py` turns each recognised hook into its
own unit node under the class, so the ops written in it land in the right lane
and `Trainer.fit` can point a `control` edge at them.

`on_*_epoch_*` and the other lifecycle hooks are described in ROADMAP FW-RECOG
as *control*. `StageId` is a frozen eight-value enum with no `control` member,
and inventing one is not on the table, so **control is expressed as it always
has been - by the `control` edge `Trainer.fit` draws into the hook** - and the
hook itself is staged by the phase its own name declares
(`on_train_epoch_end` -> train, `on_validation_epoch_end` -> eval). The role
`LIGHTNING_HOOK_CONTROL` records that the hook is lifecycle rather than
pipeline, for the rules that will want to know.

**`LIGHTNING_METHOD_ENTRIES`** pins the `LightningModule` methods that are not
hooks. Every one of them exists for the same reason: a `LightningModule` *is*
an `nn.Module`, so `ir/resolve` proposes `torch.nn.Module.<attr>` for its
methods, and `torch.nn.` prefix-matches **anything** - `self.log(...)` resolved
to role `LAYER` and drew a layer node in the Model lane for a logging call.
Pinning the real methods is what stops a symbol nobody declared being invented,
exactly as CONTRACTS 11.19 A2 did for `self.loss_fn`.

`log` / `log_dict` / `save_hyperparameters` and the lifecycle helpers are
deliberately given roles that are **not** in `knowledge.OP_ROLES`: they are
recognised so nothing is fabricated for them, and not drawn, because a training
step logs five scalars and five metric cards in the Save lane is noise, not
recognition. `manual_backward` **is** drawn - it is a real gradient update, and
the rule tier that judges manual optimisation (ANA-7) needs it in the graph.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from .entries import E, Entry

__all__ = ["LIGHTNING_ROOTS", "HOOK_STAGES", "HOOK_OWNER_BASES", "hook_stage",
           "LIGHTNING_METHOD_ENTRIES", "LIGHTNING_HOOK_ROLES"]

L = "lightning"

#: Every import root the same class is published under.
LIGHTNING_ROOTS = ("pytorch_lightning", "lightning", "lightning.pytorch")

#: Classes whose methods are framework hooks rather than ordinary methods.
HOOK_OWNER_BASES = frozenset(
    ["%s.%s" % (root, name)
     for root in LIGHTNING_ROOTS
     for name in ("LightningModule", "LightningDataModule")])

#: hook method name -> (stage, role, why)
HOOK_STAGES: Dict[str, Tuple[str, str, str]] = {
    "forward": ("model", "LIGHTNING_HOOK_MODEL",
                "forward() is the module's own computation"),
    "training_step": ("train", "LIGHTNING_HOOK_TRAIN",
                      "training_step() is the body Trainer.fit runs per batch"),
    "training_step_end": ("train", "LIGHTNING_HOOK_TRAIN",
                          "training_step_end() closes the training batch"),
    "training_epoch_end": ("train", "LIGHTNING_HOOK_TRAIN",
                           "training_epoch_end() closes the training epoch"),
    "validation_step": ("eval", "LIGHTNING_HOOK_EVAL",
                        "validation_step() is the held-out evaluation body"),
    "validation_step_end": ("eval", "LIGHTNING_HOOK_EVAL",
                            "validation_step_end() closes the validation batch"),
    "validation_epoch_end": ("eval", "LIGHTNING_HOOK_EVAL",
                             "validation_epoch_end() closes the validation epoch"),
    "test_step": ("eval", "LIGHTNING_HOOK_EVAL",
                  "test_step() is the test-set evaluation body"),
    "predict_step": ("eval", "LIGHTNING_HOOK_EVAL",
                     "predict_step() is the inference body"),
    "configure_optimizers": ("objective", "LIGHTNING_HOOK_OBJECTIVE",
                             "configure_optimizers() declares what is optimised"),
    "train_dataloader": ("data", "LIGHTNING_HOOK_DATA",
                         "train_dataloader() supplies the training data"),
    "val_dataloader": ("data", "LIGHTNING_HOOK_DATA",
                       "val_dataloader() supplies the validation data"),
    "test_dataloader": ("data", "LIGHTNING_HOOK_DATA",
                        "test_dataloader() supplies the test data"),
    "predict_dataloader": ("data", "LIGHTNING_HOOK_DATA",
                           "predict_dataloader() supplies the inference data"),
    "prepare_data": ("data", "LIGHTNING_HOOK_DATA",
                     "prepare_data() downloads / materialises the dataset"),
    "setup": ("data", "LIGHTNING_HOOK_DATA",
              "setup() builds the splits the dataloaders serve"),
    "teardown": ("data", "LIGHTNING_HOOK_DATA", "teardown() releases the dataset"),
    "transfer_batch_to_device": ("data", "LIGHTNING_HOOK_DATA",
                                 "transfer_batch_to_device() moves a batch"),
    "on_after_batch_transfer": ("preprocess", "LIGHTNING_HOOK_DATA",
                                "on_after_batch_transfer() augments a batch on device"),
    "on_before_batch_transfer": ("preprocess", "LIGHTNING_HOOK_DATA",
                                 "on_before_batch_transfer() augments a batch on host"),
}

#: The roles the table above uses, for the readers that want the set.
LIGHTNING_HOOK_ROLES = frozenset(
    [row[1] for row in HOOK_STAGES.values()] + ["LIGHTNING_HOOK_CONTROL"])

#: `on_<phase>_<...>` lifecycle hooks. The phase word decides the lane; the
#: `control` half of the roadmap's mapping is the edge, not a ninth stage.
_LIFECYCLE = re.compile(r"^on_[a-z_]+$")
_PHASE_STAGE = (
    ("validation", "eval"), ("sanity_check", "eval"), ("test", "eval"),
    ("predict", "eval"), ("train", "train"), ("fit", "train"),
    ("before_optimizer", "train"), ("after_backward", "train"),
    ("before_zero_grad", "train"), ("save_checkpoint", "deliver"),
    ("load_checkpoint", "deliver"), ("exception", "config"),
)


def hook_stage(name: str) -> Optional[Tuple[str, str, str]]:
    """`(stage, role, why)` for a framework hook method name, else None."""
    row = HOOK_STAGES.get(name)
    if row is not None:
        return row
    if not name or not _LIFECYCLE.match(name):
        return None
    for phase, stage in _PHASE_STAGE:
        if phase in name:
            return (stage, "LIGHTNING_HOOK_CONTROL",
                    "%s() is a %s-phase lifecycle hook" % (name, phase.replace("_", " ")))
    return ("train", "LIGHTNING_HOOK_CONTROL", "%s() is a lifecycle hook" % name)


# ---------------------------------------------------------------------------
# the non-hook LightningModule surface
# ---------------------------------------------------------------------------
#: (method, entry factory). Roles outside `knowledge.OP_ROLES` are recognised
#: and deliberately not drawn - see the module docstring.
_MODULE_METHODS = (
    ("log", E("metric", "train", L, "LIGHTNING_LOG")),
    ("log_dict", E("metric", "train", L, "LIGHTNING_LOG")),
    ("save_hyperparameters", E("config", "config", L, "LIGHTNING_HPARAMS")),
    ("manual_backward", E("loss", "train", L, "BACKWARD")),
    ("optimizers", E("optimizer", "train", L, "LIGHTNING_CTL")),
    ("lr_schedulers", E("scheduler", "train", L, "LIGHTNING_CTL")),
    ("toggle_optimizer", E("optimizer", "train", L, "LIGHTNING_CTL")),
    ("untoggle_optimizer", E("optimizer", "train", L, "LIGHTNING_CTL")),
    ("clip_gradients", E("optimizer", "train", L, "CLIP_GRAD")),
    ("all_gather", E("metric", "train", L, "LIGHTNING_CTL")),
    ("freeze", E("model", "model", L, "LIGHTNING_CTL")),
    ("unfreeze", E("model", "model", L, "LIGHTNING_CTL")),
    ("print", E("metric", "train", L, "LIGHTNING_CTL")),
    ("forward", E("model", "model", L, "FORWARD", ("LOGITS",))),
    ("__call__", E("model", "model", L, "FORWARD", ("LOGITS",))),
    ("load_from_checkpoint", E("model", "model", L, "LIGHTNING_MODULE", ("MODEL",),
                               "lightning_module")),
    ("configure_optimizers", E("optimizer", "objective", L, "LIGHTNING_HOOK_OBJECTIVE",
                               ("OPTIMIZER",))),
)

#: DataModule methods that are called from outside the class.
_DM_METHODS = (
    ("setup", E("dataset", "data", L, "LIGHTNING_DM")),
    ("prepare_data", E("dataset", "data", L, "LIGHTNING_DM")),
    ("train_dataloader", E("dataloader", "data", L, "LOADER", ("LOADER",), "loader")),
    ("val_dataloader", E("dataloader", "data", L, "LOADER", ("LOADER",), "loader")),
    ("test_dataloader", E("dataloader", "data", L, "LOADER", ("LOADER",), "loader")),
    ("predict_dataloader", E("dataloader", "data", L, "LOADER", ("LOADER",), "loader")),
)

#: Trainer methods, mirrored under every import root.
_TRAINER_METHODS = (
    ("fit", E("train_loop", "train", L, "LIGHTNING_FIT")),
    ("validate", E("eval_loop", "eval", L, "LIGHTNING_VAL")),
    ("test", E("eval_loop", "eval", L, "LIGHTNING_TEST")),
    ("predict", E("predict", "eval", L, "PREDICT", ("PREDS",))),
    ("save_checkpoint", E("checkpoint", "deliver", L, "SAVE")),
)

LIGHTNING_METHOD_ENTRIES: Dict[str, Entry] = {}
for _root in LIGHTNING_ROOTS:
    for _method, _entry in _MODULE_METHODS:
        LIGHTNING_METHOD_ENTRIES["%s.LightningModule.%s" % (_root, _method)] = dict(_entry)
    for _method, _entry in _DM_METHODS:
        LIGHTNING_METHOD_ENTRIES["%s.LightningDataModule.%s" % (_root, _method)] = dict(_entry)
    for _method, _entry in _TRAINER_METHODS:
        LIGHTNING_METHOD_ENTRIES["%s.Trainer.%s" % (_root, _method)] = dict(_entry)
