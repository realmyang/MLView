"""MLV205's machinery: is this accumulated value still holding a graph?

`loss_accumulated_with_graph` in `rules/r_trainloop.py` is the rule; everything
it needs to decide is here, because the decision is the whole of the rule and
it is far larger than the other four training-step rules put together.

The question is asked backwards from the accumulation (`total += loss`): is the
operand detached upstream, is it a Python scalar already, does a helper that
produced it return one, is the accumulation guarded by `.item()` / `.detach()`,
and is the accumulator even a tensor? Every answer that is *not* "still
attached" silences the rule, so each of these helpers exists to say no.
"""

from __future__ import annotations

import ast
from typing import List, Optional

from .. import knowledge as K
from ..ir.model import LoopIR, ValueRef
from ..ir.symbols import dotted_text


#: Wrappers that detach the value before it is accumulated.
_ACCUM_SAFE = ("item", "detach", "float", "cpu", "numpy", "tolist")


def _within(loop: Optional[LoopIR], outer: Optional[LoopIR]) -> bool:
    """True when `loop` is `outer` or nested inside it."""
    if outer is None:
        return False
    while loop is not None:
        if loop is outer:
            return True
        loop = loop.parent_loop
    return False


def _accumulations(ctx, module):
    """`total += loss`, `total = total + loss` and `losses.append(loss)` in a loop."""
    out = []
    for record in module.assignments:
        if record.loop is None or record.value is None:
            continue
        # INFRA-01 (a). ISSUE_RULES section 3 promises this guard and the code
        # never had it: under `torch.no_grad()` there is no autograd graph, so
        # nothing an accumulator holds can keep one alive. `avg_psnr += psnr`
        # inside a validation loop is the canonical shape.
        if record.inside_no_grad:
            continue
        name = None
        if record.kind == "aug":
            name = dotted_text(record.targets[0]) if record.targets else None
        elif record.kind == "assign" and isinstance(record.value, ast.BinOp):
            for target in record.targets:
                text = dotted_text(target)
                if text and text in _names_of(record.value):
                    name = text
                    break
        if name is None or _guarded(record.value):
            continue
        loss_ref = _loss_operand(ctx, record.value, record.scope, name)
        if loss_ref is None:
            continue
        if _detached_upstream(module, record.value, record.scope, record.loc, name):
            continue
        out.append((name, record.loop, record.loc, record.scope, loss_ref,
                    "accumulates"))
    for call in module.calls:
        if (call.method or "") != "append" or call.loop is None or not call.args:
            continue
        if call.inside_no_grad:
            continue
        name = call.receiver_name
        container = ctx.binding_of(name, call.scope) if name else None
        if container is None or container.literal not in ("[]", "()"):
            continue
        if _guarded(call.args[0]):
            continue
        loss_ref = _loss_operand(ctx, call.args[0], call.scope, name)
        if loss_ref is None:
            continue
        if _detached_upstream(module, call.args[0], call.scope, call.loc, name):
            continue
        out.append((name, call.loop, call.loc, call.scope, loss_ref, "collects"))
    return out


def _detached_upstream(module, value, scope, loc, accumulator: str,
                       hops: int = 3) -> bool:
    """Does the accumulated value reach a `.item()` / `float()` / `math.*` hop?

    INFRA-01 (b) / PUB-08. `_guarded` only reads the right-hand side of the
    accumulation itself, so `psnr = 10 * log10(1 / mse.item())` one statement
    earlier was invisible and MLV205 called a Python float "the tensor psnr".
    The walk is bounded and purely syntactic: it follows the binding of each
    name the expression reads, in the same scope, to the statement that
    created it, and stops at the first detaching hop.
    """
    frontier = [n for n in _names_of(value) if n != accumulator]
    seen = set(frontier)
    for _ in range(max(1, hops)):
        nxt: List[str] = []
        for name in frontier:
            record = _last_binding(module, name, scope, loc)
            if record is None or record.value is None:
                continue
            if _produces_scalar(record.value) or _math_only(record.value):
                return True
            if _scalar_callee(record):
                return True
            for other in _names_of(record.value):
                if other not in seen and other != accumulator:
                    seen.add(other)
                    nxt.append(other)
        if not nxt:
            break
        frontier = nxt
    return False


#: Return annotations that declare the value is a Python number, not a tensor.
_SCALAR_ANNOTATIONS = ("float", "int", "builtins.float", "builtins.int")


