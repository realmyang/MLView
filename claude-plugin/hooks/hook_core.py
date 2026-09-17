"""H8 — the shared body of MLView's two Claude Code hooks.

The plugin is otherwise entirely pull-based: when Claude edits a training file
during a session nothing tells it the edit introduced MLV203, and the user finds
out on the next manual ``/mlview-issues``. These hooks close that loop.

**The discipline is the feature.** A hook that speaks on every edit gets turned
off within a day, so every rule below is a rule about staying quiet:

* Exit 0 **immediately** unless the edited path is a ``.py`` under
  ``CLAUDE_PROJECT_DIR`` — or an ``.ipynb`` when notebooks are switched on.
* Re-analyze through the **same** ``load_graph`` cache the MCP tools read, so the
  hook *warms* the cache those tools then read for free rather than duplicating
  it.  ``MLVIEW_DATA_DIR`` is what the two share.
* Diff the **issue-id set** against the previous run and emit only when it
  **grew** — a re-analysis that finds the same 12 findings says nothing.
* At most :data:`MAX_ROWS` rows, under a hard :data:`BUDGET_SECONDS` wall-clock
  budget after which the process exits 0 in silence.
* Hooks are opt-in; unset or ``MLVIEW_HOOK=off`` disables both.
* **Never blocks** (exit is always 0; exit 2 is what blocks, and nothing here
  can produce it) and **never writes to the project**: when nothing names a data
  directory the analysis is redirected to a temporary one rather than allowed to
  create ``<project>/.mlview``.

What this cannot see, stated because the roadmap makes it a standing criterion:
an issue id is content-addressed, so an *unchanged* finding whose line moved
because of the edit comes back with a **new id**. Rows are therefore filtered to
genuinely new ``(code, file)`` pairs, and the re-anchored remainder is counted in
the summary line rather than printed as if it were new.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

# The vendored core is imported below; `claude plugin install` copies that tree
# verbatim, so a stale .pyc compiled from another revision must never ship with it.
sys.dont_write_bytecode = True

#: Hard wall clock. The signature cache makes an unchanged re-run ~0 s and the
#: bundled sample 0.07 s; a 445-file repository takes 5.6 s cold, and that run is
#: abandoned rather than allowed to sit in front of the next tool call.
BUDGET_SECONDS = 3.0
#: The most rows an `additionalContext` may carry.
MAX_ROWS = 5
#: The same floor the VS Code Problems panel publishes at (`mlview.minConfidence`).
#: A hook is the noisiest surface MLView has, so it is not the place to be louder
#: than the quietest one.
MIN_CONFIDENCE = 0.6

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_OFF = {"off", "0", "false", "no", "none", "disabled"}
_POST_ONLY = {"on", "1", "true", "yes", "post", "edit", "posttooluse"}
_STOP_ONLY = {"stop", "turn", "summary"}
_BOTH = {"both", "all"}

PY_SUFFIXES = (".py", ".pyi")
NOTEBOOK_SUFFIX = ".ipynb"

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_PLUGIN_ROOT)
_SERVER_DIR = os.path.join(_PLUGIN_ROOT, "server")


# ------------------------------------------------------------------ configuration
def hook_enabled(event: str, environ: Optional[Dict[str, str]] = None) -> bool:
    """Which of the two hooks may speak, per ``MLVIEW_HOOK``.

    Both matchers ship in ``hooks.json`` so switching between them costs an
    environment variable rather than a reinstall:

    ==================  ====================================================
    ``MLVIEW_HOOK``     effect
    ==================  ====================================================
    unset / ``off``     neither (the default)
    ``on``              PostToolUse speaks; Stop stays silent
    ``stop``            one summary per turn; PostToolUse stays silent
    ``both``            both
    ``off``             neither
    ==================  ====================================================

    An unrecognized value stays disabled: a typo must not enable analysis.
    """
    env = os.environ if environ is None else environ
    raw = (env.get("MLVIEW_HOOK") or "").strip().lower()
    if raw in _OFF:
        return False
    if raw in _STOP_ONLY:
        return event == "Stop"
    if raw in _BOTH:
        return True
    if raw in _POST_ONLY:
        return event == "PostToolUse"
    return False


def read_payload(stream: Any) -> Dict[str, Any]:
    """The hook's stdin JSON, or ``{}`` for anything unreadable.

    A malformed payload is a reason to do nothing, never a reason to raise: a
    traceback on stderr would be logged as a hook failure on every single edit.
    """
    try:
        text = stream.read()
    except Exception:  # pragma: no cover - a closed stdin
        return {}
    if not text or not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def edited_paths(payload: Dict[str, Any]) -> List[str]:
    """The files an ``Edit`` / ``Write`` / ``NotebookEdit`` call touched."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    found: List[str] = []
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
    return found


