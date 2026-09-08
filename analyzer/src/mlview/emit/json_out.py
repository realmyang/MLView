"""Canonical JSON emission.

`indent=2`, `ensure_ascii=False`, LF newlines, key order as built by
`core.graph.MLGraph.to_dict()`, arrays sorted per CONTRACTS section 0. The
same bytes on every run for the same input.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

__all__ = ["dumps", "dump_bytes", "write_json", "load_json"]


def dumps(doc: Dict[str, Any], newline: bool = True) -> str:
    """Canonical JSON text for a graph document."""
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    return text + "\n" if newline else text


def dump_bytes(doc: Dict[str, Any], newline: bool = True) -> bytes:
    return dumps(doc, newline=newline).encode("utf-8")


def write_json(doc: Dict[str, Any], path: str) -> str:
    """Write the document to `path`; returns the absolute, forward-slashed path."""
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps(doc))
    return abs_path.replace("\\", "/")


def load_json(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)
