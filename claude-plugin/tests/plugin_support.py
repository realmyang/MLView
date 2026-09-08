"""Test helpers for the Claude Code plugin suite.

Import these as ``from plugin_support import ...`` — never ``from conftest``.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_ROOT = os.path.join(REPO_ROOT, "claude-plugin")
SERVER_DIR = os.path.join(PLUGIN_ROOT, "server")
VENDOR_DIR = os.path.join(PLUGIN_ROOT, "vendor")
SERVER_SCRIPT = os.path.join(SERVER_DIR, "mlview_mcp.py")

STAGES = (
    ("config", "Configuration"), ("data", "Data"), ("preprocess", "Preprocess"),
    ("model", "Model"), ("objective", "Objective"), ("train", "Train"),
    ("eval", "Evaluate"), ("deliver", "Save / Deploy"),
)


def corpus_path() -> str:
    """The repo-relative corpus to analyze: the sample if it exists, else fixtures."""
    for rel in (
        "samples/vision_pipeline",
        "analyzer/tests/fixtures/rules",
        "analyzer/tests/fixtures",
    ):
        if os.path.isdir(os.path.join(REPO_ROOT, rel.replace("/", os.sep))):
            return rel
    raise AssertionError("no analyzable corpus in the repository")


def child_env(**extra: str) -> Dict[str, str]:
    """The environment CONTRACTS section 3 requires for every CLI/server spawn.

    ``PYTHONDONTWRITEBYTECODE`` is set because these spawns import the core out of
    ``claude-plugin/vendor``, and `claude plugin install` copies that tree
    verbatim: a test run must not leave 48 .pyc files behind for the packaged
    plugin to ship (``tools/sync-core.py --check`` fails when they are there).
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (VENDOR_DIR, os.path.join(REPO_ROOT, "analyzer", "src")) if p
    )
    env["MLVIEW_PROJECT_DIR"] = REPO_ROOT
    env["MLVIEW_NO_OPEN"] = "1"
    env.update(extra)
    return env


def _loc(index: int) -> Dict[str, Any]:
    line = (index % 400) + 1
    return {
        "file": "pkg/mod_%02d.py" % (index % 12),
        "absFile": "C:/synthetic/pkg/mod_%02d.py" % (index % 12),
        "line": line,
        "col": 4,
        "endLine": line,
        "endCol": 40,
        "symbol": "call_%d" % index,
        "snippet": "    result_%d = call_%d(argument_%d, keyword=%d)" % (index, index, index, index),
    }


