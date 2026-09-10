"""H5 - structured fixes (`Issue.fix`), CONTRACTS 11.42.

The acceptance criterion the roadmap wrote for this item is a *behavioural*
one, and it is what `test_fix_makes_the_rule_stop_firing` does for every rule
that opts in: apply the edit to the bad fixture, re-parse it, re-analyse it,
and assert the rule goes quiet **and nothing new appears**. An edit that
silences a rule by breaking the file, or by trading one finding for another,
fails here.

Everything else in this module exists because the roadmap called H5 "the
riskiest item on the board because it is the one that edits someone's training
loop": the four conditions that withhold an edit each have a fixture, the
`likely` floor has a fixture on both sides of it, and the clean twins prove the
lightbulb is empty where the code is right.
"""

from __future__ import annotations

import ast
import glob
import inspect
import io
import json
import os
from typing import Dict, List

import pytest

from rule_harness import (SCHEMA_PATH, analyze_fixture, analyze_paths, validate,
                          write_workspace)

from mlview.rules.fixes import (FIX_CODES, FIX_DOCS, FIXABLE_BUCKETS, MAX_EDITS,
                                MECHANICAL, NEEDS_REVIEW, SAFETY_VALUES, Fix,
                                TextEdit, apply_edits, build_fix)
from mlview.rules.registry import all_rules

HERE = os.path.dirname(os.path.abspath(__file__))
FIXES_DIR = os.path.join(HERE, "..", "fixtures", "fixes")
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SAMPLES = os.path.join(REPO, "samples")
MIRROR_SCHEMA = os.path.join(REPO, "analyzer", "src", "mlview", "schema",
                             "graph.schema.json")

#: `(fixture, the code whose edits are applied)` - one per opted-in rule.
ACCEPTANCE = [
    ("MLV111_test_loader_bad.py", "MLV111"),
    ("MLV201_nested_loop_bad.py", "MLV201"),
    ("MLV301_with_block_bad.py", "MLV301"),
    ("MLV302_eval_fn_bad.py", "MLV302"),
    ("MLV602_unseeded_bad.py", "MLV602"),
]

#: A finding fires, and no edit is offered, for the stated reason.
WITHHELD = [
    ("withheld_no_torch_import.py", "MLV602"),
    ("withheld_non_ascii.py", "MLV111"),
    ("withheld_inline_loop_body.py", "MLV201"),
    ("withheld_module_level_eval.py", "MLV302"),
]

#: Every clean twin: the code is right, so there must be nothing to fix.
CLEAN_TWINS = sorted(os.path.basename(p) for p in
                     glob.glob(os.path.join(FIXES_DIR, "*_clean.py")))


# ------------------------------------------------------------------ helpers
def fixes_path(name: str) -> str:
    return os.path.abspath(os.path.join(FIXES_DIR, name)).replace("\\", "/")


def analyze_fixes_fixture(name: str) -> Dict:
    return analyze_paths(fixes_path(name))


def issues_of(doc: Dict, code: str) -> List[Dict]:
    return [i for i in doc.get("issues", []) if i.get("code") == code]


def fixes_in(doc: Dict) -> List[Dict]:
    return [i["fix"] for i in doc.get("issues", []) if isinstance(i.get("fix"), dict)]


def edits_of(issue: Dict) -> List[TextEdit]:
    return [TextEdit(**edit) for edit in issue["fix"]["edits"]]


def apply_to_source(path: str, edits) -> str:
    with io.open(path, encoding="utf-8") as fh:
        return apply_edits(fh.read(), edits)


class _StubModule:
    """The three attributes `build_fix` reads. No IR, no parse, no workspace."""

    def __init__(self, source: str, relpath: str = "stub.py"):
        self.source = source
        self.relpath = relpath
        self.abspath = "/tmp/" + relpath


def _edit(relpath: str, line: int, col: int, end_line: int, end_col: int,
          text: str) -> TextEdit:
    return TextEdit(file=relpath, absFile="/tmp/" + relpath, line=line, col=col,
                    endLine=end_line, endCol=end_col, newText=text)