def _scalar_callee(record) -> bool:
    """Was this value produced by a workspace function that returns a scalar?

    `loss = _one_epoch(...)` where `def _one_epoch(...) -> float:` returns
    `running / max(len(loader), 1)` and `running` accumulated `loss.item()`.
    The author has declared the type; taking their word for it is cheaper and
    more reliable than re-deriving it, and a wrong annotation costs a missed
    finding rather than a false accusation.
    """
    call = getattr(record, "call", None)
    target = getattr(call, "target_function", None) if call is not None else None
    if target is None:
        return False
    annotation = (target.annotations or {}).get("return")
    if annotation and annotation.split(".")[-1] in ("float", "int"):
        return True
    node = getattr(target, "node", None)
    returns = getattr(node, "returns", None) if node is not None else None
    text = dotted_text(returns) if returns is not None else None
    if text and text.split(".")[-1] in ("float", "int"):
        return True
    # PUB2-04: no annotation, so read what the callee actually returns.
    return _callee_returns_scalar(target)


#: How many operand hops `_produces_scalar` walks before giving up.
_SCALAR_WALK = 16


def _produces_scalar(value: Optional[ast.expr]) -> bool:
    """Is the **value itself** produced by a detaching call? (VIS2-02)

    `_guarded` walks the whole statement with `ast.walk` and answers yes on any
    `int()` / `len()` / `float()` / `sum()` anywhere under it - including inside
    a comprehension, a subscript or another call's keyword. `_detached_upstream`
    then declared an accumulator a Python number because a statement two lines
    earlier happened to contain one:

        lengths = torch.tensor([int(w) for w in widths], dtype=torch.long)
        loss = criterion(model(x), y, lengths)
        running += loss           # <- MLV205 silent, on a live CTC loss

    That was `vision_ocr_ctc_bad train.py:87`, a standing miss. The walk here
    is value-directed: it descends only through operators that pass a value
    through (`a + b`, `-x`, `a if c else b`, a parenthesised tuple) and stops
    at the first call, which must itself be the detaching one. Arguments are
    never entered, because the argument of `torch.tensor(...)` is not the value
    `torch.tensor(...)` returns.
    """
    if value is None:
        return False
    stack: List[ast.expr] = [value]
    seen = 0
    while stack and seen < _SCALAR_WALK:
        node = stack.pop()
        seen += 1
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _ACCUM_SAFE:
                return True
            if isinstance(func, ast.Name) and func.id in ("float", "int", "len", "sum"):
                return True
            continue                 # a call's ARGUMENTS are not its value
        if isinstance(node, ast.BinOp):
            stack.extend([node.left, node.right])
        elif isinstance(node, ast.UnaryOp):
            stack.append(node.operand)
        elif isinstance(node, ast.IfExp):
            stack.extend([node.body, node.orelse])
        elif isinstance(node, (ast.Tuple, ast.List)):
            stack.extend(node.elts)
    return False


def _callee_returns_scalar(target, depth: int = 0) -> bool:
    """PUB2-04. Does every `return` of this workspace function yield a number?

    Round 1 taught the return-type inference to carry the LOSS tag across an
    arithmetic return, so MLV201/202 stop going blind on `loss = bpr_loss(...)`.
    That same inference then handed MLV205 a **Python float wearing a LOSS
    tag**, and the rule called it "the tensor":

        def train_epoch(dataloader, model, optimizer, criterion):
            total_loss = 0
            ...
                total_loss += loss.item()        # already a float
            return total_loss / len(dataloader)

        loss = train_epoch(...)
        print_loss_total += loss                 # <- MLV205, high confidence

    measured three times on the canonical PyTorch seq2seq tutorial. The tag is
    doing two jobs - "this is the objective" for the graph and "this is a live
    tensor" for MLV205 - and only the second is wrong here, so MLV205 (only)
    asks whether the callee's accumulator was already detached, using exactly
    the terminator test it applies locally.
    """
    if target is None or depth > 2 or not getattr(target, "returns", None):
        return False
    module = getattr(target, "module", None)
    scope = getattr(target, "scope", None)
    if module is None or scope is None:
        return False
    for expr in target.returns:
        if not _expr_is_scalar(module, scope, expr, depth):
            return False
    return True


