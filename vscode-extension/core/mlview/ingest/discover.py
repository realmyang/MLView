"""File discovery: walk paths, honour excludes, cap, count notebooks.

Deterministic: the returned file list is always sorted by its
forward-slashed workspace-relative path.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Iterable, List, Sequence, Tuple

__all__ = ["ALWAYS_PRUNE", "DEFAULT_EXCLUDES", "Discovery", "discover",
           "normalize_path", "matches_any", "is_regular_file"]

DEFAULT_EXCLUDES: Tuple[str, ...] = (
    "**/.venv/**",
    "**/site-packages/**",
    "**/node_modules/**",
    "**/build/**",
    "**/.git/**",
)

#: Directories never walked into, regardless of patterns. Public since CACHE:
#: `core/cache.file_signature` must prune exactly what discovery prunes, or a
#: tree signature covers files that were never analyzed - the second copy of
#: this set in `claude-plugin/server/mlview_workspace.py` was already drifting.
ALWAYS_PRUNE = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".nox", ".idea", ".vscode-test", ".ipynb_checkpoints",
    ".mlview", "site-packages", "node_modules", ".venv", "venv", ".env",
    ".eggs", "dist", "build", ".claude",
})
#: The historical private name, kept so nothing that imported it breaks.
_ALWAYS_PRUNE = ALWAYS_PRUNE


def normalize_path(path: str) -> str:
    """Absolute, forward-slashed, no trailing slash (except a drive root)."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    out = abs_path.replace("\\", "/")
    if len(out) > 1 and out.endswith("/") and not out.endswith(":/"):
        out = out[:-1]
    return out


def _rel(root: str, abs_path: str) -> str:
    rel = os.path.relpath(abs_path, root).replace("\\", "/")
    return "./" if rel == "." else rel


def matches_any(relpath: str, patterns: Sequence[str]) -> bool:
    """fnmatch a forward-slashed relative path against glob patterns.

    `**/x/**` also matches `x/...` at the root, and a pattern matching any
    ancestor directory matches the file.
    """
    if not patterns:
        return False
    candidates = [relpath]
    parts = relpath.split("/")
    for i in range(1, len(parts)):
        candidates.append("/".join(parts[:i]))
    for pattern in patterns:
        variants = [pattern]
        if pattern.startswith("**/"):
            variants.append(pattern[3:])
        if pattern.endswith("/**"):
            variants.append(pattern[:-3])
            if pattern.startswith("**/"):
                variants.append(pattern[3:-3])
        for cand in candidates:
            for var in variants:
                if fnmatch(cand, var):
                    return True
    return False


@dataclass
class Discovery:
    """The result of a discovery pass."""

    root: str
    files: List[str] = field(default_factory=list)          # relpaths, sorted
    notebooks: int = 0
    file_cap_hit: bool = False
    total_found: int = 0
    missing: List[str] = field(default_factory=list)
    #: ROB-02 / ROB-04. `(path, reason)` for every entry discovery refused or
    #: could not enter: a FIFO / socket / device named `*.py`, and a directory
    #: `os.walk` could not read. Both used to vanish in silence - a FIFO wedged
    #: the process for ever and an unreadable package simply was not there,
    #: with `filesFailed: 0` asserting nothing had gone wrong. The pipeline
    #: turns each into a `parse_error` diagnostic.
    refused: List[Tuple[str, str]] = field(default_factory=list)
    #: NB. Appended last and empty unless `discover(..., notebooks=True)`:
    #: the `.ipynb` relpaths the caller asked to analyze, sorted. `notebooks`
    #: above stays the **count of every notebook found**, whether or not it is
    #: in this list, so `notebooksSkipped` can never quietly become zero.
    notebook_files: List[str] = field(default_factory=list)

    def abspath(self, relpath: str) -> str:
        return "%s/%s" % (self.root, relpath)


