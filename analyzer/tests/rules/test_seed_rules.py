"""The four seed rules against their fixtures (CONTRACTS amendment A8).

MLV201 missing `zero_grad` · MLV101 fit before split · MLV401 softmax before
CrossEntropyLoss · MLV601 no seed anywhere.

The rules agent extends this file (and `conftest.py`) with the remaining
sixteen codes; the harness needs no changes to accept them - a new
`<CODE>_bad.py` / `<CODE>_good.py` pair is picked up by
`test_every_fixture_pair_behaves` automatically.
"""

from __future__ import annotations

import pytest

from rule_harness import (
    analyze_fixture,
    assert_fires,
    assert_silent,
    parse_expectations,
    rule_fixture_pairs,
)

SEED_CODES = ("MLV101", "MLV201", "MLV401", "MLV601")


# ------------------------------------------------------------------ the pairs
@pytest.mark.parametrize("code", SEED_CODES)
def test_bad_fixture_fires(code):
    assert_fires("%s_bad" % code)


@pytest.mark.parametrize("code", SEED_CODES)
def test_good_fixture_is_silent(code):
    assert_silent("%s_good" % code, code)


@pytest.mark.parametrize("code", rule_fixture_pairs())
def test_every_fixture_pair_behaves(code):
    """Whatever is on disk must hold, so a new pair cannot be added half-done."""
    assert_fires("%s_bad" % code)
    assert_silent("%s_good" % code, code)


# --------------------------------------------------------- per-rule specifics
def test_mlv201_declares_a_ghost_node_in_the_batch_loop():
    """The absence rule must plant a dashed placeholder in its correct slot (A9)."""
    run = assert_fires("MLV201_bad")
    issue = run.of("MLV201")[0]
    ghosts = [n for n in run.ghost_nodes() if issue["id"] in n["issueIds"]]
    assert len(ghosts) == 1
    ghost = ghosts[0]
    assert ghost["label"] == "zero_grad()"
    assert ghost["sublabel"] == "missing"
    assert ghost["fqn"] == "torch.optim.Optimizer.zero_grad"
    assert ghost["qualname"].endswith(".__ghost_zero_grad")
    assert ghost["issueIds"], "invariant 1.1.8: a ghost always carries an issue"
    assert issue["nodeIds"][0] == ghost["id"], "the badge is drawn on the ghost"
    # the ghost hangs off the batch loop it is missing from
    parent = next(n for n in run.doc["nodes"] if n["id"] == ghost["parent"])
    assert parent["attrs"]["loopKind"] == "batch"
    assert parent["loc"]["line"] == ghost["loc"]["line"]


def test_mlv201_cites_the_optimizer_and_the_backward():
    issue = assert_fires("MLV201_bad").of("MLV201")[0]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert set(roles) == {"optimizer_site", "backward_site"}
    assert roles["optimizer_site"]["line"] == 16      # optimizer = optim.Adam(...)
    assert roles["backward_site"]["line"] == 24       # loss.backward()
    assert "zero_grad" in issue["message"]
    assert issue["severity"] == "high", "static scope, no wrapper: the cap does not bite"


def test_mlv101_cites_the_fit_and_the_split():
    issue = assert_fires("MLV101_bad").of("MLV101")[0]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert set(roles) == {"fit_site", "split_site"}
    assert roles["fit_site"]["line"] == 17            # scaler.fit_transform(X)
    assert roles["split_site"]["line"] == 19          # train_test_split(...)
    assert issue["loc"]["line"] < roles["split_site"]["line"], "the fit is the earlier site"
    assert "sklearn" in issue["frameworks"]


