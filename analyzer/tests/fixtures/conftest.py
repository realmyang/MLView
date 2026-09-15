"""Keep pytest out of the fixture tree.

The fixtures under `analyzer/tests/fixtures/` are **analyzed source**, not
tests: nothing here is imported or executed, and `rule_harness` parses each
file statically. One of them has to be called `tests/test_model.py`, because
PUB-05 is precisely about MLView treating a pytest case as an evaluation loop -
so pytest would otherwise try to collect (and import) a fixture that names a
module MLView invents for it.
"""

collect_ignore_glob = ["*"]
