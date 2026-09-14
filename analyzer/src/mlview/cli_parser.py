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
#: DATAFLOW-IP. The mode names live with the pass that implements them, so the
#: flag surface cannot offer a mode `ir.build_ir` does not know.
from .ir.build_ir import DATAFLOW_MODES, DEFAULT_DATAFLOW

__all__ = ["build_parser", "FORMATS", "GROUP_BY", "RELEVANCE_MODES",
           "DATAFLOW_MODES"]

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
    """PERF-03 and CACHE (CONTRACTS 11.28, defaults flipped by 11.39). Three
    flags: `ml` is the shipped mode and `all` is the identity one - it builds
    the IR for every discovered file, derives no facts and consults no cache,
    so it reproduces the pre-11.39 bytes exactly."""
    parser.add_argument("--relevance", dest="relevance", choices=RELEVANCE_MODES,
                        default=DEFAULT_RELEVANCE,
                        help="`ml` (default) builds the IR only for files within "
                             "--relevance-hops import hops of a framework import, "
                             "and says how many it set aside; `all` builds it for "
                             "every discovered file")
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


def _add_dataflow_flag(parser: argparse.ArgumentParser) -> None:
    """DATAFLOW-IP (CONTRACTS 11.36). One flag, `local` by default, so a command
    that does not name it emits exactly the bytes it always emitted."""
    parser.add_argument("--dataflow", dest="dataflow", choices=DATAFLOW_MODES,
                        default=DEFAULT_DATAFLOW,
                        help="`local` (default) tracks a value tag inside one "
                             "scope; `ip` additionally carries it across the "
                             "object boundary through constructor, return and "
                             "method-argument summaries, de-rating every finding "
                             "once per hop and naming the hop chain in its "
                             "evidence")


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
                        # Every spelling `SCOPE_SPELLINGS` accepts, named here:
                        # the help text is the only place a CLI user learns a
                        # selector exists, and `pipeline:` (11.47) and `symbol:`
                        # were reachable but unadvertised until doc-gate check 16
                        # started holding this string to the parser's own tuple.
                        help="project the graph before emitting: 'all', "
                             "unit:<name>, symbol:<name>, stage:<id>, "
                             "file:<path.py>, concern:<name>, node:<id>, "
                             "pipeline:<entrypoint.py>")
    parser.add_argument("--depth", dest="depth", metavar="N", default=None,
                        help="boundary hops 0..2 (default: 1 for unit/node, "
                             "0 for stage/file/concern)")


#: HOSTS-UX-R2-08 / config precedence. Every numeric flag defaults to `None`,
#: not to the documented default: `--max-nodes 400` and `--min-confidence 0.0`
#: are the defaults, so a value-equals-default test could not tell a flag the
#: user typed from one they did not, and a checked-in `.mlview.toml` overruled
#: the flag. `cli._options` substitutes the real default and records the name
#: in `AnalyzeOptions.explicit`.
#:
#: The `type=` callables also make an out-of-range value an argparse **usage
#: error** (exit 1) instead of a silently accepted no-op: `--max-nodes 0` used
#: to run the whole analysis and cap nothing, and `--min-confidence 2.0` to
#: exit 0 with no warning, while the same value in a config file produced a
#: `config_warning`. The MCP server already clamps and says so; this is the
#: CLI meeting the same bar.
def _at_least_one(text: str) -> int:
    import argparse
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not an integer" % text)
    if value < 1:
        raise argparse.ArgumentTypeError(
            "must be 1 or more (got %d); it is a budget, not a switch" % value)
    return value


def _a_probability(text: str) -> float:
    import argparse
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not a number" % text)
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError(
            "must be between 0 and 1 (got %s)" % text)
    return value


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
    analyze.add_argument("--min-confidence", type=_a_probability, default=None)
    analyze.add_argument("--show-suppressed", action="store_true")
    analyze.add_argument("--max-files", type=_at_least_one, default=None)
    analyze.add_argument("--max-nodes", type=_at_least_one, default=None,
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
    _add_dataflow_flag(analyze)
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
    issues.add_argument("--min-confidence", type=_a_probability, default=None)
    issues.add_argument("--code", default="", help="comma-separated rule codes")
    issues.add_argument("--limit", type=int, default=0)
    issues.add_argument("--max-files", type=_at_least_one, default=None)
    issues.add_argument("--max-nodes", type=_at_least_one, default=None,
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
    _add_dataflow_flag(issues)
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
    baseline.add_argument("--max-files", type=_at_least_one, default=None)
    baseline.add_argument("--max-nodes", type=_at_least_one, default=None)
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
    render.add_argument("--max-files", type=_at_least_one, default=None)
    render.add_argument("--max-nodes", type=_at_least_one, default=None,
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

    _add_init_command(sub)
    _add_diff_command(sub)

    sub.add_parser("schema", help="print the MLGraph JSON Schema")
    return parser


def _add_init_command(sub) -> None:
    """CFG-ONE (CONTRACTS 11.37). `mlview init` writes a commented
    `.mlview.toml` listing every registered rule with the severity it ships at,
    generated from the registry so the file cannot drift from the rules.

    Every key in it is commented out, so running `init` cannot change what a
    later `analyze` reports - the file documents the surface, it does not
    configure anything until a human uncomments a line.
    """
    init = sub.add_parser("init", help="write a commented .mlview.toml")
    init.add_argument("paths", nargs="*", default=[],
                      help="the workspace to write it into (default: .)")
    init.add_argument("--out", dest="out_file", metavar="FILE",
                      help="write here instead of <root>/.mlview.toml "
                           "('-' means stdout)")
    init.add_argument("--force", dest="force", action="store_true",
                      help="overwrite an existing file")
    init.add_argument("--no-color", action="store_true")


def _add_diff_command(sub) -> None:
    """VIEW-08 (CONTRACTS 11.38). `mlview diff base.json head.json`.

    Both inputs are documents `mlview analyze --json` already writes, and the
    output is a **separate overlay document** - never a graph - so
    `schemaVersion` stays 1.0 and nothing about an ordinary analysis moves.
    """
    diff = sub.add_parser("diff", help="compare two analyses (VIEW-08)")
    diff.add_argument("base_file", metavar="BASE.json",
                      help="the earlier `mlview analyze --json` document")
    diff.add_argument("head_file", metavar="HEAD.json",
                      help="the later one")
    diff.add_argument("--json", dest="json_out", metavar="FILE|-",
                      help="write the overlay document ('-' means stdout)")
    diff.add_argument("--format", dest="fmt", choices=("summary", "json"),
                      default="summary")
    diff.add_argument("--no-color", action="store_true")
