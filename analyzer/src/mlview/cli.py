"""The `python -m mlview` command line (CONTRACTS section 3).

Both hosts call exactly this. **stdout carries only the requested payload**;
every log, warning and progress line goes to stderr.

Exit codes: 0 ok · 1 usage/IO · 2 --fail-on exceeded · 3 internal · 4 nothing
analyzable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import api
from .core.graph import SEVERITY_RANK
from .core.pipeline import AnalyzeOptions
from .core.project import Scope, ScopeError, parse_scope, project, scope_catalog
from .emit import html_out, json_out, mermaid_out, scope_out
from .emit.text_out import write_stderr, write_stdout, write_stdout_bytes
from .version import SCHEMA_VERSION, __version__

__all__ = ["main", "build_parser"]

EXIT_OK, EXIT_USAGE, EXIT_FAIL_ON, EXIT_INTERNAL, EXIT_EMPTY = 0, 1, 2, 3, 4
_FORMATS = ("summary", "json", "mermaid", "text")


# ---------------------------------------------------------------- parser
def _add_scope_flags(parser: argparse.ArgumentParser) -> None:
    """`--scope` / `--depth` (CONTRACTS 11.5). Both optional; the defaults
    reproduce today's behaviour exactly.

    `--depth` is taken as text, not `type=int`, so a bad value comes back as
    the contractual `bad_depth` code on stderr instead of argparse's own
    usage error.
    """
    parser.add_argument("--scope", dest="scope", metavar="SPEC", default=None,
                        help="project the graph before emitting: "
                             "unit:|stage:|file:|concern:|node:<target>, or 'all'")
    parser.add_argument("--depth", dest="depth", metavar="N", default=None,
                        help="boundary hops 0..2 (default: 1 for unit/node, "
                             "0 for stage/file/concern)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mlview",
        description="Visualize and audit Python ML pipelines - static analysis only.")
    parser.add_argument("--version", action="store_true",
                        help="print the core version and exit")
    parser.add_argument("--json", dest="version_json", action="store_true",
                        help="with --version: print JSON")
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze", help="analyze a workspace and emit the graph")
    analyze.add_argument("paths", nargs="*", default=[])
    analyze.add_argument("--json", dest="json_out", metavar="FILE|-",
                         help="write the graph JSON ('-' means stdout)")
    analyze.add_argument("--html", dest="html_out", metavar="FILE",
                         help="write a self-contained HTML report")
    analyze.add_argument("--open", dest="open_report", action="store_true")
    analyze.add_argument("--format", dest="fmt", choices=_FORMATS, default="summary")
    analyze.add_argument("--include", action="append", default=[], metavar="GLOB")
    analyze.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    analyze.add_argument("--min-severity", choices=("low", "medium", "high"), default="low")
    analyze.add_argument("--min-confidence", type=float, default=0.0)
    analyze.add_argument("--show-suppressed", action="store_true")
    analyze.add_argument("--max-files", type=int, default=500)
    analyze.add_argument("--max-nodes", type=int, default=400,
                          help="operation-node budget; units and ghost nodes "
                               "are never dropped, so the emitted document may "
                               "hold more nodes than this. Sets stats.truncated.")
    analyze.add_argument("--framework",
                         choices=("auto", "torch", "sklearn", "keras", "hf", "lightning"),
                         default="auto")
    analyze.add_argument("--config", dest="config_path", metavar="FILE")
    analyze.add_argument("--fail-on", choices=("none", "low", "medium", "high"),
                         default="none")
    analyze.add_argument("--strict", action="store_true")
    analyze.add_argument("--demo", action="store_true",
                         help="emit the golden contracts/graph.sample.json")
    analyze.add_argument("--no-color", action="store_true")
    _add_scope_flags(analyze)
    analyze.add_argument("--list-scopes", dest="list_scopes", action="store_true",
                         help="print the scopable-unit catalogue and exit 0")

    issues = sub.add_parser("issues", help="list detected issues")
    issues.add_argument("paths", nargs="*", default=[])
    issues.add_argument("--json", dest="json_out", action="store_true")
    issues.add_argument("--text", dest="text_out", action="store_true")
    issues.add_argument("--min-severity", choices=("low", "medium", "high"), default="low")
    issues.add_argument("--min-confidence", type=float, default=0.0)
    issues.add_argument("--code", default="", help="comma-separated rule codes")
    issues.add_argument("--limit", type=int, default=0)
    issues.add_argument("--max-files", type=int, default=500)
    issues.add_argument("--max-nodes", type=int, default=400,
                          help="operation-node budget; units and ghost nodes "
                               "are never dropped, so the emitted document may "
                               "hold more nodes than this. Sets stats.truncated.")
    issues.add_argument("--include", action="append", default=[], metavar="GLOB")
    issues.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    issues.add_argument("--config", dest="config_path", metavar="FILE")
    issues.add_argument("--show-suppressed", action="store_true")
    issues.add_argument("--fail-on", choices=("none", "low", "medium", "high"),
                        default="none")
    issues.add_argument("--strict", action="store_true")
    issues.add_argument("--no-color", action="store_true")
    _add_scope_flags(issues)

    render = sub.add_parser("render", help="render an existing or fresh graph")
    render.add_argument("paths", nargs="*", default=[])
    render.add_argument("--graph", dest="graph_file", metavar="FILE")
    render.add_argument("--out", dest="out_file", metavar="FILE")
    render.add_argument("--format", dest="fmt", choices=("html", "mermaid", "text"),
                        default="html")
    render.add_argument("--open", dest="open_report", action="store_true")
    render.add_argument("--max-files", type=int, default=500)
    render.add_argument("--max-nodes", type=int, default=400,
                          help="operation-node budget; units and ghost nodes "
                               "are never dropped, so the emitted document may "
                               "hold more nodes than this. Sets stats.truncated.")
    render.add_argument("--config", dest="config_path", metavar="FILE")
    render.add_argument("--no-color", action="store_true")
    _add_scope_flags(render)

    explain = sub.add_parser("explain", help="explain a node id or a rule code")
    explain.add_argument("target")
    explain.add_argument("--graph", dest="graph_file", metavar="FILE")
    explain.add_argument("--json", dest="json_out", action="store_true")

    rules = sub.add_parser("rules", help="list the registered rules")
    rules.add_argument("--list", dest="list_rules", action="store_true")
    rules.add_argument("--json", dest="json_out", action="store_true")
    rules.add_argument("--explain", dest="explain_code", metavar="MLV201")

    sub.add_parser("schema", help="print the MLGraph JSON Schema")
    return parser


# ----------------------------------------------------------------- helpers
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
        strict=bool(getattr(args, "strict", False)))


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
    if threshold in (None, "none"):
        return False
    floor = SEVERITY_RANK[threshold]
    return any(SEVERITY_RANK.get(i["severity"], 0) >= floor
               for i in doc.get("issues", []) if not i.get("suppressed"))


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


# ---------------------------------------------------------------- commands
def _cmd_analyze(args) -> int:
    scope = _scope_from_args(args)          # raises ScopeError -> exit 1, clean stdout
    if getattr(args, "list_scopes", False):
        return _cmd_list_scopes(args, scope)
    if args.demo:
        if scope is not None and not scope.is_all:
            raise ScopeError(
                "bad_selector", scope.spec, (),
                "--demo emits the frozen golden document; it is a fixed artefact "
                "and cannot be projected. Analyze a path instead.")
        doc = api.demo_dict()
        if args.json_out == "-":
            write_stdout_bytes(api.demo_bytes())
        else:
            wrote = _emit_payload(doc, args)
            if not wrote:
                _print_format(doc, args)
        return EXIT_OK

    paths = args.paths or ["."]
    result = api.analyze_full(_options(args, paths))
    full = result.graph.to_dict()
    doc = _apply_scope(full, scope)         # raises ScopeError -> exit 1
    wrote_stdout = _emit_payload(doc, args, full=full, scope=scope)
    if not wrote_stdout:
        _print_format(doc, args)
    note = scope_out.empty_note(doc)
    if note:
        write_stderr(note)
    if result.empty:
        write_stderr("mlview: no analyzable Python files found under %s"
                     % ", ".join(paths))
        return EXIT_EMPTY
    if _fail_on_hit(doc, args.fail_on):
        write_stderr("mlview: --fail-on %s threshold exceeded%s"
                     % (args.fail_on, scope_out.fail_on_suffix(doc)))
        return EXIT_FAIL_ON
    return EXIT_OK


def _cmd_list_scopes(args, scope: Optional[Scope]) -> int:
    """`analyze --list-scopes`: the catalogue **is** the requested payload."""
    if args.json_out or args.html_out or (scope is not None and not scope.is_all):
        write_stderr("mlview: --list-scopes cannot be combined with --json, "
                     "--html or --scope; it is the payload")
        return EXIT_USAGE
    if args.demo:
        doc = api.demo_dict()
    else:
        doc = api.analyze_full(_options(args, args.paths or ["."])).graph.to_dict()
    rows = scope_catalog(doc, limit=0)
    write_stdout(scope_out.render_catalog_json(rows) if args.fmt == "json"
                 else scope_out.render_catalog_text(rows))
    return EXIT_OK


def _print_format(doc: Dict[str, Any], args) -> None:
    fmt = getattr(args, "fmt", "summary")
    if fmt == "json":
        write_stdout(json_out.dumps(doc))
    elif fmt == "mermaid":
        write_stdout(mermaid_out.render_mermaid(doc))
    elif fmt == "text":
        write_stdout(api.render_text(doc))
    else:
        write_stdout(api.render_summary(
            doc, show_suppressed=bool(getattr(args, "show_suppressed", False))))


def _cmd_issues(args) -> int:
    scope = _scope_from_args(args)          # raises ScopeError -> exit 1
    paths = args.paths or ["."]
    result = api.analyze_full(_options(args, paths))
    doc = _apply_scope(result.graph.to_dict(), scope)
    codes = {c.strip().upper() for c in (args.code or "").split(",") if c.strip()}
    issues = [i for i in doc.get("issues", [])
              if (args.show_suppressed or not i.get("suppressed"))
              and (not codes or i["code"] in codes)]
    if args.limit and args.limit > 0:
        issues = issues[:args.limit]
    if args.json_out:
        counts = {"low": 0, "medium": 0, "high": 0}
        for issue in issues:
            counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
        payload = {
            "countBySeverity": counts,
            "suppressedCount": sum(1 for i in doc.get("issues", []) if i.get("suppressed")),
            "issues": issues,
        }
        if isinstance(doc.get("view"), dict):
            payload["scope"] = doc["view"]["scope"]
        write_stdout(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        from .emit.text_out import render_issue_table
        scoped = scope_out.issues_scope_suffix(doc)   # names the denominator
        header = "%d issue(s) in %s%s\n" % (len(issues), doc["workspace"]["root"], scoped)
        write_stdout(header + (render_issue_table(issues) + "\n" if issues
                               else "  none found\n"))
    if result.empty:
        return EXIT_EMPTY
    note = scope_out.empty_note(doc)
    if note:
        write_stderr(note)
    if _fail_on_hit({"issues": issues}, args.fail_on):
        suffix = scope_out.fail_on_suffix(doc)
        if suffix:
            write_stderr("mlview: --fail-on %s threshold exceeded%s"
                         % (args.fail_on, suffix))
        return EXIT_FAIL_ON
    return EXIT_OK


def _cmd_render(args) -> int:
    scope = _scope_from_args(args)          # raises ScopeError -> exit 1
    if args.graph_file:
        try:
            doc = json_out.load_json(args.graph_file)
        except OSError as exc:
            write_stderr("mlview: cannot read %s: %s" % (args.graph_file, exc))
            return EXIT_USAGE
        except ValueError as exc:
            write_stderr("mlview: %s is not valid JSON: %s" % (args.graph_file, exc))
            return EXIT_USAGE
        # A saved document may itself be a projection; re-scoping it would
        # restate project-level truth (CONTRACTS 11.3).
        _reject_reprojection(doc, scope, args.graph_file)
        empty = False
    else:
        result = api.analyze_full(_options(args, args.paths or ["."]))
        doc = result.graph.to_dict()
        empty = result.empty
    full = doc
    doc = _apply_scope(full, scope)         # raises ScopeError -> exit 1
    note = scope_out.empty_note(doc)
    if args.fmt == "mermaid":
        text = mermaid_out.render_mermaid(doc)
    elif args.fmt == "text":
        text = api.render_text(doc)
    else:
        target = args.out_file or os.path.join(os.getcwd(), ".mlview", "report.html")
        scoped = scope is not None and not scope.is_all
        path = html_out.write_html(full, target,
                                   scope=scope.spec if scoped else None,
                                   depth=scope.depth if scoped else None)
        write_stderr("mlview: wrote %s" % path)
        if note:
            write_stderr(note)
        if args.open_report:
            _open_path(path)
        return EXIT_EMPTY if empty else EXIT_OK
    if args.out_file:
        abs_path = os.path.abspath(args.out_file)
        parent = os.path.dirname(abs_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        write_stderr("mlview: wrote %s" % abs_path.replace("\\", "/"))
    else:
        write_stdout(text)
    if note:
        write_stderr(note)
    return EXIT_EMPTY if empty else EXIT_OK


def _cmd_explain(args) -> int:
    from .rules import rule_for

    target = args.target
    if target.upper().startswith("MLV"):
        spec = rule_for(target.upper())
        if spec is None:
            write_stderr("mlview: unknown rule %s" % target)
            return EXIT_USAGE
        payload = {
            "code": spec.code, "severity": spec.severity, "basePrior": spec.base_prior,
            "frameworks": list(spec.frameworks), "ruleVersion": spec.rule_version,
            "tags": list(spec.tags), "absence": spec.absence, "enabled": spec.enabled,
            "title": spec.title, "why": spec.why, "fixHint": spec.fix_hint,
            "docs": spec.docs,
        }
        if args.json_out:
            write_stdout(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        else:
            write_stdout(
                "%s  %s  (%s, base prior %.2f)\n%s\n\nWhy: %s\nFix: %s\nDocs: %s\n"
                % (spec.code, spec.title, spec.severity, spec.base_prior,
                   "frameworks: " + (", ".join(spec.frameworks) or "any"),
                   spec.why, spec.fix_hint, spec.docs))
        return EXIT_OK

    if not args.graph_file:
        write_stderr("mlview: explaining a node id needs --graph FILE")
        return EXIT_USAGE
    try:
        doc = json_out.load_json(args.graph_file)
    except (OSError, ValueError) as exc:
        write_stderr("mlview: cannot read %s: %s" % (args.graph_file, exc))
        return EXIT_USAGE
    node = next((n for n in doc.get("nodes", []) if n["id"] == target), None)
    if node is None:
        write_stderr("mlview: no node %s in %s" % (target, args.graph_file))
        return EXIT_USAGE
    incoming = [e for e in doc.get("edges", []) if e["target"] == target]
    outgoing = [e for e in doc.get("edges", []) if e["source"] == target]
    issues = [i for i in doc.get("issues", []) if target in i.get("nodeIds", [])]
    payload = {"node": node, "in": incoming, "out": outgoing, "issues": issues,
               "stageEvidence": node.get("stageEvidence", [])}
    if args.json_out:
        write_stdout(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return EXIT_OK
    lines = ["%s  %s  [%s / %s]" % (node["label"], node["id"], node["kind"], node["stage"]),
             "  %s:%d" % (node["loc"]["file"], node["loc"]["line"]),
             "  qualname: %s" % node["qualname"]]
    if node.get("fqn"):
        lines.append("  fqn: %s" % node["fqn"])
    for evidence in node.get("stageEvidence", []):
        lines.append("  why this stage: %s (%s)" % (evidence["detail"], evidence["kind"]))
    for edge in incoming:
        lines.append("  in  <- %s %s" % (edge["source"], edge.get("label") or edge["kind"]))
    for edge in outgoing:
        lines.append("  out -> %s %s" % (edge["target"], edge.get("label") or edge["kind"]))
    for issue in issues:
        lines.append("  %s %s: %s" % (issue["severity"], issue["code"], issue["title"]))
    write_stdout("\n".join(lines) + "\n")
    return EXIT_OK


def _cmd_rules(args) -> int:
    from .rules import all_rules, rule_for

    if args.explain_code:
        return _cmd_explain(argparse.Namespace(target=args.explain_code, graph_file=None,
                                               json_out=args.json_out))
    specs = all_rules()
    if args.json_out:
        payload = [{"code": s.code, "severity": s.severity, "basePrior": s.base_prior,
                    "frameworks": list(s.frameworks), "ruleVersion": s.rule_version,
                    "tags": list(s.tags), "absence": s.absence, "enabled": s.enabled,
                    "title": s.title, "fixHint": s.fix_hint, "docs": s.docs}
                   for s in specs]
        write_stdout(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return EXIT_OK
    lines = ["%d rule(s) registered" % len(specs)]
    for spec in specs:
        lines.append("  %-7s %-7s %-9s %s%s"
                     % (spec.code, spec.severity,
                        ",".join(spec.frameworks)[:9] or "any", spec.title,
                        "" if spec.enabled else "  (disabled)"))
    write_stdout("\n".join(lines) + "\n")
    return EXIT_OK


def _cmd_schema(_args) -> int:
    write_stdout_bytes(api.schema_text())
    return EXIT_OK


def _cmd_version(args) -> int:
    if getattr(args, "version_json", False):
        write_stdout(json.dumps({"name": "mlview", "version": __version__,
                                 "schemaVersion": SCHEMA_VERSION,
                                 "python": "%d.%d" % sys.version_info[:2]},
                                indent=2) + "\n")
    else:
        write_stdout("mlview %s (schema %s)\n" % (__version__, SCHEMA_VERSION))
    return EXIT_OK


_COMMANDS = {
    "analyze": _cmd_analyze,
    "issues": _cmd_issues,
    "render": _cmd_render,
    "explain": _cmd_explain,
    "rules": _cmd_rules,
    "schema": _cmd_schema,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        # argparse already printed the reason and uses status 2 for a usage
        # error - but 2 is reserved for `--fail-on`, so remap it to 1.
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    if args.version or (args.command is None and getattr(args, "version_json", False)):
        return _cmd_version(args)
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    handler = _COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse guards this
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        return handler(args)
    except ScopeError as exc:
        # A usage error (CONTRACTS 11.5): the code, the offending term and the
        # candidates go to stderr; stdout stays untouched.
        write_stderr(scope_out.error_text(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:  # pragma: no cover - interactive
        write_stderr("mlview: interrupted")
        return EXIT_INTERNAL
    except Exception as exc:  # noqa: BLE001 - the CLI must never traceback
        import traceback
        detail = traceback.format_exc(limit=6)
        write_stdout(json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}},
                                indent=2) + "\n")
        write_stderr(detail)
        return EXIT_INTERNAL


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
