"""The fuzz generator's LATER shapes: PERF-04 rollup and MLV-P12 pipelines.

`analyzer/tools/scope_gen_projections.py` teaches the differential fuzzer
(HEALTH-02, CONTRACTS 11.30) to produce two documents it could not produce
before: one that hit `--max-nodes` and was **rolled up** rather than truncated
(11.46), and one carrying a root **`pipelines[]`** block (11.47). Both are
schema-gated — the document schema is `additionalProperties: false` everywhere,
so the generator reads the schema and produces only what it is allowed to.

These tests hold the generated documents to the two amendments: the invariants
in 11.46 C, the block definition in 11.47 D, and the honesty rule that a shape
the repository cannot express is *reported*, never quietly skipped. They are
what stops the fuzzer from going green on documents no analyzer would emit —
a fuzz run asserting parity over fiction is worse than no fuzz run.

What these tests do NOT check: that the *analyzer* rolls a document up this way
(that is `test_rollup.py` / `test_pipelines.py`) or that the two `project()`
implementations agree about the result (that is the fuzzer itself, and
`tools/verify.py --scopes --fuzz N`).
"""

from __future__ import annotations

import copy
import json
import os
import random
import sys

import pytest

from core_support import REPO_ROOT

sys.path.insert(0, os.path.join(REPO_ROOT, "analyzer", "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "contracts"))

import scope_gen_projections as projections  # noqa: E402
import scope_fuzz  # noqa: E402
from scope_gen import make_graph  # noqa: E402
from validate_sample import DEFAULT_SCHEMA, validate_graph  # noqa: E402

SEEDS = tuple(range(9001, 9021))


@pytest.fixture(scope="module")
def documents():
    """One decorated document per seed, under the repository's own schema."""
    out = []
    for seed in SEEDS:
        graph, notes = projections.decorate(make_graph(seed),
                                            random.Random(seed ^ 0x5EED))
        out.append((seed, scope_fuzz._normalize(graph), notes))
    return out


def _validate(doc):
    return validate_graph(doc, run_schema=True)


def _support_is_complete():
    return projections.support().rollup and projections.support().pipelines


# ------------------------------------------------------------- the two shapes
def test_the_generator_produces_both_shapes(documents):
    """If the schema declares the optional fields, a run must actually generate
    them — a fuzzer that only ever emits the old shape is a fuzzer that checks
    the old shape."""
    if not _support_is_complete():
        pytest.skip("this checkout's schema declares %s"
                    % projections.capability_note())
    rolled = [d for _s, d, _n in documents if any("rolledUp" in n for n in d["nodes"])]
    piped = [d for _s, d, _n in documents if d.get("pipelines")]
    assert rolled, "no seed produced a rolled-up document"
    assert piped, "no seed produced a pipelines[] document"
    assert any(any("weight" in e for e in d["edges"]) for d in rolled), \
        "rollup never merged a parallel edge into a weight"
    assert any(any(n["attrs"].get("rollup") == "file" for n in d["nodes"])
               for d in rolled), "phase 2 never synthesized a file summary node"


def test_every_generated_document_validates(documents):
    for seed, doc, _notes in documents:
        assert _validate(doc) == [], "seed %d" % seed


# ------------------------------------------------------ 11.46 C, the rollup
def test_a_truncated_document_carries_a_truncated_diagnostic(documents):
    """11.46 C4 and D: `stats.truncated` is a boolean; the words are the
    diagnostic's job, and it must name the budget and the kept count."""
    seen = 0
    for _seed, doc, _notes in documents:
        if not doc["stats"]["truncated"]:
            continue
        seen += 1
        notes = [d for d in doc["diagnostics"] if d["kind"] == "truncated"]
        assert len(notes) == 1
        assert "budget" in notes[0]["message"]
        assert "%d node(s) kept" % len(doc["nodes"]) in notes[0]["message"]
    assert seen


def test_a_full_fidelity_document_never_claims_to_have_summarised(documents):
    """11.46 C5, the direction that matters: no `rolledUp` without `truncated`."""
    for seed, doc, _notes in documents:
        if doc["stats"]["truncated"]:
            continue
        assert not any("rolledUp" in n for n in doc["nodes"]), "seed %d" % seed
        assert not any("weight" in e for e in doc["edges"]), "seed %d" % seed


def test_no_self_loop_and_no_parallel_survives_the_fold(documents):
    """11.46 C2 and C3, asserted unconditionally on every generated document."""
    for seed, doc, _notes in documents:
        keys = []
        for edge in doc["edges"]:
            assert edge["source"] != edge["target"], "seed %d: self-loop" % seed
            keys.append((edge["source"], edge["kind"], edge["target"]))
        assert len(keys) == len(set(keys)), "seed %d: parallels" % seed


def test_a_weight_is_two_or_more_and_a_rolled_up_count_is_one_or_more(documents):
    """11.46 B1/B2 and C1."""
    for _seed, doc, _notes in documents:
        for node in doc["nodes"]:
            if "rolledUp" in node:
                assert isinstance(node["rolledUp"], int) and node["rolledUp"] >= 1
        for edge in doc["edges"]:
            if "weight" in edge:
                assert isinstance(edge["weight"], int) and edge["weight"] >= 2


def test_a_fold_never_drops_an_issue(documents):
    """11.46 B4: anchors are mapped through the fold, never discarded. Only
    phase 3 (drop) may lose one, and the generator never runs phase 3."""
    for seed, doc, _notes in documents:
        ids = {n["id"] for n in doc["nodes"]}
        for issue in doc["issues"]:
            assert issue["nodeIds"], "seed %d: issue %s lost every anchor" % (
                seed, issue["id"])
            assert set(issue["nodeIds"]) <= ids
            assert len(set(issue["nodeIds"])) == len(issue["nodeIds"])


def test_a_file_summary_node_is_the_one_11_44_a3_describes(documents):
    """The synthesized node is a real node in every respect, and its id follows
    the section 0 recipe with the `file-rollup` kind slot."""
    import hashlib

    seen = 0
    for _seed, doc, _notes in documents:
        for node in doc["nodes"]:
            if node["attrs"].get("rollup") != "file":
                continue
            seen += 1
            path = node["qualname"]
            want = "n:" + hashlib.sha1(
                ("%s|%s|file-rollup" % (path, path)).encode("utf-8")).hexdigest()[:12]
            assert node["id"] == want
            assert node["level"] == "stage" and node["parent"] is None
            assert node["ghost"] is False and node["collapsedByDefault"] is True
            assert node["label"] == path.rsplit("/", 1)[-1]
            assert node["sublabel"].endswith("nodes rolled up")
            assert node["rolledUp"] >= 2
    if _support_is_complete():
        assert seen


# --------------------------------------------------- 11.47 D, the pipelines
def test_a_pipeline_block_is_byte_identical_to_what_the_analyzer_would_emit(documents):
    """The generator has no second copy of 11.47 A on purpose: a document whose
    block a subtly different local relation computed is a document the analyzer
    could never emit, and a fuzz run asserting parity over one of those proves
    nothing. `pipelines_block` is the only implementation."""
    from mlview.core.pipelines import pipelines_block

    checked = 0
    for seed, doc, _notes in documents:
        if "pipelines" not in doc:
            continue
        checked += 1
        assert doc["pipelines"] == pipelines_block(doc), "seed %d" % seed
    if _support_is_complete():
        assert checked, "no pipelines[] block was checked"


def test_every_row_is_about_a_real_entrypoint_and_its_arithmetic_holds(documents):
    """11.47 D: rows are in `workspace.entrypoints` order, and
    `exclusiveCount + sharedCount == nodeCount`."""
    for seed, doc, _notes in documents:
        rows = doc.get("pipelines") or []
        entrypoints = list(doc["workspace"]["entrypoints"])
        assert [r["entrypoint"] for r in rows] == [
            e for e in entrypoints if e in {r["entrypoint"] for r in rows}], (
            "seed %d: rows are not in entrypoints order" % seed)
        for row in rows:
            assert row["entrypoint"] in entrypoints
            assert row["label"] == row["entrypoint"]
            assert row["exclusiveCount"] + row["sharedCount"] == row["nodeCount"]
            assert 0 < row["nodeCount"] <= len(doc["nodes"])


def test_the_block_is_emitted_only_for_two_or_more_pipelines(documents):
    """11.47 D: the block exists to drive a chooser, and a single-pipeline
    workspace has nothing to choose — it emits the bytes it always did."""
    for seed, doc, _notes in documents:
        if "pipelines" in doc:
            assert len(doc["pipelines"]) >= 2, "seed %d" % seed
    single = make_graph(9101)
    assert len(single["workspace"]["entrypoints"]) == 1
    entries, note = projections.pipeline_entries(single)
    assert entries == [] and "fewer than two" in note


def test_pipeline_issue_counts_count_findings_not_anchors(documents):
    """11.47 D: a non-suppressed issue with at least one anchor in the reach
    counts ONCE, and an issue spanning two pipelines counts in both."""
    from mlview.core.pipelines import build_index

    for _seed, doc, _notes in documents:
        if not doc.get("pipelines"):
            continue
        index = build_index(doc)
        for row in doc["pipelines"]:
            members = set(index.reach.get(row["entrypoint"]) or ())
            counts = {"low": 0, "medium": 0, "high": 0}
            for issue in doc["issues"]:
                if issue["suppressed"]:
                    continue
                if any(node_id in members for node_id in issue["nodeIds"]):
                    counts[issue["severity"]] += 1
            assert row["issueCounts"] == counts


def test_a_reduced_document_is_re_derived_as_thoroughly_as_a_generated_one(documents):
    """The minimizer's contract: delete nodes, and the LATER blocks must still
    describe the document that is left — a stale `pipelines[]` or a stale kept
    count would promote a counterexample nobody can replay."""
    checked = 0
    for seed, doc, _notes in documents:
        if len(doc["nodes"]) < 4:
            continue
        checked += 1
        doomed = {doc["nodes"][1]["id"], doc["nodes"][-1]["id"]}
        reduced = scope_fuzz._drop_nodes(doc, doomed)
        assert _validate(reduced) == [], "seed %d" % seed
        for entry in reduced.get("pipelines") or []:
            assert entry["exclusiveCount"] + entry["sharedCount"] == entry["nodeCount"]
        if reduced["stats"]["truncated"]:
            note = [d for d in reduced["diagnostics"] if d["kind"] == "truncated"][0]
            assert "%d node(s) kept" % len(reduced["nodes"]) in note["message"]
    assert checked


# ------------------------------------------------------------------ selectors
def test_pipeline_selectors_are_emitted_whether_or_not_the_grammar_landed():
    """CONTRACTS 11.16: `project()`, the fixtures, the MCP docstring and
    `SCOPE_KINDS` move together. Two ports that disagree about whether
    `pipeline:` parses at all is the drift this fuzzer is for, so the selectors
    are generated even on a checkout whose grammar has no `pipeline` kind."""
    graph = make_graph(9101)
    specs = [spec for spec, _depth
             in projections.selectors_for(graph, random.Random(1), 3)]
    assert specs and all(s.startswith("pipeline:") for s in specs)
    every = [spec for spec, _d in projections.selectors_for(graph, random.Random(1), 99)]
    assert "pipeline:" in every, "the empty term is a grammar case too"
    assert "pipeline:nope.py" in every
    entry = graph["workspace"]["entrypoints"][0]
    assert "pipeline:" + entry.upper() in every, "11.47 B case folding"
    assert ("pipeline:main.py", 3) in projections.selectors_for(
        graph, random.Random(1), 99), "a bad depth is a grammar case too"


# ------------------------------------------------------------------- honesty
def test_the_note_says_what_it_could_not_generate():
    """The framing this sprint carries: a change states what it could not do.
    A run against a schema without the optional fields must say so rather than
    pass quietly."""
    with open(DEFAULT_SCHEMA, encoding="utf-8") as fh:
        stripped = copy.deepcopy(json.load(fh))
    stripped["$defs"]["Node"]["properties"].pop("rolledUp", None)
    stripped["$defs"]["Edge"]["properties"].pop("weight", None)
    stripped["properties"].pop("pipelines", None)
    previous = projections._SUPPORT
    projections._SUPPORT = projections.Support(stripped)
    try:
        note = projections.capability_note()
        assert "Node.rolledUp" in note and "Edge.weight" in note
        assert "pipelines[]" in note and "OUTSIDE this run" in note
        graph, notes = projections.decorate(make_graph(9102), random.Random(3))
        assert "pipelines" not in graph
        assert not any("rolledUp" in n for n in graph["nodes"])
        assert notes, "a skipped shape must be reported, not silently dropped"
    finally:
        projections._SUPPORT = previous


def test_a_required_member_the_generator_cannot_compute_is_a_skip_not_a_guess():
    """The generator fills the *declared* members. One it has never heard of is
    a refusal naming the member — never an invented value that would make the
    fuzz run assert against fiction."""
    with open(DEFAULT_SCHEMA, encoding="utf-8") as fh:
        schema = copy.deepcopy(json.load(fh))
    item = schema["$defs"]["Pipeline"]
    item["required"] = list(item["required"]) + ["provenanceLedger"]
    item["properties"]["provenanceLedger"] = {"type": "object"}
    previous = projections._SUPPORT
    projections._SUPPORT = projections.Support(schema)
    try:
        graph = make_graph(9104)
        graph["workspace"]["entrypoints"] = sorted(
            {n["loc"]["file"] for n in graph["nodes"]})[:2]
        _entries, note = projections.pipeline_entries(graph)
        assert "provenanceLedger" in note, note
    finally:
        projections._SUPPORT = previous


# -------------------------------------------------------- the compared digest
def test_the_extras_block_carries_exactly_the_requested_fields(documents):
    """`extras_of` in the driver and `extrasOf` in the harness are one rule
    written twice; this pins the Python half's shape."""
    doc = next((d for _s, d, _n in documents if d.get("pipelines")),
               documents[0][1])
    both = scope_fuzz.extras_of(doc, ("rolledUp", "weight", "pipelines"))
    assert set(both) == {"rolledUp", "weight", "pipelines"}
    assert both["pipelines"] == doc.get("pipelines")
    only = scope_fuzz.extras_of(doc, ("weight",))
    assert set(only) == {"weight"}
    assert scope_fuzz.extras_of(doc, ()) == {}


def test_a_field_the_shared_digest_already_carries_is_not_compared_twice():
    """If `gen_scope_fixtures.digest_of` ever grows one of these fields, the
    driver must stand down for that field rather than compare it in two
    layouts. The probe is what decides."""
    extras = scope_fuzz.digest_extras()
    assert set(extras) <= set(projections.DIGEST_EXTRAS)
    import gen_scope_fixtures

    real = gen_scope_fixtures.digest_of({"nodes": [], "edges": [], "issues": [],
                                         "stages": [], "stats": {}, "view": None})
    for name in extras:
        assert name not in real, (
            "%r is in the shared digest; the driver should not add it" % name)