# ------------------------------------------------- the acceptance criterion
@pytest.mark.parametrize("fixture,code", ACCEPTANCE)
def test_fix_makes_the_rule_stop_firing(tmp_path, fixture, code):
    """Apply, re-parse, re-analyse: the rule goes quiet and nothing new appears."""
    before = analyze_fixes_fixture(fixture)
    firing = issues_of(before, code)
    assert firing, "%s did not fire on %s" % (code, fixture)

    edits: List[TextEdit] = []
    for issue in firing:
        assert isinstance(issue.get("fix"), dict), (
            "%s on %s carries no fix - this fixture exists to produce one"
            % (code, fixture))
        edits.extend(edits_of(issue))
    patched = apply_to_source(fixes_path(fixture), edits)
    assert patched != open(fixes_path(fixture), encoding="utf-8").read()

    ast.parse(patched)                      # the file is still Python

    root = write_workspace(str(tmp_path), {fixture: patched})
    after = analyze_paths(os.path.join(root, fixture))

    assert not issues_of(after, code), (
        "%s still fires after its own fix was applied:\n%s"
        % (code, "\n".join("  line %s: %s" % (i["loc"]["line"], i["message"])
                           for i in issues_of(after, code))))
    new = {i["code"] for i in after.get("issues", [])} - {
        i["code"] for i in before.get("issues", [])}
    assert not new, "applying the %s fix introduced %s" % (code, sorted(new))


@pytest.mark.parametrize("fixture,code", ACCEPTANCE)
def test_fix_shape_is_well_formed(fixture, code):
    doc = analyze_fixes_fixture(fixture)
    for issue in issues_of(doc, code):
        fix = issue["fix"]
        assert fix["safety"] in SAFETY_VALUES
        assert fix["title"] and fix["title"][0].isupper()
        assert 1 <= len(fix["edits"]) <= MAX_EDITS
        files = {edit["file"] for edit in fix["edits"]}
        assert files == {issue["loc"]["file"]}, "one fix, one file"
        for edit in fix["edits"]:
            assert edit["line"] >= 1 and edit["col"] >= 0
            assert (edit["endLine"], edit["endCol"]) >= (edit["line"], edit["col"])
            assert edit["absFile"].endswith(edit["file"])


@pytest.mark.parametrize("fixture", CLEAN_TWINS)
def test_clean_twin_has_no_issue_and_no_fix(fixture):
    """The trust beat: right code yields an empty rail and an empty lightbulb."""
    doc = analyze_fixes_fixture(fixture)
    assert doc["issues"] == [], "%s is not clean: %s" % (
        fixture, [(i["code"], i["loc"]["line"]) for i in doc["issues"]])
    assert fixes_in(doc) == []


@pytest.mark.parametrize("code", sorted(FIX_CODES))
def test_rule_good_fixture_has_no_fix(code):
    """The per-rule false-positive trap offers nothing either."""
    run = analyze_fixture("%s_good" % code)
    assert run.of(code) == []
    assert fixes_in(run.doc) == []


# ------------------------------------------------------ the four refusals
@pytest.mark.parametrize("fixture,code", WITHHELD)
def test_withheld_fixture_fires_but_offers_no_edit(fixture, code):
    doc = analyze_fixes_fixture(fixture)
    firing = issues_of(doc, code)
    assert firing, "%s must still fire on %s - a withheld fix is not a withheld "
    for issue in firing:
        assert issue.get("fix") is None, (
            "%s offered an edit on %s, which exists to prove it does not"
            % (code, fixture))
        assert issue["fixHint"], "the prose hint is never withheld"


def test_no_fix_below_the_likely_bucket():
    """`MLV602_bad.py` seeds globally, so its findings are `possible`.

    Same rule, same shape of call, one bucket lower - and no edit. This is the
    guardrail "no fix at all below the `likely` bucket", asserted from both
    sides: `MLV602_unseeded_bad.py` is the `certain` twin that does get one.
    """
    run = analyze_fixture("MLV602_bad")
    firing = run.of("MLV602")
    assert firing
    for issue in firing:
        assert issue["confidenceBucket"] not in FIXABLE_BUCKETS
        assert issue.get("fix") is None

    unseeded = analyze_fixes_fixture("MLV602_unseeded_bad.py")
    for issue in issues_of(unseeded, "MLV602"):
        assert issue["confidenceBucket"] in FIXABLE_BUCKETS
        assert issue["fix"]["safety"] == MECHANICAL


def test_mechanical_is_reserved_for_single_keyword_edits():
    """`isPreferred` is derived from `safety`, and only two rules earn it."""
    mechanical = {code for code, doc in FIX_DOCS.items() if doc["safety"] == MECHANICAL}
    assert mechanical == {"MLV111", "MLV602"}
    review = {code for code, doc in FIX_DOCS.items() if doc["safety"] == NEEDS_REVIEW}
    assert review == {"MLV201", "MLV301", "MLV302"}
    assert Fix("t", MECHANICAL, ()).is_preferred is True
    assert Fix("t", NEEDS_REVIEW, ()).is_preferred is False


