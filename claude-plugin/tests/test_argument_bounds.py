"""Every MCP argument is either an enum that is REJECTED or a bound that is SAID.

Hardening round 1, `claude-plugin`. `test_tool_arguments.py` pins the enum half
(`format`, `minSeverity`, `groupBy`, `scope`): out of range is an error the model
can retry, never a silent coercion. This file pins the two arguments that
escaped that rule and the two numeric bounds that had no rule at all.

**HOSTS-UX-FRAMEWORK (critical, fixed here).** `mlview_analyze(framework=...)`
passed its string straight to `AnalyzeOptions.framework`, and
`mlview.rules.registry._applies` keeps a rule that declares frameworks only when
`framework_filter in spec.frameworks` — so a name no rule declares disables every
framework-specific rule at once instead of failing. Measured on
`samples/vision_pipeline` before the guard (`python -c` against
`mlview_workspace.load_graph`):

    framework="auto"      -> 54 nodes, 15 findings, 5 high
    framework="torch"     -> 54 nodes, 13 findings, 4 high   (the real filter)
    framework="pytorch"   -> 52 nodes,  1 finding,  0 high
    framework="TORCH"     -> 52 nodes,  1 finding,  0 high
    framework="Lightning" -> 52 nodes,  1 finding,  0 high

with `frameworks: ["torch", "sklearn", "numpy", "torchvision"]` still in the same
payload and no `note` anywhere in it — the model is told torch was detected and
that nothing is high-severity, about a project with five high-severity findings.
`pytorch` for `torch` is the single most likely spelling a model produces.

**HOSTS-UX-MCPBOUNDS (minor, fixed here).** `depth` was already handled exactly
right — clamped AND reported (`depth=5 is above the maximum 2; 2 was used`).
`limit <= 0` returned `issues: []` beside a `countBySeverity` of fifteen with no
note, which is the shape a reader takes for "there are none"; `maxNodes <= 0` was
reported as nothing at all, though a non-positive budget means UNCAPPED
(CONTRACTS 11.46 A) and the caller had asked for a small graph; and an unknown
entry in `code[]` answered with the same empty list as a clean project.

The two are one rule with two halves: an enum has no nearest legal value, so it
is refused; a bound has one, so it is moved and the move is said out loud.
"""

from __future__ import annotations

import argparse
import io
import os

import pytest

import mlview_budget as budget
import mlview_mcp
import mlview_payloads as payloads
import mlview_workspace as workspace
from plugin_support import REPO_ROOT, SERVER_DIR, synthetic_graph

SAMPLE = os.path.join("samples", "vision_pipeline")

#: Every spelling a model plausibly produces for a real framework, plus nonsense.
#: All of them used to analyze successfully and answer 0 high on the demo.
REJECTED = ("pytorch", "tensorflow", "tf", "sk-learn", "huggingface", "torch2",
            "none", "all", "lightening", "tourch")


@pytest.fixture(scope="module", autouse=True)
def _project(tmp_path_factory):
    """Analyze the repository, writing graph documents to a scratch data dir."""
    data = tmp_path_factory.mktemp("mlview-bounds-data")
    saved = {k: os.environ.get(k) for k in
             ("MLVIEW_PROJECT_DIR", "MLVIEW_DATA_DIR", "MLVIEW_NO_OPEN")}
    os.environ["MLVIEW_PROJECT_DIR"] = REPO_ROOT
    os.environ["MLVIEW_DATA_DIR"] = str(data)
    os.environ["MLVIEW_NO_OPEN"] = "1"
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def graph():
    return synthetic_graph(nodes=40, edges=60, issues=20)


def _cli_framework_choices():
    """The `--framework` choices argparse really declares, read off the parser.

    Not a copied literal: the CLI is the authority on this vocabulary (CONTRACTS
    section 3), and a value added there must not stay unreachable through the
    MCP for a release. Reading the parser makes the drift a test failure.
    """
    from mlview.cli_parser import build_parser

    for action in build_parser()._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for sub in action.choices.values():
            for option in sub._actions:
                if "--framework" in (option.option_strings or []):
                    return tuple(option.choices)
    raise AssertionError("the CLI no longer declares --framework")


