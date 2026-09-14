"""timm (`pytorch-image-models`) knowledge table — vision-04.

**Why this file exists.** `grep -rl timm analyzer/src/mlview/knowledge/`
returned nothing, and timm is the de-facto standard backbone / augmentation /
scheduler library for modern image classification. The measured consequence on
a correct timm program (`analyzer/tests/accuracy/corpus/vision_vit_timm`) was a
rendered workflow with **no** node for `timm.create_model`, none for
`SoftTargetCrossEntropy`, none for `timm.data.Mixup`, none for
`CosineLRScheduler`, none for `create_transform`, and none for the forward,
the loss or the backward that hang off them — 11 of 20 hand-labelled ops, 45%
fidelity — while `workspace.frameworks` reported `['torch','numpy',
'torchvision']` and `diagnostics` was `[]`. The reader had no way to know the
analyzer did not know the project's main library.

Everything here resolves onto **existing** roles and onto the `torch`
`Framework` enum value. Nothing in `contracts/graph.schema.json` changes:
timm's models really are `torch.nn.Module`s, its losses really are torch
losses, and its schedulers really are stepped like torch schedulers. Adding a
`timm` enum value would be a contract change for no gain the reader can see.

`timm.scheduler.*.step_update` is the per-batch cadence and `*.step` the
per-epoch one — the distinction MLV207 is about — so the two carry different
roles.
"""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

TORCH = "torch"

TIMM: Dict[str, Entry] = {}

# ---------------------------------------------------------------- model ---
#: `timm.create_model("vit_base_patch16_224", pretrained=True, num_classes=10)`
#: is how every timm project builds its network.
for _path in ("timm.create_model", "timm.models.create_model",
              "timm.models.factory.create_model"):
    TIMM[_path] = E("model", "model", TORCH, "MODEL_FACTORY", ("MODEL",), "module")
TIMM["timm.models.resume_checkpoint"] = E("checkpoint", "deliver", TORCH, "LOAD")
TIMM["timm.utils.ModelEmaV2"] = E("model", "model", TORCH, "WRAP_MODEL", ("MODEL",),
                                  "module")
TIMM["timm.utils.ModelEmaV3"] = E("model", "model", TORCH, "WRAP_MODEL", ("MODEL",),
                                  "module")

# ------------------------------------------------------------ objective ---
#: All three are members of the CrossEntropy family, which is what makes MLV401
#: (softmax before a cross-entropy loss) apply to a timm head.
TIMM.update(expand("timm.loss", [
    "SoftTargetCrossEntropy", "LabelSmoothingCrossEntropy", "BinaryCrossEntropy",
    "JsdCrossEntropy", "AsymmetricLossMultiLabel", "AsymmetricLossSingleLabel",
], E("loss", "objective", TORCH, "LOSS_CLS", ("LOSS",), "loss")))

# ----------------------------------------------------------- preprocess ---
#: `create_transform(is_training=True)` is timm's augmentation pipeline, and
#: `Mixup` is its batch-level augmentation. Both are AUGMENT so MLV114 can see
#: a timm evaluation pipeline that augments.
TIMM["timm.data.create_transform"] = E("transform", "preprocess", TORCH,
                                       "TRANSFORM_PIPE", (), None)
TIMM["timm.data.transforms_factory.create_transform"] = E(
    "transform", "preprocess", TORCH, "TRANSFORM_PIPE", (), None)
TIMM["timm.data.Mixup"] = E("augment", "preprocess", TORCH, "AUGMENT", (), "mixup")
TIMM["timm.data.mixup.Mixup"] = E("augment", "preprocess", TORCH, "AUGMENT", (), "mixup")
TIMM["timm.data.rand_augment_transform"] = E("augment", "preprocess", TORCH, "AUGMENT")
TIMM["timm.data.auto_augment_transform"] = E("augment", "preprocess", TORCH, "AUGMENT")
TIMM["timm.data.RandomErasing"] = E("augment", "preprocess", TORCH, "AUGMENT")
TIMM["timm.data.create_loader"] = E("dataloader", "data", TORCH, "LOADER", ("LOADER",),
                                    "loader")
TIMM["timm.data.create_dataset"] = E("dataset", "data", TORCH, "DATASET", ("RAW_DATA",),
                                     "dataset")
TIMM["timm.data.resolve_data_config"] = E("config", "config", TORCH, "CONFIG_LOAD")

# ---------------------------------------------------------------- train ---
TIMM.update(expand("timm.scheduler", [
    "CosineLRScheduler", "StepLRScheduler", "TanhLRScheduler",
    "PlateauLRScheduler", "PolyLRScheduler", "MultiStepLRScheduler",
], E("scheduler", "train", TORCH, "SCHEDULER", (), "timm_scheduler")))
TIMM["timm.scheduler.create_scheduler"] = E("scheduler", "train", TORCH, "SCHEDULER",
                                            (), "timm_scheduler")
TIMM["timm.scheduler.create_scheduler_v2"] = E("scheduler", "train", TORCH, "SCHEDULER",
                                               (), "timm_scheduler")
TIMM.update(expand("timm.optim", ["create_optimizer", "create_optimizer_v2",
                                  "AdamP", "Lamb", "Lars", "Lookahead",
                                  "MADGRAD", "Nadam", "RAdam", "RMSpropTF", "SGDP"],
                   E("optimizer", "train", TORCH, "OPTIMIZER", ("OPTIMIZER",),
                     "optimizer")))
TIMM["timm.utils.NativeScaler"] = E("scaler", "train", TORCH, "GRAD_SCALER", (), "scaler")
TIMM["timm.utils.dispatch_clip_grad"] = E("optimizer", "train", TORCH, "CLIP_GRAD")
TIMM["timm.utils.accuracy"] = E("metric", "eval", TORCH, "METRIC")

# ------------------------------------------------- methods on those values --
TIMM_METHODS: Dict[str, Entry] = {
    #: `scheduler.step_update(num_updates=...)` is the **per-batch** cadence and
    #: `scheduler.step(epoch)` the per-epoch one. MLV207 is exactly the question
    #: of which one the code wrote, so the two may not share a role.
    "timm.scheduler.CosineLRScheduler.step": E("scheduler", "train", TORCH, "SCHED_STEP"),
    "timm.scheduler.CosineLRScheduler.step_update":
        E("scheduler", "train", TORCH, "SCHED_STEP_BATCH"),
    "timm.data.Mixup.__call__": E("augment", "preprocess", TORCH, "AUGMENT"),
    "timm.utils.ModelEmaV2.update": E("model", "train", TORCH, "EMA_UPDATE"),
    "timm.utils.ModelEmaV3.update": E("model", "train", TORCH, "EMA_UPDATE"),
}
