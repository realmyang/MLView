"""`GraphContext` - the frozen surface every rule is written against.

    ctx.graph                      the partially built MLGraph
    ctx.frameworks                 set[Framework] detected in the workspace
    ctx.modules                    dict[relpath, ModuleIR]
    ctx.calls_of(fqn)              every CallSite whose canonical_fqns match
    ctx.loops(kind=None)           loops, optionally filtered by kind
    ctx.values_tagged(tag)         every ValueRef carrying a ValueTag
    ctx.binding_of(name, scope)    the ValueRef a name resolves to
    ctx.class_bases(node)          resolved canonical base FQNs
    ctx.node_for(loc)              the narrowest node containing a location
    ctx.follow_call(call)          one level, module-local
    ctx.is_dynamic(scope)          scope (or its ancestors) is dynamic
    ctx.issue(...)                 builder; applies confidence + severity cap
    ctx.ghost(kind, parent, label) declares a ghost slot for an absence rule
    ctx.untraced(call, name, why)  declares a COVERAGE gap: the rule was blind
    ctx.dataflow                   "local" | "ip" (DATAFLOW-IP)
    ctx.hops(ref)                  interprocedural evidence for a ValueRef
    ctx.hop_related(ref)           one RelatedLoc per hop, oldest first

Rules never construct `Issue` directly.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..core.coverage import UntaggedNotes
from ..core.graph import (SEVERITY_RANK, Diagnostic, Edge, Evidence, Issue, MLGraph,
                          Node)
from ..core.ids import issue_id, node_id
from ..ir.bindings import binding_of as _binding_of
from ..ir.model import CallSite, ClassIR, FunctionIR, Loc, LoopIR, ModuleIR, ScopeIR, ValueRef
from ..ir.provenance import chain_text
from .confidence import (cap_severity, compute_confidence,
                         interprocedural_evidence, normalize_evidence,
                         notebook_evidence)

__all__ = ["GraphContext"]

_GHOST_SLUG = str.maketrans({" ": "_", "(": "", ")": "", ".": "_", "-": "_", "/": "_"})


class GraphContext:
    """Everything a rule may see, and the only way it may emit."""

    def __init__(self, graph: MLGraph, workspace, builder, suppressor,
                 options=None, diagnostics: Optional[List[Diagnostic]] = None):
        self.graph = graph
        self.workspace = workspace
        self.builder = builder
        self.suppressor = suppressor
        self.options = options
        self.diagnostics = diagnostics if diagnostics is not None else graph.diagnostics
        self.frameworks = set(workspace.frameworks)
        self.modules: Dict[str, ModuleIR] = workspace.modules
        self.issues: List[Issue] = []
        self.ghosts: List[Node] = []
        self.current_rule = None
        self._call_index: Optional[Dict[str, List[CallSite]]] = None
        self._role_index: Dict[str, List[CallSite]] = {}
        self._call_seq: Dict[int, int] = {}
        self._nodes_by_file: Optional[Dict[str, List[Node]]] = None
        self._gate_codes: List[str] = []
        self._untagged = UntaggedNotes(self.diagnostics)
        #: NB: generated-module relpath -> NotebookMap, empty on every run
        #: that did not ask for notebooks. Read only by `issue()`.
        self._notebooks: Dict[str, Any] = dict(getattr(workspace, "notebooks", None) or {})
        #: DATAFLOW-IP. The mode the IR was built in, read off the workspace
        #: rather than the options so that every construction of a context -
        #: the pipeline's, a test's - agrees with the IR it was handed.
        self.dataflow: str = getattr(workspace, "dataflow", "local") or "local"

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
                   at: Optional[int] = None) -> Optional[ValueRef]:
        """`at` is the 1-based line of the consumer (REV-01 ordered lookup)."""
        return _binding_of(name, scope, at=at)

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

    def ghost(self, kind: str, parent_node: Node, label: str,
              fqn: Optional[str] = None, confidence: float = 0.9) -> Node:
        """Declare a REQUIRED-BUT-ABSENT step in its correct slot (A9)."""
        slug = label.translate(_GHOST_SLUG).strip("_").lower() or "missing"
        qualname = "%s.__ghost_%s" % (parent_node.qualname, slug)
        node = Node(
            id=node_id(parent_node.loc.file, qualname, kind), kind=kind, level="op",
            stage=parent_node.stage, label=label, qualname=qualname,
            loc=parent_node.loc, sublabel="missing", fqn=fqn,
            framework=parent_node.framework, parent=parent_node.id, ghost=True,
            dynamic=parent_node.dynamic, confidence=confidence,
            stageEvidence=[Evidence("context_confirmed",
                                    "ghost slot for %s" % (self.current_rule.code
                                                           if self.current_rule else "a rule"),
                                    1.0)])
        existing = self.graph.node_by_id(node.id)
        if existing is not None:
            return existing
        self.graph.nodes.append(node)
        self.ghosts.append(node)
        if self._nodes_by_file is not None:
            self._nodes_by_file.setdefault(node.loc.file, []).append(node)
        return node

    def issue(self, title: Optional[str] = None, message: str = "", why: Optional[str] = None,
              fix_hint: Optional[str] = None, loc: Optional[Loc] = None,
              node_ids: Sequence[Any] = (), edge_ids: Sequence[Any] = (),
              related: Sequence[Any] = (), evidence: Sequence[Any] = (),
              tags: Sequence[str] = (), dynamic: Optional[bool] = None,
              stage: Optional[str] = None, qualname: Optional[str] = None,
              severity: Optional[str] = None, wrapper_gated: bool = False) -> Issue:
        """Build one issue: confidence, severity cap, suppression, ids.

        `severity` may only **lower** the declared severity (MLV301's
        "drop to medium when the architecture cannot be resolved" refinement);
        a rule can never grade itself up, and the absence cap still applies on
        top of whatever it asks for.
        """
        spec = self.current_rule
        if spec is None:  # pragma: no cover - registry always sets it
            raise RuntimeError("ctx.issue() called outside a rule")
        nodes = [self._as_node(n) for n in node_ids]
        nodes = [n for n in nodes if n is not None]
        edges = [self._as_edge(e) for e in edge_ids]
        edges = [e for e in edges if e is not None]
        primary = nodes[0] if nodes else None
        if loc is None and primary is not None:
            loc = primary.loc
        if loc is None:
            raise ValueError("%s: an issue needs a loc" % spec.code)

        ev = normalize_evidence(evidence)
        # NB: a finding inside a notebook says which cell it is in, and an
        # order-sensitive rule in an out-of-order notebook is de-rated by the
        # weight of that same factor. Appended last so the evidence a rule
        # wrote is untouched, and reached only when the run asked for
        # notebooks - no `.py` finding ever gains a factor here.
        nbmap = self._notebooks.get(loc.file) if self._notebooks else None
        if nbmap is not None:
            ev = ev + notebook_evidence(nbmap, loc.line, spec.code)
        if dynamic is None:
            dynamic = bool(primary.dynamic) if primary is not None else False
        wrapper_present = bool(self.wrappers_for(loc.file))
        # `wrapper_gated` lets a rule that is not an *absence* rule opt into the
        # same x0.4 de-rating instead of deleting its findings outright.
        gate = bool((spec.absence or wrapper_gated) and wrapper_present)
        confidence = compute_confidence(spec.base_prior, ev, dynamic=dynamic,
                                        wrapper_gate=gate)
        declared = spec.severity
        if severity in SEVERITY_RANK and SEVERITY_RANK[severity] < SEVERITY_RANK[declared]:
            declared = severity
        severity = cap_severity(declared, spec.absence, not dynamic, wrapper_present)
        if gate:
            self._note_gate(spec.code, self.wrappers_for(loc.file))

        qual = qualname or (primary.qualname if primary is not None else loc.symbol or "")
        issue = Issue(
            id=issue_id(spec.code, loc.file, qual, loc.symbol or ""),
            code=spec.code, ruleVersion=spec.rule_version, severity=severity,
            confidence=confidence,
            title=title or spec.title or spec.code,
            message=message or title or spec.title or spec.code,
            why=why or spec.why or "",
            fixHint=fix_hint or spec.fix_hint or "See the rule documentation.",
            loc=loc,
            stage=stage or (primary.stage if primary is not None else "train"),
            relatedLocs=[_as_related(r) for r in related],
            nodeIds=[n.id for n in nodes],
            edgeIds=[e.id for e in edges],
            frameworks=tuple(spec.frameworks),
            tags=tuple(tags) or tuple(spec.tags),
            evidence=list(ev),
            suppressed=self.suppressor.is_suppressed(spec.code, loc.file, loc.line),
            docs="docs/rules/%s.md" % spec.code)
        for node in nodes:
            if issue.id not in node.issueIds:
                node.issueIds.append(issue.id)
        for edge in edges:
            if issue.id not in edge.issueIds:
                edge.issueIds.append(issue.id)
        self.issues.append(issue)
        self.graph.issues.append(issue)
        return issue

    # -------------------------------------------------------------- helpers
    def _as_node(self, value) -> Optional[Node]:
        if isinstance(value, Node):
            return value
        if isinstance(value, str):
            return self.graph.node_by_id(value)
        return None

    def _as_edge(self, value) -> Optional[Edge]:
        if isinstance(value, Edge):
            return value
        if isinstance(value, str):
            for edge in self.graph.edges:
                if edge.id == value:
                    return edge
        return None

    def _note_gate(self, code: str, wrappers: Sequence[str] = ()) -> None:
        if code in self._gate_codes:
            return
        self._gate_codes.append(code)
        label = ", ".join(wrappers or self.workspace.wrappers)
        for diagnostic in self.diagnostics:
            if diagnostic.kind == "framework_suppressed":
                codes = list(diagnostic.codes or ())
                if code not in codes:
                    codes.append(code)
                diagnostic.codes = sorted(codes)
                diagnostic.count = len(codes)
                diagnostic.message = _gate_message(label, len(codes))
                return
        self.diagnostics.append(Diagnostic(
            kind="framework_suppressed",
            message=_gate_message(label, 1),
            codes=[code], count=1))


def _gate_message(label: str, count: int) -> str:
    """The `framework_suppressed` chip text - counting every gated rule."""
    return ("Training loop handled by %s - %d rule(s) de-rated to speculative."
            % (label, count))


def _as_related(item) -> Dict[str, Any]:
    """Accept `(role, loc)` / `(role, loc, message)` / a ready dict."""
    if isinstance(item, dict):
        return item
    role = item[0]
    loc = item[1]
    message = item[2] if len(item) > 2 else None
    return loc.related_dict(role, message)