# ------------------------------------------------------------------- framework
def test_the_accepted_frameworks_are_exactly_the_cli_choices():
    assert tuple(workspace.FRAMEWORKS) == _cli_framework_choices()


@pytest.mark.parametrize("name", ["auto", "torch", "sklearn", "keras", "hf", "lightning"])
def test_every_accepted_framework_survives_normalization(name):
    assert workspace.normalize_framework(name) == name
    assert workspace.normalize_framework(name.upper()) == name
    assert workspace.normalize_framework("  %s  " % name.title()) == name


def test_a_missing_framework_is_auto():
    assert workspace.normalize_framework(None) == "auto"
    assert workspace.normalize_framework("") == "auto"
    assert workspace.normalize_framework("   ") == "auto"


@pytest.mark.parametrize("bad", REJECTED)
def test_an_unknown_framework_is_refused_with_the_accepted_values(bad):
    with pytest.raises(ValueError) as excinfo:
        workspace.normalize_framework(bad)
    message = str(excinfo.value)
    assert bad.strip() in message, "the error must name the value the caller passed"
    for accepted in workspace.FRAMEWORKS:
        assert accepted in message, "the error must list %r" % accepted


@pytest.mark.parametrize("bad", ["pytorch", "tensorflow"])
def test_load_graph_refuses_before_it_analyzes_anything(bad):
    """The guard is at the analysis chokepoint, not only in the tool signature."""
    with pytest.raises(ValueError):
        workspace.load_graph(SAMPLE, framework=bad)
    with pytest.raises(ValueError):
        workspace.load_attributed(SAMPLE, changed_since="HEAD", framework=bad)


def test_the_quieter_analysis_is_now_unreachable_through_the_tool():
    """The measured regression: 5 high with `auto`, 0 high with `pytorch`."""
    auto = mlview_mcp.mlview_analyze(path=SAMPLE, framework="auto")
    assert auto["stats"]["issues"]["high"] >= 5, (
        "the demo must carry high-severity findings for this test to mean anything"
    )
    with pytest.raises(mlview_mcp.ToolError) as excinfo:
        mlview_mcp.mlview_analyze(path=SAMPLE, framework="pytorch")
    # ToolError is what carries the text into the isError result the model reads.
    assert "pytorch" in str(excinfo.value)
    assert "torch" in str(excinfo.value) and "lightning" in str(excinfo.value)


def test_case_is_folded_into_the_same_analysis_not_a_second_one():
    """`TORCH` is `torch`: one cache entry, one document — never a quieter one."""
    lower = workspace.load_graph(SAMPLE, framework="torch")["graph"]
    upper = workspace.load_graph(SAMPLE, framework=" TORCH ")["graph"]
    assert upper is lower, "the cache key must be the normalized value"


def test_a_restricting_framework_still_restricts_and_says_nothing_false():
    """The legitimate filter is untouched: fewer rules run, and the count is real."""
    auto = workspace.load_graph(SAMPLE, framework="auto")["graph"]
    torch = workspace.load_graph(SAMPLE, framework="torch")["graph"]
    assert len(torch["issues"]) <= len(auto["issues"])
    assert len(torch["nodes"]) == len(auto["nodes"]), (
        "a rule filter must not change the recovered structure"
    )


