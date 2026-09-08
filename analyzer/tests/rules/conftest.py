"""Fixtures for the per-rule tests; the harness itself lives in `rule_harness`.

**Import the harness as `rule_harness`, not as `conftest`:**

    from rule_harness import assert_fires, assert_silent

`tests/core/` and `tests/rules/` both put a `conftest.py` on `sys.path`, and
only the first one imported wins the name `conftest` - so `from conftest
import ...` in a test module resolves to whichever suite pytest collected
first. The names are re-exported below for the case where this suite runs
alone, but `rule_harness` is unambiguous in every collection order.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from rule_harness import (  # noqa: F401 - re-exported for `from conftest import ...`
    EXPECT_NONE_RE,
    EXPECT_RE,
    FIXTURES,
    RULE_FIXTURES,
    TESTS_DIR,
    Expectation,
    FixtureRun,
    analyze_fixture,
    assert_expectation,
    assert_fires,
    assert_silent,
    fixture_path,
    parse_expectations,
    rule_fixture_pairs,
)

# -------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def rules_harness():
    """The harness as one object, for tests that prefer an injected helper."""

    class _Harness:
        FIXTURES = RULE_FIXTURES
        analyze = staticmethod(analyze_fixture)
        fires = staticmethod(assert_fires)
        silent = staticmethod(assert_silent)
        path = staticmethod(fixture_path)
        pairs = staticmethod(rule_fixture_pairs)
        parse = staticmethod(parse_expectations)

    return _Harness()


@pytest.fixture
def analyze_rule_fixture():
    """`analyze_rule_fixture("MLV201_bad")` -> `FixtureRun`."""
    return analyze_fixture
