#!/usr/bin/env python
"""H8 — the ``Stop`` variant: one summary per turn, for teams that prefer it.

The roadmap pairs this with the PostToolUse hook rather than replacing it
("pair it with a ``Stop`` variant for teams that prefer one summary per turn"),
so both matchers ship and ``MLVIEW_HOOK`` decides which one speaks:

    unset / off  neither (the default)
    on           PostToolUse only
    stop         this one only
    both         both
    off          neither

Its diff is kept in a separate slot of the same state file, so turning the pair
on does not make each of them suppress the other's news.

It exits 0 in every reachable case. A ``Stop`` hook *can* block a turn from
ending by exiting 2; this one never does.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_core import main  # noqa: E402  (needs the sys.path line above)

if __name__ == "__main__":
    raise SystemExit(main("Stop"))