# ----------------------------------------------------------- opt-in is real
def test_only_the_five_rules_can_attach_a_fix():
    """A sixth rule cannot opt in without appearing in `FIX_DOCS`."""
    opted = set()
    for spec in all_rules():
        source = inspect.getsource(spec.func)
        if "fix=" in source:
            opted.add(spec.code)
    assert opted == set(FIX_CODES), (
        "rules attaching a fix: %s; FIX_DOCS: %s" % (sorted(opted), sorted(FIX_CODES)))


def test_no_other_rule_emits_a_fix_across_the_corpora():
    for target in ("vision_pipeline", "vision_pipeline_clean"):
        doc = analyze_paths(os.path.join(SAMPLES, target))
        for issue in doc.get("issues", []):
            if issue.get("fix") is not None:
                assert issue["code"] in FIX_CODES, issue["code"]


def test_the_clean_sample_offers_nothing():
    doc = analyze_paths(os.path.join(SAMPLES, "vision_pipeline_clean"))
    assert doc["issues"] == []
    assert fixes_in(doc) == []


# ----------------------------------------------------------------- the demo
def test_demo_fixes_apply_and_reparse(tmp_path):
    """Every edit the demo publishes lands on the demo's own files."""
    doc = analyze_paths(os.path.join(SAMPLES, "vision_pipeline"))
    fixed = [i for i in doc["issues"] if isinstance(i.get("fix"), dict)]
    assert {i["code"] for i in fixed} == {"MLV111", "MLV201", "MLV301", "MLV302",
                                          "MLV602"}
    for issue in fixed:
        edits = edits_of(issue)
        source = apply_to_source(edits[0].absFile, edits)
        ast.parse(source)


def test_demo_withholds_the_second_split_fix():
    """`data.py` never binds `torch`, so its `random_split` gets prose only.

    The demo is where a reader forms their impression of what the lightbulb
    means, so it has to contain both answers - and `Fixes (N)` has to say the
    second one is there.
    """
    from mlview.emit.text_out import render_summary

    doc = analyze_paths(os.path.join(SAMPLES, "vision_pipeline"))
    splits = issues_of(doc, "MLV602")
    with_edit = [i for i in splits if i.get("fix")]
    without = [i for i in splits if not i.get("fix")]
    assert len(with_edit) == 1 and with_edit[0]["loc"]["file"] == "sklearn_baseline.py"
    assert len(without) == 1 and without[0]["loc"]["file"] == "data.py"

    text = render_summary(doc)
    assert "Fixes (5)" in text
    assert "no edit was computed for 1 other finding(s) of MLV602" in text
    assert "nothing here is applied automatically." in text
    assert "(fix)" in text


def test_summary_and_findings_render_the_marker():
    from mlview.emit.text_out import fix_block, render_findings, render_issue_table

    doc = analyze_fixes_fixture("MLV111_test_loader_bad.py")
    table = render_issue_table(doc["issues"])
    assert "(fix)" in table
    block = "\n".join(fix_block(doc))
    assert "Fixes (1)" in block and MECHANICAL in block
    findings = render_findings(doc["issues"])
    assert "edit: Set shuffle=False" in findings and "(not applied)" in findings

    quiet = analyze_fixes_fixture("MLV111_test_loader_clean.py")
    assert fix_block(quiet) == []


# --------------------------------------------------------------- the schema
def test_schema_mirrors_are_byte_identical():
    with io.open(SCHEMA_PATH, "rb") as fh:
        contract = fh.read()
    with io.open(MIRROR_SCHEMA, "rb") as fh:
        mirror = fh.read()
    assert contract == mirror, "CONTRACTS 11.16: the two schemas must not drift"


def test_schema_declares_the_fix_shape():
    with io.open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    defs = schema["$defs"]
    assert defs["Fix"]["properties"]["safety"]["enum"] == list(SAFETY_VALUES)
    assert defs["Fix"]["additionalProperties"] is False
    assert defs["Fix"]["properties"]["edits"]["maxItems"] == MAX_EDITS
    assert defs["TextEdit"]["required"] == ["file", "absFile", "line", "col",
                                            "endLine", "endCol", "newText"]
    assert defs["Issue"]["properties"]["fix"]["$ref"] == "#/$defs/Fix"
    assert "fix" not in defs["Issue"]["required"], "additive means optional"


