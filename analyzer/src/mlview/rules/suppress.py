"""Suppression: `# mlview: ignore` comments and `.mlview.toml`.

* `# mlview: ignore[MLV201]` / `# mlview: ignore` - on the issue's primary
  line **or the line above**.
* `# mlview: ignore-file` - anywhere in the first 5 lines.
* `.mlview.toml`:

      [rules]
      disable = ["MLV601"]

      [paths]
      exclude = ["experiments/**"]

Suppressed issues are still emitted, with `suppressed: true`, so the UI can
offer "show suppressed"; hosts never publish them as diagnostics.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

__all__ = ["RuleConfig", "load_config", "Suppressor", "IGNORE_RE"]

IGNORE_RE = re.compile(r"#\s*mlview\s*:\s*ignore(?:-(?P<file>file))?"
                       r"(?:\s*\[(?P<codes>[^\]]*)\])?", re.IGNORECASE)
_HEADER_LINES = 5


@dataclass
class RuleConfig:
    """The resolved `.mlview.toml`."""

    path: Optional[str] = None
    disabled: Set[str] = field(default_factory=set)
    excludes: Tuple[str, ...] = ()
    warnings: List[str] = field(default_factory=list)


def load_config(config_path: Optional[str], root: Optional[str] = None) -> RuleConfig:
    """Load `.mlview.toml` (explicit path, or the one in the workspace root)."""
    path = config_path
    if path is None and root:
        candidate = os.path.join(root, ".mlview.toml")
        if os.path.isfile(candidate):
            path = candidate
    if not path:
        return RuleConfig()
    config = RuleConfig(path=path.replace("\\", "/"))
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10 without tomllib
        config.warnings.append("tomllib is unavailable; %s was ignored" % path)
        return config
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        config.warnings.append("cannot read %s: %s" % (path, exc))
        return config
    except Exception as exc:  # tomllib.TOMLDecodeError
        config.warnings.append("cannot parse %s: %s" % (path, exc))
        return config

    rules = data.get("rules") or {}
    if isinstance(rules, dict):
        disable = rules.get("disable") or []
        if isinstance(disable, (list, tuple)):
            config.disabled.update(str(c).strip().upper() for c in disable if str(c).strip())
        for key, value in rules.items():
            if key == "disable":
                continue
            text = str(value).strip().lower()
            if text in ("off", "false", "disabled", "no"):
                config.disabled.add(str(key).strip().upper())
            elif text in ("low", "medium", "high"):
                config.warnings.append(
                    "severities are fixed; the override %s = %r in %s was ignored"
                    % (key, value, path))
    paths = data.get("paths") or {}
    if isinstance(paths, dict):
        exclude = paths.get("exclude") or []
        if isinstance(exclude, (list, tuple)):
            config.excludes = tuple(str(p) for p in exclude)
    return config


class Suppressor:
    """Per-file ignore-comment index."""

    def __init__(self, config: Optional[RuleConfig] = None):
        self.config = config or RuleConfig()
        self._files: Dict[str, Tuple[bool, Dict[int, Optional[Set[str]]]]] = {}

    def index_module(self, relpath: str, lines: Sequence[str]) -> None:
        whole_file = False
        marks: Dict[int, Optional[Set[str]]] = {}
        for number, text in enumerate(lines, start=1):
            if "mlview" not in text:
                continue
            match = IGNORE_RE.search(text)
            if not match:
                continue
            if match.group("file"):
                if number <= _HEADER_LINES:
                    whole_file = True
                continue
            codes = match.group("codes")
            if codes:
                marks[number] = {c.strip().upper() for c in codes.split(",") if c.strip()}
            else:
                marks[number] = None          # bare ignore: every code
        self._files[relpath] = (whole_file, marks)

    def is_suppressed(self, code: str, relpath: str, line: int) -> bool:
        if code.upper() in self.config.disabled:
            return True
        entry = self._files.get(relpath)
        if entry is None:
            return False
        whole_file, marks = entry
        if whole_file:
            return True
        for candidate in (line, line - 1):
            if candidate in marks:
                codes = marks[candidate]
                if codes is None or code.upper() in codes:
                    return True
        return False

    def disabled_codes(self) -> Set[str]:
        return set(self.config.disabled)
