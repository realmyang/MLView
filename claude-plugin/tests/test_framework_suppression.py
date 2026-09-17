"""A VALID framework filter that hides a finding has to say so (INFRA-R2-18).

Round 1 fixed the typo half of `mlview_analyze(framework=...)`: a spelling no rule
declares ("pytorch", "tensorflow") is refused instead of silently disabling every
framework-specific rule, and `mlview_workspace.normalize_framework` states the
invariant behind it — *a filter that names no extractor must never quietly return
a shorter finding list, because the caller cannot tell that answer from a clean
project.*

An ACCEPTED name did exactly that. Measured on
`analyzer/tests/accuracy/corpus/infra_tf_custom_loop_bad`, and reproduced here on
the self-contained fixture below because that corpus program is newer than this
suite:

    framework="auto"  -> [MLV121 high, MLV601 low]   diagnostics []
    framework="torch" -> [MLV601 low]                diagnostics []
                         verdict: "1 finding(s): 0 high / 0 medium / 1 low"

The high-severity finding is gone, nothing in the payload says a rule was
disabled, and the same payload still advertises `frameworks: ["keras", "tf"]` —
which is what makes narrowing to `torch` look like the obvious next move in the
first place. A model reading that answers "no high-severity problems" about a
project whose training and validation halves are reshuffled every epoch.

The fix emits the `framework_suppressed` diagnostic that
`contracts/graph.schema.json` already reserves ("For framework_suppressed: which
rules were not applied"), from `mlview_workspace.framework_suppression`, on every
path out of `load_graph` and `load_attributed`; `mlview_notes.COVERAGE_KINDS`
then carries it into the payload as a `coverage` row with the codes and into the
`note` as the COVERAGE sentence.

The analyzer already writes that same kind for a DIFFERENT statement — the R3.8
absence gate, "Training loop handled by Keras - 1 rule(s) de-rated to
speculative" — and the fixture below carries one, which is why half these tests
are about keeping the two apart. Those rules ran; rendering them as "MLV601 could
not run" beside "the finding count is a floor" would invent a coverage caveat on
every Keras, Lightning and HF workspace, so `is_framework_filter_note` is checked
in both directions here.

What is pinned here: the count is derived from the registry and not hard-coded
(the mirror test), only rules that WOULD have run under `auto` are counted, a
filter that costs a workspace nothing stays silent, `auto` gains no caveat, the
absence gate never becomes a coverage row, the note reaches a document written by
an older build of this server (the disk cache is keyed on the ANALYZER, which
cannot see a change to this file) and one that already carries the gate, and the
whole block still fits the 4 KB budget with all three coverage kinds present.
"""

from __future__ import annotations

import json
import os
import re

import pytest

import mlview_budget as budget
import mlview_mcp
import mlview_notes as notes
import mlview_payloads as payloads
import mlview_workspace as workspace
from plugin_support import PLUGIN_ROOT, REPO_ROOT, synthetic_graph

LIMIT = 4096

#: A tf.data `shuffle` feeding a `take`/`skip` holdout: MLV121 (high, declared for
#: `tf` and `keras`) plus MLV601 (low, no declared framework). Written into the
#: test's own tmp directory so the suite depends on no corpus program.
FIXTURE = '''"""A tf.data pipeline whose holdout is carved out of a reshuffled dataset."""

import tensorflow as tf


def make_datasets(rows, labels):
    ds = tf.data.Dataset.from_tensor_slices((rows, labels))
    shuffled = ds.shuffle(1024)
    val_ds = shuffled.take(100)
    train_ds = shuffled.skip(100)
    return train_ds.batch(32), val_ds.batch(32)


def build_model():
    return tf.keras.Sequential([tf.keras.layers.Dense(10, activation="softmax")])


def main(rows, labels):
    train_ds, val_ds = make_datasets(rows, labels)
    model = build_model()
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy")
    model.fit(train_ds, validation_data=val_ds, epochs=5)
    return model
'''

