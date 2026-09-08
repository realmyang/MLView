#!/usr/bin/env python
"""Gate 5 — one projection, two languages (CONTRACTS 11.2 / 11.15).

Split out of ``tools/verify.py`` so that file stays a gate *table* rather than a
gate implementation; ``verify.py --scopes`` and ``--all`` call ``check_scopes``
from here.

Feature 2 is one algorithm written twice — ``analyzer/src/mlview/core/project.py``
in Python, ``webview/src/scope/project.ts`` in TypeScript — because the CLI must
project without a browser and the standalone report must re-scope without an
analyzer. Two implementations of one specification drift; the only question is
whether anyone finds out.

So the battery is **data**: ``contracts/scope.cases.json`` names ten selectors and
six error codes, ``contracts/scope.expected.json`` holds what the Python
``project()`` produces for each, and both are computed over the **frozen**
``contracts/graph.sample.json`` so a rule change can never redden this gate. Two
steps, reported as two rows so a red table says which half moved:

1. ``analyzer/tools/gen_scope_fixtures.py --check`` regenerates the fixtures from
   the Python side and byte-diffs them, writing nothing.
2. ``node --test test/scope_parity.test.mjs`` in ``webview/`` pushes the same
   cases through the port and deep-compares the node, edge and issue id lists in
   order, every ``issue.nodeIds`` (so the stable rotation is checked), every
   node's ``viewRole``, all eight stage rows, ``stats``, and the whole ``view``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Callable, Dict, List, Tuple

Result = Tuple[str, bool, str]  # (gate name, passed, detail) — verify.py's shape

PARITY_TEST = "test/scope_parity.test.mjs"


def _tap_count(text: str, marker: str) -> int:
    """`# pass 24` -> 24. Node's run summary, read without a parser.

    Node prints that summary two ways and which one you get is not a flag we
    set: the TAP reporter writes `# pass 24`, and the `spec` reporter -- the
    default on a non-TTY stdout since Node 20 -- writes `\u2139 pass 24`. Reading
    only the TAP spelling made the row report "(0 assertions)" on a machine
    whose Node had moved on, which is a gate quietly understating its own work.
    Both spellings are accepted; a run that matches neither still counts 0, and
    the row still fails on a non-zero exit.
    """
    markers = (marker, marker.replace("# ", "\u2139 ", 1))
    for line in text.splitlines():
        stripped = line.strip()
        for m in markers:
            if stripped.startswith(m):
                try:
                    return int(stripped[len(m):].strip())
                except ValueError:
                    return 0
    return 0


def battery_shape(repo_root: str) -> str:
    """"10 projections + 6 error cases" — read from the battery, never hard-coded."""
    try:
        with open(os.path.join(repo_root, "contracts", "scope.cases.json"),
                  "r", encoding="utf-8") as fh:
            cases = json.load(fh).get("cases") or []
    except (OSError, ValueError):
        return "the scope battery"
    projections = sum(1 for c in cases if c.get("kind") == "project")
    return "%d projections + %d error cases" % (projections, len(cases) - projections)


def _node_available(repo_root: str, env: Dict[str, str]) -> bool:
    try:
        proc = subprocess.run(
            ["node", "--version"], cwd=repo_root, env=env,
            capture_output=True, shell=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


def check_scopes(
    repo_root: str,
    cli_env: Callable[[], Dict[str, str]],
    base_env: Callable[[], Dict[str, str]],
) -> List[Result]:
    """The two rows. ``cli_env`` runs Python against ``analyzer/src``; ``base_env``
    runs node with no ``PYTHONPATH`` of ours on it."""
    results: List[Result] = []

    generator = os.path.join(repo_root, "analyzer", "tools", "gen_scope_fixtures.py")
    if not os.path.isfile(generator):
        return [(
            "scopes: fixtures", False,
            "analyzer/tools/gen_scope_fixtures.py is missing — the battery cannot "
            "be regenerated",
        )]
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", generator, "--check"],
        cwd=repo_root, env=cli_env(), capture_output=True, shell=False,
    )
    lines = (proc.stdout or proc.stderr).decode("utf-8", "replace").strip().splitlines()
    summary = lines[-1] if lines else ""
    if proc.returncode != 0:
        results.append((
            "scopes: fixtures", False,
            "contracts/scope.*.json drifted from the Python project() — run "
            "`python analyzer/tools/gen_scope_fixtures.py`%s"
            % ((" (%s)" % summary) if summary else ""),
        ))
    else:
        results.append(("scopes: fixtures", True, summary or "current"))

    webview = os.path.join(repo_root, "webview")
    if not os.path.isfile(os.path.join(webview, PARITY_TEST.replace("/", os.sep))):
        results.append((
            "scopes: python == ts", False,
            "webview/%s is missing — the TypeScript half of the gate is not wired"
            % PARITY_TEST,
        ))
        return results

    env = base_env()
    if not _node_available(repo_root, env):
        results.append((
            "scopes: python == ts", False,
            "no `node` on PATH — cannot run the viewer half of the gate",
        ))
        return results

    proc = subprocess.run(
        ["node", "--test", PARITY_TEST],
        cwd=webview, env=env, capture_output=True, shell=False,
    )
    text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    passed = _tap_count(text, "# pass ")
    failed = _tap_count(text, "# fail ")
    if proc.returncode != 0 or failed:
        first = next(
            (l.strip() for l in text.splitlines() if l.strip().startswith("not ok")), ""
        )
        results.append((
            "scopes: python == ts", False,
            "%d of %d assertions differ%s — the TypeScript project() did not follow "
            "the Python one" % (failed, passed + failed, (": %s" % first) if first else ""),
        ))
    else:
        results.append((
            "scopes: python == ts", True,
            "%s, python == typescript (%d assertions)" % (battery_shape(repo_root), passed),
        ))
    return results


__all__ = ["check_scopes", "battery_shape", "Result", "PARITY_TEST"]
