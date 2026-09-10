"""Building `Loc`s from AST nodes.

Two invariants this module exists to guarantee:

* `loc.symbol` is sliced out of the primary source line **starting exactly at
  `loc.col`**, so `snippet.find(symbol) == col` always holds (the golden
  validator asserts it).
* columns are character offsets, converted from `ast`'s UTF-8 byte offsets.
"""

from __future__ import annotations

import ast
from typing import Optional

from ..ingest.parse import ParsedFile
from .model import Loc

__all__ = ["loc_of", "call_loc", "symbol_slice", "expr_symbol"]

_MAX_SYMBOL = 120


def _end_of(node: ast.AST, line: int, col: int):
    end_line = getattr(node, "end_lineno", None) or line
    end_col = getattr(node, "end_col_offset", None)
    if end_col is None:
        end_col = col
    return end_line, end_col


def symbol_slice(parsed: ParsedFile, line: int, col: int, end_line: int,
                 end_col: int) -> Optional[str]:
    """The source text of a single-line span, or None."""
    if end_line != line:
        return None
    text = parsed.line_text(line)
    if not text or col < 0 or end_col > len(text) or end_col <= col:
        return None
    seg = text[col:end_col]
    if not seg.strip() or "\n" in seg or len(seg) > _MAX_SYMBOL:
        return None
    return seg


def _header_symbol(parsed: ParsedFile, line: int, col: int, keyword: str) -> Optional[str]:
    """`for ... in ...` / `while ...` header text up to the colon."""
    text = parsed.line_text(line)
    if not text or col >= len(text):
        return None
    seg = text[col:]
    idx = seg.rfind(":")
    if idx > 0:
        seg = seg[:idx]
    seg = seg.rstrip()
    if not seg or len(seg) > _MAX_SYMBOL:
        return keyword if text[col:col + len(keyword)] == keyword else None
    return seg


def expr_symbol(parsed: ParsedFile, node: ast.AST, line: int, col: int,
                end_line: int, end_col: int) -> Optional[str]:
    """A `symbol` for this node that starts at (line, col)."""
    if isinstance(node, ast.Call):
        func = node.func
        f_line, f_col = func.lineno, parsed.char_col(func.lineno, func.col_offset)
        f_end_line, f_end_col = _end_of(func, f_line, f_col)
        f_end_col = parsed.char_col(f_end_line, f_end_col)
        if f_line == line and f_col == col:
            return symbol_slice(parsed, line, col, f_end_line, f_end_col)
        return None
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return _header_symbol(parsed, line, col, "for")
    if isinstance(node, ast.While):
        return _header_symbol(parsed, line, col, "while")
    if isinstance(node, ast.comprehension):
        return None
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        text = parsed.line_text(line)
        for kw in ("async def %s" % node.name, "def %s" % node.name):
            if text[col:col + len(kw)] == kw:
                return kw
        return None
    if isinstance(node, ast.ClassDef):
        kw = "class %s" % node.name
        if parsed.line_text(line)[col:col + len(kw)] == kw:
            return kw
        return None
    if isinstance(node, ast.Name):
        if parsed.line_text(line)[col:col + len(node.id)] == node.id:
            return node.id
        return None
    return symbol_slice(parsed, line, col, end_line, end_col)


def loc_of(parsed: ParsedFile, node: ast.AST, symbol: Optional[str] = None,
           line: Optional[int] = None) -> Loc:
    """A `Loc` for `node`, with a symbol sliced from the primary line."""
    start_line = line or getattr(node, "lineno", 1) or 1
    raw_col = getattr(node, "col_offset", 0) or 0
    col = parsed.char_col(start_line, raw_col)
    end_line, raw_end_col = _end_of(node, start_line, raw_col)
    end_col = parsed.char_col(end_line, raw_end_col)
    if end_line < start_line:
        end_line, end_col = start_line, col
    if end_line == start_line and end_col < col:
        end_col = col
    sym = symbol if symbol is not None else expr_symbol(parsed, node, start_line, col,
                                                        end_line, end_col)
    snippet = parsed.snippet(start_line)
    if sym and snippet is not None:
        found = snippet.find(sym)
        if found < 0 or (snippet.count(sym) == 1 and found != col):
            sym = None
    return Loc(file=parsed.relpath, absFile=parsed.abspath, line=start_line, col=col,
               endLine=end_line, endCol=end_col, symbol=sym, snippet=snippet)


def call_loc(parsed: ParsedFile, node: ast.Call) -> Loc:
    """A `Loc` for a call, anchored on the method name in a multi-line chain.

    `ast` gives a method call the position of the **start of its receiver**, so
    every link of

        ds = (tf.data.Dataset.from_tensor_slices((x, y))
              .map(normalize)
              .shuffle(4096)
              .batch(128))

    reports the line of `from_tensor_slices`: five nodes stacked on one line,
    and click-to-code that never lands on the call you clicked. When the callee
    attribute **ends on a later line** than the expression starts, the method
    name is the honest anchor and the only one a reader can find.

    A call written on one line is untouched - `func.end_lineno == node.lineno`
    - so every existing `Loc` in every fixture is byte-identical, which is what
    keeps R2.1's re-slice guarantee (`tests/core/test_locations.py`) provable
    rather than re-measured.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return loc_of(parsed, node)
    end_line = getattr(func, "end_lineno", None)
    raw_end_col = getattr(func, "end_col_offset", None)
    if (end_line is None or raw_end_col is None
            or end_line == (getattr(node, "lineno", None) or end_line)):
        return loc_of(parsed, node)
    col = parsed.char_col(end_line, raw_end_col) - len(func.attr)
    if col < 0 or parsed.line_text(end_line)[col:col + len(func.attr)] != func.attr:
        return loc_of(parsed, node)
    node_end_line, node_raw_end = _end_of(node, end_line, raw_end_col)
    node_end_col = parsed.char_col(node_end_line, node_raw_end)
    if node_end_line < end_line:
        node_end_line, node_end_col = end_line, col
    if node_end_line == end_line and node_end_col < col:
        node_end_col = col
    snippet = parsed.snippet(end_line)
    sym = func.attr
    if snippet is not None:
        found = snippet.find(sym)
        if found < 0 or (snippet.count(sym) == 1 and found != col):
            sym = None
    return Loc(file=parsed.relpath, absFile=parsed.abspath, line=end_line, col=col,
               endLine=node_end_line, endCol=node_end_col, symbol=sym, snippet=snippet)
