"""PyTorch / torchvision / torchmetrics knowledge table (canonical FQN -> entry)."""

from __future__ import annotations

from .entries import E, Entry, expand
from typing import Dict

T = "torch"
TV = "torchvision"

TORCH: Dict[str, Entry] = {}

# ---------------------------------------------------------------- data ----
TORCH.update({
    "torch.utils.data.DataLoader": E("dataloader", "data", T, "LOADER", ("LOADER",), "loader"),
    "torch.utils.data.Dataset": E("dataset", "data", T, "DATASET", ("RAW_DATA",), "dataset"),
    "torch.utils.data.IterableDataset": E("dataset", "data", T, "DATASET", ("RAW_DATA",), "dataset"),
    "torch.utils.data.TensorDataset": E("dataset", "data", T, "DATASET", ("RAW_DATA",), "dataset"),
    "torch.utils.data.ConcatDataset": E("dataset", "data", T, "DATASET", ("RAW_DATA",), "dataset"),
    "torch.utils.data.Subset": E("dataset", "data", T, "DATASET", ("RAW_DATA",), "dataset"),
    "torch.utils.data.random_split": E("split", "data", T, "SPLIT"),
    "torch.utils.data.DistributedSampler": E("dataset", "data", T, "SAMPLER"),
    "torch.utils.data.WeightedRandomSampler": E("dataset", "data", T, "SAMPLER"),
    "torch.utils.data.RandomSampler": E("dataset", "data", T, "SAMPLER"),
    "torch.utils.data.SequentialSampler": E("dataset", "data", T, "SAMPLER"),
})
TORCH.update(expand("torchvision.datasets", [
    "CIFAR10", "CIFAR100", "MNIST", "FashionMNIST", "ImageFolder", "ImageNet",
    "SVHN", "STL10", "VOCDetection", "CocoDetection", "DatasetFolder",
], E("dataset", "data", TV, "DATASET", ("RAW_DATA",), "dataset")))

# ---------------------------------------------------------- preprocess ----
TORCH.update({
    "torchvision.transforms.Compose": E("transform", "preprocess", TV, "TRANSFORM_PIPE"),
    "torchvision.transforms.ToTensor": E("transform", "preprocess", TV, "TRANSFORM"),
    "torchvision.transforms.Normalize": E("transform", "preprocess", TV, "TRANSFORM"),
    "torchvision.transforms.Resize": E("transform", "preprocess", TV, "TRANSFORM"),
    "torchvision.transforms.CenterCrop": E("transform", "preprocess", TV, "TRANSFORM"),
    "torchvision.transforms.ToPILImage": E("transform", "preprocess", TV, "TRANSFORM"),
    "torchvision.transforms.RandomCrop": E("augment", "preprocess", TV, "AUGMENT"),
    "torchvision.transforms.RandomHorizontalFlip": E("augment", "preprocess", TV, "AUGMENT"),
    "torchvision.transforms.RandomVerticalFlip": E("augment", "preprocess", TV, "AUGMENT"),
    "torchvision.transforms.RandomRotation": E("augment", "preprocess", TV, "AUGMENT"),
    "torchvision.transforms.ColorJitter": E("augment", "preprocess", TV, "AUGMENT"),
    "torchvision.transforms.RandomResizedCrop": E("augment", "preprocess", TV, "AUGMENT"),
    "torchvision.transforms.RandomErasing": E("augment", "preprocess", TV, "AUGMENT"),
})

# --------------------------------------------------------------- model ----
TORCH["torch.nn.Module"] = E("model", "model", T, "MODEL_CLS", ("MODEL",), "module")
TORCH["torch.nn.Sequential"] = E("model", "model", T, "CONTAINER", ("MODEL",), "module")
TORCH["torch.nn.ModuleList"] = E("model", "model", T, "CONTAINER", ("MODEL",), "module")
TORCH["torch.nn.ModuleDict"] = E("model", "model", T, "CONTAINER", ("MODEL",), "module")
TORCH["torch.nn.ParameterList"] = E("model", "model", T, "CONTAINER", ("MODEL",), "module")
TORCH.update(expand("torch.nn", [
    "Linear", "Bilinear", "LazyLinear", "Conv1d", "Conv2d", "Conv3d",
    "ConvTranspose2d", "MaxPool2d", "AvgPool2d", "AdaptiveAvgPool2d",
    "AdaptiveMaxPool2d", "Flatten", "Unflatten", "Embedding", "EmbeddingBag",
    "LSTM", "GRU", "RNN", "Transformer", "TransformerEncoder",
    "TransformerEncoderLayer", "MultiheadAttention", "Identity",
], E("layer", "model", T, "LAYER", ("MODEL",), "module")))
TORCH.update(expand("torch.nn", [
    "BatchNorm1d", "BatchNorm2d", "BatchNorm3d", "SyncBatchNorm",
    "InstanceNorm1d", "InstanceNorm2d", "GroupNorm",
], E("layer", "model", T, "NORM_TRAIN_SENSITIVE", ("MODEL",), "module")))
TORCH.update(expand("torch.nn", ["LayerNorm", "RMSNorm"],
                    E("layer", "model", T, "NORM", ("MODEL",), "module")))