def test_every_analysis_in_this_server_goes_through_one_vocabulary():
    """No sibling may build `AnalyzeOptions` with an unvalidated framework.

    A static check on purpose: the next module that analyzes something is the one
    that would reintroduce this, and it would do so silently.
    """
    builders = []
    for name in sorted(os.listdir(SERVER_DIR)):
        if not name.endswith(".py"):
            continue
        source = io.open(os.path.join(SERVER_DIR, name), encoding="utf-8").read()
        if "AnalyzeOptions(" in source:
            builders.append(name)
            assert "normalize_framework" in source, (
                "%s builds AnalyzeOptions without normalize_framework" % name
            )
    assert builders, "no module builds AnalyzeOptions any more — has the guard moved?"


def test_the_tool_docstring_tells_the_model_the_six_values():
    doc = mlview_mcp.mlview_analyze.__doc__ or ""
    for accepted in workspace.FRAMEWORKS:
        assert accepted in doc, "the docstring must name %r" % accepted
    assert "ERROR" in doc or "error" in doc, (
        "the docstring must say an unknown framework is an error, not a filter"
    )


# ----------------------------------------------------------------------- limit
@pytest.mark.parametrize(
    "given,expected",
    [(None, 20), (1, 1), (5, 5), (300, 300), (0, 1), (-3, 1), ("7", 7)],
)
def test_clamp_limit_holds_the_row_cap_at_or_above_one(given, expected):
    value, _note = payloads.clamp_limit(given)
    assert value == expected


@pytest.mark.parametrize("bad", [0, -3, -1])
def test_a_clamped_limit_always_says_it_moved(bad):
    value, note = payloads.clamp_limit(bad)
    assert value == payloads.MIN_ISSUE_LIMIT
    assert note and str(bad) in note and "1 was used" in note


def test_a_non_numeric_limit_falls_back_to_the_default_and_says_so():
    value, note = payloads.clamp_limit("twenty")
    assert value == payloads.DEFAULT_ISSUE_LIMIT
    assert note and "twenty" in note and "20" in note


@pytest.mark.parametrize("bad", [0, -3])
def test_a_listing_is_never_empty_while_the_counts_are_not(graph, bad):
    """The failure this bound exists for: `issues: []` read as "there are none"."""
    payload = payloads.issues_payload(graph, limit=bad)
    assert sum(payload["countBySeverity"].values()) > 0
    assert payload["issues"], "a listing tool must not answer [] because of a bound"
    assert "limit=" in (payload.get("note") or ""), "the move must be in the note"


def test_a_clamped_limit_changes_nothing_but_the_rows(graph):
    clamped = payloads.issues_payload(graph, limit=-3)
    normal = payloads.issues_payload(graph, limit=20)
    assert clamped["countBySeverity"] == normal["countBySeverity"]
    assert clamped["suppressedCount"] == normal["suppressedCount"]
    assert clamped["issues"] == normal["issues"][:1]


def test_a_grouped_answer_does_not_claim_a_cut_that_did_not_happen(graph):
    """`limit` caps the flat list only; groups are folded before it is applied."""
    grouped = payloads.issues_payload(graph, limit=-3, group_by="rule")
    assert grouped["groups"], "the fold must still happen"
    assert "issues" not in grouped
    assert "limit=" not in (grouped.get("note") or "")
    assert grouped["groups"] == payloads.issues_payload(
        graph, limit=20, group_by="rule"
    )["groups"], "a bound must not change what the groups count"


def test_a_valid_limit_adds_no_note(graph):
    assert "limit=" not in (payloads.issues_payload(graph, limit=5).get("note") or "")


def test_the_tool_passes_a_bad_limit_to_the_bound_not_to_int(graph):
    """`mlview_issues` must not raise on `limit=0`: it is a bound, not an enum."""
    payload = mlview_mcp.mlview_issues(path=SAMPLE, limit=0)
    assert payload["issues"], "limit=0 must not empty the listing"
    assert "limit=0" in (payload.get("note") or "")


# -------------------------------------------------------------------- maxNodes
@pytest.mark.parametrize("given,expected", [(None, 400), (400, 400), (1, 1), (5000, 5000)])
def test_a_positive_max_nodes_is_passed_through_untouched(given, expected):
    value, note = payloads.max_nodes_note(given)
    assert value == expected and note is None


