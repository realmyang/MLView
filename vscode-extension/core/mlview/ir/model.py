"""The MLView intermediate representation.

Everything the rules and the graph builder see is one of these dataclasses.
They are plain data: no AST walking, no I/O, no framework imports.

Conventions (CONTRACTS section 0): `line` is 1-based, `col` is 0-based,
`file` is workspace-relative with forward slashes, `absFile` is absolute with
forward slashes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "Loc", "ValueRef", "CallSite", "LoopIR", "ScopeIR", "FunctionIR",
    "ClassIR", "ModuleIR", "WorkspaceIR", "VALUE_TAGS",
]

#: The frozen `ValueTag` enum (CONTRACTS section 1).
VALUE_TAGS = (
    "RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT", "VAL_SPLIT", "TEST_SPLIT",
    "FITTED_TRANSFORMER", "MODEL", "LOADER", "BATCH", "LOGITS", "PROBS",
    "PREDS", "LOSS", "OPTIMIZER", "DEVICE",
)
_TAG_ORDER = {t: i for i, t in enumerate(VALUE_TAGS)}


def sort_tags(tags) -> Tuple[str, ...]:
    """Canonical (schema-enum) tag order, de-duplicated."""
    return tuple(sorted({t for t in tags if t in _TAG_ORDER}, key=lambda t: _TAG_ORDER[t]))


@dataclass(frozen=True)
class Loc:
    """A source range. `line` 1-based inclusive, `col` 0-based."""

    file: str
    absFile: str
    line: int
    col: int
    endLine: int
    endCol: int
    symbol: Optional[str] = None
    snippet: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "file": self.file,
            "absFile": self.absFile,
            "line": self.line,
            "col": self.col,
            "endLine": self.endLine,
            "endCol": self.endCol,
        }
        if self.symbol:
            out["symbol"] = self.symbol
        if self.snippet:
            out["snippet"] = self.snippet
        return out

    def related_dict(self, role: str, message: Optional[str] = None) -> Dict[str, Any]:
        """This location as a `RelatedLoc` with a named role."""
        out: Dict[str, Any] = {"role": role}
        if message:
            out["message"] = message
        out.update({
            "file": self.file,
            "absFile": self.absFile,
            "line": self.line,
            "col": self.col,
            "endLine": self.endLine,
            "endCol": self.endCol,
        })
        if self.symbol:
            out["symbol"] = self.symbol
        if self.snippet:
            out["snippet"] = self.snippet
        return out


@dataclass
class ScopeIR:
    """A module / class / function scope."""

    qualname: str
    kind: str                      # "module" | "class" | "function"
    module: str                    # relpath of the owning module
    dynamic: bool = False
    reasons: List[str] = field(default_factory=list)
    node: Optional[ast.AST] = None
    parent: Optional["ScopeIR"] = None
    bindings: Dict[str, "ValueRef"] = field(default_factory=dict)
    #: REV-01. `bindings` keeps the LAST store for a name, which is what a
    #: consumer *after* every store wants; `binding_history` keeps them all, in
    #: source order, so a consumer can be resolved against the store in effect
    #: at its own line. `x = layer(x)` twice in one `forward` is the universal
    #: PyTorch idiom, and the flat map wired its first consumer to its last
    #: producer - a data edge pointing backwards through the model.
    binding_history: Dict[str, List["ValueRef"]] = field(default_factory=dict)
    loc: Optional[Loc] = None

    def mark_dynamic(self, reason: str) -> None:
        self.dynamic = True
        if reason not in self.reasons:
            self.reasons.append(reason)

    @property
    def is_dynamic(self) -> bool:
        scope: Optional[ScopeIR] = self
        while scope is not None:
            if scope.dynamic:
                return True
            scope = scope.parent
        return False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ScopeIR(%s, %s)" % (self.qualname, self.kind)


@dataclass
class ValueRef:
    """A named value inside a scope, with the tags dataflow assigned to it."""

    name: str
    scope: ScopeIR
    tags: Tuple[str, ...] = ()
    producer: Optional["CallSite"] = None
    loc: Optional[Loc] = None
    sources: Tuple[str, ...] = ()      # names read by the producing expression
    literal: Optional[str] = None      # stringified literal, when the value is one
    index: Optional[int] = None        # position in a tuple unpacking
    class_ir: Optional["ClassIR"] = None   # workspace class this value instantiates
    is_config: bool = False            # produced by argparse / yaml / json / a cfg dict
    #: Canonical FQNs this value is known to be an instance of when its producer
    #: call does not name them itself - `opt = build_optimizer(...)` gets
    #: `("torch.optim.Adam",)` from the callee's return expressions (ir.returns).
    via_fqns: Tuple[str, ...] = ()
    #: ANA-5a. A short noun phrase for the construct that produced this value
    #: when the analyzer could not resolve it - "a lambda", "a value assigned in
    #: a match case", "a dataclass default_factory". Set only where the binding
    #: really exists and really has nothing behind it, so a call *through* this
    #: name can say which construct defeated it instead of vanishing.
    opaque: Optional[str] = None

    def has(self, *tags: str) -> bool:
        return any(t in self.tags for t in tags)

    def add_tags(self, tags) -> None:
        self.tags = sort_tags(tuple(self.tags) + tuple(tags))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ValueRef(%s, tags=%s)" % (self.name, ",".join(self.tags))


@dataclass
class CallSite:
    """One call expression, resolved as far as static analysis allows."""

    fqn: Optional[str]                     # best single canonical FQN
    canonical_fqns: Tuple[str, ...]        # every FQN this call answers to
    node: ast.Call
    loc: Loc
    scope: ScopeIR
    module: "ModuleIR"
    import_fqn: Optional[str] = None       # what the import table alone resolved
    receiver: Optional[ValueRef] = None
    receiver_name: Optional[str] = None
    method: Optional[str] = None
    args: Tuple[ast.expr, ...] = ()
    kwargs: Dict[str, str] = field(default_factory=dict)   # literal kwargs, stringified
    kwarg_nodes: Dict[str, ast.expr] = field(default_factory=dict)
    var: Optional[str] = None              # name this call's value was bound to
    short_name: str = ""
    loop: Optional["LoopIR"] = None
    inside_no_grad: bool = False
    inside_autocast: bool = False
    stmt_index: int = 0
    block_id: str = ""
    function: Optional["FunctionIR"] = None
    #: The workspace class this call *resolves to* - `Net()` inside `train()`.
    #: ANA-1: strictly the resolution, never the enclosing class. `ir/resolve.py`
    #: is the only writer; `core/build.py` maps such a call onto the class's own
    #: unit node instead of minting an op.
    class_ir: Optional["ClassIR"] = None   # workspace class being instantiated
    #: The class whose body this call is *written in* - `nn.Conv2d(...)` inside
    #: `SmallCNN.__init__`. Set by `ir/scopes.py` at record time. Before ANA-1
    #: both meanings shared `class_ir`, and `_create_op` read the second one as
    #: the first, so every op written inside a method was silently dropped.
    enclosing_class: Optional["ClassIR"] = None
    target_function: Optional["FunctionIR"] = None  # workspace function being called
    #: ANA-5a. A **per-call** signal: the callee expression is not a name or an
    #: attribute chain (a call of a call, a subscript, a lambda), or it is a
    #: name whose binding the analyzer could not follow (a `match`-assigned
    #: value, a dataclass `default_factory`). The value is the noun phrase the
    #: diagnostic names. It is deliberately **not** `ScopeIR.mark_dynamic`:
    #: `DYNAMIC_FACTOR` 0.7 applies per scope, so widening the scope flag would
    #: move the confidence of every finding in the same function.
    unresolved_callee: Optional[str] = None

    def matches(self, *fqns: str) -> bool:
        return any(f in self.canonical_fqns for f in fqns)

    @property
    def qualname(self) -> str:
        base = self.scope.qualname
        return "%s.%s" % (base, self.var or self.short_name or "call")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "CallSite(%s @%s:%d)" % (self.fqn or self.short_name,
                                        self.loc.file, self.loc.line)


@dataclass
class LoopIR:
    """A `for` / `while` loop, classified by what it iterates."""

    kind: str                     # "epoch" | "batch" | "fold" | "other"
    node: ast.AST
    loc: Loc
    scope: ScopeIR
    module: "ModuleIR"
    iterates: Optional[ValueRef] = None
    iter_text: str = ""
    iter_loc: Optional[Loc] = None
    targets: Tuple[str, ...] = ()
    body: Tuple[ast.stmt, ...] = ()
    depth: int = 1
    inside_no_grad: bool = False
    inside_autocast: bool = False
    parent_loop: Optional["LoopIR"] = None
    function: Optional["FunctionIR"] = None
    qualname: str = ""
    evidence: Tuple[str, ...] = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "LoopIR(%s @%s:%d)" % (self.kind, self.loc.file, self.loc.line)


@dataclass
class FunctionIR:
    """A module-level function, a method, or a nested function."""

    name: str
    qualname: str
    node: ast.AST
    loc: Loc                       # the `def` header
    scope: ScopeIR
    module: "ModuleIR"
    params: Tuple[str, ...] = ()
    annotations: Dict[str, str] = field(default_factory=dict)
    decorators: Tuple[str, ...] = ()
    class_ir: Optional["ClassIR"] = None
    is_method: bool = False
    parent_function: Optional["FunctionIR"] = None
    calls: List[CallSite] = field(default_factory=list)
    loops: List[LoopIR] = field(default_factory=list)
    returns: List[ast.expr] = field(default_factory=list)
    inside_no_grad: bool = False
    #: `ir.returns.ReturnSummary` for this function, or None when its return
    #: expressions carry nothing static. Recomputed each IR round.
    return_summary: Any = None


@dataclass
class ClassIR:
    """A class definition, with its base FQNs resolved as far as possible."""

    name: str
    qualname: str
    node: ast.ClassDef
    loc: Loc
    scope: ScopeIR
    module: "ModuleIR"
    bases: Tuple[str, ...] = ()            # resolved base FQNs (canonical or workspace)
    resolved_bases: Tuple[str, ...] = ()   # transitively resolved, framework FQNs included
    methods: Dict[str, FunctionIR] = field(default_factory=dict)
    calls: List[CallSite] = field(default_factory=list)

    @property
    def is_nn_module(self) -> bool:
        return "torch.nn.Module" in self.resolved_bases

    @property
    def is_model_module(self) -> bool:
        """FW-RECOG: an `nn.Module` **or** an equivalent framework model base.

        `pytorch_lightning.LightningModule` subclasses an `nn.Module`, so a
        `LitClassifier` is a model in every sense the graph cares about - and
        MLView drew it as `kind: class` in the Config lane while the
        `SmallCNN` two files away was `kind: model`. `is_nn_module` keeps its
        exact torch meaning for the readers that need it (`torch.nn.Module.*`
        method proposal); this is the question the graph actually asks.
        """
        from ..knowledge import is_model_base
        return is_model_base(self.resolved_bases)

    @property
    def is_hook_owner(self) -> bool:
        """True when this class's methods are framework hooks, not methods."""
        from ..knowledge import HOOK_OWNER_BASES
        return any(base in HOOK_OWNER_BASES for base in self.resolved_bases)

    @property
    def workspace_fqn(self) -> str:
        return "%s.%s" % (self.module.dotted, self.name) if self.module.dotted else self.name