def _expr_is_scalar(module, scope, expr, depth: int, hops: int = 3) -> bool:
    """Does this expression reduce to a Python number, following local stores?"""
    if expr is None:
        return False
    if isinstance(expr, ast.Constant):
        return True
    if _produces_scalar(expr) or _math_only(expr):
        return True
    if isinstance(expr, (ast.BinOp, ast.UnaryOp, ast.IfExp)):
        operands = ([expr.operand] if isinstance(expr, ast.UnaryOp)
                    else [expr.body, expr.orelse] if isinstance(expr, ast.IfExp)
                    else [expr.left, expr.right])
        return all(_expr_is_scalar(module, scope, o, depth, hops)
                   for o in operands)
    name = dotted_text(expr)
    if not name or hops <= 0:
        return False
    stores = [r for r in module.assignments
              if r.scope is scope and any(dotted_text(t) == name for t in r.targets)]
    if not stores:
        return False
    for record in stores:
        if not _expr_is_scalar(module, scope, record.value, depth, hops - 1):
            return False
    return True


def _last_binding(module, name: str, scope, loc):
    """The latest assignment to `name` in `scope` strictly above `loc`."""
    best = None
    for record in module.assignments:
        if record.scope is not scope or record.loc.line >= loc.line:
            continue
        if any(dotted_text(t) == name for t in record.targets):
            best = record
    return best


#: Free functions that cannot return a tensor, so a value built from one is a
#: Python number however it was spelled (`math.log10`, `math.sqrt`, ...).
_SCALAR_MODULES = ("math.", "statistics.")


def _math_only(value: ast.expr) -> bool:
    for child in ast.walk(value):
        if not isinstance(child, ast.Call):
            continue
        text = dotted_text(child.func) or ""
        if text.startswith(_SCALAR_MODULES) or text.split(".")[0] == "math":
            return True
    return False


def _returned(scope, name: str) -> bool:
    """Is the accumulator handed back to a caller that may back-propagate it?

    vision-05. ISSUE_RULES MLV205 false-positive note (a) suppresses the rule
    when `.backward()` is called on the accumulator, and note (b) covers a list
    later `torch.stack`ed and backwarded. `_backwarded` implements both by
    matching the accumulator's NAME inside the same module - which never
    applies to the standard custom-loss shape, where a `nn.Module.forward`
    accumulates its terms and RETURNS them for the caller to back-propagate
    under another name in another scope. The graph has to stay alive until
    then, so the only defensible answer is silence.

    The discriminator against the equally standard `def train_one_epoch(...):
    running += loss; return running / n` is what the enclosing function does
    with the gradients: a function that itself calls `.backward()` or
    `.step()` **is** the training loop, and the value it returns is
    bookkeeping the caller prints. A function that returns an accumulated
    tensor and never back-propagates is a loss builder, and this rule cannot
    see whether its caller detaches.
    """
    node = getattr(scope, "node", None)
    if node is None:
        return False
    short = name.split(".")[-1]
    returned = False
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) \
                and child.func.attr in ("backward", "step"):
            return False              # this scope owns the update: keep firing
        if not isinstance(child, ast.Return) or child.value is None:
            continue
        for sub in ast.walk(child.value):
            if isinstance(sub, (ast.Name, ast.Attribute)):
                text = dotted_text(sub) or ""
                if text and text.split(".")[-1] == short:
                    returned = True
    return returned


def _names_of(value: ast.expr) -> List[str]:
    out: List[str] = []
    for child in ast.walk(value):
        text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) else None
        if text and text not in out:
            out.append(text)
    return out


def _guarded(value: ast.expr) -> bool:
    for child in ast.walk(value):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr in _ACCUM_SAFE:
            return True
        if isinstance(func, ast.Name) and func.id in ("float", "int", "len", "sum"):
            return True
    return False


def _accumulated_label(loss_ref: ValueRef) -> str:
    """What is actually being added - the tensor, or the call that returns it.

    vision-16. `_loss_operand` returns the binding of any LOSS-tagged name in
    the accumulation expression, which for `total = total + self.classification(
    logits, y)` is the **criterion module**, not the tensor. Saying "the tensor
    self.classification" sends a reader looking for a variable that is an
    `nn.BCEWithLogitsLoss` instance.
    """
    producer = loss_ref.producer
    role = K.role_of(producer.fqn) if producer is not None else None
    if role in ("LOSS_CLS",) or (producer is not None and producer.var != loss_ref.name):
        return "the result of %s(...)" % loss_ref.name
    return "the tensor %s" % loss_ref.name


def _loss_operand(ctx, value: ast.expr, scope, accumulator: str) -> Optional[ValueRef]:
    for text in _names_of(value):
        if text == accumulator:
            continue
        ref = ctx.binding_of(text, scope)
        if ref is not None and ref.has("LOSS"):
            return ref
    return None


