"""Ops, transparency, stages, levels: what each call is and where it belongs.

One node per call whose canonical FQN the knowledge tables know, minus the
roles that are deliberately not drawn (`core/build_roles.py`): a transparent
role keeps the value flowing from its receiver rather than minting a box of its
own, and a call the resolver could not name becomes an `unknown` op only where
that is the honest answer.

The stage passes follow: a unit's lane is voted on by the ops inside it unless
a framework hook declared it, `_promote_levels` keeps every parent at a
strictly lower level than its child (stage > unit > op), and `_remap_ids`
rewrites the ids the earlier passes handed out when a node's stage moves.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Tuple

from .. import knowledge as K
from ..ir import config_values as CV
from ..ir.bindings import binding_of
from ..ir.model import (CallSite, ClassIR, FunctionIR, LoopIR, ModuleIR,
                        ValueRef)
from ..ir.symbols import dotted_text
from . import config_nodes, workspace_ops
from .build_roles import NOT_DRAWN_ROLES, TRANSPARENT_ROLES
from .graph import Evidence, Node, Port
from .ids import node_id
from .stages import unit_stage
from .views import clip_literal, loop_stage, op_sublabel, within_loop


class OpsMixin:
    """`GraphBuilder`'s op and stage passes. Mixed in, never instantiated."""

    # ------------------------------------------------------------------ ops
    def _create_ops(self) -> None:
        for module in self._modules():
            for call in module.calls:
                self._create_op(call, module)

    def _create_op(self, call: CallSite, module: ModuleIR) -> None:
        if K.role_of(call.fqn) in NOT_DRAWN_ROLES:
            # F9, applied before the unit shortcuts below: mapping the call
            # onto its class's node is what let a logging call carry edges.
            return
        # calls into workspace definitions map onto the definition's unit node,
        # unless the construction / factory return says something of its own
        # (`core/workspace_ops`), in which case the call site gets a box.
        if call.class_ir is not None:
            if workspace_ops.construction_op(self, call, module) is not None:
                return
            target = self.scope_unit.get(call.class_ir.scope.qualname)
            if target is not None:
                self.node_for_call[id(call)] = target
                return
        if call.target_function is not None:
            if workspace_ops.factory_op(self, call, module) is not None:
                return
            target = self.scope_unit.get(call.target_function.scope.qualname)
            if target is not None:
                self.node_for_call[id(call)] = target
                return

        selected = CV.selected_symbol(module, call)
        if selected is not None:
            # ANA-10: `factory = getattr(torch.optim, cfg["optimizer"])`. The
            # box is kept - deleting a node is exactly the silently-smaller
            # graph this project refuses - but it now names the symbol the
            # config selected instead of saying `unresolved call`, and the
            # construction on the next line resolves through it.
            config_nodes.selection_op(self, call, module, fqn=selected)
            return
        entry, _best_fqn = K.best_entry(call.canonical_fqns)
        resolved = CV.resolved_call_fqn(module, call)
        if resolved is not None:
            # ANA-10: `factory(...)` where `factory` came out of a resolved
            # `getattr`. The config-resolved symbol is more specific than the
            # `<fqn>.__call__` candidate `_canonical_for_receiver` proposes for
            # a called value, so it wins and the node carries the real FQN.
            resolved_entry = K.lookup(resolved)
            if resolved_entry is not None:
                entry = resolved_entry
        role = entry.get("role") if entry else None
        if role in TRANSPARENT_ROLES:
            # ... except the outer forward pass: `logits = model(images)` and
            # `loss = criterion(out, y)` are the two most drawn boxes in any
            # training diagram, and transparency swallowed both.
            workspace_ops.invoke_op(self, call, module, entry)
            return                       # otherwise: _resolve_transparent
        if entry is None or role not in K.OP_ROLES:
            alternatives = CV.alternatives_for(module, call)
            if alternatives is not None:
                config_nodes.selection_op(self, call, module,
                                          alternatives=alternatives)
                return
            # ANA-5a: an unresolved callee is a per-call fact, so it mints its
            # own `unknown` op whether or not the scope is dynamic. The old
            # gate (`is_dynamic and not canonical_fqns`) never fired for lambda
            # indirection, `match` dispatch or a `default_factory`, which is
            # exactly how a whole training step disappeared in silence.
            if call.unresolved_callee or (call.scope.is_dynamic
                                          and not call.canonical_fqns):
                self._create_unknown_op(call, module)
            return

        parent = self._owning_unit(call)
        qualname = "%s.%s" % (call.scope.qualname, call.var or call.short_name)
        label = call.var or "%s()" % call.short_name
        confidence = 0.95 if call.receiver is None else 0.85
        if call.scope.is_dynamic:
            confidence *= 0.7
        node = self._make_node(
            module.relpath, qualname, entry["kind"],
            level="op", stage=entry.get("stage") or "config", label=label,
            sublabel=op_sublabel(call, entry),
            fqn=resolved or call.fqn, framework=entry.get("framework"), var=call.var,
            loc=call.loc, parent=parent.id if parent else None,
            attrs=dict(call.kwargs), dynamic=call.scope.is_dynamic,
            confidence=confidence,
            stageEvidence=[Evidence("knowledge_table",
                                    "%s -> %s" % (resolved or call.fqn or call.short_name,
                                                  entry.get("stage")), 1.0)])
        if resolved is not None:
            node.stageEvidence.append(
                Evidence("fqn_resolved",
                         "selected by a getattr this run resolved to %s" % resolved,
                         0.9))
        if call.receiver is not None:
            node.stageEvidence.append(
                Evidence("fqn_resolved",
                         "receiver %s resolved to %s" % (call.receiver_name, call.fqn), 0.9))
        self.node_for_call[id(call)] = node
        self.call_for_node[node.id] = call
        if parent is not None:
            self._children.setdefault(parent.id, []).append(node)
            weight = float(entry.get("weight", 1.0))
            votes = self._op_votes.setdefault(parent.id, {})
            stage = entry.get("stage") or "config"
            votes[stage] = votes.get(stage, 0.0) + weight
        self._attach_ports(node, call)

    def _create_config_literals(self) -> None:
        """A `cfg = {...}` dict literal is a config source with no call behind it.

        `argparse` / `yaml.safe_load` / `json.load` values already have an op
        node (their call), but a literal has none - so mint one, otherwise the
        `config` edges out of it have nowhere to start.

        ANA-10 adds the second half of the same idea. A config container that
        travelled into a function - `def train(cfg=CFG)`, then
        `optimizer_for(model, cfg)` - is bound to a name in each of those
        scopes, and minting a node per name would draw the same dict three
        times. Every such **alias** is mapped onto the one node its container
        already has instead, which is what turns *"where does `batch_size` come
        from"* into a `config` edge from `CFG` into each consuming unit,
        **across files**, rather than three orphan boxes.
        """
        aliases: List[Tuple[ValueRef, ValueRef]] = []
        for module in self._modules():
            for scope in module.scopes:
                for name in sorted(scope.bindings):
                    ref = scope.bindings[name]
                    if not ref.is_config or ref.producer is not None or ref.loc is None:
                        continue
                    if id(ref) in self.config_literal_node:
                        continue
                    origin = CV.alias_origin(module, ref)
                    if origin is not None and origin is not ref:
                        aliases.append((origin, ref))
                        continue
                    parent = self._scope_unit_for(scope, module)
                    node = self._make_node(
                        module.relpath, "%s.%s" % (scope.qualname, name), "config",
                        level="op", stage="config", label=name,
                        sublabel=clip_literal(ref.literal), var=name,
                        loc=ref.loc, parent=parent.id if parent else None,
                        dynamic=scope.is_dynamic, confidence=0.9,
                        produces=[Port(name, tuple(ref.tags))],
                        stageEvidence=[Evidence("name_regex",
                                                "%s is a config-shaped literal" % name, 1.0)])
                    self.config_literal_node[id(ref)] = node
                    if parent is not None:
                        self._children.setdefault(parent.id, []).append(node)
                        votes = self._op_votes.setdefault(parent.id, {})
                        votes["config"] = votes.get("config", 0.0) + 0.5
        config_nodes.map_aliases(self, aliases)

    def _create_unknown_op(self, call: CallSite, module: ModuleIR) -> None:
        parent = self._owning_unit(call)
        qualname = "%s.%s" % (call.scope.qualname, call.var or call.short_name)
        construct = call.unresolved_callee
        if construct:
            # ANA-5a. `dynamic` stays the scope's own answer: the callee is
            # unresolved, the *scope* may be perfectly static, and saying
            # otherwise would contradict `dynamic_scope`'s own definition.
            sublabel = "unresolved callee · %s" % construct
            evidence = Evidence("scope_static",
                                "callee is %s, so the call could not be resolved"
                                % construct, 0.5)
            dynamic = call.scope.is_dynamic
        else:
            sublabel = "unresolved call"
            evidence = Evidence("scope_static",
                                "unresolved call in a dynamic scope", 0.5)
            dynamic = True
        node = self._make_node(
            module.relpath, qualname, "unknown",
            level="op", stage=parent.stage if parent else "config",
            label=call.var or "%s()" % call.short_name,
            sublabel=sublabel, loc=call.loc,
            parent=parent.id if parent else None, dynamic=dynamic, confidence=0.35,
            stageEvidence=[evidence])
        self.node_for_call[id(call)] = node
        self.call_for_node[node.id] = call
        if parent is not None:
            self._children.setdefault(parent.id, []).append(node)

    def _attach_ports(self, node: Node, call: CallSite) -> None:
        if call.var:
            ref = binding_of(call.var, call.scope)
            node.produces = [Port(call.var, tuple(ref.tags) if ref else ())]
        consumes: List[Port] = []
        for name, ref in self._consumed_values(call):
            if ref is not None and not any(p.name == name for p in consumes):
                consumes.append(Port(name, tuple(ref.tags)))
        node.consumes = consumes

    def _consumed_values(self, call: CallSite) -> List[Tuple[str, Optional[ValueRef]]]:
        out: List[Tuple[str, Optional[ValueRef]]] = []
        if call.receiver_name and call.receiver is not None:
            out.append((call.receiver_name, call.receiver))
        for arg in call.args:
            name = dotted_text(arg)
            if not name:
                continue
            out.append((name, binding_of(name, call.scope)))
        for key in sorted(call.kwarg_nodes):
            name = dotted_text(call.kwarg_nodes[key])
            if not name:
                continue
            out.append((name, binding_of(name, call.scope)))
        return out

    def _resolve_transparent(self) -> None:
        """Map forward/`.to()`/`.item()` calls onto the node they flow from."""
        for module in self._modules():
            for call in module.calls:
                if id(call) in self.node_for_call:
                    continue
                if K.role_of(call.fqn) in NOT_DRAWN_ROLES:
                    # F9 at the edge site. Without this a `self.log(...)` fell
                    # through to its receiver's class node and every argument
                    # of the logging call drew a `data` edge into the model.
                    continue
                node = self._through(call, 0)
                if node is not None:
                    self.node_for_call[id(call)] = node

    def _through(self, call: Optional[CallSite], depth: int) -> Optional[Node]:
        if call is None or depth > 4:
            return None
        node = self.node_for_call.get(id(call))
        if node is not None:
            return node
        ref = call.receiver
        if ref is not None:
            # The **construction site** answers before the class definition:
            # since `core/workspace_ops` draws `model = SmallCNN()` as its own
            # op, that node is the instance this chain flows from, and the class
            # node is where the instance was *declared*. Falling back to the
            # class keeps every graph that has no construction node unchanged.
            if ref.producer is not None:
                through = self._through(ref.producer, depth + 1)
                if through is not None:
                    return through
            if ref.class_ir is not None:
                unit = self.scope_unit.get(ref.class_ir.scope.qualname)
                if unit is not None:
                    return unit
        return None

    # --------------------------------------------------------------- stages
    def _assign_stages(self) -> None:
        remap: Dict[str, str] = {}
        for node in self.nodes:
            if node.level != "unit":
                continue
            owner = self.unit_for_node.get(node.id)
            votes = dict(self._op_votes.get(node.id, {}))
            for child in self._children.get(node.id, []):
                if child.level == "unit":
                    for stage, weight in self._op_votes.get(child.id, {}).items():
                        votes[stage] = votes.get(stage, 0.0) + weight * 0.5
            flags = self._unit_flags(owner)
            name = getattr(owner, "name", "") or node.label
            forced = self.hook_stage.get(node.id)
            if forced is not None:
                # FW-RECOG: the framework declares which lane a hook runs in.
                # Its ops do not get to outvote that - a `training_step` whose
                # only recognised call is `self.log` is still the train body.
                stage, evidence = forced[0], [Evidence("class_base", forced[1], 1.0)]
            elif isinstance(owner, LoopIR):
                stage, evidence = loop_stage(owner, votes)
            else:
                stage, evidence = unit_stage(node.kind, votes, flags, name)
            node.stage = stage
            node.stageEvidence = evidence
            wanted = None
            # vision-11: only a unit that actually OWNS a loop may be re-kinded
            # into one. Without this, a transform factory, a Keras `compile()`
            # wrapper and a callback-list builder were each drawn as a
            # `train_loop` / `eval_loop` - phantom loops on the diagram, next
            # to real training loops missing their forward and backward. The
            # `NodeKind` enum already has `function` for exactly this case, and
            # the stage lane is unaffected either way.
            if node.kind == "function" and stage in ("train", "eval") \
                    and _unit_has_loop(owner):
                wanted = "train_loop" if stage == "train" else "eval_loop"
            elif node.kind in ("train_loop", "eval_loop") and stage in ("train", "eval"):
                # the loop's own kind must agree with the lane it is drawn in:
                # an `eval_loop` in the Train lane (or the reverse) contradicts
                # its own stageEvidence in the inspector
                wanted = "train_loop" if stage == "train" else "eval_loop"
            if wanted and wanted != node.kind:
                node.kind = wanted
                new_id = node_id(node.loc.file, node.qualname, node.kind)
                if new_id != node.id:
                    remap[node.id] = new_id
                    node.id = new_id
        if remap:
            self._remap_ids(remap)
        self._by_id = {n.id: n for n in self.nodes}

    def _remap_ids(self, remap: Dict[str, str]) -> None:
        """A unit re-kinded by its stage gets a new content-addressed id."""
        for node in self.nodes:
            if node.parent in remap:
                node.parent = remap[node.parent]
        for mapping in (self._children, self._op_votes, self.hook_stage):
            for old, new in remap.items():
                if old in mapping:
                    mapping[new] = mapping.pop(old)
        for old, new in remap.items():
            if old in self.call_for_node:
                self.call_for_node[new] = self.call_for_node.pop(old)
            if old in self.loop_for_node:
                self.loop_for_node[new] = self.loop_for_node.pop(old)
            if old in self.unit_for_node:
                self.unit_for_node[new] = self.unit_for_node.pop(old)

    def _unit_flags(self, owner) -> Dict[str, bool]:
        flags = {"is_nn_module": False, "is_dataset": False, "is_lightning": False,
                 "has_backward": False, "has_step": False, "is_eval_region": False}
        if isinstance(owner, ClassIR):
            flags["is_nn_module"] = owner.is_nn_module
            flags["is_dataset"] = any(b.startswith("torch.utils.data.Dataset")
                                      for b in owner.resolved_bases)
            flags["is_lightning"] = any(b in K.WRAPPER_BASES for b in owner.resolved_bases)
            calls = owner.calls
        elif isinstance(owner, FunctionIR):
            calls = owner.calls
        elif isinstance(owner, ModuleIR):
            calls = [c for c in owner.calls if c.function is None and c.enclosing_class is None]
        elif isinstance(owner, LoopIR):
            calls = [c for c in owner.module.calls if within_loop(c.loop, owner)]
        else:
            calls = []
        forward = metrics = no_grad = eval_mode = False
        for call in calls:
            role = K.role_of(call.fqn)
            if role == "BACKWARD":
                flags["has_backward"] = True
            elif role in ("OPT_STEP", "ZERO_GRAD"):
                flags["has_step"] = True
            elif role == "FORWARD":
                forward = True
            elif role in ("METRIC", "SCORE_METRIC", "PREDICT", "CV"):
                metrics = True
            elif role == "NO_GRAD":
                no_grad = True
            elif role == "EVAL_MODE":
                eval_mode = True
            if call.inside_no_grad:
                no_grad = True
        flags["is_eval_region"] = bool((forward or metrics) and (no_grad or eval_mode or metrics))
        return flags

    def _promote_levels(self) -> None:
        """A unit that owns unit children is drawn one level up (stage > unit > op)."""
        for node in self.nodes:
            if node.level != "unit":
                continue
            if any(child.level == "unit" for child in self._children.get(node.id, [])):
                node.level = "stage"


def _unit_has_loop(owner) -> bool:
    """Does this unit really contain a loop? (vision-11)

    A `LoopIR` is one by definition. A `FunctionIR` knows its own loops, and a
    `ClassIR` is asked about its methods. Anything else - a unit with no owner
    the builder could attach - is left as a `function`, which is the honest
    answer when the question cannot be asked.
    """
    if isinstance(owner, LoopIR):
        return True
    if isinstance(owner, FunctionIR):
        if owner.loops:
            return True
        for child in ast.walk(owner.node):
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                return True
        return False
    if isinstance(owner, ClassIR):
        return any(_unit_has_loop(m) for m in owner.methods.values())
    return False
