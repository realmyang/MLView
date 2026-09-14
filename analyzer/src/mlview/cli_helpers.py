"""Request shaping and payload writing for `python -m mlview`.

Everything between argparse and a command: the progress sink, `AnalyzeOptions`,
the `--scope` selector, the `--fail-on` verdict, and the one function that
decides what lands on stdout and what lands on disk. Split out of `cli.py`,
which is now the command table alone.

**stdout carries only the requested payload** (CONTRACTS section 3): every log,
warning and progress line written from here goes to stderr.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Sequence

from .adopt import cli_glue
from .core.graph import SEVERITY_RANK
from .core.pipeline import DEFAULT_RELEVANCE, AnalyzeOptions
from .core.project import Scope, ScopeError, parse_scope, project
from .core.relevance import DEFAULT_HOPS
from .emit import html_out, json_out
from .emit.text_out import write_stderr, write_stdout_bytes
from .ir.build_ir import DEFAULT_DATAFLOW

#: The underscore spellings are deliberate: `cli.py` calls these by the names
#: they had before the split, so the command table reads exactly as it did.
__all__ = ["_progress_sink", "_options", "_scope_from_args", "_apply_scope",
           "_reject_reprojection", "_fail_on_hit", "_adopt_usage_error",
           "_emit_sarif", "_open_path", "_emit_payload"]


# ----------------------------------------------------------------- helpers
def _progress_sink(args):
    """H3: `--progress-json` is the only thing that opens the stderr sink; the
    library itself never writes a byte of progress on its own."""
    if not getattr(args, "progress_json", False):
        return None
    from .core.progress import ProgressWriter
    return ProgressWriter()


def _options(args, paths: Sequence[str]) -> AnalyzeOptions:
    return AnalyzeOptions(
        paths=tuple(paths),
        include=tuple(getattr(args, "include", ()) or ()),
        exclude=tuple(getattr(args, "exclude", ()) or ()),
        max_files=int(getattr(args, "max_files", 500)),
        max_nodes=int(getattr(args, "max_nodes", 400)),
        framework=getattr(args, "framework", "auto"),
        min_severity=getattr(args, "min_severity", "low"),
        min_confidence=float(getattr(args, "min_confidence", 0.0)),
        config_path=getattr(args, "config_path", None),
        strict=bool(getattr(args, "strict", False)),
        progress=_progress_sink(args),
        # PERF-03 / CACHE. `getattr` defaults keep every command that does not
        # declare the flags on exactly the behaviour it had.
        relevance=getattr(args, "relevance", DEFAULT_RELEVANCE),
        relevance_hops=int(getattr(args, "relevance_hops", DEFAULT_HOPS)),
        cache=False if getattr(args, "no_cache", False) else None,
        # NB. `.mlview.toml`'s `[paths] notebooks` is read inside `run()`, so a
        # command without the flag still honours a checked-in opt-in.
        include_notebooks=bool(getattr(args, "include_notebooks", False)),
        # DATAFLOW-IP. `local` is this release's default and the `getattr`
        # default, so a command that does not declare the flag - and every host
        # that builds `AnalyzeOptions` itself - keeps today's analysis exactly.
        dataflow=getattr(args, "dataflow", DEFAULT_DATAFLOW))


def _scope_from_args(args) -> Optional[Scope]:
    """Parse `--scope`/`--depth` **before** the analysis runs, so an invalid
    selector costs nothing and never reaches stdout (CONTRACTS 11.5)."""
    spec = getattr(args, "scope", None)
    depth = getattr(args, "depth", None)
    if spec is None and depth is None:
        return None
    return parse_scope(spec, depth)


def _apply_scope(doc: Dict[str, Any], scope: Optional[Scope]) -> Dict[str, Any]:
    """The projection. `all` (and no scope at all) is the identity, and the
    document then carries no `view` - which is what keeps an unscoped run
    byte-identical to what it emitted before this feature existed."""
    if scope is None or scope.is_all:
        return doc
    return project(doc, scope)


def _reject_reprojection(doc: Dict[str, Any], scope: Optional[Scope],
                         source: str) -> None:
    """Refuse `--scope` on a document that is **already** a projection.

    A document carrying `view` is a projection (CONTRACTS 11.4 invariant 9),
    and `view.of` is by definition taken from the **unprojected** document
    (11.3). Projecting it a second time would rebuild `of` from the projection
    itself, so the payload would say `workspace.filesAnalyzed: 5` and
    `view.of.nodes: 10` in the same breath - exactly the claim the `View`
    contract forbids ("no surface can claim the project is smaller than it
    is"). Only `render --graph FILE` can reach this, because it is the one
    command that scopes a document it did not build; the refusal follows the
    `--scope` + `--demo` precedent in `_cmd_analyze`: `bad_selector`, exit 1,
    stdout untouched.

    `--scope all` (and no scope at all) is not a projection, so rendering an
    already-projected file stays legal - that is the documented two-step flow.
    """
    view = doc.get("view")
    if scope is None or scope.is_all or not isinstance(view, dict):
        return
    of_nodes = (view.get("of") or {}).get("nodes", 0)
    raise ScopeError(
        "bad_selector", scope.spec, (),
        "%s is already a projection of scope %s (%d of %d nodes); scoping it "
        "again would recompute view.of from the projection and report the "
        "project as smaller than it is. Scope the full graph instead: "
        "mlview analyze <path> --scope %s, or render the unprojected document."
        % (source, view.get("scope", "?"), (doc.get("stats") or {}).get("nodes", 0),
           of_nodes, scope.spec))


def _fail_on_hit(doc: Dict[str, Any], threshold: str) -> bool:
    """CI-ADOPT: a baselined finding does not trip the gate - that is the whole
    point of the ratchet - and `--changed-only` has already removed `existing`
    findings from `issues[]` by the time this runs."""
    if threshold in (None, "none"):
        return False
    floor = SEVERITY_RANK[threshold]
    return any(SEVERITY_RANK.get(i["severity"], 0) >= floor
               for i in doc.get("issues", [])
               if not i.get("suppressed") and not i.get("baselined"))


def _adopt_usage_error(args) -> Optional[str]:
    """Flag-combination errors for the CI-ADOPT surface (exit 1, clean stdout)."""
    error = cli_glue.validate_args(args)
    if error:
        return error
    if getattr(args, "sarif_out", None) == "-":
        json_target = getattr(args, "json_out", None)
        claimed = (json_target == "-") if isinstance(json_target, str) else bool(json_target)
        if claimed:
            return ("--sarif - and --json both write to stdout; send one of them "
                    "to a file.")
    return None


def _emit_sarif(doc: Dict[str, Any], args) -> bool:
    """Write `--sarif`. Returns True when the SARIF went to **stdout**, which
    is what tells the caller not to print a second payload after it."""
    target = getattr(args, "sarif_out", None)
    if not target:
        return False
    path, payload = cli_glue.write_sarif_output(doc, target)
    if payload:
        write_stdout_bytes(payload)
        return True
    write_stderr("mlview: wrote %s" % path)
    return False


def _open_path(path: str) -> None:
    try:
        if os.name == "nt" and hasattr(os, "startfile"):
            os.startfile(path)  # noqa: S606 - opening a file we just wrote
        else:  # pragma: no cover - non-Windows
            import webbrowser
            webbrowser.open("file:///" + path.lstrip("/"))
    except Exception as exc:  # pragma: no cover - environment dependent
        write_stderr("mlview: could not open %s: %s" % (path, exc))


def _emit_payload(doc: Dict[str, Any], args, full: Optional[Dict[str, Any]] = None,
                  scope: Optional[Scope] = None) -> bool:
    """Write --json / --html outputs. Returns True when stdout carried JSON.

    `--json` gets the projected document; `--html` embeds the **full** one and
    opens at the scope through the root-element attributes (CONTRACTS 11.8).
    """
    json_target = getattr(args, "json_out", None)
    html_target = getattr(args, "html_out", None)
    wrote_stdout = False
    if json_target == "-":
        write_stdout_bytes(json_out.dump_bytes(doc))
        wrote_stdout = True
    elif json_target:
        path = json_out.write_json(doc, json_target)
        write_stderr("mlview: wrote %s" % path)
    if html_target:
        scoped = scope is not None and not scope.is_all
        path = html_out.write_html(full if full is not None else doc, html_target,
                                   scope=scope.spec if scoped else None,
                                   depth=scope.depth if scoped else None)
        write_stderr("mlview: wrote %s" % path)
        if getattr(args, "open_report", False):
            _open_path(path)
    return wrote_stdout
