#!/usr/bin/env python
"""The half of the compared digest this driver owns (HEALTH-02, 11.30).

`digest_of` in `gen_scope_fixtures.py` and `digestOf` in
`webview/test/scope_fuzz.test.mjs` are one shape written twice, and the Sprint-5
fields - PERF-04's `rolledUp` and `weight`, MLV-P12's `pipelines[]` - are not in
it. Rather than fork that shape, the fuzz driver probes it and compares whatever
it does not carry through an `_extras` block of its own, built here and by
`extrasOf` in the harness from the same rule. Either way each field is compared
exactly once.

Split out of `scope_fuzz.py` so that file stays a driver: build a batch, run one
node process, compare, minimize, promote.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
for _path in (HERE, os.path.join(REPO, "analyzer", "src"),
              os.path.join(REPO, "contracts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import gen_scope_fixtures                                       # noqa: E402
from gen_scope_fixtures import digest_of, outcome_of            # noqa: E402
import scope_gen_projections as projections                     # noqa: E402

__all__ = ["digest_extras", "extras_of", "outcome_with_extras"]


def digest_extras(log=None) -> List[str]:
    """Which of PERF-04's and MLV-P12's fields THIS driver must compare itself.

    `digest_of` in `gen_scope_fixtures.py` and `digestOf` in the harness are one
    shape written twice, and neither is mine to extend unilaterally. So the
    driver *probes* the Python twin with sentinel values: a field the twin
    already carries is compared by the twin, in the twin's own layout, and this
    driver keeps its hands off it; a field the twin does not carry is compared
    through the `_extras` block that `extras_of` and the harness both build from
    this file's rule. Either way the field is checked exactly once.
    """
    probe = {
        "nodes": [{"id": "n:probe", "viewRole": "core", "issueIds": [],
                   "rolledUp": 424242}],
        "edges": [{"id": "e:probe", "issueIds": [], "weight": 313131}],
        "issues": [], "stages": [], "stats": {}, "view": None,
        "pipelines": [{"id": "p:probe", "entrypoint": "probe191919.py"}],
    }
    try:
        text = json.dumps(digest_of(probe), default=str)
    except Exception:                              # a twin that cannot take it
        return list(projections.DIGEST_EXTRAS)
    covered = {"rolledUp": "424242" in text, "weight": "313131" in text,
               "pipelines": "probe191919" in text}
    if log:
        for name, is_covered in sorted(covered.items()):
            if is_covered:
                log("  NOTE: gen_scope_fixtures.digest_of now carries %r - "
                    "webview/test/scope_fuzz.test.mjs's digestOf must mirror its "
                    "layout, and this driver no longer compares it separately"
                    % name)
    return [name for name in projections.DIGEST_EXTRAS if not covered[name]]


def extras_of(doc: Dict[str, Any], extras: Sequence[str]) -> Dict[str, Any]:
    """The `_extras` block - the JavaScript twin is `extrasOf` in the harness.

    Only the *requested* keys appear, so a repository that has landed neither
    PERF-04 nor MLV-P12 produces `{"rolledUp": [], "weight": [], "pipelines":
    null}` on both sides and nothing is silently skipped.
    """
    out: Dict[str, Any] = {}
    if "rolledUp" in extras:
        out["rolledUp"] = [[n["id"], n["rolledUp"]] for n in doc.get("nodes") or []
                           if "rolledUp" in n]
    if "weight" in extras:
        out["weight"] = [[e["id"], e["weight"]] for e in doc.get("edges") or []
                         if "weight" in e]
    if "pipelines" in extras:
        out["pipelines"] = doc.get("pipelines")
    return out


def outcome_with_extras(graph: Dict[str, Any], spec: str, depth: Optional[int],
             extras: Sequence[str]) -> Dict[str, Any]:
    """`outcome_of` - the shared one, never a second copy of its control flow -
    with the `_extras` block appended to a successful projection."""
    out = outcome_of(graph, spec, depth)
    if not extras or out.get("kind") != "project":
        return out
    scope = gen_scope_fixtures.parse_scope(spec, depth)
    out["digest"]["_extras"] = extras_of(gen_scope_fixtures.project(graph, scope),
                                         extras)
    return out

