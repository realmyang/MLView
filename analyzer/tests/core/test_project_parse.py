"""The scope selector grammar (CONTRACTS 11.1).

One string, exactly one `kind` and one `target`, split on the **first** colon
only - a node id contains one. `depth` always travels as its own parameter.
Only the error **code**, the offending **term** and the sorted, <=10-entry
candidate list are contractual; the prose is free.
"""

from __future__ import annotations

import pytest

from mlview.api import (CONCERN_ALIASES, CONCERNS, SCOPE_KINDS, Scope, ScopeError,
                        parse_scope)
from mlview.core.project import DEFAULT_DEPTH, MAX_DEPTH, SCOPE_SPELLINGS

STAGE_IDS = ("config", "data", "preprocess", "model", "objective", "train",
             "eval", "deliver")


# ------------------------------------------------------------ valid forms
@pytest.mark.parametrize("spec,kind,target", [
    ("unit:sklearn_baseline.baseline", "unit", "sklearn_baseline.baseline"),
    ("stage:train", "stage", "train"),
    ("file:data.py", "file", "data.py"),
    ("concern:evaluation", "concern", "evaluation"),
    ("node:n:55662bceebd0", "node", "n:55662bceebd0"),
    ("unit:n:55662bceebd0", "unit", "n:55662bceebd0"),
    ("unit:train()", "unit", "train()"),
])
def test_every_valid_form_parses(spec, kind, target):
    scope = parse_scope(spec)
    assert (scope.kind, scope.target, scope.spec) == (kind, target, spec)


def test_a_node_id_is_split_on_the_first_colon_only():
    scope = parse_scope("node:n:55662bceebd0")
    assert scope.target == "n:55662bceebd0", "a node id contains a colon"


def test_all_and_the_empty_spec_mean_the_whole_document():
    for spec in ("all", "ALL", " all ", "", "   ", None):
        scope = parse_scope(spec)
        assert scope.kind == "all" and scope.spec == "all" and scope.is_all


def test_the_kind_is_lowercased_but_the_target_is_not():
    scope = parse_scope("UNIT:SmallCNN")
    assert scope.kind == "unit"
    assert scope.target == "SmallCNN", "a qualname is case-sensitive data"


def test_symbol_normalizes_to_unit():
    scope = parse_scope("symbol:model.SmallCNN")
    assert scope.kind == "unit"
    assert scope.spec == "unit:model.SmallCNN", "view.scope reports the normal form"
    assert scope == parse_scope("unit:model.SmallCNN")


@pytest.mark.parametrize("alias,canonical", sorted(CONCERN_ALIASES.items()))
def test_a_concern_alias_normalizes_before_validation(alias, canonical):
    scope = parse_scope("concern:" + alias)
    assert scope.target == canonical
    assert scope.spec == "concern:" + canonical
    assert scope == parse_scope("concern:" + canonical), "byte-identical documents"


def test_the_four_concerns_partition_the_eight_stages():
    covered = [s for stages in CONCERNS.values() for s in stages]
    assert sorted(covered) == sorted(STAGE_IDS)
    assert len(covered) == len(set(covered)), "no stage is claimed by two concerns"


def test_a_windows_path_is_forward_slashed_inside_a_file_target():
    assert parse_scope(r"file:pkg\data.py").target == "pkg/data.py"
    assert parse_scope(r"file:pkg\data.py").spec == "file:pkg/data.py"


def test_surrounding_whitespace_is_trimmed():
    assert parse_scope("  stage:train  ") == parse_scope("stage:train")


# ------------------------------------------------------------------ depth
def test_depth_defaults_are_per_kind():
    # MLV-P12 (CONTRACTS 11.47 B) appends `pipeline` at depth 0: a pipeline is
    # already a whole region, and its relation carries containment, so a ring
    # around it is mostly noise. Every pre-existing default is unchanged.
    assert DEFAULT_DEPTH == {"unit": 1, "node": 1, "stage": 0, "file": 0,
                             "concern": 0, "all": 0, "pipeline": 0}
    assert parse_scope("unit:x").depth == 1
    assert parse_scope("node:n:1").depth == 1
    assert parse_scope("stage:train").depth == 0
    assert parse_scope("file:a.py").depth == 0
    assert parse_scope("concern:data").depth == 0
    assert parse_scope("pipeline:train.py").depth == 0


@pytest.mark.parametrize("value", [0, 1, 2, "0", "2", " 1 "])
def test_an_explicit_depth_overrides_the_default(value):
    assert parse_scope("unit:x", value).depth == int(str(value).strip())


@pytest.mark.parametrize("value", [3, -1, 99, "x", "1.5", 1.5, True, "", " "])
def test_depth_outside_0_2_is_bad_depth(value):
    if value in ("", " "):                       # empty means "use the default"
        assert parse_scope("unit:x", value).depth == 1
        return
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("unit:x", value)
    assert excinfo.value.code == "bad_depth"
    assert excinfo.value.candidates == ("0", "1", "2")
    assert MAX_DEPTH == 2


# ----------------------------------------------------------- error codes
def test_a_spec_without_a_colon_is_bad_selector():
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("train")
    assert excinfo.value.code == "bad_selector"
    assert excinfo.value.term == "train"
    assert "unit" in excinfo.value.candidates


def test_an_unknown_kind_is_bad_selector_naming_the_kind():
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("bogus:x")
    assert (excinfo.value.code, excinfo.value.term) == ("bad_selector", "bogus")


