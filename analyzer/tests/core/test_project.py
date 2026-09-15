"""The projection algorithm (CONTRACTS 11.2, FEATURES F2-A1..A9, A15).

The measured figures in this module come from `samples/vision_pipeline` and
legitimately move when a rule changes; the frozen parity battery over
`contracts/graph.sample.json` is asserted here too, against the generated
fixture, so a Python-side change the fixture did not follow fails loudly.
"""

from __future__ import annotations

import copy
import json

import pytest

from core_support import validate
from mlview.api import (AnalyzeOptions, analyze_to_dict, parse_scope, project,
                        resolve_scope)
from scope_support import cases, codes_of, expected, golden, ids_of, sample

SAMPLE_SCOPES = [
    ("concern:evaluation", 1), ("unit:SmallCNN", 1), ("stage:train", None),
    ("concern:optimization", None), ("unit:sklearn_baseline.baseline", None),
    ("unit:batch_loop", 2), ("file:train.py", None), ("unit:Nope", None),
]


def scoped(spec, depth=None, doc=None):
    return project(doc if doc is not None else sample(), parse_scope(spec, depth))


def roles(doc):
    out = {"core": [], "boundary": [], "context": []}
    for node in doc["nodes"]:
        out[node["viewRole"]].append(node["qualname"])
    return out


# ------------------------------------------------------- roles and counts
def test_concern_evaluation_roles_and_context_set():
    """F2-A6, measured: 8 core / 8 boundary / 3 context.

    7 / 7 / 3 before GRAPH-R3: `logits = model(images)` in `validate()` is now
    a `predict` op of its own (it was folded onto the `SmallCNN` class card),
    so the evaluation concern has one more core node and its one-hop ring one
    more boundary node. The context set is unchanged.
    """
    doc = scoped("concern:evaluation", 1)
    parts = roles(doc)
    assert [len(parts[k]) for k in ("core", "boundary", "context")] == [8, 8, 3]
    assert sorted(parts["context"]) == ["data.__main__", "sklearn_baseline.baseline",
                                        "train.train"]
    assert doc["view"]["counts"] == {"core": 8, "boundary": 8, "context": 3}
    assert (doc["view"]["counts"]["core"] + doc["view"]["counts"]["boundary"]
            + doc["view"]["counts"]["context"]) == doc["stats"]["nodes"]


def test_a_unit_scope_can_be_entirely_self_contained():
    """F2-A6: `baseline()` is 13 core nodes with an empty boundary ring."""
    doc = scoped("unit:sklearn_baseline.baseline")
    assert doc["view"]["counts"] == {"core": 13, "boundary": 0, "context": 0}
    assert doc["stats"]["nodes"] == 13 and doc["stats"]["edges"] == 16


def test_the_ancestor_closure_keeps_the_containment_forest_a_forest():
    """`stage:train` gains exactly one `context` node - the parent of a node
    whose lane it is not (CONTRACTS 11.15: a one-node superset).

    9 core before GRAPH-R3, 11 after: the training loop's forward pass
    (`logits`) and its loss computation (`loss`) are ops of their own instead
    of being folded onto the `SmallCNN` class and the `criterion` construction.
    """
    doc = scoped("stage:train")
    parts = roles(doc)
    assert len(parts["core"]) == 11
    assert parts["context"] == ["sklearn_baseline.baseline"]
    kept = {n["id"] for n in doc["nodes"]}
    for node in doc["nodes"]:
        assert node["parent"] is None or node["parent"] in kept


def test_a_parent_crossing_a_stage_lane_is_untouched():
    """`train.train.device` is stage `config` under a `train` parent; roles are
    assigned per node and the forest is preserved exactly."""
    doc = scoped("unit:train")
    device = next(n for n in doc["nodes"] if n["qualname"] == "train.train.device")
    assert device["stage"] == "config" and device["viewRole"] == "core"


