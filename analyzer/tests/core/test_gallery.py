"""MLV-P11's gallery, and the one thing its index must not get wrong.

GALLERY-FALSE-BLINDSPOT: the index used to render a hard-coded paragraph
asserting that MLV301 / MLV302 / MLV401 / MLV501 "structurally cannot fire
here" and that "the analyzer says so on every page as a
`single_file_analysis` diagnostic". Both halves were false on this build - all
four fire on their own self-contained fixtures, and 0 of 90 pages carried the
diagnostic, because `core/coverage.single_file_diagnostic` only speaks when an
analysed module *imports* a sibling that was left out.

The standing criterion is that a surface must say what it could not analyze.
Telling a reader the tool was blind where it was not is the same class of error
in the other direction, and it was asserted, by name, against evidence printed
two tables lower on the same page.
"""

from __future__ import annotations

import importlib.util
import os
import re

import pytest

from core_support import REPO_ROOT

GALLERY = os.path.join(REPO_ROOT, "analyzer", "tools", "gen_gallery.py")


def _module():
    spec = importlib.util.spec_from_file_location("mlview_gen_gallery", GALLERY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gallery():
    return _module()


def _page(gen, diagnostics, codes=()):
    page = gen.Page("x.py", "x.py", "x.html")
    page.diagnostics = list(diagnostics)
    page.codes = list(codes)
    return page


def test_the_caveat_counts_the_pages_that_carry_the_diagnostic(gallery):
    pages = [_page(gallery, ["single_file_analysis"]),
             _page(gallery, []),
             _page(gallery, ["untagged_dataflow"])]
    said = gallery.blindspot_caveat(pages)
    assert "1 of 3 page(s) carry a <code>single_file_analysis</code>" in said


def test_the_caveat_never_claims_a_rule_cannot_fire(gallery):
    """The false half. It is stated as a *measurement* now, or not at all."""
    pages = [_page(gallery, [], ["MLV301", "MLV401"])]
    said = gallery.blindspot_caveat(pages)
    assert "structurally cannot fire" not in said
    assert "MLV301" in said and "fired on at least one single-file page" in said


def test_the_caveat_names_the_rules_that_stayed_quiet(gallery):
    pages = [_page(gallery, [], ["MLV301"])]
    said = gallery.blindspot_caveat(pages)
    assert "did not" in said, said
    assert "MLV401" in said


def test_the_caveat_matches_a_real_run(gallery, tmp_path):
    """One rule end to end: whatever number the index states is the number of
    pages that really carry the diagnostic."""
    out = str(tmp_path / "gallery")
    assert gallery.build(out, "MLV101", "rules", False, True) == 0
    with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    match = re.search(r"(\d+) of (\d+) page\(s\) carry", html)
    assert match, html[:400]
    stated, total = int(match.group(1)), int(match.group(2))
    pages = [p for p in os.listdir(os.path.join(out, "rules", "MLV101"))
             if p.endswith(".html")]
    assert total == len(pages), (total, pages)
    from mlview.api import AnalyzeOptions, analyze_to_dict
    fixtures = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures", "rules")
    carried = 0
    for name in pages:
        doc = analyze_to_dict(AnalyzeOptions(
            paths=(os.path.join(fixtures, name[:-5] + ".py"),)))
        if any(d["kind"] == "single_file_analysis" for d in doc["diagnostics"]):
            carried += 1
    assert stated == carried, (stated, carried)
