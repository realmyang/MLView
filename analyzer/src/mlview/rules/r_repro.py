"""Reproducibility rules: MLV601 (no seed at all), MLV602 (unseeded split)."""

from __future__ import annotations

from typing import Iterable, List, Optional

from ..core.graph import Issue, Node
from .fixes import random_state_fix
from .helpers import is_seeded
from .registry import rule

__all__ = ["no_seed_anywhere", "split_without_random_state"]

_TRAIN_EVIDENCE_ROLES = ("FIT", "FIT_TRANSFORM", "SPLIT", "OPT_STEP", "BACKWARD",
                         "KERAS_FIT", "LIGHTNING_FIT", "HF_TRAIN")

#: Frameworks that actually own a random source worth seeding. Without one
#: of these in the workspace there is nothing for a seed to make reproducible.
_RANDOM_FRAMEWORKS = frozenset({"torch", "sklearn", "numpy", "keras", "tf", "hf",
                                "lightning", "torchvision", "imblearn", "xgboost",
                                "lightgbm", "albumentations"})


@rule(code="MLV601", severity="low", base_prior=0.90, frameworks=(),
      rule_version=1, tags=["reproducibility"], absence=True,
      title="No random seed set anywhere",
      why="Two runs of this pipeline give different splits, initial weights and "
          "results, so a reported number cannot be reproduced or compared.",
      fix_hint="Seed every source at startup: random.seed(s); np.random.seed(s); "
               "torch.manual_seed(s); torch.cuda.manual_seed_all(s).")
def no_seed_anywhere(ctx) -> Iterable[Issue]:
    if is_seeded(ctx):
        return []
    if not ctx.frameworks & _RANDOM_FRAMEWORKS:
        # No ML framework in the workspace: a `for i in range(10)` is just a
        # loop, and there is no randomness for a seed to pin down.
        return []
    trains = ctx.calls_with_role(*_TRAIN_EVIDENCE_ROLES)
    loops = ctx.loops("epoch") + ctx.loops("batch")
    if not trains and not loops:
        return []
    anchor = _anchor(ctx, loops)
    if anchor is None:
        return []
    witness = trains[0] if trains else None
    evidence = [
        ("negation_absent",
         "no torch.manual_seed / numpy.random.seed / random.seed / seed_everything / "
         "random_state= anywhere in the workspace", 1.0),
        ("context_confirmed",
         "training evidence: %s" % (witness.fqn if witness is not None
                                    else "%d training loop(s)" % len(loops)), 1.0),
        ("scope_static", "workspace-wide check", 1.0),
    ]
    related = []
    if witness is not None:
        related.append(("construction", witness.loc, "randomness starts here"))
    return [ctx.issue(
        message="No call to torch.manual_seed / numpy.random.seed / random.seed / "
                "seed_everything and no random_state= keyword appears in the %d analyzed "
                "file(s), while %s runs here."
                % (len(ctx.modules),
                   witness.short_name + "()" if witness is not None else "a training loop"),
        loc=anchor.loc, node_ids=[anchor], related=related, evidence=evidence,
        dynamic=False)]


def _anchor(ctx, loops) -> Optional[Node]:
    """The ranked primary entrypoint node, else the first training loop.

    `workspace.entrypoints` is already ranked (main guard first, then
    train.py / main.py / run.py); alphabetical order over the entry-unit
    map would anchor "no seed anywhere" on whatever file sorts first,
    which is typically `config.py`.
    """
    entry = ctx.builder.entry_unit
    ranked = tuple(getattr(ctx.graph, "entrypoints", ()) or ())
    for relpath in ranked:
        node = entry.get(relpath)
        if node is not None:
            return node
        # a library-shaped train.py has no module-scope block: its training loop
        # is where a reader looks for the seed, and it still beats the *next*
        # entrypoint in the ranking (typically config.py, which sorts first).
        for loop in loops:
            if loop.loc.file == relpath:
                node = ctx.node_for_loop(loop)
                if node is not None:
                    return node
    for loop in loops:
        node = ctx.node_for_loop(loop)
        if node is not None:
            return node
    for relpath in sorted(entry):
        return entry[relpath]
    for node in ctx.graph.nodes:
        if node.level != "op":
            return node
    return ctx.graph.nodes[0] if ctx.graph.nodes else None