#: The rules a `torch` filter disables on a workspace whose detected frameworks are
#: keras and tf: the two tf/keras rules plus the tf.data holdout rule. Spelled out
#: so a rule gaining or losing a `frameworks=` declaration is a visible change here
#: rather than a quietly different number.
TORCH_ON_KERAS = ["MLV121", "MLV705", "MLV709"]


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A one-file Keras project, analyzed with a private, empty data directory."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "train.py").write_text(FIXTURE, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", str(root))
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(data))
    workspace._CACHE.clear()
    yield root
    workspace._CACHE.clear()


def _codes(graph):
    return [issue["code"] for issue in graph["issues"]]


def _filter_notes(graph):
    """The `--framework` notes, never the analyzer's absence gate."""
    return [d for d in graph.get("diagnostics") or []
            if notes.is_framework_filter_note(d)]


def _gate_notes(graph):
    """The analyzer's R3.8 absence-gate notes, which share the kind."""
    return [d for d in graph.get("diagnostics") or []
            if d.get("kind") == "framework_suppressed"
            and not notes.is_framework_filter_note(d)]


# ------------------------------------------------------- the core's own filter
@pytest.mark.parametrize("framework", list(workspace.FRAMEWORKS))
def test_the_mirror_of_the_core_filter_agrees_with_the_registry(framework):
    """`_rule_applies` is a copy of `registry._applies`; this is the drift alarm.

    The copy exists so a rename in the core cannot turn a tool call into an
    `AttributeError`. The cost of a copy is that it can go stale, and a stale copy
    would misreport WHICH rules a filter disabled — so every registered rule is
    cross-checked against the real helper, for every accepted `--framework` value,
    against workspaces that detect nothing, one framework, and several.
    """
    from mlview.rules import registry

    registry.discover_rules()
    detected_sets = (
        [],
        ["torch"],
        ["keras", "tf"],
        ["torch", "sklearn", "numpy", "torchvision"],
        ["hf", "lightning", "torch"],
    )
    for spec in registry.all_rules():
        for detected in detected_sets:
            assert workspace._rule_applies(
                spec.frameworks, detected, framework
            ) == registry._applies(spec, detected, framework), (
                spec.code, detected, framework
            )


# ------------------------------------------------------------------- the repro
def test_a_valid_filter_that_hides_a_high_finding_carries_the_diagnostic(project):
    auto = workspace.load_graph(str(project), framework="auto")["graph"]
    torch = workspace.load_graph(str(project), framework="torch")["graph"]

    assert "MLV121" in _codes(auto), "the fixture must carry the high finding"
    assert [i["severity"] for i in auto["issues"] if i["code"] == "MLV121"] == ["high"]
    assert "MLV121" not in _codes(torch), "the filter really does disable it"
    assert torch["workspace"]["frameworks"] == ["keras", "tf"], (
        "the payload still advertises the frameworks that make `torch` look sensible"
    )

    assert _filter_notes(auto) == [], "an unfiltered run invents no caveat"
    assert _gate_notes(auto), (
        "this fixture must carry the analyzer's absence gate, or the tests below "
        "that keep the two statements apart prove nothing"
    )
    note = _filter_notes(torch)
    assert len(note) == 1, torch["diagnostics"]
    note = note[0]
    assert note["codes"] == TORCH_ON_KERAS, "the hidden high finding is named"
    assert note["count"] == len(TORCH_ON_KERAS)
    assert "--framework torch" in note["message"]
    assert "3 framework-specific rule(s) did not run" in note["message"]
    assert "not a clean bill of health" in note["message"]
    # The codes stay OUT of the sentence: every reader shows them beside it, and
    # the report chip is `message + " (" + codes + ")"`.
    for code in TORCH_ON_KERAS:
        assert code not in note["message"], note["message"]


def test_only_rules_that_would_have_run_under_auto_are_counted(project):
    """A sklearn rule on a Keras project was never going to fire; counting it
    would inflate the number into noise and name rules that lost nothing."""
    torch = workspace.load_graph(str(project), framework="torch")["graph"]
    codes = _filter_notes(torch)[0]["codes"]
    for sklearn_only in ("MLV102", "MLV103", "MLV306"):
        assert sklearn_only not in codes, codes
    for torch_only in ("MLV201", "MLV202", "MLV401"):
        assert torch_only not in codes, "the filter KEPT the torch rules"


