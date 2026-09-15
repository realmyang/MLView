"""MLView knowledge tables: canonical FQN -> what the analyzer knows about it.

Plain Python dicts, no YAML, no I/O. `lookup()` is the only entry point rules
and the graph builder use; it falls back to a small set of prefix rules so an
unlisted member of a known family still lands in the right stage.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Optional, Tuple

from .entries import E, Entry
from .gbm_tbl import GBM, GBM_METHODS
from .hf_tbl import HF_DATA, HF_DATA_METHODS
from .hooks_tbl import (
    HOOK_OWNER_BASES,
    HOOK_STAGES,
    LIGHTNING_HOOK_ROLES,
    LIGHTNING_METHOD_ENTRIES,
    LIGHTNING_ROOTS,
    hook_stage,
)
from .other_tbl import (
    ACCELERATE_METHODS,
    ARGPARSE_METHODS,
    FRAME_METHODS,
    HF_METHODS,
    KERAS_METHODS,
    LIGHTNING_METHODS,
    OTHER,
    WRAPPER_METHODS,
)
from .metrics_tbl import (
    METRIC_FAMILY_BASE,
    METRIC_OBJECTS,
    METRIC_OBJECT_METHODS,
)
from .pandas_tbl import FRAME_ACCESSORS, PANDAS, PANDAS_METHODS
from .stats_tbl import STATS, STATS_FAMILY_BASE, STATS_METHODS
from .timm_tbl import TIMM, TIMM_METHODS
from .sklearn_tbl import SKLEARN, SKLEARN_METHODS, STATELESS_TRANSFORMERS
from .tf_tbl import (
    KERAS_EXTRA,
    KERAS_EXTRA_METHODS,
    TFDATA,
    TFDATA_METHODS,
    TF_PREFIX_RULES,
)
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
    # FW-RECOG (CONTRACTS 11.23) - framework hooks and the model base set
    "HOOK_STAGES", "HOOK_OWNER_BASES", "LIGHTNING_HOOK_ROLES", "LIGHTNING_ROOTS",
    "hook_stage", "MODEL_BASES", "is_model_base",
    "CANONICAL_ALIASES", "canonical_alias",
    # GRAPH-R2 - pandas beyond the shape-preserving hop, time-series
    # estimators and metric objects.
    "FRAME_ACCESSORS", "FAMILY_BASES",
]

#: Every constructor / free function we recognise.
KNOWLEDGE: Dict[str, Entry] = {}
KNOWLEDGE.update(TORCH)
KNOWLEDGE.update(SKLEARN)
KNOWLEDGE.update(OTHER)
KNOWLEDGE.update(TFDATA)
KNOWLEDGE.update(KERAS_EXTRA)
KNOWLEDGE.update(HF_DATA)
KNOWLEDGE.update(GBM)
KNOWLEDGE.update(TIMM)
KNOWLEDGE.update(STATS)
KNOWLEDGE.update(PANDAS)
KNOWLEDGE.update(METRIC_OBJECTS)

#: Every *method* we recognise, keyed by its canonical base FQN.
METHODS: Dict[str, Entry] = {}
METHODS.update(TORCH_METHODS)
METHODS.update(SKLEARN_METHODS)
METHODS.update(KERAS_METHODS)
METHODS.update(HF_METHODS)
METHODS.update(LIGHTNING_METHODS)
METHODS.update(ARGPARSE_METHODS)
METHODS.update(FRAME_METHODS)
METHODS.update(TFDATA_METHODS)
METHODS.update(KERAS_EXTRA_METHODS)
METHODS.update(HF_DATA_METHODS)
METHODS.update(GBM_METHODS)
METHODS.update(LIGHTNING_METHOD_ENTRIES)
METHODS.update(WRAPPER_METHODS)
METHODS.update(ACCELERATE_METHODS)
METHODS.update(TIMM_METHODS)
METHODS.update(STATS_METHODS)
METHODS.update(PANDAS_METHODS)
METHODS.update(METRIC_OBJECT_METHODS)

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
    # GRAPH-R2: the `torchmetric` family is what makes `acc.update(...)` /
    # `acc.compute()` resolve - a metric object with no family answered to
    # nothing, which is the entire point of holding one.
    ("torchmetrics.", E("metric", "eval", "torchmetrics", "METRIC", (),
                        "torchmetric", 0.8)),
    # vision-04: timm is the de-facto standard backbone / augmentation /
    # scheduler library for modern image classification, and there was no timm
    # row anywhere - so a timm project rendered with no model, no loss, no
    # forward and no backward, and `workspace.frameworks` did not even name the
    # library. The exact rows live in `timm_tbl.py`; this is the family net.
    ("timm.models.", E("model", "model", "torch", "MODEL_FACTORY", ("MODEL",), "module", 0.8)),
    ("timm.loss.", E("loss", "objective", "torch", "LOSS_CLS", ("LOSS",), None, 0.8)),
    ("timm.optim.", E("optimizer", "train", "torch", "OPTIMIZER", ("OPTIMIZER",), "optimizer", 0.8)),
    ("timm.scheduler.", E("scheduler", "train", "torch", "SCHEDULER", (), "scheduler", 0.8)),
    ("timm.data.", E("transform", "preprocess", "torch", "TRANSFORM", (), None, 0.7)),
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
) + TF_PREFIX_RULES

#: GRAPH-R2. Receiver families contributed by the tables that define them,
#: so `ir/resolve_receivers._FAMILY_BASE` reads one mapping instead of keeping
#: a transcription of every table's private choice.
FAMILY_BASES: Dict[str, str] = {}
FAMILY_BASES.update(STATS_FAMILY_BASE)
FAMILY_BASES.update(METRIC_FAMILY_BASE)

_ALIAS_PREFIXES = (("tf.", "tensorflow."),)

#: VIS2-10 / DGRG2-13. Framework classes that **are** the torch class they are
#: aliased to - `monai.data.DataLoader`, `torch_geometric.loader.*` and
#: `accelerate`'s prepared loaders all subclass `torch.utils.data.DataLoader`
#: and take the same `shuffle=` / `num_workers=` with the same semantics. An
#: alias, not a re-description: the whole MLV1xx / MLV2xx family then applies
#: verbatim, which is what "the rule matches a canonical FQN" (iron law 1) is
#: for. `ir/resolve` rewrites `canonical_fqns` through this map, so a rule that
#: asks `ctx.calls_of("torch.utils.data.DataLoader")` sees them.
CANONICAL_ALIASES: Dict[str, str] = {
    "torch.utils.data.dataloader.DataLoader": "torch.utils.data.DataLoader",
    "monai.data.DataLoader": "torch.utils.data.DataLoader",
    "monai.data.ThreadDataLoader": "torch.utils.data.DataLoader",
    "monai.data.dataloader.DataLoader": "torch.utils.data.DataLoader",
    "torch_geometric.loader.DataLoader": "torch.utils.data.DataLoader",
    "torch_geometric.loader.DataListLoader": "torch.utils.data.DataLoader",
    "torch_geometric.loader.NeighborLoader": "torch.utils.data.DataLoader",
    "torch_geometric.loader.LinkNeighborLoader": "torch.utils.data.DataLoader",
    "torch_geometric.loader.ClusterLoader": "torch.utils.data.DataLoader",
    "torch_geometric.loader.HGTLoader": "torch.utils.data.DataLoader",
    "torch_geometric.data.DataLoader": "torch.utils.data.DataLoader",
    "monai.data.Dataset": "torch.utils.data.Dataset",
    "monai.data.CacheDataset": "torch.utils.data.Dataset",
    "monai.data.PersistentDataset": "torch.utils.data.Dataset",
    "monai.data.SmartCacheDataset": "torch.utils.data.Dataset",
    "monai.data.ArrayDataset": "torch.utils.data.Dataset",
    "monai.data.decathlon_datalist.load_decathlon_datalist":
        "torch.utils.data.Dataset",
}


def canonical_alias(fqn: Optional[str]) -> Optional[str]:
    """The torch FQN a framework subclass is the same thing as, or `fqn`."""
    return CANONICAL_ALIASES.get(fqn or "", fqn)

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
    row = _prefix_entry(fqn)
    if row is None and alt != fqn:
        # FW-RECOG: the alias rewrite used to apply to the exact tables only, so
        # `tf.keras.applications.ResNet50` missed the `tensorflow.keras.
        # applications.` prefix rule that the same symbol written the long way
        # hits. A prefix family is a family whichever alias names it.
        row = _prefix_entry(alt)
    return row


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
    # FW-RECOG (11.23). tf.data / HuggingFace `datasets` / Keras callbacks /
    # boosting. `LIGHTNING_LOG`, `LIGHTNING_HPARAMS`, `LIGHTNING_CTL`,
    # `MODEL_SUMMARY`, `TFDATA_CARD` and every `LIGHTNING_HOOK_*` role are
    # **deliberately absent**: they are recognised so that no symbol is
    # fabricated for them, and not drawn, because a per-batch `self.log(...)`
    # is not a node anybody wants five of.
    "TFDATA_MAP", "TFDATA_SHUFFLE", "TFDATA_BATCH", "TFDATA_PREFETCH",
    "TFDATA_SUBSET", "TFDATA_OP", "HF_MAP", "HF_SHUFFLE", "HF_DATA_OP",
    "COLLATOR", "CALLBACK", "GBM_TRAIN",
    # vision-04 / INFRA-03 / INFRA-04. timm, fastai, ignite and DeepSpeed:
    # each of these was a lane the analyzer declared ABSENT on correct code
    # because the call that fills it had no knowledge row at all.
    # `SCHED_STEP_BATCH` is timm's per-batch `step_update`, kept distinct from
    # `SCHED_STEP` because "which cadence" is precisely MLV207's question.
    "SCHED_STEP_BATCH", "EMA_UPDATE",
    "FASTAI_LEARNER", "FASTAI_FIT", "FASTAI_EVAL",
    "IGNITE_TRAIN", "IGNITE_EVAL", "IGNITE_RUN",
    # GRAPH-R2 (knowledge/pandas_tbl.py, knowledge/metrics_tbl.py). The pandas
    # families that change what the data means, and the metric objects.
    # `FRAME_OP` stays transparent; these do not. `HF_METRIC` is the
    # `evaluate.load(...)` construction, `METRIC_UPDATE` the in-loop feed, and
    # `KERAS_EXPORT` the SavedModel hand-off that had no row at all.
    "FRAME_TEMPORAL", "FRAME_RESHAPE", "FRAME_WRITE",
    "HF_METRIC", "METRIC_UPDATE", "KERAS_EXPORT",
})

# ---------------------------------------------------------------------------
# frameworks
# ---------------------------------------------------------------------------
#: Framework enum values from `contracts/graph.schema.json`.
FRAMEWORKS = ("torch", "sklearn", "pandas", "numpy", "keras", "tf", "hf",
              "lightning", "imblearn", "torchvision", "torchmetrics",
              "albumentations", "xgboost", "lightgbm", "other")

_MODULE_FRAMEWORK = {
    # INFRA-03 / vision-04: a framework MLView does not name is a framework the
    # reader has no hint MLView did not model, and "stage absent" then reads as
    # a property of the code rather than as a blind spot. These map onto the
    # nearest `Framework` enum value rather than inventing one, which would be
    # a schema change.
    "timm": "torch",
    "fastai": "torch",
    "ignite": "torch",
    "deepspeed": "torch",
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

#: FW-RECOG (11.23). Bases whose subclass **is a model**, so the class node is
#: drawn in the Model lane with `kind: model`. A `LightningModule` really is an
#: `nn.Module` subclass, so this is a widening of a base set, never a claim
#: about a class that does not have one. `ClassIR.is_nn_module` keeps its exact
#: torch meaning; readers that mean "a model class" ask `is_model_module`.
#: VIS2-11 adds the three torch containers. `class ConvNormActivation(
#: nn.Sequential)` is torchvision's own idiom and the shape every modern
#: backbone block is written in, and `resolved_bases` for it holds
#: `torch.nn.Sequential` and not `torch.nn.Module` - so MLV301's architecture
#: probe would not look inside it, the BatchNorm and the Dropout it passes to
#: `super().__init__(...)` were invisible, and an identical network reported
#: `medium / 0.51 / possible` instead of `high / 0.85` - below
#: `mlview.minConfidence`, so the finding never reached the Problems panel at
#: all. A `Sequential` subclass IS an `nn.Module` subclass; saying so is a
#: widening of a base set, not a claim about a class that lacks one.
MODEL_BASES = frozenset({"torch.nn.Module", "torch.nn.Sequential",
                         "torch.nn.ModuleList", "torch.nn.ModuleDict"}) | frozenset(
    "%s.LightningModule" % root for root in LIGHTNING_ROOTS)


def is_model_base(bases) -> bool:
    """True when any resolved base makes this class a model class."""
    return any(base in MODEL_BASES for base in bases or ())

WRAPPER_LABELS = tuple(sorted(set(WRAPPER_FQNS.values())))