# --------------------------------------------------------- issue retention
@pytest.mark.parametrize("spec,depth,codes", [
    ("concern:evaluation", 1, {"MLV103", "MLV301", "MLV302"}),
    ("unit:SmallCNN", 1, {"MLV401", "MLV702"}),
    # GRAPH-R3: MLV401's primary anchor moved from the `criterion =
    # CrossEntropyLoss()` construction (Objective) to the `loss =
    # criterion(logits, labels)` computation (Train), so the train lane now
    # retains it.
    ("stage:train", None, {"MLV201", "MLV205", "MLV401", "MLV501", "MLV601"}),
    ("concern:optimization", None,
     {"MLV201", "MLV205", "MLV401", "MLV501", "MLV601", "MLV702"}),
    ("unit:sklearn_baseline.baseline", None, {"MLV101", "MLV103", "MLV602"}),
])
def test_issue_retention_is_measured_and_exact(spec, depth, codes):
    """F2-A5. An issue survives only through `core` - never through a faded
    boundary stub whose findings are out of scope."""
    assert codes_of(scoped(spec, depth)) == codes


def test_an_issue_anchored_on_a_boundary_node_is_dropped():
    """A boundary stub is drawn so the reader sees where flow enters; its own
    findings are **not** retained by it.

    The example moved with GRAPH-R3: `train.train.criterion` used to be the
    one-hop neighbour of `SmallCNN` (the forward pass folded onto the class
    card, so the class had a data edge straight into the criterion). The
    forward pass is its own node now, and the same property is asserted on
    `model.SmallCNN` itself, which is a boundary node of the evaluation
    concern and carries MLV401 and MLV702 there.
    """
    doc = scoped("concern:evaluation", 1)
    smallcnn = next(n for n in doc["nodes"] if n["qualname"] == "model.SmallCNN")
    assert smallcnn["viewRole"] == "boundary"
    assert smallcnn["issueIds"] == [], "a boundary stub carries no reverse link"
    assert not {"MLV401", "MLV702"} & codes_of(doc), \
        "a boundary node's own findings are out"


def test_the_stable_rotation_puts_the_badge_on_a_core_card():
    """F2-A5: MLV401's anchors are `[criterion, SmallCNN, softmax()]`; under
    `unit:SmallCNN` they rotate to `[SmallCNN, softmax(), criterion]`.

    Written as a rotation of whatever the anchor list is, rather than against a
    hard-coded pair: REV-06 added the `softmax()` op node ANA-1 mints for the
    offending call as a third anchor, and a rotation is a property of the list,
    not of its length.
    """
    full = sample()
    smallcnn = next(n for n in full["nodes"] if n["qualname"] == "model.SmallCNN")
    before = next(i for i in full["issues"] if i["code"] == "MLV401")
    assert before["nodeIds"][0] != smallcnn["id"], "the unscoped order is unchanged"
    assert smallcnn["id"] in before["nodeIds"]
    assert len(before["nodeIds"]) >= 3, "the offending softmax op is an anchor too"

    doc = scoped("unit:SmallCNN", 1)
    after = next(i for i in doc["issues"] if i["code"] == "MLV401")
    assert after["nodeIds"][0] == smallcnn["id"]
    # CONTRACTS 11.2 step 6 in the order it states: **filter** to the kept ids
    # (order preserved), then stably rotate the first core element to index 0.
    # Written against the filtered list because GRAPH-R3 moved MLV401's primary
    # anchor to `train.train.loss`, which this scope does not keep - and a
    # rotation of a list that lost an element is still a rotation of what is
    # left, which is the property the step actually promises.
    kept = {n["id"] for n in doc["nodes"]}
    filtered = [n for n in before["nodeIds"] if n in kept]
    pivot = filtered.index(smallcnn["id"])
    assert after["nodeIds"] == filtered[pivot:] + filtered[:pivot], \
        "a rotation, not a sort: the rest keeps its relative order"


