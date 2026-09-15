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

A third pair, ``framework_suppression`` / ``note_framework_suppression``, is the
other half of the first: ``normalize_framework`` refuses a spelling no rule
declares, and these say out loud what an ACCEPTED one cost this workspace, so a
filtered finding list can never be read as a clean one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview_notes import (  # the reader of the note written below
    FRAMEWORK_FILTER_PREFIX,
    is_framework_filter_note,
)

log = logging.getLogger("mlview.mcp")

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SERVER_DIR)
_REPO_ROOT = os.path.dirname(_PLUGIN_ROOT)

__all__ = [
    "project_dir", "named_data_dir", "data_dir", "cache_dir", "shared_cache_dir",
    "resolve_path", "resolve_out",
    "FRAMEWORKS", "normalize_framework",
    "framework_suppression", "note_framework_suppression",
    "analyzer_identity", "file_signature", "graph_file_for",
    "load_graph", "load_graph_or_file", "load_attributed",
    "read_source", "rule_doc", "rule_spec", "rule_codes", "RULE_DOC_ROOTS",
]


#: Still used by `analyzer_identity`'s walk. The signature's own prune set
#: moved into `mlview.core.cache`, which uses `ingest.discover.ALWAYS_PRUNE` -
#: the set that decides what is analyzed in the first place, and therefore the
#: only correct answer to "what should a signature cover".
_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    "site-packages", "build", "dist", ".mypy_cache", ".pytest_cache", ".mlview",
    ".tox", ".idea", ".vscode",
}

# In-process memo: (resolved path, framework, maxNodes, signature) -> (graph, path)
_CACHE: Dict[Any, Any] = {}


# --------------------------------------------------------------- argument guards
#: The six values `--framework` accepts (`analyzer/src/mlview/cli_parser.py`, the
#: argparse `choices` on `analyze`). The MCP boundary holds the same vocabulary
#: because of what the value DOES: `mlview.rules.registry._applies` keeps a rule
#: that declares frameworks only when `framework_filter in spec.frameworks`, so a
#: name no rule declares disables every framework-specific rule at once instead of
#: failing. Measured on `samples/vision_pipeline` before this guard existed:
#: `framework="auto"` -> 59 nodes, 15 findings, 5 high; `framework="pytorch"`,
#: `"TORCH"` or `"Lightning"` -> 52 nodes, 1 finding, 0 high, with
#: `frameworks: ["torch", "sklearn", ...]` still reported in the same payload and
#: no note anywhere in it.
FRAMEWORKS = ("auto", "torch", "sklearn", "keras", "hf", "lightning")


def normalize_framework(framework: Optional[str]) -> str:
    """The canonical spelling of a ``framework`` argument, or ``ValueError``.

    Case and surrounding whitespace are folded first — ``"TORCH"`` and ``" torch "``
    name the same extractor filter, and this boundary already folds ``format`` and
    upper-cases ``code`` the same way. A missing or empty value is ``"auto"``,
    which is what every caller's default already meant.

    Anything else is a caller mistake the model can fix by retrying, so it raises
    ``ValueError`` — which ``mlview_mcp.visible_errors`` turns into a ``ToolError``
    whose text reaches the model verbatim. Analyzing anyway is the one behaviour
    ruled out: a filter that names no extractor must never quietly return a
    shorter finding list, because the caller cannot tell that answer from a clean
    project. This is the MCP half of the CLI's argparse ``choices``.
    """
    if framework is None:
        return "auto"
    name = str(framework).strip().lower()
    if not name:
        return "auto"
    if name not in FRAMEWORKS:
        raise ValueError(
            "framework=%r is not valid; accepted values are %s. An unrecognized "
            "name matches no rule's declared framework, so it would silently drop "
            "every framework-specific finding instead of failing; omit the "
            "argument to analyze with every extractor."
            % (framework, ", ".join(repr(f) for f in FRAMEWORKS))
        )
    return name