TORCH.update(expand("torch.nn", ["Dropout", "Dropout1d", "Dropout2d", "Dropout3d", "AlphaDropout"],
                    E("layer", "model", T, "DROPOUT", ("MODEL",), "module")))
TORCH.update(expand("torch.nn", [
    "ReLU", "LeakyReLU", "GELU", "SiLU", "ELU", "Tanh", "Softplus", "Mish", "Hardswish",
], E("layer", "model", T, "ACTIVATION", ("MODEL",), "module")))
TORCH["torch.nn.Softmax"] = E("layer", "model", T, "SOFTMAX", ("PROBS",), "module")
TORCH["torch.nn.LogSoftmax"] = E("layer", "model", T, "LOG_SOFTMAX", ("LOGITS",), "module")
TORCH["torch.nn.Sigmoid"] = E("layer", "model", T, "SIGMOID", ("PROBS",), "module")
TORCH["torch.nn.functional.softmax"] = E("layer", "model", T, "SOFTMAX", ("PROBS",))
TORCH["torch.nn.functional.log_softmax"] = E("layer", "model", T, "LOG_SOFTMAX", ("LOGITS",))
TORCH["torch.nn.functional.sigmoid"] = E("layer", "model", T, "SIGMOID", ("PROBS",))
TORCH["torch.sigmoid"] = E("layer", "model", T, "SIGMOID", ("PROBS",))
TORCH["torch.softmax"] = E("layer", "model", T, "SOFTMAX", ("PROBS",))
TORCH["torch.log_softmax"] = E("layer", "model", T, "LOG_SOFTMAX", ("LOGITS",))
TORCH["torch.Tensor.softmax"] = E("layer", "model", T, "SOFTMAX", ("PROBS",))
TORCH["torch.Tensor.log_softmax"] = E("layer", "model", T, "LOG_SOFTMAX", ("LOGITS",))
TORCH["torch.Tensor.sigmoid"] = E("layer", "model", T, "SIGMOID", ("PROBS",))
TORCH.update(expand("torch.nn.functional", [
    "relu", "gelu", "silu", "elu", "tanh", "max_pool2d", "avg_pool2d", "linear", "conv2d",
], E("layer", "model", T, "LAYER")))
TORCH["torch.nn.functional.dropout"] = E("layer", "model", T, "DROPOUT")
TORCH["torch.compile"] = E("model", "model", T, "WRAP_MODEL", ("MODEL",), "module")
TORCH["torch.nn.DataParallel"] = E("model", "model", T, "WRAP_MODEL", ("MODEL",), "module")
TORCH["torch.nn.parallel.DistributedDataParallel"] = E(
    "model", "model", T, "WRAP_MODEL", ("MODEL",), "module")

# ----------------------------------------------------------- objective ----
TORCH.update(expand("torch.nn", [
    "CrossEntropyLoss", "NLLLoss", "BCELoss", "BCEWithLogitsLoss", "MSELoss",
    "L1Loss", "SmoothL1Loss", "HuberLoss", "KLDivLoss", "CTCLoss",
    "TripletMarginLoss", "CosineEmbeddingLoss", "MultiMarginLoss",
], E("loss", "objective", T, "LOSS_CLS", ("LOSS",), "loss")))
TORCH.update(expand("torch.nn.functional", [
    "cross_entropy", "nll_loss", "binary_cross_entropy",
    "binary_cross_entropy_with_logits", "mse_loss", "l1_loss", "smooth_l1_loss",
    "kl_div",
], E("loss", "objective", T, "LOSS_FN", ("LOSS",))))