def test_an_edge_borne_issue_needs_both_endpoints_in_core():
    """A one-node scope keeps MLV401 through its own anchor, and a scope that
    holds neither anchor nor a live retaining edge drops it.

    The anchor is `train.train.loss` since GRAPH-R3 (it was
    `train.train.criterion`, the construction, before the loss *computation*
    had a node of its own).
    """
    doc = scoped("unit:train.train.loss", 0)
    assert doc["view"]["counts"]["core"] == 1
    assert "MLV401" in codes_of(doc), "the loss computation IS core here"
    narrowed = scoped("stage:eval")
    assert "MLV401" not in codes_of(narrowed)


def test_issue_node_ids_and_edge_ids_are_filtered_to_kept_objects():
    doc = scoped("concern:evaluation", 1)
    kept_nodes = {n["id"] for n in doc["nodes"]}
    kept_edges = {e["id"] for e in doc["edges"]}
    for issue in doc["issues"]:
        assert issue["nodeIds"], "invariant 1.1.3: nodeIds[0] is the primary"
        assert set(issue["nodeIds"]) <= kept_nodes
        assert set(issue["edgeIds"]) <= kept_edges


# ------------------------------------------------------------- ghost rules
def test_a_ghost_that_keeps_its_issue_survives():
    doc = scoped("unit:train.train.batch_loop", 0)
    ghosts = [n for n in doc["nodes"] if n["ghost"]]
    assert [g["qualname"] for g in ghosts] == \
        ["train.train.batch_loop.__ghost_zero_grad"]
    assert "MLV201" in codes_of(doc)
    assert ghosts[0]["issueIds"], "invariant 1.1.8"


def test_a_ghost_dragged_in_by_an_edge_without_its_issue_is_pruned():
    """Step 7 on a hand-built document: the ghost is reachable at depth 1 but
    its issue is anchored outside `core`, so both the ghost and the emptied
    issue go."""
    doc = {
        "schemaVersion": "1.0", "generator": {}, "workspace": {},
        "stages": [{"id": "train", "label": "Train", "order": 5, "present": True,
                    "nodeCount": 3, "issueCounts": {"low": 0, "medium": 0, "high": 1},
                    "maxSeverity": "high"}],
        "nodes": [
            {"id": "n:aaaaaaaaaaaa", "stage": "train", "level": "unit", "parent": None,
             "ghost": False, "issueIds": [], "qualname": "m.a", "label": "a",
             "loc": {"file": "m.py", "line": 1}},
            {"id": "n:bbbbbbbbbbbb", "stage": "train", "level": "op", "parent": None,
             "ghost": False, "issueIds": ["i:111111111111"], "qualname": "m.b",
             "label": "b", "loc": {"file": "m.py", "line": 2}},
            {"id": "n:cccccccccccc", "stage": "train", "level": "op",
             "parent": "n:bbbbbbbbbbbb", "ghost": True, "issueIds": ["i:111111111111"],
             "qualname": "m.b.__ghost_x", "label": "x()",
             "loc": {"file": "m.py", "line": 2}},
        ],
        "edges": [{"id": "e:aaaaaaaaaaaa", "kind": "data", "source": "n:aaaaaaaaaaaa",
                   "target": "n:cccccccccccc", "issueIds": []}],
        "issues": [{"id": "i:111111111111", "code": "MLV201", "severity": "high",
                    "stage": "train", "suppressed": False,
                    "nodeIds": ["n:cccccccccccc", "n:bbbbbbbbbbbb"], "edgeIds": []}],
        "diagnostics": [],
        "stats": {"nodes": 3, "edges": 1, "issues": {"low": 0, "medium": 0, "high": 1},
                  "suppressed": 0, "durationMs": 1, "truncated": False},
    }
    out = project(doc, parse_scope("node:n:aaaaaaaaaaaa", 1))
    kept = [n["id"] for n in out["nodes"]]
    assert "n:cccccccccccc" not in kept, "the ghost is pruned (invariant 1.1.8)"
    assert out["issues"] == [], "an issue whose nodeIds emptied out goes with it"
    assert out["edges"] == [], "and the edge that pointed at the ghost"
    # The ghost's parent stays: a `context` ancestor whose only descendants were
    # dropped is still a frame, and re-deriving the closure would re-orphan
    # nodes the algorithm deliberately keeps (FEATURES 3.5).
    assert kept == ["n:aaaaaaaaaaaa", "n:bbbbbbbbbbbb"]
    assert [n["viewRole"] for n in out["nodes"]] == ["core", "context"]