#: How many detected framework names the diagnostic below spells out. The rule
#: codes are NOT in its sentence: every reader of the message shows the ``codes``
#: field beside it — `webview/src/ui/chrome.ts` appends them to the chip,
#: `mlview_notes.coverage_notes` carries them as a field and `coverage_note` puts
#: them in the payload's note — so repeating them inline only made the chip say
#: the same three codes twice. Bounding the prose is also what keeps the message
#: under ``mlview_notes.MAX_MESSAGE`` (400), so the coverage block never clips a
#: sentence mid-word: the widest case measured (nine frameworks detected, the
#: `lightning` filter) is 301 characters.
FRAMEWORKS_IN_MESSAGE = 6


def _rule_applies(
    declared: Sequence[str], detected: Sequence[str], framework_filter: str
) -> bool:
    """``mlview.rules.registry._applies``, mirrored on a spec's own fields.

    Mirrored rather than called because the core's helper is private: a rename
    there would turn a runtime call into an ``AttributeError`` raised inside a
    tool call — a crash in the one function whose whole job is to stop a silent
    answer. The copy cannot drift unnoticed either, because
    ``tests/test_framework_suppression.py`` cross-checks it against
    ``registry._applies`` for every registered rule against every accepted
    ``--framework`` value and several detected-framework sets, so a change to the
    core's filter fails the plugin suite loudly instead of skewing a count.
    """
    if not declared:
        return True
    declared_set = set(declared)
    if framework_filter and framework_filter != "auto":
        return framework_filter in declared_set
    detected_set = set(detected)
    if not detected_set:
        return True
    return bool(declared_set & detected_set) or "all" in declared_set


def framework_suppression(
    graph: Optional[Dict[str, Any]], framework: Optional[str]
) -> Optional[Dict[str, Any]]:
    """The ``framework_suppressed`` diagnostic a non-``auto`` filter owes, or ``None``.

    :func:`normalize_framework` states the invariant this completes: *a filter
    that names no extractor must never quietly return a shorter finding list,
    because the caller cannot tell that answer from a clean project.* Rejecting an
    unknown spelling covered the typo half. The other half is a VALID name that
    happens to disable rules on THIS workspace — measured on
    ``analyzer/tests/accuracy/corpus/infra_tf_custom_loop_bad``, whose document
    advertises ``frameworks: ["torch", "numpy", "keras", "tf"]``, so narrowing to
    ``torch`` is the obvious next move:

        framework="auto"  -> MLV121 (high), MLV601 (low), diagnostics []
        framework="torch" -> MLV601 (low),                diagnostics []

    A high-severity finding disappeared and nothing in the payload said why. The
    diagnostic below is what says why: which rules the filter disabled, how many,
    and that the shorter list is a filtered answer rather than a clean one. It
    uses the kind ``contracts/graph.schema.json`` already reserves for exactly
    this ("For framework_suppressed: which rules were not applied"), so the
    document stays schema-valid, no new vocabulary is invented, and the webview
    chip renders the message verbatim (`webview/src/ui/chrome.ts`). The analyzer
    writes that kind too, for the R3.8 absence gate — a DIFFERENT statement, since
    those rules ran and were de-rated — which is why
    ``mlview_notes.is_framework_filter_note`` separates the two everywhere they
    are read.

    A rule counts as suppressed only when it WOULD have run under ``auto`` on this
    workspace: a keras rule on a torch-only project was never going to fire, and
    counting it would inflate the number into noise. ``None`` means the filter
    cost this workspace nothing, which is a real answer and not a caveat.
    """
    name = normalize_framework(framework)
    if name == "auto":
        return None
    detected = [
        f for f in ((graph or {}).get("workspace") or {}).get("frameworks") or []
        if isinstance(f, str)
    ]
    try:
        from mlview.rules import registry  # noqa: PLC0415 - after the bootstrap

        registry.discover_rules()
        specs = list(registry.all_rules())
    except Exception as exc:  # a registry problem must not sink the tool
        log.warning("rule registry unavailable: %s", exc)
        # Silence is the one answer ruled out here: the filter DID narrow the run,
        # and the caller cannot see that from the finding list. Say so without the
        # codes rather than say nothing.
        return {
            "kind": "framework_suppressed",
            "message": (
                "%s%s ran only the rules that declare it; the rule registry could "
                "not be read, so this run cannot name which rules it disabled. "
                "This finding list is filtered, not a clean bill of health - omit "
                'framework (or pass "auto") to run every rule.'
                % (FRAMEWORK_FILTER_PREFIX, name)
            ),
        }

    codes = sorted(
        spec.code for spec in specs
        if spec.enabled
        and _rule_applies(spec.frameworks, detected, "auto")
        and not _rule_applies(spec.frameworks, detected, name)
    )
    if not codes:
        return None
    seen = ", ".join(detected[:FRAMEWORKS_IN_MESSAGE]) or "none"
    return {
        "kind": "framework_suppressed",
        "message": (
            "%s%s ran only the rules that declare it, so %d framework-specific "
            "rule(s) did not run here. Detected frameworks: %s. A shorter finding "
            "list is a filtered answer, not a clean bill of health - omit "
            'framework (or pass "auto") to run every rule.'
            % (FRAMEWORK_FILTER_PREFIX, name, len(codes), seen)
        ),
        "codes": codes,
        "count": len(codes),
    }


