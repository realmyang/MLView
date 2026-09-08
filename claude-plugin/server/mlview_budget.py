"""The 4 KB payload budget: measuring it, and shrinking a payload into it.

Split out of ``mlview_payloads`` because every tool shares this machinery and
no tool varies it: keeping it here leaves that module to the per-tool builders.
Pure — no filesystem, no network, no MCP SDK.

CONTRACTS section 5: "every model-facing payload is capped at 4 KB with full
detail behind ``graphPath``".

**What "4 KB" is measured on.** The MCP SDK returns each tool result twice: as
``structuredContent`` (the dict) and as ``content[0].text``, which it renders with
``pydantic_core.to_json(result, indent=2)``. The indented form is the one a model
without structured-output support actually reads, and it is ~25-30% larger than the
compact encoding — so measuring the compact one let ``mlview_issues`` ship 4985
bytes of model-facing text on the demo sample while every assertion said 3909.
``payload_size`` therefore measures the INDENTED encoding: the bigger of the two,
and the one the contract is about.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

LIMIT_BYTES = 4096

#: Keys a caller needs verbatim; ``fit`` never shortens or drops these.
PROTECTED_KEYS = frozenset(
    {
        "graphPath", "reportPath", "reportUrl", "opened", "format", "scope",
        "schemaVersion", "truncated", "code", "nodeId", "severity", "line",
        "file", "kind", "stage", "level",
        # Provenance and "this is not a clean bill of health" text: short, and the
        # whole point of the payload when it is present.
        "note", "docNote", "docPath", "diagnostics",
        "filesAnalyzed", "filesFailed", "notebooksSkipped",
    }
)


# --------------------------------------------------------------------------- size
def serialize(payload: Any) -> str:
    """Exactly what the MCP SDK puts in ``content[0].text`` for a tool result.

    ``mcp.server.mcpserver.utilities.func_metadata`` renders a tool's return value
    with ``pydantic_core.to_json(result, fallback=str, indent=2)``. ``json.dumps``
    with ``indent=2`` and ``ensure_ascii=False`` produces the same shape and the
    same byte count for the plain dicts these builders return.
    """
    return json.dumps(payload, ensure_ascii=False, indent=2)


def compact_size(payload: Any) -> int:
    """Bytes of the compact encoding — what ``structuredContent`` costs."""
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def payload_size(payload: Any) -> int:
    """Bytes of the encoding the 4 KB budget is measured in: the SDK's text block.

    This is deliberately the LARGER of the two encodings the SDK emits, so a
    payload that passes the budget passes it for both ``structuredContent`` and
    the indented ``content`` text a model may be reading instead.
    """
    return len(serialize(payload).encode("utf-8"))


def _longest_list_key(payload: Dict[str, Any]) -> Optional[str]:
    best, best_size = None, 0
    for key, value in payload.items():
        if key in PROTECTED_KEYS or not isinstance(value, list) or not value:
            continue
        size = payload_size(value)
        if size > best_size:
            best, best_size = key, size
    return best


def _longest_text_key(payload: Dict[str, Any]) -> Optional[str]:
    best, best_len = None, 0
    for key, value in payload.items():
        if key in PROTECTED_KEYS or not isinstance(value, str):
            continue
        if len(value) > best_len:
            best, best_len = key, len(value)
    return best if best_len > 80 else None


def fit(payload: Dict[str, Any], limit: int = LIMIT_BYTES) -> Dict[str, Any]:
    """Shrink ``payload`` until it fits ``limit`` bytes.

    Lists are shed first (longest list, last element), because a shorter list is
    still a correct answer; only then are long free-text fields clipped.  The
    payload is marked ``truncated: true`` the moment anything is removed.
    """
    out = dict(payload)
    if payload_size(out) <= limit:
        return out

    out["truncated"] = True
    while payload_size(out) > limit:
        key = _longest_list_key(out)
        if key is None:
            break
        out[key] = list(out[key])[:-1]

    while payload_size(out) > limit:
        key = _longest_text_key(out)
        if key is None:
            break
        text = out[key]
        keep = max(40, int(len(text) * 0.7))
        out[key] = text[:keep].rstrip() + " ..."

    return out


def clip_text_lines(text: str, budget: int, note: str) -> Tuple[str, bool]:
    """Clip ``text`` to whole lines fitting ``budget`` bytes, appending ``note``."""
    if len(text.encode("utf-8")) <= budget:
        return text, False
    lines = text.splitlines()
    kept: List[str] = []
    used = len(note.encode("utf-8")) + 1
    for line in lines:
        cost = len(line.encode("utf-8")) + 1
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    kept.append(note)
    return "\n".join(kept), True


__all__ = [
    "LIMIT_BYTES", "PROTECTED_KEYS", "payload_size", "compact_size", "serialize",
    "fit", "clip_text_lines",
]
