"""Mermaid `flowchart LR` emission.

One subgraph per present stage; a unit with children becomes a nested
subgraph inside its stage lane. Severity is a text prefix (`[!!]`, `[!]`,
`[i]`) so the diagram survives a greyscale terminal, and each edge kind gets
its own arrow style.

**Every node is declared exactly once.** A node whose parent sits in a
different stage lane is emitted as a root of its *own* lane rather than a
second time inside the parent's subgraph - mermaid resolves a repeated
declaration unpredictably, and the containment is still visible through the
`call` / `control` edges.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..core.unresolved import UNRESOLVED_KIND, unresolved_note

__all__ = ["render_mermaid"]


def _unresolved_suffix(doc: Dict[str, Any]) -> str:
    """ANA-5a: "not detected" may not be an unqualified claim when the
    analyzer could not resolve every call it saw."""
    count = sum(int(d.get("count") or 1) for d in (doc.get("diagnostics") or [])
                if isinstance(d, dict) and d.get("kind") == UNRESOLVED_KIND)
    return unresolved_note(count) or ""

_ARROW = {
    "data": "-->",
    "call": "-.->",
    "control": "==>",
    "config": "--o",
}
_SEVERITY_PREFIX = {"high": "[!!] ", "medium": "[!] ", "low": "[i] "}
_ID_RE = re.compile(r"[^A-Za-z0-9_]")


def _mid(node_id: str) -> str:
    return "n_" + _ID_RE.sub("", node_id.split(":", 1)[-1])


def _text(label: str) -> str:
    out = (label or "").replace("\\", "/").replace('"', "'")
    out = out.replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")")
    out = out.replace("|", "/").replace("<", "‹").replace(">", "›")
    return out.strip() or "node"


def _worst_map(doc: Dict[str, Any]) -> Dict[str, str]:
    return {i["id"]: i["severity"] for i in doc.get("issues", [])}


def _worst(severities: Dict[str, str], issue_ids) -> Optional[str]:
    worst = None
    for issue_id in issue_ids or ():
        severity = severities.get(issue_id)
        if severity == "high":
            return "high"
        if severity == "medium":
            worst = "medium"
        elif severity == "low" and worst is None:
            worst = "low"
    return worst


def _shape(node: Dict[str, Any], label: str) -> str:
    if node.get("ghost"):
        return '%s>"%s"]' % (_mid(node["id"]), label)
    if node["level"] == "op":
        return '%s("%s")' % (_mid(node["id"]), label)
    return '%s["%s"]' % (_mid(node["id"]), label)


def _label_for(node: Dict[str, Any], severities: Dict[str, str]) -> str:
    label = _text(node["label"])
    severity = _worst(severities, node.get("issueIds", []))
    if severity:
        label = _SEVERITY_PREFIX[severity] + label
    if node.get("ghost"):
        # A9 already puts "missing" in the ghost's sublabel; appending both
        # rendered `zero_grad() · missing — missing` on the demo diagram.
        return label + " · missing"
    sublabel = node.get("sublabel")
    if sublabel:
        label += " — " + _text(sublabel)
    return label


def _scope_comment(doc: Dict[str, Any]) -> Optional[str]:
    """The leading `%% scope: ...` comment a PROJECTION carries (CONTRACTS 11.5).

    A comment, not a `classDef`: mermaid drops `%%` lines before parsing, so
    the diagram renders identically in every mermaid version, and an unscoped
    document emits nothing at all.
    """
    view = doc.get("view")
    if not isinstance(view, dict):
        return None
    return ("%%%% scope: %s — %s of %s nodes"
            % (view.get("scope", "all"), doc.get("stats", {}).get("nodes", 0),
               view.get("of", {}).get("nodes", 0)))


def render_mermaid(doc: Dict[str, Any]) -> str:
    """A compact textual diagram of the whole graph."""
    lines: List[str] = []
    scoped = _scope_comment(doc)
    if scoped:
        lines.append(scoped)
    lines.append("flowchart LR")
    nodes = doc.get("nodes", [])
    severities = _worst_map(doc)
    by_id = {n["id"]: n for n in nodes}

    #: children of a node that live in the *same* stage lane; those are the
    #: only ones nested under it, so no node is declared twice.
    nested: Dict[str, List[Dict[str, Any]]] = {}
    roots: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        parent = by_id.get(node.get("parent") or "")
        if parent is not None and parent["stage"] == node["stage"]:
            nested.setdefault(parent["id"], []).append(node)
        else:
            roots.setdefault(node["stage"], []).append(node)

    def emit(node: Dict[str, Any], indent: str) -> None:
        label = _label_for(node, severities)
        children = nested.get(node["id"]) or []
        if children:
            lines.append('%ssubgraph %s_g["%s"]' % (indent, _mid(node["id"]), label))
            lines.append("%s  direction LR" % indent)
            lines.append("%s  %s" % (indent, _shape(node, label)))
            for child in children:
                emit(child, indent + "  ")
            lines.append("%send" % indent)
        else:
            lines.append("%s%s" % (indent, _shape(node, label)))

    for stage in doc.get("stages", []):
        if not stage.get("present"):
            continue
        lane = roots.get(stage["id"]) or []
        if not lane:
            continue
        lines.append('  subgraph stage_%s["%s"]' % (stage["id"], _text(stage["label"])))
        lines.append("    direction LR")
        for node in lane:
            emit(node, "    ")
        lines.append("  end")

    for edge in doc.get("edges", []):
        if edge["source"] not in by_id or edge["target"] not in by_id:
            continue  # pragma: no cover - finalize() already drops these
        arrow = _ARROW.get(edge["kind"], "-->")
        label = edge.get("label")
        if label:
            # the label MUST be quoted: mermaid's flowchart lexer rejects `(`
            # in a bare pipe slot, and every `call` edge is labelled `callee()`
            lines.append('  %s %s|"%s"| %s' % (_mid(edge["source"]), arrow,
                                               _text(label), _mid(edge["target"])))
        else:
            lines.append("  %s %s %s" % (_mid(edge["source"]), arrow, _mid(edge["target"])))

    absent = [s["id"] for s in doc.get("stages", []) if not s.get("present")]
    if absent:
        lines.append("  %% not detected: " + ", ".join(absent)
                     + _unresolved_suffix(doc))
    return "\n".join(lines) + "\n"