# ----------------------------------------------------- project-level truth
@pytest.mark.parametrize("spec,depth", SAMPLE_SCOPES)
def test_workspace_and_generator_are_carried_verbatim(spec, depth):
    """F2-A1: analysis stays whole-workspace, and a projection never restates
    project-level truth."""
    full = sample()
    doc = scoped(spec, depth)
    assert doc["workspace"] == full["workspace"]
    assert doc["workspace"]["filesAnalyzed"] == 5
    assert doc["generator"] == full["generator"]
    assert doc["schemaVersion"] == full["schemaVersion"]


@pytest.mark.parametrize("spec,depth", SAMPLE_SCOPES)
def test_stage_present_is_carried_through_and_node_counts_are_recomputed(spec, depth):
    """F2-A7 / CONTRACTS 11.4."""
    full = sample()
    doc = scoped(spec, depth)
    assert [s["id"] for s in doc["stages"]] == [s["id"] for s in full["stages"]]
    assert len(doc["stages"]) == 8
    for before, after in zip(full["stages"], doc["stages"]):
        assert after["present"] == before["present"], "project-level truth"
        assert after["nodeCount"] == len([n for n in doc["nodes"]
                                          if n["stage"] == after["id"]])
        counts = {"low": 0, "medium": 0, "high": 0}
        for issue in doc["issues"]:
            if issue["stage"] == after["id"] and not issue["suppressed"]:
                counts[issue["severity"]] += 1
        assert after["issueCounts"] == counts
        assert after["maxSeverity"] == next(
            (s for s in ("high", "medium", "low") if counts[s]), None)


def test_a_present_stage_can_be_empty_in_a_scope():
    doc = scoped("unit:sklearn_baseline.baseline")
    empty_but_present = [s for s in doc["stages"]
                         if s["present"] and s["nodeCount"] == 0]
    assert empty_but_present, "this is the case CONTRACTS 11.4 F1/F2/F3 are about"
    assert validate(doc) == []


def test_view_reports_project_level_totals_and_what_is_hidden():
    full = sample()
    doc = scoped("concern:evaluation", 1)
    view = doc["view"]
    assert view["of"] == {"nodes": len(full["nodes"]), "edges": len(full["edges"]),
                          "issues": full["stats"]["issues"]}
    assert view["hidden"]["nodes"] == len(full["nodes"]) - len(doc["nodes"])
    assert view["hidden"]["edges"] == len(full["edges"]) - len(doc["edges"])
    kept = {n["id"] for n in doc["nodes"]}
    assert view["hidden"]["inboundEdges"] == len(
        [e for e in full["edges"] if e["target"] in kept and e["source"] not in kept])
    assert view["hidden"]["outboundEdges"] == len(
        [e for e in full["edges"] if e["source"] in kept and e["target"] not in kept])


def test_view_is_the_last_key_and_absent_without_a_scope():
    doc = scoped("stage:train")
    assert list(doc.keys())[-1] == "view"
    assert list(doc.keys())[:-1] == list(sample().keys())
    assert "view" not in sample()


# --------------------------------------------------------- ordering (11.2.1)
@pytest.mark.parametrize("spec,depth", SAMPLE_SCOPES)
def test_every_output_array_is_a_subsequence_of_the_input(spec, depth):
    """F2-A4. No output array is ever re-sorted, so a port never reimplements
    a comparator and cannot drift on ordering."""
    full = sample()
    doc = scoped(spec, depth)
    for key in ("nodes", "edges", "issues"):
        assert _is_subsequence(ids_of(doc[key]), ids_of(full[key])), key


def _is_subsequence(small, large):
    iterator = iter(large)
    return all(item in iterator for item in small)