def test_mlv401_attaches_to_the_model_to_loss_edge_when_there_is_one():
    """The pairing rule marks the connection, not just a node (section 7.1)."""
    run = assert_fires("MLV401_bad")
    issue = run.of("MLV401")[0]
    assert issue["nodeIds"], "an issue always names a primary node"
    assert issue["edgeIds"], "the model -> loss edge exists here, so it carries the marker"
    edges = {e["id"]: e for e in run.doc["edges"]}
    for edge_id in issue["edgeIds"]:
        assert edge_id in edges
        edge = edges[edge_id]
        assert edge["kind"] == "data"
        assert issue["id"] in edge["issueIds"], "the edge points back at the issue"
        assert edge["target"] in issue["nodeIds"], "it ends at the loss node"
    related = {r["role"]: r for r in issue["relatedLocs"]}
    assert "final_layer" in related, "the softmax call itself must be cited"
    assert related["final_layer"]["line"] == 19        # return F.softmax(x, dim=1)
    assert related["definition"]["line"] == 10         # class SmallNet(nn.Module)
    assert "cross_file" in {e["kind"] for e in issue["evidence"]}


def test_mlv601_is_workspace_wide_and_lands_on_the_entrypoint():
    run = assert_fires("MLV601_bad")
    issue = run.of("MLV601")[0]
    assert len(run.of("MLV601")) == 1, "an absence rule fires once for the workspace"
    anchor = next(n for n in run.doc["nodes"] if n["id"] == issue["nodeIds"][0])
    assert anchor["kind"] == "entrypoint"
    assert issue["severity"] == "low"
    kinds = {e["kind"] for e in issue["evidence"]}
    assert "negation_absent" in kinds


def test_mlv601_stays_quiet_when_any_file_in_the_workspace_seeds():
    """It is a workspace-wide absence: seeding in one file covers the run."""
    run = analyze_fixture("MLV601_good")
    assert not run.of("MLV601")


# ------------------------------------------------------------- harness itself
def test_expect_headers_are_parsed():
    expected, silent = parse_expectations(
        "# MLVIEW-EXPECT: MLV201 line=18 confidence>=0.6 severity=high\n"
        "# MLVIEW-EXPECT: MLV301 line=40\n"
        "# MLVIEW-EXPECT-NONE: MLV101, MLV601\n")
    assert [e.code for e in expected] == ["MLV201", "MLV301"]
    assert expected[0].line == 18
    assert expected[0].confidence == (">=", 0.6)
    assert expected[0].severity == "high"
    assert expected[1].confidence == ("", 0.0)
    assert silent == ["MLV101", "MLV601"]


def test_a_wrong_expectation_actually_fails():
    """The harness must be able to fail, or none of the above means anything."""
    run = analyze_fixture("MLV201_bad")
    run.expected[0] = run.expected[0].__class__(code="MLV201", raw="MLV201 line=999",
                                                line=999)
    with pytest.raises(AssertionError, match="no occurrence matched"):
        from rule_harness import assert_expectation
        assert_expectation(run, run.expected[0])


def test_every_seed_fixture_declares_a_header():
    for code in SEED_CODES:
        bad = analyze_fixture("%s_bad" % code)
        good = analyze_fixture("%s_good" % code)
        assert bad.expected and bad.expected[0].code == code
        assert good.silent == [code]


def test_mlv401_anchors_on_the_softmax_op_node_ana1_created():
    """REV-06. ANA-1's headline claim is that "issue anchoring follows for
    free" once a `forward()` body mints op nodes - but MLV401's anchor set was
    byte-identical before and after: the reader still landed on the whole class
    card rather than on the line that applies the softmax. The op node exists;
    the rule now names it."""
    run = assert_fires("MLV401_bad")
    issue = run.of("MLV401")[0]
    nodes = {n["id"]: n for n in run.doc["nodes"]}
    anchored = [nodes[i] for i in issue["nodeIds"]]
    softmax = [n for n in anchored
               if (n.get("fqn") or "").endswith(("softmax", "log_softmax"))]
    assert softmax, [(n["label"], n.get("fqn")) for n in anchored]
    # the same line the `final_layer` related location already cited
    related = {r["role"]: r for r in issue["relatedLocs"]}
    assert softmax[0]["loc"]["line"] == related["final_layer"]["line"]
    # ... and the primary anchor did not move: `nodeIds[0]` is still the loss
    assert nodes[issue["nodeIds"][0]]["id"] != softmax[0]["id"]
