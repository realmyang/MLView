"""H5 - structured fixes: the only place in MLView where an edit is computed.

`REQUIREMENTS.md` section 5 non-goal 5 barred fixes that edit user logic. The
lead lifted it for this item **with guardrails**, and every one of them lives
here rather than in the five rules that opt in:

1. **Rules opt in.** `Issue.fix` is absent unless a rule asked for one, so the
   field is never a lie about what MLView is willing to stand behind.
2. **Edits are computed from the AST.** Every position on every edit comes from
   an `ast` node's `lineno` / `col_offset` / `end_lineno` / `end_col_offset`.
   No fix is ever built by searching the source for a substring, because that
   is how an edit lands inside a string literal or at the wrong indentation
   depth in a `with` block.
3. **Nothing below `likely`.** `GraphContext.issue` drops the fix when the
   computed bucket is `possible` or `speculative` (`FIXABLE_BUCKETS`). A rule
   cannot override that: it hands over a candidate, the engine decides.
4. **`mechanical` is a promise, not a mood.** A `mechanical` fix changes one
   keyword argument at one call site and cannot change control flow; a host may
   mark it `isPreferred`. Everything that inserts a *statement* into somebody's
   training loop is `needs-review`, because an inserted statement can always be
   the thing the author deliberately left out (the `MLV201_good.py` fixture is
   exactly that: `zero_grad()` under a gradient-accumulation guard).
5. **Never auto-applied.** Nothing in the analyzer, and nothing this module
   returns, applies an edit to a file on disk. `apply_edits` exists so that
   *this* module can prove an edit re-parses before publishing it, and so the
   tests can prove the rule stops firing afterwards.

**Every fix is parse-checked before it is published.** `build_fix` applies the
candidate edits to a copy of the module source in memory and runs `ast.parse`
over the result; a candidate that does not parse is discarded and the issue
ships with its prose `fixHint` alone. That is what makes "applying the edit
leaves the file `ast.parse`-valid" a property of the design rather than a hope
pinned by five tests.

**What this cannot do, stated where the code is.** Four conditions withhold an
edit and there is deliberately no attempt to work around any of them:

* **A non-ASCII line.** `CONTRACTS` section 0 says columns are 0-based and
  "matches `ast.col_offset` and `vscode.Position.character`" - true for ASCII,
  false the moment a line carries a non-ASCII character, because the first is a
  UTF-8 byte offset and the second a UTF-16 code-unit offset. A location is
  only ever *read* by a host, so the divergence costs a highlight a few columns
  wide; an **edit** applied at the wrong offset corrupts the file. Every line an
  edit touches must therefore be pure ASCII, or no fix is offered.
* **A name that is not a name.** An edit that has to spell an object
  (`optimizer.zero_grad()`, `model.eval()`) is built only when the receiver is a
  plain dotted name. `get_optimizer()[0].step()` gets prose, not an edit.
* **A missing import.** `generator=torch.Generator().manual_seed(42)` and
  `@torch.no_grad()` both need the name `torch` bound *in the edited module*.
  `samples/vision_pipeline/data.py` imports `random_split` but never `torch`,
  so its unseeded split gets the hint and no edit - and that is the honest
  answer, not an excuse to also insert an import statement.
* **A block that would have to be re-indented.** MLV302's textbook fix wraps a
  loop in `with torch.no_grad():`, which means re-indenting every physical line
  of the block - including the inside of any triple-quoted string in it. This
  module refuses; it offers the decorator form when the enclosing function is
  provably gradient-free, and nothing otherwise.

`fix_docs.FIX_DOCS` carries those statements per rule, and
`analyzer/tools/gen_rule_docs.py` renders them into `docs/rules/<CODE>.md`, so
the page a host deep-links to says when the lightbulb is empty and why.
"""

from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import knowledge as K
from .fix_docs import FIX_CODES, FIX_DOCS, MECHANICAL, NEEDS_REVIEW

__all__ = [
    "TextEdit", "Fix", "MECHANICAL", "NEEDS_REVIEW", "SAFETY_VALUES",
    "FIXABLE_BUCKETS", "MAX_EDITS", "FIX_CODES", "FIX_DOCS",
    "apply_edits", "build_fix", "insert_before_stmt", "insert_decorator",
    "replace_node", "append_keyword",
    "zero_grad_fix", "eval_mode_fix", "no_grad_fix", "random_state_fix",
    "shuffle_false_fix",
]

