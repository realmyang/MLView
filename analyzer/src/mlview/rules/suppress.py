"""Suppression: `# mlview: ignore` comments, and the configuration file.

* `# mlview: ignore[MLV201]` / `# mlview: ignore` - on the issue's primary
  line **or the line above**.
* `# mlview: ignore-file` - anywhere in the first 5 lines.
* `.mlview.toml` (or `[tool.mlview]` in `pyproject.toml`):

      [rules]
      disable = ["MLV601"]

      [paths]
      exclude = ["experiments/**"]
      notebooks = true          # NB: analyze `.ipynb` too (off by default)

Suppressed issues are still emitted, with `suppressed: true`, so the UI can
offer "show suppressed"; hosts never publish them as diagnostics.

**CFG-ONE (CONTRACTS 11.37): the file itself is parsed in `core/config.py`.**
`RuleConfig`, `load_config`, `known_codes` and `unknown_code_warning` are
re-exported from here unchanged, because `mlview.rules` is where every caller
in and out of this tree reaches them - there is one implementation of the
configuration surface, in `core`, and one import path for it, here. What lives
in this module is only what suppression itself needs: the ignore-comment index.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..core.config import (MlviewConfig, RuleConfig, known_codes, load_config,
                           unknown_code_warning)

__all__ = ["RuleConfig", "MlviewConfig", "load_config", "Suppressor", "IGNORE_RE",
           "known_codes", "unknown_code_warning"]

IGNORE_RE = re.compile(r"#\s*mlview\s*:\s*ignore(?:-(?P<file>file))?"
                       r"(?:\s*\[(?P<codes>[^\]]*)\])?", re.IGNORECASE)
_HEADER_LINES = 5


class Suppressor:
    """Per-file ignore-comment index."""

    def __init__(self, config: Optional[RuleConfig] = None):
        self.config = config or RuleConfig()
        self._files: Dict[str, Tuple[bool, Dict[int, Optional[Set[str]]]]] = {}
        #: CLEANUP 3 - an ignore comment naming a code that does not exist
        #: suppresses nothing and used to say nothing. The pipeline turns these
        #: into `config_warning` diagnostics.
        self.warnings: List[str] = []
        self._warned: Set[str] = set()

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
                found = {c.strip().upper() for c in codes.split(",") if c.strip()}
                marks[number] = found
                for code in sorted(found):
                    self._note_unknown(code, "%s:%d" % (relpath, number))
            else:
                marks[number] = None          # bare ignore: every code
        self._files[relpath] = (whole_file, marks)

    def _note_unknown(self, code: str, where: str) -> None:
        if code in self._warned:
            return
        warning = unknown_code_warning(code, "the ignore comment at %s" % where)
        if warning:
            self._warned.add(code)
            self.warnings.append(warning)

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
