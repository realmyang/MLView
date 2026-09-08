"""Where the server is allowed to read and write, and the analysis it caches.

Split out of ``mlview_mcp`` so the entry module is the bootstrap plus the five
tool definitions and nothing else.  Everything here is about the *outside* of a
tool call: resolving a caller-supplied path, deciding where a report may be
written, memoising an analysis, and finding a rule page.

Importing this module requires the ``mlview`` core to already be on ``sys.path``
— ``mlview_mcp`` runs its bootstrap first, which is why this is a separate file
rather than the top of that one.

Two of these functions exist purely as guards, and both cover a confirmed defect:

* ``resolve_out`` — the caller is a language model that has been reading untrusted
  third-party source, and ``mlview_open_diagram`` writes ~270 KB of HTML to the
  path it is handed and then launches it.  A ``../`` traversal or an unrelated
  absolute path must be a refusal, not an overwrite (CONTRACTS section 4 puts the
  same obligation on the webview's ``openLocation``).
* ``_RULE_DOC_ROOTS`` — rule pages are a property of the analyzer version, never of
  the code under analysis, so the analyzed project is deliberately not searched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

from mlview.api import AnalyzeOptions, analyze_to_dict

log = logging.getLogger("mlview.mcp")

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SERVER_DIR)
_REPO_ROOT = os.path.dirname(_PLUGIN_ROOT)

__all__ = [
    "project_dir", "data_dir", "resolve_path", "resolve_out",
    "analyzer_identity", "file_signature", "graph_file_for",
    "load_graph", "load_graph_or_file",
    "read_source", "rule_doc", "rule_spec", "RULE_DOC_ROOTS",
]


_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    "site-packages", "build", "dist", ".mypy_cache", ".pytest_cache", ".mlview",
    ".tox", ".idea", ".vscode",
}
_MAX_SIGNATURE_FILES = 2000

# In-process memo: (resolved path, framework, maxNodes, signature) -> (graph, path)
_CACHE: Dict[Any, Any] = {}


# ------------------------------------------------------------------ path handling
def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/")


def project_dir() -> str:
    """MLVIEW_PROJECT_DIR when set and real, otherwise the current directory."""
    raw = (os.environ.get("MLVIEW_PROJECT_DIR") or "").strip()
    if raw and os.path.isdir(raw):
        return _norm(raw)
    return _norm(os.getcwd())


def data_dir() -> str:
    """Where graph.json and report.html live: MLVIEW_DATA_DIR or <project>/.mlview."""
    raw = (os.environ.get("MLVIEW_DATA_DIR") or "").strip()
    base = _norm(raw) if raw else os.path.join(project_dir(), ".mlview")
    base = base.replace("\\", "/")
    os.makedirs(base, exist_ok=True)
    return base


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
    for root in (project_dir(), data_dir()):
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


_ANALYZER_IDENTITY: Optional[str] = None


def analyzer_identity() -> str:
    """A fingerprint of the analyzer that *produces* a document, cached per process.

    A cache key that names only the input is a lie: it says "these sources" when
    what it stores is "these sources, analyzed by that build". A confirmed defect
    came out of exactly that gap — a `.mlview/graph-*.json` written by an earlier
    build kept being served for unmodified sources while the current analyzer
    produced six more cross-file edges for them, so every scoped MCP answer
    disagreed with the CLI on the same selector (CONTRACTS 11.15 requires
    CLI-vs-MCP parity on scoped selectors).

    ``__version__`` alone is far too coarse — it does not move while a feature is
    being built, which is precisely when the analyzer changes hourly — so the
    bytes of every ``.py`` in the imported ``mlview`` package are hashed as well,
    plus ``renderer_sha()`` because the bundle hash is written into every
    document's ``generator``. Whichever copy of the core is on ``sys.path``
    (``analyzer/src`` or ``claude-plugin/vendor``) is the one measured.
    """
    global _ANALYZER_IDENTITY
    if _ANALYZER_IDENTITY is not None:
        return _ANALYZER_IDENTITY

    import mlview
    from mlview.version import __version__, renderer_sha

    digest = hashlib.sha1()
    digest.update(("%s\n%s\n" % (__version__, renderer_sha())).encode("utf-8"))
    try:
        root = os.path.dirname(os.path.abspath(mlview.__file__ or ""))
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root).replace("\\", "/")
                with open(full, "rb") as fh:
                    body = fh.read()
                digest.update(rel.encode("utf-8"))
                digest.update(hashlib.sha1(body).digest())
    except OSError as exc:
        # An unreadable package is not a reason to fail a tool call; it *is* a
        # reason to distrust the on-disk cache, so mark the identity unknown —
        # `load_graph` then treats every stored document as stale.
        log.warning("analyzer identity unavailable (%s); disk cache disabled", exc)
        _ANALYZER_IDENTITY = "unknown-%s" % os.getpid()
        return _ANALYZER_IDENTITY

    _ANALYZER_IDENTITY = "%s+%s" % (__version__, digest.hexdigest()[:16])
    return _ANALYZER_IDENTITY


def file_signature(path: str) -> str:
    """A cheap content signature: every .py file's relative path, mtime and size."""
    parts: List[str] = []
    if os.path.isfile(path):
        stat = os.stat(path)
        parts.append("%s|%d|%d" % (os.path.basename(path), stat.st_mtime_ns, stat.st_size))
    else:
        count = 0
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, path).replace("\\", "/")
                parts.append("%s|%d|%d" % (rel, stat.st_mtime_ns, stat.st_size))
                count += 1
                if count >= _MAX_SIGNATURE_FILES:
                    break
            if count >= _MAX_SIGNATURE_FILES:
                break
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def graph_file_for(path: str) -> str:
    """`<data>/graph.json` for the project root, `graph-<hash>.json` for a subpath."""
    base = data_dir()
    if _norm(path) == project_dir():
        return os.path.join(base, "graph.json").replace("\\", "/")
    stem = hashlib.sha1(_norm(path).encode("utf-8")).hexdigest()[:8]
    return os.path.join(base, "graph-%s.json" % stem).replace("\\", "/")


