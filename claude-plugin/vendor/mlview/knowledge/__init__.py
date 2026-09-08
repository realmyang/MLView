"""MLView knowledge tables: canonical FQN -> what the analyzer knows about it.

Plain Python dicts, no YAML, no I/O. `lookup()` is the only entry point rules
and the graph builder use; it falls back to a small set of prefix rules so an
unlisted member of a known family still lands in the right stage.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Optional, Tuple

from .entries import E, Entry
from .other_tbl import (
    ARGPARSE_METHODS,
    FRAME_METHODS,
    HF_METHODS,
    KERAS_METHODS,
    LIGHTNING_METHODS,
    OTHER,
)
from .sklearn_tbl import SKLEARN, SKLEARN_METHODS, STATELESS_TRANSFORMERS
from .torch_tbl import (
    AUTOCAST_FQNS,
    ENABLE_GRAD_FQNS,
    NO_GRAD_FQNS,
    TORCH,
    TORCH_FAMILY_BASE,
    TORCH_METHODS,
)

__all__ = [
    "KNOWLEDGE", "METHODS", "lookup", "lookup_exact", "best_entry", "lookup_any",
    "role_of", "stage_of", "kind_of",
    "tags_of", "framework_of", "family_of", "is_known",
    "framework_for_module", "FRAMEWORKS", "WRAPPER_FQNS", "WRAPPER_LABELS",
    "SEED_ROLES", "SPLIT_ROLES", "FIT_ROLES", "OPT_STEP_ROLES",
    "ZERO_GRAD_ROLES", "BACKWARD_ROLES", "NO_GRAD_FQNS", "ENABLE_GRAD_FQNS",
    "AUTOCAST_FQNS", "TORCH_FAMILY_BASE", "STATELESS_TRANSFORMERS",
    "OP_ROLES", "SOFTMAX_ROLES", "CONFIG_ROLES", "STAGE_IDS", "STAGE_LABELS",
]

#: Every constructor / free function we recognise.
KNOWLEDGE: Dict[str, Entry] = {}
KNOWLEDGE.update(TORCH)
KNOWLEDGE.update(SKLEARN)
KNOWLEDGE.update(OTHER)

#: Every *method* we recognise, keyed by its canonical base FQN.
METHODS: Dict[str, Entry] = {}
METHODS.update(TORCH_METHODS)
METHODS.update(SKLEARN_METHODS)
METHODS.update(KERAS_METHODS)
METHODS.update(HF_METHODS)
METHODS.update(LIGHTNING_METHODS)
METHODS.update(ARGPARSE_METHODS)
METHODS.update(FRAME_METHODS)

#: Everything, for a single lookup.
ALL: Dict[str, Entry] = {}
ALL.update(KNOWLEDGE)
ALL.update(METHODS)

STAGE_IDS = ("config", "data", "preprocess", "model", "objective", "train", "eval", "deliver")
STAGE_LABELS = {
    "config": "Configuration",
    "data": "Data",
    "preprocess": "Preprocess",
    "model": "Model",
    "objective": "Objective",
    "train": "Train",
    "eval": "Evaluate",
    "deliver": "Save / Deploy",
}

# ---------------------------------------------------------------------------
# prefix fallbacks - an unlisted member of a known family still resolves
# ---------------------------------------------------------------------------
_PREFIX_RULES: Tuple[Tuple[str, Entry], ...] = (
    ("torch.optim.lr_scheduler.", E("scheduler", "train", "torch", "SCHEDULER", (), "scheduler")),
    ("torch.optim.", E("optimizer", "train", "torch", "OPTIMIZER", ("OPTIMIZER",), "optimizer")),
    ("torch.nn.functional.", E("layer", "model", "torch", "LAYER", (), None, 0.7)),
    ("torch.nn.utils.", E("optimizer", "train", "torch", "NN_UTIL", (), None, 0.6)),
    ("torch.nn.init.", E("layer", "model", "torch", "INIT", (), None, 0.6)),
    ("torch.nn.", E("layer", "model", "torch", "LAYER", ("MODEL",), "module", 0.8)),
    ("torch.utils.data.", E("dataset", "data", "torch", "DATASET", ("RAW_DATA",), "dataset", 0.7)),
    ("torchvision.transforms.", E("transform", "preprocess", "torchvision", "TRANSFORM", (), None, 0.8)),
    ("torchvision.datasets.", E("dataset", "data", "torchvision", "DATASET", ("RAW_DATA",), "dataset", 0.8)),
    ("torchvision.models.", E("model", "model", "torchvision", "MODEL_FACTORY", ("MODEL",), "module", 0.8)),
    ("torchmetrics.", E("metric", "eval", "torchmetrics", "METRIC", (), None, 0.8)),
    ("sklearn.metrics.", E("metric", "eval", "sklearn", "METRIC", (), None, 0.8)),
    ("sklearn.preprocessing.", E("scaler", "preprocess", "sklearn", "TRANSFORMER", (), "estimator", 0.8)),
    ("sklearn.decomposition.", E("transform", "preprocess", "sklearn", "TRANSFORMER", (), "estimator", 0.8)),
    ("sklearn.impute.", E("transform", "preprocess", "sklearn", "TRANSFORMER", (), "estimator", 0.8)),
    ("sklearn.feature_selection.", E("transform", "preprocess", "sklearn", "TRANSFORMER", (), "estimator", 0.8)),
    ("sklearn.feature_extraction.", E("transform", "preprocess", "sklearn", "TRANSFORMER", (), "estimator", 0.8)),
    ("sklearn.model_selection.", E("split", "data", "sklearn", "SPLITTER", (), "splitter", 0.7)),
    ("sklearn.linear_model.", E("model", "model", "sklearn", "ESTIMATOR", ("MODEL",), "estimator", 0.8)),
    ("sklearn.ensemble.", E("model", "model", "sklearn", "ESTIMATOR", ("MODEL",), "estimator", 0.8)),
    ("sklearn.svm.", E("model", "model", "sklearn", "ESTIMATOR", ("MODEL",), "estimator", 0.8)),
    ("sklearn.tree.", E("model", "model", "sklearn", "ESTIMATOR", ("MODEL",), "estimator", 0.8)),
    ("sklearn.cluster.", E("model", "model", "sklearn", "ESTIMATOR", ("MODEL",), "estimator", 0.8)),
    ("sklearn.datasets.", E("dataset", "data", "sklearn", "DATASET", ("RAW_DATA",), None, 0.8)),
    ("imblearn.", E("transform", "preprocess", "imblearn", "RESAMPLE", (), "estimator", 0.7)),
    ("albumentations.", E("augment", "preprocess", "albumentations", "AUGMENT", (), None, 0.7)),
)

_ALIAS_PREFIXES = (("tf.", "tensorflow."),)

#: The prefix rules again, as a dict. Every key ends at a dotted boundary, so a
#: probe over the progressively shorter dotted prefixes of an FQN - longest
#: first - answers exactly what the 26-entry `startswith` scan answered: the
#: tuple is written specific-before-general within each family, and "longest
#: prefix wins" is the same order. `_PREFIX_DOTTED` guards the shortcut, so a
#: future rule that does not end in "." silently falls back to the scan.
_PREFIX_MAP: Dict[str, Entry] = {}
for _prefix, _row in _PREFIX_RULES:
    _PREFIX_MAP.setdefault(_prefix, _row)
_PREFIX_DOTTED = all(p.endswith(".") for p, _ in _PREFIX_RULES)

#: `lookup` is the hottest function in the analyzer - 2.3M calls on a 210-file
#: workspace before PERF-01 - and the tables it reads are immutable module
#: state built once at import, so memoising it is safe by construction. The
#: bound is generous (an FQN universe that large means a workspace far past
#: `--max-files`) and keeps a long-lived MCP server from growing without limit.
_LOOKUP_CACHE = 32768


def _normalize(fqn: str) -> str:
    for src, dst in _ALIAS_PREFIXES:
        if fqn.startswith(src):
            return dst + fqn[len(src):]
    return fqn


def _prefix_entry(fqn: str) -> Optional[Entry]:
    """The prefix-rule row for an FQN, or None."""
    if not _PREFIX_DOTTED:  # pragma: no cover - guard for a future rule shape
        for prefix, row in _PREFIX_RULES:
            if fqn.startswith(prefix):
                return row
        return None
    parts = fqn.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        row = _PREFIX_MAP.get(".".join(parts[:cut]) + ".")
        if row is not None:
            return row
    return None


@lru_cache(maxsize=_LOOKUP_CACHE)
def lookup(fqn: Optional[str]) -> Optional[Entry]:
    """The knowledge row for a canonical FQN, or None."""
    if not fqn:
        return None
    entry = ALL.get(fqn)
    if entry is not None:
        return entry
    alt = _normalize(fqn)
    if alt != fqn:
        entry = ALL.get(alt)
        if entry is not None:
            return entry
    return _prefix_entry(fqn)


@lru_cache(maxsize=_LOOKUP_CACHE)
def lookup_exact(fqn: Optional[str]) -> Optional[Entry]:
    """Exact-table hit only - no prefix fallback."""
    if not fqn:
        return None
    return ALL.get(fqn) or ALL.get(_normalize(fqn))


def best_entry(fqns) -> Tuple[Optional[Entry], Optional[str]]:
    """The most specific row for a candidate list: exact hits beat prefixes."""
    candidates = tuple(fqns or ())
    for fqn in candidates:
        entry = lookup_exact(fqn)
        if entry is not None:
            return entry, fqn
    for fqn in candidates:
        entry = lookup(fqn)
        if entry is not None:
            return entry, fqn
    return None, None


def lookup_any(fqns) -> Optional[Entry]:
    """First knowledge row among an ordered list of candidate FQNs."""
    return best_entry(fqns)[0]


def is_known(fqn: Optional[str]) -> bool:
    return lookup(fqn) is not None


def role_of(fqn: Optional[str]) -> Optional[str]:
    entry = lookup(fqn)
    return entry["role"] if entry else None


def stage_of(fqn: Optional[str]) -> Optional[str]:
    entry = lookup(fqn)
    return entry["stage"] if entry else None


def kind_of(fqn: Optional[str]) -> Optional[str]:
    entry = lookup(fqn)
    return entry["kind"] if entry else None


def tags_of(fqn: Optional[str]) -> Tuple[str, ...]:
    entry = lookup(fqn)
    return tuple(entry["tags"]) if entry else ()


def framework_of(fqn: Optional[str]) -> Optional[str]:
    entry = lookup(fqn)
    return entry["framework"] if entry else None


def family_of(fqn: Optional[str]) -> Optional[str]:
    entry = lookup(fqn)
    return entry["family"] if entry else None


# ---------------------------------------------------------------------------
# role groupings the rules query
# ---------------------------------------------------------------------------
SEED_ROLES = frozenset({"SEED"})
SPLIT_ROLES = frozenset({"SPLIT"})
SPLITTER_ROLES = frozenset({"SPLITTER"})
FIT_ROLES = frozenset({"FIT", "FIT_TRANSFORM"})
OPT_STEP_ROLES = frozenset({"OPT_STEP"})
ZERO_GRAD_ROLES = frozenset({"ZERO_GRAD"})
BACKWARD_ROLES = frozenset({"BACKWARD"})
SOFTMAX_ROLES = frozenset({"SOFTMAX", "LOG_SOFTMAX"})
CONFIG_ROLES = frozenset({"CONFIG_LOAD", "ARGPARSE", "CONFIG_ENV"})
METRIC_ROLES = frozenset({"METRIC", "SCORE_METRIC", "CV"})
PREDICT_ROLES = frozenset({"PREDICT"})

#: Roles that always deserve their own `op` node in the graph.
OP_ROLES = frozenset({
    "LOADER", "DATASET", "SPLIT", "SPLITTER", "TRANSFORM", "TRANSFORM_PIPE",
    "AUGMENT", "TRANSFORMER", "STATELESS_TRANSFORMER", "MODEL_CLS", "LAYER",
    "CONTAINER", "NORM", "NORM_TRAIN_SENSITIVE", "DROPOUT", "ACTIVATION",
    "SOFTMAX", "LOG_SOFTMAX", "SIGMOID", "LOSS_CLS", "LOSS_FN", "OPTIMIZER",
    "SCHEDULER", "GRAD_SCALER", "AUTOCAST", "NO_GRAD", "ENABLE_GRAD",
    "CLIP_GRAD", "OPT_STEP", "ZERO_GRAD", "SCHED_STEP", "BACKWARD", "ITEM",
    "DETACH", "EVAL_MODE", "TRAIN_MODE", "TO_DEVICE", "PARAMETERS",
    "STATE_DICT", "LOAD_STATE", "SAVE", "LOAD", "METRIC", "SCORE_METRIC",
    "CV", "CV_SEARCH", "ESTIMATOR", "PIPELINE", "FIT", "FIT_TRANSFORM",
    "PREDICT", "DEVICE", "DEVICE_CHECK", "SEED", "GENERATOR", "ARGPARSE",
    "CONFIG_LOAD", "CONFIG_ENV", "DATASET_HF", "HF_MODEL", "HF_TOKENIZER",
    "HF_TRAINER", "HF_ARGS", "HF_TRAIN", "HF_EVAL", "HF_PIPELINE",
    "LIGHTNING_MODULE", "LIGHTNING_TRAINER", "LIGHTNING_FIT", "LIGHTNING_VAL",
    "LIGHTNING_TEST", "LIGHTNING_DM", "KERAS_MODEL", "KERAS_COMPILE",
    "KERAS_FIT", "KERAS_EVAL", "KERAS_LOAD", "ACCELERATOR", "FABRIC",
    "TRACKER", "RESAMPLE", "ARGMAX", "SCALE", "SCALER_UPDATE", "UNSCALE",
    "MODEL_FACTORY", "WRAP_MODEL", "SAMPLER", "FORWARD", "TEMPORAL",
    "DETERMINISM", "TO_NUMPY",
})

# ---------------------------------------------------------------------------
# frameworks
# ---------------------------------------------------------------------------
#: Framework enum values from `contracts/graph.schema.json`.
FRAMEWORKS = ("torch", "sklearn", "pandas", "numpy", "keras", "tf", "hf",
              "lightning", "imblearn", "torchvision", "torchmetrics",
              "albumentations", "xgboost", "lightgbm", "other")

_MODULE_FRAMEWORK = {
    "torch": "torch",
    "torchvision": "torchvision",
    "torchmetrics": "torchmetrics",
    "torchaudio": "torch",
    "sklearn": "sklearn",
    "pandas": "pandas",
    "numpy": "numpy",
    "keras": "keras",
    "tensorflow": "tf",
    "tf": "tf",
    "transformers": "hf",
    "datasets": "hf",
    "accelerate": "hf",
    "pytorch_lightning": "lightning",
    "lightning": "lightning",
    "imblearn": "imblearn",
    "albumentations": "albumentations",
    "xgboost": "xgboost",
    "lightgbm": "lightgbm",
}


@lru_cache(maxsize=4096)
def framework_for_module(module: str) -> Optional[str]:
    """Framework enum value for a top-level imported module name, or None."""
    if not module:
        return None
    return _MODULE_FRAMEWORK.get(module.split(".")[0])


# ---------------------------------------------------------------------------
# the negation_absent gate: frameworks that own the training loop
# ---------------------------------------------------------------------------
WRAPPER_FQNS: Dict[str, str] = {
    "pytorch_lightning.Trainer": "Lightning",
    "pytorch_lightning.LightningModule": "Lightning",
    "pytorch_lightning.Fabric": "Lightning Fabric",
    "lightning.Trainer": "Lightning",
    "lightning.LightningModule": "Lightning",
    "lightning.Fabric": "Lightning Fabric",
    "lightning.pytorch.Trainer": "Lightning",
    "lightning.pytorch.LightningModule": "Lightning",
    "transformers.Trainer": "HuggingFace Trainer",
    "transformers.Seq2SeqTrainer": "HuggingFace Trainer",
    "accelerate.Accelerator": "accelerate",
    "ignite.engine.Engine": "ignite",
    "ignite.engine.create_supervised_trainer": "ignite",
    "fastai.learner.Learner": "fastai",
    "fastai.vision.learner.vision_learner": "fastai",
    "deepspeed.initialize": "DeepSpeed",
    "torch.nn.parallel.DistributedDataParallel": "DistributedDataParallel",
    "torch.distributed.fsdp.FullyShardedDataParallel": "FSDP",
    "keras.Model.fit": "Keras",
    "tensorflow.keras.Model.fit": "Keras",
}

#: Base classes whose subclasses mean "the framework owns the loop".
WRAPPER_BASES = frozenset({
    "pytorch_lightning.LightningModule",
    "lightning.LightningModule",
    "lightning.pytorch.LightningModule",
})

WRAPPER_LABELS = tuple(sorted(set(WRAPPER_FQNS.values())))
