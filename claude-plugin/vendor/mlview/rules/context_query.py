"""Everything a rule *asks* the graph, and the indexes that answer it.

A rule never walks the IR: it asks `ctx.calls_of("torch.optim.Optimizer.step")`
or `ctx.values_tagged("LOADER")` and gets back what the analyzer resolved. The
indexes here are built once per analysis and read many times, which is why they
are built lazily and never invalidated - the graph they index is finished
before the first rule runs.

Two of these answers carry a cost the rule must pay: `binding_of` and `hops`
record how many provenance hops the answer needed, so `rules/context_issue.py`
can de-rate an issue built on a long chain.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .. import knowledge as K
from ..core.graph import Edge, Node
from ..ir.bindings import binding_of as _binding_of
from ..ir.model import CallSite, ClassIR, FunctionIR, LoopIR, ScopeIR, ValueRef
from ..ir.provenance import chain_text
from .confidence import interprocedural_evidence


class QueryMixin:
    """`GraphContext`'s read side. Mixed in, never instantiated."""

    # ------------------------------------------------------------ queries
    def _index(self) -> Dict[str, List[CallSite]]:
        """Build - once - the FQN index, the role index and the canonical order.

        `calls_with_role` used to re-walk every call in every module on each of
        the 14 rule call sites that ask for one (6.4 s cumulative on a 210-file
        workspace). One pass now fills both indexes. A call is filed under
        **every** role any of its canonical FQNs answers to, never just the
        first: a single-role index silently drops findings from a call that is,
        say, both FIT and FIT_TRANSFORM.
        """
        if self._call_index is not None:
            return self._call_index
        from .. import knowledge as K
        index: Dict[str, List[CallSite]] = {}
        roles: Dict[str, List[CallSite]] = {}
        order: Dict[int, int] = {}
        seq = 0
        for relpath in sorted(self.modules):
            for call in self.modules[relpath].calls:
                order[id(call)] = seq
                seq += 1
                seen: set = set()
                for fqn in call.canonical_fqns or ():
                    index.setdefault(fqn, []).append(call)
                    role = K.role_of(fqn)
                    if role is None or role in seen:
                        continue
                    seen.add(role)
                    roles.setdefault(role, []).append(call)
        self._call_index = index
        self._role_index = roles
        self._call_seq = order
        return self._call_index

    def _canonical_order(self, call: CallSite):
        """`(file, line, col, discovery order)` - the total order both queries
        return. The discovery tiebreak is what the old stable `sort` gave for
        free when the candidate list was already in discovery order."""
        return (call.loc.file, call.loc.line, call.loc.col,
                self._call_seq.get(id(call), 0))

    def calls_of(self, *fqns: str) -> List[CallSite]:
        """Every call site answering to any of these canonical FQNs."""
        index = self._index()
        out: List[CallSite] = []
        seen: set = set()
        for fqn in fqns:
            for call in index.get(fqn, ()):
                # id-keyed: `call not in out` compared CallSite dataclasses
                # field by field, which recursed through scope and module.
                if id(call) not in seen:
                    seen.add(id(call))
                    out.append(call)
        out.sort(key=lambda c: (c.loc.file, c.loc.line, c.loc.col))
        return out

    def calls_with_role(self, *roles: str) -> List[CallSite]:
        """Every call whose knowledge-table role is one of `roles`."""
        self._index()
        out: List[CallSite] = []
        seen: set = set()
        for role in roles:
            for call in self._role_index.get(role, ()):
                if id(call) not in seen:
                    seen.add(id(call))
                    out.append(call)
        out.sort(key=self._canonical_order)
        return out

    def loops(self, kind: Optional[str] = None) -> List[LoopIR]:
        out: List[LoopIR] = []
        for relpath in sorted(self.modules):
            for loop in self.modules[relpath].loops:
                if kind is None or loop.kind == kind:
                    out.append(loop)
        out.sort(key=lambda l: (l.loc.file, l.loc.line, l.loc.col))
        return out

    def values_tagged(self, tag: str) -> List[ValueRef]:
        out: List[ValueRef] = []
        seen: set = set()
        for relpath in sorted(self.modules):
            for scope in self.modules[relpath].scopes:
                for name in sorted(scope.bindings):
                    ref = scope.bindings[name]
                    # id-keyed for the same reason as `calls_of`: two distinct
                    # bindings differ in name or scope, so identity and
                    # dataclass equality agree, and identity is O(1).
                    if tag in ref.tags and id(ref) not in seen:
                        seen.add(id(ref))
                        out.append(ref)
        return out

    def binding_of(self, name: Optional[str], scope: Optional[ScopeIR],
                   at: Optional[int] = None, in_loop: bool = False) -> Optional[ValueRef]:
        """`at` is the 1-based line of the consumer (REV-01 ordered lookup).

        `in_loop` says the consumer is inside a loop, where a store written
        *below* it really can reach it on the next iteration - so the last
        store is the honest answer there and `None` is the honest answer
        outside one.
        """
        ref = _binding_of(name, scope, at=at, in_loop=in_loop)
        self.note_hops(ref, scope)
        return ref

    def note_hops(self, ref, scope: Optional[ScopeIR] = None) -> None:
        """Record that the running rule consulted an interprocedural value (IP-01).

        Every read goes through `binding_of`, so this is automatic for a rule
        that asks the context for a value; `traced_arg`'s projection builds a
        *derived* ref and calls this itself. `issue()` spends the record.
        """
        if not getattr(ref, "provenance", ()):
            return
        spec = self.current_rule
        if spec is None:
            return
        where = getattr(ref, "scope", None) or scope
        if where is None:
            return
        self._hop_reads.append((spec.code, where, ref))

    def class_bases(self, node) -> List[str]:
        """Resolved canonical base FQNs for a class node (or a ClassIR)."""
        cls = node
        if isinstance(node, Node):
            cls = self.builder.unit_for_node.get(node.id)
        if isinstance(cls, ClassIR):
            return list(cls.resolved_bases)
        return []

    def class_of(self, node: Node) -> Optional[ClassIR]:
        owner = self.builder.unit_for_node.get(node.id)
        return owner if isinstance(owner, ClassIR) else None

    def node_for(self, loc) -> Optional[Node]:
        """The narrowest node whose range contains `loc`."""
        if loc is None:
            return None
        file = getattr(loc, "file", None) or (loc.get("file") if isinstance(loc, dict) else None)
        line = getattr(loc, "line", None) or (loc.get("line") if isinstance(loc, dict) else None)
        if file is None or line is None:
            return None
        if self._nodes_by_file is None:
            index: Dict[str, List[Node]] = {}
            for node in self.graph.nodes:
                index.setdefault(node.loc.file, []).append(node)
            self._nodes_by_file = index
        best: Optional[Node] = None
        best_span = None
        for node in self._nodes_by_file.get(file, ()):
            if node.loc.line <= line <= max(node.loc.endLine, node.loc.line):
                span = (node.loc.endLine - node.loc.line, 0 if node.level == "op" else 1)
                if best is None or span < best_span:
                    best, best_span = node, span
        return best

    def node_for_call(self, call: CallSite) -> Optional[Node]:
        return self.builder.node_for_call.get(id(call))

    def node_for_loop(self, loop: LoopIR) -> Optional[Node]:
        return self.builder.loop_unit.get(id(loop))

    def unit_for_call(self, call: CallSite) -> Optional[Node]:
        return self.builder._owning_unit(call)

    def edge_between(self, source: Optional[Node], target: Optional[Node],
                     kind: str = "data") -> Optional[Edge]:
        if source is None or target is None:
            return None
        for edge in self.graph.edges:
            if edge.source == source.id and edge.target == target.id and edge.kind == kind:
                return edge
        return None

    def follow_call(self, call: CallSite) -> Optional[FunctionIR]:
        """One level of module-local call following."""
        if call is None:
            return None
        return call.target_function

    def is_dynamic(self, scope) -> bool:
        if scope is None:
            return False
        if isinstance(scope, ScopeIR):
            return scope.is_dynamic
        if isinstance(scope, str):
            for module in self.modules.values():
                for candidate in module.scopes:
                    if candidate.qualname == scope:
                        return candidate.is_dynamic
        return False

    @property
    def wrappers(self) -> Tuple[str, ...]:
        """Every framework wrapper detected anywhere in the workspace."""
        return tuple(self.workspace.wrappers)

    def wrappers_for(self, file: Optional[str]) -> Tuple[str, ...]:
        """The wrappers that own the training loop *of one module*.

        Iron law 4 gates a finding when a framework owns the loop the finding
        is in - which is a property of that module (and the workspace modules
        it imports), not of the workspace. Falls back to the workspace-wide
        set when the file is not one of the analyzed modules.
        """
        module = self.modules.get(file) if file else None
        if module is None:
            return tuple(self.workspace.wrappers)
        return tuple(getattr(module, "wrappers", ()) or ())

    # ------------------------------------------------------------- emitters
    def untraced(self, call: CallSite, name: Optional[str], reason: str) -> None:
        """Declare that this rule could not check `name` at `call` (COVERAGE).

        A rule stays silent when the value it needs carries no dataflow tag -
        that silence is what keeps precision at 100% - but silence and "nothing
        wrong here" must not look the same to a reader. This records the gap as
        an `untagged_dataflow` diagnostic; it never produces an issue and never
        changes a rule's gate.
        """
        spec = self.current_rule
        self._untagged.note(
            code=spec.code if spec is not None else "",
            file=call.loc.file, line=call.loc.line,
            scope=call.scope.qualname if call.scope is not None else "",
            variable=name, reason=reason)

    def hops(self, *refs) -> Tuple[Any, ...]:
        """The interprocedural evidence for these values (DATAFLOW-IP).

        One `cross_file` entry per value that arrived through a hop, carrying
        the chain in words and `IP_HOP_WEIGHT ** hops` as its weight. Empty for
        a local value, so a rule may pass every reference it used and pay
        nothing for the ones dataflow established in one scope.
        """
        out: List[Any] = []
        for ref in refs:
            out.extend(interprocedural_evidence(ref))
        return tuple(out)

    def hop_related(self, ref, message: Optional[str] = None) -> List[Any]:
        """One `RelatedLoc` per hop, oldest first (DATAFLOW-IP).

        A cross-object finding is only auditable if the reader can open the
        construction site the tag entered through. The roles are the frozen
        ones - `construction`, `call_site`, `definition` - so this adds no
        vocabulary to CONTRACTS 11.1.
        """
        out: List[Any] = []
        for hop in getattr(ref, "provenance", ()) or ():
            loc = getattr(hop, "loc", None)
            if loc is None:
                continue
            out.append((hop.role, loc,
                        message or ("%s carries %s through this %s hop"
                                    % (getattr(ref, "name", "the value"),
                                       ", ".join(ref.tags) or "no tag", hop.kind))))
        return out

    def hop_chain(self, ref) -> str:
        """The hop chain of a value, in words (empty when it is local)."""
        chain = getattr(ref, "provenance", ()) or ()
        return chain_text(chain) if chain else ""
