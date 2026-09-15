"""Graph construction: units, ops, typed edges, hierarchy, caps.

Units  - every top-level function, every class, the module entrypoint block,
         and every epoch/batch/fold loop (as a child unit of its function).
Ops    - every call whose canonical FQN is known to the knowledge tables.
Edges  - `data` (producer -> consumer through a ValueRef), `call`
         (unit -> workspace definition), `control` (enter / back), `config`
         (a config value -> each consuming unit).

Containment is `Node.parent`, and a parent always sits at a strictly lower
level than its child (stage > unit > op), as the renderer requires.

The builder is one object with one state, and it is written across four
modules that this one composes: `core/build_units.py`, `core/build_ops.py` and
`core/build_edges.py` are mixins holding one pass each, `core/build_roles.py`
holds the role tables both of them read, and what stays here is the state they
share - `__init__`, the pass order in `build()`, and the four node helpers
every pass calls.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from ..ir.model import CallSite, LoopIR, ModuleIR, WorkspaceIR
from . import config_nodes, workspace_ops
from .build_edges import EdgesMixin
from .build_ops import OpsMixin
from .build_roles import NOT_DRAWN_ROLES, TRANSPARENT_ROLES  # noqa: F401
from .build_units import UnitsMixin
from .graph import Diagnostic, Edge, MLGraph, Node
from .ids import node_id

__all__ = ["GraphBuilder", "build_graph", "NOT_DRAWN_ROLES"]


class GraphBuilder(UnitsMixin, OpsMixin, EdgesMixin):
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
        #: Ids of the `core/workspace_ops` nodes whose lane is a property of
        #: *where* they run rather than of what they are - a forward pass is
        #: training inside a train loop and evaluation inside an eval loop - so
        #: they are re-staged from their parent once the units have voted.
        self.inherit_stage: Set[str] = set()

    # ------------------------------------------------------------------ API
    def build(self) -> MLGraph:
        self._create_units()
        self._create_ops()
        self._create_config_literals()
        config_nodes.config_diagnostics(self)
        self._resolve_transparent()
        self._assign_stages()
        workspace_ops.restage_inherited(self)
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


def build_graph(workspace: WorkspaceIR, max_nodes: int = 400) -> Tuple[MLGraph, GraphBuilder]:
    builder = GraphBuilder(workspace, max_nodes=max_nodes)
    return builder.build(), builder
