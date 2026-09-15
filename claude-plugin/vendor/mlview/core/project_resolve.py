"""`--scope <what>` -> the nodes it names, or an error that says why not.

Resolution is the half of scoped views that can *fail*, and every failure here
is a sentence the user can act on: a unit spelling that matches nothing, a file
that is not in the workspace, a pipeline name no entrypoint answers to. The
tiers in `_unit_tiers` are the order a name is tried in - exact qualname, then
the last segment, then a suffix - so the closest match wins and an ambiguous
one is reported as ambiguous rather than silently picked.

`core/project.py` takes the `ScopeResolution` this hands back and builds the
projected document from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .pipelines import build_index, resolve_entrypoint
from .selectors import CONCERNS, Scope, ScopeError, ascii_lower


# ------------------------------------------------------------ resolution
@dataclass(frozen=True)
class ScopeResolution:
    """Anchors and core for a scope - no projection (CONTRACTS 11.6)."""

    scope: Scope
    anchors: Tuple[str, ...]
    core: Tuple[str, ...]
    ambiguous: bool = False
    warnings: Tuple[str, ...] = ()
    #: MLV-P12 (CONTRACTS 11.47 C). Nodes the scope must keep but must NOT call
    #: its own - today only a `pipeline:` scope's shared nodes, the ones another
    #: entrypoint reaches too. Appended last and defaulted to `()`, so every
    #: other kind builds exactly the resolution it built before.
    context: Tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.anchors


def _last_segment(qualname: str) -> str:
    return qualname.rsplit(".", 1)[-1] if "." in qualname else qualname


def _unit_tiers(nodes: Sequence[Dict[str, Any]], target: str, fold: bool
                ) -> List[List[Dict[str, Any]]]:
    """The five `unit:` tiers, in order, over `nodes` in document order."""
    def fold_fn(value: str) -> str:
        return ascii_lower(value) if fold else value

    want = fold_fn(target)
    want_call = fold_fn(target + "()")

    def eq(value: Optional[str], expected: str) -> bool:
        return bool(value) and fold_fn(value) == expected

    definition = ("stage", "unit")
    return [
        [n for n in nodes if eq(n.get("qualname"), want)],
        [n for n in nodes if eq(n.get("fqn"), want)],
        [n for n in nodes if eq(_last_segment(n.get("qualname", "")), want)
         and n.get("level") in definition],
        [n for n in nodes if eq(_last_segment(n.get("qualname", "")), want)],
        [n for n in nodes if eq(n.get("label"), want) or eq(n.get("label"), want_call)],
    ]


def _resolve_unit(nodes: Sequence[Dict[str, Any]], target: str
                  ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Tiered `unit:` resolution: the first non-empty tier wins (11.2 step 1)."""
    warnings: List[str] = []
    text = target[:-2] if target.endswith("()") else target
    if text.startswith("n:"):
        exact = [n for n in nodes if n.get("id") == text]
        if exact:
            return exact, warnings
    for tier in _unit_tiers(nodes, text, False):
        if tier:
            return tier, warnings
    for tier in _unit_tiers(nodes, text, True):
        if tier:
            spellings = sorted({n.get("qualname", "") for n in tier})[:5]
            warnings.append(
                "scope unit:%s matched case-insensitively; the canonical spelling is %s"
                % (text, ", ".join(spellings)))
            return tier, warnings
    return [], warnings


