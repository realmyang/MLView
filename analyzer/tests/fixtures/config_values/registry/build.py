"""`getattr(<workspace module>, <a name>)` with the name unresolvable.

The answer is still bounded: it is one of the symbols `factories` defines, and
"one of Alpha, Beta" is a claim a reader can check. `unknown` never was.
"""
from __future__ import annotations

import factories


def build(name):
    cls = getattr(factories, name)
    return cls()