def test_a_filter_that_costs_this_workspace_nothing_stays_silent():
    """`None` is a real answer: nothing was disabled, so there is no caveat."""
    torch_only = {"workspace": {"frameworks": ["torch"]}}
    assert workspace.framework_suppression(torch_only, "torch") is None
    assert workspace.framework_suppression(torch_only, "auto") is None
    assert workspace.framework_suppression(torch_only, None) is None
    assert workspace.framework_suppression(torch_only, "  AUTO ") is None


def test_an_unknown_filter_is_still_refused_here_too():
    """The round-1 guard is upstream of this one, and stays that way."""
    with pytest.raises(ValueError):
        workspace.framework_suppression({"workspace": {"frameworks": []}}, "pytorch")


# --------------------------------------------------------------- the MCP payload
def test_the_payload_names_the_rules_the_filter_disabled(project):
    filtered = mlview_mcp.mlview_analyze(path=str(project), framework="torch")
    assert filtered["stats"]["issues"]["high"] == 0, "the shorter answer, as measured"

    # The tally is a per-KIND sum, and this workspace has two statements under
    # `framework_suppressed`: the analyzer's absence gate (1 rule de-rated) and
    # this host's filter note (3 rules not run). 1 + 3 is what a tally of
    # occurrences means, and it is why the tally is documented as "not an
    # explanation" - the coverage row below is the statement, and it names the
    # three. `framework_filter` is C8's: the ANALYZER naming the same three, which
    # is why exactly one of the two reaches the coverage block (§11.4 C3).
    assert filtered["diagnostics"] == [
        {"kind": "framework_suppressed", "count": 4},
        {"kind": "framework_filter", "count": 3},
    ]
    assert len(filtered["coverage"]) == 1, (
        "one cost, one row: the analyzer's `framework_filter` and this host's "
        "`framework_suppressed` name the same three rules, and a reader who saw "
        "both would be invited to add 3 and 3"
    )
    row = filtered["coverage"][0]
    assert row["kind"] == "framework_filter", "the producer that ran the rules wins"
    assert row["codes"] == TORCH_ON_KERAS
    assert row["count"] == 3
    for code in TORCH_ON_KERAS:
        assert code in filtered["note"], filtered["note"]
    assert "not a clean bill of health" in filtered["note"]
    assert budget.payload_size(filtered) <= LIMIT


def test_the_unfiltered_payload_gains_no_caveat(project):
    """`auto` is the default and the common case: it must cost nothing and say
    nothing new. The absence-gate tally it always carried is still there, and is
    still NOT a coverage row."""
    payload = mlview_mcp.mlview_analyze(path=str(project))
    assert payload["diagnostics"] == [{"kind": "framework_suppressed", "count": 1}], (
        "the analyzer's absence gate, tallied exactly as it was before this fix"
    )
    assert "coverage" not in payload
    assert "note" not in payload
    assert payload["stats"]["issues"]["high"] == 1


def test_the_absence_gate_is_never_rendered_as_a_rule_that_could_not_run(project):
    """The gate's rules RAN and were de-rated. `commands/mlview.md` tells the
    model to quote a coverage row's codes as rules that stayed silent, so putting
    MLV601 there would be a finding MLView did not make."""
    auto = workspace.load_graph(str(project), framework="auto")["graph"]
    gate = _gate_notes(auto)[0]
    assert gate["codes"] == ["MLV601"] and "de-rated" in gate["message"]
    assert notes.coverage_notes(auto) == [], auto["diagnostics"]
    assert notes.coverage_note(notes.coverage_notes(auto)) is None


def test_the_tool_docstring_tells_the_model_a_valid_filter_is_reported():
    doc = mlview_mcp.mlview_analyze.__doc__ or ""
    assert "framework_suppressed" in doc, (
        "the docstring must say a valid filter is reported, not only that an "
        "invalid one is refused"
    )