def test_issue_node_ids_keep_their_relative_order_apart_from_the_rotation():
    full = sample()
    doc = scoped("concern:evaluation", 1)
    before = {i["id"]: i["nodeIds"] for i in full["issues"]}
    for issue in doc["issues"]:
        original = [n for n in before[issue["id"]] if n in set(issue["nodeIds"])]
        rotated = issue["nodeIds"]
        index = original.index(rotated[0])
        assert rotated == original[index:] + original[:index]


# ------------------------------------------------------------ depth axis
def test_depth_is_monotone_and_depth_0_has_no_boundary():
    """F2-A15."""
    sets = []
    for depth in (0, 1, 2):
        doc = scoped("unit:train_test_split", depth)
        sets.append({n["id"] for n in doc["nodes"]})
        assert doc["view"]["depth"] == depth
    assert sets[0] <= sets[1] <= sets[2]
    assert sets[0] < sets[2], "the demo scope must actually grow"
    zero = scoped("unit:train_test_split", 0)
    assert [n for n in zero["nodes"] if n["viewRole"] == "boundary"] == []


def test_containment_is_not_a_hop():
    """A child is never pulled in by `depth` - only by the `unit:` descendant
    closure - which is what makes depth mean exactly one thing."""
    doc = scoped("node:n:none", 0, doc=_with_node_id())
    assert doc["stats"]["nodes"] == 1


def _with_node_id():
    doc = copy.deepcopy(sample())
    parent = next(n for n in doc["nodes"] if n["qualname"] == "model.SmallCNN")
    parent["id"] = "n:none"
    for node in doc["nodes"]:
        if node.get("parent") == parent["id"]:
            node["parent"] = "n:none"
    for edge in doc["edges"]:
        for end in ("source", "target"):
            if edge[end] == parent["id"]:
                edge[end] = "n:none"
    doc["edges"] = [e for e in doc["edges"] if "n:none" not in (e["source"], e["target"])]
    return doc


# ------------------------------------------------------------- truncation
def test_max_nodes_runs_before_the_projection_and_is_disclosed(make_workspace):
    """CONTRACTS 11.2.2: the cap stays where it lives; `view.of.nodes` always
    reports the pre-projection count."""
    from test_graph_invariants import MULTIFILE
    root = make_workspace(MULTIFILE)
    capped = analyze_to_dict(AnalyzeOptions(paths=(root,), max_nodes=12))
    assert capped["stats"]["truncated"] is True
    doc = project(capped, parse_scope("stage:train"))
    assert doc["view"]["of"]["nodes"] == len(capped["nodes"])
    assert doc["stats"]["truncated"] is True
    assert any(d["kind"] == "truncated" and "BEFORE this scope" in d["message"]
               for d in doc["diagnostics"]), doc["diagnostics"]
    assert validate(doc) == []


# ---------------------------------------------------------------- purity
def test_project_never_mutates_its_input():
    full = copy.deepcopy(sample())
    snapshot = json.dumps(full, sort_keys=True)
    for spec, depth in SAMPLE_SCOPES:
        project(full, parse_scope(spec, depth))
    assert json.dumps(full, sort_keys=True) == snapshot


def test_project_of_all_is_the_identity():
    full = sample()
    out = project(full, parse_scope("all"))
    assert out == full and "view" not in out


def test_a_projection_can_be_re_projected():
    once = scoped("unit:train")
    twice = project(once, parse_scope("unit:train.train.batch_loop", 0))
    assert twice["view"]["scope"] == "unit:train.train.batch_loop"
    assert list(twice.keys())[-1] == "view"
    assert all("viewRole" in n for n in twice["nodes"])


# ------------------------------------------- retention through an edge alone
_SEV_RANK = {"high": 2, "medium": 1, "low": 0}


