"""NB - `.ipynb` ingest: one notebook becomes one **generated** Python module.

Off unless the caller asks (`--include-notebooks`, or `[paths] notebooks =
true` in `.mlview.toml`). With the flag absent nothing here runs and the bytes
a run emits are exactly what they were before this module existed.

What the conversion guarantees, and why each guarantee exists:

* **Line counts are 1:1 inside a cell.** An IPython line magic (`%matplotlib
  inline`), a shell escape (`!pip install ...`) and a help query (`df.head?`)
  are not Python, so each becomes `pass  # mlview: magic` at its own
  indentation - never deleted, because deleting one would slide every later
  line of the cell by one and R2.1's re-slice guarantee would be off by that
  much for the rest of the notebook. The one exception is a magic that *wraps*
  a statement (`%time model.fit(X, y)`): the magic token is dropped and the
  statement kept, on its own line, so the pipeline still sees a real `fit`
  call - the only thing that moves is the column, by the width of the token.
  A cell whose first line is a *cell* magic that does not carry a Python body
  (`%%bash`, `%%writefile`) has every one of its lines blanked the same way, at
  column 0.
* **Cells are concatenated in document order**, each preceded by a
  `# %% cell N (execution_count K)` marker and followed by one blank line, and
  a three-line header names the notebook the module came from. The markers and
  the header are the reason a per-cell offset table exists at all: with it,
  every flat line maps back to `(cell, cellLine)`.
* **The generated module is materialised on disk** under `<root>/.mlview/
  notebooks/`, mirroring the notebook's own directory layout, and every `Loc`
  points at *that* file. `Loc` is frozen (CONTRACTS section 2), so it cannot
  carry a cell index; a location that pointed at the `.ipynb` would name a line
  of JSON, which is worse than useless to the host that has to open it. The
  cell mapping rides beside the `Loc` instead - `Node.attrs.cell` /
  `.cellLine` / `.notebook`, and one evidence factor per finding.

**What this cannot analyze, stated once.** Execution order. A notebook records
only the `execution_count` of its *last* run, and cells may have been run,
edited and re-run in any order since. Document order is therefore an
assumption, not a fact: when the recorded counts are not monotonic the
`notebook_analyzed` diagnostic says so and the order-sensitive rules are
de-rated (`rules/confidence.notebook_evidence`). Nothing here reconstructs a
real execution order, because nothing in the file records one.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .parse import ParsedFile, parse_source

__all__ = [
    "MAGIC_LINE", "SHADOW_DIR", "PYTHON_CELL_MAGICS", "PYTHON_LINE_MAGICS",
    "CellMap", "NotebookMap",
    "NotebookIngest", "convert", "ingest_notebooks", "is_notebook",
    "shadow_relpath", "failure_summary",
]

#: Where a generated module lives, workspace-relative. `.mlview/` is already
#: git-ignored, already in `discover.ALWAYS_PRUNE` (so a second pass can never
#: re-discover a shadow as source), and already where the analyzer writes its
#: cache - this is not a new place for the tool to put things.
SHADOW_DIR = ".mlview/notebooks"
#: PUB-15. The directory that gets the self-ignoring `.gitignore`.
SELF_IGNORE_DIR = ".mlview"


def _write_self_ignore(directory: str) -> None:
    """Drop a `.gitignore` containing `*` into MLView's own output directory.

    Written once, never overwritten: a user who edits it keeps their edit.
    Any `OSError` is swallowed - failing to write a convenience file must
    never fail an analysis.
    """
    import os as _os

    path = _os.path.join(directory, ".gitignore")
    try:
        if _os.path.exists(path):
            return
        _os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("# Created by MLView. Generated analysis output; not source.\n*\n")
    except OSError:
        pass

#: What a magic, a shell escape or a help query becomes. Never deleted: the
#: line has to stay a line.
MAGIC_LINE = "pass  # mlview: magic"

#: Cell magics whose body really is Python. Everything else beginning `%%` is
#: another language, and the whole cell is blanked.
PYTHON_CELL_MAGICS = frozenset({
    "time", "timeit", "capture", "prun", "debug", "memit", "snakeviz",
    "python", "python3", "pypy", "heat", "lprun",
})

#: Line magics that *wrap* a Python statement: `%time model.fit(X, y)` is a
#: real call, and blanking the line would lose it. The magic token is dropped
#: and the statement kept at the cell's own indentation, so the line count is
#: still 1:1 and only the **column** moves - by exactly the width of the magic
#: token. Padding with spaces instead would preserve the column too, and would
#: also make `%time y = 1` an IndentationError at module level, which costs the
#: whole notebook: a column is worth less than a file.
PYTHON_LINE_MAGICS = frozenset({
    "time", "timeit", "prun", "memit", "lprun", "capture", "debug", "snakeviz",
})

_HELP_RE = re.compile(r"^\?{0,2}[A-Za-z_][\w.]*\(?\)?\?{0,2}$")
_LINE_MAGIC_RE = re.compile(r"^(?P<magic>%{1,2}(?P<name>[A-Za-z_]\w*))(?P<rest>\s.*)?$")
_MAX_NAMED = 3


def is_notebook(relpath: str) -> bool:
    return relpath.lower().endswith(".ipynb")


def shadow_relpath(notebook_rel: str) -> str:
    """`nb/leak.ipynb` -> `.mlview/notebooks/nb/leak.py`.

    The notebook's own directory layout is preserved, so two notebooks can
    never collide, and the `.mlview` segment is not a legal Python identifier,
    so the generated module's dotted name can never shadow a real one.
    """
    rel = notebook_rel.replace("\\", "/")
    if rel.lower().endswith(".ipynb"):
        rel = rel[: -len(".ipynb")]
    return "%s/%s.py" % (SHADOW_DIR, rel)


# ------------------------------------------------------------------ mapping
@dataclass(frozen=True)
class CellMap:
    """One code cell's place in the generated module."""

    #: 0-based index among **all** cells of the notebook, markdown included -
    #: the index a host needs to address `vscode-notebook-cell:...#Wn`.
    index: int
    #: `execution_count` as recorded, or None for a cell that was never run.
    executionCount: Optional[int]
    #: 1-based flat line of this cell's FIRST source line in the module.
    startLine: int
    lineCount: int

    def contains(self, line: int) -> bool:
        return self.startLine <= line < self.startLine + self.lineCount