SAFETY_VALUES = (MECHANICAL, NEEDS_REVIEW)

#: The two confidence buckets that may carry an edit (guardrail 3).
FIXABLE_BUCKETS = ("certain", "likely")
#: An upper bound on how much of a file one fix may touch. Nothing built here
#: needs more than two edits; the cap is what stops a future builder from
#: quietly becoming a refactoring engine.
MAX_EDITS = 4

_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
#: Roles whose presence anywhere in a function means the function trains, so it
#: must never be decorated `@torch.no_grad()`.
_TRAINING_ROLES = ("BACKWARD", "OPT_STEP", "ZERO_GRAD")


# ---------------------------------------------------------------- the objects
@dataclass(frozen=True)
class TextEdit:
    """One replacement of a source range, in `CONTRACTS` section 0 coordinates.

    `line` / `endLine` are 1-based inclusive, `col` / `endCol` 0-based, exactly
    as every `Loc` in the document is - and for the same reason: a host must
    convert once, at its own boundary, and never guess. A zero-width range
    (`line == endLine and col == endCol`) is an insertion.

    Both `file` and `absFile` are carried. Every other location-bearing object
    in the schema carries both, and a host that has to rebuild an absolute path
    from a relative one is the multi-root bug CONTRACTS 11.40 B already fixed
    once.
    """

    file: str
    absFile: str
    line: int
    col: int
    endLine: int
    endCol: int
    newText: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "absFile": self.absFile,
            "line": self.line,
            "col": self.col,
            "endLine": self.endLine,
            "endCol": self.endCol,
            "newText": self.newText,
        }


@dataclass(frozen=True)
class Fix:
    """A titled, safety-graded set of edits to exactly one file.

    There is deliberately no `isPreferred` field: it is derivable from `safety`
    (`mechanical` and only `mechanical`), and two spellings of one decision is
    how they come to disagree.
    """

    title: str
    safety: str
    edits: Tuple[TextEdit, ...]

    @property
    def is_preferred(self) -> bool:
        return self.safety == MECHANICAL

    @property
    def file(self) -> str:
        return self.edits[0].file if self.edits else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "safety": self.safety,
            "edits": [e.to_dict() for e in self.edits],
        }


# ------------------------------------------------------------- applying edits
def _line_starts(data: bytes) -> List[int]:
    starts = [0]
    for index, byte in enumerate(data):
        if byte == 0x0A:
            starts.append(index + 1)
    return starts


def _byte_offset(data: bytes, starts: List[int], line: int, col: int) -> int:
    """Absolute byte offset of `(line, col)`, or `ValueError`.

    `col` is interpreted the way `ast.col_offset` produces it: a UTF-8 **byte**
    offset inside the line. Every edit this module publishes is confined to
    ASCII lines, where that is also the character offset and the UTF-16 offset,
    so the three conventions cannot disagree about a published fix; the byte
    reading is what keeps `apply_edits` correct when a test hands it something
    outside that promise.
    """
    if line < 1 or line > len(starts):
        raise ValueError("line %d is outside the file" % line)
    start = starts[line - 1]
    end = starts[line] if line < len(starts) else len(data)
    while end > start and data[end - 1] in (0x0A, 0x0D):
        end -= 1
    if col < 0 or start + col > end:
        raise ValueError("column %d is past the end of line %d" % (col, line))
    return start + col


def apply_edits(source: str, edits: Sequence[TextEdit]) -> str:
    """Apply `edits` to `source` and return the new text.

    Pure: it never touches a file. Overlapping edits raise rather than
    silently producing whichever result the sort order happened to give.
    """
    data = source.encode("utf-8")
    starts = _line_starts(data)
    spans: List[Tuple[int, int, bytes]] = []
    for edit in edits:
        begin = _byte_offset(data, starts, edit.line, edit.col)
        finish = _byte_offset(data, starts, edit.endLine, edit.endCol)
        if finish < begin:
            raise ValueError("edit ends before it starts")
        spans.append((begin, finish, edit.newText.encode("utf-8")))
    spans.sort(key=lambda span: (span[0], span[1]))
    out = bytearray()
    cursor = 0
    for begin, finish, text in spans:
        if begin < cursor:
            raise ValueError("overlapping edits")
        out += data[cursor:begin]
        out += text
        cursor = finish
    out += data[cursor:]
    return out.decode("utf-8")


