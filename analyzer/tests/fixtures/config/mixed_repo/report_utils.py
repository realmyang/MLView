"""The non-framework half: ordinary application code, deliberately unreachable.

Nothing here mentions any token in `core.relevance.framework_tokens()` and
nothing imports it, so `--relevance ml` sets it aside. That is the whole point
of the file: 11.39 flipped the shipped default, and a filter that narrows a
workspace has to be provable on a workspace it actually narrows.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List


def read_rows(path: str) -> List[Dict[str, str]]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return list(json.load(handle))


def format_table(rows: List[Dict[str, str]], columns: List[str]) -> str:
    widths = [max([len(c)] + [len(str(r.get(c, ""))) for r in rows]) for c in columns]
    header = "  ".join(c.ljust(w) for c, w in zip(columns, widths))
    body = ["  ".join(str(r.get(c, "")).ljust(w) for c, w in zip(columns, widths))
            for r in rows]
    return "\n".join([header] + body)
