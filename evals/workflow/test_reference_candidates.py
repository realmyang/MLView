"""Structure and source integrity of the eight immutable reference-candidate ledgers.

The ledgers stay draft proposals: every review is pending and no reviewer is named. With the pinned
corpus present (MLVIEW_PUBLIC_CORPUS_DIR or .public-corpus) every anchor quote is compared with the
pinned bytes under the helper's line semantics and every anchor file's blob with `git ls-tree`;
without it those checks are skipped with the reason printed. This replaces the ignored
.mlview/reference-candidate-validation.json as the proof of source integrity. It establishes byte
integrity only, not claim correctness or completeness, and it is not human review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import eval_records as er  # noqa: E402

CANDIDATES = ROOT / "evals/workflow/reference-candidates"
LEDGER_KEYS = {"taskId", "repositoryCommit", "status", "review", "scenario", "facts", "unknowns", "nonDefects"}
SCENARIO_KEYS = {"description", "entrypoints", "arguments"}
FACT_KEYS = {"id", "claim", "basis", "essential", "anchors", "review"}
ANCHOR_KEYS = {"id", "file", "line", "endLine", "quote"}
BASES = {"observed", "inferred", "unresolved"}


def manifest() -> dict:
    return json.loads((ROOT / "evals/workflow/tasks.json").read_text(encoding="utf-8"))


def heldout() -> list[dict]:
    return [task for task in manifest()["tasks"] if task["split"] == "heldout"]


def repositories() -> dict[str, dict]:
    value = json.loads((ROOT / "evals/workflow/repositories.json").read_text(encoding="utf-8"))
    return {repo["name"]: repo for repo in value["repos"]}


def ledgers() -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(CANDIDATES.glob("*.json"))}


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def test_one_ledger_per_held_out_task() -> None:
    assert sorted(ledgers()) == sorted(task["id"] for task in heldout())


@pytest.mark.parametrize("task", heldout(), ids=lambda task: task["id"])
def test_ledger_structure_and_pending_status(task: dict) -> None:
    ledger = ledgers()[task["id"]]
    assert set(ledger) == LEDGER_KEYS
    assert ledger["taskId"] == task["id"]
    assert ledger["repositoryCommit"] == task["commit"] == repositories()[task["repository"]]["sha"]
    assert ledger["status"] == "draft-needs-human-review"
    assert ledger["review"] == {"reviewer": None, "decision": "pending"}
    assert set(ledger["scenario"]) == SCENARIO_KEYS
    assert isinstance(ledger["scenario"]["description"], str) and ledger["scenario"]["description"].strip()
    for key in ("entrypoints", "arguments"):
        assert isinstance(ledger["scenario"][key], list) and all(isinstance(v, str) and v for v in ledger["scenario"][key])
    assert ledger["scenario"]["entrypoints"]
    for key in ("unknowns", "nonDefects"):
        assert isinstance(ledger[key], list) and all(isinstance(v, str) and v.strip() for v in ledger[key])
    for fact in ledger["facts"]:
        assert set(fact) == FACT_KEYS, fact.get("id")
        assert fact["review"] == "pending" and fact["basis"] in BASES and isinstance(fact["essential"], bool)
        assert isinstance(fact["claim"], str) and fact["claim"].strip()
        assert fact["anchors"], fact["id"]
        for anchor in fact["anchors"]:
            notebook = anchor["file"].endswith(".ipynb")
            assert set(anchor) == ANCHOR_KEYS | ({"cell"} if notebook else set()), anchor["id"]
            assert er._path_problem(anchor["file"]) is None
            assert is_int(anchor["line"]) and is_int(anchor["endLine"]) and 1 <= anchor["line"] <= anchor["endLine"]
            if notebook:
                assert is_int(anchor["cell"]) and anchor["cell"] >= 0
            assert isinstance(anchor["quote"], str) and anchor["quote"]


def test_ids_are_unique_and_the_totals_hold() -> None:
    values = ledgers().values()
    facts = [fact for ledger in values for fact in ledger["facts"]]
    anchors = [anchor for fact in facts for anchor in fact["anchors"]]
    ids = [fact["id"] for fact in facts] + [anchor["id"] for anchor in anchors]
    assert len(ids) == len(set(ids))
    assert (len(facts), len(anchors), sum(fact["essential"] for fact in facts)) == (93, 106, 74)
    assert (sum(len(ledger["unknowns"]) for ledger in values), sum(len(ledger["nonDefects"]) for ledger in values)) == (25, 20)


def corpus() -> Path | None:
    import os
    configured = os.environ.get("MLVIEW_PUBLIC_CORPUS_DIR")
    path = Path(configured).expanduser() if configured else ROOT / ".public-corpus"
    return path if path.is_dir() else None


@pytest.mark.parametrize("task", heldout(), ids=lambda task: task["id"])
def test_quotes_match_the_pinned_bytes(task: dict) -> None:
    base = corpus()
    if base is None or not (base / task["repository"]).is_dir():
        pytest.skip(f"corpus absent for {task['repository']}: set MLVIEW_PUBLIC_CORPUS_DIR or run "
                    "python tools/fetch_workflow_repos.py")
    repo = base / task["repository"]
    tree = er.pinned_tree(repo, task["commit"])
    helper = er.load_helper()
    checked = 0
    for fact in ledgers()[task["id"]]["facts"]:
        for anchor in fact["anchors"]:
            data = er.pinned_bytes(repo, task["commit"], anchor["file"], tree=tree)  # blob-exact against ls-tree
            lines = er.source_lines(data, anchor.get("cell"), helper)
            assert er.quote_matches(anchor["quote"], lines, anchor["line"], anchor["endLine"], helper), anchor["id"]
            checked += 1
    assert checked == sum(len(fact["anchors"]) for fact in ledgers()[task["id"]]["facts"])
