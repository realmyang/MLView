"""The rule-authoring checklist, enforced mechanically (ISSUE_RULES section 5).

Boxes 1-6: every registered rule is declared through `@rule`, has both
fixtures, a non-empty one-sentence `fixHint` naming a real API, a severity, a
`rule_version`, and a generated `docs/rules/<CODE>.md` page. And the reverse
direction: every fixture on disk belongs to a registered code, so a fixture
cannot be orphaned by a rule that was renamed or deleted.
"""

from __future__ import annotations

import io
import os
import re

import pytest

from mlview.core.graph import SEVERITY_RANK
from mlview.rules.registry import all_rules, rule_for
from rule_harness import (DOCS_RULES, RULE_FIXTURES, analyze_fixture, bad_fixtures,
                          good_fixtures, parse_expectations)

SPECS = all_rules()
CODES = [spec.code for spec in SPECS]
CODE_RE = re.compile(r"^MLV[0-9]{3}$")


def _fixture_codes(paths):
    return {os.path.basename(p).split("_", 1)[0] for p in paths}


# ------------------------------------------------------------------ box 1
@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_declaration_is_complete(spec):
    assert CODE_RE.match(spec.code), spec.code
    assert spec.severity in SEVERITY_RANK, "%s: %r" % (spec.code, spec.severity)
    assert 0.0 < spec.base_prior <= 1.0, "%s: %r" % (spec.code, spec.base_prior)
    assert isinstance(spec.rule_version, int) and spec.rule_version >= 1
    assert spec.tags, "%s declares no tags" % spec.code
    assert callable(spec.func)
    assert spec.module.startswith("mlview.rules.r_"), (
        "%s lives in %s - rules belong in a discoverable r_*.py module"
        % (spec.code, spec.module))


def test_codes_are_unique_and_sorted_stably():
    assert len(CODES) == len(set(CODES))
    assert CODES == sorted(CODES), "all_rules() must return code order"


# ------------------------------------------------------------- boxes 2 and 3
@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_both_fixtures_exist(spec):
    for kind in ("bad", "good"):
        path = os.path.join(RULE_FIXTURES, "%s_%s.py" % (spec.code, kind))
        assert os.path.exists(path), "missing %s" % path


@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_the_bad_fixture_declares_a_header(spec):
    path = os.path.join(RULE_FIXTURES, "%s_bad.py" % spec.code)
    expected, _silent = parse_expectations(io.open(path, encoding="utf-8").read())
    assert expected, "%s_bad.py has no `# MLVIEW-EXPECT:` header" % spec.code
    assert all(e.code == spec.code for e in expected)
    assert all(e.line is not None for e in expected), "pin the line"


@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_the_good_fixture_declares_a_header(spec):
    path = os.path.join(RULE_FIXTURES, "%s_good.py" % spec.code)
    _expected, silent = parse_expectations(io.open(path, encoding="utf-8").read())
    assert silent == [spec.code], "%s_good.py must say MLVIEW-EXPECT-NONE" % spec.code


@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_the_good_fixture_documents_the_trap_it_encodes(spec):
    """Box 3: a good fixture is the nearest false-positive trap, not just
    correct code - and it has to say which trap, or nobody can maintain it."""
    path = os.path.join(RULE_FIXTURES, "%s_good.py" % spec.code)
    text = io.open(path, encoding="utf-8").read()
    assert '"""' in text, "%s_good.py has no docstring" % spec.code
    doc = text.split('"""')[1].lower()
    assert len(doc.split()) >= 8, "%s_good.py: explain the trap" % spec.code


@pytest.mark.parametrize("path", bad_fixtures() + good_fixtures(),
                         ids=lambda p: os.path.basename(p))
def test_fixture_size_is_readable(path):
    """10-40 lines (CONTRACTS section 7.3); a header and a docstring are extra."""
    lines = io.open(path, encoding="utf-8").read().splitlines()
    assert 10 <= len(lines) <= 48, "%s has %d lines" % (os.path.basename(path), len(lines))


# ------------------------------------------------------------------ box 5
@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_fix_hint_is_one_actionable_sentence(spec):
    hint = spec.fix_hint
    assert hint, "%s has no fixHint" % spec.code
    assert len(hint) > 25, "%s: %r is not actionable" % (spec.code, hint)
    assert hint[0].isupper(), "%s: %r" % (spec.code, hint)
    assert any(ch in hint for ch in "().="), (
        "%s: the fix hint must name the actual API: %r" % (spec.code, hint))