@dataclass
class ModuleIR:
    """Everything recovered from one source file."""

    relpath: str
    abspath: str
    dotted: str
    source: str
    lines: Tuple[str, ...]
    tree: ast.Module
    symbols: Any = None                     # ir.symbols.SymbolTable
    module_scope: Optional[ScopeIR] = None
    scopes: List[ScopeIR] = field(default_factory=list)
    functions: Dict[str, FunctionIR] = field(default_factory=dict)
    classes: Dict[str, ClassIR] = field(default_factory=dict)
    calls: List[CallSite] = field(default_factory=list)
    loops: List[LoopIR] = field(default_factory=list)
    assignments: List[Any] = field(default_factory=list)
    entry_stmts: List[ast.stmt] = field(default_factory=list)
    main_guard: Optional[ast.If] = None
    imports: Tuple[str, ...] = ()
    frameworks: Tuple[str, ...] = ()
    #: Framework wrappers that own a training loop *reachable from this module*
    #: (its own plus those of the workspace modules it imports). A hand-written
    #: loop in train.py is not owned by a Trainer in finetune.py.
    wrappers: Tuple[str, ...] = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ModuleIR(%s)" % self.relpath


@dataclass
class WorkspaceIR:
    """All modules plus the cross-file registries."""

    root: str
    modules: Dict[str, ModuleIR] = field(default_factory=dict)      # relpath -> ModuleIR
    by_dotted: Dict[str, ModuleIR] = field(default_factory=dict)
    classes: Dict[str, ClassIR] = field(default_factory=dict)       # workspace FQN -> ClassIR
    functions: Dict[str, FunctionIR] = field(default_factory=dict)  # workspace FQN -> FunctionIR
    frameworks: Tuple[str, ...] = ()
    wrappers: Tuple[str, ...] = ()          # detected framework wrappers (labels)
    dynamic_scopes: List[ScopeIR] = field(default_factory=list)
    #: ANA-3: `pkg.Net` -> `pkg.net.Net` for every symbol a workspace module
    #: re-exports, already followed to the definition (cap `_MAX_REEXPORT_HOPS`).
    reexports: Dict[str, str] = field(default_factory=dict)
    #: (relpath, line, message) for every import that resolved to nothing while
    #: a module of that name does exist somewhere in the workspace - the
    #: degradation is reported instead of silently shrinking the graph.
    unresolved_imports: List[Tuple[str, int, str]] = field(default_factory=list)
    #: How many IR rounds `build_workspace` ran, and whether it stopped because
    #: the state stopped moving (PERF-02). `False` means the round cap was hit
    #: and some cross-module resolution may be incomplete; the pipeline reports
    #: that rather than letting the graph come back quietly smaller.
    ir_rounds: int = 0
    ir_converged: bool = True

    def all_calls(self) -> List[CallSite]:
        out: List[CallSite] = []
        for rel in sorted(self.modules):
            out.extend(self.modules[rel].calls)
        return out

    def all_loops(self) -> List[LoopIR]:
        out: List[LoopIR] = []
        for rel in sorted(self.modules):
            out.extend(self.modules[rel].loops)
        return out