@dataclass(frozen=True)
class NotebookMap:
    """The per-cell offset table for one converted notebook."""

    notebook: str                      # workspace-relative `.ipynb`
    shadow: str                        # workspace-relative generated `.py`
    cells: Tuple[CellMap, ...] = ()
    totalCells: int = 0
    executionCounts: Tuple[Optional[int], ...] = ()
    orderOk: bool = True
    magicLines: int = 0

    @property
    def codeCells(self) -> int:
        return len(self.cells)

    def locate(self, line: int) -> Optional[Tuple[int, int]]:
        """Flat 1-based line -> `(cell index, 1-based line within the cell)`.

        None for the header and the `# %%` markers, which belong to no cell:
        an invented mapping is worse than an absent one.
        """
        for cell in self.cells:
            if cell.contains(line):
                return cell.index, line - cell.startLine + 1
        return None

    def counts_text(self) -> str:
        parts = ["?" if c is None else str(c) for c in self.executionCounts]
        return "[%s]" % ", ".join(parts)

    def order_text(self) -> str:
        """One sentence about what the recorded execution order proves."""
        if not any(c is not None for c in self.executionCounts):
            return ("no cell records an execution_count, so this notebook has "
                    "not been run since it was last saved; document order is "
                    "the only order there is")
        if self.orderOk:
            return ("execution_count %s is monotonic, so document order was "
                    "the last run order" % self.counts_text())
        return ("execution_count %s is NOT monotonic - the notebook was last "
                "run out of order, so document order may not be the order "
                "these cells actually ran in" % self.counts_text())

    def summary(self) -> str:
        """The `notebook_analyzed` message."""
        magics = ("; %d magic/shell line(s) replaced with `%s`"
                  % (self.magicLines, MAGIC_LINE)) if self.magicLines else ""
        return ("%s: %d of %d cell(s) are code and were analyzed as the "
                "generated module %s%s. %s. Locations name the generated "
                "module; every node carries attrs.notebook / attrs.cell / "
                "attrs.cellLine, and every finding carries the same mapping "
                "as evidence."
                % (self.notebook, self.codeCells, self.totalCells,
                   self.shadow, magics, self.order_text()))