# ---------------------------------------------------------------------- analysis
def load_graph(
    path: Optional[str], framework: str = "auto", max_nodes: int = 400
) -> Dict[str, Any]:
    """Analyze (or reuse a cached analysis of) ``path``; also writes graph.json.

    Returns ``{"graph": <document>, "graphPath": <abs path>, "cached": bool}``.

    The key is ``(resolved, framework, maxNodes, signature)`` and never the scope
    (CONTRACTS 11.10): ``project()`` is applied to the cached dict, so widening is
    free. The *disk* half of the cache additionally records
    ``analyzer_identity()``, because a file that outlives the process also
    outlives the build that wrote it.
    """
    resolved = resolve_path(path)
    signature = file_signature(resolved)
    key = (resolved, framework or "auto", int(max_nodes), signature)
    graph_path = graph_file_for(resolved)

    cached = _CACHE.get(key)
    if cached is not None and os.path.exists(graph_path):
        return {"graph": cached, "graphPath": graph_path, "cached": True}

    # A previous process may have left a usable file behind — usable only if the
    # same analyzer wrote it. The sources are half of what a document depends on;
    # `analyzer_identity()` is the other half, and a sidecar without it (or with a
    # different one) was written by a build that is no longer running here.
    sidecar = graph_path + ".sig"
    analyzer = analyzer_identity()
    if os.path.exists(graph_path) and os.path.exists(sidecar):
        try:
            with open(sidecar, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if (
                stored.get("key") == list(key[:3])
                and stored.get("signature") == signature
                and stored.get("analyzer") == analyzer
            ):
                with open(graph_path, "r", encoding="utf-8") as fh:
                    graph = json.load(fh)
                _CACHE[key] = graph
                return {"graph": graph, "graphPath": graph_path, "cached": True}
        except (OSError, ValueError):
            log.warning("ignoring unreadable graph cache at %s", graph_path)

    log.info("analyzing %s (framework=%s maxNodes=%s)", resolved, framework, max_nodes)
    graph = analyze_to_dict(
        AnalyzeOptions(
            paths=(resolved,),
            framework=framework or "auto",
            max_nodes=int(max_nodes),
        )
    )
    _CACHE[key] = graph
    try:
        os.makedirs(os.path.dirname(graph_path), exist_ok=True)
        with open(graph_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(graph, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        with open(sidecar, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(
                {"key": list(key[:3]), "signature": signature, "analyzer": analyzer}, fh
            )
    except OSError as exc:  # a read-only data dir must not fail the tool
        log.warning("could not write %s: %s", graph_path, exc)
    return {"graph": graph, "graphPath": graph_path, "cached": False}


def load_graph_or_file(
    path: Optional[str], graph_path: Optional[str] = None
) -> Dict[str, Any]:
    """Prefer an existing ``graphPath``; otherwise analyze ``path``."""
    if graph_path:
        resolved = resolve_path(graph_path)
        if os.path.isfile(resolved):
            with open(resolved, "r", encoding="utf-8") as fh:
                return {"graph": json.load(fh), "graphPath": resolved, "cached": True}
        raise ValueError("graphPath is not a file: %s" % resolved)
    return load_graph(path)


def read_source(abs_file: Optional[str]) -> Optional[List[str]]:
    if not abs_file or not os.path.isfile(abs_file):
        return None
    try:
        with open(abs_file, "r", encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    except OSError:
        return None


#: Where a rule page may come from, in order. `_PLUGIN_ROOT/docs/rules` is what a
#: real install has (tools/sync-core.py ships it); `_REPO_ROOT/docs/rules` is the
#: checkout the plugin is being run out of.
#:
#: SECURITY: the directory *under analysis* is deliberately NOT on this list. It is
#: untrusted third-party source, `skills/mlview-triage/SKILL.md` tells the model to
#: trust a rule page over its own judgement of a finding, and a repository that could
#: plant `docs/rules/MLV201.md` would therefore get to define what MLView's own rules
#: mean about it — i.e. turn off any finding made against it.
RULE_DOC_ROOTS = (_PLUGIN_ROOT, _REPO_ROOT)


def rule_doc(code: str) -> Dict[str, Optional[str]]:
    """Find the shipped `docs/rules/<CODE>.md`; never one from the analyzed project."""
    for root in RULE_DOC_ROOTS:
        candidate = os.path.join(root, "docs", "rules", "%s.md" % code)
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                    return {"text": fh.read(), "path": _norm(candidate)}
            except OSError:
                continue
    return {"text": None, "path": None}


def rule_spec(code: str) -> Optional[Dict[str, Any]]:
    try:
        from mlview.rules import registry

        registry.discover_rules()
        spec = registry.rule_for(code)
    except Exception as exc:  # a registry problem must not sink the tool
        log.warning("rule registry unavailable: %s", exc)
        return None
    if spec is None:
        return None
    return {
        "severity": spec.severity, "frameworks": list(spec.frameworks),
        "tags": list(spec.tags), "absence": spec.absence, "enabled": spec.enabled,
        "title": spec.title, "why": spec.why, "fix_hint": spec.fix_hint,
    }