# ------------------------------------------------------------------- guards
def _lines(module) -> List[str]:
    return module.source.splitlines()


def _line_text(module, line: int) -> Optional[str]:
    lines = _lines(module)
    if line < 1 or line > len(lines):
        return None
    return lines[line - 1]


def _ascii_span(module, first: int, last: int) -> bool:
    """Every physical line in `[first, last]` is pure ASCII."""
    lines = _lines(module)
    if first < 1 or last > len(lines) or last < first:
        return False
    return all(lines[i].isascii() for i in range(first - 1, last))


def _starts_its_line(module, node: ast.AST) -> bool:
    """`node` is the first thing on its line - so inserting above it is safe.

    `with a: b()` and `if x: y()` put a statement in the middle of a line; an
    "insert before this statement" edit there would produce a new line inside
    somebody else's suite header.
    """
    text = _line_text(module, getattr(node, "lineno", 0))
    col = getattr(node, "col_offset", None)
    if text is None or col is None or col > len(text):
        return False
    return text[:col].strip() == ""


def _dotted_ok(name: Optional[str]) -> bool:
    """A plain dotted name we are willing to write into somebody's file."""
    if not name or not _DOTTED_RE.match(name):
        return False
    return not any(keyword.iskeyword(part) for part in name.split("."))


def _binds_module(module, name: str) -> bool:
    """`name` is bound in this module to the module of the same dotted name.

    `import torch` binds it; `from torch.utils.data import random_split` does
    not, and `samples/vision_pipeline/data.py` is exactly that file.
    """
    symbols = getattr(module, "symbols", None)
    if symbols is None:
        return False
    return symbols.resolve_name(name) == name


def _first_body_stmt(node: ast.AST) -> Optional[ast.stmt]:
    """The first statement of a suite, skipping a docstring."""
    body = list(getattr(node, "body", ()) or ())
    if not body:
        return None
    head = body[0]
    if (isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant)
            and isinstance(head.value.value, str)):
        return body[1] if len(body) > 1 else None
    return head


def _defined_after(ref, module, line: int) -> bool:
    """The value's producer sits at or below `line` in this file.

    Writing `optimizer.zero_grad()` above the statement that creates the
    optimizer turns a finding into a `NameError`.
    """
    producer = getattr(ref, "producer", None) if ref is not None else None
    loc = getattr(producer, "loc", None)
    if loc is None:
        return False
    return loc.file == module.relpath and loc.line >= line


# -------------------------------------------------------------- edit builders
def insert_before_stmt(module, stmt: ast.AST, text: str) -> Optional[TextEdit]:
    """Insert `text` as its own statement immediately above `stmt`.

    The indentation is `stmt.col_offset` - the AST's own answer to "how deep is
    this suite" - so the edit is correct at any nesting depth, inside a `with`,
    an `if` or three loops, with no knowledge of tab width or of the file's
    style.
    """
    if stmt is None or not _starts_its_line(module, stmt):
        return None
    line = stmt.lineno
    col = stmt.col_offset
    if not _ascii_span(module, line, line):
        return None
    return TextEdit(file=module.relpath, absFile=module.abspath, line=line, col=col,
                    endLine=line, endCol=col, newText="%s\n%s" % (text, " " * col))


def insert_decorator(module, func_node: ast.AST, text: str) -> Optional[TextEdit]:
    """Insert a decorator line directly above a `def`.

    Placed below any decorators the function already has, which is where a
    context-manager decorator belongs: it is applied first, closest to the
    body.
    """
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    if not _starts_its_line(module, func_node):
        return None
    line = func_node.lineno
    col = func_node.col_offset
    if not _ascii_span(module, line, line):
        return None
    return TextEdit(file=module.relpath, absFile=module.abspath, line=line, col=col,
                    endLine=line, endCol=col, newText="%s\n%s" % (text, " " * col))