@dataclass
class NotebookIngest:
    """What one ingest pass produced."""

    parsed: List[ParsedFile] = field(default_factory=list)
    #: generated-module relpath -> its offset table
    maps: Dict[str, NotebookMap] = field(default_factory=dict)
    #: `(notebook relpath, why)` for every notebook that did not make it
    failures: List[Tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------- conversion
def _cell_lines(source) -> List[str]:
    """A cell's `source`, as the notebook editor shows it.

    `source` is a list of lines (each keeping its trailing newline) in every
    notebook nbformat has ever written, but a string is legal and is what
    hand-written and generated notebooks tend to carry.
    """
    if isinstance(source, str):
        text = source
    elif isinstance(source, (list, tuple)):
        text = "".join(part for part in source if isinstance(part, str))
    else:
        return []
    if not text:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()                    # a trailing newline is not a line
    return lines


def _scan(line: str, depth: int, triple: str) -> Tuple[int, str]:
    """Bracket depth and open triple-quote after `line`.

    A magic is only a magic at statement position. `z = (a\\n % b)` is a
    modulo written on two lines, and a triple-quoted block may hold anything at
    all; rewriting either would turn correct code into a syntax error and lose
    the whole notebook. This is deliberately small - it tracks strings,
    comments and brackets, and nothing else.
    """
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if triple:
            if line.startswith(triple, index):
                index += 3
                triple = ""
                continue
            index += 2 if char == "\\" else 1
            continue
        if char == "#":
            break
        if char in "\"'":
            if line.startswith(char * 3, index):
                triple = char * 3
                index += 3
                continue
            index += 1
            while index < length:                 # a single-line string
                if line[index] == "\\":
                    index += 2
                    continue
                if line[index] == char:
                    index += 1
                    break
                index += 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        index += 1
    return depth, triple


def _is_magic(stripped: str) -> bool:
    if not stripped:
        return False
    head = stripped[0]
    if head in "%!?":
        return True
    if stripped.endswith("?") and _HELP_RE.match(stripped):
        return True
    return False


def _unwrap_magic(line: str) -> Optional[str]:
    """`%time model.fit(X, y)` -> `model.fit(X, y)`, or None.

    None whenever the result would not be Python - an unknown magic, a magic
    with no body, or one carrying its own options (`%timeit -n 100 f()`). The
    `ast.parse` check is what keeps a guess from costing the whole notebook: a
    bad substitution is a SyntaxError in the generated module, and the notebook
    would then be skipped entirely.
    """
    import ast

    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    match = _LINE_MAGIC_RE.match(stripped)
    if match is None or match.group("name").lower() not in PYTHON_LINE_MAGICS:
        return None
    rest = match.group("rest") or ""
    body = rest.strip()
    if not body:
        return None
    try:
        ast.parse(body)
    except (SyntaxError, ValueError):
        return None
    return indent + body


def _cell_magic_name(lines: Sequence[str]) -> Optional[str]:
    """The `%%name` of a cell magic, when the cell opens with one."""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            name = stripped[2:].split()[0] if stripped[2:].split() else ""
            return name.lower()
        return None
    return None


def _rewrite(lines: Sequence[str]) -> Tuple[List[str], int]:
    """One cell's lines, with the non-Python ones replaced. 1:1, always."""
    magic = _cell_magic_name(lines)
    if magic is not None and magic not in PYTHON_CELL_MAGICS:
        # `%%bash`, `%%html`, `%%writefile`: the body is another language, and
        # its indentation is not Python's, so every line goes to column 0.
        return [MAGIC_LINE] * len(lines), len(lines)
    out: List[str] = []
    replaced = 0
    depth, triple = 0, ""
    #: ROB-05. How many following lines belong to a blanked magic because the
    #: one above them ended in a backslash. `!pip install -q \` with two
    #: indented continuation lines is the single commonest install cell in a
    #: public Colab notebook: the first line became `pass  # mlview: magic` and
    #: the continuations were left as Python, so the generated module raised
    #: `IndentationError` and the notebook - training loop and all - was
    #: skipped. In a 655-notebook sweep, 16 of the 23 conversion failures were
    #: exactly this. A continuation of a non-Python line is not Python either.
    carry = False
    carry_indent = ""
    for line in lines:
        stripped = line.strip()
        if carry:
            # The continuation keeps the FIRST line's indent, not its own: a
            # shell continuation is indented for the shell's benefit, and
            # `pass` at a deeper column than the `pass` above it is the
            # IndentationError this guard exists to prevent.
            out.append(carry_indent + MAGIC_LINE)
            replaced += 1
            carry = line.rstrip().endswith("\\")
            continue
        if depth == 0 and not triple and _is_magic(stripped):
            unwrapped = _unwrap_magic(line)
            if unwrapped is not None:
                out.append(unwrapped)
                depth, triple = _scan(unwrapped, depth, triple)
                continue
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + MAGIC_LINE)
            replaced += 1
            carry = line.rstrip().endswith("\\")
            carry_indent = indent
            continue                   # a magic opens no bracket and no string
        out.append(line)
        depth, triple = _scan(line, depth, triple)
    return out, replaced


def _marker(index: int, count: Optional[int]) -> str:
    tail = "never executed" if count is None else "execution_count %d" % count
    return "# %%%% cell %d (%s)" % (index, tail)


def _monotonic(counts: Sequence[Optional[int]]) -> bool:
    """Strictly increasing over the cells that record a count.

    A cell with no count was not run in the last session and contradicts
    nothing, so it is skipped rather than treated as a break.
    """
    previous = None
    for count in counts:
        if count is None:
            continue
        if previous is not None and count <= previous:
            return False
        previous = count
    return True


