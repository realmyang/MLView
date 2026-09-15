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
from typing import Any, Dict, Optional, Sequence

from . import api
from . import cli_commands
from .adopt import cli_glue
from .cli_helpers import (_adopt_usage_error, _apply_scope, _emit_payload,
                          _emit_sarif, _fail_on_hit, _open_path, _options,
                          _reject_reprojection, _scope_from_args)
from .cli_parser import FORMATS, GROUP_BY, build_parser
from .core.project import Scope, ScopeError, pipeline_catalog, scope_catalog
from .emit import html_out, json_out, mermaid_out, scope_out
from .emit.text_out import write_stderr, write_stdout, write_stdout_bytes
from .version import SCHEMA_VERSION, __version__

#: `build_parser` is re-exported: it lives in `cli_parser` now, but every
#: caller outside this package reaches it as `mlview.cli.build_parser`.
__all__ = ["main", "build_parser", "FORMATS", "GROUP_BY"]

EXIT_OK, EXIT_USAGE, EXIT_FAIL_ON, EXIT_INTERNAL, EXIT_EMPTY = 0, 1, 2, 3, 4


def _missing_paths(paths) -> list:
    """Positional paths that do not exist (HOSTS-UX-MISSINGPATH)."""
    return [p for p in paths or () if not os.path.exists(os.path.expanduser(p))]


# ---------------------------------------------------------------- commands
def _cmd_analyze(args) -> int:
    scope = _scope_from_args(args)          # raises ScopeError -> exit 1, clean stdout
    cli_commands.apply_file_config(args)
    usage = _adopt_usage_error(args)
    if usage:
        write_stderr("mlview: " + usage)
        return EXIT_USAGE
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
    missing = _missing_paths(paths)
    if missing:
        # HOSTS-UX-MISSINGPATH. Section 3 reserves exit 1 for a usage or I/O
        # error and exit 4 for "nothing analyzable found (no .py files after
        # filtering)". A path that is not there is the former, and the old
        # shared branch printed 1156 bytes of clean-looking summary - "0 files
        # analyzed, frameworks: none detected, No data entry was detected" -
        # about a directory that does not exist.
        write_stderr("mlview: no such path: %s" % ", ".join(missing))
        return EXIT_USAGE
    result = api.analyze_full(_options(args, paths))
    # CI-ADOPT: the analysis above saw the WHOLE workspace; attribution and the
    # baseline are applied to the finished graph, never to the analysis.
    cli_glue.apply_to_graph(result.graph, args)
    full = result.graph.to_dict()
    doc = _apply_scope(full, scope)         # raises ScopeError -> exit 1
    wrote_stdout = _emit_payload(doc, args, full=full, scope=scope)
    wrote_stdout = _emit_sarif(doc, args) or wrote_stdout
    if not wrote_stdout:
        _print_format(doc, args)
    note = scope_out.empty_note(doc, scope)
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
    # MLV-P12 (CONTRACTS 11.47 B2): the coarsest scopes lead the menu, and
    # only when the workspace has two or more pipelines to choose between.
    rows = pipeline_catalog(doc) + scope_catalog(doc, limit=0)
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
            doc, show_suppressed=bool(getattr(args, "show_suppressed", False)),
            group_by=getattr(args, "group_by", "none")))


