"""Scope, loop and call-site recovery.

One walk over the AST produces: the scope tree (module / class / function),
every call site with its context flags, every loop with what it iterates,
the `with`-block gradient contexts, and the dynamic-scope markers.

Loop *kind* classification happens afterwards (`classify_loops`) because it
needs the binding table.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..ingest.parse import ParsedFile
from ..knowledge import AUTOCAST_FQNS, ENABLE_GRAD_FQNS, NO_GRAD_FQNS
from .locs import call_loc, loc_of
from .model import CallSite, ClassIR, FunctionIR, Loc, LoopIR, ModuleIR, ScopeIR
from .symbols import SymbolTable, dotted_name, dotted_text

__all__ = ["AssignRecord", "walk_module", "classify_loops", "literal_str",
           "callee_construct"]

_LOADER_NAME_RE = ("loader", "_dl", "dl_", "batches", "dataloader")
_EPOCH_NAMES = ("epoch", "epochs", "n_epochs", "num_epochs", "max_epochs")


@dataclass
class AssignRecord:
    """One binding-creating statement, in source order."""

    kind: str                       # assign | ann | aug | for | with | walrus
    targets: Tuple[ast.expr, ...]
    value: Optional[ast.expr]
    scope: ScopeIR
    loc: Loc
    call: Optional[CallSite] = None
    stmt_index: int = 0
    loop: Optional[LoopIR] = None
    function: Optional[FunctionIR] = None
    class_ir: Optional[ClassIR] = None
    #: ANA-5a: written inside a `match` case body. Which arm ran is undecidable
    #: statically, so a name bound here is the textbook unresolvable callee.
    in_match: bool = False
    #: INFRA-01: the statement runs under `torch.no_grad()` /
    #: `inference_mode()`. `CallSite` has carried this since MLV204; an
    #: assignment needs it for the same reason - there is no autograd graph to
    #: keep alive under no_grad, so MLV205 has nothing to say about a value
    #: accumulated there.
    inside_no_grad: bool = False


def literal_str(node: Optional[ast.AST]) -> Optional[str]:
    """Stringify a literal expression; None when it is not a literal."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, str):
            return value
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (int, float)):
            return repr(value)
        return None
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        parts = [literal_str(e) for e in node.elts]
        if any(p is None for p in parts):
            return None
        open_, close = ("[", "]") if isinstance(node, ast.List) else ("(", ")")
        if isinstance(node, ast.Set):
            open_, close = "{", "}"
        return open_ + ", ".join(parts) + close
    if isinstance(node, ast.Dict):
        items = []
        for k, v in zip(node.keys, node.values):
            ks, vs = literal_str(k), literal_str(v)
            if ks is None or vs is None:
                return None
            items.append("%s: %s" % (ks, vs))
        return "{" + ", ".join(items) + "}"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = literal_str(node.operand)
        return "-%s" % inner if inner is not None else None
    if isinstance(node, ast.Attribute) or isinstance(node, ast.Name):
        return None
    return None


