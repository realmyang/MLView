"""Graph construction: units, ops, typed edges, hierarchy, caps.

Units  - every top-level function, every class, the module entrypoint block,
         and every epoch/batch/fold loop (as a child unit of its function).
Ops    - every call whose canonical FQN is known to the knowledge tables.
Edges  - `data` (producer -> consumer through a ValueRef), `call`
         (unit -> workspace definition), `control` (enter / back), `config`
         (a config value -> each consuming unit).

Containment is `Node.parent`, and a parent always sits at a strictly lower
level than its child (stage > unit > op), as the renderer requires.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .. import knowledge as K
from ..ir import config_values as CV
from ..ir.bindings import binding_of, names_in
from ..ir.locs import loc_of
from ..ir.model import CallSite, ClassIR, FunctionIR, Loc, LoopIR, ModuleIR, ValueRef, WorkspaceIR
from ..ir.symbols import dotted_text
from . import config_nodes, hooks
from .graph import Diagnostic, Edge, Evidence, MLGraph, Node, Port
from .ids import edge_id, node_id
from .stages import unit_stage
from .views import (
    class_sublabel,
    clip_literal,
    loop_is_eval,
    loop_stage,
    op_sublabel,
    parsed_view,
    within_loop,
)

__all__ = ["GraphBuilder", "build_graph", "NOT_DRAWN_ROLES"]

#: Roles whose call is not drawn as its own op - the value keeps flowing from
#: the receiver's node (a forward pass belongs to the model, `.item()` to the
#: loss, `.parameters()` to the model).
TRANSPARENT_ROLES = frozenset({"FORWARD", "TO_DEVICE", "ITEM", "DETACH",
                               "TO_NUMPY", "PARAMETERS", "FRAME_OP"})

#: FW-RECOG F9 - recognised so that no symbol is fabricated for them, and
#: deliberately absent from `K.OP_ROLES` so they mint no node: "five metric
#: cards per training step is noise, not recognition".
#:
#: F9 was written about **nodes**, and the edge site still ran. A call that
#: minted no node of its own was mapped onto its class's unit node, so
#: `self.log("train_loss", loss)` drew a `data` edge from the loss node into
#: the LightningModule - the diagram told the reader the loss flows into the
#: model, which is a false statement about dataflow; the loss is being logged.
#: `self.log_dict({...})` drew none, so the two logging calls were rendered
#: inconsistently as well. The exclusion belongs at both sites.
NOT_DRAWN_ROLES = frozenset({"LIGHTNING_LOG", "LIGHTNING_HPARAMS",
                             "LIGHTNING_CTL", "MODEL_SUMMARY", "TFDATA_CARD"})

_LOOP_BACK_LABEL = {"batch": "next batch", "epoch": "next epoch", "fold": "next fold",
                    "other": "next iteration"}


class GraphBuilder:
    """Turns a `WorkspaceIR` into an `MLGraph` (before rules run)."""

    def __init__(self, workspace: WorkspaceIR, max_nodes: int = 400):
        self.ws = workspace
        self.max_nodes = max_nodes
        self.nodes: List[Node] = []
        self.edges: Dict[str, Edge] = {}
        self.diagnostics: List[Diagnostic] = []
        self.truncated = False
        self._by_id: Dict[str, Node] = {}
        self._qualnames: Set[str] = set()
        self.scope_unit: Dict[str, Node] = {}        # scope qualname -> unit node
        self.loop_unit: Dict[int, Node] = {}         # id(LoopIR) -> unit node
        self.loop_target_node: Dict[Tuple[str, str], Node] = {}  # (scope, name) -> loop
        self.entry_unit: Dict[str, Node] = {}        # module relpath -> entrypoint node
        self.node_for_call: Dict[int, Node] = {}     # id(CallSite) -> node
        self.config_literal_node: Dict[int, Node] = {}   # id(ValueRef) -> node
        self.call_for_node: Dict[str, CallSite] = {}
        self.loop_for_node: Dict[str, LoopIR] = {}
        self.unit_for_node: Dict[str, object] = {}
        self._op_votes: Dict[str, Dict[str, float]] = {}
        self._children: Dict[str, List[Node]] = {}
        #: FW-RECOG: node id -> (stage, why) for a framework hook unit, whose
        #: lane is declared by the framework rather than voted on by its ops.
        self.hook_stage: Dict[str, Tuple[str, str]] = {}
        #: id(FunctionIR) -> the hook unit node minted for it.
        self.hook_unit: Dict[int, Node] = {}

    # ------------------------------------------------------------------ API
    def build(self) -> MLGraph:
        self._create_units()
        self._create_ops()
        self._create_config_literals()
        config_nodes.config_diagnostics(self)
        self._resolve_transparent()
        self._assign_stages()
        self._promote_levels()
        self._create_edges()
        graph = MLGraph(root=self.ws.root)
        graph.nodes = list(self.nodes)
        graph.edges = list(self.edges.values())
        graph.diagnostics = list(self.diagnostics)
        graph.frameworks = self.ws.frameworks
        graph.truncated = self.truncated
        graph.entrypoints = self._entrypoints()
        return graph

    # -------------------------------------------------------------- helpers
    def _modules(self) -> List[ModuleIR]:
        return [self.ws.modules[rel] for rel in sorted(self.ws.modules)]

    def _unique_qualname(self, qualname: str) -> str:
        if qualname not in self._qualnames:
            self._qualnames.add(qualname)
            return qualname
        index = 2
        while "%s#%d" % (qualname, index) in self._qualnames:
            index += 1
        out = "%s#%d" % (qualname, index)
        self._qualnames.add(out)
        return out

    def _add_node(self, node: Node) -> Node:
        if node.id in self._by_id:  # pragma: no cover - defensive
            return self._by_id[node.id]
        self.nodes.append(node)
        self._by_id[node.id] = node
        return node

    def _make_node(self, file: str, qualname: str, kind: str, **kwargs) -> Node:
        qualname = self._unique_qualname(qualname)
        node = Node(id=node_id(file, qualname, kind), kind=kind, qualname=qualname, **kwargs)
        return self._add_node(node)

    # ---------------------------------------------------------------- units
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
        # calls into workspace definitions map onto the definition's unit node
        if call.class_ir is not None:
            target = self.scope_unit.get(call.class_ir.scope.qualname)
            if target is not None:
                self.node_for_call[id(call)] = target
                return
        if call.target_function is not None:
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
            return                       # resolved in _resolve_transparent
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
            if ref.class_ir is not None:
                unit = self.scope_unit.get(ref.class_ir.scope.qualname)
                if unit is not None:
                    return unit
            if ref.producer is not None:
                return self._through(ref.producer, depth + 1)
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

    # ---------------------------------------------------------------- edges
    def _add_edge(self, kind: str, source: Node, target: Node, loc: Loc,
                  label: str = "", tags: Sequence[str] = (), subkind: Optional[str] = None,
                  confidence: float = 0.9) -> None:
        if source is None or target is None or source.id == target.id:
            return
        if kind != "control" and (source.parent == target.id or target.parent == source.id):
            # CONTRACTS section 1: "Containment is expressed by Node.parent, not
            # by an edge". A data/config/call edge between a node and the unit
            # that already contains it renders as an arrow from a card back into
            # its own group header, and says nothing the hierarchy does not.
            return
        eid = edge_id(source.id, kind, target.id, label)
        if eid in self.edges:
            return
        self.edges[eid] = Edge(id=eid, kind=kind, source=source.id, target=target.id,
                               loc=loc, subkind=subkind, label=label or None,
                               tags=tuple(tags), confidence=confidence)

    def _create_edges(self) -> None:
        for module in self._modules():
            parsed = parsed_view(module)
            for call in module.calls:
                self._data_edges_for_call(call, module, parsed)
                self._call_edge(call, module)
                self._hook_edges(call)
            for loop in module.loops:
                self._loop_edges(loop, module)
            self._config_edges(module, parsed)

    def _data_edges_for_call(self, call: CallSite, module: ModuleIR, parsed) -> None:
        target = self.node_for_call.get(id(call))
        if target is None:
            return
        by_node = getattr(module, "_calls_by_node", {})
        for arg in list(call.args) + [call.kwarg_nodes[k] for k in sorted(call.kwarg_nodes)]:
            name = dotted_text(arg)
            # REV-01: resolved against the store in effect *at this call*, not
            # the last store in the scope. `x = layer(x)` three times in one
            # `forward` used to wire every consumer to the final producer, so
            # the demo drew `self.pool -> self.stem` - a backwards arrow in the
            # one lane the Model view exists to get right.
            ref = binding_of(name, call.scope, at=call.loc.line,
                             in_loop=call.loop is not None) if name else None
            tags: Sequence[str] = ()
            if ref is not None:
                source = self._producer_node(ref)
                tags = ref.tags
                label = name
            elif isinstance(arg, ast.Call):
                # an inline producer: `criterion(model(images), labels)`
                inner = by_node.get(id(arg))
                if inner is None:
                    continue
                source = self._through(inner, 0)
                label = inner.var or inner.short_name
            else:
                continue
            if source is None or source.id == target.id:
                continue
            self._add_edge("data", source, target, loc_of(parsed, arg, symbol=None),
                           label=label, tags=tags, confidence=0.9)
        if call.receiver is not None:
            # FW-RECOG: a *chained* receiver has no name of its own -
            # `Dataset.from_tensor_slices(...).map(f)` binds nothing - so
            # `receiver_name` is None and the edge out of the previous link
            # used to be dropped. A five-call tf.data pipeline was seven nodes
            # and zero edges. The ValueRef carries the label instead.
            label = call.receiver_name or call.receiver.name
            source = self._producer_node(call.receiver)
            if source is not None and source.id != target.id and label:
                self._add_edge("data", source, target, call.loc,
                               label=label, tags=call.receiver.tags,
                               confidence=0.85)

    def _producer_node(self, ref: Optional[ValueRef]) -> Optional[Node]:
        if ref is None:
            return None
        if ref.producer is not None:
            node = self._through(ref.producer, 0)
            if node is not None:
                return node
        if ref.class_ir is not None:
            return self.scope_unit.get(ref.class_ir.scope.qualname)
        literal = self.config_literal_node.get(id(ref))
        if literal is not None:
            return literal
        if ref.scope is not None:
            return self.loop_target_node.get((ref.scope.qualname, ref.name))
        return None

    def _call_edge(self, call: CallSite, module: ModuleIR) -> None:
        target = None
        if call.target_function is not None:
            target = self.scope_unit.get(call.target_function.scope.qualname)
        elif call.class_ir is not None:
            target = self.scope_unit.get(call.class_ir.scope.qualname)
        if target is None:
            return
        source = self._owning_unit(call)
        if source is None:
            return
        self._add_edge("call", source, target, call.loc,
                       label="%s()" % call.short_name, confidence=0.95)

    def _hook_edges(self, call: CallSite) -> None:
        """FW-RECOG: `trainer.fit(model, ...)` enters the module's hooks.

        This is the arrow that says *the framework owns the loop*: it starts at
        the line where the user's code hands control over, and it ends in the
        `training_step` / `validation_step` / `configure_optimizers` bodies the
        Trainer will run. Without it those units are correct and unreachable.
        """
        source = self.node_for_call.get(id(call))
        if source is None:
            return
        for func, label in hooks.trainer_hooks(call):
            target = self.hook_unit.get(id(func))
            if target is None:
                continue
            self._add_edge("control", source, target, call.loc,
                           label="enter %s" % label, subkind="enter",
                           confidence=0.9)

    def _loop_edges(self, loop: LoopIR, module: ModuleIR) -> None:
        node = self.loop_unit.get(id(loop))
        if node is None:
            return
        source = self._enclosing_loop_node(loop) or self._by_id.get(node.parent or "")
        if source is not None:
            self._add_edge("control", source, node, loop.loc,
                           label="enter %s loop" % loop.kind, subkind="enter", confidence=1.0)
        children = self._children.get(node.id, [])
        # ops first (the last statement of the body), else the nested loop unit -
        # every drawn loop carries its iteration arrow.
        back = ([child for child in children if child.level == "op"]
                or list(children)
                or self._nested_loop_nodes(loop, module))
        if back:
            last = sorted(back, key=lambda n: (n.loc.line, n.loc.col))[-1]
            self._add_edge("control", last, node, loop.loc,
                           label=_LOOP_BACK_LABEL.get(loop.kind, "next iteration"),
                           subkind="back", confidence=1.0)
        if loop.iterates is not None:
            source = self._producer_node(loop.iterates)
            if source is not None:
                loc = loop.iter_loc or loop.loc
                self._add_edge("data", source, node, loc,
                               label=loop.iter_text or loop.iterates.name,
                               tags=loop.iterates.tags, confidence=0.9)

    def _nested_loop_nodes(self, loop: LoopIR, module: ModuleIR) -> List[Node]:
        """Unit nodes of the loops nested directly inside `loop`.

        A loop unit hangs off its *function* (invariant 1.1.2), so an epoch loop
        whose body is only an inner loop has no children at all - without this
        it would be drawn with no iteration arrow.
        """
        out: List[Node] = []
        for other in module.loops:
            if other.parent_loop is not loop:
                continue
            node = self.loop_unit.get(id(other))
            if node is not None:
                out.append(node)
        return out

    def _enclosing_loop_node(self, loop: LoopIR) -> Optional[Node]:
        """The unit node of the innermost enclosing loop that has one.

        Loop containment is flattened in `Node.parent` (invariant 1.1.2 keeps a
        loop unit hanging off its function), but `Edge.source` is unconstrained
        by level - so the epoch -> batch nesting is expressed by the `enter`
        edge instead of by the hierarchy.
        """
        outer = loop.parent_loop
        while outer is not None:
            node = self.loop_unit.get(id(outer))
            if node is not None:
                return node
            outer = outer.parent_loop
        return None

    def _config_edges(self, module: ModuleIR, parsed) -> None:
        configs: List[ValueRef] = []
        for scope in module.scopes:
            for name in sorted(scope.bindings):
                ref = scope.bindings[name]
                if ref.is_config and self._producer_node(ref) is not None:
                    configs.append(ref)
        if not configs:
            return
        for call in module.calls:
            consumer = self._owning_unit(call)
            if consumer is None:
                continue
            used = names_in(call.node)
            for ref in configs:
                if ref.name not in used and not any(u.startswith(ref.name + ".") for u in used):
                    continue
                source = self._producer_node(ref)
                if source is None or source.id == consumer.id:
                    continue
                self._add_edge("config", source, consumer, call.loc, label=ref.name,
                               confidence=0.8)

    # ---------------------------------------------------------- entrypoints
    def _entrypoints(self) -> List[str]:
        ranked: List[Tuple[Tuple[int, int, str], str]] = []
        for module in self._modules():
            has_train = any(l.kind in ("epoch", "batch") for l in module.loops)
            if module.main_guard is None and not has_train and not module.entry_stmts:
                continue
            base = module.relpath.split("/")[-1]
            rank = (0 if module.main_guard is not None else 1,
                    0 if base in ("train.py", "main.py", "run.py", "__main__.py") else 1,
                    module.relpath)
            ranked.append((rank, module.relpath))
        ranked.sort()
        return [rel for _rank, rel in ranked[:10]]


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


def build_graph(workspace: WorkspaceIR, max_nodes: int = 400) -> Tuple[MLGraph, GraphBuilder]:
    builder = GraphBuilder(workspace, max_nodes=max_nodes)
    return builder.build(), builder