def replace_node(module, node: ast.AST, text: str) -> Optional[TextEdit]:
    """Replace exactly the source range of one expression."""
    line = getattr(node, "lineno", None)
    end_line = getattr(node, "end_lineno", None)
    if line is None or end_line is None:
        return None
    if not _ascii_span(module, line, end_line):
        return None
    return TextEdit(file=module.relpath, absFile=module.abspath, line=line,
                    col=node.col_offset, endLine=end_line, endCol=node.end_col_offset,
                    newText=text)


def append_keyword(module, call: ast.Call, text: str) -> Optional[TextEdit]:
    """Add `text` as the last argument of `call`.

    Anchored on the **end of the last argument** rather than on the closing
    parenthesis, so a trailing comment or a closing paren on its own line is
    untouched and the result stays valid whether or not the call had a trailing
    comma. A call with no arguments at all anchors just inside the parenthesis,
    and only when the character there really is one.
    """
    if not isinstance(call, ast.Call):
        return None
    for kw in call.keywords:
        if kw.arg is None:
            return None                  # `**overrides` - we cannot see inside it
    pieces = list(call.args) + [kw.value for kw in call.keywords]
    if pieces:
        last = max(pieces, key=lambda n: (getattr(n, "end_lineno", 0) or 0,
                                          getattr(n, "end_col_offset", 0) or 0))
        line = getattr(last, "end_lineno", None)
        col = getattr(last, "end_col_offset", None)
        if line is None or col is None:
            return None
        newText = ", %s" % text
    else:
        line = getattr(call, "end_lineno", None)
        col = getattr(call, "end_col_offset", None)
        if line is None or col is None or col < 1:
            return None
        col -= 1
        text_line = _line_text(module, line)
        if text_line is None or col >= len(text_line) or text_line[col] != ")":
            return None
        newText = text
    if not _ascii_span(module, line, line):
        return None
    return TextEdit(file=module.relpath, absFile=module.abspath, line=line, col=col,
                    endLine=line, endCol=col, newText=newText)


# ------------------------------------------------------------------ assembly
def build_fix(module, title: str, safety: str,
              edits: Sequence[Optional[TextEdit]]) -> Optional[Fix]:
    """Validate a candidate and return it, or `None` - never a partial fix.

    The last gate is the important one: the edits are applied to a copy of the
    module source and the result is re-parsed. Nothing that fails to parse can
    reach a user, whatever a builder above believed about the shape of the code.
    """
    if not title or safety not in SAFETY_VALUES:
        return None
    kept: List[TextEdit] = []
    for edit in edits:
        if edit is None:
            return None                  # a builder gave up: publish nothing
        kept.append(edit)
    if not kept or len(kept) > MAX_EDITS:
        return None
    if any(edit.file != module.relpath for edit in kept):
        return None                      # one fix, one file
    try:
        updated = apply_edits(module.source, kept)
    except ValueError:
        return None
    if updated == module.source:
        return None
    try:
        ast.parse(updated)
    except SyntaxError:
        return None
    return Fix(title=title, safety=safety, edits=tuple(kept))


# ------------------------------------------------------------- rule builders
def zero_grad_fix(ctx, loop, step) -> Optional[Fix]:
    """MLV201: zero the gradients as the first statement of the batch loop.

    Withheld when the optimizer is not a plain name, when the step that proves
    the finding lives in a followed callee rather than in this loop's own body
    (the loop we can see is then not the loop to edit), or when the optimizer is
    constructed below the insertion point.
    """
    module = getattr(loop, "module", None)
    node = getattr(loop, "node", None)
    if module is None or node is None or not hasattr(node, "body"):
        return None
    name = getattr(step, "receiver_name", None)
    if not _dotted_ok(name):
        return None
    if step.loc.file != module.relpath:
        return None
    end = getattr(node, "end_lineno", node.lineno)
    if not (node.lineno <= step.loc.line <= end):
        return None
    target = _first_body_stmt(node)
    if target is None:
        return None
    if _defined_after(getattr(step, "receiver", None), module, target.lineno):
        return None
    edit = insert_before_stmt(module, target, "%s.zero_grad(set_to_none=True)" % name)
    return ctx.fix(module, "Zero the gradients at the top of the batch loop",
                   [edit], safety=NEEDS_REVIEW)


