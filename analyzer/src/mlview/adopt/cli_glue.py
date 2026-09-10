"""The CLI half of CI-ADOPT: flag validation, application, SARIF, `baseline`.

Kept out of `cli.py` on purpose. `cli.py` is the frozen command surface and is
already 490 lines; the adoption flags are one feature with one story, so they
live together where the story can be read in one sitting.

Order of operations, and it matters:

1. **analyze the whole workspace** - always, whatever the flags say;
2. attribute (`--changed-since` / `--changed-paths`), which may drop
   `existing` findings under `--changed-only`;
3. baseline (`--baseline`), which *marks* and never drops;
4. re-run the ghost sweep and `finalize()`, because step 2 can remove the only
   finding a ghost node was carrying (invariant 1.1.8) and the stage
   aggregates are derived from the surviving issues.

Baselining after attributing is deliberate: a baselined finding still carries
its change class, so `--changed-since HEAD~1 --baseline b.json` can report
"this is new **and** it was already in the baseline", which is the signal that
the baseline needs regenerating.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..core.graph import MLGraph
from ..core.pipeline import drop_orphan_ghosts
from . import baseline as baseline_mod
from .attribute import apply_change_attribution
from .gitdiff import ChangeSet, changed_from_file, changed_from_rev

__all__ = ["validate_args", "apply_to_graph", "write_sarif_output",
           "cmd_baseline", "visible_issues", "baselined_count"]


# -------------------------------------------------------------- validation
def validate_args(args) -> Optional[str]:
    """`None` when the flag combination is usable, else the error text.

    A *flag* mistake is a usage error (exit 1) even though a *git* failure
    never is: `--changed-only` with nothing to compare against would silently
    show everything, which is the one direction a CI gate must not fail in.
    """
    since = getattr(args, "changed_since", None)
    paths = getattr(args, "changed_paths", None)
    if since and paths:
        return ("--changed-since and --changed-paths are two ways to say the "
                "same thing; pass one.")
    if getattr(args, "changed_only", False) and not (since or paths):
        return ("--changed-only needs a change source: add --changed-since <rev> "
                "or --changed-paths <file>.")
    return None


def _change_set(args, root: str) -> Optional[ChangeSet]:
    paths = getattr(args, "changed_paths", None)
    if paths:
        return changed_from_file(paths, root)
    since = getattr(args, "changed_since", None)
    if since:
        return changed_from_rev(since, root)
    return None


# ------------------------------------------------------------- application
def apply_to_graph(graph: MLGraph, args) -> None:
    """Attribute, baseline, and repair the document. Mutates `graph`."""
    root = graph.root or os.getcwd()
    changes = _change_set(args, root)
    diagnostics = apply_change_attribution(
        graph, changes, changed_only=bool(getattr(args, "changed_only", False)))

    baseline_path = getattr(args, "baseline_path", None)
    if baseline_path:
        entries, error = baseline_mod.load_baseline(baseline_path)
        diagnostics += baseline_mod.apply_baseline(graph, entries, baseline_path,
                                                   load_error=error)
    if not diagnostics:
        return
    graph.diagnostics = list(graph.diagnostics) + diagnostics
    drop_orphan_ghosts(graph)
    graph.finalize()


# ------------------------------------------------------------------- views
def visible_issues(issues, show_suppressed: bool = False) -> List[Dict[str, Any]]:
    """The issues a human is meant to read: neither suppressed nor baselined,
    unless `--show-suppressed` asked for both."""
    if show_suppressed:
        return list(issues)
    return [i for i in issues
            if not i.get("suppressed") and not i.get("baselined")]


def baselined_count(issues) -> int:
    return sum(1 for i in issues if i.get("baselined") and not i.get("suppressed"))


# ------------------------------------------------------------------- SARIF
def write_sarif_output(doc: Dict[str, Any], target: str) -> Tuple[str, bytes]:
    """`(path_written, stdout_bytes)`. `-` means stdout and writes no file."""
    from ..emit import sarif_out

    if target == "-":
        return "", sarif_out.sarif_bytes(doc)
    return sarif_out.write_sarif(doc, target), b""


# ---------------------------------------------------------------- baseline
def cmd_baseline(args, analyze) -> Tuple[int, str]:
    """`mlview baseline write [PATHS] [--out FILE]`.

    `analyze` is injected rather than imported so this module stays free of
    `mlview.api` (and of the import cycle that would create). Returns
    `(exit_code, message_for_stderr)`; the command writes nothing to stdout,
    because the payload is the file.
    """
    action = getattr(args, "action", "write")
    if action != "write":                       # pragma: no cover - argparse guards
        return 1, "mlview: unknown baseline action %r; only 'write' exists" % action
    graph = analyze()
    out = getattr(args, "out_file", None) or os.path.join(
        graph.root or os.getcwd(), baseline_mod.DEFAULT_BASELINE_PATH)
    path = baseline_mod.write_baseline(graph, out)
    entries = len(baseline_mod.build_baseline(graph)["entries"])
    return 0, ("mlview: wrote %s (%d entry/entries). Commit it, then gate with "
               "`mlview issues . --baseline %s --fail-on high`."
               % (path, entries, out))