def test_a_document_carrying_fixes_validates():
    doc = analyze_paths(os.path.join(SAMPLES, "vision_pipeline"))
    assert fixes_in(doc)
    assert validate(doc) == []


def test_the_frozen_golden_carries_no_fix():
    """`contracts/graph.sample.json` never changes - not even for this."""
    with io.open(os.path.join(REPO, "contracts", "graph.sample.json"),
                 encoding="utf-8") as fh:
        sample = json.load(fh)
    assert all("fix" not in issue for issue in sample["issues"])


# ------------------------------------------------------- the edit machinery
def test_apply_edits_inserts_at_the_ast_indentation():
    source = "def f():\n    if x:\n        g()\n"
    edit = _edit("stub.py", 3, 8, 3, 8, "h()\n        ")
    assert apply_edits(source, [edit]) == "def f():\n    if x:\n        h()\n        g()\n"


def test_apply_edits_replaces_a_range():
    source = "loader(shuffle=True)  # keep me\n"
    edit = _edit("stub.py", 1, 15, 1, 19, "False")
    assert apply_edits(source, [edit]) == "loader(shuffle=False)  # keep me\n"


def test_apply_edits_applies_several_in_one_pass():
    source = "a = f(1)\nb = g(2)\n"
    edits = [_edit("stub.py", 1, 7, 1, 7, ", x=1"), _edit("stub.py", 2, 7, 2, 7, ", y=2")]
    assert apply_edits(source, edits) == "a = f(1, x=1)\nb = g(2, y=2)\n"


def test_apply_edits_refuses_overlaps_and_bad_ranges():
    source = "a = f(1)\n"
    with pytest.raises(ValueError):
        apply_edits(source, [_edit("stub.py", 1, 0, 1, 5, "x"),
                             _edit("stub.py", 1, 3, 1, 8, "y")])
    with pytest.raises(ValueError):
        apply_edits(source, [_edit("stub.py", 9, 0, 9, 0, "x")])
    with pytest.raises(ValueError):
        apply_edits(source, [_edit("stub.py", 1, 0, 1, 99, "x")])
    with pytest.raises(ValueError):
        apply_edits(source, [_edit("stub.py", 1, 5, 1, 2, "x")])


def test_apply_edits_counts_columns_in_utf8_bytes():
    """The AST convention, so a fix built off `col_offset` lands where it means.

    Published fixes never touch a line like this - `_ascii_span` refuses them -
    but the applier still has to agree with the parser about what column 8 is.
    """
    source = "x = 'ok'  # \u2713\n"
    col = len("x = 'ok'  # \u2713".encode("utf-8"))
    assert apply_edits(source, [_edit("stub.py", 1, col, 1, col, "!")]) == \
        "x = 'ok'  # \u2713!\n"


def test_build_fix_rejects_everything_it_cannot_stand_behind():
    module = _StubModule("a = f(1)\nb = 2\n")
    good = _edit(module.relpath, 1, 7, 1, 7, ", x=1")

    assert build_fix(module, "T", MECHANICAL, [good]) is not None
    assert build_fix(module, "T", MECHANICAL, [good, None]) is None, "a builder gave up"
    assert build_fix(module, "", MECHANICAL, [good]) is None, "no title"
    assert build_fix(module, "T", "whatever", [good]) is None, "unknown safety"
    assert build_fix(module, "T", MECHANICAL, []) is None, "no edits"
    assert build_fix(module, "T", MECHANICAL, [good] * (MAX_EDITS + 1)) is None
    assert build_fix(module, "T", MECHANICAL,
                     [_edit("other.py", 1, 0, 1, 0, "x")]) is None, "one fix, one file"
    assert build_fix(module, "T", MECHANICAL,
                     [_edit(module.relpath, 1, 0, 1, 0, "")]) is None, "no-op"


def test_build_fix_refuses_an_edit_that_does_not_reparse():
    """The last gate, and the one that makes the acceptance a property."""
    module = _StubModule("a = f(1)\n")
    broken = _edit(module.relpath, 1, 7, 1, 7, ", **")
    assert apply_edits(module.source, [broken]) == "a = f(1, **)\n"
    with pytest.raises(SyntaxError):
        ast.parse(apply_edits(module.source, [broken]))
    assert build_fix(module, "T", MECHANICAL, [broken]) is None


def test_fix_docs_cover_every_opted_in_rule():
    for code in FIX_CODES:
        entry = FIX_DOCS[code]
        assert entry["safety"] in SAFETY_VALUES
        assert entry["offered"] and entry["withheld"], (
            "%s must state when the edit is withheld, not only when it is offered"
            % code)