@pytest.mark.parametrize("bad", [0, -5])
def test_a_non_positive_max_nodes_is_reported_and_not_clamped(bad):
    """CONTRACTS 11.46 A: `apply_node_budget` returns untouched at `<= 0`.

    Clamping to the default here would make `mlview_analyze {maxNodes: 0}`
    disagree with `--max-nodes 0`, which is the one thing worse than the silence
    this replaces.
    """
    value, note = payloads.max_nodes_note(bad)
    assert value == bad, "the analyzer's own semantics must survive"
    assert note and str(bad) in note and "not a cap" in note


def test_a_non_numeric_max_nodes_falls_back_to_the_default_and_says_so():
    value, note = payloads.max_nodes_note("lots")
    assert value == payloads.DEFAULT_MAX_NODES
    assert note and "lots" in note and "400" in note


def test_the_uncapped_note_reaches_the_analyze_payload():
    payload = mlview_mcp.mlview_analyze(path=SAMPLE, maxNodes=0)
    assert "maxNodes=0" in (payload.get("note") or "")


def test_a_bound_note_never_costs_the_digest_a_finding():
    """Measured: a 232-byte sentence here shed one of the eight `topIssues`.

    `note` is a PROTECTED key, so `fit` pays for it out of the lists. A note that
    displaces a finding is a worse misrepresentation than the silence it fixed,
    which is why the wording is short and this is a gate.

    This case measures the invariant on ONE checkout, whose absolute paths are
    whatever this machine's are; `test_a_bound_note_is_free_at_any_checkout_depth`
    is the one that measures it at every depth.
    """
    capped = mlview_mcp.mlview_analyze(path=SAMPLE, maxNodes=400)
    uncapped = mlview_mcp.mlview_analyze(path=SAMPLE, maxNodes=0)
    assert len(uncapped.get("topIssues", [])) == len(capped.get("topIssues", []))
    assert mlview_payload_size(uncapped) <= payloads.LIMIT_BYTES


def mlview_payload_size(payload):
    from mlview_budget import payload_size

    return payload_size(payload)


# ------------------------------------------------- the note reserve (FC-05)
#: The bound notes the two tables above produce, alone and joined — the caveats
#: B4 is about, taken from the builders rather than copied as literals.
def _bound_notes():
    joined = [payloads.max_nodes_note(0)[1], payloads.clamp_limit(0)[1]]
    return tuple(joined) + ("; ".join(joined),)


def _digest_like(path_padding: int = 0):
    """A payload shaped like `mlview_analyze`'s, with the absolute paths padded.

    `root` and `graphPath` are absolute, and their length is a property of the
    MACHINE, not of the project: a CI workspace, a nested monorepo or a Windows
    profile directory adds a hundred bytes the analysis never chose. Padding them
    measures the same answer at several checkout depths without moving the tree.
    """
    root = "/" + "d" * (24 + path_padding) + "/proj"
    return {
        "schemaVersion": "1.0",
        "root": root,
        "filesAnalyzed": 5, "filesFailed": 0, "notebooksSkipped": 0,
        "frameworks": ["torch", "sklearn", "numpy", "torchvision"],
        "stats": {"nodes": 59, "edges": 51,
                  "issues": {"low": 4, "medium": 6, "high": 5}},
        "lanes": [{"stage": stage, "label": stage.title(), "nodeCount": 8,
                   "maxSeverity": "high"}
                  for stage in ("config", "data", "preprocess", "model",
                                "objective", "train", "eval")],
        "topIssues": [{"code": "MLV%d" % (101 + i), "severity": "high",
                       "confidenceBucket": "certain",
                       "title": "A finding with a title as long as the real ones are",
                       "file": "train.py", "line": 29 + i} for i in range(10)],
        "graphPath": root + "/.mlview/graph.json",
        "truncated": False,
    }


