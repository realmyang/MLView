"""Discovery honesty: what `scope="units"` claims about itself (CONTRACTS 11.10).

The catalogue is the surface the skill and the `/mlview` command point a model
at ("call `mlview_graph {scope:'units'}` first and pick the row"), so its two
silences are the expensive ones:

1. **It is shed to fit 4 KB**, smallest rows first — exactly the leaf classes and
   short functions a user names. A clipped menu with only `truncated: true` on it
   reads as a complete one, and the model answers "there is no such unit" for a
   name `unit:<x>` resolves perfectly. Every clipped payload must therefore name
   both counts and point at the unbudgeted `--list-scopes`.
2. **It lists container units only** (`level` `stage`/`unit`, plus parents), by
   contract. A call site such as `train_test_split` is an `op`: `unit:` resolves
   it, the catalogue never lists it. The docs must say so, because the skill
   otherwise forbids the only way to reach it.

Plus the one deliberate CLI/MCP divergence on `depth`, pinned here rather than
left implicit in a note string.
"""

from __future__ import annotations

import json
import os
import re

import pytest

import mlview_payloads as payloads
import mlview_scope as scopes
from mlview_budget import payload_size
from plugin_support import PLUGIN_ROOT, REPO_ROOT, corpus_path, synthetic_graph

LIMIT = 4096
DOC_FILES = (
    os.path.join(PLUGIN_ROOT, "skills", "mlview-visualize", "SKILL.md"),
    os.path.join(PLUGIN_ROOT, "README.md"),
)


def _renderers():
    from mlview.api import render_mermaid, render_text

    return {"mermaid": render_mermaid, "text": render_text}


@pytest.fixture(scope="module")
def sample_graph():
    from mlview.api import AnalyzeOptions, analyze_to_dict

    return analyze_to_dict(
        AnalyzeOptions(paths=(os.path.join(REPO_ROOT, corpus_path()),))
    )


@pytest.fixture(scope="module")
def big():
    return synthetic_graph(nodes=500, edges=800, issues=300)


def _payload(graph, **kwargs):
    call = {
        "fmt": "mermaid", "scope": None, "depth": None, "renderers": _renderers(),
        "graph_path": "C:/proj/.mlview/graph.json",
    }
    call.update(kwargs)
    return payloads.graph_payload(graph, **call)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


# ------------------------------------------------- 1. a clipped menu says it is clipped
@pytest.mark.parametrize("fmt", ["mermaid", "text", "json"])
def test_a_clipped_units_catalogue_names_both_counts_and_where_the_rest_are(big, fmt):
    payload = _payload(big, fmt=fmt, scope="units")
    total = len(scopes.catalog_rows(big))
    assert total > 40, "this fixture exists to overflow the budget"
    assert payload["truncated"] is True
    assert payload_size(payload) <= LIMIT

    note = payload.get("note", "")
    match = re.search(r"showing (\d+) of (\d+) scopable units", note)
    assert match, "a clipped catalogue must say how many rows it is showing: %r" % note
    shown, reported_total = int(match.group(1)), int(match.group(2))
    assert reported_total == total
    assert 0 < shown < total
    assert "--list-scopes" in note, "the note must point at the unbudgeted catalogue"

    if fmt == "json":
        assert len(json.loads(payload["content"])) == shown, (
            "the note must count the rows the payload actually carries"
        )


def test_the_clipped_note_survives_the_budget_because_note_is_protected(big):
    """`fit` sheds the biggest sheddable value; `note` must never be it."""
    payload = _payload(big, fmt="json", scope="units")
    assert "INCOMPLETE" in payload.get("note", "")
    assert payload_size(payload) <= LIMIT


def test_a_complete_units_catalogue_makes_no_incompleteness_claim(sample_graph):
    payload = _payload(sample_graph, fmt="json", scope="units")
    rows = json.loads(payload["content"])
    assert len(rows) == len(scopes.catalog_rows(sample_graph))
    assert payload["truncated"] is False
    assert "INCOMPLETE" not in payload.get("note", "")
    assert "scopable units" not in payload.get("note", "")


# --------------------------------------- 2. op-level targets resolve but are not listed
def _op_targets(graph):
    """Bare names of `op` nodes that no catalogue row carries."""
    listed = {row.get("qualname") for row in scopes.catalog_rows(graph)}
    names = []
    for node in graph.get("nodes", []):
        if node.get("level") != "op":
            continue
        qualname = node.get("qualname") or ""
        if qualname in listed:
            continue
        last = qualname.rsplit(".", 1)[-1]
        if last:
            names.append(last)
    return names


def test_a_call_site_unit_target_resolves_although_the_catalogue_omits_it(sample_graph):
    """The gap the docs must disclose — verified, not assumed."""
    listed = {row["qualname"] for row in scopes.catalog_rows(sample_graph)}
    resolved = []
    for name in _op_targets(sample_graph)[:40]:
        payload = _payload(sample_graph, fmt="text", scope="unit:%s" % name)
        if "matched no nodes" not in payload.get("note", ""):
            resolved.append(name)
    assert resolved, (
        "if no op-level name resolves any more, the catalogue is complete and the "
        "disclosure below can be deleted"
    )
    assert not (set(resolved) & listed)


@pytest.mark.parametrize("path", DOC_FILES)
def test_the_docs_disclose_that_the_catalogue_lists_container_units_only(path):
    body = _read(path)
    lowered = body.lower()
    assert "container" in lowered, (
        "%s must say the catalogue lists CONTAINER units only" % os.path.basename(path)
    )
    assert "train_test_split" in body or "call site" in lowered


def test_the_skill_no_longer_forbids_the_only_way_to_reach_an_op_target():
    body = _read(DOC_FILES[0])
    assert "do not guess a qualname" not in body, (
        "an absolute prohibition contradicts the skill's own "
        "`unit:train_test_split` example, which the catalogue cannot list"
    )
    assert "--list-scopes" in body


# ---------------------------------------------- 3. the one CLI/MCP divergence on depth
def test_out_of_range_depth_is_clamped_and_disclosed_at_the_tool_boundary():
    """CONTRACTS 11.1 raises `bad_depth` on the CLI; the MCP boundary clamps.

    Deliberate and filed as a contract change request: a model that guesses
    `depth: 3` recovers better from a disclosed clamp than from a usage error.
    Pinned here so the divergence is a decision rather than an accident.
    """
    assert scopes.clamp_depth(3) == (scopes.MAX_DEPTH, "depth=3 is above the maximum 2; 2 was used")
    assert scopes.clamp_depth(-1) == (0, "depth=-1 is below 0; 0 was used")
    assert scopes.clamp_depth(2) == (2, None)
    assert scopes.clamp_depth(None) == (None, None)


def test_the_clamp_reaches_the_caller_in_the_payload_note(sample_graph):
    stage = next(
        row["id"] for row in sample_graph["stages"] if row.get("present")
    )
    payload = _payload(sample_graph, fmt="text", scope="stage:%s" % stage, depth=7)
    assert "2 was used" in payload.get("note", ""), (
        "a clamp the caller cannot see is a wrong answer with a confident label"
    )
