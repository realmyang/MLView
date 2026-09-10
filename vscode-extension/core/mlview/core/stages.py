"""The eight-stage classifier.

Ops take the stage of their knowledge-table row. Units take a weighted vote of
their ops, corrected by structural evidence (an `nn.Module` subclass is
`model`; a function containing `backward` + `step` is `train`; a function
containing `eval()` / `no_grad` / metrics / `predict` is `eval`). Ties break
towards the earlier stage in pipeline order.

Every vote is recorded as `Evidence` so the inspector can answer
"why is this node in this stage?".
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from ..knowledge import STAGE_IDS
from .graph import Evidence

__all__ = ["STAGE_PRIORITY", "vote_stage", "unit_stage", "name_stage", "op_stage"]

STAGE_PRIORITY = {sid: i for i, sid in enumerate(STAGE_IDS)}

_NAME_STAGE = (
    (re.compile(r"(?i)^(validate|validation|evaluate|evaluation|eval|test|testing|"
                r"predict|inference|infer|score)"), "eval"),
    (re.compile(r"(?i)^(train|fit|run_train|training|optimize|epoch)"), "train"),
    (re.compile(r"(?i)^(build|make|create|get|load|prepare)_?(data|loader|loaders|"
                r"dataset|datasets|dataloader)"), "data"),
    (re.compile(r"(?i)^(preprocess|transform|clean|scale|normalize|featur)"), "preprocess"),
    (re.compile(r"(?i)^(build|make|create|get)_?(model|net|network|classifier)"), "model"),
    (re.compile(r"(?i)^(save|export|serve|deploy|checkpoint)"), "deliver"),
    (re.compile(r"(?i)^(config|configure|parse_args|get_config|setup)"), "config"),
    (re.compile(r"(?i)^(loss|criterion|objective)"), "objective"),
)


def name_stage(name: str) -> Optional[str]:
    """Weakest evidence: what the identifier suggests. Tiebreak only."""
    for pattern, stage in _NAME_STAGE:
        if pattern.match(name or ""):
            return stage
    return None


def op_stage(entry, fallback: str = "config") -> str:
    """Stage for a knowledge-table row."""
    if entry is None:
        return fallback
    return entry.get("stage") or fallback


def vote_stage(votes: Dict[str, float]) -> Optional[str]:
    """Highest total weight; ties break towards the earlier pipeline stage."""
    if not votes:
        return None
    best = max(votes.items(), key=lambda kv: (kv[1], -STAGE_PRIORITY.get(kv[0], 99)))
    return best[0]


def unit_stage(unit_kind: str, op_votes: Dict[str, float], flags: Dict[str, bool],
               name: str = "") -> Tuple[str, List[Evidence]]:
    """Classify one unit. Returns (stage, evidence)."""
    evidence: List[Evidence] = []
    votes: Dict[str, float] = {k: v for k, v in op_votes.items() if v > 0}

    if flags.get("is_nn_module"):
        return "model", [Evidence("class_base", "class derives torch.nn.Module", 1.0)]
    if flags.get("is_dataset"):
        return "data", [Evidence("class_base", "class derives torch.utils.data.Dataset", 1.0)]
    if flags.get("is_lightning"):
        return "model", [Evidence("class_base", "class derives LightningModule", 1.0)]

    if flags.get("has_backward") and flags.get("has_step"):
        evidence.append(Evidence("context_confirmed",
                                 "contains backward() and an optimizer step", 1.0))
        return "train", evidence
    if flags.get("has_backward"):
        evidence.append(Evidence("context_confirmed", "contains backward()", 0.9))
        votes["train"] = votes.get("train", 0.0) + 2.0
    if flags.get("is_eval_region") and not flags.get("has_backward"):
        evidence.append(Evidence(
            "context_confirmed",
            "forward pass with no backward, under eval()/no_grad or metrics", 0.9))
        votes["eval"] = votes.get("eval", 0.0) + 2.0

    if unit_kind == "entrypoint":
        votes["config"] = votes.get("config", 0.0) + 1.0
        evidence.append(Evidence("context_confirmed", "module entrypoint", 0.6))

    if votes:
        winner = vote_stage(votes)
        detail = ", ".join("%s=%.1f" % (s, votes[s]) for s in sorted(votes))
        evidence.append(Evidence("knowledge_table", "op stage votes: %s" % detail, 1.0))
        return winner or "config", evidence

    guess = name_stage(name)
    if guess:
        evidence.append(Evidence("name_regex", "unit name suggests %s" % guess, 0.8))
        return guess, evidence
    evidence.append(Evidence("context_confirmed", "no ops recognised in this unit", 0.4))
    return "config", evidence
