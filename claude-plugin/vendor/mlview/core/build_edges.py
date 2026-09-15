"""The four typed edges, drawn once the nodes and their stages are settled.

  * `data`    a producer's node -> the consumer that reads its `ValueRef`,
              hopping through transparent nodes to the box a reader sees.
  * `call`    a unit -> the workspace definition it calls.
  * `control` `enter` into a loop body, and the `back` edge that closes it.
  * `config`  one config value -> each unit that consumes it.

`_add_edge` is the single writer, so the de-duplication, the self-edge refusal
and the evidence a viewer shows on hover all live in one place.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Sequence, Tuple

from ..ir.bindings import binding_of, names_in
from ..ir.locs import loc_of
from ..ir.model import CallSite, Loc, LoopIR, ModuleIR, ValueRef
from ..ir.symbols import dotted_text
from . import hooks
from .build_roles import _LOOP_BACK_LABEL
from .graph import Edge, Node
from .ids import edge_id
from .views import parsed_view


class EdgesMixin:
    """`GraphBuilder`'s edge pass. Mixed in, never instantiated."""

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
