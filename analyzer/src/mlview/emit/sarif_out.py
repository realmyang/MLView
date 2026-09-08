"""SARIF 2.1.0 output (CI-ADOPT part c).

A mechanical transform of the document's `issues[]` - no analysis, no
re-ranking, no second opinion. `--sarif FILE` is what lets GitHub code
scanning, Azure DevOps and every SARIF-reading review tool show MLView
findings inline on a pull request.

Four properties are load-bearing and each has a test:

1. **No absolute path, ever.** Every `artifactLocation.uri` is the
   workspace-relative `Loc.file` with `uriBaseId: "%SRCROOT%"`; GitHub rejects
   an absolute URI outright, and a CI log that leaks `/home/runner/work/...`
   leaks the runner's layout. `originalUriBaseIds` declares the base **without
   a `uri`**, for exactly that reason: the importer supplies the root.
2. **`partialFingerprints.mlviewIssueId` is `Issue.id`**, which CONTRACTS §0
   defines as `sha1(code|file|qualname|symbol)` - content-addressed, never
   line-derived - so a finding keeps its identity across an edit above it and
   the consumer's "new / existing" agrees with `--changed-since`.
3. **`rules[]` is the whole registry**, not the rules that happened to fire,
   so `ruleIndex` is stable between runs and every `helpUri` resolves whether
   or not the rule fired on this workspace.
4. **A suppressed or baselined finding ships as a suppressed result**, not as
   a missing one (`suppressions[].kind = "external"`, the SARIF spelling of
   "something outside the tool decided this"). Deleting them would make the
   SARIF disagree with `--show-suppressed`.

Columns are `Loc.col + 1`: MLView's are 0-based, SARIF's are 1-based. The
document deliberately does **not** declare `columnKind` - `Loc.col` is
CPython's `ast.col_offset`, a UTF-8 byte offset, which is neither of SARIF's
two enumerations, and claiming one of them would be a false precision on
non-ASCII source lines.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from ..version import __version__

__all__ = ["render_sarif", "sarif_bytes", "write_sarif", "SARIF_VERSION",
           "SARIF_SCHEMA_URI", "URI_BASE_ID", "level_for"]

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA_URI = ("https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/"
                    "os/schemas/sarif-schema-2.1.0.json")
URI_BASE_ID = "%SRCROOT%"

_LEVEL = {"high": "error", "medium": "warning", "low": "note"}
_BASELINE_STATE = {"new": "new", "touched": "unchanged", "existing": "unchanged"}


def level_for(severity: str) -> str:
    """MLView severity -> SARIF level. `low` is `note`, not `warning`: a note
    does not fail a default GitHub gate, and `low` findings are advisory."""
    return _LEVEL.get(severity, "warning")


# ------------------------------------------------------------------ rules
def _rule_descriptors() -> List[Dict[str, Any]]:
    from ..rules import all_rules

    rules: List[Dict[str, Any]] = []
    for spec in all_rules():
        descriptor: Dict[str, Any] = {
            "id": spec.code,
            "name": spec.code,
            "shortDescription": {"text": spec.title or spec.code},
            "fullDescription": {"text": spec.why or spec.title or spec.code},
            "helpUri": spec.docs,
            "help": {"text": spec.fix_hint or spec.why or spec.title or spec.code},
            "defaultConfiguration": {"level": level_for(spec.severity),
                                     "enabled": bool(spec.enabled)},
            "properties": {
                # `helpUri` is relative to the same base as every location, and
                # SARIF has no per-field uriBaseId, so the base is stated here
                # rather than being guessed by the reader.
                "helpUriBaseId": URI_BASE_ID,
                "severity": spec.severity,
                "basePrior": spec.base_prior,
                "ruleVersion": spec.rule_version,
                "tags": list(spec.tags),
                "frameworks": list(spec.frameworks),
            },
        }
        rules.append(descriptor)
    return rules


# -------------------------------------------------------------- locations
def _artifact(loc: Dict[str, Any]) -> Dict[str, Any]:
    return {"uri": (loc.get("file") or "").replace("\\", "/"),
            "uriBaseId": URI_BASE_ID}


def _region(loc: Dict[str, Any]) -> Dict[str, Any]:
    region: Dict[str, Any] = {"startLine": max(1, int(loc.get("line") or 1))}
    if isinstance(loc.get("col"), int):
        region["startColumn"] = int(loc["col"]) + 1
    end_line = loc.get("endLine")
    if isinstance(end_line, int) and end_line >= region["startLine"]:
        region["endLine"] = end_line
    if isinstance(loc.get("endCol"), int):
        region["endColumn"] = int(loc["endCol"]) + 1
    snippet = loc.get("snippet")
    if snippet:
        region["snippet"] = {"text": snippet}
    return region


def _physical(loc: Dict[str, Any]) -> Dict[str, Any]:
    return {"physicalLocation": {"artifactLocation": _artifact(loc),
                                 "region": _region(loc)}}


# -------------------------------------------------------------- the document
def render_sarif(doc: Dict[str, Any], tool_version: str = __version__) -> Dict[str, Any]:
    """The SARIF document for an MLGraph document. Pure dict -> dict."""
    rules = _rule_descriptors()
    index_of = {rule["id"]: i for i, rule in enumerate(rules)}

    results: List[Dict[str, Any]] = []
    for issue in doc.get("issues") or []:
        loc = issue.get("loc") or {}
        result: Dict[str, Any] = {
            "ruleId": issue.get("code", ""),
            "level": level_for(issue.get("severity", "medium")),
            "message": {"text": issue.get("message") or issue.get("title") or ""},
            "locations": [_physical(loc)],
            "partialFingerprints": {"mlviewIssueId": issue.get("id", "")},
        }
        rule_index = index_of.get(issue.get("code", ""))
        if rule_index is not None:
            result["ruleIndex"] = rule_index
        confidence = issue.get("confidence")
        if isinstance(confidence, (int, float)):
            # SARIF `rank` is 0-100 and orders the queue the same way the rail
            # does: severity first, then how sure the rule is.
            result["rank"] = round(float(confidence) * 100.0, 1)
        related = [_related(rel, index)
                   for index, rel in enumerate(issue.get("relatedLocs") or [])]
        if related:
            result["relatedLocations"] = related
        change = issue.get("change")
        if change in _BASELINE_STATE:
            result["baselineState"] = _BASELINE_STATE[change]
        suppression = _suppression(issue)
        if suppression is not None:
            result["suppressions"] = [suppression]
        result["properties"] = _result_properties(issue)
        results.append(result)

    run: Dict[str, Any] = {
        "tool": {"driver": {"name": "MLView", "version": tool_version,
                            "semanticVersion": tool_version, "rules": rules}},
        "originalUriBaseIds": {
            URI_BASE_ID: {"description": {
                "text": "The analyzed workspace root. Deliberately carries no "
                        "uri: MLView never emits an absolute path, so the "
                        "importer supplies the checkout location."}}},
        "results": results,
        "invocations": [{"executionSuccessful": True}],
    }
    workspace = doc.get("workspace") or {}
    run["properties"] = {
        "filesAnalyzed": workspace.get("filesAnalyzed", 0),
        "filesFailed": workspace.get("filesFailed", 0),
        "notebooksSkipped": workspace.get("notebooksSkipped", 0),
        "frameworks": list(workspace.get("frameworks") or []),
        # The honesty column: what the analyzer could not see travels with the
        # findings instead of being lost at the CI boundary.
        "diagnostics": [{"kind": d.get("kind", ""), "message": d.get("message", "")}
                        for d in (doc.get("diagnostics") or [])],
    }
    return {"$schema": SARIF_SCHEMA_URI, "version": SARIF_VERSION, "runs": [run]}


def _related(related: Dict[str, Any], index: int) -> Dict[str, Any]:
    out = _physical(related)
    out["id"] = index + 1
    message = related.get("message") or related.get("role")
    if message:
        out["message"] = {"text": str(message)}
    return out


def _suppression(issue: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if issue.get("suppressed"):
        return {"kind": "external",
                "justification": "suppressed by .mlview.toml or a "
                                 "`# mlview: ignore[...]` comment"}
    if issue.get("baselined"):
        return {"kind": "external",
                "justification": "present in the MLView baseline; excluded from "
                                 "the counts and from --fail-on"}
    return None


def _result_properties(issue: Dict[str, Any]) -> Dict[str, Any]:
    properties: Dict[str, Any] = {
        "confidence": issue.get("confidence"),
        "confidenceBucket": issue.get("confidenceBucket"),
        "stage": issue.get("stage"),
        "title": issue.get("title"),
        "why": issue.get("why"),
        "fixHint": issue.get("fixHint"),
        "tags": list(issue.get("tags") or []),
        "nodeIds": list(issue.get("nodeIds") or []),
    }
    if issue.get("change"):
        properties["change"] = issue["change"]
    if issue.get("baselined"):
        properties["baselined"] = True
    return properties


def sarif_bytes(doc: Dict[str, Any]) -> bytes:
    return (json.dumps(render_sarif(doc), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_sarif(doc: Dict[str, Any], path: str) -> str:
    """Write the SARIF document; returns the absolute forward-slashed path."""
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(abs_path, "wb") as handle:
        handle.write(sarif_bytes(doc))
    return abs_path.replace("\\", "/")
