"""Framework hook units and the `Trainer.fit` control edges (FW-RECOG).

A `LightningModule` never calls its own methods: `Trainer.fit(model, ...)`
calls them. Before this, `analyzer/tests/clean/lightning_module.py` drew
`LitClassifier` as `kind: class` in the Config lane, and the audit's Lightning
project reported *"not detected: preprocess, objective, eval, deliver"* on a
**correct** program - a graph that says nothing happened where the whole
program happens.

This module is the graph-side half of `knowledge/hooks_tbl.py`. It answers two
questions and holds no state:

* `model_hooks(cls)` - which of a class's methods are framework hooks, and in
  which lane each one's body belongs. `core/build.py` mints one **unit** node
  per hook under the class node, so the ops written in `training_step` land in
  Train and the ops written in `validation_step` land in Evaluate, instead of
  all of them voting on one class node that is pinned to Model by its base.
* `trainer_hooks(call)` - for a `Trainer.fit` / `.validate` / `.test` /
  `.predict` call, the hook methods that call actually runs, found through the
  **binding** behind its model / datamodule argument (iron law 1: never a
  name). `core/build.py` draws a `control` edge (`subkind: "enter"`) from the
  call's op node into each of them, which is the honest rendering of "the
  framework owns the loop": the arrow exists, and it starts where the user's
  code hands control over.

What this cannot do, stated rather than hidden: a hook reached only through a
`Trainer` built in another module and passed in as a parameter has no binding
to resolve, so no control edge is drawn for it. The hook units still exist -
the class is still read correctly - the edge is what is missing, and a missing
edge is visible in a way a missing lane is not.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .. import knowledge as K
from ..ir.bindings import binding_of
from ..ir.model import CallSite, ClassIR, FunctionIR
from ..ir.symbols import dotted_text

__all__ = ["HookUnit", "model_hooks", "trainer_hooks", "hook_sublabel"]

#: `Trainer` method role -> the **phase words** whose hooks that method runs.
#: `trainer.test(...)` does not run `training_step` and `trainer.fit(...)` does
#: not run `test_step`, and drawing those arrows would be a false statement
#: about control flow, not merely a busy diagram.
_ENTRY_POINTS: Dict[str, Tuple[str, ...]] = {
    "LIGHTNING_FIT": ("train", "training", "val", "validation", "sanity", "fit",
                      "optimizer", "backward", "zero_grad", "checkpoint"),
    "LIGHTNING_VAL": ("val", "validation", "sanity"),
    "LIGHTNING_TEST": ("test",),
}

#: Hooks every entry point runs, whatever phase it is in.
_PHASE_NEUTRAL = frozenset({"setup", "prepare_data", "teardown", "forward",
                            "transfer_batch_to_device", "on_after_batch_transfer",
                            "on_before_batch_transfer"})

#: Keyword arguments of `Trainer.fit(...)` that name a hook-owning object.
_OWNER_KWARGS = ("model", "datamodule", "train_dataloaders", "val_dataloaders",
                 "dataloaders", "ckpt_path")

#: How many hooks one `Trainer` call draws a control edge into. A DataModule
#: plus a module can publish twenty hooks between them, and twenty arrows out
#: of one node is a hairball, not a diagram. The cap is above what a normal
#: module and datamodule publish together (eight on the shipped fixture), so it
#: bites only on a deliberately exhaustive subclass.
MAX_CONTROL_EDGES = 12


class HookUnit(object):
    """One recognised framework hook: the method, its lane and why."""

    __slots__ = ("func", "stage", "role", "why")

    def __init__(self, func: FunctionIR, stage: str, role: str, why: str) -> None:
        self.func = func
        self.stage = stage
        self.role = role
        self.why = why

    @property
    def name(self) -> str:
        return self.func.name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "HookUnit(%s -> %s)" % (self.func.qualname, self.stage)


def hook_sublabel(unit: "HookUnit") -> str:
    """The sublabel a hook unit carries in the inspector."""
    return "framework hook · %s" % K.STAGE_LABELS.get(unit.stage, unit.stage)


def model_hooks(cls: ClassIR) -> List[HookUnit]:
    """Every recognised framework hook on `cls`, in source order.

    Empty for any class that is not a hook owner, which is every class in a
    workspace with no Lightning in it - so this costs a `resolved_bases` scan
    and nothing else on the projects that do not use it.
    """
    if cls is None or not cls.is_hook_owner:
        return []
    units: List[HookUnit] = []
    for name in sorted(cls.methods):
        row = K.hook_stage(name)
        if row is None:
            continue
        func = cls.methods[name]
        if func.node is None:
            continue                     # pragma: no cover - defensive
        stage, role, why = row
        units.append(HookUnit(func, stage, role, why))
    units.sort(key=lambda u: (u.func.loc.line, u.func.loc.col, u.func.name))
    return units


def _owner_classes(call: CallSite) -> List[ClassIR]:
    """The hook-owning workspace classes this call's arguments name."""
    seen: Dict[int, ClassIR] = {}
    candidates = list(call.args)
    for key in _OWNER_KWARGS:
        node = call.kwarg_nodes.get(key)
        if node is not None:
            candidates.append(node)
    for node in candidates:
        name = dotted_text(node)
        if not name:
            continue
        ref = binding_of(name, call.scope)
        cls = ref.class_ir if ref is not None else None
        if cls is not None and cls.is_hook_owner and id(cls) not in seen:
            seen[id(cls)] = cls
    return list(seen.values())


def trainer_hooks(call: CallSite) -> List[Tuple[FunctionIR, str]]:
    """`(hook method, edge label)` for a Lightning `Trainer` entry point.

    Empty when the call is not one, when no argument resolves to a hook-owning
    class, or when the owner publishes no recognised hook.
    """
    role = K.role_of(call.fqn)
    if role not in _ENTRY_POINTS:
        return []
    phases = _ENTRY_POINTS[role]
    out: List[Tuple[FunctionIR, str]] = []
    for cls in _owner_classes(call):
        for unit in model_hooks(cls):
            name = unit.name
            if name not in _PHASE_NEUTRAL and not any(p in name for p in phases):
                continue
            out.append((unit.func, "%s()" % name))
    return out[:MAX_CONTROL_EDGES]
