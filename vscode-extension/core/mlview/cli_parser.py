"""The `python -m mlview` argument parser (CONTRACTS section 3).

Split out of `cli.py` so the command implementations and the flag surface stay
readable apart; `mlview.cli` re-exports `build_parser`, which is the only name
anything outside this package uses.
"""

from __future__ import annotations

import argparse

#: RAIL-GROUP. `none` is the default on every command, so every existing
#: invocation - and every snapshot taken of one - prints what it always did.
#: Re-exported from `emit/group_out`, which is the single source of truth: the
#: two lists had drifted, and `severity` - named in RAIL-GROUP's own
#: `rule|file|severity` - was an argparse error here until 2026-09-08 (TB-12).
from .emit.group_out import GROUP_BY
#: PERF-03 / CACHE. Both live in `core` so the flag surface and the pipeline
#: cannot disagree about the mode names or the default hop count.
from .core.pipeline import DEFAULT_RELEVANCE
from .core.relevance import DEFAULT_HOPS, MODES as RELEVANCE_MODES

__all__ = ["build_parser", "FORMATS", "GROUP_BY", "RELEVANCE_MODES"]

FORMATS = ("summary", "json", "mermaid", "text")


def _add_adopt_flags(parser: argparse.ArgumentParser) -> None:
    """CI-ADOPT. Five flags that make MLView adoptable on a repo which already
    has findings; every one of them is additive and off by default, so a
    command that does not name them prints exactly what it always printed."""
    parser.add_argument("--changed-since", dest="changed_since", metavar="REV",
                        help="classify each finding as new / touched / existing "
                             "against `git diff -M --unified=0 REV`; the whole "
                             "workspace is still analyzed")
    parser.add_argument("--changed-paths", dest="changed_paths", metavar="FILE",
                        help="the same, from a diff (or a newline-separated path "
                             "list) a CI runner already has, instead of shelling git")
    parser.add_argument("--changed-only", dest="changed_only", action="store_true",
                        help="drop `existing` findings from the output and from "
                             "--fail-on; needs a change source")
    parser.add_argument("--baseline", dest="baseline_path", metavar="FILE",
                        help="mark findings recorded in FILE as baselined: still "
                             "emitted, excluded from the counts and from --fail-on")
    parser.add_argument("--sarif", dest="sarif_out", metavar="FILE|-",
                        help="also write SARIF 2.1.0 ('-' means stdout)")
    parser.add_argument("--progress-json", dest="progress_json", action="store_true",
                        help="write NDJSON progress frames to stderr, one per "
                             "analyzed file (H3); stdout is untouched")


def _add_perf_flags(parser: argparse.ArgumentParser) -> None:
    """PERF-03 and CACHE (CONTRACTS 11.28). Three flags, all additive, all with
    defaults that reproduce today's bytes exactly: `--relevance all` is the
    identity mode, and the cache can only change how long an answer takes."""
    parser.add_argument("--relevance", dest="relevance", choices=RELEVANCE_MODES,
                        default=DEFAULT_RELEVANCE,
                        help="`all` (default) builds the IR for every discovered "
                             "file; `ml` builds it only for files within "
                             "--relevance-hops import hops of a framework import, "
                             "and says how many it set aside")
    parser.add_argument("--relevance-hops", dest="relevance_hops", type=int,
                        default=DEFAULT_HOPS, metavar="N",
                        help="import hops, in either direction, that --relevance ml "
                             "follows out from a framework-touching file (default %d)"
                             % DEFAULT_HOPS)
    parser.add_argument("--no-cache", dest="no_cache", action="store_true",
                        help="do not read or write the per-file parse cache "
                             "(same as MLVIEW_NO_CACHE=1)")


def _add_notebook_flag(parser: argparse.ArgumentParser) -> None:
    """NB (CONTRACTS 11.29). One flag, off by default, so a command that does
    not name it emits exactly the bytes it always emitted. `[paths] notebooks =
    true` in `.mlview.toml` is the checked-in equivalent; either one turns it
    on and neither can turn the other off."""
    parser.add_argument("--include-notebooks", dest="include_notebooks",
                        action="store_true",
                        help="analyze `.ipynb` files too: code cells are "
                             "concatenated in document order into a generated "
                             "module under <root>/.mlview/notebooks/, magics "
                             "become `pass  # mlview: magic`, and every finding "
                             "names its cell (default: notebooks are counted "
                             "and skipped)")


def _add_group_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--group-by", dest="group_by", choices=GROUP_BY,
                        default="none",
                        help="collapse the issue table: one row per rule, per "
                             "file or per severity, with occurrence counts "
                             "(default: none)")


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
    _add_perf_flags(analyze)
    _add_notebook_flag(analyze)
    _add_group_flag(analyze)
    _add_adopt_flags(analyze)
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
    _add_perf_flags(issues)
    _add_notebook_flag(issues)
    _add_group_flag(issues)
    _add_adopt_flags(issues)
    _add_scope_flags(issues)

    # CI-ADOPT (b): the ratchet. `write` is the only action there is; it is a
    # positional rather than a flag so `mlview baseline write` reads as the
    # sentence it is, and so a later `check` / `prune` needs no new command.
    baseline = sub.add_parser("baseline", help="record today's findings as a baseline")
    baseline.add_argument("action", choices=("write",))
    baseline.add_argument("paths", nargs="*", default=[])
    baseline.add_argument("--out", dest="out_file", metavar="FILE",
                          help="where to write it (default: <root>/.mlview/baseline.json)")
    baseline.add_argument("--include", action="append", default=[], metavar="GLOB")
    baseline.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    baseline.add_argument("--max-files", type=int, default=500)
    baseline.add_argument("--max-nodes", type=int, default=400)
    baseline.add_argument("--config", dest="config_path", metavar="FILE")
    baseline.add_argument("--no-color", action="store_true")
    _add_perf_flags(baseline)
    _add_notebook_flag(baseline)

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
    _add_perf_flags(render)
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
