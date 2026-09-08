"""The `python -m mlview` argument parser (CONTRACTS section 3).

Split out of `cli.py` so the command implementations and the flag surface stay
readable apart; `mlview.cli` re-exports `build_parser`, which is the only name
anything outside this package uses.
"""

from __future__ import annotations

import argparse

__all__ = ["build_parser", "FORMATS", "GROUP_BY"]

FORMATS = ("summary", "json", "mermaid", "text")

#: RAIL-GROUP. `none` is the default on every command, so every existing
#: invocation - and every snapshot taken of one - prints what it always did.
GROUP_BY = ("none", "rule", "file")


def _add_group_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--group-by", dest="group_by", choices=GROUP_BY,
                        default="none",
                        help="collapse the issue table: one row per rule or "
                             "per file, with occurrence counts (default: none)")


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
    analyze.add_argument("--format", dest="fmt", choices=FORMATS, default="summary")
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
    _add_group_flag(analyze)
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
    _add_group_flag(issues)
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
