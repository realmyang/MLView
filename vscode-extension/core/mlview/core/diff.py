"""VIEW-08 (CONTRACTS 11.38) — comparing two analyses.

The most valuable question a reviewer has is *"my PR added a scaler; did it
move to the wrong side of the split?"*, and until now the only way to ask it
was to open two reports side by side. This module answers it in the analyzer,
so all three hosts get the same answer from the same code.

**Both audits argued that node ids churn on edit and proposed inventing a
parallel identity. They were wrong, and the correction is what makes this
cheap:** §0 already defines `nodeId = sha1(file|qualname|kind)`, never
line-derived, and `test_id_stability.py` gates it against a 20-blank-line
insertion. The stable identity exists. A diff is therefore a **join on ids**,
and everything interesting is in what the join is allowed to call *changed*.

Three decisions, each of which is the difference between a useful overlay and
a noisy one:

1. **A move is not a change.** The comparison key deliberately excludes
   `loc.line` and `loc.col`. Inserting a function above a node must not paint
   the whole file as changed - that is the exact property the stable ids were
   built for, and a diff that threw it away would be reporting churn. A node
   whose line moved and whose meaning did not is `unchanged`, with `moved`
   recorded beside it for anyone who wants it.
2. **A float is not a fact.** Confidences are compared rounded to three places;
   below that they are noise from a model, not a statement about the code.
3. **The overlay is a separate document.** It never becomes part of a graph, so
   `schemaVersion` stays 1.0, `contracts/graph.sample.json` is untouched and an
   unscoped `analyze` emits exactly the bytes it always emitted.

**What a diff cannot see, and always says out loud (`notes[]`).** A status of
`removed` means *"the head document does not contain this id"*, and there are
four honest reasons for that which have nothing to do with the code changing:
the head analysis set files aside (the relevance prefilter, a `--max-files`
cap), the head document is capped (`stats.truncated`), the head document is a
**projection** (`view`), or the two documents came from different analyzer
versions or different workspace roots. Each of those emits a note, because a
reviewer reading "-16 nodes" and concluding a refactor deleted them would be
misled by the tool, and this project's one unrecoverable failure is a
high-severity claim that is not true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..version import SCHEMA_VERSION, __version__

__all__ = ["DIFF_KIND", "DIFF_VERSION", "NODE_KEYS", "EDGE_KEYS", "ISSUE_KEYS",
           "DiffError", "diff_documents"]

#: The overlay's own `kind` and version. It is **not** an MLGraph and must never
#: be read as one; a consumer checks `kind` before anything else.
DIFF_KIND = "mlview-diff"
DIFF_VERSION = "1.0"

#: Node fields that make a node *what it is*. `loc` is absent on purpose (see
#: the module docstring); `issueCodes` is derived, not a document field.
NODE_KEYS = ("label", "sublabel", "kind", "level", "stage", "parent", "dynamic",
             "ghost", "collapsedByDefault", "confidenceBucket", "issueCodes")
#: Edge fields that can move without changing the edge id (`source`, `kind`,
#: `target` and `label` are *in* the id, so a change to any of them is an
#: add plus a remove, which is the truthful reading).
EDGE_KEYS = ("confidence", "tags", "issueCodes")
#: Issue fields worth reporting on a finding that is present in both runs.
ISSUE_KEYS = ("severity", "confidenceBucket", "suppressed", "message", "nodeIds")

_ROUND = 3


class DiffError(ValueError):
    """A document that cannot be diffed at all, with the reason a user needs."""


# --------------------------------------------------------------- validation
def _require_graph(doc: Any, label: str) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        raise DiffError("%s is not an MLView document (expected a JSON object)" % label)
    if doc.get("kind") == DIFF_KIND:
        raise DiffError("%s is a diff overlay, not a graph; pass the two "
                        "`mlview analyze --json` documents instead" % label)
    for key in ("nodes", "edges", "issues"):
        if not isinstance(doc.get(key), list):
            raise DiffError("%s has no `%s` array; it is not an MLView graph "
                            "document" % (label, key))
    return doc


# ------------------------------------------------------------------ helpers
def _round(value: Any) -> Any:
    return round(float(value), _ROUND) if isinstance(value, (int, float)) else value


def _issue_codes(entries: Sequence[Mapping[str, Any]], key: str) -> Dict[str, Tuple[str, ...]]:
    """`{node or edge id: sorted rule codes anchored on it}`.

    A node that gained or lost a finding is a node a reviewer wants to see, and
    it is the one *derived* field in the comparison key. Codes rather than
    issue ids, because an issue id embeds the symbol it was raised on and would
    make a renamed variable look like a changed node.
    """
    out: Dict[str, List[str]] = {}
    for issue in entries:
        if not isinstance(issue, dict):
            continue
        code = str(issue.get("code") or "")
        for target in issue.get(key) or ():
            out.setdefault(str(target), []).append(code)
    return {k: tuple(sorted(set(v))) for k, v in out.items()}


def _key_of(entry: Mapping[str, Any], keys: Sequence[str],
            codes: Mapping[str, Tuple[str, ...]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in keys:
        if key == "issueCodes":
            out[key] = list(codes.get(str(entry.get("id")), ()))
        elif key == "confidence":
            out[key] = _round(entry.get(key))
        elif key == "tags":
            out[key] = sorted(str(t) for t in (entry.get(key) or ()))
        elif key == "nodeIds":
            out[key] = list(entry.get(key) or ())
        else:
            out[key] = entry.get(key)
    return out


def _changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[str]:
    return sorted(k for k in after if before.get(k) != after.get(k))


def _index(entries: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id"):
            out[str(entry["id"])] = entry
    return out


def _loc(entry: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    loc = entry.get("loc")
    if not isinstance(loc, dict):
        return None
    return {"file": loc.get("file"), "line": loc.get("line")}


def _moved(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return _loc(before) != _loc(after)


@dataclass
class _Side:
    """One of the two documents, reduced to what the diff needs of it."""

    label: str
    doc: Dict[str, Any]
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    edges: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    issues: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    node_codes: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    edge_codes: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def of(cls, doc: Dict[str, Any], label: str) -> "_Side":
        side = cls(label=label, doc=doc)
        side.nodes = _index(doc.get("nodes") or ())
        side.edges = _index(doc.get("edges") or ())
        side.issues = _index(doc.get("issues") or ())
        issues = [i for i in (doc.get("issues") or ()) if isinstance(i, dict)]
        side.node_codes = _issue_codes(issues, "nodeIds")
        side.edge_codes = _issue_codes(issues, "edgeIds")
        return side

    def summary(self) -> Dict[str, Any]:
        workspace = self.doc.get("workspace") or {}
        stats = self.doc.get("stats") or {}
        out = {
            "root": workspace.get("root"),
            "generatedAt": (self.doc.get("generator") or {}).get("generatedAt")
                           or self.doc.get("generatedAt"),
            "analyzerVersion": (self.doc.get("generator") or {}).get("version"),
            "schemaVersion": self.doc.get("schemaVersion"),
            "filesAnalyzed": workspace.get("filesAnalyzed"),
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "issues": len(self.issues),
            "truncated": bool(stats.get("truncated")),
        }
        if isinstance(self.doc.get("view"), dict):
            out["view"] = self.doc["view"].get("scope")
        return {k: v for k, v in out.items() if v is not None}


# --------------------------------------------------------------------- notes
_ASIDE_MARKERS = ("Relevance prefilter", "Discovery capped", "Graph cap")


def _blindness_notes(side: _Side) -> List[Dict[str, Any]]:
    """Every reason this side of the diff may be missing something, named.

    This is the whole honesty half of VIEW-08: `removed` is a claim about the
    *documents*, and it becomes a claim about the *code* only when nothing was
    set aside, capped or projected away.
    """
    notes: List[Dict[str, Any]] = []
    doc = side.doc
    if isinstance(doc.get("view"), dict):
        scope = doc["view"].get("scope", "?")
        notes.append({
            "kind": "projection",
            "side": side.label,
            "message": "the %s document is a projection of scope %s, so it holds "
                       "a subset of its own analysis; a `removed` status may be "
                       "the projection rather than the code. Diff the unprojected "
                       "documents." % (side.label, scope)})
    if (doc.get("stats") or {}).get("truncated"):
        notes.append({
            "kind": "truncated",
            "side": side.label,
            "message": "the %s document hit its --max-nodes budget, so nodes "
                       "exist that it does not contain; `removed` cannot be "
                       "read as deleted for that side." % side.label})
    for diagnostic in doc.get("diagnostics") or ():
        if not isinstance(diagnostic, dict):
            continue
        message = str(diagnostic.get("message") or "")
        if any(marker in message for marker in _ASIDE_MARKERS):
            notes.append({
                "kind": "not-analyzed",
                "side": side.label,
                "count": diagnostic.get("count"),
                "message": "the %s analysis did not read every file: %s"
                           % (side.label, message)})
        elif diagnostic.get("kind") == "notebook_skipped":
            notes.append({
                "kind": "not-analyzed",
                "side": side.label,
                "count": diagnostic.get("count"),
                "message": "the %s analysis skipped notebooks: %s"
                           % (side.label, message)})
    return notes


def _pair_notes(base: _Side, head: _Side) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    base_root = (base.doc.get("workspace") or {}).get("root")
    head_root = (head.doc.get("workspace") or {}).get("root")
    if base_root and head_root and base_root != head_root:
        notes.append({
            "kind": "different-roots",
            "message": "the two documents describe different workspace roots "
                       "(%s vs %s). Ids are built from the workspace-relative "
                       "path, so only files that exist under both roots with "
                       "the same relative path can match."
                       % (base_root, head_root)})
    base_version = (base.doc.get("generator") or {}).get("version")
    head_version = (head.doc.get("generator") or {}).get("version")
    if base_version and head_version and base_version != head_version:
        notes.append({
            "kind": "different-analyzers",
            "message": "the documents were produced by mlview %s and %s; a "
                       "`changed` or `new` status may reflect a rule change "
                       "rather than a code change." % (base_version, head_version)})
    base_schema = base.doc.get("schemaVersion")
    head_schema = head.doc.get("schemaVersion")
    if base_schema and head_schema and base_schema != head_schema:
        notes.append({
            "kind": "different-schemas",
            "message": "schemaVersion %s vs %s: fields present on one side and "
                       "absent on the other are reported as changes."
                       % (base_schema, head_schema)})
    return notes


# ---------------------------------------------------------------- the diff
def _diff_entries(base: Mapping[str, Dict[str, Any]], head: Mapping[str, Dict[str, Any]],
                  keys: Sequence[str], base_codes: Mapping[str, Tuple[str, ...]],
                  head_codes: Mapping[str, Tuple[str, ...]],
                  describe) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    rows: List[Dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for entry_id in sorted(set(base) | set(head)):
        before = base.get(entry_id)
        after = head.get(entry_id)
        if before is None:
            row = {"id": entry_id, "status": "added"}
            row.update(describe(after))
        elif after is None:
            row = {"id": entry_id, "status": "removed"}
            row.update(describe(before))
        else:
            fields = _changed_fields(_key_of(before, keys, base_codes),
                                     _key_of(after, keys, head_codes))
            row = {"id": entry_id, "status": "changed" if fields else "unchanged"}
            row.update(describe(after))
            if fields:
                row["changed"] = fields
            if _moved(before, after):
                # Recorded, never a status: the stable ids exist precisely so a
                # node that only moved is not reported as a change.
                row["moved"] = True
        counts[row["status"]] += 1
        rows.append(row)
    return rows, counts


def _describe_node(node: Mapping[str, Any]) -> Dict[str, Any]:
    out = {"label": node.get("label"), "kind": node.get("kind"),
           "level": node.get("level"), "stage": node.get("stage")}
    loc = _loc(node)
    if loc:
        out["loc"] = loc
    return {k: v for k, v in out.items() if v is not None}


def _describe_edge(edge: Mapping[str, Any]) -> Dict[str, Any]:
    out = {"source": edge.get("source"), "target": edge.get("target"),
           "kind": edge.get("kind")}
    if edge.get("label"):
        out["label"] = edge["label"]
    return out


def _describe_issue(issue: Mapping[str, Any]) -> Dict[str, Any]:
    out = {"code": issue.get("code"), "severity": issue.get("severity"),
           "title": issue.get("title"),
           "confidenceBucket": issue.get("confidenceBucket"),
           "nodeIds": list(issue.get("nodeIds") or ())}
    loc = _loc(issue)
    if loc:
        out["loc"] = loc
    if issue.get("suppressed"):
        out["suppressed"] = True
    return {k: v for k, v in out.items() if v is not None}


def _diff_issues(base: _Side, head: _Side) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    rows: List[Dict[str, Any]] = []
    counts = {"new": 0, "fixed": 0, "persisting": 0}
    for issue_id in sorted(set(base.issues) | set(head.issues)):
        before = base.issues.get(issue_id)
        after = head.issues.get(issue_id)
        if before is None:
            row = {"id": issue_id, "status": "new"}
            row.update(_describe_issue(after))
        elif after is None:
            row = {"id": issue_id, "status": "fixed"}
            row.update(_describe_issue(before))
        else:
            row = {"id": issue_id, "status": "persisting"}
            row.update(_describe_issue(after))
            fields = _changed_fields(_key_of(before, ISSUE_KEYS, {}),
                                     _key_of(after, ISSUE_KEYS, {}))
            if fields:
                row["changed"] = fields
        counts[row["status"]] += 1
        rows.append(row)
    return rows, counts


def _headline(nodes: Mapping[str, int], issues: Mapping[str, int]) -> str:
    return ("+%d nodes · −%d nodes · %d new findings · %d fixed"
            % (nodes["added"], nodes["removed"], issues["new"], issues["fixed"]))


def diff_documents(base_doc: Any, head_doc: Any, generated_at: str = "") -> Dict[str, Any]:
    """The overlay document for `base_doc` -> `head_doc` (CONTRACTS 11.38).

    Pure: it reads two dicts and returns a third. `generated_at` is passed in
    rather than read from the clock so a test can pin the bytes.
    """
    base = _Side.of(_require_graph(base_doc, "the base document"), "base")
    head = _Side.of(_require_graph(head_doc, "the head document"), "head")

    node_rows, node_counts = _diff_entries(
        base.nodes, head.nodes, NODE_KEYS, base.node_codes, head.node_codes,
        _describe_node)
    edge_rows, edge_counts = _diff_entries(
        base.edges, head.edges, EDGE_KEYS, base.edge_codes, head.edge_codes,
        _describe_edge)
    issue_rows, issue_counts = _diff_issues(base, head)

    notes = _pair_notes(base, head)
    notes.extend(_blindness_notes(base))
    notes.extend(_blindness_notes(head))

    overlay: Dict[str, Any] = {
        "kind": DIFF_KIND,
        "diffVersion": DIFF_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "generator": {"name": "mlview", "version": __version__},
        "base": base.summary(),
        "head": head.summary(),
        "summary": {
            "nodes": node_counts,
            "edges": edge_counts,
            "issues": issue_counts,
            "headline": _headline(node_counts, issue_counts),
        },
        "nodes": node_rows,
        "edges": edge_rows,
        "issues": issue_rows,
        "notes": notes,
    }
    if generated_at:
        overlay["generatedAt"] = generated_at
    return overlay
