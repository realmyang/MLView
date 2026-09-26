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


def _note(line: str) -> bool:
    return line.lstrip().startswith(">")


def pristine_difference(raw: bytes, template: str) -> str | None:
    """None when ``raw`` is the template apart from what the grammar ignores (section 1.3): line
    endings, a byte order mark, trailing spaces, a missing final newline, blank lines, and note lines
    (first non-space character ">"), which the owner may add, edit or remove before deciding
    anything (the candidate ledger, bound by the Candidate line, stays the source of the proposals);
    otherwise the first difference."""
    text = raw.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = [line.rstrip() for line in re.split(r"\r\n|\r|\n", text)]
    expected = [line.rstrip() for line in template.split("\n") if not _note(line)]
    index = 0
    for number, line in enumerate(lines, 1):
        if _note(line):
            continue
        while index < len(expected) and not expected[index] and line != expected[index]:
            index += 1  # a blank template line the owner removed
        if index < len(expected) and line == expected[index]:
            index += 1
            continue
        if not line:
            continue
        wanted = repr(expected[index]) if index < len(expected) else "the end of the file"
        return f"line {number} is {line!r} where the template has {wanted}"
    missing = [line for line in expected[index:] if line]
    if missing:
        return f"the file ends before the template line {missing[0]!r}"
    return None


def pristine_message(path: Path, name: str, difference: str) -> str:
    return (f"{path.name} still has every value pending but differs from `python tools/workflow_eval.py template "
            f"--show {name}`: {difference}. Only blank lines and note lines starting with \">\" may be added, edited "
            f"or removed before the first decision; restore the other lines from template --show.")


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
            difference = pristine_difference(raw, template)
            assert difference is None, pristine_message(path, name, difference)


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
            difference = pristine_difference(committed.read_bytes(), path.read_text(encoding="utf-8"))
            assert difference is None, pristine_message(committed, path.stem, difference)


def test_owner_notes_and_line_endings_keep_a_pristine_file_valid() -> None:
    current = world()
    template = wd.task_template(current, heldout_ids()[0])
    lines = template.split("\n")
    noted = "\n".join(lines[:12] + ["> My note: check this before deciding (synthetic)."] + lines[12:])
    assert pristine_difference(noted.encode("utf-8"), template) is None
    assert pristine_difference(template.replace("\n", "\r\n").encode("utf-8"), template) is None
    assert pristine_difference(("\ufeff" + template).encode("utf-8"), template) is None
    drifted = template.replace("Decision: pending", "Decision:  pending", 1)
    difference = pristine_difference(drifted.encode("utf-8"), template)
    assert difference is not None and "where the template has 'Decision: pending'" in difference
    assert "Only blank lines and note lines starting with" in pristine_message(DECISIONS / "x.md", "x", difference)
    # What the grammar ignores never fails CI while check shows no error (OWNERUX2-4).
    note_then_blank = "\n".join(lines[:12] + ["> My note (synthetic).", ""] + lines[12:])
    indented = "\n".join(lines[:12] + ["  > My indented note (synthetic)."] + lines[12:])
    trailing = template.replace("\nReviewer:\n", "\nReviewer: \n", 1)
    for variant in (note_then_blank, indented, trailing, template.rstrip("\n"), template.rstrip("\n") + "\n> end (synthetic)",
                    template.replace("\n\n## ", "\n## ", 1)):
        assert pristine_difference(variant.encode("utf-8"), template) is None, variant[:80]
    deleted = template.replace("Decision: pending\n", "", 1)
    assert pristine_difference(deleted.encode("utf-8"), template) is not None
    # Editing or deleting a tool-written ">" note is ignored like adding one (OWNERUX3-6); the next
    # difference is still reported at its own line.
    notes = [index for index, line in enumerate(lines) if line.startswith(">")]
    edited = "\n".join(line + " (check the resume branch too)" if index == notes[-1] else line
                       for index, line in enumerate(lines))
    trimmed = "\n".join(line for index, line in enumerate(lines) if index != notes[0])
    for variant in (edited, trimmed):
        assert variant != template and pristine_difference(variant.encode("utf-8"), template) is None
    both = edited.replace("Decision: pending", "Decision:  pending", 1)
    difference = pristine_difference(both.encode("utf-8"), template)
    assert difference is not None and difference.startswith(
        f"line {both.split(chr(10)).index('Decision:  pending') + 1} is 'Decision:  pending'"), difference
    truncated = template[:template.index("## Task")]
    assert "the file ends before the template line '## Task'" == pristine_difference(truncated.encode("utf-8"), template)


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
        patterns += [rf"{short}-u\d{{2}}", rf"{short}-n\d{{2}}", rf"{short}-(?:s-)?(?:h|hu|d)\d{{2}}",
                     rf"{short}-(?:s-)?(?:h|hu|d)\d{{2}}-a\d+"]
        patterns += [rf"{re.escape(fact)}-h\d+" for fact in fact_ids[task]]
        assert wd.short_name(task) not in candidate_ids
        assert set(wd.added_patterns(task).values()) == {rf"{short}-h\d{{2}}", rf"{short}-hu\d{{2}}", rf"{short}-d\d{{2}}"}
        assert set(wd.added_patterns(task, "second").values()) == {rf"{short}-s-h\d{{2}}", rf"{short}-s-hu\d{{2}}",
                                                                  rf"{short}-s-d\d{{2}}"}
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