def project_dir(payload: Dict[str, Any]) -> Optional[str]:
    """``CLAUDE_PROJECT_DIR``, then the payload's ``cwd``. Never a guess."""
    for candidate in (os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd")):
        if isinstance(candidate, str) and candidate.strip() and os.path.isdir(candidate):
            return os.path.abspath(candidate).replace("\\", "/")
    return None


def _key(value: str) -> str:
    return os.path.normcase(os.path.abspath(value)).replace("\\", "/").rstrip("/")


def inside(root: str, target: str) -> bool:
    """True when ``target`` is ``root`` or lives under it, case-folded per platform."""
    root_key, target_key = _key(root), _key(target)
    return target_key == root_key or target_key.startswith(root_key + "/")


def notebooks_enabled(root: str) -> bool:
    """Whether an ``.ipynb`` edit is worth re-analyzing for.

    ``MLVIEW_INCLUDE_NOTEBOOKS`` first, then the project's own configuration —
    ``[paths] notebooks = true`` in ``.mlview.toml``, or the same key under
    ``[tool.mlview]`` in ``pyproject.toml``. Read as text rather than through the
    core, because this decision has to be made *before* the core is imported.
    """
    raw = (os.environ.get("MLVIEW_INCLUDE_NOTEBOOKS") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in _OFF:
        return False
    for name in (".mlview.toml", "pyproject.toml"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.split("#", 1)[0].strip().replace(" ", "")
            if stripped.lower() in ("notebooks=true",):
                return True
    return False


def relevant_paths(payload: Dict[str, Any], root: str) -> List[str]:
    """The edited paths this hook has any business re-analyzing for."""
    notebooks: Optional[bool] = None
    keep: List[str] = []
    for path in edited_paths(payload):
        absolute = path if os.path.isabs(path) else os.path.join(root, path)
        if not inside(root, absolute):
            continue
        lower = absolute.lower()
        if lower.endswith(PY_SUFFIXES):
            keep.append(absolute)
        elif lower.endswith(NOTEBOOK_SUFFIX):
            if notebooks is None:
                notebooks = notebooks_enabled(root)
            if notebooks:
                keep.append(absolute)
    return keep


# ------------------------------------------------------------------- the state file
def hook_data_dir(root: str) -> str:
    """Where the hook may write — and it is **never** the project.

    ``MLVIEW_DATA_DIR`` is what ``.mcp.json`` sets to ``${CLAUDE_PLUGIN_DATA}``,
    so honouring it is what makes the hook and the MCP tools share one cache. A
    hook process does not necessarily inherit that variable, so
    ``CLAUDE_PLUGIN_DATA`` is accepted directly as the same directory. With
    neither, the core's own default would be ``<project>/.mlview`` — a tool that
    writes into somebody's repository on every edit — so a per-project directory
    under the system temp is used instead.
    """
    for var in ("MLVIEW_DATA_DIR", "CLAUDE_PLUGIN_DATA"):
        raw = (os.environ.get(var) or "").strip()
        if raw:
            return os.path.abspath(raw).replace("\\", "/")
    stem = hashlib.sha1(_key(root).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "mlview-hook-%s" % stem).replace("\\", "/")


def state_file(data_dir: str) -> str:
    return os.path.join(data_dir, "hook-state.json").replace("\\", "/")


def load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path: str, state: Dict[str, Any]) -> None:
    """Best effort. A read-only data directory costs the diff, never the session."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(state, fh, ensure_ascii=False)
    except OSError:
        pass


def project_key(root: str) -> str:
    return hashlib.sha1(_key(root).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------- the analysis
def bootstrap_core() -> None:
    """Put exactly one ``mlview`` on ``sys.path``, the way ``mlview_mcp`` does.

    First match wins: ``<plugin>/vendor``, then the ``analyzer/src`` dev tree.
    ``<plugin>/server`` joins it too, because ``mlview_workspace`` is what owns
    the cache the MCP tools read and this hook must use *that* one.
    """
    for candidate in (os.path.join(_PLUGIN_ROOT, "vendor"),
                      os.path.join(_REPO_ROOT, "analyzer", "src")):
        if os.path.isdir(os.path.join(candidate, "mlview")):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            break
    if _SERVER_DIR not in sys.path:
        sys.path.insert(0, _SERVER_DIR)


def analyze(root: str, include_notebooks: bool) -> Optional[Dict[str, Any]]:
    """The project's graph, through the MCP tools' own cache. None on any failure.

    Two directories, and neither may be the project. ``MLVIEW_DATA_DIR`` holds the
    graph document and its signature sidecar, and is deliberately the one the MCP
    tools use so this run warms what they read. ``MLVIEW_CACHE_DIR`` holds the
    per-file parse cache (CONTRACTS 11.28), whose default is
    ``<workspace>/.mlview/cache`` — measured creating ``.mlview/`` inside a test
    project on the first hook run, which is exactly the "never writes to the
    project" clause being broken. Both are ``setdefault``, so a user who has named
    either one keeps it.

    The cache directory is not computed here: ``mlview_workspace.shared_cache_dir()``
    points it at ``<MLVIEW_DATA_DIR>/cache``, and it is the same context the MCP
    server's own analyses run inside. This hook used to invent ``<data>/hook-cache``
    for itself, which kept the write out of the repository but left the two halves
    reading *different* parse caches — so the "warms the cache the tools then read"
    claim (11.41 C3) covered only the graph document. One function, one directory,
    actually shared. Scoped rather than exported into the environment for good,
    because the variable is read during the analysis and by nothing else.
    """
    data = hook_data_dir(root)
    os.environ["MLVIEW_PROJECT_DIR"] = root
    os.environ.setdefault("MLVIEW_DATA_DIR", data)
    bootstrap_core()
    try:
        # noqa: PLC0415 - both imports have to follow the bootstrap
        from mlview_workspace import load_graph, shared_cache_dir

        with shared_cache_dir():
            loaded = load_graph(root, include_notebooks=include_notebooks)
    except Exception:  # a broken core is not a reason to disturb the session
        return None
    graph = loaded.get("graph") if isinstance(loaded, dict) else None
    return graph if isinstance(graph, dict) else None


def analyze_within_budget(
    root: str, include_notebooks: bool, budget: float = BUDGET_SECONDS
) -> Optional[Dict[str, Any]]:
    """:func:`analyze` on a worker thread, abandoned when the budget expires.

    The worker is a daemon, so a run that overshoots is simply left behind when
    the process exits. That cannot corrupt the shared cache: ``load_graph``
    writes ``graph.json`` first and its ``.sig`` sidecar afterwards, so a
    half-written document is one whose sidecar does not match, and the next
    reader re-analyzes instead of trusting it.
    """
    result: List[Optional[Dict[str, Any]]] = [None]

    def worker() -> None:
        result[0] = analyze(root, include_notebooks)

    thread = threading.Thread(target=worker, name="mlview-hook", daemon=True)
    thread.start()
    thread.join(budget)
    if thread.is_alive():
        return None
    return result[0]


# -------------------------------------------------------------------------- the diff
def publishable(issue: Dict[str, Any]) -> bool:
    if issue.get("suppressed"):
        return False
    try:
        return float(issue.get("confidence", 0.0)) >= MIN_CONFIDENCE
    except (TypeError, ValueError):
        return False


def issue_rows(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues = graph.get("issues")
    return [i for i in issues if isinstance(i, dict) and publishable(i)] if isinstance(issues, list) else []


def issue_key(issue: Dict[str, Any]) -> str:
    """``CODE|file`` — the identity that survives a line moving underneath it."""
    loc = issue.get("loc") if isinstance(issue.get("loc"), dict) else {}
    return "%s|%s" % (issue.get("code", "?"), loc.get("file", "?"))


def diff_issues(
    current: Sequence[Dict[str, Any]], previous_ids: Sequence[str], previous_keys: Sequence[str]
) -> Tuple[List[Dict[str, Any]], int, int]:
    """``(rows worth printing, re-anchored count, resolved count)``.

    ``rows`` are the findings whose id is new **and** whose ``(code, file)`` pair
    is new. The rest of the new ids are the same finding re-anchored after the
    edit shifted its line, which is a fact about content addressing rather than
    about the code, and is counted instead of printed.
    """
    seen_ids = set(previous_ids)
    seen_keys = set(previous_keys)
    new = [i for i in current if str(i.get("id")) not in seen_ids]
    rows = [i for i in new if issue_key(i) not in seen_keys]
    resolved = len(seen_ids - {str(i.get("id")) for i in current})
    return rows, len(new) - len(rows), resolved


def rank(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda i: (
            _SEVERITY_ORDER.get(str(i.get("severity")), 3),
            -float(i.get("confidence") or 0.0),
            str(i.get("code")),
        ),
    )


def format_row(issue: Dict[str, Any]) -> str:
    loc = issue.get("loc") if isinstance(issue.get("loc"), dict) else {}
    where = "%s:%s" % (loc.get("file", "?"), loc.get("line", "?"))
    return "  [%s] %s %s - %s" % (
        str(issue.get("severity", "?")).upper(),
        issue.get("code", "?"),
        where,
        issue.get("title", "").strip(),
    )


def coverage_line(graph: Dict[str, Any]) -> Optional[str]:
    """One line naming what the run could NOT look at, or None when it saw everything.

    The roadmap's standing criterion applies to a hook as much as to a rule: a
    hook that says "no new findings" about a run that skipped three notebooks has
    reported a clean bill of health for code it never read.
    """
    notes: List[str] = []
    workspace = graph.get("workspace") if isinstance(graph.get("workspace"), dict) else {}
    skipped = workspace.get("notebooksSkipped") or 0
    failed = workspace.get("filesFailed") or 0
    if isinstance(skipped, int) and skipped > 0:
        notes.append("%d notebook(s) not analyzed" % skipped)
    if isinstance(failed, int) and failed > 0:
        notes.append("%d file(s) failed to parse" % failed)
    stats = graph.get("stats") if isinstance(graph.get("stats"), dict) else {}
    if stats.get("truncated"):
        notes.append("the graph was truncated at the node cap")
    if not notes:
        return None
    return "  MLView could not see everything here: %s." % "; ".join(notes)


def build_context(
    event: str,
    rows: Sequence[Dict[str, Any]],
    reanchored: int,
    resolved: int,
    total: int,
    graph: Dict[str, Any],
) -> Optional[str]:
    """The ``additionalContext`` body, or None when there is nothing worth saying."""
    if not rows:
        return None
    ranked = rank(rows)
    shown = ranked[:MAX_ROWS]
    if event == "Stop":
        head = "MLView: %d new finding(s) since the last summary" % len(ranked)
        if resolved:
            head += ", %d resolved" % resolved
        head += "."
    else:
        head = "MLView: that edit added %d finding(s)." % len(ranked)
    lines = [head]
    lines.extend(format_row(issue) for issue in shown)
    if len(ranked) > len(shown):
        lines.append("  ... and %d more." % (len(ranked) - len(shown)))
    if reanchored:
        lines.append(
            "  (%d existing finding(s) moved line and are not repeated here.)" % reanchored
        )
    coverage = coverage_line(graph)
    if coverage:
        lines.append(coverage)
    lines.append(
        "  %d finding(s) in the project in total - call mlview_issues, or run "
        "/mlview-issues, for the ranked list." % total
    )
    return "\n".join(lines)


def emit(event: str, context: str, stream: Any = None) -> None:
    """The one thing this process ever prints: a hook JSON object on stdout.

    Claude Code parses stdout as JSON when it starts with ``{``; anything else on
    a PostToolUse or Stop hook goes to the debug log and is never seen.
    """
    payload = {
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": context}
    }
    out = sys.stdout if stream is None else stream
    out.write(json.dumps(payload, ensure_ascii=False))
    out.write("\n")
    out.flush()


# ------------------------------------------------------------------------ the driver
def run_hook(event: str, payload: Dict[str, Any], stream: Any = None) -> int:
    """The whole body of both hooks. Always returns 0 — this never blocks anything."""
    if not hook_enabled(event):
        return 0
    if event == "Stop" and payload.get("stop_hook_active"):
        # Already inside a stop-hook continuation; speaking again risks a loop.
        return 0
    root = project_dir(payload)
    if not root:
        return 0
    if event == "PostToolUse" and not relevant_paths(payload, root):
        return 0

    data_dir = hook_data_dir(root)
    path = state_file(data_dir)
    state = load_state(path)
    slot = "stop" if event == "Stop" else "post"
    project = project_key(root)
    remembered = state.get(project) if isinstance(state.get(project), dict) else {}
    previous = remembered.get(slot) if isinstance(remembered.get(slot), dict) else {}

    graph = analyze_within_budget(root, notebooks_enabled(root))
    if graph is None:
        return 0  # over budget, or the core is unusable: say nothing at all

    current = issue_rows(graph)
    rows, reanchored, resolved = diff_issues(
        current,
        previous.get("ids") if isinstance(previous.get("ids"), list) else [],
        previous.get("keys") if isinstance(previous.get("keys"), list) else [],
    )
    first_run = not previous
    remembered[slot] = {
        "ids": sorted({str(i.get("id")) for i in current}),
        "keys": sorted({issue_key(i) for i in current}),
    }
    state[project] = remembered
    save_state(path, state)
    if first_run:
        # The first run has nothing to diff against; every finding would look new.
        # Warming the cache is the whole value of that run.
        return 0
    context = build_context(event, rows, reanchored, resolved, len(current), graph)
    if context:
        emit(event, context, stream)
    return 0


def main(event: str, argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for both scripts. Any unexpected failure is still exit 0."""
    try:
        return run_hook(event, read_payload(sys.stdin))
    except Exception as exc:  # pragma: no cover - the belt beyond the braces
        if os.environ.get("MLVIEW_HOOK_DEBUG"):
            print("mlview-hook: %s" % exc, file=sys.stderr)
        return 0
