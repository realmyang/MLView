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
        # ROADMAP COVERAGE: the rules that could NOT run. Bounded by
        # `mlview_notes.MAX_CODES` / `MAX_MESSAGE` to ~1 KB worst case, so
        # protecting it cannot starve the payload — and shedding it would leave
        # the model a finding count it has no way to know is a floor.
        "coverage",
        "filesAnalyzed", "filesFailed", "notebooksSkipped",
    }
)

#: The free-text caveat keys — the ones a bound, a filter or a coverage gap
#: speaks through. They are PROTECTED above, which is why they need `NOTE_RESERVE`.
NOTE_KEYS = ("note", "docNote")

#: Bytes `fit` holds back for `NOTE_KEYS` **whether or not a caveat is present**.
#:
#: Without it the budget walk is not a function of the answer alone: `note` is
#: protected, so its bytes come out of the lists, and a payload sitting near the
#: cap answers with one row fewer the moment a caveat appears. How near the cap it
#: sits is decided by the absolute paths inside it — `root` and `graphPath` — whose
#: length is a property of the MACHINE, not of the project. Measured on
#: `samples/vision_pipeline` with the same graph: at a 74-character `graphPath` the
#: payload was 3932 B without a caveat and 4014 B with the 82-byte `maxNodes=0` one,
#: both carrying eight `topIssues`; at the 174-character `graphPath` a pytest data
#: directory hands out, the caveat-free payload still carried eight (4032 B) and the
#: caveated one crossed 4096 and shed the eighth — the same shortening a user gets
#: in a CI workspace, a nested monorepo or a Windows profile directory (CONTRACTS
#: §11 B4: "a bound note must never cost a finding").
#:
#: Reserving the bytes up front makes the walk caveat-independent by construction:
#: a payload carrying a caveat of `c` bytes is measured against `limit - (RESERVE
#: - c)`, the same ceiling the caveat-free payload is measured against, so both
#: shed exactly the same rows at any checkout depth. 160 B covers every **bound**
#: note the tools emit, including two of them joined (`maxNodes=...` at 68 B plus
#: `limit=...` at 59 B); a longer caveat — the coverage block, a filtered-view
#: sentence — pays only for its excess, exactly as it does today.
NOTE_RESERVE = 160


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


def caveat_cost(payload: Dict[str, Any]) -> int:
    """Bytes the `NOTE_KEYS` cost ``payload`` — keys, quoting and separators too.

    Measured by difference rather than from ``len(text)`` so that the reserve
    accounting matches the encoding the budget is measured in exactly: a 68-character
    note costs 82 bytes of indented JSON, and a reserve that ignored the other 14
    would still let the caveat move the shedding decision.
    """
    if not any(key in payload for key in NOTE_KEYS):
        return 0
    bare = {k: v for k, v in payload.items() if k not in NOTE_KEYS}
    return payload_size(payload) - payload_size(bare)


def fit(payload: Dict[str, Any], limit: int = LIMIT_BYTES,
        note_reserve: int = NOTE_RESERVE) -> Dict[str, Any]:
    """Shrink ``payload`` until it fits ``limit`` bytes.

    Lists are shed first (longest list, last element), because a shorter list is
    still a correct answer; only then are long free-text fields clipped.  The
    payload is marked ``truncated: true`` the moment anything is removed.

    ``note_reserve`` bytes are held back for the caveat keys whether or not a
    caveat is present, so that what a payload sheds is a function of the answer
    and not of the caveats printed beside it — see `NOTE_RESERVE`. A caveat larger
    than the reserve pays for its excess in the ordinary way.
    """
    out = dict(payload)
    # The reserve is a SHARE of the budget, never the budget: a caller that asks
    # for a 512-byte payload — the fitter's own unit tests do — must not spend a
    # third of it holding room for a caveat that is not there. An eighth is above
    # NOTE_RESERVE at the contractual 4096 and below it wherever a caller has
    # deliberately asked for something small.
    reserve = min(note_reserve, limit // 8)
    budget = max(0, limit - max(0, reserve - caveat_cost(out)))
    if payload_size(out) <= budget:
        return out

    out["truncated"] = True
    while payload_size(out) > budget:
        key = _longest_list_key(out)
        if key is None:
            break
        out[key] = list(out[key])[:-1]

    while payload_size(out) > budget:
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
    "LIMIT_BYTES", "PROTECTED_KEYS", "NOTE_KEYS", "NOTE_RESERVE", "payload_size",
    "compact_size", "serialize", "caveat_cost", "fit", "clip_text_lines",
]
