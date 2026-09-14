"""VIEW-08 (CONTRACTS 11.38): `mlview diff` over two analyses.

The acceptance criterion is the shipped sample pair — `samples/vision_pipeline`
against `samples/vision_pipeline_clean` — and it is pinned here with exact
counts, because a diff whose numbers drift silently is worse than no diff.

The rest of this file is about the two things that make the overlay trustworthy
rather than merely correct:

* **a move is not a change** — the stable ids from §0 exist precisely so that
  inserting twenty blank lines above a node does not repaint the file, and a
  diff that lost that property would be reporting churn instead of change;
* **`removed` is a claim about two documents, not about the code** — every
  reason one side might be missing something (a projection, a cap, a set-aside
  file, a different analyzer) is emitted as a note, and the notes are the one
  block the renderer never elides.
"""

from __future__ import annotations

import json
import os

import pytest

from core_support import REPO_ROOT, write_files
from mlview import cli
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.core import diff as diff_mod
from mlview.emit import diff_out

DIRTY = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
CLEAN = os.path.join(REPO_ROOT, "samples", "vision_pipeline_clean")

TRAIN = ("import torch\n"
         "import torch.nn as nn\n"
         "import torch.optim as optim\n"
         "from torch.utils.data import DataLoader\n\n\n"
         "def train(ds):\n"
         "    model = nn.Linear(4, 2)\n"
         "    crit = nn.CrossEntropyLoss()\n"
         "    opt = optim.Adam(model.parameters())\n"
         "    loader = DataLoader(ds, batch_size=8)\n"
         "    for x, y in loader:\n"
         "        loss = crit(model(x), y)\n"
         "        loss.backward()\n"
         "        opt.step()\n")


@pytest.fixture(scope="module")
def pair():
    base = analyze_to_dict(AnalyzeOptions(paths=(DIRTY,), cache=False))
    head = analyze_to_dict(AnalyzeOptions(paths=(CLEAN,), cache=False))
    return base, head


@pytest.fixture(scope="module")
def overlay(pair):
    return diff_mod.diff_documents(*pair)


@pytest.fixture
def run(capsysbinary):
    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out, captured.err.decode("utf-8", "replace")

    return _run


# ------------------------------------------------------------- acceptance
def test_the_sample_pair_reports_the_added_nodes_and_the_fixed_findings(overlay, pair):
    """ROADMAP VIEW-08's acceptance, at the counts this tree actually produces
    after the §11.19 re-baseline and its §11.35 erratum: the dirty sample is 54
    nodes / 51 edges / 15 findings and the clean twin is 64 / 55 / 0."""
    base, head = pair
    assert (len(base["nodes"]), len(base["issues"])) == (54, 15)
    assert (len(head["nodes"]), len(head["issues"])) == (64, 0)
    summary = overlay["summary"]
    assert summary["nodes"] == {"added": 26, "removed": 16, "changed": 11,
                                "unchanged": 27}
    assert summary["edges"] == {"added": 26, "removed": 22, "changed": 1,
                                "unchanged": 28}
    assert summary["issues"] == {"new": 0, "fixed": 15, "persisting": 0}
    assert summary["headline"] == "+26 nodes · −16 nodes · 0 new findings · 15 fixed"


def test_every_finding_of_the_dirty_sample_is_reported_fixed(overlay, pair):
    base, _head = pair
    fixed = {row["id"] for row in overlay["issues"] if row["status"] == "fixed"}
    assert fixed == {issue["id"] for issue in base["issues"]}
    codes = sorted(row["code"] for row in overlay["issues"]
                   if row["status"] == "fixed")
    assert len(codes) == 15 and codes[0].startswith("MLV")


def test_the_counts_add_up_to_both_documents(overlay, pair):
    """A diff that loses an id is a diff that lies about a deletion."""
    base, head = pair
    nodes = overlay["summary"]["nodes"]
    assert nodes["added"] + nodes["changed"] + nodes["unchanged"] == len(head["nodes"])
    assert nodes["removed"] + nodes["changed"] + nodes["unchanged"] == len(base["nodes"])
    assert len(overlay["nodes"]) == nodes["added"] + nodes["removed"] \
        + nodes["changed"] + nodes["unchanged"]


def test_the_overlay_is_a_separate_document_and_never_a_graph(overlay):
    assert overlay["kind"] == "mlview-diff"
    assert overlay["diffVersion"] == "1.0"
    assert overlay["schemaVersion"] == "1.0"
    assert overlay["generator"]["name"] == "mlview"
    assert set(overlay) >= {"base", "head", "summary", "nodes", "edges",
                            "issues", "notes"}
    with pytest.raises(diff_mod.DiffError):
        diff_mod.diff_documents(overlay, overlay)