def _defined_outside(module, name: str, loop: Optional[LoopIR], loc):
    """The statement that created the accumulator outside the loop, if any."""
    best = None
    for other in module.assignments:
        if other.loc.line >= loc.line:
            continue
        # vision-06: the arguments were the wrong way round. `_within(a, b)`
        # asks "is a inside b"; the question here is whether the INITIALIZER
        # lives inside the accumulating loop (reset every pass, nothing to
        # leak), not whether the accumulating loop lives inside the
        # initializer's loop - which is true for `running = 0.0` in the epoch
        # loop and `running += loss` in the batch loop, the placement every
        # PyTorch tutorial writes and the one this rule most needs to see.
        if _within(other.loop, loop):
            continue                    # created inside the same loop: reset each pass
        if any(dotted_text(t) == name for t in other.targets):
            best = other
    return best


def _backwarded(module, name: str) -> bool:
    """`total_loss.backward()` (or `torch.stack(losses).backward()`) is deliberate."""
    short = name.split(".")[-1]
    stacked = set()
    for call in module.calls:
        if (call.fqn or "").endswith(("torch.stack", "torch.cat")) and call.var:
            for arg in call.args:
                if (dotted_text(arg) or "").split(".")[-1] == short:
                    stacked.add(call.var.split(".")[-1])
    wanted = {short} | stacked
    for call in module.calls:
        # The BACKWARD role needs the receiver's binding to resolve to a known
        # tensor producer, and an accumulator initialised `total = 0.0` never
        # does - so the role test alone made this guard blind to exactly the
        # shape the guard exists for. A syntactic `x.backward()` is proof
        # enough that somebody back-propagates `x`; a rule may stay silent on
        # weak evidence, but it may not accuse on it.
        if K.role_of(call.fqn) != "BACKWARD" \
                and (call.method or call.short_name) != "backward":
            continue
        receiver = (call.receiver_name or "").split(".")[-1]
        if receiver in wanted:
            return True
        for child in ast.walk(call.node):
            text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) \
                else None
            if text and text.split(".")[-1] in wanted:
                return True
    return False


# ---------------------------------------------------------------------------
# R18 - the two guards the recall round added, and the widening it did not
# ---------------------------------------------------------------------------
# R18(a) widened MLV205 from "the training loop" to *any* accumulating loop,
# which is right and which inherits two correct shapes the narrower rule never
# met. Both are guards: they can only remove a finding, never create one.
#
# R18's other half - reading a LOSS tag through `loss = criterion(...) / STEPS`
# - is deliberately **not** here. It was measured on the pinned public corpus
# and produced three false positives there (a running float divided by the step
# count, and two accumulations already taken off the graph upstream), so the
# guard is kept and the widening is not: a rule that is silent on a real defect
# costs a miss, and a rule that accuses correct code costs the reader's trust.


def _no_grad_region(loop: Optional[LoopIR]) -> bool:
    """True when the accumulation runs where autograd builds no graph.

        with torch.no_grad():
            for vinputs, vlabels in validation_loader:
                running_vloss += loss_fn(model(vinputs), vlabels)

    There is no graph behind `running_vloss`, so nothing is kept alive and the
    finding is simply wrong. The `with` block and the `@torch.no_grad()`
    decorator are the same fact recorded in two places (`ir.scopes_walk`), so
    both are read.
    """
    if loop is None:
        return False
    if loop.inside_no_grad:
        return True
    func = loop.function
    return bool(func is not None and func.inside_no_grad)


def _consumed_downstream(module, name: str, scope) -> bool:
    """True when the running total is one operand of the loss actually stepped.

        style_loss += mse_loss(...)
        total = content_loss + style_loss
        total.backward()

    The accumulation is the live value on purpose - one arithmetic step from
    the tensor the optimizer differentiates - so `.item()` here would detach
    the whole term from training. `_backwarded` asks the same question about
    the accumulator's own name; this asks it about the names *derived* from it,
    one level only, in its own scope. Nothing here can raise the rule, so a
    missed derivation costs a false negative and never a false positive.
    """
    return any(_backwarded(module, candidate)
               for candidate in _derived_names(module, name, scope)
               if candidate != name)


def _derived_names(module, name: str, scope) -> List[str]:
    """Every name assigned from an expression that mentions `name`."""
    out: List[str] = []
    for record in module.assignments:
        if record.scope is not scope or record.value is None:
            continue
        if name not in _names_of(record.value):
            continue
        for target in record.targets:
            text = dotted_text(target)
            if text and text not in out and text != name:
                out.append(text)
    return out