def is_regular_file(abs_path: str) -> Tuple[bool, str]:
    """`(ok, reason)` - is this path something it is safe to open and read?

    ROB-02. A repository is untrusted input, and `open()` on a FIFO with no
    writer blocks for ever while a `*.py` symlink to `/dev/zero` is read until
    the machine runs out of memory. Neither is a crash the user can see: the
    analyzer simply never returns. `os.stat` follows symlinks on purpose - the
    question is what will actually be read, not what the entry looks like.
    """
    try:
        st = os.stat(abs_path)
    except OSError as exc:
        # A dangling symlink lands here. The wording matches `parse.read_bytes`
        # on purpose: it is the same fact - this path cannot be read - and one
        # sentence for it is what the diagnostic channel is worth.
        return False, "cannot read file: %s" % (exc.strerror or exc)
    if not stat.S_ISREG(st.st_mode):
        return False, "not a regular file"
    return True, ""


def _common_root(paths: Sequence[str]) -> str:
    """Workspace root: the dir itself, the parent of a file, else the common path."""
    if len(paths) == 1:
        only = paths[0]
        return only if os.path.isdir(only) else normalize_path(os.path.dirname(only))
    bases = [p if os.path.isdir(p) else os.path.dirname(p) for p in paths]
    try:
        common = os.path.commonpath(bases)
    except ValueError:  # different drives on Windows
        common = os.path.dirname(bases[0])
    return normalize_path(common)


def discover(
    paths: Iterable[str],
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    max_files: int = 500,
    notebooks: bool = False,
) -> Discovery:
    """Walk `paths` (files or directories) and return the analyzable set.

    `notebooks` (NB) is appended last and defaults to False, so every existing
    call - positional or keyword - discovers exactly what it always did. With
    it True the `.ipynb` files that survive the exclude and include filters are
    additionally returned in `Discovery.notebook_files`; the `notebooks` count
    is unchanged either way.
    """
    given = [normalize_path(p) for p in (paths or ())]
    if not given:
        given = [normalize_path(".")]
    missing = [p for p in given if not os.path.exists(p)]
    existing = [p for p in given if os.path.exists(p)]
    root = _common_root(existing or given)
    excludes = tuple(DEFAULT_EXCLUDES) + tuple(exclude or ())

    found: List[str] = []
    notebook_files: List[str] = []
    notebook_count = 0
    refused: List[Tuple[str, str]] = []
    seen = set()

    def consider(abs_file: str) -> None:
        nonlocal notebook_count
        rel = _rel(root, abs_file)
        if rel in seen:
            return
        lower = rel.lower()
        if lower.endswith(".ipynb"):
            if not matches_any(rel, excludes):
                ok, why = is_regular_file(abs_file)
                if not ok:
                    refused.append((rel, why))
                    return
                seen.add(rel)
                notebook_count += 1
                if notebooks and not (include and not matches_any(rel, include)):
                    notebook_files.append(rel)
            return
        if not lower.endswith(".py"):
            return
        if matches_any(rel, excludes):
            return
        if include and not matches_any(rel, include):
            return
        ok, why = is_regular_file(abs_file)
        if not ok:
            refused.append((rel, why))
            return
        seen.add(rel)
        found.append(rel)

    def _walk_error(exc: OSError) -> None:
        """ROB-04: a directory `os.walk` could not enter is a fact, not a gap.

        `os.walk` swallows `PermissionError` by default, so a package the
        process may not read was skipped in silence and the document reported
        `filesAnalyzed: 1, filesFailed: 0, diagnostics: []` - a positive claim
        that nothing had gone wrong about a run that lost a whole package.
        """
        path = getattr(exc, "filename", None) or ""
        rel = _rel(root, normalize_path(path)) if path else "(unknown directory)"
        refused.append((rel, "%s: the directory could not be read (%s), so every "
                             "file under it is missing from this analysis"
                        % (rel, exc.strerror or str(exc))))

    for path in sorted(existing):
        if os.path.isfile(path):
            consider(path)
            continue
        for dirpath, dirnames, filenames in os.walk(path, onerror=_walk_error):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in _ALWAYS_PRUNE
                and not matches_any(_rel(root, os.path.join(dirpath, d).replace("\\", "/")), excludes)
            )
            for name in sorted(filenames):
                consider(os.path.join(dirpath, name).replace("\\", "/"))

    found.sort()
    refused.sort()
    notebook_files.sort()
    total = len(found)
    cap_hit = total > max_files > 0
    if cap_hit:
        found = found[:max_files]
    return Discovery(root=root, files=found, notebooks=notebook_count,
                     file_cap_hit=cap_hit, total_found=total, missing=missing,
                     refused=refused, notebook_files=notebook_files)
