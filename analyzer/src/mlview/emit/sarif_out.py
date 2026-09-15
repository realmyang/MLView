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
   or not the rule fired on this workspace. `helpUri` is an **absolute
   `https://` URI pinned to the running version**: GitHub code scanning renders
   it as the alert's documentation link, and a workspace-relative string there
   resolves against the alerts page and 404s in every repository that is not
   this one. The in-repo path is kept beside it as `properties.docsPath`.
4. **A suppressed or baselined finding ships as a suppressed result**, not as
   a missing one (`suppressions[].kind = "external"`, the SARIF spelling of
   "something outside the tool decided this"). Deleting them would make the
   SARIF disagree with `--show-suppressed`.
5. **`Issue.fix` becomes `result.fixes[]`** (C8). The structured edit of
   CONTRACTS 11.42 already travels in the JSON document, and the review tools
   that read SARIF are exactly the surface that can offer it - GitHub renders a
   `fixes[]` entry as the alert's suggested change. One `artifactChanges` entry,
   because 11.42 A6 says every edit of one fix names one file; one
   `replacements` entry per edit, with a **zero-width `deletedRegion`** for an
   insertion, which is SARIF's own spelling of the same idea. The safety grade
   rides beside it in `properties.fixSafety`: SARIF has no `isPreferred`, and
   inventing one would be the second spelling of one decision that 11.42 A5
   refuses. A finding with no `fix` gets no `fixes` key at all, so every SARIF
   document MLView produced before this one is unchanged.

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
           "SARIF_SCHEMA_URI", "URI_BASE_ID", "level_for", "help_uri_for",
           "DOCS_BASE_URL", "fixes_for"]

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA_URI = ("https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/"
                    "os/schemas/sarif-schema-2.1.0.json")
URI_BASE_ID = "%SRCROOT%"
#: Where a rule page is published. A SARIF consumer resolves `helpUri` against
#: nothing - `reportingDescriptor.helpUri` has no `uriBaseId` companion - so an
#: adopter's alert needs an absolute URL, and the wheel ships no `docs/rules/`
#: for a `pip install` to resolve either. Pinned to the running version so an
#: alert filed today keeps pointing at the page the finding was written against.
DOCS_BASE_URL = "https://github.com/realmyang/MLView/blob/v%s/docs/rules/"


def help_uri_for(code: str) -> str:
    """The absolute, resolving documentation URL for one rule code."""
    return "%s%s.md" % (DOCS_BASE_URL % __version__, code)

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
            "helpUri": help_uri_for(spec.code),
            "help": {"text": spec.fix_hint or spec.why or spec.title or spec.code},
            "defaultConfiguration": {"level": level_for(spec.severity),
                                     "enabled": bool(spec.enabled)},
            "properties": {
                # The workspace-relative page, for a consumer reading the SARIF
                # inside this checkout. It is deliberately NOT `helpUri`:
                # `reportingDescriptor.helpUri` has no `uriBaseId` companion in
                # SARIF 2.1.0, so a relative reference there resolves against
                # the consumer's own page and dies.
                "docsPath": spec.docs,
                "docsPathBaseId": URI_BASE_ID,
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


# ------------------------------------------------------------------- fixes
def _replacement(edit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One `TextEdit` -> one SARIF `replacement`, or None if it is not one.

    The region is the range the edit **deletes**; `insertedContent` is what goes
    in its place. An insertion is a zero-width region, which is how both schemas
    already spell it, so the two conventions meet without a special case.
    Columns are 1-based here and 0-based in the document, exactly as everywhere
    else in this module.
    """
    try:
        line = int(edit["line"])
        col = int(edit["col"])
        end_line = int(edit["endLine"])
        end_col = int(edit["endCol"])
    except (KeyError, TypeError, ValueError):
        return None
    region = {"startLine": max(1, line), "startColumn": col + 1,
              "endLine": max(1, end_line), "endColumn": end_col + 1}
    inserted = edit.get("newText")
    out: Dict[str, Any] = {"deletedRegion": region}
    if isinstance(inserted, str) and inserted:
        out["insertedContent"] = {"text": inserted}
    return out


def fixes_for(issue: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`issue["fix"]` -> SARIF `result.fixes[]`; `[]` when there is no edit.

    Empty rather than absent so the caller decides whether the key exists at
    all: a `fixes: []` on every result would change every SARIF document MLView
    has ever written, for no consumer's benefit.
    """
    fix = issue.get("fix")
    if not isinstance(fix, dict):
        return []
    edits = [e for e in (fix.get("edits") or []) if isinstance(e, dict)]
    if not edits:
        return []
    replacements = [r for r in (_replacement(e) for e in edits) if r is not None]
    if len(replacements) != len(edits):
        # A malformed edit is not a partial fix: 11.42 A6 says the edits of one
        # fix apply atomically, and half of them is a corrupted file.
        return []
    # 11.42 A6: every edit of one fix names one file - the issue's own.
    uri = (edits[0].get("file") or issue.get("loc", {}).get("file") or "")
    change = {"artifactLocation": {"uri": uri.replace("\\", "/"),
                                   "uriBaseId": URI_BASE_ID},
              "replacements": replacements}
    entry: Dict[str, Any] = {"artifactChanges": [change]}
    title = fix.get("title")
    if isinstance(title, str) and title:
        entry["description"] = {"text": title}
    return [entry]


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
        fixes = fixes_for(issue)
        if fixes:
            result["fixes"] = fixes
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
    fix = issue.get("fix")
    if isinstance(fix, dict) and fix.get("safety"):
        # SARIF has no `isPreferred`; a consumer derives it from this and from
        # nothing else, which is CONTRACTS 11.42 A5 carried across the boundary.
        properties["fixSafety"] = fix["safety"]
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
