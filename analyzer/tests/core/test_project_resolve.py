"""`unit:` and `file:` resolution against `samples/vision_pipeline`
(CONTRACTS 11.2 step 1).

Resolution runs against the **finished graph document**, never the IR - which
is precisely what lets the TypeScript port resolve identically with no
analyzer. Tier 3 (a *definition*: the last dotted segment at level stage/unit)
is what makes `unit:train` mean the function `train.train` rather than also
dragging in the unrelated `model.train()` op node `train.train.train`.
"""

from __future__ import annotations

import pytest

from core_support import validate
from mlview.api import ScopeError, parse_scope, project, resolve_scope
from scope_support import sample


def qualnames(doc, ids):
    by_id = {n["id"]: n for n in doc["nodes"]}
    return [by_id[i]["qualname"] for i in ids]


def resolve(spec, depth=None):
    doc = sample()
    return doc, resolve_scope(doc, parse_scope(spec, depth))


# ------------------------------------------------------------ the tiers
def test_tier_1_matches_a_full_qualname():
    doc, res = resolve("unit:sklearn_baseline.baseline")
    assert qualnames(doc, res.anchors) == ["sklearn_baseline.baseline"]
    assert len(res.core) == 13, "a unit means its whole definition"


def test_tier_2_matches_an_fqn():
    doc, res = resolve("unit:torch.optim.Adam")
    assert qualnames(doc, res.anchors) == ["train.train.optimizer"]


def test_tier_3_beats_tier_4_so_unit_train_is_the_function():
    """`unit:train` -> `train.train` alone, not the `model.train()` op node
    `train.train.train` that tier 4 would also match."""
    doc, res = resolve("unit:train")
    assert qualnames(doc, res.anchors) == ["train.train"]
    # the tier-4 op `train.train.train` is *not* an anchor; it comes along only
    # as a descendant of the function, which is where it belongs.
    assert "train.train.train" not in qualnames(doc, res.anchors)
    assert "train.train.train" in qualnames(doc, res.core)
    # 10 -> 13: GRAPH-R3 draws `model = SmallCNN()` and the two `model(images)`
    # forward passes, and the first of those is a descendant of `train()`.
    assert len(res.core) == 13


def test_tier_4_catches_a_call_site_op_with_no_definition():
    """`train_test_split` has no tier-3 match (it is an `op`), so resolution
    correctly falls through to tier 4."""
    doc, res = resolve("unit:train_test_split")
    assert qualnames(doc, res.anchors) == ["sklearn_baseline.baseline.train_test_split"]
    by_id = {n["id"]: n for n in doc["nodes"]}
    assert by_id[res.anchors[0]]["level"] == "op"


def test_tier_5_matches_a_label():
    doc, res = resolve("unit:data.py")
    assert qualnames(doc, res.anchors) == ["data.__main__"]


def test_a_trailing_call_pair_is_stripped():
    doc, res = resolve("unit:train()")
    assert qualnames(doc, res.anchors) == ["train.train"]


def test_a_node_id_resolves_through_unit_too():
    """The tools hand back ids; a human types a qualname. Both must work."""
    doc = sample()
    smallcnn = next(n for n in doc["nodes"] if n["qualname"] == "model.SmallCNN")
    _doc, res = resolve("unit:" + smallcnn["id"])
    assert res.anchors == (smallcnn["id"],)


# ----------------------------------------------------------- ambiguity
def test_two_batch_loops_resolve_to_two_anchors_and_report_ambiguity():
    doc, res = resolve("unit:batch_loop")
    assert sorted(qualnames(doc, res.anchors)) == ["train.train.batch_loop",
                                                   "train.validate.batch_loop"]
    assert res.ambiguous is True
    assert any("train.validate.batch_loop" in w for w in res.warnings), res.warnings


def test_ambiguity_reaches_the_document_as_a_diagnostic():
    doc = project(sample(), parse_scope("unit:batch_loop", 0))
    assert doc["view"]["ambiguous"] is True
    assert len(doc["view"]["resolvedTo"]) == 2
    warnings = [d for d in doc["diagnostics"]
                if d["kind"] == "config_warning" and "ambiguous" in d["message"]]
    assert warnings, doc["diagnostics"]
    assert validate(doc) == []


def test_a_single_match_is_not_ambiguous():
    _doc, res = resolve("unit:sklearn_baseline.baseline")
    assert res.ambiguous is False


# ------------------------------------------------- case-insensitive retry
def test_a_case_insensitive_hit_warns_and_names_the_canonical_spelling():
    doc, res = resolve("unit:smallcnn")
    assert qualnames(doc, res.anchors) == ["model.SmallCNN"]
    assert any("model.SmallCNN" in w for w in res.warnings), res.warnings


def test_the_exact_tier_wins_over_the_folded_one():
    _doc, res = resolve("unit:SmallCNN")
    assert res.warnings == (), "an exact hit never warns"


def test_file_resolution_is_exact_then_basename_then_folded():
    doc = sample()
    exact = resolve_scope(doc, parse_scope("file:sklearn_baseline.py"))
    folded = resolve_scope(doc, parse_scope("file:SKLEARN_BASELINE.PY"))
    assert exact.anchors == folded.anchors
    assert exact.warnings == () and folded.warnings


# ----------------------------------------------------- empty, not an error
def test_unit_nope_is_an_empty_scope_not_an_error():
    doc, res = resolve("unit:Nope")
    assert res.anchors == () and res.core == ()
    assert res.empty is True
    projected = project(doc, parse_scope("unit:Nope"))
    assert projected["nodes"] == [] and projected["edges"] == []
    assert projected["issues"] == []
    assert len(projected["stages"]) == 8
    assert projected["view"]["empty"] is True
    assert projected["view"]["resolvedTo"] == []
    assert any(d["kind"] == "config_warning" and "matched no nodes" in d["message"]
               for d in projected["diagnostics"])
    assert validate(projected) == [], "an empty projection is still a valid document"


def test_an_empty_stage_is_empty_but_legal():
    projected = project(sample(), parse_scope("stage:deliver"))
    assert projected["stats"]["nodes"] == 0
    assert projected["view"]["empty"] is True


# ----------------------------------------------------------- graph errors
def test_an_unknown_node_id_names_candidates_from_this_graph():
    with pytest.raises(ScopeError) as excinfo:
        resolve("node:n:deadbeefdead")
    assert excinfo.value.code == "unknown_node"
    assert excinfo.value.term == "n:deadbeefdead"
    assert len(excinfo.value.candidates) == 10
    assert all(c.startswith("n:") for c in excinfo.value.candidates)


def test_an_unknown_file_names_the_analyzed_files():
    with pytest.raises(ScopeError) as excinfo:
        resolve("file:nope.py")
    assert excinfo.value.code == "unknown_file"
    assert "train.py" in excinfo.value.candidates


@pytest.mark.parametrize("spec,code", [("node:", "unknown_node"),
                                       ("file:", "unknown_file")])
def test_an_empty_node_or_file_target_raises_that_kinds_error(spec, code):
    """R2-F2-06. The parser defers these two; the resolver answers with the
    kind's own code, the empty term and a real candidate list."""
    with pytest.raises(ScopeError) as excinfo:
        project(sample(), parse_scope(spec))
    assert (excinfo.value.code, excinfo.value.term) == (code, "")
    assert excinfo.value.candidates, "the candidates the parser could not know"
