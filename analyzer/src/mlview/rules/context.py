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
    ctx.fix(module, title, edits)  builds a validated `Issue.fix` candidate (H5)
    ctx.ghost(kind, parent, label) declares a ghost slot for an absence rule
    ctx.untraced(call, name, why)  declares a COVERAGE gap: the rule was blind
    ctx.dataflow                   "local" | "ip" (DATAFLOW-IP)
    ctx.hops(ref)                  interprocedural evidence for a ValueRef
    ctx.hop_related(ref)           one RelatedLoc per hop, oldest first

Rules never construct `Issue` directly.

The object is one state and three modules: the class and `__init__` are here,
the read side (`calls_of`, `values_tagged`, `binding_of`, the indexes) is
`rules/context_query.py`, and the write side (`issue`, `fix`, `ghost` and the
de-rating they go through) is `rules/context_issue.py`. A rule sees one `ctx`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..core.coverage import UntaggedNotes
from ..core.graph import Diagnostic, Issue, MLGraph, Node
from ..ir.model import CallSite, ModuleIR, ScopeIR, ValueRef
from .context_issue import IssueMixin
from .context_query import QueryMixin

__all__ = ["GraphContext"]




class GraphContext(QueryMixin, IssueMixin):
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
        #: IP-01. `(rule code, ScopeIR, ValueRef)` for every value a rule looked
        #: up whose tags arrived through an interprocedural hop. Filled by
        #: `binding_of` - the one door a rule reads a value through - and spent
        #: by `issue()`. Empty on every `--dataflow local` run, because nothing
        #: there ever carries a provenance chain.
        self._hop_reads: List[Tuple[str, ScopeIR, ValueRef]] = []
        #: ROB-03. Every `Issue.id` this context has minted, so `_unique_id`
        #: can keep CONTRACTS section 0 invariant 1 true by construction
        #: instead of leaving it to each rule not to fire twice.
        self._minted_ids: set = set()
