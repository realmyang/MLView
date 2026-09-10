"""The `unresolved_callee` diagnostic (ANA-5a).

CONTRACTS 11.18 reserved the `unresolved_callee` kind with the note *"no -
reserved"*. This is its emitter.

The failure it ends, measured on the hostile-syntax corpus: an odd-syntax file
lost its **entire training step** - `model = Net()` through a factory, the
criterion, the optimizer via a `match` dispatch, `backward()` and `step()` -
and reported `dynamic: 0` on every node it did keep. Nothing in the document
said the analyzer had given up, so a file MLView could not read and a file
MLView had read and found clean produced the same green answer.

The diagnostic follows 11.18's C1 shape exactly, and for the same reason: **one
row per `(file, scope)`**, never one per site. A dispatch table called in a loop
would otherwise emit a diagnostic per iteration, and the constructs that
defeated the analyzer in one function belong on one line.

What it does **not** do is as important. It never sets
`ScopeIR.mark_dynamic`: `rules/confidence.DYNAMIC_FACTOR` is 0.7 and applies to
every finding in a scope, so widening the scope flag to cover a lambda in one
statement would silently drop unrelated findings a confidence bucket. ANA-5a is
per call, and `samples/vision_pipeline`'s fifteen findings keep their exact
confidence values because of it.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .graph import Diagnostic

__all__ = ["UNRESOLVED_KIND", "unresolved_callee_diagnostics",
           "unresolved_call_count"]

UNRESOLVED_KIND = "unresolved_callee"

#: How many constructs one message names before it says "and N more".
_NAMED_SITES = 3


def _iter_unresolved(workspace):
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        for call in module.calls:
            if not call.unresolved_callee:
                continue
            yield relpath, call


def unresolved_call_count(workspace) -> int:
    """How many call sites the analyzer could not resolve a callee for."""
    return sum(1 for _relpath, _call in _iter_unresolved(workspace))


def _site_text(short: str, line: int, construct: str) -> str:
    """One site, named by its callee when the callee has a name to give.

    A subscript callee (`BUILDERS[kind]()`) has no name at all, and printing
    `call(...)` for it would invent one - so it is described rather than named.
    """
    if short and short != "call":
        return "`%s(...)` at line %d is %s" % (short, line, construct)
    return "the call at line %d has %s as its callee" % (line, construct)


def _message(scope: str, sites: Sequence[Tuple[str, int, str]]) -> str:
    ordered = sorted(sites, key=lambda s: (s[1], s[0]))
    named = "; ".join(_site_text(*row) for row in ordered[:_NAMED_SITES])
    rest = ordered[_NAMED_SITES:]
    more = ""
    if rest:
        # The site list is bounded (11.18 C1), but the **constructs** are the
        # point: a reader must be able to see that a `match` and a
        # `default_factory` were among them without opening the file.
        unnamed: List[str] = []
        already = {row[2] for row in ordered[:_NAMED_SITES]}
        for row in rest:
            if row[2] not in already and row[2] not in unnamed:
                unnamed.append(row[2])
        more = " and %d more" % len(rest)
        if unnamed:
            more += " (%s)" % ", ".join(unnamed)
    return ("MLView could not resolve %d call%s in %s: %s%s. Each one is drawn as "
            "an `unknown` op rather than dropped, and any stage those calls "
            "belong to may be present without being detected - a gap in "
            "coverage, not a clean result."
            % (len(ordered), "" if len(ordered) == 1 else "s",
               scope or "this scope", named, more))


def unresolved_callee_diagnostics(workspace) -> List[Diagnostic]:
    """One `unresolved_callee` diagnostic per `(file, scope)`, in sort order."""
    sites: Dict[Tuple[str, str], List[Tuple[str, int, str]]] = {}
    order: List[Tuple[str, str]] = []
    for relpath, call in _iter_unresolved(workspace):
        key = (relpath, call.scope.qualname if call.scope is not None else "")
        if key not in sites:
            sites[key] = []
            order.append(key)
        sites[key].append((call.short_name or "call", call.loc.line,
                           call.unresolved_callee))
    out: List[Diagnostic] = []
    for relpath, scope in order:
        rows = sites[(relpath, scope)]
        out.append(Diagnostic(
            kind=UNRESOLVED_KIND, message=_message(scope, rows),
            file=relpath or None, line=min(line for _s, line, _c in rows) or None,
            scope=scope or None, count=len(rows)))
    return out


def unresolved_note(count: int) -> Optional[str]:
    """The qualifier the summary appends to its "not detected" line."""
    if count <= 0:
        return None
    return (" (unverified: %d call%s could not be resolved, so a stage may be "
            "present but undetected)" % (count, "" if count == 1 else "s"))