class _Walker:
    """Single-pass structural walk of one module."""

    def __init__(self, parsed: ParsedFile, symbols: SymbolTable, dotted: str):
        self.parsed = parsed
        self.symbols = symbols
        self.module = ModuleIR(
            relpath=parsed.relpath, abspath=parsed.abspath, dotted=dotted,
            source=parsed.source, lines=parsed.lines, tree=parsed.tree,
            symbols=symbols)
        root = ScopeIR(qualname=dotted or parsed.relpath, kind="module",
                       module=parsed.relpath)
        self.module.module_scope = root
        self.module.scopes.append(root)
        self.scopes: List[ScopeIR] = [root]
        self.funcs: List[FunctionIR] = []
        self.classes: List[ClassIR] = []
        self.loops: List[LoopIR] = []
        self.no_grad = 0
        self.autocast = 0
        self.match_depth = 0
        self._loop_names: Dict[str, int] = {}
        if symbols.star_imports:
            root.mark_dynamic("star import: from %s import *" % symbols.star_imports[0])

    # -- helpers ------------------------------------------------------------
    @property
    def scope(self) -> ScopeIR:
        return self.scopes[-1]

    @property
    def func(self) -> Optional[FunctionIR]:
        return self.funcs[-1] if self.funcs else None

    @property
    def cls(self) -> Optional[ClassIR]:
        return self.classes[-1] if self.classes else None

    @property
    def loop(self) -> Optional[LoopIR]:
        return self.loops[-1] if self.loops else None

    def loc(self, node: ast.AST, symbol: Optional[str] = None) -> Loc:
        return loc_of(self.parsed, node, symbol)

    # -- entry --------------------------------------------------------------
    def run(self) -> ModuleIR:
        self.visit_body(self.module.tree.body, "module", top_level=True)
        return self.module

    def visit_body(self, body, block_id: str, top_level: bool = False) -> None:
        for index, stmt in enumerate(body):
            self.visit_stmt(stmt, index, block_id, top_level)

    # -- statements ---------------------------------------------------------
    def visit_stmt(self, stmt: ast.stmt, index: int, block_id: str,
                   top_level: bool = False) -> None:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            return
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.visit_function(stmt, index, block_id)
            return
        if isinstance(stmt, ast.ClassDef):
            self.visit_class(stmt, index, block_id)
            return
        if top_level and not _is_docstring(stmt):
            self.module.entry_stmts.append(stmt)

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self.visit_for(stmt, index, block_id)
            return
        if isinstance(stmt, ast.While):
            self.visit_while(stmt, index, block_id)
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            self.visit_with(stmt, index, block_id)
            return
        if isinstance(stmt, ast.If):
            self.visit_if(stmt, index, block_id, top_level)
            return
        if isinstance(stmt, ast.Match):
            # ANA-5a. `ast.Match`'s children are its subject plus `match_case`
            # nodes, which are neither `stmt` nor `expr`, so the generic branch
            # below walked straight past every case body: a `match`-dispatched
            # model, criterion and optimizer produced no call sites at all and
            # nothing said so. The bodies are ordinary statements; the fact that
            # only one arm runs is recorded on the bindings they create.
            self.visit_expr(stmt.subject, index, block_id)
            self.match_depth += 1
            for case_index, case in enumerate(stmt.cases):
                if case.guard is not None:
                    self.visit_expr(case.guard, index, block_id)
                self.visit_body(case.body, "%s#match%d.%d" % (block_id, stmt.lineno,
                                                             case_index))
            self.match_depth -= 1
            return
        if isinstance(stmt, ast.Try):
            self.visit_body(stmt.body, block_id + ".try")
            for handler in stmt.handlers:
                self.visit_body(handler.body, block_id + ".except")
            self.visit_body(stmt.orelse, block_id + ".else")
            self.visit_body(stmt.finalbody, block_id + ".finally")
            return
        if isinstance(stmt, ast.Assign):
            call = self.visit_expr(stmt.value, index, block_id)
            self.record_assign("assign", tuple(stmt.targets), stmt.value, stmt, call, index)
            for target in stmt.targets:
                self.visit_target(target, index, block_id)
            return
        if isinstance(stmt, ast.AnnAssign):
            call = self.visit_expr(stmt.value, index, block_id) if stmt.value else None
            if stmt.value is not None:
                self.record_assign("ann", (stmt.target,), stmt.value, stmt, call, index)
            self.visit_target(stmt.target, index, block_id)
            return
        if isinstance(stmt, ast.AugAssign):
            call = self.visit_expr(stmt.value, index, block_id)
            self.record_assign("aug", (stmt.target,), stmt.value, stmt, call, index)
            return
        if isinstance(stmt, ast.Return):
            if stmt.value is not None:
                self.visit_expr(stmt.value, index, block_id)
                if self.func is not None:
                    self.func.returns.append(stmt.value)
            return
        # generic: visit every contained expression
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.expr):
                self.visit_expr(child, index, block_id)
            elif isinstance(child, ast.stmt):  # pragma: no cover - defensive
                self.visit_stmt(child, index, block_id)

    def visit_target(self, target: ast.expr, index: int, block_id: str) -> None:
        """Subscript / attribute targets can contain calls of their own."""
        if isinstance(target, (ast.Subscript,)):
            self.visit_expr(target.slice, index, block_id)
            self.visit_expr(target.value, index, block_id)

    def record_assign(self, kind: str, targets, value, stmt, call, index: int) -> None:
        self.module.assignments.append(AssignRecord(
            kind=kind, targets=tuple(targets), value=value, scope=self.scope,
            loc=self.loc(stmt), call=call, stmt_index=index, loop=self.loop,
            function=self.func, class_ir=self.cls, in_match=self.match_depth > 0,
            inside_no_grad=self.no_grad > 0))

    # -- definitions --------------------------------------------------------
    def visit_function(self, node, index: int, block_id: str) -> None:
        parent = self.scope
        qualname = "%s.%s" % (parent.qualname, node.name)
        scope = ScopeIR(qualname=qualname, kind="function", module=self.module.relpath,
                        node=node, parent=parent, loc=self.loc(node))
        self.module.scopes.append(scope)
        decorators = []
        no_grad_dec = False
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            resolved = self.symbols.resolve(target) or dotted_name(target)
            if resolved:
                decorators.append(resolved)
                if resolved in NO_GRAD_FQNS:
                    no_grad_dec = True
        arg_nodes = (list(node.args.posonlyargs) + list(node.args.args)
                     + list(node.args.kwonlyargs))
        annotations = {}
        for arg in arg_nodes:
            if arg.annotation is None:
                continue
            target = arg.annotation
            if isinstance(target, ast.Constant) and isinstance(target.value, str):
                continue
            resolved = self.symbols.resolve(target)
            if not resolved:
                # A workspace-local name (`def validate(model: Net, ...)`) has no
                # import to resolve; keep the bare name so `seed_annotations`
                # can look it up in the workspace class registry.
                resolved = dotted_name(target)
            if resolved:
                annotations[arg.arg] = resolved
        func = FunctionIR(
            name=node.name, qualname=qualname, node=node, loc=self.loc(node),
            scope=scope, module=self.module, annotations=annotations,
            params=tuple(a.arg for a in arg_nodes),
            decorators=tuple(decorators), class_ir=self.cls,
            is_method=self.cls is not None,
            parent_function=self.func, inside_no_grad=bool(no_grad_dec) or self.no_grad > 0)
        self.module.functions[qualname] = func
        if self.cls is not None:
            self.cls.methods[node.name] = func

        self.scopes.append(scope)
        self.funcs.append(func)
        saved_loops, self.loops = self.loops, []
        if no_grad_dec:
            self.no_grad += 1
        for default in list(node.args.defaults) + [d for d in node.args.kw_defaults if d]:
            self.visit_expr(default, index, block_id)
        self.visit_body(node.body, "%s.body" % qualname)
        if no_grad_dec:
            self.no_grad -= 1
        self.loops = saved_loops
        self.funcs.pop()
        self.scopes.pop()

    def visit_class(self, node: ast.ClassDef, index: int, block_id: str) -> None:
        parent = self.scope
        qualname = "%s.%s" % (parent.qualname, node.name)
        scope = ScopeIR(qualname=qualname, kind="class", module=self.module.relpath,
                        node=node, parent=parent, loc=self.loc(node))
        self.module.scopes.append(scope)
        bases = []
        for base in node.bases:
            resolved = self.symbols.resolve(base) or dotted_name(base)
            if resolved:
                bases.append(resolved)
        cls = ClassIR(name=node.name, qualname=qualname, node=node, loc=self.loc(node),
                      scope=scope, module=self.module, bases=tuple(bases))
        self.module.classes[qualname] = cls
        self.scopes.append(scope)
        self.classes.append(cls)
        self.visit_body(node.body, "%s.body" % qualname)
        self.classes.pop()
        self.scopes.pop()

    # -- control flow -------------------------------------------------------
    def _new_loop(self, node, iter_node, targets) -> LoopIR:
        loop = LoopIR(
            kind="other", node=node, loc=self.loc(node), scope=self.scope,
            module=self.module, iter_text=dotted_text(iter_node) or "",
            iter_loc=self.loc(iter_node) if iter_node is not None else None,
            targets=targets, body=tuple(getattr(node, "body", ()) or ()),
            depth=len(self.loops) + 1, inside_no_grad=self.no_grad > 0,
            inside_autocast=self.autocast > 0, parent_loop=self.loop,
            function=self.func)
        self.module.loops.append(loop)
        return loop

    def visit_for(self, node, index: int, block_id: str) -> None:
        targets = tuple(_target_names(node.target))
        self.visit_expr(node.iter, index, block_id)
        loop = self._new_loop(node, node.iter, targets)
        self.record_assign("for", (node.target,), node.iter, node, None, index)
        self.loops.append(loop)
        self.visit_body(node.body, "%s#for%d" % (block_id, node.lineno))
        self.loops.pop()
        self.visit_body(node.orelse, block_id + ".else")

    def visit_while(self, node: ast.While, index: int, block_id: str) -> None:
        self.visit_expr(node.test, index, block_id)
        loop = self._new_loop(node, None, ())
        self.loops.append(loop)
        self.visit_body(node.body, "%s#while%d" % (block_id, node.lineno))
        self.loops.pop()
        self.visit_body(node.orelse, block_id + ".else")

    def visit_with(self, node, index: int, block_id: str) -> None:
        no_grad = autocast = enable_grad = 0
        for item in node.items:
            expr = item.context_expr
            target = expr.func if isinstance(expr, ast.Call) else expr
            fqn = self.symbols.resolve(target)
            if fqn in NO_GRAD_FQNS:
                no_grad += 1
            elif fqn in AUTOCAST_FQNS:
                autocast += 1
            elif fqn in ENABLE_GRAD_FQNS:
                enable_grad += 1
            call = self.visit_expr(expr, index, block_id)
            if item.optional_vars is not None:
                self.module.assignments.append(AssignRecord(
                    kind="with", targets=(item.optional_vars,), value=expr,
                    scope=self.scope, loc=self.loc(node), call=call,
                    stmt_index=index, loop=self.loop, function=self.func,
                    class_ir=self.cls, inside_no_grad=self.no_grad > 0))
        self.no_grad += no_grad
        if enable_grad:
            self.no_grad = max(0, self.no_grad - enable_grad)
        self.autocast += autocast
        self.visit_body(node.body, "%s#with%d" % (block_id, node.lineno))
        self.autocast -= autocast
        if enable_grad:
            self.no_grad += enable_grad
        self.no_grad -= no_grad

    def visit_if(self, node: ast.If, index: int, block_id: str, top_level: bool) -> None:
        if top_level and _is_main_guard(node):
            self.module.main_guard = node
            self.visit_body(node.body, "%s#main" % block_id, top_level=True)
            self.visit_body(node.orelse, "%s#main.else" % block_id, top_level=True)
            return
        self.visit_expr(node.test, index, block_id)
        self.visit_body(node.body, "%s#if%d" % (block_id, node.lineno), top_level=top_level)
        self.visit_body(node.orelse, "%s#if%d.else" % (block_id, node.lineno),
                        top_level=top_level)

    # -- expressions --------------------------------------------------------
    def visit_expr(self, node: Optional[ast.AST], index: int, block_id: str) -> Optional[CallSite]:
        """Walk an expression; returns the outermost CallSite it contains."""
        if node is None:
            return None
        outer: Optional[CallSite] = None
        if isinstance(node, ast.Call):
            return self.record_call(node, index, block_id)
        if isinstance(node, ast.NamedExpr):
            inner = self.visit_expr(node.value, index, block_id)
            self.module.assignments.append(AssignRecord(
                kind="walrus", targets=(node.target,), value=node.value,
                scope=self.scope, loc=self.loc(node), call=inner,
                stmt_index=index, loop=self.loop, function=self.func,
                class_ir=self.cls, inside_no_grad=self.no_grad > 0))
            return inner
        elif isinstance(node, ast.Lambda):
            self.visit_expr(node.body, index, block_id)
            return None
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.expr, ast.comprehension, ast.keyword)):
                if isinstance(child, ast.comprehension):
                    self.visit_expr(child.iter, index, block_id)
                    for cond in child.ifs:
                        self.visit_expr(cond, index, block_id)
                elif isinstance(child, ast.keyword):
                    self.visit_expr(child.value, index, block_id)
                else:
                    self.visit_expr(child, index, block_id)
        return outer

    def record_call(self, node: ast.Call, index: int, block_id: str) -> CallSite:
        func = node.func
        fqn = self.symbols.resolve(func)
        receiver_name = method = None
        if fqn is None and isinstance(func, ast.Attribute):
            receiver_name = dotted_text(func.value)
            method = func.attr
        short = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else (dotted_text(func) or "call"))
        kwargs: Dict[str, str] = {}
        kwarg_nodes: Dict[str, ast.expr] = {}
        has_forward = False
        for kw in node.keywords:
            if kw.arg is None:
                has_forward = True
                continue
            kwarg_nodes[kw.arg] = kw.value
            lit = literal_str(kw.value)
            if lit is not None:
                kwargs[kw.arg] = lit
        call = CallSite(
            fqn=fqn, canonical_fqns=(fqn,) if fqn else (), import_fqn=fqn,
            node=node, loc=call_loc(self.parsed, node),
            scope=self.scope, module=self.module, receiver_name=receiver_name,
            method=method, args=tuple(node.args), kwargs=kwargs, kwarg_nodes=kwarg_nodes,
            short_name=short or "call", loop=self.loop, inside_no_grad=self.no_grad > 0,
            inside_autocast=self.autocast > 0, stmt_index=index, block_id=block_id,
            function=self.func, enclosing_class=self.cls,
            unresolved_callee=callee_construct(func))
        setattr(call, "has_kwargs_forward", has_forward)
        self.module.calls.append(call)
        if self.func is not None:
            self.func.calls.append(call)
        if self.cls is not None:
            self.cls.calls.append(call)
        self._check_dynamic(node, short, fqn)
        for arg in node.args:
            self.visit_expr(arg, index, block_id)
        for kw in node.keywords:
            self.visit_expr(kw.value, index, block_id)
        if not isinstance(func, (ast.Name, ast.Attribute)):
            self.visit_expr(func, index, block_id)
        elif isinstance(func, ast.Attribute):
            # The receiver of a method call is an expression like any other:
            # `(model(x).argmax(1) == y).sum().item()` hides a FORWARD call
            # behind a Compare, and stopping at `ast.Call` receivers alone lost
            # every call in that subtree (and with it the whole eval region).
            self.visit_expr(func.value, index, block_id)
        return call

    def _check_dynamic(self, node: ast.Call, short: str, fqn: Optional[str]) -> None:
        bare = isinstance(node.func, ast.Name)
        if bare and short in ("exec", "eval") and fqn in (None, "exec", "eval",
                                                          "builtins.exec", "builtins.eval"):
            self.scope.mark_dynamic("%s() call at line %d" % (short, node.lineno))
        elif bare and short == "getattr" and len(node.args) >= 2:
            if not isinstance(node.args[1], ast.Constant):
                self.scope.mark_dynamic(
                    "getattr with a non-literal attribute at line %d" % node.lineno)
        elif short == "import_module":
            self.scope.mark_dynamic("dynamic import at line %d" % node.lineno)