def test_the_diff_is_deterministic(pair):
    first = diff_mod.diff_documents(*pair)
    second = diff_mod.diff_documents(*pair)
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


# ----------------------------------------------------------- what a change is
def test_a_document_diffed_against_itself_is_entirely_unchanged(pair):
    base, _head = pair
    same = diff_mod.diff_documents(base, base)
    assert same["summary"]["nodes"]["added"] == 0
    assert same["summary"]["nodes"]["removed"] == 0
    assert same["summary"]["nodes"]["changed"] == 0
    assert same["summary"]["issues"] == {"new": 0, "fixed": 0,
                                         "persisting": len(base["issues"])}
    assert all(row["status"] == "unchanged" for row in same["nodes"])


def test_inserting_blank_lines_moves_a_node_without_changing_it(tmp_path):
    """§0's stable ids, used for the thing they were built for. Twenty blank
    lines above the training loop must not repaint the file as changed."""
    base_root = write_files(str(tmp_path / "base"), {"train.py": TRAIN})
    head_root = write_files(str(tmp_path / "head"),
                            {"train.py": "\n" * 20 + TRAIN})
    base = analyze_to_dict(AnalyzeOptions(paths=(base_root,), cache=False))
    head = analyze_to_dict(AnalyzeOptions(paths=(head_root,), cache=False))
    overlay = diff_mod.diff_documents(base, head)
    assert overlay["summary"]["nodes"]["added"] == 0
    assert overlay["summary"]["nodes"]["removed"] == 0
    assert overlay["summary"]["nodes"]["changed"] == 0
    moved = [row for row in overlay["nodes"] if row.get("moved")]
    assert moved, "the move is recorded, it is just not a change"
    assert all(row["status"] == "unchanged" for row in moved)


def test_a_new_finding_is_reported_as_new(tmp_path):
    base_root = write_files(str(tmp_path / "b"), {
        "train.py": TRAIN.replace("        loss = crit",
                                  "        opt.zero_grad()\n        loss = crit")})
    head_root = write_files(str(tmp_path / "h"), {"train.py": TRAIN})
    overlay = diff_mod.diff_documents(
        analyze_to_dict(AnalyzeOptions(paths=(base_root,), cache=False)),
        analyze_to_dict(AnalyzeOptions(paths=(head_root,), cache=False)))
    new = [row for row in overlay["issues"] if row["status"] == "new"]
    assert [row["code"] for row in new] == ["MLV201"]
    assert new[0]["severity"] == "high" and new[0]["nodeIds"]
    assert overlay["summary"]["issues"]["new"] == 1


def test_a_node_that_gained_a_finding_is_changed(tmp_path):
    base_root = write_files(str(tmp_path / "b"), {
        "train.py": TRAIN.replace("        loss = crit",
                                  "        opt.zero_grad()\n        loss = crit")})
    head_root = write_files(str(tmp_path / "h"), {"train.py": TRAIN})
    overlay = diff_mod.diff_documents(
        analyze_to_dict(AnalyzeOptions(paths=(base_root,), cache=False)),
        analyze_to_dict(AnalyzeOptions(paths=(head_root,), cache=False)))
    changed = [row for row in overlay["nodes"] if row["status"] == "changed"]
    assert any("issueCodes" in (row.get("changed") or ()) for row in changed)


# ------------------------------------------------------- what it cannot see
def test_different_roots_are_stated(overlay):
    kinds = {note["kind"] for note in overlay["notes"]}
    assert "different-roots" in kinds
    message = next(n["message"] for n in overlay["notes"]
                   if n["kind"] == "different-roots")
    assert "workspace-relative path" in message


def test_a_set_aside_file_is_stated_so_removed_is_not_read_as_deleted(tmp_path):
    """The join between VIEW-08 and 11.39. Under the shipped `--relevance ml`
    default a file with no framework token is never analyzed, so its nodes are
    absent from the head document for a reason that has nothing to do with the
    change. If the overlay did not say so, `-N nodes` would be a lie."""
    mixed = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures", "config",
                         "mixed_repo")
    wide = analyze_to_dict(AnalyzeOptions(paths=(mixed,), relevance="all",
                                          cache=False))
    narrow = analyze_to_dict(AnalyzeOptions(paths=(mixed,), cache=False))
    overlay = diff_mod.diff_documents(wide, narrow)
    assert overlay["summary"]["nodes"]["removed"] > 0
    notes = [n for n in overlay["notes"] if n["kind"] == "not-analyzed"]
    assert notes and notes[0]["side"] == "head"
    assert "Relevance prefilter" in notes[0]["message"]


def test_a_projection_is_stated(pair):
    from mlview.core.project import parse_scope, project

    base, _head = pair
    projected = project(base, parse_scope("stage:train", None))
    overlay = diff_mod.diff_documents(base, projected)
    kinds = [n["kind"] for n in overlay["notes"]]
    assert "projection" in kinds
    note = next(n for n in overlay["notes"] if n["kind"] == "projection")
    assert note["side"] == "head" and "stage:train" in note["message"]


