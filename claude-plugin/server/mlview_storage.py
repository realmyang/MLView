"""Where the MCP server is allowed to read and write, and where it keeps its own state.

Split out of ``mlview_workspace`` when C8's cache-directory wiring pushed that
module past the repository's 750-line ceiling. The cut is along a real seam rather
than a line count: everything here answers *which directory*, takes no analyzer
import at module scope, and is therefore testable (``tests/test_storage_paths.py``,
``tests/test_out_containment.py``) without the core on ``sys.path``.

Two of these functions exist purely as guards, and both cover a confirmed defect:

* ``resolve_out`` — the caller is a language model that has been reading untrusted
  third-party source, and ``mlview_open_diagram`` writes ~270 KB of HTML to the path
  it is handed and then launches it. A ``../`` traversal or an unrelated absolute
  path must be a refusal, not an overwrite (CONTRACTS section 4 puts the same
  obligation on the webview's ``openLocation``).
* ``cache_dir`` — the parse cache is ON by default (11.39), so every directory this
  answers with is a directory MLView writes sidecars into. None of the three answers
  is inside the analyzed project, which is C8's whole clause.

``mlview_workspace`` re-exports every name below, so importers may use either
spelling and nothing that named ``mlview_workspace.data_dir`` had to change.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator, Optional

__all__ = [
    "project_dir", "named_data_dir", "data_dir", "cache_dir", "shared_cache_dir",
    "resolve_path", "resolve_out",
]


def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/")


def project_dir() -> str:
    """MLVIEW_PROJECT_DIR when set and real, otherwise the current directory."""
    raw = (os.environ.get("MLVIEW_PROJECT_DIR") or "").strip()
    if raw and os.path.isdir(raw):
        return _norm(raw)
    return _norm(os.getcwd())


def named_data_dir() -> Optional[str]:
    """The host's own storage directory, when the host named one.

    ``.mcp.json`` sets ``MLVIEW_DATA_DIR=${CLAUDE_PLUGIN_DATA}``, but a process that
    did not inherit it may still see ``CLAUDE_PLUGIN_DATA`` itself — a
    ``claude --plugin-dir`` session is the measured case — so both names are
    honoured, exactly as ``hooks/hook_core.hook_data_dir`` already does. ``None``
    means no host named anything and the defaults below apply.
    """
    for var in ("MLVIEW_DATA_DIR", "CLAUDE_PLUGIN_DATA"):
        raw = (os.environ.get(var) or "").strip()
        if raw:
            return _norm(raw)
    return None


def data_dir(create: bool = True) -> str:
    """Where graph.json and report.html live: the host's directory, else <project>/.mlview.

    ``create=False`` resolves the path without touching the disk. ``resolve_out``
    needs the string only to decide whether a model-supplied ``out`` is contained,
    and creating a directory inside somebody's repository as a side effect of
    ANSWERING A QUESTION is how ``.mlview/`` appeared in projects nobody had run a
    report on. Everything that actually writes here keeps ``create=True``.
    """
    base = (named_data_dir() or _norm(os.path.join(project_dir(), ".mlview")))
    base = base.replace("\\", "/")
    if create:
        os.makedirs(base, exist_ok=True)
    return base


def cache_dir() -> str:
    """The per-file parse cache: MLVIEW_CACHE_DIR, else the host's dir, else the core's.

    Three answers, in order, and **none of them is inside the analyzed project**:

    1. ``MLVIEW_CACHE_DIR`` — a host (or a CI job collecting the sidecar) named it.
    2. ``<data_dir>/cache`` when a host named its storage directory. This is what
       makes 11.41 C3 true — the hooks and the MCP tools share the *parse* cache
       and not merely the graph document, because both halves compute this one
       path — and it keeps everything under one directory the user can delete.
    3. Otherwise the core's own ``cache_dir_for(project)``: since C8 that is the
       user's cache directory keyed by the workspace path. Until C8 it fell
       through to ``<project>/.mlview/cache``, so a ``--plugin-dir`` session, or
       any direct run of this server, wrote a sidecar into the repository it was
       reading — the one thing C8 says must never happen by default. Deferring to
       the core is what keeps this host from having to re-decide it.
    """
    raw = (os.environ.get("MLVIEW_CACHE_DIR") or "").strip()
    if raw:
        return _norm(raw)
    if named_data_dir() is not None:
        return os.path.join(data_dir(), "cache").replace("\\", "/")
    from mlview.core.cache import cache_dir_for

    return cache_dir_for(project_dir()).replace("\\", "/")


@contextlib.contextmanager
def shared_cache_dir() -> Iterator[None]:
    """Run an analysis with ``MLVIEW_CACHE_DIR`` pointing at :func:`cache_dir`.

    Scoped to the call rather than set once at import: the variable is read by the
    core at analysis time and by nothing else, and a long-lived server that
    mutated its own environment permanently would carry one project's directory
    into a later call resolved against a different one. A host that named the
    variable itself keeps it — this only fills the hole.
    """
    if (os.environ.get("MLVIEW_CACHE_DIR") or "").strip():
        yield
        return
    os.environ["MLVIEW_CACHE_DIR"] = cache_dir()
    try:
        yield
    finally:
        os.environ.pop("MLVIEW_CACHE_DIR", None)


def resolve_path(path: Optional[str]) -> str:
    """Resolve a tool's ``path`` argument against the project directory.

    A missing path is a caller mistake, not a crash, so this raises ``ValueError``
    and the ``visible_errors`` wrapper re-raises it as ``ToolError`` — which is
    what carries the message into the ``isError`` result the model reads, so it
    can retry with a real path instead of seeing a bare "tool failed".
    """
    root = project_dir()
    if not path or not str(path).strip():
        return root
    raw = str(path).strip()
    candidate = raw if os.path.isabs(raw) else os.path.join(root, raw)
    candidate = _norm(candidate)
    if not os.path.exists(candidate):
        raise ValueError(
            "path not found: %r (resolved to %s). Pass a path relative to the "
            "project directory %s, or an absolute path." % (raw, candidate, root)
        )
    return candidate


def _contains(root: str, target: str) -> bool:
    """True when ``target`` is ``root`` itself or lives underneath it.

    Compared with ``os.path.normcase`` so a drive letter or a directory that
    differs only in case on Windows is still recognized as the same place.
    """
    def key(value: str) -> str:
        # normcase lowercases AND flips to backslashes on Windows; flip back so
        # one separator is compared throughout.
        return os.path.normcase(value).replace("\\", "/")

    root = key(root).rstrip("/")
    target = key(target)
    return target == root or target.startswith(root + "/")


def resolve_out(target: Optional[str], default_name: str = "report.html") -> str:
    """Resolve a caller-supplied output path, refusing anything outside the roots.

    ``mlview_open_diagram`` writes ~270 KB of HTML to this path and then hands it
    to ``os.startfile``, and the caller is a language model reading untrusted
    source — so ``out="../../../../Users/me/.bashrc"`` must be a refusal, not an
    overwrite. The permitted roots are the project directory and MLVIEW_DATA_DIR,
    the same containment obligation CONTRACTS section 4 puts on ``openLocation``.
    """
    roots = []
    for root in (project_dir(), data_dir(create=False)):
        if root and root not in roots:
            roots.append(root)
    raw = (str(target).strip() if target is not None else "")
    if not raw:
        return os.path.join(data_dir(), default_name).replace("\\", "/")
    full = _norm(raw if os.path.isabs(raw) else os.path.join(project_dir(), raw))
    if not any(_contains(root, full) for root in roots):
        raise ValueError(
            "out must stay inside the project directory or MLVIEW_DATA_DIR; %r "
            "resolves to %s, which is outside %s. Pass a relative path such as "
            "'.mlview/report.html', or omit out entirely."
            % (raw, full, " and ".join(roots))
        )
    return full