def _cells_of(data) -> Optional[List]:
    cells = data.get("cells")
    if isinstance(cells, list):
        return cells
    sheets = data.get("worksheets")             # nbformat 3
    if isinstance(sheets, list):
        out: List = []
        for sheet in sheets:
            if isinstance(sheet, dict) and isinstance(sheet.get("cells"), list):
                out.extend(sheet["cells"])
        return out
    return None


def convert(text: str, notebook_rel: str):
    """`(source, NotebookMap, None)` or `(None, None, why)`."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, None, "invalid notebook JSON: %s" % exc
    if not isinstance(data, dict):
        return None, None, "invalid notebook JSON: the document is not an object"
    cells = _cells_of(data)
    if cells is None:
        return None, None, "invalid notebook JSON: no `cells` array"

    shadow = shadow_relpath(notebook_rel)
    out: List[str] = [
        "# Generated by MLView from %s - do not edit." % notebook_rel,
        "# Cell boundaries are the `# %%` markers; inside a cell every line "
        "maps 1:1",
        "# to the notebook (magics and shell escapes become `%s`)." % MAGIC_LINE,
    ]
    maps: List[CellMap] = []
    counts: List[Optional[int]] = []
    magic_lines = 0
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source")
        if source is None:
            source = cell.get("input")           # nbformat 3
        body, replaced = _rewrite(_cell_lines(source))
        magic_lines += replaced
        raw_count = cell.get("execution_count")
        if raw_count is None:
            raw_count = cell.get("prompt_number")
        count = (raw_count if isinstance(raw_count, int)
                 and not isinstance(raw_count, bool) else None)
        out.append(_marker(index, count))
        maps.append(CellMap(index=index, executionCount=count,
                            startLine=len(out) + 1, lineCount=len(body)))
        counts.append(count)
        out.extend(body)
        out.append("")

    nbmap = NotebookMap(
        notebook=notebook_rel, shadow=shadow, cells=tuple(maps),
        totalCells=len(cells), executionCounts=tuple(counts),
        orderOk=_monotonic(counts), magicLines=magic_lines)
    return "\n".join(out) + "\n", nbmap, None


# ------------------------------------------------------------------ ingest
def ingest_notebooks(root: str, relpaths: Sequence[str]) -> NotebookIngest:
    """Convert, materialise and parse every notebook in `relpaths`.

    A notebook that does not survive any of the three steps is a **failure**,
    not a silence: it comes back in `failures` and the pipeline both counts it
    in `notebooksSkipped` and says why. `notebooksSkipped` never silently
    becomes zero because the flag was on.
    """
    result = NotebookIngest()
    for rel in relpaths:
        abspath = "%s/%s" % (root, rel)
        try:
            with open(abspath, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            result.failures.append((rel, "cannot read the notebook: %s" % exc))
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            result.failures.append(
                (rel, "the notebook is not valid UTF-8 (%s at byte %d)"
                 % (exc.reason, exc.start)))
            continue
        source, nbmap, error = convert(text, rel)
        if source is None or nbmap is None:
            result.failures.append((rel, error or "cannot convert the notebook"))
            continue
        shadow_abs = "%s/%s" % (root, nbmap.shadow)
        try:
            parent = os.path.dirname(shadow_abs)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            # PUB-15: `--include-notebooks` writes generated modules into the
            # ANALYZED repository, which may not be the user's own, and left it
            # git-dirty with no way to ignore the output. `.pytest_cache` and
            # `.ruff_cache` solve this by ignoring themselves; so does this.
            _write_self_ignore("%s/%s" % (root, SELF_IGNORE_DIR))
            with open(shadow_abs, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(source)
        except OSError as exc:
            result.failures.append(
                (rel, "cannot write the generated module %s: %s"
                 % (nbmap.shadow, exc)))
            continue
        parsed, failure = parse_source(source, nbmap.shadow, shadow_abs)
        if parsed is None:
            why = failure.message if failure is not None else "parse failed"
            result.failures.append(
                (rel, "the generated module %s does not parse (%s) - a magic "
                      "or shell line this converter did not recognise is the "
                      "usual cause" % (nbmap.shadow, why)))
            continue
        result.parsed.append(parsed)
        result.maps[nbmap.shadow] = nbmap
    return result


def failure_summary(failures: Sequence[Tuple[str, str]]) -> str:
    """The tail of the `notebook_skipped` message when the flag is on."""
    named = ["%s (%s)" % (rel, why) for rel, why in failures[:_MAX_NAMED]]
    more = len(failures) - len(named)
    text = "; ".join(named)
    if more > 0:
        text += "; and %d more" % more
    return text
