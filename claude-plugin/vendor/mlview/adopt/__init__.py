"""CI adoption: change attribution, the baseline ratchet and SARIF (CI-ADOPT).

Three mechanisms that let MLView be turned on for the first time on a repo that
already has findings, without asking anybody to fix 111 of them first:

* `gitdiff` turns `git diff -M --unified=0 <rev>` (or a diff a CI runner
  already has) into per-file **added-line ranges**;
* `attribute` classifies every issue the whole-workspace analysis produced as
  `new` / `touched` / `existing` against those ranges;
* `baseline` records today's findings and marks them on a later run, so the
  ratchet only ever tightens.

The invariant all three share: **a failure degrades to "unattributed, showing
everything" with a diagnostic**, never to an error and never to an empty list.
A tool that reports nothing because git was missing is worse than one that
reports everything.
"""

from __future__ import annotations

from .attribute import (CHANGE_VALUES, apply_change_attribution, classify_issue)
from .baseline import (BASELINE_VERSION, DEFAULT_BASELINE_PATH,
                       apply_baseline, build_baseline, load_baseline,
                       snippet_hash, write_baseline)
from .gitdiff import ChangeSet, changed_from_file, changed_from_rev

__all__ = [
    "ChangeSet", "changed_from_rev", "changed_from_file",
    "CHANGE_VALUES", "classify_issue", "apply_change_attribution",
    "BASELINE_VERSION", "DEFAULT_BASELINE_PATH", "snippet_hash",
    "build_baseline", "write_baseline", "load_baseline", "apply_baseline",
]
