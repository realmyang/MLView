"""The MLGraph document model and its canonical serialization.

Key order matches `contracts/graph.schema.json`; array order matches the
CONTRACTS section 0 ordering rules. `to_dict()` output is what
`emit/json_out.py` writes and what the schema validates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..ir.model import Loc
from ..knowledge import STAGE_IDS, STAGE_LABELS
from ..version import GENERATOR_NAME, SCHEMA_VERSION, __version__, renderer_sha

__all__ = [
    "Evidence", "Port", "Node", "Edge", "Issue", "StageSummary", "Diagnostic",
    "MLGraph", "bucket_for", "STAGE_ORDER", "SEVERITY_RANK", "clamp_confidence",
]

STAGE_ORDER = {sid: i for i, sid in enumerate(STAGE_IDS)}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
_BUCKETS = ((0.9, "certain"), (0.7, "likely"), (0.5, "possible"), (0.0, "speculative"))
CONFIDENCE_DIGITS = 3


def clamp_confidence(value: float) -> float:
    """Clamp to [0.05, 0.99] and round, so the JSON is byte-deterministic."""
    value = max(0.05, min(0.99, float(value)))
    return round(value, CONFIDENCE_DIGITS)


def bucket_for(confidence: float) -> str:
    for floor, name in _BUCKETS:
        if confidence >= floor:
            return name
    return "speculative"


@dataclass(frozen=True)
class Evidence:
    kind: str
    detail: str
    weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "weight": round(self.weight, 3)}


@dataclass(frozen=True)
class Port:
    name: str
    tags: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "tags": list(self.tags)}


@dataclass
class Node:
    id: str
    kind: str
    level: str
    stage: str
    label: str
    qualname: str
    loc: Loc
    sublabel: Optional[str] = None
    fqn: Optional[str] = None
    framework: Optional[str] = None
    var: Optional[str] = None
    defLoc: Optional[Loc] = None
    parent: Optional[str] = None
    attrs: Dict[str, str] = field(default_factory=dict)
    produces: List[Port] = field(default_factory=list)
    consumes: List[Port] = field(default_factory=list)
    ghost: bool = False
    dynamic: bool = False
    confidence: float = 0.9
    issueIds: List[str] = field(default_factory=list)
    collapsedByDefault: bool = False
    stageEvidence: List[Evidence] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "level": self.level,
            "stage": self.stage,
            "label": self.label,
        }
        if self.sublabel:
            out["sublabel"] = self.sublabel
        out["qualname"] = self.qualname
        if self.fqn:
            out["fqn"] = self.fqn
        if self.framework:
            out["framework"] = self.framework
        if self.var:
            out["var"] = self.var
        out["loc"] = self.loc.to_dict()
        if self.defLoc is not None:
            out["defLoc"] = self.defLoc.to_dict()
        out["parent"] = self.parent
        out["attrs"] = {k: self.attrs[k] for k in sorted(self.attrs)}
        out["produces"] = [p.to_dict() for p in self.produces]
        out["consumes"] = [p.to_dict() for p in self.consumes]
        out["ghost"] = self.ghost
        out["dynamic"] = self.dynamic
        confidence = clamp_confidence(self.confidence)
        out["confidence"] = confidence
        out["confidenceBucket"] = bucket_for(confidence)
        out["issueIds"] = list(self.issueIds)
        out["collapsedByDefault"] = self.collapsedByDefault
        out["stageEvidence"] = [e.to_dict() for e in self.stageEvidence]
        return out

    @property
    def sort_key(self):
        return (STAGE_ORDER.get(self.stage, 99), self.loc.file, self.loc.line,
                self.loc.col, self.id)


@dataclass
class Edge:
    id: str
    kind: str
    source: str
    target: str
    loc: Loc
    subkind: Optional[str] = None
    label: Optional[str] = None
    tags: Tuple[str, ...] = ()
    confidence: float = 0.9
    issueIds: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"id": self.id, "kind": self.kind}
        if self.subkind and self.kind == "control":
            out["subkind"] = self.subkind
        out["source"] = self.source
        out["target"] = self.target
        if self.label:
            out["label"] = self.label
        out["loc"] = self.loc.to_dict()
        out["tags"] = list(self.tags)
        out["confidence"] = clamp_confidence(self.confidence)
        out["issueIds"] = list(self.issueIds)
        return out

    @property
    def sort_key(self):
        return (self.source, self.kind, self.target, self.id)


@dataclass
class Issue:
    id: str
    code: str
    ruleVersion: int
    severity: str
    confidence: float
    title: str
    message: str
    why: str
    fixHint: str
    loc: Loc
    stage: str
    relatedLocs: List[Dict[str, Any]] = field(default_factory=list)
    nodeIds: List[str] = field(default_factory=list)
    edgeIds: List[str] = field(default_factory=list)
    frameworks: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    evidence: List[Evidence] = field(default_factory=list)
    suppressed: bool = False
    docs: str = ""
    #: CI-ADOPT, both appended last and defaulted so every existing positional
    #: construction still works, and both emitted **only when set** so a run
    #: without `--baseline` / `--changed-since` is byte-identical to what it
    #: was before the flags existed.
    #: `baselined` - matched an entry in the baseline file: still emitted, and
    #: excluded from the rendered counts and from `--fail-on`.
    baselined: bool = False
    #: `change` - `new` / `touched` / `existing` against a diff.
    change: Optional[str] = None

    @property
    def confidenceBucket(self) -> str:
        return bucket_for(clamp_confidence(self.confidence))

    def to_dict(self) -> Dict[str, Any]:
        confidence = clamp_confidence(self.confidence)
        out: Dict[str, Any] = {
            "id": self.id,
            "code": self.code,
            "ruleVersion": self.ruleVersion,
            "severity": self.severity,
            "confidence": confidence,
            "confidenceBucket": bucket_for(confidence),
            "title": self.title,
            "message": self.message,
            "why": self.why,
            "fixHint": self.fixHint,
            "loc": self.loc.to_dict(),
            "relatedLocs": list(self.relatedLocs),
            "nodeIds": list(self.nodeIds),
            "edgeIds": list(self.edgeIds),
            "stage": self.stage,
            "frameworks": list(self.frameworks),
            "tags": list(self.tags),
            "evidence": [e.to_dict() for e in self.evidence],
            "suppressed": self.suppressed,
        }
        if self.baselined:
            out["baselined"] = True
        if self.change:
            out["change"] = self.change
        out["docs"] = self.docs or ("docs/rules/%s.md" % self.code)
        return out

    @property
    def sort_key(self):
        return (-SEVERITY_RANK.get(self.severity, 0), self.loc.file, self.loc.line,
                self.code, self.id)


@dataclass
class StageSummary:
    id: str
    label: str
    order: int
    present: bool = False
    nodeCount: int = 0
    issueCounts: Dict[str, int] = field(default_factory=lambda: {"low": 0, "medium": 0, "high": 0})
    maxSeverity: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "order": self.order,
            "present": self.present,
            "nodeCount": self.nodeCount,
            "issueCounts": {"low": self.issueCounts.get("low", 0),
                            "medium": self.issueCounts.get("medium", 0),
                            "high": self.issueCounts.get("high", 0)},
            "maxSeverity": self.maxSeverity,
        }


@dataclass
class Diagnostic:
    kind: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    scope: Optional[str] = None
    ruleCode: Optional[str] = None
    codes: Optional[Sequence[str]] = None
    count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"kind": self.kind, "message": self.message}
        if self.file:
            out["file"] = self.file
        if self.line:
            out["line"] = self.line
        if self.scope:
            out["scope"] = self.scope
        if self.ruleCode:
            out["ruleCode"] = self.ruleCode
        if self.codes:
            out["codes"] = list(self.codes)
        if self.count is not None:
            out["count"] = self.count
        return out

    @property
    def sort_key(self):
        return (self.kind, self.file or "", self.line or 0, self.message)


@dataclass
class MLGraph:
    """The complete document."""

    root: str
    entrypoints: List[str] = field(default_factory=list)
    filesAnalyzed: int = 0
    filesFailed: int = 0
    notebooksSkipped: int = 0
    frameworks: Tuple[str, ...] = ()
    configPath: Optional[str] = None
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    stages: List[StageSummary] = field(default_factory=list)
    truncated: bool = False
    durationMs: int = 0
    generatedAt: str = "1970-01-01T00:00:00Z"

    # -- lookups ------------------------------------------------------------
    def node_by_id(self, node_id: str) -> Optional[Node]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    # -- finalisation -------------------------------------------------------
    def finalize(self) -> None:
        """Sort every array and recompute the derived aggregates."""
        self.nodes.sort(key=lambda n: n.sort_key)
        self.edges.sort(key=lambda e: e.sort_key)
        self.issues.sort(key=lambda i: i.sort_key)
        self.diagnostics.sort(key=lambda d: d.sort_key)
        node_ids = {n.id for n in self.nodes}
        edge_ids = {e.id for e in self.edges}
        issue_ids = {i.id for i in self.issues}
        for issue in self.issues:
            issue.nodeIds = [n for n in _dedup(issue.nodeIds) if n in node_ids]
            issue.edgeIds = [e for e in _dedup(issue.edgeIds) if e in edge_ids]
        for node in self.nodes:
            node.issueIds = sorted({i for i in node.issueIds if i in issue_ids})
        for edge in self.edges:
            edge.issueIds = sorted({i for i in edge.issueIds if i in issue_ids})
        self._recount_stages()

    def _recount_stages(self) -> None:
        summaries = {sid: StageSummary(id=sid, label=STAGE_LABELS[sid], order=i)
                     for i, sid in enumerate(STAGE_IDS)}
        for node in self.nodes:
            summary = summaries.get(node.stage)
            if summary is not None:
                summary.nodeCount += 1
        for issue in self.issues:
            if issue.suppressed:
                continue
            summary = summaries.get(issue.stage)
            if summary is not None:
                summary.issueCounts[issue.severity] = summary.issueCounts.get(issue.severity, 0) + 1
        for summary in summaries.values():
            counts = summary.issueCounts
            summary.present = bool(summary.nodeCount) or any(counts.values())
            summary.maxSeverity = next((s for s in ("high", "medium", "low") if counts.get(s)), None)
        self.stages = [summaries[sid] for sid in STAGE_IDS]

    # -- serialization ------------------------------------------------------
    def issue_counts(self) -> Dict[str, int]:
        counts = {"low": 0, "medium": 0, "high": 0}
        for issue in self.issues:
            if not issue.suppressed:
                counts[issue.severity] = counts.get(issue.severity, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        workspace: Dict[str, Any] = {
            "root": self.root,
            "entrypoints": list(self.entrypoints),
            "filesAnalyzed": self.filesAnalyzed,
            "filesFailed": self.filesFailed,
            "notebooksSkipped": self.notebooksSkipped,
            "frameworks": list(self.frameworks),
        }
        if self.configPath:
            workspace["configPath"] = self.configPath
        doc = {
            "schemaVersion": SCHEMA_VERSION,
            "generator": {
                "name": GENERATOR_NAME,
                "version": __version__,
                "rendererSha": renderer_sha(),
                "generatedAt": self.generatedAt,
            },
            "workspace": workspace,
            "stages": [s.to_dict() for s in self.stages],
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "issues": [i.to_dict() for i in self.issues],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "stats": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "issues": self.issue_counts(),
                "suppressed": sum(1 for i in self.issues if i.suppressed),
                "durationMs": int(self.durationMs),
                "truncated": bool(self.truncated),
            },
        }
        # MLV-P1: the four answers are composed from the finished document, so
        # every host gets the same four sentences without asking for them. The
        # import is local because `emit` is a layer above `core` - nothing in
        # `core` may depend on it at import time.
        from ..emit.answers import compose
        doc["answers"] = compose(doc)
        return doc


def _dedup(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