# --------------------------------------------------------------- train ----
TORCH.update(expand("torch.optim", [
    "SGD", "Adam", "AdamW", "Adamax", "Adagrad", "Adadelta", "ASGD", "NAdam",
    "RAdam", "RMSprop", "Rprop", "LBFGS", "SparseAdam",
], E("optimizer", "train", T, "OPTIMIZER", ("OPTIMIZER",), "optimizer")))
TORCH["torch.optim.Optimizer"] = E("optimizer", "train", T, "OPTIMIZER", ("OPTIMIZER",), "optimizer")
TORCH.update(expand("torch.optim.lr_scheduler", [
    "StepLR", "MultiStepLR", "ExponentialLR", "CosineAnnealingLR",
    "CosineAnnealingWarmRestarts", "ReduceLROnPlateau", "OneCycleLR",
    "CyclicLR", "LambdaLR", "LinearLR", "ConstantLR", "PolynomialLR",
], E("scheduler", "train", T, "SCHEDULER", (), "scheduler")))
TORCH["torch.optim.lr_scheduler.LRScheduler"] = E("scheduler", "train", T, "SCHEDULER", (), "scheduler")
TORCH["torch.amp.GradScaler"] = E("scaler", "train", T, "GRAD_SCALER", (), "grad_scaler")
TORCH["torch.cuda.amp.GradScaler"] = E("scaler", "train", T, "GRAD_SCALER", (), "grad_scaler")
TORCH["torch.autocast"] = E("train_loop", "train", T, "AUTOCAST")
TORCH["torch.amp.autocast"] = E("train_loop", "train", T, "AUTOCAST")
TORCH["torch.cuda.amp.autocast"] = E("train_loop", "train", T, "AUTOCAST")
TORCH["torch.nn.utils.clip_grad_norm_"] = E("optimizer", "train", T, "CLIP_GRAD")
TORCH["torch.nn.utils.clip_grad_value_"] = E("optimizer", "train", T, "CLIP_GRAD")

# ---------------------------------------------------------------- eval ----
TORCH["torch.no_grad"] = E("eval_loop", "eval", T, "NO_GRAD")
TORCH["torch.inference_mode"] = E("eval_loop", "eval", T, "NO_GRAD")
TORCH["torch.enable_grad"] = E("train_loop", "train", T, "ENABLE_GRAD")
TORCH["torch.argmax"] = E("metric", "eval", T, "ARGMAX", ("PREDS",))
TORCH["torch.Tensor.argmax"] = E("metric", "eval", T, "ARGMAX", ("PREDS",))
TORCH["torch.Tensor.topk"] = E("metric", "eval", T, "ARGMAX", ("PREDS",))
TORCH["torch.Tensor.max"] = E("metric", "eval", T, "ARGMAX", ("PREDS",), weight=0.5)
#: GRAPH-R2: the `torchmetric` receiver family. A metric **object** exists to
#: be `update`d and then `compute`d, and with no family on the constructor row
#: neither method resolved to anything - the whole point of holding one.
#: `knowledge/stats_tbl.py` carries the method surface it resolves to.
TORCH.update(expand("torchmetrics", [
    "Accuracy", "F1Score", "Precision", "Recall", "AUROC", "ConfusionMatrix",
    "MeanSquaredError", "R2Score", "MetricCollection", "MeanAbsoluteError",
    "AveragePrecision", "CohenKappa", "JaccardIndex", "Dice", "Specificity",
], E("metric", "eval", "torchmetrics", "METRIC", (), "torchmetric")))
TORCH.update(expand("torchmetrics.functional", [
    "accuracy", "f1_score", "precision", "recall", "auroc",
], E("metric", "eval", "torchmetrics", "METRIC")))

# ------------------------------------------------------------- deliver ----
TORCH["torch.save"] = E("checkpoint", "deliver", T, "SAVE")
TORCH["torch.load"] = E("checkpoint", "deliver", T, "LOAD")

# -------------------------------------------------------------- config ----
TORCH["torch.device"] = E("config", "config", T, "DEVICE", ("DEVICE",), "device")
TORCH["torch.cuda.is_available"] = E("config", "config", T, "DEVICE_CHECK")
TORCH["torch.manual_seed"] = E("config", "config", T, "SEED")
TORCH["torch.cuda.manual_seed"] = E("config", "config", T, "SEED")
TORCH["torch.cuda.manual_seed_all"] = E("config", "config", T, "SEED")
TORCH["torch.use_deterministic_algorithms"] = E("config", "config", T, "DETERMINISM")
TORCH["torch.Generator"] = E("config", "config", T, "GENERATOR")