def _document_with_an_edge_only_issue():
    """A schema-valid document whose extra issue cites a core-to-core EDGE and
    a node OUTSIDE the scope - the one shape CONTRACTS 11.2 step 6 retains
    through the edge rule alone (R2-F2-07).

    No shipped rule emits it today (every rule that cites an edge also cites
    its two endpoints), but `project()` is contracted as total over any
    schema-valid document, so the case is built by hand rather than waited for.
    """
    doc = copy.deepcopy(sample())
    scope = parse_scope("unit:sklearn_baseline.baseline", 0)
    core = {n["id"] for n in project(doc, scope)["nodes"] if n["viewRole"] == "core"}
    edge = next(e for e in doc["edges"] if e["source"] in core and e["target"] in core)
    outside = next(n for n in doc["nodes"] if n["id"] not in core)
    issue = copy.deepcopy(doc["issues"][0])
    issue.update({"id": "i:ffffffffffff", "severity": "low", "suppressed": False,
                  "nodeIds": [outside["id"]], "edgeIds": [edge["id"]],
                  "stage": outside["stage"], "relatedLocs": [],
                  "loc": copy.deepcopy(edge["loc"])})
    doc["issues"].append(issue)
    doc["issues"].sort(key=lambda i: (-_SEV_RANK[i["severity"]], i["loc"]["file"],
                                      i["loc"]["line"], i["code"]))
    for node in doc["nodes"]:
        if node["id"] == outside["id"]:
            node["issueIds"] = list(node["issueIds"]) + [issue["id"]]
    for candidate in doc["edges"]:
        if candidate["id"] == edge["id"]:
            candidate["issueIds"] = list(candidate["issueIds"]) + [issue["id"]]
    _recount(doc)
    assert validate(doc) == [], "the hand-built input is itself contract-valid"
    return doc, scope, issue["id"], edge


def _recount(doc):
    """Re-derive the stage/stats aggregates after the hand-built issue, so the
    INPUT is a contract-valid document rather than an approximation of one."""
    live = [i for i in doc["issues"] if not i.get("suppressed")]
    for row in doc["stages"]:
        counts = {sev: sum(1 for i in live
                           if i["stage"] == row["id"] and i["severity"] == sev)
                  for sev in ("low", "medium", "high")}
        row["issueCounts"] = counts
        row["maxSeverity"] = next((s for s in ("high", "medium", "low")
                                   if counts[s]), None)
        row["present"] = bool(row["nodeCount"] or any(counts.values()))
    doc["stats"]["issues"] = {sev: sum(1 for i in live if i["severity"] == sev)
                              for sev in ("low", "medium", "high")}
    doc["stats"]["suppressed"] = sum(1 for i in doc["issues"] if i.get("suppressed"))


def test_an_issue_kept_by_the_edge_rule_never_ends_with_empty_node_ids():
    """R2-F2-07. Step 6 retains through `edgeIds` independently of `nodeIds`,
    then filters `nodeIds` to kept nodes - so an issue could survive with
    `nodeIds: []`, which breaks invariant 1.1.3 (`nodeIds[0]` always names a
    node) and leaves the renderer nowhere to put the badge. The schema cannot
    catch it: `Issue.nodeIds` has no `minItems`. The retaining edge's `source`
    is promoted instead - a `core` node by construction - and the reverse link
    is written with it, so no invariant is traded for another."""
    doc, scope, issue_id, edge = _document_with_an_edge_only_issue()
    out = project(doc, scope)
    kept = {i["id"]: i for i in out["issues"]}
    assert issue_id in kept, "the core-to-core edge retains it (step 6)"
    assert kept[issue_id]["nodeIds"] == [edge["source"]]
    assert kept[issue_id]["edgeIds"] == [edge["id"]]
    holder = next(n for n in out["nodes"] if n["id"] == edge["source"])
    assert issue_id in holder["issueIds"], "the node <-> issue link stays two-way"
    assert all(issue["nodeIds"] for issue in out["issues"])
    assert validate(out) == []


def test_an_edge_only_issue_outside_the_scope_is_simply_dropped():
    """The other half of the rule: no core-to-core edge, no retention - the
    promotion must never resurrect an issue step 6 did not keep."""
    doc, _scope, issue_id, _edge = _document_with_an_edge_only_issue()
    out = project(doc, parse_scope("unit:SmallCNN", 0))
    assert issue_id not in {i["id"] for i in out["issues"]}
    assert validate(out) == []