def synthetic_graph(
    nodes: int = 500, edges: int = 800, issues: int = 300
) -> Dict[str, Any]:
    """A large, schema-shaped document for the payload-budget tests.

    It is deliberately verbose — long labels, long messages, many related
    locations — because the budget only matters when the honest payload would
    overflow it.
    """
    node_list: List[Dict[str, Any]] = []
    for index in range(nodes):
        stage = STAGES[index % len(STAGES)][0]
        node_list.append(
            {
                "id": "n:%012x" % index,
                "kind": "unknown" if index % 7 else "train_loop",
                "level": "op" if index % 3 else "unit",
                "stage": stage,
                "label": "a_rather_long_synthetic_node_label_number_%d" % index,
                "sublabel": "synthetic sublabel with attributes lr=1e-3 · wd=0 · n=%d" % index,
                "qualname": "pkg.mod_%02d.function_%d.symbol_%d" % (index % 12, index, index),
                "fqn": "torch.nn.Module.forward",
                "framework": "torch",
                "loc": _loc(index),
                "parent": None if index % 5 == 0 else "n:%012x" % (index - index % 5),
                "attrs": {"batch_size": "128", "num_workers": "4"},
                "produces": [{"name": "value_%d" % index, "tags": ["BATCH"]}],
                "consumes": [{"name": "input_%d" % index, "tags": ["LOADER"]}],
                "ghost": False,
                "dynamic": bool(index % 11 == 0),
                "confidence": 0.9,
                "confidenceBucket": "certain",
                "issueIds": ["i:%012x" % (index % issues)] if index % 3 == 0 else [],
                "collapsedByDefault": False,
                "stageEvidence": [
                    {
                        "kind": "knowledge_table",
                        "detail": "torch.nn.Module.forward -> %s (synthetic evidence row)" % stage,
                        "weight": 1.0,
                    }
                ],
            }
        )

    edge_list: List[Dict[str, Any]] = []
    for index in range(edges):
        source = index % nodes
        target = (index * 7 + 3) % nodes
        edge_list.append(
            {
                "id": "e:%012x" % index,
                "kind": ("data", "call", "control", "config")[index % 4],
                "source": "n:%012x" % source,
                "target": "n:%012x" % target,
                "label": "variable_name_%d" % index,
                "loc": _loc(index),
                "tags": ["BATCH"],
                "confidence": 0.9,
                "issueIds": [],
            }
        )

    severities = ("low", "medium", "high")
    issue_list: List[Dict[str, Any]] = []
    for index in range(issues):
        severity = severities[index % 3]
        issue_list.append(
            {
                "id": "i:%012x" % index,
                "code": "MLV%03d" % (101 + (index % 20)),
                "ruleVersion": 1,
                "severity": severity,
                "confidence": 0.6 + (index % 4) * 0.1,
                "confidenceBucket": "certain",
                "title": "A synthetic finding with a deliberately long title number %d" % index,
                "message": (
                    "The synthetic batch loop at pkg/mod_%02d.py:%d calls backward() and step() "
                    "but never zero_grad(); this message is long on purpose so the payload "
                    "budget is exercised rather than merely asserted." % (index % 12, index % 400 + 1)
                ),
                "why": "The consequence of finding %d, stated in one long ML sentence." % index,
                "fixHint": "Call the real API here, naming it explicitly, for finding %d." % index,
                "loc": _loc(index),
                "relatedLocs": [
                    dict(_loc(index + 1), role="split_site", message="related site one"),
                    dict(_loc(index + 2), role="fit_site", message="related site two"),
                ],
                "nodeIds": ["n:%012x" % (index % nodes)],
                "edgeIds": [],
                "stage": STAGES[index % len(STAGES)][0],
                "frameworks": ["torch"],
                "tags": ["correctness", "synthetic"],
                "evidence": [
                    {"kind": "fqn_resolved", "detail": "synthetic evidence %d" % index, "weight": 1.0}
                ],
                "suppressed": bool(index % 25 == 0),
                "docs": "docs/rules/MLV%03d.md" % (101 + (index % 20)),
            }
        )

    counts = {"low": 0, "medium": 0, "high": 0}
    for issue in issue_list:
        counts[issue["severity"]] += 1

    stage_rows = []
    for order, (sid, label) in enumerate(STAGES):
        members = [n for n in node_list if n["stage"] == sid]
        stage_issues = [i for i in issue_list if i["stage"] == sid]
        row_counts = {"low": 0, "medium": 0, "high": 0}
        for issue in stage_issues:
            row_counts[issue["severity"]] += 1
        stage_rows.append(
            {
                "id": sid, "label": label, "order": order, "present": bool(members),
                "nodeCount": len(members), "issueCounts": row_counts,
                "maxSeverity": next((s for s in ("high", "medium", "low") if row_counts[s]), None),
            }
        )

    return {
        "schemaVersion": "1.0",
        "generator": {
            "name": "mlview", "version": "0.1.0",
            "rendererSha": "0" * 64, "generatedAt": "2026-09-07T00:00:00Z",
        },
        "workspace": {
            "root": "C:/synthetic/a/deliberately/long/workspace/root/path/for/the/budget/test",
            "entrypoints": ["pkg/mod_00.py", "pkg/mod_01.py", "pkg/mod_02.py"],
            "filesAnalyzed": 12, "filesFailed": 0, "notebooksSkipped": 3,
            "frameworks": ["torch", "sklearn", "numpy", "pandas", "torchvision"],
        },
        "stages": stage_rows,
        "nodes": node_list,
        "edges": edge_list,
        "issues": issue_list,
        "diagnostics": [
            {"kind": "notebook_skipped", "message": "3 notebooks were not analyzed", "count": 3}
        ],
        "stats": {
            "nodes": len(node_list), "edges": len(edge_list), "issues": counts,
            "suppressed": sum(1 for i in issue_list if i["suppressed"]),
            "durationMs": 1234, "truncated": False,
        },
    }


__all__ = [
    "REPO_ROOT", "PLUGIN_ROOT", "SERVER_DIR", "VENDOR_DIR", "SERVER_SCRIPT",
    "corpus_path", "child_env", "synthetic_graph",
]