@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_why_is_stated_in_ml_terms(spec):
    """Box 8: the consequence, in one sentence, not in linter terms."""
    assert spec.why, "%s has no `why`" % spec.code
    assert len(spec.why.split()) >= 10, "%s: %r" % (spec.code, spec.why)
    assert "rule" not in spec.why.lower().split(), spec.why


@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_title_is_one_short_line(spec):
    assert spec.title, "%s has no title" % spec.code
    assert len(spec.title) <= 70, spec.title
    assert "\n" not in spec.title


# ------------------------------------------------------------------ box 6
@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_the_rule_has_a_documentation_page(spec):
    path = os.path.join(DOCS_RULES, "%s.md" % spec.code)
    assert os.path.exists(path), (
        "missing %s - run `python analyzer/tools/gen_rule_docs.py`" % path)
    text = io.open(path, encoding="utf-8").read()
    assert text.startswith("# %s" % spec.code)
    assert spec.fix_hint.split(".")[0][:40] in text
    assert "## How to fix it" in text
    assert "## Example that fires" in text
    assert "## Example that does not" in text
    if not spec.enabled:
        assert "Disabled in this build" in text, (
            "%s ships disabled; its page must say why" % spec.code)


def test_the_documentation_index_lists_every_rule():
    path = os.path.join(DOCS_RULES, "README.md")
    assert os.path.exists(path)
    text = io.open(path, encoding="utf-8").read()
    for spec in SPECS:
        assert "[%s](%s.md)" % (spec.code, spec.code) in text, spec.code


def test_the_generated_docs_are_up_to_date():
    """The pages are generated, so drift is a test failure, not a review note."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(DOCS_RULES), "..",
                                    "analyzer", "tools"))
    from gen_rule_docs import build  # noqa: E402
    stale = []
    for name, text in sorted(build().items()):
        path = os.path.join(DOCS_RULES, name)
        current = io.open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if current != text:
            stale.append(name)
    assert not stale, ("out of date: %s - run `python analyzer/tools/gen_rule_docs.py`"
                       % ", ".join(stale))


# ------------------------------------------------------- the reverse direction
def test_every_fixture_maps_to_a_registered_code():
    orphans = sorted((_fixture_codes(bad_fixtures()) | _fixture_codes(good_fixtures()))
                     - set(CODES))
    assert not orphans, "fixtures with no rule: %s" % orphans


def test_every_registered_code_has_both_fixtures():
    missing_bad = sorted(set(CODES) - _fixture_codes(bad_fixtures()))
    missing_good = sorted(set(CODES) - _fixture_codes(good_fixtures()))
    assert not missing_bad and not missing_good, (missing_bad, missing_good)


def test_no_documentation_page_is_orphaned():
    pages = {n[:-3] for n in os.listdir(DOCS_RULES)
             if n.endswith(".md") and n != "README.md"}
    assert pages == set(CODES), sorted(pages ^ set(CODES))


# ------------------------------------------------------------ boxes 10 and 12
def test_no_rule_ever_emits_mlv000():
    """MLV000 is the diagnostics channel, never a finding."""
    assert rule_for("MLV000") is None
    for path in bad_fixtures():
        code = os.path.basename(path).split("_", 1)[0]
        for issue in analyze_fixture("%s_bad" % code).issues:
            assert issue["code"] != "MLV000"


@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_a_rule_does_not_duplicate_itself_at_one_location(spec):
    """Box 12: one finding per root cause, never two at the same `loc`."""
    if not spec.enabled:
        pytest.skip("%s ships disabled" % spec.code)
    seen = set()
    for issue in analyze_fixture("%s_bad" % spec.code).of(spec.code):
        key = (issue["loc"]["file"], issue["loc"]["line"])
        assert key not in seen, "%s fired twice at %s" % (spec.code, key)
        seen.add(key)


@pytest.mark.parametrize("spec", SPECS, ids=CODES)
def test_issue_ids_are_content_addressed(spec):
    if not spec.enabled:
        pytest.skip("%s ships disabled" % spec.code)
    for issue in analyze_fixture("%s_bad" % spec.code).of(spec.code):
        assert re.match(r"^i:[0-9a-f]{12}$", issue["id"]), issue["id"]