# --------------------------------------------- method families (torch) ----
#: Methods reachable on a receiver of a known family. The key is the canonical
#: base FQN produced by receiver resolution; rules match exactly these.
TORCH_METHODS: Dict[str, Entry] = {
    "torch.optim.Optimizer.step": E("optimizer", "train", T, "OPT_STEP"),
    "torch.optim.Optimizer.zero_grad": E("optimizer", "train", T, "ZERO_GRAD"),
    "torch.optim.Optimizer.state_dict": E("checkpoint", "deliver", T, "STATE_DICT"),
    "torch.optim.Optimizer.load_state_dict": E("checkpoint", "deliver", T, "LOAD_STATE"),
    "torch.optim.lr_scheduler.LRScheduler.step": E("scheduler", "train", T, "SCHED_STEP"),
    "torch.nn.Module.eval": E("model", "eval", T, "EVAL_MODE"),
    "torch.nn.Module.train": E("model", "train", T, "TRAIN_MODE"),
    "torch.nn.Module.to": E("model", "model", T, "TO_DEVICE", ("MODEL",)),
    "torch.nn.Module.cuda": E("model", "model", T, "TO_DEVICE", ("MODEL",)),
    "torch.nn.Module.cpu": E("model", "model", T, "TO_DEVICE", ("MODEL",)),
    "torch.nn.Module.parameters": E("model", "train", T, "PARAMETERS"),
    "torch.nn.Module.named_parameters": E("model", "train", T, "PARAMETERS"),
    "torch.nn.Module.state_dict": E("checkpoint", "deliver", T, "STATE_DICT"),
    "torch.nn.Module.load_state_dict": E("checkpoint", "deliver", T, "LOAD_STATE"),
    "torch.nn.Module.zero_grad": E("optimizer", "train", T, "ZERO_GRAD"),
    "torch.nn.Module.forward": E("model", "model", T, "FORWARD", ("LOGITS",)),
    "torch.nn.Module.__call__": E("model", "model", T, "FORWARD", ("LOGITS",)),
    "torch.nn.Module.add_module": E("model", "model", T, "LAYER"),
    "torch.Tensor.backward": E("loss", "train", T, "BACKWARD"),
    "torch.Tensor.item": E("metric", "train", T, "ITEM"),
    "torch.Tensor.detach": E("metric", "train", T, "DETACH"),
    "torch.Tensor.to": E("model", "train", T, "TO_DEVICE"),
    "torch.Tensor.cuda": E("model", "train", T, "TO_DEVICE"),
    "torch.Tensor.cpu": E("model", "train", T, "TO_DEVICE"),
    "torch.Tensor.numpy": E("metric", "eval", T, "TO_NUMPY"),
    "torch.amp.GradScaler.scale": E("scaler", "train", T, "SCALE"),
    "torch.amp.GradScaler.step": E("scaler", "train", T, "OPT_STEP"),
    "torch.amp.GradScaler.update": E("scaler", "train", T, "SCALER_UPDATE"),
    "torch.amp.GradScaler.unscale_": E("scaler", "train", T, "UNSCALE"),
    "torch.Generator.manual_seed": E("config", "config", T, "SEED"),
}

#: Receiver family -> (base FQN prefix, method names that resolve to it).
TORCH_FAMILY_BASE = {
    "optimizer": "torch.optim.Optimizer",
    "scheduler": "torch.optim.lr_scheduler.LRScheduler",
    "module": "torch.nn.Module",
    "tensor": "torch.Tensor",
    "grad_scaler": "torch.amp.GradScaler",
    "loss": "torch.nn.Module",
    "device": "torch.device",
}

#: FQN prefixes whose *result* is a torch tensor (so ``.backward()`` resolves).
TENSOR_PRODUCING_PREFIXES = ("torch.", "torchvision.")

NO_GRAD_FQNS = frozenset({"torch.no_grad", "torch.inference_mode"})
ENABLE_GRAD_FQNS = frozenset({"torch.enable_grad"})
AUTOCAST_FQNS = frozenset({"torch.autocast", "torch.amp.autocast", "torch.cuda.amp.autocast"})