@pytest.mark.parametrize("spec", ["unit:", "symbol:", "UNIT:  "])
def test_an_empty_unit_target_is_bad_selector_with_the_empty_term(spec):
    """`unit:` is the one kind whose unresolvable target is an empty scope
    rather than an error (CONTRACTS 11.1), so an empty target must be rejected
    by the parser or a typo becomes a silent zero-node document. R2-F2-06: the
    reported `term` is the missing half, not the whole spec - the user
    demonstrably knows the kind already."""
    with pytest.raises(ScopeError) as excinfo:
        parse_scope(spec)
    assert (excinfo.value.code, excinfo.value.term) == ("bad_selector", "")


def test_a_known_kind_with_an_empty_target_reports_that_kinds_own_code():
    """R2-F2-06. CONTRACTS 11.1 spends `bad_selector` on "no `:`, or an unknown
    `kind`". `stage:` and `concern:` have a colon AND a known kind, so they
    fall through to their own validation and answer with their own candidate
    list instead of re-listing the six kinds."""
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("stage:")
    assert (excinfo.value.code, excinfo.value.term) == ("unknown_stage", "")
    assert excinfo.value.candidates == tuple(sorted(STAGE_IDS))
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("concern:")
    assert (excinfo.value.code, excinfo.value.term) == ("unknown_concern", "")
    assert excinfo.value.candidates == tuple(sorted(CONCERNS))


@pytest.mark.parametrize("spec,kind", [("node:", "node"), ("file:", "file")])
def test_an_empty_node_or_file_target_is_left_to_the_resolver(spec, kind):
    """R2-F2-06. Only the resolver can name the candidates 11.1 requires for
    these two (this graph's node ids, its analyzed `loc.file` values), so the
    parser passes the empty target on; `test_project_resolve.py` asserts the
    `unknown_node` / `unknown_file` that comes back."""
    scope = parse_scope(spec)
    assert (scope.kind, scope.target, scope.spec) == (kind, "", spec)


def test_an_unknown_stage_names_the_eight():
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("stage:nope")
    assert (excinfo.value.code, excinfo.value.term) == ("unknown_stage", "nope")
    assert excinfo.value.candidates == tuple(sorted(STAGE_IDS))


def test_an_unknown_concern_names_the_four_canonical_presets():
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("concern:nope")
    assert (excinfo.value.code, excinfo.value.term) == ("unknown_concern", "nope")
    assert excinfo.value.candidates == tuple(sorted(CONCERNS))


def test_unknown_unit_is_never_raised():
    """A `unit:` target that resolves to nothing is an *empty scope*, not an
    error (CONTRACTS 11.2 step 9)."""
    assert parse_scope("unit:Nope").target == "Nope"


def test_scope_error_is_a_value_error_with_a_sorted_capped_candidate_list():
    error = ScopeError("unknown_node", "n:x", ["n:c", "n:a", "n:b"] * 8)
    assert isinstance(error, ValueError)
    assert error.candidates == ("n:a", "n:b", "n:c")
    assert len(ScopeError("x", "y", ["n:%02d" % i for i in range(40)]).candidates) == 10


# ------------------------------------------------------------- round trip
@pytest.mark.parametrize("spec", [
    "all", "unit:train.train", "stage:eval", "file:sklearn_baseline.py",
    "concern:optimization", "node:n:8d3e0f7a2b61", "symbol:model.SmallCNN",
    "concern:inference", r"file:pkg\net.py",
])
def test_parse_format_parse_round_trips(spec):
    once = parse_scope(spec, 1 if spec != "all" else None)
    twice = parse_scope(once.spec, once.depth)
    assert once == twice
    assert isinstance(once, Scope)


def test_the_kind_tuple_is_frozen():
    """Frozen means *additive only*: MLV-P12 (CONTRACTS 11.47 B2) appends
    `pipeline` and moves nothing. The five that shipped keep their exact order,
    because `SCOPE_SPELLINGS` - and therefore the `bad_selector` candidate list
    both ports must agree on - is derived from this tuple."""
    assert SCOPE_KINDS[:5] == ("unit", "stage", "file", "concern", "node")
    assert SCOPE_KINDS == ("unit", "stage", "file", "concern", "node", "pipeline")
    assert SCOPE_SPELLINGS == ("all", "concern", "file", "node", "pipeline",
                               "stage", "symbol", "unit")


# ------------------------------------------------ case-mismatch prose (F2-08)
# `stage:` and `concern:` targets are matched EXACTLY (11.1 lowercases the kind
# only), while `unit:` and `file:` fold case during resolution. Folding these
# two here would change the grammar, which is a two-port change (11.16), so the
# message names the canonical spelling instead. Only the code, the term and the
# candidate list are contractual - these assertions guard the prose, not it.
@pytest.mark.parametrize("spec,code,hint", [
    ("stage:TRAIN", "unknown_stage", "stage:train"),
    ("stage:Eval", "unknown_stage", "stage:eval"),
    ("concern:Evaluation", "unknown_concern", "concern:evaluation"),
    ("concern:INFERENCE", "unknown_concern", "concern:evaluation"),
])
def test_a_case_only_typo_is_told_the_canonical_spelling(spec, code, hint):
    with pytest.raises(ScopeError) as excinfo:
        parse_scope(spec)
    error = excinfo.value
    assert error.code == code, "the code and term stay exactly as contracted"
    assert error.term == spec.split(":", 1)[1] or error.term
    assert hint in str(error)


def test_a_genuinely_unknown_target_gets_no_invented_suggestion():
    with pytest.raises(ScopeError) as excinfo:
        parse_scope("stage:nope")
    assert "did you mean" not in str(excinfo.value)
