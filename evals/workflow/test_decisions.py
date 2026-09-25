"""Guards for the committed owner decision files in evals/workflow/decisions/.

Owner edits in progress never fail these tests: to-dos are allowed, errors are not. A file that is
still pristine must equal a fresh template byte for byte, the generator may only write pending
values, and a committed frozen campaign must re-derive exactly (check-frozen). These tests read the
candidate and native review ledgers and never write outside a temporary directory. They are
tooling checks, not human review, semantic accuracy or live-host validation.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import eval_records as er  # noqa: E402
import workflow_decisions as wd  # noqa: E402

DECISIONS = ROOT / "evals/workflow/decisions"
TOOL_WRITTEN = {"candidate", "ledger"}


def world() -> wd.World:
    return wd.World(ROOT, None)


def heldout_ids() -> list[str]:
    return [task["id"] for task in world().heldout]


def owner_values(raw: bytes, name: str) -> tuple[er.Record, list[tuple[str, str]]]:
    record, problems = er.parse_record(raw, name)
    assert record is not None, problems
    values = [(f.key, f.value) for section in [record.header, *record.sections] for f in section.lines
              if f.key.casefold() not in TOOL_WRITTEN]
    return record, values


def is_pristine(raw: bytes, template: str, name: str) -> bool:
    """Reviewer empty, every value pending or empty, the same sections and the same prompt text."""
    record, values = owner_values(raw, name)
    fresh, _values = owner_values(template.encode("utf-8"), name)
    return (all(value.strip().casefold() in ("", "pending") for _key, value in values)
            and [(s.kind, s.ident, s.fence) for s in record.sections] == [(s.kind, s.ident, s.fence) for s in fresh.sections])


def test_the_folder_holds_every_owner_file() -> None:
    names = {path.name for path in DECISIONS.iterdir()}
    required = {f"{task}.md" for task in heldout_ids()} | {"run-policy.md", "development-adjudication.md", "README.md"}
    assert required <= names
    for extra in sorted(names - required):
        assert re.fullmatch(r"(.+)\.second\.md", extra) and extra[:-len(".second.md")] in heldout_ids(), extra


@pytest.mark.parametrize("path", wd.decision_files(world()), ids=lambda path: path.name)
def test_every_decision_file_checks_without_errors(path: Path) -> None:
    checks = wd.check_path(world(), path)
    problems = [str(problem) for check in checks for problem in check.problems if problem.level == er.ERROR]
    assert problems == []


def test_pristine_files_equal_a_fresh_template() -> None:
    current = world()
    targets = {name: (path, generate()) for name, (path, generate) in wd.template_targets(current).items()}
    for task in heldout_ids():
        second = DECISIONS / f"{task}.second.md"
        if second.is_file():
            targets[f"{task} --second"] = (second, wd.task_template(current, task, second=True))
    for name, (path, template) in targets.items():
        raw = path.read_bytes()
        if is_pristine(raw, template, path.name):
            assert raw == template.encode("utf-8"), f"{path.name} is pristine but differs from template --show {name}"


def test_the_generator_writes_only_pending_values(tmp_path: Path) -> None:
    fresh = wd.World(ROOT, None, decisions_dir=tmp_path)
    args = wd.build_parser().parse_args(["template", "--init-all"])
    assert wd.command_template(fresh, args, io.StringIO()) == 0
    generated = sorted(path.name for path in tmp_path.iterdir())
    assert generated == sorted([f"{task}.md" for task in heldout_ids()]
                               + ["run-policy.md", "development-adjudication.md", "README.md"])
    assert (tmp_path / "README.md").read_bytes() == (DECISIONS / "README.md").read_bytes()
    for path in sorted(tmp_path.glob("*.md")):
        if path.name == "README.md":
            continue
        record, values = owner_values(path.read_bytes(), path.name)
        assert {value for _key, value in values} <= {"", "pending"}, path.name
        for key in ("Reviewer", "Date", "Transcribed by"):
            assert record.header.value(key) == "", (path.name, key)
        committed = DECISIONS / path.name
        if is_pristine(committed.read_bytes(), path.read_text(encoding="utf-8"), path.name):
            assert committed.read_bytes() == path.read_bytes(), path.name


def test_committed_frozen_campaigns_re_derive_exactly() -> None:
    out = io.StringIO()
    assert wd.check_frozen(wd.World(ROOT), out) == 0, out.getvalue()


def test_no_generated_id_collides_with_a_candidate_id() -> None:
    current = world()
    candidate_ids: list[str] = []
    fact_ids: dict[str, list[str]] = {}
    for task in heldout_ids():
        ledger = current.ledger(task)[0]
        fact_ids[task] = [fact["id"] for fact in ledger["facts"]]
        candidate_ids += fact_ids[task] + [anchor["id"] for fact in ledger["facts"] for anchor in fact["anchors"]]
    assert len(candidate_ids) == len(set(candidate_ids)) == 199
    patterns = []
    for task in heldout_ids():
        short = re.escape(wd.short_name(task))
        patterns += [rf"{short}-u\d{{2}}", rf"{short}-n\d{{2}}", rf"{short}-(?:h|hu|d)\d{{2}}",
                     rf"{short}-(?:h|hu|d)\d{{2}}-a\d+"]
        patterns += [rf"{re.escape(fact)}-h\d+" for fact in fact_ids[task]]
        assert wd.short_name(task) not in candidate_ids
        assert set(wd.added_patterns(task).values()) == {rf"{short}-h\d{{2}}", rf"{short}-hu\d{{2}}", rf"{short}-d\d{{2}}"}
    collisions = [(ident, pattern) for ident in candidate_ids for pattern in patterns if re.fullmatch(pattern, ident)]
    assert collisions == []
    generated = [ident for task in heldout_ids() for ident in
                 wd.unknown_ids(task, current.ledger(task)[0]) + wd.nondefect_ids(task, current.ledger(task)[0])]
    assert len(generated) == len(set(generated)) == 25 + 20
    assert not set(generated) & set(candidate_ids)


def test_committed_files_have_no_machine_paths() -> None:
    for path in sorted(DECISIONS.iterdir()):
        assert not wd.MACHINE_PATH_RE.search(path.read_text(encoding="utf-8")), path.name


def test_readme_points_to_the_guide_and_the_check_command() -> None:
    text = (DECISIONS / "README.md").read_text(encoding="utf-8")
    assert "(../reference-candidates/REVIEW_GUIDE.md)" in text and (DECISIONS / "../reference-candidates/REVIEW_GUIDE.md").is_file()
    assert "python tools/workflow_eval.py check" in text and "adds no approval" in text


def test_the_check_command_reports_to_dos_and_no_errors() -> None:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "tools/workflow_eval.py"), "check"], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not [line for line in result.stdout.splitlines() if ": ERROR " in line]
    summaries = [line for line in result.stdout.splitlines() if re.match(r"\S+(?: \(second review\))?: \d+ error\(s\), \d+ to do; ", line)]
    assert len(summaries) == len(wd.decision_files(world()))


def test_tasks_json_is_canonical_for_a_byte_predictable_freeze() -> None:
    raw = (ROOT / "evals/workflow/tasks.json").read_bytes()
    assert raw == (json.dumps(json.loads(raw), indent=2) + "\n").encode("utf-8")
    assert er.check_task_manifest(json.loads(raw)) == []
