"""Content-addressed ids (CONTRACTS section 0).

Never line-derived, so ids survive edits above a node:

    nodeId  = "n:" + sha1("<file>|<qualname>|<kind>")[:12]
    edgeId  = "e:" + sha1("<sourceId>|<kind>|<targetId>|<label>")[:12]
    issueId = "i:" + sha1("<code>|<file>|<qualname>|<symbol>")[:12]
"""

from __future__ import annotations

import hashlib

__all__ = ["node_id", "edge_id", "issue_id", "digest12"]


def digest12(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def node_id(file: str, qualname: str, kind: str) -> str:
    return "n:" + digest12("%s|%s|%s" % (file, qualname, kind))


def edge_id(source: str, kind: str, target: str, label: str = "") -> str:
    return "e:" + digest12("%s|%s|%s|%s" % (source, kind, target, label or ""))


def issue_id(code: str, file: str, qualname: str, symbol: str = "") -> str:
    return "i:" + digest12("%s|%s|%s|%s" % (code, file, qualname, symbol or ""))