#: ANA-5a. Callee expressions that are neither a name nor an attribute chain,
#: mapped to the noun phrase the diagnostic prints. A `Name` and an `Attribute`
#: are absent on purpose: those are the two shapes `ir/resolve` knows how to
#: chase, and flagging them here would mint an `unknown` node for `print()`.
_CALLEE_CONSTRUCTS = (
    (ast.Call, "the result of another call"),
    (ast.Subscript, "a subscript"),
    (ast.Lambda, "a lambda"),
    (ast.IfExp, "a conditional expression"),
    (ast.Await, "an awaited value"),
    (ast.BoolOp, "a boolean expression"),
    (ast.BinOp, "an arithmetic expression"),
    (ast.Starred, "a starred expression"),
    (ast.Tuple, "a tuple element"),
    (ast.ListComp, "a comprehension"),
    (ast.GeneratorExp, "a generator expression"),
)


def callee_construct(func: ast.expr) -> Optional[str]:
    """The construct name when a callee is not a Name / Attribute chain."""
    if isinstance(func, (ast.Name, ast.Attribute)):
        return None
    for node_type, phrase in _CALLEE_CONSTRUCTS:
        if isinstance(func, node_type):
            return phrase
    return "a computed callee"


def _target_names(target: ast.expr) -> List[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: List[str] = []
        for elt in target.elts:
            out.extend(_target_names(elt))
        return out
    if isinstance(target, ast.Attribute):
        name = dotted_text(target)
        return [name] if name else []
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    if isinstance(left, ast.Name) and left.id == "__name__":
        return isinstance(right, ast.Constant) and right.value == "__main__"
    if isinstance(right, ast.Name) and right.id == "__name__":
        return isinstance(left, ast.Constant) and left.value == "__main__"
    return False


def walk_module(parsed: ParsedFile, symbols: SymbolTable, dotted: str) -> ModuleIR:
    """Structural pass over one module."""
    module = _Walker(parsed, symbols, dotted).run()
    module.imports = tuple(symbols.imported_modules)
    module.frameworks = symbols.frameworks
    return module


# ---------------------------------------------------------------------------
# loop classification (runs after bindings exist)
# ---------------------------------------------------------------------------

def _unwrap_iter(node: ast.expr) -> ast.expr:
    """Strip enumerate()/zip()/tqdm() wrappers around the iterated value."""
    seen = 0
    while isinstance(node, ast.Call) and seen < 4:
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else "")
        if name in ("enumerate", "tqdm", "zip", "iter", "list", "reversed", "trange"):
            if not node.args:
                return node
            node = node.args[0]
            seen += 1
            continue
        break
    return node


