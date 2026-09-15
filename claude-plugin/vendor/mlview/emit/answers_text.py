"""The vocabulary the four answers are written in.

Every sentence in the answers block is built from the same pieces: pick the
nodes confident enough to assert a fact from, cite them with a file and a line,
join a list into English, say how many were dropped for low confidence, and say
so when a rollup or a blind spot means the answer is narrower than it looks.

`MIN_CONFIDENCE` is the whole honesty policy in one number - a node the
analyzer is less sure of than this is never the subject of a sentence - and it
lives here because every helper below it enforces it.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple


#: Never assert a fact from a node the analyzer is less than this sure of.
MIN_CONFIDENCE = 0.6
FIELDS = ("dataEntry", "objective", "evaluation", "verdict")
_LABELS = {"dataEntry": "data", "objective": "objective",
           "evaluation": "evaluation", "verdict": "verdict"}
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
#: ANA-5a adds `unresolved_callee`: a call MLView could not read is exactly the
#: reason a verdict of "no findings" must not be read as a clean bill of health.
#:
#: INFRA-R2-11 adds the three *larger* gaps that were outside the set, so the
#: card and the MCP digest used to hand back four unqualified absence claims
#: and a clean "No findings: no rule fired on this workspace" for a workspace
#: whose only ML file failed to parse, whose notebooks were never opened, or
#: whose directory could not be read. A kind that means **we did not read
#: something** must always reach the verdict.
_COVERAGE_KINDS = ("untagged_dataflow", "single_file_analysis", "unresolved_callee",
                   "parse_error", "notebook_skipped", "truncated")
#: How each kind is said in the absence clause, in this order.
_COVERAGE_PHRASE = (
    ("unresolved_callee", "%d call(s) could not be read"),
    ("parse_error", "%d file(s) could not be parsed"),
    ("notebook_skipped", "%d notebook(s) were not analyzed - re-run with "
                         "--include-notebooks"),
    ("truncated", "%d part(s) of the analysis were capped"),
    ("untagged_dataflow", "%d value(s) carry no dataflow tag"),
    ("single_file_analysis", "%d file(s) of a larger package were read alone"),
)
_MAX_CITED = 3


# ------------------------------------------------------------------ helpers
def _nodes(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [n for n in (doc.get("nodes") or []) if isinstance(n, dict)]


def _confident(node: Dict[str, Any]) -> bool:
    value = node.get("confidence")
    return isinstance(value, (int, float)) and float(value) >= MIN_CONFIDENCE


def _pick(nodes: Iterable[Dict[str, Any]], **match) -> Tuple[List[Dict[str, Any]], int]:
    """`(confident matches, how many were dropped for low confidence)`.

    Ghosts are excluded here by construction: every caller that wants one asks
    for it explicitly through `_ghosts`.
    """
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for node in nodes:
        if node.get("ghost"):
            continue
        if any(node.get(key) != value for key, value in match.items()):
            continue
        if _confident(node):
            kept.append(node)
        else:
            dropped += 1
    return kept, dropped


def _ghosts(nodes: Iterable[Dict[str, Any]], predicate) -> List[Dict[str, Any]]:
    return [n for n in nodes if n.get("ghost") and predicate(n)]


def _loc(node: Dict[str, Any]) -> Dict[str, Any]:
    loc = node.get("loc") or {}
    return {"file": loc.get("file", ""), "line": int(loc.get("line") or 1)}


def _at(node: Dict[str, Any]) -> str:
    loc = node.get("loc") or {}
    return "%s:%s" % (loc.get("file", "?"), loc.get("line", "?"))


def _cite(node: Dict[str, Any], with_fqn: bool = False) -> str:
    label = node.get("label") or node.get("qualname") or "?"
    if with_fqn and node.get("fqn"):
        return "%s (%s) at %s" % (label, node["fqn"], _at(node))
    return "%s at %s" % (label, _at(node))


def _join(parts: Sequence[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "%s and %s" % (", ".join(parts[:-1]), parts[-1])


def _listing(nodes: Sequence[Dict[str, Any]], with_fqn: bool = False,
             limit: int = _MAX_CITED) -> str:
    shown = _join([_cite(n, with_fqn) for n in nodes[:limit]])
    if len(nodes) > limit:
        shown += " (+%d more)" % (len(nodes) - limit)
    return shown


def _dropped_clause(dropped: int) -> str:
    if not dropped:
        return ""
    return (" %d further candidate(s) were below the %.1f confidence floor and "
            "are not asserted." % (dropped, MIN_CONFIDENCE))


def _rolled_up(doc: Dict[str, Any]) -> bool:
    """Did `--max-nodes` fold this document (VIEW-R1)?

    `stats.truncated` is the document saying so about itself. It matters here
    because every "No X was detected" sentence below is a claim about the
    *workspace*, read off the `nodes[]` array - and after PERF-04's rollup that
    array is a summary of the workspace, not the workspace. On
    `samples/vision_pipeline --max-nodes 20` the objective node folds into
    `train()` and the data nodes into a file summary that votes itself into
    `preprocess`, and the card then stated "No loss function was detected" and
    "No data entry was detected" about a program with a `CrossEntropyLoss` and
    two loaders in it. The graph must never claim it looked and found nothing
    when it was blinded.
    """
    stats = doc.get("stats")
    if isinstance(stats, dict) and stats.get("truncated"):
        return True
    return bool(doc.get("truncated"))


def _blinded(what: str, raise_hint: str = "") -> str:
    return ("%s could not be read off this document: the graph was rolled up to "
            "fit --max-nodes, so what survives is a summary of the workspace "
            "rather than the workspace. Raise --max-nodes, or scope the analysis "
            "to one part of the project, to answer this%s."
            % (what, (" - %s" % raise_hint) if raise_hint else ""))
