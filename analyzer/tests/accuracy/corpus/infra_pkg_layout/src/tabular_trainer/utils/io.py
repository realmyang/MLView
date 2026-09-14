"""Path helpers. No ML anywhere in this module."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def resolve_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def ensure_dir(path: str) -> Path:
    target = resolve_path(path)
    os.makedirs(target, exist_ok=True)
    return target


def write_json(path: str, payload: Dict[str, Any]) -> Path:
    target = resolve_path(path)
    ensure_dir(str(target.parent))
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return target