# ------------------------------------------------------- the frozen battery
def test_the_battery_covers_every_kind_and_every_error_code():
    """MLV-P12 (CONTRACTS 11.47 E) grew the battery from 10 + 6 to 13 + 7: three
    `pipeline:` projections and the new `unknown_pipeline` refusal. The counts
    are still pinned, because a case silently dropped from the generator is a
    parity gate that stops testing something."""
    kinds = [c["kind"] for c in cases()]
    assert kinds.count("project") == 13 and kinds.count("error") == 7
    assert {c["error"]["code"] for c in expected().values()
            if c["kind"] == "error"} == {"bad_selector", "unknown_stage",
                                         "unknown_concern", "unknown_node",
                                         "unknown_file", "bad_depth",
                                         "unknown_pipeline"}
    specs = {c["spec"].split(":", 1)[0] for c in cases() if c["kind"] == "project"}
    assert "pipeline" in specs


@pytest.mark.parametrize("case", [c for c in cases() if c["kind"] == "project"],
                         ids=lambda c: c["name"])
def test_the_generated_fixture_still_matches_the_implementation(case):
    """The parity gate the TypeScript port is measured against: if this fails,
    `analyzer/tools/gen_scope_fixtures.py` must be re-run and the viewer's
    `scope_parity.test.mjs` re-checked."""
    doc = project(golden(), parse_scope(case["spec"], case["depth"]))
    assert doc == expected()[case["name"]]["doc"]


@pytest.mark.parametrize("case", [c for c in cases() if c["kind"] == "project"],
                         ids=lambda c: c["name"])
def test_every_battery_case_is_a_valid_document(case):
    """F2-A2 / F2-A3: schema plus every invariant group of
    `contracts/validate_sample.py`."""
    doc = project(golden(), parse_scope(case["spec"], case["depth"]))
    assert validate(doc) == []
    assert len(doc["stages"]) == 8
    for key in ("nodes", "edges", "issues"):
        assert _is_subsequence(ids_of(doc[key]), ids_of(golden()[key])), key


def test_the_identity_case_carries_no_view():
    doc = project(golden(), parse_scope("all"))
    assert "view" not in doc
    assert doc == golden()
    assert all("viewRole" not in n for n in doc["nodes"])


# ------------------------------------------------------------- suppression
SUPPRESSED = {
    "train.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from torch.utils.data import DataLoader\n\n\n"
                 "def train(ds):\n"
                 "    torch.manual_seed(0)\n"
                 "    model = nn.Linear(4, 2)\n"
                 "    crit = nn.CrossEntropyLoss()\n"
                 "    opt = optim.Adam(model.parameters())\n"
                 "    loader = DataLoader(ds, batch_size=8)\n"
                 "    for x, y in loader:  # mlview: ignore[MLV201]\n"
                 "        loss = crit(model(x), y)\n"
                 "        loss.backward()\n"
                 "        opt.step()\n"),
}


def test_a_suppressed_issue_follows_the_same_rule_and_stays_suppressed(analyze_ws):
    """CONTRACTS 11.2 step 6: suppressed issues are retained like any other and
    keep `suppressed: true`; `stats.suppressed` counts the retained ones and
    the stage counts still ignore them."""
    full = analyze_ws(SUPPRESSED)
    suppressed = [i for i in full["issues"] if i["suppressed"]]
    assert suppressed, "the fixture must plant a suppressed finding"

    doc = project(full, parse_scope("stage:train"))
    kept = [i for i in doc["issues"] if i["suppressed"]]
    assert [i["id"] for i in kept] == [i["id"] for i in suppressed]
    assert doc["stats"]["suppressed"] == len(kept)
    train = next(s for s in doc["stages"] if s["id"] == "train")
    assert train["issueCounts"]["high"] == len(
        [i for i in doc["issues"]
         if i["stage"] == "train" and i["severity"] == "high" and not i["suppressed"]])
    assert validate(doc) == []

    narrowed = project(full, parse_scope("concern:data"))
    assert [i for i in narrowed["issues"] if i["suppressed"]] == []
