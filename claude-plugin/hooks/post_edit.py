#!/usr/bin/env python
"""H8 — the ``PostToolUse`` hook: say something only when an edit ADDED a finding.

Matched on ``Edit|Write|NotebookEdit`` by ``hooks/hooks.json``. Everything it
does lives in ``hook_core.run_hook``; this file exists so the manifest can name
one path per event and so each event's entry point is trivially readable.

It exits 0 in every reachable case — a ``PostToolUse`` hook that exits 2 blocks
the tool call, and MLView is advisory.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_core import main  # noqa: E402  (needs the sys.path line above)

if __name__ == "__main__":
    raise SystemExit(main("PostToolUse"))