def test_a_bound_note_is_free_at_any_checkout_depth():
    """FC-05: the rows a payload keeps must not depend on where it was checked out.

    `fit` used to measure the payload against a flat 4096, so the absolute paths
    inside it were spent out of the same budget as the findings: at one checkout
    depth a caveat still fitted and at the next it shed a row. Measured over this
    sweep before `NOTE_RESERVE` existed, 134 of the 690 (padding, note) pairs came
    back with one `topIssues` row fewer than the caveat-free payload at the same
    padding — silently, because the same tree at a shorter path answered with all
    of them. The reserve is what makes the walk caveat-independent by construction.
    """
    notes = _bound_notes()
    shed_somewhere = False
    for padding in range(0, 460, 2):
        payload = _digest_like(padding)
        bare = budget.fit(payload)
        shed_somewhere = shed_somewhere or len(bare["topIssues"]) < 10
        for note in notes:
            noted = budget.fit(dict(payload, note=note))
            assert len(noted["topIssues"]) == len(bare["topIssues"]), (
                "a %d-byte caveat cost a finding at padding %d"
                % (len(note), padding)
            )
            assert noted["note"] == note, "the caveat itself is never clipped"
            assert budget.payload_size(noted) <= budget.LIMIT_BYTES
    assert shed_somewhere, "the sweep must reach the cap, or it proves nothing"


def test_the_reserve_is_large_enough_for_the_bound_notes_it_exists_for():
    """A reserve smaller than the caveats it covers would be decoration.

    The two bound notes joined are the longest this file can produce; the reserve
    is measured against their cost in the encoding the budget is measured in
    (`caveat_cost`, keys and separators included), not against `len(text)`.
    """
    longest = max(_bound_notes(), key=len)
    cost = budget.caveat_cost({"note": longest, "topIssues": []})
    assert cost <= budget.NOTE_RESERVE, (
        "the longest bound note costs %d bytes against a %d-byte reserve"
        % (cost, budget.NOTE_RESERVE)
    )


# ------------------------------------------------------------------ code[] note
def test_an_unknown_rule_code_is_named_rather_than_answered_with_an_empty_list(graph):
    payload = payloads.issues_payload(graph, codes=["NOPE"], known_codes=["MLV102"])
    assert payload["issues"] == []
    note = payload.get("note") or ""
    assert "NOPE" in note and "no rule" in note


def test_a_real_rule_that_found_nothing_is_not_called_a_typo(graph):
    payload = payloads.issues_payload(
        graph, codes=["MLV803"], known_codes=["MLV102", "MLV803"]
    )
    note = payload.get("note") or ""
    assert "no rule" not in note, "a real code that found nothing is not a mistake"
    assert "no finding matched" in note, "an empty list still has to be explained"


def test_without_a_registry_no_code_is_called_a_typo(graph):
    """`rule_codes()` returns None when the registry cannot be read (never a set).

    An empty set would turn every code into "names no rule", which is exactly the
    confident-and-wrong sentence this note exists to avoid.
    """
    payload = payloads.issues_payload(graph, codes=["MLV803"], known_codes=None)
    assert "no rule" not in (payload.get("note") or "")


def test_the_registry_vocabulary_is_real_and_is_what_the_tool_passes():
    codes = workspace.rule_codes()
    assert codes is not None and len(codes) >= 20
    assert all(c == c.upper() for c in codes)
    payload = mlview_mcp.mlview_issues(path=SAMPLE, code=["NOPE"])
    assert "NOPE" in (payload.get("note") or "")


def test_a_lowercase_code_still_matches(graph):
    lower = payloads.issues_payload(graph, codes=["mlv102"])
    upper = payloads.issues_payload(graph, codes=["MLV102"])
    assert lower["issues"] == upper["issues"]
    assert upper["issues"], "MLV102 must really be in this fixture for the test to bite"
    assert "no rule" not in (upper.get("note") or "")