def classify_loops(module: ModuleIR, binding_lookup) -> None:
    """Assign `kind`, `iterates` and a stable qualname to every loop."""
    counters: Dict[str, int] = {}
    for loop in module.loops:
        kind, evidence, value = _classify(loop, binding_lookup)
        loop.kind = kind
        loop.evidence = evidence
        loop.iterates = value
    for loop in module.loops:
        base = "%s.%s_loop" % (loop.scope.qualname, loop.kind)
        counters[base] = counters.get(base, 0) + 1
        loop.qualname = base if counters[base] == 1 else "%s%d" % (base, counters[base])


def _classify(loop: LoopIR, binding_lookup):
    node = loop.node
    if not isinstance(node, (ast.For, ast.AsyncFor)):
        return "other", (), None
    iter_node = _unwrap_iter(node.iter)
    targets = loop.targets
    value = None
    name = dotted_text(iter_node)
    if name:
        value = binding_lookup(name, loop.scope)

    # fold: iterating a splitter's .split()
    if isinstance(iter_node, ast.Call):
        callee = iter_node.func
        if isinstance(callee, ast.Attribute) and callee.attr == "split":
            base = dotted_text(callee.value)
            base_ref = binding_lookup(base, loop.scope) if base else None
            if base_ref is not None and base_ref.producer is not None:
                from ..knowledge import role_of
                if role_of(base_ref.producer.fqn) in ("SPLITTER", "SPLIT"):
                    return "fold", ("iterates a cross-validation splitter",), base_ref
            if base and any(k in base.lower() for k in ("kfold", "splitter", "cv", "skf")):
                return "fold", ("iterates a splitter-named value",), base_ref
        func_fqn = None
        if isinstance(callee, ast.Name):
            func_fqn = callee.id
        if func_fqn == "range":
            arg_names = [dotted_text(a) or "" for a in iter_node.args]
            if any(any(e in (a or "").lower() for e in _EPOCH_NAMES) for a in arg_names):
                return "epoch", ("range() over an epoch count",), None
            if any("epoch" in t.lower() for t in targets):
                return "epoch", ("range() with an epoch target",), None
            # A *fully* literal range - `range(10)`, `range(0, 100, 5)`. One
            # literal bound is not enough: `range(1, len(parts))` is ordinary
            # index arithmetic, not an epoch count.
            if iter_node.args and all(isinstance(a, ast.Constant) for a in iter_node.args):
                return "epoch", ("range() over a literal count",), None
            if any("epoch" in t.lower() for t in targets):
                return "epoch", ("epoch loop target",), None
            return "other", (), None

    if any("epoch" in t.lower() for t in targets):
        return "epoch", ("loop target named epoch",), None

    if value is not None and value.has("LOADER"):
        return "batch", ("iterates a LOADER-tagged value",), value
    lowered = (name or "").lower()
    if lowered and any(k in lowered for k in _LOADER_NAME_RE):
        return "batch", ("iterates a loader-named value",), value
    if value is not None and value.has("TRAIN_SPLIT", "VAL_SPLIT", "TEST_SPLIT", "BATCH"):
        return "batch", ("iterates a split value",), value
    return "other", (), value