def _resolve_file(nodes: Sequence[Dict[str, Any]], target: str
                  ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Exact path, then bare basename, then the same two case-insensitively."""
    def file_of(node: Dict[str, Any]) -> str:
        return (node.get("loc") or {}).get("file") or ""

    def base(path: str) -> str:
        return path.rsplit("/", 1)[-1]

    bare = "/" not in target
    exact = [n for n in nodes if file_of(n) == target]
    if exact:
        return exact, []
    if bare:
        by_base = [n for n in nodes if base(file_of(n)) == target]
        if by_base:
            return by_base, []
    want = ascii_lower(target)
    folded = [n for n in nodes if ascii_lower(file_of(n)) == want]
    if not folded and bare:
        folded = [n for n in nodes if ascii_lower(base(file_of(n))) == want]
    if folded:
        spellings = sorted({file_of(n) for n in folded})[:5]
        return folded, ["scope file:%s matched case-insensitively; the canonical "
                        "spelling is %s" % (target, ", ".join(spellings))]
    raise ScopeError("unknown_file", target,
                     sorted({file_of(n) for n in nodes if file_of(n)}))


def _resolve_pipeline(graph: Dict[str, Any], nodes: Sequence[Dict[str, Any]],
                      scope: Scope) -> ScopeResolution:
    """`pipeline:<entrypoint>` (CONTRACTS 11.47 B/C).

    Anchors are the **seeds**: the nodes of the entrypoint file itself, which is
    what the user named. `core` is the pipeline's *exclusive* reach - everything
    it reaches that no other entrypoint does - and the shared remainder becomes
    forced `context`, so a node two pipelines both use is never claimed by one
    of them. A target that is not an entrypoint is `unknown_pipeline`; an
    entrypoint whose file contributed no node is an EMPTY scope, not an error,
    for the same reason `unit:` is (11.2 step 9).
    """
    canonical, warnings = resolve_entrypoint(graph, scope.target)
    if canonical is None:
        raise ScopeError(
            "unknown_pipeline", scope.target,
            [str(e) for e in
             ((graph.get("workspace") or {}).get("entrypoints") or [])])
    index = build_index(graph)
    anchors = tuple(n["id"] for n in nodes
                    if (n.get("loc") or {}).get("file") == canonical)
    core = index.core_of(canonical)
    context = index.context_of(canonical)
    if anchors:
        warnings = list(warnings) + [
            "scope pipeline:%s draws %d node(s) of %d: %d are shared with "
            "another entrypoint and are shown as context, and %d node(s) of "
            "this graph belong to no pipeline at all."
            % (canonical, len(core) + len(context), len(nodes), len(context),
               len(index.unreached))]
    return ScopeResolution(scope, anchors, core, False, tuple(warnings), context)


def resolve_scope(graph: Dict[str, Any], scope: Scope) -> ScopeResolution:
    """Anchors + core for `scope`, in document order. No projection."""
    nodes: List[Dict[str, Any]] = list(graph.get("nodes") or [])
    warnings: List[str] = []
    if scope.kind == "all":
        return ScopeResolution(scope, tuple(n["id"] for n in nodes),
                               tuple(n["id"] for n in nodes))
    if scope.kind == "stage":
        anchors = [n for n in nodes if n.get("stage") == scope.target]
    elif scope.kind == "concern":
        wanted = set(CONCERNS[scope.target])
        anchors = [n for n in nodes if n.get("stage") in wanted]
    elif scope.kind == "file":
        anchors, extra = _resolve_file(nodes, scope.target)
        warnings.extend(extra)
    elif scope.kind == "node":
        anchors = [n for n in nodes if n.get("id") == scope.target]
        if not anchors:
            raise ScopeError("unknown_node", scope.target,
                             [n["id"] for n in nodes])
    elif scope.kind == "pipeline":
        return _resolve_pipeline(graph, nodes, scope)
    else:                                                   # unit
        anchors, extra = _resolve_unit(nodes, scope.target)
        warnings.extend(extra)

    anchor_ids = tuple(n["id"] for n in anchors)
    ambiguous = scope.kind == "unit" and len(anchor_ids) > 1
    if ambiguous:
        warnings.append(
            "scope unit:%s is ambiguous: %d nodes match. Use one of: %s"
            % (scope.target, len(anchor_ids),
               ", ".join(sorted(n.get("qualname", n["id"]) for n in anchors))))
    core = anchor_ids
    if scope.kind == "unit" and anchor_ids:
        core = _with_descendants(nodes, anchor_ids)
    return ScopeResolution(scope, anchor_ids, core, ambiguous, tuple(warnings))


def _with_descendants(nodes: Sequence[Dict[str, Any]],
                      seeds: Sequence[str]) -> Tuple[str, ...]:
    """Seeds plus their transitive `parent` descendants, in document order."""
    children: Dict[str, List[str]] = {}
    for node in nodes:
        parent = node.get("parent")
        if parent:
            children.setdefault(parent, []).append(node["id"])
    keep: Set[str] = set()
    stack = list(seeds)
    while stack:                                            # cycle-guarded
        current = stack.pop()
        if current in keep:
            continue
        keep.add(current)
        stack.extend(children.get(current, ()))
    return tuple(n["id"] for n in nodes if n["id"] in keep)
