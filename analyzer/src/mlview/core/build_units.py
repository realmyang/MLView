"""Unit nodes: functions, classes, framework hooks, entrypoints and loops.

One half of `GraphBuilder` (see `core/build.py`), as a mixin: every method here
runs on a `GraphBuilder` instance and uses the state its `__init__` declares.
"""

from __future__ import annotations

from typing import Optional

from ..ir.locs import loc_of
from ..ir.model import CallSite, ClassIR, ModuleIR
from . import hooks
from .graph import Node, Port
from .views import class_sublabel, loop_is_eval, parsed_view

__all__ = ["UnitsMixin"]


class UnitsMixin:
    """`GraphBuilder`'s unit half - mixed in, never instantiated alone."""

    def _create_units(self) -> None:
        for module in self._modules():
            self._create_module_units(module)

    def _create_module_units(self, module: ModuleIR) -> None:
        module_scope = module.module_scope
        # top-level functions
        for qualname in sorted(module.functions):
            func = module.functions[qualname]
            if func.is_method or func.parent_function is not None:
                continue
            if func.scope.parent is not module_scope:
                continue
            node = self._make_node(
                module.relpath, func.qualname, "function",
                level="unit", stage="config", label="%s()" % func.name,
                loc=func.loc, defLoc=func.loc, parent=None,
                dynamic=func.scope.is_dynamic, confidence=0.95)
            self.scope_unit[func.scope.qualname] = node
            self.unit_for_node[node.id] = func
        # classes
        for qualname in sorted(module.classes):
            cls = module.classes[qualname]
            # FW-RECOG: `is_model_module`, not `is_nn_module` - a
            # LightningModule subclass is a model class, and drawing it as
            # `kind: class` in Config next to an `nn.Module` drawn as
            # `kind: model` in Model was the single most visible symptom.
            is_model = cls.is_model_module
            kind = "model" if is_model else "class"
            node = self._make_node(
                module.relpath, cls.qualname, kind,
                level="unit", stage="model" if is_model else "config",
                label=cls.name, loc=cls.loc, defLoc=cls.loc, parent=None,
                dynamic=cls.scope.is_dynamic, confidence=0.95,
                sublabel=class_sublabel(cls))
            self.scope_unit[cls.scope.qualname] = node
            self.unit_for_node[node.id] = cls
            self._create_hook_units(module, cls, node)
        # module entrypoint
        if module.entry_stmts or module.main_guard is not None:
            anchor = module.main_guard or module.entry_stmts[0]
            parsed = parsed_view(module)
            loc = loc_of(parsed, anchor)
            qualname = "%s.__main__" % (module.dotted or module.relpath)
            node = self._make_node(
                module.relpath, qualname, "entrypoint",
                level="unit", stage="config",
                label=module.relpath.split("/")[-1],
                sublabel="module entrypoint" if module.main_guard else "module scope",
                loc=loc, defLoc=loc, parent=None,
                dynamic=module.module_scope.is_dynamic, confidence=0.95)
            self.entry_unit[module.relpath] = node
            self.unit_for_node[node.id] = module
        # loops that deserve their own unit
        for loop in module.loops:
            if loop.kind not in ("epoch", "batch", "fold"):
                continue
            kind = "eval_loop" if loop_is_eval(loop) else "train_loop"
            attrs = {
                "loopKind": loop.kind,
                "depth": str(loop.depth),
                "insideNoGrad": "true" if loop.inside_no_grad else "false",
                "insideAutocast": "true" if loop.inside_autocast else "false",
            }
            if loop.iter_text:
                attrs["iterates"] = loop.iter_text
            label = (loop.loc.symbol or "%s loop" % loop.kind)
            node = self._make_node(
                module.relpath, loop.qualname or "%s.%s_loop" % (loop.scope.qualname, loop.kind),
                kind, level="unit", stage="train",
                label=label, sublabel="%s loop · depth %d" % (loop.kind, loop.depth),
                loc=loop.loc, parent=None, attrs=attrs,
                dynamic=loop.scope.is_dynamic, confidence=0.95)
            if loop.iterates is not None:
                node.consumes = [Port(loop.iter_text or loop.iterates.name,
                                      tuple(loop.iterates.tags))]
            self.loop_unit[id(loop)] = node
            self.loop_for_node[node.id] = loop
            self.unit_for_node[node.id] = loop
            for target in loop.targets:
                # the loop is the producer of its own targets: `images` comes
                # out of `for images, labels in train_loader`, so the batch
                # loop is where the Data lane hands over to the model
                self.loop_target_node.setdefault((loop.scope.qualname, target), node)

        # parents: a loop unit hangs off its enclosing function / class / entrypoint
        for loop in module.loops:
            node = self.loop_unit.get(id(loop))
            if node is None:
                continue
            parent = self._scope_unit_for(loop.scope, module)
            if parent is not None and parent.id != node.id:
                node.parent = parent.id
                self._children.setdefault(parent.id, []).append(node)

    def _create_hook_units(self, module: ModuleIR, cls: ClassIR, owner: Node) -> None:
        """FW-RECOG: one unit node per framework hook, under its class.

        A `LightningModule`'s methods are called by `Trainer.fit`, never by the
        module, so before this every op in `training_step` and every op in
        `validation_step` hung off the same class node - which
        `stages.unit_stage` pins to `model` by its base. The result was a
        correct Lightning program reporting no objective and no eval stage.
        """
        for unit in hooks.model_hooks(cls):
            func = unit.func
            node = self._make_node(
                module.relpath, func.qualname, "function",
                level="unit", stage=unit.stage, label="%s()" % func.name,
                sublabel=hooks.hook_sublabel(unit),
                loc=func.loc, defLoc=func.loc, parent=owner.id,
                dynamic=func.scope.is_dynamic, confidence=0.9)
            self.scope_unit[func.scope.qualname] = node
            self.unit_for_node[node.id] = func
            self.hook_unit[id(func)] = node
            self.hook_stage[node.id] = (unit.stage, unit.why)
            self._children.setdefault(owner.id, []).append(node)

    def _scope_unit_for(self, scope, module: ModuleIR) -> Optional[Node]:
        cur = scope
        while cur is not None:
            node = self.scope_unit.get(cur.qualname)
            if node is not None:
                return node
            cur = cur.parent
        return self.entry_unit.get(module.relpath)

    def _owning_unit(self, call: CallSite) -> Optional[Node]:
        loop = call.loop
        while loop is not None:
            node = self.loop_unit.get(id(loop))
            if node is not None:
                return node
            loop = loop.parent_loop
        return self._scope_unit_for(call.scope, call.module)
