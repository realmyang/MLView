"""Keep pytest out of this corpus program's `tests/` folder.

`analyzer/tests/accuracy/corpus/` lives under `analyzer/tests/`, so
`pytest analyzer/tests` walks into it. Every corpus program before this one
happened to contain no `test_*.py`, so nothing ever stopped the walk. This
program deliberately ships a `tests/` folder - that is the repository shape it
exists to exercise - and those files import torch, which is not installed on
the machines that run the analyzer suite.

The durable fix is one `collect_ignore_glob` at `corpus/conftest.py`, which is
outside this program's directory; this file is the same guard scoped to the one
program that needs it today.
"""

collect_ignore_glob = ["tests/*"]
