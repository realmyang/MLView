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
from . import cli_commands
from .adopt import cli_glue
from .cli_parser import DATAFLOW_MODES, FORMATS, GROUP_BY, build_parser
from .core.graph import SEVERITY_RANK
from .core.pipeline import DEFAULT_RELEVANCE, AnalyzeOptions
from .core.relevance import DEFAULT_HOPS
from .ir.build_ir import DEFAULT_DATAFLOW
from .core.project import (Scope, ScopeError, parse_scope, pipeline_catalog,
                          project, scope_catalog)
from .emit import html_out, json_out, mermaid_out, scope_out
from .emit.text_out import write_stderr, write_stdout, write_stdout_bytes
from .version import SCHEMA_VERSION, __version__

#: `build_parser` is re-exported: it lives in `cli_parser` now, but every
#: caller outside this package reaches it as `mlview.cli.build_parser`.
__all__ = ["main", "build_parser", "FORMATS", "GROUP_BY"]

EXIT_OK, EXIT_USAGE, EXIT_FAIL_ON, EXIT_INTERNAL, EXIT_EMPTY = 0, 1, 2, 3, 4


# ----------------------------------------------------------------- helpers
def _progress_sink(args):
    """H3: `--progress-json` is the only thing that opens the stderr sink; the
    library itself never writes a byte of progress on its own."""
    if not getattr(args, "progress_json", False):
        return None
    from .core.progress import ProgressWriter
    return ProgressWriter()


#: `(option name, argparse dest, documented default)`. The flags default to
#: `None` in `cli_parser`, so `None` here means "not typed" and anything else
#: is recorded in `AnalyzeOptions.explicit` - which is what stops a checked-in
#: `.mlview.toml` from overruling `--max-nodes 400` or `--min-confidence 0.0`.
_NUMERIC_FLAGS = (("max_files", 500), ("max_nodes", 400), ("min_confidence", 0.0))


def _numeric(args, name: str, fallback):
    value = getattr(args, name, None)
    return fallback if value is None else value


def _explicit(args) -> tuple:
    return tuple(name for name, _default in _NUMERIC_FLAGS
                 if getattr(args, name, None) is not None)


def _options(args, paths: Sequence[str]) -> AnalyzeOptions:
    return AnalyzeOptions(
        paths=tuple(paths),
        include=tuple(getattr(args, "include", ()) or ()),
        exclude=tuple(getattr(args, "exclude", ()) or ()),
        max_files=int(_numeric(args, "max_files", 500)),
        max_nodes=int(_numeric(args, "max_nodes", 400)),
        framework=getattr(args, "framework", "auto"),
        min_severity=getattr(args, "min_severity", "low"),
        min_confidence=float(_numeric(args, "min_confidence", 0.0)),
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
        dataflow=getattr(args, "dataflow", DEFAULT_DATAFLOW),
        explicit=_explicit(args))


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