def _cmd_issues(args) -> int:
    scope = _scope_from_args(args)          # raises ScopeError -> exit 1
    cli_commands.apply_file_config(args)
    usage = _adopt_usage_error(args)
    if usage:
        write_stderr("mlview: " + usage)
        return EXIT_USAGE
    paths = args.paths or ["."]
    result = api.analyze_full(_options(args, paths))
    cli_glue.apply_to_graph(result.graph, args)
    doc = _apply_scope(result.graph.to_dict(), scope)
    codes = {c.strip().upper() for c in (args.code or "").split(",") if c.strip()}
    issues = [i for i in cli_glue.visible_issues(doc.get("issues", []),
                                                 args.show_suppressed)
              if not codes or i["code"] in codes]
    if args.limit and args.limit > 0:
        issues = issues[:args.limit]
    baselined = cli_glue.baselined_count(doc.get("issues", []))
    # The SARIF honours `--code` - it is a statement about which rules were
    # asked for - but not `--limit` or the suppressed/baselined hiding: a limit
    # is a reading convenience, and a suppressed finding ships as a *suppressed
    # result* so the consumer does not read it as fixed and then as new again.
    sarif_doc = dict(doc, issues=[i for i in doc.get("issues", [])
                                  if not codes or i["code"] in codes])
    sarif_to_stdout = _emit_sarif(sarif_doc, args)
    if sarif_to_stdout:
        pass                                # the SARIF *is* the payload
    elif args.json_out:
        counts = {"low": 0, "medium": 0, "high": 0}
        for issue in issues:
            counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
        payload = {
            "countBySeverity": counts,
            "suppressedCount": sum(1 for i in doc.get("issues", []) if i.get("suppressed")),
            "issues": issues,
            # HOST-4: the same diagnostics `analyze --format json` carries. An
            # agent reading this payload could not tell an attributed-away
            # finding from a clean workspace without them.
            "diagnostics": doc.get("diagnostics", []),
        }
        if baselined:
            payload["baselinedCount"] = baselined
        if isinstance(doc.get("view"), dict):
            payload["scope"] = doc["view"]["scope"]
        write_stdout(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        from .emit.text_out import diagnostic_block, issue_lines, render_findings
        scoped = scope_out.issues_scope_suffix(doc)   # names the denominator
        set_aside = sum(int(d.get("count") or 0)
                        for d in (doc.get("diagnostics") or [])
                        if isinstance(d, dict) and d.get("scope") == "changed-only")
        marks = []
        if baselined:
            marks.append("%d baselined" % baselined)
        if set_aside:
            marks.append("%d not shown" % set_aside)
        marked = (" · " + " · ".join(marks)) if marks else ""
        header = "%d issue(s) in %s%s%s\n" % (len(issues), doc["workspace"]["root"],
                                              scoped, marked)
        if not issues:
            # Never a bare "none found" while something was set aside: an agent
            # cannot tell "I checked and it is fine" from "I could not check".
            body = ("  none found\n" if not set_aside else
                    "  none shown - %d finding(s) do not touch the change; see "
                    "Notes below\n" % set_aside)
        elif getattr(args, "text_out", False):
            # CLEANUP 1: `--text` was declared with `dest="text_out"` and read
            # by nobody, so the two invocations were byte-identical and the
            # obvious command for "show me the issues" was the one that hid the
            # why / fix text.
            body = render_findings(issues) + "\n"
        else:
            body = "\n".join(issue_lines(issues, getattr(args, "group_by", "none"))) + "\n"
        notes = diagnostic_block(doc)
        if notes:
            body += "\n".join(notes) + "\n"
        write_stdout(header + body)
    if result.empty:
        return EXIT_EMPTY
    note = scope_out.empty_note(doc, scope)
    if note:
        write_stderr(note)
    if _fail_on_hit({"issues": issues}, args.fail_on):
        suffix = scope_out.fail_on_suffix(doc)
        if suffix:
            write_stderr("mlview: --fail-on %s threshold exceeded%s"
                         % (args.fail_on, suffix))
        return EXIT_FAIL_ON
    return EXIT_OK


def _cmd_baseline(args) -> int:
    """`mlview baseline write` (CI-ADOPT b). The payload is the file, so stdout
    stays empty and the path goes to stderr like every other written artifact."""

    def analyze():
        return api.analyze_full(_options(args, args.paths or ["."])).graph

    try:
        code, message = cli_glue.cmd_baseline(args, analyze)
    except OSError as exc:
        write_stderr("mlview: cannot write the baseline: %s" % exc)
        return EXIT_USAGE
    write_stderr(message)
    return code


def _cmd_init(args) -> int:
    """`mlview init` (CFG-ONE, CONTRACTS 11.37 D). The body is in
    `cli_commands`; this is the exit-code mapping, and it is the only place the
    §3 table is written down."""
    return EXIT_OK if cli_commands.run_init(args) else EXIT_USAGE


def _cmd_diff(args) -> int:
    """`mlview diff BASE.json HEAD.json` (VIEW-08, CONTRACTS 11.38)."""
    return EXIT_OK if cli_commands.run_diff(args) else EXIT_USAGE


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
    note = scope_out.empty_note(doc, scope)
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
    # CLEANUP 6: the framework column used to be sliced to 9 characters, which
    # cut names mid-word (`sklearn,p`, `torch,lig`). Width it to the widest
    # value actually present and elide on a comma, never inside a name.
    frameworks = [_framework_column(spec) for spec in specs]
    width = max([len(f) for f in frameworks] + [len("FRAMEWORKS")])
    lines = ["%d rule(s) registered" % len(specs)]
    for spec, column in zip(specs, frameworks):
        lines.append("  %-7s %-7s %-*s %s%s"
                     % (spec.code, spec.severity, width, column, spec.title,
                        "" if spec.enabled else "  (disabled)"))
    write_stdout("\n".join(lines) + "\n")
    return EXIT_OK


def _framework_column(spec, limit: int = 24) -> str:
    """`torch, lightning` - whole names only, `+N` when there are too many."""
    names = list(spec.frameworks)
    if not names:
        return "any"
    out = ""
    for index, name in enumerate(names):
        candidate = name if not out else "%s, %s" % (out, name)
        if len(candidate) > limit and out:
            return "%s +%d" % (out, len(names) - index)
        out = candidate
    return out


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
    "baseline": _cmd_baseline,
    "render": _cmd_render,
    "explain": _cmd_explain,
    "rules": _cmd_rules,
    "schema": _cmd_schema,
    "init": _cmd_init,                      # CFG-ONE   (CONTRACTS 11.37)
    "diff": _cmd_diff,                      # VIEW-08   (CONTRACTS 11.38)
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
    except OSError as exc:
        # ROB-07. README's exit table is `0 ok · 1 usage or I/O · 2 --fail-on ·
        # 3 internal error`, and an unwritable `--json` / `--sarif` / `--html`
        # path used to exit **3** with a Python traceback - so a CI harness
        # reading that code could not tell "MLView has a bug" from "your output
        # directory is read-only". An `OSError` reaching here is I/O, by
        # definition; nothing goes to stdout.
        path = getattr(exc, "filename", None)
        detail = exc.strerror or str(exc)
        write_stderr("mlview: cannot write %s: %s" % (path or "the output", detail)
                     if path else "mlview: I/O error: %s" % detail)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - the CLI must never traceback
        import traceback
        detail = traceback.format_exc(limit=6)
        write_stdout(json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}},
                                indent=2) + "\n")
        write_stderr(detail)
        return EXIT_INTERNAL


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
