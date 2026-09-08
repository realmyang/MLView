"""Classify findings against a `ChangeSet` (CI-ADOPT part a).

The whole workspace is always analyzed - fidelity is the point, and a
per-file invocation is exactly the loss `core/coverage.single_file_diagnostic`
reports. Attribution happens **afterwards**, on the finished issue list:

| value      | when |
|------------|------|
| `new`      | the issue's **primary** loc sits inside an added hunk |
| `touched`  | the primary loc is in a changed file but outside the hunks, **or** a `relatedLoc` sits inside an added hunk |
| `existing` | neither |

The second half of `touched` is the one that earns its keep: a leak introduced
upstream of an untouched `fit()` site keeps the fit site's finding on the PR
that caused it.

**`--changed-only` keeps exactly the findings that intersect an added hunk** -
`new`, plus the `touched` whose evidence is inside one. It drops `existing`
and the other half of `touched`, the findings that merely share a file with
the change: on the measured PR fixture (7 lines appended to `train.py`) those
are 7 pre-existing findings on lines the pull request never saw, and failing a
gate on them is the adoption blocker CI-ADOPT exists to remove. `change`
stays a three-value **display** classification - a reviewer wants to know that
a file they edited also carries old findings - while `--changed-only` is the
**gate** filter. A leak whose `relatedLoc` lands in a hunk is `touched` and is
**never dropped**, which is the case the distinction was written for.

When attribution could not run at all, no issue carries `change`, nothing is
dropped, and a `config_warning` says why. "Unattributed, showing everything"
is the only acceptable failure mode: a gate that passes because git was
missing is worse than no gate.
"""

from __future__ import annotations

from typing import List, Optional

from ..core.graph import Diagnostic, MLGraph
from .gitdiff import ChangeSet

__all__ = ["CHANGE_VALUES", "CHANGE_NEW", "CHANGE_TOUCHED", "CHANGE_EXISTING",
           "classify_issue", "intersects_hunk", "apply_change_attribution"]

CHANGE_NEW = "new"
CHANGE_TOUCHED = "touched"
CHANGE_EXISTING = "existing"
#: The closed enum `Issue.change` may carry, mirrored in both schema copies.
CHANGE_VALUES = (CHANGE_NEW, CHANGE_TOUCHED, CHANGE_EXISTING)


def classify_issue(issue, changes: ChangeSet) -> str:
    """`new` / `touched` / `existing` for one issue against one change set."""
    loc = getattr(issue, "loc", None)
    primary_file = getattr(loc, "file", "") or ""
    primary_line = getattr(loc, "line", None)
    if changes.in_added(primary_file, primary_line):
        return CHANGE_NEW
    if _related_in_hunk(issue, changes):
        return CHANGE_TOUCHED
    if changes.is_changed(primary_file):
        return CHANGE_TOUCHED
    return CHANGE_EXISTING


def _related_in_hunk(issue, changes: ChangeSet) -> bool:
    for related in getattr(issue, "relatedLocs", ()) or ():
        if not isinstance(related, dict):       # pragma: no cover - defensive
            continue
        if changes.in_added(related.get("file", ""), related.get("line")):
            return True
    return False


def intersects_hunk(issue, changes: ChangeSet) -> bool:
    """True when any of the issue's own locations sits inside an added hunk.

    This - not `change != "existing"` - is what `--changed-only` keeps. Sharing
    a file with the change is proximity, not involvement.

    With a bare path list there are no hunks to intersect (`hunks_known` is
    False), so the best available answer is "in a changed file"; the run
    already carries a `config_warning` saying line attribution was unavailable.
    """
    loc = getattr(issue, "loc", None)
    primary_file = getattr(loc, "file", "") or ""
    if not changes.hunks_known:
        return changes.is_changed(primary_file)
    return (changes.in_added(primary_file, getattr(loc, "line", None))
            or _related_in_hunk(issue, changes))


def apply_change_attribution(graph: MLGraph, changes: Optional[ChangeSet],
                             changed_only: bool = False) -> List[Diagnostic]:
    """Stamp `Issue.change`, optionally drop `existing`, and report failures.

    Returns the diagnostics to append. The graph is mutated in place; the
    caller re-runs `finalize()` (and the ghost sweep, when issues were
    dropped) so every §1.1 invariant still holds.
    """
    if changes is None:
        return []
    if not changes.ok:
        return [_unattributed(changes, changed_only)]

    counts = {CHANGE_NEW: 0, CHANGE_TOUCHED: 0, CHANGE_EXISTING: 0}
    for issue in graph.issues:
        issue.change = classify_issue(issue, changes)
        counts[issue.change] += 1
    diagnostics: List[Diagnostic] = []
    if not changes.hunks_known:
        diagnostics.append(Diagnostic(
            kind="config_warning",
            message="%s carried file names but no diff hunks, so findings in a "
                    "changed file are reported as 'touched' and none as 'new'. "
                    "Pass the diff itself, or --changed-since <rev>, for "
                    "line-level attribution." % changes.source,
            count=len(changes.files)))
    if changed_only:
        kept = [i for i in graph.issues if intersects_hunk(i, changes)]
        dropped = [i for i in graph.issues if not intersects_hunk(i, changes)]
        nearby = sum(1 for i in dropped if i.change == CHANGE_TOUCHED)
        graph.issues = kept
        diagnostics.append(Diagnostic(
            kind="config_warning",
            message="--changed-only against %s: %d finding(s) that do not touch "
                    "the change are not shown - %d elsewhere in the workspace and "
                    "%d in a changed file but not on a changed line. %d shown (%d "
                    "new, %d touched), from %d changed file(s) and %d added "
                    "line(s). Re-run without --changed-only to see all of them."
                    % (changes.source, len(dropped), len(dropped) - nearby, nearby,
                       len(kept), sum(1 for i in kept if i.change == CHANGE_NEW),
                       sum(1 for i in kept if i.change == CHANGE_TOUCHED),
                       len(changes.files), changes.added_lines),
            count=len(dropped)))
    return diagnostics


def _unattributed(changes: ChangeSet, changed_only: bool) -> Diagnostic:
    """The degradation contract, in one diagnostic the user can act on."""
    tail = (" --changed-only had no effect: every finding is shown."
            if changed_only else "")
    return Diagnostic(
        kind="config_warning",
        message="change attribution is unavailable (%s): %s. Every finding is "
                "reported without a change class.%s"
                % (changes.source or "no diff", changes.reason, tail))