def test_a_capped_document_is_stated(tmp_path):
    root = write_files(str(tmp_path), {"train.py": TRAIN})
    full = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    capped = analyze_to_dict(AnalyzeOptions(paths=(root,), max_nodes=3, cache=False))
    overlay = diff_mod.diff_documents(full, capped)
    kinds = {n["kind"] for n in overlay["notes"]}
    assert "truncated" in kinds


def test_two_analyzer_versions_are_stated(pair):
    base, head = pair
    older = json.loads(json.dumps(base))
    older["generator"] = dict(older["generator"], version="0.0.1")
    overlay = diff_mod.diff_documents(older, head)
    assert any(n["kind"] == "different-analyzers" for n in overlay["notes"])


def test_a_clean_pair_says_a_removal_is_a_removal(tmp_path):
    base_root = write_files(str(tmp_path / "b"), {"train.py": TRAIN})
    head_root = write_files(str(tmp_path / "h"), {"train.py": TRAIN})
    overlay = diff_mod.diff_documents(
        analyze_to_dict(AnalyzeOptions(paths=(base_root,), cache=False)),
        analyze_to_dict(AnalyzeOptions(paths=(head_root,), cache=False)))
    assert [n for n in overlay["notes"] if n["kind"] != "different-roots"] == []


# --------------------------------------------------------------- rendering
def test_the_summary_names_both_sides_and_the_headline(overlay):
    text = diff_out.render_summary(overlay)
    assert text.startswith("mlview diff\n")
    assert "vision_pipeline " in text and "vision_pipeline_clean" in text
    assert overlay["summary"]["headline"] in text
    assert "fixed findings (15)" in text
    assert "new findings (0)" in text
    assert "added nodes (26)" in text


def test_the_summary_elides_rows_but_never_the_notes(overlay):
    text = diff_out.render_summary(overlay)
    assert "… and 5 more finding(s)" in text
    assert "Notes (%d)" % len(overlay["notes"]) in text
    for note in overlay["notes"]:
        assert note["message"] in text


# --------------------------------------------------------------------- CLI
def test_the_cli_prints_the_summary_and_exits_zero(run, tmp_path, pair):
    base, head = pair
    base_file = str(tmp_path / "base.json")
    head_file = str(tmp_path / "head.json")
    for path, doc in ((base_file, base), (head_file, head)):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
    code, out, err = run("diff", base_file, head_file)
    assert code == 0 and err == ""
    assert out.decode("utf-8").startswith("mlview diff\n")
    assert "15 fixed" in out.decode("utf-8")


def test_the_cli_writes_the_overlay_where_it_is_asked_to(run, tmp_path, pair):
    """`--json FILE` follows `analyze --json FILE` exactly: the file is written,
    its path goes to **stderr**, and stdout still carries the requested
    `--format` payload. `--json -` makes the overlay itself the payload."""
    base, head = pair
    base_file, head_file = str(tmp_path / "b.json"), str(tmp_path / "h.json")
    for path, doc in ((base_file, base), (head_file, head)):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
    target = str(tmp_path / "out" / "overlay.json")
    code, out, err = run("diff", base_file, head_file, "--json", target)
    assert code == 0
    assert out.decode("utf-8").startswith("mlview diff\n")
    assert "wrote" in err and os.path.isfile(target)
    with open(target, encoding="utf-8") as handle:
        written = json.load(handle)
    assert written["kind"] == "mlview-diff"
    assert written["summary"]["issues"]["fixed"] == 15

    code, out, _err = run("diff", base_file, head_file, "--format", "json")
    assert code == 0 and json.loads(out.decode("utf-8"))["kind"] == "mlview-diff"

    code, out, _err = run("diff", base_file, head_file, "--json", "-")
    assert code == 0 and json.loads(out.decode("utf-8"))["kind"] == "mlview-diff"


def test_a_missing_or_unusable_input_is_exit_1_with_clean_stdout(run, tmp_path):
    code, out, err = run("diff", str(tmp_path / "nope.json"), str(tmp_path / "x.json"))
    assert code == 1 and out == b"" and "cannot read" in err

    junk = str(tmp_path / "junk.json")
    with open(junk, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    code, out, err = run("diff", junk, junk)
    assert code == 1 and out == b"" and "not valid JSON" in err

    empty = str(tmp_path / "empty.json")
    with open(empty, "w", encoding="utf-8") as handle:
        json.dump({"schemaVersion": "1.0"}, handle)
    code, out, err = run("diff", empty, empty)
    assert code == 1 and out == b"" and "not an MLView graph" in err
