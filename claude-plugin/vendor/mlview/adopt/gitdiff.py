"""Added-line ranges from a git diff (CI-ADOPT part a).

    git -c core.quotepath=false diff -M --unified=0 --no-color <rev> --

`-M` is not optional: without rename detection a moved file reads as entirely
new and every finding in it is reported as `new` on the PR that moved it.
`--unified=0` is what makes a *line* attribution possible at all - with the
default three lines of context the added ranges would swallow their
neighbours.

Everything here is **failure-tolerant by contract**. No git binary, not a
repository, an unknown revision, a git that hangs, a diff that does not parse:
each returns a `ChangeSet` with `ok=False` and a human-readable `reason`, and
the caller turns that into a `config_warning` diagnostic and shows every
finding unattributed. Nothing in this module raises.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = ["ChangeSet", "changed_from_rev", "changed_from_file",
           "parse_unified_diff", "looks_like_diff", "GIT_TIMEOUT_S"]

#: A `git` that has not answered in this many seconds is treated as absent.
GIT_TIMEOUT_S = 20

_HUNK = re.compile(r"^@@+ .*?\+(\d+)(?:,(\d+))? .*?@@")
_DIFF_HEADER = re.compile(r"^diff --git ")


@dataclass(frozen=True)
class ChangeSet:
    """What changed, relative to the **analyzed workspace root**.

    `added` maps a workspace-relative path to inclusive `(first, last)` line
    ranges that the diff **added**. A path present in `files` with no entry in
    `added` changed without gaining lines (a pure deletion, a rename, or a
    path list that carried no hunks) - which is `touched`, never `new`.
    """

    files: Tuple[str, ...] = ()
    added: Dict[str, Tuple[Tuple[int, int], ...]] = field(default_factory=dict)
    source: str = ""
    ok: bool = True
    reason: str = ""
    #: False when the input was a bare path list: the files are known, the
    #: lines are not, so nothing can be classified `new`.
    hunks_known: bool = True

    def is_changed(self, relpath: str) -> bool:
        return _norm(relpath) in self.files

    def in_added(self, relpath: str, line: Optional[int]) -> bool:
        if not self.hunks_known or line is None:
            return False
        for first, last in self.added.get(_norm(relpath), ()):
            if first <= int(line) <= last:
                return True
        return False

    def has_added(self, relpath: str) -> bool:
        """Any added line anywhere in this file.

        NB (11.29 N5) makes a notebook finding's `loc.file` the **generated**
        module under `.mlview/notebooks/`, a path git has never seen and no PR
        ever contains, so its line numbers cannot be intersected with a hunk of
        the `.ipynb`. File granularity is the honest answer there: an added
        hunk anywhere in the notebook is a changed cell.
        """
        return bool(self.added.get(_norm(relpath)))

    @property
    def added_lines(self) -> int:
        return sum(last - first + 1
                   for ranges in self.added.values() for first, last in ranges)


def _norm(relpath: str) -> str:
    """Forward slashes, no `./` prefix. Written as a loop, not `lstrip('./')`:
    `lstrip` takes a character *set*, so it would eat the dot of
    `.github/workflows/ci.yml` and turn a hidden directory into a new one."""
    path = (relpath or "").replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _failed(source: str, reason: str) -> ChangeSet:
    return ChangeSet(files=(), added={}, source=source, ok=False, reason=reason)


def _finish(files: Dict[str, List[Tuple[int, int]]], source: str,
            hunks_known: bool = True) -> ChangeSet:
    """Freeze the accumulator into a deterministic `ChangeSet`."""
    added = {path: tuple(sorted(set(ranges)))
             for path, ranges in sorted(files.items()) if ranges}
    return ChangeSet(files=tuple(sorted(files)), added=added, source=source,
                     ok=True, reason="", hunks_known=hunks_known)


# ------------------------------------------------------------------- git
def _git(args: Sequence[str], cwd: str) -> Tuple[bool, str, str]:
    """Run git; returns `(ok, stdout, detail)`. Never raises."""
    try:
        proc = subprocess.run(["git"] + list(args), cwd=cwd, check=False,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=GIT_TIMEOUT_S)
    except FileNotFoundError:
        return False, "", "git is not on PATH"
    except subprocess.TimeoutExpired:
        return False, "", "git did not answer within %ds" % GIT_TIMEOUT_S
    except OSError as exc:                      # pragma: no cover - exotic
        return False, "", "git could not be run: %s" % exc
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
    if proc.returncode != 0:
        return False, out, (err[-1] if err else "git exited %d" % proc.returncode)
    return True, out, ""


def changed_from_rev(rev: str, root: str) -> ChangeSet:
    """`git diff -M --unified=0 <rev>` inside `root`, mapped to workspace paths."""
    source = "--changed-since %s" % rev
    if not os.path.isdir(root):                 # pragma: no cover - guarded upstream
        return _failed(source, "%s is not a directory" % root)
    ok, top, detail = _git(["rev-parse", "--show-toplevel"], root)
    if not ok:
        return _failed(source, "%s is not inside a git repository (%s)" % (root, detail))
    repo_root = top.strip() or root
    ok, _out, detail = _git(["rev-parse", "--verify", "--quiet", "%s^{commit}" % rev], root)
    if not ok:
        return _failed(source, "revision %r is unknown to git (%s)"
                       % (rev, detail or "no such commit"))
    ok, diff, detail = _git(["-c", "core.quotepath=false", "diff", "-M",
                             "--unified=0", "--no-color", rev, "--"], root)
    if not ok:
        return _failed(source, "git diff failed: %s" % detail)
    return parse_unified_diff(diff, root=root, repo_root=repo_root, source=source)


# ------------------------------------------------------------ diff parsing
def looks_like_diff(text: str) -> bool:
    for line in text.splitlines():
        if line.startswith("diff --git ") or line.startswith("@@ ") \
                or line.startswith("+++ ") or line.startswith("--- "):
            return True
    return False


def parse_unified_diff(text: str, root: str, repo_root: Optional[str] = None,
                       source: str = "diff") -> ChangeSet:
    """Parse a unified diff into per-file added-line ranges.

    Paths come from `+++ b/<path>` and from `rename to <path>`; `diff --git`
    only resets the per-file state, because its two-path form cannot be split
    unambiguously when a path contains a space. A `+++ /dev/null` (a deletion)
    contributes nothing: there is no line in the working tree to attribute to.
    """
    files: Dict[str, List[Tuple[int, int]]] = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        if _DIFF_HEADER.match(raw):
            current = None
            continue
        if raw.startswith("+++ "):
            target = raw[4:].split("\t")[0].strip()
            current = None if target == "/dev/null" else _relocate(target, root, repo_root)
            if current is not None:
                files.setdefault(current, [])
            continue
        if raw.startswith("rename to "):
            current = _relocate(raw[len("rename to "):].strip(), root, repo_root)
            if current is not None:
                files.setdefault(current, [])
            continue
        if raw.startswith("@@") and current is not None:
            match = _HUNK.match(raw)
            if match is None:
                continue
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            if count > 0:
                files[current].append((start, start + count - 1))
    return _finish(files, source)


def _relocate(git_path: str, root: str, repo_root: Optional[str]) -> Optional[str]:
    """git path (`b/src/train.py`, repo-relative) -> workspace-relative path.

    Returns `None` when the file is outside the analyzed workspace, so a
    monorepo diff touching another package never marks this package's findings
    as changed.
    """
    path = git_path
    for prefix in ("a/", "b/", "i/", "w/", "c/", "o/"):
        if path.startswith(prefix):
            path = path[2:]
            break
    path = path.strip('"')
    if repo_root is None:
        return _norm(path)
    absolute = os.path.normpath(os.path.join(repo_root, path))
    try:
        relative = os.path.relpath(absolute, os.path.abspath(root))
    except ValueError:                          # pragma: no cover - other drive
        return None
    relative = relative.replace("\\", "/")
    if relative.startswith("../") or relative == "..":
        return None
    return _norm(relative)


# ------------------------------------------------------------- path lists
def changed_from_file(path: str, root: str) -> ChangeSet:
    """`--changed-paths FILE`: either a unified diff or a list of paths.

    CI runners already hold one of the two. A diff gives line attribution; a
    bare path list gives file attribution only, so every finding in a listed
    file is `touched` and none is `new` - stated through `hunks_known=False`
    rather than by silently under-reporting.
    """
    source = "--changed-paths %s" % path
    try:
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
    except OSError as exc:
        return _failed(source, "cannot read %s: %s" % (path, exc))
    if looks_like_diff(text):
        return parse_unified_diff(text, root=root, repo_root=None, source=source)
    files: Dict[str, List[Tuple[int, int]]] = {}
    for raw in text.splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        relative = _as_relative(entry, root)
        if relative is not None:
            files.setdefault(relative, [])
    if not files:
        return _failed(source, "%s listed no changed paths" % path)
    return _finish(files, source, hunks_known=False)


def _as_relative(entry: str, root: str) -> Optional[str]:
    """A listed path, workspace-relative. Absolute entries outside the analyzed
    root are dropped rather than folded in - a runner that lists the whole
    repository must not mark another package's findings as changed."""
    entry = entry.strip('"').replace("\\", "/")
    if not os.path.isabs(entry):
        return _norm(entry)
    try:
        relative = os.path.relpath(entry, os.path.abspath(root)).replace("\\", "/")
    except ValueError:                          # pragma: no cover - other drive
        return None
    if relative.startswith("../") or relative == "..":
        return None
    return _norm(relative)