# ---------------------------------------------------------------------------
# MLV602
# ---------------------------------------------------------------------------
#: Splitters that shuffle by default - no keyword needed to make them random.
_ALWAYS_RANDOM = {
    "sklearn.model_selection.train_test_split": "random_state",
    "sklearn.model_selection.ShuffleSplit": "random_state",
    "sklearn.model_selection.StratifiedShuffleSplit": "random_state",
    "sklearn.model_selection.GroupShuffleSplit": "random_state",
    "torch.utils.data.random_split": "generator",
    # FW-RECOG: the HuggingFace spelling. `Dataset.train_test_split` shuffles by
    # default and takes `seed=`, so an unseeded call really is a different split
    # on every run - the rule was structurally unreachable on the HF path only
    # because the knowledge tables had no row for it.
    "datasets.Dataset.train_test_split": "seed",
}
#: Splitters that are deterministic unless `shuffle=True` is passed.
_SHUFFLE_OPTIONAL = {
    "sklearn.model_selection.KFold": "random_state",
    "sklearn.model_selection.StratifiedKFold": "random_state",
    "sklearn.model_selection.GroupKFold": "random_state",
    "sklearn.model_selection.RepeatedKFold": "random_state",
    "sklearn.model_selection.RepeatedStratifiedKFold": "random_state",
}


@rule(code="MLV602", severity="low", base_prior=0.95,
      frameworks=["sklearn", "torch", "hf"],
      rule_version=1, tags=["reproducibility", "data"],
      title="Split without random_state / generator",
      why="A different split every run means the reported score moves for reasons that "
          "have nothing to do with the model, and a regression cannot be told from noise.",
      fix_hint="Pass random_state=42 (scikit-learn) or "
               "generator=torch.Generator().manual_seed(42) (PyTorch) so the split is "
               "reproducible independently of global RNG state.")
def split_without_random_state(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    seeded = is_seeded(ctx)
    for call in _random_splits(ctx):
        keyword = _keyword_for(call)
        if keyword is None or _has_keyword(call, keyword):
            continue
        node = ctx.node_for_call(call) or ctx.unit_for_call(call)
        if node is None:
            continue
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (call.fqn or call.short_name), 1.0),
            ("negation_absent", "no %s= keyword at this call site" % keyword, 1.0),
        ]
        if seeded:
            evidence.append(("context_confirmed",
                             "a global seed is set elsewhere in the workspace, which "
                             "does make this split reproducible - an explicit %s= is "
                             "still better locality" % keyword, 0.65))
        if not call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % call.scope.qualname, 1.0))
        wording = ("prefer an explicit %s= here" % keyword if seeded
                   else "the split is different on every run")
        issues.append(ctx.issue(
            message="%s at %s:%d takes no %s=, so %s."
                    % (call.short_name, call.loc.file, call.loc.line, keyword, wording),
            loc=call.loc, node_ids=[node],
            related=[("split_site", call.loc, "split happens here")],
            evidence=evidence, dynamic=call.scope.is_dynamic,
            # H5. Note what `seeded` does above: a workspace that seeds
            # globally lands this finding in `possible`, and `ctx.issue` then
            # drops the edit. Prose is the right answer for "prefer an explicit
            # random_state= here"; an edit is not.
            fix=random_state_fix(ctx, call, keyword)))
    return issues


def _random_splits(ctx) -> List:
    """Split / splitter constructions whose output actually depends on an RNG."""
    out = []
    for call in ctx.calls_with_role("SPLIT", "SPLITTER"):
        fqn = call.fqn or ""
        if fqn in _ALWAYS_RANDOM:
            # ANA-9. `train_test_split(..., shuffle=False)` is the documented way
            # to take a chronological cut, and it is deterministic: sklearn
            # *raises* if you also pass random_state=. Asking for one was a
            # false positive, and it is the exact shape MLV106's good fixture
            # has to write.
            if call.kwargs.get("shuffle") == "False":
                continue
            out.append(call)
        elif fqn in _SHUFFLE_OPTIONAL and call.kwargs.get("shuffle") == "True":
            out.append(call)
    out.sort(key=lambda c: (c.loc.file, c.loc.line, c.loc.col))
    return out


def _keyword_for(call) -> Optional[str]:
    fqn = call.fqn or ""
    return _ALWAYS_RANDOM.get(fqn) or _SHUFFLE_OPTIONAL.get(fqn)


def _has_keyword(call, keyword: str) -> bool:
    node = call.kwarg_nodes.get(keyword)
    if node is None:
        return bool(getattr(call, "has_kwargs_forward", False))
    import ast as _ast
    if isinstance(node, _ast.Constant) and node.value is None:
        return False
    return True