# ------------------------------------------------------------- every load path
def test_the_note_reaches_a_document_written_by_an_older_build(project):
    """The disk cache is keyed on the ANALYZER, which cannot see a change here.

    `analyzer_identity()` hashes the `mlview` package; a `graph.json` written by
    yesterday's build of THIS server has a valid sidecar and no framework note, so
    deriving the note only after a fresh analysis would leave that document silent
    for as long as the sources are untouched.
    """
    loaded = workspace.load_graph(str(project), framework="torch")
    graph_path = loaded["graphPath"]
    with open(graph_path, "r", encoding="utf-8") as handle:
        stored = json.load(handle)
    assert _filter_notes(stored), "the document on disk says what the payload says"

    # Only the filter note is removed: what is left is exactly an older build's
    # document, absence gate and all - and that gate is what an idempotency check
    # written against the KIND would mistake for "already noted".
    stored["diagnostics"] = [
        d for d in stored["diagnostics"] if not notes.is_framework_filter_note(d)
    ]
    assert _gate_notes(stored), "the gate has to survive, or this proves nothing"
    with open(graph_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(stored, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    workspace._CACHE.clear()

    served = workspace.load_graph(str(project), framework="torch")
    assert served["cached"] is True, "the sidecar must still hit, or this proves nothing"
    assert _filter_notes(served["graph"])[0]["codes"] == TORCH_ON_KERAS


def test_the_note_is_added_exactly_once(project):
    graph = workspace.load_graph(str(project), framework="torch")["graph"]
    for _ in range(3):
        workspace.note_framework_suppression(graph, "torch")
    assert len(_filter_notes(graph)) == 1, graph["diagnostics"]
    # and the memo path, which hands back that very dict
    again = workspace.load_graph(str(project), framework="torch")["graph"]
    assert again is graph
    assert len(_filter_notes(again)) == 1


def test_the_attributed_path_carries_the_note_too(project, monkeypatch):
    """`mlview_adopt` builds its own `AnalyzeOptions`, so it needs its own pass."""
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", REPO_ROOT)
    loaded = workspace.load_attributed(
        str(project), changed_since="HEAD", framework="torch"
    )
    assert _filter_notes(loaded["graph"])[0]["codes"] == TORCH_ON_KERAS


def test_a_registry_that_cannot_be_read_still_says_the_run_was_filtered(monkeypatch):
    """Silence is the one answer ruled out: the filter narrowed the run either way."""
    from mlview.rules import registry

    def boom():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(registry, "discover_rules", boom)
    note = workspace.framework_suppression({"workspace": {"frameworks": ["keras"]}},
                                           "torch")
    assert note is not None and note["kind"] == "framework_suppressed"
    assert "torch" in note["message"]
    assert "not a clean bill of health" in note["message"]
    assert notes.is_framework_filter_note(note), (
        "even the degraded note has to be recognizable as a filter note, or it "
        "is dropped from the coverage block that carries it"
    )
    assert "codes" not in note, "no codes is honest; an empty list reads as none"


# ------------------------------------------------------------------ the budget
@pytest.mark.parametrize("framework", [f for f in workspace.FRAMEWORKS if f != "auto"])
def test_every_accepted_filter_fits_the_coverage_block_uncut(framework):
    """`mlview_notes` clips a coverage message at 400 bytes. A sentence that ends
    in `...` mid-clause is exactly the sort of half-statement this note exists to
    prevent, so the widest workspace must still fit whole."""
    everything = {
        "workspace": {
            "frameworks": ["torch", "sklearn", "numpy", "torchvision", "keras",
                           "tf", "hf", "lightning", "pandas"]
        }
    }
    note = workspace.framework_suppression(everything, framework)
    assert note is not None
    assert len(note["message"]) <= notes.MAX_MESSAGE, len(note["message"])
    rendered = notes.coverage_notes({"diagnostics": [note]})[0]
    assert rendered["message"] == note["message"], "carried verbatim, never clipped"
    assert rendered["count"] == note["count"], "the count is rules, not rows"
    assert len(rendered["codes"]) <= notes.MAX_CODES


def _widest_graph(with_framework_filter):
    """A document carrying every coverage kind this host reads, at full width."""
    graph = synthetic_graph(nodes=8, edges=4, issues=60)
    graph["diagnostics"] = [
        {"kind": "single_file_analysis", "message": "x" * 500,
         "codes": ["MLV%03d" % n for n in range(301, 320)], "count": 4},
        {"kind": "untagged_dataflow", "message": "y" * 500, "codes": ["MLV101"],
         "count": 9},
        workspace.framework_suppression(
            {"workspace": {"frameworks": ["torch", "keras", "tf"]}}, "lightning"
        ),
    ]
    if with_framework_filter:
        graph["diagnostics"].append(
            {"kind": "framework_filter", "message": "z" * 500,
             "codes": ["MLV121", "MLV705"], "count": 2}
        )
    return graph


@pytest.mark.parametrize("with_framework_filter", [False, True])
def test_the_widest_coverage_block_fits_one_payload(with_framework_filter):
    """The block is protected from the budget walk, so it has to stay bounded.

    Three rows either way, never four: `framework_filter` and the filter half of
    `framework_suppressed` are two statements of ONE cost (CONTRACTS §11.4 C3),
    so whichever is present renders and the other does not.
    """
    payload = payloads.issues_payload(_widest_graph(with_framework_filter))
    filter_kind = "framework_filter" if with_framework_filter else "framework_suppressed"
    assert [row["kind"] for row in payload["coverage"]] == [
        "single_file_analysis", "untagged_dataflow", filter_kind,
    ]
    assert budget.payload_size(payload) <= LIMIT
    for row in payload["coverage"]:
        assert len(row["codes"]) <= notes.MAX_CODES
        assert len(row["message"]) <= notes.MAX_MESSAGE
    assert filter_kind in payload["note"]


def test_every_kind_this_host_reads_is_one_the_core_or_this_host_emits():
    """CONTRACTS §2.6 C9 as restated by §17 E40: a SUBSET rule plus a naming one.

    No coverage kind the core emits may be dropped by a host, and each EXTRA kind
    a host lists is named in the contract. `framework_suppressed` is the one extra
    and §11.4 B1 is where it is named.
    """
    from mlview.core import coverage as core_coverage

    assert set(core_coverage.COVERAGE_KINDS) <= set(notes.COVERAGE_KINDS), (
        "a kind the analyzer emits as coverage and this host drops is a caveat "
        "the model never sees"
    )
    assert set(notes.COVERAGE_KINDS) - set(core_coverage.COVERAGE_KINDS) == {
        "framework_suppressed"
    }


def test_a_kind_with_no_wording_of_its_own_borrows_no_other_kinds_explanation():
    """`_default_message` used to fall through to the dataflow sentence for every
    kind but one, so the next kind added described itself as a leakage gap."""
    assert "leakage" not in notes._default_message("framework_suppressed")
    assert "leakage" in notes._default_message("untagged_dataflow")
    # and a framework_suppressed entry with no message is not a filter note at
    # all, so it never reaches the coverage block to need a default
    assert notes.coverage_notes(
        {"diagnostics": [{"kind": "framework_suppressed", "count": 2}]}
    ) == []


# ------------------------------------------------------------------ the schema
def test_the_document_written_to_disk_stays_schema_valid(project):
    """The kind is one `contracts/graph.schema.json` already reserves, and the
    document is what `graphPath` hands the model to read."""
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(REPO_ROOT, "contracts", "graph.schema.json")
    with open(schema_path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    loaded = workspace.load_graph(str(project), framework="torch")
    with open(loaded["graphPath"], "r", encoding="utf-8") as handle:
        document = json.load(handle)
    assert _filter_notes(document), "the diagnostic under test has to be in there"
    jsonschema.validate(document, schema)


# ----------------------------------------------- the prompts that read the row
# The payload half of C8 is only half the fix: `commands/*.md` is what tells the
# model what a coverage row MEANS and what to offer when it sees one. Those files
# enumerated `framework_suppressed` while `coverage_notes` had already started
# rendering the analyzer's `framework_filter` in its place, so the only
# instruction that closes the loop - "offer to re-run with auto" - was keyed to a
# row a current build never emits. These tests pin both directions.
COMMAND_FILES = ("mlview-issues.md",)

#: A backticked lowercase identifier whose tail is one a coverage kind can have.
#: Wider than `COVERAGE_KINDS` on purpose: a prompt naming `framework_filtered`
#: has to fail here, and a check written as `token in COVERAGE_KINDS` could not.
_KIND_SHAPED = ("_analysis", "_dataflow", "_filter", "_suppressed")


def _command_text(name):
    with open(os.path.join(PLUGIN_ROOT, "commands", name), encoding="utf-8") as fh:
        return fh.read()


def _backticked(text):
    return set(re.findall(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`", text))


def _coverage_entry(kind):
    """A diagnostic of `kind` that `coverage_notes` is willing to render."""
    if kind == "framework_suppressed":
        # Only the FILTER half of the kind is a coverage caveat, and it is
        # recognized by its message - so this has to be the real note.
        return workspace.framework_suppression(
            {"workspace": {"frameworks": ["keras", "tf"]}}, "torch"
        )
    return {"kind": kind, "message": "measured", "codes": ["MLV301"], "count": 1}


def test_every_coverage_kind_this_host_can_render_is_explained_by_both_prompts():
    """Payload -> prompt: a row the model can receive must have prose about it.

    Rendered here rather than read off `COVERAGE_KINDS`, so a kind that stops
    reaching the block stops being required in the prompts at the same moment.
    """
    renderable = set()
    for kind in notes.COVERAGE_KINDS:
        renderable.update(
            row["kind"]
            for row in notes.coverage_notes({"diagnostics": [_coverage_entry(kind)]})
        )
    assert renderable == set(notes.COVERAGE_KINDS), (
        "every kind in COVERAGE_KINDS renders from a document carrying only it; "
        "one that cannot is dead weight in the tuple"
    )
    for name in COMMAND_FILES:
        missing = renderable - _backticked(_command_text(name))
        assert not missing, (
            "commands/%s never names %s, a coverage row the model can be handed"
            % (name, ", ".join(sorted(missing)))
        )


def test_no_prompt_names_a_coverage_kind_this_host_cannot_produce():
    """Prompt -> payload: the other direction, which is how H3 got in."""
    for name in COMMAND_FILES:
        named = {t for t in _backticked(_command_text(name))
                 if t.endswith(_KIND_SHAPED)}
        assert named <= set(notes.COVERAGE_KINDS), (name, sorted(named))


def test_the_re_run_with_auto_offer_is_keyed_to_the_row_the_filter_produces(project):
    """The one instruction that closes C8's loop has to sit on the rendered kind.

    Measured on the fixture: a `torch` filter on this Keras workspace renders
    `framework_filter` and nothing else, so prose hung on `framework_suppressed`
    alone is an instruction the model never reaches.
    """
    payload = mlview_mcp.mlview_analyze(path=str(project), framework="torch")
    rendered = [row["kind"] for row in payload["coverage"]]
    assert rendered == ["framework_filter"], payload["coverage"]

    with open(os.path.join(PLUGIN_ROOT, "skills", "mlview-visualize", "SKILL.md"), encoding="utf-8") as handle:
        text = handle.read()
    offers = [p for p in text.split("\n\n") if 'framework: "auto"' in p]
    assert len(offers) == 1, "one offer, or this test is reading the wrong prose"
    for kind in rendered:
        assert kind in offers[0], offers[0]


def test_the_tool_docstring_names_the_rendered_row_too(project):
    """`mlview_analyze.__doc__` is prose the model reads before it ever calls the
    tool, and it promised a `framework_suppressed` coverage row for the same
    reason the commands did."""
    doc = mlview_mcp.mlview_analyze.__doc__ or ""
    payload = mlview_mcp.mlview_analyze(path=str(project), framework="torch")
    for row in payload["coverage"]:
        assert row["kind"] in doc, row["kind"]