def note_framework_suppression(
    graph: Optional[Dict[str, Any]], framework: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Add :func:`framework_suppression` to ``graph["diagnostics"]``, in place.

    Applied on EVERY path out of :func:`load_graph`, not only after a fresh
    analysis, and idempotent because of it — idempotent on ITS OWN note:
    ``mlview/rules/context.py`` emits the same ``kind`` for the R3.8 absence gate,
    and most Keras, Lightning and HF workspaces carry one, so "a diagnostic of
    this kind is already here" would have meant "say nothing" exactly where the
    filter had the most to hide. A ``graph.json`` written by an older
    plugin build carries no such diagnostic, and ``analyzer_identity()`` — the
    thing that decides whether a sidecar is stale — hashes the ANALYZER, not this
    server, so that document is still served. Re-deriving the note on the way out
    is what stops the fix from depending on a cache miss.
    """
    if not isinstance(graph, dict):
        return None
    diagnostics = graph.get("diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = []
        graph["diagnostics"] = diagnostics
    for entry in diagnostics:
        if is_framework_filter_note(entry):
            return entry
    note = framework_suppression(graph, framework)
    if note is not None:
        diagnostics.append(note)
    return note


# ---- path handling: `mlview_storage`, re-exported here -------------------------
# Moved out when C8's cache wiring pushed this module past the line ceiling.
# Re-exported unchanged: `mlview_payloads`, `mlview_mcp`, `mlview_views` and four
# test modules already import these names from here.
from mlview_storage import (  # noqa: E402  (after the core bootstrap, like the rest)
    _contains,
    _norm,
    cache_dir,
    data_dir,
    named_data_dir,
    project_dir,
    resolve_out,
    resolve_path,
    shared_cache_dir,
)


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
    """A content signature for a file or a tree — **the core's implementation**.

    CACHE (CONTRACTS 11.28): there is exactly one of these now, in
    ``mlview.core.cache``, and this is a re-export so the server and the CLI can
    never disagree about whether a tree changed. The old local copy hashed each
    file's **mtime and size**; that key moved when a ``git checkout`` restored
    content it had already seen, and — the direction that actually hurts — could
    fail to move on a filesystem with coarse timestamps, which is how a stale
    document reaches a caller. The replacement hashes the bytes, prunes exactly
    what ``ingest.discover`` prunes, and stops at the same 2000-file bound.

    Kept as a wrapper rather than a bare import so the docstring above stays
    with the name the rest of this module and its tests use.
    """
    from mlview.core.cache import file_signature as _core_file_signature

    return _core_file_signature(path)


def graph_file_for(path: str) -> str:
    """`<data>/graph.json` for the project root, `graph-<hash>.json` for a subpath."""
    base = data_dir()
    if _norm(path) == project_dir():
        return os.path.join(base, "graph.json").replace("\\", "/")
    stem = hashlib.sha1(_norm(path).encode("utf-8")).hexdigest()[:8]
    return os.path.join(base, "graph-%s.json" % stem).replace("\\", "/")


# ---------------------------------------------------------------------- analysis
def load_graph(
    path: Optional[str], framework: str = "auto", max_nodes: int = 400,
    include_notebooks: bool = False,
) -> Dict[str, Any]:
    """Analyze (or reuse a cached analysis of) ``path``; also writes graph.json.

    Returns ``{"graph": <document>, "graphPath": <abs path>, "cached": bool}``.

    The key is ``(resolved, framework, maxNodes, includeNotebooks, signature)``
    and never the scope (CONTRACTS 11.10): ``project()`` is applied to the cached
    dict, so widening is free. The *disk* half of the cache additionally records
    ``analyzer_identity()``, because a file that outlives the process also
    outlives the build that wrote it.

    Every path out of here — memo, sidecar, fresh analysis — goes through
    ``note_framework_suppression`` first, so a non-``auto`` filter always carries
    the ``framework_suppressed`` diagnostic naming the rules it disabled.

    NB. ``include_notebooks`` is part of the key, not a filter applied afterwards:
    the same sources analyzed with and without it are two different documents, and
    serving the notebook-free one to a caller that asked for notebooks would report
    a clean bill of health for code the run never read. Sidecars written before the
    flag existed carry a shorter key and simply miss, which costs one analysis.
    """
    # Before the cache key, so `"TORCH"` and `"torch"` are one entry and an
    # unknown name never reaches `AnalyzeOptions` (nor a sidecar on disk).
    framework = normalize_framework(framework)
    resolved = resolve_path(path)
    signature = file_signature(resolved)
    key = (resolved, framework, int(max_nodes), bool(include_notebooks),
           signature)
    graph_path = graph_file_for(resolved)

    cached = _CACHE.get(key)
    if cached is not None and os.path.exists(graph_path):
        # Idempotent, so a memo that already carries the note is untouched.
        note_framework_suppression(cached, framework)
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
                stored.get("key") == list(key[:4])
                and stored.get("signature") == signature
                and stored.get("analyzer") == analyzer
            ):
                with open(graph_path, "r", encoding="utf-8") as fh:
                    graph = json.load(fh)
                # A document written by an older build of THIS server carries no
                # framework note, and the sidecar's `analyzer` field cannot see
                # that: it fingerprints the analyzer, not the plugin.
                note_framework_suppression(graph, framework)
                _CACHE[key] = graph
                return {"graph": graph, "graphPath": graph_path, "cached": True}
        except (OSError, ValueError):
            log.warning("ignoring unreadable graph cache at %s", graph_path)

    log.info("analyzing %s (framework=%s maxNodes=%s includeNotebooks=%s)",
             resolved, framework, max_nodes, bool(include_notebooks))
    with shared_cache_dir():
        graph = analyze_to_dict(
            AnalyzeOptions(
                paths=(resolved,),
                framework=framework,
                max_nodes=int(max_nodes),
                include_notebooks=bool(include_notebooks),
            )
        )
    note_framework_suppression(graph, framework)
    _CACHE[key] = graph
    try:
        os.makedirs(os.path.dirname(graph_path), exist_ok=True)
        with open(graph_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(graph, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        with open(sidecar, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(
                {"key": list(key[:4]), "signature": signature, "analyzer": analyzer}, fh
            )
    except OSError as exc:  # a read-only data dir must not fail the tool
        log.warning("could not write %s: %s", graph_path, exc)
    return {"graph": graph, "graphPath": graph_path, "cached": False}


def load_attributed(
    path: Optional[str],
    changed_since: Optional[str] = None,
    baseline: Optional[str] = None,
    framework: str = "auto",
    max_nodes: int = 400,
    include_notebooks: bool = False,
) -> Dict[str, Any]:
    """CI-ADOPT: analyze the whole project, then attribute against a diff or a baseline.

    **Never cached, and deliberately so.** Every other analysis in this server is
    keyed on `(path, framework, maxNodes, file signature)` because the document is a
    function of the sources. An attributed document is not: `git checkout` moves HEAD
    without touching one byte of any file, and a baseline file can be rewritten
    underneath us. Serving a cached attribution would answer "what did this PR
    introduce" with yesterday's diff, which is worse than not answering.

    The attributed document is written beside the plain one as
    `<graph>.attributed.json` rather than over it, so `mlview_analyze`'s `graphPath`
    keeps pointing at the FULL, unattributed graph the rest of the tools read.

    `include_notebooks` is honoured here exactly as it is in `load_graph` (HOST-5).
    It used to stop at the caller: `mlview_issues` dropped the flag whenever
    `changedSince` or `baseline` was passed, so the two together produced a run that
    had opened no notebook and said nothing about it. Attribution never required
    that — the CLI takes `--include-notebooks --changed-since` together — and where
    attribution genuinely cannot carry a notebook finding (its location names a
    generated module git does not track), `mlview_adopt` returns a note saying so
    rather than an unexplained empty list.
    """
    if _SERVER_DIR not in sys.path:
        sys.path.insert(0, _SERVER_DIR)
    import mlview_adopt  # noqa: PLC0415 - sibling module, after the sys.path bootstrap

    framework = normalize_framework(framework)
    resolved = resolve_path(path)
    log.info("analyzing %s with attribution (changedSince=%s baseline=%s "
             "includeNotebooks=%s)", resolved, changed_since, baseline,
             bool(include_notebooks))
    with shared_cache_dir():
        graph, notes = mlview_adopt.analyze_attributed(
            resolved, framework=framework, max_nodes=int(max_nodes),
            changed_since=changed_since, baseline=baseline,
            include_notebooks=bool(include_notebooks),
        )
    note_framework_suppression(graph, framework)
    plain = graph_file_for(resolved)
    graph_path = plain[: -len(".json")] + ".attributed.json" if plain.endswith(".json") else plain
    try:
        os.makedirs(os.path.dirname(graph_path), exist_ok=True)
        with open(graph_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(graph, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
    except OSError as exc:  # a read-only data dir must not fail the tool
        log.warning("could not write %s: %s", graph_path, exc)
    return {"graph": graph, "graphPath": graph_path, "cached": False, "notes": notes}


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


def rule_codes() -> Optional[frozenset]:
    """Every code the registry knows, or ``None`` when the registry cannot say.

    `mlview_issues` passes it so that `code=["NOPE"]` (no such rule — a typo the
    caller can fix) is distinguishable from `code=["MLV601"]` (a real rule that
    found nothing here — a fact about the project). Both answer with an empty
    list today, and an empty list from a listing tool is the shape a model reads
    as "clean".

    ``None`` rather than an empty set on failure, so a registry that could not be
    imported cannot be mistaken for "no rule exists" and turn every code into a
    typo in the note.
    """
    try:
        from mlview.rules import registry  # noqa: PLC0415 - after the bootstrap

        registry.discover_rules()
        return frozenset(spec.code.upper() for spec in registry.all_rules())
    except Exception as exc:  # a registry problem must not sink the tool
        log.warning("rule registry unavailable: %s", exc)
        return None

