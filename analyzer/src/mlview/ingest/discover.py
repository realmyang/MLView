"""File discovery: walk paths, honour excludes, cap, count notebooks.

Deterministic: the returned file list is always sorted by its
forward-slashed workspace-relative path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Iterable, List, Sequence, Tuple

__all__ = ["ALWAYS_PRUNE", "DEFAULT_EXCLUDES", "Discovery", "discover",
           "normalize_path", "matches_any"]

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

    def abspath(self, relpath: str) -> str:
        return "%s/%s" % (self.root, relpath)


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
) -> Discovery:
    """Walk `paths` (files or directories) and return the analyzable set."""
    given = [normalize_path(p) for p in (paths or ())]
    if not given:
        given = [normalize_path(".")]
    missing = [p for p in given if not os.path.exists(p)]
    existing = [p for p in given if os.path.exists(p)]
    root = _common_root(existing or given)
    excludes = tuple(DEFAULT_EXCLUDES) + tuple(exclude or ())

    found: List[str] = []
    notebooks = 0
    seen = set()

    def consider(abs_file: str) -> None:
        nonlocal notebooks
        rel = _rel(root, abs_file)
        if rel in seen:
            return
        lower = rel.lower()
        if lower.endswith(".ipynb"):
            if not matches_any(rel, excludes):
                seen.add(rel)
                notebooks += 1
            return
        if not lower.endswith(".py"):
            return
        if matches_any(rel, excludes):
            return
        if include and not matches_any(rel, include):
            return
        seen.add(rel)
        found.append(rel)

    for path in sorted(existing):
        if os.path.isfile(path):
            consider(path)
            continue
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in _ALWAYS_PRUNE
                and not matches_any(_rel(root, os.path.join(dirpath, d).replace("\\", "/")), excludes)
            )
            for name in sorted(filenames):
                consider(os.path.join(dirpath, name).replace("\\", "/"))

    found.sort()
    total = len(found)
    cap_hit = total > max_files > 0
    if cap_hit:
        found = found[:max_files]
    return Discovery(root=root, files=found, notebooks=notebooks,
                     file_cap_hit=cap_hit, total_found=total, missing=missing)
