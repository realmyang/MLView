"""`mlview.api` - the FROZEN in-process entry point (CONTRACTS section 3).

    from mlview.api import analyze, analyze_to_dict, AnalyzeOptions, MLGraph

The MCP server and the VS Code helper both come through here rather than
shelling out to the CLI, so argument handling cannot diverge; `tools/verify.py`
proves the two outputs match anyway.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence

from .core.graph import MLGraph
from .core.pipeline import AnalysisResult, AnalyzeOptions, run
from .core.project import (CONCERN_ALIASES, CONCERNS, SCOPE_KINDS, Scope,
                           ScopeError, ScopeResolution, parse_scope, project,
                           resolve_scope, scope_catalog)
from .emit import html_out, json_out, mermaid_out, text_out
from .version import SCHEMA_VERSION, __version__

__all__ = [
    "AnalyzeOptions", "MLGraph", "analyze", "analyze_to_dict", "analyze_full",
    "render_html", "render_mermaid", "render_text", "render_summary", "digest",
    "schema_path", "sample_path", "schema_text", "demo_dict", "demo_bytes",
    "__version__", "SCHEMA_VERSION",
    # scoped views (CONTRACTS 11.6) - additive
    "CONCERNS", "CONCERN_ALIASES", "SCOPE_KINDS", "Scope", "ScopeError",
    "ScopeResolution", "parse_scope", "resolve_scope", "project", "scope_catalog",
]

_SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema")


# ---------------------------------------------------------------- analysis
def analyze(options: AnalyzeOptions) -> MLGraph:
    """Analyze a workspace and return the graph object.

    Always the **FULL** workspace graph, even when `options.scope` is set: a
    scope is a document-level projection (CONTRACTS 11.2), applied by
    `analyze_to_dict()` / `project()`, never a smaller analysis.
    """
    return run(options).graph


def analyze_full(options: AnalyzeOptions) -> AnalysisResult:
    """Analyze and return the graph plus the IR (used by tests and `explain`)."""
    return run(options)


def analyze_to_dict(options: AnalyzeOptions) -> Dict[str, Any]:
    """Schema-valid, canonically ordered document.

    With `options.scope` set, the returned document is the **projection** and
    carries `view`; without it the bytes are exactly what they were before
    this feature existed - no `view` key.
    """
    doc = analyze(options).to_dict()
    if getattr(options, "scope", None):
        return project(doc, parse_scope(options.scope, getattr(options, "depth", None)))
    return doc


# ----------------------------------------------------------------- render
def render_html(graph: Dict[str, Any], out_path: str,
                scope: Optional[str] = None, depth: Optional[int] = None) -> str:
    """Write the self-contained report; returns the absolute path written.

    `graph` is always the **FULL** document: with a scope, the report embeds
    the whole graph and opens *at* that scope through the two root-element
    attributes (`data-mlview-scope` / `data-mlview-depth`, CONTRACTS 11.8), so
    the viewer runs one code path in every host and can widen for free.
    """
    return html_out.write_html(graph, out_path, scope=scope, depth=depth)


def render_mermaid(graph: Dict[str, Any]) -> str:
    return mermaid_out.render_mermaid(graph)


def render_text(graph: Dict[str, Any]) -> str:
    return text_out.render_text(graph)


def render_summary(graph: Dict[str, Any], show_suppressed: bool = False,
                   group_by: str = "none") -> str:
    """`group_by` (RAIL-GROUP) is appended last and defaulted to `none`, so the
    frozen two-argument call still returns exactly what it always returned."""
    return text_out.render_summary(graph, show_suppressed=show_suppressed,
                                   group_by=group_by)


# ----------------------------------------------------------------- digest
def digest(graph: Dict[str, Any], limit_bytes: int = 4096) -> Dict[str, Any]:
    """The <=4 KB model-facing summary. Full detail lives behind `graphPath`."""
    ws = graph.get("workspace", {})
    stats = graph.get("stats", {})
    lanes = [{"stage": s["id"], "label": s["label"], "nodeCount": s.get("nodeCount", 0),
              "maxSeverity": s.get("maxSeverity")}
             for s in graph.get("stages", []) if s.get("present")]
    issues = [i for i in graph.get("issues", []) if not i.get("suppressed")]
    top = [{"code": i.get("code"), "severity": i.get("severity"),
            "confidenceBucket": i.get("confidenceBucket"), "title": i.get("title"),
            "file": i.get("loc", {}).get("file"), "line": i.get("loc", {}).get("line")}
           for i in issues[:10]]
    out: Dict[str, Any] = {
        "schemaVersion": graph.get("schemaVersion", SCHEMA_VERSION),
        "root": ws.get("root", ""),
        "filesAnalyzed": ws.get("filesAnalyzed", 0),
        "filesFailed": ws.get("filesFailed", 0),
        "notebooksSkipped": ws.get("notebooksSkipped", 0),
        "frameworks": list(ws.get("frameworks") or []),
        "stats": {"nodes": stats.get("nodes", 0), "edges": stats.get("edges", 0),
                  "issues": stats.get("issues", {"low": 0, "medium": 0, "high": 0})},
        "lanes": lanes,
        "topIssues": top,
        "truncated": bool(stats.get("truncated")),
    }
    view = graph.get("view")
    if isinstance(view, dict):                       # CONTRACTS 11.6, ~110 bytes
        spec = view.get("scope", "")
        kind, _, target = spec.partition(":")
        out["scope"] = {
            "spec": spec, "kind": kind or "all", "target": target,
            "depth": view.get("depth", 0),
            "nodesInScope": stats.get("nodes", 0),
            "nodesTotal": view.get("of", {}).get("nodes", stats.get("nodes", 0)),
        }
    while _size(out) > limit_bytes and out["topIssues"]:
        out["topIssues"].pop()
        out["truncatedDigest"] = True
    while _size(out) > limit_bytes and out["lanes"]:
        out["lanes"].pop()
        out["truncatedDigest"] = True
    return out


def _size(payload: Dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


# ----------------------------------------------------------------- schema
def schema_path() -> str:
    return os.path.join(_SCHEMA_DIR, "graph.schema.json").replace("\\", "/")


def sample_path() -> str:
    return os.path.join(_SCHEMA_DIR, "graph.sample.json").replace("\\", "/")


def schema_text() -> bytes:
    """The schema exactly as shipped (byte-identical to `contracts/`)."""
    with open(schema_path(), "rb") as fh:
        return fh.read()


def demo_bytes() -> bytes:
    """The golden sample exactly as shipped (`analyze --demo`)."""
    with open(sample_path(), "rb") as fh:
        return fh.read()


def demo_dict() -> Dict[str, Any]:
    return json.loads(demo_bytes().decode("utf-8-sig"))