def eval_mode_fix(ctx, region) -> Optional[Fix]:
    """MLV301: switch the model to eval mode immediately above the region.

    `needs-review` and never anything else: the edit adds `model.eval()` and
    cannot add the `model.train()` that has to follow it, because where that
    belongs is a question about the caller, not about this region.
    """
    forward = region.forward
    module = getattr(forward, "module", None)
    if module is None:
        return None
    name = region.model_name
    if not _dotted_ok(name):
        return None
    if region.loop is not None:
        anchor = getattr(region.loop, "node", None)
    else:
        func = region.func
        anchor = _first_body_stmt(getattr(func, "node", None)) if func is not None else None
    if anchor is None or region.loc.file != module.relpath:
        return None
    if _defined_after(region.model_ref, module, anchor.lineno):
        return None
    edit = insert_before_stmt(module, anchor, "%s.eval()" % name)
    return ctx.fix(module, "Switch %s to eval mode before this region" % name,
                   [edit], safety=NEEDS_REVIEW)


def no_grad_fix(ctx, region) -> Optional[Fix]:
    """MLV302: decorate the enclosing function `@torch.no_grad()`.

    The `with torch.no_grad():` wrap the fix hint names is **not** built here:
    wrapping a suite means re-indenting every physical line inside it, and a
    triple-quoted string in that suite would silently change value. The
    decorator form is the same guarantee expressed at a boundary the AST gives
    us exactly, so it is offered when - and only when - the enclosing function
    provably never trains, and withheld entirely when the region is not inside
    a function or the file has no `torch` bound to decorate with.
    """
    func = region.func
    module = getattr(func, "module", None) if func is not None else None
    node = getattr(func, "node", None) if func is not None else None
    if module is None or node is None:
        return None
    if not _binds_module(module, "torch"):
        return None
    for call in getattr(func, "calls", ()) or ():
        if K.role_of(call.fqn) in _TRAINING_ROLES:
            return None                  # the function trains: a wrap, not a decorator
    edit = insert_decorator(module, node, "@torch.no_grad()")
    return ctx.fix(module, "Decorate %s() with @torch.no_grad()" % func.name,
                   [edit], safety=NEEDS_REVIEW)


#: The literal each splitter's reproducibility keyword takes.
_SEED_VALUES = {
    "random_state": "42",
    "seed": "42",
    "generator": "torch.Generator().manual_seed(42)",
}


def random_state_fix(ctx, call, keyword_name: str) -> Optional[Fix]:
    """MLV602: pin the split by adding its reproducibility keyword.

    `mechanical`: one keyword at one call site, no statement inserted, no
    control flow touched. The torch spelling needs the name `torch` bound in
    the edited module and is withheld where it is not - which is the shape of
    `samples/vision_pipeline/data.py`, and the reason the demo ships one
    MLV602 with an edit and one without.
    """
    module = getattr(call, "module", None)
    node = getattr(call, "node", None)
    value = _SEED_VALUES.get(keyword_name)
    if module is None or node is None or value is None:
        return None
    if value.startswith("torch.") and not _binds_module(module, "torch"):
        return None
    edit = append_keyword(module, node, "%s=%s" % (keyword_name, value))
    return ctx.fix(module, "Add %s= to this split" % keyword_name,
                   [edit], safety=MECHANICAL)


def shuffle_false_fix(ctx, call) -> Optional[Fix]:
    """MLV111: turn the evaluation loader's `shuffle=True` into `shuffle=False`.

    The narrowest edit in the product: it replaces the range of one literal
    with another literal, so it is `mechanical` by any reading.
    """
    module = getattr(call, "module", None)
    node = (getattr(call, "kwarg_nodes", None) or {}).get("shuffle")
    if module is None or not isinstance(node, ast.Constant) or node.value is not True:
        return None
    edit = replace_node(module, node, "False")
    return ctx.fix(module, "Set shuffle=False on this evaluation DataLoader",
                   [edit], safety=MECHANICAL)
